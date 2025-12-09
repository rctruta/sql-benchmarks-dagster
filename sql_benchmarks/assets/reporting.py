import os
import polars as pl
import pandas as pd
import plotly.express as px
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult, DagsterEventType, EventRecordsFilter

from ..constants import RESULTS_DIR
from ..utils.common import load_context
from .benchmark_factory import benchmark_assets

all_benchmark_keys = [k.key for k in benchmark_assets]

# ==========================================
# 1. PURE LOGIC (Testable)
# ==========================================
def parse_events_to_records(events, active_exp_id):
    """
    Pure function: Transforms raw Dagster events into a list of dictionaries.
    Decoupled from the Asset Context for unit testing.
    """
    records = []
    
    for record in events:
        # 1. Extract Metadata Safe-ly
        # Note: Depending on how the event was fetched, structure might vary.
        # This assumes standard Dagster EventLogEntry structure.
        try:
            mat = record.event_log_entry.dagster_event.step_materialization_data.materialization
            meta = mat.metadata
        except AttributeError:
            continue # Skip malformed records

        def get_val(k, default=None):
            v = meta.get(k)
            if v is None: return default
            return v.value if hasattr(v, 'value') else v

        # 2. Filter by Experiment ID
        stored_id = get_val("experiment_id")
        if stored_id != active_exp_id: 
            continue
        
        # 3. Build Record
        # We rely on the AssetKey path for the name
        asset_name = record.asset_key.path[-1]
        
        row = {
            "Asset": asset_name,
            "Duration": float(get_val("duration_seconds", 0.0)),
            "Engine": str(get_val("config_engine", "Unknown")),
            "Rows": int(get_val("dim_rows", 0)),
            "Selectivity": float(get_val("derived_selectivity", 0.0)),
            "System": str(get_val("config_engine"))
        }
        
        # Optional: Add Disk Type if present
        if get_val("dim_disk_type"):
            row["System"] += f" ({get_val('dim_disk_type')})"
            
        records.append(row)
        
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

    # 1. FETCH (Side Effect)
    raw_events = []
    for key in all_benchmark_keys:
        events = instance.get_event_records(
            EventRecordsFilter(event_type=DagsterEventType.ASSET_MATERIALIZATION, asset_key=key),
            limit=50
        )
        raw_events.extend(events)

    # 2. PARSE (Logic)
    records = parse_events_to_records(raw_events, EXP_ID)

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
    
    return MaterializeResult(metadata={"dashboard_path": MetadataValue.path(html_path)})