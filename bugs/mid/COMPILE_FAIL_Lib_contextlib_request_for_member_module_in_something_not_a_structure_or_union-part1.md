# COMPILE_FAIL_Lib_contextlib part1: variadic async coroutine call-site arity/packing

Split from `bugs/hard/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md`.

## Problem

A call to an async coroutine (or async method) whose signature takes a variadic
positional parameter (e.g. `async def __aexit__(self, *exc_details)`) is
lowered with the caller's positional arguments passed flat to the generated
`__mgco_..._start` function. For a call like `await b.__aexit__(1, 2, 3)` this
produces a C arity mismatch at the call site (e.g. `error: too many arguments
to function '__mgco_Box___aexit___start'; expected 2, have 3`).

Packing for `*args` at coroutine/generator call sites was partially landed for
other paths (generators, methods, await/async-for start resolution per the
parent doc), but this variadic-async call shape still fails on the codegen path
that emits the start-function call.

## Scope

- Identify the call-lowering site(s) that supply the argument list for an async
  coroutine start (`__mgco_..._start` / equivalent) and ensure trailing
  positional arguments bound to a `*args` parameter are packed the same way the
  callee/frame expects (mirroring the existing generator/await packing helpers
  where appropriate).
- Cover at least the async instance-method case used by async context managers:
  `await obj.__aexit__(a, b, c)` against `async def __aexit__(self, *exc_details)`.
- Keep the fix narrow to call-site packing/arity for variadic async coroutines;
  do not attempt boxed non-scalar `__aenter__` returns or general coroutine-frame
  support for `*args/**kwargs` beyond what is required for this call shape.

## Acceptance check

1. A minimal reproducer of the form below compiles and runs under the same
   compiled/gimple async path used for async coroutine tests, returning the
   expected value (the count/sum derived from `exc_details`, not a C compile
   error):

   ```python
   class Box:
       async def __aexit__(self, *exc_details):
           n = 0
           for x in exc_details:
               n = n + 1
           return n

   async def main():
       b = Box()
       return await b.__aexit__(1, 2, 3)  # expect 3
   ```

2. Add a regression test next to the existing async/gimple runner tests for this
   area (e.g. `test_gimple_async_runner.py` or the closest existing async
   call/variadic coverage) that fails before the fix and passes after.
3. Existing generator/async runner tests covering landed `*args` packing remain
   passing (at minimum the narrow suites that exercise those paths).

## Notes

- This addresses step 0 / the "separate defect" noted in the parent doc's
  2026-10-29 status: call-site packing must match callee frame for variadic
  coroutines.
- Reproduce through the codegen path that exhibits the `__mgco_..._start` arity
  mismatch; in-process `compile_to_gimple_with_cpp` acceptance alone is not
  sufficient evidence.
