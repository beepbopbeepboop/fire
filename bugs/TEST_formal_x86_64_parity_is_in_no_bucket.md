# TEST: `test_formal_x86_64_parity.py` is in NO bucket, and its one red row is
# the whole reason it matters

**Area:** TEST — the estate check's own class, applied to the file that holds it.
**Status: OPEN, measured 2026-10-05 while merging the `gate34` batch.** Not
caused by the batch: the file was unregistered before it, and the red row inside
it is already filed at
`bugs/TEST_a_parity_row_pins_an_xmm_float_operand_the_tree_refuses.md` as
PRE-EXISTING on `master` (`86af1b44`).

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ grep -n "test_formal_x86_64_parity.py" tools/suite.py
$ # no output
$ grep -rn "x86_64_parity" bugs/UNTESTED.md test_suite.py
$ # no output
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_x86_64_parity.py
x86-64 formal parity: PASS=78 FAIL=1 (79 cases)
  FAIL  printf_float_operand_read_from_an_xmm_register: --backend=arm64 did not build:
    `x` printed 3.9's bit pattern as a decimal and `printf("[%.17g]", 7)` printed
    the integer as a denormal. Refused rather than converted, because the
    conversion is the source's decision and this path already has both of them:
    `Int(x)` truncates toward zero and `float(x)` rounds to the nearest double
```

## Why this is a bug and not a note

The file is in no bucket, so **no gate runs it**, and it is also in no
`UNREGISTERED` exemption list — which is the shape `test_suite.py`'s estate check
was written for and the shape it reports: a test file that is neither registered
nor excused, so the census counts it as covered while no run executes it.

And the thing it is not running is the only evidence anyone has for the red
above. `bugs/TEST_a_parity_row_pins_an_xmm_float_operand_the_tree_refuses.md`
records that measurement and says it is pre-existing on `master`; nothing in any
gate would notice if a second row joined it, and nothing would notice if the file
stopped parsing.

That is the same failure the `formal-bracketed-method-field-set` registration
comment calls "a coverage hole and not a stale entry", and the reason
`formal-field-walk`, `formal-host-import-wall` and `formal-per-struct-asks` were
all registered on 2026-10-04 after the estate check named them.

## The exact next step

One registration, on the cost rule the three above it used:

1. Measure it — `python3 tools/memslot.py --gb 8 --label t -- python3
   test_formal_x86_64_parity.py` is 79 cases that each BUILD AND EXECUTE a
   formal image on both backends, so the number to record is seconds and peak
   GB from that run, not an estimate.
2. `test('formal-x86-64-parity', [PY, 'test_formal_x86_64_parity.py'], mem=…,
   cache=True, deps=['preflight'], extra=[…], expect="1 of 79: …", desc=…)`,
   with `mem` taken from the measurement. It is very likely `small` or `module`,
   not `tiny`, unlike its three neighbours — which is exactly why it was left
   ungated rather than noticed.
3. The marker: the file is 78/79 and the one red is the filed one, so `expect=`
   with its count stated in the leading prose (which is what the count-checked
   rows require) and `desc` naming it.
4. The budget exemption list (`STALE_PER_CHILD_BUDGETS`) gains the file if it
   spells any per-child timeout as a literal — the census is exact and an
   unlisted file with a literal is a failure, not an omission.
5. `bugs/UNTESTED.md` loses the entry, if it has one for this file after the
   registration lands — it does not name it today, which is the other half of
   the hole: nothing records that this file was never gated.

Whoever takes it does not need Lean and does not need a gate: steps 1-5 are a
registration and a measurement.