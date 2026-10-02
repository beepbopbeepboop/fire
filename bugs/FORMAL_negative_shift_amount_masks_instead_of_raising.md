# FORMAL_negative_shift_amount_masks_instead_of_raising: `1 << -1` is `1 << 63`

**Status: OPEN, on both backends, pre-existing, and deliberately NOT fixed by
the saturation change that sits right next to it** (2026-09-30, the
`construct:arm64-silent-wrong-answers` claim; see "Why the saturation fix left
it alone" below, which is the part worth knowing).

This is a **wrong answer, not a refusal**, and it is silent on both
architectures.

---

## What I ran

```mojo
def shl(x: int, n: int) -> int:
  return x << n

def shr(x: int, n: int) -> int:
  return x >> n

def main() -> int:
  printf("l=%lld@@", shl(1, 0 - 1))
  printf("r=%lld@@", shr(8, 0 - 1))
  return 0
```

## What I saw

`shl(1, -1)` is `-9223372036854775808`, which is `1 << 63`. `shr(8, -1)` is
`0`. Both identical on arm64 and on x86-64.

The rule being applied is the hardware's: `LSL`/`ASR`/`LSR` use the low six
bits of the shift register, and `-1 & 63` is `63`. So a negative amount is
silently turned into a large positive one.

CPython raises for both:

```
>>> 1 << -1
ValueError: negative shift count
>>> 8 >> -1
ValueError: negative shift count
```

## Why it matters here, concretely

A rotation written as `rotr(x, n)` with `n` computed rather than passed as a
literal will do this the moment `n` is 0 and the caller writes `rotr(x, 64 -
n)` without the `& 63` — a routine mask, and its absence is invisible until
the digest stops matching. The wrong answer is a plausible word, not a
crash: `1 << -1` returning `0x8000000000000000` reads as a deliberate
high-bit set.

## What I expect

Either of two, and the choice is a design decision rather than a bug fix:

1. **Refuse it.** This path already has the shape for it: a construct with
   no representation here is a `CodegenError` naming the construct, and
   every other "this backend cannot lower exactly" case in `formal/` takes
   it. A negative shift amount at COMPILE time is easy — `model` already
   folds constant shift amounts, so a literal `x << -1` can be refused with
   no new machinery.
2. **Trap at run time**, the way division by zero already does on this path.
   `_emit_div_shift_pow`'s `/`, `//` and `%` arms emit
   `movz x1, #1; movz x16, #1; svc #0x80` on a zero divisor, and CPython
   raises there too. A negative amount is the same kind of fact: not
   representable as a shift distance, and CPython's answer is an exception
   rather than a value. This is the more useful of the two, because the
   amount is usually a variable.

A "saturate to 0" answer would be wrong, and it is worth saying why rather
than leaving it as an option: `x << -1` is not `0` in any reading, and
returning 0 would be as much a fabrication as returning `1 << 63`. It is
also the answer the saturation fix would give if the compare were unsigned,
which is the trap to avoid.

## The exact next step

Option 2, in `formal/arm64_codegen.py`'s `_emit_div_shift_pow` and
`formal/x86_64_codegen.py`'s `_emit_shift`, at the place that already
computes the amount:

1. The amount is already in X1 (arm64) / RCX (x86-64) by the time the
   saturating compare runs. Add one more compare — `CMP X1, #0` /
   `B.LT` on arm64, `CMP RCX, 0` / `JGE` on x86-64 — branching to a
   three-instruction `exit(1)` copied from the divide-by-zero arm in the same
   function, so the diagnostic path is the one the file already uses and
   there is nothing new to design.
2. Do it BEFORE the saturating compare, so a negative amount cannot reach
   the saturation branch and be reported as 0 — the ordering matters and is
   the whole reason this is not a two-line change to the compare that is
   already there.
3. A test in `test_formal_run.py` next to `shl_amount_64_is_zero`: a program
   that shifts by a negative variable exits non-zero, and the two BACKENDS
   must agree on the exit status, which `refuse:`-style cases do not cover
   because this is a run-time trap rather than a build refusal.

Option 1 is a one-line addition on top and is worth doing as well: a literal
negative amount is decidable at build time and a build-time diagnostic names
the line, where a run-time trap can only say "something went wrong".

## Why the saturation fix left it alone

A shift of 64 or more wrapping instead of saturating was fixed in the same
session (and that doc is deleted with its fix, hence named by symptom here).
Its fix puts a `CMP X1, #64` / `B.GE` in front of exactly this instruction. The obvious way to write that compare is UNSIGNED
(`B.HS`/`B.CC`), which would have made a negative amount take the saturating
branch and answer 0 — a third wrong answer, arrived at by fixing the wrong
thing.

The compare is therefore SIGNED on both backends, so a negative amount is
below 64 and falls through to the hardware's masking, which is what it did
before. That is not an endorsement of the masking: it is the refusal to
change a second thing under cover of a fix that claims to be about the
saturation boundary, and it is what keeps this document a separate piece of
work with its own decision in it (refuse, or trap) rather than a detail
somebody has to re-derive.

## Checked and NOT the same bugs

- Not the arithmetic-vs-logical fill (`FORMAL_arm64_right_shift_is_always_arithmetic.md`): that one is about WHICH shift and is fixed; this is about the AMOUNT being out of range at all, and it affects `<<` and `>>` alike.
- Not the saturation boundary: `x >> -1` is not a saturating case. `x >> 64` saturates and is now 0; `x >> -1` is out of range in the other direction and is not.
- Not the ninth-argument refusal: both are "this construct has no
  representation here", but one is a build-time arity check and this one is a
  value the hardware cannot be asked about.
