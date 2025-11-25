import docker
import json
import time
from dagster import ConfigurableResource, InitResourceContext

class DockerIsolatedDatabase(ConfigurableResource):
    """
    Manages a fresh Docker container for every single query to ensure isolation.
    """
    image: str = "postgres:16-alpine" # Default to Postgres
    container_name: str = "benchmark_db_runner"
    
    # We need to know where the data is on the HOST so we can mount it
    host_data_path: str 
    
    def run_benchmark_query(self, sql_query: str):
        client = docker.from_env()
        
        # 1. CLEANUP (Ensure no zombies from previous runs)
        try:
            old = client.containers.get(self.container_name)
            old.remove(force=True)
        except docker.errors.NotFound:
            pass

        print(f"🐳 Starting fresh container: {self.image}...")
        
        # 2. START CONTAINER
        # We mount the host data path to /data inside the container
        container = client.containers.run(
            self.image,
            name=self.container_name,
            environment={"POSTGRES_PASSWORD": "password"}, # For PG
            volumes={self.host_data_path: {'bind': '/data', 'mode': 'rw'}},
            detach=True,
            ports={'5432/tcp': 5432}
        )

        try:
            # 3. WAIT FOR HEALTH
            # We must wait for the DB to be ready to accept connections.
            # (Simplified wait loop - in prod we'd check logs or socket)
            time.sleep(5) 
            
            # 4. EXECUTE QUERY
            # We use 'docker exec' to run the query via CLI inside the container.
            # We wrap the query in EXPLAIN (ANALYZE, FORMAT JSON) to get the truth.
            
            # Note: This command is specific to Postgres. 
            # If benchmarking DuckDB CLI, we would change this command.
            cmd = [
                "psql", "-U", "postgres", 
                "-c", f"EXPLAIN (ANALYZE, FORMAT JSON) {sql_query}"
            ]
            
            exec_result = container.exec_run(cmd)
            
            output = exec_result.output.decode('utf-8')
            
            # 5. PARSE METADATA
            # Postgres returns the JSON plan. We parse it to find 'Execution Time'.
            # The output might contain some psql header junk, we need to find the JSON array.
            json_start = output.find('[')
            json_end = output.rfind(']') + 1
            clean_json = output[json_start:json_end]
            
            plan = json.loads(clean_json)
            execution_time_ms = plan[0]['Plan']['Actual Total Time']
            
            return {
                "execution_time_sec": execution_time_ms / 1000.0,
                "full_plan": plan[0]
            }

        finally:
            # 6. TEAR DOWN (The Guarantee)
            print("💀 Killing container to flush buffers...")
            container.stop()
            container.remove()