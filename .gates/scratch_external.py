#!/usr/bin/env python3
"""
scratch_external — verify that local scratch directories reside outside the worktree.

Usage:
    python3 .gates/scratch_external.py              report
    python3 .gates/scratch_external.py --check      exit 1 on anything not baselined
    python3 .gates/scratch_external.py --baseline   accept structural findings

Ensures any local scratch/ directory is either absent or externally symlinked and
ignored by git, preventing accidental staging of local scratch notes.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _baseline

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = "scratch_external"

# One tuple so adding another notes folder is a one-line decision in a diff.
NOTE_DIRS = ("scratch", "notes", "drafts")


def git(*args):
    """stdout, or None when git itself failed -- never silently empty."""
    try:
        p = subprocess.run(["git", "-C", ROOT, *args],
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return p.stdout if p.returncode == 0 else None


def tracked_under(name):
    out = git("ls-files", "-z", "--", name)
    if out is None:
        return None
    return [f for f in out.split("\0") if f]


def ignored(name):
    """True when git would ignore this path. None when git could not say."""
    try:
        p = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", "--", name],
                           capture_output=True, timeout=30)
    except Exception:
        return None
    if p.returncode in (0, 1):
        return p.returncode == 0
    return None                      # 128: not a repository, or worse


def inspect(name):
    """(hard, soft) findings for one notes folder."""
    path = os.path.join(ROOT, name)
    hard, soft = {}, {}

    files = tracked_under(name)
    if files is None:
        soft[f"{name}\tgit-unavailable"] = (
            f"{name}: git could not be consulted, so nothing here is verified.")
        return hard, soft
    for f in files:
        hard[f"{f}\ttracked"] = (
            f"{f}\n      tracked in the index. A local note is in version "
            f"control;\n      .gitignore does not apply to a file git already "
            f"carries.\n      Fix:  git rm --cached {f}")

    exists = os.path.islink(path) or os.path.exists(path)
    if not exists:
        return hard, soft            # nothing to arrange

    if not os.path.islink(path):
        soft[f"{name}\tnot-a-symlink"] = (
            f"{name}/ is a real directory inside the worktree, so its contents "
            f"can be staged.\n      Fix:  mv {name} ~/scratch/<repo> && ln -s "
            f"~/scratch/<repo> {name}")
    else:
        target = os.path.realpath(path)
        root_real = os.path.realpath(ROOT)
        if target == root_real or target.startswith(root_real + os.sep):
            soft[f"{name}\tinside-worktree"] = (
                f"{name} -> {os.readlink(path)}\n      resolves to "
                f"{os.path.relpath(target, root_real)} INSIDE the worktree, so "
                f"git can still reach it.\n      Point it outside the "
                f"repository.")
        elif not os.path.exists(target):
            soft[f"{name}\tdangling"] = (
                f"{name} -> {os.readlink(path)}\n      points at nothing. Notes "
                f"written here go to a path that does not exist.")

    isig = ignored(name)
    if isig is None:
        soft[f"{name}\tignore-unknown"] = (
            f"{name}: git could not say whether this path is ignored.")
    elif not isig:
        soft[f"{name}\tnot-ignored"] = (
            f"{name} is not gitignored, so the link itself can be committed.\n"
            f"      Harmless beside the notes, but it publishes where they live."
            f"\n      Fix:  echo '{name}' >> .gitignore")

    return hard, soft


def main():
    hard, soft = {}, {}
    for name in NOTE_DIRS:
        h, s = inspect(name)
        hard.update(h)
        soft.update(s)

    if "--baseline" in sys.argv:
        # Refusing here is the gate's one real opinion. A baseline is for a
        # backlog, and an already-published private note is not a backlog.
        if hard:
            print(f"{GATE}: REFUSED to baseline.\n")
            for key in sorted(hard):
                print(f"  {hard[key]}")
            print("\nA tracked note is already in version control. Baselining it "
                  "would record\nthe leak as acceptable. Untrack these, then "
                  "baseline the rest.\n")
            sys.exit(1)
        out = _baseline.save(ROOT, GATE, soft, f"{len(soft)} structural finding(s) at adoption")
        print(f"Baselined {len(soft)} finding(s) -> {os.path.relpath(out, ROOT)}")
        return

    new, old = _baseline.split(ROOT, GATE, soft)
    new.update(hard)                 # never baselineable, so never in `old`
    blocking = _baseline.report(
        GATE, new, old,
        "Notes belong outside the worktree, where git cannot stage them.\n"
        "To accept the STRUCTURAL findings only: .gates/scratch_external.py --baseline")

    _baseline.record(ROOT, GATE, len(new), len(old), blocking)

    if "--check" in sys.argv and blocking:
        sys.exit(1)


main()
