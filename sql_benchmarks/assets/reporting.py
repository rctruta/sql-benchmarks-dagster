import os
import re
import polars as pl
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult, DagsterEventType, EventRecordsFilter

from ..constants import RESULTS_DIR
from ..utils.common import load_context
from .benchmark_factory import benchmark_assets

all_benchmark_keys = [k.key for k in benchmark_assets]

def parse_selectivity(asset_name):
    if "filler" in asset_name: return 64.0
    match = re.search(r"q_(\d+)_?(\d*)", asset_name)
    if match:
        whole = match.group(1)
        decimal = match.group(2)
        return float(f"{whole}.{decimal}") if decimal else float(whole)
    return 0.0

@asset(
    deps=all_benchmark_keys,
    group_name="reporting",
    description="Generates a Multi-View Dashboard (Per-Query Scaling + 3D)."
)
def performance_dashboard(context: AssetExecutionContext):
    instance = context.instance
    
    try:
        CTX = load_context()
        EXP_ID = CTX['meta'].get("experiment_id", "unknown")
    except Exception:
        context.log.warning("Could not read active context.")
        return

    records = []
    
    # 1. SCAN HISTORY
    for key in all_benchmark_keys:
        events = instance.get_event_records(
            EventRecordsFilter(event_type=DagsterEventType.ASSET_MATERIALIZATION, asset_key=key),
            limit=50
        )
        for record in events:
            meta = record.event_log_entry.dagster_event.step_materialization_data.materialization.metadata
            stored_id = meta.get("experiment_id")
            stored_id_val = stored_id.value if hasattr(stored_id, 'value') else stored_id
            
            if stored_id_val != EXP_ID: continue
            
            def get_val(k):
                v = meta.get(k)
                return v.value if hasattr(v, 'value') else v

            partition_key = record.event_log_entry.dagster_event.partition
            disk_type = partition_key.split("_")[-1] if partition_key and "_" in partition_key else "default"
            asset_name = key.path[-1]
            
            records.append({
                "Asset": asset_name,
                "Selectivity": parse_selectivity(asset_name),
                "Duration": float(get_val("duration_seconds") or 0.0),
                "Engine": str(get_val("config_engine") or "Unknown"),
                "Rows": int(get_val("trace_rows") or 0),
                "Disk": disk_type,
                "System": f"{str(get_val('config_engine'))} ({disk_type})" # Composite Key
            })

    if not records:
        context.log.info(f"No records for {EXP_ID}")
        return

    # 2. PREPARE DATA
    df = pl.DataFrame(records)
    # Deduplicate and Sort
    df = df.unique(subset=["Asset", "System", "Rows"], keep="last").sort("Rows")
    pldf = df.to_pandas()

    figures_html = []

    # --- VIEW 1: PER-QUERY SCALING (The "Small Multiples" Strategy) ---
    # We create one graph for each Query (Selectivity Level)
    # This isolates the "Selectivity" variable so lines don't cross confusingly.
    unique_assets = sorted(pldf["Asset"].unique(), key=lambda x: parse_selectivity(x))
    
    for asset_name in unique_assets:
        subset = pldf[pldf["Asset"] == asset_name]
        selectivity = subset["Selectivity"].iloc[0]
        
        fig = px.line(
            subset,
            x="Rows",
            y="Duration",
            color="System",
            markers=True,
            log_x=True, # Log scale for Rows (100k -> 10M)
            title=f"Scaling at {selectivity}% Selectivity ({asset_name})",
            symbol="System"
        )
        fig.update_layout(yaxis_title="Duration (s)", height=400)
        figures_html.append(fig.to_html(full_html=False, include_plotlyjs='cdn'))

    # --- VIEW 2: 3D LANDSCAPE (The "Nerdy" View) ---
    # Shows the entire performance surface
    fig_3d = px.scatter_3d(
        pldf,
        x="Selectivity",
        y="Rows",
        z="Duration",
        color="System",
        symbol="System",
        log_y=True, # Log scale for Rows
        title="3D Performance Landscape: Rows x Selectivity x Time",
        height=800
    )
    # Draw lines connecting the dots for better 3D visibility
    """
    for system in pldf["System"].unique():
        sys_data = pldf[pldf["System"] == system].sort_values(["Rows", "Selectivity"])
        fig_3d.add_trace(go.Scatter3d(
            x=sys_data["Selectivity"], y=sys_data["Rows"], z=sys_data["Duration"],
            mode='lines', name=system, line=dict(width=2), showlegend=False
        ))
    """
    figures_html.append(fig_3d.to_html(full_html=False, include_plotlyjs=False))

    # 3. REPORT
    exp_folder = os.path.join(RESULTS_DIR, EXP_ID)
    os.makedirs(exp_folder, exist_ok=True)
    html_path = os.path.join(exp_folder, f"dashboard_{EXP_ID}.html")
    
    with open(html_path, "w") as f:
        f.write(f"<h1>Benchmark: {EXP_ID}</h1><hr>")
        f.write("<br>".join(figures_html))
    
    return MaterializeResult(metadata={"dashboard_path": MetadataValue.path(html_path)})