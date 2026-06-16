# We need to import the parser helper from common to avoid code duplication
# But to avoid circular imports, we just reimplement the tiny extractor or 
# pass the FKs in. Let's keep it simple and self-contained.

class PostgresDDLGenerator:
    def __init__(self, table_def, physical_name, partition_key):
        self.def_ = table_def
        self.name = physical_name
        self.part = partition_key

    def generate_pk_sql(self):
        pk_cols = [c['name'] for c in self.def_.get('columns', []) if c.get('primary_key')]
        if pk_cols:
            return f"ALTER TABLE {self.name} ADD PRIMARY KEY ({', '.join(pk_cols)});"
        return None

    def generate_index_sqls(self):
        sqls = []
        for idx in self.def_.get('indexes', []):
            cols = idx.get('columns', [])
            if not cols: continue
            # Index names are schema-global in Postgres, but the same table_def is
            # applied to every partition's physical table. A fixed config name would
            # collide across partitions — and CREATE INDEX IF NOT EXISTS would
            # SILENTLY skip all but the first. Scope the name to the physical table
            # so it is unique, and omit IF NOT EXISTS so a genuine collision is loud.
            base = idx.get('name') or f"idx_{'_'.join(cols)}"
            name = f"{base}_{self.name}"
            sqls.append(f"CREATE INDEX {name} ON {self.name} ({', '.join(cols)});")
        return sqls

    def generate_fk_sqls(self):
        sqls = []
        # Local logic to find FKs (Clean and self-contained)
        for col in self.def_.get('columns', []):
            if col.get('provider') == 'foreign_key':
                target = col.get('target_table')
                target_col = col.get('target_column')
                if not target or not target_col: continue

                target_phys = f"{target}_{self.part}"
                fk_name = f"fk_{self.name}_{col['name']}"
                sqls.append(
                    f"ALTER TABLE {self.name} ADD CONSTRAINT {fk_name} "
                    f"FOREIGN KEY ({col['name']}) REFERENCES {target_phys} ({target_col});"
                )
        return sqls