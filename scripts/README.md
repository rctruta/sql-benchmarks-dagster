# Scripts

Auxiliary tooling — nothing here is required by the harness itself.

## tools/ — result utilities
- `regenerate_dashboard.py` — rebuild the HTML dashboard for an existing experiment capsule
- `extract_results.py` — pull flattened results out of capsules
- `load_parquet_to_local.py` — load staged parquet into a local engine for ad-hoc inspection
- `demo_breach_detection.py` — demonstrates the semantic-audit breach detection

## dev/ — verification helpers
- `verify_capsule.py` — integrity-check a results capsule (see `docs/integrity_sealing.md`)
- `verify_portability.py`, `verify_fix_locally.sh` — local verification utilities
