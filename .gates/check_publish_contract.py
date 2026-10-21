#!/usr/bin/env python3
"""
check_publish_contract — every publishing surface must carry its own rules.

    python3 .gates/check_publish_contract.py            report
    python3 .gates/check_publish_contract.py --check     exit 1 on a finding
    python3 .gates/check_publish_contract.py --surfaces  list what is declared
    python3 .gates/check_publish_contract.py --stage prepublish
    python3 .gates/check_publish_contract.py --stage postbuild

Reads publish_contract.toml, which declares each surface this project publishes
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

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = Path(__file__).resolve().parent / "publish_contract.toml"

# A check names the moments it runs at. Three, because that is how many
# distinct moments exist and the earlier two-stage model hid one of them:
#
#   commit      the pre-commit hook, where the project's dependencies exist
#   prepublish  the release job BEFORE the build -- no project dependencies,
#               no wheel yet. The 0.1.4 release failed three times here,
#               because this moment was being treated as "commit" and so ran
#               a pytest check in a job that has no pytest.
#   postbuild   the release job AFTER the build, where dist/ exists
#
STAGE_COMMIT, STAGE_PREPUBLISH, STAGE_POSTBUILD = "commit", "prepublish", "postbuild"
STAGES = (STAGE_COMMIT, STAGE_PREPUBLISH, STAGE_POSTBUILD)

KNOWN_KINDS = (
    "file_exists",
    "json_version_matches_source",
    "yaml_version_matches_source",
    "file_contains_json_field",
)

# Which file holds the version every other file must agree with. Declared in
# the contract rather than assumed, because a Python project keeps it in
# pyproject.toml, a Node one in package.json, a Rust one in Cargo.toml, and a
# repository that publishes nothing has no version at all.
DEFAULT_VERSION_SOURCE = {"path": "pyproject.toml", "kind": "toml_project_version"}

#: Set from the contract by parse_contract(). A module global rather than a
#: parameter threaded through every check, because every comparison in the
#: file is against the same single source and passing it around would invite
#: one call site using a different one.
VERSION_SOURCE = dict(DEFAULT_VERSION_SOURCE)
KNOWN_STATUS = ("live", "planned")


def parse_contract(text):
    """The contract, via tomllib.

    Two earlier attempts, both wrong:

    A hand-rolled YAML subset parser, to avoid a dependency in a pre-commit
    hook. It silently dropped every requirement that followed a multi-line
    value -- one surface reported a single requirement where the file declared
    three. A parser that loses rules without saying so is the exact failure
    this tool exists to prevent.

    Then pyyaml, which is correct but is a dependency. In one project that was
    fine. In this registry it is not: a gate here runs in a freshly
    bootstrapped repository that has installed nothing, and it broke
    init-agent-project outright -- the pre-commit hook crashed on
    ModuleNotFoundError and the first commit never happened.

    tomllib has been in the standard library since Python 3.11, parses a real
    documented format, and keeps comments -- which matters, because most of
    this contract's value is the reasons written beside the rules.
    """
    import tomllib
    try:
        data = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        hint = ""
        if "immutable namespace" in str(exc):
            hint = ("\n\nAlmost certainly an inline `requires = []` or "
                    "`checks = []` left in place.\nTOML makes an inline array "
                    "immutable, so a later [[surfaces.requires]]\nblock cannot "
                    "extend it. Delete the inline line and keep the blocks.")
        raise SystemExit(f"check_publish_contract: {CONTRACT.name} is not "
                         f"valid TOML: {exc}{hint}")
    global VERSION_SOURCE
    declared = data.get("version_source")
    if declared:
        missing = [k for k in ("path", "kind") if k not in declared]
        if missing:
            raise SystemExit(f"check_publish_contract: version_source is "
                             f"missing {missing}")
        VERSION_SOURCE = declared
    surfaces = data.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        raise SystemExit("check_publish_contract: publish_contract.toml has no "
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

def source_version(spec):
    """The one version everything else is compared against.

    Fails loudly when the declared source is missing or has no version. A
    checker that quietly treats "no source" as "nothing to compare" would
    report clean on a repository whose versions all disagree.
    """
    path, kind = spec.get("path", ""), spec.get("kind", "")
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(f"check_publish_contract: version_source {path!r} "
                         f"does not exist. Declare the file that holds this "
                         f"project's version in {CONTRACT.name}.")
    text = target.read_text(encoding="utf-8")
    if kind == "toml_project_version":
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    elif kind == "json_version":
        import json as _json
        v = _json.loads(text).get("version")
        return str(v) if v else _fail(path)
    elif kind == "yaml_version":
        # Same reasoning as above: no pyyaml, and a miss is loud.
        m = re.search(r'^version:\s*["\']?([^"\'\s#]+)', text, re.M)
        return m.group(1) if m else _fail(path)
    else:
        raise SystemExit(f"check_publish_contract: version_source kind "
                         f"{kind!r} is not implemented. Known: "
                         f"toml_project_version, json_version, yaml_version.")
    return m.group(1) if m else _fail(path)


def _fail(path):
    raise SystemExit(f"check_publish_contract: no version found in {path}")


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

    elif kind == "json_version_matches_source":
        if not (ROOT / path).is_file():
            return [f"{surface_id}: {path} is missing, so its version cannot be checked"]
        want = source_version(VERSION_SOURCE)
        for label, got in _json_at(path, req.get("field", "version")):
            if got != want:
                out.append(f"{surface_id}: {path} {label} is {got!r} but "
                           f"{VERSION_SOURCE['path']} says {want!r}"
                           + (f" — {req['because']}" if req.get("because") else ""))

    elif kind == "yaml_version_matches_source":
        # CITATION.cff is YAML, and a gate here must not import pyyaml: this
        # runs in a release job and in freshly bootstrapped repositories that
        # have installed nothing. A regex that MISSES the field would report
        # "clean" instead of "unknown", which is the worse failure -- so the
        # field is matched at line start and its absence is a finding, never a
        # pass. That is the whole difference between a cheap parser being
        # acceptable and being a liability.
        target = ROOT / path
        if not target.is_file():
            return [f"{surface_id}: {path} is missing, so its version cannot be checked"]
        field = req.get("field", "version")
        m = re.search(rf'^{re.escape(field)}:\s*["\']?([^"\'\s#]+)',
                      target.read_text(encoding="utf-8"), re.M)
        if not m:
            return [f"{surface_id}: {path} has no top-level {field!r} line. "
                    f"It is required here, so its absence is a finding rather "
                    f"than a pass."]
        got = m.group(1)
        want = source_version(VERSION_SOURCE)
        if got != want:
            out.append(f"{surface_id}: {path} {req.get('field','version')} is "
                       f"{got!r} but {VERSION_SOURCE['path']} says {want!r}"
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
    """Run the surface's checks whose `stages` include this stage.

    `stages` is required and must be explicit. A default would be a guess
    about where a check can run, and guessing that is what made the 0.1.4
    release fail three times.
    """
    out = []
    for entry in checks:
        if not isinstance(entry, dict) or "path" not in entry:
            out.append(f"{surface_id}: each check needs a mapping with `path` "
                       f"and `stages`, got {entry!r}")
            continue
        script = entry["path"]
        declared = entry.get("stages")
        if not declared:
            out.append(f"{surface_id}: check {script} declares no `stages`. "
                       f"Name them explicitly: {', '.join(STAGES)}")
            continue
        unknown = [d for d in declared if d not in STAGES]
        if unknown:
            out.append(f"{surface_id}: check {script} declares unknown "
                       f"stage(s) {unknown}; known: {', '.join(STAGES)}")
            continue
        if stage not in declared:
            continue
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
    stage = STAGE_COMMIT
    if "--stage" in sys.argv:
        stage = sys.argv[sys.argv.index("--stage") + 1]
        if stage not in STAGES:
            print(f"check_publish_contract: unknown stage {stage!r}; "
                  f"expected one of {', '.join(STAGES)}", file=sys.stderr)
            return 2
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
