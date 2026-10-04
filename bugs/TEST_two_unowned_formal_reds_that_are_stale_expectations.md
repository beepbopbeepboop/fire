# two unowned formal reds that are STALE EXPECTATIONS, not defects: `AXIOM_CLOSURE` for four of five modules, and `sum_range` in a REFUSED table

**Area:** `test_formal_sweep_truth.py::TestAxiomClosureCensus` (via
`test_formal_admitted.py::AXIOM_CLOSURE`) and
`test_formal_call_proof_gen.py::TestTheRecursionFamiliesStillGenerate` ·
**found 2026-10-04 on `work/formal25-6`** while running the narrow suites for
two unrelated FORMAL fixes · **both pre-existing, neither caused by that work**
· measured on arm64 (the axiom census is over `lib/*.lean`, so it is one set of
numbers for both architectures)

They are filed together because the thing worth knowing is the same: **each is
red because the thing it watches got FIXED and the row that recorded the old
state was not updated.** Neither is a bug in the code under test, and in both
cases the honest fix is to re-measure and rewrite the expectation — which is the
opposite of what a red normally asks for, and is why each survived.

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

## 2. `sum_range` generates, and a `REFUSED` row still says it does not

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
    Ran 84 tests … FAILED (failures=1)
    FAIL: test_the_one_that_refuses_says_why (stem='sum_range')
    AssertionError: … "sum_range generates now (…); delete it from REFUSED and
    say what closed it — the doc this row cites names the owner of the fix"

`TestTheRecursionFamiliesStillGenerate::REFUSED` holds
`"sum_range": ("cbz taken continuation", …)`, and the generation refusal it
pins is **fixed at the root cause**: `bugs/FORMAL_sum_range_generation_refused_
and_it_is_not_an_expected_failure.md`'s own Status (2026-10-04,
`work/formal21-6`) says "the GENERATION refusal is FIXED at the root cause — the
back edge is discharged by a bottom-tested loop contract … The proof now
generates on arm64", and that branch is merged. What remains of that doc is a
TYPECHECK failure in the walk's shared conditional-branch machinery, which is a
different subject from "does it generate".

**Next step.** Delete the `sum_range` row from that `REFUSED` dict and say what
closed it in the comment — which the assertion's own message asks for, and which
is one line naming `work/formal21-6`. If the intent is to keep watching
`sum_range`, the row belongs somewhere that asserts the thing that is still
open (the typecheck), not in a table whose contract is "these refuse to
GENERATE".

## Why neither is fixed here

Both fixes are one line of bookkeeping each, and neither is in this worker's
write set: `AXIOM_CLOSURE` belongs to the axiom-census work
(`bugs/FORMAL_native_decide_axiom.md`, unclaimed) and the `REFUSED` dict belongs
to whoever holds `formal/arm64_proof_gen.py`'s walk. More to the point, both
were found while running the narrow suites for two unrelated FORMAL fixes, and
"the suite I was running is red for a reason that is not my change" is a
measurement to report rather than a thing to absorb into a branch that has
nothing to do with it. The measurements are above so that neither has to be
re-derived.

## Reproducing

    python3 tools/memslot.py --gb 8 --label st -- python3 test_formal_sweep_truth.py
    python3 tools/memslot.py --gb 8 --label t  -- python3 test_formal_call_proof_gen.py
    # #1 needs lib/ProofLib.olean; `python3 tools/suite.py prooflib` builds it

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