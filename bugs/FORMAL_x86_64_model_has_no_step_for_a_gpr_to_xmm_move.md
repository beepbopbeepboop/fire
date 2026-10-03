# FORMAL_x86_64_model_has_no_step_for_a_gpr_to_xmm_move: `lib/X86.lean` does not decode `movq xmm, r64`, so a proved x86-64 build of a floating `printf` loses its instruction certificates

**Area:** x86-64 machine model (`lib/X86.lean`) — another worker's file, see
"Whose file" below. **Status: OPEN, NOT FIXED, and NOT MEASURABLE on this tree
for a second and independent reason that is also not mine.** Found while landing
`bugs/FORMAL_x86_64_a_float_printf_operand_reads_XMM0.md` (deleted by that
commit), whose fix is `encode_movq_xmm_rm64` — the first instruction this
project has emitted into a formal x86-64 image that crosses from a general
register into an SSE one.

## What I ran and what I saw

The fix emits `66 REX.W 0F 6E /r` for every operand a floating `printf`
conversion reads. That byte sequence is new to this path, so the two readers of
an instruction stream were asked about it, and both decline — in the designed
way rather than by crashing, which is why the fix itself lands clean:

```
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o out .tmp/f1.mojo
Built: out  [x86_64/macho]        # runs, prints 3.141593
```

```
formal/x86_64_decode.py:284   raise DecodeError(f"undecodable byte 0x{op:02x} …")
lib/X86.lean:560              else if op = 0x0f then … else none
```

`formal/x86_64_proof_gen.py`'s `_decode_function_body` (`:366`) catches
`DEC.DecodeError` and returns `[], 0`, and `_step_certificate_section` then
emits the "the image did not decode" comment instead of one theorem per
instruction. So the effect is **one proved image loses its per-instruction
certificates**, not a build that fails.

**And the run tests were already suppressed for this image anyway**, which is
what keeps this a coverage loss rather than a new red:
`_run_tests_section`'s own docstring (`:466`) says `externs` "suppresses the
whole section for an image that calls out to the runtime … the branch lands
outside the image and the run stops". An image containing `printf` is an image
with an extern. So a floating-`printf` program had no run tests before this and
has none now; what it loses is the certificate list.

## What it costs, precisely

`formal/examples/*.mojo` — the 44 programs the x86-64 model test runs — contain
no floating conversion, so nothing measured changes: the new instruction is
emitted only for a call in `model.PRINTF_TEXT_CONVERSIONS_CALLEES` whose format
string names a floating conversion, and no example prints a double. That is the
whole blast radius and it is genuinely zero **today**; it is the first
`printf`-with-a-float in a PROVED x86-64 build that costs anything, and the cost
is a proof file with a comment in it where a list of theorems was.

## The exact next step

One arm in `lib/X86.lean`'s `0x0F` escape, beside the existing `0xAF`/`0xB6`
arms at `:576`:

```lean
else if op2 = 0x6e && w then
  -- movq xmm, r/m64: the SSE register takes the 64 bits of the GPR.
  -- `x86State` HAS no XMM file, so the successor cannot record the value —
  -- which is the real question, not the decode. See "The part that is not
  -- one line" below.
  ...
```

and `formal/x86_64_decode.py`'s `0x0F` escape (`:227`) needs the matching
`0x6E` case so the certificates come back. **Decode first and step second** is
not available as a stopping point: the certificate theorem is
`(x86_step s code).isSome = true`, so decoding an instruction the step refuses
turns a lost list into a proof that does not typecheck.

## The part that is not one line, and is why this is filed rather than done

`lib/X86.lean`'s `X86State` (`:14`) is 16 `UInt64` GPRs and no XMM file at all —
`Frame.frameRead_in_range`'s docstring and `MojoExpr`'s "no aggregate node"
argument (`bugs/FORMAL_wide_receiver_by_reference.md` §"Is the one-word value a
true invariant?") both rest on that. A `double` that must be READ OUT of XMM0
by the C library is not a value this value model can carry, so the model cannot
say what `printf("%f", w)` computes — and it does not need to, because an image
with an extern has no run tests. What it CAN say is "this instruction decodes
and produces a successor", which for `movq xmm, r64` means writing something
into an XMM slot that does not exist, or adding eight `UInt64`s and the
register-save-area argument they need. **That is a decision about the machine
model, and it is formal8-14's** — `bugs/FORMAL_x86_64_end_to_end_proof.md`
opens with "Every x86-64 bug found and fixed while building the Lean formal
layer for the x86-64 backend — `lib/X86.lean` (the machine model and its step
lemmas)", and its "Bugs" table is the inventory of exactly these gaps.

## Whose file, and why it was not fixed here

`lib/X86.lean` and `formal/x86_64_decode.py` are claimed by `formal8-14`
(`bug:FORMAL_x86_64_end_to_end_proof`), whose docstring claims the model and the
proof generator explicitly. This worker was told to stop rather than edit another
worker's area.

**It could not have been MEASURED here either**, which is worth recording
because it is a second, independent blocker and not a matter of permission:
`lib/X86.lean` does not compile on this tree, so every Lean-checking formal
build fails before it reaches any of this.
`bugs/FORMAL_x86_64_cqo_step_lemma_contradicts_the_model.md` is the one-line
cause (`x86_step_cqo`'s conclusion still states the pre-`da151f0c` `cdq`
semantics while `x86_step` says `x86_cqo`), it is in the SAME file, and it is
also formal8-14's. **Fixing that one line is the prerequisite for measuring this
one**, and the two belong in the same commit or the second cannot be verified.
A worker holding `lib/X86.lean` should take both; the first is four lines and the
second needs the XMM decision.

## Verification of what IS here

| command | result |
|---|---|
| `python3 fire.py build --formal --no-prove --backend=x86_64 -o out .tmp/f1.mojo` then run | `f=3.141593`, byte-identical to arm64 |
| `python3 test_formal_x86_64_parity.py` | PASS=20 FAIL=0, including `printf_float_operand_read_from_an_xmm_register` |
| `python3 test_formal_math.py consts` | PASS — the printed-double comparison now runs on x86-64 |
| `python3 test_formal_time.py --backend x86_64` | 4/4 groups |
| `python3 test_formal_run.py limit_a_ninth_floating_printf_operand` | PASS (both backends refuse, each naming its own ABI's limit) |