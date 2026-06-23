# Publishing a capsule — the trust-chain checklist

A published capsule carries four independent guarantees. This is the habit that
produces all four. **Run every step from your own checkout** (after `git pull`);
the scripts resolve paths relative to themselves, so they act on whatever
checkout holds the capsule — no dependence on anyone else's working copy.

| Guarantee | How it happens | Required? |
|---|---|---|
| **Reproducibility** | content-addressed Experiment ID | **Automatic** — every run |
| **Integrity** | `integrity.seal` over the capsule | **Automatic** — at finalize |
| **Timestamp** | `integrity.seal.ots` (you stamp it — two phases, below) | **Optional** — publish only |
| **Authorship** | signed git tag (your key) | **Optional** — publish only |

A local or exploratory capsule needs neither optional step — it is still
reproducible and tamper-evident from the two automatic ones.

## Release discipline (why the ID is reproducible)

The Experiment ID hashes the **measurement code** along with the config and SQL —
deliberately broad, so *any* change that could affect a result changes the ID
(loud), never silently keeps it (which would be the integrity hole this lab
exists to expose). The consequence: **freeze the code, mint the capsules, and tag
that exact commit as one act.** Don't edit hashed code after minting a release —
re-running a config on a *different* build yields a *different* ID, by design.
Each capsule also stamps its build (`generator: sqlbenchdag@<sha>` in metadata),
so reproduction is always against the recorded build, not arbitrary HEAD.

## At publish time (once)

```bash
# 1. Run the experiment — capsule is sealed automatically.
./run.sh sql_benchmarks/experiments/queue/<config>.yaml --auto

# 2. Timestamp the seal (submits the hash to the OpenTimestamps calendars).
python scripts/dev/timestamp_capsule.py <id>

# 3. Commit the capsule + proof. results/ is gitignored, so FORCE-add it.
git add -f sql_benchmarks/experiments/results/<id>
git add sql_benchmarks/experiments/configs/config_<id>.yaml   # if present

# 3b. Refresh the experiment catalog (the pre-commit hook enforces this).
python scripts/tools/gen_experiment_catalog.py
git add docs/experiments.md

git commit -m "feat: publish capsule <id> — <one-line finding>"

# 4. Sign the release tag (YOUR key — this is the authorship guarantee).
git tag -s sqlbenchdag-<topic>-v<N>-<YYYYMMDD> -m "<release summary>"
git verify-tag sqlbenchdag-<topic>-v<N>-<YYYYMMDD>     # → Good "git" signature

# 5. Push the branch and the tag.
git push origin <branch>
git push origin sqlbenchdag-<topic>-v<N>-<YYYYMMDD>
```

## A few hours later (finalize the timestamp)

The `.ots` from step 2 is a *calendar promise*. A Bitcoin block confirms it
within hours; only then can it become a self-verifying on-chain proof. This step
is **independent of the signature** — no re-signing.

```bash
git pull                                          # if you stamped on another checkout
python scripts/dev/upgrade_capsule.py <id>        # bakes in the Bitcoin attestation
git commit -am "chore: finalize OTS attestation for <id>"
git push
```

If it still says *pending*, the block hasn't landed — just run it again later.

## Verify any capsule, anytime (no trust required)

```bash
python scripts/dev/verify_capsule.py <id>         # integrity seal + timestamp
git config gpg.ssh.allowedSignersFile .github/allowed_signers
git verify-tag <release-name>                     # authorship
```

> **Why `git add -f`?** `sql_benchmarks/experiments/results/` is a directory-level
> ignore, and git cannot re-include a file whose parent directory is ignored — so
> the `!`-allowlist lines in `.gitignore` are documentation, not the mechanism.
> Force-add is what actually tracks a published capsule.

## Capsule tier & removal (lifecycle)

A committed capsule becomes a catalogued record, so adding is deliberate — and
now reversible.

- **Tier**: declare `meta.tier: verified | exploratory` in the experiment config.
  The catalog (`docs/experiments.md`) shows it, so an *exploratory* capsule can't
  pass as *verified* just by being committed. Capsules that predate this
  convention show **`—` (undeclared)** — they are sealed, so their config can't be
  edited to add a tier without breaking the integrity seal; the curated verified
  set lives in `published_capsules.md`. Declare `tier` on all new capsules.
- **Remove** (the inverse of `git add -f`):

  ```bash
  python scripts/dev/remove_capsule.py <id> [<id> ...]
  ```

  Deletes the capsule dir + its config-registry entry and regenerates the
  catalog. A *tracked* capsule is `git rm`-ed (staged — commit to finalize, so
  it's reversible until then); an untracked/local one is deleted outright. Only
  8-hex IDs are accepted (no path traversal).
