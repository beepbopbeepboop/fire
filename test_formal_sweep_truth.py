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

    def test_the_librarys_semantics_is_reported(self):
        """Run against this tree's real lib/, not a fixture.

        A scanner tested only against text it wrote itself tests its own
        assumptions; this one is the shape in a file nobody may edit this round.
        """
        path = os.path.join(LIB, "ProofLib.lean")
        if not os.path.isfile(path):
            self.skipTest("lib/ProofLib.lean is not here")
        with open(path) as f:
            got = L.vacuous_declarations(f.read())
        self.assertIn("Semantics", [n for n, _s, _l in got],
                      "DylibExport.Semantics is `∀ o, o ∈ l → True` on this "
                      "tree and is the proposition every dylib proof's "
                      "semantics theorem is stated with")

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

    def test_the_library_has_known_holes_and_they_are_named(self):
        """The measured claim, on this tree, with Lean.

        Three declarations in `lib/` admit a `sorry` and every one of them is
        load-bearing: `in_image_stub` and `semantics_stub` in ProofLib.lean and
        `dylib_export_contract_stub` in Refine.lean, which is what
        `formal/arm64_proof_gen.py` invokes for every dylib export contract
        with `obs := fun n => n` — asserting every export is the identity map.
        Skipped without Lean, never asserted as zero.
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
        self.assertTrue(lib, "no library module could be measured at all")
        total = sum(got[0] for got in lib.values())
        self.assertGreaterEqual(
            total, 1,
            "the library admits no `sorry` on this tree any more — if that is "
            "true, the three named in FORMAL.md 6 are fixed and the docs are "
            "stale; if it is not, the census is broken and this says so")
        named = {name for _count, names in lib.values() for name in names}
        self.assertIn("dylib_export_contract_stub", named,
                      "Refine.lean's contract stub is the hole every dylib "
                      "proof's contract theorem rests on, and it must be NAMED "
                      "— a count of 3 does not tell a reader where to look")


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
    SRC = "import os\nimport json\n\ndef main():\n    pass\n"

    def test_a_self_describing_message_is_a_target_fact(self):
        got = S._system_module_call(
            "build: os.getenv is a system module call: os has no Mojo source "
            "on any path", self.SRC)
        self.assertEqual(got, "os")

    def test_a_message_naming_a_host_member_is_a_target_fact(self):
        got = S._system_module_call(
            "build: json.dumps() cannot be lowered: json is not available here",
            self.SRC)
        self.assertEqual(got, "json")

    def test_a_construct_refusal_is_not(self):
        """The negative that matters most, because the fallback is `codegen`.

        A frame-receiver refusal mentions dotted names constantly, and this
        repo's own files are full of `self.field`. If the rule fired on those,
        30-odd real codegen findings would silently become target facts and the
        headline would improve by about a quarter without anyone writing code.
        """
        for term in ("gen.type_checker cannot be placed: this name holds a "
                     "frame address in more than one shape",
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
        be one.
        """
        self.assertEqual(
            S._system_module_call("build: socket.recv cannot be lowered", self.SRC),
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


if __name__ == "__main__":
    unittest.main()
