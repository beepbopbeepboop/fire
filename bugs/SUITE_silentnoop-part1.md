# SUITE_silentnoop-part1: Investigate the make check failure (silent noop)

**Parent BUG:** bugs/hard/SUITE_silentnoop.md  
**Class:** easy  

`make check` reported `silentnoop` failing (exit 1 / timeout) on 2026-11-08. This doc tracks an investigation-only slice.

## Scope
- Run the `silentnoop` job (`tools/suite.py silentnoop` or `python3 test_silent_noop_iter.py`) and capture the output.
- Determine whether the failure is:
  1. test timeout (remaining runtime > 900 s or 1500 s?)
  2. a specific compiled-case diverging from the CPython reference
  3. build error
- Record the exact cases that fail, if any.

## Not in scope
- Changing `tools/suite.py` timeouts (that's part2, or can be fixed directly if it's already done)
- Editing compiler code
- Merging the bug doc or deleting it

## Acceptance
- `build/suite.log` or the output of `python3 tools/suite.py silentnoop` attached / summarized inside this doc.
- If it's purely a timeout, part2 handles the fix.
- If specific cases fail, part2 must be updated accordingly with the exact cases and errors.