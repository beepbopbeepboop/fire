# FORMAL_x86_64_instruction_coverage_backlog: the x86-64 half of the ISA census, form by form

**Found 2026-10-05 by `tools/formal_isa_census.py`**, the instruction-coverage
census, which prints the matrix for BOTH backends. arm64 is closed: every one
of its 77 emitted forms has a model arm, a fuzz case and an `as` differential,
with the exceptions named in `formal_isa_census.HARNESS_LIMITS` (eight, each a
property of the harness) and `.BACKLOG` (twelve, each with its own doc). This
file is the x86-64 answer, and it is **not** closed: 18 of the 85 emitted forms
have no fuzz case, no model sample, or no decoder arm.

It is one document rather than eight because the gaps are not eight problems.
They are three shapes, and the shapes are what a reader wants.

## What I ran

```
$ python3 tools/formal_isa_census.py --arch x86_64 | tail -22
   -- 0 form(s) with no LEAN/FUZZ/AS and no exemption; 23 exempt (5 harness, 18 backlog)
```

`0` there means every gap is EXEMPTED, and this file is where 18 of those
exemptions point. The tool's own numbers, not a count stated here: run it.

## Shape 1: SSE2 scalar binary64 (9 forms) — no decoder, no model, no pool

`encode_addsd_xmm`, `subsd`, `mulsd`, `divsd`, `ucomisd`, `xorpd`,
`movq_r64_xmm`, `cvtsi2sd_xmm_r64`, `cvttsd2si_r64_xmm`. All nine are called by
`formal/x86_64_codegen.py` (the `formal_examples.py` host module's `printf`
path and the float arithmetic) and all nine are byte-checked against clang's
assembler in `test_x86_64_encoders.py`. None of them can be NAMED: 

* `formal/x86_64_decode.py` has no `0xF2 0x0F 0x58` arm, so `decode_one`
  refuses — which means `formal/x86_64_proof_gen.py`'s `decode_function_body`
  and `formal/x86_64_endtoend_test.py`'s `_body` cannot walk an image
  containing one, and both report it as "no step lemma wired for: …";
* `formal/x86_64_model_coverage_test.py::samples()` has no sample of any of
  them, so `x86_step` is never asked;
* `formal/x86_64_model_fuzz.py`'s pool has no entry.

The arm64 counterpart of this gap is `bugs/FORMAL_arm64_ieee754_has_no_step_
arms.md`, and it says the same thing about the same ten instructions. Read that
one for what closing it costs on the model side; the x86-64 half additionally
needs the decoder, because on arm64 the emitter's words are classified by
`_STEP_CONDS` (a mask table) rather than by a decoder.

**Next step**: one form, `ucomisd`, end to end — a decoder arm, a sample in
`x86_64_model_coverage_test.py`, a pool entry. The compare is the interesting
one: `UCOMISD` reports UNORDERED with ZF=PF=CF=1, which is why
`formal/x86_64_codegen.py` follows it with `andb`/`setnp` rather than reading
one flag, and a model that decoded it as an integer compare would agree with the
hardware on every ordered pair and disagree on `NaN`.

## Shape 2: forms the emitted encoder has and the DECODER cannot name (4)

| encoder | what it is | why nothing downstream can see it |
|---|---|---|
| `encode_imul_r64_r64_imm` | `69 /r id`, the `x * 10` shape | the decoder's `imul` arm is `0x0F 0xAF` only |
| `encode_call_r64` | `FF /2` with `mod=11`, the call through a function VALUE | the decoder maps `FF` only to `FF 15` / `FF 25` (the RIP-relative forms) |
| `encode_and_r8_r8` / `encode_or_r8_r8` | the byte-wise `and`/`or` the floating compare needs | no REX.W, and the decoder's ALU arm is `w and …` |

Each of these is byte-checked against clang today (`test_x86_64_encoders.py`'s
new rows: `imulq $7, %rbx, %rax`, `andb %cl, %al`, `orb %cl, %al`), which is
why this gap is a NAMING gap and not an encoding gap — and why it is invisible
to every other check in the tree.

**Next step**: the three decoder arms, each with a `samples()` row so the
coverage test asks `x86_step` about it, and each with a `test_x86_64_decode.py`
row. `encode_movq_xmm_rm64` is the fourth in this shape and is already decodable
(`0x66 REX.W 0F 6E`); it only lacks a coverage sample and a pool entry.

## Shape 3: runnable, and the pool does not draw them (5)

`encode_jcc_rel32`, `encode_jmp_rel32` — the pool draws only the rel8 branch,
while `formal/x86_64_codegen.py` emits the rel32 spelling past a 128-byte reach.
`encode_call_rel32` — a call cannot run in a straight-line stub without leaving
it. `encode_lea_r64_rip` — RIP-relative, so it belongs in `HARNESS_LIMITS`
alongside arm64's `encode_adrp` (the two engines' RIPs differ by the load
slide); it is in `BACKLOG` only because moving it is a one-line edit to this
tool and the edit has not been made.

**Next step**: add `jcc_rel32`/`jmp_rel32` to `formal/x86_64_model_fuzz.py`'s
pool as a branch to the NEXT instruction (the same shape as its rel8 entry, and
`formal/x86_64_endtoend_test.py::_BRANCH_FORMS` already treats them as one
family), and move `encode_lea_r64_rip` to `HARNESS_LIMITS`.

## What is NOT a gap here, so nobody re-derives it

* **`encode_je_rel8` / `encode_jne_rel8`** read `FUZZ: no` to a naive grep and
  are covered: both bottom out in the private `_jcc_rel8`, and the pool draws
  every condition code through `encode_jcc_rel8`. `formal_isa_census._
  delegating_encoders` follows that, and the census reports `yes`.
* **The ten `encode_set*` encoders** are drawn by the pool through
  `getattr(X, "encode_set" + nm)`, which an attribute-only AST walk cannot see.
  `_resolve_getattr` resolves it from the tuple that feeds the comprehension, so
  the answer comes from the ten NAMES rather than from a prefix match — which
  matters, because `setp`/`setnp` are deliberately NOT in that tuple (the model
  does not evaluate parity) and a prefix rule would have claimed them.
* **The memory forms' REX byte.** `as` writes `8b 45 f8` where this backend
  writes `40 8b 45 f8` (a null REX) and writes `48 0f b6` where this backend
  writes `40 0f b6` (no REX.W on a zero-extending load). Both are the same
  instruction; `test_x86_64_encoders.py`'s `REX_VARIANT_CASES` checks that the
  two differ in the REX byte and in NOTHING ELSE, which is the property a field
  in the wrong place would break.