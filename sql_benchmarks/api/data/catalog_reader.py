import os
from typing import Dict, List

from ...constants import ENGINE_SQL_DIALECTS, KNOWN_ENGINES, SQL_DIR
from ..models.catalog import CatalogEnginesResponse, CatalogSuitesResponse, EngineInfo, SuiteDetail
from . import taxonomy


def _dialect_of(engine: str) -> str:
    """Which on-disk SQL dialect directory this engine reads from.
    Quack variants (`quack`, `quack_pushdown`, `quack_adbc`, `quack_arrow`)
    all share the DuckDB SQL dialect. Anything not in the mapping uses its
    own name (duckdb, postgres, actian, typedb)."""
    return ENGINE_SQL_DIALECTS.get(engine, engine)


class CatalogReader:
    """Reads SQL catalog from the filesystem.

    Distinguishes engines (`quack`, `quack_pushdown`, `duckdb`, …) from
    SQL dialects (the directory the engine actually reads SQL from).
    Quack variants ship as separate engines but read DuckDB SQL — so both
    endpoints must expand dialect-shared SQL to the full engine set."""

    def _suite_names(self) -> List[str]:
        if not os.path.isdir(SQL_DIR):
            return []
        return [
            d for d in os.listdir(SQL_DIR)
            if os.path.isdir(os.path.join(SQL_DIR, d))
        ]

    def _dialect_sql(self, suite_name: str) -> Dict[str, Dict[str, str]]:
        """Load SQL keyed by DIALECT (not engine). Multiple engines may share
        a dialect — the caller decides how to expand back to engines."""
        suite_dir = os.path.join(SQL_DIR, suite_name)
        dialect_sql: Dict[str, Dict[str, str]] = {}
        if not os.path.isdir(suite_dir):
            return dialect_sql
        for dialect in os.listdir(suite_dir):
            dialect_dir = os.path.join(suite_dir, dialect)
            if not os.path.isdir(dialect_dir):
                continue
            sql_files = [f for f in os.listdir(dialect_dir) if f.endswith(".sql")]
            if not sql_files:
                continue
            dialect_sql[dialect] = {}
            for fname in sql_files:
                name = os.path.splitext(fname)[0]
                with open(os.path.join(dialect_dir, fname)) as f:
                    dialect_sql[dialect][name] = f.read()
        return dialect_sql

    def _suite_detail(self, suite_name: str, include_sql: bool = False) -> SuiteDetail:
        dialect_sql = self._dialect_sql(suite_name)

        # Expand dialect-keyed SQL back to engine-keyed SQL. Any engine
        # whose dialect is present in this suite gets a copy of the
        # dialect's SQL under its own name — so `sql_content["quack"]`
        # returns the same DuckDB SQL as `sql_content["duckdb"]` when
        # both engines exist.
        engines_present = set()
        sql_content: Dict[str, Dict[str, str]] = {}
        for engine in KNOWN_ENGINES:
            dialect = _dialect_of(engine)
            if dialect in dialect_sql:
                engines_present.add(engine)
                sql_content[engine] = dialect_sql[dialect]

        benchmark_names = sorted({
            name
            for engine_files in sql_content.values()
            for name in engine_files
        })

        return SuiteDetail(
            name=suite_name,
            engines=sorted(engines_present),
            benchmark_names=benchmark_names,
            categories=taxonomy.suite_categories(suite_name),
            # Drop the SQL from the default payload — that's the 88 KB
            # bloat that made turn 1 of an agent run expensive. Callers
            # who need the SQL pass `include_sql=True`.
            sql_content=sql_content if include_sql else {},
        )

    def get_suites_response(self, include_sql: bool = False,
                            category: str | None = None) -> CatalogSuitesResponse:
        names = self._suite_names()
        if category:
            allowed = set(taxonomy.suites_in_category(category))
            names = [n for n in names if n in allowed]
        suites = [self._suite_detail(s, include_sql=include_sql) for s in names]
        return CatalogSuitesResponse(suites=suites)

    def get_engines_response(self) -> CatalogEnginesResponse:
        """List every KNOWN_ENGINES entry that has at least one suite
        available under its DIALECT directory. Quack variants share the
        DuckDB dialect, so they inherit DuckDB's suite list."""
        suite_names = self._suite_names()
        engine_suites: Dict[str, List[str]] = {e: [] for e in KNOWN_ENGINES}

        for suite_name in suite_names:
            suite_dir = os.path.join(SQL_DIR, suite_name)
            for engine in KNOWN_ENGINES:
                dialect_dir = os.path.join(suite_dir, _dialect_of(engine))
                if os.path.isdir(dialect_dir) and any(
                    f.endswith(".sql") for f in os.listdir(dialect_dir)
                ):
                    engine_suites[engine].append(suite_name)

        engines = [
            EngineInfo(name=e, available_suites=sorted(suites))
            for e, suites in engine_suites.items()
            if suites
        ]
        return CatalogEnginesResponse(engines=engines)
