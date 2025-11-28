from dagster import DagsterInstance

def inspect_raw_data():
    # 1. Connect
    try:
        instance = DagsterInstance.get()
        print(f"📍 Connected to: {instance.root_directory}")
    except Exception:
        print("❌ CRITICAL: Set DAGSTER_HOME first.")
        return

    # 2. Find ONE benchmark asset
    try:
        all_keys = list(instance.all_asset_keys) # Try property
    except TypeError:
        all_keys = list(instance.all_asset_keys()) # Try method

    # Look for ANY asset with "benchmark" in the name
    target_key = next((k for k in all_keys if "benchmark" in k.path[-1]), None)

    if not target_key:
        print("❌ No assets found containing 'benchmark'.")
        print("Found keys:", [k.path[-1] for k in all_keys[:5]])
        return

    print(f"🔎 Inspecting Asset: {target_key.to_string()}")

    # 3. Get the LATEST materialization (No lists, no loops)
    event = instance.get_latest_materialization_event(target_key)

    if not event:
        print("❌ This asset has NEVER been materialized in this database.")
        print("Action: Go to UI and materialize it.")
        return

    # 4. Dump the Raw Metadata
    mat = event.dagster_event.step_materialization_data.materialization
    meta = mat.metadata
    
    print("\n--- RAW METADATA DUMP ---")
    print(f"Timestamp: {event.timestamp}")
    print("Keys found in metadata:")
    for key, val in meta.items():
        # dagster often wraps values, we try to print the raw value
        try:
            print(f" - {key}: {val.value}")
        except:
            print(f" - {key}: {val} (Could not extract value)")

    # 5. Check our specific target
    if "duration_seconds" in meta:
        print("\n✅ SUCCESS: 'duration_seconds' exists!")
    else:
        print("\n❌ FAILURE: 'duration_seconds' is MISSING from the metadata.")

if __name__ == "__main__":
    inspect_raw_data()