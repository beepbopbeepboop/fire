# PROOF: `lib/ProofLib.lean`'s `SMULH` arm is reverted — its `work_step_smulh`
# neither closes the goal nor finishes inside the heartbeat budget

**Area:** PROOF — `lib/ProofLib.lean`'s `arm64_step` chain and the
`formal/arm64_proof_gen.py` tables that must agree with it. **Status: OPEN,
measured 2026-10-05 while merging `work/formal33-int-semantics`, and the SMULH
half of that merge is NOT landed.** Everything else of that branch — the
integer-overflow refusals on both backends, `formal/model.py::int_overflow_traps`,
`printf %d`, the saturating `>>` fix — is landed and green.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/suite.py formal-sweep-truth --no-cache
```

which runs `test_formal_sweep_truth.py`, and through it
`formal/lean.py::run_lean`. Two separate failures, both from
`lib/ProofLib.lean`, both about the one `work_step_smulh` lemma:

**1. As `work/formal33-int-semantics` landed it, the lemma does not CLOSE.**
It carried 54 `hne_*` word-test exclusions, because that branch's
`_STEP_CONDS` had only 55 entries; this tree's chain has 68, so fourteen
`if` arms of `arm64_step` were never discharged:

```
lib/ProofLib.lean:7069:169: error: unsolved goals
s : Arm64State
...
hne_54 : ¬w &&& 4292870144 = 2868903936
⊢ (if w &&& 4291821568 = 960495616 then … else if w &&& 4292934656 = 4167067648
    then … else if w &&& 4292870144 = 3925868544 then … ) =
    some (arm64_set_reg (w &&& 31).toNat s (smulhi64 …))
```

**2. With the exclusion list rebuilt against this tree's 68-arm chain (which is
what `formal/arm64_proof_gen.py::check_step_conds` and the family's own
"append, never insert" rule both require), it no longer FINISHES:**

```
lib/ProofLib.lean:7128:67: error: Tactic `bv_decide` failed. Error: failed to
  compile definition, consider marking it as 'noncomputable' because it depends
  on 'work_step_smulh._expr_def_1_271', which is 'noncomputable'
lib/ProofLib.lean:7129:67: error: Tactic `simp` failed with a nested error:
  (deterministic) timeout at `isDefEq`, maximum number of heartbeats (200000)
  has been reached
lib/ProofLib.lean:7062:0:  error: (deterministic) timeout at `whnf`, maximum
  number of heartbeats (200000) has been reached
lib/ProofLib.lean:7128:67: error: (deterministic) timeout at `«LCNF compiler»`,
  maximum number of heartbeats (200000) has been reached
```

So the arm is not merely unproved, it is not provable by the same script its
siblings use. `work_step_tst`, 66 arms deep, proves; `work_step_smulh` is two
arms deeper and does not, and the difference between them is the RIGHT-HAND
SIDE: every other lemma's result is `arm64_set_reg`/`{s with mem := …}`, and
this one's is `smulhi64`, whose body is `Int.fdiv ((u64_toS64 a) * (u64_toS64 b))
(2^64 : Int)`. An `Int` division inside the statement is what the `bv_decide`
"noncomputable" complaint and the three heartbeat timeouts both point at.

## What I did instead

Reverted the SMULH arm and its lemma: `lib/ProofLib.lean` loses `smulhi64`, the
`0xffe07c00/0x9b407c00` arm of `arm64_step`, and `work_step_smulh`; and
`formal/arm64_proof_gen.py` loses `(0xffe07c00, 0x9b407c00)` from `_STEP_CONDS`
and `(68, "work_step_smulh", …)` from `_WORK_STEP`. The chain is back to 68
arms ending at `0xffe00c00/0xf8000000` (STUR) and
`check_step_conds()` agrees with it.

The cost of that is exactly the one the table above the removed arm already
names and accepts: `formal/arm64.py` can encode `SMULH` and `arm64_step` cannot
step it, so `tools/formal_model_fuzz.py` reports it as a `NOSTEP` — a hole in
the MODEL, not a wrong answer, which is the distinguishing test that table
exists for. `formal-sweep-truth` is green with it, which is the evidence that
it is a hole and not a defect.

The axiom ledger is therefore also back where it was: `ProofLib` 1518, `lib/`
1540, total 1607, arrivals 856. Nothing was recorded and nothing was hidden —
the +54 arrival was never a fact about this tree.

## The exact next step

One file, one lemma, and a decision about the tactic:

1. Put `smulhi64` and the arm back at the END of `arm64_step` (appended, never
   inserted — `_STEP_CONDS` and `check_step_conds` both assume it), and
   `_STEP_CONDS`'s / `_WORK_STEP`'s entries at index 68.
2. Write `work_step_smulh` by hand, as this family is maintained: one
   `have hne_N : ¬ ((w &&& mask) = base) := by intro t; bv_decide` for each of
   the 67 arms BEFORE it in the CHAIN (not in `_STEP_CONDS` — the chain order
   and the table order differ, and `check_step_conds` compares sets), then
   `rw [if_neg hne_ret, …, if_neg hne_67]; try dsimp; try rfl; try simp`.
3. If that still times out, the `Int` division is the cost and the fix is one of
   two things, and which one is a decision rather than a lookup:
   * give the theorem `set_option maxHeartbeats <n> in` with an `n` MEASURED
     (the heartbeat ceiling is this project's own recurring subject —
     `FORMAL.md` §"…maxHeartbeats does not meter the thing that spins", and
     `bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md` is the
     precedent for a per-declaration ceiling), or
   * express the high half WITHOUT `Int`: `(a * b) >>> 64` on the unsigned
     product is the same 64 bits, and it is the shape every other arm in this
     file already has. That removes the `Int` from the statement and with it the
     reason `bv_decide` calls the definition noncomputable — which is the more
     likely of the two to work and the one whose result is the same theorem.
4. Re-land the +54 in `bugs/FORMAL_native_decide_axiom.md` and `FORMAL.md` §7
   row 10 when the lemma elaborates, and NOT before: the ledger's own rule is
   that an arrival is recorded as debt when it exists, and a `bv_decide` site in
   a file that does not compile is not a site.

Whoever takes it needs `formal/lean.py::run_lean` (or the `formal-sweep-truth`
job), which the merging worker is not permitted to launch — that restriction is
why this is filed rather than fixed.