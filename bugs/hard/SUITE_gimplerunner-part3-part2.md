# SUITE_gimplerunner-part3-part2: wrong stdout values

## Goal

Decompose the "test expectation mismatches" of
`bugs/hard/SUITE_gimplerunner-part3.md` into the stdout half of it.

For each `gimplerunner`-flavoured compile-and-execute case that exits 0 but
prints incorrect text (wrong string formatting, raw address, wrong line endings,
or missing output), determine whether the generated GIMPLE code's stdout is
wrong or whether the recorded expectation is wrong.

## Acceptance

- The set of stdout-mismatch cases is listed with expected vs actual output.
- The plan distinguishes, per case, "compiler bug" from "wrong expected stdout".

## Done when

- One quick test proves the part is fixed, e.g. a new/updated
  `test_gimple_stdout_regression.py` asserting a compiled program prints the
  expected string; run via:
  `python3 tools/memslot.py --gb 8 --label gimplerunner-stdout -- \
      python3 test_gimple_stdout_regression.py`.

## NOT DONE

- [ ] Identify specific failing tests with wrong stdout output
- [ ] Compare expected vs actual stdout
- [ ] Determine if the bug is in the code or the test
- [ ] Create fix plan
