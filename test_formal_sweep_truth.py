#!/usr/bin/env python3
"""Tests for the instruments: is what the formal path REPORTS true?

`test_formal_sweep.py` covers the sweep's verdict classification — which class a
build's outcome belongs in. This file covers the other half, which is the half
that was missing: whether the numbers the tools print describe the thing they
claim to describe. Three claims, each of which was false on this tree and each
of which had a mechanism in place that reported otherwise:

  1. a proof's `sorry` census was computed, stored beside the verdict, put in a
     dict by formal/build.py — and read by nobody. A proof with a thousand holes
     and a proof with none both printed `PASS`.
  2. the census could not see the holes that matter most. A `sorry` in
     `lib/ProofLib.lean` or `lib/Refine.lean` produces NO warning when a
     generated proof imports the pre-built `.olean` — and
     `test_formal_dylib.py`'s "the generated proof contains no sorry" check
     greps the GENERATED file, so it is green over three library holes,
     including the bare `sorry` every `dylib --formal` contract theorem rests
     on. And `extern_<sym>_step : True := by trivial`, which is what the
     generators emit at every extern call site, is a complete proof of nothing
     at all and reports ZERO sorries.
  3. the sweep's largest bucket asserted something false. `not-answerable/
     host-import`'s own blurb said a host import is "outside this backend's
     reach, and not fixable", which is true of `subprocess` and false of `os`.

Nothing here builds a program and nothing here runs Lean except where a case
says so and skips without it. The units are the census and the classifier.

    python3 test_formal_sweep_truth.py [-v]
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import formal_sweep as S
from formal import lean as L

LIB = os.path.join(HERE, "lib")


def _lean() -> str | None:
    return L.find_lean(HERE)


# ── 1. vacuity: a complete proof of nothing ──────────────────────────────────
#
# These are the two shapes and the two shapes only (see `vacuous_declarations`).
# The generator's real text is quoted first for each, so the scanner is pinned
# against what the tree emits rather than against what this file invented.
EXTERN_STEP = """import ProofLib

theorem main_pre_0 (x0_0 : UInt64) (x0_1 : UInt64) (x0_2 : UInt64) :
    True := by trivial
"""


class TestVacuity(unittest.TestCase):
    def test_a_true_statement_is_vacuous(self):
        got = L.vacuous_declarations(EXTERN_STEP)
        self.assertEqual([(n, sh) for n, sh, _ in got],
                         [("main_pre_0", L._VACUOUS_TRUE)],
                         "a theorem stated as `True` is admitted by a complete "
                         "proof and asserts nothing; it must be reported")

    def test_the_generated_extern_step_is_vacuous(self):
        """The shape both proof generators actually emit.

        `formal/arm64_proof_gen.py` and `formal/x86_64_proof_gen.py` write
        `theorem extern_<sym>_step :\\n  True := by\\n  trivial` at every extern
        call site, and it is the only thing standing between the machine model
        and the program's own behaviour across a `mojo_*` or libc call. It
        counts ZERO sorries. This is the case the whole instrument exists for.
        """
        got = L.vacuous_declarations(
            "theorem extern_mojo_print_step :\n  True := by\n  trivial\n")
        self.assertEqual([n for n, _s, _l in got], ["extern_mojo_print_step"])

    def test_a_forall_into_true_is_vacuous(self):
        # lib/ProofLib.lean:4617, verbatim. Inhabited for every `observables`,
        # which is what makes the dylib proofs' `<export>_semantics` theorems
        # vacuous; the empty `dylib_observables := []` the generator emits is a
        # second, independent reason the same theorem says nothing.
        got = L.vacuous_declarations(
            "def Semantics (image : DylibImage) (export_ : DylibExport)\n"
            "    (observables : List (UInt64 → UInt64)) : Prop :=\n"
            "  ∀ observable, observable ∈ observables → True\n")
        self.assertEqual([(n, sh) for n, sh, _ in got],
                         [("Semantics", L._VACUOUS_GOAL)])

    def test_the_librarys_semantics_is_not_vacuous(self):
        """Run against this tree's real lib/, not a fixture.

        `DylibExport.Semantics` WAS `∀ o, o ∈ l → True`, and this test pinned
        that the scanner reported it.  [3] replaced it with `Total ∧
        Functional`, a real claim about the machine (`Semantics_refutable`
        exhibits an export that fails it), so the real-tree assertion is now
        the negative one: the scanner must NOT report it.  The fixture test
        above still pins that the old shape IS reported, so the scanner is
        tested in both directions.
        """
        path = os.path.join(LIB, "ProofLib.lean")
        if not os.path.isfile(path):
            self.skipTest("lib/ProofLib.lean is not here")
        with open(path) as f:
            text = f.read()
        self.assertIn("def Semantics (image : DylibImage)", text,
                      "DylibExport.Semantics is gone or renamed; this negative "
                      "check would then pass for the wrong reason")
        got = L.vacuous_declarations(text)
        self.assertNotIn("Semantics", [n for n, _s, _l in got],
                         "DylibExport.Semantics is reported vacuous again -- it "
                         "is the proposition every dylib proof's semantics "
                         "theorem is stated with")

    def test_a_real_theorem_is_not_vacuous(self):
        """The negative half, and it is the half that keeps the census honest.

        A census that flags everything is as useless as one that flags nothing:
        it sends the reader to declarations that were fine.
        """
        got = L.vacuous_declarations(
            "theorem add_zero (n : Nat) : n + 0 = n := by simp\n"
            "def double (n : Nat) : Nat := n * 2\n"
            "def IsList (l : List Nat) : Prop := l.length ≥ 0\n"
            "theorem two : 2 + 2 = 4 := by native_decide\n")
        self.assertEqual(got, [])

    def test_binders_are_not_mistaken_for_the_statement(self):
        """The bug a naive "text after the last `)`" rule has.

        `offset_stub (image : DylibImage) (export_ : DylibExport) : offset image
        export_ = …` has a RETURN type in parentheses on some spellings; a
        scanner that takes the wrong span either misses real findings or invents
        them. Neither is acceptable for a census.
        """
        got = L.vacuous_declarations(
            "theorem t (x : Nat) (y : Nat) : (x = y) := by simp\n"
            "def f (a : Nat) (b : Nat) : Bool := a == b\n")
        self.assertEqual(got, [])

    def test_a_def_returning_a_value_is_never_vacuous(self):
        """`def f : Nat := True` is a NONSENSE program, not a vacuous proof.

        The `True` in it is a value, and reporting it would put a nonsense
        declaration in a list of things that assert nothing. Only a `Prop`-typed
        `def` is judged, and only on its body.
        """
        self.assertEqual(L.vacuous_declarations("def f : Nat := 1 + 1\n"),
                         [])


# ── 2. the library census: holes Lean will never re-report ───────────────────


class TestLibraryCensus(unittest.TestCase):
    def test_a_module_that_cannot_be_measured_is_absent_not_zero(self):
        """The distinction the whole function turns on.

        A dict that returned `{stem: (0, ())}` for a module it could not
        elaborate would make "the library has no holes" reportable by a tool
        that never looked, which is the exact failure this instrument exists to
        stop. `library_census` documents it; this makes it executable.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            got = L.library_census("definitely-not-lean", td, measure=False)
        self.assertEqual(got, {}, "no source, no measurement, and an absent "
                                 "entry is the only honest way to say that")

    def test_the_census_survives_the_verdict_cache(self):
        """A cached verdict must not come back as a clean library.

        The record stores the library's figures beside the verdict's, so the
        cached path reports the same census the measured one did. Reading a
        v2-shaped body is a MISS, not a zero — asserted here by round-tripping
        a record and by refusing to read one that has no library line.
        """
        detail = "ProofLib\tin_image_stub\toffset_stub\nRefine\tstub"
        lib = L._lib_from_record({}, 3, detail)
        self.assertEqual(lib["ProofLib"],
                         (2, ("in_image_stub", "offset_stub")))
        self.assertEqual(lib["Refine"], (1, ("stub",)))
        # The encoding must survive a name that is not a bare word, which is
        # what a dylib proof's per-export theorem looks like: `Foo.bar`.
        dotted = L._lib_from_record({}, 1, "ProofLib\tDylib.triple_in_image")
        self.assertEqual(dotted["ProofLib"], (1, ("Dylib.triple_in_image",)))
        # And the totals must round-trip back into the same record, so a cached
        # verdict and a measured one cannot print different library lines.
        self.assertEqual(L._lib_totals(lib), (3, detail))
        # -1 is UNMEASURED, and it must survive the round trip as absence.
        self.assertEqual(L._lib_from_record({}, -1, ""), {})
        self.assertEqual(L._lib_totals({}), (L._LIB_UNMEASURED, ""))

    def test_the_library_holes_are_exactly_the_known_ones(self):
        """The measured claim, on this tree, with Lean.

        There used to be three holes in `lib/` (`in_image_stub`,
        `semantics_stub`, `dylib_export_contract_stub`), and this test pinned
        that the census found and named them.  All three are closed: the first
        is the decidable `in_image_decide`, the second went with the vacuous
        `Semantics`, the third was deleted for asserting every export is the
        identity.  So the set of known holes is now empty, which is the same
        set `test_formal_dylib.py`'s `KNOWN_LIB_HOLES` pins.

        "The census reports zero" is only evidence of "there are zero" if the
        census can see a hole at all, and that is what `TestLeanOutput` pins
        against the toolchain's real output.  Here, every library module must
        have been MEASURED, so a module the census silently failed to reach
        does not read as clean.  Skipped without Lean.
        """
        lean = _lean()
        if not lean:
            print("    SKIP: no lean found (library hole census)")
            return
        # measure=False on purpose. The measurement is a full elaboration of
        # lib/ProofLib.lean (~90s, 27MB), and it is not this test's job to pay
        # it: `ensure_library` captures it for free out of the run that builds
        # the .olean, which the `prooflib` step does once, before the fan-out.
        # So in a gated run the data is here; in a bare run on a tree whose
        # .oleans predate the census, it is not, and the honest answer then is
        # a skip that says so.
        lib = L.library_census(lean, LIB, measure=False)
        if not lib:
            print("    SKIP: no library module has a recorded census yet "
                  "(run the `prooflib` step, or any proof check on a cold "
                  "store, to measure it)")
            return
        self.assertIn("ProofLib", lib,
                      f"ProofLib was not measured (measured: {sorted(lib)}); "
                      f"an unmeasured module reads exactly like a clean one")
        KNOWN_LIB_HOLES: set = set()
        named = {name for _count, names in lib.values() for name in names}
        total = sum(got[0] for got in lib.values())
        self.assertEqual(
            named - KNOWN_LIB_HOLES, set(),
            f"lib/ admits {total} `sorry`(s) nobody has recorded: "
            f"{sorted(named - KNOWN_LIB_HOLES)} -- every dylib proof rests on "
            f"these, and Lean does not warn about a hole in an imported .olean")


class TestLeanOutput(unittest.TestCase):
    """Two traps that each made this census report zero holes, measured.

    Both were found by running the measurement and getting `0` out of a file
    that contains two `sorry`s, which is the only way this kind of instrument
    is ever debugged. Both are cheap to state and easy to reintroduce, so both
    are pinned.
    """

    # What the pinned toolchain really prints, for the two holes in
    # lib/ProofLib.lean, and the shape of the source they are in.
    STDOUT_FORM = ("/src/lib/ProofLib.lean:4624:8: warning: declaration uses "
                   "`sorry`\n/src/lib/ProofLib.lean:4627:8: warning: "
                   "declaration uses `sorry`\n")
    SRC = ["theorem in_image_stub (i : D) (e : X) :",
           "    InImage i e := by sorry",
           "",
           "theorem semantics_stub (i : D) (e : X) (o : L) :",
           "    Semantics i e o := by sorry"]

    def test_the_warning_is_on_stdout(self):
        """The trap that reported a two-hole file as clean.

        Lean writes its diagnostics to STDOUT. A probe — or a parser — that
        reads only `result.stderr` sees an empty string for a run that reported
        two holes, and `0` looks like an answer. Everything here parses
        stdout + stderr for that reason, and this is the assertion that says so
        with the toolchain's real wording in it.
        """
        got = L._census_from_output(self.STDOUT_FORM, self.SRC)
        self.assertEqual(got[0], 2, "the real wording must be recognised, on "
                                    "whichever stream it arrives")
        # The lines are the library's (4624/4627) and the source is a 5-line
        # excerpt, so the names degrade to locations — which is the point of
        # the next case, and why the count above is the load-bearing claim.
        self.assertEqual(got[1], ("line 4624", "line 4627"))

    def test_a_hole_line_resolves_to_its_declaration(self):
        """The other half: with the real source, the name comes back.

        A count of 2 does not tell a reader where to look; "in_image_stub,
        semantics_stub" is what `test_formal_dylib.py`'s grep for `sorry` in
        the generated file cannot produce, because these two holes are not in
        any generated file.
        """
        out = ("/src/lib/ProofLib.lean:2:8: warning: declaration uses `sorry`\n"
               "/src/lib/ProofLib.lean:5:8: warning: declaration uses `sorry`\n")
        got = L._census_from_output(out, self.SRC)
        self.assertEqual(got, (2, ("in_image_stub", "semantics_stub")))

    def test_a_line_outside_the_source_does_not_borrow_a_name(self):
        """The bug that made a count come back SHORT rather than wrong.

        Clamping the line index resolves every out-of-range hole to the last
        declaration in the file, and two such holes then de-duplicate to one —
        a short count that is indistinguishable in the output from a right one.
        """
        got = L._census_from_output(self.STDOUT_FORM, self.SRC)
        self.assertEqual(got[0], 2,
                         "two holes reported at 4624 and 4627 are two holes, "
                         "not one name seen twice")
        self.assertEqual(len(set(got[1])), 2)
        self.assertEqual(L._declaration_at(self.SRC, 9999), "line 9999")
        self.assertEqual(L._declaration_at(self.SRC, 4), "semantics_stub")

    def test_an_unreadable_source_degrades_to_locations_not_to_zero(self):
        got = L._census_from_output(self.STDOUT_FORM, None)
        self.assertEqual(got[0], 2, "the COUNT must not depend on being able "
                                    "to name the declarations")
        self.assertTrue(all(":462" in n for n in got[1]),
                        f"without the source the names degrade to locations, "
                        f"which are still actionable: {got[1]}")

    def test_a_losing_tactic_alternative_is_not_a_hole(self):
        """The property that makes this a census rather than a grep.

        `all_goals first | native_decide | sorry` contains the word in text
        whether or not the fallback ran, so a textual count never goes down.
        Lean warns only for the declaration that actually admitted one, so
        this parse — and only this parse — is the sound one.
        """
        clean = ("/src/p.lean:10:1: warning: declaration uses `sorry`\n")
        self.assertEqual(L._census_from_output(clean, None)[0], 1)
        self.assertEqual(L._census_from_output("", None)[0], 0)

    def test_the_measurement_directory_is_reached_by_an_absolute_path(self):
        """`LEAN_PATH` is resolved against the elaborating process's cwd.

        The census elaborates copies in a temp directory with that directory as
        the cwd, so a relative `lib` in `LEAN_PATH` points at `<tempdir>/lib`,
        every cross-module import fails, and the modules after the first are
        reported UNMEASURED. That is what happened: ProofLib measured (from the
        CAS) and X86/work/Refine silently absent, which reads exactly like
        "the library is nearly clean". Asserted at the level where it was
        wrong, because asserting it at the level of a real measurement costs
        90 seconds of Lean per run.
        """
        import inspect
        src = inspect.getsource(L.library_census)
        self.assertIn("os.path.abspath(lib_dir)", src,
                      "the LEAN_PATH handed to the measurement must be "
                      "absolute")
        self.assertIn("os.pathsep.join((td, os.path.abspath(lib_dir)))", src)


# ── 3. the report: a sorried proof and a vacuous one are distinguishable ─────


class TestCensusReport(unittest.TestCase):
    def _lines(self, tmpdir, proof_text, lib=None, n_sorries=0):
        path = os.path.join(tmpdir, "p_proof.lean")
        with open(path, "w") as f:
            f.write(proof_text)
        return L._census_lines(path, tmpdir, n_sorries, lib or {})

    def test_a_vacuous_proof_says_so_and_a_clean_one_says_nothing(self):
        import tempfile
        vacuous = ("theorem extern_mojo_print_step :\n  True := by\n"
                   "  trivial\n")
        clean = "theorem add_zero (n : Nat) : n + 0 = n := by simp\n"
        # A MEASURED, hole-free library: "silent" is only available to a proof
        # whose own holes and whose library's are both known, which is exactly
        # the condition under which silence is a claim rather than a shrug.
        clean_lib = {"ProofLib": (0, ()), "Refine": (0, ()), "X86": (0, ()),
                     "work": (0, ())}
        with tempfile.TemporaryDirectory() as td:
            a = self._lines(td, vacuous, clean_lib)
            b = self._lines(td, clean, clean_lib)
        self.assertTrue(any("vacuous" in ln for ln in a),
                        f"a proof whose only theorem is `True` must be "
                        f"reported: got {a}")
        self.assertIn("extern_mojo_print_step", "\n".join(a),
                      "the report must NAME the vacuous declaration")
        self.assertEqual(b, [], "a clean proof over a measured clean library "
                                "must be silent, or a line in the log stops "
                                "meaning anything")

    def test_a_sorried_proof_and_a_vacuous_one_are_different_lines(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            sorried = self._lines(td, "theorem t : 1 = 1 := by sorry\n",
                                  n_sorries=1)
            vacuous = self._lines(td, "theorem extern_x_step :\n  True := by\n"
                                    "  trivial\n")
        self.assertIn("1 declaration(s) admitted a `sorry`", sorried[0])
        self.assertIn("0 declaration(s) admitted a `sorry`", vacuous[0])
        self.assertNotEqual(sorried, vacuous,
                            "a hole and a vacuous theorem are different "
                            "failures and must not read the same")

    def test_an_unmeasured_library_is_said_to_be_unmeasured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            lines = self._lines(td, "theorem t : 1 = 1 := by sorry\n")
        joined = "\n".join(lines)
        self.assertIn("NOT MEASURED", joined,
                      "a proof with no local hole and no measurement of the "
                      "library it rests on must say so")
        self.assertIn("NOT a report of zero", joined,
                      "0 and unmeasured are different facts and the report "
                      "must not let a reader conflate them")

    def test_a_library_hole_is_reported_even_with_no_local_hole(self):
        """The case that made this necessary.

        `test_formal_dylib.py` greps the GENERATED proof for `sorry` and the
        generated proof has none — the holes are in the `.olean` it imports,
        which Lean does not re-report. So a run with zero local sorries is
        still a run resting on admitted holes, and the report has to say so.
        """
        import tempfile
        lib = {"ProofLib": (2, ("in_image_stub", "semantics_stub")),
               "Refine": (1, ("dylib_export_contract_stub",))}
        with tempfile.TemporaryDirectory() as td:
            lines = self._lines(td, "theorem t : 1 = 1 := by native_decide\n",
                                lib)
        joined = "\n".join(lines)
        self.assertIn("3 declaration(s) in 2 module(s) admitted a `sorry`",
                      joined)
        self.assertIn("dylib_export_contract_stub", joined,
                      "the library hole must be NAMED, not only counted")

    def test_emit_is_silent_when_clean_and_loud_when_not(self):
        clean, dirty = [], ["proof census: 1 vacuous"]
        for mode, lines, expect in (("", clean, ""), ("", dirty, "1 vacuous"),
                                    ("always", clean, "no admitted"),
                                    ("off", dirty, "")):
            env = {"FORMAL_CENSUS": mode} if mode else {}
            saved = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            for k in ("FORMAL_CENSUS",):
                if k not in env:
                    os.environ.pop(k, None)
            try:
                buf = io.StringIO()
                with redirect_stderr(buf):
                    L._emit_census(lines)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            self.assertIn(expect, buf.getvalue(),
                          f"FORMAL_CENSUS={mode!r} on {lines!r} printed "
                          f"{buf.getvalue()!r}, which does not contain "
                          f"{expect!r}")


# ── 4. the sweep's reach split, and the system-module-call class ─────────────


class TestSweepReach(unittest.TestCase):
    def test_the_mirror_and_the_authority_agree(self):
        """The anti-rot mechanism for `IN_REACH_HOST_MODULES`.

        formal/imports.py owns the split (it is the module the build consults).
        This file's copy exists only until that lands, and a fallback that can
        disagree with the authority is worse than none — so the two are
        compared here, and the day [4]'s split lands and differs, this fails
        and says to delete the mirror.
        """
        in_reach, _unreachable, where = S._host_tiers()
        if where is not None:
            self.assertEqual(
                {n for n in in_reach if n.split(".")[0] in in_reach},
                set(S.IN_REACH_HOST_MODULES),
                f"formal/imports.py's {where} and this tool's mirror "
                f"disagree; formal/imports.py is the authority, so delete "
                f"IN_REACH_HOST_MODULES and read the split")
        else:
            self.assertEqual(set(S.IN_REACH_HOST_MODULES),
                             {"os", "sys", "math", "struct", "time", "json",
                              "re"},
                             "the pinned mirror must name the modules the "
                             "brief names, and nothing else")

    def test_the_mirror_is_a_subset_of_what_the_build_refuses(self):
        """A reach split that includes a module the build can resolve is a
        different defect from one that excludes a module it cannot: the first
        reports a file as unreachable when it is not."""
        from formal.imports import HOST_MODULES
        self.assertLessEqual(set(S.IN_REACH_HOST_MODULES),
                             {n.split(".")[0] for n in HOST_MODULES})

    def test_in_reach_host_modules_stay_out_of_every_rate(self):
        """Explicit, because the temptation is exactly the wrong move.

        They are unanswerable TODAY, and moving them into ANSWERABLE would
        raise the coverage rate with work nobody has done. The brief says to
        size the work, not to improve the number, so this is pinned rather than
        left to judgement.
        """
        for cls in S.ANSWERABLE:
            self.assertNotIn(S.CLASS_HOST, (cls,),
                             "host-import must not be answerable")
        self.assertNotIn(S.CLASS_SYSCALL, S.ANSWERABLE)
        self.assertNotIn(S.CLASS_SYSCALL, S.DIRTY,
                         "a fact about the target must not be able to fail a "
                         "run — that is what makes it a target fact")

    def test_unreachable_names_are_unreachable(self):
        """The other half of the split, asserted rather than asserted-about.

        `subprocess`, `ctypes`, `asyncio`, `threading` and `socket` each need
        something this target does not have: a host process, an embedded
        interpreter, an event loop, a second thread, a kernel socket. If one of
        them is ever called in reach, the summary's "permanent" half is a lie
        and the line stops being a size.
        """
        for name in ("subprocess", "ctypes", "asyncio", "threading", "socket",
                     "tempfile"):
            self.assertNotIn(name, S.IN_REACH_HOST_MODULES)


class TestSystemModuleCall(unittest.TestCase):
    # `socket` and not `json`, and not `math`: `json` used to be the host module
    # named here and `formal/hostmods/json.mojo` landed in 2026-09-30; then
    # `math` was named here, on the same reasoning, and `formal/hostmods/math.
    # mojo` landed too. A name in this slot is a CLAIM that it has no Mojo
    # source, and the claim stops being true the day the module is written — at
    # which point the name leaves HOST_MODULES entirely (it is not refused at
    # all any more) and this test fails on the tool being right. The premise is
    # therefore asserted below rather than trusted: a fixture that has quietly
    # stopped being an example of anything is a silent hole in a suite whose
    # whole subject is the difference between a fact about the target and a gap
    # in the backend.
    SRC = "import os\nimport socket\n\ndef main():\n    pass\n"

    def test_the_example_is_still_a_host_module_with_no_reach(self):
        # Read from the tool's own tables, not from this comment: the rule
        # under test is structural (`mod in HOST_MODULES`, and the file imports
        # it), so its premise is a fact about two sets that this tree edits
        # whenever a hostmod is written.
        from formal.imports import HOST_MODULES
        self.assertIn("socket", HOST_MODULES)
        self.assertNotIn("socket", S.IN_REACH_HOST_MODULES)
        self.assertTrue(S._source_imports(self.SRC, "socket"))

    def test_a_self_describing_message_is_a_target_fact(self):
        got = S._system_module_call(
            "build: os.getenv is a system module call: os has no Mojo source "
            "on any path", self.SRC)
        self.assertEqual(got, "os")

    def test_a_message_naming_a_host_member_is_a_target_fact(self):
        got = S._system_module_call(
            "build: socket.recv() cannot be lowered: socket is not available "
            "here", self.SRC)
        self.assertEqual(got, "socket")

    def test_a_construct_refusal_is_not(self):
        """The negative that matters most, because the fallback is `codegen`.

        A frame-receiver refusal mentions dotted names constantly, and this
        repo's own files are full of `self.field`. If the rule fired on those,
        30-odd real codegen findings would silently become target facts and the
        headline would improve by about a quarter without anyone writing code.
        """
        for term in ("gen.type_checker is a field of gen, and GimpleGen has no "
                     "field 'type_checker'",
                     "a Spec receiver is returned from the function that "
                     "created it on this path",
                     "Traceback (most recent call last): x = 1"):
            self.assertEqual(S._system_module_call(term, self.SRC), "",
                             f"a construct refusal was misfiled as a target "
                             f"fact: {term!r}")

    def test_a_dotted_name_in_an_unimported_module_is_not(self):
        """The file's own source is the confirmation.

        A diagnostic that happens to contain `socket.recv` does not make the
        file a system-module call; a file that never mentions `socket` cannot
        be one. The source is spelled out here rather than taken from SRC
        because SRC deliberately DOES import the name the rule reads, and a
        negative that reused it would be testing the opposite of what it says.
        """
        self.assertEqual(
            S._system_module_call("build: socket.recv cannot be lowered",
                                  "import os\n\ndef main():\n    pass\n"),
            "")

    def test_classify_routes_it_out_of_codegen(self):
        cls, reason = S.classify(
            False, "build: os.getenv: os has no Mojo source on any path",
            None, self.SRC)
        self.assertEqual(cls, S.CLASS_SYSCALL)
        self.assertIn("os", reason)
        self.assertNotEqual(cls, S.CLASS_CODEGEN)

    def test_it_is_not_answerable_and_not_dirty(self):
        """Stated again at the point of use, because this class exists only to
        be outside both sets and a later edit could add it to either."""
        self.assertNotIn(S.CLASS_SYSCALL, S.ANSWERABLE)
        self.assertNotIn(S.CLASS_SYSCALL, S.DIRTY)
        self.assertIn(S.CLASS_SYSCALL, S.CLASS_ORDER)
        self.assertIn(S.CLASS_SYSCALL, S.CLASS_BLURB,
                      "every class in CLASS_ORDER needs a blurb; the report is "
                      "the tool's contract with a reader who has not read it")


# ── 4. an interpreter that cannot import the backend ─────────────────────────
#
# Every file in a sweep is answered by `fire.py build --formal` in a child of
# the interpreter running the sweep, so one that cannot import `formal.build`
# cannot answer a single file. It fails in the least visible way there is: each
# child dies inside an import, the classifier reads the traceback as
# `backend-crash`, and the run comes back as a finding per FILE about the
# compiler's plumbing. Measured with the `python3` a shell finds by default on
# this machine (Xcode's 3.9.6, which is what `python3` resolves to before any
# Homebrew directory is on PATH): 392 of 392 files, `backend-crash`, in about a
# minute. So the guard is asserted here in both halves — it fires on a backend
# that will not import, and it is silent on one that will.
class TestInterpreterGuard(unittest.TestCase):
    def test_a_healthy_interpreter_is_asked_nothing(self):
        self.assertEqual(
            S.interpreter_diagnosis(), "",
            "this file is running, so the backend imports; the guard must not "
            "speak on a sweep that could have run")

    def test_a_backend_that_will_not_import_stops_the_sweep_before_any_build(self):
        """The failure branch, and it is a failure branch that COST a session.

        `formal/model.py` annotates `def call_callee_name(func) -> str | None`,
        which 3.9 evaluates eagerly and cannot: every x86-64 sweep run on the
        default `python3` reported one `backend-crash` per file and no coverage
        number at all. Exit 2 is the documented status for a sweep that did not
        run, and nothing may be swept or cached on the way out.
        """
        boom = TypeError("unsupported operand type(s) for |: 'type' and "
                         "'NoneType'")
        argv, real = sys.argv, S.importlib.import_module

        def refuse(name, *a, **kw):
            if name == "formal.build":
                raise boom
            return real(name, *a, **kw)

        S.importlib.import_module = refuse
        err = io.StringIO()
        try:
            sys.argv = ["formal_sweep.py", "--no-stdlib", "formal/model.py"]
            with redirect_stderr(err):
                with self.assertRaises(SystemExit) as caught:
                    S.main()
        finally:
            S.importlib.import_module = real
            sys.argv = argv
        self.assertEqual(caught.exception.code, 2,
                         "a sweep that could not build anything is 2 ('did not "
                         "run'), never 1 ('there were findings')")
        said = err.getvalue()
        self.assertIn("could have been built", said)
        self.assertIn(str(boom), said, "the reader needs the exception itself, "
                     "not a paraphrase of it")
        self.assertIn(sys.executable, said,
                      "the message has to name the interpreter that failed, or "
                      "it is advice about the wrong python")
        self.assertIn(sys.version.split()[0], said)
        self.assertIn("backend-crash", said,
                      "the reader needs to know what the run WOULD have said, "
                      "because the symptom they came here with is a wall of "
                      "those lines")
        self.assertNotIn("Total:", said, "the sweep must stop before it "
                         "announces a scope it cannot cover")


# ── 5. the launcher: a Lean run that will not stop is a loud failure ────────
#
# On 2026-10-02 the user killed ten `lean` processes on this machine by hand,
# some of them hundreds of CPU-hours old. Every launch site that had a bound at
# all had a WALL bound (`subprocess.run(timeout=1200)`), and
# `formal/x86_64_endtoend_test.py` had none, and `maxHeartbeats` does not meter
# the thing that spins: `native_decide` and kernel reduction. So the bound has
# to be wall AND cpu, it has to kill the tree, and it has to be impossible to
# read as a pass. That is what these exercise, on a file that really does not
# terminate, at a cap small enough to keep the test cheap.
#
# The file is `partial def` + `native_decide`, which is the cheapest genuine
# non-terminating elaboration there is: Lean's partial fixpoint compiles to an
# `implemented_by` that evaluates forever, and `native_decide` runs that
# outside the heartbeat counter entirely. So it is the same failure class as the
# processes above, not a simulation of one — measured below at ~4 s of CPU
# before it is stopped.

#: `loop 0` reduces forever, so `loop 0 = 0` is not decidable by evaluation and
#: `native_decide` never returns from trying. Nothing here imports: the point is
#: that a LOOP is bounded, and a test that had to import the 27 MB library to
#: demonstrate it would cost 90 s to prove a claim about a `def`.
LOOPING_LEAN = """partial def loop : Nat → Nat
  | _ => loop 0

theorem loop_is_zero : loop 0 = 0 := by
  native_decide
"""

#: The negative control, and it matters that it is a REAL file rather than a
#: mocked run: a launcher that reported "exceeded" for everything would pass a
#: test that only ever launched a loop.
CHECKS_LEAN = """example : (2 : Nat) + 2 = 4 := by decide
"""


class TestLeanLauncher(unittest.TestCase):
    """`run_lean`'s bounds, on files that really do and really do not stop."""

    def setUp(self):
        self.lean = _lean()
        if not self.lean:
            self.skipTest("lean not installed (see ./lean-toolchain)")
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="lean_bounds_")
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        self.loop = self._write("Loop.lean", LOOPING_LEAN)
        self.checks = self._write("Checks.lean", CHECKS_LEAN)

    def _write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_a_finishing_run_is_not_reported_as_exceeded(self):
        """The control, and the reason the loop below means anything.

        A launcher that reported a breach on every run — a flag whose name
        matched the wrong argv, a bound of zero — would satisfy every other case
        in this class.
        """
        run = L.run_lean(self.lean, [os.path.basename(self.checks)], cwd=self.dir)
        self.assertIsNone(run.exceeded, "a file Lean checked said nothing: "
                                       f"{run.exceeded}")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout + run.stderr, "", "and it said no error")

    def test_a_looping_elaboration_is_killed_within_the_wall_bound(self):
        """The case that cost the user ten processes: a small WALL bound, and a
        file that would otherwise run until somebody noticed.

        Three things are asserted because each is a way this could be defeated:
        it is reported as `exceeded` (not as a normal failure, not as success),
        the message NAMES the bound, and the exit status is not 0 — the last one
        is the trap, because `procrun.kill_group` reaps the child itself, so
        `Popen` reports **0** for a process that was killed, and a caller that
        only tested `returncode == 0` would call this proof checked.
        """
        run = L.run_lean(self.lean, [os.path.basename(self.loop)], cwd=self.dir,
                         wall_s=5, cpu_s=120)
        self.assertIsNotNone(run.exceeded,
                             "a non-terminating elaboration returned as a "
                             "normal run: this is the bug this file exists for")
        self.assertIn("wall", run.exceeded)
        self.assertIn("5s", run.exceeded)
        self.assertNotEqual(run.returncode, 0,
                            "a killed run must not report success, whatever "
                            "the reaper left in `returncode`")
        self.assertLessEqual(run.wall_s, 20,
                             "and it must not overshoot its own bound by the "
                             "length of a kill")

    def test_the_cpu_bound_fires_while_the_wall_clock_is_still_fine(self):
        """The bound that matters on this machine, and the one that was absent.

        `lean` runs a thread pool, so an elaboration that will not terminate can
        burn CPU while its wall clock looks entirely ordinary — which is why the
        processes the user killed were measured in CPU-hours. A wall-only bound
        is satisfied by that run for as long as the machine is quiet.
        """
        run = L.run_lean(self.lean, [os.path.basename(self.loop)], cwd=self.dir,
                         wall_s=600, cpu_s=2)
        self.assertIsNotNone(run.exceeded,
                             "2 s of CPU was spent and nothing said so")
        self.assertIn("CPU", run.exceeded)
        self.assertNotEqual(run.returncode, 0)
        self.assertLessEqual(run.wall_s, 30, "…and the cpu bound stopped it, "
                                             "rather than waiting for 600 s")

    def test_nothing_survives_the_bound(self):
        """The kill is of the TREE, and this is what says so.

        `kill_group` walks `ps` and kills children before parents; the assertion
        is that the process group the run was given (`start_new_session`, which
        is why `LeanRun.pgid` exists) holds nothing once `run_lean` returns. An
        orphan here is not a slow test, it is one of the hundred-CPU-hour
        processes this class is about — and it is invisible to `returncode`, to
        the test that spawned it, and to the suite that ran it.
        """
        import time as _time
        import procrun
        run = L.run_lean(self.lean, [os.path.basename(self.loop)], cwd=self.dir,
                         wall_s=4, cpu_s=120)
        self.assertIsNotNone(run.exceeded)
        self.assertNotEqual(run.pgid, 0, "no pgid means the run was never given "
                                         "a group to kill, so the tree claim "
                                         "below would be vacuous")
        _time.sleep(0.5)                 # the kill is synchronous; this is slack
        self.assertEqual(procrun.group_pids(run.pgid), [],
                         "a process from the killed run is still running in "
                         "its process group")

    def test_a_breach_reports_no_hole_count(self):
        """`None`, not `0`, and that is the whole difference.

        A killed elaborator printed a PREFIX of the file's warnings. Reporting
        the prefix as the count says "N holes", reporting 0 says "measured, no
        holes", and only `None` says "nothing was measured" — which is the fact,
        and which `_census_lines` already knows how to print.
        """
        ok, detail, n_sorries, exceeded = L._run_lean(
            self.loop, self.dir, self.lean, 5)
        self.assertFalse(ok)
        self.assertIsNotNone(exceeded, "the breach must be its own return, not "
                                       "something a caller infers from detail")
        self.assertEqual(n_sorries, None,
                         "an unmeasured census reported as a count is the "
                         "failure this module keeps arguing against")
        self.assertIn("lean exceeded", detail)

    def test_lean_gets_its_own_bounds_too(self):
        """`-j`, `-M` and `-T` are passed, so a runaway can stop ITSELF.

        `-T` is Lean's own default (200000) rather than something larger, on
        purpose: every generated proof overrides it with
        `set_option maxHeartbeats 20000000`, so raising it here would buy
        nothing and could only let a command that does NOT override it spin
        longer. It is passed because pinning the value makes it a bound of this
        repository's policy rather than of whatever the toolchain's default
        happens to be.
        """
        flags = L.lean_flags()
        self.assertEqual(flags, ["-j", str(L.LEAN_THREADS), "-M",
                                 str(L.LEAN_MEMORY_MB), "-T",
                                 str(L.LEAN_HEARTBEATS)])
        self.assertEqual(L.LEAN_HEARTBEATS, 200000,
                         "Lean's own default, not a raised one — raising it "
                         "loosens every command that does not override it")
        # `-M` is above what the work needs and not far above it. The floor is
        # measured, not chosen: with `-M 4096` the ProofLib build FAILS ("(kernel)
        # excessive memory consumption detected", after 43 s and 7.0 GB), so a
        # 4 GB ceiling is not a tighter policy — it is a red suite. The fact
        # that the largest module needs 7.8 GB is debt, and it is filed as
        # `prooflib`'s `memwhy` in tools/suite.py rather than paid for by
        # refusing to build the library.
        self.assertGreaterEqual(L.LIBRARY_MEMORY_MB, 8192,
                                "lib/ProofLib.lean peaks at 7.82 GB; below that "
                                "the build is killed by Lean's own ceiling")
        self.assertLess(L.LIBRARY_MEMORY_MB, 16 * 1024,
                        "…and it is still a ceiling, not a blank cheque")
        self.assertGreaterEqual(L.LEAN_MEMORY_MB, 6144,
                                "the largest generated proof measured peaks at "
                                "3.00 GB, so this is 2x the real need")
        self.assertLess(L.LEAN_MEMORY_MB, L.LIBRARY_MEMORY_MB,
                        "two kinds of work with two measured peaks; one number "
                        "for both would have to be the larger")

    def test_the_library_bound_is_the_only_one_an_environment_may_raise(self):
        """The escape hatch, and why it is exactly one.

        `FORMAL_LEAN_LIBRARY_*` exists because the library build is the one
        legitimate step whose cost cannot be bounded in advance. A proof bound
        the environment can lift is not a bound: the thing that needs lifting
        during a runaway is precisely the thing somebody would lift it for.
        """
        import os as _os
        old = {k: _os.environ.get(k) for k in
               ("FORMAL_LEAN_LIBRARY_WALL_S", "FORMAL_LEAN_LIBRARY_CPU_S")}
        try:
            _os.environ["FORMAL_LEAN_LIBRARY_WALL_S"] = "4321"
            self.assertEqual(L.library_bounds()[0], 4321.0)
            _os.environ["FORMAL_LEAN_LIBRARY_CPU_S"] = "not-a-number"
            self.assertEqual(L.library_bounds()[1], L.LIBRARY_CPU_S,
                             "a typo in the one escape hatch must not turn it "
                             "into an unbounded run")
        finally:
            for k, v in old.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v
        self.assertEqual(L.library_bounds(), (L.LIBRARY_WALL_S, L.LIBRARY_CPU_S))

    def test_the_bounds_are_above_what_the_real_measurements_needed(self):
        """The policy is sized from measurement, so this pins the relationship.

        The measurements are in `formal/lean.py`'s docstring, and they are the
        reason these numbers are what they are: the largest library module build
        measured is ~118 s and the largest generated proof ~96 s. This asserts
        only the RATIO, because a number that moves is not what a test should
        be about — but a bound that dropped below what the work needs would fail
        every proof in the suite, so the direction is worth pinning.
        """
        self.assertGreaterEqual(L.PROOF_WALL_S, 5 * 298,
                                "the proof bound must stay several times the "
                                "slowest legitimate proof measured "
                                "(formal/examples/udivmod.mojo, 297.8 s)")
        self.assertGreaterEqual(L.LIBRARY_WALL_S, 5 * 112,
                                "and the library bound above the slowest "
                                "module build measured (ProofLib, 112.0 s)")
        self.assertLess(L.PROOF_WALL_S, 45 * 60,
                        "…and far below tools/control.py guard's 45 min net, "
                        "which is the net UNDER a launcher that lacks these")


# ── 7. the x86-64 end-to-end tree: does `terminates` mean what it says ──────
#
# `formal/x86_64_endtoend_test.py` states one theorem per example — "for EVERY
# input the model runs this image to the exit pc" — and proves it by walking the
# path the machine actually takes. The walk used to make EVERY `ret` the end of
# the run, so a function that CALLS another stopped at the callee's return and
# the closing fact `s_N.rip = 0` claimed the run had reached the exit sentinel.
# It had not: `ret` pops `(mem_read_bytes …)`, which after a `call` is the
# address that `call` pushed.
#
# That is the one outcome in this reporter that is not "not proved" but "cannot
# be true", and it was invisible twice over. The proof attempt ground on the false
# goal until a heartbeat or wall bound fired, so the report read as a chain that
# was too long — and `wide_recv` came back `terminates: proved, 1 sorry`, a green
# resting on a false claim, and the only example in the corpus whose path
# contains a call.
#
# So the return address is tracked (`rets`), and a `ret` with a frame to return to
# is its own reported outcome. These cases are Lean-free: they drive `_tree` over
# hand-built images, because what is under test is the SHAPE of the walk and a
# proof is a 100-second way to learn that a tree is wrong.


def _image(*chunks):
    """`(code, shapes)` — bytes plus the `[(insn, form, raw)]` `_shapes` builds.

    Decoded with the real `formal/x86_64_decode.py`, so a case cannot disagree
    with the decoder about what an instruction IS, which is the mistake
    `formal/x86_64_model_coverage_test.py` records about hand-written encodings.
    """
    import formal.x86_64_decode as D
    from formal.x86_64_endtoend_test import _shapes
    code = b"".join(chunks)
    insns, off = [], 0
    while off < len(code):
        insn = D.decode_one(code, off)
        insns.append(insn)
        off = insn.next_offset
    return code, _shapes(code, insns)


def _call(displacement: int) -> bytes:
    return b"\xe8" + int(displacement).to_bytes(4, "little", signed=True)


def _calling(prologue: bytes, callee: bytes, tail: bytes = b"") -> bytes:
    """`prologue ; call <callee> ; tail ; callee` — one image, callee placed after.

    The displacement is computed from the byte offset of the `call` rather than
    written down, because the displacement is measured from the END of the
    instruction and getting that off by one gives a target in the middle of the
    caller — which reads as "no tree" and says nothing about the case.
    """
    here = len(prologue)
    body = prologue + _call(0) + tail + callee
    target = len(prologue) + 5 + len(tail)
    return body[:here] + _call(target - (here + 5)) + body[here + 5:]


#: `push rbp ; mov rbp, rsp ; … ; ret` — a leaf function's prologue and epilogue.
PROLOGUE = b"\x55\x48\x89\xe5"
EPILOGUE = b"\xc9\xc3"          # leave ; ret
NOPFRAME = b"\x48\x81\xec\x10\x00\x00\x00"   # sub rsp, 16


class TestX86EndToEndTree(unittest.TestCase):
    """The path tree, and the outcome each shape of it has to be reported as."""

    #: Where the images below are placed.  Any address works — the model
    #: addresses the code function absolutely — and a round one makes a
    #: disassembled failure readable.  `func_offset` is that ABSOLUTE address,
    #: which is what `formal.build` reports and what `_tree` looks up in a table
    #: keyed by `base + offset`.
    BASE = 0x1000

    def _tree(self, code, shapes, entry=None):
        from formal.x86_64_endtoend_test import _tree
        return _tree(code, {"base_addr": self.BASE,
                            "func_offset": self.BASE if entry is None
                            else entry}, shapes)

    def test_a_leaf_function_still_ends_at_its_ret(self):
        """The ordinary case, and the one the new bookkeeping must not break."""
        from formal.x86_64_endtoend_test import _paths
        code, shapes = _image(PROLOGUE, NOPFRAME, EPILOGUE)
        root = self._tree(code, shapes)
        self.assertIsNotNone(root)
        (path,) = _paths(root)
        self.assertEqual(path[-1].form, "ret")
        self.assertEqual([n.form for n in path],
                         ["push_r64", "mov_rm64_r64_reg", "alu_ri32:sub_rsp",
                          "leave", "ret"])

    def test_a_call_that_returns_is_its_own_outcome_not_a_proof(self):
        """`call` pushes a return address and `ret` pops one.

        The caller below is `push rbp ; call far ; mov rax, 0 ; ret` and the callee
        is `push rbp ; leave ; ret`. Walking it must DECLINE, naming the reason,
        because the theorem it would emit claims the run stops at the callee's
        `ret` and the machine carries on into `mov rax, 0`.
        """
        from formal.x86_64_endtoend_test import _NoTree
        MOV_EAX_0 = b"\x48\xc7\xc0\x00\x00\x00\x00"
        code, shapes = _image(_calling(PROLOGUE, PROLOGUE + EPILOGUE,
                                       MOV_EAX_0 + b"\xc3"))
        with self.assertRaises(_NoTree) as cm:
            self._tree(code, shapes)
        self.assertEqual(cm.exception.kind, "call")
        self.assertIn("caller", str(cm.exception))

    def test_calling_one_function_twice_is_two_calls_not_a_loop(self):
        """The second call re-enters an address the path has already been in.

        A `seen` set shared across the frame boundary makes that a cycle, and the
        report then says "loops" -- a second, different, wrong reason, on a path
        that has not looped.  This is `wide_recv`, which calls one method body
        three times (`set_x`, then `get_x`, then `get_y`).

        Laid out by hand rather than spliced: `call A ; call B ; mov rax, 0 ;
        ret`, then the callee, and each displacement is computed from its own
        offset.  The `seen` set that would catch this mistake is the one the
        SECOND call walks into, so the case has to actually contain two calls --
        one call into a callee that itself calls once would not reach it.
        """
        from formal.x86_64_endtoend_test import _NoTree
        callee = PROLOGUE + EPILOGUE
        MOV_EAX_0 = b"\x48\xc7\xc0\x00\x00\x00\x00"
        first = len(PROLOGUE)
        second = first + 5
        target = second + 5 + len(MOV_EAX_0) + 1
        code = (PROLOGUE
                + _call(target - (first + 5))
                + _call(target - (second + 5))
                + MOV_EAX_0 + b"\xc3" + callee)
        self.assertEqual(len(code), target + len(callee),
                         "the callee must start where the two calls point")
        _, shapes = _image(code)
        with self.assertRaises(_NoTree) as cm:
            self._tree(code, shapes)
        self.assertEqual(cm.exception.kind, "call")

    def test_a_backward_call_is_a_loop_and_not_the_call_outcome(self):
        """`jmp` back to the function's own entry is recursion, and `_has_loop`
        names it `loops`. Deciding it here instead keeps the two reasons apart:
        a path that both returns and loops would be reported as `loops`."""
        from formal.x86_64_endtoend_test import _NoTree
        # entry is 0, the call at 0x10 reaches back to 0x00.
        at = 0x10
        pad = b"\x90" * (at - len(PROLOGUE))
        # the call sits at `at`, so its target is `at + 5 + off` and the entry is 0
        code, shapes = _image(PROLOGUE + pad + _call(-(at + 5)))
        root = self._tree(code, shapes)
        self.assertIsNone(root, "a backward call must build no tree at all")
        self.assertNotIsInstance(root, _NoTree)

    def test_a_backward_jump_is_still_a_loop(self):
        from formal.x86_64_endtoend_test import _NoTree
        code, shapes = _image(PROLOGUE + b"\x90\x90\x90"
                              + b"\xeb\xf7" + b"\xc3")
        self.assertIsNone(self._tree(code, shapes))

    def test_the_declining_outcome_is_a_ValueError_so_the_handler_still_sees_it(self):
        """`main()` catches `ValueError` to reach the reason split, so a new kind
        that did not derive from it would be an uncaught traceback rather than a
        reported line."""
        from formal.x86_64_endtoend_test import _NoTree
        self.assertTrue(issubclass(_NoTree, ValueError))
        self.assertEqual(_NoTree("call", "x").kind, "call")


# ── 6. the estate: nothing launches Lean outside the launcher ───────────────
#
# A bound that a second launch site does not share is not a policy, it is a
# habit. Three files launched `lean` directly before this: `formal/lean.py`
# (three sites, wall-only, one of them with no bound at all in an earlier
# revision), `formal/x86_64_endtoend_test.py` (two sites, NO `timeout=` at all),
# and the model/coverage scripts (wall-only, 3600 s and 7200 s). The launcher
# exists so there is exactly one place that knows the bounds; this exists so the
# next file does not quietly become a second one.
#
# The detector reads the AST rather than grepping, and that is the whole design:
# comments are not in the AST, so a file that explains why it does NOT launch
# Lean cannot be mistaken for one that does. A grep over the same three files
# would have to allowlist their comments.

_LAUNCHERS = {"subprocess": ("run", "Popen", "call", "check_output",
                             "check_call"),
              "os": ("system", "popen", "spawnl", "spawnv", "spawnvp",
                     "execl", "execv", "execvp"),
              "commands": ("getoutput", "getstatusoutput")}


def _launch_sites(source: str, path: str = "<snippet>"):
    """`[(lineno, how)]` for every call in `source` that could start Lean.

    A "could" rather than a "does": the call's own names and string literals are
    what is matched, so `subprocess.run([lean, "X.lean"])` is a site and
    `subprocess.run(["arch", "-x86_64", path])` is not. Deliberately blind to
    whether the argument is a real binary path — the point of the guard is that
    nobody gets to decide that for themselves.
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(-1, f"does not parse ({e})")]
    out = []

    def mentions_lean(node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and "lean" in sub.id.lower():
                return True
            if isinstance(sub, ast.Attribute) and "lean" in sub.attr.lower():
                return True
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                    and "lean" in sub.value.lower():
                return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.attr in _LAUNCHERS.get(f.value.id, ())):
            continue
        if mentions_lean(node):
            out.append((node.lineno, f"{f.value.id}.{f.attr}"))
    return sorted(out)


def _lean_files(root: str, skip=()):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in ("build",
                                                              "__pycache__")]
        for name in filenames:
            if name.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                if rel not in skip:
                    yield rel, os.path.join(dirpath, name)


class TestLeanLaunchEstate(unittest.TestCase):
    def test_the_detector_sees_a_launch_and_ignores_an_explanation(self):
        """The control, in both directions, because a detector that finds nothing
        makes the guard below a green light over an unexamined tree."""
        self.assertEqual(
            _launch_sites('import subprocess\n'
                          'subprocess.run([lean, "ModelCheck.lean"])\n'),
            [(2, "subprocess.run")])
        self.assertEqual(
            _launch_sites('import subprocess\n'
                          'subprocess.run(["arch", "-x86_64", p])\n'
                          '# and a comment naming lean proves nothing\n'),
            [], "a comment, and an unrelated launch, are not a launch site")

    def test_nothing_launches_lean_outside_the_launcher(self):
        found = {}
        for rel, path in _lean_files(HERE, skip=("formal/lean.py",)):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError as e:
                found[rel] = [(0, f"unreadable: {e}")]
                continue
            hits = _launch_sites(source, rel)
            if hits:
                found[rel] = hits
        self.assertEqual(found, {},
                         "every Lean run goes through formal/lean.py's "
                         "`run_lean`, which is the one place that bounds it: "
                         + repr(found))

    def test_the_launcher_itself_is_still_a_launch_site(self):
        """The other half of the non-vacuity, against the real tree.

        `formal/lean.py` is exempt from the guard above, so the guard has to be
        shown to be looking at it. It is exempt *by path*, and its own
        `Popen` call takes an `argv` variable rather than a name containing
        "lean" — which is precisely the shape the AST detector cannot see
        through, and precisely why the second guard below exists.
        """
        import inspect
        src = inspect.getsource(L.run_lean)
        self.assertIn("subprocess.Popen", src,
                      "the launcher must still spawn a process, or "
                      "formal/lean.py's exemption is not an exemption of "
                      "anything")
        self.assertIn("start_new_session=True", src,
                      "…in its own process group, which is what makes the "
                      "whole-tree kill reachable")

    def test_a_file_that_resolves_lean_reaches_it_only_through_this_module(self):
        """The second guard, for the shape the first cannot see.

        A file can resolve the toolchain with `find_lean` and then hand the path
        somewhere `ast` cannot follow — `os.system("lean " + p)`, `sh -c`, a
        variable holding an argv the detector has no name for. So the rule is
        about the RESOLVER rather than the spawn: anything that asks
        `formal/lean.py` where Lean is must also reach Lean through one of its
        sanctioned entry points, and `formal/lean.py` is the only module allowed
        to do either.
        """
        sanctioned = ("run_lean", "ensure_library", "library_census",
                      "lean_version", "check_proof", "check_proof_cached",
                      "proof_census", "census_report")
        resolved, missed = [], {}
        for rel, path in _lean_files(HERE, skip=("formal/lean.py",)):
            with open(path, encoding="utf-8", errors="replace") as f:
                source = f.read()
            if "find_lean" not in source:
                continue
            resolved.append(rel)
            if not any(entry in source for entry in sanctioned):
                missed[rel] = "calls find_lean and no formal.lean entry point"
        self.assertEqual(missed, {},
                         "resolving the toolchain and starting it are the same "
                         "decision: " + repr(missed))
        self.assertGreaterEqual(len(resolved), 5,
                                f"only {len(resolved)} file(s) resolve Lean "
                                "through formal/lean.py, so this rule is not "
                                "being exercised: " + repr(resolved))

    def test_no_shell_recipe_runs_a_lean_binary(self):
        """The shell half, and it is the half a Python guard cannot see.

        `tools/proof.sh`, `Makefile` and any `*.mk` can start a `lean` without
        going near `ast`, and a bound written in Python does not apply to it. The
        pattern is a command POSITION only, so `LEAN="$(…)"` (which
        `tools/proof.sh` has, to check that the toolchain exists) and comments
        naming Lean are not matches.
        """
        import re
        run = re.compile(r"^\s*(?:\$\{?LEAN\}?|(?:[\w./-]+/)?(?:lean|lake))\s+\S")
        offenders = []
        for rel in ["Makefile", "tools/proof.sh"] + [
                f"tools/{n}" for n in sorted(os.listdir(os.path.join(HERE, "tools")))
                if n.endswith(".sh") or n.endswith(".mk")]:
            path = os.path.join(HERE, rel)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if line.lstrip().startswith("#") or "=" in line.split()[0:1]:
                        continue
                    if run.match(line):
                        offenders.append(f"{rel}:{i}: {line.strip()[:70]}")
        self.assertEqual(offenders, [],
                         "a shell recipe that starts Lean bypasses every bound "
                         "in formal/lean.py: " + "; ".join(offenders))


if __name__ == "__main__":
    unittest.main()
