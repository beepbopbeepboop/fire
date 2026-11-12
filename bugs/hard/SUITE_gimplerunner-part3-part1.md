# SUITE_gimplerunner-part3-part1: wrong return values

## Goal

Decompose the "test expectation mismatches" of
`bugs/hard/SUITE_gimplerunner-part3.md` into the return-value half of it.

For each `gimplerunner`-flavoured compile-and-execute case that exits 0 with a
plausible-but-wrong program result, the question under investigation is whether
the generated GIMPLE code's return value (or the program's chosen exit value) is
wrong, or whether the expectation recorded for it is wrong.

## Acceptance

- The set of return-value-mismatch cases is listed with expected vs actual values.
- The plan distinguishes, per case, "compiler bug" from "wrong expected value".

## Done when

- One quick test proves the part is fixed, e.g. a new/updated
  `test_gimple_return_value_regression.py` asserting a compiled program returns
  the expected value; run via:
  `python3 tools/memslot.py --gb 8 --label gimplerunner-return-value -- \
      python3 test_gimple_return_value_regression.py`.

## NOT DONE

- [ ] Identify specific failing tests with wrong return values
- [ ] Compare expected vs actual return values
- [ ] Determine if the bug is in the code or the test
- [ ] Create fix plan
