#!/usr/bin/env python3
"""Rebase the work from master onto the github branch, leaving master untouched.

The github branch is a copy of master with its early history omitted (GitHub
caps file sizes, and the oldest blobs of this repo exceed the cap), so it
shares no history with master. It was seeded as an orphan snapshot whose tree
is byte-identical to one commit of master; `git tag | grep github` lists those
anchor commits (the current one is `github-1`).

This tool moves the branch forward. Every commit from the anchor up to the
source tip is replayed on top of the current github tip, and the github tip
ends byte-identical to the source tip. Each replayed commit takes its tree,
message, topology (merges included) and author/committer identity verbatim
from the original, so `git log` on the result reads exactly as on master;
only the SHAs differ, because the history is grafted onto the github tip
instead of the anchor commit.

The replay is pure plumbing (`git commit-tree` over the raw commit objects):
no worktree, no index, no checkout, no cherry-pick state, so the current
working tree can never be disturbed, and the source branch is never written.

The anchor (base) is found automatically: the newest source commit whose tree
equals the tree of the current github tip. That makes reruns incremental —
after a sync, the next run replays only what the source did in the meantime.
`--base` overrides it. The tool refuses to run when no such commit exists,
because the github tip would then carry content the source does not have and
replaying the source onto it would silently drop that content. Before any ref
moves, it verifies the replayed tip's tree is byte-identical to the source's.

The local branch is created or moved to the new tip (refused if it points
somewhere other than the start point the run was computed from, unless
--force). The result is then pushed to the remote with --force-with-lease;
the push is refused if the remote tip is not an ancestor of the new tip, so
work pushed from elsewhere is never clobbered. --no-push keeps the result
local.

    github_rebase.py [--source master] [--branch github] [--remote github]
                     [--from REF] [--base REF] [--fetch] [--no-push]
                     [--force] [--dry-run]
"""
import argparse
import heapq
import os
import subprocess
import sys

PROG = "github_rebase.py"


def die(msg, code=1):
    print("%s: %s" % (PROG, msg), file=sys.stderr)
    sys.exit(code)


def short(sha):
    return sha[:12].decode("ascii")


def run_git(*args, data=None, env=None):
    p = subprocess.run(["git", *args], input=data, capture_output=True, env=env)
    if p.returncode != 0:
        die("git %s failed:\n  %s" % (" ".join(args), p.stderr.decode("utf-8", "replace").strip()))
    return p.stdout


def try_sha(ref):
    p = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        capture_output=True)
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def try_tree(ref):
    p = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref + "^{tree}"],
        capture_output=True)
    if p.returncode != 0:
        return None
    return p.stdout.strip()


def tree_of(sha):
    t = try_tree(sha.decode())
    if t is None:
        die("cannot resolve the tree of %s" % short(sha))
    return t


def is_ancestor(a, b):
    p = subprocess.run(
        ["git", "merge-base", "--is-ancestor", a.decode(), b.decode()],
        capture_output=True)
    return p.returncode == 0


def tag_at(sha):
    out = run_git("tag", "--points-at", sha.decode())
    tags = [l for l in out.split(b"\n") if l]
    return tags[0].decode() if tags else None


def resolve_start(branch, remote, from_ref):
    if from_ref:
        s = try_sha(from_ref)
        if not s:
            die("--from %s does not resolve to a commit" % from_ref)
        return s, from_ref
    local = try_sha("refs/heads/%s" % branch)
    if local:
        return local, "refs/heads/%s" % branch
    tracked = try_sha("refs/remotes/%s/%s" % (remote, branch))
    if tracked:
        return tracked, "refs/remotes/%s/%s" % (remote, branch)
    die("no local branch %r and no remote-tracking %s/%s to start from; use --from"
        % (branch, remote, branch))


def find_base(source_sha, start, start_tree, explicit):
    if explicit:
        b = try_sha(explicit)
        if not b:
            die("--base %s does not resolve to a commit" % explicit)
        if not is_ancestor(b, source_sha):
            die("--base %s is not an ancestor of the source" % explicit)
        if tree_of(b) != start_tree:
            die("--base %s has a different tree than the start point %s, so the\n"
                "    replay would rewrite the start point's own content. Re-run\n"
                "    without --base to let the anchor be found from the trees."
                % (explicit, short(start)))
        return b
    out = run_git("log", "--format=%H%x09%T", source_sha.decode())
    for line in out.split(b"\n"):
        if not line:
            continue
        c, t = line.split(b"\t")
        if t == start_tree:
            return c
    die("no commit on the source has the tree of the start point %s:\n"
        "    the github branch carries content the source does not have (or the\n"
        "    source was rewound). Refusing, because replaying the source on top\n"
        "    of it would drop that content. Investigate the divergence first."
        % short(start))


def commits_between(base, source_sha):
    """{commit: [parents]} and a deterministic topological order, parents first.

    A parent outside the range is an ancestor of the base (a commit in the
    range cannot have any other kind of out-of-range parent); it is grafted
    onto the start point at replay time, which keeps redundant merges —
    merges of a branch already contained in the base — well formed.
    """
    parents, order = {}, []
    out = run_git("rev-list", "--parents", "%s..%s" % (base.decode(), source_sha.decode()))
    for line in out.split(b"\n"):
        if not line:
            continue
        parts = line.split()
        parents[parts[0]] = parts[1:]
        order.append(parts[0])
    inrange = set(order)
    pos = {s: i for i, s in enumerate(order)}
    children, indeg = {}, {s: 0 for s in order}
    for s in order:
        for p in parents[s]:
            if p in inrange:
                children.setdefault(p, []).append(s)
                indeg[s] += 1
    heap = [(pos[s], s) for s in order if indeg[s] == 0]
    heapq.heapify(heap)
    topo = []
    while heap:
        _, s = heapq.heappop(heap)
        topo.append(s)
        for c in children.get(s, ()):
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(heap, (pos[c], c))
    if len(topo) != len(order):
        die("internal: the commit graph between base and source is not a DAG")
    return parents, topo


def raw_commits(topo):
    data = run_git("cat-file", "--batch", data=b"\n".join(topo) + b"\n")
    out, i = {}, 0
    for c in topo:
        nl = data.index(b"\n", i)
        head = data[i:nl].split()
        if len(head) != 3 or head[0] != c or head[1] != b"commit":
            die("internal: unexpected cat-file output for %s" % short(c))
        size = int(head[2])
        body = data[nl + 1: nl + 1 + size]
        i = nl + 1 + size + 1
        if len(body) != size:
            die("internal: truncated commit object for %s" % short(c))
        out[c] = body
    return out


def parse_commit(raw):
    i = raw.find(b"\n\n")
    if i < 0:
        die("internal: malformed commit object (no blank line after headers)")
    header, message = raw[:i], raw[i + 2:]
    tree = author = committer = None
    for line in header.split(b"\n"):
        if line.startswith(b"tree "):
            tree = line[5:]
        elif line.startswith(b"author ") or line.startswith(b"committer "):
            rest = line.split(b" ", 1)[1]
            lt = rest.find(b" <")
            if lt < 0:
                die("internal: malformed person header %r" % line)
            name = rest[:lt].decode("utf-8")
            gt = rest.find(b">", lt)
            email = rest[lt + 2: gt].decode("utf-8")
            when = rest[gt + 1:].strip()
            if line.startswith(b"author "):
                author = (name, email, when.decode("ascii"))
            else:
                committer = (name, email, when.decode("ascii"))
    if not (tree and author and committer):
        die("internal: commit object missing tree/author/committer headers")
    return tree, author, committer, message


def replay(topo, parents, base, start, raws):
    """Rebuild every commit, grafted: parents replayed, everything else verbatim."""
    mapping = {base: start}
    merges = 0
    for n, c in enumerate(topo, 1):
        tree, (an, ae, aw), (cn, ce, cw), message = parse_commit(raws[c])
        env = dict(os.environ)
        env.update({
            "GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae, "GIT_AUTHOR_DATE": aw,
            "GIT_COMMITTER_NAME": cn, "GIT_COMMITTER_EMAIL": ce, "GIT_COMMITTER_DATE": cw,
        })
        args = ["commit-tree", "--no-gpg-sign", tree.decode()]
        for p in parents[c]:
            # A parent outside the range is an ancestor of the base and is
            # collapsed into the start point, like the rest of the trimmed
            # history.
            args += ["-p", mapping.get(p, start).decode()]
        new = subprocess.run(["git", *args], input=message, env=env, capture_output=True)
        if new.returncode != 0:
            die("commit-tree failed for %s:\n  %s"
                % (short(c), new.stderr.decode("utf-8", "replace").strip()))
        mapping[c] = new.stdout.strip()
        if len(parents[c]) > 1:
            merges += 1
        if n % 50 == 0 or n == len(topo):
            print("  replayed %d/%d commits" % (n, len(topo)))
    return mapping, merges


def verify(tip, source_sha, start):
    if tree_of(tip) != tree_of(source_sha):
        die("the replayed tip %s does not have the source's tree — aborting\n"
            "    before moving any ref" % short(tip))
    if not is_ancestor(start, tip):
        die("internal: the start point is not an ancestor of the replayed tip")


def update_branch(branch, tip, start, force):
    local = try_sha("refs/heads/%s" % branch)
    if local and local != start and not force:
        die("local branch %s is at %s, not the start point %s this run was\n"
            "    computed from; refusing to move it. Pass --force to override."
            % (branch, short(local), short(start)))
    if local == tip:
        return False
    run_git("branch", "-f", branch, tip.decode())
    return True


def push(remote, branch, tip):
    p = subprocess.run(["git", "fetch", remote, branch], capture_output=True)
    if p.returncode != 0 and b"couldn't find remote ref" not in p.stderr:
        die("git fetch %s %s failed:\n  %s"
            % (remote, branch, p.stderr.decode("utf-8", "replace").strip()))
    remote_now = try_sha("refs/remotes/%s/%s" % (remote, branch))
    # Fully qualified: the remote and branch share a name (github/github),
    # which makes the bare refname ambiguous locally.
    refspec = "refs/heads/%s:refs/heads/%s" % (branch, branch)
    if remote_now == tip:
        return "remote %s/%s is already at %s; nothing to push" % (remote, branch, short(tip))
    if remote_now is not None and not is_ancestor(remote_now, tip):
        die("remote %s/%s is at %s, which is not part of the new history;\n"
            "    someone else pushed work there. Find out what it is, then re-run."
            % (remote, branch, short(remote_now)))
    run_git("push", "--force-with-lease", remote, refspec)
    return "pushed %s (force-with-lease)" % refspec


def main():
    ap = argparse.ArgumentParser(
        description="rebase the work from the source branch onto the github branch; "
                    "the source branch is never touched")
    ap.add_argument("--source", default="master",
                    help="branch to replay from (default: master)")
    ap.add_argument("--branch", default="github",
                    help="local branch to build and move (default: github)")
    ap.add_argument("--remote", default="github",
                    help="remote to fetch from / push to (default: github)")
    ap.add_argument("--from", dest="from_ref",
                    help="start point to build on (default: the local branch, else "
                         "the remote-tracking branch)")
    ap.add_argument("--base",
                    help="anchor commit on the source (default: found automatically "
                         "from the trees)")
    ap.add_argument("--fetch", action="store_true",
                    help="git fetch <remote> before resolving refs")
    ap.add_argument("--no-push", action="store_true",
                    help="keep the result local; do not push to <remote>/<branch>")
    ap.add_argument("--force", action="store_true",
                    help="move the local branch even if it does not point at the "
                         "start point")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve and print the plan; create no objects, move no refs")
    a = ap.parse_args()

    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    if top.returncode == 0:
        os.chdir(top.stdout.decode().strip())

    source_sha = try_sha(a.source)
    if not source_sha:
        die("source %r does not resolve to a commit" % a.source)
    if a.fetch:
        run_git("fetch", a.remote)
    start, start_name = resolve_start(a.branch, a.remote, a.from_ref)
    start_tree = tree_of(start)
    print("source   %s %s" % (a.source, short(source_sha)))
    print("start    %s %s" % (start_name, short(start)))

    if start_tree == tree_of(source_sha):
        print("already in sync: the start point has the source's tree; nothing to replay")
        if not a.no_push:
            local = try_sha("refs/heads/%s" % a.branch)
            if local != start:
                die("the local branch %s is at %s, not the in-sync point %s;\n"
                    "    not pushing an unverified branch"
                    % (a.branch, short(local) if local else "nowhere", short(start)))
            print("push     " + push(a.remote, a.branch, start))
        return 0

    base = find_base(source_sha, start, start_tree, a.base)
    tag = tag_at(base)
    parents, topo = commits_between(base, source_sha)
    if not topo:
        print("base     %s %s: no commits between it and the source; nothing to replay"
              % (short(base), " (tag %s)" % tag if tag else ""))
        return 0
    print("base     %s%s: %d commits to replay on top of the start point"
          % (short(base), " (tag %s)" % tag if tag else "", len(topo)))

    if a.dry_run:
        print("dry run: the replay takes each commit's tree verbatim onto the identical\n"
              "content it originally sat on, so the new tip will have the source's\n"
              "tree exactly; no objects were created and no ref moved")
        return 0

    raws = raw_commits(topo)
    mapping, merges = replay(topo, parents, base, start, raws)
    if len(mapping) != len(topo) + 1:
        die("internal: replayed %d commits, expected %d" % (len(mapping) - 1, len(topo)))
    tip = mapping[source_sha]
    verify(tip, source_sha, start)
    moved = update_branch(a.branch, tip, start, a.force)
    print("replayed %d commits (%d merges) onto %s; tip tree is byte-identical to %s"
          % (len(topo), merges, short(start), a.source))
    print("tip      %s" % short(tip))
    print("branch   %s %s" % (a.branch, "-> " + short(tip) if moved else "already at " + short(tip)))
    if not a.no_push:
        print("push     " + push(a.remote, a.branch, tip))
    if not tag:
        print("note     the new sync point is untagged; to keep the anchor-tag\n"
              "         convention, tag the source tip, e.g. git tag github-2 %s"
              % source_sha.decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
