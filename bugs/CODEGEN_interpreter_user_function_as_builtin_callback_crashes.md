# CODEGEN: the interpreter crashes on a user-defined function passed as a builtin callback

**State: OPEN.** A hard `AttributeError` out of `myinterpreter.py` — the
program does not run at all. Found while working
`bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md`; not part of that
claim and not touched by it.

## What I ran and what I saw

`python3 fire.py run` on the program below:

    def main():
        print(sorted([1, 2, 3], key=lambda a: -a))

| | result |
|---|---|
| CPython | `[3, 2, 1]` |
| `python3 fire.py run` (interpreter) | `AttributeError: 'int' object has no attribute 'scope'` |
| compiled | `[3, 2, 1]` (correct) |

The interpreter raises from `myinterpreter.py:302`, in `_invoke`:

    old_scope = interpreter.scope
                ^^^^^^^^^^^^^^^^^
    AttributeError: 'int' object has no attribute 'scope'

## It is not about variadic lambdas

I first hit this through `sorted(key=lambda *a: -a[0])` and assumed the
`*args` was involved. It is not — the shape is a user-defined function of ANY
signature used as a builtin callback. Measured, all four crash the same way:

    sorted([1,2,3], key=lambda a: -a)   -> AttributeError
    def k(a): return -a
    sorted([1,2,3], key=k)               -> AttributeError
    sorted([1,2,3], key=abs)            -> [1, 2, 3]   (a BUILTIN works)
    f = lambda *a: len(a); f(1, 2)       -> 2            (a direct call works)

So the difference is not lambda-vs-def, not variadic-vs-fixed, and not
compiled-vs-interpreted. It is that a *builtin* receiving a user function as a
callback crashes, while the same function called directly, or a C builtin used
the same way, does not.

## Mechanism (as far as the trace goes)

`_invoke` expects its first argument to be an interpreter and reaches for
`.scope`. It is being handed an `int`, so something upstream replaced the
interpreter object with an integer on this path. Given that
`sorted(key=<builtin>)` works, the most likely reading is that the builtin
callback path calls the callable through a helper that does not thread the
interpreter through — but the trace alone does not prove that, and the failing
line is in `_invoke` rather than in the builtin dispatch, so the caller needs
to be identified first. **That is the first thing to do**, not a fix.

## Next step

1. Find which caller reaches `_invoke` from `sorted`'s `key=` handling and
   passes the value in the interpreter's slot — a wrong-arity or
   wrong-position call in the builtin callback path, most likely.
2. With that identified, either thread the interpreter through, or special-case
   the callback the way `key=<builtin>` evidently is.

Worth noting for whoever takes it: this is the last known blocker on
`test_runtime_diff.py` covering a variadic lambda as a `sorted(key=)` /
`map` callable. The compiled path is already correct for both (see
`test_gimple_runner.py`'s `gimple_variadic_lambda_works_through_every_holder`),
so once the interpreter is fixed the two engines can be diffed on that shape
too — which is a strictly stronger check than the compiled-only one now in
place.
