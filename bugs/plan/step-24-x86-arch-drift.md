# plan/step-24: x86-64 arch drift (`^` and comptime over a subscript)

**Source:** `bugs/FORMAL_known_limits.md` §6.5.
**Master plan:** `doc/finish-formal.md` §"Step 24".

## Goal

§6.5's two files whose message differs between architectures, which "is *not*
cosmetic" and is a codegen gap in x86-64, not a wording difference:

- `std/builtin/swap.mojo` — arm64 builds it, x86-64 refuses
  `unsupported unary operator '^' on the formal x86-64 path`.
- `std/math/polynomial.mojo` — arm64 says "comptime … does not fold to a
  compile-time constant", x86-64 says `unsupported call target on the formal
  x86-64 path (got SubscriptExpr)`. The two architectures name different limits
  for one construct, and only one is operative.

Fix is to give x86-64 the same resolver arm64 uses
(`mojo/middle/comptime.py` documents x86-64 as an intended consumer of exactly
this seam and it never was one — per §3's `comptime` drift fix).

## What to add

- The unary `^` lowering in `formal/x86_64_codegen.py`.
- The `SubscriptExpr` call-target arm so `polynomial.mojo` refuses with the same
  `comptime_fold_refusal` arm64 emits, byte for byte.
- A parity row in `test_formal_x86_64_parity.py`.

## Structure-only rule

Shared *answers* live in `formal/model/`; the resolver arm is the codegen seam.
Do not change arm64. Scaffold any proof obligation with `sorry`.

## Files

`formal/x86_64_codegen.py`, `formal/model/` (if a table moves),
`test_formal_x86_64_parity.py`.

## Verification

`test_formal_x86_64_parity.py`; the two files in the same class on both
architectures.

## Done when

- [ ] both files are in the same class on both architectures
- [ ] a parity row pins it
- [ ] no arm64 change

## Dependencies

step-01 (holes only). Independent.
