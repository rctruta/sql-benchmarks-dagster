"""
Tests for TypeDBClient.

Mirrors the structure of test_duckdb_client.py: all external I/O (TypeDB driver,
filesystem) is mocked so the suite runs without a live TypeDB instance.
"""
import pytest
import polars as pl
from unittest.mock import patch, MagicMock, call

from sql_benchmarks.resources.typedb_client import TypeDBClient
from sql_benchmarks.resources.base_schema_client import SchemaFirstClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADDRESS = "127.0.0.1:1729"
DB_NAME = "bench_test_partition"


def _make_driver_mock():
    """
    Builds a mock that faithfully models the TypeDB driver context manager:

        with TypeDB.driver(...) as driver:
            with driver.transaction(...) as tx:
                tx.query(...).resolve()
    """
    promise = MagicMock()
    promise.resolve.return_value = MagicMock(
        as_concept_rows=MagicMock(return_value=iter([]))
    )

    tx = MagicMock()
    tx.query.return_value = promise
    tx.__enter__ = MagicMock(return_value=tx)
    tx.__exit__ = MagicMock(return_value=False)

    driver = MagicMock()
    driver.transaction.return_value = tx
    driver.databases = MagicMock()
    driver.databases.contains.return_value = False
    driver.__enter__ = MagicMock(return_value=driver)
    driver.__exit__ = MagicMock(return_value=False)

    return driver, tx, promise


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TypeDBClient(address=ADDRESS, db_name=DB_NAME)


@pytest.fixture
def small_df():
    """A minimal Polars DataFrame that exercises the main column types."""
    return pl.DataFrame({
        "id":               [1, 2, 3],
        "selectivity_code": ["sel_1", "sel_5", None],
        "score":            [1.5, 2.5, 3.5],
        "active":           [True, False, True],
    })


# ---------------------------------------------------------------------------
# 1. Type mapping (_polars_to_typeql_value)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dtype,expected", [
    (pl.Int8,    "integer"),
    (pl.Int16,   "integer"),
    (pl.Int32,   "integer"),
    (pl.Int64,   "integer"),
    (pl.UInt32,  "integer"),
    (pl.Float32, "double"),
    (pl.Float64, "double"),
    (pl.Boolean, "boolean"),
    (pl.Utf8,    "string"),
    (pl.String,  "string"),
    (pl.Date,    "datetime"),
])
def test_polars_to_typeql_value_mapping(dtype, expected):
    """Every Polars dtype we care about maps to the correct TypeQL value type."""
    assert TypeDBClient._polars_to_typeql_value(dtype) == expected


def test_polars_to_typeql_value_datetime_instance():
    """Datetime with time-unit params is also mapped correctly."""
    assert TypeDBClient._polars_to_typeql_value(pl.Datetime("us")) == "datetime"


def test_polars_to_typeql_value_unknown_falls_back_to_string():
    """An unrecognised dtype safely falls back to string."""
    class _FakeDtype:
        pass
    assert TypeDBClient._polars_to_typeql_value(_FakeDtype()) == "string"


# ---------------------------------------------------------------------------
# 2. Schema builder (_build_schema)
# ---------------------------------------------------------------------------

def test_build_schema_starts_with_define(client, small_df):
    schema = client._build_schema("my_entity", small_df)
    assert schema.strip().startswith("define")


def test_build_schema_declares_entity_type(client, small_df):
    schema = client._build_schema("my_entity", small_df)
    assert "entity my_entity" in schema


def test_build_schema_id_column_gets_key_annotation(client, small_df):
    schema = client._build_schema("my_entity", small_df)
    assert "owns id @key" in schema


def test_build_schema_non_id_columns_have_no_key_annotation(client, small_df):
    schema = client._build_schema("my_entity", small_df)
    assert "owns selectivity_code @key" not in schema
    assert "owns selectivity_code" in schema


def test_build_schema_all_columns_declared_as_attributes(client, small_df):
    schema = client._build_schema("my_entity", small_df)
    for col in small_df.columns:
        assert f"attribute {col}" in schema


def test_build_schema_correct_value_types(client):
    df = pl.DataFrame({"id": [1], "label": ["x"], "ratio": [0.5], "flag": [True]})
    schema = client._build_schema("t", df)
    assert "attribute id, value integer" in schema
    assert "attribute label, value string" in schema
    assert "attribute ratio, value double" in schema
    assert "attribute flag, value boolean" in schema


# ---------------------------------------------------------------------------
# 3. Insert builder (_build_insert)
# ---------------------------------------------------------------------------

def test_build_insert_starts_with_insert_keyword(client):
    rows = [{"id": 1, "label": "hello"}]
    result = client._build_insert("my_entity", rows)
    assert result.strip().startswith("insert")


def test_build_insert_one_variable_per_row(client):
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    result = client._build_insert("my_entity", rows)
    assert "$x0" in result
    assert "$x1" in result
    assert "$x2" in result


def test_build_insert_string_values_are_quoted(client):
    rows = [{"id": 1, "label": "hello world"}]
    result = client._build_insert("my_entity", rows)
    assert 'has label "hello world"' in result


def test_build_insert_string_values_escape_double_quotes(client):
    rows = [{"id": 1, "label": 'say "hi"'}]
    result = client._build_insert("my_entity", rows)
    assert r'has label "say \"hi\""' in result


def test_build_insert_string_values_escape_backslashes(client):
    rows = [{"id": 1, "label": "back\\slash"}]
    result = client._build_insert("my_entity", rows)
    assert 'has label "back\\\\slash"' in result


def test_build_insert_none_values_are_skipped(client):
    rows = [{"id": 1, "label": None}]
    result = client._build_insert("my_entity", rows)
    assert "has label" not in result
    assert "has id 1" in result


def test_build_insert_boolean_values_are_lowercase(client):
    rows = [{"id": 1, "flag": True}, {"id": 2, "flag": False}]
    result = client._build_insert("my_entity", rows)
    assert "has flag true" in result
    assert "has flag false" in result


def test_build_insert_numeric_values_are_unquoted(client):
    rows = [{"id": 42, "score": 3.14}]
    result = client._build_insert("my_entity", rows)
    assert "has id 42" in result
    assert "has score 3.14" in result


def test_build_insert_entity_type_present_in_each_statement(client):
    rows = [{"id": 1}, {"id": 2}]
    result = client._build_insert("skewed_data_small", rows)
    assert result.count("isa skewed_data_small") == 2


# ---------------------------------------------------------------------------
# 4. run_query — timing and delegation
# ---------------------------------------------------------------------------

def test_run_query_returns_elapsed_time(client):
    driver, tx, promise = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver), \
         patch("time.time", side_effect=[10.0, 11.5]):
        duration = client.run_query("match $x isa t; select $x;", {})

    assert duration == pytest.approx(1.5)


def test_run_query_calls_query_with_given_typeql(client):
    driver, tx, promise = _make_driver_mock()
    typeql = "match $x isa my_entity; select $x;"

    with patch.object(client, "_driver", return_value=driver):
        client.run_query(typeql, {})

    tx.query.assert_called_once_with(typeql)


def test_run_query_resolves_promise(client):
    driver, tx, promise = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.run_query("match $x isa t; select $x;", {})

    promise.resolve.assert_called_once()


def test_run_query_consumes_all_concept_rows(client):
    """Ensures list() is called on as_concept_rows() to force full materialisation."""
    driver, tx, promise = _make_driver_mock()
    row_iter = iter(["row1", "row2", "row3"])
    promise.resolve.return_value.as_concept_rows.return_value = row_iter

    with patch.object(client, "_driver", return_value=driver):
        client.run_query("match $x isa t; select $x;", {})

    # All rows must be consumed — the iterator should be exhausted
    assert list(row_iter) == []


def test_run_query_uses_read_transaction(client):
    from typedb.driver import TransactionType
    driver, tx, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.run_query("match $x isa t; select $x;", {})

    driver.transaction.assert_called_once_with(DB_NAME, TransactionType.READ)


# ---------------------------------------------------------------------------
# 5. bulk_load — database lifecycle and batching
# ---------------------------------------------------------------------------

def test_bulk_load_drops_existing_database(client, small_df, tmp_path):
    parquet_path = str(tmp_path / "test.parquet")
    small_df.write_parquet(parquet_path)

    driver, tx, _ = _make_driver_mock()
    driver.databases.contains.return_value = True  # DB already exists

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load(parquet_path, entity_type="my_entity")

    driver.databases.get.assert_called_once_with(DB_NAME)
    driver.databases.get.return_value.delete.assert_called_once()


def test_bulk_load_skips_delete_when_db_absent(client, small_df, tmp_path):
    parquet_path = str(tmp_path / "test.parquet")
    small_df.write_parquet(parquet_path)

    driver, tx, _ = _make_driver_mock()
    driver.databases.contains.return_value = False  # DB does not exist

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load(parquet_path, entity_type="my_entity")

    driver.databases.get.assert_not_called()


def test_bulk_load_creates_database(client, small_df, tmp_path):
    parquet_path = str(tmp_path / "test.parquet")
    small_df.write_parquet(parquet_path)

    driver, tx, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load(parquet_path, entity_type="my_entity")

    driver.databases.create.assert_called_once_with(DB_NAME)


def test_bulk_load_sends_schema_transaction_first(client, small_df, tmp_path):
    """The SCHEMA transaction must be opened before any WRITE transaction."""
    from typedb.driver import TransactionType

    parquet_path = str(tmp_path / "test.parquet")
    small_df.write_parquet(parquet_path)

    driver, tx, _ = _make_driver_mock()
    transaction_calls = []
    driver.transaction.side_effect = lambda db, ttype: (
        transaction_calls.append(ttype) or tx
    )

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load(parquet_path, entity_type="my_entity")

    assert transaction_calls[0] == TransactionType.SCHEMA


def test_bulk_load_batches_rows_correctly(tmp_path):
    """With N rows and BATCH_SIZE B, we expect ceil(N/B) WRITE transactions."""
    import math

    n_rows = SchemaFirstClient.BATCH_SIZE * 2 + 1  # forces 3 batches
    df = pl.DataFrame({
        "id": list(range(n_rows)),
        "label": ["x"] * n_rows,
    })
    parquet_path = str(tmp_path / "big.parquet")
    df.write_parquet(parquet_path)

    driver, tx, _ = _make_driver_mock()
    client = TypeDBClient(address=ADDRESS, db_name=DB_NAME)

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load(parquet_path, entity_type="t")

    from typedb.driver import TransactionType
    write_calls = [
        c for c in driver.transaction.call_args_list
        if c[0][1] == TransactionType.WRITE
    ]
    expected_batches = math.ceil(n_rows / SchemaFirstClient.BATCH_SIZE)
    assert len(write_calls) == expected_batches


def test_bulk_load_commits_each_transaction(client, small_df, tmp_path):
    parquet_path = str(tmp_path / "test.parquet")
    small_df.write_parquet(parquet_path)

    driver, tx, _ = _make_driver_mock()

    with patch.object(client, "_driver", return_value=driver):
        client.bulk_load(parquet_path, entity_type="my_entity")

    # commit() must be called at least once per transaction (schema + writes)
    assert tx.commit.call_count >= 2


# ---------------------------------------------------------------------------
# 6. _driver — correct TypeDB API usage
# ---------------------------------------------------------------------------

def test_driver_uses_correct_address(client):
    """_driver() must pass the configured address to TypeDB.driver()."""
    with patch("sql_benchmarks.resources.typedb_client.TypeDB") as MockTypeDB, \
         patch("sql_benchmarks.resources.typedb_client.Credentials"), \
         patch("sql_benchmarks.resources.typedb_client.DriverOptions"):
        client._driver()
        args = MockTypeDB.driver.call_args[0]
        assert args[0] == ADDRESS


def test_driver_disables_tls(client):
    """Local connections must use DriverOptions(is_tls_enabled=False)."""
    with patch("sql_benchmarks.resources.typedb_client.TypeDB"), \
         patch("sql_benchmarks.resources.typedb_client.Credentials"), \
         patch("sql_benchmarks.resources.typedb_client.DriverOptions") as MockOpts:
        client._driver()
        MockOpts.assert_called_once_with(is_tls_enabled=False)
