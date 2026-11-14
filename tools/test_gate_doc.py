#!/usr/bin/env python3
"""Work exists only while its bug doc does, and a red gate becomes a doc.

    python3 tools/test_gate_doc.py

Points C.MAIN at a temporary tree and replaces the registry with an in-memory dict, so the live bugs/ and tasks.json
are never read or written."""
import contextlib, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import integrate as I
import verify_landed as VL

FAILED = []
JOB = "formal-host-import-shapes"   # a real job; the doc name is built, never written out


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED.append(name)


def fake_registry(reg):
    @contextlib.contextmanager
    def registry():
        yield reg
    return registry


def in_tree(fn):
    """Run fn with C.MAIN at a fresh tree that has an empty bugs/."""
    real_main = C.MAIN
    tmp = tempfile.mkdtemp(prefix="gatedoc_")
    os.makedirs(os.path.join(tmp, "bugs"))
    C.MAIN = tmp
    try:
        fn(tmp)
    finally:
        C.MAIN = real_main


def git(tree, *args):
    """Run git in a test tree (never the live one: every call names its cwd)."""
    r = subprocess.run(["git", *args], cwd=tree, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def git_tree(tmp):
    """A tree that is a git repo on master with an empty bugs/ committed, and C.MAIN pointed at it."""
    os.environ.setdefault("GIT_AUTHOR_NAME", "test")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "test@example.invalid")
    os.environ.setdefault("GIT_COMMITTER_NAME", "test")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "test@example.invalid")
    git(tmp, "init", "-q", "-b", "master")
    open(os.path.join(tmp, "bugs", ".keep"), "w").close()
    git(tmp, "add", "bugs/.keep")
    git(tmp, "commit", "-q", "-m", "init")


def in_repo(fn):
    """Run fn with C.MAIN at a fresh git repo on master (see git_tree)."""
    real_main = C.MAIN
    tmp = tempfile.mkdtemp(prefix="gatedoc_repo_")
    os.makedirs(os.path.join(tmp, "bugs"))
    git_tree(tmp)
    C.MAIN = tmp
    try:
        fn(tmp)
    finally:
        C.MAIN = real_main


def test_gate_doc_is_tracked_on_master_at_once():
    """A worker is cut from a git commit, so the doc must be IN a commit on master the moment it exists: an
    untracked file in MAIN is invisible to the worker's worktree and collides with the ledger merge."""
    def body(tmp):
        reg = {"fix-x": {"branch": "work/x", "state": "exited-ok", "claims": ["bug:x"]}}
        real = C.registry
        C.registry = fake_registry(reg)
        try:
            paths = I.gate_doc(None, None, ["formal-host-import-shapes"])
            rel = "bugs/gate-%s.md" % JOB
            check("the gate doc is tracked on master (ls-files names it)",
                  git(tmp, "ls-files", "--", rel) == rel)
            check("the gate doc is in the master commit log, not just the working tree",
                  ("gate-%s" % JOB) in git(tmp, "show", "--name-only", "--format=", "master"))
            check("MAIN has no untracked gate doc left behind", git(tmp, "status", "--porcelain") == "")
            in_master = subprocess.run(["git", "cat-file", "-e", "master:" + rel], cwd=tmp).returncode == 0
            check("a worktree cut from master sees the doc", in_master)
            check("the returned path is the committed file", os.path.exists(paths[0]))
        finally:
            C.registry = real
    in_repo(body)


def test_ledger_landing_clears_an_untracked_twin_of_a_tracked_doc():
    """The ledger commit tracks bugs/gate-<job>.md; an untracked MAIN copy of the same file makes git refuse the merge
    ("would be overwritten by merge"), which held every job's marker on verify-ledger. The twin is removed before the
    merge when it is byte-identical to the tracked copy; an untracked doc the ledger does not track is never touched."""
    def body(tmp):
        ledger_doc = "# Gate: formal-host-import-shapes is red on master\n\nfrom the ledger\n"
        git(tmp, "checkout", "-q", "-b", "verify-ledger")
        open(os.path.join(tmp, "bugs", "gate-%s.md" % JOB), "w").write(ledger_doc)
        git(tmp, "add", "bugs/gate-%s.md" % JOB)
        git(tmp, "commit", "-q", "-m", "ledger")
        new = git(tmp, "rev-parse", "HEAD")
        git(tmp, "checkout", "-q", "master")
        sha = git(tmp, "rev-parse", "master")
        twin = os.path.join(tmp, "bugs", "gate-%s.md" % JOB)
        open(twin, "w").write(ledger_doc)                       # the orphan: same bytes, untracked
        other = os.path.join(tmp, "bugs", "gate-other-job.md")
        open(other, "w").write("untracked, not in the ledger\n")

        seen = {}

        class Lock:
            def close(self):
                pass

        def fake_merge(main, *args):
            seen["twin"] = os.path.exists(twin)
            seen["other"] = os.path.exists(other)
            return "ok", ""

        real_lock, real_merge = VL.integrator_lock, VL.SF.merge
        VL.integrator_lock = lambda wait_s=0: Lock()
        VL.SF.merge = fake_merge
        try:
            landed = VL.land_ledger(new, sha)
        finally:
            VL.integrator_lock, VL.SF.merge = real_lock, real_merge
        check("the ledger lands once the untracked twin is cleared", landed is True)
        check("the untracked twin is gone before the merge runs", seen.get("twin") is False)
        check("an untracked doc the ledger does not track is left alone", seen.get("other") is True)
    in_repo(body)


def test_ledger_landing_keeps_a_twin_whose_bytes_differ():
    """A MAIN copy that differs from the tracked one is somebody's work: it is not deleted to make the merge pass."""
    def body(tmp):
        git(tmp, "checkout", "-q", "-b", "verify-ledger")
        open(os.path.join(tmp, "bugs", "gate-%s.md" % JOB), "w").write("ledger version\n")
        git(tmp, "add", "bugs/gate-%s.md" % JOB)
        git(tmp, "commit", "-q", "-m", "ledger")
        new = git(tmp, "rev-parse", "HEAD")
        git(tmp, "checkout", "-q", "master")
        sha = git(tmp, "rev-parse", "master")
        twin = os.path.join(tmp, "bugs", "gate-%s.md" % JOB)
        open(twin, "w").write("a different local edit\n")

        class Lock:
            def close(self):
                pass

        real_lock, real_merge = VL.integrator_lock, VL.SF.merge
        VL.integrator_lock = lambda wait_s=0: Lock()
        VL.SF.merge = lambda main, *args: ("conflict", "untracked file would be overwritten")
        try:
            VL.land_ledger(new, sha)
        finally:
            VL.integrator_lock, VL.SF.merge = real_lock, real_merge
        check("a twin whose bytes differ is kept, not deleted",
              open(twin).read() == "a different local edit\n")
    in_repo(body)


def test_two_states_for_a_claim():
    """x exists -> the claim has work; deleted -> it has none."""
    def body(tmp):
        p = os.path.join(tmp, "bugs", "bug-x-thing.md")
        open(p, "w").write("# x\n")
        check("a claim whose doc exists has work", C.doc_exists_for(["bug:x-thing"]))
        os.remove(p)
        check("the same claim after its doc is deleted has no work", not C.doc_exists_for(["bug:x-thing"]))
        check("a claim naming no doc has no work", not C.doc_exists_for(["task:nothing-here"]))
    in_tree(body)


def test_gate_doc_never_names_a_path_and_holds_first():
    def body(tmp):
        reg = {"fix-x": {"branch": "work/x", "state": "exited-ok", "claims": ["bug:x"]}}
        real = C.registry
        C.registry = fake_registry(reg)
        try:
            paths = I.gate_doc("fix-x", reg["fix-x"], ["stdlib-syntax", "std/builtin/bool.mojo"],
                               ["std/builtin/bool.mojo"])
            check("a failing FILE is not a job: no doc is named after a path",
                  [os.path.basename(p) for p in paths] == ["gate-stdlib-syntax.md"])
            check("the failing file is listed in the doc body", "std/builtin/bool.mojo" in open(paths[0]).read())
        finally:
            C.registry = real
    in_repo(body)


def test_failed_job_names_stops_at_the_section_end():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("FAILED:\n  stdlib-syntax  (36s)\n      NEW: no bug doc tracks this job\n"
                "time: wall 0:36 | work 0:36 across 1 job(s) (0 replayed from cache)\n"
                "suite: 0 passed, 1 failed (1 tests)\n")
    try:
        check("only the indented job line is a failing job (not `time`)",
              I.failed_job_names(f.name) == ["stdlib-syntax"])
    finally:
        os.unlink(f.name)


def test_red_gate_writes_one_doc_per_job():
    def body(tmp):
        reg = {"fix-x": {"branch": "work/x", "state": "exited-ok", "claims": ["bug:x"]}}
        real = C.registry
        C.registry = fake_registry(reg)
        try:
            paths = I.gate_doc("fix-x", reg["fix-x"], ["formal-host-import-shapes", "stdlib-syntax"])
            check("a red gate creates bugs/gate-<job>.md for each failing job",
                  all(os.path.exists(p) for p in paths) and len(paths) == 2)
            body1 = open(paths[0]).read()
            check("the doc names its job and the culprit branch",
                  "formal-host-import-shapes" in body1 and "work/x" in body1)
            open(paths[0], "w").write("edited by a worker\n")
            I.gate_doc("fix-x", reg["fix-x"], ["formal-host-import-shapes"])
            check("a second red for the same job does not overwrite the doc",
                  open(paths[0]).read() == "edited by a worker\n")
            check("the culprit is superseded and held, so it cannot land again",
                  reg["fix-x"]["state"] == "superseded" and reg["fix-x"]["hold"] is True)
            check("the culprit is excluded from landing candidates by its hold",
                  bool(reg["fix-x"].get("hold")))
            check("a doc named after the job is what the claim matches",
                  C.doc_exists_for(["gate:formal-host-import-shapes"]))
        finally:
            C.registry = real
    in_repo(body)


def test_restart_refuses_a_task_with_no_doc():
    def body(tmp):
        t = {"name": "fix-gate-x-r2", "claims": ["gate:formal-host-import-shapes"], "branch": "work/y",
             "worktree": os.path.join(tmp, "no-such-tree")}
        reg = {"fix-gate-x-r2": dict(t)}
        real_load, real_reg = C.load, C.registry
        C.load = lambda: {"fix-gate-x-r2": t}
        C.registry = fake_registry(reg)
        try:
            new = C.restart("fix-gate-x-r2", "process dead")
            check("restart refuses a task whose doc is gone (returns None)", new is None)
            check("the refused task is abandoned, so its claim releases",
                  reg["fix-gate-x-r2"]["state"] == "abandoned")
        finally:
            C.load, C.registry = real_load, real_reg
    in_tree(body)


if __name__ == "__main__":
    test_gate_doc_is_tracked_on_master_at_once()
    test_ledger_landing_clears_an_untracked_twin_of_a_tracked_doc()
    test_ledger_landing_keeps_a_twin_whose_bytes_differ()
    test_two_states_for_a_claim()
    test_red_gate_writes_one_doc_per_job()
    test_gate_doc_never_names_a_path_and_holds_first()
    test_failed_job_names_stops_at_the_section_end()
    test_restart_refuses_a_task_with_no_doc()
    print("%d failure(s)" % len(FAILED))
    sys.exit(1 if FAILED else 0)
