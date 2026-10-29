# Gate job `selfhost` is red: self-host compile/link regressed

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
   44 | # at `Unexpected RBRACKET(']')` on both backends. See
✗ self-host compile/link regressed (GCC error, ICE, undefined symbol, or the produced binary cannot compile)
```

## What to check first

selfhost: GCC error / undefined symbol; the mojoc arity error (bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md) is the shared cause to check first.

## Next step

1. Run `python3 tools/suite.py selfhost` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
