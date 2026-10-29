# Gate job `formal-sweep-truth` is red: formal sweep truth test: a Lean launch outside the launcher

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
FAIL: test_nothing_launches_lean_outside_the_launcher (__main__.TestLeanLaunchEstate.test_nothing_launches_lean_outside_the_launcher)
Traceback (most recent call last):
AssertionError: {'tools/swarm.py': [(175, 'subprocess.run')]} != {}
FAIL: test_no_tool_grinds_generated_code_into_a_hard_coded_dir (__main__.TestScratchDirEstate.test_no_tool_grinds_generated_code_into_a_hard_coded_dir)
Traceback (most recent call last):
AssertionError: {'tools/repro_indent.py': [(38, '/tmp/mono[76 chars]c')]} != {}
```

## What to check first

test_nothing_launches_lean_outside_the_launcher fails; find the new direct Lean invocation.

## Next step

1. Run `python3 tools/suite.py formal-sweep-truth` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
