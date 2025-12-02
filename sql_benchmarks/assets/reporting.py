import polars as pl
# import pandas as pd
import plotly.express as px
import os
import yaml
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult

# FIX: Import from the new Universal Factory
from .benchmark_factory import benchmark_assets

# Combine dependencies (It's just one list now!)
all_benchmark_assets = [k.key for k in benchmark_assets]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_ROOT = os.path.join(PROJECT_ROOT, "sql_benchmarks", "results")

@asset(
    deps=all_benchmark_assets,
    group_name="reporting",
    description="Generates an interactive Plotly dashboard for the active experiment."
)
def performance_dashboard(context: AssetExecutionContext):
    instance = context.instance
    records = []
    
    # 1. READ ACTIVE CONFIG
    config_path = os.path.join(PROJECT_ROOT, "sql_benchmarks", "experiments", "active.yaml")
    
    # Robust Config Reading
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        exp_id = config.get("meta", {}).get("experiment_id", "unknown_id")
    except Exception:
        context.log.warning("Could not read active.yaml")
        return

    # 2. GATHER DATA
    for key in all_benchmark_assets:
        event = instance.get_latest_materialization_event(key)
        if not event: continue
        
        meta = event.dagster_event.step_materialization_data.materialization.metadata
        
        # Filter by Experiment ID
        run_id = meta.get("experiment_id")
        # Handle wrapped value or raw string
        run_id_val = run_id.value if hasattr(run_id, 'value') else run_id
        
        if run_id_val != exp_id:
            continue
        
        if "duration_seconds" in meta:
            records.append({
                "Asset": key.path[-1],
                "Duration (s)": meta["duration_seconds"].value,
                "Orphans": meta.get("trace_orphans", {}).value if "trace_orphans" in meta else 0,
                "Rows": meta.get("trace_rows", {}).value if "trace_rows" in meta else 0,
                "Engine": meta.get("config_engine", {}).value if "config_engine" in meta else "Unknown",
                "Strategy": "Antipattern" if "antipattern" in key.path[-1] else "Recommended"
            })

    if not records:
        context.log.info(f"No data found for Experiment {exp_id}.")
        return

    df = pl.DataFrame(records)
    pldf = df.to_pandas()

    # 3. PLOTLY CHART
    fig = px.bar(
        pldf, 
        x="Strategy", 
        y="Duration (s)", 
        color="Engine", 
        barmode="group",
        facet_col="Rows", 
        title=f"Benchmark Results: {exp_id}",
        text_auto='.3s',
        hover_data=["Orphans", "Asset"]
    )
    fig.update_layout(margin=dict(t=50, b=0, l=0, r=0))

    # 4. SAVE
    exp_folder = os.path.join(RESULTS_ROOT, exp_id)
    os.makedirs(exp_folder, exist_ok=True)
    
    html_path = os.path.join(exp_folder, f"dashboard_{exp_id}.html")
    csv_path = os.path.join(exp_folder, f"data_{exp_id}.csv")
    
    fig.write_html(html_path)
    pldf.to_csv(csv_path, index=False)
    
    context.log.info(f"Dashboard saved to: {html_path}")
    
    return MaterializeResult(
        metadata={
            "dashboard_path": MetadataValue.path(html_path),
            "csv_path": MetadataValue.path(csv_path)
        }
    )