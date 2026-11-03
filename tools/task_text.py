#!/usr/bin/env python3
"""The task a worker gets for one bug doc, built from the doc's path alone.

    python3 tools/task_text.py bugs/mid/CODEGEN_foo.md          # the attempts on the doc, and the task it would get
    python3 tools/task_text.py bugs/mid/CODEGEN_foo.md --json   # the same, as data

A doc is keyed by its file name (without .md): the registry (.git/control/tasks.json) records each attempt's
branch under a claim `bug:<name>`, so every attempt on a doc is found from the doc's path, whatever the branch
was named. A fresh worker starts from the newest attempt that has commits not on master (so it builds on that
work), or from master when there is none. The text below is the one place the worker's instructions live; the
swarm (tools/swarm.py) uses this same module to queue every task.
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C

# The worker's instructions. Edit here; the swarm picks the change up on its next task.
INSTRUCTIONS = (
    "Fix the bug in %(where)s at its ROOT CAUSE. Read the doc's Status/next step first; it may already be fixed "
    "on master (then delete the doc with a pinning test, or report). QUICK tests only: write a small regression "
    "test that FAILS before your fix and passes after (next to the existing tests for that area), and run just "
    "that test plus the one existing test file that covers the code you touched, each wrapped in python3 "
    "tools/memslot.py --gb 8 --label x --. No gate, no stdlib sweep, no self-host build: an integrator gates on "
    "the stdlib compile after you land. If the bug is fully fixed, git rm its doc in the same commit and run "
    "python3 tools/dangling_doc_refs.py --ratchet. Commit, end with a clean tree and the CONTROL-STATUS line."
)
# Prepended when the worker starts from an earlier attempt's branch.
CONTINUE = (
    "An earlier attempt left %(ahead)d commit(s) on branch %(branch)s, which you start from. Read `git log "
    "master..HEAD` and `git diff master...HEAD` first. "
)


def key(doc_or_path):
    """'bugs/mid/CODEGEN_foo.md' or 'mid/CODEGEN_foo' -> ('mid/CODEGEN_foo', 'CODEGEN_foo')."""
    d = doc_or_path.replace("\\", "/")
    if d.startswith("bugs/"):
        d = d[len("bugs/"):]
    if d.endswith(".md"):
        d = d[:-3]
    return d, d.rsplit("/", 1)[-1]


def attempts(base):
    """Every registry task that claims this doc, oldest first, each with its branch, state and commits not on master."""
    out = []
    for name, t in C.load().items():
        if "bug:" + base in t.get("claims", []) and t.get("branch"):
            out.append({"task": name, "branch": t["branch"], "state": C.state_of(t), "ahead": C.ahead(t),
                        "started": t.get("started", "")})
    return sorted(out, key=lambda a: a["started"])


def start_from(base):
    """The newest attempt with commits not on master that is not integrated: the work a fresh worker builds on."""
    live = [a for a in attempts(base) if a["state"] != "integrated" and a["ahead"] > 0]
    return live[-1] if live else None


def doc_on(branch, base):
    """Where the doc sits on BRANCH (bugs/<dir>/<base>.md, never formal's), or None when the branch no longer has it."""
    r = subprocess.run(["git", "ls-tree", "-r", "--name-only", branch, "--", "bugs"], capture_output=True, text=True,
                       cwd=C.MAIN)
    for p in r.stdout.split():
        if (p == "bugs/%s.md" % base or p.endswith("/%s.md" % base)) and not p.startswith("bugs/formal/"):
            return p
    return None


def plan(doc_or_path, continue_from=None):
    """Everything a worker needs for one doc: where it starts, where the doc is there, and the task text. CONTINUE_FROM
    names the branch of a round the swarm is continuing; otherwise the newest unlanded attempt is used."""
    doc, base = key(doc_or_path)
    master_path = "bugs/%s.md" % doc
    if continue_from:
        start = {"branch": continue_from, "ahead": C.ahead({"branch": continue_from})}
    else:
        start = start_from(base)
    path, ahead = None, 0
    if start:
        path = doc_on(start["branch"], base)
        if path:
            ahead = start["ahead"]
        else:                                   # the branch no longer has the doc (fixed there): start from master
            start = None
    where = path if start else master_path
    text = (CONTINUE % {"ahead": ahead, "branch": start["branch"]} if start else "") + INSTRUCTIONS % {"where": where}
    return {"doc": doc, "base": base, "master_path": master_path, "attempts": attempts(base),
            "start_branch": start and start["branch"], "start_path": where, "ahead": ahead, "text": text}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", help="the bug doc, e.g. bugs/mid/CODEGEN_foo.md")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    a = ap.parse_args()
    p = plan(a.doc)
    if a.json:
        print(json.dumps(p, indent=1))
        return
    print("doc:       %s" % p["master_path"])
    print("attempts:  %d" % len(p["attempts"]))
    for t in p["attempts"]:
        print("  %-14s %-3d commit(s) not on master  %s  (%s)" % (t["state"], t["ahead"], t["branch"], t["task"]))
    print("starts:    %s" % (p["start_branch"] or "master"))
    print("doc there: %s" % p["start_path"])
    print("\nTASK TEXT:\n%s" % p["text"])


if __name__ == "__main__":
    main()
