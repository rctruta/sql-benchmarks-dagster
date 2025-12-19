import os
import polars as pl
import pandas as pd
import plotly.express as px
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult, DagsterEventType, EventRecordsFilter

from ..constants import RESULTS_DIR
from ..utils.common import load_context
from .benchmark_factory import benchmark_assets
import glob
import json

all_benchmark_keys = [k.key for k in benchmark_assets]

# ==========================================
# 1. PURE LOGIC (Testable)
# ==========================================
def parse_fragments_to_records(experiment_id):
    """
    Scans the results directory for the given experiment_id
    and parses all fragment JSONs into a flat list of records.
    """
    fragments_pattern = os.path.join(RESULTS_DIR, experiment_id, "fragments", "*.json")
    fragment_files = glob.glob(fragments_pattern)
    
    records = []
    
    for fpath in fragment_files:
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            
            meta = data.get("meta", {})
            metrics = data.get("metrics", {})
            params = data.get("parameters", {})
            
            # Check ID consistency (optional but good sanity check)
            if meta.get("experiment_id") != experiment_id:
                continue

            asset_name = meta.get("asset", "unknown_asset")
            row = {
                "Asset": asset_name,
                "Duration": float(metrics.get("duration_seconds", 0.0)),
                "Engine": str(meta.get("engine", "Unknown")),
                "Rows": int(params.get("rows", 0)), # Assuming 'rows' is in params
                "Selectivity": float(params.get("derived_selectivity", 0.0) or 0.0), # Assuming this might be explicitly passed or derived
                "System": str(meta.get("engine"))
            }

            # Handle Dimensions broadly if needed, but for now stick to the plan:
            if "disk_type" in params:
                 row["System"] += f" ({params['disk_type']})"

            records.append(row)
            
        except Exception as e:
            print(f"Skipping malformed fragment {fpath}: {e}")
            continue
            
    return records

# ==========================================
# 2. THE ASSET (Orchestration)
# ==========================================
@asset(
    deps=all_benchmark_keys,
    group_name="reporting",
    description="Generates a Multi-View Dashboard."
)
def performance_dashboard(context: AssetExecutionContext):
    instance = context.instance
    try:
        CTX = load_context()
        EXP_ID = CTX['meta'].get("experiment_id", "unknown")
    except Exception:
        context.log.warning("Could not read active context.")
        return

    # 1. FETCH & PARSE (New Logic)
    records = parse_fragments_to_records(EXP_ID)

    if not records:
        context.log.info(f"No records found for experiment: {EXP_ID}")
        return

    # 3. PREPARE DATA
    df = pl.DataFrame(records)
    df = df.unique(subset=["Asset", "System", "Rows"], keep="last").sort("Rows")
    pldf = df.to_pandas()

    # 4. RENDER (Visualization)
    figures_html = []
    unique_assets = sorted(pldf["Asset"].unique())
    
    for asset_name in unique_assets:
        subset = pldf[pldf["Asset"] == asset_name]
        fig = px.line(
            subset, x="Rows", y="Duration", color="System", markers=True, 
            log_x=True, title=f"Scaling: {asset_name}", symbol="System"
        )
        figures_html.append(fig.to_html(full_html=False, include_plotlyjs='cdn'))

    # 5. SAVE (Side Effect)
    exp_folder = os.path.join(RESULTS_DIR, EXP_ID)
    os.makedirs(exp_folder, exist_ok=True)
    html_path = os.path.join(exp_folder, f"dashboard_{EXP_ID}.html")
    
    with open(html_path, "w") as f:

        f.write(f"<h1>Benchmark: {EXP_ID}</h1><hr>")
        f.write("<br>".join(figures_html))

    # 6. WRITE CSV (Legacy Support / Unified Output)
    # Replaces the partial logic in extract_results.py
    csv_path = os.path.join(exp_folder, f"results_{EXP_ID}.csv")
    df.write_csv(csv_path)
    
    return MaterializeResult(
        metadata={
            "dashboard_path": MetadataValue.path(html_path),
            "results_csv_path": MetadataValue.path(csv_path),
            "experiment_id": EXP_ID 
        })