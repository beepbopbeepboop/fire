# The binary64 semantics is modelled; the FP STEP FUNCTIONS are not, and a float program cannot be proved yet

**Area:** FORMAL (the Lean machine model). Claim `project26:float`, found
2026-10-04 on `work/formal26-float`. **PARTIALLY FIXED** — the semantics landed
in `lib/IEEE754.lean` and is checked by Lean's kernel where that is possible; the
step functions did not, and this is what is left. What DOES work today is the
whole codegen: a float program builds, links, runs, and answers CPython on both
architectures (`test_formal_run.py`'s 21 `FLOAT_CASES`, all `== CPython`).

## What was run

```
$ cat .tmp/flt/proof.mojo
def main(n: Int) -> Int:
    var a = 1.5
    var b = 2.25
    var c = a + b
    if c > 2.0:
        return 1
    return 0

$ python3 fire.py build --formal -o proof.arm64 proof.mojo     # proof ON
  File "formal/arm64_proof_gen.py", line 1081, in _expr_go
    raise NotImplementedError(
NotImplementedError: model: a FloatLiteral has no value in the semantic model
(a `UInt64 → UInt64` function over the source's arithmetic); refusing rather than
modelling it as 0, which would be a false statement about the source
```

So the refusal is HONEST — it declines rather than admitting a false `0` — but it
escapes as a traceback rather than a `CodegenError`, and with `--no-prove` off
there is no way to build such a program at all.

## What landed, and what is still missing

**Landed.** `lib/IEEE754.lean`, 24 declarations, 0 `sorry`, 0 `axiom`, added to
`formal/lean.py`'s `LIBRARY_MODULES` (first, because it imports nothing) and
therefore to the hole census and the axiom census. Measured by a real
`#print axioms` run over all 24: **19 reach a decide axiom, 5 are
kernel-checked**, and the 5 are exactly the COMPARISON section. That split is the
design, and it is why the comparisons are modelled bit-level and the arithmetic
is not:

| section | modelled over | decidable by | cost |
|---|---|---|---|
| `isNaN`, `isInf`, `isFinite`, `comparable`, `key`, `ltBits`, `leBits`, `eqBits`, `neBits`, `gtBits`, `geBits` | `UInt64` / `Bool` | **`decide`** — kernel-checked | 0 sites |
| `faddBits`, `fsubBits`, `fmulBits`, `fdivBits`, `fnegBits`, `fromIntBits` | Lean's `Float` | **`native_decide`** only | 19 sites |

`Float.ofBits` / `Float.toBits` are compiled primitives, so `decide` cannot
reduce them: measured, `decide` on `Float.toBits (Float.ofBits p) = p` gets stuck
at the `UInt64.decEq` instance and reports *"reduction got stuck"*, while the same
proposition closes under `native_decide`. The alternative was a from-scratch
bit-level IEEE implementation — kernel-checkable, and a SECOND implementation of
arithmetic both machines already perform, with its own rounding bugs. So the
arithmetic goes through `Float` and its cost is named in
`test_formal_admitted.py`'s `NATIVE_DECIDE_ALLOWED`, per declaration, with the
reason.

**The one thing that is NOT bit-exact, stated in the file rather than left to be
found:** a NaN's payload is not preserved through `ofBits`/`toBits` — Lean
normalises a NaN to the canonical quiet one
(`ofBits_toBits_normalises_a_nan_payload`). Every VALUE statement is unaffected,
because `isNaN` reads the pattern of the ANSWER rather than of the operand, but
no statement about a NaN's bits is reproducible through these functions.

**Missing, in the order it has to be done.**

1. **`Arm64State` needs V0..V7 and `X86State` needs XMM0..XMM15.** This is the
   blocking step and it is not small: both are `structure`s whose `Inhabited`
   instances, every `record` update and every theorem that names a field has to
   follow. `IEEE754`'s functions are written to be `rfl`-reachable from a step arm
   the moment the registers exist, which is why they take and return a `UInt64`
   and nothing else.
2. **`arm64_step`'s decode arms** for `FADD`/`FSUB`/`FMUL`/`FDIV` (mask
   `0xFFE0FC00`, bases `0x1E600800` / `0x1E601800` / `0x1E602800` /
   `0x1E603800`), `FNEG` (`0x1E614000`), `FCMP` (`0x1E602000`), `FMOV`
   (`0x9E670000` G→V, `0x9E660000` V→G), `SCVTF` (`0x9E620000`), `FCVTZS`
   (`0x9E780000`) — the words are already in `formal/arm64.py` and are checked
   against `as -arch arm64` by `test_arm64_encoders.py`.
3. **`x86_64_step`'s arms** for `ADDSD`/`SUBSD`/`MULSD`/`DIVSD` (`F2 0F
   58/5C/59/5E`), `UCOMISD` (`66 0F 2E`), `MOVQ` both ways (`66 REX.W 0F 6E` /
   `7E`), `CVTSI2SD` (`F2 REX.W 0F 2A`), `CVTTSD2SI` (`F2 REX.W 0F 2C`), and the
   flag-setting semantics the emitters' condition codes rely on — `unordered`
   sets `ZF=PF=CF=1`, which is the whole reason `IEEE754.eqBits` tests the PARITY
   bit as well as equality.
4. **`MojoExpr` needs a float literal and the arithmetic nodes**, and `evalExpr`
   needs to call `IEEE754.faddBits` and its siblings. `evalExpr` is a
   `UInt64 → UInt64` function and that is already the right shape; what is missing
   is that a `FloatLiteral` is not a `MojoExpr` constructor today.
5. **`formal/arm64_proof_gen.py` / `formal/x86_64_proof_gen.py` need the per-
   instruction step lemmas**, one per new instruction, in the shape the existing
   ones take. This is the part that costs the most Lean time and the part the
   `x86_64_endtoend_chain_times_out_past_a_hundred_steps` measurement says to
   watch.
6. **`formal/model.py`'s semantic model needs a float kind**, so
   `arm64_proof_gen.py::_expr_go` stops refusing. Its refusal text
   ("refusing rather than modelling it as 0, which would be a false statement
   about the source") is the right decision and the right reason; what is missing
   is the alternative it names.

## Two measurements from this slice that the next step needs

**Lean's `Float.ofInt` agrees with CPython.** `Float.ofInt 9007199254740995`
elaborates to `0x4340000000000002`, and CPython 3.14's `float(9007199254740995)`
is `9007199254740996.0`, which is the same word. So the model's int→float half
can go through `Float.ofInt` rather than needing a hand-rolled conversion — worth
recording because the obvious fear (a Lean Int conversion that rounds
differently) is false, and it was checked rather than assumed.

**`IEEE754`'s `key` has to normalise the zeros before flipping the sign bit.**
The bare flip (`b ^^^ 0x8000000000000000`) maps `+0.0` to `0x8000…` and `-0.0`
to `0x0000…`, so the two zeros get different keys: `+0.0 < -0.0` and
`+0.0 != -0.0`, both false, where IEEE-754 §6.3 says they are equal. Measured:
`native_decide` on `eqBits 0x0000000000000000 0x8000000000000000` answered
`false` with the bare flip. Clearing the sign bit of a zero first fixes it and
keeps every nonzero value distinct. **A model that got this wrong would have
been consistent, provable and wrong** — the same failure shape as an integer
`EQ` for an unordered compare, one level down.

## Three order-theory theorems are NOT in `IEEE754`, and that is stated in the file

`ltBits`'s asymmetry and transitivity over binary64, and `leBits`'s reflexivity,
are out of reach of both tactics on this toolchain: `omega` handles `Nat` and
`Int` and not `<` on a 64-bit word, and `decide` cannot decide a universally
quantified `UInt64` comparison at this width. The route is a `Nat`-valued `toNat`
on `key` with the order restated over it. Nothing in the module DEPENDS on those
three, and every reading in it is a function the two machines' compare
instructions are asked to implement — but "the model's order is not yet proved to
be an order" is a statement about the model's completeness and belongs in the file
rather than in a reader's head.