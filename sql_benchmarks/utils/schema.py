from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Optional, Union, Any
import warnings

# Temporarily silence Dagster's Pydantic V2 Deprecation Warning
# Since this file is now fully V2, this filter might be unnecessary, 
# but it's kept here in case the test runner needs it.
warnings.filterwarnings(
    "ignore", 
    category=DeprecationWarning, 
    message="Support for class-based `config` is deprecated"
)

# ==========================================
# 1. TABLE & COLUMN DEFINITIONS (Synthetic)
# ==========================================
class ColumnDef(BaseModel):
    name: str
    provider: str  # e.g., "sequence", "choice", "foreign_key"
    
    # Optional parameters specific to providers
    options: Optional[List[Any]] = None
    weights: Optional[List[float]] = None
    target_table: Optional[str] = None
    target_column: Optional[str] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    
    # Nullability Control
    null_probability: Union[float, str] = 0.0  # Default 0.0 (No NULLs)
    
    # Type override for DB DDL (e.g., "double precision")
    type: Optional[str] = None
    
    model_config = ConfigDict(extra='allow')

class IndexDef(BaseModel):
    columns: List[str]
    name: Optional[str] = None
    unique: bool = False
    method: str = "btree"

class TableDef(BaseModel):
    # 'rows' can be an integer literal OR a variable name reference (string)
    rows: Optional[Union[int, str]] = None 
    columns: Optional[List[ColumnDef]] = None
    indexes: Optional[List[IndexDef]] = []
    
    # --- V2 MIGRATION: Replaces class Config: extra = 'allow' ---
    model_config = ConfigDict(extra='allow')

# ==========================================
# 2. DATASET CONFIGURATION (Polymorphic)
# ==========================================
class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    source: Optional[str] = None
    tables: Optional[Dict[str, Any]] = None
    paths: Optional[Dict[str, str]] = None
    # Base seed for synthetic data generation (declarative_gen). Default 42.
    # The config is hashed, so changing the seed changes the Experiment ID —
    # two experiments with different data can never share an identity.
    seed: Optional[int] = None

# ==========================================
# 3. EXECUTION CONFIGURATION (The Matrix)
# ==========================================
class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    engines: List[str]

    # Optional
    test_suite: Optional[str] = None
    replication: int = 1

    # Per-engine tuning, namespaced by engine name. Each engine receives ONLY
    # its own namespace at run time and owns the vocabulary inside it.
    # Reserved namespaces: postgres, duckdb, actian, typedb, quack.
    #   engine_params:
    #     postgres: {work_mem: "64MB", random_page_cost: 1.1}
    #     duckdb:   {memory_limit: "1GB", threads: 4}
    # To VARY an engine param across partitions, declare it as a namespaced
    # matrix dimension instead:  matrix: {postgres.work_mem: [4MB, 1GB]}
    engine_params: Optional[Dict[str, Dict[str, Any]]] = None

    # The Matrix (can be named matrix or dimensions)
    matrix: Optional[Dict[str, List[Any]]] = None
    dimensions: Optional[Dict[str, List[Any]]] = None

# ==========================================
# 4. ROOT CONFIGURATION
# ==========================================
class MetaInfo(BaseModel):
    # --- V2 MIGRATION: Replaces class Config: extra = 'allow' ---
    model_config = ConfigDict(extra='allow')
    # experiment_id is computed by the system (SHA-256 hash). Never set manually.
    name: Optional[str] = None         # Short human-readable identifier, e.g. "Sort Spill Cliff"
    description: Optional[str] = None  # Prose description of the hypothesis being tested

class ExperimentSchema(BaseModel):
    meta: Optional[Dict[str, Optional[str]]] = None
    dataset: Optional[DatasetConfig] = None
    execution: Optional[ExecutionConfig] = None

# ==========================================
# 5. PUBLIC INTERFACE
# ==========================================
def validate_yaml_content(config_dict: dict) -> ExperimentSchema:
    """
    Validates a raw dictionary against the V7 Schema.
    Raises pydantic.ValidationError if the contract is violated.
    """
    return ExperimentSchema(**config_dict)

def get_json_schema():
    """Returns the JSON Schema for Agents/LLMs."""
    return ExperimentSchema.model_json_schema()