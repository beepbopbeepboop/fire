# Integer overflow at RUN TIME is still a silent wrap on a variable operand

**Status: open.** Steps 1 and 2 (the refusal, then the terminal trap block the
walk closes at its own `BL`) and step 3's EMISSION for `+ - *` have landed —
both backends trap a variable-operand `+`, `-` or `*` the build cannot fold,
and the generated proofs close the trap's own `BL` (2026-11-02, below). What
keeps this doc open: the four remaining `VARIABLE_ROWS` (`<<`, `//`, string
conversion, `**`) still wrap, and the `wdiff` residual below — the signed
counter model 3dbec27a pins does not state `while n != 0`.

Found and mostly fixed by `work/formal33-int-semantics` (`project33:
int-semantics`). What landed with it is the build-time half and is not the
subject of this doc; this is the half that did not.

## What still happens

A `+`, `-`, `*`, `<<`, `**` or `//` whose operands the build **cannot** fold.
`formal/model.py::fold_overflow` asks `fold_literal_expr`, and a name is not a
value to it, so:

    def main(n):
        a = n + n
        return a            # n = 2**62  ->  0, exit 0, nothing on stderr

CPython answers 9223372036854775808. Measured, both backends, before the change
this branch landed:

| source | CPython | arm64 | x86-64 |
|---|---|---|---|
| `a = n + n`, `n = 2**62` | 9223372036854775808 | 0 | 0 |
| `a = n - n - 2`, `n = 2**63 - 1` | -9223372036854775809 | -1 | -1 |
| `a = n * n`, `n = 3000000000` | 9000000000000000000 | wraps | wraps |
| `a = 1 << n`, `n = 63` | 9223372036854775808 | -2**63 | -2**63 |
| `a = n // m`, `n = -2**63`, `m = -1` | 9223372036854775808 | -2**63 | **SIGFPE** |

Exit 0, empty stderr, and a number that is not what the source says.

## What is already in place, and is not the obstacle

1. **The decision is shared and arch-free.** `model.int_overflow_traps` is the
   one predicate both backends ask, with the exclusions that have reasons
   (narrow and unsigned types wrap by definition; pointer arithmetic wraps
   because a one-past-the-end address is not an overflow). It already answers
   correctly for the variable case — it is the *emission* that is not wired up.

2. **The message is shared.** `model.int_overflow_trap_message(op)` is one
   sentence per operator, in the shape `int_parse_trap_message` established,
   and it says plainly that this path cannot raise rather than pretending to be
   `OverflowError`.

3. **The status is shared.** `model.INT_OVERFLOW_TRAP_STATUS` IS
   `SHIFT_TRAP_STATUS`, deliberately: "this program could not be answered on
   this target" is one answer on this path, not one per check.

4. **The encoders exist and are verified against `as`.**
   `formal/arm64.py::encode_adds_xd_xn_xm` (`0xab010000` for
   `adds x0, x0, x1`) and `::encode_smulh_xd_xn_xm` (`0x9b417c02` for
   `smulh x2, x0, x1`).

5. **The sequences are written and RUN correctly.**
   `formal/arm64_codegen.py::_emit_int_alu_checked`:

   | op | sequence | measured |
   |---|---|---|
   | `+` | `ADDS X0, X0, X1` ; `B.vs` | traps on overflow, right on the edges |
   | `-` | `SUBS X0, X0, X1` ; `B.vs` | same |
   | `*` | `SMULH X2, X0, X1` ; `MUL X0, X0, X1` ; `EOR X2, X2, X0` ; `LSR X2, X2, #63` ; `CBNZ X2` | same, including `-4000000000000000000` and `a * 1` at `2**63-1` |

   Two things about the multiply are worth keeping, because both were wrong
   first:

   * **`high == low` is not the test.** For `6 * 7` the high half is 0 and the
     low half is 42, so `high == low` traps on the most ordinary multiplication
     there is (measured: `a = 6 * 7` exited 1 with the overflow message). The
     test is `high == sext(low)`, which is exactly "bit 63 of `high XOR low` is
     set", and the `EOR`+`LSR #63`+`CBNZ` spelling is that identity without
     materialising the sign extension.
   * **`TBNZ #63` is not available.** `encode_tbnz_xn_bit` refuses a bit above
     31 and its own assertion names the alternative this uses.

6. **The Lean model is ready.** `lib/ProofLib.lean` has `arm64_step` branches
   for `ADDS`/`CMN` and `SMULH` on top of `arm64_adds_flags` and `smulhi64`;
   `formal/arm64_proof_gen.py` has the `_STEP_CONDS` rows and `_step_rhs`
   cases; `work_step_adds` and `work_step_smulh` are proven. `check_step_conds`
   passes, `lib/ProofLib.lean` builds, and `def main(n): return n + 1` proves in
   15 s **with these arms present but unreached**.

   x86-64 needs no Lean work at all: `lib/X86.lean` already models `ADD`, `SUB`
   and `IMUL r64, r/m64` flags including OF (`x86_flags_sub`, and the `ovf` the
   `imul` arm computes), `x86_cond 0 = of_` / `x86_cond 1 = !of_` exist, and
   `jcc rel32` and `setcc` are decoded. The x86-64 sequence is
   `ADD/IMUL rax, r11` ; `JO`/`JNO` over an inline trap, or `SETO`+`TEST`+`JZ`.

## The obstacle, measured

Enabling the trap puts `_emit_exit`'s `fflush` **on the overflow path**, and
`arm64_proof_gen.py::_unfollowable_calls` counts every `BL` a proved function
contains. The raw-syscall `write` in `_emit_overflow_diagnostic` already removed
the first of the two calls this branch's trap would have had; what remains is
the `fflush`, and with exactly one call the generator builds its whole
pre/post-extern apparatus around it:

    pp1_proof.lean:1653:48: error: Tactic `native_decide` evaluated that the
      proposition
        main_pre_0.pc = 4294968416
    is false

`main_pre_0` is the state the generator *believes* the call is reached from, and
for `def main(n): return n + 1` with `n = 10` the overflow path is not taken, so
the belief is false and the proof fails on its own premise.

**This is a PRE-EXISTING limitation and not one this branch introduces.**
Measured on master, unchanged:

    def main(n):
        if n > 100:
            printf("hi")
        return 0

    → build: proof check failed
      cc_proof.lean:1064:48: error: Tactic `native_decide` evaluated that the
        proposition
          main_pre_0.pc = 4294968392
        is false

Same error, same shape, no integer arithmetic involved: **any `BL` reachable
only on a path the test input does not take breaks the arm64 proof.** The
generator's own comment on `_unfollowable_calls` documents the neighbouring
half of this limit ("the halt address is ONE address and the walk reaches it
only on the paths that pass it") and turned the TWO-call version into a named
refusal; the ONE-call-on-a-untaken-path version is not yet named and is a
crash-shaped failure.

## Status, 2026-10-05: step 1 LANDED, and it is narrower than "not reachable on
## the concrete test input" — the filter is the emitter's own `cond_branches`

The obstacle below is named rather than proved past. That is all step 1 asks
for, and it is worth having on its own: it converts `exit 1` plus eleven Lean
errors into one sentence that names the two facts a reader needs.

**What landed** is `formal/arm64_proof_gen.py::_reached_without_a_condition`,
asked where `_calls` is computed, and a refusal when it answers False:

```
build: no proof was generated: … The generator's own word for it: universal
theorem: the call at 0x100000448 -> 0x100000468 is the halt address, and it is
behind a CONDITIONAL, so whether the run reaches it is a fact about the test
input rather than about the CFG. …
```

**The filter is `info["cond_branches"]`, and that is not a detail — it is the
whole of what keeps the check the right SIZE.** The doc's step 1 says "not
reachable on the concrete test input", which is the question about the RUN; the
generator cannot evaluate a condition, so the question is approximated with
"reachable on a path that crosses no SOURCE conditional", and the difference is
measured both ways:

| program | source conditionals | before | after |
|---|---:|---|---|
| `if n > 100: printf("hi"); return 0` | 1 | exit 1, eleven Lean errors | **refused by name** |
| `printf("hi"); return 0` | 0 | **proves** (exit 0, proof checked) | proves |
| `a // b` (the div0 rows' own program) | 0 | **proves** | proves |

The two controls are why a wider filter is wrong. `printf` with no `if` is five
`cbz`-kinded blocks wide — the `printf` expansion's own structure — so blocking
on every conditional would refuse a program that proves. And `a // b` puts its
`__div0` call on the TAKEN edge of the guard's own `CBZ Xb`, which is not a
source conditional at all and whose proof
`test_formal_call_proof_gen.py`'s `TestTheZeroDivisorGuardAgainstLean` READS; a
filter that cannot tell the two removes a measurement other rows depend on. So
an emitter-internal branch is followed down BOTH edges (the over-approximating
answer, and the right one for a question whose failure mode is a false
refusal), and only a branch the emitter recorded as testing an `if`/`while`/
ternary refuses.

**Corpus: nothing moved.** All 52 `formal/examples/*.mojo` regenerate to the
same verdict (`compile_formal(prove=True, check=False)`, no Lean): 48 generated,
the same 4 refused as before, because **no example in the corpus has an
unfollowable call at all** except `floordiv` and `udivmod`, and both already
refuse on the TWO-call rule above.

**What is still missing is step 2, and this change does not touch it.** A trap
BLOCK the walk treats as terminal — so a `BL` in a block that cannot return is
not an unfollowable call — is what would let a call behind a condition be
DISCHARGED rather than refused, and the trap block also has to be excluded from
the source-condition mapping (the mis-attribution `_cfg_blocks`' own
`either`/`both` comment warns about). Only after that is step 3 — flipping
`M.int_overflow_traps` from `refuse-if-foldable` to `emit` — a real fix rather
than a better diagnostic. The `VARIABLE_ROWS` table in
`test_formal_int_semantics.py` still asserts the current (wrong) answer, and it
is still the table that has to change.

## Status, 2026-10-31: step 2 LANDED — the trap block is terminal, the walk
## closes it at its own `BL`, and the residual is measured again

Step 2's rule landed whole, in both halves the doc names, and it is measured on
`def q(a, b): return a // b`, the corpus's one program whose trap `BL` was the
walk's problem.

1. **A `BL` in a block that cannot return is not an unfollowable call.**
   `_unfollowable_calls` ends its count with that rule, decided on the machine
   rather than on the symbol: `_trap_terminating` is the set of blocks the
   machine cannot return from (a block that ENDS in the `movz`/`svc` tail, or
   one that ends in a `BL` whose fall-through is in the set, iterated to a
   fixpoint), and `_is_trap_bl` is the cut the two consumers need — a block
   that ends in a `BL` whose fall-through is in that set.  The sharper cut is
   deliberate: the weaker "any block in `_trap`" fires for EVERY compiled
   function (the stack-floor guard), and the statement would weaken for a
   program whose run never halts early.

2. **The walk closes the trap path at the call, under a `none => True`
   statement** (`_gen_universal_e2e_cfg`'s `bl` arm trap stop, the
   `generate_arm64_proof` gate, the concrete run test's suppression, the
   refinement's machine half).  The measured shape, on `q` (base
   `0x1000003c0`, slice 2391 bytes, EXIT `0x100000d17`): the divide-by-zero
   arm's `BL` at `0x100000504` targets `0x100000d18` — just PAST the slice,
   where the map the generator EMITS (`_gen_code_defs` appends the terminal
   `ret`) answers `0x00d65f03` — the tail of that word.  The word matches
   no decode arm, so the model runs one step and halts, and `hnone` states
   exactly that: the pc projection (`rfl`), the word (`native_decide` against
   the REAL word — the Lean side is the check, so a map that ever grows past
   the shape fails the `have` loudly), and the decode chain (`unfold` + `rw` +
   `rfl` — the kernel reduces it, `simp` would not, and `native_decide` cannot:
   the untaken arms still carry the state).  One measurement the emission
   cost: `rw [hstep]` closes its OWN goal (the `match none` reduces
   syntactically), while the first branch's `if 0 = 0` ite only reduces under
   `rfl` — so a trailing `rfl` after the step rewrite is "No goals to be
   solved" (measured in the generated proof, both paths into block 4), and the
   two branches end differently by design.

3. **The trap branch is excluded from the source-condition mapping.**
   `_trap_branch` (a conditional block that reaches a bounded stop on either
   edge) is cut out of `_cond_blocks` — the mis-attribution the doc's second
   sub-decision names: the emitter's own overflow guard must not be handed a
   SOURCE condition it does not test.

**Lean verdict on the generated `q` proof** (whole file, v4.32.2): clean —
the only error is the PRE-EXISTING `q_b7_self1` `isDefEq` timeout at
`q_proof.lean:7791/7792` (the same line and column in the pre-change file, and
out of scope), and the universal's two terminal value-flow admissions are the
two `all_goals (first | done | sorry)` named leaves — the residual this doc's
measurement exists for.

**The measurement class sees the residual again** (`TestTheZeroDivisorGuard
AgainstLean`, both spellings byte-identical): the fixture emits
`q_compiles_correctly_universal` once more (no `q_reaches_call_at_`
substitution), and the residual is the guard's false goal, now
implication-shaped —

    ⊢ n1 = 0 → sdiv64 n n1 − ((if n − sdiv64 n n1 * n1 = 0 then 0 else 1) &&&
        if n − sdiv64 n n1 * n1 ^^^ n1 ^^^ 9223372036854775808
        < 9223372036854775808 then 1 else 0) = 0

— and the doc's next step (adding the enclosing branch fact to the terminal
flow) changes nothing measured, so it is still not a version of the fix.  The
pin moved with it.

**Corpus: one verdict moved, in the direction this doc wants.**  `mod_by_var`
(the other example whose trap `BL` fell into the old one-call substitution)
now generates its universal: its trap branch is DEAD by value flow — the
divisor register holds the constant `4`, the zero case closes by `hne_2`
(`simp` over the block states) + `absurd` — so there is no `hnone` there at
all, and the concrete run test is suppressed with the named note.  `floordiv`
and `udivmod` are unchanged (still the two-call refusal).  The quick test —
the `VARIABLE_ROWS` table — is green (16/16) and asserts the CURRENT answer,
which step 2 does not change: flipping the EMISSION is step 3.

**What is still missing is step 3**: `M.int_overflow_traps` becomes `emit`
rather than `refuse-if-foldable` in both backends (the check sequences are
written and measured and the Lean model is ready, section above), the
`VARIABLE_ROWS` table flips to the trap answers, and this doc is deleted in
the same commit.

## Status, 2026-11-01: the verification completed — the class ran to the end,
## and the two pins the flip left stale moved with the measurement

The round above committed the walk-side half before the class's own Lean
lines had run to completion on the new state.  This round ran them, and the
two pins the flip left stale are fixed and measured; nothing in the entry
above changes, except one sentence's precision.

- **The Lean lines ran, 3/3** (`TestTheZeroDivisorGuardAgainstLean`, under
  the 12 GB ceiling, peak 5.8 GB).  The entry's "both spellings
  byte-identical" was the GOAL's identity, not the trace count's: the walk
  runs the divisor-nonzero path once per visit to the guard block, so the
  file carries a SECOND terminal value flow, and the `hc_N` patch reaches
  the second terminal, where the in-scope branch fact is the NEGATION, so
  its `simp` leaves the same goal the first terminal always leaves.
  Measured: `as_emitted` traces `[goal]`, `doc_next_step` traces
  `[goal, goal]` — the implication-shaped false goal above, byte for byte,
  twice.  The line now compares the residual's goal (the set); the
  survival itself is the sibling line's pin, and the walk-terminal's own
  `done` at the second terminal as emitted is what says the divisor-nonzero
  path is fully closed there.  With the old list-identity assertion the
  line was red on the committed state — the first real run of the class
  since the flip.
- **`TestTheOneOpaqueCallIsAnnounced`'s fixture was this doc's own.**  It
  measured the substitution the walk no longer makes for `a // b` — three
  of its four lines red on the committed state, the fourth (the no-opaque
  control) the only survivor.  It now measures the note with a GENUINE
  single out-of-image call — `printf` with an unused return value, the
  corpus's other shape (`formal/examples/printf_int.mojo`'s body, named
  `q`): the substitution and the note are emitted exactly as its lines
  pin, Lean-free, 4/4.  The flip its div0 fixture pinned is
  `TestTheDiv0FixtureHaltsAtTheCompilerTrap`'s to own now.
- **The rest of the round, re-measured on this tree:** the quick test
  16/16 (the `VARIABLE_ROWS` rows asserting the current answer — the table
  step 3 must flip); the 13 Lean-free affected classes green (the four
  above plus `TestCompilerTrapIsNotAProgramCall`, `TestCfgLeafCensus`,
  `TestTheDivisionExamplesHaveNoProofToCheck`, `TestTheReachedWalkIsPerPath`,
  `TestACallOnAnUntakenPathIsARefusalNotALeanError`,
  `TestTheRecursionFamiliesStillGenerate`,
  `TestTheStackFloorGuardReadsTheLimitInTheStartupStub`,
  `TestAPlaceholderModelClaimsNothing`,
  `TestTheDivideByZeroGuardIsEmittedOnlyWhenItCanFire`); and the
  regenerated `q` proof checks clean in Lean (peak 6.5 GB under 12 GB) —
  the entry above's verdict, confirmed on the file the current source
  generates, the two `hnone` branches included.

What is still missing is step 3, unchanged: the emission flip in both
backends, the `VARIABLE_ROWS` flip, and this doc's deletion in the same
commit.

## Status, 2026-11-02: step 3 LANDED for `+ - *` on both backends, the walk
## closes the trap's own `BL`, and the doc stays open on four rows plus one
## model

The emission flip is in, and it is the flip this doc's "The next step, in
order" names — with one deliberate narrowing that the measurements forced: it
covers `+`, `-` and `*`, the three rows whose checked sequences the section
above measured.

**What landed.**

1. **Both backends emit the trap when the build cannot fold.** The checked
   sequences the section above measured (`ADDS`/`SUBS` + `B.vs` and the
   `SMULH`/`MUL`/`EOR`/`LSR`/`CBNZ` multiply; `ADD`/`SUB`/`IMUL` + `JO` over an
   inline trap on x86-64) are now what the variable-operand `+ - *` emits
   instead of a bare wrap; a folded constant expression emits exactly the
   bytes it did before, so no program whose arithmetic the build can fold
   moves a byte. `test_formal_int_semantics.py`'s `VARIABLE_ROWS` flips the
   three rows to `("trapped", INT_OVERFLOW_TRAP_STATUS)` — the CPython answer
   stays in each row's comment — and the two control rows (the signed
   multiply that FITS, the unsigned control) do not move.
2. **The walk closes the trap's own `BL`, and the close is a STATEMENT close.**
   The overflow trap ends in a `BL` whose target is the program's exit stub —
   the address `arm64_go_exit` was given as `exit` — so at the call state the
   model answers `some st`, not `none`, and the trap stop's `hnone` would be a
   false statement. The walk closes the statement instead: `unfold
   arm64_go_exit`, split on the fuel, `if_neg`/`if_pos` the two ites, and the
   goal is `call_state.x0 = mojo n` over the executed path, which the ret
   block's own terminal flow discharges.
3. **wdiff's back edge is a named leaf, and that is the honest answer.** The
   only loop contract this generator states is the single-block countdown one;
   the flip splits the body the overflow branch crosses into several blocks,
   so a `while n != 0` loop has no contract whose `hbodyRun` the machine
   actually runs — and the contract's statement would be false on this model
   regardless (the `B.vs` trap plus the signed counter, below). The walk
   admits the rest of the run at the new `loop-back-edge-no-contract` leaf
   rather than walk an unbounded number of iterations, and the registry is
   17: the fifteen plus `trap-stop-hnone` (the trap stop whose `BL` targets a
   word INSIDE the slice, where the generator does not mirror the model's
   decode) and the back-edge leaf.

**Measured, on this tree.**

- The quick test is 16/16 (8 rows x 2 backends); the full
  `test_formal_int_semantics.py` is 182/182.
- The named suites are green: `TestTheRecursionFamiliesStillGenerate`
  (eleven generate, including `count` and `wdiff`; `sum_range` still refuses
  with the pinned needles), `TestCfgLeafCensus` 3/3 (the registry is exactly
  the pinned seventeen; the three-stem slice reaches seven of the seventeen —
  the two `dec-while` back edges and `loop-cond-step` left it when the flip
  split the `while`'s body, and `loop-back-edge-no-contract` is what the test
  pins instead), `TestTheZeroDivisorGuardAgainstLean` 3/3,
  `TestTheDiv0FixtureHaltsAtTheCompilerTrap` 1/1,
  `TestTheStackFloorGuardLeavesNoCallOnTheWalkedPath` 2/2,
  `TestCompilerTrapIsNotAProgramCall` 11/11,
  `TestTheDivisionExamplesHaveNoProofToCheck` 3/3,
  `TestTheZeroDivisorGuardIsAFalseGoal` 4/4, and
  `TestDecWhileSignedModelRegression` (the model itself is unchanged — the
  flip did not move a byte of it).
- **The `q` proof is byte-identical** to the file the 2026-11-01 entry
  checked: the trap stop's out-of-slice `hnone` machinery and the walk are
  untouched, so its verdict stands.
- **`count` regenerates with exactly two changes** — the two trap stops the
  walk closes — every other byte of the file unchanged.  Its Lean verdict on
  the full generated file is **blocked by an upstream regression that landed
  mid-round** (not by this change): commit 39cd95d4 (2026-11-02, "Strengthen
  formal semantic model and proof generation") modified `lib/ProofLib.lean`
  and `formal/arm64_proof_gen.py` after the old `ProofLib.olean` (Nov 1) was
  built, and the committed library does not compile from source — `lean
  lib/ProofLib.lean` fails with 16 errors (a forward reference to
  `u64_ofNat_sub` at line 740, defined at 770; eight missing `noncomputable`
  markers on the new `strlen`-dependent definitions; two proof failures at
  1426/1434/9231).  The generated `count` proof references the new library's
  content (`strlen` in the six eval-table expressions, the split-lemma `rw`
  lines in the frame contract), so it cannot be checked against the old
  olean, and the library cannot be rebuilt until 39cd95d4's source is
  repaired — a separate round, and the next Lean verdict on every
  frame-contract proof that references the new lemmas waits on it.  Measured
  in its place: the `count` proof minus exactly those 39cd95d4 lines (the six
  `strlen` arms and the split-lemma `rw` lines — byte for byte, every other
  line including both entry==EXIT trap-stop closes is the generated file)
  checks against the pre-39cd95d4 library: exit 0, zero errors, and both
  trap-branch terminals close genuinely, `0 = 0` by the unconditional
  `count_go_zero`, no `sorry` at either.
- **`wdiff`'s Lean verdict is strictly better than its pre-flip baseline.**
  The pre-flip file (the 2026-11-02 measurement, 15 errors) carried the ten
  model-section errors below PLUS five walk-section errors: the
  `wdiff_loop_body_dec` grind failure, the `wdiff_cd_loop` refine tail, and
  the two unsolved `⊢ 0 = wdiff_go n.toNat` at the back-edge tails. The
  post-flip file has the same ten model-section errors at the same lines and
  **zero** walk-section errors: the countdown contract is gone (the flip's
  `B.vs` is a bare ite the contract's run certificate cannot state), its back
  edge is the named leaf, and the trap-branch terminal is the walk-terminal
  leaf. 10 errors, all of them the pre-existing class, none of them new.

**The residual the doc now owns.**

1. **Four `VARIABLE_ROWS` still wrap.** `<<` (the shift-count overflow at
   `1 << 63`), `//` (the `n = -2^63, m = -1` division), the string-conversion
   row and the negative-exponent `**` row: their check sequences are not
   emitted, and each row asserts the current wrap with the CPython answer in
   its comment. The next step for each is the same shape as step 3's — write
   the sequence, measure it, emit it — and the multiply's `high == sext(low)`
   identity is the precedent for the `**` row's `smpy`-shaped overflow test.
   That is four sequences, not one, which is why the flip landed in the
   narrow form it did and this doc is not deleted.
2. **The `wdiff` model mismatch.** `3dbec27a` ("arm64 dec-while model assumes
   signed counter") states the `while n > 0` shape as `wdiff_go m = if m < 2^63
   then 0 else ofNat (m % 2^64)`, and that statement is false for the `while
   n != 0` shape wdiff actually is: the loop iterates for negative `n`, and
   the machine returns `0` for every `n`, so `s.x0 = mojo n` is false for
   negative `n` — measured pre- AND post-flip, which is the pre-existing red
   this round did not introduce. The model is pinned by
   `TestDecWhileSignedModelRegression` and stays; closing the residual is a
   per-shape model (a `while n != 0` statement with its own `go`), which is
   work for its own round. The trap-branch terminal and the back edge are
   where the walk admits it, at named leaves, until then.

What is still missing, in order: the four remaining rows' check sequences
(each one a step-3-shaped round), and the per-shape `while n != 0` model.
Steps 1-3 of the plan below are done for `+ - *`; the doc's deletion, which
step 3 promised, waits on the four rows and the model.

## The next step, in order

1. **Name the limit, so it is a refusal rather than a Lean error.** In
   `_gen_universal_e2e_cfg`, where `_calls` is computed: if the FIRST
   unfollowable call is not reachable from `func_entry` on the concrete test
   input, raise `NotImplementedError` (the generator's refusal type, which
   `tools/formal_proof_breadth.py` classifies as `proof-refused`) with a
   message naming the call address and saying the run does not reach it. That
   alone turns this doc's failure from eleven Lean errors into one sentence,
   and it fixes `if n > 100: printf(...)` at the same time.
2. **Then teach the walk a conditional trap.** The trap is not a call on the
   program's path, it is a block the CFG reaches only when the overflow flag is
   set. Two sub-decisions:
   * `_cfg_blocks` already records it as a `cbz`-kinded block (a `B.cond`), and
     `info["cond_branches"]` will not name it — which is the mis-attribution
     `_cfg_blocks`' own `either`/`both` comment warns about, so the block needs
     to be excluded from the source-condition mapping explicitly.
   * the trap block's own `fflush` needs the block treated as **terminal**, so
     that `_unfollowable_calls` does not count it and the walk does not try to
     certify a block whose `arm64_step` returns `none` at a `BL`. The rule is
     principled rather than special-cased: *a `BL` in a block that cannot return
     is not an unfollowable call, because the walk halts there anyway.*
3. **Then flip the call on**: `M.int_overflow_traps` becomes `emit` rather than
   `refuse-if-foldable`, in both backends, and
   `bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md` is deleted
   in the same commit (per `CLAUDE.md`: a fixed bug's doc is deleted).

## What NOT to do

**Do not make the trap a raw `SYS_exit` with no `fflush`.** It removes the call,
and it is wrong: `svc` is modelled as a NO-OP by `arm64_step`
(`work_step_svc`, "(modelled no-op)"), so the machine model would step
*through* the trap and the universal theorem would go on to assert a terminal
property about a program that has already stopped — which is a false theorem,
not a missing one. The `fflush` before the `svc` is load-bearing for the
model's soundness, exactly as `_emit_exit`'s own docstring says it is for
stdout.

**Do not widen the proven-function budget to two unfollowable calls instead.**
The halt address is ONE address by construction (`_gen_universal_e2e_cfg`'s
`exit_pc`), and every arithmetic operator in a function would then be a
candidate for it.

## Commands that reproduce

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_int_semantics.py \
        -k bugs/formal/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md

The pin is the **`VARIABLE_ROWS` table** in `test_formal_int_semantics.py`, and
`-k` on this doc's own path selects exactly those rows (`main` reads
`STILL_UNTRAPPED_DOC`). Each row asserts the CURRENT (wrong) answer for a
variable operand, with the CPython answer in its own comment and this doc named
as the reason; the `VARIABLE_ROWS` table is the one that must change when the
run-time trap lands. (It carried a per-row `test_variable_operands_are_still_
untrapped` function when this doc was written; the driver is now the table, and
the table's `STILL_UNTRAPPED_DOC` constant is what points back here.)
