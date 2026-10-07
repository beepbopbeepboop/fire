# `formal-os-backing` is registered with NO marker and is red 6 of 70 on `master`

## Status

OPEN, measured, NOT fixed here — pre-existing on `master`, and two of the three
root causes are not this worker's write set (see "Whose"). Filed because a
registered job that is red with no marker is the specific hole CLAUDE.md's
`expect=`/`disabled=` rule exists to close, and because the number is stable
enough to hand over as a claim.

**The doc's earlier state (28/58, thirty failures, all the non-ASCII
string-subscript refusal) is superseded and gone**: the `FOREIGN_BYTES_KIND` work
closed that wall, the file grew from 58 to 70 rows, and the failures left are a
different, smaller set. Re-measured 2026-10-07 (`formal112-docs`).

## What I ran, and what I saw

```console
$ python3 tools/memslot.py --gb 8 --label osback -- python3 test_formal_os_backing.py
FAIL pointer_subscript_i32 [arm64]   2 of 4 answers wrong: a '8589934593000' != '1000'; b '12884901890000' != '2000'
FAIL pointer_subscript_i32 [x86_64]  (the same two, byte-identical)
FAIL pointer_subscript_augmented [arm64]  1 of 2 wrong: a '90194313231' != '15'
FAIL pointer_subscript_augmented [x86_64] (the same)
FAIL stat_null [arm64]   1 of 5 wrong: m2 dev '2835028608' != '18446744072249612928'
FAIL stat_null [x86_64]  (the same)
64/70 passed
```

Six failures, three shapes, and each shape is byte-identical on the two
architectures — so each is ONE root cause reached through both backends.

## The three root causes

### 1. A `Pointer[Int32]` SUBSCRIPT reads and stores EIGHT bytes (4 rows)

`8589934593000` is `2000 << 32 | 1000`: an 8-byte load at `q+0` over a `q` whose
`q[0]` and `q[1]` are each 4 bytes. `q[1]`'s `12884901890000` is `3000 << 32 |
2000`, and the augmented row's `90194313231` is `21 << 32 | 15` — the same
over-read through the read-modify-write.

The width is DECIDED correctly and then not emitted.
`model.subscript_base_lowering` answers `("load", 4, True)` for a `Pointer[Int32]`
base, and `arm64_codegen._emit_subscript_addr` records it in `self._sub_width`.
But the two consumers only special-case width 1:

* `formal/arm64_codegen.py::_emit_subscript_load` (around line 5322) —
  `if self._sub_width == 1: ldrb else: ldr x`. A width of 2 or 4 falls to the
  64-bit `ldr`, and the docstring even says the sub-word widths "are the same two
  instructions `_emit_dereference` uses for them" while the code does not emit
  them.
* the same `if width == 1 … else str x` in `_emit_subscript_store_reg`
  (line ~6098) and `_emit_subscript_aug` (line ~6154), so the STORE is 8 bytes
  too.

The correct arms are three lines away, in `_emit_dereference`
(`formal/arm64_codegen.py:6895-6905`) and `_emit_pointer_store` (`:6950-6957`):
`ldrsh`/`ldrh`, `ldrsw`/`ldr w`, `strh`, `str w`. The signedness is also needed
and is currently discarded at the `subscript_base_lowering` call site
(`shape, width, _signed, sub_why`), so a `_sub_signed` beside `_sub_width` is part
of the fix. The x86-64 twin (`formal/x86_64_codegen.py`) has the same shape and
must be fixed in the same commit, because a one-sided fix makes the two
architectures answer one construct differently.

`Pointer[UInt8]` (width 1) and `Pointer[Int64]` (width 8, the `else`) pass, which
is why this survived: the only failing widths are 2 and 4.

### 2. `stat_dev` zero-extends a 4-byte field where CPython sign-extends it (2 rows)

On this host `os.stat("/dev/null").st_dev` is `18446744072249612928` =
`0xffffffffa8fb1a80`, and the image's `stat_dev` answers `2835028608` =
`0xa8fb1a80` — the low 32 bits, not sign-extended. `stat_null` is the `/dev/null`
shape; it passes on a machine whose `st_dev` has a clear high bit, which is why
the case is machine-dependent and only this box sees it.

The field reader is in `formal/hostmods/os` (and the `stat` field table in
`formal/model.py`); the fix is the same one shape #1 is: a signed 4-byte field
must be loaded sign-extending (`ldrsw` / `movslq`) and the word the reader
produces must be the sign-extended one.

### 3. The harness detail, not a bug: the count is the sum of the two

`pointer_subscript_i32` is 2 of 4 wrong, `pointer_subscript_augmented` 1 of 2,
`stat_null` 1 of 5: **4 + 1 + 1 = 6**, and the count in the summary line is what
an `expect=` marker would be checked against.

## Whose

* **Shape #1 is `bugs/FORMAL_pointer_value_model.md`'s territory and that doc is
  a LIVE CLAIM** (`formal113-docs`, `python3 tools/control.py claims`). The
  recogniser (`subscript_base_lowering`) is correct; the EMITTER that ignores its
  width is the part that has to change, and it is the same file the pointer value
  model owns. **This worker did not edit it** — rule 5 — and files the exact
  location instead.
* **Shape #2 has no live claim**; `grep` over `tools/control.py claims` finds
  nothing for `stat`/`os_backing`. The `stat(2)` out-parameter was once
  unreadable (`isfile` could not be exact); that bug was fixed and its doc
  deleted with the fix, `fd79ee2a`, which is the commit that ADDED `stat_null`.

## The exact next step

1. **Shape #1**: give `_emit_subscript_load`, `_emit_subscript_store_reg` and
   `_emit_subscript_aug` the 2/4-byte arms `_emit_dereference` and
   `_emit_pointer_store` already have, carrying the pointee's signedness out of
   `subscript_base_lowering`, on BOTH `formal/arm64_codegen.py` and
   `formal/x86_64_codegen.py`. Pin with `test_formal_os_backing.py`'s
   `pointer_subscript_i32`/`pointer_subscript_augmented` (already red) plus a
   `Pointer[Int16]`/`Pointer[UInt32]` row so the other sub-word widths are covered.
2. **Shape #2**: sign-extend the 4-byte signed `stat` fields. Pin with
   `stat_null` (already red) and, to be machine-independent, a hand-written
   struct whose `st_dev` has its high bit set rather than `/dev/null`'s.
3. Only then decide the marker: with both fixed the job is green and needs none;
   if either is left open it needs `expect='<n> of 70: <the class>'`.

Cheap to re-measure: 0.1 GB, a few seconds, no Lean.
