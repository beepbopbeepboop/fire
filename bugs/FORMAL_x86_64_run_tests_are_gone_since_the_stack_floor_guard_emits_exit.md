# FORMAL_x86_64_run_tests_are_gone_since_the_stack_floor_guard_emits_exit

**Area:** FORMAL, `formal/x86_64_codegen.py` (the stack-floor guard) against
`formal/x86_64_proof_gen.py` (`_run_tests_section`'s externs guard).
**Status: MEASURED, NOT FIXED.** Found while merging `work/formal16-7` into
master (`work/merge-formal17`); the one test it makes red is
`test_formal_call_proof_gen.py::TestStringValueInTheModel::test_a_returned_string_is_still_run_tested_on_x86_64`.
It is NOT that test's defect and NOT `work/formal16-7`'s: it is a coverage loss
that landed on master in `e11f066d` and that nothing on master looks at.

## What was measured

`e11f066d` ("every prologue of an image that has an entry carries the
stack-floor guard") put a call to the C library's `exit` in the prologue of
**every** function of an x86-64 image:

    formal/x86_64_codegen.py:1590, inside `_emit_stack_floor_guard`
        self._emit_call_exit(M.STACK_TRAP_STATUS)      # exit(2), the SP trap

`_emit_call_exit` goes through `_emit_extern_call`, so every such image now has
an `extern_refs` entry for `exit`, so `info["extern_calls"]` is non-empty, so
`formal/x86_64_proof_gen.py:565`'s guard fires and the file says NO RUN TESTS.

Reproduced with a four-line probe (build `def main(n: Int) -> Int: return 7`
with `prove=True` and read the emitted `.lean`):

    program                        arm64          x86-64
    return 7                       extern_calls=[]      extern_calls=['exit']
    return "small"                 extern_calls=[]      extern_calls=['exit']
    print(42)                      extern_calls=['printf']  extern_calls=['exit','printf']

    NO RUN TESTS in the proof      arm64: no      x86-64: YES, every program
    theorem main_runs_0            arm64: present x86-64: absent, every program

    python3 test_formal_run.py a_two_thousand_statement_body_builds_and_runs   # the
    control that is NOT affected: 2000 statements, PASS, 37/37 in isolation.

The same probe on master (55951ba3, this worktree's `.tmp/master`) and on
`work/formal16-7` (`.tmp/branch7`) both give the arm64 column above and the
x86-64 column above, so the loss is master's and neither branch caused it.

**So: x86-64 currently emits ZERO run tests and ZERO termination obligations
for every program in the corpus**, and it did emit them before `e11f066d`.
Those are the theorems that compare the machine's result register against `mojo`
by `native_decide` — the one part of an x86-64 proof that is evidence about the
machine rather than about the model, and the part that caught the fabricated
string `0` (`bugs/FORMAL_string_value_model.md`) and the logical `not`
(`lib/ProofLib.lean`'s `unop "bnot"` arm) without a human reading anything.

**Nothing on master notices**, because no test asserts that an x86-64 run test
exists. The only assertion of the shape is branch formal16-7's, which is how
this was found:

    grep -rn "main_runs_" --include='test_*.py' .
    ./test_formal_call_proof_gen.py:1052          # formal16-7's new row

## Why it is a false negative and not a correct refusal

The guard's own stated reason (`formal/x86_64_proof_gen.py:568`) is right for a
call the model *executes*: "the model has no memory for a `__TEXT,__stubs`
trampoline. The branch lands outside the image and the run stops". The
stack-floor trap is a call the model provably never executes, and the argument
is the guard's own emitted sequence:

    lea r11, &floor ; mov r10, [r11] ; test r10, r10 ; jne done
      → `X86State` has NO memory, so the load reads 0, ZF is set, `jne` is NOT
        taken: control falls into the "first caller sets it" half
    mov r10, rsp ; sub r10, BUDGET ; mov [r11], r10
    done: mov r11, rsp ; cmp r11, r10 ; jae ok
      → r10 = SP − 131072 and r11 = SP, so SP ≥ SP − 131072, CF is clear and
        `jae` IS taken: control lands on `ok`, which is the body's first
        instruction

which holds for **every** input and every function, and does not depend on the
memory model at all beyond "a load reads 0". Every instruction of that sequence
is one `x86_step` decodes: the generated proof's own per-instruction
certificates cover `lea_r64_rip`, `mov_r64_rm64`, `alu_rr:test`, `jcc_rel32`,
`mov_r64_r64`, `alu_ri32:sub`, `mov_rm64_r64`, `alu_rr:cmp`, `mov_r64_imm32`
and `call_rel32` for the guard's own bytes, and each certificate is a Lean proof
that `(x86_step s main_code).isSome = true`.

## arm64 does not have this, and the asymmetry is the bug

`formal/arm64_codegen.py:1606` traps the same way and emits a raw syscall:

    movz x0, 2 ; movz x16, 1 ; svc #0x80        # Darwin: x16 = SYS_exit (1)

`svc` is IN the image, `lib/ProofLib.lean` has an `arm64_step` arm for it
(`work_step_svc`), so `extern_calls` stays empty, so arm64 keeps its run tests.
The two backends were made to differ on purpose — x86-64's `_emit_call_exit`
docstring says "the syscall number for exit differs between Darwin and Linux
and the formal x86-64 path emits the same code for both — the binary format,
not the instruction stream, is what differs per platform" — and the cost of
that decision was not visible until something else put an `exit` in EVERY
image.

## Two fixes, either of which restores the coverage

**(A) Make the x86-64 trap an in-image mechanism, the way arm64's is.** Replace
`formal/x86_64_codegen.py:1590` with `mov eax, <exit number>; mov edi, 2;
syscall`, taking the number from `self._target_fmt` (1 on `macho`, 60 on
`elf`), which the backend already carries and which is the portability worry the
current docstring names — so this REMOVES that worry rather than trading it
away. Cost: `lib/X86.lean`'s `0x0f` dispatch has no `syscall` arm, so the trap
becomes an instruction `x86_step` cannot decode (`none`). That is harmless for
the run tests, which never reach it, but `_decode_function_body` will have to
LIST it rather than certify it, so `formal/x86_64_endtoend_test.py`'s
certificate counts move and `test_x86_64_examples.py` is the suite that sees it.
Bigger blast radius; the more honest fix.

**(B) Tell the proof generator which call sites are the compiler's own.**
Publish the trap's address from the emitter (e.g. `"stack_floor_traps": [addr]`
next to `"cond_branches"` in `compile()`'s `info`) and subtract those addresses
from the list `_run_tests_section` refuses on, carrying the §"Why it is a false
negative" argument above as the reason in the guard. Nothing about the image
changes, so nothing else in the tree moves; the cost is that the generator now
has a second input to be right about, and that the unreachability argument above
is prose rather than a decision procedure.

Either way the fix needs the Lean gate, because "the run tests come back" and
"the run tests come back TRUE" are different claims and only Lean tells them
apart.

## Exact next step, for whoever can run Lean

1. Land (A) or (B).
2. `python3 tools/suite.py prooflib` (one build, ~80 s, then the `.olean`).
3. `python3 test_formal_call_proof_gen.py` — `TestStringValueInTheModel::
   test_the_generated_proofs_typecheck_on_both_machines` and `TestEntryArity::
   test_lean_accepts_the_two_parameter_proof_on_both_backends` are the two
   assertions that a restored-but-FALSE run test would turn red, and
   `test_a_returned_string_is_still_run_tested_on_x86_64` is the one that is
   red now.
4. `make check-formal-x86` (`python3 tools/suite.py formal-x86`) for the
   certificate counts, `make check-formal-x86-endtoend`
   (`formal-x86-endtoend`, the 43-proof driver), and `formal-call-proofgen`.

**This branch does NOT carry the fix**, on purpose: it is a light worker with no
Lean budget (`lib/ProofLib.olean` is not built in its worktree, so every Lean
assertion in these files skips), and re-enabling a run test whose truth is
unverified risks a proof of something FALSE — which this project's own rule in
`formal/arm64_proof_gen.py::_expr_go`'s docstring puts above a stated gap.
