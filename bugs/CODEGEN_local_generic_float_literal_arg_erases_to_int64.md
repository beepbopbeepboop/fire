# Local (in-TU) generic call with a float literal argument instantiates as int64_t

**Status:** OPEN. Measured 2026-11-12 while replanning
`bugs/hard/CODEGEN_simd_and_array_values_erase_to_int64-part4.md`.

## What was run

`build_stdlib_dylib.compile_module_to_c` (the same harness the
`test_codegen_*` quick tests use) on

```mojo
def absorb[T](x: T) -> T where T.is_floating_point():
    return x

def f():
    var r = absorb(1.0)
    return r
```

and the identical module WITHOUT the `where` clause, plus the imported-
generic path directly:

```python
import elaborate
elaborate.Elaborator().elaborate_generic_call_inferred(
    'fn f[T: DType](x: T) -> Bool where T.is_floating_point():\n    return True\n',
    'f', ['double'])
```

## What was seen

The LOCAL generic is instantiated with `int64_t` in both cases (with and
without the where clause):

```c
int64_t genprobe_absorb_9f63a2 (int64_t x)   // 9f63a2 = the int64_t hash
...
_t2 = (int64_t)1.0;                           // the literal truncated to an int at the call site
_t1 = genprobe_absorb_9f63a2 (_t2);
```

The import path infers correctly: the same where-clause, fed the C type
`'double'`, instantiates with `Float64` (measured: it generated
`f_1_T_7_Float64.mojo`), and `['float']` with `Float32`; erased spellings
(`'int64_t'`) decline to `None` instead of instantiating. So the asymmetry
is: an imported generic sees the argument's C type; a local (in-TU) generic
call never does — a float literal is truncated to an integer and a
value-wrong instantiation is EMITTED (the caller reads back an int, e.g. `2`
where `2.5` was written), not a conservative stub.

## What was expected

`absorb(1.0)` instantiates with `Float64` (the literal's C type is
`double`), exactly as the imported path does for a `double` argument — or,
if inference cannot answer, the call declines to the nominal stub rather
than emitting the int64_t instantiation.

## Exact next step

In the in-TU pre-pass (`mojo/backend_gimple/elab_intu.py`; local generic
call recordings land in `gen._intu_func_args`, consulted at
`mojo/backend_gimple/emit_resolve.py::_elaborate_generic_call` line ~3067),
find where the call argument's C type is determined and trace the `1.0`
literal through it: it arrives as `int64_t`. The imported path's answer
(`elaborate_generic_call_inferred` over the argument C types) is the shape
to match; a literal argument should contribute its literal C type
(`double` here), not the generic box.
