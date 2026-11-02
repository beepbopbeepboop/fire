# test_gimple: `scalar_arity_min_max_params_are_not_containers` prints nothing

Found 2026-10-29 while running `test_gimple.py` for the walk-memo census fix.
It fails on untouched HEAD (`ebf08cc0d`), so it is not caused by that fix.

## What was run

    python3 tools/memslot.py --gb 8 --label head-baseline -- python3 test_gimple.py

Result on HEAD: `412 passed, 2 failed`. The two failures were the walk-memo
census and this test:

    FAIL  scalar_arity_min_max_params_are_not_containers: single-TU, link-mode printed '', CPython printed '9 12 6 4096\n'

## Expected

Both the single-TU inline path and the link-mode pipeline print
`9 12 6 4096`, matching CPython. The test's own docstring records that the
program compiled and printed this on the zipfile `max(n, MIN_READ_SIZE)` shape.

## Next step

1. Run the test's program through `compile_to_gimple` / `driver.compile_program`
   by hand and capture the compile and run stderr (the test discards it). A
   non-zero exit from the compiled binary, or a gcc error, is the first thing
   to look for.
2. Check whether the link-mode output is empty because the binary is missing
   (link failure) or because it exits before printing.
3. Confirm with `python3 tools/memslot.py --gb 8 --label x -- python3 test_gimple.py`
   that the test passes once the cause is found, and do not mark it `expect=`.
