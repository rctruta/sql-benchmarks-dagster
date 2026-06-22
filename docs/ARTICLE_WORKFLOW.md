# Writing an article from capsules

The repeatable path from sealed experiments to a published article. It exists
because the first article (Quack) was slow for one reason: the lab work and the
writing happened at the same time. Every number surprise, integrity question, and
figure mismatch interrupted the prose and restarted the circling.

**The one rule that makes it fast:** lock the numbers and the structure
*mechanically* — before writing a sentence. Prose is the last step, never mixed
with number-fixing. **Never edit numbers and prose in the same sitting.**

Phases 0–2 are mechanical (scriptable, agent-friendly). Phase 3 is voice only.

---

## Phase 0 — Freeze the capsules (once)

Pick the capsules the article will cite. Confirm each one verifies, then stop
touching hashed code.

```bash
python scripts/dev/verify_capsule.py <ID>     # integrity seal (+ timestamp)
```

- All cited IDs must be **current-format capsules** (archived `experiment_config.yaml`,
  sealed, with a `generator: sqlbenchdag@<sha>` stamp). Legacy results without an
  archived config must be **re-run** before they can be cited — they are not
  reproducible capsules. See `docs/PUBLISHING.md`.
- Decide the **statistic once**: the capsule `<ID>.csv` `Duration` column is the
  **mean**. Every table and figure uses the mean; the scaling exponent α is the
  sealed median fit (`scaling.json`). The tools already enforce this — don't
  recompute by hand.
- After this point, **don't edit hashed code** (anything under `sql_benchmarks/`
  except `api/` and `experiments/`). Editing it changes Experiment IDs and breaks
  "clone the build → same ID." Freeze → mint → tag is one atomic act.

## Phase 1 — Generate the numbers pack (one command)

```bash
python scripts/tools/article_pack.py <ID> [<ID> ...] > scratch/pack.md
```

This runs every analysis tool over the capsules and emits one Markdown file with:
the X-factor table (mean duration vs a baseline, per scale), the scaling
exponents, and the figures (written to `scratch/figures/`). Every number is
derived from the sealed capsule — **never hand-typed**, so it cannot drift.

Underlying tools, if you need one on its own:

| Tool | Produces |
|---|---|
| `scripts/tools/xfactor.py <ID> [--baseline duckdb]` | X-factor table (row-scaled capsules) |
| `scripts/tools/analyze_scaling.py <ID>` | power-law α per engine (sealed fit) |
| `scripts/tools/plot_scaling.py <ID> ...` | log-log scaling figure (mean points, sealed α) |
| `scripts/tools/plot_threads.py <ID>` | thread-sweep figure |

## Phase 2 — Drop into the act skeleton

One shape per act, reused for every act and every article:

```
Act N — <question>? (capsule <ID>)

  Setup        — what this experiment changes vs the previous act.
  Hypothesis   — a falsifiable claim (something a measurement could refute).
  Test design  — engines, scales, replications; what's held constant.
  Table        — paste from the numbers pack (Phase 1).
  Figure       — paste the figure path (Phase 1).
  Conclusion   — what the numbers showed; was the hypothesis supported?
  Transition   — the question this raises → the next act.
```

Paste the locked numbers into the skeleton. Structure is now decided; there is
nothing left to re-arrange.

## Phase 3 — Write the prose (yours)

Only voice goes in. The numbers and the structure are fixed, so this is writing,
not engineering. Keep the author's voice; the lab supplies the facts.

## Phase 4 — Verify claims, then publish

```bash
python scripts/tools/verify_doc_claims.py --check    # capsule refs resolve to sealed capsules
```

- Every capsule reference resolves to a sealed, tracked capsule (the pre-commit
  hook enforces this when docs/capsules are staged).
- Figure captions name the **mean** (the statistic Phase 0 fixed).
- Set the publication tags; publish.
- For the optional trust proofs (timestamp, signed tag), follow `docs/PUBLISHING.md`.

---

## Why this works

The slowness was never the writing — it was re-deriving and re-checking numbers
mid-prose. Front-loading every number and figure into one generated pack (Phase 1)
and fixing the structure once (Phase 2) means Phase 3 has nothing to interrupt it.
Lock first, write last.
