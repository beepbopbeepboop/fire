# A `*expr` spread in a LIST or TUPLE display SIGSEGVs; a `*args` call collects one tuple

## Status: OPEN, filed 2026-10-03 on `work/merge-bugs3-r4` while fixing the
## `**`-spread sibling in dict literals
## (`bugs/` has no doc for it yet; that one is fixed and had none).

## What I ran

Each compiled with `test_gimple_runner.py`'s own
`compile_mojo_to_gimple_exe`, run, and compared with CPython on the same text.
One program per run, because the runner spawns a `gcc -fgimple` per case and
running several in one process made the harness itself fall over.

## What I saw

    # list_spread
    def f(a: list) -> list:
        return [0, *a, 9]
    print(f([1, 2]))
    compiled rc=-11 (SIGSEGV)   cpython: [0, 1, 2, 9]

    # tuple_spread
    def f(a: list) -> tuple:
        return (0, *a)
    print(f([1, 2]))
    compiled rc=-11 (SIGSEGV)   cpython: (0, 1, 2)

    # call_star_args
    def g(*a, **k):
        return sorted(a), sorted(k.items())
    print(g(1, 2, x=3))
    compiled rc=0 out="((1, 2), [('x', 3)])"   cpython: "([1, 2], [('x', 3)])"

Three shapes, and the third is the informative one: `g(1, 2, x=3)` bound `a`
to `((1, 2),)` — the compiler collected the loose arguments into ONE tuple
and put THAT tuple in the varargs list — so `sorted(a)` sorted a one-element
list and printed the tuple inside it. `**kwargs` is correct in all three, so
this is the `*` side alone.

The interpreter has all three right: `myinterpreter.py`'s
`eval_ListLiteral` / `eval_TupleLiteral` both call
`_spread_operand(e, "*")` and `extend`/`result.extend`. The parser's
convention is the same one the `**` case uses — a `UnaryOp(op='*',
operand=<iterable>)` element in the literal's `elements` — and
`eval_SetLiteral` has the identical `update` shape.

## Why it matters more than a segfault on a test program

A SIGSEGV at exit -11 with no output is the worst failure shape this codebase
has: `test_gimple_runner.py`'s cases are the only thing standing between a
`[*a]` in real source and a crashed artifact, and a list/tuple display with a
spread is ordinary Python (`[*items]`, `(head, *rest)`).

## Exact next step

The sibling that was just fixed gives the shape. `_lower_dict_literal` now
asks `_dict_literal_spread_operand(key_expr)` and merges with
`mojo_dict_update`; the three sites to mirror it are

1. the list-display lowering (`_lower_list_literal` / `_emit_container_new`'s
   list caller in `mojo/backend_gimple/emit_exprs.py`) — merge with
   `mojo_list_extend(res, spread)`,
2. the tuple-display lowering, same helper, and
3. the CALL path — `_lower_named_call`'s / `_lower_struct_method_call`'s
   handling of a `UnaryOp(op='*')` argument. `_lower_UnaryOp` is supposed to
   pass an already-packed `MojoList *` through unchanged (the comment at
   `emit_calls.py` around `_call_has_spread` says so), but `g(1, 2)` has no
   spread in the SOURCE, so the loose arguments are being packed once as a
   tuple and then collected again. Compare against
   `_pack_vararg_trailing_params` (`emit_calls.py`), which is the one place
   that already reasons about this.

`mojo_list_extend` is the helper the comprehension path already uses
(`emit_exprs.py:5094`, `:5556`), so the runtime side needs nothing new.

A `test_gimple_runner.py` case per shape, in the same style as
`test_gimple.py`'s `dict_literal_star_star_pair_merges_instead_of_storing`
(asserted against CPython's stdout on both pipeline modes), is what should
pin all three.