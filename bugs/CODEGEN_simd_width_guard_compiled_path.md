# SIMD bad-width validation only guards the interpreter; the compiled path still accepts it

## Symptom

`SIMD[DType.float32, N]` with an invalid lane count (`0`, `-1`, `3`, or
`> 2**15`) is accepted by the compiled path. `python3 fire.py <file>` builds and
runs the program and prints a value; Mojo rejects it with

    error: SIMD vector length must be a power of two between 1 and 2^15, found '!kgen.simd<3, f32>'

The interpreter guard landed for `GPU_offload_validation_modular` part 4
(`_mojo_simd_width_is_valid`, `myinterpreter.py:3835`, commit 5594d2541) is only
consulted by `python3 fire.py run`. The gimple/compiled codegen never calls it,
so the guard does not cover the mode the canonical Modular test runs in
(`not %mojo %s`, i.e. compile and run).

## What I ran

From this worktree, with `SIMD[DType.float32, 3](1.0)`:

    python3 tools/memslot.py --gb 8 --label probe-simd3 -- python3 fire.py .tmp/simd3.mojo

prints `1.0` and exits 0 (the program reached the runtime and printed a
value), where the expected result is a compile-time diagnostic and a non-zero
exit.

The canonical source `modular/mojo/test/mojo-integration/simd_bad_size_lowering.mojo`
(`SIMD[.float32, 0|-1|3]`) under the same command prints `0.0` three times and
exits 0. Under `python3 fire.py run` it stops earlier, at the dot-relative
`.float32` (the interpreter's `eval_DottedLiteral`, `myinterpreter.py:7449`,
raises `cannot resolve the dot-relative value '.float32'`), so the compiled
path is the mode that must be guarded to satisfy that test.

Part 4's test (`test_regress_gpu_offload_validation_modular_part4.py`) uses
`fire.py run` and a rewritten `DType.float32` source, which is why it is green
while this gap is open.

## Root cause / exact next step

The compiled path resolves/constructs the SIMD type outside
`myinterpreter.py` (the `SIMD` bracket and dtype dispatch live in
`fire_compiler.py` / `gimple_codegen.py` / `mojo/middle/types.py`). Add the same
power-of-two/range check where the compiled path builds a `SIMD[dtype, width]`
type from a concrete integer width, before lowering, and report

    error: SIMD vector length must be a power of two between 1 and 2^15, found '!kgen.simd<N, dtype>'

naming the lowered type (the canonical FileCheck matches the `!kgen.simd<...>`
shape, not the raw integer that the interpreter message uses). Keep the
interpreter guard as the cheap backstop for `fire.py run`; do not delete it.

## Done when

Extend `test_regress_gpu_offload_validation_modular_part4.py` with a
build-mode case: write `SIMD[DType.float32, 3](1.0)`, run
`python3 fire.py <file>` under `tools/memslot.py --gb 8`, and require a
non-zero exit plus `SIMD vector length must be a power of two` in the output.
That test is red today (`1.0`, exit 0) and must pass.
