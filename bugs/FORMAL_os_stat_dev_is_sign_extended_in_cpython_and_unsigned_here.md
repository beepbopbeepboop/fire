# `stat_dev` answers the low 32 bits unsigned; CPython answers them sign-extended, and `test_formal_os_backing.py`'s `stat_null` compares the two with `%d`

**Status: OPEN, measured 2026-10-08 on this machine, and it is a TEST-ORACLE /
representation mismatch rather than a backend defect.** `test_formal_os_backing.py`
is 68/70 on this tree; both failures are the same case, `stat_null`, on BOTH
architectures, identically.

## What I ran, and what I saw

```console
$ python3 tools/memslot.py --gb 8 --label t1 -- python3 test_formal_os_backing.py
FAIL    stat_null [arm64]  1 of 5 answers wrong:
      m2: the image says 'size=0 ino=336 dev=2835028608 blocks=0 blksize=65536',
      the expected answer is 'size=0 ino=336 dev=18446744072249612928 blocks=0 blksize=65536'
FAIL    stat_null [x86_64]  1 of 5 answers wrong:  (byte-identical)
```

The expected value is CPython's own `os.stat(p).st_dev` formatted with `%d` by
`_stat_oracle`; the image's value is `formal/hostmods/os/path/__init__.mojo`'s
`stat_dev`, which reads 32 bits at offset 0 through `fs_stat_field32`'s `le32`
and so **zero-extends**. The raw field is `0xa8fb1a80`:

```console
$ python3 -c "import os; st=os.stat('/dev/null'); print(st.st_dev, hex(st.st_dev))"
18446744072249612928 0xffffffffa8fb1a80
```

`0xa8fb1a80` is `dev_t` = `int32_t` on Darwin, and CPython reports it as the
**sign-extended** 64-bit pattern (`0xffffffffa8fb1a80`); this path reports
`0x00000000a8fb1a80`. Both are "the same 32 bits".

## Why it is not a one-line sign-extension

The obvious repair — return `le32(...) - 2**32` when bit 31 is set — does NOT
make the test pass, and the measurement is why: this path's `printf("%d", x)` is
a **signed 64-bit** print (measured with a two-line program:
`printf("%d", 0 - 1459938688)` prints `-1459938688`), while CPython's `%d` over a
Python int prints `18446744072249612928`. So even with `stat_dev` sign-extended
the image would print `dev=-1459938688`, and the oracle's string is not
representable as a signed 64-bit value at all.

## The next step (a decision, not a patch)

One of two, and the first is the honest one:

1. **Fix the ORACLE, then decide the hostmod.** `_stat_oracle` should compare the
   field in a domain both sides can represent — mask CPython's `st_dev` to 32
   bits, or compare `st_dev & 0xffffffff` against the image's value — because a
   `dev_t` is 32 bits in the ABI and neither reading is more "the device" than
   the other. That makes `stat_null` a statement about the 32 bits.
2. **Or give `stat_dev` a signed reading and make the case not print it with
   `%d`.** Matching CPython's *unsigned* presentation needs a `%u`/`%llu`-style
   format this path does not have for that case, so this is the larger change and
   it buys nothing a 32-bit comparison does not.

Either way, `test_formal_os_backing.py` is a registered job in the `proofs`
bucket (not in `check`/`gate`) and its **registrations** are already tracked by
`TEST formal os backing is red with no marker`, whose count (30 of 58,
all the non-ASCII string class) is now STALE — the non-ASCII class is fixed and
what is left is this one case, 2 of 70. That document is the right one to update
with the new number; this one exists so the `stat_dev` subject has a home.

**Reproducing:** the two commands above; no Lean, 0.1 GB.
