import os
from typing import Dict, List

from ...constants import KNOWN_ENGINES, SQL_DIR
from ..models.catalog import CatalogEnginesResponse, CatalogSuitesResponse, EngineInfo, SuiteDetail


class CatalogReader:
    """Reads SQL catalog from the filesystem."""

    def _suite_names(self) -> List[str]:
        if not os.path.isdir(SQL_DIR):
            return []
        return [
            d for d in os.listdir(SQL_DIR)
            if os.path.isdir(os.path.join(SQL_DIR, d))
        ]

    def _suite_detail(self, suite_name: str) -> SuiteDetail:
        suite_dir = os.path.join(SQL_DIR, suite_name)
        sql_content: Dict[str, Dict[str, str]] = {}
        engines_present = []

        for engine in os.listdir(suite_dir):
            engine_dir = os.path.join(suite_dir, engine)
            if not os.path.isdir(engine_dir):
                continue
            sql_files = [f for f in os.listdir(engine_dir) if f.endswith(".sql")]
            if not sql_files:
                continue
            engines_present.append(engine)
            sql_content[engine] = {}
            for fname in sql_files:
                name = os.path.splitext(fname)[0]
                with open(os.path.join(engine_dir, fname)) as f:
                    sql_content[engine][name] = f.read()

        benchmark_names = sorted({
            name
            for engine_files in sql_content.values()
            for name in engine_files
        })

        return SuiteDetail(
            name=suite_name,
            engines=sorted(engines_present),
            benchmark_names=benchmark_names,
            sql_content=sql_content,
        )

    def get_suites_response(self) -> CatalogSuitesResponse:
        suites = [self._suite_detail(s) for s in self._suite_names()]
        return CatalogSuitesResponse(suites=suites)

    def get_engines_response(self) -> CatalogEnginesResponse:
        suite_names = self._suite_names()
        engine_suites: Dict[str, List[str]] = {e: [] for e in KNOWN_ENGINES}

        for suite_name in suite_names:
            suite_dir = os.path.join(SQL_DIR, suite_name)
            for engine in KNOWN_ENGINES:
                engine_dir = os.path.join(suite_dir, engine)
                if os.path.isdir(engine_dir) and any(
                    f.endswith(".sql") for f in os.listdir(engine_dir)
                ):
                    engine_suites[engine].append(suite_name)

        engines = [
            EngineInfo(name=e, available_suites=sorted(suites))
            for e, suites in engine_suites.items()
            if suites
        ]
        return CatalogEnginesResponse(engines=engines)
