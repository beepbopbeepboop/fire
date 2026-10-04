# FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot: `bv_decide` reports a counterexample for a flag the spill hid

**Area:** FORMAL (the arm64 proof generator's CFG walk — the `cbz` arm's
`hcond` obligation). Found 2026-10-04 on `work/formal21-6`, while fixing
`FORMAL_sum_range_generation_refused_and_it_is_not_an_expected_failure.md`,
which is **not** fixed either and says so.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 -c "
import sys, os; sys.path.insert(0, os.getcwd())
import formal.build as fb
fb.compile_formal('formal/examples/sum_range.mojo', arch='arm64',
                  output='.tmp/sr.aout', prove=True, check=False)"
```

Generation succeeds after the loop-contract fix in this branch's other
commit; the generated `sum_range_proof.lean` then fails to TYPECHECK with one
error, and it is in the walk's shared conditional-branch machinery rather than
in anything the loop contract emits:

```
sum_range_proof.lean:6760:137: error: The prover found a potentially spurious counterexample:
- It abstracted the following unsupported expressions as opaque variables:
  [arm64_reg 16 { … }, arm64_matches_condition 2 nzcv✝¹]
```

The goal is the walk's `hcond` for the loop's **preheader** — the block that
tests the range's emptiness before the counter is stored — and the emitted
tactic chain is:

```lean
have hcond_4 : (arm64_matches_condition 11 s_4.nzcv = true) ↔
                 ¬(((0 ^^^ 0x8000000000000000 : UInt64) <
                    (n ^^^ 0x8000000000000000 : UInt64))) := by
  rw [hsid_4]
  simp only [arm64_reg_pc]
  simp only [sum_range_b4_qS0, …, arm64_reg, arm64_set_reg,
             arm64_subs_flags, arm64_matches_condition]
  rw [mem_read_two_writes_adj_uint _ ((s_2).sp - UInt64.ofNat 16) _ _]
  by_cases h : (…) <;> simp [h, Arm64State.init] <;> bv_decide
```

## What I saw

**`simp [h, Arm64State.init]` carries no flag lemma, and that is the whole
failure.** `_fls` — the set of `arm64_flag_*` lemmas derived from the block
that wrote the tested register with a `CSET` — comes out EMPTY for this block,
because there is no `CSET`: the comparison's answer is in NZCV and the branch
is a `B.cond`. So the emitted `simp` list is `h, Arm64State.init`, the raw
`arm64_matches_condition 11 (arm64_subs_flags …)` never reduces to an order,
and `bv_decide` is handed an expression with an opaque `arm64_reg 16` in it
and returns a "counterexample" that is an artefact of its own abstraction.

**So the fix is the one `loop_test_def` already has and this chain does not
use:** the flag predicate has to be read off the block's OWN terminator
(`formal/arm64_proof_gen.py::loop_test`, which answers `arm64_matches_condition
11 s.nzcv` for a `B.cond`), and the comparison's operands have to be peeled
out of the spill slot they were saved in — which is what
`_cond_flag_lines`'s step 3 (`rw [mem_read_push_low s.mem s.sp]`, emitted
BEFORE the flag rewrite, because `arm64_flag_*` will not fire while the
operand is still a `mem_read` of a moved `sp`) does for a loop contract. This
chain's `_rw_spills` emitted a `mem_read_two_writes_adj_uint` and stopped, and
the value it needed came from a slot stored two blocks earlier.

**Three things this is NOT, measured rather than argued:**

* **not a signed/unsigned mismatch.** The statement is already stated with
  the signed reading (`^^^ 0x8000…`), which is what `b.lt` means, and the
  iff is true. The counterexample Lean reports is explicitly "potentially
  spurious" and its cause is the abstraction above.
* **not specific to this program.** Any conditional branch whose condition
  comes from a `CMP` + `B.cond` pair with the operand spilled, reached on a
  path whose prior block holds the spill's store, hits it. The reason this
  program is the first measured case is that until the loop contract was
  generated the walk RAISED before it ever emitted this block's proof.
* **not this branch's to fix.** `hcond` is emitted by the walk's shared `cbz`
  arm for every conditional branch; changing it changes every generated
  proof's verdicts, which is why the loop-contract commit left it alone rather
  than appending a `sorry` to the chain (a hole there would silently convert
  other programs' build failures into admitted obligations).

## The next step

In the `cbz` arm, where `_src is not None` and the block's terminator is a
`B.cond` (index 51) rather than a `CSET`-and-`CBZ` pair:

1. take the flag lemma from `_COND_LEMMA[words[block["instrs"][-1]] & 0xf]`
   — the same table `loop_test` reads — instead of from `_cset_conds`;
2. emit `mem_read_push_low` for every spill slot the operands are read
   through, including the ones stored in PRIOR blocks on the path (the
   `hprior_{bi}_{pb}_{v}` loop already carries a value-flow fact per prior
   block for a NAMED VARIABLE; the comparison's operand needs the same
   treatment, and the `_rw_spills` call only looks at this block);
3. keep `bv_decide` as the closer, so a claim that is genuinely false still
   reports a counterexample instead of being admitted.

The regression net is `formal/examples/sum_range.mojo`'s own proof
(`python3 test_formal.py sum_range`, which must go from FAIL to PASS with the
admitted-hole count reported) plus `test_formal_call_proof_gen.py` and
`test_formal_run.py`, whose conditional-branch rows all read `hcond`.
