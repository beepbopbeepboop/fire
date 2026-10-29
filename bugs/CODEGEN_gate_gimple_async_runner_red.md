# Gate job `gimple-async-runner` is red: bare async calls never run their bodies

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
FAIL  bare_async_call_never_runs_body: expected a non-empty generated .cpp — this source doesn't actually contain a Step-B-supported async function
FAIL  multiple_bare_async_calls_never_run_bodies: expected a non-empty generated .cpp — this source doesn't actually contain a Step-B-supported async function
FAIL  async_function_multi_statement_body_compiles_and_runs: expected a non-empty generated .cpp — this source doesn't actually contain a Step-B-supported async function
FAIL  async_function_float_return_compiles_and_runs: expected a non-empty generated .cpp — this source doesn't actually contain a Step-B-supported async function
FAIL  value_consuming_assignment_lazily_constructs_and_never_runs_body: expected a non-empty generated .cpp — this source doesn't actually contain a Step-B-supported async function
FAIL  value_consuming_print_arg_lazily_constructs_and_never_runs_body: expected a non-empty generated .cpp — this source doesn't actually contain a Step-B-supported async function
```

## What to check first

the Step-B async runner reports no supported async function in its test sources.

## Next step

1. Run `python3 tools/suite.py gimple-async-runner` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
