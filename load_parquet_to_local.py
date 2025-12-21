
import os
import sys
import glob

# 1. SETUP PATHS INDEPENDENT OF EXECUTION CONTEXT
# Get the directory where this script lives (Project Root)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure module imports work regardless of where script is run from
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from sql_benchmarks.resources.postgres_client import PostgresClient
# We define path manually to avoid circular dependeny or context issues
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

def load_local(target_pattern="*.parquet"):
    """
    Loads Parquet files from data/staging into local Postgres.
    """
    # 2. Configuration
    # Allow simple override via env var
    PG_CONN = os.getenv("PG_CONN", "postgresql://postgres:password@localhost:5432/postgres")
    STAGING_DIR = os.path.join(DATA_DIR, "staging")
    
    print(f"\n[INFO] 🔌 Target Database: {PG_CONN}")
    print(f"       (Override with 'export PG_CONN=postgresql://...')")

    try:
        client = PostgresClient(PG_CONN)
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return

    # 2. Find Files
    search_path = os.path.join(STAGING_DIR, target_pattern)
    files = glob.glob(search_path)
    
    if not files:
        print(f"[WARN] No files found matching: {search_path}")
        return

    print(f"[INFO] Found {len(files)} files to ingest.")
    
    success_count = 0

    # 3. Load
    for f in files:
        basename = os.path.basename(f)
        table_name = basename.replace(".parquet", "").replace(".", "_")
        
        # Cleanup name to be SQL friendly
        table_name = table_name.lower()
        
        print(f"\n---> Ingesting: {basename} -> 📦 Table: {table_name}")
        try:
            # We use a custom loading logic here to force lowercase columns
            # because standard PostgresClient preserves case with quotes.
            # 1. Read Schema
            import polars as pl
            df = pl.scan_parquet(f).limit(1).collect()
            
            # 2. Rename columns to lowercase
            new_cols = {c: c.lower() for c in df.columns}
            
            # 3. Drop/Create Table with strict lowercase
            # We can't easily use client.bulk_load directly because it infers schema internally from file.
            # Workaround: We let client.bulk_load do its thing, BUT we patch the _create_schema method on the instance?
            # Or better: We subclass it for this script.
            
            class FriendlyPostgresClient(PostgresClient):
                def _create_schema(self, table_name, sample_df):
                    # Rename columns in the sample DF before passing to super or custom logic
                    # Polars rename is easy
                    lower_map = {c: c.lower() for c in sample_df.columns}
                    sample_df = sample_df.rename(lower_map)
                    super()._create_schema(table_name, sample_df)

            # Re-init client with friendly version
            friendly_client = FriendlyPostgresClient(PG_CONN)
            friendly_client.bulk_load(f, table_name)
            
            print("     [SUCCESS] Table created.")
            success_count += 1
        except Exception as e:
            print(f"     [FAILED] {e}")
            
    if success_count > 0:
        print("\n[TIP] Check your tables with:")
        print(f"      psql '{PG_CONN}' -c '\\dt'")

if __name__ == "__main__":
    target = "*.parquet"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    
    load_local(target)
