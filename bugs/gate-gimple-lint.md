# Gate: gimple-lint is red on master

**Job:** `gimple-lint`. Created when branch `work/bug-codegen-runtime-calls-spelled-as-tex` (task `bug-codegen-runtime-calls-spelled-as-tex`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It was red on `work/bug-codegen-runtime-calls-spelled-as-tex`: reproduce it there (`python3 tools/suite.py gimple-lint`), then fix the cause. Do not skip or mark the test.

## Status — 2026-11-14: fixed on master, no work left

The cause was the ratchet the job exists to keep: the branch left 26 runtime
calls and 8 casts spelled as text inside `gen._emit(...)` / `gen._new_val(...)`,
so `test_text_calls` / `test_text_casts` counted above their baselines (and four
of the text calls were an inline `if (o && o->frozen) raise (...)` that is not
valid GIMPLE in a tagged method). Commit `37f7325cc` ("codegen: route the last
26 runtime text calls through the rt helpers") routed every one through
`_rt_call` / `_rt_into` / `_rt_void` / `_cast`, set both baselines to 0, and
pinned the invalid-GIMPLE shape with a frozendict method case in
`test_regress_gimple_frozendict.py`.

Verified on master + this branch's commit: the registered job is green. The
`TEXT_CALL_BASELINE` / `TEXT_CAST_BASELINE` ratchets are the pinning test — a
new text call or cast raises the count above 0 and fails the job, exactly as
the 26 + 8 did before `37f7325cc`.

## Done when

`python3 tools/memslot.py --gb 8 --label gimple-lint -- python3 tools/suite.py gimple-lint`

reports `1 passed, 0 failed` (it runs both `unit` and `ratchet`).
