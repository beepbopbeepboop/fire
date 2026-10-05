# `lib/X86.lean`'s model of `idiv r64` disagrees with the hardware on `udivmod`

## Status

OPEN, and **not fixed** — re-read 2026-10-04, and one of its two suspects is
now DISMISSED by inspection, which is a real result: the fix it proposes for
that suspect would be a regression.

**Why it is not fixed here.** `lib/X86.lean` is a Lean library whose
correctness is established by RUNNING Lean, and this worker is not permitted to
launch lean (`formal/x86_64_model_test.py` builds the model and runs every
example through it). Editing `x86_idiv128` unverified would be exactly the
"silence an error" shortcut the project's rules exist to end: a wrong
128-bit divide model breaks every x86-64 proof, and the exit code a reviewer
would see is unchanged. So the reading-level findings are recorded below and the
experiment is left for whoever can run it.

## Suspect 1 is WRONG, and its proposed fix is a regression

The doc observes that `x86_idiv128` is handed `x86_signed s.rax` for the low
word and proposes changing it to the raw `s.rax.toNat`. Reading the definitions
on this tree shows that would break the model rather than fix it, because the
TWO sign-extensions cancel:

```lean
def x86_idiv128 (hi lo d : Int) : Option (Int × Int) :=
  if d = 0 then none
  else
    let n := hi * (x86_two64 : Int) + lo
    some (Int.tdiv n d, Int.tmod n d)
```

with, at the only call site (`lib/X86.lean`, the group-3 handler's `idiv r/m64`
arm):

```lean
match x86_idiv128 (x86_signed s.rdx) (x86_signed s.rax) (x86_signed a) with
```

For a NEGATIVE two's-complement dividend RDX:RAX, RAX's top bit is set, and so
is RDX's (they are the two halves of one 128-bit value). So with both halves
signed:

    (rdx_raw - 2^64) * 2^64 + (rax_raw - 2^64)
      = rdx_raw * 2^64 + rax_raw - 2^128

which is EXACTLY the two's-complement value of RDX:RAX. For a POSITIVE
dividend neither `x86_signed` fires and `n` is `rdx_raw * 2^64 + rax_raw`,
also exact. So the `lo` argument is correct on both signs, and replacing it
with `s.rax.toNat` would make `n` non-negative for a negative dividend — a real
regression, invisible for every non-negative dividend, which is precisely why
it would survive a casual test.

This is also why the note above `x86_div128`/`x86_idiv128` ("All 43 examples
agree, … the dividing ones (which is what pins the 128-bit group-3 results)")
is not evidence against the finding: `div` is unsigned and `idiv` is the signed
one, and the negative-dividend case is the one nothing in `formal/examples/`
exercises.

**So the two hypotheses left are:** (a) the QUOTIENT-OVERFLOW check the doc's
suspect 2 names — `x86_idiv128` returns the quotient of an arbitrary-precision
`Int` with no range check, where the hardware raises `#DE` — and (b) something
after the divide, in the remainder path (`add rax, r11` at `4c 01 d8`) or in how
`formal/x86_64_model_test.py` reads RAX. Note that the observed value is the
EXIT STATUS, read after `add rax, r11`, so the model's `q + 7` is 186 and `q`
is 179 (mod 256): the defect is a value 179 where the hardware has 4, not an
off-by-a-small-amount, which is a poor fit for the remainder arm and a good one
for a quotient computed from a wrong dividend.

## The exact next step, unchanged in shape and now cheaper

1. Single-step `udivmod`'s image and print `(rip, rax, rdx, rcx, r11)` at each
   boundary across the `cqo`/`idiv` pair. That is the measurement this doc was
   written for and it is a Lean run, so it belongs to whoever can do one. RAX
   `0x6db6db6db6db6d`-ish across the pair says the quotient came from the wrong
   dividend; RAX and RDX correct across it and wrong after says the fault is in
   `add rax, r11` or in the harness.
2. If and only if that says the dividend is wrong, the fix is in the CANDIDATE
   set, not in `x86_idiv128`'s signature — check `x86_split128`'s handling of a
   NEGATIVE product (`let lo := p % x86_two64`, which is non-negative for
   negative `p` in Lean, and `(p - lo) / x86_two64`, which floors) against what
   `imul`'s RDX:RAX actually holds. `cqo`'s own encoding is
   `if x86_msb v then 0xffffffffffffffff else 0`, i.e. an all-ones sign
   extension, so a negative dividend reaching `idiv` has `rdx` all ones — and
   `x86_signed` of that is `-1`, which is right.
3. Add the `#DE` range check to `x86_idiv128` as its OWN step, separately: it
   is a refusal, `x86_step`'s contract already returns `none` for anything it
   cannot model, and folding it into the same commit would make it impossible to
   tell which of two changes moved the 44/45 count.
4. `formal-x86-machine-model`'s `expect=` marker states `1 of 45 WRONG:
   udivmod`, so a change that does not move that count is reported as a
   FAILURE rather than absorbed — which means the experiment is self-checking
   and cannot be "done" by inspection.

## Original report

Found 2026-10-02 by running `formal/x86_64_model_test.py` for
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

- The reason this was invisible is its own bug: the estate check's walk
  counted `test_*.py` and not `*_test.py`, so this file was in no spec and in
  no `UNREGISTERED`. Fixed by `test_suite.py`'s `is_test_file_name` and by
  the registration above, both in the same commit as the first run of this
  file; `scripts/bootstrap_full_test.py` is the other file that widened.
- `formal/x86_64_model_test.py`'s own docstring is the right description of
  why this class of bug survives a typechecker: "A machine model that has only
  been typechecked is worth very little: it can be wrong in ways Lean's kernel
  will never notice, because every definition in it is trivially well-typed."