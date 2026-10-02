# FORMAL_arm64_right_shift_is_always_arithmetic: the repro was measuring the right answer

**Status: the underlying construct gap is FIXED and the document's diagnosis
is CORRECTED. What this file is kept for is the second half, because the
first half is the expensive mistake: a bug report whose repro asserts a
WRONG expectation, and whose "fix" would have broken working code.**

Fixed 2026-09-30 (`construct:arm64-silent-wrong-answers`). Kept rather than
deleted because its two "next step" options are still the record of how this
was decided, and because the repro below is still the fastest way to convince
a reader that the arithmetically-signed answer is the CORRECT one — which is
the opposite of what this document used to say.

---

## The correction, which is the point

The document's repro, re-run against the current tree:

```mojo
def shr(x: int, n: int) -> int:
    return x >> n
def main() -> int:
    printf("shr1=0x%016lx@@", shr(0 - 5, 1) & 0xFFFFFFFFFFFFFFFF)
    printf("shr4=0x%016lx@@", shr(0 - 5, 4) & 0xFFFFFFFFFFFFFFFF)
    return 0
```

```
shr1=0xfffffffffffffffd
shr4=0xffffffffffffffff
```

and CPython, on the same two expressions:

```
>>> hex((-5) >> 1 & (2**64-1))    0xfffffffffffffffd
>>> hex((-5) >> 4 & (2**64-1))    0xffffffffffffffff
```

**Identical.** The document's "what I expect" column said
`(-5) >> 1` should be `0x7ffffffffffffffd` and `(-5) >> 4` should be
`0x0fffffffffffffff` — i.e. a LOGICAL shift. But `>>` on a negative `int` is
ARITHMETIC in Python: it rounds toward negative infinity, so `-5 >> 1` is
`-3` and `-5 >> 4` is `-1`. The "want" column was computed as though the
value were unsigned, and the backend was right.

This is worth stating loudly because the document's own later text already
half-knew it — it said "a test that only pins the negative case would invite
exactly that wrong fix" and "`>>` on a negative `int` is arithmetic and `>>>`
is logical" — while its headline, its repro and its fix direction all assumed
the opposite. A "fix" that made every `>>` logical would have passed the
document's own repro and broken Python.

## What the real defect was, and it was real

The construct gap underneath was genuine, and it is fixed. It is just not
the one the document measured. `UInt64 >> Int` computed

```
0xFFFFFFFFFFFFFFFF >> 4  as  0xFFFFFFFFFFFFFFFF     (arithmetic — wrong)
CPython:                                        0x0FFFFFFFFFFFFFFF
```

The cause: both backends asked
`cmp_signed(common_type(ttype(left), ttype(right)))`, and `common_type` is
signed-wins (`formal/types.py`). That is the right rule for `/` and `%`,
where the operands genuinely combine. It is the wrong rule for a shift,
because the right operand is a COUNT, and how far to move says nothing about
what to move in. An unannotated — hence signed — shift amount won the
promotion and then decided the fill.

The rows that isolate it, all the same shift and the same amount `4`:

| source | before | after | CPython |
|---|---|---|---|
| `x: UInt64, n: Int` | `0xffffffffffffffff` | `0x0fffffffffffffff` | `0x0fffffffffffffff` |
| `x: UInt64, n: UInt64` | `0x0fffffffffffffff` | unchanged | `0x0fffffffffffffff` |
| `x: UInt64, n: literal 4` | `0x0fffffffffffffff` | unchanged | `0x0fffffffffffffff` |

The literal row is the diagnostic, and it is why this hid: the amount is the
same number 4 in all three, so the only thing that differs is whether the
COUNT was typed. A count that happens to agree with the answer is not a
reason to give the right answer, and a bit-manipulating algorithm that shifts
by a literal looked correct throughout.

Fixed as `formal/model.py`'s `shift_signedness` — the left operand alone —
read by both emitters. The result WIDTH still comes from `common_type` of
both operands, because that is a different question and does involve both.
Pinned by `test_formal_run.py`'s `ushift_u64_by_typed_int_amount`,
`..._typed_u64_amount`, `..._literal_amount`, `..._variable_amount`, and
`signed_shift_by_unsigned_amount_stays_arithmetic` — the last of which is
there so that "the amount never decides the fill" cannot be satisfied by
refusing to decide at all.

## The two "next step" options, and what happened to each

The document offered three and ranked them. All three are now settled, and
two of them were wrong for reasons worth keeping.

**1. "Check whether `>>>` parses, and route it to LSRV."** It does not parse,
and neither does the interpreter — `fire_compiler.py`'s `_PREC` has `<<` and
`>>` and no `>>>`, so `x >>> n` is `Unexpected OP('>')` on every path that
goes through this tree's parser.

More decisively: **CPython 3.14.7 on this machine rejects `>>>` too.**

```
$ printf 'x = -5\nn = 4\nprint(x >>> n)\n' > /tmp/t.py && python3 /tmp/t.py
  File "/tmp/t.py", line 3
    print(x >>> n)
              ^
SyntaxError: invalid syntax
```

Checked through `ast.parse`, through `exec`, and through `eval` of a
string built at run time (`op = ">>" + ">"`), so it is the grammar and not
the shell. `>>` is accepted on the same lines. This is surprising enough to
be worth stating as a measured fact rather than an assumption, because it
inverts the conclusion: adding `>>>` to `_PREC` would make this compiler
accept a program its own oracle rejects. **Do not add it on the strength of a
Python-2-era memory of the operator.**

**2. "Expose the choice the emitter already makes — `cmp_signed` does the
right thing for a `UInt`; check whether `UInt >> UInt` is expressible."** This
is what was implemented, and it is the whole fix. `UInt >> UInt` was already
expressible and already lowered through `LSRV`; the defect was that the
AMOUNT's type could overrule the VALUE's.

**3. "A new operator or a module-level flag."** Not needed, and the operator
half is unavailable per (1).

## What is left of the original ask

Nothing construct-wise. A program that wants zeros shifted in says so with an
unsigned type, and that is now honoured regardless of how the amount is
spelled. There is deliberately no spelling for a logical shift of a SIGNED
value, for the reason in (1).

## Checked and NOT the same bugs

Three neighbouring shift defects were ruled out while diagnosing this one, and
all three are named by SYMPTOM rather than by the doc they once had, because
CLAUDE.md deletes a fixed bug's doc and the citation would then point at
nothing. The facts live with the code that carries them.

- Not **a shift of 64 or more wrapping instead of saturating** (fixed in the
  same session, and its doc deleted with the fix). That is how FAR a shift
  goes; this is what comes in. `x >> 64` saturating to 0 is unrelated to
  `x >> 4` on an unsigned value. The rule is `formal/model.py`'s
  `shift_saturated_is_zero`, and both backends branch on it rather than
  re-deriving the test.
- Not **the immediate-`<<` encoder's base opcode carrying stray bits in
  `immr`** (also fixed, also in the same session, also with its doc deleted):
  `encode_lsl_xd_xn_imm` carried `0xd3780000` where its own docstring said
  `0xd3400000`, so `1 << 12` returned `16` and only amounts 1-8 were right. A
  different instruction and a different direction — the amount field, not the
  value's type. `test_arm64_encoders.py` sweeps all three shift encoders over
  the whole 0..63 range and says so at the sweep.
- Not **a negative shift amount masking instead of raising** (a finding from
  the same session, also fixed, also with its doc deleted): an amount out of
  range in the OTHER direction, affecting `<<` and `>>` alike. The range check
  is `formal/model.py`'s, and the encoders raise on an out-of-range amount
  rather than truncating it.
