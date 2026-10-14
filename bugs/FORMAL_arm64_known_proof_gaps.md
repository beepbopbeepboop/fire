# FORMAL_arm64_known_proof_gaps: the arm64 examples whose proof is a documented gap

**Status: the census below is CORRECTED (2026-10-04, `formal28-2`) by measurement
on this tree, one example at a time, and the correction is in three directions
rather than one. `EXPECTED_FAILURES` is still the authority — it is what
`test_formal.py` reports against — but this file's own numbers about what is red
had gone stale in three separate ways, and a census that is stale in the
direction of "more broken than it says" is as wrong as one that is stale the
other way.**

**Measured, `python3 test_formal.py -j 1 <stem>`, one at a time (each is a
150-300 s Lean run, which is why this is a sample of the corpus and not all of
it — the full sweep is a heavy run and belongs to the integrator):**

| stem | before this file said | measured 2026-10-04 | owner |
|---|---|---|---|
| `fib` | known gap | **KNOWN-GAP** (declared) | this file |
| `countdown` | known gap | **KNOWN-GAP** (declared) | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` |
| `wge` | known gap | **KNOWN-GAP** (declared) | same |
| `subscript_var` | known gap | **KNOWN-GAP** (declared) | `FORMAL_wide_receiver_by_reference.md` |
| `count` | one of the five UNEXPECTED | **KNOWN-GAP** — it is in `EXPECTED_FAILURES` now, with the return-frame read as its reason | `FORMAL_arm64_x30_is_reloaded_from_the_frame.md` |
| `pow2` | one of the five UNEXPECTED | **KNOWN-GAP** for the same reason (measured in `EXPECTED_FAILURES`; not re-run) | same |
| `fact`, `sqsum`, `sum` | the other three of the five | **FAIL** — one at a time, all three with the identical obligation, a read of the stack-floor word at `4294968008` | same |
| `sum_range` | "2 sorries in a PASSING proof" | **FAIL** — `⊢ match arm64_go_exit … with | some s => s.x0 = mojo n | none => False`, and **it fails identically on `master`** (measured in a clean `git archive master` export with its own `ProofLib.olean`) | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` — `loop_cond_flag`'s unsigned order |
| `sgt8`, `sle8` | not mentioned at all | **PASS** (2026-10-05) — were **FAIL** on `⊢ t32s (t32u (t8s n)) = n`, an obligation FALSE over the theorem's unconstrained `n`; the range hypothesis the obligation needs is now on the theorem | **FIXED**, with its doc deleted |
| `ug8` | not mentioned at all | **PASS** (2026-10-05) — was **FAIL** on `⊢ t8u n = n`, the same defect on the UNSIGNED spelling | **FIXED**, with its doc deleted |
| `floordiv`, `udivmod` | not mentioned at all | **KNOWN-GAP** (declared 2026-10-05) — were **FAIL**, and what they were failing at is **not a Lean residual goal**: `formal/arm64_proof_gen.py` raises out of `generate_arm64_proof`, so no `_proof.lean` is written at all. The cause is the universal theorem's call walk refusing two call sites of ONE callee (`//` and `%` each lower to a call to the same divide-and-correct helper) with a single halt address | `FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`; declared in `test_formal.py::EXPECTED_FAILURES`, and `test_formal_call_proof_gen.py::TestTheDivisionExamplesHaveNoProofToCheck` pins that no proof file exists and that both images still build and run |

**The three corrections, so a reader does not have to diff the table:**

1. **"There are FIVE MORE red examples … so `test_formal.py` should be
   reporting five unexpected failures" is no longer true, and the reason is not
   that they got fixed.** `count` and `pow2` are DECLARED in `EXPECTED_FAILURES`
   with the return-frame read as their reason, so the harness reports them as
   gaps; `fact`, `sqsum` and `sum` still fail with the identical obligation and
   are still undeclared. The FAMILY is unchanged — `count` was re-run here and
   comes back with the same stack-floor-word read — and the census moved because
   the marker table moved. That is worth stating because a declared failure is
   not a fixed one, and the doc's own argument (a gap nobody revisits is a bug
   quietly reintroduced) applies to `EXPECTED_FAILURES` exactly as it does to a
   bug doc.
2. **`sum_range` does not pass with two `sorry`s.** It FAILS, with the
   `arm64_go_exit … = none` disjunct unproved — and it fails the same way with no
   change of mine applied, so this is not a regression from anything on this
   branch. The row in the table below that says "sorries in passing proofs: 2,
   both in `sum_range`" should be read as "an obligation `sum_range` cannot
   discharge", and its owner is the same document as `countdown`'s.
3. ~~**Two examples are missing from this file entirely.** `sgt8` and `sle8`
   are a TYPED narrow parameter making the universal contract false, they are
   red, and they have their own document (the narrow-typed one).~~ **RESOLVED
   2026-10-05: both PASS, and `ug8` with them.**  A narrow typed parameter's
   universal theorem now carries the RANGE the truncation needs, and the
   truncation discharges against it — three examples green where three were
   red, with no `sorry` introduced (`test_formal_call_proof_gen.py`'s
   `TestANarrowTypedParameterGetsItsRange` asserts the sorries count is 0
   precisely because "the obligation became admissible" is the failure mode a
   bound can hide).  The document that owned them is deleted with the fix.

   **Two more examples were missing here too, and are now RESOLVED rather than
   recorded**: `floordiv` and `udivmod` were red on `master` and were not in
   `EXPECTED_FAILURES`, so they were FAILURES by this file's own argument with
   no document anywhere saying why. Measured 2026-10-05 through
   `compile_formal(prove=True, check=False)`: they are refused at PROOF
   GENERATION — the arm64 generator raises before writing a proof file, so the
   "residual goal" a reader would go looking for does not exist — and the cause
   is the universal theorem's call walk with two call sites of one callee. Both
   are declared in `test_formal.py::EXPECTED_FAILURES` with that reason, pinned
   in `test_formal_call_proof_gen.py`, and the document that was tracking them is
   deleted with the answer.

**What is still true of everything below, and is why the rest of the file is
kept as it is:** the four declared gaps are each owned by another document or by
this one, and the three undeclared `dec1` failures are one fact owned by
`FORMAL_arm64_x30_is_reloaded_from_the_frame.md`. The narrow-typed failures are
no longer among them. Nothing in this file is a fix and nothing in it should be
worked from as one.


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
| declared in `EXPECTED_FAILURES` | **7** | read on this tree 2026-10-04: `fib`, `countdown`, `wge`, `subscript_var`, `wide_recv`, `count`, `pow2` |
| **UNEXPECTED failures among the 13 stems measured here** | **5** | `fact`, `sqsum`, `sum` are one fact (`FORMAL_arm64_x30_is_reloaded_from_the_frame.md`); `sum_range` is another (`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`, the range loop's `loop_cond_flag` stating an UNSIGNED order) |
| **UNDECLARED and not listed anywhere in this file before 2026-10-04** | **0** | was `2` (`sgt8`, `sle8`); both PASS as of 2026-10-05 and `ug8` with them, so the row is empty rather than moved |
| sorries in passing proofs | **0 measured**, and the "2 in `sum_range`" row is superseded — `sum_range` does not pass at all, on this tree or on master | — |

**The second row is the one this file was missing, and it is why the "0 fail"
in the header was wrong.** A gap that is not in `EXPECTED_FAILURES` is
reported as a FAILURE, which is the correct behaviour and the reason this
document cannot be a closed list: it is a census of what the harness's table
says, and anything outside that table is a failure until someone writes the
entry down.

The `fib` entry above is one of the original three gaps of this document; `countdown`, `wge` and `subscript_var` were added later and are
recorded in `test_formal.py`'s inline comments with the same contract.
