# FORMAL: `test_formal_format_conformance.py` pins a `\uXXXX` divergence that master no longer has

**Status (2026-11-02):** found while verifying the float-print merge
(`work/fix-merge-fix-merge-bug-formal-formal-a-float-has-no-print-s`). Not fixed there: it is
outside that claim.

## What was run
`python3 test_formal_format_conformance.py` on master (`458c7dd5f`) and on the merged branch.

## What was seen
```
FAIL  [arm64]  unicode_escape prints the pinned '\\u00e9\n' (CPython: 'é\n'): printed 'é\n'
FAIL  [x86_64] unicode_escape prints the pinned '\\u00e9\n' (CPython: 'é\n'): printed 'é\n'
```

## What was expected
The `DIVERGENT_ROWS` entry at `test_formal_format_conformance.py` (~line 343) says a `\uXXXX`
escape is NOT decoded and pins the six-character output. Master's commits `1619dad87` and
`aeb9d1487` ("decode \uXXXX ... in the one shared decoder" / "front end: decode \uXXXX ...")
made the decoder answer `é`, which matches CPython. The row was not updated, so the pin is
now stale and the test is red on master.

## Next step
Move `unicode_escape` out of `DIVERGENT_ROWS` into the ordinary rows (expected `é\n`, the
CPython answer), and check the `FORMAL_string_value_model.md` / `FORMAL_LEXER` citations for
the same stale claim. Verify with `python3 test_formal_format_conformance.py` (expect 244/244).
