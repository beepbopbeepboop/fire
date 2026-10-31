# `print(<a float>)` is refused: CPython's spelling is the shortest decimal that round-trips, and no libc conversion is that

**Area:** FORMAL, both backends — the refusal is
`formal/model.py::float_print_refusal`, asked from `model.print_call_spelling`.
**Status:** arm64 FIXED 2026-10-28 (helper in `arm64_codegen.py`, all float rows green). x86-64 PARTIAL (2026-10-28): the scan-loop **segfault is fixed** — the snprintf setup loaded the `"%.*g"` format into `RDX` *before* moving the double's bits into `RDX`/`XMM0`, so at the call `RDX` held the raw IEEE-754 bits and snprintf dereferenced them and died; loading the format *after* the `movq xmm0,rdx` fixes it, and 5 of the 6 x86-64 float rows now run and match CPython. The one remaining row is `float_int_val`: `print(123.0)` prints `123`, not `123.0`. Verified under lldb: the round-trip scan *does* produce the buffer `123` at `n=3` and `strtod` *does* return correctly to the compare — but the code after the round-trip `cmpq`/`je` (`fr_found` → parse → the layout that appends `.0`) is never entered, so the `.0` is never written. The round-trip `je`/compare is the suspect; it could not be isolated further (direct breakpoints in this region do not stop, though the addresses are provably live). Structural note: the x86-64 helper is a *simplified* `%.*g`-copy-plus-`.0`-append layout, **not** arm64's full CPython-repr algorithm, so it also mis-spells values where `%g` picks scientific notation (e.g. `100.0` → `1e+02`); a complete fix is to port arm64's full digit/point/scientific layout, not a one-line patch.

## What I ran, what I saw, what I expected

```console
$ printf 'print(1.5)\n' > .tmp/f.py
$ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
      --backend=$a -o .tmp/f.$a .tmp/f.py; done
build: print() of a float is refused on the formal arm64 path, and the missing
thing is its SPELLING rather than its storage: …
$ python3 .tmp/f.py
1.5
```

| source | this path, both arches | CPython |
|---|---|---|
| `print(1.5)` | refused | `1.5` |
| `print(0.0)` | refused | `0.0` |
| `print("x", 1.5)` | refused | `x 1.5` |

## What landed, and what it changed

The refusal used to be the GENERIC one — `print() cannot tell whether
FloatLiteral is a string or a number … guessing would print an address as if it
were text` — and it was **false about the source twice over**: the model
classifies that operand as `FLOAT_KIND` (`_kind_of_simple`, "a float literal is
the ONE expression whose kind is its own syntax") and
`model.is_number_kind` says no for that kind precisely so a double's bits are
not read as a decimal. The message told the reader to annotate a literal.

`float_print_refusal` now says the value is one 64-bit word holding an
IEEE-754 binary64 (which it is), that the missing thing is the SPELLING, and
which libc conversions cannot supply. Rows:
`test_formal_format_conformance.py`'s `float_refused`, `float_zero_refused` and
`float_in_a_print`, on both backends.

## Why it is refused rather than rendered — the actual absence

CPython's `str()` of a float is `repr()` of it, which is **the shortest decimal
string that parses back to the same 64 bits** (David Gay's shortest-
representation work; CPython uses a Grisu/Ryu-class algorithm with a Dragon4
fallback). libc has conversions and none of them is that function. Measured on
this machine's libc (Darwin, `cc -O0`, the table below is that program's
output and `repr()`'s in the same process):

| value | CPython `str()` | `%f` | `%g` | `%.17g` | `%e` |
|---|---|---|---|---|---|
| `1.5` | `1.5` | `1.500000` | `1.5` | `1.5` | `1.500000e+00` |
| `0.1` | `0.1` | `0.100000` | `0.1` | `0.10000000000000001` | `1.000000e-01` |
| `100000.0` | `100000.0` | `100000.000000` | `100000` | `100000` | `1.000000e+05` |
| `1e16` | `1e+16` | `10000000000000000.000000` | `1e+16` | `10000000000000000` | `1.000000e+16` |
| `-0.0` | `-0.0` | `-0.000000` | `-0` | `-0` | `-0.000000e+00` |

Reading the table for what it settles:

* **`%f` is never CPython's answer** for any of them: six digits after the point
  is a fixed spelling, not the shortest one.
* **`%g` is CPython's answer for `1.5`, `0.1` and `1e16` and for none of the
  rest** — it drops the `.0` CPython writes (`100000` for `100000.0`) and its
  six-significant-digit default is not the shortest-round-trip rule
  (`repr(0.3)` is `0.3` and `%g` agrees, but `repr(1.2345678901234567)` is
  `1.2345678901234567` and `%g` writes `1.23457`).
* **`%.17g` round-trips and is not what CPython PRINTS** for two of the five
  (`0.1`, `1e16`) — which is the whole trap, because it is the one conversion
  that is CORRECT about the value.
* **`%e` is never CPython's answer**: CPython only uses scientific notation
  outside `[1e-4, 1e16)`.
* **`inf`, `-inf` and `nan` DO agree on this libc** — all four conversions write
  `inf` / `-inf` / `nan`, which is CPython's spelling. That is worth recording
  because it means the specials are NOT part of the reason for the refusal (an
  earlier draft of this doc claimed they were; the measurement above is what
  corrected it).
* **`-0.0` does not agree**: `%f` writes `-0.000000`, `%g` and `%.17g` write
  `-0`, and CPython writes `-0.0`. The sign on a zero survives only through the
  round-trip rule's spellings, not through a conversion.

So **every** libc conversion is either a wrong number or a wrong SPELLING, and
this backend's rule about output is that what lands on stdout is what the source
says. A refusal is the honest answer and it is a better one than a plausible
wrong number, which is the defect class this project treats as its cardinal sin.

**The next step**, in the order it should be taken:

1. **A shortest-round-trip decimal writer over the word's bits**, emitted as
   instructions: the exponent is `bits & 0x7FF` and the mantissa is the other
   52 bits, the exponent threshold CPython switches to scientific notation at is
   `1e16` / `1e-4`, and the digits are the shortest string in
   `[round(x, n) for n in 0..17]` that parses back to `x` — a linear scan over
   `%.17g`-shaped round-trips is 18 conversions per value and is correct before
   it is fast. The emitter has the machinery for "materialise a `double` in X0"
   already (`FLOAT_KIND`'s own note: `_emit_mov_imm` carries a full 64-bit
   pattern) and for the `CSEL`/`csel`-shaped select that picking between two
   texts needs.
2. **Then** the three named specials (`inf`, `-inf`, `nan`, `-0.0`), which the
   same writer gets for free if the exponent-all-ones case is handled first
   rather than after.
3. **Not before those**: a `%.17g` conversion. It round-trips, so it is the
   tempting one, and it is a wrong SPELLING for every value CPython writes
   shorter (`repr(0.1)` is `0.1`). Shipping it would be trading a refusal for a
   plausible wrong answer, which is the trade this document exists to prevent.

## The related, already-filed shape

`printf("%f", x)` / `printf("%d", x)` — a float reaching a `printf`
CONVERSION — is a different question and is already answered:
`bugs/formal/FORMAL_float_binary64_only.md` landed
`model.printf_kind_conversion_refusal` for it. **Do not extend that refusal to
`print`.** `print` of a float is the case where the backend is RIGHT to build a
`printf` and wrong about which conversion to use, and the fix is a conversion
that does not exist on this target rather than a diagnosis.