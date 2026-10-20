#!/usr/bin/env python3
"""
check_publish_contract — every publishing surface must carry its own rules.

    python3 scripts/dev/check_publish_contract.py            report
    python3 scripts/dev/check_publish_contract.py --check     exit 1 on a finding
    python3 scripts/dev/check_publish_contract.py --surfaces  list what is declared
    python3 scripts/dev/check_publish_contract.py --release    also run release-stage checks

Reads publish_contract.yaml, which declares each surface this project publishes
to, the file whose presence means that surface is in play, and what must be
true when it is. The header of that file records why it exists; the short
version is that three pieces of required information went missing in one
afternoon and nothing asked for any of them.

THE RULE THIS ENFORCES, and the part that is not standard practice:

  a surface declared `live` whose trigger file is MISSING is a failure
  a surface declared `planned` whose trigger file has APPEARED is a failure

The second is the one that matters. Normally a new package.json arrives, nobody
has written npm publishing rules, and nothing says so -- the gap is silent
until it bites. Here the arrival of the artifact demands its own requirements,
so a surface can be declared years before it exists and still be safe. Nobody
has to remember; the contract becomes loud at exactly the moment it starts to
matter.

The first catches what happened to server.json: a live public listing whose
defining manifest was not on main.

Deliberately small. Three `requires` kinds, because those are the three that
are actually needed. A fourth belongs here when a fourth is needed, not before
-- a rules engine nobody uses is the same mistake one layer up.

Parsed with pyyaml, which this project already depends on. An earlier version
hand-rolled a YAML subset to avoid the dependency and silently dropped three
requirements down to one, which is worse than any dependency.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "publish_contract.yaml"
PYPROJECT = ROOT / "pyproject.toml"

KNOWN_KINDS = (
    "file_exists",
    "json_version_matches_pyproject",
    "yaml_version_matches_pyproject",
    "file_contains_json_field",
)
# Checks that need a built artifact cannot run in a pre-commit hook. A gate
# that fails on every commit for a reason unrelated to the commit gets
# switched off, so a check declares its stage and the runner honours it.
STAGES = ("commit", "release", "any")
KNOWN_STATUS = ("live", "planned")


def parse_contract(text):
    """The contract, via PyYAML.

    The first version hand-rolled a YAML subset parser to avoid a dependency
    in a pre-commit hook. It silently dropped every requirement that followed
    a multi-line `because:` -- mcp-registry reported one requirement where the
    file declares three. A parser that loses rules without saying so is the
    exact failure this tool exists to prevent, so it is gone. pyyaml is
    already a declared dependency of this project and already used by four
    scripts in scripts/.
    """
    import yaml
    data = yaml.safe_load(text) or {}
    surfaces = data.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise SystemExit("check_publish_contract: publish_contract.yaml has no "
                         "`surfaces:` list")
    for s in surfaces:
        s.setdefault("requires", [])
        s.setdefault("checks", [])
        if s.get("requires") is None:
            s["requires"] = []
        if s.get("checks") is None:
            s["checks"] = []
    return surfaces


# --- requirement kinds ------------------------------------------------------

def pyproject_version():
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("check_publish_contract: no version in pyproject.toml")
    return m.group(1)


def _json_at(path, field):
    """Values at `field`, supporting the one list form the contract uses."""
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    if field.startswith("packages[]."):
        leaf = field.split(".", 1)[1]
        return [(f"packages[{i}].{leaf}", p.get(leaf))
                for i, p in enumerate(data.get("packages") or [])]
    return [(field, data.get(field))]


def check_requirement(surface_id, req):
    kind = req.get("kind")
    if kind not in KNOWN_KINDS:
        return [f"{surface_id}: requirement kind {kind!r} is not implemented. "
                f"Known kinds: {', '.join(KNOWN_KINDS)}"]
    path = req.get("path", "")
    out = []

    if kind == "file_exists":
        if not (ROOT / path).exists():
            out.append(f"{surface_id}: {path} is required but missing"
                       + (f" — {req['because']}" if req.get("because") else ""))

    elif kind == "json_version_matches_pyproject":
        if not (ROOT / path).is_file():
            return [f"{surface_id}: {path} is missing, so its version cannot be checked"]
        want = pyproject_version()
        for label, got in _json_at(path, req.get("field", "version")):
            if got != want:
                out.append(f"{surface_id}: {path} {label} is {got!r} but "
                           f"pyproject.toml says {want!r}"
                           + (f" — {req['because']}" if req.get("because") else ""))

    elif kind == "yaml_version_matches_pyproject":
        # CITATION.cff is YAML. Read with pyyaml rather than a regex, because
        # a regex that misses the field reports "clean" instead of "unknown".
        import yaml
        target = ROOT / path
        if not target.is_file():
            return [f"{surface_id}: {path} is missing, so its version cannot be checked"]
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        got = str(data.get(req.get("field", "version"), ""))
        want = pyproject_version()
        if got != want:
            out.append(f"{surface_id}: {path} {req.get('field','version')} is "
                       f"{got!r} but pyproject.toml says {want!r}"
                       + (f" — {req['because']}" if req.get("because") else ""))

    elif kind == "file_contains_json_field":
        src, field = req.get("from", ""), req.get("field", "")
        if not (ROOT / src).is_file():
            return [f"{surface_id}: {src} is missing, so the token cannot be derived"]
        value = json.loads((ROOT / src).read_text(encoding="utf-8")).get(field)
        needle = req.get("template", "{}").replace("{}", str(value))
        target = (ROOT / path)
        if not target.is_file() or needle not in target.read_text(encoding="utf-8", errors="ignore"):
            out.append(f"{surface_id}: {path} must contain {needle!r}, derived "
                       f"from {src} field {field!r}"
                       + (f" — {req['because']}" if req.get("because") else ""))
    return out


def run_checks(surface_id, checks, stage):
    """Run the surface's checks that belong to this stage.

    A check is either a bare path (every stage) or a mapping with `when`.
    """
    out = []
    for entry in checks:
        if isinstance(entry, dict):
            script, when = entry.get("path", ""), entry.get("when", "commit")
            if when not in STAGES:
                out.append(f"{surface_id}: check {script} declares stage "
                           f"{when!r}, not one of {', '.join(STAGES)}")
                continue
            if when != "any" and when != stage:
                continue
        else:
            # A bare path means every stage, which is only safe for a check
            # with no dependencies beyond the standard library.
            script = entry
        target = ROOT / script
        if not target.exists():
            out.append(f"{surface_id}: declared check {script} does not exist")
            continue
        # A test file runs under pytest. A script runs as itself: passing
        # --check to one that does not parse arguments made check_wheel.py
        # treat "--check" as a filename and fail for the wrong reason, which
        # is a check reporting a problem it did not actually find.
        if target.name.startswith("test_"):
            cmd = [sys.executable, "-m", "pytest", str(target), "-q"]
        else:
            accepts = "--check" in target.read_text(encoding="utf-8", errors="ignore")
            cmd = [sys.executable, str(target)] + (["--check"] if accepts else [])
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ROOT)
        except Exception as exc:
            out.append(f"{surface_id}: could not run {script}: {exc}")
            continue
        if p.returncode != 0:
            tail = (p.stdout or p.stderr or "").strip().splitlines()
            out.append(f"{surface_id}: {script} failed — "
                       f"{tail[-1] if tail else 'no output'}")
    return out


def main():
    stage = "release" if "--release" in sys.argv else "commit"
    if not CONTRACT.is_file():
        print(f"check_publish_contract: {CONTRACT.name} is missing. Every "
              f"publishing surface is declared there.", file=sys.stderr)
        return 1
    surfaces = parse_contract(CONTRACT.read_text(encoding="utf-8"))

    if "--surfaces" in sys.argv:
        for s in surfaces:
            present = (ROOT / s.get("trigger", "")).exists()
            print(f"  {s.get('status','?'):8} {s.get('id','?'):16} "
                  f"trigger {s.get('trigger','?')} "
                  f"{'present' if present else 'absent'} "
                  f"({len(s.get('requires', []))} requirement(s), "
                  f"{len(s.get('checks', []))} check(s))")
        return 0

    found = []
    for s in surfaces:
        sid, status, trigger = s.get("id", "?"), s.get("status"), s.get("trigger", "")
        if status not in KNOWN_STATUS:
            found.append(f"{sid}: status {status!r} is not one of "
                         f"{', '.join(KNOWN_STATUS)}")
            continue
        present = bool(trigger) and (ROOT / trigger).exists()

        if status == "live" and not present:
            found.append(
                f"{sid}: declared live, but its trigger {trigger} is missing. "
                f"A published surface whose defining file is not in the tree "
                f"cannot be reproduced — this is what happened to server.json.")
            continue
        if status == "planned" and present:
            found.append(
                f"{sid}: {trigger} now exists, and this surface's rules were "
                f"never written. Fill in `requires` and `checks` for {sid} in "
                f"{CONTRACT.name} and set status: live before publishing.")
            continue
        if status == "planned":
            continue

        for req in s.get("requires", []):
            found += check_requirement(sid, req)
        found += run_checks(sid, s.get("checks", []), stage)

    if not found:
        live = [s["id"] for s in surfaces if s.get("status") == "live"]
        planned = [s["id"] for s in surfaces if s.get("status") == "planned"]
        print(f"check_publish_contract: clean at stage {stage!r}. "
              f"live: {', '.join(live)}; waiting: {', '.join(planned) or 'none'}.")
        return 0

    print("\nPUBLISH CONTRACT:\n")
    for f in found:
        print(f"  {f}")
    print(f"\nDeclared in {CONTRACT.name}. A surface's rules are its own; "
          f"fill them in there.\n")
    return 1 if "--check" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
