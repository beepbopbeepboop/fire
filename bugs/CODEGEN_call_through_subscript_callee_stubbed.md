# CODEGEN: calling a function value held in a subscript returns 0

**State: PARTIALLY FIXED (2026-10-01). The dict case this doc was filed for
works, and one further gap in it is now fixed; two shapes are still open and
are measured below.** Not part of any claim currently being worked; filed from
the variadic-lambda work because it was found alongside it and has the same
shape (a callable held as a first-class value, reached through a subscript).

## Status (2026-10-01) — what is closed and what is not

**Closed before this session, by `9d40b1b6`** ("CODEGEN: calling a function
value held in a subscript was stubbed to 0"). That commit added the positive
discriminator `_lower_call` consults — a container recorded in
`gen._dict_callable_ret` as holding a callable — and left this doc in place,
so the doc read as open while its own repro was green. Re-measured today, all
of these print CPython's answer:

| shape | before `9d40b1b6` | today |
|---|---|---|
| `d['k'] = lambda a, b: a + b` → `d['k'](2, 3)` | `0` | `5` |
| `d['k'] = lambda *a: ...` → `d['k'](2, 3)` | `0` | `5` |
| `d['k'] = add3` (a lifted free function) | `0` | `6` |
| `d['k'] = lambda x: x + n` (CAPTURING lambda) | `0` | `11` |

**Closed in this session: a `MojoBoundMethod *` stored into a dict.**
`note_dict_callable_ret` (emit_infra.py) recorded only
`gen._callable_ret_types`, which is where a *bare function pointer* — a
non-capturing closure or a lifted free function — lands. A struct method bound
as a value (`C().m`) and a CAPTURING lambda both materialize as a
`MojoBoundMethod *` and are recorded in `gen._bound_method_ret_types`, which
nothing consulted, so:

```python
dd = {}
dd['m'] = C().m
print(dd['m'](4))        # CPython 8    ->  compiled 0, exit 0
f = dd['m']
print(f(4))               # CPython 8    ->  compiled 8   (the control)
```

The value in the dict was a perfectly good bound method all along —
`mojo_fnptr_call_1` dispatches it, which is exactly what the working
named-local spelling emits — so what was missing was an ENTRY, not a
mechanism. It reproduced **only when the bound method was the dict's first
callable store**: one lambda stored first puts the container in the table and
the bound method then rides in on that entry. That is why this doc's own repro
looked already-fixed. `note_dict_callable_ret` now consults both tables, plus
`value_ctype == 'MojoBoundMethod *'` for a value whose construction temp is in
neither (see the residual below). Regression:
`test_gimple_runner.py`'s `gimple_dict_held_bound_method_through_subscript`,
which pins the bound-method-first case and the lambda-first case side by side
because the two differ only in what is stored first.

**Still open, measured today (all exit 0, all silently wrong):**

| shape | CPython | compiled | why |
|---|---|---|---|
| `lst = [add3]; lst[0](1, 2, 3)` | `6` | `0` | the list is never recorded, so the gate fails |
| `def mk(n): return lambda x: x + n` … `e['c'] = mk(100); e['c'](1)` | `101` | `0` | see below |
| `a[i]['k'](...)`, `self.d['k'](...)` | — | stub | documented as deliberately out of reach |

The `mk(100)` case is NOT a missing table entry and cannot be fixed by adding
one: `func_return_types` records `mk` as returning `int64_t`, not
`MojoBoundMethod *` (measured), and nothing at the store site can tell a
callable result from a plain integer — `gen._actual_types`, `gen.var_types`,
`_callable_ret_types` and `_bound_method_ret_types` are all silent for that
temp. It works only when something ELSE already put the container in the table.
The root cause is upstream: a function whose body returns a closure has no
callable return type, so its result is an ordinary `int64_t` everywhere.

## Still-open next step

The list case is the one worth doing next, and it is the same mechanism
rather than a second one: `_lower_list_literal`'s per-element append loop is a
single chokepoint, and the table is already keyed by the container's lowered
name, so recording list literals is one call. It needs the table RENAMED
(`_dict_callable_ret` → something container-neutral) to stay honest, which is
~20 mechanical sites across `emit_calls.py`, `emit_exprs.py`, `emit_infra.py`,
`emit_resolve.py`, `emit_stmts.py` and `gimple_codegen.py` — and `gimple_codegen.py`
is compiled by the self-hosting bootstrap, so both sides change together.
Decide first whether to cover `append`/comprehension-built lists too or only
literals: the gate is a POSITIVE test, so partial coverage is never wrong, but
a list built by `append` would still be stubbed.

The `mk(100)` case is a return-type inference change (a function returning a
closure should have a callable return type), which is its own piece of work.

## Original report (2026-09-30) follows

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
