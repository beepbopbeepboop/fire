# CODEGEN: a str VARIABLE passed beside a list to an iterated parameter, called at module level, is not refused

Found 2026-11-01 while landing the per-kind clone pass for an iterated
parameter (the bug doc for that is DELETED — fixed by commit `51f9c69d6`).


## Repro (compiled path, exit -11; CPython prints `4 5 d e`)

    def each(xs):
        for x in xs:
            print(x)
    ys = "de"
    each([4, 5])
    each(ys)

Compiled: `4`, `5`, then SIGSEGV. The same mix inside a function
(`def main(): ys = "de"; each([4, 5]); each(ys)`) IS refused at compile time
by `_refuse_mixed_container_params`, so `fire.py` falls back to the
interpreter and prints the right answer. Only the module-level caller slips
through.

Reproduced with the per-kind clone pass disabled, so this is not a regression
from it (it is not a literal argument, so the clone pass does not apply).

## Why it is not refused (verified by reading)

The refusal needs both a container observation and a non-container
observation for `xs`. The list literal gives the container one. The `ys`
argument should give the non-container one through `_is_noncontainer_arg`,
which needs `_arg_scalar_type(...)` to answer `char *` for `ys`. At module
level that answer is apparently not available (the caller is `<module>`, not a
`FunctionDef`), so the call is not recorded as a non-container observer.

## Next step

1. In `module_gen.py`, check what `_arg_scalar_type` returns for a bare name
   bound at module level (`ys = "de"` at top level, passed to a function).
   Probably `None`, which `_is_noncontainer_arg` deliberately does not count.
2. Either teach `_arg_scalar_type` / `_is_noncontainer_arg` the module-level
   binding of a str (the `_inferred_var_types` scan may not cover the module
   scope), or make the refusal count a call whose argument's kind is unknown
   AND whose argument is a plain name bound to a literal of a different kind.
3. Test: the repro above as a `test_gimple.py` case, both single-TU and
   link-mode, expecting either CPython's stdout or the refusal. Next to
   `test_a_mixed_iterated_parameter_with_a_str_variable_still_refuses`, which
   covers the in-function variant.
