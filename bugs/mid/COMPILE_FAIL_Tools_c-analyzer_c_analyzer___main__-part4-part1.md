# COMPILE_FAIL: `yield from` a captured nested generator inside a coroutine generator — delegation lookup and capture threading (minimal shape)

Part 1 of `bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_analyzer___main__-part4.md`
(SPLIT). Parts 2 and 3 carry the rest.

## Goal

A generator on the C++20-coroutine path must be able to `yield from` a nested
generator it defines and captures from. Today `cpp_async._compile_nested_generator_closures`
claims and registers the nested generator (in `_nested_generator_api`, keyed
`(outer, inner)`, with its captures as trailing `_start` parameters), but
`cpp_core._cpp_yield_from` only recognises callees in `_generator_api`, so the
delegating call falls through to the plain-collection path and is refused:

    a call to unresolved callee 'section(...)' is not supported in a compiled
    generator/coroutine body

Repro (`.tmp/replan/t13.py` in the parent doc):

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

This part makes that minimal shape compile and run with CPython's output.

## Plan

1. `mojo/backend_gimple/cpp_core.py`, `_cpp_yield_from` (~line 11790, the
   `is_gen_call` decision): when the callee is a bare `IdentExpr`, also accept
   it if `(gen._cpp_gen_self_name, name)` is in `gen._nested_generator_api`
   (`_cpp_gen_self_name` is set by `_gen_cpp_generator_unit`, `cpp_async.py`
   ~line 913; registration is at `cpp_async.py` ~line 1881). This is an
   additional registration source, not a new detector. Do not touch
   `_nested_generator_captures` or `_compute_nested_closure_captures`.
2. Lower the start call the same way the stack-switch path does. The argument
   assembly already exists in `emit_calls.py`: `_nested_generator_start_arg_pairs`
   and `_finish_generator_start`, used by `_emit_nested_generator_start_call`
   (~line 349). Extract or reuse that assembly from the coroutine path; do not
   write a second copy (CLAUDE.md: no duplicated implementations). Call
   `_record_generator_value_kind(api)` as that function does, so the delegation
   sees the slot kind the nested generator was compiled with.
3. Leave the `_resume`/`_value`/`_destroy` delegation loop unchanged.
4. Add a case selector to `test_nested_generator_yield_from_in_coroutine.py`:
   `python3 test_nested_generator_yield_from_in_coroutine.py minimal` runs only
   `MINIMAL_SRC`, and with no argument it runs both cases as before. This lets
   parts 1 to 3 each name one case as their done-when.

## Acceptance

* `python3 test_nested_generator_yield_from_in_coroutine.py minimal` exits 0:
  the minimal program builds through `driver.compile_program`, runs, and prints
  exactly what CPython prints (`1` and `2`, one per line).
* Before the change, the same command fails with the unresolved-callee refusal
  quoted above.
* `python3 test_gimple_generator_runner.py` still passes. The stack-switch path
  and the free-generator lookup must not change.

## Done when

`python3 test_nested_generator_yield_from_in_coroutine.py minimal` exits 0.
Run it under `python3 tools/memslot.py --gb 8 --label part4-part1 -- python3 test_nested_generator_yield_from_in_coroutine.py minimal`.

## Out of scope

* The `main-shape` fixture (`fmt_summary` / `section` / `build_section`): part 2.
* Keyword/rebound/`nonlocal` refusals and tagged-kind parity: part 3.
* The plain consuming `for x in <nested generator>(...)` path: part 5 of the parent (already fixed and deleted).
