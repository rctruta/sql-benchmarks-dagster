#!/usr/bin/env python3
"""
scratch_external — keep the local notes folder physically outside the repository.

  .gates/scratch_external.py              report
  .gates/scratch_external.py --check      exit 1 on anything not baselined
  .gates/scratch_external.py --baseline   accept today's STRUCTURAL findings

The cause: `scratch/` is where drafts, private notes, employment details and
half-formed thinking go. Keeping it out of a commit was a .gitignore rule, and
a .gitignore rule is advisory -- it is consulted only for files git does not
already track. Once a file is tracked, the rule is silent forever.

The specimen, measured 2026-10-19 across nine repositories: harness-bench had
`scratch/` on line 25 of its .gitignore AND `scratch/skills-antipattern-final.md`
tracked in HEAD since 2026-07-14, in a PUBLIC repository. The ignore rule was
present the whole time and did nothing, because the file was added before it or
with -f. Nothing reported a contradiction, because nothing was looking for one.

So the fix is not a better rule. It is to put the notes somewhere git mechanically
cannot reach, and have this gate assert that arrangement instead of policing
content. `scratch` becomes a symlink to a directory outside the worktree:

    ~/scratch/<repo>/           the real directory
    <repo>/scratch -> ~/scratch/<repo>

git then refuses to stage anything through it, by its own pathspec resolution:

    $ git add scratch/note.md
    fatal: pathspec 'scratch/note.md' is beyond a symbolic link

`git add -A` stages mode 120000 -- the link, sixty bytes of target text -- and
never the contents. Keeping `scratch` gitignored stops even that. The guarantee
stops depending on anyone remembering, which is the whole point: it binds the
human and the agent equally, and neither has to be trusted.

WHAT IT REPORTS, and why the two kinds are not equally forgivable:

  TRACKED (never baselineable)
      A file under the notes folder is in the index. That note is already
      published, or will be on the next push. There is no state of the world in
      which accepting this is correct, so --baseline will not take it. Untrack
      it and decide separately about history.

  STRUCTURAL (baselineable)
      The folder is a real directory, or the symlink points back inside the
      worktree, or the link is not ignored. Nothing has leaked yet; the
      arrangement merely permits it. Baselineable so adopting the gate in a
      repository mid-migration does not block every commit.

An absent `scratch` is clean. This gate refuses a leaky notes folder; it does
not require one to exist. init-agent-project.sh is what creates it.
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
