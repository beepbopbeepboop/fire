# Gate: suite-self-test is red on master (six undeclared test files)

**Job:** `suite-self-test` (`python3 test_suite.py`). Not to be confused with the
`test_suite_self_test_red.py` file, which is a fixture for the red-run path.
**Two states:** this doc exists = the job is red and this is the work. Delete it
when the job is green on master.

## What was run, and what was seen

Found while closing an unrelated gate doc (`gimplerunner`), on HEAD 286243b91
(the integration of `bug-gate-red-recover-land-2026-11-02-par`). The command was
the one the job runs, wrapped for the light-worker rule:

    python3 tools/memslot.py --gb 8 --label suite-self -- python3 test_suite.py

    Results: 408 passed, 3 failed
      - the estate: every test file is run by something, or says why not:
        not run by any registered spec, not in UNREGISTERED, and in no declared
        family: test_bare_object_ctor_no_stub.py,
        test_globals_in_function_scope.py, test_imported_global_stub.py,
        test_module_attr_module_call.py,
        test_selfhost_iter_structdefs_no_nested_gen.py,
        test_star_reexport_resolution.py
      - admission: and the job runs, and passes, once there is room: got 1
      - admission: the recorded duration is the job's, not the queue's:
        the 2s timeout is inside (no exit line)

The two `admission:` lines are the known load-sensitive flake (the previous
`suite-self-test` closing commit measured 409 passed and called 411/411 the
steady state "including the two admission-timing lines that only flake when the
machine is loaded"); this tree was under a full memslot budget. The **estate**
failure is not a flake and is the subject here.

## Cause

The same integration, 286243b91, added six standalone `test_*.py` files without
either registering one in `tools/suite.py` or declaring it in
`test_suite.py`'s `UNREGISTERED` inventory:

- `test_bare_object_ctor_no_stub.py`
- `test_globals_in_function_scope.py`
- `test_imported_global_stub.py`
- `test_module_attr_module_call.py`
- `test_selfhost_iter_structdefs_no_nested_gen.py`
- `test_star_reexport_resolution.py`

They are the cheap pins for the stub classes that commit fixed (the doc at
`bugs/GATE_red_recover-land_2026-11-02-part5-part1.md` names them as its pins),
so the files are wanted; only their estate declaration is missing. The estate
check is deliberately strict in both directions — an `UNREGISTERED` entry that
outlives its file or its registration is also a failure — so the tree cannot be
made green by deleting the entries instead.

## Exact next step

Register the six in a bucket, which is what CLAUDE.md wants for cheap pins (a
`reg-*` spec per file, or one spec over a small driver, beside
`reg-gate-rthdrscan`), and add the registration to the bucket list in
`tools/suite.py`. If a file is deliberately not gate-run, declare it in
`test_suite.py::UNREGISTERED` with a reason instead. Then:

    python3 tools/memslot.py --gb 8 --label suite-self -- python3 test_suite.py
      -> 409 passed, 0 failed (the two admission lines can flake under load)

## Done when

`python3 test_suite.py` reports 0 failed on a quiet machine, and this doc is
deleted in the commit that lands the declarations.
