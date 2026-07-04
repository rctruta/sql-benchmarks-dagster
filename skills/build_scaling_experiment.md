# Skill: build a scaling experiment

**Use when:** the goal names a scale-varying investigation ("how does X scale from N to M rows", "is the growth linear", "at what size does Y break").

**Do NOT construct YAML from scratch.** Fetch a template, adapt it. `quickstart` (DuckDB-only) and `scaling_depth` (multi-engine) are the two scaling starters — `list_templates` names them all.

## Recipe

1. `list_suites` → pick the suite whose SQL matches the *shape* of the question. For "analytical aggregation scaling", use `analytical_wall`. For "selectivity/index scaling", use `selectivity`.
2. `list_templates` → `get_template quickstart` (DuckDB-only, no Docker) OR `get_template scaling_depth` (multi-engine, needs Docker). Use `quickstart` unless the question requires Postgres.
3. Adapt the fetched YAML: keep `dataset.tables.*.rows` as the string alias `rows` (not a literal integer); add the scale points you want to `definitions.rows`; list them in `execution.matrix.rows`.
4. `submit_experiment` with the adapted YAML.
5. `get_experiment_status` until `complete` or `failed`.

## Adapt-template pattern

Start from `quickstart` and change three things:

```yaml
definitions:
  rows:
    small:  100_000     # add/rename scale points here
    medium: 1_000_000
    large:  10_000_000

execution:
  test_suite: analytical_wall     # match the question's shape
  engines:
    - duckdb                       # add postgres/quack only if the question needs cross-engine
  replication: 5                   # 5 is a good default; 3 for quick sanity, 10 for a paper
  matrix:
    rows:
      - small                      # every value here MUST exist as a key under definitions.rows
      - medium
      - large
```

## Common pitfalls (each has broken a previous run)

- **Literal `rows: 100000` under `dataset.tables.*.rows`** — must be the string alias `rows`. Literals are rejected at submission.
- **Matrix alias missing from `definitions.rows`** — every matrix value must be a key in `definitions.<dim>`. Rejected with `Alias 'X' in matrix dimension 'rows' could not be resolved`.
- **Empty `execution.engines`** — rejected at submission.
- **Suite that doesn't exist** — check `list_suites` first; the user's goal may name a suite that isn't in the catalog.
- **Docker not running** — `postgres` and `quack` engines need Docker. `duckdb` doesn't. If Docker is off, use `duckdb` only.

## After submission — see `skills/read_experiment_results.md`
