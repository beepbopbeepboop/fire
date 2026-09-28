# [3] round 2: per-export contracts — Done-when CLOSED

**Status: done, sorry-free, with negative controls.** FORMAL.md §11.2 [3] asks
for one real export carrying a spec that is not the identity, and a caller
discharging its obligation against it. Both exist, proved, for a real generated
dylib. This doc is the record; the deliverable is `lib/Contracts.lean` plus
`IR-3-to-2-dylib-contract-emitter.md`.

Write set: `lib/Refine.lean`, `lib/work.lean`, new `lib/Contracts.lean`.
[2] has `lib/ProofLib.lean` and `formal/arm64_proof_gen.py`; nothing was written
outside my set. `lib/work.lean` was not needed and is unmodified.

## What is proved

Real dylib, real export `triple` (`def triple(n) { return n * 3 }`, arm64):

```lean
theorem triple_spec :
    Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n * 3)

theorem triple_caller : ∀ n : UInt64,
    Refine.DylibExportContract
      (Refine.dylibExportProg dylib_image dylib_export_0_triple) (fun n => n * 3) n
```

`fun n => n * 3` is not the identity, and the caller's conclusion is a real
equation (`s.x0 = n * 3`), not `True` — checked explicitly, because a contract
that concludes `True` would satisfy §11.2 on paper and mean nothing.

## The three results worth keeping

**1. `bv_decide` discharges the spec, memory round trip included.** I expected
the contract's value obligation to need hand-written address arithmetic: the
final `x0` is a `mem_read_u64` of a slot the function's own prologue wrote, so
the result passes through `sp` bookkeeping and the frame. It does not. Every
value is a `UInt64`, so the whole thing is bitvector computation and one
`bv_decide` closes it for **symbolic** `n`. Anyone budgeting for
per-export spec proofs should budget for the code emitter, not for the proof.
The two facts that fall out of the same tactic:

```lean
theorem hreg : ∀ n, arm64_reg 0 (S15 (triStart n)) = n * 3   := by intro n; bv_decide
theorem hx30 : ∀ n, arm64_reg 30 (S14 (triStart n)) = UInt64.ofNat triExit := by intro n; bv_decide
```

**2. The identity spec is now REFUTABLE, which is a change in kind.** [2]'s
current output is `export_result_spec … (fun n => n) := by sorry` — §11.2's
named trap, and it typechecks. `agrees_of_body` takes the spec's agreement with
the machine as a *hypothesis*, so identity now survives only if the export
really is the identity. Proved:

```lean
theorem ctl_identity_spec :
    ¬ Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n)
theorem ctl_wrong_spec :
    ¬ Refine.export_result_spec dylib_image dylib_export_0_triple (fun n => n + 1)
```

Before: a wrong spec compiles and is believed. Now: it fails `bv_decide`
against the machine's own expression. This is the difference the whole phase is
about, and it is structural rather than editorial.

**3. A contract does not need the step bound, and the reason generalises.** The
absence of a uniform `Total` was, I thought, the thing standing between me and
this Done-when. It is not. `Total` is hard because `arm64_go_exit` recurses on
*fuel*, so a symbolic argument means a symbolic number of steps. A contract is
a different problem: the step count is the body's own length, a **literal**, so
the budget side condition is `block.pcs.length + 1 ≤ exportFuel` — concrete
arithmetic `omega` closes — while the argument stays symbolic.

This was written while `Total` was still `sorry`. **[2] has since landed the
step bound and `total_of_halts`**, and this instance re-verifies against it (0
errors). So the sequencing turned out not to matter: the contract was provable
before the bound existed, and is still provable after. Worth keeping, because
the general shape is reusable — anything whose cost is the body's own length
rather than a fuel budget is a step count a generator can state as a literal.

## Two bugs the typechecker caught in my own work

**`atExit` was false as I first stated it.** I had it for every state at the
entry; a body ends by returning, and a return jumps to whatever `x30` holds, so
a state at the entry with `x30 := 0` returns to `0`. Restated for the start
state, which is exactly the state that sets `x30` to the exit. The general form
would have made the generator emit a false obligation, so this is recorded in
the IR rather than only here.

**`go_exit_within` is false without `hmid`.** `go_exit` stops the instant
`pc = ρ`; `arm64_runs` never stops. A run whose *start* is already at `ρ` with a
nonempty body therefore satisfies "some `m` reaches `ρ`" while `go_exit` returns
the start. The side condition is in the statement and the false version is in
the comment, because a reader who drops it gets a lemma that looks right and is
not.

Also: `go_exit_step` is unusable for this body. On a sequential instruction
`arm64_runs` recurses on the *bumped* state while the step produced the unbumped
one, so its hypothesis `arm64_step st code = some st'` cannot be supplied.
`go_exit_cons` mirrors the definition instead.

## A retraction

Last round I flagged, as an aside, that the `triple` run returns `x19 = 0`
"after a prologue that spilled `x19 = n` and an epilogue that reloads it", and
suggested a model-fidelity gap in `sp` arithmetic or a real codegen defect. **I
was wrong, and I withdraw it.** I walked the body one instruction at a time:

```
st0    x19=0                      x30=exit
step 2 STP x19,x20   x19=0        <- saved as 0, which is its ENTRY value
step 3 MOV x19, x0  x19=n         <- in-function use of a callee-saved reg
step 9 LDP          x0=n          <- the spill/reload round trip is exact
step 12 LDP         x19=0         <- correctly restored to its entry value
step 14 RET         pc=exit
```

`x19` was 0 on entry, the prologue saved 0, and the epilogue correctly returned
it to 0. The frame round trip is exact — `mem_read_u64` after `mem_write_u64`
at the same address — and the `x30` round trip is what makes the return land on
the exit. The `x30` round trip being exact is load-bearing: `atExit` *is* that
fact. My aside was a misreading of a single end-state, and had I left it in a doc
it would have sent someone hunting a defect that does not exist. The general
lesson I would keep: one sample of a multi-instruction trace is not evidence
about any of its steps.

## The two findings that are NOT about contracts

**Compose by naming, never by textual nesting.** Building the composed effect by
substituting the accumulated expression into the next `dylib_sr` conclusion
grows **exponentially** — mine reached 981 MB of Lean source at 15 steps and the
compiler never terminated. One `def` per step makes it linear at ~2.3 KB. This
is a trap for whoever implements the emitter, and it is in the IR.

**The `interval_cases` no-early-exit proof is per-export and does not scale.** For
a body of `m` instructions it is `m` cases. `m = 15` is fine; a 60-instruction
export is not. A `Fin`-indexed induction over the pc discipline is the right
shape and I did not build it, because I did not need it and an untested
generalisation is worse than the case split.

## Verification

* The closing instance compiles with **0 errors and 0 `sorry`/`admit`**
  (checked textually, not inferred from a clean exit).
* Both negative controls compile, i.e. the identity spec and a wrong spec are
  each *refuted*.
* Non-vacuity checked: the caller's conclusion is `s.x0 = n * 3`, a real
  equation.
* `lib/Contracts.lean` compiles clean with **0 admitted holes** against the
  repo's own `lib/*.olean`.
* The four registered modules still report **0 admitted sorries** between them.
  Round 1's zero is not regressed. (The library was rebuilt into a private
  directory for iteration, because [2] was concurrently rebuilding
  `lib/ProofLib.lean` and holding the `ProofLib.olean` build lock; the repo's
  `lib/` was not written to.)
* No file outside the write set was modified. `git status` shows one new file
  under `lib/`, one edit to it, and the two IR docs.

The verified instance is landed at
`formal/golden/arm64_dylib_contract_triple.lean`, header-marked as generated
output to be deleted once the generator emits the contract. It compiles clean
from that path (0 errors). It is deliberately a *golden* artifact rather than a
second implementation: it is self-contained, and the emitter in the IR is what
is meant to supersede it.

## Not done, honestly

* **The spec is still typed by a human.** `fun n => n * 3` is written into the
  generator, not derived from the export's source AST. `bv_decide` rejects a
  wrong one, so it is checked rather than believed — but it is a second thing to
  keep in sync with the source, and that is the rot this programme already
  removed once. Deriving it from the AST via `Refine.evalExpr` is my next
  argument, and it is the only remaining piece of §11.2 [3] I would call
  unfinished.
* **`Total` is [2]'s, and it is now landed** — `total_of_halts` plus the export
  step bound, which this instance was re-verified against. Nothing here depends
  on it, which is the result above.
* **One export, one architecture.** Nothing here is x86-64;
  `formal/x86_proof_gen.py` is untouched.
* **The generator still emits the identity spec.** This Done-when is closed in
  `lib/` and in the verified generated artifact; making the *shipped* generator
  emit it is `IR-3-to-2-dylib-contract-emitter.md`, and until that lands the
  dylib proof still says `(fun n => n) := by sorry`.
