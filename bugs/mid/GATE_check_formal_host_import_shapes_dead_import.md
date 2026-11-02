# GATE: `make check` job `formal-host-import-shapes` is red

## Status (2026-10-31, OPEN)

`make check` run (2026-10-31, 56 jobs, 13 failed) on `mojo-reference2` at `5f805c94`, which is four commits behind master.

Observed, from the job's output in the suite log:

```
FAIL: test_the_whole_tree_has_no_dead_host_import
AssertionError: {'test_dylib_inline_symbol_regression.py': ['inspect']} != {}

`test_dylib_inline_symbol_regression.py` has a dead import of `inspect`.
```

Next step: reproduce the job on master (`python3 tools/suite.py formal-host-import-shapes` or the
job's `checked_run.py` line) and read its full output in `build/suite.log`.
Fix the root cause; the job must pass without an `expect=` or `disabled=`
marker.
