# FORMAL Mach-O: the dylib's `__stubs` section fields, mach_header flags and `__DATA_CONST` protection all differ from what `ld` emits

**Area:** `formal/macho_linker.py` (`_write_text_segment`'s section writer and
`build_macho_dylib`) and `formal/macho.py` (the `MH_*` constants). Found
2026-10-07 while bisecting the x86-64 dylib outbound-call SIGSEGV, which turned
out to be a **different** bug (`__LINKEDIT`'s segment ORDER, fixed `3ac56981`).
These three are spec violations that match `ld`'s output and were deliberately
recorded rather than landed at the time.

## 1. `__stubs`' `reserved1`/`reserved2` are swapped

`<mach-o/loader.h>`: for a section with `type == S_SYMBOL_STUBS`, `reserved1` is
the **indirect-symbol-table index** and `reserved2` is **the size of one stub**.

`_write_text_segment` writes the section tuple's 6th element into `reserved1`
(currently the stub size, `ssize`) and hardcodes `reserved2 = 0`:

```python
for name, vmaddr, size, fileoff, flags, reserved1 in sections:
    ...
    patch(s + 68, "<I", reserved1)
    patch(s + 72, "<I", 0)      # reserved2
```

The three call sites pass `ssize` as that 6th element
(`formal/macho_linker.py`'s `build_macho_executable`, `..._extern` and
`build_macho_dylib`). `ld` emits `reserved1 0 / reserved2 6` for x86-64 (12 for
arm64). Verified: patching an emitted `reserved2` to the stub size makes
`otool -l` read like `ld`'s; it does not change whether the image runs.

**Fix:** make the tuple's extra field mean the *stub size* and write it to
`reserved2` (offset 72), with `reserved1` (offset 68) taking the indirect-symbol
index (0 when there is no indirect symbol table entry to name). `test_formal_*`
should compare `otool -l`'s two fields against `ld`'s for one linked module.

## 2. dylib mach_header flags are wrong, and so are three `MH_*` constants

`build_macho_dylib` hardcodes `0x800005` =
`MH_NOUNDEFS | MH_DYLDLINK | MH_HAS_TLV_DESCRIPTORS`. That is **missing
`MH_TWOLEVEL`** and sets a TLV-descriptor bit the library does not have; `ld`
emits `0x100085` for the same dylib
(`MH_NOUNDEFS | MH_DYLDLINK | MH_TWOLEVEL | MH_NO_REEXPORTED_DYLIBS`).

The root cause is in `formal/macho.py`, whose constants are aliased onto other
flags:

| constant | current | correct |
|---|---|---|
| `MH_TWOLEVEL` | `0x00800000` | `0x00000080` |
| `MH_BIND_AT_LOAD` | `0x00000002` (`MH_INCRLINK`) | `0x00000008` |
| `MH_DEAD_STRIPPABLE_DYLIB` | `0x00002000` (`MH_SUBSECTIONS_VIA_SYMBOLS`) | `0x00400000` |

None of the three is read anywhere in the tree today (checked: the only mention
is the prose at `formal/macho_linker.py:376`), so correcting them is safe.

**Fix:** correct the three constants and use them for the dylib header rather
than the literal. A test should read the dylib's header flags back and compare
against the set `ld` emits.

## 3. `__DATA_CONST` does not carry `SG_READ_ONLY`

`ld` sets `SG_READ_ONLY` (`0x10`) on `__DATA_CONST` for executables and
libraries alike — the segment that carries the `__got` and is written only by
dyld's binding pass. This tree leaves the segment flags `0x0`.

**Fix:** OR `0x10` into `__DATA_CONST`'s segment flags. Hardening only, but it
is what the loader is being told to expect.

## Why this is filed rather than fixed

Each of the three is an independent, low-severity emitter-conformance item, and
none of them is on the path of the defect that was under investigation. Landing
them means re-reading every container's `otool -l` against `ld`'s and running
the dylib-loading rows (`test_formal_run.py`, `test_formal_interop.py`), which
is its own change; this doc is the record so the next reader does not have to
re-bisect to find them. The measurements above are from the original bisect and
have not been re-confirmed on the current tree beyond the code shape.
