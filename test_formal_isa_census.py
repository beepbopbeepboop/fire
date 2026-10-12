#!/usr/bin/env python3
"""No emitted instruction form may lack a model, a fuzz case, or an `as` check.

`tools/formal_isa_census.py` prints the matrix: for every instruction form an
emitter can produce, whether the Lean model gives it semantics, whether the
model-vs-hardware fuzzer runs it against the CPU, and whether a byte-for-byte
differential against the platform assembler exists. This file is the RATCHET on
that matrix, and it is the thing that makes the matrix worth printing: a census
nobody reads drifts, and a census nobody checks is a survey.

**The property, stated so it cannot be satisfied by shrinking the subject:**

    every encoder that `formal/arm64_codegen.py` or `formal/x86_64_codegen.py`
    (or the Mach-O linker's stub) references has all three of LEAN, FUZZ and AS

Three ways a row can be excused, and each is checked rather than trusted:

  * it is not an emitted form at all — the census's own definition, re-derived
    here, so "the census only looked at the forms it liked" fails;
  * it is in `HARNESS_LIMITS`, a permanent answer about the HARNESS (the form
    traps, or jumps to an address the two engines cannot share, or needs a
    register file the harness does not have) — each reason is printed by the
    census, and a stale one (a limit the harness no longer has, or a form
    nothing emits) fails here;
  * it is in `BACKLOG`, a real gap with a bug doc — and the doc must EXIST, and
    the entry must still name a row the census reports as missing. That second
    half is the anti-rot: a gap that gets fixed cannot leave its entry behind,
    because an entry that exempts nothing is an exemption for whatever comes
    next.

So the matrix cannot be made to pass by deleting rows, and it cannot be made to
pass by adding rows to an exemption list without naming a doc that says what the
gap is.

Verified non-vacuous, all three ways, by driving the tables in a scratch
interpreter rather than by editing them in the tree: dropping
`encode_smulh_xd_xn_xm` from `BACKLOG` fails the first test with
`[('encode_smulh_xd_xn_xm', ['lean'])]`; adding an entry for a row that is not
missing anything fails the anti-rot test; pointing an entry at a path under
`bugs/` that is not in the tree fails the doc test. A check that cannot fail is a comment.

Run: python3 test_formal_isa_census.py [-v]
"""
import argparse
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import formal_isa_census as C                              # noqa: E402

ARCHES = ("arm64", "x86_64")

#: Both backends, read once. `C.census` is a static read of the repository (an
#: AST walk of the emitters, the harnesses and the encoder tests, and the
#: generator's own step table cross-checked against `lib/ProofLib.lean`), so
#: this file needs neither `as`, nor a compiler, nor Lean.
_ROWS = {arch: C.census(arch) for arch in ARCHES}


class TestEmittedFormCoverage(unittest.TestCase):
    """The property, one backend at a time."""

    def test_every_emitted_form_has_a_model_a_fuzz_case_and_an_as_check(self):
        for arch in ARCHES:
            gaps = [r for r in _ROWS[arch] if r.missing() and not r.excluded]
            self.assertEqual(
                [], [(r.encoder, r.missing()) for r in gaps],
                "these emitted %s forms have no %s, and no entry in "
                "`formal_isa_census.HARNESS_LIMITS` or `.BACKLOG` explains why. "
                "Each one is either a gap in the model, a form the fuzzer "
                "never runs, or an encoder nothing has ever compared against "
                "`as`:\n  %s"
                % (arch, "/".join(("LEAN", "FUZZ", "AS")), gaps))

    def test_the_census_is_about_emitted_forms_and_not_the_encoder_table(self):
        """Every row is emitted, and there are enough of them to be a census.

        The first half is the definition (`bugs/FORMAL_arm64_instruction_
        coverage.md`'s 2026-10-03 method change: an encoder no lowering calls
        is not an instruction any image can contain). The second is a
        DIRECTION check rather than a count, for the reason the arm64 survey
        keeps re-learning: a number here goes stale the moment an encoder lands,
        and the ordinary order of work in this tree is encoder first.
        """
        for arch in ARCHES:
            rows = _ROWS[arch]
            self.assertTrue(rows, "no emitted %s forms at all: the emitters "
                                 "reference nothing, or the census's emitter "
                                 "roots are wrong" % arch)
            for row in rows:
                self.assertTrue(row.emitted_in,
                                "%s is a row but nothing emits it" % row.encoder)
            table = set(C.encoder_names(arch))
            unwired = table - {r.encoder for r in rows}
            self.assertTrue(
                unwired,
                "every encoder in formal/%s.py reads as emitted, so the census "
                "has stopped distinguishing the TABLE from the CALLERS — which "
                "is the mistake `bugs/FORMAL_arm64_instruction_coverage.md` "
                "records as overstating coverage by 120,647 real instructions"
                % arch)

    def test_every_row_has_a_canonical_word(self):
        """The census could ask LEAN only because it can CALL each encoder.

        A row whose canonical sample raises prints `sample?` and its LEAN
        column reads `no`, which is indistinguishable in the tally from a form
        the model has no arm for. That is a false reading of the model's
        coverage, so it fails here instead.
        """
        for arch in ARCHES:
            broken = [(r.encoder, r.sample_error) for r in _ROWS[arch]
                      if r.sample_error]
            self.assertEqual([], broken,
                             "these emitted %s encoders have no canonical "
                             "sample: %s" % (arch, broken))


class TestExemptions(unittest.TestCase):
    """Every exemption is honest, and an exemption cannot outlive its reason."""

    def test_every_harness_limit_is_still_a_limit_of_this_harness(self):
        """A `HARNESS_LIMITS` entry must name a row that is EMITTED.

        Not "must still be missing a column" — a limit is about the harness, so
        it stays correct when the model grows an arm. What it must not do is
        exempt a form nothing emits, which is how an exemption becomes a
        permanent hole for whatever lands next.
        """
        emitted = {r.encoder for arch in ARCHES for r in _ROWS[arch]}
        stale = sorted(n for n in C.HARNESS_LIMITS if n not in emitted)
        self.assertEqual([], stale,
                         "these HARNESS_LIMITS entries name an encoder no "
                         "emitter references any more, so they exempt nothing: "
                         "%s" % stale)

    def test_every_backlog_entry_has_a_doc_that_exists(self):
        missing = []
        for name, (doc, _why) in sorted(C.BACKLOG.items()):
            if not os.path.exists(os.path.join(ROOT, doc)):
                missing.append((name, doc))
        self.assertEqual([], missing,
                         "these BACKLOG entries name a bug doc that is not in "
                         "the tree. A gap with no document is a gap nobody "
                         "works through, and the alternative — dropping the "
                         "entry — puts the row straight back in the failing "
                         "list above: %s" % missing)

    def test_every_backlog_entry_still_describes_a_gap(self):
        """The anti-rot half: an exemption must exempt SOMETHING.

        A `BACKLOG` entry whose row now has all three columns is a fixed gap
        that never gave its entry back, which is exactly the "stale marker"
        failure `tools/suite.py`'s `expect=` anti-rot exists to catch — here it
        would exempt the NEXT gap that lands on the same encoder.
        """
        by_encoder = {r.encoder: r for arch in ARCHES for r in _ROWS[arch]}
        stale = []
        for name, (doc, _why) in sorted(C.BACKLOG.items()):
            row = by_encoder.get(name)
            if row is None or not row.missing():
                stale.append(name)
        self.assertEqual([], stale,
                         "these BACKLOG entries name a row that is no longer "
                         "missing anything (or no longer emitted at all), so "
                         "they are a fixed gap that kept its exemption: %s"
                         % stale)

    def test_the_arm64_backend_has_no_unexplained_gap_at_all(self):
        """arm64 is the backend this census was built for, so it is held to the
        whole property with no slack: every one of its exemptions is a named
        harness limit or a named bug doc, and the list above is empty. x86-64
        carries the same ratchet with its backlog attached; this is what stops
        that backlog from being where new gaps go by default.
        """
        rows = _ROWS["arm64"]
        self.assertGreater(len(rows), 50,
                           "the arm64 census has collapsed to %d rows, so it "
                           "is no longer measuring the emitter" % len(rows))
        self.assertEqual(
            [], [r.encoder for r in rows if r.missing() and not r.excluded])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    return unittest.main(argv=[__file__, "-v"] if args.verbose else [__file__],
                         exit=False).result.wasSuccessful() and 0 or 1


if __name__ == "__main__":
    sys.exit(main())