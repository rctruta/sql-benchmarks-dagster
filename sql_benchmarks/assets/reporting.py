import os
import polars as pl
import pandas as pd
import plotly.express as px
from dagster import asset, AssetExecutionContext, MetadataValue, MaterializeResult, DagsterEventType, EventRecordsFilter

from ..constants import RESULTS_DIR
from ..utils.common import load_context
from .benchmark_factory import benchmark_assets
import glob
import json

all_benchmark_keys = [k.key for k in benchmark_assets]

# ==========================================
# 1. PURE LOGIC (Testable)
# ==========================================
def parse_fragments_to_records(experiment_id):
    """
    Scans the results directory for the given experiment_id
    and parses all fragment JSONs into a flat list of records.
    """
    fragments_pattern = os.path.join(RESULTS_DIR, experiment_id, "fragments", "*.json")
    fragment_files = glob.glob(fragments_pattern)
    
    records = []
    
    for fpath in fragment_files:
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            
            meta = data.get("meta", {})
            metrics = data.get("metrics", {})
            params = data.get("parameters", {})
            
            if meta.get("experiment_id") != experiment_id:
                continue

            asset_name = meta.get("asset", "unknown_asset")
            
            # Extract Partition from Filename: asset_name__PARTITION.json
            filename = os.path.basename(fpath)
            partition_name = "default"
            
            # Logic: Split by asset_name + "__"
            # It's safer to use the known separator "__"
            if "__" in filename:
                # Remove extension
                name_no_ext = os.path.splitext(filename)[0]
                parts = name_no_ext.split("__")
                if len(parts) >= 2:
                    partition_name = parts[-1]
            
            row = {
                "Asset": asset_name,
                "Partition": partition_name,
                "Duration": float(metrics.get("duration_seconds", 0.0)),
                "Engine": str(meta.get("engine", "Unknown")),
                "System": str(meta.get("engine")),
                "Rows": int(params.get("rows", 0)) if "rows" in params else 0,
                "Selectivity": float(params.get("derived_selectivity", 0.0) or 0.0)
            }

            if "disk_type" in params:
                 row["System"] += f" ({params['disk_type']})"

            # Merge ALL parameters into the row (Dynamic Columns)
            # This ensures 'null_probability' etc appear in CSV
            for k, v in params.items():
                if k not in row:
                    row[k] = v

            records.append(row)
            
        except Exception as e:
            print(f"Skipping malformed fragment {fpath}: {e}")
            continue
            
    return records

# ==========================================
# 2. THE ASSET (Orchestration)
# ==========================================
@asset(
    deps=all_benchmark_keys,
    group_name="reporting",
    description="Generates a Multi-View Dashboard."
)
def performance_dashboard(context: AssetExecutionContext):
    instance = context.instance
    try:
        CTX = load_context()
        EXP_ID = CTX['meta'].get("experiment_id", "unknown")
    except Exception:
        context.log.warning("Could not read active context.")
        return

    # 1. FETCH & PARSE (New Logic)
    records = parse_fragments_to_records(EXP_ID)

    if not records:
        context.log.info(f"No records found for experiment: {EXP_ID}")
        return

    # 3. PREPARE DATA
    df = pl.DataFrame(records)
    
    # Deduplicate: Keep last run for same (Asset, Partition, Engine)
    # Rows might technically differ but Partition should cover it.
    unique_keys = ["Asset", "Partition", "System", "Rows"]
    # Filter keys that actually exist (to be safe if Partition is missing in legacy)
    unique_keys = [k for k in unique_keys if k in df.columns]
    
    df = df.unique(subset=unique_keys, keep="last").sort("Rows")
    pldf = df.to_pandas()

    # 3.5 SANITIZE DATA (The "Gas in the Trunk")
    # ------------------------------------------
    # Drop columns that are effectively "Null" or "Default" across the entire dataset
    # This prevents "Selectivity=0.0" from appearing in titles when it wasn't used.
    
    cols_to_drop = []
    for col in pldf.columns:
        if col in ["Asset", "System", "Engine", "Partition", "Duration"]:
            continue
            
        # Check if column is all null or all default (0.0 for float, 0 for int)
        is_all_null = pldf[col].isnull().all()
        is_all_zero = (pldf[col] == 0).all() and pd.api.types.is_numeric_dtype(pldf[col])
        is_single_value = pldf[col].nunique() <= 1
        
        # Heuristic: If it's 0 everywhere, it's likely a parser default, UNLESS it's "Rows" (which shouldn't be 0)
        # or if the user explicitly set 0. But for Selectivity/Skew, 0 is often "Not Used".
        if col != "Rows" and (is_all_null or is_all_zero):
             cols_to_drop.append(col)
        # Also drop constant columns from the "Matrix Params" consideration (but keep in DF for reference if needed?)
        # Actually, simpler to just drop them from the DF used for plotting considerations.
    
    if cols_to_drop:
        context.log.info(f"Dropping irrelevant/default columns: {cols_to_drop}")
        pldf = pldf.drop(columns=cols_to_drop)

    # Fill NaNs in remaining parameters to prevent fragmentation
    # e.g. if 'null_probability' is present in some rows but NaN in others, fill with 0 via Polars upstream or Pandas here.
    # For numeric params, 0 is usually safe default for "parameter not present".
    numeric_cols = pldf.select_dtypes(include=['number']).columns
    pldf[numeric_cols] = pldf[numeric_cols].fillna(0)

    # 4. RENDER (Visualization - Matrix Explorer)
    figures_html = []
    
    # Identify Matrix Parameters (Columns that are not "System", "Asset", "Duration", "Engine", "Partition")
    excluded_cols = {"Asset", "Partition", "Duration", "Engine", "System"}
    matrix_params = [c for c in pldf.columns if c not in excluded_cols and pd.api.types.is_numeric_dtype(pldf[c])]
    
    context.log.info(f"Matrix Params Detected: {matrix_params}")
    if "null_probability" in pldf.columns:
         context.log.info(f"Unique Null Probs: {pldf['null_probability'].unique().tolist()}")

    # 1. Comparison by System (The Basics)
    # -------------------------------------------------------------------------
    # 1. Comparison by System (The Basics)
    # -------------------------------------------------------------------------
    try:
        # Side-by-Side System Comparison (Fixed Rows Scaling)
        # Check if "Rows" is a parameter, as it's the standard X-axis
        if "Rows" in matrix_params:
             fig_compare = px.line(
                pldf, 
                x="Rows", 
                y="Duration", 
                color="System", 
                line_dash="Asset", 
                symbol="System",
                log_x=True,
                log_y=True,
                markers=True,
                title="<b>Global Comparison</b>: System Scaling (Rows vs Duration)"
            )
             figures_html.append(fig_compare.to_html(full_html=False, include_plotlyjs='cdn'))
    except Exception as e:
         context.log.warning(f"Global Plot Error: {e}")

    # 2. DYNAMIC DISCOVERY ENGINE (The "Smart Logic")
    # -------------------------------------------------------------------------
    unique_systems = sorted(pldf["System"].unique())
    
    for system in unique_systems:
        system_df = pldf[pldf["System"] == system].copy()
        
        # A. Discover Roles
        # -----------------
        # Candidates for X-Axis: Numeric params with > 1 unique value
        x_candidates = []
        for p in matrix_params:
            if system_df[p].nunique() > 1:
                x_candidates.append(p)
        
        # Heuristic: Prefer "Rows" if available, else param with max cardinality
        if "Rows" in x_candidates:
            x_axis = "Rows"
        elif x_candidates:
            # Pick max cardinality
            x_axis = max(x_candidates, key=lambda c: system_df[c].nunique())
        else:
            # Fallback if nothing varies (single point)
            x_axis = matrix_params[0] if matrix_params else "Asset"

        # B. Classify Remaining Parameters (Series vs Slices)
        # ---------------------------------------------------
        other_params = [p for p in matrix_params if p != x_axis]
        
        # Slices: High Cardinality OR Orthogonal Dimensions we want to isolate
        # Series: Low Cardinality dimensions we want to compare on one chart
        
        slice_params = []
        series_params = ["Asset"] # Always compare Assets (Logic) on same chart
        
        for p in other_params:
            # Exclude parameters that are just case variants of X-Axis (Rows vs rows)
            if p.lower() == x_axis.lower():
                continue
                
            unique_count = system_df[p].nunique()
            # If it has only 1 value, it doesn't matter (it's fixed context), 
            # but we can treat it as a Slice to be safe/explicit in title.
            # If it has many values (>5), slice it to avoid clutter.
            # If it has few values (2-5), add to SERIES (lines).
            if unique_count > 5:
                slice_params.append(p)
            elif unique_count > 1:
                series_params.append(p)
            else:
                # It's a fixed value, add to slice context implicitly
                slice_params.append(p)

        # C. Generate Plots via Slicing
        # -----------------------------
        # Group by all slice parameters to create distinct scenarios
        if slice_params:
            # Sort to ensure consistent grouping order
            slice_params = sorted(slice_params)
            grouped = system_df.groupby(slice_params)
        else:
            grouped = [((), system_df)]

        for group_keys, slice_df in grouped:
            if not isinstance(group_keys, tuple):
                group_keys = (group_keys,)
            
            # 1. Build Title
            title_parts = [f"<b>{system}</b>: Varying <b>{x_axis}</b>"]
            if slice_params:
                ctx_str = ", ".join([f"{k}={v}" for k, v in zip(slice_params, group_keys)])
                title_parts.append(f"<span style='font-size:12px'>({ctx_str})</span>")
            title = "<br>".join(title_parts)

            # 2. Construct Series Column (Legend)
            # Combine all series params into one string column "Series"
            # e.g. "2VL - 10% Nulls"
            slice_df = slice_df.copy()
            
            if len(series_params) > 1:
                # We have multiple dimensions (Asset + NullProb + ...)
                # Create a composite key
                def make_series_label(row):
                    parts = []
                    for sp in series_params:
                        val = row[sp]
                        # Beautify: If val is float, format it? 
                        # For now, simplistic str()
                        parts.append(str(val))
                    return " / ".join(parts)
                
                slice_df["_Series_"] = slice_df.apply(make_series_label, axis=1)
                color_col = "_Series_"
                symbol_col = "Asset" # Keep using Asset for symbol if present
            else:
                # Simple case: Only Asset varies
                slice_df["_Series_"] = slice_df[series_params[0]].astype(str)
                color_col = "_Series_"
                symbol_col = "_Series_"

            try:
                # 3. Plot
                scenario_df = slice_df
                scenario_df = scenario_df.sort_values(by=x_axis)
                
                fig = px.line(
                    scenario_df,
                    x=x_axis,
                    y="Duration",
                    color=color_col,
                    symbol=symbol_col if symbol_col in slice_df.columns else None,
                    markers=True,
                    log_y=True,
                    log_x=True if "Rows" in x_axis or "null" in x_axis.lower() else False,
                    title=title,
                    labels={x_axis: x_axis, "Duration": "Duration (s)", "_Series_": " / ".join(series_params)}
                )
                figures_html.append(fig.to_html(full_html=False, include_plotlyjs=False))
            except Exception as e:
                context.log.warning(f"Dynamic Plot Error ({system}): {e}")

    # 3. 3D Landscape (The "Bonus")
    # -------------------------------------------------------------------------
    if "null_probability" in matrix_params and "Rows" in matrix_params:
         try:
             fig_3d = px.scatter_3d(
                 pldf, 
                 x="Rows", 
                 y="null_probability", 
                 z="Duration", 
                 color="System",
                 symbol="Asset",
                 log_x=True,
                 log_z=True,
                 title="<b>3D Landscape</b>: Rows x Nulls x Duration",
                 height=800
             )
             figures_html.append(fig_3d.to_html(full_html=False, include_plotlyjs=False))
         except Exception as e:
             # Just skip if 3D fails
             pass

    # 5. SAVE (Side Effect)
    exp_folder = os.path.join(RESULTS_DIR, EXP_ID)
    os.makedirs(exp_folder, exist_ok=True)
    html_path = os.path.join(exp_folder, f"dashboard_{EXP_ID}.html")
    print(f"DEBUG: Saving Dashboard to: {html_path}")
    
    with open(html_path, "w") as f:
        f.write(f"<h1>Benchmark: {EXP_ID}</h1>")
        f.write(f"<p>Generated at: {pd.Timestamp.now()}</p><hr>")
        f.write("<br><hr><br>".join(figures_html))

    # 6. WRITE CSV (Legacy Support / Unified Output)
    # Replaces the partial logic in extract_results.py
    csv_path = os.path.join(exp_folder, f"results_{EXP_ID}.csv")
    df.write_csv(csv_path)
    
    return MaterializeResult(
        metadata={
            "dashboard_path": MetadataValue.path(html_path),
            "results_csv_path": MetadataValue.path(csv_path),
            "experiment_id": EXP_ID 
        })