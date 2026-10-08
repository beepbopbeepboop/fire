# FORMAL_pointer_subscript_loads_a_word_for_a_sub_word_pointee: `p[i]` on a `Pointer[Int32]` reads eight bytes, and `formal-os-backing` is red for it

**Area:** FORMAL, both backends — `formal/arm64_codegen.py::_emit_subscript_load`
(and `formal/x86_64_codegen.py::_emit_subscript`, whose read is inline).
**Status: OPEN, root-caused, NOT fixed — it lands in `FORMAL_pointer_value_model`'s
lane (`formal132-docs` holds that claim, and is not alive at filing), so this is
reported rather than edited.** Found 2026-10-07 (`work/formal143-docs`) while
running the test file one of this task's own docs cites.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label tob -- python3 test_formal_os_backing.py
FAIL    pointer_subscript_i32 [arm64]  2 of 4 answers wrong:
      a: the image says '8589934593000', the expected answer is '1000'
      b: the image says '12884901890000', the expected answer is '2000'
FAIL    pointer_subscript_i32 [x86_64]  2 of 4 answers wrong:
      a: the image says '8589934593000', the expected answer is '1000'
      b: the image says '12884901890000', the expected answer is '2000'
FAIL    pointer_subscript_augmented [arm64]  1 of 2 answers wrong:
      a: the image says '90194313231', the expected answer is '15'
FAIL    pointer_subscript_augmented [x86_64]  1 of 2 answers wrong:
      a: the image says '90194313231', the expected answer is '15'
FAIL    stat_null [arm64]  1 of 5 answers wrong:
      m2: the image says 'size=0 ino=336 dev=2835028608 …',
          the expected answer is 'size=0 ino=336 dev=18446744072249612928 …'
FAIL    stat_null [x86_64]  1 of 5 answers wrong:
      m2: the image says '… dev=2835028608 …', the expected answer is '… dev=18446744072249612928 …'

64/70 passed
```

`formal-os-backing` is registered in `tools/suite.py` with no `expect=` marker, so
this is a red gate job and not a declared one. **This is a DIFFERENT red from
`bugs/TEST_formal_os_backing_is_red_with_no_marker.md`**, whose subject (30 of 58,
every one the non-ASCII string-subscript refusal) is fixed: the `listdir`/`len`/
readdir rows this task's docs are about now all PASS, and the 6 above are the
residual. That TEST doc's `expect=`/green decision is still owed, and it is now
owed against THESE six.

## The arithmetic, which is the root cause

`8589934593000 = 1000 + 2000 * 2**32` and `12884901890000 = 2000 + 3000 *
2**32`; `90194313231 = 15 + 21 * 2**32`. So the STORE path is right (four bytes,
stride four: element 1 lands at byte 4) and the READ path loads **eight** bytes
at `base + i*4`, folding the next `Int32` into the high half of the word. Nothing
about the value is subtle once the numbers are read that way.

`formal/arm64_codegen.py:5322`:

```python
def _emit_subscript_load(self, reg: int, base: int) -> None:
    """Load one element through X{base} into X{reg}, at `_sub_width`.
    ...
    anything wider is the full 64-bit load, and the sub-word widths the pointee
    table can return (2 and 4) are the same two instructions
    `_emit_dereference` uses for them.
    """
    if self._sub_width == 1:
        self.asm.emit(encode_ldrb_wd_wn(reg, base, 0))
    else:
        self.asm.emit(encode_ldr_xt_xn_imm(reg, base, 0))   # 8 bytes, width 2/4/8
```

The docstring describes the four arms `_emit_dereference` has
(`arm64_codegen.py:6895-6905`: LDRB/LDRSB, LDRH/LDRSH, LDR/LDRSW, LDR X), and the
implementation has one and a fallback. `formal/x86_64_codegen.py:6028` is the
same: an unconditional `mov rax, [rax]` (eight bytes) with a `movzx` only for
`_sub_width == 1`.

`subscript_base_lowering` (`formal/model.py:18196`) already returns the right
`(shape="load", width, signed)` — its docstring is explicit that the caller
"emits `base + i*width` and a load of `width` bytes, which is the same
instruction pair `_emit_dereference` emits for `p.value()`". The call site at
`arm64_codegen.py:5936` reads the triple as
`shape, width, _signed, sub_why` and **discards `_signed`**, and passes only
`width` (via `self._sub_width`) to a loader with no signedness. So width 4 gets
an unsigned-or-anything 64-bit read and width 2 would too.

## The exact next step

Give `_emit_subscript_load` the four arms `_emit_dereference` has, carrying
`_signed` alongside `_sub_width` (the x86-64 twin the matching width forms), and
make `Pointer[Int32]`/`Int16`/`UInt32`/`UInt16` reads load exactly their width.
`pointer_subscript_i32` and `pointer_subscript_augmented` then pass, and the
signed widths get the extension the source declares rather than a guess.

**`stat_null`'s `dev` is the same shape but a separate site and needs its own
look:** the image answers `2835028608` where CPython answers
`18446744072249612928`, i.e. the low 32 bits zero-extended where the oracle
sign-extends `st_dev` (`-1459938688` as a 64-bit two's complement) — so
`formal/hostmods/os/_syscalls.mojo`'s `stat_dev` reads a signed field as an
unsigned one. It may or may not share the root above; that is the first thing to
measure once the subscript load is width-correct.

## Why this is filed and not fixed here

The pointer width/scale question is `bugs/FORMAL_pointer_value_model.md`'s
subject (`formal132-docs` holds `bug:FORMAL_pointer_value_model` in
`tools/control.py claims`), and this file is a regression of the pointee-width
contract that doc's §9 records as closed. Editing it from this task would be
working in another worker's lane; the measurement and the line numbers above are
what that lane needs.
