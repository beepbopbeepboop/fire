#!/usr/bin/env python3
"""Give the integrator its own tree for master, so edits in your checkout can never block a landing.

    master_tree.py setup [--dev BRANCH]   one time: master moves to ../work-master, this checkout goes to BRANCH (dev)
    master_tree.py sync                   in your checkout: bring master's landings in without losing your edits

Why. Git allows one worktree per branch, and `git merge --ff-only` of a landing runs in whichever tree has master
checked out. While that was your checkout, any uncommitted edit that a landing also touched stopped the landing
("holding ...: the main checkout has uncommitted edits"). The swarm's root (C.MAIN) is the directory its own
tools/ lives in, so a swarm started from work-master/tools/swarm.py lands, reclasses and writes ledger commits in
work-master, a tree nobody edits, and your checkout is never touched.

    python3 ../work-master/tools/swarm.py        # start the swarm from the integrator's tree

`sync` is the stash dance, made safe: stash your edits (named, by sha, so another worktree's stash entry can never be
the one popped), fast-forward to master, re-apply them, and drop the stash only when the re-apply was clean. On a
conflict your edits stay applied with markers AND in the stash entry, which is reported, never dropped."""
import argparse, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def git(*a, cwd=None, check=True):
    r = subprocess.run(["git", *a], cwd=cwd or ROOT, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit("git %s failed: %s" % (" ".join(a), (r.stderr or r.stdout).strip()))
    return r


def branch_of(tree):
    return git("branch", "--show-current", cwd=tree).stdout.strip()


def master_tree():
    """The worktree that has master checked out, or None."""
    cur = None
    for line in git("worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            cur = line[9:]
        elif line == "branch refs/heads/master":
            return cur
    return None


def setup(dev="dev", target=None):
    """master -> ../work-master, this checkout -> DEV (created at master; the working tree is untouched)."""
    here = master_tree()
    target = target or os.path.join(os.path.dirname(ROOT), "work-master")
    if here and os.path.realpath(here) != os.path.realpath(ROOT):
        print("master is already checked out in %s" % here)
        return here
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        print("note: your checkout has uncommitted edits; they stay exactly where they are (the switch keeps them)")
    if git("rev-parse", "--verify", "-q", "refs/heads/" + dev, check=False).returncode == 0:
        git("switch", dev)
    else:
        git("switch", "-c", dev)          # a new branch at the current commit: no file changes, edits stay in place
    git("worktree", "add", target, "master")
    print("master is now owned by %s; this checkout is on %s.\nStart the swarm from there:\n  python3 %s"
          % (target, dev, os.path.join(target, "tools", "swarm.py")))
    return target


def sync(tree=None):
    """Fast-forward TREE (default: this checkout) to master, carrying its uncommitted edits across. Returns 0 clean,
    1 when the re-apply conflicted (edits kept, stash entry kept)."""
    tree = tree or ROOT
    br = branch_of(tree)
    if br == "master":
        sys.exit("this checkout is master itself: run `master_tree.py setup` first (or just `git pull`)")
    if git("merge-base", "--is-ancestor", "HEAD", "master", cwd=tree, check=False).returncode != 0:
        sys.exit("%s has commits master does not: merge or rebase them by hand (this only fast-forwards)" % br)
    dirty = bool(git("status", "--porcelain", "--untracked-files=no", cwd=tree).stdout.strip())
    ref = None
    if dirty:
        git("stash", "push", "-m", "master_tree sync %s" % time.strftime("%F %T"), cwd=tree)
        ref = git("rev-parse", "stash@{0}", cwd=tree).stdout.strip()
    git("merge", "--ff-only", "master", cwd=tree)
    if not ref:
        print("fast-forwarded %s to master" % br)
        return 0
    if git("stash", "apply", ref, cwd=tree, check=False).returncode == 0:
        for i, line in enumerate(git("stash", "list", "--format=%H", cwd=tree).stdout.split()):
            if line == ref:
                git("stash", "drop", "stash@{%d}" % i, cwd=tree)
                break
        print("fast-forwarded %s to master; your edits re-applied cleanly" % br)
        return 0
    print("fast-forwarded %s to master, but your edits CONFLICT with it: they are applied with markers and also kept in "
          "stash entry %s (`git stash apply %s` to retry after resolving). Nothing was dropped." % (br, ref[:10], ref[:10]))
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--dev", default="dev")
    sub.add_parser("sync")
    a = ap.parse_args()
    if a.cmd == "setup":
        setup(a.dev)
        return 0
    return sync()


if __name__ == "__main__":
    sys.exit(main())
