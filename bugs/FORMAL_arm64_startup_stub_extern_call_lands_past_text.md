# arm64: an extern call emitted from the startup stub lands its `bl` past the end of `__TEXT`

## What I ran

    export PATH=/opt/homebrew/bin:$PATH
    python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/rec/ah .tmp/rec/hello.mojo
    .tmp/rec/ah

on `work/formal33-recursion-stack`, with the x86-64 half of this task landed and
arm64's guard rewritten to read `RLIMIT_STACK` once in the startup stub
(`ARM64Codegen::_emit_stack_floor_init`, called from `compile`'s `emit_startup`
branch before the frame push).

## What I saw

`hello.mojo` is three lines with no recursion:

    def main():
        printf("hi")
        return 0

It does not exit. Redirected to a file it wrote **187 MB of "hi"** in three
seconds and was still running when killed. `otool -tV` on the image:

    00000001000003e4   bl  0x10000082c     # getrlimit
    00000001000004c4   bl  0x100000838     # printf
    ...
    0000000100000828   .long 0x6d006968    # end of __TEXT,__text

Both `bl` targets are **past the end of the emitted section** (0x828). The
`__TEXT,__stubs` region is sized before the startup stub is emitted, so an
extern call made from the stub has nowhere to put its trampoline and the branch
lands in whatever follows.

The same program built from `HEAD~1` (`git show HEAD~1:formal/arm64_codegen.py`)
has one `bl` and runs correctly, which is what makes this a regression in the
startup-stub placement rather than a pre-existing one.

## Why it matters beyond this one program

This blocks the arm64 half of the recursion/stack task, and it blocks it for a
reason that is not a choice:

- **arm64 cannot keep `getrlimit` in the guard's prologue.** A `call` to a
  `__TEXT,__stubs` trampoline is exactly what `formal/arm64_proof_gen.py`
  refuses run tests over, and those tests are the one part of a proof that is
  evidence about the machine rather than about the model. Measured: with the
  call in the prologue, `test_formal_call_proof_gen.py` goes from 21 failures
  (at `HEAD~1`) to 42 failures and 15 errors, and
  `TestCompilerTrapIsNotAProgramCall::test_arm64_needs_no_trap_list_and_keeps_its_run_tests`
  fails with `['getrlimit'] != []` — an arm64 image is supposed to carry no
  extern call at all, because its trap is an `svc`.
- **So the read has to move to the startup stub**, which is the only place a
  `call` can live that no proof layer walks. That is exactly what x86-64 does
  (`x86_64_codegen.py::_emit_stack_floor_init`) and it works there.

Until this is fixed, arm64 keeps a **compile-time** stack budget. A budget larger
than the process's real stack never fires, so arm64 SIGSEGVs (exit 139) under a
reduced `ulimit -s` where x86-64 refuses with exit 2. Measured, at
`ulimit -s 2048`, both depths:

| depth | x86-64 | arm64 |
|---|---|---|
| 100 | prints 100, exit 0 | SIGSEGV (139) |
| 5000 | message on stderr, exit 2 | SIGSEGV (139) |

Those two rows are the `reduced_stack_*` cases in `test_formal_run.py`, and they
are declared DEFERRED for arm64 in `_REDUCED_STACK_DEFERRED` with this doc as the
reason — reported on screen, counted in neither PASS nor FAIL.

## Expected

`hello` prints `hi` and exits 0 on arm64, as it does at `HEAD~1` and as x86-64
does now.

## Next step

Size the `__TEXT,__stubs` region for the externs the startup stub adds, or emit
the stub section after the last function body rather than before it. The thing to
look at is where the stub layout is computed in `formal/arm64.py`'s assembler and
in `formal/arm64_codegen.py::compile`: `asm.extern_refs` is what
`externer_layout` consumes, and the startup stub currently contributes to it
after the layout has been fixed. Either emit the startup stub after the layout is
computed, or reserve for the externs it will add before computing it.

Then flip `_REDUCED_STACK_DEFERRED` to `{}` — the rows are already written and
already fail for the right reason.

A second, smaller thing found on the way and **fixed on this branch**, recorded
here because the same trap will catch the next person: arm64's budget clamp was a
`CSEL`, and `arm64_step` has no `csel` arm, so it refused proof generation for
every program in the corpus. It is two branches now
(`formal/arm64_codegen.py::_emit_stack_floor_guard`), and `test_formal_call_proof_gen.py`
goes from 42 failures + 15 errors to 22 + 3. x86-64 had the same problem with
`cmov` and the same fix.
