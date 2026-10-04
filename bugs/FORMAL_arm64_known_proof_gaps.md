# FORMAL_arm64_known_proof_gaps: the arm64 examples whose proof is a documented gap

**Status: the FOUR gaps below are still the four `EXPECTED_FAILURES` entries in
`test_formal.py` (read on this tree, 2026-10-03: `fib`, `countdown`, `wge`,
`subscript_var`, and nothing else), so the CENSUS in this file is current and
`EXPECTED_FAILURES` is still its authority. What is NOT current is the
"0 fail": there are FIVE MORE red examples that this file does not list, they
are all one fact, and their doc is `FORMAL_arm64_x30_is_reloaded_from_the_frame.md`.
Nothing changed on this branch, so this is a correction to the file's own header
rather than a finding.**

## The count, corrected (2026-10-03)

`41 pass / 4 known-gap / 0 fail` was measured 2026-10-01 and the "0 fail" has
not been true since. On this tree:

* `count`, `fact`, `pow2`, `sqsum`, `sum` — the five arm64 examples with a
  RECURSIVE CALL in the `_dec1_pattern` shape — all fail with the identical
  obligation, which is a load of a frame slot against the entry state's `x30`
  where the read's slot is five writes deep and the innermost write is the
  stack-floor word at an ABSOLUTE address. Measured directly here for `count`
  (`python3 fire.py build --formal --backend=arm64 -o .tmp/f18/dump/count2.aout
  formal/examples/count.mojo`, 4.3 GB, one Lean run): the reduced goal is
  `mem_read_u64 (mem_write_u64 … (<stack-floor>) (st.sp - 1984))
  (st.sp - 8).toNat = st.x30`, inside `hx30fr_5` of `count_contract`, whose
  `st` IS a free `Arm64State` — which is why the emitted theorem is false as
  stated and why the fix is a premise rather than a tactic. All five are
  UNEXPECTED failures: nothing in `EXPECTED_FAILURES` names them, so they are
  reported as failures rather than as gaps.

They are a family and not five findings, and they are worth **12 % of the arm64
corpus**, which is the number that makes this file's census worth correcting
rather than leaving at "0 fail".

**What this file is NOT the place to fix them.** `fib`, `countdown`, `wge` and
`subscript_var` are each owned by another document and are not re-derived here;
the five dec1 failures are owned by
`FORMAL_arm64_x30_is_reloaded_from_the_frame.md` and its fix needs a premise on a
Lean contract theorem plus a per-conjunct `FrameOk` tactic, which is a
generator-and-library change rather than a census edit.

## `either` and `both` — FIXED 2026-10-01, the per-path statement it needed

`either` is `if n > 10 or n == 0:`; `both` is `if n > 0 and n < 10:`. Both
build and typecheck now, and both entries are out of
`test_formal.py`'s `EXPECTED_FAILURES`. The record of what was wrong is worth
keeping, because the diagnosis in the original version of this section was
about the wrong layer.

The shape: `_emit_truthy_word` recurses into both operands and branches
between them, so a short-circuit condition lowers to TWO conditional branches
— the chain's own (CBNZ for `or`, CBZ for `and`), whose taken edge skips the
right operand, and the `if`'s own, in the merge block that both paths reach.
That merge block's register holds the LEFT operand's cset on the short-circuit
path and the RIGHT one's on the fallthrough.

Three defects, each of which alone was enough to fail the build:

  1. The source condition was paired with the i-th CONDITIONAL block. A
     short-circuit condition puts the chain's own branch first, so
     `if a or b:` was read as `if a:` — `bv_decide` returned the
     counterexample, which is `bv_decide` doing its job.
  2. The `*_entry_cond` seed claimed `arm64_reg r <merge block> = 0 ↔ ¬(…)`
     for a block containing no cset at all, so no register carried that
     condition. The theorem is referenced by nothing; its entire effect was
     the counterexample.
  3. A CBNZ's step-RESULT lemma was proved by `by_cases … ≠ 0` while the
     model's `if` is normalised to `= 0` as soon as `arm64_reg` unfolds, so
     the branch's own `*_sr_N` lemma did not typecheck. That one is not
     specific to short circuits: it affects every program whose image has a
     CBNZ.

The fix is `formal/arm64_proof_gen.py`: the pairing is a filter on
`info["cond_branches"]` (the terminators the codegen recorded as `if`/`while`
tests), the chain's own branch is found STRUCTURALLY (the conditional block
whose TAKEN target is the merge block's start), it states a fact about the left
operand whose sense follows the operator, and the merge block states the
operand ITS register holds — found by looking back along the path for the block
whose cset wrote that register — and combines it with the fact the chain's own
branch handed down.

**Still open and separate:** a chain NESTED in a chain (`(a or b) or c`), where
the outer merge has four entry paths each with a different cset having written
the register. See `FORMAL_nested_short_circuit_chain_in_a_condition.md`, and
`test_formal_short_circuit_cond.py`'s `KNOWN_GAP` entry for it.

## `fib` — a tree-recursion `FrameOk` window read

`fib(n) = fib(n-1) + fib(n-2)`, tree recursion, one goal left.

The caller's `FrameOk` window read sits over the callee's store stack, whose
addresses the frame canonicalisation's `u64_sub_add` splits into `sp - (K - 8)`.
`mem_read_write_below` peels a single store at `sp - UInt64.ofNat K`, so the
split has to be folded back first — and the nesting depth is data-dependent.

**Per-depth collapse lemmas were tried, and each one exposed the next form.**
That is recorded here so nobody restarts the ladder. The right fix is to teach
`mem_read_write_below` the split form so that nothing needs collapsing at all.

## `countdown` and `wge` — the generated loop MODEL, not the machine

These two are the `while n > 0` / `while n >= 1` spellings of one shape, and the
shape is a MODEL, not a lowering. The measurement that settles it (and that the
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md` entry now records) is that a
negative counter really does leave the loop immediately and is returned
unchanged — so `countdown_go`'s `| 0 => 0 | k+1 => countdown_go k` is the wrong
function of the source for exactly the inputs the sign bit selects.

`wge` is the same gap as `countdown` (`≥ 1` rather than `> 0`); `wdiff`
(`while n != 0`) is NOT affected, because equality is signedness-independent,
and it passes with no hole. Both are in `EXPECTED_FAILURES` with the reason.

**Owner:** `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` §"Still open 3",
which names the three generator sites and the statements each has to become.
This document does not repeat them; the two are one piece of work and the
other one is the precise version.

## `subscript_var` — a runtime index has no domain in the model

`a = [10,20,30]; i = 1; return a[i]`. The program builds, runs and returns 20
on both architectures, and the x86-64 generator proves it. On arm64 the
*machine* half is proved — every `LDR`/`STR` through a non-SP base gets a correct
step RESULT lemma, and the block certificates build. What is missing is the
*source* half, and it is not a dataflow question: the semantic model is
`UInt64 → UInt64`, so a list has no domain in it and `a[i]` has no value; and
the list's storage (a blob whose first word is its count) is never related to
the source literal.

**Owner:** `FORMAL_wide_receiver_by_reference.md`, which records both halves
(a list domain in the model, and a `Frame.frameToEnv`-shaped fact about the
blob). Left out of the sections above only because it is that document's
subject, not this one's.

## Relationship to the `B.cond` work

These gaps are **pre-existing** and independent of
`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`'s CODEGEN half. That work took
the suite from 30 pass / 10 fail to 40 / 0 without touching them. Three
distinct problems, and the counts should not be conflated:

| | count | owner |
|---|---|---|
| known gaps (fail, documented reason) | 4 | this document (`fib` = 1, `countdown`/`wge` = 1, `subscript_var` = 1); `either`/`both` were 2 more and are fixed |
| **UNEXPECTED failures (fail, no documented reason)** | **5** | `FORMAL_arm64_x30_is_reloaded_from_the_frame.md` — `count`, `fact`, `pow2`, `sqsum`, `sum`, one fact, measured 2026-10-03 and see §"The count, corrected" above |
| sorries in passing proofs | 2, both in `sum_range` | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` ("Still open 3", item 2: the range loop's `loop_cond_flag` states an UNSIGNED order) |
| passing proofs carrying no `sorry` at all | 38 of 39 | — |

**The second row is the one this file was missing, and it is why the "0 fail"
in the header was wrong.** A gap that is not in `EXPECTED_FAILURES` is
reported as a FAILURE, which is the correct behaviour and the reason this
document cannot be a closed list: it is a census of what the harness's table
says, and anything outside that table is a failure until someone writes the
entry down.

The `fib` entry above is one of the original three gaps of this document; `countdown`, `wge` and `subscript_var` were added later and are
recorded in `test_formal.py`'s inline comments with the same contract.
