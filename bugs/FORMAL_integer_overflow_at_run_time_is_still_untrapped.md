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
   `bugs/FORMAL_integer_overflow_at_run_time_is_still_untrapped.md` is deleted
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

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_int_semantics.py

`test_formal_int_semantics.py::test_variable_operands_are_still_untrapped` is
the row that pins this doc: it asserts the CURRENT (wrong) answer for a variable
operand, with a comment pointing here, and it is the row that must change when
this is fixed.
