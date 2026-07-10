---
name: build-scaling-experiment
description: Build and submit a scaling benchmark experiment. Use when the goal names a scale-varying investigation (e.g. how does X scale from N to M rows, is the growth linear, or at what size does Y break).
---
# Skill: build a scaling experiment

**Use when:** the goal names a scale-varying investigation ("how does X scale from N to M rows", "is the growth linear", "at what size does Y break").

**Do NOT construct YAML from scratch.** Fetch a template, adapt it. `quickstart` (DuckDB-only) and `scaling_depth` (multi-engine) are the two scaling starters — `list_templates` names them all.

## Recipe

1. `list_categories` → the vocabulary is small. For scaling questions, `scaling` is the tag. For cross-engine investigations, also `cross-engine`. For selectivity/index behavior, `selectivity`.
2. `list_suites` **with `category=<name>`** → returns only the suites tagged with that category, without SQL bloat. For "analytical aggregation scaling", `list_suites(category="scaling")` narrows to `analytical_wall` and any other scaling-tagged suite. NEVER call `list_suites` without a category unless you have no idea what you're looking for — an unfiltered call is expensive.
3. `list_templates` → `get_template quickstart` (DuckDB-only, no Docker) OR `get_template scaling_depth` (multi-engine, needs Docker). Use `quickstart` unless the question requires Postgres.
4. Adapt the fetched YAML: keep `dataset.tables.*.rows` as the string alias `rows` (not a literal integer); add the scale points you want to `definitions.rows`; list them in `execution.matrix.rows`.
5. `submit_experiment` with the adapted YAML.
6. `get_experiment_status` until `complete` or `failed`.

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

## After submission — see `skills/read-experiment-results/SKILL.md`
