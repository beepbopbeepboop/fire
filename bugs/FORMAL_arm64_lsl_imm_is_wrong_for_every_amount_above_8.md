# FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8: `x << 9` and above computes something else

**Status: OPEN. Found while writing `hashlib` (2026-09-29, the
`module:hashlib` claim); it is a one-constant fix in `formal/arm64.py`, which
that claim does not own, so it is filed rather than applied. Until it lands,
`formal/hostmods/hashlib.mojo` writes its 64-bit rotations with a VARIABLE
shift amount, which is a different instruction and is correct — see "What the
hashlib module does about it" below.**

This is a **wrong answer, not a refusal**, which is why it is written down
rather than worked around quietly: `1 << 12` returns `16`, and `16` is
plausible enough to pass an eyeball.

---

## What I ran

```
$ cat > .tmp/w/lsl.mojo
def f12(x: int) -> int:
  return x << 12
def main() -> int:
  printf("%lld@@", f12(1))
  return 0
$ python3 fire.py build --formal --no-prove -o .tmp/w/lsl .tmp/w/lsl.mojo
$ .tmp/w/lsl
16
```

`1 << 12` is `4096`.

## What I saw

Every shift amount from **1 through 8 is correct and every amount from 9
through 63 is wrong**, on arm64, and only the `<<` direction. Measured over
all 64 amounts with `x = 0x0123456789ABCDEF`:

| shift | got | want |
|---|---|---|
| `<<8` | `0x23456789abcdef00` | `0x23456789abcdef00` ✓ |
| `<<9` | `0x00468acf13579bde` | `0x468acf13579bde00` |
| `<<12` | `0x003456789abcdef0` | `0x3456789abcdef000` |
| `<<16` | `0x00456789abcdef00` | `0x456789abcdef0000` |
| `<<32` | `0x00000089abcdef00` | `0x89abcdef00000000` |
| `<<63` | `0x0000000000000080` | `0x8000000000000000` |

Three facts that narrow it to one line, all measured rather than inferred:

1. **The VARIABLE form is correct.** `def g(x, n): return x << n`, called as
   `g(1, 12)`, returns `4096`; `g(1, 32)` returns `4294967296`. So the shift is
   right and the immediate form is wrong — which is a different bug from "the
   shift is wrong".
2. **`>>` is correct at every amount**, immediate and variable: `x >> 4`, `>>9`,
   `>>12`, `>>16`, `>>32` all match. Only `<<`.
3. **x86-64 is correct.** The same file with `--backend x86_64` returns `4096`,
   `65536` and `1048576` for `<<12`, `<<16` and `<<20`. So this is arm64-only
   and the two backends do not share the code that does it.

## Why

One constant, in `formal/arm64.py:579`:

```python
def encode_lsl_xd_xn_imm(xd: int, xn: int, shift: int) -> bytes:
    """LSL Xd, Xn, #shift (immediate, 0..63). UBFM-based.
    Encoding: UBFM Xd, Xn, #(-shift mod 64), #(63-shift)
    sf=1, opc=10, 100110, N=1 → 0xd3400000 base with immr/imms.
    """
    immr = (-shift) & 63
    imms = 63 - shift
    insn = 0xd3780000 | (immr << 16) | (imms << 10) | (xn << 5) | xd
```

**The docstring names the right base (`0xd3400000`) and the code uses
`0xd3780000`.** The two differ by `0x00380000`, which is inside `immr`'s field
(`immr` occupies bits 21:16). So the base pre-loads `immr` with `0x38`, and
because the code ORs the real `immr` into the same field, the emitted value is

    immr_emitted = immr_intended | 0x38

which is exactly what the measurements show. Verified for all 64 shift
amounts: the emitted `immr` equals `((-shift) % 64) | 0x38` every time, and
the amounts where that OR is harmless — where the intended `immr` already has
bits 3, 4 and 5 set — are precisely **1 through 8**, which is precisely the
set of amounts that work.

The `0x8` in `0x38` is bit 3 of the field, so the amounts that survive are
those whose `-shift mod 64` has bit 3 set, i.e. shift ≡ 0..7 (mod 16) with
the low three bits non-zero. That predicts 1-8 correct and everything else
wrong, and 1-8 is what is observed. A one-constant bug with a boundary at 8 is
a strong fingerprint, and the disassembled encoding in the built image
(`d37ccc00` for `<<12`, where the assembler's own `lsl x0, x0, #12` is
`d374cc00`) confirms the field, not the operand: `immr` is 60 where it should
be 52, and `Rn`/`Rd` are both right.

The comparison above is against **clang's own assembler**, assembling
`lsl x0, x0, #N` for N in {0,1,8,9,12,16,32,63} on
`arm64-apple-macos11`. So this is not a disagreement between two readings of
the ARM ARM; it is disagreement with the toolchain.

## What I expect

`f12(1) == 4096`, and every amount 0..63 to shift by exactly that much.

## The exact next step

Change the constant, and only the constant:

```python
    insn = 0xd3400000 | (immr << 16) | (imms << 10) | (xn << 5) | xd
```

The docstring already says `0xd3400000`, so the fix makes the code agree with
its own comment — which is also the reason to believe `0xd3400000` is right
rather than merely plausible: it is the one value that reproduces clang's
encoding for all eight shifts checked.

Then check the OTHER immediate-shift encoders in `formal/arm64.py` for the
same mistake, because this one has a docstring that contradicts it and that
is a class of defect rather than a slip. Specifically
`encode_asr_xd_xn_imm` (`:591`) and `encode_lsr_xd_xn_imm` — `>>` is
*observably* correct at every amount, which is evidence they are right and not
evidence they were written carefully.

A test to write with it, and where it belongs: `test_arm64_encoders.py` is the
encoding-level home, and it currently has no `lsl` case at all (`grep lsl` finds
one unrelated `lsl #12` in a load-addressing test). The assertion should be
against clang's assembler rather than against a table — the same oracle
argument `test_formal_os.py` makes for `posixpath` — so it cannot itself
encode the same misreading. The narrowest version is: for every shift 0..63,
`encode_lsl_xd_xn_imm(0, 0, n)` equals the word clang emits for
`lsl x0, x0, #n`, which is 64 comparisons and needs no expected values typed
by hand. An end-to-end row belongs in `test_formal_run.py` too, since
`test_arm64_encoders.py` proves the ENCODING and only a built-and-run image
proves the arithmetic.

## What the hashlib module does about it, in the meantime

`formal/hostmods/hashlib.mojo`'s BLAKE2b needs 64-bit rotations, and a
rotation is `x << n` with `n` in 1..63 — squarely in the broken range. The
module rotates with a **variable** shift amount instead, which lowers to
`LSLV` rather than `LSL #imm` and is correct (measured above: `g(1,12) == 4096`).

That is not a silent workaround, and the reason is worth stating because the
alternative — leaving blake2b out — was the wrong call: the variable form is a
**different instruction with its own correct encoding**, not an emulation of
the broken one, so the module's output is right and its test compares against
CPython byte for byte. The cost is one extra register-pair move per rotation,
which is not a cost worth optimising against correctness on a backend whose
job is to be trustworthy rather than fast. The module's docstring says this at
the rotation's definition, and `test_formal_hashlib.py` would fail if the
immediate form were ever substituted back in, because the digest would stop
matching CPython.

**When the fix lands, this should be revisited on purpose**: the variable form
is a workaround for a defect someone else owns, and the natural thing to do
then is change the rotation back to the immediate form (which is one
instruction instead of a move pair) and let the digest test confirm nothing
moved. That is a deliberate follow-up, not something to do blind.
