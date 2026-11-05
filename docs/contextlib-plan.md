# Plan: contextlib async/coroutine codegen

Source bug: bugs/hard/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md

## Decomposition

Step 1 — *args/**kwargs packing at call sites (done)
Step 2 — async for / await through callable-valued params
Step 3 — coroutine eligibility for kwonly params
Step 4 — Re-build Lib/contextlib.py end-to-end

## Repro (2026-11-05)
`python3 fire.py build /Users/mrs/net/Python-3.14.6/Lib/contextlib.py` does not finish within the worker budget; it drags in the stdlib dylib build and emits many unrelated module errors. The contextlib-specific refusal remains the async/coroutine codegen gate (`__aenter__` non-scalar return; `*args`/`**kwargs` in coroutine frames), per the bug doc.
