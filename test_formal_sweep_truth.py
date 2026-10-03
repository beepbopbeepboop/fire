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
import re
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


def _first_unreachable_host_module() -> str:
    """The first name in `HOST_UNREACHABLE` that is a plain module.

    Read, never copied: the tier is what `formal.imports.host_module_tier`
    decides, and it is the answer to "is a refusal naming this module a fact
    about the TARGET". A name that has a `formal/hostmods/` source is not in
    `HOST_MODULES` at all, and one that is modelled or admitted is in it and
    answers, so neither may be the fixture. Dotted names are skipped because a
    fixture has to be able to `import` what it names.
    """
    import formal.imports as I
    names = [n for n in sorted(I.HOST_UNREACHABLE) if "." not in n]
    assert names, "HOST_UNREACHABLE is empty, so there is no target fact to "\
                  "name and this class is about nothing"
    return names[0]


class TestSystemModuleCall(unittest.TestCase):
    # The host module these rows name is CHOSEN, not spelled, because the choice
    # is a fact about the tree that goes stale on its own: `json` was named here
    # until `formal/hostmods/json.mojo` landed on 2026-09-30, `math` until
    # `formal/hostmods/math.mojo` landed in 9c7ec795, and `socket` until the day
    # `socket.mojo` lands — and a host module with real Mojo source is not in
    # `formal.imports.HOST_MODULES` at all, so the row stopped firing and
    # asserted `'' != 'math'`, which is a test failure that reads like a sweep
    # bug and is not one. `_HOSTMEMBER` is picked from what the build still
    # treats as a host module, and the three rows below keep the choice honest:
    # it must have no `formal/hostmods` source, the build must not say it
    # ANSWERS it, and the file really must import it.
    #
    # The choice is made from `formal.imports.HOST_UNREACHABLE` rather than from
    # a list written out here, and that is the whole of what makes it keep
    # holding: a name in `HOST_MODULES` that is MODELLED or ADMITTED answers, so
    # a refusal naming it is about a construct in a module this build compiles
    # and not a fact about the target — the same division the sweep's own
    # `IN_REACH_HOST_MODULES` makes, read from the table that decides it instead
    # of from a snapshot of it. formal8-13's hand-written exclusion list named
    # the six names that were unreachable when it was written; `abc`, `array`,
    # `bisect` and forty more have models now, and picking one of those would
    # have made this class assert a target fact that is not one.
    #
    # `os`, `json` and `math` are the NEGATIVE cases below rather than the
    # positive one: `os` has had `formal/hostmods/os/` for most of the tree's
    # life and `json` since 2026-09-30, and `math` since 9c7ec795, so none of
    # the three is in `HOST_MODULES` at all. "a `math.floor()` refusal is a
    # target fact" stopped being true the day `math.mojo` landed and the sweep is
    # RIGHT not to believe it: a refusal about a module that EXISTS is a refusal
    # about a construct in a module this build can compile, which is `codegen`,
    # not "not fixable here" — the one class a coverage number must never grow.
    _HOSTMEMBER = _first_unreachable_host_module()
    SRC = f"import os\nimport {_HOSTMEMBER}\n\ndef main():\n    pass\n"

    def test_the_named_host_module_still_has_no_mojo_source(self):
        """The anti-rot for the choice above, and the reason it is a test.

        Without this row the class would go quietly vacuous the next time a
        host module gains source: `_HOSTMEMBER` would pick a different name,
        every other row would still pass, and nothing would say the original
        one had stopped being the thing the rows are about.
        """
        import os.path
        self.assertFalse(
            os.path.exists(os.path.join("formal", "hostmods",
                                        f"{self._HOSTMEMBER}.mojo")),
            f"{self._HOSTMEMBER} gained a formal/hostmods source, so it is no "
            f"longer a host module the build cannot resolve and the rows below "
            f"are about something else")
        from formal.imports import HOST_MODULES
        self.assertIn(self._HOSTMEMBER, HOST_MODULES)

    def test_the_example_is_still_a_host_module_with_no_reach(self):
        """The other two premises of the choice, and neither is about source.

        Read from the tool's own tables, not from the comment: the rule under
        test is structural (`mod in HOST_MODULES`, and the file imports it), so
        its premise is a fact about two sets that this tree edits whenever a
        hostmod is written. A name that is in `IN_REACH_HOST_MODULES` answers —
        it has a model or an admitted contract — so a refusal naming it is not
        a target fact by that table's own account either.
        """
        from formal.imports import HOST_MODULES
        self.assertIn(self._HOSTMEMBER, HOST_MODULES)
        self.assertNotIn(self._HOSTMEMBER, S.IN_REACH_HOST_MODULES)
        self.assertTrue(S._source_imports(self.SRC, self._HOSTMEMBER))

    def test_a_module_that_HAS_a_source_is_not_a_target_fact(self):
        """The anti-rot for the row above, and the reason it changed hands.

        `math` was this class's positive case while `formal/hostmods/math.mojo`
        did not exist. It does now, so a refusal naming `math` is about a
        construct in a module this backend compiles, and filing it as a target
        fact would put real codegen findings in the bucket that is "not fixable
        here". Its own source, and NOT this class's `SRC`, which imports
        `_HOSTMEMBER` deliberately because the positive case above needs a file
        that does.
        """
        from formal.imports import HOST_MODULES
        self.assertNotIn("math", HOST_MODULES,
                         "math.mojo exists, so math is no longer a host module "
                         "this backend cannot compile; if it is back in the set, "
                         "the positive row above is what to re-check")
        self.assertEqual(
            S._system_module_call(
                "build: math.floor() cannot be lowered: math is not available "
                "here", "import math\n\ndef main():\n    pass\n"),
            "")

    def test_a_self_describing_message_is_a_target_fact(self):
        got = S._system_module_call(
            "build: os.getenv is a system module call: os has no Mojo source "
            "on any path", self.SRC)
        self.assertEqual(got, "os")

    def test_a_message_naming_a_host_member_is_a_target_fact(self):
        got = S._system_module_call(
            f"build: {self._HOSTMEMBER}.somefn() cannot be lowered: "
            f"{self._HOSTMEMBER} is not available here",
            self.SRC)
        self.assertEqual(got, self._HOSTMEMBER)

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

    # ── the TIER, not membership of HOST_MODULES ──────────────────────────
    #
    # Measured on the 2026-10-03 sweep: 11 files were filed
    # `not-answerable/system-module-call` whose refusal is an except-ARM
    # refusal, and every clause of this class's claim was false of them.

    _ADMITTED_MEMBER = "subprocess.TimeoutExpired"
    _ARM_REFUSAL = (
        "line 324: `subprocess.TimeoutExpired` is a handler arm with a body "
        "this path cannot put in the image, so it is refused rather than "
        "dropped: `formal` has no exception unwinder, so no edge runs from a "
        "raise site into an arm")
    _ARM_SRC = ("import subprocess\n\n"
                "def main():\n"
                "    try:\n"
                "        subprocess.run(['x'])\n"
                "    except subprocess.TimeoutExpired as e:\n"
                "        print('timed out', e)\n")

    def test_a_handler_arm_naming_an_ADMITTED_module_is_a_construct_refusal(self):
        """The regression, verbatim from the run, and it is 11 files.

        `subprocess` is in `HOST_MODULES` because that set is
        `UNREACHABLE | MODELLED | ADMITTED`, and the file really does import it
        — so the structural arm fired on a MENTION. Nothing is called, and
        `subprocess` answers under declared contracts, so "has no Mojo source
        on any path" is false of it. The refusal underneath is a construct
        refusal (`FORMAL_except_arm_is_never_emitted`), and filing it here hid
        a real codegen gap from the count that exists to measure them.
        """
        import formal.imports as I
        self.assertEqual(I.host_module_tier("subprocess"), "admitted",
                         "the fixture names an ADMITTED module; if subprocess "
                         "moved tier, re-pick the fixture")
        self.assertEqual(
            S._system_module_call(self._ARM_REFUSAL, self._ARM_SRC), "",
            "a construct refusal was filed as a fact about the target")
        cls, _reason = S.classify(False, f"build: {self._ARM_REFUSAL}",
                                  None, self._ARM_SRC)
        self.assertEqual(cls, S.CLASS_CODEGEN)

    def test_the_tier_is_what_the_rule_asks_and_not_HOST_MODULES(self):
        """The premise, asserted, because the rule reads a set that grows.

        `HOST_MODULES` grew by every hostmod written since; the class did not,
        and the two disagreeing is exactly what put 11 files in the wrong
        bucket. So the authority is named here rather than left to the fix's
        own comment: the class fires for `unreachable` names and for nothing
        else.
        """
        import formal.imports as I
        for name in I.HOST_UNREACHABLE:
            if "." in name or not I._is_host_module(name):
                continue
            src = f"import {name}\n\ndef main():\n    pass\n"
            self.assertEqual(
                S._system_module_call(f"build: {name}.somefn() cannot be "
                                      f"lowered here", src), name)
            break
        for name in sorted(I.HOST_ADMITTED)[:5]:
            top = name.split(".")[0]
            src = f"import {top}\n\ndef main():\n    pass\n"
            self.assertEqual(
                S._system_module_call(f"build: {top}.somefn() cannot be "
                                      f"lowered here", src), "",
                f"{top} is admitted and answers, so a refusal naming it is "
                f"about a construct, not about the target")

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


# ── 4b. a file with SEVERAL unresolvable imports, all named at once ─────────
#
# `formal/imports.py`'s `unresolvable_import_errors` reports every blocker in
# one message, one indented line per module, instead of raising on whichever
# came first in the statement list. The measurement that asked for it is
# `bugs/FORMAL_admitted_contracts_sweep_measurement.md`, and the part of it that
# matters to THIS file is that a per-module breakdown drawn from a diagnostic
# naming one of a file's blockers is a sample of how the file's imports are
# written: fixing `subprocess` on eight files moved them from "refused for
# `subprocess`" to "refused for `tempfile`" without moving one file out of
# `not-answerable/host-import`.
#
# So the property is ORDER-INDEPENDENCE of the class and the reason, and
# COMPLETENESS of the reason — the two are separate assertions because the rule
# below (`mods[-1]`) gets them wrong in separate ways: it drops the other names,
# and in a shape whose last name is whatever sorted last it also lets the sort
# order decide the class.
_MULTI_HOST = (
    "build: prog.mojo imports 2 modules this backend cannot build, and every "
    "one of them is named here rather than only the first: fixing one moves "
    "the file to the next\n"
    "  prog.mojo imports 'glob', which is a host module (CPython standard "
    "library), which has no Mojo source for this backend to compile\n"
    "  prog.mojo imports 'tempfile', which is a host module (CPython standard "
    "library), which has no Mojo source for this backend to compile")
_MULTI_MIXED = (
    "build: prog.mojo imports 2 modules this backend cannot build, and every "
    "one of them is named here rather than only the first: fixing one moves "
    "the file to the next\n"
    "  prog.mojo imports 'nope_xyz', which is not a stdlib or sibling module, "
    "and no such file exists\n"
    "  prog.mojo imports 'tempfile', which is a host module (CPython standard "
    "library), which has no Mojo source for this backend to compile")
_MULTI_SRC = "import glob\nimport tempfile\n\ndef main():\n    return 1\n"


class TestSeveralUnresolvableImports(unittest.TestCase):
    def test_every_name_is_in_the_reason(self):
        cls, reason = S.classify(False, _MULTI_HOST, source=_MULTI_SRC,
                                 path="prog.mojo")
        self.assertEqual(cls, S.CLASS_HOST)
        self.assertEqual(reason, "glob, tempfile",
                         "the reason is the per-class breakdown's key, so a "
                         "reason naming one of several blockers is a "
                         "breakdown that measures import order")

    def test_the_class_does_not_depend_on_which_name_is_last(self):
        """The same set, lines swapped: same class, same reason.

        This is the assertion that would fail if the rule were left as
        `mods[-1]` over the whole message, since the two orderings disagree
        about which name that is.
        """
        lines = _MULTI_HOST.splitlines()
        swapped = "\n".join([lines[0], lines[2], lines[1]])
        self.assertEqual(S.classify(False, _MULTI_HOST, source=_MULTI_SRC,
                                    path="prog.mojo"),
                         S.classify(False, swapped, source=_MULTI_SRC,
                                    path="prog.mojo"))

    def test_the_worst_reason_wins(self):
        """A file importing a host module AND a module that does not exist is
        blocked by the second, and filing it as host-import would file a
        missing-module finding under "not fixable here"."""
        cls, reason = S.classify(False, _MULTI_MIXED, source=_MULTI_SRC,
                                 path="prog.mojo")
        self.assertEqual(cls, S.CLASS_UNRESOLVED)
        self.assertIn("nope_xyz", reason)
        self.assertIn("tempfile", reason)

    def test_a_chain_is_still_the_innermost_one(self):
        """The multi-module rule must not swallow the chain rule.

        `mods[-1]` is RIGHT for a chain: the last `imports '…'` is the innermost
        import, and naming the outer module instead would blame a module that
        resolves perfectly well. So a message that is one import wrapping
        another is still classified by the inner one, and by it alone.
        """
        cls, reason = S.classify(
            False,
            "build: a.mojo imports 'b', which cannot be built either: "
            "b.mojo imports 're', which is a host module (CPython standard "
            "library), which has no Mojo source for this backend to compile",
            source="import b\n", path="a.mojo")
        self.assertEqual(cls, S.CLASS_HOST)
        self.assertEqual(reason, "re")

    def test_a_single_module_keeps_the_single_sentence(self):
        """The wording every needle in the tree is written against.

        `formal/imports.py` gives a one-module file `unresolvable_import_error`
        verbatim, so this message classifies exactly as it did before the
        several-module shape existed.
        """
        cls, reason = S.classify(
            False,
            "build: prog.mojo imports 'nope_xyz', which is not a stdlib or "
            "sibling module, and no such file exists",
            source="import nope_xyz\n", path="prog.mojo")
        self.assertEqual(cls, S.CLASS_UNRESOLVED)
        self.assertEqual(reason, "nope_xyz")


class TestTheThirdImportWording(unittest.TestCase):
    """`unresolvable_import_error` has THREE wordings and this tool knew two.

    The third is for a CPython stdlib name that `formal/imports.py` does not
    put in any tier — `tokenize`, `plistlib`, `sqlite3` — and it says so
    ("no tier in `formal/imports.py` saying whether implementing it would need
    an object this target does not have"). Before the marker existed, the
    2026-10-03 sweep filed four files as `unknown`: a class that is in NO rate,
    with the backend's own correct answer printed in full on the row.
    """

    WORDING = ("build: test_ast_formal.py imports 'tokenize', which is a "
               "CPython standard-library module, which has no Mojo source in "
               "this tree and no tier in `formal/imports.py` saying whether "
               "implementing it would need an object this target does not "
               "have — so nothing here can say whether it is reachable")

    def test_it_is_host_import_and_not_unknown(self):
        cls, reason = S.classify(False, self.WORDING,
                                 source="import tokenize\n", path="a.py")
        self.assertEqual(cls, S.CLASS_HOST)
        self.assertEqual(reason, "tokenize")

    def test_the_backend_still_produces_this_wording(self):
        """The anti-rot: a marker with no producer is a marker with no cause.

        Read out of `formal/imports.py` rather than pinned here, so the day the
        backend words this differently the test says so instead of the sweep
        quietly going back to `unknown`.
        """
        import formal.imports as I
        got = I.unresolvable_import_error("x.py", "tokenize")
        self.assertIn(S._STDLIB_UNCLASSIFIED_MARK, got,
                      "the wording the classifier matches is not the one the "
                      "backend emits; re-read it rather than adding a second "
                      "spelling")
        self.assertEqual(I.host_module_tier("tokenize"), "",
                         "the fixture names an UNTYPED module; if tokenize "
                         "gained a tier this row is about something else")

    def test_it_is_not_added_to_the_reach_mirror(self):
        """Deliberate, and pinned so a later reader does not "fix" it.

        This sweep reports a build's verdict. Claiming a tier for a name the
        build says it cannot classify would be the tool inventing the fact its
        own reason string says is missing — and it would move the reach line
        without anyone writing a module. A name that gains a tier stops being
        refused, and then it leaves here on its own.
        """
        self.assertNotIn("tokenize", S.IN_REACH_HOST_MODULES)


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

    def test_a_callees_return_continues_into_the_caller(self):
        """`call` pushes a return address and `ret` pops one, so the callee's
        `ret` is NOT the end of the run.

        The caller below is `push rbp ; call far ; mov rax, 0 ; ret` and the callee
        is `push rbp ; leave ; ret`. Walking it used to DECLINE, naming the
        reason, because the theorem it emitted claimed the run stopped at the
        callee's `ret` — and the machine carries on into `mov rax, 0`. Declining
        was right and stopping was wrong; following the return is the fix, and
        this is the case that says the chain now runs to the exit.

        The `ret` at 0x1016 is the CALLEE's and its successor is 0x1009, the
        instruction after the `call` at 0x1004 — which is `UInt64.ofNat (m + 5)`,
        the literal the model's own `x86_step_call_rel32` pushes, so the two agree
        about where the machine goes. The LAST node is the caller's own `ret`,
        with no successor: that is the outermost one, and it pops the zero
        `X86State.init` leaves on the stack, which is what makes address 0 the
        exit sentinel.
        """
        from formal.x86_64_endtoend_test import _paths
        MOV_EAX_0 = b"\x48\xc7\xc0\x00\x00\x00\x00"
        code, shapes = _image(_calling(PROLOGUE, PROLOGUE + EPILOGUE,
                                       MOV_EAX_0 + b"\xc3"))
        root = self._tree(code, shapes)
        self.assertIsNotNone(root, "the return must be followed, not declined")
        (path,) = _paths(root)
        self.assertEqual([n.form for n in path],
                         ["push_r64", "mov_rm64_r64_reg", "call_rel32",
                          "push_r64", "mov_rm64_r64_reg", "leave", "ret",
                          "mov_rm64_imm32", "ret"])
        rets = [n for n in path if n.form == "ret"]
        self.assertEqual([n.succ for n in rets],
                         [self.BASE + 9, None],
                         "the callee's ret returns to the instruction after the "
                         "call; only the outermost one ends the run")

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

        Following the return is what makes this case bite twice: the callee's
        `ret` comes back to 0x1009, which is the SECOND call, so a `seen` carried
        across the return boundary would read the callee's own body as a cycle.
        The callee is entered at 0x1016 twice and the chain still ends at the
        caller's `ret`.
        """
        from formal.x86_64_endtoend_test import _paths
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
        root = self._tree(code, shapes)
        self.assertIsNotNone(root, "two calls are two calls")
        (path,) = _paths(root)
        entered = [n.addr for n in path if n.addr == self.BASE + target]
        self.assertEqual(len(entered), 2, "the callee is entered twice")
        self.assertEqual(path[-1].form, "ret")
        self.assertIsNone(path[-1].succ,
                          "the chain ends at the CALLER's return, which is the "
                          "outermost one")

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


# ── the .olean currency check, and the IMPORTS it used to ignore ─────────────
#
# `formal/lean.py::ensure_library` decides whether a `.olean` is current by
# comparing a stamp against a digest of the module's own source, and a Lean
# `.olean` EMBEDS its imports' definitions. The library modules import each
# other, so editing `lib/X86.lean` changes what `work.olean` MEANS while
# leaving `work.lean` byte-identical — and nothing rebuilt it. Nothing anywhere
# reported an error: every individual file was fine, the artifact the checker
# read was simply not the artifact its source now describes, and Lean's answer
# to a stale import is to recompile it in-process in every one of the
# concurrent typecheckers. Measured: `python3 test_formal.py` went from 1.2 GB
# to a 32 GB kill with no red anywhere. The CAS key had the same hole, which
# is worse — a hit would have served the stale `.olean` to every machine.
#
# `_effective_digest` is the fix: this module's own bytes AND every
# `LIBRARY_MODULES` name its `import` lines name, transitively. These cases are
# pure file-content arithmetic, so nothing here runs Lean.
class TestOleanCurrency(unittest.TestCase):
    """`_effective_digest`: a module's own bytes AND its imports', transitively.

    `formal/lean.py::ensure_library` decides whether a `.olean` is current by
    comparing a stamp against a digest of the module's own source, and a Lean
    `.olean` EMBEDS its imports' definitions. The library modules import each
    other, so editing `lib/X86.lean` changes what `work.olean` MEANS while
    leaving `work.lean` byte-identical — and nothing rebuilt it. Nothing
    anywhere reported an error: every individual file was fine, the artifact
    the checker read was simply not the artifact its source now describes, and
    Lean's answer to a stale import is to recompile it in-process in every one
    of the concurrent typecheckers. Measured: `python3 test_formal.py` went
    from 1.2 GB across 31 processes to a 32 GB kill, with no red anywhere.

    The CAS key had the same hole, which is worse — a hit would have served the
    stale `.olean` to every machine that shares the store, making the divergence
    permanent rather than local.

    Every case here is pure file-content arithmetic, so none of it runs Lean.
    """

    # The real graph's SHAPE, which is the part that matters: one root that
    # imports nothing from the set (`ProofLib`), a middle module, and two
    # leaves that reach it by different routes. Two modules importing `X86` is
    # the case the defect was measured on — three modules rebuilt from one
    # edit — and one importing only the root is what says the fix does not
    # over-invalidate.
    SOURCES = {
        "ProofLib": "import Lean\n",
        "X86": "import ProofLib\n",
        "work": "import ProofLib\nimport X86\n",
        "Refine": "import ProofLib\n",
        "Contracts": "import ProofLib\nimport Refine\n",
    }

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="olean_currency_")
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        for stem, text in self.SOURCES.items():
            with open(os.path.join(self.dir, stem + ".lean"), "w") as f:
                f.write(text)

    def _digests(self):
        return {stem: L._effective_digest(stem, self.dir)
                for stem in self.SOURCES}

    def _edit(self, stem, extra="\n-- an edit\n"):
        with open(os.path.join(self.dir, stem + ".lean"), "a") as f:
            f.write(extra)

    def test_the_fixtures_are_the_real_graph(self):
        """A graph of invented names would pass every case below with an
        `_effective_digest` that followed nothing.

        The digest's dependency walk is deliberately scoped to
        `LIBRARY_MODULES` — `import Lean` and the toolchain are the version
        half of the key's business, not this mechanism's — so a fixture whose
        names are not in that tuple exercises nothing at all. That is what
        makes this the first case rather than a formality.
        """
        self.assertEqual(set(self.SOURCES), set(L.LIBRARY_MODULES))
        for stem, text in self.SOURCES.items():
            named = set()
            for line in text.splitlines():
                if line.startswith("import "):
                    token = line[len("import "):].strip().split()
                    if token:
                        named.add(token[0])
            self.assertEqual(
                L._module_imports(os.path.join(self.dir, stem + ".lean")),
                named & set(L.LIBRARY_MODULES),
                f"{stem}'s library imports are read out of the source")

    def _imports_of(self, stem):
        """The fixture's own graph, parsed HERE rather than through
        `formal.lean._module_imports`.

        That is the point: an expectation computed with the function under test
        cannot fail when that function returns nothing, so the expected closure
        below is derived from `SOURCES` text alone.
        """
        named = set()
        for line in self.SOURCES[stem].splitlines():
            if line.startswith("import "):
                token = line[len("import "):].strip().split()
                if token:
                    named.add(token[0])
        return named & set(L.LIBRARY_MODULES)

    def _closure(self, stem, seen=None):
        seen = set() if seen is None else seen
        if stem in seen:
            return seen
        seen.add(stem)
        for dep in self._imports_of(stem):
            self._closure(dep, seen)
        return seen

    def _dependents(self, stem):
        """The modules whose digest FOLLOWS `stem` — the dependency closure read
        the other way round, which is the direction the invalidation travels."""
        return {other for other in self.SOURCES
                if stem in self._closure(other)}

    def test_editing_a_module_moves_exactly_its_import_closure(self):
        """The whole rule, in one loop over every module.

        Both directions matter and they are the two failure modes a fix for
        this defect has: a digest that stops short misses a module that must be
        rebuilt, and one that over-reaches costs a 27MB Lean build on a module
        nothing touched. The expected set is the transitive set of DEPENDENTS
        of the edited module, computed from the fixture text.
        """
        for edited in self.SOURCES:
            before = self._digests()
            self._edit(edited, f"\n-- edited {edited}\n")
            after = self._digests()
            moved = {stem for stem in self.SOURCES
                     if before[stem] != after[stem]}
            self.assertEqual(moved, self._dependents(edited),
                             f"editing {edited} must move the digests of "
                             f"exactly the modules that import it (expected "
                             f"{sorted(self._dependents(edited))}, moved "
                             f"{sorted(moved)})")

    def test_the_two_measured_answers_of_the_real_graph(self):
        """Stated, so a reader does not have to re-derive the closure, and so a
        change to the fixture cannot quietly change what is being pinned.

        Editing `X86` — the case the defect was found on — rebuilds `work` and
        leaves `ProofLib` (27MB, ~80s) and the two modules that never import it
        alone. Editing `ProofLib` rebuilds everything, because every other
        module imports it, directly or through one hop.
        """
        before = self._digests()
        self._edit("X86")
        mid = self._digests()
        self.assertEqual({s for s in self.SOURCES if before[s] != mid[s]},
                         {"X86", "work"})
        self._edit("ProofLib")
        after = self._digests()
        self.assertEqual({s for s in self.SOURCES if mid[s] != after[s]},
                         {"ProofLib", "X86", "work", "Refine", "Contracts"})

    def test_a_touch_is_not_an_edit(self):
        """Content-based, with no `mtime` in the decision — at the DIGEST's
        level too. `touch lib/X86.lean`, a git checkout, or an editor that
        rewrites mtimes must not move any digest, or the whole library is
        rebuilt by anything that touches a file."""
        before = self._digests()
        os.utime(os.path.join(self.dir, "X86.lean"), (0, 0))
        self.assertEqual(before, self._digests())

    def test_a_cycle_does_not_hang(self):
        """The walk is recursive, and a future cycle must not hang the library
        build — which is a build that never finishes rather than an error."""
        with open(os.path.join(self.dir, "work.lean"), "a") as f:
            f.write("import work\n")
        self.assertEqual(len(L._effective_digest("work", self.dir)), 64)

    def test_a_module_that_is_not_there_digests_to_nothing(self):
        self.assertEqual(L._effective_digest("NoSuchModule", self.dir), "")

    def test_the_import_graph_is_read_and_not_tabulated(self):
        """A table beside the sources is a second copy of the graph to forget,
        and the graph is the thing that has to stay right.

        So the import list comes out of each source, and a name the sources do
        not import stays out of the walk even though it IS a
        `LIBRARY_MODULES` member — asserted through `Refine`, whose only
        library import is `ProofLib`.
        """
        refine = os.path.join(self.dir, "Refine.lean")
        self.assertEqual(L._module_imports(refine), {"ProofLib"})
        before = L._effective_digest("Refine", self.dir)
        self._edit("X86")
        self.assertEqual(before, L._effective_digest("Refine", self.dir))

    def test_the_real_library_sources_declare_the_graph_they_have(self):
        """`lib/` itself, because the fix reads the imports off the sources: a
        module that FORGOT to import something is not caught by the digest, it
        is caught by Lean, late and expensively, by recompiling it in every
        checker.

        So every module in `LIBRARY_MODULES` must name, at its own top, what it
        depends on from the set — which is what the check below reads, and a
        module whose `import` lines are not at the top of the file is reported
        here rather than silently carried in nobody's digest.
        """
        for stem in L.LIBRARY_MODULES:
            source = os.path.join(LIB, stem + ".lean")
            if not os.path.isfile(source):
                self.skipTest(f"lib/{stem}.lean is not in this checkout")
            named = set()
            with open(source, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.startswith("import "):
                        if line.strip() and not line.startswith("import "):
                            break          # imports are a header, not scattered
                        continue
                    token = line[len("import "):].strip().split()
                    if token:
                        named.add(token[0])
            self.assertEqual(L._module_imports(source),
                             named & set(L.LIBRARY_MODULES),
                             f"lib/{stem}.lean's library imports")

    def test_the_olean_key_moves_with_the_imports(self):
        """The CAS key, which is the same hole with a longer reach."""
        stem = "work"
        source = os.path.join(self.dir, stem + ".lean")
        before = L._olean_key(stem, source, "lean", L._effective_digest(
            stem, self.dir))
        own_only = L._olean_key(stem, source, "lean")
        self._edit("X86")
        after = L._effective_digest(stem, self.dir)
        self.assertNotEqual(before, L._olean_key(stem, source, "lean", after))
        # And the DEFAULT is the hole, which is what makes the argument
        # non-optional and the scan below necessary: this is the key an
        # unguarded caller computes.
        self.assertEqual(own_only, L._olean_key(stem, source, "lean"))

    def test_every_digest_decision_takes_the_effective_one(self):
        """The call sites, by AST, because the hole is only closed at all of
        them.

        `_olean_key` and `_write_stamp` DEFAULT to the module's own bytes when
        no digest is passed, so a call site that forgets the argument is
        silently back to the defect rather than raising. The cases above pin
        the function; this pins the callers, including the one that threads a
        local (`digest = _effective_digest(...)`) into three of them.
        """
        import ast
        path = os.path.join(HERE, "formal", "lean.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        wanted = {"_olean_key": 3, "_write_stamp": 3, "_library_is_current": 3}

        def is_effective(node, assigned):
            """Is this expression the effective digest — written out, or a name
            assigned from one in the same function?"""
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "_effective_digest":
                return True
            if isinstance(node, ast.Name):
                return node.id in assigned
            return False

        checked = {name: 0 for name in wanted}
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            assigned = set()
            for stmt in ast.walk(fn):
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) \
                        and isinstance(stmt.value.func, ast.Name) \
                        and stmt.value.func.id == "_effective_digest":
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name):
                            assigned.add(tgt.id)
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in wanted):
                    continue
                name = node.func.id
                checked[name] += 1
                where = f"formal/lean.py:{node.lineno} in {fn.name}"
                self.assertGreaterEqual(
                    len(node.args), wanted[name] + 1,
                    f"{where} calls {name} with no digest at all, so it falls "
                    "back to this module's OWN bytes — the defect this whole "
                    "class is about")
                self.assertTrue(
                    is_effective(node.args[wanted[name]], assigned),
                    f"{where} calls {name} without the effective digest")
        for name, count in checked.items():
            self.assertGreater(count, 0,
                               f"{name} is never called in formal/lean.py, so "
                               "this scan proves nothing about it")


class TestOleanCurrencyCheck(unittest.TestCase):
    """`_library_is_current` — the decision, over a stamp that is really there.

    This is the half that does not need Lean either: a stamp, an `.olean` of
    some bytes, and a source. The digest is an ARGUMENT, so these cases pass
    the old one (own bytes) and the new one (effective) and require the two to
    disagree about the same three files — which is the whole defect, at the
    level where it can be stated as an assertion.
    """

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="olean_stamp_")
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        for stem, text in self.SOURCES.items():
            with open(os.path.join(self.dir, stem + ".lean"), "w") as f:
                f.write(text)
        # An `.olean` of arbitrary bytes plus a stamp that records it: the
        # check only ever compares digests, so the artifact's CONTENT is not
        # what is under test here.
        self.olean = os.path.join(self.dir, "work.olean")
        with open(self.olean, "wb") as f:
            f.write(b"not really an olean")
        self.stamp = self.olean + ".srcsha256"

    # The chain `work` → `X86` → `ProofLib`, which is the one the defect was
    # measured on.
    SOURCES = TestOleanCurrency.SOURCES

    def _current(self, stem="work"):
        source = os.path.join(self.dir, stem + ".lean")
        return L._library_is_current(
            source, self.olean, self.stamp,
            L._effective_digest(stem, self.dir))

    def _edit(self, stem, extra="\n-- an edit\n"):
        with open(os.path.join(self.dir, stem + ".lean"), "a") as f:
            f.write(extra)

    def test_a_stamped_olean_is_current(self):
        L._write_stamp(self.stamp, os.path.join(self.dir, "work.lean"),
                       self.olean, L._effective_digest("work", self.dir))
        self.assertTrue(self._current())

    def test_editing_an_import_invalidates_through_the_effective_digest(self):
        """The regression, as a single assertion.

        The stamp below is written the way the code wrote it before the fix —
        from this module's OWN bytes — so it is accepted after `X86.lean` is
        edited, and the stale `.olean` is served. Both halves are asserted on
        purpose: that the own-bytes digest says CURRENT is what makes the
        effective one saying "rebuild" a fact about the fix rather than about
        the fixture.
        """
        source = os.path.join(self.dir, "work.lean")
        L._write_stamp(self.stamp, source, self.olean,
                       L._sha256_file(source))
        self._edit("X86")
        self.assertTrue(
            L._library_is_current(source, self.olean, self.stamp,
                                  L._sha256_file(source)),
            "the own-bytes digest cannot see an edit to an import, which is "
            "exactly why it is not the one the check is given")
        self.assertFalse(self._current(),
                         "an edit to X86.lean must rebuild work.olean")

    def test_editing_the_module_itself_still_invalidates(self):
        """The half that was never broken, and the one a fix for the imports
        could plausibly break: an edit to `work.lean` itself must still say
        "rebuild"."""
        L._write_stamp(self.stamp, os.path.join(self.dir, "work.lean"),
                       self.olean, L._effective_digest("work", self.dir))
        self._edit("work")
        self.assertFalse(self._current())

    def test_a_touch_is_not_an_edit(self):
        """No `mtime` in the decision, and this is why the effective digest had
        to stay content-based: a module's imports can change with its own
        bytes changing AT ALL, so an mtime rule would either rebuild the whole
        library on every touch or miss the import edit."""
        source = os.path.join(self.dir, "work.lean")
        L._write_stamp(self.stamp, source, self.olean,
                       L._effective_digest("work", self.dir))
        os.utime(source, (0, 0))
        self.assertTrue(self._current())

    def test_an_olean_swapped_out_from_under_the_stamp_invalidates(self):
        """The other half of the stamp: it records the `.olean`'s own digest as
        well as the source's, so a file replaced by something else — a
        truncated concurrent write, a copy out of a stale store — is not served
        as current either."""
        L._write_stamp(self.stamp, os.path.join(self.dir, "work.lean"),
                       self.olean, L._effective_digest("work", self.dir))
        with open(self.olean, "wb") as f:
            f.write(b"something else entirely")
        self.assertFalse(self._current())

    def test_a_missing_stamp_or_a_missing_olean_is_not_current(self):
        """No stamp at all is the fresh-clone case, and it must not read as
        current — that is the stamp-only adoption path in `ensure_library`
        doing its job, not a currency answer."""
        self.assertFalse(self._current())
        L._write_stamp(self.stamp, os.path.join(self.dir, "work.lean"),
                       self.olean, L._effective_digest("work", self.dir))
        os.remove(self.olean)
        self.assertFalse(self._current())

    def test_a_truncated_stamp_is_not_current(self):
        """A stamp written by an older tree, or a half-written line, must read
        as "not current" rather than raising: this is a REPORT about an
        artifact, and an exception here would take down every caller."""
        L._write_stamp(self.stamp, os.path.join(self.dir, "work.lean"),
                       self.olean, L._effective_digest("work", self.dir))
        with open(self.stamp, "w") as f:
            f.write("deadbeef")
        self.assertFalse(self._current())

class TestX86EndToEndEmitter(unittest.TestCase):
    """What the path-tree EMITTER does with a return, checked on the text.

    `_tree` following the return is only half of it: the step after a `ret` has
    to know `s_k.rip`, and the model says that is a value read out of the frame
    rather than a literal. So the emitter has to state the value as its own named
    fact and put it into the step, or the chain cannot continue. These are
    Lean-free and they compile one small program — a 100-second proof is a very
    expensive way to learn that the emitter forgot a line.
    """

    SOURCE = ("struct Point:\n"
              "    var x: Int\n"
              "    fn get_x(self) -> Int:\n"
              "        return self.x\n"
              "\n"
              "def main(n) -> Int:\n"
              "    var p = Point()\n"
              "    return p.get_x()\n")

    #: No call at all, so the whole return machinery must be absent. Loop-free
    #: too, because `_tree` declines a body with a back edge and this is about
    #: the return, not about that.
    STRAIGHT = ("def main(n) -> Int:\n"
                "    var t = n * 3 + 1\n"
                "    return t\n")

    @staticmethod
    def _emitted(source=None):
        import tempfile
        import formal.x86_64_endtoend_test as E
        with tempfile.TemporaryDirectory(prefix="formal-ret-emit-") as td:
            path = os.path.join(td, "case.mojo")
            with open(path, "w") as f:
                f.write(TestX86EndToEndEmitter.SOURCE if source is None
                        else source)
            return E.emit_terminates(path)

    def test_the_return_is_a_named_fact_and_the_step_uses_it(self):
        text = self._emitted()
        self.assertIn("hpop", text,
                      "the value a `ret` pops is read out of memory, so the "
                      "step after a return needs it as a fact of its own")
        # The step is still the MODEL's: the literal goes back to
        # `(mem_read_bytes …).toNat` and `x86_step_ret` concludes the record.
        self.assertIn("(mem_read_bytes s", text)
        self.assertIn("x86_step_ret", text)
        self.assertIn("rw [← hpop", text)
        # …and the closing fact is still about the EXIT SENTINEL, which is the
        # outermost `ret` and not the callee's. Before the return was followed
        # this was the false claim the whole bug is about.
        self.assertRegex(text, r"have hrip : s\d+\.rip = 0 := by")

    def test_a_chain_that_crossed_a_frame_is_admitted_at_the_closing_read(self):
        """The cost side, stated as text so it cannot be forgotten.

        A chain that returned into its caller has more than one frame's worth of
        register file for the closing `simp` to reconstruct, and that `simp` does
        not finish: measured on `wide_recv` it is 1190 s and then a heartbeat
        timeout, which is B21's lesson from the other side — an unaffordable
        attempt reported as a FAILURE is worse than an admitted gap. So a crossed
        chain takes the cheap route at `hrip` and says so with a `sorry`.
        """
        text = self._emitted()
        i = text.index("have hrip :")
        closing = text[i:]
        self.assertIn("simp only [hs", closing,
                      "a crossed chain must not pay for the full closing simp")
        self.assertNotIn("x86_flags_add", closing,
                         "…which is what makes it the expensive one")

    def test_a_chain_that_never_left_its_frame_is_untouched(self):
        """The other half, and the one that must NOT change: 32 of the 45 examples
        prove with no sorry, and they get there through the expensive closing
        block. If the return work had changed that block for them, every one of
        them would quietly become `proved, 1 sorry`.
        """
        text = self._emitted(self.STRAIGHT)
        self.assertNotIn("hpop", text,
                         "a straight-line function has no return to follow")
        i = text.index("have hrip :")
        self.assertIn("x86_flags_add", text[i:],
                      "…and it keeps the expensive closing block, which is what "
                      "those 32 sorries-free proofs go through")

    # ── what the REPORT says about those holes ──────────────────────────────
    #
    # The verdict line used to be computed from Lean's
    # `declaration 'terminates' uses 'sorry'` lines, which Lean emits ONCE per
    # declaration. So this chain's FOUR admitted `hpop`s and its admitted
    # closing `hrip` all read as `proved, 1 sorry` — and the doc that describes
    # this machinery says twice that "the number the reader will want is not the
    # number the report gives". `admitted_facts` counts the emitter's own holes
    # by the name it gave them; these are the tests that it counts them at all.

    def test_every_admission_is_counted_by_name_and_not_collapsed_to_one(self):
        import formal.x86_64_endtoend_test as E
        facts = E.admitted_facts(self._emitted())
        admitted = sorted({n for n, _l, k in facts if k == "admitted"})
        # One per returned-to, plus the closing read. Asserted as a SET and not
        # as a count, because the count is the thing that was wrong.
        self.assertEqual(
            [n for n in admitted if n.startswith("hpop")],
            ["hpop%d" % k for k in sorted(
                int(n[4:]) for n in admitted if n.startswith("hpop"))])
        self.assertIn("hrip", admitted,
                      "the closing read is admitted on a crossed chain, and it "
                      "is a hole of its own — reporting only the `hpop`s would "
                      "undercount by one")
        self.assertGreaterEqual(len(admitted), 2,
                                "the point of the check: several distinct "
                                "admissions must not read as one")

    def test_a_guarded_side_condition_is_not_counted_as_an_admission(self):
        """The other direction, and the one that needs its own test.

        A side condition is emitted `(by try (…) <;> all_goals sorry)`: the
        tactic runs FIRST and the `sorry` is reached only if it does not close
        the goal. Counting that as an admission over-counts — measured, 118
        "holes" on `wide_recv` where there are 5 — and not counting it
        under-counts. They are two numbers, and this asserts the split.
        """
        import formal.x86_64_endtoend_test as E
        facts = E.admitted_facts(self._emitted())
        kinds = {k for _n, _l, k in facts}
        self.assertIn("guarded", kinds,
                      "the emitted side conditions must be counted as guarded; "
                      "a chain has several per step and they are the majority")
        guarded = [n for n, _l, k in facts if k == "guarded"]
        admitted = [n for n, _l, k in facts if k == "admitted"]
        self.assertGreater(len(guarded), len(admitted),
                           "the guarded count is expected to dominate; if it "
                           "has collapsed to the admitted count the guard is no "
                           "longer being recognised")

    def test_a_sorry_in_a_comment_is_not_an_admission(self):
        """Both comment forms, and the theorem's OWN docstring is the case.

        `/- … -/` used to be charged as an admission and reported under `_body`,
        which is the "a check that cannot fail is green" shape from the other
        end: the report invented a hole that was not there.
        """
        import formal.x86_64_endtoend_test as E
        self.assertEqual(
            E.admitted_facts("theorem t : True := by\n"
                             "  -- a line comment naming sorry\n"
                             "  /- a block comment naming sorry -/\n"
                             "  exact trivial\n"),
            [])

    def test_the_hpop_docstring_makes_no_claim_about_sorries(self):
        """The generated theorem's docstring asserted `No sorry`, and the chain
        it heads carries five admissions. A docstring that contradicts the file
        it heads is worse than none, so the claim is gone rather than made
        true — the emitter cannot make it true, because closing those five is
        the memory-separation work the bug doc names as remaining.
        """
        text = self._emitted()
        self.assertNotIn("No `sorry`", text,
                         "the theorem's docstring must not claim no sorries "
                         "while the file below it admits five")


# ── 8. the other half of the launch estate: WHERE the generated file goes ─────
#
# Section 6 above is about who starts Lean; this is about where the file Lean
# reads was written. Two scripts each wrote their generated source to a
# hard-coded `os.path.join("/tmp", "<a fixed name>")` and handed it to `lean` BY
# RELATIVE NAME with `cwd` set there
# (fixed 2026-10-03 in 01d77c3a). Both are
# registered suite jobs, the corpus has several worktrees, and `tools/suite.py`
# runs `-j 18` — so two concurrent runs wrote the SAME `Coverage.lean` and the
# second writer's bytes were what the first run's `lean` read. The coverage file
# is 151 `native_decide` goals plus 482 hypothesis checks, so an interleaved
# read is not a small corruption, and it surfaces as "a form is not steppable"
# or "hypothesis N does not hold": a model or lemma bug, in the wrong file, in
# somebody else's run. It is the same hazard `ensure_library` takes an exclusive
# `flock` over, arrived at from the other end — a bound that says "only one
# writer" and a path that says "any number of them".
#
# The guard is scoped to files that RUN Lean, which is the estate this bug is
# in. `tools/tu_grind.py` has the same shape for its own `.ci` scratch and is
# outside it; it is written down at `bugs/TOOLS_tu_grind_scratch_defaults_to_tmp.md`.

_TMP_LITERAL = re.compile(r"^/tmp(?:/|$)")


def _shared_scratch_dirs(source: str, path: str = "<snippet>"):
    """[(lineno, literal)] for every hard-coded absolute scratch path in `source`.

    Read out of the AST, for the reason `_launch_sites` gives: a file that
    explains why it needs no scratch directory must not be mistaken for one that
    does, and a comment is not in the AST. A docstring *is* a `Constant`, so the
    search is restricted to constants a CALL or an ASSIGNMENT consumes — which is
    also what makes it find `workdir = os.path.join("/tmp", name)`, where the
    literal is nowhere near an `open` or a `makedirs`.
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(-1, f"does not parse ({e})")]
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Call, ast.Assign, ast.AugAssign,
                                 ast.AnnAssign)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                    and _TMP_LITERAL.match(sub.value):
                out.add((sub.lineno, sub.value))
    return sorted(out)


class TestScratchDirEstate(unittest.TestCase):
    def test_the_detector_sees_a_hard_coded_dir_and_ignores_an_explanation(self):
        """The control, in both directions: a detector that finds nothing makes
        the guard below a green light over an unexamined tree."""
        self.assertEqual(
            _shared_scratch_dirs('import os\n'
                                 'workdir = os.path.join("/tmp", "x86_model")\n'
                                 'os.makedirs(workdir, exist_ok=True)\n'),
            [(2, "/tmp")], "the literal is in the join, not in the makedirs")
        self.assertEqual(
            _shared_scratch_dirs('import os, tempfile, shutil\n'
                                 '# a comment naming /tmp proves nothing\n'
                                 'workdir = tempfile.mkdtemp(prefix="x86_model")\n'
                                 'shutil.rmtree(workdir, ignore_errors=True)\n'),
            [], "a comment, and a private mkdtemp, are not a shared path")

    def test_nothing_generates_a_lean_file_into_a_hard_coded_dir(self):
        found, scanned = {}, []
        for rel, path in _lean_files(HERE, skip=("formal/lean.py",
                                               os.path.basename(__file__))):
            with open(path, encoding="utf-8", errors="replace") as f:
                source = f.read()
            if "run_lean" not in source:
                continue          # not a Lean-launching file; see above
            scanned.append(rel)
            hits = _shared_scratch_dirs(source, rel)
            if hits:
                found[rel] = hits
        self.assertEqual(found, {},
                         "a generated .lean goes in a private directory "
                         "(formal/lean.py::scratch_dir): " + repr(found))
        # This file is exempt — like formal/lean.py is above — because it QUOTES
        # the violation in its own control, and a string holding source text is
        # indistinguishable from source to `ast`. So the exemption has to be
        # shown to be costing nothing: the walk must still reach both scripts the
        # bug named, or the guard is green over an unexamined estate.
        for rel in ("formal/x86_64_model_test.py",
                    "formal/x86_64_model_coverage_test.py"):
            self.assertIn(rel, scanned,
                          "the guard stopped reaching " + rel)

    def test_the_two_scripts_ask_for_a_private_directory(self):
        """The positive half, against the two files the doc named.

        The guard above is a negative ("nothing hard-codes /tmp"), which a file
        that writes nowhere at all would satisfy. So the two scripts are also
        required to name the helper, and to hand `lean` a path built by joining
        onto the directory rather than a bare `os.path.basename` of it — the
        relative name is what made the shared directory load-bearing.
        """
        for rel in ("formal/x86_64_model_test.py",
                    "formal/x86_64_model_coverage_test.py"):
            with open(os.path.join(HERE, rel), encoding="utf-8") as f:
                source = f.read()
            self.assertIn("scratch_dir", source, rel)
            self.assertNotIn("os.path.basename(src)", source,
                             rel + ": lean is handed a relative name, so the "
                             "cwd has to be the scratch directory — which is "
                             "the half of the old shape that collides")
            self.assertNotIn("os.path.basename(lpath)", source, rel)

    def test_scratch_dir_is_private_and_self_removing(self):
        """The helper's three properties, each of which the bug needs."""
        import shutil
        import tempfile
        with L.scratch_dir("x86_model_test") as a, \
                L.scratch_dir("x86_model_test") as b:
            self.assertNotEqual(a, b, "two runs got the same directory, which "
                                      "is the collision")
            self.assertTrue(os.path.isdir(a))
            with open(os.path.join(a, "Coverage.lean"), "w") as f:
                f.write("import X86\n")
            self.assertTrue(os.path.isdir(b))
        for path in (a, b):
            self.assertFalse(os.path.exists(path),
                             "a generated .lean outlived its run")

        # TMPDIR is what puts it inside the checkout for a worker or a sandbox
        # with no writable /tmp, so the helper has to honour it rather than
        # asking for /tmp by name.
        base = tempfile.mkdtemp(prefix="scratch_base_")
        old = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = base
        try:
            with L.scratch_dir("x86_model_coverage") as inner:
                self.assertEqual(os.path.dirname(inner), base)
        finally:
            if old is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = old
            shutil.rmtree(base, ignore_errors=True)

    def test_scratch_dir_removes_the_directory_when_the_body_raises(self):
        """The other control: a `finally`, not a happy-path `rmtree`.

        A run that dies mid-elaboration is the one that most needs the directory
        gone, and it is the one that would leave it behind.
        """
        import tempfile
        seen = []
        with self.assertRaises(RuntimeError):
            with L.scratch_dir("x86_model_coverage") as path:
                seen.append(path)
                raise RuntimeError("lean did not finish")
        self.assertEqual(len(seen), 1)
        self.assertFalse(os.path.exists(seen[0]))


# ── 9. a label name is unique per emission site, on BOTH assemblers ─────────
#
# `Assembler.label` records an address in a dict and `resolve` patches every
# branch out of it, so a name defined TWICE is not a duplicate — it is a
# retargeting of every earlier branch to the second block, which assembles, runs,
# exits 0 and answers with a different number. Nothing downstream can see it.
#
# That is not a hypothetical. Every label in `x86_64_codegen.py` carries a
# per-site counter (`assert{aid}`, `rok{rid}`, `bnds{bid}`, `sl{sid}`) except the
# three bound-clamp labels of `_emit_slice_parts`, which were named after the
# REGISTER alone (`f_s4a`/`_z`/`_c`) — so a second slice in one function rebound
# the first's `jge` and `xs[1:5][1:3]` summed the OUTER slice
# (fixed 2026-10-03 in 68671a62). The five behavioural
# rows for it are `test_x86_64_containers.py`'s `slice-two-*` / `slice-of-slice`
# cases; what is here is the mechanism, on both backends, because the defect is
# in the assembler and arm64's is the same line of code.

class TestLabelUniqueness(unittest.TestCase):
    BACKENDS = ("formal.x86_64", "formal.arm64")

    @staticmethod
    def _asm(module: str):
        """A fresh assembler per backend, with its own relative-branch spelling.

        The two spell the same operation differently (`emit_label_rel` on arm64,
        `emit_label_rel8` on x86-64), which is the naming convention
        `formal/x86_64.py`'s own docstring says mirrors arm64's — so the test
        takes the name from the module rather than hard-coding one."""
        import importlib
        mod = importlib.import_module(module)
        asm = mod.Assembler()
        asm.org(0x1000)
        rel = getattr(asm, "emit_label_rel", None) or asm.emit_label_rel8
        return asm, rel

    def test_a_label_defined_twice_is_refused_on_both_backends(self):
        """The control in each direction: a distinct name is accepted, and the
        same name twice is a `CodegenError` naming the label.

        Both halves matter. A guard that fired on every `label()` call would
        refuse every program; one that stayed silent is the bug.
        """
        from formal.model import CodegenError
        for module in self.BACKENDS:
            with self.subTest(backend=module):
                asm, _rel = self._asm(module)
                asm.label("f_sl1_c4a")
                asm.emit(b"\x90")
                asm.label("f_sl2_c4a")          # a distinct name: fine
                asm.emit(b"\x90")
                with self.assertRaises(CodegenError) as cm:
                    asm.label("f_sl1_c4a")      # …and now the same one again
                msg = str(cm.exception)
                self.assertIn("f_sl1_c4a", msg,
                              "the refusal must name the label, or it is a "
                              "number with no subject")
                self.assertIn("defined twice", msg)

    def test_an_earlier_branch_is_not_left_pointing_at_the_second_block(self):
        """Why the second binding has to be an error and not a rebinding.

        A branch recorded to `one`, then a second `one` further along: `resolve`
        patches every fixup out of the same dict, so without the guard the branch
        lands in the middle of the second block — which assembles, runs, exits 0
        and computes a different number. The guard refuses before the image
        exists, which is the only place this class of bug can be caught.
        """
        from formal.model import CodegenError
        for module in self.BACKENDS:
            with self.subTest(backend=module):
                asm, rel = self._asm(module)
                asm.label("one")
                rel("one")                      # a branch back to `one`
                asm.emit(b"\x90\x90\x90\x90")
                asm.label("two")
                with self.assertRaises(CodegenError):
                    asm.label("one")             # the collision the guard names
                # The recorded fixup is still the one for `one`, so nothing in
                # the assembler quietly dropped the branch to keep going.
                self.assertEqual([r[1] for r in asm.relocs], ["one"])

    #: An OVERLOADED name — ordinary Mojo, and a class whose two `__init__`
    #: overloads are renamed one. Both backends key their function table by
    #: NAME, so a name with two definitions is one function in the image and a
    #: call reaches the body registered last. That rule is deliberate
    #: (`formal/build.py`'s `_check_holder_agreements` is asked about EVERY
    #: definition for exactly this reason, and `test_formal_run.py`'s
    #: `overload_*_CASES` assert the answer the LAST body computes) — but it
    #: used to reach the assembler as `self.asm.label(f.name)` for both bodies,
    #: which implemented "last wins" as a silent REBINDING. That is the defect
    #: the guard above refuses, so the two guards together refused five real
    #: programs in `test_formal_run.py` until the emitters gave each definition
    #: a label of its own and bound the name to the last one explicitly.
    OVERLOADED = ("def twice(x: Int) -> Int:\n"
                  "    return x * 2\n"
                  "\n"
                  "def twice[K: Copyable](x: Int) -> Int:\n"
                  "    return x * 3\n"
                  "\n"
                  "def main(n: Int) -> Int:\n"
                  "    return twice(7)\n")

    @staticmethod
    def _compiled(arch: str):
        """`(code, info, labels)` for `OVERLOADED` on `arch`, from the real
        emitter.

        Driven through `formal/build.py`'s own `_make_codegen`, so the backend
        gets the same globals base and data-segment budget every real build
        gives it — a Codegen built by hand would be a second answer to "what
        does this backend emit", which is the thing this file exists to
        prevent. The assembler's own label table comes back with it because
        the per-definition labels are emitter-internal: `info["labels"]`
        deliberately does not publish them, so they can only be read here.
        """
        import formal.build as B
        import fire_compiler as F
        stmts = F.Parser(F.py_tokenize(TestLabelUniqueness.OVERLOADED)
                         ).with_filename("t").parse_module()
        gen = B._make_codegen(arch, "macho", 10)
        code, info = gen.compile(stmts)
        return code, info, dict(gen.asm.labels)

    def test_an_overloaded_name_is_one_label_per_definition_and_one_address(
            self):
        """The shape that replaced the rebinding, on both backends.

        Three facts, and each is a way the rule can be got wrong:

          * the program BUILDS — the guard above refusing it is the regression
            this case exists to keep fixed;
          * the label table holds one entry per DEFINITION, so no label is
            defined twice and the guard above never has to fire on a name the
            emitter itself owns;
          * `info["labels"]` publishes ONE address per NAME, equal to the LAST
            definition's — the rule the rebound label implemented by accident,
            now stated — and none of the per-definition labels leak into it,
            because `build.py`'s dylib export table and `arm64_proof_gen.py`'s
            method table both read that map and both expect one address per
            name.
        """
        for arch in ("arm64", "x86_64"):
            with self.subTest(backend=arch):
                code, info, emitted = self._compiled(arch)
                self.assertTrue(code)
                per_def = sorted(n for n in emitted
                                  if n.startswith("twice") and "__def" in n)
                self.assertEqual(per_def, ["twice__def1", "twice__def2"],
                                 f"[{arch}] each definition gets its own entry "
                                 "label, and no two share one")
                self.assertEqual(info["labels"]["twice"],
                                 emitted["twice__def2"],
                                 f"[{arch}] a call to an overloaded name lands "
                                 "on the LAST definition, which is what the "
                                 "rebound label did")
                self.assertEqual(
                    sorted(n for n in info["labels"] if "__def" in n), [],
                    f"[{arch}] a per-definition label leaked into the published "
                    "map, which every consumer reads as one address per name")
                # …and the main module is not overloaded, so its name is still
                # bound and still points into the image: an alias that forgot
                # the single-definition case would show up here as a KeyError.
                self.assertEqual(info["labels"]["main"], info["func_offset"])


if __name__ == "__main__":
    unittest.main()
