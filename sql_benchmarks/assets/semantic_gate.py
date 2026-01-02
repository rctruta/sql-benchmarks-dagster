import os
import json
from dagster import asset, AssetExecutionContext, MaterializeResult, MetadataValue
from ..constants import RESULTS_DIR, VIOLATIONS_DIR
from ..partitions import partitions_def
from ..utils.common import load_context, get_scoped_asset_name
from ..utils.semantic_auditor import SemanticAuditor

CTX = load_context()
EXP_ID = CTX['meta'].get("experiment_id", "unknown")

def make_semantic_gate_asset(benchmark_asset_key):
    """
    Creates a SemanticGate asset that validates the results of a benchmark.
    """
    # The gate name should be semantic_gate_<benchmark_name>
    benchmark_name = benchmark_asset_key.path[-1]
    base_gate_name = f"semantic_gate_{benchmark_name.replace(f'e_{EXP_ID}__', '')}"
    asset_name = get_scoped_asset_name(base_gate_name, EXP_ID)
    
    @asset(
        name=asset_name,
        group_name="semantic_firewall",
        partitions_def=partitions_def,
        deps=[benchmark_asset_key],
        description=f"Audits benchmark results for {benchmark_name} for hallucinations."
    )
    def _gate(context: AssetExecutionContext):
        partition_key = context.partition_key
        
        # 1. Locate the fragment produced by the dependency
        # matches: benchmark_factory.py:30
        from ..utils.common import load_context
        ctx = load_context()
        fragment_path = os.path.join(
            RESULTS_DIR, 
            "fragments",
            f"{benchmark_name}__{partition_key}.json"
        )
        
        if not os.path.exists(fragment_path):
            context.log.warning(f"Fragment not found for audit: {fragment_path}")
            return MaterializeResult(metadata={"status": "missing_fragment"})

        # 2. Audit
        with open(fragment_path, "r") as f:
            data = json.load(f)
            
        auditor = SemanticAuditor()
        report = auditor.audit_fragment(data)
        
        # 3. Handle Violations
        if not report["success"]:
            context.log.error(f"SEMANTIC HALLUCINATION DETECTED: {report['violations']}")
            # In a real system, we might raise an error or mark it with a high-severity tag.
            # For this PoC, we add metadata.
            metadata = {
                "audit_status": "FAILED",
                "violations": MetadataValue.json(report["violations"]),
                "fragment_path": MetadataValue.path(fragment_path)
            }
        else:
            metadata = {
                "audit_status": "PASSED",
                "fragment_path": MetadataValue.path(fragment_path)
            }
            
        return MaterializeResult(metadata=metadata)

    return _gate

def get_semantic_gate_assets(benchmark_assets):
    """
    Generates gate assets based on a list of benchmark assets.
    """
    return [make_semantic_gate_asset(b.key) for b in benchmark_assets]
