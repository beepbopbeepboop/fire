# [3] The Lean model — what landed, and what did not

**Status: landed in `lib/`, verified, with one named gap and one blocking
hand-off.** This is the [3] scope from FORMAL.md §11.2: `lib/ProofLib.lean`,
`lib/Refine.lean`, `lib/X86.lean`, and nothing else.

## The measured before

Established on `21a82d6` + the sqlite work, not inferred:

| | count | where |
|---|---|---|
| admitted `sorry` in `lib/` | **3** | `ProofLib.in_image_stub`, `ProofLib.semantics_stub`, `Refine.dylib_export_contract_stub` |
| vacuous declaration | **1** | `ProofLib.lean:4617` `Semantics` — `∀ …, … → True` |
| `DylibExport.Semantics` says | `∀ observable, observable ∈ [] → True` | twice vacuous: the list is hardcoded `[]` *and* the body is `True` |

## The measured after

| | count |
|---|---|
| admitted `sorry` in `lib/` | **0** (all four modules, `library_census`) |
| vacuous declarations in `lib/` | **0** |

## What each hole was, and what replaced it

### 1. `in_image_stub` — was `sorry`, now a check

`InImage` is two `Nat` inequalities over literals the generator already emits,
so it was decidable the whole time. The `sorry` was standing in for a
computation that was available.

    theorem {ident}_in_image : DylibExport.InImage dylib_image {ident} :=
      (DylibExport.in_image_decide dylib_image {ident}).2 (by native_decide)

Strictly better: a `sorry` accepts anything, so a linker that put an export
outside its own image produced a green proof. This fails. (2 of 2 exports of a
real generated dylib pass.)

### 2. `semantics_stub` — was `sorry` over `True`, now a real claim

`Semantics` is now `Total ∧ Functional`:

* `Functional` — the observable behaviour is a **function of the input**. This
  is the clause a caller consumes, it is `rfl`-provable (the run is a function,
  so the two states are equal), and it is what the old definition had nothing
  to say about.
* `Total` — the run terminates for every argument. **Not discharged.** See
  "What did not land".

`Semantics_refutable` exhibits a counterexample, so the new definition is
demonstrably not another `True`: a dylib with no code at all falsifies it.

### 3. `dylib_export_contract_stub` — was `sorry` over a FALSE claim, now deleted

It was `by sorry` over *any* `p` and *any* `obs`, and
`formal/arm64_proof_gen.py` invoked it with `obs := fun n => n`. So the claim
every generated dylib proof made was:

> **Every dylib export computes the identity function.**

That is false, and measured on the first real dylib in the tree:

    Refine.export_result dylib_image triple 7 = 21    (by native_decide)
    Refine.export_result dylib_image negate 5 = -5    (by native_decide)

`identity_claim_is_false` is a `native_decide` theorem saying so. FORMAL.md
§11.2 [3] names the two options — prove it or delete it — and there was
nothing to prove, so it is **deleted**, per the instruction.

What replaces it is a real obligation plus a **proved** consumer:

* `export_result_spec image export spec` — the obligation ("this export agrees
  with this spec"). A bare `Prop` with no theorem discharging it, so it cannot
  be mistaken for a proof.
* `dylib_export_contract_of_spec` — the caller's theorem, **proved, sorry-free**.
  Given the spec, the caller's contract follows.
* `caller_may_use_export` — the same, stated over the machine's own run.

So the caller's side is no longer an admitted claim, which is the point.

## Also landed

**arm64 call/return semantics** (FORMAL.md phase 3, the gate). The root cause
was measured, not assumed: an in-image `BL`+`RET` already round-trips today
(`arm64_go_exit` from a call to a return returns the right value), and the halt
is exactly a call target *outside* the image — `arm64_read_insn` reads 0
there, `arm64_step` decodes nothing, returns `none`, and the whole run is
`none`. More fuel does not help.

* `CallFrame`, `CalleeOk` — what a call frame is on AArch64 (the link register
  and `sp`; AArch64 pushes nothing, so a memory frame would model a convention
  the architecture does not have).
* `Callee` with `returns_to` as a **field**, so a callee that forgot to return
  cannot be constructed. The alternative — an unconstrained `run` plus a
  separate claim that it returns — is the vacuous shape this exists to remove.
* `arm64_step_call` / `arm64_go_exit_call` — a call to a bound address applies
  the callee.
* `arm64_step_bl` — the `BL` decode, as a lemma over the assembled word, in the
  same `bv_decide`-per-arm shape as every `work_step_*` in the file. This is
  the piece an extern call site could not previously state, because its word is
  a linker-patched placeholder.
* `arm64_call_returns_to_next` — the round trip: the post-call state is
  **computed** (`c.run` applied to it) and its `pc` is **derived** (the return
  address), rather than the previous `{pre with pc := bl+4}` with the callee's
  effect discarded.
* **Conservation**, as theorems: `arm64_step_call_none` is `rfl` and
  `arm64_go_exit_call_none` holds at every fuel. This is what makes the change
  safe under four other agents — the 40 existing proofs are consuming a special
  case of the new function, and that is a theorem rather than a claim.
* `calleeTable_bound` — discharging "is this address bound" without a
  `DecidableEq Callee`, which a generated proof needs because `Callee` carries
  a `∀ s, …` field and `native_decide` cannot evaluate an equality about one.
  The obligation reduces to the address test, which is decidable.

**x86-64** `x86_call_post` / `x86_at_target` / `x86_ret_post`, and
`x86_call_ret_balances_stack` + `x86_call_return_slot_separated` (both proved).
The separation lemma is the fact A1 names.

## What did NOT land

### `Total` (uniform termination) — the honest gap

`Total` is stated and **not** proved, and the reason is measured rather than
guessed. `arm64_go_exit` is structural recursion on fuel, so a symbolic `n`
means a symbolic number of steps and `native_decide` refuses outright:

    Expected type must not contain free variables

Both directions were checked: for a **concrete** `n` the run evaluates and is
correct (`triple(7) = 21`); for a **symbolic** `n` it does not evaluate at all.

So `Total` cannot be discharged by evaluation, and this change does not
pretend otherwise. Discharging it means proving a step bound — a run confined
to the image needs at most one step per instruction, and `4 * codeSize + 8` is
below the fuel. **That is real work, it is not in this change, and it is not a
design question.** It is the next piece of phase 4.

The per-argument half *is* checkable, which is why `Total` is a stated
obligation and not a hole in `lib/`.

### The x86-64 `rip` half of the call/return round trip

`x86_call_ret_balances_stack` proves the stack-pointer half. The `rip` half —
that the `ret` lands on `m + 5` — additionally needs a read-of-write lemma for
`mem_read_bytes`/`mem_write_bytes`, which this file does not have:

    mem_read_bytes (mem_write_bytes m a v 8) a 8 = v

That statement is **false as a general-width claim** (at width 0 the read is 0
whatever `v` is), so it needs a mask to induct on, and the induction needs the
pointwise byte lemma because the tail of the step compares a `k`-write at
`a+1` against a `k+1`-write at `a`, which agree everywhere except at `a`:

    ∀ n m a v, mem_read_bytes (mem_write_bytes m a v n) a n = v &&& lowMask n

That is **one medium induction in `mem`**, and it is the whole of what stands
between this and a complete x86-64 round trip. Recorded in the docstring of
`x86_call_ret_balances_stack` rather than asserted, because a theorem that
quietly stops at the register file is how the old `Semantics` came to state
`True`.

### The x86-64 generator wiring (A1)

`bugs/OPEN_WORK.md` A1 is **stale about its mechanism**: `_FORMS`/`_SUCCS`/
`_resolve` are in `formal/x86_64_endtoend_test.py`, not the proof generator,
and the proof generator was rewritten to a per-instruction certificate loop
that covers `call_rel32` already. What A1's *substance* is still true of is
measured: `call_rel32` is the reason 7 of the x86-64 examples have "no tree" —
the largest single uncovered form. Wiring it needs two successors and a
separation fact, both of which now exist in `lib/X86.lean`; the tree-building
is in a file in nobody's write set, so it is a second interface request.

## Hand-offs

**Both resolved. Kept, with what happened, because a hand-off that reads
"URGENT, not yet done" once the work has landed is the same class of error as
a commit message that claims a deletion it performed.**

* `IR-3-to-2-dylib-stubs.md` — **DONE**, in 19d5211. All four generator call
  sites replaced with [3]'s verified patch; `test_formal_dylib.py` is 11 PASS /
  0 FAIL, not 10/1. The request file is deleted, per FORMAL.md 11.5.
  Two calls [3] left to [2] were decided: `dylib_observables := [id]`, because
  `Functional` quantifies over that list and an empty one makes the clause
  vacuous again without `vacuous_declarations` flagging it; and the `sorry`
  form of the two named obligations rather than `def ... : Prop`, for [3]'s
  stated reason that a named hole the census reports beats one nothing reports.
* `formal/x86_64_endtoend_test.py` (A1 wiring) — requested as
  `bugs/INTERFACE_REQUEST_3_to_x86_endtoend.md`. That file is in nobody's
  write set, which is why it is a request and not an edit.

## Verified independently, after the merge

[3]'s Done-when per FORMAL.md 11.2, re-measured on the merged tree rather than
taken from the commit message:

  * a dylib export has a NON-VACUOUS semantics — `Total`/`Functional` are
    separate, and `Functional` reads a non-empty `dylib_observables`;
  * a caller can discharge an obligation against it — `{ident}_contract` is
    PROVED, via `dylib_export_contract_of_spec`, with 0 sorries of its own;
  * `lib/ProofLib.lean:4617` no longer states `forall ..., ... -> True` — that
    line is now `work_step_svc`; the vacuous `Semantics` is gone.

  library_census:  ProofLib 0,  Refine 0,  X86 0,  work 0   admitted sorries
  vacuous_declarations: 0 in all four modules

The line number moved because this change added 445 lines to ProofLib.lean, so
"4617" no longer names the declaration it used to; that is a fact about line
numbers, not a change in the census.

## What was verified, and how

* All four library modules build with the **pinned** toolchain
  (`leanprover/lean4:v4.32.2`; an earlier "breakage" I reported was my own
  using the wrong one) — 0 errors, 0 sorries.
* `library_census` reports **0** for `ProofLib`, `X86`, `work`, `Refine`.
* The IR patch was applied to a real generated dylib proof and typechecks:
  `ok: True`, `lib_sorries: 0`.
* The call/return layer was exercised on a concrete extern call: the `BL`
  decode fires, the callee's effect is visible in `x0` (42, not the caller's 0),
  control returns to the link register, and the unbound case is still `none`.
* `fire.py build --backend x86_64 formal/examples/fact.mojo` is unaffected: the
  same 2 pre-existing sorries, no new ones.

A note on the temporary edit: verifying the IR required patching
`formal/arm64_proof_gen.py`, which is [2]'s file. It was reverted immediately
and `git status` confirms only the three `lib/` files are modified.
