# CODEGEN: a callable-valued parameter called inside an ORDINARY compiled generator returns garbage, silently

`def f(x, _g=<a function>)` with `_g` **called** in a generator body compiles
clean, links, exits 0, and produces **nothing** — the call yields an
`int64_t` that is then reinterpreted as a container pointer, so the loop it
feeds iterates a garbage object.

Distinct from `bugs/CODEGEN_unresolved_imported_callable_default_null_pointer.md`,
which is about the **padding** site (what symbol gets passed for a callable
default). This is about the **call** site inside a body the ordinary GIMPLE
generator path lowered, and it is reached by a default that this compile CAN
resolve — so that doc's fix does not cover it and its repro does not hit it.

## Repro (measured, exit 0)

```python
def upper(s):
    return s.upper()

def apply_to(items, _f=upper):
    for it in _f(items):
        yield it

def go():
    for v in apply_to('ab'):
        print(v)

go()
```

```
$ python3 repro.py
A
B
$ ./repro            # compiled, arm64, gcc -fgimple + the coro runtime
$ echo $?
0                    # ...and prints NOTHING
```

Measured on `6b9b6b18` with the tree reverted to it (this is not caused by
any change in flight).

## What the generated C does

`apply_to` is lowered by the ORDINARY GIMPLE generator path (A3,
`__mgco_apply_to_body`), not by the C++20-coroutine emitter. Its parameter
`_f` is typed `int64_t`, so:

```c
void __mgco_apply_to_body (int64_t __c)
{
  ...
  _t6 = <the call through _f>;          /* returns the CALLEE's real value,
                                          an unboxed char* / MojoList* */
  _t11 = (int64_t)_t6;                  /* ...boxed to int64_t */
  _t10 = (MojoDict *)_t11;              /* ...and read back as a DICT */
  _t12 = mojo_dict_iter_new (_t10);     /* ...then iterated */
```

A `char *` (the string `'ab'` from `upper`) is read as a `MojoDict *` and
handed to `mojo_dict_iter_new`. No diagnostic, exit 0, no output.

## Why this is the ordinary path's gap and not the coroutine one's

There are two generator emitters and they disagree about callable-valued
parameters:

* the **C++20 coroutine** path has a first-class callable type
  (`_CPP_CALLABLE_CTYPE` / `_CPP_CALLABLE_CTYPE_1ARG`, the `std::function`
  category) that `_cpp_expr`'s LambdaExpr and method-as-value cases
  produce and its bare-name CallExpr case already dispatches on, so it both
  stores and calls a callable value;
* the **ordinary GIMPLE** path (`__mgco_*_body`) types the same parameter
  `int64_t` via the shared `_param_ctype`, which has no callable category,
  and `_lower_call`'s indirect-call branch then boxes the callee's real
  return value into `int64_t` with nothing recording that it was a pointer.

A lambda assigned to a LOCAL inside the body (`g = lambda: None`) works on
the ordinary path — `_callable_ret_types` and the `_funcptr_` machinery
cover it. Only the *parameter* spelling falls through, because nothing
types the parameter.

## Next step

The ordinary path needs a callable category too. Two separable pieces, and
the order matters:

1. **Type the parameter.** `_param_ctype`
   (`mojo/middle/funcs_shared.py`) is shared by both emitters, so the change
   cannot live there unconditionally — the ordinary path would then put a
   `std::function` in a plain C signature whose call sites would all have to
   construct one. Either give the ordinary path its own callable
   representation (e.g. `void *` plus a registered kind, matching
   `mojo_is_bound_method` / `mojo_is_vararg_fn`'s existing pointer-registry
   idiom in `runtime/fire_runtime.c`), or carry the parameter's callable-ness
   as side-table metadata the way `_callable_ret_types` /
   `_callable_param_gen_api` already do.
2. **Call through it.** `emit_calls._lower_fnptr_call_value` already emits
   `mojo_fnptr_call_N`, which handles varargs and bound methods but returns
   `int64_t`; a `char *` / `MojoList *` return from such a callee needs the
   `_d`-twin treatment the `double` case already gets, keyed on the callee's
   declared return type.

Note the interaction with
`bugs/CODEGEN_next_generator_value_truncated_in_return_position.md`: that
one is the *same class* one level up — a value of a non-`int64_t` kind
travelling through an `int64_t` slot in a compiled generator context. Both
are the "this scalar body model has no way to say what KIND of thing this
is" problem, in different positions.

## Regression test

Must assert on the built binary's **stdout against CPython**, not on a
successful compile — this bug compiles, links and exits 0. A fixture whose
callable default is a plain module-level function of this same file is
enough; `csv.reader`-style imported defaults hit the padding doc instead.