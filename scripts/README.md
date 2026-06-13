# Scripts

Auxiliary tooling — nothing here is required by the harness itself.

## tools/ — result utilities
- `plot_execution_modes.py` — generate the execution-modes figure (median + min–max bands)
  from a capsule's raw durations; needs matplotlib (`uv pip install matplotlib`, optional dep)
- `analyze_scaling.py` — fit each engine's power-law exponent (complexity class) from a
  capsule's raw fragments; reproducible from any sealed capsule
- `regenerate_dashboard.py` — rebuild the HTML dashboard for an existing experiment capsule
- `extract_results.py` — pull flattened results out of capsules
- `load_parquet_to_local.py` — load staged parquet into a local engine for ad-hoc inspection
- `demo_breach_detection.py` — demonstrates the semantic-audit breach detection

## dev/ — verification helpers
- `verify_capsule.py` — verify a capsule's integrity (seal) AND timestamp (.ots) — see `docs/published_capsules.md`
- `timestamp_capsule.py` — OpenTimestamp a published capsule's seal (publication-time; needs `opentimestamps-client`)
- `verify_portability.py`, `verify_fix_locally.sh` — local verification utilities
