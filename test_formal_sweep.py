#!/usr/bin/env python3
"""Tests for tools/formal_sweep.py's verdict classification and reporting.

The sweep itself is expensive (a real `fire.py build --formal` per file), so
nothing here builds anything: the unit under test is the layer that decides
what a build's outcome MEANS, which is the layer that was missing. Every case
below is a real message the build prints, quoted from the tool's own recorded
runs, because a classifier tested only against messages it invented tests
nothing.

    python3 test_formal_sweep.py [-v]

NOT YET WIRED INTO make: no check-* target covers tools/formal_sweep.py, and
adding one means editing the Makefile, which is shared with the other agents in
flight. When that is done it should follow the checked_run.py convention the
other suites use:

    check-formal-sweep: tools/formal_sweep.py test_formal_sweep.py fire.py
        python3 checked_run.py check-formal-sweep \\
            --extra tools/formal_sweep.py --extra test_formal_sweep.py \\
            --extra fire.py --extra fire_compiler.py -- python3 test_formal_sweep.py
"""
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "tools"))

import cas
import formal_sweep as S

# ── The messages this classifies, verbatim ───────────────────────────────────
# The host-import and unresolved-import wordings are the two ImportBuildError
# texts in formal/build.py and formal/imports.py; formal/build.py's own comment
# says there is one wording for one condition, so these two partition that
# space. The "cannot be lowered" text is formal/build.py's refusal for a
# construct, and the "builds, but N import(s)" text is the dyld check in
# run_one itself.
HOST_MSG = ("build: fire.py imports 'os', which is a host module (CPython "
            "standard library), which has no Mojo source for this backend to "
            "compile")
UNRESOLVED_MSG = ("build: wave1.py imports '__future__', which is not a "
                  "stdlib or sibling module, and no such file exists")
CODEGEN_MSG = ("build: GimpleGen._record_sys_path_inserts() cannot be lowered: "
               "its receiver has 16 fields and a formal value is one word, so "
               "`self.<field>` has no representation on this path")
EXTERN_MSG = ("builds, but 31 import(s) dyld cannot resolve (one file "
              "compiled, no import resolution): _ZN6mojo5printEPKc, _ZN4mojo"
              "5writeEPKc, _ZN5mojo34read_file_to_stringB5cxx11E ...")
# fire.py prints `build: {e}` for a FormalBuildError AND for any other
# exception, so a crash is only distinguishable by its traceback. These two are
# the shapes that decides, taken from how fire.py's handler and CPython's
# traceback module print them.
TB_BACKEND = (
    "build: 'AssignStmt' object has no attribute 'name'\n"
    "Traceback (most recent call last):\n"
    '  File "/x/fire.py", line 186, in _run_formal_build\n'
    "    result = _fb.compile_formal(\n"
    '  File "/x/formal/build.py", line 412, in compile_formal\n'
    "    emit(stmts)\n"
    '  File "/x/formal/arm64_codegen.py", line 90, in emit\n'
    "    return self._stmt(node)\n"
    "AttributeError: 'AssignStmt' object has no attribute 'name'\n")
# Same top frame in formal/ (which sits between the driver and the emitter),
# but the exception came out of the parser. Not a codegen finding.
TB_DRIVER = (
    "build: 'AssignStmt' object has no attribute 'name'\n"
    "Traceback (most recent call last):\n"
    '  File "/x/fire.py", line 186, in _run_formal_build\n'
    "    result = _fb.compile_formal(\n"
    '  File "/x/formal/build.py", line 400, in compile_formal\n'
    "    stmts = F.parse(source)\n"
    '  File "/x/fire_compiler.py", line 1200, in parse\n'
    "    return AssignStmt(name, value)\n"
    "AttributeError: 'AssignStmt' object has no attribute 'name'\n")


class TestClassify(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(S.classify(True, ""), (S.CLASS_PASS, ""))

    def test_host_import_is_not_a_codegen_finding(self):
        cls, reason = S.classify(False, HOST_MSG)
        self.assertEqual(cls, S.CLASS_HOST)
        self.assertEqual(reason, "os")
        self.assertNotIn(cls, S.ANSWERABLE)
        self.assertNotIn(cls, S.DIRTY)

    def test_unresolved_import_is_its_own_class(self):
        # __future__ is a CPython standard-library module, so this lands in
        # host — via the interpreter's own table, because formal/imports.py's
        # HOST_MODULES does not list it (that gap is formal/imports.py's, and
        # this tool must not inherit a copy of it).
        self.assertEqual(S.classify(False, UNRESOLVED_MSG)[0], S.CLASS_HOST)

    def test_unresolved_non_host_module_keeps_its_own_class(self):
        # A sibling module the resolver cannot see from this file's directory
        # is NOT provably a host module, so it must not be filed as one.
        msg = ("build: tools/x.py imports 'fire_compiler', which is not a "
               "stdlib or sibling module, and no such file exists")
        cls, reason = S.classify(False, msg)
        self.assertEqual(cls, S.CLASS_UNRESOLVED)
        self.assertEqual(reason, "fire_compiler")
        self.assertNotIn(cls, S.ANSWERABLE)

    def test_third_party_package_is_unresolved_not_host(self):
        msg = ("build: t.py imports 'pytest', which is not a stdlib or sibling "
               "module, and no such file exists")
        self.assertEqual(S.classify(False, msg)[0], S.CLASS_UNRESOLVED)

    def test_chained_import_error_names_the_innermost_module(self):
        # Verbatim from this tree: formal/build.py wraps a DEPENDENCY's own
        # error inside the importer's, so one message carries two `imports '…'`
        # and two different modules. The outer one resolves fine; blaming it
        # would send a reader after a module that is not the problem.
        msg = ("build: model.py imports 'fire_compiler', which cannot be "
               "built either: fire_compiler.py imports 're', which is a host "
               "module (CPython standard library), which has no Mojo source "
               "for this backend to compile")
        self.assertEqual(S.classify(False, msg), (S.CLASS_HOST, "re"))

    def test_codegen(self):
        cls, reason = S.classify(False, CODEGEN_MSG)
        self.assertEqual(cls, S.CLASS_CODEGEN)
        self.assertIn(cls, S.ANSWERABLE)
        self.assertIn(cls, S.DIRTY)
        self.assertIn("cannot be lowered", reason)

    def test_dyld_unresolvable_is_not_coverage(self):
        cls, reason = S.classify(False, EXTERN_MSG)
        self.assertEqual(cls, S.CLASS_EXTERN)
        self.assertEqual(reason, "31 unresolved extern(s)")
        self.assertNotIn(cls, S.ANSWERABLE)

    def test_silent_nonzero_exit_is_a_codegen_finding(self):
        # No message and no traceback: the backend died on the construct.
        # Counting that as `tool` would let a crash shrink coverage silently.
        self.assertEqual(S.classify(False, "exit 139")[0], S.CLASS_CODEGEN)

    def test_reworded_import_error_is_still_an_import_error(self):
        # A different agent editing formal/imports.py can reword the message
        # at any time. It must not start counting as codegen coverage, and it
        # must not need this file edited in the same commit to stay honest:
        # the quoted module plus the file's own source is the evidence.
        msg = "build: x.py cannot acquire 'os' on this target, sorry"
        self.assertEqual(S.classify(False, msg, source="import os\n")[0],
                         S.CLASS_HOST)
        msg2 = ("build: x.py has no module named 'fire_compiler' anywhere, "
                "and will not invent one")
        self.assertEqual(
            S.classify(False, msg2, source="import fire_compiler as F\n")[0],
            S.CLASS_UNRESOLVED)

    def test_a_quoted_name_the_file_does_not_import_is_a_codegen_finding(self):
        # The structural test must not over-reach: a quoted identifier that is
        # not one of this file's imports says nothing about imports, so the
        # refusal is about the code (this is the fallback a new codegen
        # diagnostic has to land in — see the docstring on CLASS_UNKNOWN).
        msg = "build: Type.foo() cannot be lowered: field 'os' has no word"
        self.assertEqual(S.classify(False, msg, source="import sys\n")[0],
                         S.CLASS_CODEGEN)

    def test_import_wording_with_no_module_named_is_unknown(self):
        # CLASS_UNKNOWN: recognisably about an import, but with nothing to
        # classify by. Its own bucket rather than a guess in either direction.
        msg = "build: this file is a host module (CPython standard library)"
        self.assertEqual(S.classify(False, msg)[0], S.CLASS_UNKNOWN)
        self.assertIn(S.CLASS_UNKNOWN, S.DIRTY)
        self.assertNotIn(S.CLASS_UNKNOWN, S.ANSWERABLE)

    def test_cause_short_circuits_the_message(self):
        # A timeout whose text happens to mention an import is still a timeout:
        # the cause run_one reports outranks anything in the message.
        for cause in (S.CAUSE_TIMEOUT, S.CAUSE_UNREADABLE, S.CAUSE_TOOL_ERROR,
                      S.CAUSE_DRIVER_CRASH):
            self.assertEqual(S.classify(False, HOST_MSG, cause),
                             (S.CLASS_TOOL, cause))
        self.assertEqual(S.classify(True, "", S.CAUSE_TIMEOUT)[0],
                         S.CLASS_PASS)

    def test_crash_classification_uses_the_deepest_frame(self):
        self.assertEqual(S._crash_cause(TB_BACKEND), S.CAUSE_BACKEND_CRASH)
        self.assertEqual(S._crash_cause(TB_DRIVER), S.CAUSE_DRIVER_CRASH)
        self.assertIsNone(S._crash_cause("build: something refused\n"))
        # A backend crash IS a finding about the construct; a driver crash is
        # this tool's own problem and belongs in no rate.
        self.assertEqual(S.classify(False, "AttributeError: x", "backend-crash"
                                   )[0], S.CLASS_CODEGEN)
        self.assertEqual(S.classify(False, "AttributeError: x", "driver-crash"
                                   )[0], S.CLASS_TOOL)

    def test_reason_is_one_line_and_bounded(self):
        cls, reason = S.classify(False, CODEGEN_MSG + "\n" + "x" * 500)
        self.assertEqual(cls, S.CLASS_CODEGEN)
        self.assertNotIn("\n", reason)
        self.assertLessEqual(len(reason), 68)

    def test_criteria_id_is_the_cache_key_input(self):
        # The contract _criteria_id() exists for: a verdict is a function of
        # the source AND the rules, so the rules must be in the key. Editing
        # THIS file changes its bytes, which is what makes a change to the
        # classification rules above invalidate every cached verdict.
        self.assertNotEqual(
            cas.formal_build_key("src", "p.mojo", S.build_flags("arm64"), ""),
            cas.formal_build_key("src", "p.mojo", S.build_flags("arm64"),
                                 S._criteria_id()))

    def test_arch_is_still_separate_in_the_key(self):
        # Classification must not have weakened the other half of the key.
        a = cas.formal_build_key("s", "p.mojo", S.build_flags("arm64"), "c")
        b = cas.formal_build_key("s", "p.mojo", S.build_flags("x86_64"), "c")
        self.assertNotEqual(a, b)


class TestReport(unittest.TestCase):
    """The summary, over a synthetic sweep — no builds, no CAS.

    run_one is stubbed at its own boundary (a Verdict in, a report out), so
    what is under test is the accounting and the wording, which is the layer
    that decides whether a reader can trust the number.
    """

    def _main(self, rows, prev=None, cas_state=(3, 2)):
        """rows: [(rel, ok, detail, cause)]. Returns (stdout, exit, ledger)."""
        import formal_sweep as mod
        files = [os.path.join(mod.REPO, r) for r, _ok, _d, _c in rows]
        by_path = {os.path.join(mod.REPO, r): (ok, d, c) for r, ok, d, c in rows}
        saved = {n: getattr(mod, n) for n in
                 ("run_one", "load_ledger", "publish_ledger", "find_source_files")}

        def fake_run_one(path, timeout, flags):
            ok, detail, cause = by_path[path]
            return mod.Verdict(ok, detail, cause, True,
                               *mod.classify(ok, detail, cause, "import os\n"))

        def fake_publish(arch, f, v):
            published.update(v)
        published = {}
        mod.run_one = fake_run_one
        mod.load_ledger = lambda arch, f: prev
        mod.publish_ledger = fake_publish
        mod.find_source_files = lambda roots: files
        mod.cas.stats.update(hits=cas_state[0], misses=cas_state[1])
        old_argv, sys.argv = sys.argv, ["formal_sweep.py", "--no-stdlib"]
        buf, code = io.StringIO(), None
        try:
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                try:
                    mod.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
            for n, v in saved.items():
                setattr(mod, n, v)
            cas.reset_stats()      # cas.stats is process-global
        return buf.getvalue(), code, published

    def test_classes_sum_to_the_file_count(self):
        rows = [("a.py", True, "", None),
                ("b.py", False, HOST_MSG, None),
                ("c.py", False, UNRESOLVED_MSG, None),
                ("d.py", False, CODEGEN_MSG, None),
                ("e.py", False, EXTERN_MSG, None),
                ("f.py", False, "timeout (> 30s)", S.CAUSE_TIMEOUT)]
        out, code, published = self._main(rows)
        m = re.search(r"classes sum to (\d+) = (\d+) files swept", out)
        self.assertIsNotNone(m, out)
        self.assertEqual(m.group(1), m.group(2))
        self.assertEqual(m.group(1), str(len(rows)))
        # Every non-PASS file is printed, under its class — nothing that used
        # to print as FAIL stops printing.
        for r in ("b.py", "c.py", "d.py", "e.py", "f.py"):
            self.assertIn(r, out)
        self.assertNotIn("a.py", out)
        # The ledger records every file, so the next run can diff it.
        self.assertEqual(published, {"a.py": S.CLASS_PASS, "b.py": S.CLASS_HOST,
                                     "c.py": S.CLASS_HOST,
                                     "d.py": S.CLASS_CODEGEN,
                                     "e.py": S.CLASS_EXTERN,
                                     "f.py": S.CLASS_TOOL})

    def test_headline_excludes_not_answerable_and_says_so(self):
        rows = ([("p%d.py" % i, True, "", None) for i in range(7)]
                + [("h%d.py" % i, False, HOST_MSG, None) for i in range(15)]
                + [("c.py", False, CODEGEN_MSG, None)])
        out, _code, _pub = self._main(rows, cas_state=(len(rows), 0))
        self.assertIn("codegen coverage: 7/8 = 87.5%", out)
        # The denominator is stated in words, not just as a number.
        self.assertIn("denominator: the 8 swept file(s) whose build could have "
                      "answered", out)
        self.assertIn("7 pass + 1 codegen = 8", out)
        self.assertIn("the 15 in a not-answerable", out)
        self.assertIn("host-import by module: os x15", out)
        # And the old all-in-one number is gone: nothing reports PASS/total.
        self.assertNotIn("24.0% pass", out)
        self.assertNotIn("FAIL=16", out)

    def test_not_answerable_alone_does_not_fail_the_run(self):
        rows = [("p.py", True, "", None),
                ("h.py", False, HOST_MSG, None),
                ("e.py", False, EXTERN_MSG, None),
                ("u.py", False, UNRESOLVED_MSG, None)]
        _out, code, _pub = self._main(rows)
        self.assertEqual(code, 0)

    def test_codegen_tool_and_unknown_all_fail_the_run(self):
        for row, why in ((("c.py", False, CODEGEN_MSG, None), "codegen"),
                         (("t.py", False, "boom", S.CAUSE_TOOL_ERROR), "tool"),
                         (("u.py", False, "imports 'zzz_nope', which is "
                           "worrying", None), "unknown")):
            out, code, _pub = self._main([("p.py", True, "", None), row])
            self.assertEqual(code, 1, why)

    def test_empty_answerable_denominator(self):
        out, code, _pub = self._main([("h.py", False, HOST_MSG, None)])
        self.assertIn("no file could be answered", out)
        self.assertEqual(code, 0)

    def test_cas_accounting_covers_every_file(self):
        rows = [("p.py", True, "", None), ("h.py", False, HOST_MSG, None),
                ("t.py", False, "timeout (> 30s)", S.CAUSE_TIMEOUT)]
        out, _code, _pub = self._main(rows, cas_state=(2, 0))
        self.assertIn("cas: 2 hit / 0 miss / 1 not cached (3 files)", out)
        self.assertIn("got no verdict at all", out)

    def test_history_accounts_for_a_file_changing_class(self):
        # The requirement: a file that used to be reported FAIL and now sits
        # in another class must be named, not silently recategorised.
        rows = [("moved.py", False, CODEGEN_MSG, None),
                ("steady.py", False, HOST_MSG, None)]
        prev = {"when": "2026-01-01T00:00:00", "arch": "arm64", "total": 3,
                "verdicts": {"moved.py": S.CLASS_HOST,
                             "steady.py": S.CLASS_HOST,
                             "gone.py": S.CLASS_PASS}}
        out, _code, _pub = self._main(rows, prev)
        self.assertIn(f"{S.CLASS_HOST} -> {S.CLASS_CODEGEN}: 1", out)
        self.assertIn("unchanged: 1", out)
        self.assertIn("in the previous report, not swept this time: 1", out)
        self.assertIn("previous report 2026-01-01T00:00:00", out)

    def test_history_says_so_when_there_is_none(self):
        out, _code, _pub = self._main([("p.py", True, "", None)], prev=None)
        self.assertIn("verdict history: none", out)


class TestLedgerKey(unittest.TestCase):
    def test_key_is_per_arch_and_per_scope(self):
        files = [os.path.join(S.REPO, "a.py"), os.path.join(S.REPO, "b.py")]
        self.assertEqual(S.ledger_key("arm64", files),
                         S.ledger_key("arm64", list(reversed(files))))
        self.assertNotEqual(S.ledger_key("arm64", files),
                            S.ledger_key("x86_64", files))
        self.assertNotEqual(S.ledger_key("arm64", files),
                            S.ledger_key("arm64", files[:1]))

    def test_ledger_key_survives_a_change_of_classification_rules(self):
        # The ledger records what the last run REPORTED, so it must NOT be
        # keyed on _criteria_id(): the run whose history matters most is the
        # first one after the rules change, and that is exactly the run whose
        # criteria id differs from every earlier run's. Here _criteria_id() is
        # this very file's hash, so if it were folded in, a sweep of this file
        # would find no history to compare against.
        self.assertEqual(
            S.ledger_key("arm64", [os.path.abspath(__file__)]),
            S.ledger_key("arm64", [os.path.abspath(__file__)]))


if __name__ == "__main__":
    unittest.main()
