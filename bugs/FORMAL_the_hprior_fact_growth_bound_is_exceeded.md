# FORMAL_the_hprior_fact_growth_bound_is_exceeded: `TestNestedConditionFactSharing`'s x2.2 bound is red on master

**Status: OPEN, not fixed here — filed while working the `formal285-docs` batch
(2026-10-12), because it is a real red in a file another doc's fix lives in and
none of that batch's eight docs owns it. It is PRE-EXISTING: it reproduces on
this branch's base, before any of the batch's commits, and nothing in
`test_formal_call_proof_gen.py` was changed by them.**

## What I ran

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_call_proof_gen.py
```

`Ran 170 tests ... FAILED (failures=1, skipped=13)` — 1.4 GB peak, 27.6 s. The
one failure is the third case of `TestNestedConditionFactSharing`:

```
test_the_fact_count_grows_with_the_paths_and_not_with_the_branches:
AssertionError: 2.3333333333333335 not less than or equal to 2.2 :
2 -> 3 conditions grew the facts by x2.33 (9 -> 21); the per-path memo makes
this x2 (the number of paths) and anything above 2.2 is the exponential back
```

## What I saw

The three cases of the class generate the doc's `CONDS` programs (`k` = 2, 3, 4
disjoint-bit `if`s) and count `have hprior_`:

| k | `have hprior_` | distinct statements | ratio |
|---:|---:|---:|---:|
| 2 | **9** | 4 | — |
| 3 | **21** | 6 | **2.33** |
| 4 | **45** | 8 | 2.14 |

The failing ratio is `2 -> 3`, and `3 -> 4` is 2.14 — both are above the x2.0
the memo is supposed to give, and the first is above the x2.2 bound the case
asserts.

**The distinct-statement counts are the ones the memo's own argument predicts**
(4 / 6 / 8 = 2k), so the emission is not proving a new question per branch. What
grew is the per-PATH repetition: the number of paths doubles per condition
(2 / 4 / 8 inferred from the statement pattern), and the per-path fact count
also grows slowly (≈4.5 / 5.25 / 5.6 per path), which is the source of the
ratio sitting between the memo's ideal x2.0 and the pre-memo x2.5.

`bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md` was written
about this family and measures the same program shape (its `not (n & 4)` lowers
to two instructions and two branches): it reports `hprior` DOUBLING
(24 → 48 → 96) on its own shape, and states that the x3.0 / x2.67 / x2.5 that
`cfd550b5`'s commit message records is "a property of that program's condition
shape, not of the family". So a ratio above 2.0 is at least partly inherent to
the program these cases use.

## What I expected

`test_the_fact_count_grows_with_the_paths_and_not_with_the_branches` to pass:
`counts[k] / counts[k - 1] <= 2.2` for k in (3, 4). The bound was calibrated at
`cfd550b5` (2026-10-04) when the same programs measured 24 / 48 / 96 (`hprior`
column of `FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`'s
2026-10-05 table), i.e. exactly x2.0. The absolute counts on the current tree
are 9 / 21 / 45, so either

* the memo's sharing regressed (a later change re-derived facts a path already
  had — the failure `TestNestedConditionFactSharing`'s other two cases, both
  green, are what that would usually trip), or
* the emission shrank (fewer names enter the memo, so the same absolute
  duplicate count is a larger RATIO), and the bound is simply stale.

The other two cases of the class — no fact proved twice in one scope, and no
fact USED where it was not proved — are GREEN, which is the evidence for the
second reading: a fact shared between siblings would fail the second one.

## The exact next step

1. Find what moved the counts from 24 / 48 / 96 to 9 / 21 / 45. `git log -S`
   over `formal/arm64_proof_gen.py`'s `hprior` emission after `cfd550b5` is the
   place to bisect; the commit that reduced the k=2 count from 24 to 9 is the
   one that changed the ratio.
2. Decide which reading above is true:
   * if it is a regression, fix the memo and the case should go green with no
     edit to the bound;
   * if the emission legitimately shrank, re-derive the bound from the shapes
     (`FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`'s table is
     the argument that x2.0 is not the ceiling for a shape containing a
     two-branch condition), and say in the comment why the number moved rather
     than raising it silently.
3. `test_formal_call_proof_gen.py` is Lean-free for these three cases, so this
   is cheap to iterate on — `python3 tools/memslot.py --gb 8 --label t --
   python3 test_formal_call_proof_gen.py TestNestedConditionFactSharing` (three
   cases, ~1 s).
