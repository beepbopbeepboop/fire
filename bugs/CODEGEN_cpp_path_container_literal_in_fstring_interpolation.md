# CODEGEN: a collection literal in a cpp-path f-string interpolation emits invalid C++

## Symptom

Inside a generator/coroutine body compiled by the C++20 escape-hatch emitter
(`MOJO_CORO=cpp`), an f-string whose interpolated expression is a collection
literal does not compile:

```
def g():
    print(f"{[1, 2]}")
    yield 0
```

emits, in `_mojogen_g_impl`:

```
printf("%s\n", mojo_str((void *)({1, 2})));
```

g++ rejects `{1, 2}` there (`expected ';' before '}' token`), so `fire.py --jit`
reports `JIT compilation failed: executable build failed`. The interpreter
prints `[1, 2]`, so this is a compiled-path-only failure.

The sibling `_Bool`/string/int shapes and a non-literal container *variable*
are fine; it is the LITERAL that `_cpp_expr` lowers to a braced-init-list.

This is NOT specific to the `!a` conversion: `f"{[1, 2]}"` fails with no
conversion at all (with `!a` the same text is wrapped in the ascii helper and
still fails). It was found while pinning `!a` on the cpp path; the default
(A3 stack-switch) generator backend does not have this bug.

## Evidence

```
MOJO_CORO=cpp python3 fire.py --jit .tmp/gen_listinterp.mojo
# ... gen_listinterp_gen.cpp:131:29: warning: cast to pointer from integer ...
#     printf("%s\n", mojo_str((void *)({1, 2})));
# g++ ... error: expected ';' before '}' token
# JIT compilation failed: executable build failed
python3 fire.py run .tmp/gen_listinterp.mojo
# [1, 2]
```

`mojo/backend_gimple/cpp_core.py`, `_cpp_string_literal_expr`: the expression
part goes through `v = gen._cpp_expr(expr_node)` and then the `int64_t`
fallback wraps that text as `mojo_str((void *)({v}))`. `cpp_core._cpp_expr`'s
ListLiteral case is a braced-init-list, which is only valid in the few
contexts the emitter explicitly supports (initializing a `MojoList *` local,
etc.). There is no check here that the interpolation's value is a scalar;
the sibling direct-yield shape already refuses this (see the
`generator_collection_literal_yield_honest_fallback` case in `test_gimple.py`,
where `yield [1, 2]` is refused rather than emitted).

## Expected

Either (a) compile and print `[1, 2]` (a collection interpolation needs the
list-repr walker, not `mojo_str`), or (b) refuse honestly at codegen with the
same message the direct `yield [1, 2]` shape uses — never emit invalid C++
that only g++ catches.

## Exact next step

In `_cpp_string_literal_expr`'s interpolation arm (cpp_core.py, around the
`if conv == 'r' or conv == 'a':` block), detect a parsed expression whose
`_cpp_expr` lowering is a braced-init-list rather than a scalar C value
(the same node-shape check `_cpp_stmt` uses for its direct-literal refusal,
e.g. `ListLiteral`/`TupleLiteral`/`DictLiteral`/`SetLiteral`), and either
route it through the container-repr helper the ordinary GIMPLE path uses
(`_stringify_value`/`_repr_value`'s container arms) or raise
`_UnsupportedGeneratorShape` naming the literal. Add a `MOJO_CORO=cpp`
compile-and-run row next to `run_cpp_path_fstring_conversion_tests` in
`test_gimple_generator_runner.py`.

Filed 2026-11-09; outside the `!a` task, which only needed the scalar arms.
