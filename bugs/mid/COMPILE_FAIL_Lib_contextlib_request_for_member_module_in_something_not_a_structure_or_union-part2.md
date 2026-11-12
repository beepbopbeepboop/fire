# COMPILE_FAIL_Lib_contextlib part2: boxed non-scalar `__aenter__` return in async coroutine codegen

Split from `bugs/hard/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md`.

## Problem

Async context managers require `__aenter__` to return a (possibly non-scalar)
value. The coroutine/promise slot in `mojo/backend_gimple/cpp_async.py` is
typed by a scalar lattice (`_generator_yield_ctype` and related logic), so there
is no storage/read-back path for boxed/non-scalar returns (e.g. returning a
`MojoAsync *`, `MojoList *`, or other heap/struct values). This is one of the
reasons `Lib/contextlib.py` is refused by the async-function eligibility gate
(`__aenter__: every \`return\` must carry a scalar value` on the refusing path).

## Scope

- Extend the async coroutine codegen to support a boxed return slot for
  non-scalar `__aenter__` returns (and any directly equivalent async coroutine
  return case required by the same mechanism), including dynamic/typed read-back
  at every consumer site that observes the awaited result.
- Address the promise/slot typing and the emit/read paths in `cpp_async.py` (and
  any tightly coupled helpers it relies on) so a non-scalar return is
  represented correctly rather than rejected or truncated.
- Keep the change focused on non-scalar return boxing/type-erasure for async
  coroutine results; do not fold in unrelated `*args/**kwargs` coroutine-frame
  work except minimal plumbing strictly required by the same return path.

## Acceptance check

1. A minimal reproducer shaped like an async context manager compiles and runs
   (through the module/codegen path that currently refuses it), with
   `__aenter__` returning a non-scalar value that is observed correctly by the
   `async with`/await consumer. Example shape to make concrete in the test:

   ```python
   class CM:
       async def __aenter__(self):
           return [1, 2, 3]  # non-scalar
       async def __aexit__(self, exc_type, exc, tb):
           return False

   async def main():
       async with CM() as v:
           return len(v)  # expect 3
   ```

   (The exact container/value type may be adjusted to the smallest non-scalar
   case the current backend can represent once boxed, but the acceptance is:
   non-scalar `__aenter__` return is no longer refused for lacking a scalar slot
   and the returned value is correct at the use site.)

2. Add a regression test next to existing async runner/module-compile tests that
   fails before the fix and passes after, asserting the refusal is absent and
   the runtime result is correct.
3. Existing async/generator tests remain passing on the narrow suites covering
   scalar coroutine returns.

## Notes

- This corresponds to cause (1) / plan step (1) in the parent doc: "a BOXED
  return slot plus dynamic read-back at every consumer", related in shape to the
  `_actual_types`-vs-static-type handling noted there.
- Isolation through the `module_gen.py` refusing path matters for the final
  contextlib compile; a probe that only uses an in-process entry point that
  silently accepts the shape is not sufficient on its own.
