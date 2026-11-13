# Gate: stdlib-syntax still red on `test/math/test_math.mojo`

**Job:** `stdlib-syntax` (`compile_stdlib.py`, registered in `tools/suite.py`).
**Symptom:** `python3 tools/compile_one.py test/math/test_math.mojo` exits 1:

    RuntimeError: cannot materialize instantiation of generic '_call_amdgcn_intrinsic':
    its type arguments are not concrete, which would cause infinite recursion

## Measured state (2026-11-13)

- The stdlib-syntax files that were red through the string-literal refusal are
  now green: `std/math/math.mojo` (frexp), `std/utils/numerics.mojo`,
  `std/random/_rng.mojo`, `test/builtin/test_simd.mojo`,
  `test/collections/string/test_atof.mojo`, `test/collections/string/test_string.mojo`,
  `test/math/test_ldexp.mojo`, `test/utils/test_numerics.mojo`: each RC 0 through
  `compile_one.py`.
- `test/math/test_math.mojo` is still red (above).
- The regression was introduced by `b3e501b60` ("Refuse mutually recursive and
  unbounded generic instantiation"), which refuses any bracketed call with a
  non-concrete type argument inside an elaborated instantiation. The
  `b0910af726` entry the earlier gate ledger named as first-bad compiles RC 0
  on its own; bisecting `b0910af726^` / `b0910af726` / `b3e501b60` / `b3e501b60^`
  with `compile_one.py std/math/math.mojo` shows the refusal lands at `b3e501b60`.

## Root cause of the remaining red

`std/math/math.mojo:303-306`, inside `rsqrt`:

    elif is_amd_gpu():
        comptime if dtype in (DType.float16, DType.float32, DType.float64):
            return _call_amdgcn_intrinsic[
                String("llvm.amdgcn.rsq.", _get_amdgcn_type_suffix[dtype]())
            ](x)

On a CPU build `is_amd_gpu()` is false, but the `elif` is an ordinary runtime
branch, so the compiler EMITS its body. The bracket argument is a `String(...)`
call the elaborator cannot evaluate to a type or value, so it renders non-concrete
and the `b3e501b60` guard refuses the whole module. The arm is comptime-dead, and
the compiler should not be compiling it at all. (The same "comptime-dead arms are
emitted, not pruned" gap is recorded in
`bugs/mid/CODEGEN_simd_and_array_values_erase_to_int64-part5.md`.)

Before `b3e501b60` the same call was emitted as the `(int64_t)0` stub, which is
harmless only because the arm is dead. The guard is right for in-TU mutual
recursion and wrong for a dead arm.

## Decision needed (one of two)

1. **Prune (recommended).** Fold the target queries (`is_amd_gpu()`,
   `is_nvidia_gpu()`, `is_apple_gpu()`, `is_gpu()`) to `False` on the CPU target
   during elaboration/codegen, so an `if`/`elif` arm whose condition folds to
   False is never lowered. This matches Mojo semantics and removes the dead
   code, so the guard never sees it.
2. **Relax.** Keep emitting, and have the guard stub a non-concrete call whose
   callee is not a generic of this unit (the pre-`b3e501b60` behaviour). Rejected
   as the default: it re-opens the silent-stub hole the guard was added to close,
   and it hides dead code instead of removing it.

## Next step (if option 1)

- Find where the target queries are lowered (`mojo/middle/`, `mojo/backend_gimple/`
  call lowering for `is_*_gpu`; `elaborate.py` mentions `is_amd_gpu` in a comment
  only, so the query is not folded anywhere today).
- Fold them on the CPU target and prune `if`/`elif` arms whose condition folds
  to a constant False, before the arm is lowered.
- Test: `test_gimple.py`, a case with `elif is_amd_gpu(): ... String(...)` in a
  generic body compiles through `stdlib_unit_compiles` (see
  `gate_stdlib_syntax_imported_intrinsic_string_arg`, the helper beside
  `gimple_compiles`), plus `compile_one.py test/math/test_math.mojo` RC 0.
- Then delete this doc in the same commit, and run
  `python3 tools/dangling_doc_refs.py --ratchet`.

## Done when

`python3 tools/compile_one.py test/math/test_math.mojo` exits 0, and the stdlib-syntax
job's eight named files compile (they do now). Delete this doc with that fix.
