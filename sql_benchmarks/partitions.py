import itertools
from dagster import MultiPartitionsDefinition, StaticPartitionsDefinition
from .utils.common import load_context

try:
    CTX = load_context()
except Exception:
    CTX = {"dimensions": {}, "engines": []}

def build_partitions():
    """
    Dynamically projects N dimensions onto a 2D Grid (Engine x Scenario).
    Uses Composite Key Encoding (__) to prevent separator collisions with Dagster (|).
    """
    # 1. PRIMARY AXIS: Engine
    engines = CTX.get("engines", [])
    if not engines: engines = ["default"]

    # 2. SECONDARY AXIS: Scenario (Composite)
    other_dims = CTX.get("dimensions", {}).copy()

    if not other_dims:
        composite_keys = ["baseline"]
        composite_params_map = {"baseline": {}}
        composite_axis_name = "scenario"
    else:
        dim_names = sorted(other_dims.keys())
        dim_values_list = [other_dims[k] for k in dim_names]
        
        # Name the axis explicitly
        composite_axis_name = "_".join(dim_names) # e.g. "disk_rows"
        composite_keys = []
        composite_params_map = {}

        for combo in itertools.product(*dim_values_list):
            params = dict(zip(dim_names, combo))
            
            # SAFE ENCODING: Use double underscore __ to avoid clashing with Dagster's |
            key_str = "__".join([str(v) for v in combo])
            
            composite_keys.append(key_str)
            composite_params_map[key_str] = params

    # 3. DEFINE 2D GRID
    partitions_def = MultiPartitionsDefinition({
        "engine": StaticPartitionsDefinition([str(e) for e in engines]),
        composite_axis_name: StaticPartitionsDefinition(composite_keys)
    })

    # 4. BUILD LOOKUP MAP
    full_config_map = {}
    axes = sorted(["engine", composite_axis_name]) # Dagster sorts axis names alphabetically

    for eng in engines:
        for comp_key in composite_keys:
            # Reconstruct params
            params = composite_params_map[comp_key].copy()
            if eng != "default":
                params["engine"] = eng
            
            # Reconstruct Dagster Key (Axis1|Axis2)
            key_parts = []
            for axis in axes:
                if axis == "engine":
                    key_parts.append(str(eng))
                else:
                    key_parts.append(comp_key)
            
            final_key = "|".join(key_parts)
            full_config_map[final_key] = params

    return partitions_def, full_config_map

# EXPORT
partitions_def, SCENARIO_CONFIG = build_partitions()