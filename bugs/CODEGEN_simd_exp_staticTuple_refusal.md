# CODEGEN_simd_exp_staticTuple_refusal: stdlib `std/simd.mojo` elaboration refused as "advance without converging"

**Class:** mid
**Found:** 2026-11-13 on master `4c746595b`, reproduced from `compile_stdlib.py`.

## Symptom

`compile_stdlib.py` prints, for `std/simd.mojo`:

    CAUGHT_IN_MAIN_LOOP: cannot materialize instantiation of generic 'StaticTuple': its bracket arguments
    [compile_module_to_c_cached] .../std/simd.mojo: 2 generic struct elaboration(s) failed,
      so this module's C is NOT the program its source describes and it is NOT being cached:
        SIMD[exp.dtype, self.length] from .../std/simd.mojo: RuntimeError: cannot materialize
        instantiation of generic 'StaticTuple': its bracket arguments advance without converging,
        which would cause infinite recursion

The run still ends `610 passed, 0 failed`. See `CODEGEN_stdlib_failed_elaboration_counted_as_pass.md`
for why that count is wrong.

## Reproduction

    python3 compile_stdlib.py 2>&1 | grep -n 'advance without converging'

Stdlib root used by the run: `/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib`.
Same two lines appear on a second checkout's run (user's laptop, same stdlib root).

## Where the refusal comes from

- `mojo/backend_gimple/emit_calls.py` (~line 3787): the "elaborated-instantiation" refusal
  raises when a generic is called with a bracket argument that `_progressing_bracket_arg`
  classifies as a progressing index (`i + 1` shape), and the callee is not a struct
  constructor.
- The guard landed in `a38ecb8d4` (2026-11-13) ("the elaborated-instantiation refusal asks
  about a progressing arg"), following `45e8d6280`.

## Why it is a bug

`SIMD[exp.dtype, self.length]` is not recursion. It is a struct instantiation with a plain
parameter (`self.length`, an attribute of the enclosing SIMD) inside SIMD's own `exp` method.
Nothing advances. The refusal treats it as an unbounded `a[i+1] -> b[i+1] -> ...` chain and
refuses the whole module.

## Unverified hypothesis (to check, not assumed)

The classifier may be seeing `self.length` (or the `exp.dtype` argument) as a progressing
operand because the attribute-chain is lowered to a BinaryOp or a sub-expression that
`_progressing_bracket_arg` does not recognise as a fixed value. Next step: dump the
`_progressing_bracket_arg` result for each bracket element at this call site, and confirm which
element trips it.

## Acceptance

- `compile_stdlib.py` prints no `advance without converging` line for `std/simd.mojo`.
- `std/simd.mojo` is cached (no "NOT being cached" line).
- The refusal still fires on a genuine progressing case (`a[i + 1]` -> `b[i + 1]` -> ...); add
  or keep a test for it so the fix cannot remove the guard entirely.
- Stdlib `skip` count does not increase; `U` stays 0.
