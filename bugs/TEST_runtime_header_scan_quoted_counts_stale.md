# test_runtime_header_scan: quoted counts in docs are stale against runtime_abi()

Found 2026-11-12 while verifying the merge of master into
work/fix-merge-bug-orchestration-formal-unlanded-task-s. Not caused by that
merge: the failing files are byte-identical to master.

## What ran

    python3 tools/memslot.py --gb 8 --label runtime-header-scan -- python3 test_runtime_header_scan.py

Result: `42 passed, 11 failed, 53 checks`, exit 1. Failures:

    FAIL  FORMAL.md: the quoted word count is 418: the text says 415; `runtime_abi()` says 418
    FAIL  FORMAL.md: the quoted total count is 920: the text says 917; `runtime_abi()` says 920
    FAIL  formal/build.py: the quoted total count is 920: the text says 917; `runtime_abi()` says 920
    FAIL  formal/build.py: the quoted word count is 418: the text says 415; `runtime_abi()` says 418
    FAIL  build_stdlib_dylib.py: the quoted fire_runtime_h count is 810: the text says 807; `runtime_abi()` says 810
    (plus 6 more of the same shape)

## What was expected

Every count quoted in FORMAL.md, formal/build.py and build_stdlib_dylib.py
matches `runtime_abi()`.

## Likely cause and next step

`runtime_abi()` now reports 3 more words/symbols than the prose quotes, so the
runtime header gained declarations without the quoted numbers being updated
(or the scan now counts something it did not before). Next step: diff the
runtime header scan output against the last commit that updated these quoted
numbers, decide which side is right, then either update every quoted count in
one commit or fix the scan. Do not edit the test expectations to match.
