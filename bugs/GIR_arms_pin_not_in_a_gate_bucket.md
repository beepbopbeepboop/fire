# The arms-extracted pin is registered in no bucket, so it went red unnoticed for a week

`test_gimple_arms_extracted.py` is the pin for `doc/GIR.md`'s "Stage 6, arms of
the giant functions": it requires `tools/extract_arm.py --list FILE PARENT 25`
to print `0 lines can be moved` for the eight giant lowering functions. Its
own docstring says so, and its own docstring's last line is the only thing
that ever runs it.

The pin was stated to be `0 lines can be moved` for all eight on 2026-11-15.
On 2026-11-21 it was 6/8 — two arms of `_lower_IdentExpr` and
`_lower_binary_tail` had been re-opened by later work (the stage-4
type-predicate codemods, `1b94b71d4`, and `70e483ef9`) — and nothing said so.
The three arms were re-extracted on 2026-11-22 (byte-identical C on both
`tools/pydiff_corpus` and `tools/cpp_core` corpora) and the pin is 8/8 again,
but the hole that let it regress is still open: **the test is in no bucket of
`tools/suite.py`, so no gate runs it**, and the next arm added to one of the
eight functions will go unnoticed the same way.

## What was measured

    $ python3 test_gimple_arms_extracted.py
    8/8 passed
    real 0.56            # 8 child `extract_arm.py --list` calls, no compile
    peak: 0.0 GB         # under `python3 tools/memslot.py --gb 8 --label x --`

That is a `tiny` job by the `MEMCLASS` table and well inside the
`doc/POLICY_memory_over_4gb.md` line, so the "known failure too expensive to
run" case for `disabled=` does not apply to it either.

## Expected

A test that exists to catch a regression in a fixed state must be run by the
everyday check. Register it as `arms-extracted` (`tiny`, driver `python3
test_gimple_arms_extracted.py`, bucket `check`) in `tools/suite.py`, then
`python3 tools/suite.py --list` must show it and `--dry-run check` must count
it. If the owners decide it belongs to a narrower bucket, the registration is
the same line either way; the point is that a gate observes it.

## Next step

Add the registration (one registry row plus `check` in the bucket list) and
run `python3 test_suite.py` — it checks that every registration is in a bucket
and that a stated status matches the registry. Nothing else in this doc's
subject needs code: the pin's arms are extracted and the C is identical.
