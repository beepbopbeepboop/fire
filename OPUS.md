# OPUS.md — termination (`Total`) for dylib exports

Agent [2]. Write set: `lib/ProofLib.lean`, `formal/arm64_proof_gen.py`.
Shares with [3] (`lib/Refine.lean`, `lib/work.lean`, `lib/Contracts.lean`) — do
not edit those.

This is a hand-off document: what is proved, what is still open, and the
route for the open part.

---

## 1. Status

`{ident}_semantics_total` — `DylibExport.Total dylib_image {ident}`, i.e. "for
every argument `n`, `runExport` returns `some`" — is now **proved, with no
`sorry`**, for every export whose control flow is acyclic and has no calls.
That covers the plain arithmetic exports (`triple`, `negate`, …). An export
with a loop or a `bl` still gets one named `sorry` over `Total`. That
statement is true (or at least not known to be false), which is more than
could be said for what it replaced.

How: the generator's existing CFG walk (`_gen_universal_e2e_cfg`, halt-only
mode) now proves `{ident}_halts`:

```lean
theorem {ident}_halts (n : UInt64) :
    (match arm64_exec_go_exit { Arm64State.init n BASE with pc := ENTRY,
         x30 := UInt64.ofNat EXIT } dylib_code EXIT (100000) with
     | some s => True
     | none => False)
```

and `DylibExport.total_of_halts` (ProofLib) turns that into `Total`. The walk's
statement matches `runExport` up to unfolding, including the fuel.
`_EXPORT_FUEL` in the generator mirrors `exportFuel`, and if the two ever
differ the result is a type error, not a proof about some other run.

`#print axioms` on the generated `_semantics_total` shows only
`propext`/`Classical.choice`/`Quot.sound` plus the project's usual
`native_decide`/`bv_decide` step-lemma axioms. There is no `sorryAx`.

## 2. Why the plan in the previous version of this file could not work

The previous version proposed to finish with a "straight-line table":
`∀ st, st.pc < exit → st.pc % 4 = 0 → ∃ s', arm64_step st code = some s' ∧
s'.pc = st.pc`, which needed only one more hypothesis (`hbase`). Its
predecessor, the two emitted obligations `{ident}_halts` / `{ident}_nodrop`,
had the same shape. **Both are false for every dylib the backend emits.** I
measured this on a real two-export dylib (`triple`, `negate`):

```
0x1000001b0  a9bf7bfd  stp  x29, x30, [sp, #-16]!
...
0x1000001e4  a8c17bfd  ldp  x29, x30, [sp], #16
0x1000001e8  d65f03c0  ret
```

- **Every export ends in `ret`.** `ret` writes `pc := x30`, so "the step
  does not move the pc" fails at the last word of every export. Because the
  hypotheses quantify over *all* states, `x30` is arbitrary, and so the pc
  after `ret` can be anything, including an address back inside the image.
  So `hnodrop` fails too.
- **Pcs below `image.base`** are in range (`st.pc < exit`), `dylib_code`
  returns `0` there, `0` decodes to nothing, and `arm64_step` is `none`. So
  `hhalts` is false as well.

So the census had been counting two holes that no proof could ever fill. This
is the same problem as the old `∀ n s` form of `Total`, one level down. The
real run terminates because of a fact about the states it actually visits:
`stp x29, x30` saves the link register, `ldp x29, x30` restores it, and so the
`ret` goes to the exit. A claim about all states cannot express that. A walk
of the actual run can, and the CFG walk already follows `x30` through the
stack (`hx30_*`, discharged with `mem_read_after_write_u64` and friends).

Removed as a result, since nothing can use them: `effNext`,
`arm64_go_exit_terminates{,_aux,_aligned}`, `arm64_nodrop_of_straight`,
`dylibExport_total_of{,_straight}`, `arm64_branchy` (never checked against the
decoder), and `arm64_set_reg_pc` (only needed by that route). All of them are
in git history (`9c884c7`) if someone needs them back.

The `Total` shape fix from the previous round still stands: `∀ n s, … = some
s` was false and `∀ n, ∃ s, …` is correct. That history is kept in the
`DylibExport.Total` docstring.

## 3. What changed, concretely

- `formal/arm64_proof_gen.py`
  - `_gen_universal_e2e_cfg` takes a new `fuel=` argument. It states the
    theorem at a constant fuel and for every `n`, with no `hn`/`FrameBound`
    premise. It returns `None` unless the CFG is acyclic (every branch
    target is after the branch), has no `bl`, is not recursive, and `fuel` is
    at least the instruction count. Outside those conditions a constant budget
    would be false, so the emitter declines rather than emit a theorem that
    cannot check.
  - Halt-only mode was missing its closer (`trivial`) on a `ret`-terminated
    block. It only ever worked for a halt at a call boundary. This is fixed.
  - `_dylib_total_proof` emits the walk plus the `total_of_halts` application,
    or the named `sorry` fallback. It takes the export's extent from the next
    export's entry.
- `lib/ProofLib.lean`: `DylibExport.total_of_halts`, plus a section note
  explaining why the proof is per export and not a general theorem. The dead
  route listed in §2 is deleted.
- `test_formal_dylib.py`: now requires that `triple`'s `_semantics_total` is
  derived from `total_of_halts`, so falling back to the `sorry` counts as a
  failure.

## 4. Still open, in order of value

### 4.1 `Total` for exports with loops

A countdown or range loop needs fuel that grows with `n`, and `exportFuel` is
a constant. For large `n` the claim is therefore **false** at the current
definition: `runExport` runs out of fuel and returns `none`. So this is a
definitional question before it is a proof question. Options:

- make `runExport`'s fuel a function of `n` (as the executable path's
  `200000 + PATH * n` is). This changes `runExport`, and so [3]'s
  `export_result_spec`; coordinate first;
- or state `Total` as `∃ fuel, …` per `n`. This is a weaker claim, but it is
  honest about what a fixed budget cannot do.

Until one of those happens, the named `sorry` over `Total` for a looping export
sits on a statement that is false for large `n`. It is recorded here so it is
not mistaken for a hard-but-true obligation.

#### 4.1a RESOLVED as a diagnosis: the `sorry` is on a false statement, and that is now CHECKED

The paragraph above was an assertion, and it is worth checking rather than
believing, because if it were wrong then 4.1 would not be a definitional
question at all. It is right, and `lib/ProofLib.lean` now proves it:
`DylibExport.total_refuted_backward_branch : ¬ Total …` for a concrete,
**well-formed** image — `DylibExport.backward_branch_in_image` proves
`InImage` for the same export, by `native_decide`. So `InImage` and `Total`
are independent clauses, checkably (§4.4 below is thereby answered too).

The image is one instruction: `0x143fffff`, which is `B . -4` (the 26-bit
immediate `0x03ffffff` has its sign bit set, so the model sign-extends it to
`-1` and the target is `pc - 4`). That lands below `image.base`, where
`backward_branch_code` answers `0`, and `0` decodes to nothing.

Two things about this that are worth more than the refutation itself:

- **The failure is not fuel exhaustion.** The run leaves the image on the
  *first* step and returns `none` immediately. So the framing "a loop needs
  fuel proportional to `n`" is only half the story, and a fix that only made
  the fuel grow would leave this image still failing. Worth knowing before
  spending effort on option 1.
- **A named `sorry` over a false statement looks exactly like a named `sorry`
  over a true one.** The census counts holes; `vacuous_declarations` counts
  vacuous bodies; nothing in the tree asks whether a statement is inhabited.
  This is the second time in two rounds that a `sorry` has turned out to sit on
  an impossibility (`Total`'s `∀ n s` was the first). The cheapest instrument
  that catches the whole family is still the toy check: state the predicate at
  a concrete instance and see whether it survives. That is all this took.

Precisely what is proved, and no more: `runExport … 0 = none` and
`¬ Total …`, both by `native_decide`. A refutation needs one argument, and the
ground form is what lets `native_decide` work at all — it cannot decide with
`n` free, and `generalize`-ing the initial state only moves the free variable
rather than removing it. The claim "and likewise for every `n`" is *reasoning*
from the structural argument above, and is deliberately not stated as a
theorem.


### 4.2 `Total` for exports that call

A `bl` to a sibling export or helper *inside* the image can in principle be
walked (the executable path handles `bl` with `FrameBound`). That needs the
`hn` stack-bound premise, which `Total`'s `∀ n` does not have, so the same
definitional question as 4.1 comes first. A `bl` *out of* the image (libSystem)
is not executable in the model at all, so `Total` there has to be stated
relative to a callee contract.

### 4.3 x86

The same per-run walk argument applies. The all-states route should not be
revived there either: x86 `ret` pops the return address from memory, so the
same "arbitrary state" failure applies.

### 4.4 A sharper `Semantics_refutable` — DONE, as a by-product

It still refutes with a zero-length image. A code image whose entry lies
outside the code would show that `InImage` and `Total` are independent
clauses. It is small.

**Landed as a by-product of 4.1a.** `DylibExport.backward_branch_in_image`
proves `InImage` for the very image that `total_refuted_backward_branch`
refutes `Total` for, and both are `native_decide`. So the independence is now
a checked pair of theorems rather than a note about what would be nice to show,
and it is stronger than the version proposed here: the old suggestion used a
*malformed* image (entry outside the code), which would have shown the two
clauses can fail independently but only via the entry being nonsense. This one
has a perfectly good entry and fails on control flow.


## 5. Notes for [3]

- `{ident}_semantics_total` keeps its name and its type
  (`DylibExport.Total dylib_image {ident}`). Only its body changed. The names
  `{ident}_halts` (now a proved theorem with a different statement) and
  `{ident}_nodrop` (gone) were never consumed outside the generated file.
- Nothing in your write set was touched.
- If 4.1 is taken up by changing `runExport`'s fuel, that touches
  `export_result_spec`'s meaning, so I'd rather agree the shape with you first.
