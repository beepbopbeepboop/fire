# `encode_movz_xd_imm` is named `xd` and encodes `Wd`, and it has 102 callers

## Status

OPEN, and NEW — measured 2026-10-04 by `tools/formal_model_fuzz.py`, which
cross-checks every instruction it generates against `as -arch arm64` and found
that pairing this encoder with the text `movz xN` does not assemble to the same
instruction.

**It is latent, not a miscompilation.** Every one of the 102 call sites passes a
small immediate, and for a small immediate the 32-bit and 64-bit forms of MOVZ
produce the same register value. It is a trap with 102 callers in it, not a
broken build, and the difference matters the moment a caller wants a value with
bit 31 set.

## 1. The measurement

```
$ python3 -c "
from formal import arm64 as A
for n in ('encode_movz_xn_imm','encode_movz_xd_imm','encode_movn_xd_imm'):
    print(n, '%08x' % int.from_bytes(getattr(A, n)(0, 1), 'little'))"
encode_movz_xn_imm d2800020      # 0xd2800000 = MOVZ Xd  (64-bit)
encode_movz_xd_imm 52800020      # 0x52800000 = MOVZ Wd  (32-bit)
encode_movn_xd_imm 12800020      # 0x12800000 = MOVN Wd  (32-bit)
```

and against the assembler, for the text `movz x28, #55573`:

```
our encoder says 529b22bc,  `as -arch arm64` says d29b22bc
```

`0xd2…` is the 64-bit form and `0x52…` the 32-bit one, and only the first is
what `movz x28` means. `encode_movz_xd_imm`'s own docstring says
"MOVZ Xd/Wd, #imm16 … (sf/opc choose 32 vs 64-bit)" — the parenthetical is the
problem: the function chooses, once and for all, and it chooses 32.

The asymmetry inside the file is the tell: `encode_movk_xd_imm` — the *other*
half of the same idiom — uses `0xf2800000`, which is **64-bit**. So the MOVK
encoder named `_xd_` is 64-bit and the MOVZ encoder named `_xd_` is 32-bit, and
both are called with an X register by the codegen.

## 2. How many callers, and why it has not bitten

```
$ grep -c encode_movz_xd_imm formal/arm64_codegen.py
102
$ grep -c encode_movz_xn_imm formal/arm64_codegen.py
2
```

All 102 pass an immediate under 65536 — the register tests are
`encode_movz_xd_imm(0, 0)`, `(0, 1)`, `(16, 1)`, `(2, width)`, status constants —
and a MOVZ with a small immediate writes bits 31:0 to zero either way. `mvn` is
the same shape (`0x12800000` is MOVN Wd) and the same argument applies: MOVN Wd
with a small immediate is the same value as MOVN Xd with one.

So the failure needs a caller with an immediate ≥ 2^32, and there is none today.
That is luck, not design, and it is the same shape as the `bugs/FORMAL_fuzz_
ledger.md` §2 rows where an encoder that is provably right cannot occur in an
image.

## 3. Why nothing caught it

`test_arm64_encoders.py` checks every encoder against `as -arch arm64`, and it
is the right check — but it contains **no `movz`, `movn` or `movk` case at all**
(measured: `grep -n "movz\|movn\|movk" test_arm64_encoders.py` is empty). So the
three most-used immediate encoders in the backend are the three the encoder suite
does not mention, and `tools/formal_model_fuzz.py` found it by drawing
instructions from the encoders and asking the assembler what they meant.

## 4. The exact next step

1. Add the three families to `test_arm64_encoders.py`'s `cases()` — for each
   width and each `hw`, against the assembler's own word, like the shift sweep
   that already exists there for `lsl`/`lsr`/`asr`. That is a test-only change
   and it will FAIL on `movz`/`movn` as they stand, which is the point.
2. Decide which of the two `movz` encoders is the real one. Both are wired
   (`encode_movz_xn_imm` has 2 call sites, `encode_movz_xd_imm` has 102), so this
   is a rename-and-re-point rather than a deletion: either
   `encode_movz_xd_imm` moves to `0xd2800000` and the two `encode_movz_xn_imm`
   callers move to it, or the 32-bit encoder is renamed
   `encode_movz_wd_imm`, which is what it emits and what its own base opcode
   says. **The second is the smaller and safer change** and it makes the trap
   impossible to fall into: a caller reaching for `_xd_` gets the X form.
3. Same for `encode_movn_xd_imm` (32-bit) and, while there,
   `encode_movz_xn_imm`'s assertion `0 <= xn <= 31` — register 31 is
   `XZR`, which MOVZ cannot write, and an assert that permits it is the same
   class of thing.
4. Then re-run `python3 tools/formal_model_fuzz.py --cases 300 --seed sweepB`:
   the pool pairs each encoder with the width its base encodes, so the tool is
   already correct here and needs no change — its finding is that the ENCODER
   was not.

## 5. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 -c "from formal import arm64 as A; \
  [print(n, '%08x' % int.from_bytes(getattr(A, n)(0, 1), 'little')) \
   for n in ('encode_movz_xn_imm','encode_movz_xd_imm','encode_movn_xd_imm')]"
grep -c encode_movz_xd_imm formal/arm64_codegen.py
grep -c encode_movz_xn_imm formal/arm64_codegen.py
grep -n "movz\|movn\|movk" test_arm64_encoders.py      # no output
python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 300 --seed sweepB                            # ENC-MISMATCH 8 of 60, all this
```

The `ENC-MISMATCH 8 of 60` figure is from the first sweep (60 cases, seed
`model-fuzz`), where every mismatch was `movz`/`movk` pairing; the current seed
draws none because `tools/formal_model_fuzz.py`'s `gen_moves` now pairs each
encoder with the width it encodes.