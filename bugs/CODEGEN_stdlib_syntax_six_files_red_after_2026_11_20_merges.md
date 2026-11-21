# CODEGEN: stdlib-syntax is red on four files (found 2026-11-20; two fixed)

`python3 tools/suite.py stdlib-syntax` reports `FAILED: 6 (0 expected, 6
unexpected)`, `PASSED: 604`. The six files compiled on the tree before the
2026-11-20 upstream merges. They are NOT caused by the int-or-None return rule:
with `infra_infer._return_arms_are_int_or_none` forced to return False,
`std/math/math.mojo` and `test/builtin/test_sort.mojo` fail identically.

## The two files FIXED by this doc's first commit

    test/builtin/test_sort.mojo  gcc: test_sort.mojo:73:8: error: assignment to
                                 'char *' from incompatible pointer type 'int64_t *'
    test/math/test_tanh.mojo     the same shape at test_tanh.mojo:200:8

Both are the `_small_sort[length](list, _less_than)` call site, where the
implicit List->Span conversion wraps the list's storage in a `Span` header.
`d17488051` ("codegen: project List elements so Span helper calls elaborate")
generalized `_coerce_span_args` and, to satisfy `gcc -fgimple` (which rejects a
component_ref as a memory-store RHS), materialized the two field reads into
temps first -- but dropped the `(char *)` cast the old single-line form had, on
the strength of a comment claiming `MojoList._data` is already `char *`. It is
not: `runtime/fire_runtime.h` types it `int64_t *` (a list stores WORDS), while
the generated `Span` header types `_data` as `char *` (a raw view). So

    _t10 = list->data;          /* int64_t *  */
    _t9->_data = _t10;          /* char * <- int64_t *   <-- error  */

The fix restores the cast and puts it on the TEMP (a cast over a plain SSA name
is the operand form GIMPLE accepts; a cast over a component_ref is not):

    _data = gen._new_temp('int64_t *')
    gen._emit(f"  {_data} = {val}->data;")
    gen._emit(f"  {sp}->_data = (char *) {_data};")

Measured on the doc's own repro path (`compile_module_to_c_cached` then
`compile_stdlib._gcc_syntax_cached`, `GMOJO_HOME` empty so the codegen cache
cannot hide it): `test/builtin/test_sort.mojo` gcc rc=1 -> rc=0.

## The four files still red: a DIFFERENT cause

    std/math/math.mojo           codegen: gcc -c failed for the monomorphized
                                 _ldexp_impl_5_dtype_7_Float32_5_width_1_1 (exit 1, 3 attempts)
    test/math/test_exp.mojo      the same, with ..._Float64_5_width_1_1
    test/math/test_ldexp.mojo    (same family; read its message)
    test/math/test_math.mojo     (same family; read its message)

**Not `d17488051`.** Checked at that commit's parent, as this doc's original
"not bisected" note asked:

    $ git worktree add wt_ld d17488051^     # f19798253
    $ python3 <repro> std/math/math.mojo
    RC False
    codegen: gcc -c failed for the monomorphized
      _ldexp_impl_5_dtype_7_Float32_5_width_1_1 (exit 1, 3 attempts)

So this family is caused by some OTHER commit and needs its own bisect.

**Root cause, from the generated instantiation** (kept by patching
`shutil.rmtree` to a no-op around the run; the file is normally deleted):

    _ldexp_impl_5_dtype_7_Float32_5_width_1_1.c:1071:  float m;
    ...
    _t20 = _t19;   /* int64_t.mantissa_width() stubbed */
    _t21 = _t20;
    _t22 = (float)_t21;
    _t23 = m << _t22;
    _ldexp_impl_...mojo:54:12: error: invalid operands to binary <<
      (have 'float' and 'float')

`std/math/math.mojo:522` is

    comptime integral_type = FPUtils[dtype].integral_type
    var m = exp.cast[integral_type]() + SIMD[integral_type, width](...)
    return x * type_of(x)(from_bits=m << SIMD[integral_type, width](...))

and `FPUtils[dtype].integral_type` is `_integral_type_of[Self.dtype]()`, which
returns `DType.int32` for `float32` (`std/utils/numerics.mojo:54`,
`std/builtin/dtype.mojo:903`). In the monomorphized instance the comptime
member evaluated to `Float32` instead, so `m` was declared `float` and the shift
became `float << float`. `FPUtils.mantissa_width()` is also a weak stub there
(`/* int64_t.mantissa_width() stubbed */`), a second symptom of the same
instance.

## How to reproduce one file in about 20 s

    cat > /tmp/one.py <<'PY'
    import sys
    sys.path.insert(0, '.')
    from pathlib import Path
    import compile_stdlib as C
    base = Path(C.get_stdlib_path())
    for rel in sys.argv[1:]:
        r = C.transpile_file(base / rel)
        print(rel, r[0], str(r[1])[:300])
    PY
    GMOJO_HOME=$(mktemp -d) python3 /tmp/one.py std/math/math.mojo

(`GMOJO_HOME` set to an empty directory matters: the codegen cache can hide a
regression. `transpile_file` truncates its message to 120 chars, so for the
full gcc stderr call `compile_module_to_c_cached` in a try/except instead.)

## Next step

Bisect the four `_ldexp_impl` files on their own (the parent-commit check above
gives the bad side; find the last good commit before it). The defect is in
comptime member evaluation inside a monomorphized generic instance -- a
`comptime` struct member that calls a generic (`FPUtils[Float32].integral_type`
-> `_integral_type_of[Float32]()`) returns the WRONG dtype there. Reproduce
small first: a generic that reads a `comptime` member of a parameterized struct
inside its own monomorphized instance, and check the declared C type of a local
built from it.
