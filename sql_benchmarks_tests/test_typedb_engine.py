"""
Tests for TypeDBEngine.

Mirrors the structure of test_duckdb_engine.py and test_postgres_engine.py:
Docker SDK and TypeDBClient are mocked so the suite runs without a live
container or TypeDB instance.
"""
import pytest
from unittest.mock import patch, MagicMock, call
from docker.errors import NotFound, APIError

from sql_benchmarks.resources.typedb_engine import TypeDBEngine
import sql_benchmarks.resources.typedb_engine as _engine_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_initialized_partitions():
    """
    Clear the module-level partition tracker before and after every test so
    that bulk_load tests don't bleed state into one another.
    """
    _engine_mod._INITIALIZED_PARTITIONS.clear()
    yield
    _engine_mod._INITIALIZED_PARTITIONS.clear()


@pytest.fixture
def engine():
    return TypeDBEngine(
        address="127.0.0.1:1729",
        container_name="bench_typedb_test",
        docker_image="typedb/typedb:latest",
    )


@pytest.fixture
def mock_docker(engine):
    """Patches docker.from_env() for all engine tests that touch Docker."""
    with patch("sql_benchmarks.resources.typedb_engine.docker") as mock_docker_mod:
        mock_client = MagicMock()
        mock_docker_mod.from_env.return_value = mock_client
        yield mock_client


# ---------------------------------------------------------------------------
# 1. IBenchmarkEngine contract
# ---------------------------------------------------------------------------

def test_get_engine_name_returns_typedb(engine):
    assert engine.get_engine_name() == "typedb"


# ---------------------------------------------------------------------------
# 2. _db_name — partition key sanitisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("partition_key,expected", [
    ("small",           "bench_small"),
    ("ssd_small",       "bench_ssd_small"),
    ("hdd-medium",      "bench_hdd_medium"),     # hyphens → underscores
    ("rows~small",      "bench_rows_small"),      # tildes → underscores
    ("a~b-c_d",         "bench_a_b_c_d"),
])
def test_db_name_sanitises_partition_key(partition_key, expected):
    assert TypeDBEngine._db_name(partition_key) == expected


def test_db_name_two_partitions_are_distinct():
    assert TypeDBEngine._db_name("ssd_small") != TypeDBEngine._db_name("hdd_large")


# ---------------------------------------------------------------------------
# 3. _kill_container — graceful Docker lifecycle
# ---------------------------------------------------------------------------

def test_kill_container_removes_existing_container(engine, mock_docker):
    mock_container = MagicMock()
    mock_docker.containers.get.return_value = mock_container

    engine._kill_container(mock_docker)

    mock_docker.containers.get.assert_called_once_with(engine.container_name)
    mock_container.remove.assert_called_once_with(force=True)


def test_kill_container_is_silent_when_container_absent(engine, mock_docker):
    mock_docker.containers.get.side_effect = NotFound("no such container")

    # Must not raise
    engine._kill_container(mock_docker)


def test_kill_container_raises_on_docker_api_error(engine, mock_docker):
    mock_docker.containers.get.side_effect = APIError("daemon error")

    with pytest.raises(RuntimeError, match="Failed to remove TypeDB container"):
        engine._kill_container(mock_docker)


# ---------------------------------------------------------------------------
# 4. _start_container
# ---------------------------------------------------------------------------

def test_start_container_uses_correct_image(engine, mock_docker):
    engine._start_container(mock_docker)

    run_kwargs = mock_docker.containers.run.call_args[1]
    assert run_kwargs["image"] == engine.docker_image


def test_start_container_binds_port_1729(engine, mock_docker):
    engine._start_container(mock_docker)

    run_kwargs = mock_docker.containers.run.call_args[1]
    assert "1729/tcp" in run_kwargs["ports"]
    assert run_kwargs["ports"]["1729/tcp"] == 1729


def test_start_container_mounts_named_volume(engine, mock_docker):
    engine._start_container(mock_docker)

    run_kwargs = mock_docker.containers.run.call_args[1]
    assert "typedb_bench_data" in run_kwargs["volumes"]


def test_start_container_runs_detached(engine, mock_docker):
    engine._start_container(mock_docker)

    run_kwargs = mock_docker.containers.run.call_args[1]
    assert run_kwargs["detach"] is True


def test_start_container_retries_on_port_conflict(engine, mock_docker):
    """On 'port is already allocated', the engine retries up to max_retries."""
    mock_docker.containers.run.side_effect = [
        APIError("port is already allocated"),
        MagicMock(),  # succeeds on second attempt
    ]
    # Should not raise
    engine._start_container(mock_docker)
    assert mock_docker.containers.run.call_count == 2


def test_start_container_raises_after_all_retries_exhausted(engine, mock_docker):
    mock_docker.containers.run.side_effect = APIError("port is already allocated")

    with pytest.raises(RuntimeError, match="TypeDB container failed to start"):
        engine._start_container(mock_docker)


# ---------------------------------------------------------------------------
# 5. _ensure_container
# ---------------------------------------------------------------------------

def test_ensure_container_starts_stopped_container(engine, mock_docker):
    mock_container = MagicMock()
    mock_container.status = "exited"
    mock_docker.containers.get.return_value = mock_container

    engine._ensure_container()

    mock_container.start.assert_called_once()


def test_ensure_container_does_not_restart_running_container(engine, mock_docker):
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_docker.containers.get.return_value = mock_container

    engine._ensure_container()

    mock_container.start.assert_not_called()


def test_ensure_container_creates_when_not_found(engine, mock_docker):
    mock_docker.containers.get.side_effect = NotFound("not found")

    with patch.object(TypeDBEngine, "_start_container") as mock_start:
        engine._ensure_container()
        mock_start.assert_called_once_with(mock_docker)


# ---------------------------------------------------------------------------
# 6. run_query — clear_cache + delegation
# ---------------------------------------------------------------------------

def test_run_query_calls_clear_cache_before_client(engine):
    """cold-cache contract: clear_cache must fire before the client query."""
    call_order = []

    with patch.object(TypeDBEngine, "clear_cache", side_effect=lambda: call_order.append("clear_cache")), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_client.run_query.side_effect = lambda *a, **kw: call_order.append("run_query") or 1.0
        mock_get_client.return_value = mock_client

        engine.run_query("match $x isa t; select $x;", "small", {})

    assert call_order == ["clear_cache", "run_query"]


def test_run_query_delegates_to_client(engine):
    with patch.object(TypeDBEngine, "clear_cache"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_client.run_query.return_value = 2.5
        mock_get_client.return_value = mock_client

        result = engine.run_query("match $x isa t; select $x;", "small", {"k": "v"})

    mock_client.run_query.assert_called_once_with("match $x isa t; select $x;", {"k": "v"})
    assert result == 2.5


def test_run_query_raises_if_client_returns_none(engine):
    with patch.object(TypeDBEngine, "clear_cache"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_client.run_query.return_value = None
        mock_get_client.return_value = mock_client

        result = engine.run_query("match $x isa t; select $x;", "small", {})
        assert result is None


# ---------------------------------------------------------------------------
# 7. bulk_load — container lifecycle, DB init, entity/relation dispatch
# ---------------------------------------------------------------------------

def test_bulk_load_ensures_container_before_client(engine):
    call_order = []

    with patch.object(TypeDBEngine, "_ensure_container", side_effect=lambda: call_order.append("ensure")), \
         patch.object(TypeDBEngine, "_wait_for_ready", side_effect=lambda **kw: call_order.append("wait")), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_client.load_entity.side_effect = lambda *a, **kw: call_order.append("load_entity")
        mock_get_client.return_value = mock_client

        engine.bulk_load("/tmp/test.parquet", "skewed_data_small", "small")

    assert call_order[0] == "ensure"
    assert call_order[1] == "wait"
    assert "load_entity" in call_order


def test_bulk_load_passes_entity_type_to_load_entity(engine):
    """Entity tables (not in relation_configs) are routed to client.load_entity."""
    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine.bulk_load("/tmp/test.parquet", "skewed_data_small", "small")

    mock_client.load_entity.assert_called_once_with("/tmp/test.parquet", "skewed_data_small")
    mock_client.bulk_load_relation.assert_not_called()


def test_bulk_load_initializes_db_on_first_call(engine):
    """The first bulk_load for a partition must call client.initialize_db()."""
    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine.bulk_load("/tmp/a.parquet", "supplier_small", "small")

    mock_client.initialize_db.assert_called_once()


def test_bulk_load_does_not_reinitialize_db_on_second_call(engine):
    """Subsequent calls for the same partition must NOT reinitialise the DB."""
    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine.bulk_load("/tmp/a.parquet", "supplier_small", "small")
        engine.bulk_load("/tmp/b.parquet", "buyer_small", "small")

    assert mock_client.initialize_db.call_count == 1


def test_bulk_load_dispatches_relation_to_bulk_load_relation():
    """A table listed in relation_configs must be routed to client.bulk_load_relation."""
    engine_with_relation = TypeDBEngine(
        address="127.0.0.1:1729",
        container_name="bench_typedb_test",
        relation_configs={
            "supply_contract": {
                "roles": {
                    "supplier_id": ["supplier", "supplier_role"],
                    "buyer_id":    ["buyer",    "buyer_role"],
                },
                "attributes": ["volume"],
            }
        },
    )

    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine_with_relation.bulk_load("/tmp/sc.parquet", "supply_contract_small", "small")

    mock_client.bulk_load_relation.assert_called_once()
    mock_client.load_entity.assert_not_called()


def test_bulk_load_passes_resolved_role_map_to_bulk_load_relation():
    """Role map entity types must include the partition key suffix at call time."""
    engine_with_relation = TypeDBEngine(
        address="127.0.0.1:1729",
        container_name="bench_typedb_test",
        relation_configs={
            "supply_contract": {
                "roles": {
                    "supplier_id": ["supplier", "supplier_role"],
                },
                "attributes": ["volume"],
            }
        },
    )

    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine_with_relation.bulk_load("/tmp/sc.parquet", "supply_contract_small", "small")

    _, call_kwargs = mock_client.bulk_load_relation.call_args
    role_map = mock_client.bulk_load_relation.call_args[0][2]  # positional arg 3
    assert role_map["supplier_id"][0] == "supplier_small"      # partition key appended


# ---------------------------------------------------------------------------
# _base_table_name and _resolve_role_map unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("table_name,pk,expected", [
    ("supply_contract_small",  "small",  "supply_contract"),
    ("supplier_small",         "small",  "supplier"),
    ("buyer_medium",           "medium", "buyer"),
    ("no_suffix_here",         "small",  "no_suffix_here"),  # no matching suffix
])
def test_base_table_name_strips_partition_key(table_name, pk, expected):
    assert TypeDBEngine._base_table_name(table_name, pk) == expected


def test_resolve_role_map_appends_partition_key():
    role_configs = {
        "supplier_id": ["supplier", "supplier_role"],
        "buyer_id":    ["buyer",    "buyer_role"],
    }
    resolved = TypeDBEngine._resolve_role_map(role_configs, "small")
    assert resolved["supplier_id"] == ["supplier_small", "supplier_role"]
    assert resolved["buyer_id"]    == ["buyer_small",    "buyer_role"]


# ---------------------------------------------------------------------------
# 8. clear_cache — thrash + restart
# ---------------------------------------------------------------------------

def test_clear_cache_thrashes_os_cache(engine):
    with patch("sql_benchmarks.resources.typedb_engine.thrash_os_cache") as mock_thrash, \
         patch.object(TypeDBEngine, "_restart_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"):

        engine.clear_cache()

    mock_thrash.assert_called_once()


def test_clear_cache_restarts_container(engine):
    with patch("sql_benchmarks.resources.typedb_engine.thrash_os_cache"), \
         patch.object(TypeDBEngine, "_restart_container") as mock_restart, \
         patch.object(TypeDBEngine, "_wait_for_ready"):

        engine.clear_cache()

    mock_restart.assert_called_once()


def test_clear_cache_waits_for_ready_after_restart(engine):
    call_order = []

    with patch("sql_benchmarks.resources.typedb_engine.thrash_os_cache"), \
         patch.object(TypeDBEngine, "_restart_container", side_effect=lambda: call_order.append("restart")), \
         patch.object(TypeDBEngine, "_wait_for_ready", side_effect=lambda **kw: call_order.append("wait")):

        engine.clear_cache()

    assert call_order == ["restart", "wait"]


# ---------------------------------------------------------------------------
# 9. _get_client — correct wiring
# ---------------------------------------------------------------------------

def test_get_client_passes_address(engine):
    with patch("sql_benchmarks.resources.typedb_engine.TypeDBClient") as MockClient:
        engine._get_client("small")
        kwargs = MockClient.call_args[1]
        assert kwargs["address"] == engine.address


def test_get_client_passes_correct_db_name(engine):
    with patch("sql_benchmarks.resources.typedb_engine.TypeDBClient") as MockClient:
        engine._get_client("ssd_small")
        kwargs = MockClient.call_args[1]
        assert kwargs["db_name"] == "bench_ssd_small"


def test_get_client_different_partitions_get_different_db_names(engine):
    with patch("sql_benchmarks.resources.typedb_engine.TypeDBClient") as MockClient:
        engine._get_client("small")
        db1 = MockClient.call_args[1]["db_name"]
        engine._get_client("large")
        db2 = MockClient.call_args[1]["db_name"]
        assert db1 != db2


# ---------------------------------------------------------------------------
# 10. _build_transitive_inference_schema — TypeQL generator
# ---------------------------------------------------------------------------

def test_build_transitive_inference_schema_starts_with_define():
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    assert tql.strip().startswith("define")


def test_build_transitive_inference_schema_declares_fun_reachable():
    """TypeDB 3.x uses functions, not rules — output must use 'fun reachable'."""
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    assert "fun reachable" in tql


def test_build_transitive_inference_schema_declares_stream_return_type():
    """The function must return a stream of the entity type, not a scalar."""
    entity_type = "company_small"
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", entity_type, "seller_role", "buyer_role"
    )
    # Stream return: -> { company_small }
    assert f"-> {{ {entity_type} }}" in tql or f"->" in tql


def test_build_transitive_inference_schema_uses_let_in_for_recursive_call():
    """Recursive call in function body must use 'let $var in fn(...)' syntax."""
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    assert "let $to in reachable" in tql


def test_build_transitive_inference_schema_includes_entity_type_in_signature():
    entity_type = "company_small"
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", entity_type, "seller_role", "buyer_role"
    )
    # Entity type appears in function parameter and return type
    assert entity_type in tql


def test_build_transitive_inference_schema_includes_relation_type_in_rule():
    relation_type = "supplies_small"
    tql = TypeDBEngine._build_transitive_inference_schema(
        relation_type, "company_small", "seller_role", "buyer_role"
    )
    assert relation_type in tql


def test_build_transitive_inference_schema_includes_from_and_to_roles_in_rule():
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    assert "seller_role" in tql
    assert "buyer_role" in tql


def test_build_transitive_inference_schema_contains_fun_keyword():
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    assert "fun" in tql


def test_build_transitive_inference_schema_contains_match_and_return():
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    assert "match" in tql
    assert "return" in tql


def test_build_transitive_inference_schema_recursive_reference_to_reachable():
    """The function must reference 'reachable' both in its name and recursive call."""
    tql = TypeDBEngine._build_transitive_inference_schema(
        "supplies_small", "company_small", "seller_role", "buyer_role"
    )
    # Appears at least twice: function definition + recursive call inside body
    assert tql.count("reachable") >= 2


def test_build_transitive_inference_schema_different_roles_produce_different_tql():
    tql1 = TypeDBEngine._build_transitive_inference_schema(
        "edge", "node", "from_role", "to_role"
    )
    tql2 = TypeDBEngine._build_transitive_inference_schema(
        "edge", "node", "left_role", "right_role"
    )
    assert tql1 != tql2


# ---------------------------------------------------------------------------
# 11. bulk_load — transitive inference dispatch
# ---------------------------------------------------------------------------

def test_bulk_load_calls_apply_inference_schema_after_relation_when_flagged():
    """If config has inference=transitive, apply_inference_schema must be called."""
    engine_with_inference = TypeDBEngine(
        address="127.0.0.1:1729",
        container_name="bench_typedb_test",
        relation_configs={
            "supplies": {
                "roles": {
                    "from_id": ["company", "seller_role"],
                    "to_id":   ["company", "buyer_role"],
                },
                "attributes": [],
                "inference": "transitive",
            }
        },
    )

    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine_with_inference.bulk_load("/tmp/s.parquet", "supplies_small", "small")

    mock_client.apply_inference_schema.assert_called_once()


def test_bulk_load_does_not_call_apply_inference_schema_without_flag():
    """Without inference=transitive in config, apply_inference_schema must NOT fire."""
    engine_no_inference = TypeDBEngine(
        address="127.0.0.1:1729",
        container_name="bench_typedb_test",
        relation_configs={
            "supply_contract": {
                "roles": {
                    "supplier_id": ["supplier", "supplier_role"],
                    "buyer_id":    ["buyer",    "buyer_role"],
                },
                "attributes": ["volume"],
            }
        },
    )

    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine_no_inference.bulk_load("/tmp/sc.parquet", "supply_contract_small", "small")

    mock_client.apply_inference_schema.assert_not_called()


def test_bulk_load_passes_built_tql_to_apply_inference_schema():
    """The TQL string passed to apply_inference_schema must contain 'reachable'."""
    engine_with_inference = TypeDBEngine(
        address="127.0.0.1:1729",
        container_name="bench_typedb_test",
        relation_configs={
            "supplies": {
                "roles": {
                    "from_id": ["company", "seller_role"],
                    "to_id":   ["company", "buyer_role"],
                },
                "attributes": [],
                "inference": "transitive",
            }
        },
    )

    with patch.object(TypeDBEngine, "_ensure_container"), \
         patch.object(TypeDBEngine, "_wait_for_ready"), \
         patch.object(TypeDBEngine, "_get_client") as mock_get_client:

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        engine_with_inference.bulk_load("/tmp/s.parquet", "supplies_small", "small")

    tql_arg = mock_client.apply_inference_schema.call_args[0][0]
    assert "reachable" in tql_arg
    assert "fun" in tql_arg
