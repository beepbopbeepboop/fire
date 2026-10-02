# FORMAL_arm64_known_proof_gaps: the arm64 examples whose proof is a documented gap

**Not re-measured on 2026-10-02.** The counts below (`41 pass / 4 known-gap /
0 fail`, measured 2026-10-01) are the last real run, and nothing that session
changed reaches a proof: two `formal/model.py` walks were made iterative (both
proved answer-preserving by a differential over all 733 function bodies in
this worktree's 107 `.mojo` files (none of which failed to parse) and 1,463
generated statement lists — see `bugs/FORMAL_arm64_slice_concat_and_with_refusal.md`
and the commits behind them), a `with … as y:` alias is now stored before the
body is walked, and two `call_callee_name` guards in
`struct_returned_frame_sites` / `_frame_return_status` close a specialization
gap. None of those is `total_of_halts`, the fuel, or the loop model, and a lean
run is outside what a light worker may do. **`EXPECTED_FAILURES` in
`test_formal.py` remains the authority on whether these are still gaps**, and the
harness's own stale-entry check is what would say otherwise.

The arm64 formal suite is **41 pass / 4 known-gap / 0 fail** (measured
2026-10-01, `python3 test_formal.py`). The six gaps are listed in
`EXPECTED_FAILURES` in `test_formal.py`, and that list is the authority on
whether they are still gaps — a stale entry is reported by the harness's own
check. This document says *why* each one is hard and what closing it needs,
which the inline comments do not.

Per the harness's own contract: an entry here means "known unproven, for the
stated reason" — **not** "passing". Nothing is ever stubbed with `sorry` to go
green, because a `sorry` makes Lean accept the theorem, which would assert
exactly the semantics these examples exist to check.

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
| sorries in passing proofs | 2, both in `sum_range` | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` ("Still open 3", item 2: the range loop's `loop_cond_flag` states an UNSIGNED order) |
| passing proofs carrying no `sorry` at all | 38 of 39 | — |

The `fib` entry above is one of the original three gaps of this document; `countdown`, `wge` and `subscript_var` were added later and are
recorded in `test_formal.py`'s inline comments with the same contract.
