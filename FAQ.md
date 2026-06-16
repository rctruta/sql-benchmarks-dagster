# FAQ

## Why isn't there a `docker-compose up` step? What is `dev/docker-compose.yaml`?

**Containers are managed in code, not by Compose.** The Postgres engine
(`sql_benchmarks/resources/postgres.py`) and the TypeDB engine start,
health-check, and *reset* their containers through the Docker SDK as part of a
run — including the cold-cache container restarts the benchmark methodology
requires before each measured query. So the normal workflow (`./run.sh …`)
needs no manual Compose step, and nothing in the harness or the tests invokes
one.

A Compose file is kept at **`dev/docker-compose.yaml`** purely as a convenience
for **manual, ad-hoc inspection** — bringing up Postgres or TypeDB by hand
*outside* an experiment:

```bash
docker compose -f dev/docker-compose.yaml up -d    # start
docker compose -f dev/docker-compose.yaml down     # stop
```

It is optional and is not part of running experiments.

## Why synthetic data? Is that a limitation?

It's a deliberate fit to the question. The lab's job is to **isolate variables**.
For a *mechanism* question — "where does the Quack protocol spend its time?" —
synthetic data is the correct instrument: controlled, parameterizable, and
seeded, so the only thing varying is the thing under test. Real data's skew,
correlations, and irregularities would be *confounders* for that kind of
question. Synthetic data is also reproducible to the byte via the dataset seed.

The generator is not naive-uniform — it supports choice weights, null
probability, and Zipf skew — so realism can be dialed up. What synthetic data
can't fully reproduce is real-world *correlation* and dirtiness. That matters
for a different question type: **capacity** ("will this query be fast on *my*
data?"), where real data is necessary and more valuable. The lab supports both —
synthetic (`declarative_gen`), canonical TPC-H (`dbgen`), and real-file loading —
but the published work to date is synthetic- and canonical-focused.

## Can I run experiments on real data?

Partially — treat it as **experimental / work-in-progress**. A loader
(`sql_benchmarks/plugins/data_sources/local_file_loader.py`) streams
CSV/Parquet/JSON into the platform's Parquet, and `dataset.source` selects it.
Two things are not yet built, and both matter for the lab's guarantees:

1. **Schema validation** — real columns aren't yet checked against the SQL the
   experiment runs (a mismatch surfaces as a query-time error).
2. **Input reproducibility** — the Experiment ID hashes config + SQL + code, and
   synthetic data is pinned by its seed. A real file's *contents* aren't yet
   folded into the identity, so the same path with different contents would
   collide on one ID. Real-data capsules need an input checksum to extend the
   trust chain.

Until those land, real-data runs are exploratory.

## Does the lab build indexes (primary keys, secondary indexes)?

Yes. A table's declared `primary_key:` and `indexes:` are applied to Postgres at
ingestion (the DuckDB/Quack engines are columnar and use automatic min-max
zonemaps instead, so they ignore them). The index is built during the
ingestion/setup phase — *outside* the timed query loop — so a query measures
steady-state latency against an already-indexed table, not the one-time build
cost. Index names are scoped to each partition's physical table, so the same
table definition can be applied across a matrix without collisions.

But an index is not free, and not always a win. The selectivity study (indexed
capsule `461beee8` vs no-index `28f7aa1c`) shows Postgres's B-tree winning big on
a highly selective query — an Index-Only Scan, 4.3× faster at 0.1% of 10M rows —
yet becoming a *liability* at moderate selectivity on a cold cache: at 5%, the
planner's Bitmap Heap Scan does enough random heap reads to run *slower than a
plain sequential scan*. Because the harness measures cold cache (it flushes the
OS page cache and restarts the container before every query), it surfaces this
directly; a warm cache would favour the index more broadly. The lesson is that
"add an index" is a conditional, not a law — see
[docs/published_capsules.md](docs/published_capsules.md).

## Can this lab be used for AI-security research?

Yes — it's the top roadmap direction, and the architecture generalizes directly.
Experiments become adversarial inputs; engines become models or agent configs;
and the **semantic auditor** — today a proof-of-concept that rejects results
violating basic invariants before they're sealed — grows into a validation gate
that asks whether a *structurally valid* (e.g. Pydantic-passing) model output
still carries an exploit. *Structure is not security.* The reproducible, sealed,
timestamped capsule then becomes reproducible **exploit evidence** with full
provenance.

## Roadmap (in priority order)

1. **AI-security testbed** — repurpose the harness for adversarial testing of
   agentic pipelines; expand the semantic auditor into Pydantic/ontology-backed
   exploit-validation rules.
2. **Real-data support** — schema validation + input-content checksums, to bring
   the trust chain to production data.
3. **Methodology article** — the architecture writeup these experiments reference.

## How do I verify a published result without trusting the author?

See [docs/published_capsules.md](docs/published_capsules.md) — every capsule is
reproducible (re-run → same ID), integrity-sealed, OpenTimestamped, and the
release is signed (`git verify-tag`).
