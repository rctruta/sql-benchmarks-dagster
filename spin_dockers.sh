# Spin up 4 containers
for i in {1..4}; do
  docker run -d --name pg_test_$i -e POSTGRES_PASSWORD=password postgres:15
done

# Check stats (CPU/MEM)
docker stats --no-stream

# Clean up
docker rm -f $(docker ps -a -q --filter="name=pg_test_")