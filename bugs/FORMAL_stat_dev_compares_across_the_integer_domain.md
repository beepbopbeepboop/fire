# FORMAL_stat_dev_compares_across_the_integer_domain: the oracle renders a 32-bit field as an unsigned 64-bit value the backend's signed integers cannot hold

**Area:** FORMAL, both backends — `test_formal_os_backing.py`'s `stat_*` cases
(one case per filesystem shape, the oracle being CPython's `os.stat` in the
test process). **Status: open, found 2026-10-07 while fixing the pointer-subscript
width bug; the backend answer is RIGHT and the comparison is the defect.**

## What I ran

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os_backing.py stat_null
FAIL    stat_null [arm64]  1 of 5 answers wrong:
      m2: the image says 'size=0 ino=336 dev=2835028608 blocks=0 blksize=65536',
      the expected answer is 'size=0 ino=336 dev=18446744072249612928 blocks=0 blksize=65536'
FAIL    stat_null [x86_64]  1 of 5 answers wrong:   (the same)
```

`stat_null` is the `/dev/null` case (`make_shapes` adds `chr` → `/dev/null`,
and the case name is `"stat_" + basename`). Every other shape and every other
field agrees; only `st_dev` differs, on both architectures.

## Why it is not the backend

`/dev/null`'s `struct stat.st_dev` is `dev_t`, which is **`int32_t`** on macOS.
The raw bytes are `0xa8fb1a80`, whose signed 32-bit value is `-1459938688` (the
low 32 bits of the oracle's value). The backend reads exactly those four bytes
(`formal/hostmods/os/_syscalls.mojo::fs_stat_field32`, the `stat_dev` reader at
`formal/hostmods/os/path/__init__.mojo:621`) as an unsigned 32-bit word and gets
`2835028608`, which is `0xa8fb1a80` — the right bytes.

CPython reports the field differently:

```console
$ python3 -c "import os; print(os.stat('/dev/null').st_dev)"
18446744072249612928
$ python3 -c "import ctypes,struct
> b=ctypes.create_string_buffer(256); ctypes.CDLL(None).stat(b'/dev/null',b)
> print(struct.unpack_from('<i',b.raw,0)[0], struct.unpack_from('<I',b.raw,0)[0])"
-1459938688 2835028608
```

`18446744072249612928 == 0xffffffffa8fb1a80`, i.e. CPython sign-extends the
signed 32-bit field to 64 bits and then renders it as an **unsigned** long. That
value is greater than `2**63`, so it is outside the signed 64-bit range the
formal path keeps an integer in — the build even refuses an integer *literal*
there (`formal/model.py`'s integer-overflow refusal, measured: a `4294967296 *
4294967296` source is rejected) — and `printf("%d", …)` on this path prints a
runtime negative value signed (measured: `0 - 1459942784` prints
`-1459942784`). So **no value the backend can produce prints as
`18446744072249612928`**, and the case cannot pass as written.

## The fix, and it is a DECISION about the test oracle

The backend's answer (`2835028608`, the 32-bit field unsigned) and CPython's
(`18446744072249612928`, sign-extended-to-64 then unsigned) agree on all 32 low
bits; only the rendering differs. Two ways to make the comparison honest, and
the second is preferred:

1. **Normalize the oracle's `st_dev` into the backend's domain** before building
   the string: `((v + 2**63) % 2**64) - 2**63` (signed 64-bit) and change
   `stat_dev` to sign-extend the field. Then both sides are `-1459942784`. This
   is the mod-2^64 comparison and it is the one that keeps CPython as the oracle;
   `fs_stat_field32` stays unsigned for `st_uid`/`st_gid` (`uid_t`/`gid_t` are
   unsigned and CPython renders them unsigned), so `stat_dev` needs its own
   signed reader rather than a change to the shared one.
2. **Mask the oracle to the field's own width**: compare `field(s, "st_dev") &
   0xffffffff`. Minimal, and it says "this field is 32 bits", but it is a
   comparison-only change that leaves the two sides' *values* different.

Either is a change to `_stat_oracle`, not to the host module, because the host
module already reads the field correctly. It is filed rather than fixed here
because it is a decision about how the suite compares an out-of-domain CPython
value, and the task that found it owned the pointer-subscript width bug, not
this one.

## The exact next step

Change `test_formal_os_backing.py::_stat_oracle`'s `m2` line to the chosen
comparison (option 1 with a signed `stat_dev`, or option 2), then re-run the
`stat_*` cases on both architectures. `stat_null` is the only case that fails,
and it fails only on `dev`; the other five fields in `m2` and every field in
`m1`/`l1`/`g1` already agree.
