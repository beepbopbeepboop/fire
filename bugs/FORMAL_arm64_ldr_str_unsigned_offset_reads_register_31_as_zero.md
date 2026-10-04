# `LDR`/`STR` (unsigned offset) read register 31 as ZERO, so every SP-relative access is modelled from address `imm`

## Status

OPEN, and NEW — found 2026-10-04 by `tools/formal_model_fuzz.py` and **not
fixed**, deliberately, with the reason in §4. It is the one surviving `WRONG` in
a 296-case sweep, and it is reachable: `formal/arm64_codegen.py` emits
`encode_ldr_xt_xn_imm(_, 31, off)` at ten sites.

There are TWO defects in the two arms and they are independent:

1. **the base register** — `arm64_step` reads it with `arm64_reg`, so `Rn = 31`
   is the ZERO register instead of the stack pointer (0xf9400000 and 0xf9000000);
2. **the store width** — the `STR Wt` arm (0xb9000000) writes EIGHT bytes
   through `mem_write_u64`, so the four bytes above the one it should write are
   clobbered in the model and left alone on the hardware.

## 1. What was run, and what it printed

```
$ python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
      --cases 300 --seed sweepB
arm64 model vs hardware: AGREE 196  WRONG 1  NOSTEP 99  (of 296)
  case 74 [flags]: ...
```

Per mix, 60 cases each (seed `ledgerA`), the four `WRONG` cases are all in `mem`
and all three are memory effects:

| case | instructions | difference |
|---|---|---|
| 8 | `cmp x23, x20; orr x30, x23, x12; str x10, [sp, #16]` | `mem[+272] model=f7 hardware=fe` and two more bytes |
| 24 | `cmp x3, #1; str w30, [sp, #12]; ldr x29, [x17, #0]; and x25, x10, x13` | `mem[+268] model=95 hardware=f9` and two more bytes |
| 25 | `cmp x18, #2047; sub x10, x7, x20; ldr x0, [sp, #32]` | `x0 model=0000000000000000 hardware=53eed1de90a7dc2e` |
| 55 | `cmp x20, #16; ldr x19, [sp, #0]; and x15, x3, x10; and x1, x30, #4294967295; sub x0, x2, #811` | `x19 model=0000000000000000 hardware=888c70d2718e7769` |

Case 25 is the base defect on its own, and it is the clearest statement of it:
`ldr x0, [sp, #32]` with those bytes non-zero reads **0** in the model. The
model computed the address `0 + 32`, which is outside every window, and
`mem_read_u64` answers 0 for anything outside it. Case 24 is the width defect:
`str w30, [sp, #12]` writes 8 bytes at offset 268 in the model and 4 on the
hardware.

## 2. Why it is reachable, in the model's own words

```python
$ grep -nE "encode_(ldr|str)_xt_xn_imm\([^)]*,\s*31\s*," formal/arm64_codegen.py
3100:        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0))   # X6 = n_fixed
3101:        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 8))   # X5 = src base
4589:        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, base_off))  # X9 = base
4603:            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 0))   # X7 = lookup key
4628:            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, base_off + 16))
4651:            self.asm.emit(encode_ldr_xt_xn_imm(1, 31, base_off))
4660:            self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0))    # X6 = key
4662:            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, base_off + 16))  # value
4931:            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))  # base from [SP]
4956:            self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))   # X9 = base
```

Ten sites, and `# base from [SP]` is the codegen's own comment on the eleventh.
`encode_ldr_xt_xn_imm`'s own bound is `assert 0 <= xn <= 31`, so 31 is a
supported argument and not an accident of a caller.

The comment above the model's LDR arm says the opposite of what it does:

```
-- STR Xt, [Xn, #imm]: 0xF9000000 ...
-- The base register was `s.sp` here, hardwired, whatever the instruction
-- encoded in `Rn`. ...
```

so this arm was ONCE right for the wrong reason — it read SP for every `Rn` — and
the fix for that bug over-corrected to `arm64_reg`, which is right for every
register except the one that means SP. `arm64_reg_or_sp` is the helper that
exists for exactly this and this arm does not use it.

## 3. The three places that have to change together

The generator mirrors the model, and its comment is why the defect was cheap to
miss:

```python
# formal/arm64_proof_gen.py, the `idx == 18` row
# `arm64_reg 31 s`, not `s.sp`: the RHS has to be the SYNTACTIC mirror
# of `work_step_ldr_uoff`'s statement, because that is what `exact`
# unifies against, and a hand-simplified base is a different term even
# where it is equal.
```

1. `lib/ProofLib.lean`: `arm64_reg rn s` → `arm64_reg_or_sp rn s` in the
   0xf9400000 and 0xf9000000 arms.
2. `lib/ProofLib.lean`: `work_step_ldr_uoff` and `work_step_str_uoff`'s
   statements, same substitution.
3. `formal/arm64_proof_gen.py`: the `idx == 18` and `idx == 31` rows of
   `_step_rhs`.

## 4. Why it is written down instead of landed

The change itself is one identifier in three places. What it costs is the two
`work_step_*` PROOFS, and the reason is in `arm64_reg_or_sp`:

```lean
def arm64_reg_or_sp (i : Nat) (s : Arm64State) : UInt64 :=
  if i = 31 then s.sp else arm64_reg i s
```

`work_step_ldr_uoff`'s hypothesis is `(w &&& 0xffe00000) = 0xf9400000`, which
says nothing about `(w >>> 5) &&& 0x1f`, so the `if` cannot be discharged by
`simp` from what the lemma is given. Measured, with the change applied:

```
lib/ProofLib.lean:4723:72: error: unsolved goals      -- work_step_ldr_uoff
lib/ProofLib.lean:5253:48: error: unsolved goals      -- work_step_str_uoff
```

and with the statements changed but not the proofs, `Type mismatch` instead.
Both lemmas are ~40 lines of `bv_decide` over the 20 earlier branch conditions
each, so the repair is to add the missing split to their proofs:

```lean
  by_cases h31 : ((w >>> 5) &&& 0x1f) = 31
  · simp [h31, arm64_reg_or_sp] -- and the existing rw chain
  · have hlt : ((w >>> 5) &&& 0x1f).toNat < 31 := by omega
    simp [arm64_reg_or_sp_of_lt hlt]
```

That is a two-case proof edit to two long lemmas, and it is the kind of edit that
needs the generated-proof suite to confirm — which a light worker may not run
(`make gate` and the proofs bucket are the integrator's). Landing the model
change with the generator's mirrors but WITHOUT the proof repair would turn one
wrong model into two wrong models plus two broken lemmas, which is a worse tree
than the one measured here. So the model arms, the lemma statements and the
generator rows all carry a comment pointing here instead, and the fuzzer's
`WRONG` count keeps saying so out loud on every run.

## 5. The exact next step

1. The two `work_step_*` proof repairs above, on their own, with the statements
   UNCHANGED — a no-op change that proves the split is expressible. Build
   `lib/ProofLib.olean` (7.7 GB, ~100 s) and run
   `formal-arm64-proofs` + `formal-call-proof-gen`.
2. Then §3's three substitutions in one commit, and the same two jobs.
3. The width defect (0xb9000000 writing eight bytes) needs `mem_write_u32` first,
   which `bugs/FORMAL_arm64_step_cannot_step_nine_wired_encodings.md` §4 step 1
   is already adding for nine encodings that have no arm at all. Do them
   together: the helper is the same work either way.
4. Re-run `python3 tools/formal_model_fuzz.py --cases 300 --seed sweepB`. The
   `WRONG 1` must become `WRONG 0`, and the four `mem`-mix cases in §1's table
   are the ones to watch.

## 6. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 300 --seed sweepB
python3 tools/memslot.py --gb 4 --label fm -- python3 tools/formal_model_fuzz.py \
    --cases 60 --seed ledgerA --mix mem
python3 tools/memslot.py --gb 24 --label prooflib -- python3 -c \
    "import formal.lean as L, os; L.ensure_library(L.find_lean(), \
     os.path.join(L._default_root(),'lib'))"     # with the change applied: the two errors in §4
grep -nE "encode_(ldr|str)_xt_xn_imm\([^)]*,\s*31\s*," formal/arm64_codegen.py
```