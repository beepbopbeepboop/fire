SPLIT: COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4-part1, COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4-part2, COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4-part3

# COMPILE_FAIL: c_analyzer/__main__.py part 4 — `yield from` a captured nested generator inside a coroutine generator

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` (SPLIT)
Class: mid

## Goal

Make a generator that stays on the C++20-coroutine path able to delegate to a
**nested** generator it defines and captures from, e.g. `fmt_summary`'s
`yield from section('types')` where `section` reads `fmt_summary`'s `items`.
Today the nested generator is compiled and registered, but the delegating
call cannot see it, so the whole module is refused.

After this part, the two fixtures in
`test_nested_generator_yield_from_in_coroutine.py` compile, run, and print
exactly what CPython prints. This clears the two `__main__.py`-local shapes
that the parent doc still lists (`fmt_summary: unresolved callee
'section(...)'` and the follow-on `section: ... no capture model`), which is
the file's last file-local blocker.

## Measured current state (2026-11-12, this tree)

Minimal repro (`.tmp/replan/t13.py`):

```python
def fmt(analysis: list):
    items = list(analysis)
    def section():
        for x in items:
            yield x
    yield from section()

for v in fmt([1, 2]):
    print(v)
```

`python3 tools/memslot.py --gb 8 --label ca-main -- python3 fire.py build -o .tmp/out .tmp/replan/t13.py`
exits 1 with:

```
Unsupported shape(s): fmt: a call to unresolved callee 'section(...)' is not
supported in a compiled generator/coroutine body ...
```

A debug build (`MOJO_DEBUG=1`) plus a probe over
`cpp_async._compile_nested_generator_closures` shows exactly where the two
halves disagree:

* `section` IS claimed: `_nested_generator_captures` gives `['items']`,
  `_enclosing_scope_with_locals` resolves it as `MojoList *`,
  `_only_directly_called` is true, and `_gen_cpp_generator_unit(section,
  extra_captures=[('items', 'MojoList *')])` succeeds and registers
  `_nested_generator_api[('fmt', 'section')]`.
* `fmt`'s body then refuses the call: `cpp_core._cpp_yield_from` builds
  `is_gen_call` from `call.func.name in gen._generator_api` only
  (`cpp_core.py` ~line 11404), and `_generator_api` holds only module-level
  generators. A claimed nested generator is deliberately removed from
  `generator_fns` and lives only in `_nested_generator_api`
  (`cpp_async.py` ~line 1880), so the call falls through to the
  plain-collection path and `_cpp_expr` raises the unresolved-callee refusal.

The same program is accepted when A3 rewrites the enclosing generator to a
stack-switch body (`__mgco_fmt_body`): there the call site goes through
`emit_calls._emit_nested_generator_start_call`, which does read
`_nested_generator_api`. So this is not a capture/typing gap; it is one
missing consumer path in the coroutine body model. Verify that before
changing anything — a fixture that is A3-eligible would not exercise it (both
test fixtures use `items = list(analysis)` to stay on the coroutine path,
matching `__main__.py`'s `items = list(analysis)`).

## Plan

1. In `mojo/backend_gimple/cpp_core.py`, `_cpp_yield_from`: when the callee is
   a bare `IdentExpr` name, also look up
   `gen._nested_generator_api.get((gen._cpp_gen_self_name, name))`
   (`_cpp_gen_self_name` is set by `_gen_cpp_generator_unit`,
   `cpp_async.py:913`; registration is keyed `(outer_fn.name, inner.name)` at
   `cpp_async.py:1880`). Keep `_generator_api`/self-recursion/method lookup
   as they are; this is an additional registration source, not a new
   detector.
2. Thread the captures. The nested generator's `_start` signature is
   `(user args..., captures...)` (`api['params']`), exactly as
   `emit_calls._emit_nested_generator_start_call` builds it: lower the call's
   own positional args, then lower each captured name as an ordinary
   identifier in the enclosing generator's scope, then call `_start`.
   Reuse/extract that argument assembly rather than writing a second copy
   (CLAUDE.md: no duplicated implementations); the delegation loop's
   `_resume`/`_value`/`_destroy` protocol is unchanged.
3. Keep the value-slot kind bookkeeping the nested API needs
   (`_record_generator_value_kind` / `api['tagged']` / `value_ctype`), the
   same way the ordinary start-call path does, so `yield from` sees the same
   slot kind the nested generator was compiled with. Do not widen
   `_nested_generator_captures` or `_compute_nested_closure_captures`; the
   capture model works and must stay the single detector.
4. Leave every unclaimed nested generator refused with the existing message.
   A keyword or defaulted argument stays refused, as
   `_emit_nested_generator_start_call` already does.

## Acceptance

* Both fixtures in `test_nested_generator_yield_from_in_coroutine.py` compile,
  run, exit 0, and print exactly what CPython prints for the same text. Before
  the change they fail with the unresolved-callee refusal quoted above.
* `python3 test_gimple_generator_runner.py` (the existing nested-generator
  suite) still passes; this change must not alter the stack-switch path or
  the free-generator lookup.
* A `yield from` to a nested generator that is **not** claimed (rebound
  capture, `nonlocal` write, keyword argument) still refuses with its existing
  message; add one such negative assertion to the new test if the fixture does
  not already pin it.
* On the real file, the build's `Unsupported shape(s)` no longer names
  `fmt_summary` or `section` (measure with the parent doc's repro; the build
  may still fail on the imported-module floor owned by sibling docs — that is
  out of scope here).

## Done when

`python3 test_nested_generator_yield_from_in_coroutine.py` exits 0. The file is
on disk and fails on the 2026-11-12 tree with
`a call to unresolved callee 'section(...)'` (both cases), so it is a real red
test, not a placeholder. It builds through `driver.compile_program`, runs the
binary, and compares stdout to CPython on the same text.

## Out of scope

* The imported-module floor (`c_parser/info.py`, `.parser`) — sibling docs
  named in the parent.
* A3 stack-switch delegation, which already works.
* The plain consuming `for x in <nested generator>(...)` path — part 5.
