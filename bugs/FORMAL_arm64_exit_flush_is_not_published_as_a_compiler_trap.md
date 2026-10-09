# FORMAL/arm64: `_emit_exit`'s `BL fflush` is not published as a compiler trap, so it reads as a program call

**Area:** FORMAL, arm64 proof layer — `formal/arm64_codegen.py::_emit_exit` and
`formal/arm64_proof_gen.py::_program_extern_calls`. **Status: OPEN.** Found while
landing the stack-floor `getrlimit` fix (`work/formal245-docs`); split out
because the fix is independent of where the guard's read is emitted.

## What was measured

`test_formal_call_proof_gen.py` on this tree:

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 -m unittest test_formal_call_proof_gen.TestCompilerTrapIsNotAProgramCall
FAIL: test_a_program_whose_only_unbound_call_is_a_trap_gets_its_run_test
FAIL: test_a_recorded_trap_is_the_bl_and_not_the_instruction_before_it
FAIL: test_arm64_publishes_its_exit_flush_as_a_compiler_trap
```

`info["compiler_traps"]` is `[]` for every arm64 image, so
`_program_extern_calls` subtracts nothing and the `BL fflush` inside each
bounded stop is counted as a call the PROGRAM makes.

## Why

`formal/arm64_codegen.py::_emit_exit` calls
`self._emit_call(F.CallExpr(func=F.IdentExpr(name="fflush"), …))` directly;
nothing adds its address to `self._compiler_trap_addrs`. The arm64 half of
commit `38880520` — a `_emit_trap_flush` that does the same call AND records the
address the assembler actually appended to `asm.extern_refs` (not the position
before the call, which is short by the `mov w0, #0`) — was dropped by a merge.
The x86-64 half and the proof-generator half survived, which is why
`_program_extern_calls`'s subtraction exists and does nothing on arm64.

**The fix is small**: restore `_emit_trap_flush` (the historical body is
`git show 38880520:formal/arm64_codegen.py`) and have `_emit_exit` call it.

## Why it was not landed with the getrlimit fix

Restoring the trap makes `modvar` (`def modvar(n): d = 4; return n % d`) have
**no program extern call at all** — its only unbound call, the divide-by-zero
guard's `fflush`, becomes a compiler trap and is subtracted. That is correct
(`TestCompilerTrapIsNotAProgramCall` is the other half and demands exactly
this), but `test_formal_call_proof_gen.py::TestExternCallTheRunDoesNotReach`
uses that same `fflush` as its "an extern call the concrete run never reaches"
probe, and with the trap subtracted it no longer reaches `_gen_extern_test` at
all: its `setUpClass` then has nothing to set up and four rows fall over. The
two classes are in direct tension over one call.

Resolving it needs a probe that is a genuinely-untaken **program** extern call
that does not trip the generator's "the halt address is behind a CONDITIONAL"
refusal (`printf` behind a source `if` is refused), which is the same capability
gap `bugs/FORMAL_arm64_the_walk_cannot_discharge_a_call_on_a_conditional_path.md`
records. Until then, `TestExternCallTheRunDoesNotReach` can only pass with the
trap UNrecorded and `TestCompilerTrapIsNotAProgramCall` only with it recorded.

## Next step

1. Decide the resolution (the trap is correct, so the probe class should move —
   e.g. use an untaken call the generator's CFG treats as emitter-internal, or
   relax that refusal once the conditional-call gap is closed).
2. Land `_emit_trap_flush`, then make both classes green.
3. `test_formal_call_proof_gen.py::TestCompilerTrapIsNotAProgramCall` is the pin;
   `formal/examples/mod_by_var.mojo` regenerating with an ordinary
   `run_result_exit … = mojo 10` run test is the corpus anti-rot.
