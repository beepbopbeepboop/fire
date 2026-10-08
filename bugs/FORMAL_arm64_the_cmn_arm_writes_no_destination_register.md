# The `CMN` model arm claims the whole `0xab000000` class, so `ADDS Xd, Xn, Xm`
# with `Rd ≠ 31` writes NO register

**Status update 2026-10-07 (`work/formal125-docs`): FIXED IN SOURCE; the
`lib/ProofLib.lean` build is still owed to the integrator.** The `0xab000000`
arm now reads `Rd` and writes it
(`arm64_set_reg rd { s with nzcv := arm64_adds_flags (arm64_reg rn s) (arm64_reg xm s) } (arm64_reg rn s + arm64_reg xm s)`),
`work_step_cmn` states BOTH facts, `_step_rhs`/`_step_rhs_generic` for index 66
mirror it, and `_regs_written` for index 66 is `{rd}` when `rd ≠ 31` and `set()`
for the `CMN` spelling (which also corrects the same staleness for index 6,
whose `SUBS Xd` spelling the model already wrote). The CPU-vs-model row
`adds x11, x1, x15`, pinned beside the existing `cmn`, is in
`test_formal_call_proof_gen.py::TestUnsignedOffsetAccess`. **What this worker
could not do is rebuild `lib/ProofLib.olean`** — measured here with
`ensure_library`'s own invocation it breaches the 8 GB worker ceiling (the
sibling doc has the measurement) — so the library build and the CPU-vs-model
test are the integrator's. The model change itself was verified in ISOLATION,
which is the part a bounded worker can do: a scratch file importing the served
`ProofLib.olean` and carrying the modified `arm64_step` + `work_step_cmn`
elaborates (rc=0, 1.4 GB) and `#eval`s `adds x11,x1,x15 → 7` and
`cmn x1,x15 → x11 unchanged (0)`.

**Area:** FORMAL (the arm64 machine model's flag-setting-compare arm).
**Status: OPEN, MEASURED on the CPU, and it is a SOUNDNESS defect rather than an
incompleteness — `arm64_step` returns a state that is not the machine's.** Not
fixed: the fix is a `lib/ProofLib.lean` change, and that build peaks at
**9.8 GB** measured with `formal/lean.py::ensure_library`'s own invocation —
over a bounded worker's 8 GB ceiling, under the tree's `LIBRARY_MEMORY_MB =
12288`, so the blocker is memory alone and the library is not broken.

(The measurement has a trap: `run_lean`'s `heartbeats=0` becomes `-T 0` =
`maxHeartbeats 0`, and a build under it fails with a `bv_decide` "unknown join
point" cascade at 7.1 GB that looks exactly like an unbuildable library.
`bugs/FORMAL_contract_ladder_reach.md` carries the full note.)

## 1. What I ran

One instruction, run on the CPU and asked of `arm64_step`, through the FUZZER'S
OWN harness (`tools/formal_model_fuzz.py`'s `assemble` / `run_native` /
`run_model`) so that nothing here re-implements a comparison the tool already
owns — the encoding comes from `as`, so this is a MODEL finding and not an
encoder one:

```console
$ python3 tools/memslot.py --gb 4 --label fm -- python3 .tmp/min_repro.py
  model: 5 case(s) evaluated
adds x11, x1, x15                        0xab0f002b
cmn  x1,  x15                            0xab0f003f

case 0  adds x11, x1, x15   cpu=OK model=OK
   MISMATCH x11  cpu=0000000000000007 model=0000000000000000
case 1  cmn  x1,  x15       cpu=OK model=OK
```

(`x1 = 3`, `x15 = 4`, so the sum is 7.)

## 2. What I expected

`ADDS Xd, Xn, Xm` writes `Rd` AND the flags. `cmn x1, x15` is the same
instruction with `Rd = 31`, i.e. `ADDS XZR, Xn, Xm`, and writes no register.
The two differ only in `Rd`, so a model that gets one right and the other wrong
is reading `Rd` and then not using it.

## 3. What is wrong

`lib/ProofLib.lean:2626-2631`:

```lean
  else if (insn &&& 0xffe00000) = 0xab000000 then
    -- CMN Xn, Xm: `ADDS XZR, Xn, Xm` — the flags of the SUM, not of a
    -- difference. No register moves (`arm64_set_reg 31` is the identity, which is
    -- also how the CMP arm spells its `Rd`).
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some { s with nzcv := arm64_adds_flags (arm64_reg rn s) (arm64_reg xm s) }
```

The mask `0xffe00000` covers the WHOLE class — `Rd` is bits 4:0 and is not in
the mask — and the body never reads it. `arm64_set_reg 31` being the identity is
what makes the comment true, and it is true **only for `Rd = 31`**, which is the
one spelling of this class the arm was written for. Every other `Rd` in the class
is silently dropped: the model sets the flags correctly and leaves the
destination at its old value.

**It is reachable in a real image.** `encode_adds_xd_xn_xm` is WIRED —
`tools/arm64_insn_audit.py::unwired_encoders` does not list it, so a lowering
in `formal/` emits it — and `formal/arm64.py:394`'s own docstring says it is
`formal/model.py::int_overflow_traps`'s `+` arm, i.e. the signed-overflow check
for `+` is *this instruction*. So the instruction the backend emits for `+`
overflow detection is one the model under-steps.

## 4. Why it matters more than a fuzzer tally

The fuzzer counts it as `WRONG`, in the same bucket as a shifted-register
mismatch. It is worse than that: a `WRONG` step means any theorem emitted over
an image containing `ADDS x11, x1, x15` reasons about a state the machine never
reached. This is the `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §2
rule ("a `sorry` over a false statement is indistinguishable from one over a
true one") with the false statement one layer down, in the MODEL rather than in
the emitter.

## 5. The exact next step

The arm needs `Rd`, and `arm64_adds_flags` is already right, so the fix is
inside the existing body rather than a new arm:

```lean
  else if (insn &&& 0xffe00000) = 0xab000000 then
    let rd  := (insn &&& 0x1f).toNat
    let rn  := ((insn >>> 5) &&& 0x1f).toNat
    let xm  := ((insn >>> 16) &&& 0x1f).toNat
    let s'  := { s with nzcv := arm64_adds_flags (arm64_reg rn s) (arm64_reg xm s) }
    some (arm64_set_reg rd s' (arm64_reg rn s' + arm64_reg xm s'))
```

with `arm64_set_reg 31` the identity this needs no `if`, and then:

1. a `work_step_*` lemma for the class stating BOTH facts — the flags and
   `Rd`'s new value — and the `¬` facts for every earlier arm, per the
   append-don't-edit rule `bugs/FORMAL_arm64_step_cannot_step_nine_wired_
   encodings.md` §Status item 2 records;
2. a `_STEP_CONDS` row and a `_step_rhs` row in the SAME commit, or the
   generator's generated proof fails to elaborate with the eight Lean-checking
   formal gate tests disabled — which is exactly the failure mode that doc
   names;
3. the CPU-vs-model row in `test_formal_call_proof_gen.py::TestUnsignedOffsetAccess`
   for `adds x11, x1, x15` and for `cmn x1, x15`, so the two spellings are
   pinned TOGETHER — a model that fixed one and broke the other would pass a
   test that pinned either alone.

The encoder needs no change: `formal/arm64.py:394`'s docstring already says
`adds x0, x0, x1` assembles to `0xab010000` and `as` agrees here.

## 6. Provenance

Found while re-measuring `bugs/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md`,
whose §3 prescribed this arm ("`CMP` is `CMN` with the operands the other way
round, so all three are one-line changes to an existing arm's shape"). The
prescription produced the arm; the arm took the whole class. That doc's Status
is corrected with the same measurement. The sibling defect found in the same
sweep — the `imm12` arms dropping their `lsl #12` — is
`bugs/FORMAL_arm64_the_extended_immediate_arms_ignore_their_shift.md`.
## 7. Confirmed a second way, without the fuzzer (2026-10-05)

The fuzzer's `run_model` passes `heartbeats=0` to `formal/lean.py::run_lean`,
which becomes `-T 0`, so its model side is NOT the invocation
`ensure_library` uses. A finding that rests only on it would be worth one
independent check, so here is one: `#eval` over the prebuilt
`lib/ProofLib.olean`, through `run_lean` with **no** `heartbeats` override, on a
state with `x1 = 3`, `x15 = 4`, `x14 = 9`, `x29 = 5`, reading the instruction
word little-endian at `pc = 0x1000` the way `arm64_read_insn` does.

```
#eval (match arm64_step s0 (codeAt 0xab0f002b) with   -- ADDS x11, x1, x15
       | none => 999 | some s => s.x11.toNat)
0                                    -- hardware: 3 + 4 = 7

#eval (match arm64_step s0 (codeAt 0xab0f003f) with   -- CMN x1, x15
       | none => 999 | some s => s.x11.toNat)
0                                    -- hardware: 7's slot untouched, so 0 -- CORRECT
```

Same two words, same run, one right and one wrong, which is the whole claim:
the defect is the missing `Rd`, not the flag computation and not the byte
layout. The sibling `imm12` defect is confirmed the same way in
`bugs/FORMAL_arm64_the_extended_immediate_arms_ignore_their_shift.md`.
