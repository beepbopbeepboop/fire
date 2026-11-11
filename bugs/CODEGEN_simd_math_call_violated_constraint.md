# CODEGEN_simd_math_call_violated_constraint

## Summary
On master, six stdlib files fail to compile with `invalid call to '<fn>': violated constraint`, and they are
the only UNEXPECTED failures in `stdlib-syntax` and `stdlib-dylib`. The failing calls are math functions on SIMD
vector arguments:
- `std/random/philox.mojo:300` `sqrt(log(u) * Float32(-2.0))` (`log`)
- `test/math/test_erf.mojo:23` `erf(SIMD[.float32, 2](2))` (`erf`)
- `test/math/test_exp.mojo:110` (`exp`)
- `test/math/test_ldexp.mojo:28` `ldexp(SIMD[.float32, 4](1.5), SIMD[.int32, 4](4))` (`ldexp`)
- `test/math/test_math.mojo:626` (`log1p`)
- `test/math/test_tanh.mojo:49` (`tanh`)

The compiler's text stops at "violated constraint", so the constraint itself is not shown. Reading the
callers, the common shape is a SIMD argument.

## Evidence
- Identical six failures on the merged round-31 tree and on master (`stdlib-syntax`: `FAILED: 6 (0 expected, 6 unexpected)`
  on both). The red is pre-existing on master.
- The orchestrator blamed round 31 for it (see `ORCHESTRATION_red_gate_blames_branch_for_preexisting_red`).

## Repro
`python3 tools/suite.py stdlib-syntax` on master (about 25 s, 2.1 GB), or compile `test/math/test_erf.mojo` alone.

## Status
Open. Not started. First step: read the full diagnostic (the compiler truncates it) and find which constraint on
the generic math function is not satisfied by a SIMD argument.

## Done when
`python3 tools/suite.py stdlib-syntax` reports `FAILED: 0`, OR these six move to `EXPECTED_FAILURES` in
`compile_stdlib.py` with a comment saying why. Then delete this doc in the same commit.
