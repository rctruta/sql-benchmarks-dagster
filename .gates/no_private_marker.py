#!/usr/bin/env python3
"""
no_private_marker — refuse a tracked file that declares itself private.

  .gates/no_private_marker.py              report
  .gates/no_private_marker.py --check      exit 1 on any finding
  .gates/no_private_marker.py --list       show the patterns and exit

The cause: a file says, in its own first lines or its own name, that it must
not be published -- and it is in version control anyway. The author already
made the decision correctly. Nothing read it.

The specimen, MEASURED 2026-10-19 while auditing nine repositories:
sql_benchmarks's scratch/reducing_agent_search_scope.md has a third line
reading "Local draft. Not for the public repo." It was added to a PUBLIC
repository on 2026-07-04 and removed on 2026-07-06, present across thirteen
commits on origin/main. Two more under the same roof: a
convergence_notes_PRIVATE.md and a private_docs/ directory, both of which
stayed local by luck rather than by mechanism.

A check for this already existed -- rctruta.github.io's tools/check_private.py
grew one on 2026-10-15, after data/employment.yaml was committed to a public
repository and the contact-detail patterns passed it clean because the problem
was the file's SUBJECT, not any string in it. But it lived in one repository
and nothing carried it anywhere else, so the repository that actually leaked a
self-declared-private draft never had it. This is that check, promoted.

TWO DIFFERENCES FROM THE ORIGINAL, both learned from the failures above:

  It scans the INDEX, not the staged set. check_private.py reads `git diff
  --cached`, so it sees a file the moment it is added and never again. A file
  already tracked when the gate arrives is invisible to it forever -- the same
  shape as a .gitignore rule, which is consulted only for files git does not
  already track, and which left a tracked draft public for three months.
  A gate that can only catch a file on its way in cannot tell you what is
  already out.

  It reads names as well as headers. convergence_notes_PRIVATE.md declares
  itself in its filename and says nothing in its first lines.

NOT BASELINEABLE. Every other gate here accepts a backlog, because findings
that predate a gate are not a regression. This one does not: the file itself
says it must not be published, so there is no reading under which leaving it
tracked is correct. The escape hatch is ALLOW below -- a named path with a
reason, visible in a diff -- not a baseline file that accumulates silently.

The patterns are derived from the phrasings that actually occur in this
author's notes, not invented. `--list` prints them. Bare "private" is
deliberately absent: it matches ordinary prose, and a gate that cries wolf
gets switched off.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = "no_private_marker"

# Assembled at runtime from fragments. Written as one literal, this file would
# be its own first finding -- the mistake check_wheel.py made with a home-path
# regex, and no_local_paths.py had to carve out an exemption for.
_DECL = [
    (r"\bPRIVATE:\s*do\s+not\s+commit\b",          "PRIVATE: do not commit"),
    (r"\bnever\s+enter\s+the\s+" + r"public\s+repo", "never enter the public repo"),
    (r"\bnot\s+for\s+the\s+" + r"public\s+repo",     "not for the public repo"),
    (r"\bdo\s+not\s+" + r"publish\b",                "do not publish"),
    (r"\blocal\s+draft\b",                            "local draft"),
    # "local only" earns its place from research-backlog.md ("Local only
    # (scratch/ is gitignored)"), but it also appears in ordinary technical
    # prose, so it must look like a declaration: start of a line, optionally
    # after a bullet or emphasis marker.
    (r"^[\s>*_#-]*local\s+only\b",                    "Local only (line-initial)"),
]
# re.M so the line-initial pattern above anchors per line, not per file. An
# inline (?m) cannot sit inside an alternation -- it must be a global flag.
DECLARATION = re.compile("|".join(p for p, _ in _DECL), re.I | re.M)

# A name can declare as loudly as a header. Word-bounded and upper/lower
# tolerant, but not matching "privately" or "deprivation".
NAME_MARKER = re.compile(
    r"(^|[/_.\-])" + r"private($|[/_.\-])" + r"|(^|/)" + r"private_docs?(/|$)"
    r"|(^|[/_.\-])confidential($|[/_.\-])", re.I)

# A declaration is a header, not a mention on page nine -- so there has to be
# some notion of "near the top". The first version used 800 bytes, inherited
# from check_private.py. Two things were wrong with that.
#
# A byte count is not the unit anyone writes in. MEASURED across every real
# declaration in this author's corpus: employment.yaml at byte 2, line 1;
# contact_private.yaml byte 28, line 1; reducing_agent_search_scope.md byte 63,
# line 3; research-backlog.md byte 105, line 4. Lines are what a header is
# counted in, and 20 of them is five times the deepest case.
#
# The worse problem was silence. At byte 801 the gate printed "clean", which
# reads exactly like "this file is safe". A threshold that happens not to bite
# today is still a threshold nobody can see. So the window decides what
# BLOCKS, and the rest of the file is scanned anyway and REPORTED: a
# declaration below the window is never silently dropped, it is just not
# treated as a header. Prose discussing the marker stays non-blocking, which
# is what the window is for, but it is visible rather than invisible.
HEADER_LINES = 20

# The tail scan is bounded, because a tracked file can be a 200 MB CSV. When
# the bound is hit the report says so -- a partial scan that claims to be a
# full one is the same defect as the cliff above, one layer down.
MAX_READ = 1_000_000

SKIP_DIRS = {".git", ".gates", "node_modules", "venv", ".venv", "__pycache__",
             "dist", "build", "site-packages", ".pytest_cache", "scratch"}
# This gate names the patterns it looks for, so it matches itself. Excluding it
# is not a self-exemption: there is nothing here to leak.
SKIP_BASENAMES = {os.path.basename(__file__), "check_private.py"}
TEXT_EXTS = (".md", ".txt", ".yaml", ".yml", ".json", ".py", ".sh", ".html",
             ".css", ".js", ".toml", ".ini", ".cfg", ".rst", ".csv")

# An exemption is a decision in the diff, with a reason, never silence.
ALLOW = [
    # "docs/privacy.md",   # explains the marker; does not carry private data
]


def tracked():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"],
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return [f for f in out.stdout.split("\0") if f]


def main():
    # Refused, not ignored. Every sibling gate takes --baseline, so a caller
    # reaching for it here is following a pattern, and silently reporting
    # instead would look like acceptance.
    if "--baseline" in sys.argv:
        print(f"{GATE}: there is no baseline for this gate.\n\n"
              "Other gates accept a backlog because findings that predate them "
              "are not a\nregression. A file that says it must not be published "
              "is different: there is no\nreading under which leaving it tracked "
              "is correct.\n\n"
              "Untrack it, or -- if the declaration is wrong -- remove the "
              "declaration. To\nexempt a path deliberately, add it to ALLOW in "
              "this file with a reason.", file=sys.stderr)
        sys.exit(2)

    if "--list" in sys.argv:
        print(f"{GATE}: a tracked file is refused when its name, or its first "
              f"{HEADER_LINES} lines,\ncontain one of these:\n")
        for _, label in _DECL:
            print(f"  header  {label}")
        print("  name    PRIVATE / CONFIDENTIAL as a word, or a private_docs/ "
              "directory")
        print("\nDerived from the phrasings that occur in this author's own "
              "notes.")
        return

    files = tracked()
    if files is None:
        print(f"{GATE}: git could not be consulted; nothing verified.",
              file=sys.stderr)
        sys.exit(1)

    findings, below = [], []
    for rel in files:
        if rel in ALLOW or os.path.basename(rel) in SKIP_BASENAMES:
            continue
        if any(p in SKIP_DIRS for p in rel.split(os.sep)):
            continue

        m = NAME_MARKER.search(rel)
        if m:
            findings.append((rel, "its name", m.group(0).strip("/_.-")))
            continue

        if not rel.endswith(TEXT_EXTS):
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                raw = f.read(MAX_READ)
                truncated = len(f.read(1)) > 0
        except Exception:
            continue
        text = raw.decode("utf-8", "ignore")
        lines = text.splitlines()
        header = "\n".join(lines[:HEADER_LINES])

        d = DECLARATION.search(header)
        if d:
            findings.append((rel, f"its own header (line "
                                 f"{header[:d.start()].count(chr(10)) + 1})",
                             d.group(0).strip()))
            continue

        # Below the header: reported, not blocking. The point is that it is
        # never silent.
        rest = "\n".join(lines[HEADER_LINES:])
        d2 = DECLARATION.search(rest)
        if d2:
            ln = HEADER_LINES + rest[:d2.start()].count("\n") + 1
            below.append((rel, ln, d2.group(0).strip(), truncated))

    if not findings and not below:
        print(f"{GATE}: clean "
              f"(headers = first {HEADER_LINES} lines; whole file scanned).")
        return

    if below:
        print(f"\n{GATE}: {len(below)} marker(s) BELOW the first "
              f"{HEADER_LINES} lines — reported, not blocking.")
        for rel, ln, hit, trunc in below:
            print(f"    {rel}:{ln}  {hit!r}"
                  + ("  [file truncated at scan limit]" if trunc else ""))
        print("  A declaration is a header, so these do not block. If one of "
              "them IS a\n  declaration, move it to the top of the file and "
              "this gate will enforce it.")

    if not findings:
        return

    print(f"\n{GATE.upper().replace('_', ' ')}:\n")
    for rel, where, hit in findings:
        print(f"  {rel}\n      declares itself private in {where}: "
              f"{hit!r}\n      and is tracked in git.")
    print("\nThe file already says it must not be published. Move it outside "
          "the repository\nand read it by absolute path, or delete it. If the "
          "declaration is wrong, remove\nthe declaration -- do not leave the "
          "file saying one thing and the index another.")
    print("\nThere is no baseline for this gate. To exempt a path "
          "deliberately, add it to\nALLOW in .gates/no_private_marker.py with "
          "a reason; that edit shows in the diff.\n")

    if "--check" in sys.argv:
        sys.exit(1)


main()
