import time
import subprocess
from dagster import ConfigurableResource
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

class PostgresResource(ConfigurableResource):
    connection_string: str = "postgresql://postgres:password@localhost:5432/postgres"
    container_name: str = "benchmark_postgres" # Matches your docker-compose.yaml

    def get_engine(self):
        return create_engine(self.connection_string)

    def execute_query(self, sql: str):
        """Run a command (CREATE, DROP) without returning data."""
        engine = self.get_engine()
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()

    def clear_cache(self):
        """
        Restarts the Docker container to force a Cold Start (Clear RAM).
        """
        print(f"❄️ Restarting {self.container_name} to clear cache...")
        
        # 1. Restart the container
        subprocess.run(["docker", "restart", self.container_name], check=True)
        
        # 2. Wait for it to come back online
        # We try to connect every second for up to 15 seconds.
        retries = 15
        while retries > 0:
            try:
                engine = self.get_engine()
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                print("✅ Postgres is back online.")
                return
            except OperationalError:
                time.sleep(1)
                retries -= 1
                print("... waiting for DB ...")
        
        raise Exception("Postgres failed to restart in time.")

    def benchmark_query(self, sql: str):
        """
        Clears cache, then runs the query.
        """
        # 1. Force Cold Start
        self.clear_cache()
        
        # 2. Run Query
        engine = self.get_engine()
        with engine.connect() as conn:
            # .fetchall() forces network transfer
            _ = conn.execute(text(sql)).fetchall()