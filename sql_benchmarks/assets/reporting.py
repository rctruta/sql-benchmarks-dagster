import os
import polars as pl
import plotly.express as px
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult, DagsterEventType, EventRecordsFilter

# STRICT IMPORTS
from ..constants import RESULTS_DIR
from ..utils.common import load_context
from .benchmark_factory import benchmark_assets

all_benchmark_keys = [k.key for k in benchmark_assets]

@asset(
    deps=all_benchmark_keys,
    group_name="reporting",
    description="Generates an HTML report comparing Engine performance across ALL partitions."
)
def performance_dashboard(context: AssetExecutionContext):
    instance = context.instance
    
    try:
        CTX = load_context()
        EXP_ID = CTX['meta'].get("experiment_id", "unknown")
    except Exception:
        context.log.warning("Could not read active context. Skipping report.")
        return

    records = []
    
    # 3. SCAN HISTORY
    for key in all_benchmark_keys:
        events = instance.get_event_records(
            EventRecordsFilter(
                event_type=DagsterEventType.ASSET_MATERIALIZATION,
                asset_key=key
            ),
            limit=20
        )
        
        for record in events:
            meta = record.event_log_entry.dagster_event.step_materialization_data.materialization.metadata
            
            stored_id = meta.get("experiment_id")
            stored_id_val = stored_id.value if hasattr(stored_id, 'value') else stored_id
            
            if stored_id_val != EXP_ID:
                continue
            
            def get_val(k, default=None):
                v = meta.get(k)
                if v is None: return default
                return v.value if hasattr(v, 'value') else v

        records.append({
            "Asset": str(key.path[-1]),
            "Engine": str(get_val("config_engine", "Unknown")),
            # Force 64-bit precision
            "Duration (Mean)": float(get_val("duration_seconds", 0.0)),
            "Duration (Median)": float(get_val("duration_median", 0.0)),
            "StDev": float(get_val("duration_stdev", 0.0)),
            "Iterations": int(get_val("iterations", 1)),
            "Rows": int(get_val("trace_rows", 0)),
            "Orphans": float(get_val("trace_orphans", 0.0)),
            "Strategy": "Antipattern" if "antipattern" in key.path[-1] else "Recommended"
        })

    if not records:
        context.log.info(f"No matching records found for Experiment {EXP_ID}.")
        return

    # 4. PROCESS DATA
    # Force Polars to respect precision
    df = pl.DataFrame(records, schema={
        "Asset": pl.Utf8,
        "Engine": pl.Utf8,
        "Duration (Mean)": pl.Float64,
        "Duration (Median)": pl.Float64, 
        "StDev": pl.Float64,
        "Iterations": pl.Int64, 
        "Rows": pl.Int64,
        "Orphans": pl.Float64,
        "Strategy": pl.Utf8
    })
    # Deduplicate
    df = df.unique(subset=["Asset", "Engine", "Rows", "Orphans"], keep="last")

    # Save CSV
    exp_folder = os.path.join(RESULTS_DIR, EXP_ID)
    os.makedirs(exp_folder, exist_ok=True)
    csv_path = os.path.join(exp_folder, f"results_{EXP_ID}.csv")
    df.write_csv(csv_path)

    # 5. GENERATE CHART (VISUAL FIX)
    pldf = df.to_pandas()
    pldf = pldf.sort_values(by=["Engine", "Strategy", "Orphans"])

    fig = px.bar(
        pldf,
        x="Strategy",
        y="Duration (Mean)",
        error_y="StDev",
        color="Engine",
        barmode="group",
        facet_col="Rows", 
        facet_row="Orphans",
        title=f"Benchmark: {EXP_ID} (N={pldf['Iterations'].iloc[0]})",
        text_auto='.3s',
        hover_data=["Duration (Median)", "Asset"]
    )
    
    # --- THE FIX: Put numbers inside bars ---
    fig.update_traces(textposition='inside', textfont_color='white')
    
    fig.update_layout(
        margin=dict(t=60, b=0, l=0, r=0),
        yaxis_title="Time (s) [Lower is Better]"
    )

    html_path = os.path.join(exp_folder, f"dashboard_{EXP_ID}.html")
    fig.write_html(html_path)
    
    return MaterializeResult(
        metadata={
            "dashboard_path": MetadataValue.path(html_path),
            "csv_path": MetadataValue.path(csv_path),
            "record_count": MetadataValue.int(len(df))
        }
    )