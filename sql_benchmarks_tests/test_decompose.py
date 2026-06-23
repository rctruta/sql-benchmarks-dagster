"""Config-loader expansion of `decompose` directives into NULL-free sub-tables."""
import copy
import yaml
import pytest
from sql_benchmarks.config_loader import ConfigLoader

BASE = {
    "meta": {"name": "decompose test"},
    "dataset": {
        "source": "sql_benchmarks.plugins.data_sources.declarative_gen",
        "tables": {
            "person": {
                "rows": "rows",
                "columns": [
                    {"name": "ssn", "provider": "sequence", "primary_key": True},
                    {"name": "fname", "provider": "choice", "options": ["a", "b"]},
                    {"name": "age", "provider": "random_int", "min_value": 1, "max_value": 9,
                     "null_probability": 0.3},
                    {"name": "email", "provider": "choice", "options": ["x", "y"],
                     "null_probability": 0.3},
                ],
            }
        },
    },
    "execution": {"engines": ["duckdb"], "matrix": {"rows": ["micro"]}},
    "definitions": {"rows": {"micro": 1000}},
}


def _load(tmp_path, decompose):
    cfg = copy.deepcopy(BASE)
    cfg["dataset"]["tables"]["person"]["decompose"] = decompose
    p = tmp_path / "exp.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return ConfigLoader(str(p)).dataset["tables"]


def _cols(tables, name):
    return [c["name"] for c in tables[name]["columns"]]


def test_horizontal_expands_to_2_to_the_k(tmp_path):
    t = _load(tmp_path, {"on": ["age", "email"], "strategy": "horizontal"})
    frags = {n for n in t if n.startswith("person__h__")}
    assert frags == {"person__h__none", "person__h__age", "person__h__email", "person__h__age_email"}
    # null-pattern fragments carry mandatory cols + exactly their present subset
    assert _cols(t, "person__h__none") == ["ssn", "fname"]
    assert _cols(t, "person__h__age") == ["ssn", "fname", "age"]
    assert _cols(t, "person__h__age_email") == ["ssn", "fname", "age", "email"]
    for f in frags:
        assert t[f]["deps"] == ["person"]
        assert all(c["null_probability"] == 0.0 for c in t[f]["columns"])  # NULL-free
    assert t["person__h__age"]["_derive"] == {
        "from": "person", "strategy": "horizontal",
        "on": ["age", "email"], "present": ["age"], "select": ["ssn", "fname", "age"],
    }
    assert "person" in t  # monolithic survives for the baseline


def test_vertical_expands_to_k_plus_1(tmp_path):
    t = _load(tmp_path, {"on": ["age", "email"], "strategy": "vertical"})
    assert _cols(t, "person__v__core") == ["ssn", "fname"]
    assert _cols(t, "person__v__age") == ["ssn", "age"]        # pk + attribute
    assert _cols(t, "person__v__email") == ["ssn", "email"]
    assert t["person__v__age"]["_derive"]["where_not_null"] == "age"
    assert all(t[n]["deps"] == ["person"] for n in ("person__v__core", "person__v__age", "person__v__email"))


def test_unknown_column_in_on_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown columns"):
        _load(tmp_path, {"on": ["nope"], "strategy": "horizontal"})


def test_no_decompose_is_noop(tmp_path):
    cfg = copy.deepcopy(BASE)
    p = tmp_path / "exp.yaml"
    p.write_text(yaml.safe_dump(cfg))
    t = ConfigLoader(str(p)).dataset["tables"]
    assert set(t.keys()) == {"person"}


# --- end-to-end: the actual carving from a parent parquet ---
import polars as pl
from sql_benchmarks.plugins.data_sources.declarative_gen import _derive_table


def _parent(tmp_path):
    # one row per null-pattern: age&email, neither, age-only, email-only
    df = pl.DataFrame({
        "ssn": [1, 2, 3, 4],
        "fname": ["a", "b", "c", "d"],
        "age": [10, None, 30, None],
        "email": ["x", None, None, "w"],
    })
    df.write_parquet(tmp_path / "person_micro.parquet")


def _derive(tmp_path, name, marker):
    tp = str(tmp_path / f"{name}_micro.parquet")
    _derive_table(name, tp, marker)
    return pl.read_parquet(tp)


def test_horizontal_derive_nullfree_disjoint_covering(tmp_path):
    _parent(tmp_path)
    on = ["age", "email"]
    h = lambda present, select: {"from": "person", "strategy": "horizontal",
                                 "on": on, "present": present, "select": select}
    none = _derive(tmp_path, "person__h__none", h([], ["ssn", "fname"]))
    age = _derive(tmp_path, "person__h__age", h(["age"], ["ssn", "fname", "age"]))
    email = _derive(tmp_path, "person__h__email", h(["email"], ["ssn", "fname", "email"]))
    ae = _derive(tmp_path, "person__h__age_email", h(["age", "email"], ["ssn", "fname", "age", "email"]))

    # disjoint + covering: each original row lands in exactly one fragment
    assert none["ssn"].to_list() == [2]
    assert age["ssn"].to_list() == [3]
    assert email["ssn"].to_list() == [4]
    assert ae["ssn"].to_list() == [1]
    assert none.height + age.height + email.height + ae.height == 4
    # NULL-free by construction
    for df in (none, age, email, ae):
        assert int(df.null_count().to_numpy().sum()) == 0


def test_vertical_derive(tmp_path):
    _parent(tmp_path)
    core = _derive(tmp_path, "person__v__core",
                   {"from": "person", "strategy": "vertical", "select": ["ssn", "fname"]})
    age = _derive(tmp_path, "person__v__age",
                  {"from": "person", "strategy": "vertical", "select": ["ssn", "age"],
                   "where_not_null": "age"})
    assert core.height == 4                       # core keeps every pk
    assert sorted(age["ssn"].to_list()) == [1, 3]  # only rows where age is present
    assert int(age.null_count().to_numpy().sum()) == 0
