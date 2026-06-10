"""
Abstract base for schema-first (non-relational) database clients.

SQL clients (DuckDB, Postgres, Actian) bulk-load via a single file-level
operation (COPY / read_parquet / vwload).  Schema-first databases require a
different three-step sequence:

    1. Prepare the data store  (drop / create database, collection, graph …)
    2. Define the schema       (entity types, attributes, constraints …)
    3. Insert rows in batches  (no native bulk-file path)

This class owns that orchestration via the Template Method pattern.
Concrete subclasses implement the three abstract steps for their specific
database.  A future Neo4j, ArangoDB, or Weaviate client would extend this
class and implement only those three methods.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import polars as pl


class SchemaFirstClient(ABC):
    """
    Template-method base for schema-first database clients.

    Subclass contract
    -----------------
    Implement the three abstract methods below.  Do NOT override
    ``bulk_load`` unless you genuinely need to change the loading sequence.
    """

    #: Rows per write transaction.  Subclasses may override.
    BATCH_SIZE: int = 200

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def bulk_load(self, filepath: str, entity_type: str) -> None:
        """
        Load a Parquet file into the database.

        Sequence (fixed):
            1. _prepare_store   — wipe and recreate the data store
            2. _define_schema   — declare types / structure
            3. _insert_batch    — write rows in BATCH_SIZE chunks
        """
        df = pl.read_parquet(filepath)

        self._prepare_store(entity_type)
        self._define_schema(entity_type, df)

        rows = df.to_dicts()
        for i in range(0, len(rows), self.BATCH_SIZE):
            self._insert_batch(entity_type, rows[i : i + self.BATCH_SIZE])

        print(
            f"[{type(self).__name__}] Loaded {len(rows)} rows"
            f" into '{entity_type}'"
        )

    @abstractmethod
    def run_query(self, query: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        """
        Execute a query and return the wall-clock duration in seconds.

        Implementations must force full result materialisation before
        stopping the clock (consistent with how DuckDB and Actian are timed).
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Abstract steps (implement in subclass)
    # ------------------------------------------------------------------

    @abstractmethod
    def _prepare_store(self, entity_type: str) -> None:
        """
        Drop any existing data store and create a fresh one.

        Examples:
            TypeDB  → drop + create database
            Neo4j   → drop + create named graph
            MongoDB → drop + create collection
        """
        raise NotImplementedError

    @abstractmethod
    def _define_schema(self, entity_type: str, df: pl.DataFrame) -> None:
        """
        Declare the schema / structure for ``entity_type``.

        ``df`` is provided so implementations can derive the schema from
        the DataFrame's column names and dtypes rather than requiring a
        separate schema file.
        """
        raise NotImplementedError

    @abstractmethod
    def _insert_batch(self, entity_type: str, rows: list) -> None:
        """Persist one batch of plain-dict rows to the data store."""
        raise NotImplementedError
