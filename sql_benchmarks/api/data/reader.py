import glob
import json
import os
from typing import Any, Dict, List, Optional

import yaml

from ...constants import CONFIG_ARCHIVE_DIR, EXPERIMENTS_DIR, RESULTS_DIR
from ..models.results import (
    ExperimentSummary,
    Fragment,
    FragmentMeta,
    FragmentMetrics,
)


class ResultReader:
    """Reads benchmark results from the filesystem. Stateless — reads on every call."""

    def list_experiment_ids(self) -> List[str]:
        if not os.path.isdir(RESULTS_DIR):
            return []
        return [
            d for d in os.listdir(RESULTS_DIR)
            if os.path.isdir(os.path.join(RESULTS_DIR, d))
        ]

    def get_metadata(self, exp_id: str) -> Optional[Dict]:
        path = os.path.join(RESULTS_DIR, exp_id, f"metadata_{exp_id}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def get_config(self, exp_id: str) -> Optional[Dict]:
        path = os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_id}.yaml")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return yaml.safe_load(f)

    def get_fragments(self, exp_id: str) -> List[Fragment]:
        pattern = os.path.join(RESULTS_DIR, exp_id, "fragments", "*.json")
        fragments = []
        for fpath in glob.glob(pattern):
            try:
                with open(fpath) as f:
                    data = json.load(f)
                if data.get("meta", {}).get("experiment_id") != exp_id:
                    continue
                meta = data.get("meta", {})
                # Extract partition from filename: asset__PARTITION.json
                filename = os.path.splitext(os.path.basename(fpath))[0]
                partition = filename.split("__")[-1] if "__" in filename else "default"
                fragments.append(Fragment(
                    meta=FragmentMeta(
                        timestamp=meta.get("timestamp", ""),
                        experiment_id=meta.get("experiment_id", exp_id),
                        dagster_run_id=meta.get("dagster_run_id", ""),
                        engine=meta.get("engine", "unknown"),
                        asset=meta.get("asset", ""),
                        partition=partition,
                    ),
                    metrics=FragmentMetrics(
                        duration_seconds=float(data.get("metrics", {}).get("duration_seconds", 0.0)),
                        replication_factor=int(data.get("metrics", {}).get("replication_factor", 1)),
                        durations_raw=data.get("metrics", {}).get("durations_raw"),
                    ),
                    parameters=data.get("parameters", {}),
                ))
            except Exception:
                continue
        return fragments

    def has_csv(self, exp_id: str) -> bool:
        return os.path.exists(os.path.join(RESULTS_DIR, exp_id, f"{exp_id}.csv"))

    def has_dashboard(self, exp_id: str) -> bool:
        return os.path.exists(os.path.join(RESULTS_DIR, exp_id, f"{exp_id}.html"))

    def build_summary(self, exp_id: str) -> ExperimentSummary:
        fragments = self.get_fragments(exp_id)
        config = self.get_config(exp_id)
        metadata = self.get_metadata(exp_id)

        engines = list({f.meta.engine for f in fragments})
        partitions = list({f.meta.partition for f in fragments})
        suite = None
        if config:
            suite = config.get("execution", {}).get("test_suite")

        return ExperimentSummary(
            experiment_id=exp_id,
            suite=suite,
            engines=engines,
            partition_count=len(partitions),
            fragment_count=len(fragments),
            has_csv=self.has_csv(exp_id),
            has_dashboard=self.has_dashboard(exp_id),
            created_at=metadata.get("timestamp") if metadata else None,
        )

    def filter_experiments(
        self,
        suite: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> List[ExperimentSummary]:
        summaries = []
        for exp_id in self.list_experiment_ids():
            summary = self.build_summary(exp_id)
            if suite and summary.suite != suite:
                continue
            if engine and engine not in summary.engines:
                continue
            summaries.append(summary)
        return summaries

    def is_queued(self, exp_id: str) -> bool:
        return os.path.exists(os.path.join(EXPERIMENTS_DIR, "queue", f"{exp_id}.yaml"))

    def is_complete(self, exp_id: str) -> bool:
        return os.path.exists(os.path.join(CONFIG_ARCHIVE_DIR, f"config_{exp_id}.yaml"))

    def results_exist(self, exp_id: str) -> bool:
        return os.path.isdir(os.path.join(RESULTS_DIR, exp_id))
