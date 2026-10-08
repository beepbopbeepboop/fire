# FORMAL_os_backing_sub_word_pointer_and_stat_dev_are_red: 6 of 70 cases in `test_formal_os_backing.py` disagree with CPython, on BOTH architectures, and no doc records either cause

**Area:** FORMAL — `formal/arm64_codegen.py` / `formal/x86_64_codegen.py`'s
subscript route, and `formal/hostmods/os/path/__init__.mojo::stat_dev`. **Filed,
NOT fixed**, and filed rather than taken because both live in areas another
worker holds: `FORMAL_pointer_value_model.md` is claimed by `formal132-docs` (it
is the umbrella for the pointer width model), and the `os` host module's stat
field reader is the `formal113/114` std-os lane. See "Why this is filed and not
fixed" at the end.

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label osb -- python3 test_formal_os_backing.py
…
FAIL    pointer_subscript_i32 [arm64]  2 of 4 answers wrong:
      a: the image says '8589934593000', the expected answer is '1000'
      b: the image says '12884901890000', the expected answer is '2000'
FAIL    pointer_subscript_i32 [x86_64]  2 of 4 answers wrong:   (identical)
FAIL    pointer_subscript_augmented [arm64]  1 of 2 answers wrong:
      a: the image says '90194313231', the expected answer is '15'
FAIL    pointer_subscript_augmented [x86_64]  1 of 2 answers wrong:   (identical)
FAIL    stat_null [arm64]  1 of 5 answers wrong:
      m2: the image says 'size=0 ino=336 dev=2835028608 blocks=0 blksize=65536',
          the expected answer is '… dev=18446744072249612928 …'
FAIL    stat_null [x86_64]  1 of 5 answers wrong:             (identical)
64/70 passed
```

Both architectures give byte-identical wrong answers, so the cause is shared
(`formal/model.py` + the shared route), not per-backend.

## Cause 1 — a declared `Pointer[Int32]` subscript loads 8 bytes, not 4

`pointer_subscript_i32`:

```mojo
var q: Pointer[Int32] = malloc(32)
q[0] = 1000
q[1] = 2000
q[2] = 3000
printf("a=%d@@", q[0])   # image 8589934593000, CPython 1000
printf("b=%d@@", q[1])   # image 12884901890000, CPython 2000
```

`8589934593000 == (2000 << 32) | 1000` and `12884901890000 == (3000 << 32) |
2000`: the element STRIDE is right (4) and the LOAD WIDTH is 8. `Pointer[UInt8]`
(width 1) and `Pointer[Int64]` (width 8) both pass, so the width is honoured for
1 and 8 and dropped for 2 and 4.

The shared model is right: `formal/model.py::subscript_base_lowering` returns
`("load", width, signed, why)` from `dereference_lowering`, and for `Int32` that
is `("load", 4, True)`. The emitter throws the width away in one place:

`formal/arm64_codegen.py::_emit_subscript_load` (its own docstring says "the
sub-word widths the pointee table can return (2 and 4) are the same two
instructions `_emit_dereference` uses for them" — and it does not emit them):

```python
if self._sub_width == 1:
    self.asm.emit(encode_ldrb_wd_wn(reg, base, 0))
else:
    self.asm.emit(encode_ldr_xt_xn_imm(reg, base, 0))     # 8 bytes for width 4
```

`_emit_dereference` (same file, the `.value()` spelling) is the correct
mapper: `width == 1` LDRB/LDRSB, `2` LDRH/LDRSH, `4` LDR W/LDRSW, else LDR X.
The same shape is in the two STORE sites that consult `_sub_width` —
`_emit_subscript_store` (`arm64_codegen.py:6098`) and `_emit_subscript_aug`
(`:6154`) — and in the x86-64 twins (`x86_64_codegen.py:6029`, `:8281`, `:8341`,
`:8376`). `_sub_signed` does not exist yet; the emitters discard `_signed` at
`arm64_codegen.py:5936` / `x86_64_codegen.py:5933`.

`pointer_subscript_augmented` is the same cause through the read-modify-write:
`q[0] += 5` reads 8 bytes (`10 | (q[1]<<32)`), so `a` prints
`(21 << 32) | 15` instead of `15`.

**Exact next step:** give the subscript route the width and signedness the model
already returns — carry `_sub_signed` beside `_sub_width` (set it everywhere
`_sub_width` is set: the blob stride `8`, the string byte `1/False`, the pointer
load `width/_signed`), and make `_emit_subscript_load` and the two store sites
select the instruction from `_sub_width` exactly as `_emit_dereference` does, on
BOTH backends. The store side truncates (`STRB`/`STRH`/`STR W`/`STR X`) and the
load side extends (LDRB/LDRSB/…/LDR X), which is what the pointer-value-model
doc's width table already specifies for `.value()`.

## Cause 2 — `stat_dev` on `/dev/null` reads the wrong 32 bits

`stat_null` calls `show("/dev/null")`; `os.path.stat_dev(p, 1)` is
`fs_stat_field32(p, follow, 0)` (`formal/hostmods/os/path/__init__.mojo:621`).
The image prints `2835028608` (`0xA9000000`); CPython prints
`18446744072249612928` (`0xFFFFFFFF_A8FB1A80`). The LOW 32 bits already differ
(`0xA9000000` vs `0xA8FB1A80`), so this is not a missing sign-extension — the
image and CPython are not reading the same four bytes. Every other stat shape
(`stat_dir`, `stat_dl`, `stat_fifo`, `stat_link`, …) passes, so it is specific to
the `/dev/null` path/size, which points at the fixture path or at the
`stat(2)`/`lstat(2)` call for a character device rather than at the offset table
in `_syscalls.mojo:1208`.

**Exact next step:** dump the raw `struct stat` for `/dev/null` with `ctypes` on
this host and compare offset 0 against the image's `fs_stat_field32(p, 1, 0)`
input; the `ctypes` layout is the ground truth the image's offset table was
measured against (the table's own comment records the measurement).

## Why this is filed and not fixed

Both causes belong to claimed lanes — `formal132-docs` holds
`bug:FORMAL_pointer_value_model` (the pointer width model and its emitters) and
the `os` stat reader is the std-os lane — and CLAUDE.md's rule for a worker is to
stop and report rather than edit another worker's area. Neither cause is
recorded in `FORMAL_pointer_value_model.md` or in any `FORMAL_std_os_*` doc I
could find, which is why this is filed rather than left to a sweep. It does NOT
block: `proofs` is not in `gate` (`tools/suite.py`'s `'gate': ['check',
'coroutine', 'stdlib', 'native', 'bootstrap']`), and `formal-os-backing` is in
`proofs` only, which is why the 6 reds have gone unobserved.
