# Reproducibility model — design notes (architecture-article material)

Raw material / learning log. Not finished prose. Captures the lab's integrity
model and the reasoning behind it, including a real incident.

## The model

An Experiment ID is the first 8 hex of `SHA-256(parsed config + SQL + measurement code)`.
Reproducibility therefore means: **re-run the config on the build the capsule
records, and you get the same ID** — and results land within the published
min–max bands (cold-cache timings never repeat to the millisecond; the ID does,
the numbers fall in the band). Each capsule stamps its builder in metadata:
`generator: sqlbenchdag@<short-sha>` (a SLSA-style builder identity).

## The incident (2026-06, the lesson)

The four Quack capsules were minted at `sqlbenchdag@1eeedce`. After a week of
edits (config-archival, query embedding, doc fixes — all to *non-measurement*
code), HEAD moved to `7b5082b`. Re-deriving the same configs against HEAD now
yields **different** IDs (b8e2bfaf → ae6dd44f, etc.). Nothing was corrupt: the
ID fingerprints the code, and the code changed. But it exposed that the article's
terse claim "re-run → same ID" is only true *on the recorded build*.

## The counterintuitive conclusion: keep the hash BROAD

It's tempting to "fix" this by narrowing the hash to only measurement-relevant
modules so cosmetic edits stop drifting IDs. **That is the wrong fix for this
lab.** A narrow hash means a measurement-relevant change *outside the allowlist*
would keep the **same ID** — two methodologies, one fingerprint: a *silent*
integrity failure, the exact class this lab exists to expose ("structure is not
security," applied to our own hasher). A broad hash drifts on any code change —
**loud and annoying, but never silent.** For an anti-silent-failure lab,
false-drift (loud) beats false-stability (silent). So the broad hash is correct.

## The real fix: release discipline (process, not code)

The drift was a process bug: we minted, then kept editing. The discipline:

> **Freeze the measurement code → mint the capsules → tag that exact commit, as
> one atomic release act.** Don't edit hashed code after minting a release.

Then "clone the release tag, re-run the config → same ID" holds. During active
development, in-progress IDs are not final; mint final IDs at the release freeze.

## What this means for reproduction (humans and agents)

To reproduce capsule X: check out the build it records (`generator` in
`metadata_<ID>.json`, or the matching signed release tag), run its config, expect
the same ID and results within the bands. Reproduction is against the *recorded
build*, not arbitrary HEAD — by design.

## Deferred (deliberate, post-ship)

A unified re-mint of the published capsules at a single frozen commit, with the
release tag pointing at that same commit, so "clone the tag → reproduce" is
exact. Heavy (recompute IDs, rename, re-seal, re-OTS, re-sign); do it as its own
careful pass, not under ship pressure.
