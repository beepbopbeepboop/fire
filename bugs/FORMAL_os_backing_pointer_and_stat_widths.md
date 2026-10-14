# FORMAL: `formal-os-backing`'s remaining red — `stat`'s `dev` field is zero-extended, and the 32-bit pointer-subscript class that sat beside it is fixed

**Area:** the formal backends (`formal/model.py` / `formal/build.py` / the
emitters), via `test_formal_os_backing.py`. **Status: OPEN, measured 2026-10-12
on the merged tree (`work/merge-qwen1`), PRE-EXISTING on `master`.** This doc
is the subject the `formal-os-backing` registration's
`expect='2 of 70: …'` names.

## What the registration looked like, and what the merge changed

The job was registered with no marker and red (its own doc, deleted with this
fix pass, carried the 2026-10-08 state: 6 of 70, three cases on both
backends). `work/bugs-oct7-4` marked the 6 on 2026-10-07 with this doc's
superseded title — **32-bit pointer loads not sign-extended, and `stat`'s
`dev` width** — and taught the harness to print a `PASS=n FAIL=m` shape so the
count is checkable. **On the merged tree the 6 is a 2**: the 32-bit
pointer-subscript class is fixed on master, and the only reds left are
`stat_null`, on both backends.

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os_backing.py
68/70 passed  (PASS=68 FAIL=2 of 70)
  FAIL    stat_null [arm64]   1 of 5 answers wrong:
      m2: the image says 'size=0 ino=336 dev=2835028608 …', the expected
          answer is 'size=0 ino=336 dev=18446744072249612928 …'
  FAIL    stat_null [x86_64]  (the same)
```

## The fixed half, and what the fix was

The 2026-10-07 pass measured `pointer_subscript_i32` answering
`8589934593000` where `1000` was expected (`2000 << 32 | 1000`: an 8-byte load
over a 4-byte element, reading the neighbour's bytes as its own high half) and
`pointer_subscript_augmented` clobbering the next slot through the
read-modify-write. The diagnosis, from the superseded doc's measurement: the
width was DECIDED correctly — `model.subscript_base_lowering` answers
`("load", 4, True)` for a `Pointer[Int32]` base — and then not emitted: the
emitters' tests were `if self._sub_width == 1: …l…b else: …64-bit…`, so a width
of 2 or 4 fell to the 64-bit instruction, on BOTH backends, and the
`signedness` was discarded at the call site. `Pointer[UInt8]` (width 1) and
`Pointer[Int64]` (width 8) passed, which is why it survived: the only failing
widths were 2 and 4.

Master fixed it in exactly the shape the diagnosis named: one place per
backend, the four loads/STORES chosen by the element's WIDTH and its
SIGNEDNESS — `formal/arm64_codegen.py::_emit_subscript_load`
(`ldrsb`/`ldrh`/`ldrsh`/`ldrsw`/`ldr w`/`ldr` off `_sub_width` and
`_sub_signed`) and `_emit_subscript_store_at`, and the x86-64 mirror in
`formal/x86_64_codegen.py` (`movsx`/`movzx`/`mov r32`/`mov r64`), both reading
`_sub_width`/`_sub_signed` set by `_emit_subscript_addr` from the same
`pointee` tuple, "so the address and the load cannot disagree." The parity
differential's `aug_through_int32_pointer` case is the one that found it, on
both backends, once Rosetta could run the x86-64 half — the same case whose
existence explains why the branch's parallel `formal-x86-64-parity`
registration claimed three reds of which two were this class, and why master's
registration claims one.

## The remaining red: `stat`'s `dev` zero-extends a signed field

On this host `os.stat("/dev/null").st_dev` is `18446744072249612928` =
`0xffffffffa8fb1a80`, and the image's `stat_null` answers `2835028608` =
`0xa8fb1a80` — the low 32 bits, **zero-extended where CPython sign-extends**.
The `struct stat`'s `dev` field is a signed 4-byte `int32` on this platform,
and the formal path reads it at 4 bytes without the sign extension the 64-bit
word then needs. `stat_null` is the `/dev/null` shape; it passes on a machine
whose `st_dev` has a clear high bit, which is why the case is machine-dependent
and only this box sees it (the other `stat_*` rows pass: their `dev` values
are small).

The field reader is in `formal/hostmods/os` (and the `stat` field table in
`formal/model.py`); the fix is the same shape as the subscript one just
landed: a signed 4-byte field must be loaded sign-extending (`ldrsw` /
`movslq`), and the word the reader produces must be the sign-extended one.
`bugs/FORMAL_string_value_model.md`'s territory is the string half; this is
the struct-field half of the same width-and-signedness class.

**Whose:** no live claim covers it (`grep` over `tools/control.py claims`
finds nothing for `stat`/`os_backing`). The `stat(2)` out-parameter was once
unreadable (`isfile` could not be exact); that bug was fixed and its doc
deleted with the fix, `fd79ee2a`, which is the commit that ADDED `stat_null`.

## The exact next step

1. Sign-extend the 4-byte signed `stat` fields in the reader
   (`formal/hostmods/os` + the `stat` field table in `formal/model.py`), the
   same width-and-signedness rule the subscript fix just settled for
   elements.
2. Pin with `stat_null` (already red) and, to be machine-independent, a
   hand-written struct whose `st_dev` has its high bit set rather than
   `/dev/null`'s.
3. Then the marker is green and comes off: `expect=` on a passing job reports
   itself as a FAILURE, which is the anti-rot half of the mechanism.

Cheap to re-measure: 0.1 GB, seconds, no Lean.
