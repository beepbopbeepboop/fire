# FORMAL_a_conditions_operand_read_through_an_earlier_stores_slot: `bv_decide` reports a counterexample for a flag the spill hid

**Status 2026-10-04 (`work/formal25-1`): the ENABLING half is landed and pinned,
and the failure this doc quotes no longer reproduces — so what is left is
written down exactly, with the measurement that decides whether it is worth
landing.** Read this before the "next step" below: two of its three steps are
moot on this tree and the third is a change to a shared proof chain that a light
worker cannot Lean-verify.

**Area:** FORMAL (the arm64 proof generator's CFG walk — the `cbz` arm's
`hcond` obligation). Found 2026-10-04 on `work/formal21-6`, while fixing the
`sum_range` GENERATION refusal — a doc since deleted with its fix (commit
`cbf00b9f`: a `for`-range loop lowers with the test at the bottom of its body,
so its back edge is a conditional branch, and the loop-discovery scan only asked
the unconditional-`b` question). That fix is what makes this bug observable at
all: `sum_range.mojo` now generates a proof, which it did not when this doc was
written.

## §0 What landed, and what it is worth

**The defect below is real and is still in the generator: a `B.cond` block's
`hcond` obligation closed with a `simp` set carrying NO flag lemma.**
`formal/arm64_proof_gen.py` built that set from `_cset_conds`, which enumerates
`CSET`s, while the backend lowers comparisons to `CMP` + `B.cond` and a `B.cond`
block has no `CSET` to enumerate — so the set came out EMPTY for every
conditional branch in the corpus. `_fl` (the guard's own value) was read from
`_cset_cond`, which DOES fall back to the terminator's condition field, so the
guard passed and the defect was invisible: the file generated.

Landed, and both halves are the same line of thinking:

* **`_fls` falls back to the branch's own flag lemma** when the block holds no
  `CSET`, so the emitted closer names the lemma the branch tests.
* **`_fl_map` is GONE.** It was a private ten-entry copy of `_COND_LEMMA` in that
  same function — key for key, string for string — so "which table answers this
  condition code" had two answers in one file and nothing said they had to
  agree. `_COND_LEMMA` is the table `_cond_flag_lines` already reads for a
  LOOP's exit test, and a conditional branch's flag predicate is the same
  question, so the copy is gone rather than reconciled.

**Pinned by `test_formal_call_proof_gen.py::TestTheBranchFlagLemmaIsTheBranchOwns`**
— three assertions, and the second is the one a presence check cannot do: the
lemma must be the one the BRANCH tests (`b.lt` is `arm64_flag_lt_s`, and the
unsigned `arm64_flag_lt` would reduce the predicate to an order the machine does
not test while still elaborating). **Verified to fail on the pre-fix tree**
(2 failures: `'arm64_flag_lt_s' not found in 'by_cases h : … simp [h,
Arm64State.init] …'`) and to pass after, with no Lean run involved — which is
the point of putting it in this file rather than in `test_formal.py`.

## §1 The reported failure no longer reproduces, and what replaced it

`sum_range.mojo`'s generated proof, through `formal/lean.py::run_lean`
(`LEAN_PATH` at this worktree's `lib/`, `wall_s=900`), **before and after this
branch — the same single error on the same line**:

| | rc | wall | error |
|---|---|---|---|
| pre-fix (`sum_range.lean` generated at `HEAD`) | 1 | **35.8 s** | `6447:175: error: unsolved goals` |
| post-fix | 1 | **33.5 s** | `6447:175: error: unsolved goals` |

So **the `hcond_4` obligation this doc quotes (line 6760) typechecks on both**,
and `sum_range`'s proof is red for a different reason: line 6447 is
`sum_range_loop_frame_body`, a LOOP-CONTRACT frame-body obligation, not a
conditional-branch one. Two things moved between this doc's tree and this one —
the `hprior_*` value-flow facts now in the `hcond` chain, and the bottom-tested
loop contract — and together they closed the obligation this doc is about.

**So the enabling half is worth having and the doc's own evidence for it is
gone.** It is not worth anything measurable TODAY, and the next step below is
the thing to weigh.

## §2 What is left, and why it is not landed here

**Step 1 is landed. Step 2 is moot. Step 3 was written and measured, and is the
part that is not landed.**

* **Step 2 (spill resolution for prior blocks).** Moot: the obligation closes.
  The `hprior_*` facts the loop-contract work added pin each source variable's
  register in each prior block, which is exactly what the doc asks for, and the
  emitted chain shows them (`hprior_4_0_n`, `hprior_4_2_n`).
* **Step 1, the flag lemma.** Landed, and see §0 for why it is necessary and not
  sufficient.
* **Step 3, keep `bv_decide`.** Already true; nothing to do.
* **The part that is actually left** is the ORDER. The chain's `simp only` line
  unfolds `arm64_subs_flags` / `arm64_matches_condition`, and `simp only` is
  IRREVERSIBLE — so a lemma added to the LATER `simp [h, …]` can never match the
  term the earlier line expanded. The lemma has to fire first, which means the
  order `_cond_flag_lines` already uses for a loop's exit test:

  ```lean
  simp only [<the block chain>, arm64_reg, arm64_set_reg]
  rw [<the spill pair>]
  try rw [<the flag lemma>]
  simp only [arm64_subs_flags, arm64_matches_condition]
  by_cases h : (<the source condition>) <;> simp [h, …] <;> bv_decide
  ```

  **`try` and not `rw` is what makes it safe**: the rewrite fires only when the
  operands have already reduced, and when they have not the `try` is a no-op, the
  following `simp only` unfolds exactly as before, and the closing line is the one
  emitted today. So a chain that closes on the old route closes on the new one.

**Why it is not landed, measured:** it changes **26 of the 49** generated arm64
proofs in `formal/examples` and adds **552 lines** to them, and the only program
a light worker may Lean-check is the one above — where it makes no difference.
Changing a shared proof chain across 26 files on the strength of "it cannot make
things worse, here is why" is a claim `test_formal.py` has to confirm and a
light worker cannot. **The change was written, measured for blast radius, and
withdrawn** rather than landed unverified.

**What would settle it, in one run:** `python3 test_formal.py` (the `formal`
gate job, 47 examples through Lean). If it is green with the chain change and
red without it, the change is the fix for the range case and the next program
that needs it will say so. Until then the honest reading is that the enabling
half is in and the closing half is a project, which is a smaller claim than this
doc made and a truer one.

## The original report


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
