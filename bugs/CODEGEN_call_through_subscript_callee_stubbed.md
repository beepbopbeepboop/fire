# CODEGEN: calling a function value held in a subscript returns 0

**State: OPEN.** A silent wrong value with exit 0 — no diagnostic, and the
program runs to completion. Not part of any claim currently being worked; filed
from the variadic-lambda work because it was found alongside it and has the
same shape (a callable held as a first-class value, reached through a
subscript).

## What I ran and what I saw

CPython prints `5`; the compiled path prints `0`, exit 0, for BOTH a plain
lambda and a variadic one — so it is independent of the variadic work in
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`.

`d['k'](2, 3)` where `d['k']` holds a callable:

    def main():
        d = {}
        d['k'] = lambda a, b: a + b
        print(d['k'](2, 3))

| | CPython | compiled |
|---|---|---|
| plain lambda, `lambda a, b: a + b` | `5` | `0` |
| variadic lambda, `lambda *a: a[0] + a[1]` | `5` | `0` |

The INTERPRETER agrees with CPython here (`python3 fire.py run` prints `5`), so
this is the compiled path alone — which is why it belongs in this repository's
compiled-path bug set and not in `test_interp_oracle.py`.

The same program with the value first read into a local —
`f = d['k']; print(f(2, 3))` — prints `5` in both engines, on both paths.
So the callee is reached correctly once it is a *named* local; it is the
SUBSCRIPT callee that is not resolved.

## Mechanism

`CallExpr.func` here is a `SubscriptExpr`. `_lower_call` in
`mojo/backend_gimple/emit_calls.py` value-lowers its callee for exactly two
shapes — a chained `CallExpr` and a `LambdaExpr` (see its own comment, "ONLY a
CallExpr callee (a genuine chained call) and a LambdaExpr callee (an
immediately-invoked lambda — a real runtime callable value) are value-lowered
here"). A `SubscriptExpr` callee deliberately does NOT take that route: the
comment records that a subscript callee is "a GENERIC TYPE/constructor
expression (`Scalar[x.dtype](...)` — a comptime bracket argument, not a
runtime value), whose eager value-lowering would miscompile (found via
math.mojo's `Scalar[x.dtype](...)`)".

That exemption is right for the *generic bracket* spelling and wrong for a
plain runtime subscript on a dict or list holding a callable — the two are not
distinguishable at the point the check is made, so the safe-looking rule
silently stubs the second.

## Next step

Decide the two are different, and lower the runtime one. The discriminator is
available and cheap: a `SubscriptExpr` whose base is a value of type
`MojoDict *` / `MojoList *` (or an `int64_t` local whose
`gen._actual_types` entry says so) is a runtime value read, while a bare
`Name` base resolving to a generic/bracket type is the `Scalar[x.dtype]`
spelling. Route the first through the same value-lowering the `CallExpr` and
`LambdaExpr` callees already use — `MojoBoundMethod *` to
`_lower_bound_method_call_value`, otherwise `_lower_fnptr_call_value` — which
would also give a variadic lambda held in a dict the same treatment it gets
through a named local.

`d['k'](...)` is a common enough shape (a dispatch table keyed by name) that
it is worth the check; and note that today it is a *silently wrong* answer
rather than a refusal, so any program relying on it is already broken.

Not attempted here: this was found while working
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md` and is a different
defect on a different expression shape. The fix touches the shared
`CallExpr`-callee dispatch in `_lower_call`, which is exactly the machinery
this project's own history warns about changing narrowly.
