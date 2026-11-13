# CODEGEN: an int arm beside an ANNOTATED pointer return is truncated, not refused

Status: OPEN. Filed 2026-11-12 by the `bug-codegen-float-into-pointer-return-an`
lane, which fixed the float-arm half (`_check_float_arm_into_annotated_pointer`
in `mojo/backend_gimple/emit_stmts.py`: a float arm in a `-> String` body is a
compile-time TypeError). The int-arm half was left as it was because
`test_float_into_pointer_return_regression.py::test_int_return_into_the_same_shape_still_compiles`
pins it as compiling.

## What happens

```python
def pick(x: Int) -> String:
    if x == 1:
        return "one"
    return 7
```

Compiles with gcc's pointer-from-integer warning, and the caller receives the
pointer value `7`. `print(pick(0))` then dereferences address 7 instead of
printing `7` (CPython prints `7`).

## Why it is the same class

An annotation fixes the C return type at a pointer, and a non-pointer arm cannot
be returned as one. Same reasoning as the float fix: the annotation is
authoritative, so an int arm should be refused with a diagnostic naming the
function, not coerced into a pointer.

## Exact next step

1. In `mojo/backend_gimple/emit_stmts.py::_check_float_arm_into_annotated_pointer`,
   widen the arm check from `('double', 'float')` to any non-pointer scalar arm
   (`int`, `int64_t`, `_Bool`) when `func_ret_type` ends with ` *`. Check first
   that a `-> String` body returning an int literal from a `None` default or a
   `_Bool` comparison does not hit this in the stdlib (`compile_stdlib.py`
   `skip`/`FAILED` counts must not increase; the integrator runs that gate).
2. Flip `test_int_return_into_the_same_shape_still_compiles` to the refusal
   assertion, same shape as the float test.
