# FORMAL_arm64_model_reads_register_31_as_zero: the arm64 model cannot read SP into a general register, so a stack-floor guard has no step and cannot be proved

**Status: OPEN, measured, not started — and no longer blocking anything, which
is worth more than the fix would have been. The stack-floor guard LANDED on
2026-10-03 (`formal/model.py`: `STACK_TRAP_STATUS`,
`STACK_FLOOR_BUDGET_BYTES`, `recursive_function_names`) WITHOUT this change,
because the guard reads SP into a scratch register with `ADD Xd, SP, #imm` —
one of the handful of forms whose `Rn = 31` case the model already spells as
`s.sp` — and the `CMP` after it names two ordinary registers. Measured through
`run_lean` against the real `lib/ProofLib.olean`: `ADD X16, SP, #0` yields
`s.sp`, `SUB X16, X16, #1920, LSL #12` yields `sp - 7.5 MiB`, and `B.LO` on
that compare takes the unsigned-lower branch. So this document is still a real
defect — a shifted-register form naming X31 is still modelled as zero — and
it is now a defect in the MODEL rather than a blocker in front of a guard. It
is a PROOF-side change and remains unlanded.**

**Area:** FORMAL (the machine model, both architectures).

## What I ran

Read the model against the one instruction a stack guard needs. Not a build and
not a run — there is nothing to run yet, because the guard has never been
written; the question is whether the model can DESCRIBE it, and it is a reading
of `lib/ProofLib.lean`:

```console
$ grep -n "def arm64_reg " -A 12 lib/ProofLib.lean          # :1252
$ grep -n "CMP Xn, Xm (register)" -A 5 lib/ProofLib.lean    # :1490
$ grep -n "if rn = 31 then s.sp" lib/ProofLib.lean | wc -l
```

## What I saw

**1. Register 31 is XZR in this model, everywhere except five hand-written
cases.** `arm64_reg i s` (`lib/ProofLib.lean:1252-1260`) matches
`| 30 => s.x30 | _ => 0`, so `arm64_reg 31 s = 0` and `arm64_set_reg 31 s v = s`
(`:1263-1275`). `Arm64State` has a separate `sp : UInt64` field (`:1236`), and
the SP reading exists only where a form's body spells it out:
`if rn = 31 then s.sp else arm64_reg rn s` — SEVEN spellings of it, in the
unsigned-offset load/store cases (`:1523`, `:1526`, `:1540`, `:1543`), the
unscaled LDUR/STUR ones (`:1654`, `:1656`, `:1666`), and the ADD/SUB-immediate
forms, which use a second and identical spelling
(`if (((w >>> 5) &&& 0x1f).toNat) = 31 then s.sp else …`, `:3840`, `:3881`,
`:4069`, `:4101`). Seven in one form of one file and four in another, no helper:
which is itself a smell, because the next form that needs it will either forget
or add an eleventh.

**2. The guard's comparison is a form that does not have the spelling.** The
guard is `cmp sp, floor` after the frame subtraction, which on arm64 is
`SUBS XZR, X31, X16` — the shifted-register form, `0xeb000000` masked
(`formal/arm64.py`'s `encode_cmp_xn_xm`, whose assert is on `Xm`, so SP-in-`Rn`
encodes). The model's case for it (`:1490-1493`) is

```lean
  else if (insn &&& 0xffe00000) = 0xeb000000 then
    let rn := ((insn >>> 5) &&& 0x1f).toNat
    let xm := ((insn >>> 16) &&& 0x1f).toNat
    some { s with nzcv := arm64_subs_flags (arm64_reg rn s) (arm64_reg xm s) }
```

so it computes `arm64_subs_flags 0 x16`. **The model's step for the guard's own
comparison is a comparison against zero.** A proof generated over it would
typecheck and would be about a different instruction than the one emitted, which
is the outcome this repository treats as the worst thing a formal backend can
do: silently wrong, and green everywhere.

**3. Every other instruction the guard needs is already modelled, and that is
what makes this the whole of the blocker.** `movz`/`movk` (the immediate
materialisation), `str`/`ldr` at a computed address, `cbnz` (the lazy fill),
`b.cond` (the `b.lo`, via `arm64_matches_condition` at `:1395`, which the CSET
case at `:1716` already uses) and `svc` (`:1756-1758`, a no-op step) all have
model cases. So
the guard needs exactly one thing the model cannot say, and it is the one thing
at the centre of it.

**4. x86-64 does not have the gap**, and that is not a consolation:
`x86_get_reg` (`:76-82`) maps index 4 to `s.rsp` directly, because SysV's
register 4 IS `rsp` in a `CMP r/m64, r64` — there is no XZR/SP ambiguity to get
wrong. Both halves of the guard were therefore landable, and both landed, on
2026-10-03: the x86-64 one because of this paragraph, and the arm64 one because
the guard does not spell `CMP SP, Xm` at all. (This section is what the
two-backend split in the stack-floor bug doc was warning about, and it is
recorded here because the way round it was a way round the SPLIT, not a way
round the gap.)

**5. The shadow-counter alternative is worse, and it is worth recording so it is
not proposed next.** The guard does not have to compare SP: a counter of bytes
still owed, in a callee-saved register, is charged on entry and credited in the
epilogue, and every instruction it needs uses ORDINARY registers —
`sub x18, x18, x17` and `cmp x18, x17` are `0xcb000000` and `0xeb000000` with
`Rn = 18`, which the model already reads correctly through `arm64_reg`. So it is
expressible, today. It costs: x18 reserved in every function on the path (a
platform register, and it is spare — but `formal/arm64_codegen.py`'s
`_CALLEE_SAVED` is 19..28, so x18 is currently scratch and whatever uses it as
scratch has to be counted), ~9 extra instructions per function on entry and exit
rather than 5, and a second problem the SP version does not have — the counter
lives in a REGISTER, so a dylib cannot initialise it, since a `dlopen`ed library
inherits whatever the loading thread left in x18 and has no way to tell "not
mine" from a real value. The SP version reads the floor from a word every image
already has (`stack_floor_offset`, landed in the same tree), which is the
argument for it beyond the model gap.

## The exact next step

1. Add the helper and use it in the ten existing spellings, so there is one:

   ```lean
   def arm64_reg_sp (i : Nat) (s : Arm64State) : UInt64 :=
     if i = 31 then s.sp else arm64_reg i s
   ```

   with the ten call sites rewritten to it. Provably behaviour-preserving for
   every instruction the tree emits today (`arm64_reg 31 = 0` was correct for
   those, and none of them can have `Rn = 31` in a shifted-register form or its
   proof would already be false) — which is the argument to make in the commit,
   and it is checkable: `formal/arm64_codegen.py` emits no
   `encode_cmp_xn_xm(31, …)`, no `encode_add_xd_xn_xm(_, 31, …)` and no
   `encode_sub_xd_xn_xm(_, 31, …)` today (`grep -n "encode_.*_xm(\(.\|0-9\)*, 31,"`
   finds only LDR/STR base uses).
2. Generalize the shifted-register cases — `ADD` `0x8b000000`, `SUB`
   `0xcb000000`, `CMP` `0xeb000000`, and the logical/MUL forms that share the
   shape — to read `Rn` through `arm64_reg_sp`, and update their `arm64_step_*`
   lemmas' statements to match.
3. `formal/arm64_proof_gen.py`'s step table: a generated proof instantiates a
   library lemma with the register numbers decoded from the emitted word, so
   the instantiation has to discharge `arm64_reg_sp 3 s = arm64_reg 3 s` for
   every concrete `Rn` it uses. `simp` with `decide` should do it; if the
   generator ever instantiates with a SYMBOLIC `Rn`, that is the case that will
   not close, and it is the one to find first.
4. Then, and only then, a guard that can SPELL `CMP SP, Xm` and be proved over
   it. The guard that landed does not spell it (see the Status), so this is now
   about making the model able to say what the machine does, not about
   unblocking anything.

**The dependency to be honest about before starting:** steps 1–3 are changes to
the proof side, and the suites that check the proof side
(`formal`, `formal-call-proofgen`, `formal-dylib`, `formal-imports`,
`formal-sweep`, `formal-x86`, `formal-x86-endtoend`, `formal-x86-model`) are all
`disabled=` behind the Lean-time-bound doc. Editing `lib/ProofLib.lean` also
invalidates the `.olean` stamps, so the first check is a 27 MB / ~80 s / 7.8 GB
`prooflib` rebuild, and after that every generated proof has to be re-checked —
`formal/examples/udivmod.mojo` alone is 298 s on this tree. **Whoever takes this
should decide the ordering with the Lean bound first**, because a model change
whose tests are switched off is precisely the change that cannot be landed
soundly, and this repository has already had one of those bite.

## What is NOT wrong here

`Arm64State.sp` exists and is threaded through every form that addresses
memory with it, so "the model cannot see the stack" is false and would be the
wrong conclusion to draw: it can, it just reads 31 as XZR when the instruction
is a *data-processing* one. The x86-64 model and the interpreter need nothing;
`formal/x86_64_decode.py` decodes `cmp rsp, rax` and `formal/model.py`'s
`pointer_value_model` already says what a word can and cannot denote. The bug is
one helper and the forms that should have been using it.
