#!/usr/bin/env python3
"""The three orchestrator rules from the class-rebind and import-shapes loops.

    python3 tools/test_orch_fixes.py

1. A branch that deletes an open bug doc is not landed unless it also changes a test file.
2. A doc whose last NO_PROGRESS_LIMIT attempts changed no code outside bugs/ and TASK.md is no longer fed.
3. A gate job already red on master writes its gate doc but holds no branch.
Pure logic only: no git, no registry, no suite run."""
import contextlib, os, subprocess, sys, tempfile
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
    # MAIN is a git repo on master: gate_doc commits the doc it writes, so the test tree must be one.
    for a in (["init", "-q", "-b", "master"], ["add", "bugs"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *a], cwd=tmp, check=True)
    C.MAIN = tmp

    @contextlib.contextmanager
    def no_registry():
        raise AssertionError("gate_doc with culprit None must not touch the registry")
        yield {}
    C.registry = no_registry
    try:
        paths = I.gate_doc(None, None, ["formal-host-import-shapes"])
        check("a pre-existing red writes its gate doc", os.path.exists(paths[0]))
        check("and the doc says it is red on `master`", "red on `master`" in open(paths[0]).read())
    finally:
        C.MAIN, C.registry = real_main, real_reg


def test_free_branch_takes_the_next_suffix_when_a_branch_exists():
    real_git = C.git
    taken = set()

    def fake_git(*a, **k):
        ref = a[-1]
        return "sha\n" if ref.replace("refs/heads/", "") in taken else ""
    try:
        C.git = fake_git
        check("a free name is used as it is", C.free_branch("fix-x") == "work/fix-x")
        taken.update({"work/fix-x"})
        check("an existing branch gets the -1 suffix", C.free_branch("fix-x") == "work/fix-x-1")
        taken.update({"work/fix-x-1"})
        check("the next existing branch gets -2", C.free_branch("fix-x") == "work/fix-x-2")
    finally:
        C.git = real_git


def test_free_task_name_checks_the_cut_form_against_registry_and_queue():
    real_load, real_q = C.load, C.qdir
    tmp = tempfile.mkdtemp(prefix="orchname_")
    open(os.path.join(tmp, "bug-aaaa.json"), "w").write("{}")
    try:
        C.load, C.qdir = (lambda: {"bug-bbbb": {}}), (lambda: tmp)
        check("a free name is kept", C.free_task_name("bug-cccc") == "bug-cccc")
        check("a queued name gets -2", C.free_task_name("bug-aaaa") == "bug-aaaa-2")
        check("a registered name gets -2", C.free_task_name("bug-bbbb") == "bug-bbbb-2")
        check("the cut happens before the check", C.free_task_name("bug-aaaa-zzzz", 8) == "bug-aa-2")
        check("the suffix fits the limit", len(C.free_task_name("bug-aaaa", 8)) <= 8)
    finally:
        C.load, C.qdir = real_load, real_q


if __name__ == "__main__":
    test_free_task_name_checks_the_cut_form_against_registry_and_queue()
    test_doc_deletion_needs_a_test()
    test_no_progress_streak()
    test_no_progress_stops_the_feed()
    test_gate_doc_without_culprit_holds_nothing()
    test_free_branch_takes_the_next_suffix_when_a_branch_exists()
    print("%d failure(s)" % len(FAILED))
    sys.exit(1 if FAILED else 0)
