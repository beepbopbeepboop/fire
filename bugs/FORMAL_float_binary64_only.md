# binary64 only: `Float32` and the narrow formats are refused by name, and `float32` arithmetic is the next slice

**Area:** FORMAL (the float value model). Claim `project26:float`, found
2026-10-04 on `work/formal26-float`. **NOT FIXED, deliberately** — this is the
SCOPE of the support rather than a defect in it, and the doc exists so that
"binary64 only" is a decision somebody can read rather than an absence somebody
has to infer.

## What is supported, and where

`formal/model.py`'s `FLOAT_KIND` is **IEEE-754 binary64** and nothing else, and
`formal/types.py`'s `FLOAT_TYPE_NAMES` is `{"Float64", "float64"}` — two
spellings of one declaration, for the reason every other vocabulary in that file
carries both (`TYPE_NAMES` has `int` and `Int`, `STRING_TYPE_NAMES` has `String`
and `str`).

`formal/arm64.py` and `formal/x86_64.py` carry the SCALAR DOUBLE forms only:
`FADD`/`FSUB`/`FMUL`/`FDIV`, `FNEG`, `FCMP`, `FMOV`, `SCVTF`, `FCVTZS` on arm64;
`ADDSD`/`SUBSD`/`MULSD`/`DIVSD`, `UCOMISD`, `MOVQ`, `CVTSI2SD`, `CVTTSD2SI` on
x86-64. Every encoding is differentially tested against the platform assembler
(`test_arm64_encoders.py`, `test_x86_64_encoders.py`).

## What is NOT, and why the refusal is the right answer

**`Float32` is four bytes with a different exponent bias and its bits are NOT a
sub-pattern of a double's.** So a 64-bit word holding a `binary32` cannot be a
`FLOAT_KIND` here: reading it as a double is a wrong answer, not an
approximation, and it is the same wrong answer for every input except zero. The
honest options were to refuse by name or to accept and misread, and the codebase
already had the pattern for it — `POINTEES_REFUSED` refuses `Float16`, `Float32`
and `Float64` BY NAME rather than merely omitting them, and
`model.unrepresentable_type_ctor_refusal` is the same move for a constructor.

`Float16`, `BFloat16`, the `float8_*` / `float6_*` / `float4_*` families and
`UInt128` are all in the same position, and they are named in
`model.type_value_name_space`'s comment as types a `DType` VALUE can name — a
dtype tag is a word two programs comparing dtypes agree on, which is all a dtype
VALUE is on this path, so a tag for a format this path cannot HOLD is not a lie.

`POINTEES_REFUSED["Float32"]`'s text — *"a Float32 is four bytes of IEEE binary32
and this path has no float kind distinct from an int"* — is TRUE and only true of
binary32, and `test_formal_run.py`'s `deref_refuse_float_pointee` pins it as such.
Its `Float64` sibling was CORRECTED in the same change, because that half of the
sentence had become false: a `Float64` load IS bit-exact now. The corrected text
and the reason are in `bugs/FORMAL_float_pointer_pointee.md`.

## What the next slice would be

A `binary32` kind, and it is NOT a matter of adding `FSADD`/`FSDIV` and four more
encoders:

- **A second `FLOAT32_KIND`** threaded through `ValueKinds`,
  `declared_type_kind`, `truthy_lowering`, `float_comparison`,
  `float_binary_refusal` and both backends' readers. Every one of those today
  answers "is this a double?" and a second width makes the question "which
  width?", which is a different function at each of them rather than a new row.
- **Mixed-width arithmetic** — `Float32 + Float64` — which needs a promotion
  rule. There is none today for double/int either (it is refused), and this is
  the same decision at a second width.
- **A `Float32` value is still ONE word**, so storage needs nothing — the same
  property that makes `Float64` cheap, and the reason the estimate for the second
  width is about the KIND and not about the frame layout.
- **A `Float32` in the Lean model** is a 32-bit pattern, and `lib/IEEE754.lean`'s
  `Bits` is `UInt64` with 11-bit exponents and a 52-bit mantissa baked into every
  mask. A binary32 model is a second parameterisation of the same functions, not
  a copy of them: `isNaN32`, `key32`, `ltBits32`, and the four SCALAR SINGLE
  decode arms. Writing it as a copy is what `CLAUDE.md`'s "consolidate duplicates
  rather than maintaining parallel implementations" is about, so the shape to
  reach for is one pair of functions parameterised by the width.
- **A `Float16`/`BFloat16` cannot go in a 64-bit word without a mask on every
  read**, so it is a genuinely larger change than `Float32` and should be argued
  for separately.

## What was measured, so the next person does not have to

`formal/model.py`'s `FLOAT_BINARY_MNEMONICS` has four rows (`+`, `-`, `*`, `/`),
so `//`, `%`, `**` and the bitwise operators on two doubles are REFUSED by name —
`model.float_binary_refusal`'s message says which four are lowered and why the
other is not (neither FP unit has an instruction, and CPython's `7.0 // 2` is
`3.0`, not a truncated `3`). That refusal is a slice boundary of this one and not
a gap in it.