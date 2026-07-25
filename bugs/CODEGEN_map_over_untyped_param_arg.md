# CODEGEN: `map(str, x)` over a list-typed parameter compiles to wrong C

## Status
**Fixed** (2026-07-25, commit e387af9). Three root causes in
`gimple_codegen.py`: `_infer_param_types` didn't treat `map(fn, param)` as
evidence `param` is pointer-shaped; `mojo_map`/`mojo_filter` had no
`_KNOWN_SIGS` entry so their pointer return value was assigned to an
`int64_t` temp; and `_lower_str_method` called `self.lower_expr(a)` twice
per argument, silently duplicating codegen for `map(str, args)`. Also fixed
`shlex.join(iterable)` falling through to the generic `char*.join()` path
(added `mojo_shlex_join` to the runtime). See `test_gimple.py`'s
`map_over_untyped_param_arg` case.

## Repro

```python
import shlex

def join_command(args):
    return shlex.join(map(str, args))

print(join_command(["a", "b", "c"]))
```

- `python3 mojo.py run /tmp/mrepro.py` (interpreter): prints `a b c`, correct.
- `python3 mojo.py build /tmp/mrepro.py -o /tmp/mrepro_out`: fails to compile:

```
/tmp/mrepro.py:4:24: error: passing argument 2 of 'mojo_map' makes pointer from integer without a cast [-Wint-conversion]
/tmp/mrepro.py:4:7: error: assignment to 'int64_t' {aka 'long long int'} from 'void *' makes integer from pointer without a cast [-Wint-conversion]
```
(each error appears twice)

This is a real, reproducing bug (not stale) as of 2026-07-25, found while
investigating `bugs/COMPILE_FAIL_Android_android.py` and several other
now-stale `COMPILE_FAIL_*` reports whose original "-g3 not supported"
symptom was a red herring — the actual, still-live failure underneath is
this `map()`-over-a-plain-parameter codegen bug (`Android/android.py`'s
`join_command` has the identical shape: `shlex.join(map(str, args))` where
`args` is an untyped/unannotated parameter).

## What the generated C looks like (mrepro.ci)

```c
char * join_command_0c85c9 (int64_t args)   // BUG 1: args should be MojoList* (or a generic pointer), not int64_t
{
  ...
  int64_t _t5;
  ...
  _t4 = _funcptr_mojo_str;
  _t5 = mojo_map (_t4, args);   // BUG 2: result of mojo_map (a pointer-returning runtime fn) assigned to an int64_t temp
  _t6 = _funcptr_mojo_str;
  _t7 = mojo_map (_t6, args);   // BUG 3: the same map(str, args) sub-expression is lowered/emitted TWICE
  ...
}
```

Three distinct issues visible in the lowering of a single `shlex.join(map(str, args))` expression:

1. **Parameter type inference**: `args` is only ever used as the iterable
   argument to `map()` inside the function body, but its C parameter type
   comes out as `int64_t` instead of a pointer type (e.g. `MojoList *` or
   `void *`). Whatever type-inference pass gimple_codegen.py runs to pick
   parameter types isn't propagating "used as a map()/iterable argument"
   into a pointer-shaped type the way it presumably does for other
   list-consuming builtins.
2. **`mojo_map`'s return type**: the temp (`_t5`/`_t7`) holding the result
   of `mojo_map(...)` is declared `int64_t`, but `mojo_map` is a
   pointer-returning runtime helper (per the `-Wint-conversion` diagnostic
   on the assignment) — the temp should be a pointer type.
3. **Duplicate lowering**: the exact same `map(str, args)` call sub-expression
   is emitted twice (`_t5` then `_t7`), once for each occurrence needed by
   whatever downstream consumes it (likely `shlex.join`'s two-argument
   dispatch, or a repeated codegen visit of the same AST node) — even if
   bugs 1/2 are fixed, this duplication is wasteful and worth understanding/
   fixing since it suggests the same subexpression's code is being generated
   more than once instead of reused via a temp.

## Where to look

`gimple_codegen.py`: the lowering for `map()` calls (`_lower_...` for
`CallExpr` where `func` is `map`), the parameter-type inference pass (walks
function bodies to decide C parameter types for untyped/unannotated
parameters), and whatever emits `mojo_map` calls / declares its return type.
Also check `runtime/mojo_runtime.h` or wherever `mojo_map` is declared, to
confirm its real signature/return type that the codegen should be matching.

## Suggested fix approach

Not yet planned — first understand why the parameter-type inference walk
doesn't recognize `map(fn, param)` as a pointer-typed use of `param` (compare
against however similar builtins like `list()`, `sorted()`, `len()` already
influence parameter type inference, since those presumably already work),
then fix the mismatched `mojo_map` return-type declaration, then investigate
the duplicate-emission before deciding whether it self-resolves once 1/2 are
fixed or needs a separate dedup fix.
