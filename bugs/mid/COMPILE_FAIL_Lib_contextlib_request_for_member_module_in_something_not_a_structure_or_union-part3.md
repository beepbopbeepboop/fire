# COMPILE_FAIL_Lib_contextlib part3: variadic async params in coroutine frame and Lib/contextlib.py compile

Split from `bugs/hard/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md`.

## Problem

`Lib/contextlib.py` cannot be compiled because async function(s) in it use
variadic parameters that the async coroutine codegen/frame cannot represent
(notably `__aexit__` / exit-wrapper shapes taking `*args`/`**kwargs` on the
refusing `module_gen.py` path). The coroutine frame has fixed slots today;
supporting `*args`/`**kwargs` for compiled async functions requires carrying
variable-arity arguments in the frame and satisfying the module-level async
eligibility/refusal gate for that shape.

## Scope

- Extend `mojo/backend_gimple/cpp_async.py` coroutine codegen so compiled async
  functions can accept `*args` and/or `**kwargs` as required by the minimal
  `contextlib`-like refusal shape: represent them in the coroutine frame/slot
  table and initialize/read them correctly across suspend/resume boundaries.
- Update the async-function eligibility/refusal logic (and any module_gen
  coupling) so a supported variadic async shape is no longer refused with
  "`*args/**kwargs` parameters not supported for compiled async functions".
- Isolate the minimal refused shape through the `module_gen.py` whole-module
  path (as described in the parent doc: reduce/call the module generator
  directly, not via `fire.py build` which drags in the stdlib dylib) so the fix
  targets the real refusing condition for `contextlib`.
- This part assumes part1 (variadic async call-site arity/packing) is in place
  for the call forms exercised; if discovered to be independent in practice,
  note that explicitly but keep acceptance end-to-end for the refusing shape.

## Acceptance check

1. A minimal module containing the variadic async shape that `module_gen.py`
   currently refuses for `contextlib` (record that minimal source in the test or
   the bug doc status when implementing) compiles without the
   "cannot compile module ... `*args/**kwargs` parameters not supported for
   compiled async functions" refusal.
2. `python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/contextlib.py` exits 0
   on the default backend path (integrator/gate may run this heavy verification;
   the implementing worker must not run whole-closure/self-host builds, but must
   provide the narrowest reproducer and evidence for the fixed shape).
3. Add a regression test that invokes the same module/codegen entry point that
   produced the refusal on the minimal source and asserts the refusal is absent;
   it must fail before the fix and pass after. Existing async coroutine tests
   remain passing on their narrow suites.

## Notes

- This corresponds to cause (2) / plan steps (1)-(3) in the parent doc:
  variable-arity coroutine parameters in the frame and an end-to-end
  `Lib/contextlib.py` compile. Part2 (boxed non-scalar `__aenter__` return) is a
  separate prerequisite cause for `contextlib`; both must be satisfied for the
  file to compile cleanly. Coordinate via the parent bug's status/remaining
  causes if one lands before the other.
- Do not spend a turn only re-verifying the refusal; land the fix or a concrete
  isolated reproducer/test that demonstrates forward progress.

## Status 2026-11-12

- `mojo/backend_gimple/cpp_async.py`: `_gen_cpp_async_unit` and
  `_gen_cpp_async_generator_unit` now accept `*args` (`MojoList *`) and
  `**kwargs` (`MojoDict *`) coroutine parameters instead of refusing with
  "`*args/**kwargs` parameters not supported for compiled async functions".
- `mojo/backend_gimple/module_gen.py`: async API entries now record
  `star_slot`/`kwargs_slot` for top-level compiled async functions.
- `mojo/backend_gimple/emit_calls.py`: async handle construction packs trailing
  positional args into the `*args` list when the callee has a `star_slot`.
- Regression test `test_regress_async_variadic_params.py` compiles the minimal
  module-gen shapes (`async def __aexit__(self, *args)`, `**kwargs`, combined,
  fixed+`*args`, struct async method with `*args`) via `gen_module` and asserts
  the refusal is absent.
- Not verified here: full `Lib/contextlib.py` compile (heavy; depends on part2
  for boxed non-scalar `__aenter__` return and any remaining causes). Doc kept
  until end-to-end compile is confirmed. `tools/dangling_doc_refs.py --ratchet`
  had unrelated pre-existing ratchet failures in this tree, so doc deletion was
  deferred.
