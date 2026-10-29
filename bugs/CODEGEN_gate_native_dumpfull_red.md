# Gate job `native-dumpfull` is red: native --dump-full job red, no excerpt captured

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
memcap: native-dumpfull -- ceiling 24.0 GB across the process tree
Results: 0 passed, 1 failed
✗ /Users/mrs/net/chatgpt/claude/work-spanfix/mojoc not built - run `make mojoc` first
```

## What to check first

RESOURCE/FAIL at 0.7 s; the job died before printing; rerun alone to read its output.

## Next step

1. Run `python3 tools/suite.py native-dumpfull` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
