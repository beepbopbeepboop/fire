# COMPILE_FAIL: c_analyzer/__main__.py part 5 — `for ... in` a captured nested generator inside a coroutine generator

Parent: `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__.md` (SPLIT)
Class: mid

## Goal

Make a generator that stays on the C++20-coroutine path able to consume a
**nested** generator it defines and captures from with an ordinary consuming
loop, `for x in section():` / `for a, b in pairs():`. Today the nested
generator is compiled and registered, the loop is routed to the delegate
helper, and the helper cannot find it, so the module is refused with the
parent doc's long-standing "`for ... in <generator>` does not consume a
generator this compile has itself already translated" message.

After this part, both fixtures in
`test_nested_generator_for_in_coroutine.py` compile, run, and print exactly
what CPython prints.

## Measured current state (2026-11-12, this tree)

Minimal repro (`.tmp/replan/t15.py`):

```python
def fmt(analysis: list):
    def section():
        for x in analysis:
            yield x
    for x in section():
        yield x

for v in fmt([1, 2]):
    print(v)
```

`python3 tools/memslot.py --gb 8 --label ca-for -- python3 fire.py build -o .tmp/out .tmp/replan/t15.py`
exits 1 with:

```
Unsupported shape(s): fmt: `for ... in section(...)` does not consume a
generator this compile has itself already translated via the C++20-coroutine
path (either it's not a generator this codegen supports, or it's defined LATER
in this module — the consumed generator must be defined earlier).
```

The routing half is already correct: `_cpp_iterable_is_delegatable_generator_call`
(`cpp_async.py:214`) answers true because `section` is in
`gen._all_generator_names`, so the loop reaches
`cpp_core._cpp_for_generator_delegate` (`cpp_core.py:8643`). That function
then resolves the callee from `gen._generator_api` (and
`_generator_method_api` for `self.<method>`) only — around `cpp_core.py:8760`
— and a claimed nested generator is deliberately absent from both: it was
removed from `generator_fns` and registered in
`_nested_generator_api[(outer_fn.name, inner.name)]`
(`cpp_async.py:1880`). So the refusal is the latest-attempt text, not an
ordering problem; `_compile_nested_generator_closures` already had every
capture resolved (`_enclosing_scope_with_locals` + `_compute_nested_closure_captures`).

A debug build confirms the nested unit itself compiles with its captures
(`_gen_cpp_generator_unit(section, extra_captures=[...])` succeeds); only the
consumer lookup is missing. The same program works when A3 rewrites the outer
generator to a stack-switch body, where the loop goes through the ordinary
`emit_calls` start-call path — so the fixtures use `items = list(analysis)`
to stay on the coroutine path.

## Plan

1. In `mojo/backend_gimple/cpp_core.py`, `_cpp_for_generator_delegate`: when
   the callee is a bare `IdentExpr` name not found in `_generator_api`, look up
   `gen._nested_generator_api.get((gen._cpp_gen_self_name, name))` before
   raising. Keep the free-generator, self-recursion and generator-method
   branches unchanged; this is an additional registration source.
2. Thread the captures into the `_start` call exactly as for `yield from`:
   user positional arguments first, then each captured enclosing name lowered
   as an ordinary identifier in scope (`api['params']` and `api['captures']`).
   Reuse the argument assembly that
   `emit_calls._emit_nested_generator_start_call` already performs (extract a
   helper rather than copy it). The `<base>_resume`/`_value` drive loop,
   tuple-target unboxing and `_destroy` handling stay as they are.
3. Carry the nested API's value/tuple slot bookkeeping into the drive loop
   (`api['value_ctype']`, `api['mixed_slots']`, `_cpp_last_tuple_slot_ctypes`
   mirroring) so a tuple target unboxes the same slots the nested generator
   yields. Do not re-derive the yield type.
4. Keep unclaimed nested generators and keyword/defaulted arguments refused
   with their existing messages.

## Acceptance

* Both fixtures in `test_nested_generator_for_in_coroutine.py` (flat target
  and tuple target) compile, run, exit 0, and match CPython's stdout. Before
  the change both fail with the `does not consume a generator ...` refusal
  quoted above.
* `python3 test_gimple_generator_runner.py` still passes; top-level generator
  consumption, `self.<method>()` consumption and self-recursion must be
  unchanged (they are the existing `_generator_api` / `_generator_method_api`
  branches).
* The parent doc's build refusal list no longer contains the
  "`for ... in <nested generator>(...)` does not consume" class of line for
  this file (the file itself currently consumes via `yield from`, so this part
  is a sibling-path completion of the same registration gap as part 4; both
  parts may be landed by one worker if the shared helper is touched once).

## Done when

`python3 test_nested_generator_for_in_coroutine.py` exits 0. The file is on
disk and fails on the 2026-11-12 tree with
``for ... in section(...)`` / ``for ... in pairs(...)`` refusals, so it is a
real red test. It builds through `driver.compile_program`, runs the binary,
and compares stdout to CPython on the same text.

## Out of scope

* The imported-module floor owned by sibling docs.
* `yield from` delegation — part 4.
* Generator-method consumption and stack-switch consumption, which already
  work.
