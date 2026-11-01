# Integer overflow at RUN TIME is still a silent wrap on a variable operand

**Status: open, with the decision made, the decision shared, the instruction
sequences written and measured, and exactly one obstacle left — which is in the
proof framework, not in the arithmetic.**

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
