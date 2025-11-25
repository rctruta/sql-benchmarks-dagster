from dagster import StaticPartitionsDefinition

# We define our benchmark sizes as a fixed list of keys.
# This allows us to run the entire pipeline for just "Small" or just "Large" data.
size_partitions = StaticPartitionsDefinition(
    ["small", "medium", "large"]
)

# Optional: You can map these names to actual row counts if you want to use them later
# This is a simple dictionary to help your logic translate "small" -> 100,000
ROW_COUNTS = {
    "small": 100_000,
    "medium": 1_000_000,
    "large": 10_000_000
}