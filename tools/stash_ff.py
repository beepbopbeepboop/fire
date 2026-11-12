#!/usr/bin/env python3
"""Merge into a checkout that has uncommitted edits, without ever making the merge wait on them.

The integrator lands in its own tree (work-integ, branch `integ`) and then has to move master, which is checked out
where a person works. A plain `git merge --ff-only` refuses when any file the merge changes is also dirty there, which
used to hold every landing that touched a file being edited. This does what a person would: stash the edits, merge,
re-apply, and drop the stash only when the re-apply was clean. It takes a fraction of a second.

When the re-apply CONFLICTS the merge is undone instead of leaving conflict markers in someone's files: the branch
goes back to where it was, the edits are re-applied as they were, and the result says `blocked` (the landing waits for
the next pass). The stash entry is found by sha, never by position, because the stash list is shared by every worktree
of the repository; it is checked to exist before anything is reset, and it is dropped only after the edits are back."""
import subprocess, sys, time


def _git(tree, *a):
    return subprocess.run(["git", *a], cwd=tree, capture_output=True, text=True)


def _drop(tree, ref):
    for i, sha in enumerate(_git(tree, "stash", "list", "--format=%H").stdout.split()):
        if sha == ref:
            _git(tree, "stash", "drop", "stash@{%d}" % i)
            return


def merge(tree, *merge_args):
    """`git merge MERGE_ARGS` in TREE, carrying its uncommitted tracked edits across. Returns (status, detail):
    status "ok" (merged; edits re-applied cleanly, or there were none), "failed" (the merge itself failed, e.g. it is
    not a fast-forward; the edits are back as they were) or "blocked" (the merge is fine but the edits conflict with
    it: undone, edits restored, detail names the stash entry kept for them)."""
    dirty = bool(_git(tree, "status", "--porcelain", "--untracked-files=no").stdout.strip())
    old = _git(tree, "rev-parse", "HEAD").stdout.strip()
    ref = None
    if dirty:
        if _git(tree, "stash", "push", "-m", "stash_ff %s" % time.strftime("%F %T")).returncode:
            return "failed", "could not stash the working tree edits"
        ref = _git(tree, "rev-parse", "stash@{0}").stdout.strip()

    def restore():
        """Back to OLD with the edits re-applied; the stash entry goes only once they are back."""
        _git(tree, "reset", "-q", "--hard", old)
        if ref and _git(tree, "stash", "apply", ref).returncode == 0:
            _drop(tree, ref)
            return True
        return not ref

    m = _git(tree, "merge", *merge_args)
    if m.returncode:
        _git(tree, "merge", "--abort")
        ok = restore()
        return "failed", (m.stderr or m.stdout).strip() + ("" if ok else " (edits kept in stash %s)" % ref[:10])
    if not ref:
        return "ok", ""
    if _git(tree, "stash", "apply", ref).returncode == 0:
        _drop(tree, ref)
        return "ok", ""
    new = _git(tree, "rev-parse", "HEAD").stdout.strip()
    ok = restore()
    return "blocked", ("your uncommitted edits conflict with %s..%s; merge undone, edits %s" %
                       (old[:8], new[:8], "restored" if ok else "kept in stash %s" % ref[:10]))


if __name__ == "__main__":
    st, detail = merge(sys.argv[1], *sys.argv[2:])
    print(st, detail)
    sys.exit(0 if st == "ok" else 1)
