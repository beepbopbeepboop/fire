# Gate job `formal-doc-truth` is red: FORMAL.md figures out of date

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
FAIL  FORMAL.md restates the non-word count as 421 and runtime_abi() says 422
FAIL  FORMAL.md §1 says fire_runtime.c is 580 KB, it is 583 KB
doc truth: PASS=432 FAIL=2
```

## What to check first

the published figures (non-word count, fire_runtime.c size) are stale; regenerate from the live measurement.

## Next step

1. Run `python3 tools/suite.py formal-doc-truth` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
