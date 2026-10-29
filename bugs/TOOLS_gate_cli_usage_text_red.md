# Gate job `cli-usage-text` is red: fire.py usage text check

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
CLI SELF-NAME — fire.py usage/version/error text
PASS  test_error_messages_name_the_tool: 6 usage errors all name the tool
FAIL  test_no_stale_command_name_in_prose: a stale `mojo <command>` was added to: test_link_mode.py: 1 (was allowed 0) — test_link_mode.py:1537: this program (`tools/mojo run`, 2026-10-28). The branch sits before th
```

## What to check first

a usage/version/error string check fails; compare the expected text with fire.py output.

## Next step

1. Run `python3 tools/suite.py cli-usage-text` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
