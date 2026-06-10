# Infrastructure (Actian Vector bench — dormant)

Terraform provisioning for the EC2 instance that hosted **Actian Vector**
during its evaluation period. The Actian engine (`sql_benchmarks/resources/actian.py`)
connects to this box over an SSH tunnel.

**Status: dormant.** The evaluation license has expired; the engine remains
in the codebase as a first-class namespace (`engine_params: {actian: ...}`)
and its tests run fully mocked. This directory is kept as the provisioning
record for reviving the bench.

Caveats if reviving:
- `main.tf` opens ingress from `0.0.0.0/0` for convenience during the original
  evaluation — restrict to your IP before applying.
- Set `ACTIAN_EC2_HOST` and related env vars (see `actian.py`) after apply.
