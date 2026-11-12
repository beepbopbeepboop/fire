#!/usr/bin/env python3
"""The three orchestrator rules from the class-rebind and import-shapes loops.

    python3 tools/test_orch_fixes.py

1. A branch that deletes an open bug doc is not landed unless it also changes a test file.
2. A doc whose last NO_PROGRESS_LIMIT attempts changed no code outside bugs/ and TASK.md is no longer fed.
3. A gate job already red on master writes its gate doc but holds no branch.
Pure logic only: no git, no registry, no suite run."""
import contextlib, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import integrate as I
import task_text as T

FAILED = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED.append(name)


def test_doc_deletion_needs_a_test():
    check("deleting a bug doc with no test change is refused",
          I.deletes_doc_without_test(["bugs/" + "CODEGEN_x" + ".md"], ["mojo/a.py"]))
    check("deleting a bug doc with a test change is allowed",
          not I.deletes_doc_without_test(["bugs/" + "CODEGEN_x" + ".md"], ["mojo/a.py", "test_x.py"]))
    check("a branch that deletes no doc is not refused",
          not I.deletes_doc_without_test([], ["mojo/a.py"]))
    check("a non-test .py file does not count as a test change",
          I.deletes_doc_without_test(["bugs/" + "CODEGEN_x" + ".md"], ["tools/test_helpers_notes.txt"]))


def test_no_progress_streak():
    def mk(moved_flags):
        return [{"branch": "b%d" % i, "moved": m} for i, m in enumerate(moved_flags)]
    moved = lambda a: a["moved"]
    check("three newest attempts with no code is a streak of 3",
          T.no_progress_streak(mk([True, False, False, False]), moved) == 3)
    check("a code change in the newest attempt ends the streak at 0",
          T.no_progress_streak(mk([False, False, True]), moved) == 0)
    check("the streak stops at the first attempt that moved code",
          T.no_progress_streak(mk([False, True, False]), moved) == 1)
    check("no attempts is a streak of 0", T.no_progress_streak([], moved) == 0)


def test_no_progress_stops_the_feed():
    real_attempts, real_moved = T.attempts, T.code_moved
    try:
        T.code_moved = lambda branch: False
        T.attempts = lambda base: [{"branch": "w%d" % i} for i in range(T.NO_PROGRESS_LIMIT)]
        check("a doc with NO_PROGRESS_LIMIT no-code attempts is stopped",
              T.no_progress_reason("CODEGEN_x") is not None)
        T.attempts = lambda base: [{"branch": "w%d" % i} for i in range(T.NO_PROGRESS_LIMIT - 1)]
        check("fewer no-code attempts than the limit is not stopped",
              T.no_progress_reason("CODEGEN_x") is None)
    finally:
        T.attempts, T.code_moved = real_attempts, real_moved


def test_gate_doc_without_culprit_holds_nothing():
    real_main, real_reg = C.MAIN, C.registry
    tmp = tempfile.mkdtemp(prefix="orchfix_")
    os.makedirs(os.path.join(tmp, "bugs"))
    C.MAIN = tmp

    @contextlib.contextmanager
    def no_registry():
        raise AssertionError("gate_doc with culprit None must not touch the registry")
        yield {}
    C.registry = no_registry
    try:
        paths = I.gate_doc(None, None, ["formal-host-import-shapes"])
        check("a pre-existing red writes its gate doc", os.path.exists(paths[0]))
        check("and the doc says it is red on master", "red on `master`" in open(paths[0]).read())
    finally:
        C.MAIN, C.registry = real_main, real_reg


def test_work_worktrees_counts_only_work_branches():
    real_git = C.git
    porcelain = ("worktree /a\nHEAD x\nbranch refs/heads/master\n\n"
                 "worktree /b\nHEAD y\nbranch refs/heads/work/fix-a\n\n"
                 "worktree /c\nHEAD z\ndetached\n\n"
                 "worktree /d\nHEAD w\nbranch refs/heads/work/fix-b\n")
    try:
        C.git = lambda *a, **k: porcelain
        check("work_worktrees counts the work/* checkouts and nothing else", C.work_worktrees() == 2)
    finally:
        C.git = real_git


def test_refill_starts_nothing_at_the_backlog_limit():
    import io, contextlib as cl
    real_bl, real_git = C.BACKLOG_MAX, C.git
    real_tasks, real_breaker = C.load, C.breaker_until
    try:
        C.BACKLOG_MAX = 3
        C.git = lambda *a, **k: "".join("branch refs/heads/work/x%d\n" % i for i in range(3))
        C.load = lambda: {}
        C.breaker_until = lambda: 0
        out = io.StringIO()
        with cl.redirect_stdout(out):
            C.cmd_refill(type("A", (), {"target": None, "prefix": "bug,fix,fix-replan"})())
        check("refill starts nothing when work worktrees reach the limit",
              "starting nothing until landing catches up" in out.getvalue())
    finally:
        C.BACKLOG_MAX, C.git = real_bl, real_git
        C.load, C.breaker_until = real_tasks, real_breaker


if __name__ == "__main__":
    test_doc_deletion_needs_a_test()
    test_no_progress_streak()
    test_no_progress_stops_the_feed()
    test_gate_doc_without_culprit_holds_nothing()
    test_work_worktrees_counts_only_work_branches()
    test_refill_starts_nothing_at_the_backlog_limit()
    print("%d failure(s)" % len(FAILED))
    sys.exit(1 if FAILED else 0)
