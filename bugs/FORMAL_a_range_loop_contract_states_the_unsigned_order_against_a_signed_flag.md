# The arm64 range-loop contract states the UNSIGNED order against a SIGNED flag rewrite, so `sum_range`'s flag obligation is FALSE and admits a `sorry`

**Area:** `formal/arm64_proof_gen.py` — `_gen_range_loop`'s
`<name>_loop_body_flag` helper, and the `_ltb_loop` /
`_gen_universal_e2e_cfg` pair that consumes it. **NOT** the flag lemmas
(`lib/ProofLib.lean::arm64_flag_*_s` are correct and are what the rewrite
actually uses), and **NOT** the codegen: the emitted image is right on both
architectures and agrees with CPython. **Status: OPEN, re-measured 2026-10-05
on `work/merge-formal40` at `208c81ff`. Diagnosis contributed by
`work/formal-proofs-health-r2-r2` (`4584c49a`, `9cb83fd6`); its fix half could
not land and the reason is below.**

`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` §"What is left" already
names this as `sum_range`'s second hole ("`sum_range`'s `loop_cond_flag` states
the exit condition as the UNSIGNED `¬ (i < bound)`, so for a negative bound it
is false and the leaf falls to the `sorry`"). **This document does not
supersede it** — it is the same defect, re-measured on the current tree after
that helper was renamed and its state chain rebuilt, plus the missing-library-
lemma fact that is why the fix could not be landed with the diagnosis. Read
this for the reproduction and for the library blocker; read that one for the
sibling half (`pred_iff`'s non-negative-counter assumption, which is a MODEL
change and is not this).

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 -c "
import formal.build as fb
fb.compile_formal('formal/examples/sum_range.mojo', arch='arm64',
                  output='.tmp/sr2.aout', prove=True, check=False)"
built ok
```

`check=False` deliberately: the question is what the generator **emits**, and
asking Lean about it costs a proof run this worker is not permitted to start.
The emitted file is `.tmp/sr2_proof.lean`.

## What I saw

The helper's statement, verbatim from `sum_range_proof.lean:3243`:

```lean
theorem sum_range_loop_body_flag (s : Arm64State) (hpc : s.pc = 4294968112) :
    sum_range_loop_q ({ sum_range_b7_qT13 s with pc := 4294968168 }) = true
      ↔ (arm64_reg 21 ({ … } s) < arm64_reg 19 ({ … } s)) := by
  unfold sum_range_loop_q
  simp only […, arm64_reg, arm64_set_reg]
  …
  all_goals first | decide | omega | grind | done | sorry  -- arm64-cfg-leaf: loop-cond-flag
```

The right-hand side is the **unsigned** `<`. The obligation closes with
`_cond_flag_lines`, whose step 4 is `rw [<lemma>]` where `lemma` comes from
`_COND_LEMMA[words[cbz_pc] & 0xf]` — and this loop's test is a signed
`CSET X0, lt` / `CBZ` pair (`formal/arm64_codegen.py::_emit_for_list`, the
`encode_cset_xd_cond(0, "lt")` at the top of the loop), so the lemma is
**`arm64_flag_lt_s`** (`_COND_LEMMA[11]`). `lib/ProofLib.lean:4192` states that
lemma as

```lean
theorem arm64_flag_lt_s (a b : UInt64) :
    arm64_matches_condition 11 (arm64_subs_flags a b) = true
      ↔ (a ^^^ 0x8000000000000000) < (b ^^^ 0x8000000000000000)
```

so the `rw` puts a **sign-flipped** order on the left of the goal and the goal
becomes "flipped `<` ↔ plain `<`", which is FALSE for any `b` at or above
`2^63`. No tactic closes a false obligation, so line 3249 is the
`_COND_ARITH_DEFAULT` leaf and the file carries the `sorry`. **The statement is
false about the machine, not merely unproved** — that distinction is what makes
this a generator bug rather than a tactic gap, and it is why the leaf is not
fixable by adding anything to `_COND_ARITH`.

## Why the fix cannot be landed with the diagnosis

`work/formal-proofs-health-r2-r2` carries exactly this fix. Its second commit
says so itself, and the sentence is the reason this document exists:

> The snapshot's `arm64_proof_gen.py` half is left in place for now and dealt
> with in its own commit: it references `arm64_slt_iff_lt`, a lemma that was
> only ever going to be added to this file, so as committed it cannot
> typecheck.

Verified on the merged tree:

```console
$ grep -c 'arm64_slt_iff_lt' lib/ProofLib.lean
0
$ grep -c 'arm64_slt_iff_lt' formal/arm64_proof_gen.py   # after the merge, 0
0
```

So the fix is **two changes and only one of them landed on the branch**: the
generator half (the sign-flip spelling `_slt()`, the `hr`/`hb` side conditions
on `loop_cond_flag`/`loop_body_model`/`loop_exit_x0`, and `hbound` on
`_ltb_loop`) and the library half (`arm64_slt_iff_lt`). Merging the branch as
it stands would emit proofs naming a lemma that does not exist — strictly worse
than the current `sorry`, which at least elaborates. **That is why this merge
took master's text for `formal/arm64_proof_gen.py` and recorded the rest here
rather than landing a half.**

The library half is also the half this project measures as expensive:
`lib/ProofLib.lean` is rebuilt by `formal/lean.py::ensure_library` (~27 MB,
~80 s, up to ~4 GB, exclusive `flock`) and every `deps=['prooflib']` job reads
it, so adding a theorem there is not a bounded worker's edit — it is the same
"change to `lib/ProofLib.lean`" the `_narrow_lemma_texts` docstring already
names as out of reach for a bounded worker, and it needs the Lean run to
confirm the lemma's statement before the generator half is worth landing.

## The next step, precisely

1. **Add `arm64_slt_iff_lt` to `lib/ProofLib.lean`** — the reusable piece, and
   the reason this is not a patch:

   ```lean
   /-- The sign flip is an involution, so below the sign bit it is the
       identity on the order.  This is the OTHER direction from
       `arm64_flag_lt_s`, which is flag → flipped order; this one is
       flipped order → order, which is what a loop contract needs when it
       states its hypothesis in the flipped order the flag lemma produced. -/
   theorem arm64_slt_iff_lt (hr : a < 0x8000000000000000)
       (hb : b < 0x8000000000000000) :
       (a ^^^ 0x8000000000000000) < (b ^^^ 0x8000000000000000) ↔ a < b := by
     simp only [arm64_lt_iff_flip]; bv_decide   -- or grind/omega over the split
   ```

   `bv_decide` over the four cases (`hr`/`hb` each true or false) is the shape
   that closes it; a `Nat`-ordered form will not, for the reason
   `bugs/FORMAL_contract_ladder_reach.md` §4 records about `omega` over
   `UInt64`.
2. **Then land the generator half** from `work/formal-proofs-health-r2-r2`
   (`git show 4584c49a -- formal/arm64_proof_gen.py`), re-based: the helper is
   `loop_body_flag` on master, not `loop_cond_flag`, and its state chain is
   `bmid`/`bbody` rather than the `cqt` the branch's diff names. **Re-base it by
   hand, not by applying the diff** — three of its four hunks name identifiers
   master no longer has.
3. **The `hbound` obligation is the remaining hole and it is NOT free.** The
   branch discharges it with an explicit
   `all_goals sorry -- TODO(range): the bound below the sign bit` in
   `_gen_universal_e2e_cfg`, i.e. it moves one admission rather than removing
   one. Closing it needs `while_lt_exit_contract`'s `hbpos` discharged at the
   loop top from the theorem's own fuel hypothesis, and that is a `lib/` fact
   like step 1. **So step 2 alone converts a false statement into a `sorry`
   with a name — worth having, and not the same as fixed.**
4. **Measure the result against the census**: `sum_range`'s arm64 status should
   move from its current row, and the `sorry` count in
   `.tmp/sr2_proof.lean` (32 on this tree, of which `loop-cond-flag` at line
   3249 and the two `range-loop-exit-x30` leaves are this family) is the number
   to watch. `tools/formal_proof_census.py --only sum_range --remeasure
   --write-baseline` is how one row is re-seeded.

## What is NOT here

- **Not a codegen bug.** `sum_range` builds, runs and answers correctly on both
  architectures; `test_formal_run.py` is green over it.
- **Not `countdown`/`wge`.** Those are the `pred_iff` non-negative-counter
  model assumption, which is a different fix (a model change, named in the
  other document) and does not go through a flag lemma.
- **Not the flag lemmas.** `arm64_flag_*_s` are correct; they are what makes the
  mismatch visible.
- **Not a new refusal.** The obligation is emitted, elaborated and admitted.
  Nothing is refused and no example changed status.