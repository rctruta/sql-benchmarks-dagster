import os
import polars as pl
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def

# STRICT IMPORTS
from ..constants import DATA_DIR
from ..utils.common import load_context

# 1. LOAD CONTEXT
try:
    CTX = load_context()
    ACTIVE_ENGINES = CTX['engines']
    TARGET_TABLES = CTX['tables']
    TABLE_DEFS = CTX['table_defs'] # <--- We need the full definitions now
except Exception:
    ACTIVE_ENGINES = []
    TARGET_TABLES = []
    TABLE_DEFS = {}

def get_parquet_path(partition_key, table_name):
    return os.path.join(DATA_DIR, "staging", f"{table_name}_{partition_key}.parquet")

def make_ingestion_asset(table_name, engine, upstream_asset_key):
    prefix = "pg_" if engine == "postgres" else f"{engine}_"
    asset_name = f"{prefix}{table_name}_table"
    group_name = f"{engine}_ingestion"

    deps = [f"{table_name}_parquet"]
    if upstream_asset_key:
        deps.append(upstream_asset_key)

    @asset(
        name=asset_name,
        partitions_def=partitions_def,
        group_name=group_name,
        deps=deps,
        tags={"layer": "storage", "engine": engine},
        required_resource_keys={engine}
    )
    def _ingest_asset(context: AssetExecutionContext):
        partition_key = context.partition_key
        file_path = get_parquet_path(partition_key, table_name)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing Source Data: {file_path}")

        db_resource = getattr(context.resources, engine)
        target_table = f"{table_name}_{partition_key}"

        # 1. LOAD DATA
        if engine == "postgres":
            context.log.info(f"Loading {table_name} into Postgres...")
            df = pl.read_parquet(file_path)
            # Standard load (creates Heap table)
            df.write_database(
                table_name=target_table, 
                connection=db_resource.connection_string, 
                if_table_exists="replace", 
                engine="sqlalchemy"
            )
            
            # 2. APPLY CONSTRAINTS (Postgres Only)
            _apply_postgres_constraints(context, db_resource, table_name, target_table)

        elif engine == "duckdb":
            context.log.info(f"Loading {table_name} into DuckDB...")
            query = f"CREATE OR REPLACE TABLE {target_table} AS SELECT * FROM read_parquet('{file_path}');"
            db_resource.execute_query(query, partition_key=partition_key)

    def _apply_postgres_constraints(context, db, config_name, physical_name):
        """
        Dynamically applies PKs and Indexes defined in the YAML contract.
        """
        t_def = TABLE_DEFS.get(config_name, {})
        columns = t_def.get('columns', [])
        
        # A. Primary Keys
        pk_cols = [c['name'] for c in columns if c.get('primary_key') is True]
        if pk_cols:
            pk_str = ", ".join(pk_cols)
            # We use ALTER TABLE to add the constraint after loading
            sql = f"ALTER TABLE {physical_name} ADD PRIMARY KEY ({pk_str});"
            context.log.info(f"Applying PK: {sql}")
            db.execute_query(sql)

        # B. Indexes
        indexes = t_def.get('indexes', [])
        for idx in indexes:
            cols = idx.get('columns', [])
            idx_name = idx.get('name', f"idx_{physical_name}_{'_'.join(cols)}")
            
            if cols:
                col_str = ", ".join(cols)
                sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {physical_name} ({col_str});"
                context.log.info(f"Applying Index: {sql}")
                db.execute_query(sql)

    _ingest_asset.__name__ = f"ingest_{engine}_{table_name}"
    return _ingest_asset


# --- MAIN FACTORY LOOP ---
ingestion_assets = []

if ACTIVE_ENGINES:
    for engine in ACTIVE_ENGINES:
        previous_asset_key = None
        
        for table in TARGET_TABLES:
            # DuckDB Daisy Chain
            upstream_key = previous_asset_key if engine == "duckdb" else None
            
            new_asset = make_ingestion_asset(table, engine, upstream_key)
            ingestion_assets.append(new_asset)
            
            previous_asset_key = new_asset.key.path[-1]