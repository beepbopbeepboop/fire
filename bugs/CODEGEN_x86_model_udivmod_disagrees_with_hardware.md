# `lib/X86.lean`'s model of `idiv r64` disagrees with the hardware on `udivmod`

## Status

OPEN, and NEW — found 2026-10-02 by running `formal/x86_64_model_test.py` for
the first time in its life. That file is spelled `*_test.py`, the estate
check's walk counted only `test_*.py`, and it was in no spec and in no
`UNREGISTERED`, so it ran by nothing. It is now registered as
`formal-x86-machine-model` with `expect=` naming this disagreement
(see "What changed" at the end); the marker is what makes this a report
instead of a silence.

## What I ran, and what I saw

```
$ python3 formal/x86_64_model_test.py
  ...
  udivmod        real=4 model=7905747460161236410  (low byte 186)
x86-64 model vs hardware: agree 44  WRONG 1  NO-RUN 0  build-fail 0  (of 45)
```

`real` is the process's exit status under Rosetta, `model` is the value
`x86_exec_exit` leaves in RAX. The comparison window is the low byte of RAX,
because the kernel truncates a wait status — so this is a disagreement in a
full byte, not a truncation artefact: **186 where the hardware says 4.**

44 of the 45 examples agree and none NO-RUNs, so the disagreement is local to
the dividing instructions rather than a step function that cannot run this
program at all.

The model value decodes as `0x6db6db6db6db6dba`, and
`0x6db6db6db6db6db6` is the classic magic multiplier for a division by 7, with
the correct answer `4` added to it. I checked the obvious explanation — that
the backend emitted a magic-multiply division and the model mis-stepped it —
and it is **not** what the bytes say:

```
$ python3 -c "import formal.build as B; \
    r = B.compile_formal('formal/examples/udivmod.mojo', prove=False, \
                         check=False, arch='x86_64'); print(' '.join('%02x' % b for b in r['code']))"
55 48 89 e5 48 c7 c7 0a 00 00 00 e8 02 00 00 00 5d c3 55 48 89 e5 48 81 ec 10 41 00 00
48 89 5d f8 48 89 fb 48 89 d8 48 81 ec 10 00 00 00 48 89 04 24 48 c7 c0 07 00 00 00
49 89 c3 48 8b 04 24 48 81 c4 10 00 00 00 4d 85 db 0f 84 0a 00 00 00 48 99 49 f7 fb
e9 13 00 00 00 ... 4c 01 d8 48 8b 5d f8 c9 c3
```

`48 99` is `cqo` and `49 f7 fb` is `idiv r11`, with `r11 = 7`. There is no
multiply anywhere in the dividing path, so the magic-constant reading is a
coincidence of the decimal and the bug is in the `idiv` step itself. The
remainder is then `7 + (n mod 7)` via `4c 01 d8` (`add rax, r11`).

## What is believed, and the two suspects

`lib/X86.lean` line ~539, the `idiv` arm of the group-3 handler:

```lean
match x86_idiv128 (x86_signed s.rdx) (x86_signed s.rax) (x86_signed a) with
```

with

```lean
def x86_idiv128 (hi lo d : Int) : Option (Int × Int) :=
  if d = 0 then none
  else
    let n := hi * (x86_two64 : Int) + lo
    some (Int.tdiv n d, Int.tmod n d)
```

**Suspect 1 — the `lo` argument is sign-extended when the dividend's low half
must be raw.** RDX:RAX is a 128-bit *two's-complement* number, so its low word
contributes its unsigned value; passing `x86_signed s.rax` subtracts `2^64`
from the dividend whenever RAX's top bit is set. For `udivmod(10)` the top bit
is clear, so this alone cannot explain the observed 186 — but it is a real
defect in the same three lines and worth checking in the same pass, and it is
the kind of off-by-`2^64` that is invisible for every small dividend.

**Suspect 2 — the QUOTIENT overflow check.** Real `idiv` raises `#DE` when the
quotient does not fit in 64 bits. `x86_idiv128` returns the quotient of an
arbitrary-precision `Int` with no range check at all, so a dividend whose
quotient exceeds `Int64` produces a value RAX cannot hold. Nothing in this
example obviously overflows, so this is the weaker of the two, but it is the
other thing the hardware does that the model does not, and
`formal/x86_64_model_coverage_test.py` only checks that each opcode STEPS, not
that it produces the right number.

## The exact next step

1. Single-step `udivmod`'s image and print `(rip, rax, rdx, rcx, r11)` at each
   boundary across the `cqo`/`idiv` pair. That immediately separates the two
   suspects: RAX `0x6db6db6db6db6db6`-ish on the model side says the quotient
   was computed from the wrong dividend (suspect 1); RAX and RDX correct across
   the pair and wrong only after says the fault is later, in the remainder
   path (`add rax, r11` at `4c 01 d8`) or in how the harness reads RAX.
2. Fix `x86_idiv128`'s `lo` to be `s.rax.toNat` (the raw low word) if
   suspect 1 is confirmed — and note that `x86_div128` already takes
   `lo : Nat`, so the signed twin is the asymmetric one.
3. Re-run `formal/x86_64_model_test.py`; `formal-x86-machine-model`'s
   `expect=` marker states `1 of 45 WRONG: udivmod`, so a fix that does not
   move that count is reported as a FAILURE rather than absorbed.
4. While there: a `#DE` range check in `x86_idiv128` (return `none` when the
   quotient is outside the signed 64-bit range, which is what the hardware's
   fault means). That is a refusal, so it is the honest direction — and
   `x86_step`'s contract already returns `none` for anything it cannot model.

## Related

- The reason this was invisible is its own bug:
  `bugs/UNTESTED_estate_check_only_sees_test_prefixed_files.md` (closed with
  the widening of the estate check's subject set).
- `formal/x86_64_model_test.py`'s own docstring is the right description of
  why this class of bug survives a typechecker: "A machine model that has only
  been typechecked is worth very little: it can be wrong in ways Lean's kernel
  will never notice, because every definition in it is trivially well-typed."