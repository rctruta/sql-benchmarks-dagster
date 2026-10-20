#!/bin/sh
# prove_gates.sh — demonstrate that each gate actually FIRES.
# An untested gate is theatre. This is the same discipline as prove_lock.sh.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
G="$ROOT/.gates"
PASS=0; FAIL=0; SKIP=0
# A repository may adopt some gates and not others — this one already had a
# claim gate of its own, so it took only the two new ones. A probe for a gate
# that is not installed is skipped, not failed.
have() { [ -f "$G/$1" ] || { echo "  SKIP  $1 not installed here"; SKIP=$((SKIP+1)); return 1; }; }
ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }

echo "Proving the gates fire..."

if have scan.py; then
# 1. scan.py must BLOCK a banned claim
TMP="$ROOT/.gates/.probe.md"
cp "$G/FACTS.yaml" "$G/FACTS.yaml.bak"
printf 'facts: []\nbanned:\n  - pattern: "ZZPROBE9"\n    reason: "test probe"\nallow: []\n' > "$G/FACTS.yaml"
echo "This document contains ZZPROBE9 which is banned." > "$TMP"
if python3 "$G/scan.py" --check --quiet "$TMP" >/dev/null 2>&1; then
  bad "scan.py did NOT block a banned claim"
else
  ok "scan.py blocks a banned claim"
fi
rm -f "$TMP"; mv "$G/FACTS.yaml.bak" "$G/FACTS.yaml"

# 2. scan.py must PASS a clean file
echo "Nothing objectionable here." > "$TMP"
if python3 "$G/scan.py" --check --quiet "$TMP" >/dev/null 2>&1; then
  ok "scan.py passes a clean file"
else
  bad "scan.py false-positived on a clean file"
fi
rm -f "$TMP"

fi

if have verify.py; then
# 3. verify.py must FAIL a fact whose source does not support it.
# Written as a complete file so it does not depend on where sections sit.
cp "$G/FACTS.yaml" "$G/FACTS.yaml.bak"
echo "this scratch file contains nothing of interest" > "$G/.probe.src"
cat > "$G/FACTS.yaml" <<'YAML'
facts:
  - id: probe_should_fail
    claim: "999999"
    context: "probe"
    status: verified
    source: .gates/.probe.src
    grep: "999999"
banned: []
allow: []
YAML
if python3 "$G/verify.py" --check >/dev/null 2>&1; then
  bad "verify.py did NOT fail an unsupported fact"
else
  ok "verify.py fails an unsupported fact"
fi
mv "$G/FACTS.yaml.bak" "$G/FACTS.yaml"; rm -f "$G/.probe.src"

# 4. checkpoint must REFUSE to save a state whose proof fails
if "$G/checkpoint.sh" save probe_bad "false" >/dev/null 2>&1; then
  bad "checkpoint saved a state whose proof FAILED"
else
  ok "checkpoint refuses a state whose proof fails"
fi

# 5. checkpoint must save when the proof passes, and verify it
if "$G/checkpoint.sh" save probe_good "true" >/dev/null 2>&1 \
   && "$G/checkpoint.sh" verify probe_good >/dev/null 2>&1; then
  ok "checkpoint saves and re-verifies a good state"
else
  bad "checkpoint could not save/verify a good state"
fi
rm -f "$G/checkpoints/probe_good."* 2>/dev/null || true

fi

# 6. the pre-commit hook must exist and be executable
if [ -x "$ROOT/.githooks/pre-commit" ]; then
  ok "pre-commit hook present and executable"
else
  bad "pre-commit hook missing or not executable"
fi

if have no_hardcoding.py; then
# 7. no_hardcoding must BLOCK a value that a data file already holds
PROBE="$ROOT/.gates/.probe"
mkdir -p "$PROBE/data" "$PROBE/tools" "$PROBE/.gates"
cp "$G/no_hardcoding.py" "$G/_baseline.py" "$PROBE/.gates/"   # gate + its baseline helper
printf 'certs:\n  - "Large Language Models - Example Body"\n' > "$PROBE/data/x.yaml"
printf "    f'    <li>Large Language Models &mdash; Example Body, 2023</li>'\n" > "$PROBE/tools/gen.py"
# the gate reads only git-tracked files, so the probe has to be a repository
(cd "$PROBE" && git init -q && git add -A) >/dev/null 2>&1
if python3 "$PROBE/.gates/no_hardcoding.py" --check >/dev/null 2>&1; then
  bad "no_hardcoding did NOT block a value restated from data"
else
  ok "no_hardcoding blocks a value restated from data"
fi
# and must stay quiet when the generator reads its data instead
printf "import yaml  # reads data/x.yaml\n" > "$PROBE/tools/gen.py"
(cd "$PROBE" && git add -A) >/dev/null 2>&1
if python3 "$PROBE/.gates/no_hardcoding.py" --check >/dev/null 2>&1; then
  ok "no_hardcoding is quiet when nothing is restated"
else
  bad "no_hardcoding fired on a clean tree"
fi
rm -rf "$PROBE"

fi

if have no_local_paths.py; then
# 8. no_local_paths must BLOCK one machine's absolute path in a tracked file
LPROBE="$ROOT/.gates/.lprobe"
mkdir -p "$LPROBE/.gates"
cp "$G/no_local_paths.py" "$G/_baseline.py" "$LPROBE/.gates/"
# The planted path is assembled at runtime. Written literally, this file would
# itself be a violation — and it is installed into every seeded project, so it
# blocked the first commit of a fresh one. A fixture must not be
# indistinguishable from the thing it tests for.
HOMEISH="/U""sers/someone/Projects/theirs/README.md"
(cd "$LPROBE" && git init -q && printf 'OUT = "%s"\n' "$HOMEISH" > w.py && git add -A) >/dev/null 2>&1
if python3 "$LPROBE/.gates/no_local_paths.py" --check >/dev/null 2>&1; then
  bad "no_local_paths did NOT block a home path"
else
  ok "no_local_paths blocks a home path in a tracked file"
fi
rm -rf "$LPROBE"

fi

if have no_hardcoding.py; then
# 9. the baseline must accept old findings and still block new ones. This is
#    what makes a gate adoptable in a repository that predates it.
BPROBE="$ROOT/.gates/.bprobe"
mkdir -p "$BPROBE/.gates" "$BPROBE/data" "$BPROBE/tools"
cp "$G/no_hardcoding.py" "$G/_baseline.py" "$BPROBE/.gates/"
printf 'certs:\n  - "An Old Finding - Example Body"\n' > "$BPROBE/data/x.yaml"
printf "    f'<li>An Old Finding &mdash; Example Body, 2023</li>'\n" > "$BPROBE/tools/gen.py"
(cd "$BPROBE" && git init -q && git add -A) >/dev/null 2>&1
python3 "$BPROBE/.gates/no_hardcoding.py" --baseline >/dev/null 2>&1
if python3 "$BPROBE/.gates/no_hardcoding.py" --check >/dev/null 2>&1; then
  ok "baseline accepts a finding that predates the gate"
else
  bad "baseline did NOT accept a pre-existing finding"
fi
printf 'certs:\n  - "An Old Finding - Example Body"\n  - "A New Finding - Other Body"\n' > "$BPROBE/data/x.yaml"
printf "    f'<li>An Old Finding &mdash; Example Body, 2023</li>'\n    f'<li>A New Finding &mdash; Other Body</li>'\n" > "$BPROBE/tools/gen.py"
(cd "$BPROBE" && git add -A) >/dev/null 2>&1
if python3 "$BPROBE/.gates/no_hardcoding.py" --check >/dev/null 2>&1; then
  bad "baseline swallowed a NEW finding"
else
  ok "baseline still blocks a new finding"
fi
rm -rf "$BPROBE"

fi

# ---------------------------------------------------------------- voice -----
# Born in rctruta.github.io 2026-10-16: APPLICATION-RULES.md, in a PUBLIC
# repository, read "she presented at an event" and "which chair she was in" --
# eleven instances, after the rule had been given more than once in prose and
# written into the agent instructions.
if have check_voice.py; then
  VP="$(mktemp -d)"
  mkdir -p "$VP/.gates" "$VP/data" "$VP/tools"
  cp "$G/check_voice.py" "$VP/.gates/"
  (cd "$VP" && git init -q) >/dev/null 2>&1

  printf 'items:\n  - note: "I presented at an event."\n' > "$VP/data/x.yaml"
  (cd "$VP" && git add -A) >/dev/null 2>&1
  if (cd "$VP" && python3 .gates/check_voice.py --check) >/dev/null 2>&1; then
    ok "check_voice quiet on first-person data"
  else
    bad "check_voice fired on first-person data"
  fi

  printf 'items:\n  - note: "she presented at an event, and her slides are here."\n' > "$VP/data/x.yaml"
  (cd "$VP" && git add -A) >/dev/null 2>&1
  if (cd "$VP" && python3 .gates/check_voice.py --check) >/dev/null 2>&1; then
    bad "check_voice MISSED third person in a data file"
  else
    ok "check_voice refuses third person in a data file"
  fi

  # A quotation is someone else's sentence; rewriting one would be a forgery.
  printf 'testimonials:\n  - quote: "She was the best instructor I had."\n' > "$VP/data/x.yaml"
  (cd "$VP" && git add -A) >/dev/null 2>&1
  if (cd "$VP" && python3 .gates/check_voice.py --check) >/dev/null 2>&1; then
    ok "check_voice exempts a quoted testimonial"
  else
    bad "check_voice flagged a quotation, which it must not rewrite"
  fi
  rm -rf "$VP"
fi

# ---------------------------------------------------------------- wheel -----
# Born in sql-benchmarks-dagster 2026-10-19: sqlbenchdag 0.1.2 went to PyPI
# with 881 files that were not the package -- build/ nested six deep, venv/,
# tests/, and scratch/, twelve unrelated local scripts carrying home-directory
# paths. 82% of the download, and `python -m build` exited 0 throughout.
if have check_wheel.py; then
  WP="$(mktemp -d)"
  mkdir -p "$WP/dist"
  cp "$G/check_wheel.py" "$WP/"

  # Assembled, never literal: this file is installed into every seeded
  # project, and a fixture indistinguishable from what it tests for blocks the
  # first commit of a fresh one. Same lesson as the no_local_paths probe above.
  HOMEISH="/U""sers/someone/Projects/thing"
  python3 - "$WP" "$HOMEISH" <<'MKWHL'
import sys, zipfile, os
d, HOMEISH = sys.argv[1], sys.argv[2]
def build(name, extra):
    with zipfile.ZipFile(os.path.join(d, "dist", name), "w") as z:
        z.writestr("sql_benchmarks/__init__.py", "x = 1\n")
        z.writestr("pkg-0.1.dist-info/METADATA", "Name: pkg\n")
        for p, body in extra:
            z.writestr(p, body)
build("clean-0.1-py3-none-any.whl", [])
build("dirty-0.1-py3-none-any.whl",
      [("scratch/notes.py", "P = '" + HOMEISH + "'\n")])
MKWHL

  if python3 "$WP/check_wheel.py" "$WP/dist/clean-0.1-py3-none-any.whl" >/dev/null 2>&1; then
    ok "check_wheel passes a wheel holding only the package"
  else
    bad "check_wheel rejected a clean wheel"
  fi
  if python3 "$WP/check_wheel.py" "$WP/dist/dirty-0.1-py3-none-any.whl" >/dev/null 2>&1; then
    bad "check_wheel MISSED scratch/ and a home path in the wheel"
  else
    ok "check_wheel refuses a wheel carrying scratch/ and a home path"
  fi
  rm -rf "$WP"
fi

# --------------------------------------------------------------- orphans ----
# The cause: code exists, is tested, and is wired to nothing, so a passing test
# certifies a feature that never runs. Specimen, 2026-06-15: a DDL generator
# producing PK/index/FK statements from the config, with a passing unit test,
# imported by nothing in the live path -- so `primary_key: true` in every
# config was declared-but-unenforced behind a green tick.
if have no_orphans.py; then
  OP="$(mktemp -d)"
  mkdir -p "$OP/.gates" "$OP/pkg/plugins" "$OP/tests" "$OP/conf"
  cp "$G/no_orphans.py" "$G/_baseline.py" "$OP/.gates/"
  (cd "$OP" && git init -q) >/dev/null 2>&1

  printf 'def used(): return 1\n' > "$OP/pkg/helper.py"
  printf 'from pkg.helper import used\ndef run(): return used()\n' > "$OP/pkg/live.py"
  printf 'class Gen:\n    def sql(self): return "CREATE INDEX"\n' > "$OP/pkg/ddl.py"
  printf 'from pkg.ddl import Gen\ndef test_g(): assert Gen().sql()\n' > "$OP/tests/test_ddl.py"
  (cd "$OP" && git add -A) >/dev/null 2>&1

  if (cd "$OP" && python3 .gates/no_orphans.py --check) >/dev/null 2>&1; then
    bad "no_orphans MISSED a module only its own test imports"
  else
    ok "no_orphans refuses a module only its own test imports"
  fi

  # Live code importing it must clear the finding.
  printf 'from pkg.ddl import Gen\ndef wire(): return Gen()\n' >> "$OP/pkg/live.py"
  (cd "$OP" && git add -A) >/dev/null 2>&1
  if (cd "$OP" && python3 .gates/no_orphans.py --check) >/dev/null 2>&1; then
    ok "no_orphans goes quiet once live code imports it"
  else
    bad "no_orphans still fired after the module was wired in"
  fi

  # A plugin resolved by dotted string from a config is reached without any
  # import statement, and is not an orphan.
  printf 'def generate(): return []\n' > "$OP/pkg/plugins/gen.py"
  printf 'from pkg.plugins.gen import generate\ndef test_p(): assert generate()==[]\n' > "$OP/tests/test_p.py"
  printf 'dataset:\n  source: pkg.plugins.gen\n' > "$OP/conf/e.yaml"
  (cd "$OP" && git add -A) >/dev/null 2>&1
  if (cd "$OP" && python3 .gates/no_orphans.py --check) >/dev/null 2>&1; then
    ok "no_orphans spares a plugin named in a config"
  else
    bad "no_orphans flagged a plugin a config resolves by name"
  fi

  # The bug this case pins: a relative import was invisible, so the first
  # version reported sixteen orphans in a working repository -- every one of
  # them imported by a sibling with `from .x import Y`.
  mkdir -p "$OP/pkg/resources"
  printf '' > "$OP/pkg/resources/__init__.py"
  printf 'class Duck:\n    pass\n' > "$OP/pkg/resources/duck.py"
  printf 'from .duck import Duck\nclass Quack(Duck):\n    pass\n' > "$OP/pkg/resources/quack.py"
  printf 'from pkg.resources.duck import Duck\ndef test_d(): assert Duck\n' > "$OP/tests/test_duck.py"
  printf 'from pkg.resources.quack import Quack\ndef hold(): return Quack\n' >> "$OP/pkg/live.py"
  (cd "$OP" && git add -A) >/dev/null 2>&1
  if (cd "$OP" && python3 .gates/no_orphans.py --check) >/dev/null 2>&1; then
    ok "no_orphans resolves a relative import and spares the sibling"
  else
    bad "no_orphans flagged a module imported relatively by a sibling"
  fi
  rm -rf "$OP"
fi

# -------------------------------------------------------------- scratch -----
# Born 2026-10-19 from a survey of nine repositories: harness-bench carried
# `scratch/` on line 25 of .gitignore AND scratch/skills-antipattern-final.md
# tracked in HEAD since July, in a PUBLIC repository. An ignore rule is
# consulted only for files git does not already track, so it had been silent
# for three months. These probes assert the arrangement that makes the rule
# unnecessary -- notes outside the worktree, where git refuses to stage them.
if have scratch_external.py; then
  SP="$(mktemp -d)"; SX="$(mktemp -d)"
  mkdir -p "$SP/.gates"
  cp "$G/scratch_external.py" "$G/_baseline.py" "$SP/.gates/"
  (cd "$SP" && git init -q && git commit -q --allow-empty -m init) >/dev/null 2>&1

  # 1. No notes folder at all. This gate refuses a leaky one; it does not
  #    demand one exist, or every repository would fail on adoption.
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    ok "scratch_external quiet when there is no notes folder"
  else
    bad "scratch_external fired on a repository with no notes folder"
  fi

  # 2. The arrangement it exists to enforce: outside the worktree, ignored.
  mkdir -p "$SX/notes-store"
  ln -s "$SX/notes-store" "$SP/scratch"
  echo "a private draft" > "$SX/notes-store/draft.md"
  printf 'scratch\n' > "$SP/.gitignore"
  (cd "$SP" && git add -A) >/dev/null 2>&1
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    ok "scratch_external quiet on an external, ignored notes folder"
  else
    bad "scratch_external fired on the arrangement it is meant to accept"
  fi

  # 3. git must refuse to stage through the link. This is the guarantee the
  #    whole design rests on, so it is proven here and not assumed.
  if (cd "$SP" && git add scratch/draft.md) >/dev/null 2>&1; then
    bad "git staged a file through the symlink -- the design premise is wrong"
  else
    ok "git refuses to stage a file through the symlink"
  fi

  # 4. A real directory inside the worktree: nothing has leaked, but the
  #    contents are one `git add -A` away from it.
  rm "$SP/scratch"; mkdir -p "$SP/scratch"
  echo "a private draft" > "$SP/scratch/draft.md"
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    bad "scratch_external MISSED a real notes directory in the worktree"
  else
    ok "scratch_external refuses a real notes directory in the worktree"
  fi

  # 5. The symlink that points back inside the worktree -- the arrangement
  #    that looks right and defeats itself.
  rm -rf "$SP/scratch"; mkdir -p "$SP/inside"
  ln -s ./inside "$SP/scratch"
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    bad "scratch_external MISSED a symlink resolving inside the worktree"
  else
    ok "scratch_external refuses a symlink resolving inside the worktree"
  fi
  rm -rf "$SP/scratch" "$SP/inside"

  # 6. The specimen itself, reproduced exactly: a note tracked in the index
  #    while .gitignore names the folder. The rule is present and powerless.
  mkdir -p "$SP/scratch"
  echo "a private draft" > "$SP/scratch/draft.md"
  (cd "$SP" && git add -f scratch/draft.md && git commit -q -m "the specimen") >/dev/null 2>&1
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    bad "scratch_external MISSED a tracked note that .gitignore claims to cover"
  else
    ok "scratch_external refuses a tracked note despite the ignore rule"
  fi

  # 7. --baseline must REFUSE while that note is tracked. A baseline records a
  #    backlog; an already-published private note is not a backlog, and
  #    accepting it would launder the leak into a committed approval.
  if (cd "$SP" && python3 .gates/scratch_external.py --baseline) >/dev/null 2>&1; then
    bad "scratch_external baselined a TRACKED note -- it must refuse"
  else
    ok "scratch_external refuses to baseline a tracked note"
  fi
  [ -f "$SP/.gates/baseline/scratch_external.txt" ] \
    && bad "scratch_external wrote a baseline file while refusing" \
    || ok "scratch_external wrote no baseline file when it refused"

  # 8. Untrack it, and the structural finding alone IS baselineable -- so a
  #    repository can adopt the gate mid-migration without blocking commits.
  (cd "$SP" && git rm -q --cached scratch/draft.md) >/dev/null 2>&1
  if (cd "$SP" && python3 .gates/scratch_external.py --baseline) >/dev/null 2>&1; then
    ok "scratch_external baselines a structural finding once nothing is tracked"
  else
    bad "scratch_external refused to baseline a purely structural finding"
  fi
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    ok "scratch_external passes once the structural finding is baselined"
  else
    bad "scratch_external still blocked after its finding was baselined"
  fi

  # 9. The baseline must not swallow a NEW tracked note afterwards.
  echo "another private draft" > "$SP/scratch/second.md"
  (cd "$SP" && git add -f scratch/second.md) >/dev/null 2>&1
  if (cd "$SP" && python3 .gates/scratch_external.py --check) >/dev/null 2>&1; then
    bad "the baseline swallowed a newly tracked note"
  else
    ok "scratch_external still blocks a newly tracked note after baselining"
  fi
  rm -rf "$SP" "$SX"
fi

# ------------------------------------------------------- private marker -----
# Born 2026-10-19 from the audit that followed scratch_external. The specimen:
# sql-benchmarks-dagster/scratch/reducing_agent_search_scope.md, whose third
# line reads "Local draft. Not for the public repo.", was on origin/main of a
# PUBLIC repository from 2026-07-04 to 2026-07-06, across thirteen commits.
# rctruta.github.io already had this check in tools/check_private.py, but it
# lived in one repository and nothing carried it anywhere else.
if have no_private_marker.py; then
  MP="$(mktemp -d)"
  mkdir -p "$MP/.gates" "$MP/docs"
  cp "$G/no_private_marker.py" "$MP/.gates/"
  (cd "$MP" && git init -q && git commit -q --allow-empty -m init) >/dev/null 2>&1

  # 1. Clean tree.
  printf '# Readme\n\nOrdinary content.\n' > "$MP/docs/readme.md"
  (cd "$MP" && git add -A) >/dev/null 2>&1
  if (cd "$MP" && python3 .gates/no_private_marker.py --check) >/dev/null 2>&1; then
    ok "no_private_marker quiet on an ordinary tracked file"
  else
    bad "no_private_marker fired on an ordinary tracked file"
  fi

  # 2. The real specimen's own words, in a file outside any notes folder --
  #    which is the point: scratch_external covers notes by location, this
  #    covers a declaration anywhere in the tree.
  printf '# Methodology note\n\n*2026-07-04. Local draft. Not for the public repo.*\n' \
    > "$MP/docs/draft.md"
  (cd "$MP" && git add -A) >/dev/null 2>&1
  if (cd "$MP" && python3 .gates/no_private_marker.py --check) >/dev/null 2>&1; then
    bad "no_private_marker MISSED a header declaring the file private"
  else
    ok "no_private_marker refuses a file whose header declares it private"
  fi
  (cd "$MP" && git rm -q --cached docs/draft.md) >/dev/null 2>&1
  rm -f "$MP/docs/draft.md"

  # 3. A declaration in the NAME, with nothing in the header. This is how
  #    convergence_notes_PRIVATE.md declares itself.
  printf 'Nothing in here says anything about publication.\n' \
    > "$MP/docs/convergence_notes_PRIVATE.md"
  (cd "$MP" && git add -A) >/dev/null 2>&1
  if (cd "$MP" && python3 .gates/no_private_marker.py --check) >/dev/null 2>&1; then
    bad "no_private_marker MISSED a filename declaring the file private"
  else
    ok "no_private_marker refuses a file whose NAME declares it private"
  fi
  (cd "$MP" && git rm -q --cached docs/convergence_notes_PRIVATE.md) >/dev/null 2>&1
  rm -f "$MP/docs/convergence_notes_PRIVATE.md"

  # 4. The difference from check_private.py, which reads `git diff --cached`
  #    and so sees a file once, on the way in. A file COMMITTED before this
  #    gate existed is never staged again, and a staged-only check can never
  #    tell you what is already out. Same shape as a .gitignore rule.
  printf '# Old note\n\nPRIVATE: do not commit\n' > "$MP/docs/old.md"
  (cd "$MP" && git add -A && git commit -q -m "committed before the gate") >/dev/null 2>&1
  if (cd "$MP" && python3 .gates/no_private_marker.py --check) >/dev/null 2>&1; then
    bad "no_private_marker MISSED an ALREADY-COMMITTED private file"
  else
    ok "no_private_marker refuses a private file committed before it existed"
  fi

  # 5. No baseline, and it must say so rather than quietly reporting -- every
  #    sibling gate takes --baseline, so a caller will reach for it here.
  if (cd "$MP" && python3 .gates/no_private_marker.py --baseline) >/dev/null 2>&1; then
    bad "no_private_marker accepted --baseline; this gate must refuse it"
  else
    ok "no_private_marker refuses --baseline"
  fi
  [ -f "$MP/.gates/baseline/no_private_marker.txt" ] \
    && bad "no_private_marker wrote a baseline file" \
    || ok "no_private_marker wrote no baseline file"
  (cd "$MP" && git rm -q --cached docs/old.md && git commit -q -m untrack) >/dev/null 2>&1
  rm -f "$MP/docs/old.md"

  # 6. UNTRACKED is fine. The notes this protects are meant to exist -- just
  #    not in the index. A gate that fired on them would be unusable.
  printf 'PRIVATE: do not commit\n' > "$MP/docs/local_note.md"
  if (cd "$MP" && python3 .gates/no_private_marker.py --check) >/dev/null 2>&1; then
    ok "no_private_marker ignores an untracked private file"
  else
    bad "no_private_marker fired on an UNTRACKED file, which is allowed"
  fi
  rm -f "$MP/docs/local_note.md"

  # 7. The false-positive guard. A declaration is a header; prose discussing
  #    the marker on page nine is not a declaration. GATES.md and this very
  #    probe file both quote these phrases, and neither is private.
  python3 - "$MP/docs/essay.md" <<'PYEOF'
import sys
pad = "Ordinary prose about publishing workflows. " * 40
open(sys.argv[1], "w").write(
    "# An essay about publication rules\n\n" + pad +
    "\n\nSome authors write PRIVATE: do not commit at the top of a draft.\n")
PYEOF
  (cd "$MP" && git add -A) >/dev/null 2>&1
  if (cd "$MP" && python3 .gates/no_private_marker.py --check) >/dev/null 2>&1; then
    ok "no_private_marker ignores the phrase far below the header"
  else
    bad "no_private_marker flagged prose that merely mentions the marker"
  fi
  rm -rf "$MP"
fi

echo
echo "gates proven: $PASS passed, $FAIL failed, $SKIP not installed"
[ "$FAIL" -eq 0 ] || exit 1
