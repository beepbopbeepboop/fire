# `ProofLib.arm64_step`'s SUB-register arm shadows `NEG`, so `NEG Xd, Xn` is modelled as `SP - Xn`

**Area:** FORMAL, arm64 — `lib/ProofLib.lean`'s `arm64_step` if-chain, against
`formal/arm64.py::encode_neg_xd_xn` and `formal/arm64_codegen.py`.
**Status: OPEN, measured, NOT FIXED — found as a blocker while landing
`FORMAL_floor_division_on_a_signed_operand_is_truncated.md`, which had to route
around it rather than through it. Filed from `work/formal21-4`.**

## What is wrong

`arm64_step` tests the SUB-register form (`0xcb000000`) **before** the NEG form
(`0xcb0003e0`), and the two overlap completely: `NEG Xd, Xn` is an alias of
`SUBS Xd, XZR, Xn`, whose encoding is `0xcb0003e0 | (Xn << 16) | Xd` — the same
mask the SUB arm matches. So every `NEG` in an image is read by the SUB arm, as

    SUBS Xd, X31, Xn          (Rn field = 31)

and that arm computes `arm64_reg_or_sp 31 s - arm64_reg xn s`, i.e.
**`s.sp - Xn`**, because `arm64_reg_or_sp 31 s` is defined as `s.sp`
(`lib/ProofLib.lean:1460-1466`) and the arm reads `Rn` through it on purpose —
its own comment says so, for `cmp sp, floor`.

**The hardware disagrees, and it is the hardware that is right.** In the
flag-setting SUB/SBC forms A64 reads `Rn = 31` as the ZERO register, not as SP;
the SP form belongs to the non-flag-setting `ADD`/`SUB`. The emitted NEG runs
correctly on the machine — measured, every `//` and `%` row of the floor-division
doc's table answers CPython's value on both architectures — so the encoding
computes `-Xn` and the model computes `SP - Xn` for the same word.

    $ python3 -c "print(hex(0xcb0003e0 | (5 << 16) | 6))"
    0xcb0503e6
    # (0xcb0503e6 & 0xffe00000) == 0xcb000000   → the SUB arm matches
    # (0xcb0503e6 >> 5) & 0x1f  == 31           → Rn = 31 → arm64_reg_or_sp = SP
    # (0xcb0503e6 >> 16) & 0x1f == 5            → Rm = 5

## The two spellings this construct has already emitted once

`formal/arm64_codegen.py::_emit_floor_remainder` reached for `NEG` first and
this doc's blocker is what came back; the NEXT spelling it reached for is a
second, independent instance of the same class and is recorded here because
nobody should have to rediscover it either:

    `MSUB X6, X1, X5, XZR`   # 0x9b05fc26 — "-(d * c)"

`MUL`'s mask is `0xffe07c00` and `MSUB`'s is `0xffe08000`, and **both accept a
word with `Ra = 31`**; `arm64_step` tests MUL first, so the model reads the
word as `X1 * X5` — `+d*c` — and the residual goal came out as `r - d*c`, the
correction with the wrong sign. `encode_msub_xd_xn_xm_xa`'s `0..30` range assert
is what kept the second one from being emitted; that assert is now documented as
load-bearing rather than incidental.

Both are pinned by `test_formal_call_proof_gen.py::TestFloorCorrectionDecodes`,
which asserts that the emitter does not produce either word AND (so the row
cannot rot into "the encoder refuses it") that each one decodes as the wrong
instruction today.

## How it was found, and what it costs

`formal/arm64_codegen.py::_emit_floor_remainder` emitted the obvious spelling
of the `//` correction's product — `NEG X6, X5 ; MSUB X0, X1, X6, X3` — and the
generated proof for `formal/examples/udivmod.mojo` failed on **every** concrete
input, including the ones where the correction is zero:

```
udivmod_proof.lean:81:2: error: Tactic `native_decide` evaluated that the proposition
  run_result_exit … udivmod_code 4294968228 200000 = mojo 10
is false
```

`is false` on `n = 0, 1, 2, 5, 10` alike is the signature of a model that
computes something different from the instruction, rather than of a goal that
could not be closed: the image itself answers `4` for `n = 10`
(`./output/udivmod.aout -n 10; echo $?`), which is CPython's `10 // 7 + 10 % 7`.

**This is live on `master` today, on an emitted instruction nothing proves.**
`formal/arm64_codegen.py:3352` emits `encode_neg_xd_xn(0, 0)` for a unary minus
on an expression, so `-x` with `x` a variable is modelled as `SP - x` and any
proof of a program containing one is either wrong or absent. No example in
`formal/examples/` has a unary minus on a non-literal, which is why nothing
red.

**And the fix for it is NOT "make the SUB arm read XZR".** `sub x0, sp, x16`
(`SUBS`-family, `Rn = 31`) really does read SP — `TestRegister31` asks clang
rather than the model — and it is the SAME `arm64_step` arm. So the two forms
share an encoding and must be told apart by something other than `Rn`, and the
step below says what. What the floor-division fix did instead was route around
it: see §"The two spellings this construct has already emitted once" below.

## The audit that should have caught it, and why it did not

`formal/arm64_proof_gen.py::audit_step_table` compares `_STEP_CONDS` with
ProofLib's decoder conditions and, for every OVERLAPPING pair, checks that
ProofLib tests the earlier one first. It reports overlaps as notes
(`entry 3 shadows entry 5`) and raises only on a reversed pair — and here the
order is the same on both sides, so the audit has nothing to say: `_STEP_CONDS`
shadows NEG with SUB-register exactly as `arm64_step` does, the generated `sr`
lemmas say `s.sp - x`, and the model agrees. **Two agreeing wrong answers read
as a green run**, which is the same lesson `FORMAL_fuzz_ledger.md` §3.4 records
for `int(s, base)` and §4.5 for the internal-error verdict.

## The test that already has the right answer, on a branch it cannot reach

`test_formal_call_proof_gen.py::TestRegister31` asks **clang** which forms have
an SP encoding — `add x0, sp, x16`, `sub x0, sp, x16`, `cmp sp, x16`,
`cmp sp, #16`, `add x0, sp, #16` — and requires `ProofLib.arm64_step`'s branch
for each to read `Rn` through `arm64_reg_or_sp` exactly when the assembler
accepts it. Its table carries the NEG form on the OTHER side:

```python
    # …and the five whose 31 is the ZERO register.  They are in the table
    # because they are the direction a "31 means SP everywhere" change gets
    # wrong, and a test that only checked the accepting forms would not notice.
    ...
    ("neg x0, sp", "= 0xcb0003e0 then"),
```

**So this file already states that the NEG branch must not read register 31 as
SP, and it is right — and it passes vacuously**, because the test reads the
branch's SOURCE TEXT (`_arm64_step_branch(src, "= 0xcb0003e0 then")`) and the
branch is unreachable: `arm64_step` tests `0xcb000000` first. That is the whole
defect in one sentence: the tree has an oracle for the question, a docstring
carrying the answer, and no check that the branch the oracle answers for is one
the decoder can reach.

`TestFloorCorrectionDecodes` (added with
`FORMAL_floor_division_on_a_signed_operand_is_truncated.md`, in the same file)
is that missing check for the one construct that emits into this corner: it runs
the emitter on `n % 3`, takes the division block's words, and asks the
generator's own decoder what each word IS.

## The next step

1. **Make the NEG branch reachable, and decide what `Rn = 31` means in the
   flag-setting and non-flag-setting SUB/SBC forms separately.** The
   architecture's answer is what `TestRegister31` already encodes: SP where the
   form has an SP encoding, zero register everywhere else — and the two cannot
   share one `arm64_step` arm the way they do now, because `arm64_step`'s
   SUB-register arm is reached by *both* `sub x0, sp, x16` (SP) and
   `neg x6, x5` (zero). Narrowing the SUB arm to exclude `Rn = 31` and giving
   `NEG` its own condition is the shape; the assembler is the oracle for which
   is which and the test already asks it.
2. **Make `TestRegister31` reach the branches it checks.** Keying on the
   comment (`= 0x… then`) finds the text; it does not find out whether any word
   can arrive there. `_step_branch_index` over each form's actual encoding
   answers that in one line per row, and a row whose branch index is not the one
   the table names is exactly the NEG defect this file is about.
3. **Add a program with a unary minus on a variable to `formal/examples/`**, so
   the arm is in the proving corpus at all. `formal/examples/neg.mojo` is a
   two-line fixture and its absence is why nothing red for this.

Nothing here is fixed on `work/formal21-4`, and no claim in
`tools/control.py` was checked against: `FORMAL_arm64_instruction_coverage` and
`FORMAL_arm64_known_proof_gaps` are `formal21-3`'s, and the `arm64_step` table
is shared, so this is reported rather than edited.