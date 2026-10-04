# TEST_the_axiom_closure_table_is_stale_for_four_of_five_modules

**Area:** `test_formal_admitted.py::AXIOM_CLOSURE`, checked by
`test_formal_sweep_truth.py::TestAxiomClosureCensus::test_the_closure_census_says_what_the_text_census_cannot`
· **found 2026-10-04 on `work/formal25-6`**, pre-existing · **both
architectures** (the census is over `lib/*.lean`, which is architecture-free,
so the numbers are one set)

## What I ran

`lib/ProofLib.olean` did not exist in this worktree, so the class skipped. It
exists now — something in the suite built it (the `.olean` files are dated
2026-10-04 11:29 and are git-ignored), which is what made the class run at all
and therefore what made this visible:

    $ python3 tools/memslot.py --gb 8 --label st -- python3 test_formal_sweep_truth.py
    FAIL: test_the_closure_census_says_what_the_text_census_cannot
    AssertionError: Tuples differ: (7, 0, 7, 0, 0, 0) != (7, 0, 6, 1, 0, 0)

and the same numbers taken directly, which is the whole of the finding:

    $ python3 .tmp/axiomcheck.py        # formal/admitted.py::theorem_axiom_census
    Contracts (7, 0, 7, 0, 0, 0)     table says (7, 0, 6, 1, 0, 0)
    ProofLib   (264, 43, 211, 3, 7, 0)  table says (255, 51, 192, 3, 9, 0)
    Refine     (29, 0, 29, 0, 0, 0)  table says (22, 0, 20, 0, 2, 0)
    X86        (78, 2, 75, 0, 1, 0)  table says (73, 2, 69, 1, 1, 0)
    work       (18, 0, 17, 0, 1, 0)  table says (18, 0, 17, 0, 1, 0)   <- the only current row

Every module asks MORE theorems than the table says and reaches FEWER axioms,
and `work` — untouched by the change below — is the only row that still holds.

## Why it went stale, and it is not a rounding

`1afe11a7` ("native_decide: 63 closed-fact sites become kernel-checked") replaced
61 `native_decide` sites in `ProofLib` with `decide`/`rfl`, 1 in `Contracts` and
1 in `X86`, and it did not re-measure `AXIOM_CLOSURE`. That is the direction the
table's own note predicts ("the table moves with the commit"): `reaches` falls
where a site became kernel-checked, and `text_only` falls where a site became
`rfl` (which names no tactic at all) — `Contracts` is exactly that, one row.

The `asked` column rose for `ProofLib` (255 → 264), `Refine` (22 → 29) and `X86`
(73 → 78), so theorems have also been ADDED to those modules since the table was
written. `Refine` is the clearest: 29 asked, 0 reach, 0 text-only, 0
closure-only — every one of its 29 theorems is kernel-checked, where the table
still records two reaching an axiom through another theorem.

**Nothing here is a wrong proof.** `reaches` falling is the project paying its
`FORMAL_native_decide_axiom.md` debt, and `asked` rising is `lib/` growing. The
table is the only thing that is wrong, and it is wrong in the direction that
makes a suite red for a reason unrelated to whatever the reader is testing.

## The exact next step

Re-measure and write the five rows down, with the date and the commit, in the
style the note above already uses for `LIBRARY_TRUST`'s history:

    Contracts (7, 0, 7, 0, 0, 0)
    ProofLib   (264, 43, 211, 3, 7, 0)
    Refine     (29, 0, 29, 0, 0, 0)
    X86        (78, 2, 75, 0, 1, 0)
    work       (18, 0, 17, 0, 1, 0)

and say in the comment WHY `ProofLib`'s `reaches` fell from 51 to 43 — that is
the `1afe11a7` conversion and the number is the audit's headline figure, so the
next reader needs to know the two are the same event rather than a coincidence.

**Two things to decide with that, and they are why this is a doc rather than a
one-line fix:**

1. **`asked` is an EQUALITY and `lib/` is edited by every branch.** Five rows of
   exact counts in a file several workers edit at once is a merge conflict
   generator, and it is the same argument `LIBRARY_TRUST`'s ceiling column makes
   for its tactic-site count — "a ceiling fails when the number RISES, which is
   the direction that matters". A `reaches`/`clean`/`of_reduce_bool` row with a
   FLOOR on `asked` would keep the property that matters (no proof stopped being
   kernel-checked) without failing on every merge that adds a lemma.
2. **The class skips when `lib/ProofLib.olean` is absent**, so on a machine that
   has never run `make prooflib` this is invisible — which is how a table can be
   wrong for a day without anybody noticing. Worth saying in the class's own
   docstring that the skip hides this staleness, so the next reader of a green
   run knows what was not checked.

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