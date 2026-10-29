# Gate job `gimplegenerators` is red: generator iterating a string parameter yields nothing (and a control case)

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (see `bugs/CODEGEN_imported_function_default_argument_dropped_at_call.md`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
PASS  cpp_coroutine_exception_ctor_as_value
PASS  cpp_coroutine_exception_ctor_as_value_no_arg
FAIL  generator_iterating_a_string_parameter_yields_nothing: expected 'a\nb\n', got '4371202938\n4371202940\n'
FAIL  generator_iterating_a_string_parameter_control: expected a non-empty generated .cpp — this source doesn't actually contain a supported generator (neither stack-switch nor cpp path lowered it)
```

## What to check first

generator_iterating_a_string_parameter_yields_nothing prints object addresses instead of the characters.

## Next step

1. Run `python3 tools/suite.py gimplegenerators` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
