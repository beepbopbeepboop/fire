# CODEGEN_next_on_a_module_global_generator_is_refused: next() on a module-level generator has no lowering

Found 2026-11-01 while measuring `CODEGEN_a_bare_or_explicit_yield_of_none_prints_zero`.
NOT specific to None: an int-only generator shows the same refusal.

## What was run

Default backend (stack-switch), `gimple_codegen.compile_to_gimple_with_cpp` via
`test_gimple_generator_runner._build_generator_program`:

```python
def g():
    yield 1
    yield 2

it = g()          # module-level generator handle

def main():
    print(next(it))
main()
```

## What was seen

Refused, so the module falls back to the interpreter:

    cannot compile module: `next(...)` on next(IdentExpr) (receiver typed
    `MojoGenerator *`) in function `main` has no lowering in this codegen —
    every fall-through here emitted a call to a `next` symbol ...

A `for v in g():` loop over the same generator in a module-level context
compiles and matches CPython (measured, None and int shapes).

## What was expected

Compiled output matching CPython (`1`), like the local spelling
`it = g(); print(next(it))` inside a function, which compiles and matches.

## Likely cause (not yet verified)

The module-global read of a `MojoGenerator *` (the global store was fixed for
`.close()` in `run_module_global_generator_tests`, see
`test_gimple_generator_runner.py`) does not carry the generator's API into the
`next()` lowering the way a local assignment does (`_lower_generator_next` in
`mojo/backend_gimple/emit_calls.py`, and `_cpp_next_on_generator_expr` in
`mojo/backend_gimple/cpp_core.py` for the escape hatch). The `.close()` fix
carried the entry for a module global; `next()` needs the same carry.

## Next step

1. Reproduce with the program above, and confirm which lowering site refuses
   (grep the message text in `mojo/backend_gimple/` and `gimple_codegen.py`).
2. Make the module-global handle's "which generator is this" entry visible to
   the `next()` lowering, mirroring the `.close()` fix in
   `run_module_global_generator_tests`.
3. Pin: add `next(it)` / `next(it, default)` cases for a module-global
   generator to `run_module_global_generator_tests` (CPython oracle), and a
   None-yield variant to `run_none_yield_tests`.
