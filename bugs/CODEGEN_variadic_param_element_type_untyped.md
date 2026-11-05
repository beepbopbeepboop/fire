# CODEGEN: a `*parts: T` variadic parameter's elements are typed `int64_t`, so a struct `/=` element is raw arithmetic

Found 2026-10-30 while fixing the gate break in `CODEGEN_int_true_division_truncates.md`.

## Repro

```mojo
struct P:
    var s: String
    def __init__(out self, s: String):
        self.s = s
    def __truediv__(self, suffix: StringSlice) -> Self:
        return P(self.s + "/" + String(suffix))
    def __itruediv__(mut self, suffix: StringSlice):
        self.s = self.s + "/" + String(suffix)
    def joinpath(self, *parts: StringSlice) -> P:
        var result = self
        for i in range(len(parts)):
            result /= parts[i]
        return result

def main():
    var p = P("a")
    print(len(p.joinpath("b", "c").s) > 0)
```

- Expected: `True`, built and run.
- Observed: builds (gcc accepts it), then `JIT execution failed with code -11`
  (segfault) at run time.
- The `/=` in `joinpath` is the same statement as `std/pathlib/path.mojo:558`
  (`result /= pathsegments[i]`), which is why that stdlib file is affected.

## What the generated C shows

`P_joinpath`'s element read is `mojo_list_get_int (pathsegments, i)`, so
`_t9` is `int64_t`. `result` is `P *`. The AugAssign builds a fake
`BinaryOp('/', result, parts[i])`, and the operand types it sees are
`lt='P *'`, `rt='int64_t'`. The struct `/` never dispatches to
`__itruediv__`/`__truediv__` because the overload selector sees an `int64_t`
right-hand side, which matches neither `Self` nor `StringSlice`. It falls
through to raw integer arithmetic on the pointer:

    _t10 = (int64_t)result;
    _t12 = _t10 / _t11;         /* mojo_int_divisor */
    result = (P *)_t12;         /* an integer stored into a pointer */

## Root cause

The element type of a variadic parameter is never seeded. In
`mojo/backend_gimple/emit_funcs.py` (`gen_func`, the param element-type seed
loop around line 2823) the loop skips every `pname.startswith('*')`, and the
call-site evidence in `module_gen.py` (`_record_param_elem`) does not record
the packed element type for a variadic either. `len(parts)` and `parts[i]`
therefore use the generic `int64_t` element.

## Next step

1. Seed a variadic parameter's element type from its annotation:
   `*parts: StringSlice` gives `_elem_types['parts'] = 'char *'`, which is the
   same contract a `list[StringSlice]` parameter already gets. The loop in
   `gen_func` currently drops the star. First check what `node.params` holds
   for a variadic (the `*` may be in the name or the annotation; the
   `*`-branch of `mojo/middle/infra_infer.py`'s type mapping handles an
   annotation starting with `*`), then seed from that.
2. Check `parts[i]`'s read then types as `char *`, so the `/=` dispatches to
   `__itruediv__` on the struct.
3. Test: the repro above must print `True` (add it as a run test next to
   `test_struct_true_division_builds` in `test_codegen_int_div_zero.py`, or a
   `test_variadic_*` file), and `compile_stdlib.py --module pathlib` must keep
   `std/pathlib/path.mojo` passing.
4. Then the `(int64_t)result` lowering of a struct `/` with an unknown operand
   is still reachable; decide whether an unknown-typed operand should refuse
   rather than fall to integer arithmetic on the pointer.
