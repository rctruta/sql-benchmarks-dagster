import os
import polars as pl
import plotly.express as px
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult

# 1. STRICT IMPORTS
from ..constants import RESULTS_DIR
from ..utils.common import load_context
from .benchmark_factory import benchmark_assets

# Combine all benchmark keys so this asset waits for them to finish
all_benchmark_keys = [k.key for k in benchmark_assets]

@asset(
    deps=all_benchmark_keys,
    group_name="reporting",
    description="Generates an HTML report comparing Engine performance with Statistical Error Bars."
)
def performance_dashboard(context: AssetExecutionContext):
    instance = context.instance
    
    # 2. LOAD CONTEXT (Fail Fast)
    try:
        CTX = load_context()
        EXP_ID = CTX['meta'].get("experiment_id", "unknown")
    except Exception:
        context.log.warning("Could not read active context. Skipping report.")
        return

    records = []
    
    # 3. EXTRACT METADATA
    # We look specifically at the assets we just ran
    for key in all_benchmark_keys:
        event = instance.get_latest_materialization_event(key)
        if not event: continue
        
        meta = event.dagster_event.step_materialization_data.materialization.metadata
        
        # Verify Experiment ID matches current run
        stored_id = meta.get("experiment_id")
        stored_id_val = stored_id.value if hasattr(stored_id, 'value') else stored_id
        
        if stored_id_val != EXP_ID:
            continue
        
        # Helper to unwrap Dagster metadata values
        def get_val(k, default=None):
            v = meta.get(k)
            if v is None: return default
            return v.value if hasattr(v, 'value') else v

        records.append({
            "Asset": key.path[-1],
            "Engine": get_val("config_engine", "Unknown"),
            "Duration (Mean)": get_val("duration_seconds"),
            "Duration (Median)": get_val("duration_median"),
            "StDev": get_val("duration_stdev", 0.0), # <--- THE KEY METRIC
            "Iterations": get_val("iterations", 1),
            "Rows": get_val("trace_rows", 0),
            "Orphans": get_val("trace_orphans", 0.0),
            "Strategy": "Antipattern" if "antipattern" in key.path[-1] else "Recommended"
        })

    if not records:
        context.log.info(f"No matching records found for Experiment {EXP_ID}.")
        return

    # 4. PROCESS DATA
    df = pl.DataFrame(records)
    
    # Save Raw Data for audit
    exp_folder = os.path.join(RESULTS_DIR, EXP_ID)
    os.makedirs(exp_folder, exist_ok=True)
    
    csv_path = os.path.join(exp_folder, f"results_{EXP_ID}.csv")
    df.write_csv(csv_path)

    # 5. GENERATE CHART
    # We switch to Pandas for Plotly compatibility
    pldf = df.to_pandas()
    
    # Sort for cleaner charts
    pldf = pldf.sort_values(by=["Engine", "Strategy"])

    fig = px.bar(
        pldf,
        x="Strategy",
        y="Duration (Mean)",
        error_y="StDev",  # <--- VISUALIZES STABILITY
        color="Engine",
        barmode="group",
        facet_col="Rows", 
        title=f"Benchmark Results: {EXP_ID} (N={pldf['Iterations'].iloc[0]})",
        text_auto='.3s',
        hover_data=["Duration (Median)", "Orphans"]
    )
    
    fig.update_layout(
        margin=dict(t=60, b=0, l=0, r=0),
        yaxis_title="Time (s) [Lower is Better]"
    )

    html_path = os.path.join(exp_folder, f"dashboard_{EXP_ID}.html")
    fig.write_html(html_path)
    
    context.log.info(f"Dashboard generated: {html_path}")
    
    return MaterializeResult(
        metadata={
            "dashboard_path": MetadataValue.path(html_path),
            "csv_path": MetadataValue.path(csv_path),
            "record_count": MetadataValue.int(len(df))
        }
    )