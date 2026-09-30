# FORMAL_arm64_right_shift_is_always_arithmetic: there is no logical shift, so every bit-manipulating algorithm is wrong

**Status: OPEN. Found while writing `hashlib` (2026-09-29, the
`module:hashlib` claim); the fix is in `formal/arm64_codegen.py`, which that
claim does not own, so it is filed rather than applied. Until it lands,
`formal/hostmods/hashlib.mojo` masks after every right shift — see "What the
hashlib module does about it".**

This is a **wrong answer, not a refusal**, and it is the one with the widest
blast radius of the three arm64 defects found while writing that module: it
silently breaks **every algorithm that does bit manipulation**, which is
SHA-1, SHA-2, BLAKE2, CRC, base64, AES and anything else that shifts a word
right expecting zeros in.

---

## What I ran

```
$ cat > .tmp/neg.mojo
def shr(x: int, n: int) -> int:
    return x >> n
def main() -> int:
    printf("shr1=0x%016lx@@", shr(0 - 5, 1) & 0xFFFFFFFFFFFFFFFF)
    printf("shr4=0x%016lx@@", shr(0 - 5, 4) & 0xFFFFFFFFFFFFFFFF)
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/neg .tmp/neg.mojo
$ ./.tmp/neg
shr1=0xfffffffffffffffd
shr4=0xffffffffffffffff
```

## What I saw

`(-5) >> 4` should be `0x0fffffffffffffff` (a logical shift: the top four bits
become zero). It is `0xffffffffffffffff` — the top four bits became **ones**,
because the shift sign-extends.

| expression | got | want |
|---|---|---|
| `(-5) >> 1` | `0xfffffffffffffffd` | `0x7ffffffffffffffd` |
| `(-5) >> 4` | `0xffffffffffffffff` | `0x0fffffffffffffff` |
| `(-2**63) >> 1` | `0xc000000000000000` | `0x4000000000000000` |

Every case is right for a POSITIVE operand and wrong for a negative one, which
is why this can hide: `1 >> 4` is `0`, and testing a shift on a small positive
number says nothing.

The immediate form behaves the same way — `x >> 32` on
`0x0123456789ABCDEF` is correct because that value's bit 63 is clear.

## Why

Both backends choose between the two right-shift instructions by asking
whether the operand is signed, and nothing in the SOURCE can answer that
question:

`formal/arm64_codegen.py:5462` (the shared entry, used by both the immediate
and the register form):

```python
        signed = cmp_signed(common_type(self._ttype(e.left),
                                        self._ttype(e.right)))
```

and then, in the register form:

```python
            elif signed:
                self.asm.emit(encode_asrv_xd_xn_xm(0, 0, 1))
            else:
                self.asm.emit(encode_lsrv_xd_xn_xm(0, 0, 1))
```

So `ASRV` and `LSRV` both exist and both are implemented; the emitter picks
per-value from the type, and `Int` is signed, so **every** `Int >> Int` is
`ASRV`. There is no spelling that asks for the other one, so a program that
wants zeros shifted in has no way to say so.

This is the same shape as the two other arm64 defects found alongside it, and
the three together are worth reading as a group:

| doc | what | symptom |
|---|---|---|
| `FORMAL_arm64_lsl_imm_is_wrong_for_every_amount_above_8.md` | `<<` immediate, one wrong constant | `1 << 12` is `16` |
| `FORMAL_arm64_ninth_argument_is_silently_dropped.md` | callee `break`s at 8 params | the 9th argument reads `0` |
| this one | `>>` is always arithmetic | `(-5) >> 4` fills with ones |

In all three the code contains the right instruction and takes a wrong path to
it, and in all three the answer is plausible rather than absent.

## What I expect

A logical right shift, spelled somehow. The three candidate answers, in the
order I would try them:

1. **A builtin or a type distinction.** `>>>` is Python's logical shift and
   the parser may already have a spelling for it — worth checking before
   inventing one, because if `>>>` parses and lowers through `_emit_div_shift_pow`
   then the fix is a few lines and the spelling is already the one a Python
   programmer would reach for.
2. **Decide by a declared unsigned type.** `cmp_signed` already does the right
   thing for a `UInt`; the question is whether `UInt >> UInt` is expressible
   and lowers. If it is, the documented spelling is "declare the word
   unsigned", and this file's job is to say so.
3. **A new operator or a module-level flag.** Least good, and only if 1 and 2
   both fail.

## The exact next step

1. **Check whether `>>>` parses.** `fire_compiler.py`'s operator table is one
   grep. If `>>>` is already a token, route it to `LSRV`/`LSRL` in
   `_emit_div_shift_pow` and refuse it on a signed-only path rather than
   guessing; the refusal is the important half, because an operator that
   silently means the other thing is worse than one that does not exist.

2. **Otherwise, expose the choice the emitter already makes.** `cmp_signed` is
   the whole decision, so a source-level unsigned word type reaches both
   branches already. Check `formal/model.py` for a `UInt` spelling that a
   subscript or an annotation can produce, and check that `>>` between two of
   them takes the `LSRV` path — that path is written and, as far as the
   measurements here go, untested.

3. **A test for it**, in `test_formal_run.py`: `(0 - 5) >> 4` and
   `0x8000000000000000 >> 1`, asserted against the logical answer. A
   POSITIVE operand must be in the same test, precisely so the test fails if
   someone "fixes" this by making all shifts logical — that would be correct
   for `(-5) >> 4` and wrong for Python, where `>>` on a negative `int` is
   arithmetic and `>>>` is logical. **The two must stay distinguishable**, and
   a test that only pins the negative case would invite exactly that wrong
   fix.

**Checked and NOT the same bug**, so nobody re-derives it: this is not the
`<<` immediate defect (different instruction, different direction, different
arithmetic boundary), and not the ninth-argument defect (which loses an
argument before any shift happens). It IS however the reason a rotation cannot
be written the obvious way, and it is the second of the two blockers that
stopped BLAKE2b in `formal/hostmods/hashlib.mojo`.

## What the hashlib module does about it, in the meantime

`rotr64` masks after the shift:

```mojo
    # `x >> n` is an ARITHMETIC shift on this path (see the bug doc), so the
    # top n bits come back as ones; masking to n bits of headroom turns it
    # into the logical shift BLAKE2b specifies.
    return ((x >> n) & ((1 << (64 - n)) - 1)) | (x << (64 - n))
```

which is the logical shift spelled in the operations that do work. The inner
`1 << (64 - n)` is a VARIABLE shift, so it is `LSLV` and is correct (measured);
the arithmetic shift is then masked away. The cost is two extra ALU
instructions per rotation, which is the right trade on a backend whose job is
to be trustworthy rather than fast.

`test_formal_hashlib.py` would fail immediately if this were removed, because
the digest would stop matching CPython — which is the point of checking a
digest against an oracle rather than against itself.
