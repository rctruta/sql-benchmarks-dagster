import os
from dagster import asset, AssetExecutionContext
from ..partitions import partitions_def
from ..constants import DATA_DIR
from ..utils.common import load_context 
from ..utils.ddl import PostgresDDLGenerator

CTX = load_context()
ACTIVE_ENGINES = CTX['engines']
TABLE_DEFS = CTX['table_defs']

def make_ingestion_asset(table, engine, upstream):
    prefix = "pg_" if engine == "postgres" else f"{engine}_"
    name = f"{prefix}{table}_table"
    deps = [f"{table}_parquet"] + ([upstream] if upstream else [])

    @asset(
        name=name, partitions_def=partitions_def, deps=deps,
        group_name=f"ingest_{engine}", required_resource_keys={engine}
    )
    def _ingest(context: AssetExecutionContext):
        pk = context.partition_key
        path = os.path.join(DATA_DIR, "staging", f"{table}_{pk}.parquet")
        target = f"{table}_{pk}"
        db = getattr(context.resources, engine)

        if engine == "postgres":
            db.bulk_load(path, target)
            # DDL Logic
            ddl = PostgresDDLGenerator(TABLE_DEFS.get(table, {}), target, pk)
            if sql := ddl.generate_pk_sql(): db.execute_query(sql)
            for sql in ddl.generate_index_sqls(): db.execute_query(sql)
            for sql in ddl.generate_fk_sqls(): 
                try: db.execute_query(sql)
                except Exception as e: context.log.warning(e)
            db.execute_query(f"ANALYZE {target};")
        
        elif engine == "duckdb":
            db.execute_query(f"CREATE OR REPLACE TABLE {target} AS SELECT * FROM read_parquet('{path}')", partition_key=pk)

    return _ingest

ingestion_assets = []
if ACTIVE_ENGINES:
    for engine in ACTIVE_ENGINES:
        prev = None
        for table in CTX['tables']:
            upstream = prev if engine == "duckdb" else None
            new_asset = make_ingestion_asset(table, engine, upstream)
            ingestion_assets.append(new_asset)
            prev = new_asset.key.path[-1]