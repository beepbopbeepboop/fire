# `count` and `pow2` fail their generated proofs on master, and neither is in `EXPECTED_FAILURES`

**Area:** FORMAL, arm64 — `formal/arm64_proof_gen.py`'s frame-address goals and
`lib/ProofLib.lean`'s address canonicalisation lemmas. **Status: OPEN, measured,
NOT FIXED. Found 2026-10-04 on `work/formal21-4` while landing the floor
correction for `//` and `%`, and it is PRE-EXISTING: it reproduces on the base
commit.**

## What was run

```console
$ python3 tools/memslot.py --gb 8 --label base-ex -- python3 test_formal.py -j 1 count pow2 wide_recv
  [1/3] FAIL  count  (build/proof failed: t64.ofNat 4294968008 -
            (UInt64.ofNat 4294968008 % 4096 -
              ((if False then UInt64.ofNat 1024 - UInt64.ofNat (2 ^ 21) else UInt64.ofNat 1024) * 4096 +
                UInt64.ofNat 8))).toNat
        (st.sp - UInt64.ofNat 1984))
      (st.sp - UInt64.ofNat 8).toNat =
    st.x30)
  [2/3] FAIL  pow2   (same text)
  [3/3] FAIL  wide_recv  (build/proof failed: ImplementedError(...))
Results for arm64 formal proofs: PASS=0 KNOWN-GAP=0 FAIL=3
```

**Run against `da80b19a` in a separate worktree, which is where this tree's
branch was cut** — so this is not a regression from the floor correction, and the
three failure texts are byte-identical with and without it. The floor correction's
own two examples (`udivmod`, `floordiv`) pass on both architectures with **0
admitted `sorry`**, which is the comparison that establishes it.

## Why it matters more than three red rows

`test_formal.py`'s `EXPECTED_FAILURES` has four entries (`fib`, `countdown`,
`wge`, `subscript_var`) and the file's own stale check reports an entry that
STARTS PASSING as a failure. `count`, `pow2` and `wide_recv` are in **neither**
list: they are undeclared reds in a file the gate does not run (the eight
Lean-checking formal tests are `disabled=`), which is the
`bugs/TEST_registered_tests_in_no_bucket_never_run.md` shape with a different
cause — nothing is expected, nothing is reported, and three of the corpus's
heaviest examples have no proving case.

`formal/lean.py`'s own measurement table names two of them as the *slowest
successful* proofs it knows (`count` 79.7 s / 2.71 GB, `wide_recv` 93.4 s /
3.00 GB — the largest generated file), so whoever last measured them had them
green. Something since then turned them red and nothing noticed, which is the
`FILES BLOCKED IS AN UPPER BOUND` property applied to a test file: a change
elsewhere moved them.

## The two shapes, and they are different bugs

1. **`count`/`pow2`: a frame-slot ADDRESS goal.** The goal is a statement that
   `(A - (A % 4096 - off)).toNat = (st.sp - 1984)` for a literal `A =
   4294968008` — the `A % 4096` is the frame-slot canonicalisation
   (`lib/ProofLib.lean`'s `u64_slot_*` / `mem_read_*_slot` family, the same
   machinery `bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` and
   `FORMAL_dylib_export_loops_and_frame_bounds.md` §1 are about). The `(if False
   then … else …)` in the middle is a **degenerate frame-bound constant** — the
   condition is literally `False`, so the branch is dead weight in the term the
   `simp only` has to normalise. `count` and `pow2` are `for`-loop examples, so
   the bound is the loop's, and a bound whose condition has simplified to `False`
   is the shape to look at first: it suggests the `FrameBound` hypothesis was
   specialised to a value that made one arm vacuous and the peel then has nothing
   to match.
2. **`wide_recv`: a struct field read with no model value.** The generator raises
   `NotImplementedError: model: a struct field read has no value in the semantic
   model (a `UInt64 → UInt64` function over the source's arithmetic); refusing
   rather than modelling it as 0`. That is `_expr_go` reaching a
   `self.<field>` inside an expression, and the refusal is RIGHT about the model
   (a field's value is not derivable from the source's arithmetic) — so
   `wide_recv` has no proof because its model has no answer, not because a tactic
   gave up. It is the by-reference receiver case: `formal/model.py`'s
   `wide_receiver_by_reference` is what makes the receiver a frame ADDRESS, and
   the field reads behind it are exactly what the model's `UInt64 → UInt64`
   shape cannot express.

## The next step

1. **Bisect `count`.** It is the smaller of the two frame cases and its goal
   names every constant, so `grep`ing the generated
   `output/count_proof.lean` for `4294968008` and reading the surrounding
   `have hframe := FrameBound …` is one step. The degenerate
   `(if False then … else …)` is the thing to explain.
2. **`wide_recv` is a model question, not a proof question**, and the honest
   options are the ones `bugs/FORMAL_wide_receiver_by_reference.md` and
   `FORMAL_a_one_field_struct_whose_only_field_is_a_nested_frame.md` already name:
   either a by-reference receiver's field read gets a model, or the example is
   stated over the one shape the model can express. It is a wide receiver with
   more than one field, so the second option is the one to measure first.
3. **In the meantime, `test_formal.py`'s `EXPECTED_FAILURES` should say so** —
   with a reason per row, which is what that table is for and what its stale
   check is built on. A declared red that nobody has fixed is a census; an
   undeclared one is a hole that reads as coverage.