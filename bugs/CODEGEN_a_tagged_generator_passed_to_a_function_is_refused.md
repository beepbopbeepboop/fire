# CODEGEN_a_tagged_generator_passed_to_a_function_is_refused: a valid program refused on the default path

Filed 2026-11-01 when `CODEGEN_a_bare_or_explicit_yield_of_none_prints_zero` was
closed (its silent `0` is fixed on every shape that compiles; see that doc's
history in git, `git log -- bugs/CODEGEN_a_bare_or_explicit_yield_of_none_prints_zero.md`).

## Symptom (refusal, not a silent wrong value)

A generator whose yields need a tagged word (a None yield, or mixed kinds) is
REFUSED on the default stack-switch path when it is passed as an argument to a
function that iterates it. The program is valid Mojo and CPython runs it.

```python
def g():
    yield          # or: yield 1 / yield "s" for the mixed-kind shape
def use(it):
    for v in it:
        print(v)
def main():
    use(g())
main()
```

- CPython: `None` (mixed-kind shape: `1` then `s`).
- Default path (`gimple_codegen.compile_to_gimple_with_cpp`): RuntimeError,
  either "a None yield whose consumer is not a for loop / list() / comprehension"
  (`mojo/middle/coro.py`, `_generator_value_kind`) or the module-level
  "generator function(s) ... straight-line" catch-all
  (`mojo/backend_gimple/module_gen.py`, near line 12398).
- `MOJO_CORO=cpp`: COMPILES and matches CPython for both shapes.
- A non-tagged generator (`yield 1`, `yield 2`) passed the same way compiles on
  the default path and matches CPython. So the refusal is about the tagged word,
  not about passing a generator.

## Cause

`_tagged_consumers_ok(name)` (`mojo/middle/coro.py`) accepts a tagged generator
only when every reference is a consumer that reads the word as a boxed value in
the SAME function: a `for` iterable, `list()`, a comprehension, `yield from`, or
`next()`. A call that hands `g()` to another function is not on that list, so the
tagged kind is not taken; the fall-through then refuses a None slot, and a mixed
slot is refused by the mixed-kind checks.

## Why it is not a one-line fix

The tagged word's rendering is decided by the consumer. Inside `use`, the loop
iterates a PARAMETER, which has no static tie back to `g`. To accept the shape,
the tagged kind must cross the call boundary: either `use`'s parameter is typed
as a tagged-word generator value (interprocedural kind propagation from each call
site), or the default path lowers `use`'s `for` over an unknown-kind iterable as
a boxed read. Both change how a parameter is typed for every caller, so this is
a feature of the generator kind system, not a patch at one site.

## Pins

- `test_gimple_generator_runner.py`, `run_none_yield_tests`:
  `none_yield_lone_passed_to_function_refused` pins the honest refusal (a guard:
  it must stay a refusal, never a silent `0`).
- The cpp-path shapes are covered by `none_yield_lone_bare_for_loop_cpp` and
  `tagged_int_str_for_loop_cpp` (the cpp path already compiles them).

## Next step

1. Decide the rule for a tagged generator crossing a call: pass the kind as the
   parameter's kind (preferred: it reuses `_generator_value_kind` per call site),
   or box at the call so the callee's `for` reads a box.
2. Probe the same shapes with `next(it)` inside the callee and with `list(it)` in
   the callee, so the fix covers every consumer kind the callee can apply.
3. Flip `none_yield_lone_passed_to_function_refused` to a CPython-oracle pin
   (`test_generator_matches_cpython`, expected `None\n`) when the default path
   compiles it, and add the mixed-kind shape beside it.
4. Gate note for the integrator: `_tagged_consumers_ok` is shared by every
   generator, so the change needs `compile_stdlib.py` `U`/`skip` before and after
   and the full `gimplegenerators` run.
