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
            
            if meta.get("experiment_id") != experiment_id:
                continue

            asset_name = meta.get("asset", "unknown_asset")
            
            # Extract Partition from Filename: asset_name__PARTITION.json
            filename = os.path.basename(fpath)
            partition_name = "default"
            
            # Logic: Split by asset_name + "__"
            # It's safer to use the known separator "__"
            if "__" in filename:
                # Remove extension
                name_no_ext = os.path.splitext(filename)[0]
                parts = name_no_ext.split("__")
                if len(parts) >= 2:
                    partition_name = parts[-1]
            
            row = {
                "Asset": asset_name,
                "Partition": partition_name,
                "Duration": float(metrics.get("duration_seconds", 0.0)),
                "Engine": str(meta.get("engine", "Unknown")),
                "System": str(meta.get("engine")),
                "Rows": int(params.get("rows", 0)) if "rows" in params else 0,
                "Selectivity": float(params.get("derived_selectivity", 0.0) or 0.0)
            }

            if "disk_type" in params:
                 row["System"] += f" ({params['disk_type']})"

            # Merge ALL parameters into the row (Dynamic Columns)
            # This ensures 'null_probability' etc appear in CSV
            for k, v in params.items():
                if k not in row:
                    row[k] = v

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
    
    # Deduplicate: Keep last run for same (Asset, Partition, Engine)
    # Rows might technically differ but Partition should cover it.
    unique_keys = ["Asset", "Partition", "System", "Rows"]
    # Filter keys that actually exist (to be safe if Partition is missing in legacy)
    unique_keys = [k for k in unique_keys if k in df.columns]
    
    df = df.unique(subset=unique_keys, keep="last").sort("Rows")
    pldf = df.to_pandas()

    # 4. RENDER (Visualization - Matrix Explorer)
    figures_html = []
    
    # Identify Matrix Parameters (Columns that are not "System", "Asset", "Duration", "Engine", "Partition")
    excluded_cols = {"Asset", "Partition", "Duration", "Engine", "System"}
    matrix_params = [c for c in pldf.columns if c not in excluded_cols and pd.api.types.is_numeric_dtype(pldf[c])]
    
    # 1. Comparison by System (The Basics)
    # -------------------------------------------------------------------------
    try:
        # Side-by-Side System Comparison (Fixed Rows Scaling)
        if "Rows" in matrix_params:
             fig_compare = px.line(
                pldf, 
                x="Rows", 
                y="Duration", 
                color="System", 
                line_dash="Asset", 
                symbol="System",
                facet_col="null_probability" if "null_probability" in matrix_params else None, 
                facet_col_wrap=2,
                log_x=True,
                log_y=True,
                markers=True,
                title="<b>Global Comparison</b>: System Scaling (Rows vs Duration)"
            )
             figures_html.append(fig_compare.to_html(full_html=False, include_plotlyjs='cdn'))
    except Exception as e:
         context.log.warning(f"Global Plot Error: {e}")

    # 2. Slice and Dice (The "User Logic")
    # -------------------------------------------------------------------------
    unique_systems = sorted(pldf["System"].unique())
    
    # For each Engine...
    for system in unique_systems:
        system_df = pldf[pldf["System"] == system]
        
        # For each Parameter we want to vary on X (e.g. Rows, NullProb)...
        for param_x in matrix_params:
            
            # Find the "Other" parameters to fix (Facet By)
            other_params = [p for p in matrix_params if p != param_x]
            
            # We can't facet by *all* other params if there are many, 
            # so we pick the primary "Other" one (e.g. if X=Rows, Other=NullProb).
            # If multiple, we might need a more complex strategy, but for now we take the first.
            facet_col = other_params[0] if other_params else None
            
            title = f"<b>{system}</b>: Varying <b>{param_x}</b>"
            if facet_col:
                title += f" (Facetted by {facet_col})"
            
            try:
                # Ensure we have data
                if system_df.empty: continue

                # Logic: X=Param, Y=Duration, Color=Asset (2VL vs 3VL)
                fig = px.line(
                    system_df,
                    x=param_x,
                    y="Duration",
                    color="Asset",
                    symbol="Asset",
                    facet_col=facet_col,
                    facet_col_wrap=3,
                    markers=True,
                    log_y=True, # Duration is exponential
                    log_x=True if param_x == "Rows" or param_x == "null_probability" else False,
                    title=title,
                    labels={param_x: param_x, "Duration": "Duration (s)"}
                )
                figures_html.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception as e:
                context.log.warning(f"Slice Plot Error ({system}, {param_x}): {e}")

    # 3. 3D Landscape (The "Bonus")
    # -------------------------------------------------------------------------
    if "null_probability" in matrix_params and "Rows" in matrix_params:
         try:
             fig_3d = px.scatter_3d(
                 pldf, 
                 x="Rows", 
                 y="null_probability", 
                 z="Duration", 
                 color="System",
                 symbol="Asset",
                 log_x=True,
                 log_z=True,
                 title="<b>3D Landscape</b>: Rows x Nulls x Duration",
                 height=800
             )
             figures_html.append(fig_3d.to_html(full_html=False, include_plotlyjs=False))
         except Exception as e:
             # Just skip if 3D fails
             pass

    # 5. SAVE (Side Effect)
    exp_folder = os.path.join(RESULTS_DIR, EXP_ID)
    os.makedirs(exp_folder, exist_ok=True)
    html_path = os.path.join(exp_folder, f"dashboard_{EXP_ID}.html")
    
    with open(html_path, "w") as f:
        f.write(f"<h1>Benchmark: {EXP_ID}</h1>")
        f.write(f"<p>Generated at: {pd.Timestamp.now()}</p><hr>")
        f.write("<br><hr><br>".join(figures_html))

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