# Gate: stdlib-dylib is red on master

**Job:** `stdlib-dylib`. Filed by the full gate at `77c157bb07`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py stdlib-dylib`), then fix the cause.

## Done when

`python3 test_stdlib_dylib_degraded_module.py` passes. Its last case compiles
`std/math/math.mojo` through the job's own per-module path
(`build_stdlib_dylib._compile_module_job`, cold) and requires an object: on the
unfixed tree that row is the job's error (`gcc -c failed for the monomorphized
_ldexp_impl_5_dtype_7_Float32_5_width_1_1`), which is exactly the
`skip std/math/math.mojo: ...` line the ratchet counts as an unexpected
fallback to source. The root cause (a monomorphized instance's comptime
`FPUtils[dtype]` references erased to `float`) is fixed by 244efdbef and also
pinned by `test_comptime_member_monomorphized_instance.py`.

## Gate ledger

- **Last known working:** `e8421fc41b` integrate fix-merge-fix-merge-fix-merge-bug-formal-formal-proof-covera
- **First known not working:** `131b61adee` diag: runtime assert prints 'Assert Error: <msg>'; except <name>: is a catch-all binding
- **Seen red in the full gate at:** `77c157bb07` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-77c157bb.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-stdlib-dylib.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
