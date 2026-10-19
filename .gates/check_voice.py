#!/usr/bin/env python3
"""Refuse source files that write about the site's author in the third person.

    python3 tools/check_voice.py          report
    python3 tools/check_voice.py --check  exit 1 on any hit

The failure this exists for. The rule "never write about her in the third
person inside her own project files" was given more than once, and written into
the agent instructions. On 2026-10-16 data/APPLICATION-RULES.md — in this
PUBLIC repository — still read "she presented at an event", "which chair she
was in", "being a tag is what lets her decide". Eleven instances in one
document, plus notes in data/appearances.yaml that render on the live site, and
comments in six generators.

A rule in a document binds nobody. This is the same rule as a script.

Scope is SOURCE files only — data/, tools/, and the markdown at the root.
Generated HTML is downstream: it says "she" because the testimonials it renders
do, and fixing a source fixes the page.

What is allowed, and why:

  quotes      a testimonial is another person's words about her, and changing
              one would be falsifying a quotation. `quote:` lines and
              blockquotes are exempt.
  this file   it has to name the words in order to find them.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

THIRD_PERSON = re.compile(r"(?<![\w'])(she|her|hers)(?![\w'])|Ramona's", re.I)

SCAN_DIRS = ("data", "tools")
SCAN_ROOT_FILES = ("AGENTS.md", "README.md", "CLAUDE.md")
SCAN_EXTS = (".md", ".yaml", ".yml", ".py")

SKIP_BASENAMES = {os.path.basename(__file__), "test_tools.py"}
# A quotation is someone else's sentence. Rewriting it would be a forgery.
QUOTE_LINE = re.compile(r"^\s*(-\s*)?(quote|cite|testimonial)\s*:|^\s*>")
ALLOW = [
    # "data/somefile.yaml",   # an exemption belongs in a diff, never in silence
]


def tracked():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"],
                         capture_output=True, text=True, timeout=30).stdout
    return [f for f in out.split("\0") if f]


def main():
    hits = []
    for rel in tracked():
        if rel in ALLOW or os.path.basename(rel) in SKIP_BASENAMES:
            continue
        in_scope = rel.startswith(SCAN_DIRS) or rel in SCAN_ROOT_FILES
        if not in_scope or not rel.endswith(SCAN_EXTS):
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        for i, line in enumerate(open(path, errors="ignore"), 1):
            if QUOTE_LINE.search(line):
                continue
            m = THIRD_PERSON.search(line)
            if m:
                hits.append((rel, i, m.group(0), line.strip()[:88]))

    if not hits:
        print("check_voice: clean.")
        return 0

    print("\nWRITTEN ABOUT HER IN THE THIRD PERSON:\n", file=sys.stderr)
    for rel, i, word, text in hits:
        print(f"  {rel}:{i}  [{word}]  {text}", file=sys.stderr)
    print("\nThese are her files. Write them in her voice — \"I presented\", not\n"
          "\"she presented\" — or neutrally. A testimonial quote is exempt; put\n"
          "the path in ALLOW if a line genuinely needs third person.\n",
          file=sys.stderr)
    return 1


code = main()
if "--check" in sys.argv:
    sys.exit(code)
