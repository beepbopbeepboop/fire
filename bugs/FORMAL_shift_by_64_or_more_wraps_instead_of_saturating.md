# FORMAL_shift_by_64_or_more_wraps_instead_of_saturating: `3 >> 64` is `3`

**Status: OPEN. Found while writing `hashlib` (2026-09-29, the
`module:hashlib` claim). This one is in `formal/model.py` rather than in a
backend, so it is BOTH backends' behaviour and the fix is not this claim's.
`formal/hostmods/hashlib.mojo` avoids the construct rather than working
around it silently — see the last section.**

**A wrong answer, not a refusal, and it is silent on both architectures.**

---

## What I ran

```
$ cat > .tmp/s64.mojo
def shr(x: int, n: int) -> int:
    return x >> n
def main() -> int:
    printf("s64=%lld@@", shr(3, 64))
    printf("s65=%lld@@", shr(3, 65))
    printf("s63=%lld@@", shr(3, 63))
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/s64 .tmp/s64.mojo
$ ./.tmp/s64
s64=3
s65=1
s63=0
```

## What I saw

`3 >> 64` is `3`, and `3 >> 65` is `1`. In Python both are `0`.

The rule is **the shift amount is taken modulo 64**, which is what the
hardware does: `LSRV`/`ASRV`/`LSL` use the low six bits of the shift register,
so an amount of 64 is an amount of 0 and an amount of 65 is an amount of 1.
`shl` behaves the same way, and the immediate form does too — `(3 >> 64)`
with the amount written as a literal is also `3`.

**Both backends agree**, which is what makes this a model property rather
than a codegen slip:

```
$ python3 fire.py build --formal --no-prove --backend x86_64 -o .tmp/s64x .tmp/s64.mojo
$ ./.tmp/s64x
s64=3
s65=1
s63=0
```

A x86-64 `SARQ`/`SHRQ` with a count of 64 gives 0 (the count is saturated at
63 for `SAR`/`SHR` and masked for `SHL` with a 6-bit count that is then
special-cased), so the x86-64 emitter is reproducing the same modulo rule
deliberately or by copying the model. That is worth knowing: the fix is one
place, not two, and the two agreeing is evidence the rule is written down
somewhere rather than arising twice.

## Why it matters here, concretely

BLAKE2b's block counter `t` is 128 bits: `t[0..63]` is the low word and
`t[64..127]` is `t >> 64`. The natural transcription of that is

```mojo
    word_put(v, 96,  word_get(v, 96)  ^ t)
    word_put(v, 104, word_get(v, 104) ^ (t >> 64))
```

and the second line XORs in the WHOLE counter instead of zero, which changes
the digest. It produced a BLAKE2b answer whose first hex digit matched CPython
and whose remaining 127 did not — a very convincing wrong answer, and one
that took a bisection down to a one-character difference to find.

## What I expect

`x >> 64 == 0` and `x >> 65 == 0`, as in Python, and `x << 64 == 0`.

There is a real design question underneath, and it is not mine to settle: a
fixed-width machine word arguably *should* wrap, and a language that
documents it can be coherent. But this is a **Python** front end, CPython is
the oracle every test in this tree compares against, and Python saturates. So
the right answer here is Python's, and if anyone wants the wrapping behaviour
it has to be a separate spelling — the same argument
`FORMAL_arm64_right_shift_is_always_arithmetic.md` makes about `>>` versus
`>>>`.

## The exact next step

1. **Find where the rule is written.** `grep -rn ">> 64\|& 63\|% 64" formal/`
   and look at the shift paths in `formal/model.py` and both codegens'
   `_emit_div_shift_pow`. If the modulo is explicit, this is a two-line change
   per site; if it is implicit in the instruction selection, it needs the
   saturation branch the x86-64 count already has.

2. **Make the SATURATION explicit at the model level** rather than in each
   backend, so the two cannot drift. The arm64 and x86-64 shift paths are
   separate functions with the same shape, and this defect is in both, which
   is the argument for one rule in one place.

3. **Decide the boundary and say so in a comment**: amounts 0..63 shift;
   amounts ≥ 64 give 0. That is Python's rule and it is what a fix should
   implement. A negative amount is a separate question and a separate answer
   (CPython raises) — do not bundle it.

4. **A test**, in `test_formal_run.py`: `3 >> 64`, `3 >> 65`, `3 << 64` and
   `1 << 63`, asserted against Python. `1 << 63` belongs in the same test
   precisely because it is the largest amount that must still work, so a fix
   that saturates at 63 by accident rather than by rule is distinguishable
   from one that does it on purpose.

**Checked and NOT the same bugs**, so nobody re-derives them: this is not the
arithmetic-vs-logical shift defect (both are about *which* shift, this is
about *how far*), and not the immediate-`<<` encoder defect (that one is
arm64-only and about the amount 9..63; this one is both backends and about
64+).

## What the hashlib module does about it, in the meantime

`b2_compress` writes the counter's high word as an explicit `0`, with the
reason at the line:

```mojo
    # The high half of the 128-bit counter `t` is `t >> 64` in RFC 7693, and
    # this path cannot compute it: a shift of 64 or more wraps to the amount
    # modulo 64 (bugs/FORMAL_shift_by_64_or_more_wraps_instead_of_saturating.md),
    # so `t >> 64` would XOR the WHOLE counter back in. It is 0 for every
    # message this target can hash, and that is not a guess: `t` counts BYTES
    # of one buffer, a 64-bit address space caps a buffer at 2**48 bytes, and
    # 2**48 < 2**64. The constant is therefore the correct value over the
    # whole reachable domain, not an approximation of it.
```

That is a stronger statement than a workaround, because the bound is
arithmetical rather than empirical: there is no input this module can be given
for which the omitted word is nonzero. The honest way to write that is as a
constant with the bound attached, which is what it is, and the way to make it
an approximation instead would be to accept a `t` from a caller — which this
module does not do, since `t` is always `n`, the caller's own byte count.
