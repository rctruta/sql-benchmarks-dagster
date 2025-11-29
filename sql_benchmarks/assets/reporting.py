import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
from dagster import asset, AssetExecutionContext
from .duckdb_factory import benchmark_assets as duck_bench
from .postgres_factory import postgres_bench_assets as pg_bench

# Combine dependencies
all_benchmark_assets = [k.key for k in duck_bench + pg_bench]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_PATH = os.path.join(PROJECT_ROOT, "data", "benchmark_report.png")

@asset(
    deps=all_benchmark_assets,
    group_name="reporting",
    description="Generates a performance comparison chart."
)
def performance_chart(context: AssetExecutionContext):
    instance = context.instance
    records = []
    
    for key in all_benchmark_assets:
        event = instance.get_latest_materialization_event(key)
        if not event: continue
        meta = event.dagster_event.step_materialization_data.materialization.metadata
        
        if "duration_seconds" in meta and "trace_orphans" in meta:
            records.append({
                "asset": key.path[-1],
                "duration": meta["duration_seconds"].value,
                "orphans": meta["trace_orphans"].value,
                "engine": meta.get("config_engine", {}).value if "config_engine" in meta else "unknown",
                "Strategy": "Antipattern" if "antipattern" in key.path[-1] else "Recommended"
            })

    if not records:
        return

    df = pd.DataFrame(records)

    # VISUAL UPGRADE
    sns.set_theme(style="whitegrid", context="talk") # "talk" makes fonts larger/clearer
    plt.figure(figsize=(12, 8))
    
    # Create Bar Chart
    chart = sns.barplot(
        data=df,
        x="orphans",
        y="duration",
        hue="Strategy",
        palette={"Antipattern": "#e74c3c", "Recommended": "#2ecc71"}, # Red/Green logic
        edgecolor=".2" # Add borders to bars
    )
    
    # Add Values on top of bars (The "Professional" Touch)
    for container in chart.containers:
        chart.bar_label(container, fmt='%.2fs', padding=3, fontsize=10)

    plt.title("Impact of Orphan Records on Query Latency", fontsize=20, pad=20)
    plt.xlabel("Orphan Percentage", fontsize=14)
    plt.ylabel("Execution Time (Seconds)", fontsize=14)
    plt.legend(title="SQL Strategy", bbox_to_anchor=(1.05, 1), loc='upper left')
    
    plt.tight_layout()
    plt.savefig(REPORT_PATH, dpi=300) # High Res
    
    context.log.info(f"Report saved to {REPORT_PATH}")
    return REPORT_PATH