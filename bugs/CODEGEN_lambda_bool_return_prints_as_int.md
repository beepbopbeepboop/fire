# CODEGEN: a lambda whose body is a bool returns int64 0/1, so `print` shows a number

**State: OPEN.** A silent wrong value with exit 0: the program runs, prints a
plausible number, and never says anything is wrong. Found while working
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`; independent of it,
and not touched by it.

## What I ran and what I saw

| program | CPython | compiled |
|---|---|---|
| `e = lambda: False; print(e())` | `False` | `0` |
| `e = lambda x: x > 1; print(e(5)); print(e(0))` | `True` `False` | `1` `0` |
| `def f(): return False; print(f())` | `False` | `False` |
| `print(False)` | `False` | `False` |
| `e = lambda: True; d = {"k": e}; print(d["k"]())` | `True` | `True` |

So it is the LAMBDA, not the boolean, and not the packing: an ordinary `def`
returning the same value is right, and so is the value on its own. It shows up
when the bool crosses a `mojo_fnptr_call_N` — the value is stored in a
`void *` local, called through the arity-based helper, which reports the
generic homogenized `int64_t` return type (that helper's documented
behaviour, shared with every other indirect call).

It is also why the `Lib/doctest.py` corpus occurrence in
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` — `_colorize.
can_colorize = lambda *args, **kwargs: False` — prints `0` rather than
`False` even though its call convention is now correct. That doc's claim that
"the value is right and only the (crashing) call convention is wrong" was
half right: the crash is fixed, the printed value is not.

## Mechanism

`_lower_LambdaExpr` infers the lifted function's return type with
`gen._infer_return_type(syn_body)` and records it in `func_return_types`. For a
`BoolLiteral` (or a comparison) that inference evidently lands on `int64_t`
rather than `_Bool`, so the lifted definition is `int64_t f(...)` and the
`_Bool` is widened on the way out. `mojo_fnptr_call_N` is declared `int64_t`
and is the *right* thing to be: the box it hands back is correct for the
homogenized convention, and the callee is the one that lost the type.

The struct-method path already handles the analogous case — a `MojoBoundMethod`
call records `_bound_method_ret_types[name]` and narrows the result back, and
`sorted(..., key=...)` has a whole comment about coercing a lambda key's
`int64_t` back to `char *` when its body quick-types as one. So the
machinery for this exists; it is simply not applied to a lambda whose inferred
return type is `_Bool`.

## Next step

In `_lower_LambdaExpr`, when the inferred return type is `int64_t` but the
body's own type is `_Bool` (`gen._quick_type(node.body) == '_Bool'`, the same
predicate `_lower_builtin_sorted_keyed` already uses for its `char *` case),
record `_Bool` — either as the lifted function's return type or, matching the
bound-method precedent, as a `_bound_method_ret_types` entry the call site
narrows through. The second is the smaller change and is already wired: the
`MojoBoundMethod`/`mojo_fnptr_call_N` call path reads that map.

Worth checking while in there, because it is the same inference: a lambda
returning a `float`, and one returning a `char *` reached through a local
rather than through `sorted`'s key path.

Not attempted here — it is a different subsystem (lambda return-type
inference) from the variadic call convention, and the gate is owed for both.
