# `AXIOM_CLOSURE` is stale for FIVE of its SIX modules, and one of the five has `reaches` and `text_only` SWAPPED

**Area:** tests (`test_formal_admitted.py`'s `AXIOM_CLOSURE`, asserted by
`test_formal_sweep_truth.py::TestAxiomClosureCensus`). **Status: OPEN, measured,
PRE-EXISTING on `master` (77b24183), not fixed.** Found 2026-10-04 while merging
five finished formal branches into `work/merge-formal27a`. It is not caused by
them: none of the five touches `lib/` or `formal/admitted.py` (`git diff
master..HEAD -- lib/ formal/admitted.py` is empty), and the pinned numbers do
not describe master's own library.

**It is invisible until the library is BUILT**, which is why it has survived: the
class `skipTest`s without `lib/ProofLib.olean`, and the gate normally builds that
behind the `prooflib` dep — so a worktree that has never run a Lean-backed test
never sees it. My session built it at 22:35 as a side effect of running the
narrow formal suites, and the next run of the class went red.

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
FAIL: test_the_closure_census_says_what_the_text_census_cannot
AssertionError: Tuples differ: (7, 0, 7, 0, 0, 0) != (7, 0, 6, 1, 0, 0)
 : Contracts: the closure census moved. asked/reaches/clean/text_only/
   closure_only/ofReduceBool = (7, 0, 7, 0, 0, 0), the table says (7, 0, 6, 1,
   0, 0).
```

That is the FIRST mismatch the loop reaches (`AXIOM_CLOSURE` is a dict, `Contracts`
is its first key), and it stops there. Read the whole census directly to see the
rest — same instrument, same library, one process:

```python
from formal import admitted as A
lib = A.lean_dir('.')
summary = A.axiom_census_summary(A.theorem_axiom_census('/Users/mrs/bin/lean', lib), lib)
```

`lean --version` is 4.32.2, which is what `lean-toolchain` pins
(`leanprover/lean4:v4.32.2`), so this is the toolchain the table claims to have
been read out of:

| module | pinned `AXIOM_CLOSURE` | measured now | what moved |
|---|---|---|---|
| `Contracts` | (7, 0, 6, **1**, 0, 0) | (7, 0, 7, **0**, 0, 0) | the one `text_only` site is kernel-checked |
| `IEEE754` | (24, **19**, 5, **0**, 0, 0) | (24, **0**, 5, **19**, 0, 0) | **`reaches` and `text_only` are SWAPPED** |
| `ProofLib` | (255, 51, 192, 3, 9, 0) | (**267**, 43, 214, 3, 7, 0) | 12 more theorems asked |
| `Refine` | (22, 0, 20, 0, **2**, 0) | (**29**, 0, 29, 0, **0**, 0) | 7 more asked, no closure-only left |
| `X86` | (73, 2, 69, 1, 1, 0) | (**78**, 2, 73, 1, 2, 0) | 5 more asked |
| `work` | (18, 0, 17, 0, 1, 0) | (18, 0, 17, 0, 1, 0) | — agrees |

## Why this is filed rather than fixed by copying the numbers in

Three of the five rows are the boring kind: `lib/` grew under them (`asked`
255→267, 22→29, 73→78), so the pins are behind their own library and re-pinning
is a transcription. **The `IEEE754` row is not that.** Its `reaches` and
`text_only` counts have traded places: 19 sites that the table says reach a
decide axiom now reach none, with `clean` (5) and `of_reduce_bool` (0) unchanged
and `answered` (24) unchanged. Only three things can do that:

1. `lib/IEEE754.lean` stopped using a decide tactic in those 19 theorems while
   keeping 24 declarations — which would ALSO have to leave `text_only` at 0,
   because `text_only` is "the site's own text names a decide tactic", so a
   tactic removal moves sites OUT of both columns, not from one into the other;
2. `formal/admitted.py`'s `axiom_site_tactic` / `axiom_census_summary` changed
   what it calls a "site" — the classifier moving under a pinned measurement is
   exactly what the swap looks like;
3. the census's `LEAN_PATH` is picking up a different `IEEE754`.

(1) is excluded by its own arithmetic, so it is (2) or (3), and **both are a
question about the instrument rather than about the tree**. Refreshing the table
without answering it would publish five numbers, one of which is a swapped pair,
and the swap would then be indistinguishable from a fact about `lib/`. That is
why the fix is not "paste the numbers in".

The class's own later assertions are the reason to read this rather than to
widen the tolerance: it requires `reaches + clean + text_only + closure_only ==
answered` (which the measured rows satisfy — this is a mis-classification or a
mis-source, not a lost theorem), requires that SOME theorem reach a decide axiom
(`every_site` non-empty), and requires zero `Lean.ofReduceBool`. Those still hold
on the measured run, so the mechanism works; it is the published row that does
not describe it.

## The exact next step

1. **Answer the `IEEE754` swap before touching the table.** Diff what
   `theorem_axiom_census` collects for `IEEE754` now against what
   `AXIOM_CLOSURE`'s comment says it collected ("19 reach a decide axiom and 5
   are kernel-checked"): print `census["axioms"]["IEEE754"]` and
   `census["sites"]["IEEE754"]` and look at one theorem end to end. If
   `axiom_site_tactic` now returns `None` for the axiom names `lib/IEEE754.lean`
   actually produces, the classifier is the bug and
   `bugs/FORMAL_native_decide_axiom.md`'s "the wrong AXIOM" thread is where the
   spelling belongs.
2. Re-pin the three boring rows from the measured run, with the date and the
   `lib/` growth in the comment the way `IEEE754`'s own comment already does
   ("Read out of a real `#print axioms` run over all 24 declarations").
3. **Do not loosen the assertion.** The table is a measurement and this test is
   the only thing that notices when it stops being one; a widened comparison
   converts a stale row into a permanently silent one.
4. If the library build is what exposes this, consider whether
   `formal-sweep-truth`'s registration should `deps` on `prooflib` — it is in
   `check` and today it SKIPS in every worktree that has not built the library,
   so the row can rot unnoticed in exactly the worktrees where nobody is running
   the Lean tier. That is a registration question, not a test change.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label pb -- python3 tools/suite.py prooflib
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_sweep_truth.py
```