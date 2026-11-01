# CODEGEN_a_tagged_generator_passed_to_a_function_is_refused: a valid program refused on the default path

Filed 2026-11-01 when the silent `0` from a bare or explicit `yield None` (the
yield side of the None family, closed in 39ed52623) was fixed on every shape that
compiles. The fix commit's message carries the measurements.

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
  `none_yield_passed_to_function_next` and `tagged_passed_to_function_next_default`
  / `tagged_mixed_passed_to_function_next` (CPython oracle) pin `next(it)` and
  `next(it, default)` on the parameter (landed 2026-11-01, see Status below).
- The cpp-path shapes are covered by `none_yield_lone_bare_for_loop_cpp` and
  `tagged_int_str_for_loop_cpp` (the cpp path already compiles them).

## Status (2026-11-01): partial fix landed

**Landed.** `mojo/middle/coro.py` gained `_ParamFlow` (plus the shared
`_scope_defs` helper, which `_tagged_consumers_ok` now also uses). A tagged
generator call passed as a positional argument to a plain module-level `def` is
now accepted as a boxed consumer when the callee's parameter is consumed boxed:

- every call site of the callee passes that same generator call, or passes its
  own parameter on to another such callee (followed recursively);
- every use of the parameter in the callee is a `for` iterable, a `list()`
  argument, a comprehension iterable, or a pass-on as above.

Anything else answers False and keeps its refusal: a `*` / keyword / bare
reference to the callee, a second call site with another value, a rebound
parameter, a nested `def` in the caller, and `next()` on the parameter.

Verified: the doc's own example (`use(g())`, bare `yield`) now prints `None`, the
mixed shape prints `1` / `s`, and a two-level pass-through prints `None` / `2`
(all match CPython). `test_gimple_generator_runner.py`: 409 passed, 0 failed.
Pins are in `run_none_yield_tests`: `none_yield_lone_passed_to_function`,
`tagged_mixed_passed_to_function`, `tagged_none_passed_through_two_functions`
(CPython oracle), and the two guards `none_yield_passed_to_function_next_refused`
and `none_yield_passed_to_function_mixed_callers_refused`.

**Landed 2026-11-01 (item 1 of the first round): `next()` on the parameter.**
`_ParamFlow.use_ok` now accepts `next(it)` and `next(it, default)` on the callee
parameter as a boxed consumer. No new seeding was needed: the callee's generator
api is already carried from the call site by `emit_funcs.py`'s
`_param_generator_api` (Pass 1.3f-gen), so `_lower_generator_next` runs and tags
the result. The earlier `0` in this doc was measured before that seeding path
reached this shape; re-measured, the tagged bare-yield case prints `None`.
Verified against the CPython oracle: `use(g())` with `print(next(it))` on a bare
yield (`None`); the mixed shape with two `next()` calls (`1` / `s`); a two-level
pass-through (`None` / `2`); and `next(it, 7)` three times over `yield` / `yield 2`
(`None` / `2` / `7`, matching CPython). Before the change each
was refused. `test_gimple_generator_runner.py`: 411 passed, 0 failed.

**Still refused (the remaining work):**
1. A parameter that also receives a non-generator value at another call site
   (`use(g())` plus `use([1, 2])`). The callee has one parameter kind, so this
   needs per-call-site kinds or a boxed-at-call rule. Pinned as a refusal by
   `none_yield_passed_to_function_mixed_callers_refused`.

**Gate note for the integrator.** `_tagged_consumers_ok` is shared by every
generator. The change only widens acceptance for generators that reach a boxed
parameter. Not measured: a generator whose kinds were tagged-able and which was
passed to such a function previously fell through to a non-tagged slot (for
example `'p'`), and it may now take the `'w'` slot instead. That is a slot change
for shapes that used to compile, so run `compile_stdlib.py` (`U` and `skip`
before/after) and the full `gimplegenerators` run.

## Planning round (2026-11-01): the mixed-callers shape

**Measurement.** `test_gimple_generator_runner.py` on this tree: 415 passed,
0 failed (the pins above included). The mixed-callers guard
`none_yield_passed_to_function_mixed_callers_refused` (`use(g())` plus
`use([1, 2])`) still refuses with "generator function(s)".

**Why it refuses (the mechanism, read from code).** `module_gen.py`
(`_param_gen_obs` loop, about line 12600-12660) infers ONE C type per callee
parameter from its call sites: a call that passes a generator call observes the
generator's api (`_arg_generator_prov`) and sets the parameter to
`MojoGenerator *` with `_param_generator_api[callee][param] = api`. A list at
another call site produces no observation, so nothing reconciles it: the
parameter is `MojoGenerator *` while `use([1, 2])` passes a `MojoList *`. The
`_ParamFlow.source_ok` check (`mojo/middle/coro.py`) is the guard that keeps
this from being emitted: every call site must pass the generator call.

**Decision: per-kind specialization, not box-at-call.** Two options:
- *Box at call*: every call site of a mixed callee passes a tagged word, and
  the callee's `for` / `next` reads a box at runtime. Changes the call ABI for
  every caller of every such function, and needs a runtime dispatch on list vs
  generator inside the callee. Wide blast radius.
- *Specialize per call-site kind* (recommended): clone the callee once per
  distinct argument kind (`use` for the generator, `use__list` for the list),
  rewrite each call site to its clone, and let the existing single-kind
  inference run unchanged on each clone. This is the same move
  `mojo/middle/monomorphize.py` already makes for generic structs, and it keeps
  every individual function single-typed, so no ABI change.

**Plan (recommended option).**
1. New AST pre-pass in `mojo/middle/` (a sibling of `coro.py`'s
   `_ParamFlow`, e.g. `mojo/middle/param_specialize.py`): for each plain
   module-level `def` with a parameter that is a call-site mixed-kind argument
   (generator call at some sites, a non-generator at others), emit a clone
   `name__<kind>` per distinct kind and rewrite the matching `CallExpr.func`.
   Clone only when the parameter is consumed boxed in the body (reuse
   `_ParamFlow.use_ok` for the check), so the rest of the program is untouched.
   Run it before `_tagged_consumers_ok` / `module_gen.py`'s inference so each
   clone is seen as an ordinary single-kind function.
2. Name mangling: clone names must not collide with user names; reuse the
   `monomorphize.py` naming convention (check how it mangles instantiation
   names before choosing).
3. Recursion: a clone that calls the original (or another mixed callee) must
   be rewritten to the matching clone; a pass-through (`_ParamFlow` pass-on
   case) is already followed recursively and must be re-keyed the same way.
4. Coverage: only clone when at least two distinct kinds reach the same
   parameter. Single-kind callees keep their current code path byte-for-byte.

**Tests that prove it (add to `run_none_yield_tests`).**
- `none_yield_passed_to_function_mixed_callers_refused` flips from a refusal to
  a CPython-matched run (`use(g())` then `use([1, 2])`, both printing the
  same as CPython). Rename it accordingly; the guard it pins is the thing
  that changes.
- A cpp-path pin for the same shape (`MOJO_CORO=cpp` already compiles the
  tagged form).
- A single-kind control (`use(g())` only) whose generated C is byte-identical
  before and after (`cmp` the artifacts), proving the pass is a no-op there.

**Gate notes for the integrator.** Specialization changes which functions exist
in the module, so run `compile_stdlib.py` (U and skip counts before/after) and
the full `gimplegenerators` run. Also measure how many stdlib callees would be
cloned; if it is zero, the change is test-only in practice.

## Next step

1. Implement the per-kind specialization pre-pass above (planning is done; the
   next round executes it). Decision already made: specialize, do not box.
2. Integrator: the gate note above, plus the earlier `next()` note (the
   `next()` acceptance widens the same `_ParamFlow` decision and needs the
   same `compile_stdlib.py` U/skip check).
