# CODEGEN: a lambda inside a nested `def` is lifted but never DEFINED — link error

**State: OPEN.** A hard link failure (`undefined symbol`), so an honest loud
one rather than a silent wrong value. Found while working
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`; independent of it,
and untouched by it — it reproduces with an ordinary fixed-parameter lambda.

## What I ran and what I saw

    def _make():
        def make():
            return lambda x: x + 1
        return make

    def main():
        f = _make()()
        print(f(1))

| | |
|---|---|
| CPython | `2` |
| compiled | link error: `Undefined symbols ...: "__make_make_lambda_1", referenced from: ... __funcptr__make_make_lambda_1` |

The same with `lambda: 7`, and with a `*args` lambda. The generated C declares
the lifted function and takes its address, and never defines it:

    int64_t _make_make_lambda_1 (int64_t x);            <- declared
    static void * _funcptr__make_make_lambda_1 = (void *)_make_make_lambda_1;
    ...
      _t1 = _funcptr__make_make_lambda_1;                <- referenced
      /* no `int64_t __GIMPLE _make_make_lambda_1 (...)` anywhere in the file */

A lambda at the same nesting depth in a TOP-LEVEL function does get its
definition, immediately after the referencing function — so this is specific
to the nested-`def` case.

## Mechanism

`_lower_LambdaExpr` accumulates the lifted body in `gen._lambda_parts` and
nothing else; it is `gen_module` that flushes that list into the output.
`module_gen.py` resets and flushes `_lambda_parts` at several points, and the
comment on one of them already records the trap: "struct-method paths above
each reset-then-flush `_lambda_parts`". A nested `def` is lifted and emitted
through a different path from both a top-level function and a struct method,
and that path clears the pending list without flushing the lambda body that
was added while generating it.

So this is the same class of ordering bug as the `_field_elem_types` note in
`CODEGEN_generator_lambda_expr_unsupported.md`'s `sorted(key=)` section — a
side table flushed at the wrong point — and it is worth checking whether the
same fix point serves both.

## Next step

Find the nested-`def` emission path's handling of `gen._lambda_parts` and make
it flush rather than drop. The concrete check: after compiling a module
containing a nested `def` that itself contains a `lambda`, assert that every
`static void * _funcptr_X = (void *)X;` initializer in the output has a
matching `X` DEFINITION in the same file. That assertion is cheap, needs no
particular shape, and would have caught this.

Worth knowing for whoever takes it: this only bites when the lambda is inside
a nested `def`. `Lib/importlib/util.py`'s `_make_module` and
`Lib/doctest.py`'s nested helpers are the shapes to look at, and
`Lib/doctest.py:1566`'s `can_colorize = lambda *args, **kwargs: False` is
inside `_colorize`'s own class body, so it is a sibling case rather than this
one.
