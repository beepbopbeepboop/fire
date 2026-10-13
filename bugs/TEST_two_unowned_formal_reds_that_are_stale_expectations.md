# `AXIOM_CLOSURE` is stale for four of five modules — a STALE EXPECTATION, not a defect

> **§2 (`sum_range` in a `REFUSED` table) was FIXED on 2026-10-04 and its half of
> this doc is deleted with it.**  The row is gone, `sum_range` is in `GENERATE`,
> and the doc the row cited (`FORMAL_sum_range_generation_refused_and_it_is_not_an_
> expected_failure`) was itself deleted with commit `cbf00b9f`, which is what
> closed the generation refusal.  What was left of that doc was a TYPECHECK
> failure, which has its own doc
> (`bugs/FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot.md`) and
> is a different subject from "does it generate".  §1 below is the whole of
> what is still open here.

**Area:** `test_formal_sweep_truth.py::TestAxiomClosureCensus` (via
`test_formal_admitted.py::AXIOM_CLOSURE`) and
`test_formal_call_proof_gen.py::TestTheRecursionFamiliesStillGenerate` ·
**found 2026-10-04 on `work/formal25-6`** while running the narrow suites for
two unrelated FORMAL fixes · **both pre-existing, neither caused by that work**
· measured on arm64 (the axiom census is over `lib/*.lean`, so it is one set of
numbers for both architectures)

It is filed because the thing worth knowing is: **a red because the thing it
watches got FIXED and the row that recorded the old state was not updated.** Not
a bug in the code under test, and the honest fix is to re-measure and rewrite the
expectation — the opposite of what a red normally asks for, and why it survived.

(§2 of this doc was a second instance of the same shape, on
`TestTheRecursionFamiliesStillGenerate::REFUSED`. That one is fixed and its
section is gone; the two were filed together for that reason, not because they
share a fix.)

## 1. `AXIOM_CLOSURE` is stale for four of its five modules

`test_formal_sweep_truth.py::TestAxiomClosureCensus` SKIPS when
`lib/ProofLib.olean` is absent, and it was absent in this worktree — which is
why a table can be wrong for a day with nobody noticing. It exists now (the
suite built it), and the class runs and fails:

    $ python3 tools/memslot.py --gb 8 --label st -- python3 test_formal_sweep_truth.py
    Ran 118 tests … FAILED (failures=1)
    FAIL: test_the_closure_census_says_what_the_text_census_cannot
    AssertionError: Tuples differ: (7, 0, 7, 0, 0, 0) != (7, 0, 6, 1, 0, 0)

The numbers, taken directly through `formal/admitted.py::theorem_axiom_census`:

| module | measured `(asked, reaches, clean, text_only, closure_only, ofReduceBool)` | the table says |
|---|---|---|
| `Contracts` | `(7, 0, 7, 0, 0, 0)` | `(7, 0, 6, 1, 0, 0)` |
| `ProofLib` | `(264, 43, 211, 3, 7, 0)` | `(255, 51, 192, 3, 9, 0)` |
| `Refine` | `(29, 0, 29, 0, 0, 0)` | `(22, 0, 20, 0, 2, 0)` |
| `X86` | `(78, 2, 75, 0, 1, 0)` | `(73, 2, 69, 1, 1, 0)` |
| `work` | `(18, 0, 17, 0, 1, 0)` | `(18, 0, 17, 0, 1, 0)` — the only current row |

Every stale module asks MORE theorems and reaches FEWER axioms, and the cause is
`1afe11a7` ("native_decide: 63 closed-fact sites become kernel-checked"), which
replaced 61 `native_decide` sites in `ProofLib` with `decide`/`rfl`, 1 in
`Contracts` and 1 in `X86` without re-measuring this table. `Contracts` is the
pure case: its one `text_only` theorem became `rfl`, which names no tactic at
all. `Refine` is the other direction — 29 asked, nothing reaching anything.

**Next step.** Write the five rows above down with the date and the commit, and
say in the comment that `ProofLib`'s `reaches` falling from 51 to 43 IS
`1afe11a7`, because that number is the audit's headline figure and the next
reader needs to know the two are one event. Then decide, with the numbers in
hand, whether `asked` should be a FLOOR rather than an equality: it rises every
time somebody adds a lemma to `lib/`, and a red that fires on an unrelated merge
teaches nobody anything — which is the argument `LIBRARY_TRUST`'s tactic-site
CEILING already makes in the same file. Worth adding to the class's docstring
that its skip HIDES this staleness, so a green run is not read as a checked
table.

## Why it is not fixed here

The fix is one line of bookkeeping per row, and `AXIOM_CLOSURE` belongs to the
axiom-census work (`test_formal_admitted.py`'s own tables, where the ceiling and
the closure census both live) rather than to this worker's write set. It was found while running the narrow suites for two
unrelated FORMAL fixes, and "the suite I am running is red for a reason that is
not my change" is a measurement to report rather than a thing to absorb into a
branch that has nothing to do with it. The measurements are above so that it
does not have to be re-derived.

## Reproducing

    python3 tools/memslot.py --gb 8 --label st -- python3 test_formal_sweep_truth.py
    # needs lib/ProofLib.olean; `python3 tools/suite.py prooflib` builds it

    python3 - <<'PY'
    import os, sys; sys.path.insert(0, os.getcwd())
    from formal import admitted as A, lean as L
    lib = A.lean_dir(os.getcwd())
    s = A.axiom_census_summary(A.theorem_axiom_census(L.find_lean(), lib), lib)
    for m, g in s.items():
        print(m, (g["answered"], len(g["reaches"]), len(g["clean"]),
                  len(g["text_only"]), len(g["closure_only"]),
                  len(g["of_reduce_bool"])))
    PY