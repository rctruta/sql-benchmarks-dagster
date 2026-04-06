"""
Tests for SchemaFirstClient (abstract base).

Uses a minimal concrete stub — _StubClient — to exercise the template-method
logic without any real database I/O.  The stub records every call made to it
so tests can assert on ordering, batch counts, and argument forwarding.
"""
import math
import pytest
import polars as pl
from unittest.mock import patch

from sql_benchmarks.resources.base_schema_client import SchemaFirstClient


# ---------------------------------------------------------------------------
# Minimal concrete stub
# ---------------------------------------------------------------------------

class _StubClient(SchemaFirstClient):
    """
    Minimal SchemaFirstClient implementation for testing.

    Records every call to the three abstract steps so tests can inspect
    call ordering, argument values, and batch counts.
    """

    def __init__(self):
        self.calls = []          # ordered log of (method_name, args)
        self.insert_batches = [] # each batch passed to _insert_batch

    def run_query(self, query, scenario_params):
        self.calls.append(("run_query", query, scenario_params))
        return 0.0

    def _prepare_store(self, entity_type):
        self.calls.append(("_prepare_store", entity_type))

    def _define_schema(self, entity_type, df):
        self.calls.append(("_define_schema", entity_type, df))

    def _insert_batch(self, entity_type, rows):
        self.calls.append(("_insert_batch", entity_type, len(rows)))
        self.insert_batches.append(rows)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _write_parquet(tmp_path, n_rows: int) -> str:
    df = pl.DataFrame({
        "id":    list(range(n_rows)),
        "label": ["x"] * n_rows,
    })
    path = str(tmp_path / "data.parquet")
    df.write_parquet(path)
    return path


@pytest.fixture
def stub():
    return _StubClient()


# ---------------------------------------------------------------------------
# 1. Abstract-method enforcement
# ---------------------------------------------------------------------------

def test_cannot_instantiate_without_run_query():
    class _Missing(SchemaFirstClient):
        def _prepare_store(self, entity_type): pass
        def _define_schema(self, entity_type, df): pass
        def _insert_batch(self, entity_type, rows): pass

    with pytest.raises(TypeError):
        _Missing()


def test_cannot_instantiate_without_prepare_store():
    class _Missing(SchemaFirstClient):
        def run_query(self, q, p): return 0.0
        def _define_schema(self, entity_type, df): pass
        def _insert_batch(self, entity_type, rows): pass

    with pytest.raises(TypeError):
        _Missing()


def test_cannot_instantiate_without_define_schema():
    class _Missing(SchemaFirstClient):
        def run_query(self, q, p): return 0.0
        def _prepare_store(self, entity_type): pass
        def _insert_batch(self, entity_type, rows): pass

    with pytest.raises(TypeError):
        _Missing()


def test_cannot_instantiate_without_insert_batch():
    class _Missing(SchemaFirstClient):
        def run_query(self, q, p): return 0.0
        def _prepare_store(self, entity_type): pass
        def _define_schema(self, entity_type, df): pass

    with pytest.raises(TypeError):
        _Missing()


# ---------------------------------------------------------------------------
# 2. bulk_load — call sequence
# ---------------------------------------------------------------------------

def test_bulk_load_calls_prepare_store_first(stub, tmp_path):
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="my_entity")

    step_names = [c[0] for c in stub.calls]
    assert step_names[0] == "_prepare_store"


def test_bulk_load_calls_define_schema_second(stub, tmp_path):
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="my_entity")

    step_names = [c[0] for c in stub.calls]
    assert step_names[1] == "_define_schema"


def test_bulk_load_calls_insert_batch_after_schema(stub, tmp_path):
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="my_entity")

    step_names = [c[0] for c in stub.calls]
    # Everything after index 1 should be _insert_batch calls
    assert all(s == "_insert_batch" for s in step_names[2:])


def test_bulk_load_passes_entity_type_to_prepare(stub, tmp_path):
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="supply_contract")

    prepare_call = next(c for c in stub.calls if c[0] == "_prepare_store")
    assert prepare_call[1] == "supply_contract"


def test_bulk_load_passes_entity_type_to_define_schema(stub, tmp_path):
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="supply_contract")

    define_call = next(c for c in stub.calls if c[0] == "_define_schema")
    assert define_call[1] == "supply_contract"


def test_bulk_load_passes_dataframe_to_define_schema(stub, tmp_path):
    path = _write_parquet(tmp_path, 5)
    stub.bulk_load(path, entity_type="t")

    define_call = next(c for c in stub.calls if c[0] == "_define_schema")
    df_arg = define_call[2]
    assert isinstance(df_arg, pl.DataFrame)
    assert len(df_arg) == 5


def test_bulk_load_passes_entity_type_to_every_insert_batch(stub, tmp_path):
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="widget")

    insert_calls = [c for c in stub.calls if c[0] == "_insert_batch"]
    assert all(c[1] == "widget" for c in insert_calls)


# ---------------------------------------------------------------------------
# 3. bulk_load — batching
# ---------------------------------------------------------------------------

def test_bulk_load_single_batch_for_small_dataset(stub, tmp_path):
    """Fewer rows than BATCH_SIZE → exactly one _insert_batch call."""
    assert SchemaFirstClient.BATCH_SIZE > 3, "fixture assumption"
    path = _write_parquet(tmp_path, 3)
    stub.bulk_load(path, entity_type="t")

    assert len(stub.insert_batches) == 1


def test_bulk_load_correct_number_of_batches(tmp_path):
    """ceil(N / BATCH_SIZE) _insert_batch calls for N rows."""
    stub = _StubClient()
    n_rows = SchemaFirstClient.BATCH_SIZE * 2 + 1  # forces 3 batches
    path = _write_parquet(tmp_path, n_rows)
    stub.bulk_load(path, entity_type="t")

    expected = math.ceil(n_rows / SchemaFirstClient.BATCH_SIZE)
    assert len(stub.insert_batches) == expected


def test_bulk_load_last_batch_has_remainder_rows(tmp_path):
    """The last batch contains only the leftover rows, not a full batch."""
    stub = _StubClient()
    remainder = 7
    n_rows = SchemaFirstClient.BATCH_SIZE + remainder
    path = _write_parquet(tmp_path, n_rows)
    stub.bulk_load(path, entity_type="t")

    assert len(stub.insert_batches[-1]) == remainder


def test_bulk_load_total_rows_match_input(tmp_path):
    """All rows across all batches sum to the original row count."""
    stub = _StubClient()
    n_rows = SchemaFirstClient.BATCH_SIZE * 3 + 50
    path = _write_parquet(tmp_path, n_rows)
    stub.bulk_load(path, entity_type="t")

    total = sum(len(b) for b in stub.insert_batches)
    assert total == n_rows


def test_bulk_load_rows_are_dicts(stub, tmp_path):
    """_insert_batch receives plain Python dicts, not Polars rows."""
    path = _write_parquet(tmp_path, 2)
    stub.bulk_load(path, entity_type="t")

    for batch in stub.insert_batches:
        for row in batch:
            assert isinstance(row, dict)


# ---------------------------------------------------------------------------
# 4. bulk_load — print output
# ---------------------------------------------------------------------------

def test_bulk_load_prints_row_count_and_entity_type(stub, tmp_path, capsys):
    path = _write_parquet(tmp_path, 5)
    stub.bulk_load(path, entity_type="skewed_data")

    out = capsys.readouterr().out
    assert "5" in out
    assert "skewed_data" in out


def test_bulk_load_print_includes_class_name(tmp_path, capsys):
    """The print statement identifies the concrete subclass."""
    stub = _StubClient()
    path = _write_parquet(tmp_path, 1)
    stub.bulk_load(path, entity_type="t")

    out = capsys.readouterr().out
    assert "_StubClient" in out
