"""Shared baseline handling: adopt a gate without breaking what already runs.

A gate added to an existing repository will fire on code that predates it. That
is not a regression — it is a backlog — but a gate that fails on day one gets
switched off, and a gate that is off catches nothing.

So each gate records the violations that existed when it was adopted:

    .gates/baseline/<gate>.txt     one key per line, committed

From then on the gate reports everything and fails only on keys that are NOT in
the baseline. Old findings stay visible; new ones block. The file may shrink and
should, and every removal is a line in a diff someone can read.

Keys must survive editing, so a key is a path plus the offending value — never
a line number, which moves when anything above it changes.
"""
import os


def _path(root, gate):
    return os.path.join(root, ".gates", "baseline", f"{gate}.txt")


def load(root, gate):
    """The accepted keys. Missing file means nothing is accepted."""
    p = _path(root, gate)
    if not os.path.exists(p):
        return set()
    with open(p) as f:
        return {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}


def save(root, gate, keys, note=""):
    p = _path(root, gate)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(f"# {gate}: findings that predate this gate's adoption.\n"
                f"# They are reported, not enforced. This file may shrink, never grow.\n")
        if note:
            f.write(f"# {note}\n")
        for k in sorted(keys):
            f.write(k + "\n")
    return p


def split(root, gate, found):
    """(new, accepted) — `found` is a dict of key -> printable description."""
    accepted = load(root, gate)
    new = {k: v for k, v in found.items() if k not in accepted}
    old = {k: v for k, v in found.items() if k in accepted}
    return new, old


def record(root, gate, new_count, baselined_count, blocked):
    """No-op ledger recording."""
    pass


def report(gate, new, old, fix_hint):
    """Print both groups. Returns True when something should block."""
    if old:
        print(f"  {len(old)} finding(s) baselined — reported, not blocking.")
    if not new:
        if not old:
            print(f"{gate}: clean.")
        return False
    print(f"\n{gate.upper().replace('_', ' ')}:\n")
    for key in sorted(new):
        print(f"  {new[key]}")
    print(f"\n{fix_hint}\n")
    return True
