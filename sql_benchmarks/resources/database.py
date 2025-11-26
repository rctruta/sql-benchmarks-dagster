import duckdb
from dagster import ConfigurableResource

class DuckDBResource(ConfigurableResource):
    database_path: str

    def execute_query(self, sql: str):
        """Standard execution (lazy)"""
        with duckdb.connect(self.database_path) as con:
            con.execute(sql)

    def benchmark_query(self, sql: str):
        """
        Executes AND fetches results to force the DB to finish work 
        before stopping the timer.
        """
        with duckdb.connect(self.database_path) as con:
            # .fetchall() forces the engine to materialize the result set
            # This moves the execution time INSIDE the measurement window.
            con.execute(sql).fetchall()