import time
import polars as pl
from typing import Dict, Any, Optional
from typedb.driver import TypeDB, Credentials, DriverOptions, TransactionType

from .base_schema_client import SchemaFirstClient


class TypeDBClient(SchemaFirstClient):
    """
    Concrete SchemaFirstClient for TypeDB.

    Implements the three loading steps using the TypeDB Python driver:
        _prepare_store  → drop / create TypeDB database
        _define_schema  → SCHEMA transaction with a TypeQL ``define`` block
        _insert_batch   → WRITE transaction with a TypeQL ``insert`` block

    Query execution uses a READ transaction and forces full result
    materialisation via ``list(answer.as_concept_rows())``.
    """

    def __init__(self, address: str, db_name: str):
        self.address = address
        self.db_name = db_name

    # ------------------------------------------------------------------
    # SchemaFirstClient — abstract step implementations
    # ------------------------------------------------------------------

    def _prepare_store(self, entity_type: str) -> None:
        """Drop the TypeDB database if it exists, then recreate it."""
        with self._driver() as driver:
            if driver.databases.contains(self.db_name):
                driver.databases.get(self.db_name).delete()
            driver.databases.create(self.db_name)

    def _define_schema(self, entity_type: str, df: pl.DataFrame) -> None:
        """Run a SCHEMA transaction containing a TypeQL ``define`` block."""
        schema_tql = self._build_schema(entity_type, df)
        with self._driver() as driver:
            with driver.transaction(self.db_name, TransactionType.SCHEMA) as tx:
                tx.query(schema_tql).resolve()
                tx.commit()

    def _insert_batch(self, entity_type: str, rows: list) -> None:
        """Run a WRITE transaction containing a TypeQL ``insert`` block."""
        insert_tql = self._build_insert(entity_type, rows)
        with self._driver() as driver:
            with driver.transaction(self.db_name, TransactionType.WRITE) as tx:
                tx.query(insert_tql).resolve()
                tx.commit()

    # ------------------------------------------------------------------
    # SchemaFirstClient — run_query
    # ------------------------------------------------------------------

    def run_query(self, typeql: str, scenario_params: Dict[str, Any]) -> Optional[float]:
        """
        Execute a TypeQL query and return wall-clock duration including
        full result consumption (consistent with DuckDB / Actian timing).

        Returns ``None`` if the TypeDB server crashes during evaluation (e.g.
        stack overflow from deep recursive function calls on Zipf hub graphs).
        Crashes are logged but do not propagate so that the benchmark
        infrastructure can record a null result and continue.
        """
        from typedb.common.exception import TypeDBDriverException  # local import — optional dep
        try:
            with self._driver() as driver:
                with driver.transaction(self.db_name, TransactionType.READ) as tx:
                    start = time.time()
                    answer = tx.query(typeql).resolve()
                    list(answer.as_concept_rows())  # force full materialisation
                    end = time.time()
            return end - start
        except TypeDBDriverException as exc:
            print(
                f"[TypeDBClient] Query failed on '{self.db_name}' "
                f"(TypeDB server error — likely stack overflow or OOM "
                f"during recursive evaluation): {exc}"
            )
            return None
        except Exception as exc:
            print(f"[TypeDBClient] Query failed on '{self.db_name}' (unexpected): {exc}")
            return None

    # ------------------------------------------------------------------
    # TypeQL builders (TypeDB-specific, not part of base contract)
    # ------------------------------------------------------------------

    def _build_schema(self, entity_type: str, df: pl.DataFrame) -> str:
        """
        Produce a TypeQL ``define`` block from a Polars schema.

        Example output:
            define
              entity skewed_data_ssd_small,
                owns id @key,
                owns selectivity_code,
                owns payload;
              attribute id, value integer;
              attribute selectivity_code, value string;
              attribute payload, value string;
        """
        attr_defs = []
        owns_clauses = []

        for col_name, dtype in df.schema.items():
            typeql_value = self._polars_to_typeql_value(dtype)
            attr_defs.append(f"  attribute {col_name}, value {typeql_value};")
            if col_name == "id":
                owns_clauses.append(f"    owns {col_name} @key")
            else:
                owns_clauses.append(f"    owns {col_name}")

        owns_str = ",\n".join(owns_clauses) + ";"
        attr_str = "\n".join(attr_defs)

        return f"define\n  entity {entity_type},\n{owns_str}\n{attr_str}"

    def _build_insert(self, entity_type: str, rows: list) -> str:
        """
        Produce a single TypeQL ``insert`` block for a batch of rows.

        Each variable is uniquely named ($x0, $x1, …) to avoid clashes
        within the same transaction.
        """
        stmts = []
        for i, row in enumerate(rows):
            parts = [f"$x{i} isa {entity_type}"]
            for col, val in row.items():
                if val is None:
                    continue
                if isinstance(val, bool):
                    parts.append(f"has {col} {str(val).lower()}")
                elif isinstance(val, str):
                    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
                    parts.append(f'has {col} "{escaped}"')
                else:
                    parts.append(f"has {col} {val}")
            stmts.append(", ".join(parts) + ";")

        return "insert\n  " + "\n  ".join(stmts)

    @staticmethod
    def _polars_to_typeql_value(dtype) -> str:
        """Map a Polars dtype to the appropriate TypeQL value type."""
        if dtype in (
            pl.Int8, pl.Int16, pl.Int32, pl.Int64,
            pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
        ):
            return "integer"
        if dtype in (pl.Float32, pl.Float64):
            return "double"
        if dtype == pl.Boolean:
            return "boolean"
        if dtype == pl.Date or isinstance(dtype, pl.Datetime):
            return "datetime"
        return "string"

    # ------------------------------------------------------------------
    # Multi-table loading (hypergraph / relation support)
    # ------------------------------------------------------------------

    def initialize_db(self) -> None:
        """
        Drop and recreate the TypeDB database.

        Called once per partition at the start of a bulk-load phase so that
        multiple entity types can be loaded into the same database without
        each one wiping the previous data (the original ``_prepare_store``
        behaviour).
        """
        with self._driver() as driver:
            if driver.databases.contains(self.db_name):
                driver.databases.get(self.db_name).delete()
            driver.databases.create(self.db_name)

    def load_entity(self, filepath: str, entity_type: str) -> None:
        """
        Define schema for an entity type and load its data without dropping
        the database first.

        Use this instead of ``bulk_load()`` when multiple entity types must
        coexist in the same database (e.g. a supply-chain hypergraph where
        supplier, buyer, product and supply_contract all live in one DB).
        """
        df = pl.read_parquet(filepath)
        self._define_schema(entity_type, df)
        rows = df.to_dicts()
        for i in range(0, len(rows), self.BATCH_SIZE):
            self._insert_batch(entity_type, rows[i : i + self.BATCH_SIZE])
        print(f"[TypeDBClient] Loaded {len(rows)} rows into '{entity_type}'")

    def bulk_load_relation(
        self,
        filepath: str,
        relation_type: str,
        role_map: Dict[str, list],
        attributes: list,
    ) -> None:
        """
        Define a TypeDB n-ary relation schema and load data into it.

        All referenced entity types must already exist in the database
        (i.e. ``load_entity()`` must have been called for each role player).

        Args:
            filepath:      Path to the Parquet file whose rows become relations.
            relation_type: TypeDB relation type name (e.g. ``supply_contract_small``).
            role_map:      Mapping of DataFrame column name → [entity_type, role_name].
                           Example: ``{"supplier_id": ["supplier_small", "supplier_role"]}``.
            attributes:    Column names that become relation-owned attributes
                           (everything not in ``role_map`` and not ``id``).
        """
        df = pl.read_parquet(filepath)
        schema_tql = self._build_relation_schema(relation_type, role_map, attributes, df)
        with self._driver() as driver:
            with driver.transaction(self.db_name, TransactionType.SCHEMA) as tx:
                tx.query(schema_tql).resolve()
                tx.commit()

        rows = df.to_dicts()
        for i in range(0, len(rows), self.BATCH_SIZE):
            insert_tql = self._build_relation_insert(
                relation_type, role_map, attributes, rows[i : i + self.BATCH_SIZE]
            )
            with self._driver() as driver:
                with driver.transaction(self.db_name, TransactionType.WRITE) as tx:
                    tx.query(insert_tql).resolve()
                    tx.commit()

        print(f"[TypeDBClient] Loaded {len(rows)} relations into '{relation_type}'")

    def _build_relation_schema(
        self,
        relation_type: str,
        role_map: Dict[str, list],
        attributes: list,
        df: pl.DataFrame,
    ) -> str:
        """
        Produce a TypeQL ``define`` block that augments an existing schema with:
          - attribute types for the relation's own attributes
          - the relation type declaration (roles + owned attributes)
          - ``plays`` declarations for each role-player entity type

        Example output (supply_contract_small with 3 roles)::

            define
              attribute volume, value integer;
              attribute price_per_unit, value double;
              relation supply_contract_small,
                relates supplier_role,
                relates buyer_role,
                relates product_role,
                owns volume,
                owns price_per_unit;
              supplier_small plays supply_contract_small:supplier_role;
              buyer_small plays supply_contract_small:buyer_role;
              product_small plays supply_contract_small:product_role;
        """
        # Attribute type definitions (relation-owned columns only)
        attr_defs = []
        for col in attributes:
            typeql_val = self._polars_to_typeql_value(df.schema[col])
            attr_defs.append(f"  attribute {col}, value {typeql_val};")

        # Unique role names (preserve declaration order)
        role_names = list(dict.fromkeys(entry[1] for entry in role_map.values()))

        # Relation type body
        relates_clauses = [f"    relates {r}" for r in role_names]
        owns_clauses = [f"    owns {col}" for col in attributes]
        relation_body = ",\n".join(relates_clauses + owns_clauses) + ";"
        relation_def = f"  relation {relation_type},\n{relation_body}"

        # Plays declarations (one per role player)
        plays_lines = [
            f"  {entry[0]} plays {relation_type}:{entry[1]};"
            for entry in role_map.values()
        ]

        return "define\n" + "\n".join(attr_defs + [relation_def] + plays_lines)

    def _build_relation_insert(
        self,
        relation_type: str,
        role_map: Dict[str, list],
        attributes: list,
        rows: list,
    ) -> str:
        """
        Produce a single TypeQL ``match … insert`` block for a batch of
        relation rows.

        Each row uses unique variable names (``$e{i}_{col}``) so that all
        match constraints are satisfied in a single solution, and the insert
        phase creates one relation per row in one round trip.

        Example (one row, supply_contract)::

            match
              $e0_supplier_id isa supplier_small, has id 3;
              $e0_buyer_id isa buyer_small, has id 7;
              $e0_product_id isa product_small, has id 2;
            insert
              (supplier_role: $e0_supplier_id, buyer_role: $e0_buyer_id,
               product_role: $e0_product_id) isa supply_contract_small,
               has volume 450, has price_per_unit 12.5;
        """
        match_parts: list[str] = []
        insert_parts: list[str] = []

        for i, row in enumerate(rows):
            # Match: bind each role-player entity by its integer key
            for col, (entity_type, _) in role_map.items():
                var = f"$e{i}_{col}"
                match_parts.append(f"  {var} isa {entity_type}, has id {row[col]};")

            # Insert: build the relation with roles and attribute values
            roles_str = ", ".join(
                f"{entry[1]}: $e{i}_{col}" for col, entry in role_map.items()
            )
            attr_parts: list[str] = []
            for col in attributes:
                val = row.get(col)
                if val is None:
                    continue
                if isinstance(val, bool):
                    attr_parts.append(f"has {col} {str(val).lower()}")
                elif isinstance(val, str):
                    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
                    attr_parts.append(f'has {col} "{escaped}"')
                else:
                    attr_parts.append(f"has {col} {val}")

            attr_str = (", " + ", ".join(attr_parts)) if attr_parts else ""
            insert_parts.append(f"  ({roles_str}) isa {relation_type}{attr_str};")

        return "match\n" + "\n".join(match_parts) + "\ninsert\n" + "\n".join(insert_parts)

    def apply_inference_schema(self, tql: str) -> None:
        """
        Apply a TypeQL ``define`` block as a SCHEMA transaction.

        Used to augment an existing database with inferred relation types and
        inference rules *after* the base data has been loaded.  Calling this
        multiple times with non-conflicting definitions is safe (TypeDB is
        idempotent for ``define`` of already-existing types/rules).

        Args:
            tql: A complete TypeQL ``define`` block, e.g. the transitive
                 reachability rule generated by
                 ``TypeDBEngine._build_transitive_inference_schema()``.
        """
        with self._driver() as driver:
            with driver.transaction(self.db_name, TransactionType.SCHEMA) as tx:
                tx.query(tql).resolve()
                tx.commit()
        print(f"[TypeDBClient] Applied inference schema to '{self.db_name}'")

    # ------------------------------------------------------------------
    # Driver factory
    # ------------------------------------------------------------------

    def _driver(self):
        creds = Credentials("admin", "password")
        opts = DriverOptions(is_tls_enabled=False)
        return TypeDB.driver(self.address, creds, opts)
