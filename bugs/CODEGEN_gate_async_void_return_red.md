# Gate job `async-void-return` is red: void-returning async function / device-context repro

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
FAIL  test_void_returning_async_function_driven_via_asyncio_run  exception: expected a non-empty generated .cpp — this source doesn't actually contain a supported async function/closure
FAIL  test_device_context_shaped_repro_end_to_end  exception: link_executable(cxx=True) failed: Undefined symbols for architecture arm64:
collect2: error: ld returned 1 exit status
FAIL  test_enqueue_cpu_range_shaped_repro_multiple_handles  exception: link_executable(cxx=True) failed: Undefined symbols for architecture arm64:
collect2: error: ld returned 1 exit status
```

## What to check first

no generated .cpp for a void async function; test_device_context_shaped_repro_end_to_end link: undefined symbols.

## Next step

1. Run `python3 tools/suite.py async-void-return` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
