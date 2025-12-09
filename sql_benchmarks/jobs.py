from dagster import define_asset_job, AssetSelection

# Defines a job that selects ALL assets (Ingestion -> Benchmarks)
# This is what the Sensor triggers when it sees a new YAML file.
benchmark_job = define_asset_job(
    name="benchmark_job",
    selection=AssetSelection.all()
)