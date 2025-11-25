import duckdb
import os
from dagster import ConfigurableResource

class DuckDBResource(ConfigurableResource):
    """
    Manages the connection to a local DuckDB instance.
    """
    database_path: str = "data/benchmark.duckdb"

    def execute_query(self, sql: str):
        """
        Executes a SQL query against the DuckDB database.
        """
        # Ensure the folder exists
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        
        # Connect, run, and close (Context Manager)
        with duckdb.connect(self.database_path) as con:
            con.execute(sql)
            
    def query_as_df(self, sql: str):
        """
        Runs a query and returns the result as a Pandas DataFrame (good for checking results).
        """
        with duckdb.connect(self.database_path) as con:
            return con.execute(sql).df()