# Gate job `stdlib-syntax` is red: stdlib compile: enum-case `case` patterns rejected

## Status

OPEN. Found in the full `make gate` run on the `get_sign` String-argument fix (`974d0e538`, landed 2026-10-28 with the gate red). The failure is not confirmed to come from that fix: `mojoc` is red on master as well (the imported-function trailing-default drop, which made `mojoc`'s `compile_to_gimple` call three-argument; fixed on `work/bug-codegen-imported-function-default-ar`), and the other jobs are not compared against master yet.

## Gate output (first lines)

```
  Progress: 50 passed, 0 failed  std/builtin/dtype.mojo...FAIL
  Progress: 149 passed, 1 failed  std/logger/logger.mojo...FAIL
  std/memory/address_space.mojo...FAIL
  Progress: 247 passed, 3 failed  std/testing/suite.mojo...FAIL
FAILED: 4 (0 expected, 4 unexpected)
```

## What to check first

`case .PASS:` (an ENUM CASE) rejected at dtype.mojo:432, logger.mojo:176, address_space.mojo:140, testing/suite.mojo:116 (4 UNEXPECTED).

## Next step

1. Run `python3 tools/suite.py stdlib-syntax` alone on master (the gate ran 218 jobs at once, ~93 processes; some reds may be load or timeouts, so rerun alone before fixing).
2. If it reproduces alone on master, fix the root cause and add the test; delete this doc when it is fixed.
3. If it passes alone on master, record that here and find which concurrent job it shares state with.
