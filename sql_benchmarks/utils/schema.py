from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Optional, Union, Any
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
    
    # Type override for DB DDL (e.g., "double precision")
    type: Optional[str] = None

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
    
    # Allow table-level overrides (compression, etc.)
    class Config:
        extra = 'allow'

# ==========================================
# 2. DATASET CONFIGURATION (Polymorphic)
# ==========================================
class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    source: Optional[str] = None
    tables: Optional[Dict[str, Any]] = None # permissive for now
    paths: Optional[Dict[str, str]] = None

# ==========================================
# 3. EXECUTION CONFIGURATION (The Matrix)
# ==========================================
class PostgresSettings(BaseModel):
    work_mem: Optional[str] = None
    random_page_cost: Optional[float] = None
    # Allow other pg_settings keys without validation errors
    class Config:
        extra = 'allow'

class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    
    # REQUIRED in V7
    engines: List[str] 
    
    # Optional
    test_suite: Optional[str] = None
    replication: int = 1
    pg_settings: Optional[Dict[str, Any]] = None
    
    # The Matrix (can be named matrix or dimensions)
    matrix: Optional[Dict[str, List[Any]]] = None
    dimensions: Optional[Dict[str, List[Any]]] = None

# ==========================================
# 4. ROOT CONFIGURATION
# ==========================================
class MetaInfo(BaseModel):
    experiment_id: str
    description: Optional[str] = None
    # Allow extra metadata tags
    class Config:
        extra = 'allow'

class ExperimentSchema(BaseModel):
    meta: Dict[str, str]
    dataset: DatasetConfig
    execution: ExecutionConfig 

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