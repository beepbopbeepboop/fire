# FORMAL: `formal-os-backing`'s six remaining rows — 32-bit pointer loads not sign-extended, and `stat`'s `dev` width

**Area:** the formal backends (`formal/model.py` / `formal/build.py`), via
`test_formal_os_backing.py`. **Status: OPEN, measured 2026-10-07, PRE-EXISTING
on `master`.** These are the six failing rows now declared by the
`formal-os-backing` registration's `expect='6 of 70: …'`. Before this pass the
job was red with NO marker at all; the marker is added and this doc is the
subject it names.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os_backing.py
64/70 passed  (PASS=64 FAIL=6 of 70)
  FAIL    pointer_subscript_i32 [arm64]  2 of 4 answers wrong:
      a: the image says '8589934593000', the expected answer is '1000'
      b: the image says '12884901890000', the expected answer is '2000'
  FAIL    pointer_subscript_i32 [x86_64]  2 of 4 answers wrong:  (same two)
  FAIL    pointer_subscript_augmented [arm64]  1 of 2 answers wrong:
  FAIL    pointer_subscript_augmented [x86_64]  1 of 2 answers wrong:
  FAIL    stat_null [arm64]  1 of 5 answers wrong:
      m2: the image says 'size=0 ino=336 dev=2835028608 …', the expected answer is
          '… dev=18446744072249612928 …'
  FAIL    stat_null [x86_64]  1 of 5 answers wrong:  (same)
```

Three cases, each on both backends, so six FAIL lines.

## What each is

* **`pointer_subscript_i32` / `pointer_subscript_augmented`** — a 32-bit load
  through a pointer is answered as `8589934593000` where `1000` is expected
  (and `12884901890000` for `2000`). Those are `1000 * 2^33` and `2000 * 2^33`
  plus a small offset, i.e. a 32-bit value combined with the upper half of a
  64-bit word: the formal pointer model's i32 read is not sign/zero-extended
  before it is used. `pointer_subscript_i64` and
  `pointer_subscript_agrees_with_value` PASS, so the 64-bit path is right and
  this is the narrowing one.
* **`stat_null`'s `dev`** — the image says `dev=2835028608` (a 32-bit
  truncation) where CPython/`os.stat` answers `dev=18446744072249612928`
  (`0xffffffff...`, the full 64-bit `st_dev`). The `struct stat` field is being
  read at the wrong width.

## The exact next step

Both are value-model widths in the formal backends: the i32 pointer-load arm
needs the extension the i64 arm already has, and `stat`'s `dev` needs its
64-bit width. `formal/model.py`'s pointer/blob model and the `os` host module's
`stat` blob are the two homes. The cheapest measurement is the one command
above; it needs no Lean and 0.1 GB.
