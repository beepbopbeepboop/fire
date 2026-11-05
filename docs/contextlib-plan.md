# Plan: contextlib async/coroutine codegen

Source bug: bugs/hard/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union.md

## Decomposition

Step 1 — *args/**kwargs packing at call sites (done)
Step 2 — async for / await through callable-valued params
Step 3 — coroutine eligibility for kwonly params
Step 4 — Re-build Lib/contextlib.py end-to-end
