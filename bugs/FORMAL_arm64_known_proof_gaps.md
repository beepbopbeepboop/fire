# FORMAL_arm64_known_proof_gaps: the arm64 examples whose proof is a documented gap

**Re-measured 2026-10-12 (`work/formal306-docs`): the dec1 family is
`fact`, `sum`, `sqsum` and `pow2` PASS with `count` the only one left, and the
cause of the first three was NOT the obligation the census below records.**
Every SP tracker in `formal/arm64_proof_gen.py` read an `ADD`/`SUB` immediate's
`imm12` (bits 21-10) and dropped `sh` (bit 22), so the 128 KiB frame the codegen
takes (`sub sp, sp, #32, lsl #12`, the only way A64 can encode 131072) was
tracked as 32 bytes. The condition block's spill rewrite
(`mem_read_two_writes_adj_uint`, not wrapped in `try`) then matched no store and
the whole proof failed on a goal that was TRUE. `_addsub_imm_bytes` fixes the
decoder and the seven tracker sites
(`test_formal_call_proof_gen.py::TestTheFrameSizeAddSubImmediateIsShifted` pins
it). Measured `python3 test_formal.py -j 1 fact sum sqsum pow2 count`:
**PASS 4, KNOWN-GAP 1, FAIL 0**, and `pow2`'s `EXPECTED_FAILURES` entry was
removed with the fix. `count`'s remaining diagnostics are the return-frame read
`bugs/FORMAL_arm64_x30_is_reloaded_from_the_frame.md` owns plus the
stack-floor-word branch `bugs/FORMAL_arm64_a_cbz_on_a_literal_pool_register_
admits_over_a_false_claim.md` owns — the decoder fix does not touch either.

So the rows below that name `fact`, `sqsum` and `sum` as undeclared FAILs are
now stale: those three PASS. Everything else in the census stands.

**Status: the census below is CORRECTED (2026-10-04, `formal28-2`) by measurement
on this tree, one example at a time, and the correction is in three directions
rather than one. `EXPECTED_FAILURES` is still the authority — it is what
`test_formal.py` reports against — but this file's own numbers about what is red
had gone stale in three separate ways, and a census that is stale in the
direction of "more broken than it says" is as wrong as one that is stale the
other way.**

**Re-measured 2026-10-08 (`work/formal213-docs`), and the five dec1 examples now
PASS.** The cause is the stack-floor guard's `getrlimit` moving out of the
prologue into the startup stub (`arm64_codegen.py::_emit_stack_floor_init`): the
guard is now a load and compare with no call on the walked path, so the dec1
walk no longer stops at an opaque call and the `x30` return-frame obligation is
discharged. Measured one at a time with
`python3 tools/memslot.py --gb 8 --label t -- python3 test_formal.py -j 1 <stem>`
(3.9 GB peak): `fact`, `sqsum`, `sum`, `count`, `pow2` are each **PASS**. So the
table's `count`/`pow2` KNOWN-GAP rows and the `fact`/`sqsum`/`sum` FAIL row are
superseded, and `FORMAL_arm64_x30_is_reloaded_from_the_frame.md`'s subject is
fixed by that move. **The `count`/`pow2` entries in
`test_formal.py::EXPECTED_FAILURES` are now STALE**, and they belong to that
document's claim (`formal214-docs`, no commits yet at the time of this
measurement) — so they are reported here rather than edited from this branch. A
run of `test_formal.py` over either stem exits 1 with "STALE expected-failure
entries (now passing — remove them)", which is the anti-rot check doing its job.

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
| `pow2` | one of the five UNEXPECTED | **PASS** (2026-10-12 — the `sh`-bit SP-tracking fix; see the Status above) | — |
| `fact`, `sqsum`, `sum` | the other three of the five | **PASS** (2026-10-12 — the same fix) | — |
| `sum_range` | "2 sorries in a PASSING proof" | **FAIL** — `⊢ match arm64_go_exit … with | some s => s.x0 = mojo n | none => False`, and **it fails identically on `master`** (measured in a clean `git archive master` export with its own `ProofLib.olean`) | `CODEGEN_arm64_cmp_flags_and_loop_signedness.md` — `loop_cond_flag`'s unsigned order |
| `sgt8`, `sle8` | not mentioned at all | **PASS** (2026-10-05) — were **FAIL** on `⊢ t32s (t32u (t8s n)) = n`, an obligation FALSE over the theorem's unconstrained `n`; the range hypothesis the obligation needs is now on the theorem. **REGRESSED to FAIL on 2026-10-13** — see item 3 below and `FORMAL_call_proofgen_reds_after_the_arm64_model_merge.md` | **FIXED then RED again**, its own doc deleted with the 2026-10-05 fix |
| `ug8` | not mentioned at all | **PASS** (2026-10-05) — was **FAIL** on `⊢ t8u n = n`, the same defect on the UNSIGNED spelling. **REGRESSED to FAIL on 2026-10-13**, same cause | **FIXED then RED again**, same |
| `floordiv`, `udivmod` | not mentioned at all | **KNOWN-GAP** (declared 2026-10-05) — were **FAIL**, and what they were failing at is **not a Lean residual goal**: `formal/arm64_proof_gen.py` raises out of `generate_arm64_proof`, so no `_proof.lean` is written at all. The cause is the universal theorem's call walk refusing two call sites of ONE callee (`//` and `%` each lower to a call to the same divide-and-correct helper) with a single halt address | `FORMAL_arm64_the_universal_theorem_cannot_follow_a_call_into_the_same_image.md`; declared in `test_formal.py::EXPECTED_FAILURES`, and `test_formal_call_proof_gen.py::TestTheDivisionExamplesHaveNoProofToCheck` pins that no proof file exists and that both images still build and run |

**The three corrections, so a reader does not have to diff the table:**

1. **"There are FIVE MORE red examples … so `test_formal.py` should be
   reporting five unexpected failures" is no longer true, and now the reason IS
   that four of them were fixed.** `count` is DECLARED in `EXPECTED_FAILURES`
   with the return-frame read as its reason and the harness reports it as a gap;
   `pow2`, `fact`, `sqsum` and `sum` PASS as of 2026-10-12 on the `sh`-bit
   SP-tracking fix the Status above records, so `test_formal.py` reports no
   unexpected failure in this family at all. The doc's own argument (a gap
   nobody revisits is a bug quietly reintroduced) is what kept the four visible
   through the marker churn, and it is why their rows are updated here rather
   than left to read as open.
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

   **RE-MEASURED 2026-10-13 (`work/formal351-docs`): all three FAIL to typecheck
   again, and the failure is a `rewrite` that no longer finds its pattern, not
   the narrow-typed obligation this fix closed.** Each checked FRESH (a
   cache-buster comment on the proof so `proof_verdict_key` misses and Lean
   really runs), `ok=False cached=False sorries=0`, wrapped in an 8 GB memslot
   reservation:

       sgt8_proof.lean:4306  rw [mem_read_two_writes_adj_uint …] failed; ⊢ arm64_matches_condition 13
       sle8_proof.lean:4306  the same;                                       ⊢ arm64_matches_condition 12
       ug8_proof.lean:4168   the same;                                       ⊢ arm64_matches_condition 9

   So the theorem is not the site any more — the range hypothesis is still on it
   (`TestANarrowTypedParameterGetsItsRange`'s first two assertions are green) and
   a `mem_read_two_writes_adj_uint` peel no longer matches the goal's shape.
   This is the `test_formal_call_proof_gen.py` red the oct-7 merger filed, and
   which `f7bd05ea` ("a block's first-step sequence side condition is
   simp-proved, not rfl") closed along with the doc that recorded it — its
   `sgt8` entry said only that the red was "plausibly pre-existing", and the
   fix was a different mechanism (`first | (simp only [qT0, qS0] <;> done) | rfl`
   in place of a bare `rfl`). It is not this census's to fix, and it is not a
   regression from any narrow-typed change.  `sorries=0` on all three, so the obligation is REJECTED and not
   admitted.

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

**Status update 2026-10-13 (measured against the served `lib/ProofLib.olean`):
the "read of the stack-floor word at `4294968008`" reason the table above gives
for `fact`, `sqsum` and `sum` is STALE: the same change that put a value theorem
back in the whole arm64 corpus took that store out of the chain.** `806e72cb` /
`70b76755` moved the
`RLIMIT_STACK` read out of every prologue into the startup stub, so the
stack-floor store is no longer in the dec1 call chain at all — `grep -c
4294968008 fact_proof.lean` is **0** — and the three now stop on the
return-frame / `FrameOk` window read (`runs-ret-frame-ok-window`) that `pow2`'s
`:4857` also fails in: `⊢ mem_read_u64 (the frame stores) (st.sp + j).toNat = …`
at `fact`/`sum` `:4858` and `sqsum` `:5227`, `rfl` failing with both sides
reduced. That is `FORMAL_arm64_x30_is_reloaded_from_the_frame.md`'s family and
its owner is where the repair is, so the OWNER of this row is unchanged; what
changed is the reason the census gives for it. `count` fails earlier still, on
`maximum recursion depth has been reached` (`count_proof.lean:4305`), which the
x30 doc's re-measurement (when its examples were masked by the conditional-halt
refusal) did not see.

**What is still true of everything below, and is why the rest of the file is
kept as it is:** the four declared gaps are each owned by another document or by
this one, and the one remaining `dec1` example (`count`) is a fact owned by
`FORMAL_arm64_x30_is_reloaded_from_the_frame.md` — the other four PASS as of
2026-10-12. The narrow-typed failures are no longer among them. Nothing in this
file is a fix and nothing in it should be worked from as one.


## The count, corrected (2026-10-03)

**SUPERSEDED 2026-10-13: `fact`, `pow2`, `sqsum` and `sum` now PASS, and
`count`'s failure has moved off the `x30` read.  The measurement below is kept
because it is what the family looked like on 2026-10-03, not because it still
describes the tree — see the Status update at the top.**

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
| **UNEXPECTED failures among the 13 stems measured here** | **0** | was `5`; `pow2`, `fact`, `sqsum` and `sum` PASS as of 2026-10-12 (the `sh`-bit SP-tracking fix), and `sum_range` is a `KNOWN-GAP`/refusal rather than a FAIL (`CODEGEN_arm64_cmp_flags_and_loop_signedness.md`, the range loop's `loop_cond_flag` stating an UNSIGNED order) |
| **UNDECLARED and not listed anywhere in this file before 2026-10-04** | **0** | was `2` (`sgt8`, `sle8`); both PASS as of 2026-10-05 and `ug8` with them, so the row is empty rather than moved |
| sorries in a passing arm64 proof | **1 each** (2026-10-13) | `fact`, `pow2`, `sqsum` and `sum` each PASS with ONE admitted `sorry` (`test_formal.py` prints the per-file census: "1 declaration(s) admitted a `sorry`"); the hole is the stack-floor guard's branch, owned by `FORMAL_arm64_a_cbz_on_a_literal_pool_register_admits_over_a_false_claim.md` — so "PASS" here is "the obligations it can close are closed", not "no hole" |

**The second row is the one this file was missing, and it is why the "0 fail"
in the header was wrong.** A gap that is not in `EXPECTED_FAILURES` is
reported as a FAILURE, which is the correct behaviour and the reason this
document cannot be a closed list: it is a census of what the harness's table
says, and anything outside that table is a failure until someone writes the
entry down.

The `fib` entry above is one of the original three gaps of this document; `countdown`, `wge` and `subscript_var` were added later and are
recorded in `test_formal.py`'s inline comments with the same contract.
