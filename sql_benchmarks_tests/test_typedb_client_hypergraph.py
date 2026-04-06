"""
Tests for TypeDBClient hypergraph / relation support.

Covers the three new methods added for multi-table (supply-chain) loading:
  - initialize_db
  - load_entity
  - bulk_load_relation  (+ its two builders)

All external I/O (TypeDB driver, filesystem) is mocked so the suite runs
without a live TypeDB instance.
"""
import math
import pytest
import polars as pl
from unittest.mock import patch, MagicMock, call

from sql_benchmarks.resources.typedb_client import TypeDBClient
from sql_benchmarks.resources.base_schema_client import SchemaFirstClient

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

ADDRESS = "127.0.0.1:1729"
DB_NAME  = "bench_small"


def _make_driver_mock():
    promise = MagicMock()
    promise.resolve.return_value = MagicMock(
        as_concept_rows=MagicMock(return_value=iter([]))
    )
    tx = MagicMock()
    tx.query.return_value = promise
    tx.__enter__ = MagicMock(return_value=tx)
    tx.__exit__  = MagicMock(return_value=False)

    driver = MagicMock()
    driver.transaction.return_value = tx
    driver.databases = MagicMock()
    driver.databases.contains.return_value = False
    driver.__enter__ = MagicMock(return_value=driver)
    driver.__exit__  = MagicMock(return_value=False)
    return driver, tx, promise


@pytest.fixture
def client():
    return TypeDBClient(address=ADDRESS, db_name=DB_NAME)


@pytest.fixture
def small_supply_df():
    """Minimal supply-contract DataFrame for builder tests."""
    return pl.DataFrame({
        "id":          [1, 2],
        "supplier_id": [10, 20],
        "buyer_id":    [5,  15],
        "product_id":  [3,  7],
        "volume":      [500, 1200],
        "price_per_unit": [12.5, 99.0],
    })


ROLE_MAP = {
    "supplier_id": ["supplier_small", "supplier_role"],
    "buyer_id":    ["buyer_small",    "buyer_role"],
    "product_id":  ["product_small",  "product_role"],
}
ATTRIBUTES = ["volume", "price_per_unit"]


# ---------------------------------------------------------------------------
# 1. initialize_db
# ---------------------------------------------------------------------------

def test_initialize_db_drops_existing_database(client):
    driver, _, _ = _make_driver_mock()
    driver.databases.contains.return_value = True

    with patch.object(client, "_driver", return_value=driver):
        client.initialize_db()

    driver.databases.get.assert_called_once_with(DB_NAME)
    driver.databases.get.return_value.delete.assert_called_once()


def test_initialize_db_skips_delete_when_db_absent(client):
    driver, _, _ = _make_driver_mock()
    driver.databases.contains.return_value = False

    with patch.object(client, "_driver", return_value=driver):
        client.initialize_db()

    driver.databases.get.assert_not_called()


def test_initialize_db_creates_database(client):
    driver, _, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.initialize_db()

    driver.databases.create.assert_called_once_with(DB_NAME)


# ---------------------------------------------------------------------------
# 2. load_entity
# ---------------------------------------------------------------------------

def test_load_entity_defines_schema(client, small_supply_df, tmp_path):
    parquet = str(tmp_path / "supplier.parquet")
    small_supply_df.write_parquet(parquet)

    driver, tx, _ = _make_driver_mock()
    from typedb.driver import TransactionType

    with patch.object(client, "_driver", return_value=driver):
        client.load_entity(parquet, "supplier_small")

    schema_calls = [
        c for c in driver.transaction.call_args_list
        if c[0][1] == TransactionType.SCHEMA
    ]
    assert len(schema_calls) == 1


def test_load_entity_inserts_data(client, small_supply_df, tmp_path):
    parquet = str(tmp_path / "supplier.parquet")
    small_supply_df.write_parquet(parquet)

    driver, tx, _ = _make_driver_mock()
    from typedb.driver import TransactionType

    with patch.object(client, "_driver", return_value=driver):
        client.load_entity(parquet, "supplier_small")

    write_calls = [
        c for c in driver.transaction.call_args_list
        if c[0][1] == TransactionType.WRITE
    ]
    assert len(write_calls) >= 1


def test_load_entity_does_not_drop_database(client, small_supply_df, tmp_path):
    """load_entity must NOT touch driver.databases (no drop/create)."""
    parquet = str(tmp_path / "supplier.parquet")
    small_supply_df.write_parquet(parquet)

    driver, _, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.load_entity(parquet, "supplier_small")

    driver.databases.get.assert_not_called()
    driver.databases.create.assert_not_called()


def test_load_entity_prints_row_count(client, small_supply_df, tmp_path, capsys):
    parquet = str(tmp_path / "supplier.parquet")
    small_supply_df.write_parquet(parquet)

    driver, _, _ = _make_driver_mock()
    with patch.object(client, "_driver", return_value=driver):
        client.load_entity(parquet, "supplier_small")

    out = capsys.readouterr().out
    assert str(len(small_supply_df)) in out
    assert "supplier_small" in out


# ---------------------------------------------------------------------------
# 3. _build_relation_schema
# ---------------------------------------------------------------------------

def test_build_relation_schema_starts_with_define(client, small_supply_df):
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert result.strip().startswith("define")


def test_build_relation_schema_declares_relation_type(client, small_supply_df):
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert "relation supply_contract_small" in result


def test_build_relation_schema_includes_all_roles(client, small_supply_df):
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert "relates supplier_role" in result
    assert "relates buyer_role"    in result
    assert "relates product_role"  in result


def test_build_relation_schema_owns_attributes(client, small_supply_df):
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert "owns volume" in result
    assert "owns price_per_unit" in result


def test_build_relation_schema_plays_declarations(client, small_supply_df):
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert "supplier_small plays supply_contract_small:supplier_role" in result
    assert "buyer_small plays supply_contract_small:buyer_role"       in result
    assert "product_small plays supply_contract_small:product_role"   in result


def test_build_relation_schema_correct_attribute_value_types(client, small_supply_df):
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert "attribute volume, value integer"         in result
    assert "attribute price_per_unit, value double"  in result


def test_build_relation_schema_no_fk_columns_as_attributes(client, small_supply_df):
    """FK columns (supplier_id etc.) must NOT appear as owned attributes."""
    result = client._build_relation_schema(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, small_supply_df
    )
    assert "owns supplier_id" not in result
    assert "owns buyer_id"    not in result
    assert "owns product_id"  not in result


# ---------------------------------------------------------------------------
# 4. _build_relation_insert
# ---------------------------------------------------------------------------

def test_build_relation_insert_starts_with_match(client):
    rows = [{"supplier_id": 1, "buyer_id": 2, "product_id": 3,
             "volume": 500, "price_per_unit": 12.5}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert result.strip().startswith("match")


def test_build_relation_insert_contains_insert_section(client):
    rows = [{"supplier_id": 1, "buyer_id": 2, "product_id": 3,
             "volume": 500, "price_per_unit": 12.5}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "insert" in result


def test_build_relation_insert_match_binds_each_entity(client):
    rows = [{"supplier_id": 10, "buyer_id": 20, "product_id": 30,
             "volume": 500, "price_per_unit": 12.5}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "isa supplier_small, has id 10" in result
    assert "isa buyer_small, has id 20"    in result
    assert "isa product_small, has id 30"  in result


def test_build_relation_insert_insert_uses_correct_roles(client):
    rows = [{"supplier_id": 1, "buyer_id": 2, "product_id": 3,
             "volume": 100, "price_per_unit": 5.0}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "supplier_role:" in result
    assert "buyer_role:"    in result
    assert "product_role:"  in result


def test_build_relation_insert_includes_relation_type(client):
    rows = [{"supplier_id": 1, "buyer_id": 2, "product_id": 3,
             "volume": 100, "price_per_unit": 5.0}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "isa supply_contract_small" in result


def test_build_relation_insert_includes_attribute_values(client):
    rows = [{"supplier_id": 1, "buyer_id": 2, "product_id": 3,
             "volume": 750, "price_per_unit": 33.3}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "has volume 750"         in result
    assert "has price_per_unit 33.3" in result


def test_build_relation_insert_skips_null_attributes(client):
    rows = [{"supplier_id": 1, "buyer_id": 2, "product_id": 3,
             "volume": None, "price_per_unit": 5.0}]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "has volume" not in result
    assert "has price_per_unit 5.0" in result


def test_build_relation_insert_unique_vars_for_each_row(client):
    """Each row must use distinct variable names to avoid collision."""
    rows = [
        {"supplier_id": 1, "buyer_id": 2, "product_id": 3, "volume": 100, "price_per_unit": 1.0},
        {"supplier_id": 4, "buyer_id": 5, "product_id": 6, "volume": 200, "price_per_unit": 2.0},
    ]
    result = client._build_relation_insert(
        "supply_contract_small", ROLE_MAP, ATTRIBUTES, rows
    )
    assert "$e0_supplier_id" in result
    assert "$e1_supplier_id" in result


# ---------------------------------------------------------------------------
# 5. bulk_load_relation — orchestration
# ---------------------------------------------------------------------------

def test_bulk_load_relation_runs_schema_transaction(client, small_supply_df, tmp_path):
    from typedb.driver import TransactionType
    parquet = str(tmp_path / "sc.parquet")
    small_supply_df.write_parquet(parquet)
    driver, tx, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load_relation(parquet, "supply_contract_small", ROLE_MAP, ATTRIBUTES)

    schema_calls = [
        c for c in driver.transaction.call_args_list
        if c[0][1] == TransactionType.SCHEMA
    ]
    assert len(schema_calls) == 1


def test_bulk_load_relation_schema_before_any_write(client, small_supply_df, tmp_path):
    from typedb.driver import TransactionType
    parquet = str(tmp_path / "sc.parquet")
    small_supply_df.write_parquet(parquet)
    driver, tx, _ = _make_driver_mock()
    tx_types = []
    driver.transaction.side_effect = lambda db, ttype: tx_types.append(ttype) or tx

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load_relation(parquet, "supply_contract_small", ROLE_MAP, ATTRIBUTES)

    assert tx_types[0] == TransactionType.SCHEMA


def test_bulk_load_relation_correct_batch_count(tmp_path):
    n_rows  = SchemaFirstClient.BATCH_SIZE * 2 + 1  # forces 3 write batches
    df = pl.DataFrame({
        "id":          list(range(n_rows)),
        "supplier_id": list(range(n_rows)),
        "buyer_id":    list(range(n_rows)),
        "product_id":  list(range(n_rows)),
        "volume":      [100] * n_rows,
        "price_per_unit": [1.0] * n_rows,
    })
    parquet = str(tmp_path / "big_sc.parquet")
    df.write_parquet(parquet)

    driver, tx, _ = _make_driver_mock()
    client = TypeDBClient(address=ADDRESS, db_name=DB_NAME)

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load_relation(parquet, "supply_contract_small", ROLE_MAP, ATTRIBUTES)

    from typedb.driver import TransactionType
    write_calls = [
        c for c in driver.transaction.call_args_list
        if c[0][1] == TransactionType.WRITE
    ]
    assert len(write_calls) == math.ceil(n_rows / SchemaFirstClient.BATCH_SIZE)


def test_bulk_load_relation_commits_each_transaction(client, small_supply_df, tmp_path):
    parquet = str(tmp_path / "sc.parquet")
    small_supply_df.write_parquet(parquet)
    driver, tx, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load_relation(parquet, "supply_contract_small", ROLE_MAP, ATTRIBUTES)

    # 1 schema commit + at least 1 write commit
    assert tx.commit.call_count >= 2


def test_bulk_load_relation_prints_row_count(client, small_supply_df, tmp_path, capsys):
    parquet = str(tmp_path / "sc.parquet")
    small_supply_df.write_parquet(parquet)
    driver, _, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load_relation(parquet, "supply_contract_small", ROLE_MAP, ATTRIBUTES)

    out = capsys.readouterr().out
    assert str(len(small_supply_df)) in out


# ---------------------------------------------------------------------------
# 6. apply_inference_schema
# ---------------------------------------------------------------------------

def test_apply_inference_schema_uses_schema_transaction(client):
    """apply_inference_schema must open a SCHEMA (not WRITE/READ) transaction."""
    from typedb.driver import TransactionType

    driver, tx, _ = _make_driver_mock()
    tql = "define relation reachable, relates source, relates target;"

    with patch.object(client, "_driver", return_value=driver):
        client.apply_inference_schema(tql)

    driver.transaction.assert_called_once_with(client.db_name, TransactionType.SCHEMA)


def test_apply_inference_schema_executes_passed_tql(client):
    """The exact TypeQL string passed in must be sent to tx.query."""
    driver, tx, _ = _make_driver_mock()
    tql = "define relation reachable, relates source, relates target;"

    with patch.object(client, "_driver", return_value=driver):
        client.apply_inference_schema(tql)

    tx.query.assert_called_once_with(tql)


def test_apply_inference_schema_commits_transaction(client):
    """Schema changes must be committed, not just queried."""
    driver, tx, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.apply_inference_schema("define relation reachable, relates source;")

    tx.commit.assert_called_once()


def test_apply_inference_schema_prints_confirmation(client, capsys):
    """A confirmation line should appear on stdout so pipeline logs are legible."""
    driver, _, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.apply_inference_schema("define relation reachable, relates source;")

    out = capsys.readouterr().out
    assert "inference" in out.lower() or "schema" in out.lower() or client.db_name in out


def test_apply_inference_schema_can_be_called_multiple_times(client):
    """Calling twice should not raise — TypeDB define is idempotent."""
    driver, _, _ = _make_driver_mock()
    tql = "define relation reachable, relates source, relates target;"

    with patch.object(client, "_driver", return_value=driver):
        client.apply_inference_schema(tql)
        client.apply_inference_schema(tql)  # second call must not raise

    assert driver.transaction.call_count == 2
