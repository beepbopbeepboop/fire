# TEST: `printf_float_operand_read_from_an_xmm_register` pins a C-side conversion this path has no domain for

**Area:** TEST — one row of `test_formal_x86_64_parity.py`. **Status: OPEN,
measured 2026-10-05, PRE-EXISTING on `master` (`86af1b44`)** — not caused by any
of the six branches that merge brought together. Its sibling in the same run
(`a_subscript_on_a_type_value_faulted_identically`) is already filed, at
`bugs/TEST_stale_needle_on_the_type_value_subscript_refusal.md`; this one has no
doc naming it, which is why it is a separate file rather than a line in that one.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_x86_64_parity.py
x86-64 formal parity: PASS=76 FAIL=2 (78 cases)
  FAIL  printf_float_operand_read_from_an_xmm_register: --backend=arm64 did not build: `x` printed 3.9's bit pattern as a decimal and `printf("[%.17g]", 7)` printed the integer as a denormal. Refused rather than converted, because the conversion is the source's decision and this path already has both of them: `Int(x)` truncates toward zero and `float(x)` rounds to the nearest double
  FAIL  a_subscript_on_a_type_value_faulted_identically: --backend=arm64 refused, but not with the expected words 'is a TYPE value': ...
```

The same two rows are red on `master`, which is the measurement that makes this
pre-existing rather than a merge artifact:

```console
$ (in a `git archive master` tree) python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_x86_64_parity.py
x86-64 formal parity: PASS=71 FAIL=2 (73 cases)
```

71/73 on master against 76/78 here: **the merge added five cases and all five
pass.** Both reds are the same two rows on both trees.

## What the row wants, and what it gets

The row builds a program that puts a binary64 value in an XMM register and hands
it to `printf` as a variadic operand. arm64 REFUSES it, and the refusal is
correct and well-worded: reading a `double` out of a variadic argument needs the
C-side conversion `double -> double` promoted through the default argument
promotions, and this path has no domain for it.

Two things follow, and they are different:

* **the refusal is right.** Nothing here is a wrong answer about a value, and
  `bugs/FORMAL_float_binary64_only.md` already records that binary64 is all this
  value model supports.
* **the row pins a needle the tree does not produce**, which is the same class as
  its sibling: a test asserting a diagnostic at a site where the tree refuses for
  a *different, more accurate* reason.

## Why it is not fixed here

Two lanes, neither of them this merge's:

* the underlying refusal belongs with `formal/model.py`'s float value model,
  which is the `project26:float` / `formal31-3` area, and
* the row itself is a test needle, which is the `bugs7-4` area (its own claim
  list carries `bug:TEST_a_parity_row_pins_a_needle_the_field_arm_never_says` and
  `bug:TEST_formal_parity_a_dtype_slot_needle_names_the_non_field_arm`, i.e.
  this exact family of stale parity needles).

## Exact next step

One edit, in the row that owns it. `test_formal_x86_64_parity.py`'s
`printf_float_operand_read_from_an_xmm_register` should assert the refusal the
tree ACTUALLY emits for this construct, the way its sibling
`a_subscript_on_a_type_value_faulted_identically` will once
`bugs/TEST_stale_needle_on_the_type_value_subscript_refusal.md` is taken.

The interesting question for whoever does it is which of two rows is right,
because they are opposite and only one can be:

* **pin the refusal** — arm64 has no `double`-through-variadic domain, and saying
  so is the honest row. That is what the arm64 message already says.
* **pin the x86-64 answer** — the row's name says the operand "read from an XMM
  register", and x86-64 has the `MOVQ`/`CVTSI2SD` forms that make it work; a row
  that asserts the x86-64 build RUNS and the arm64 build refuses by name is the
  one that documents a real difference between the two backends rather than a
  missing feature in one of them.

The second is the better row, and it is also the only one that makes the file's
name true — but choosing it is a decision about what the row is FOR, so it is not
a merge's to make.