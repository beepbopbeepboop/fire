# OPUS.md — the step bound for dylib exports

Agent [2]. Write set: `lib/ProofLib.lean`, `formal/arm64_proof_gen.py`.
Shares with [3] (`lib/Refine.lean`, `lib/work.lean`, `lib/Contracts.lean`) — do
not edit those.

This is a hand-off document. It states what is *proved*, what is *reduced to
named obligations*, what is *still open*, and — the part that matters most for
the final solution — **what I believe can be proved next and by what route**,
so the next session does not re-derive the shape from scratch.

---

## 1. Status in one paragraph

`DylibExport.Total` was a **false statement**, not a hard theorem. It is now
correct, and the reason an export's run terminates has been **proved** rather
than admitted. What remains is exactly two named obligations about a given
export's own code (`hhalts`, `hnodrop`), in place of one opaque `sorry` over
`Total`. The fuel bound itself — the part that was previously just "100000
seems like a lot" — is now a theorem, and the *only* fuel hypothesis left at
the generated call site is the literal inequality `codeSize < exportFuel`,
closed by `native_decide`.

---

## 2. The bug that was hiding behind the `sorry`

`Total` used to be:

```lean
def Total (image : DylibImage) (export_ : DylibExport) : Prop :=
  ∀ (n : UInt64) (s : Arm64State), runExport image export_ n = some s
```

Read the `s` as arbitrary and this says the run returns *every* possible
state. It is refuted by taking `s` to be a state that is not the result. A toy
check, on a function that is total in the plainest possible sense, is
unprovable — verified:

```lean
def f : Nat → Option Nat := fun _ => some 0
example : (∀ n s, f n = some s) := by intro n s; simp [f]
-- ⊢ 0 = s
```

So `{ident}_semantics_total := by sorry` was not sitting on a hard theorem. It
was sitting on an **impossibility**, and nobody noticed, because a `sorry`
compiles and a named `sorry` is exactly what the census is designed to be
trusted about.

Now:

```lean
def Total (image : DylibImage) (export_ : DylibExport) : Prop :=
  ∀ (n : UInt64), ∃ s, runExport image export_ n = some s
```

Termination is `∀ n, ∃ s, …`. Uniqueness of the result is *not* part of
`Total` and is not wanted — it is `Functional`, which states agreement of
*observables* rather than of whole states, and is the right home for
"same input, same answer".

**Consequence for the shape of the work, and this is the part worth reading
twice:** the correction is not cosmetic. Under `∀ s, …` there is no witness to
produce and the statement is vacuous in a way that *looks* like content. Under
`∀ n, ∃ s, …` there is a witness, and the witness is the entire content of the
step bound. Every proof step below exists to produce it.

### Collateral fixed

`DylibExport.Semantics_refutable` was stated against the old two-argument
`Total` (`htotal 0 (Arm64State.init 0 0)`). It had to be restated as
`obtain ⟨s, h⟩ := htotal 0`. This is the tell that the old shape was wrong: a
*refutability* check for a predicate that cannot be inhabited is not a
meaningful thing to have written.

---

## 3. The step bound, proved

### 3.1 `effNext` — the pc the loop is *actually* at next

`arm64_go_exit` has a wrinkle that has to be mirrored exactly:

```lean
let st'' := if st'.pc = st.pc then { st' with pc := st.pc + 4 } else st'
```

When a step leaves `pc` alone the loop does not stay put — it substitutes
`st.pc + 4`. So the pc the next iteration sees is `effNext st st'`, **not**
`st'.pc`.

This matters and it is the single easiest thing to get wrong.
`st.pc + 4` can **overshoot the exit**: an `nop` at the last word of the code
advances *past* `exit`. A progress hypothesis phrased about `st'.pc` would
therefore be satisfiable while the run walks off the end. `effNext` is the one
function that is right in both branches, and stating `hnodrop` about it yields
progress *and* containment from a single hypothesis.

```lean
def effNext (st st' : Arm64State) : Nat :=
  if st'.pc = st.pc then st.pc + 4 else st'.pc
```

### 3.2 The two hypotheses, and why they are the right two

```lean
theorem arm64_go_exit_terminates_aux (code : Nat → UInt8) (exit : Nat)
    (hhalts  : ∀ st : Arm64State, st.pc < exit → ∃ st', arm64_step st code = some st')
    (hnodrop : ∀ st st' : Arm64State, st.pc < exit →
              arm64_step st code = some st' →
              st.pc < effNext st st' ∧ effNext st st' ≤ exit) :
    ∀ (f : Nat) (st : Arm64State), st.pc ≤ exit → exit - st.pc < f →
      ∃ s, arm64_go_exit st code exit f = some s
```

- `hhalts` — every in-range state has a successor. Without it `arm64_step`
  returns `none` and so does the run, with fuel to spare.
- `hnodrop` — the effective next pc strictly advances and stays `≤ exit`.

Neither is derivable in general, and that is the point. An export containing a
backward branch has no `hnodrop`, so this proves `Total` for **straight-line**
exports and says so, rather than asserting it for all of them.

**Why the bound is strict.** `arm64_go_exit _ _ _ 0 = none` unconditionally, so
the run needs `exit - st.pc < f`, not `≤`. At `f = exit - st.pc` the induction
lands on `succ 0` and has nothing to recurse on. This is why `Total`'s shape
change above matters concretely: a `≤` bound would have been silently wrong.

**Why induction on fuel, not on distance.** `Nat.strong_induction_on` is not
available in this environment (checked, not assumed). It is also not needed:
`arm64_go_exit` recurses on `fuel - 1`, so plain induction on `f` is
*structural* and matches the definition exactly. The three cases are the three
branches of the loop: fuel exhausted, already at the exit, or one step.

### 3.3 `dylibExport_total_of` — the fuel is *proved* sufficient

```lean
theorem dylibExport_total_of (image : DylibImage) (export_ : DylibExport)
    (hhalts  : …) (hnodrop : …)
    (hin     : InImage image export_)
    (hfuel   : image.codeSize < exportFuel) :
    Total image export_
```

`InImage` is already a *check* — two `Nat` inequalities on literals the
generator emits, closed by `native_decide` (`in_image_decide`). It supplies
`entry ≤ base + codeSize`, and with it:

```
exit - entry  ≤  exit - base  =  codeSize  <  exportFuel
```

so `hfuel` is the *entire* remaining fuel obligation and it is a literal
inequality. This is the "the fuel is proved sufficient" half of the round's
done-when, and it is now real rather than rhetorical.

Note what is **not** needed: `arm64_go_exit_mono` is not used on this path.
The auxiliary is handed a budget of `exportFuel` directly, so its conclusion is
already at `exportFuel`. `mono` remains useful for the *other* consumer (a
caller with a smaller budget) but is not load-bearing here.

---

## 4. What the generator now emits

`formal/arm64_proof_gen.py` no longer emits a bare `sorry` over `Total`:

```lean
theorem {ident}_halts : …            -- OBLIGATION, stated in full
theorem {ident}_nodrop : …           -- OBLIGATION, stated in full
theorem {ident}_semantics_total :
    DylibExport.Total dylib_image {ident} :=
  DylibExport.dylibExport_total_of dylib_image {ident}
    {ident}_halts {ident}_nodrop {ident}_in_image (by native_decide)
```

The reduction is real: from **one opaque hole over `Total`** to **two precisely
stated obligations about this export's code, plus a proved derivation**. The
hole census now reports two named claims with readable statements instead of
one black box. `{ident}_in_image` was already proved, so the derived half of
`Total` costs no holes at all.

---

## 5. Test bench

### 5.1 What runs right now

```bash
# The library builds clean with the new theorems (this is the gate that matters
# most for [2]'s own work; ProofLib.olean is 27MB and ~80-90s to produce).
cd /Users/mrs/net/gcc/gcc/.mojo/fire/.fire-fire
python3 -c "import sys; sys.path.insert(0,'.'); \
  from formal.lean import find_lean, ensure_library; \
  ensure_library(find_lean(), 'lib', timeout=2400)"
# => no errors

# A scratch file that imports ProofLib and re-checks the conclusion compiles
# standalone. The theorems are in the library, so this needs nothing else:
LEAN_PATH=lib "$(python3 -c "import sys;sys.path.insert(0,'.');\
  from formal.lean import find_lean; print(find_lean())")" /tmp/a2tot/t6.lean
# => silence, and `grep -c sorry` is 0
```

`/tmp/a2tot/t6.lean` is a self-contained file holding both theorems plus the
`Total` derivation, developed against the *imported* library. That is the
isolation that is achievable here: the theorems depend on `Arm64State` /
`arm64_step` / `arm64_go_exit`, so they cannot be lifted out of `ProofLib`, but
they can be developed, iterated and re-checked against nothing but the built
`.olean`, in about a second, without touching the 27MB library build. That
scratch loop is what made this tractable and it should be kept.

### 5.2 The end-to-end bench — RESOLVED, and it was not a model gap

This is now settled, and the answer is reassuring. The first attempt was:

```lean
def benchCode : Nat → UInt8 := fun pc =>
  match pc with
  | 4096 => 0xc0 | 4100 => 0x03 | 4104 => 0x5f | 4108 => 0xd6 | _ => 0
#eval (arm64_step { Arm64State.init 0 4096 with pc := 4096 } benchCode).isSome
-- => false
```

I flagged this as alarming — it looked like the model might refuse to step on a
`ret`. **It does not.** Two things were wrong, neither in the model:

1. `arm64_read_insn` (`ProofLib.lean:1388`) is little-endian over the byte
   list, so bytes `c0 03 5f d6` *should* assemble to `0xd65f03c0`. My
   hand-written `code` function did not actually return those bytes — the match
   was malformed, and `#eval arm64_read_insn c 4096` returns `192` (`0xc0`),
   proving bytes 1–3 came back zero.
2. The `st.pc = st.x30.toNat` guard I was worried about lives at
   `ProofLib.lean:1863`, which is in **`arm64_go`**, not `arm64_go_exit`. It is
   the RET-sentinel condition for the *other* loop. `arm64_step` itself handles
   RET unconditionally at `ProofLib.lean:1454` with
   `some { s with pc := s.x30.toNat }`.

So the takeaway for §6.1 is a correction, and it is the important part: **`ret`
is one of the seven pc-writing opcodes** (below), which is exactly why the
straight-line argument has to exclude it rather than assume every word advances
by 4. The lesson for anyone rebuilding this bench: **use `_gen_code_defs`'s
`code` shape, not a hand-written one** — a `code` function that is wrong in a
way Lean accepts is a silent-false signal, and it cost me a detour.


---

## 6. What I believe can be proved next

This is the part I would want a reader to act on. Ordered by value.

### 6.1 Discharge `hhalts` and `hnodrop` for straight-line exports — the real close

**This section is now a decomposition, not a suggestion.** I read the decoder
and the generator's existing opcode machinery, and the work splits into three
pieces with one genuinely hard member. Two are landed.

**The shape of the obstacle, measured rather than assumed.** `arm64_step` is a
51-branch `if`-chain, but only **seven** of them assign `pc`; the other 44 go
through `arm64_set_reg` or a `with` update that omits `pc`. The seven are
RET, B, BL, CBZ, CBNZ, B.cond, BR. That is small enough to enumerate, and it
means "a non-branching instruction leaves the pc alone" is a *finite* fact
about a table, not a 51-way grind.

#### Landed

1. **`arm64_set_reg_pc`** — `(arm64_set_reg rd s v).pc = s.pc`. Proved, zero
   holes, by `split <;> rfl` over the 32-way register match. This is what makes
   "44 of the 51 handlers cannot move the pc" a fact rather than a hope, and
   it is the first thing any of the downstream proofs need.

2. **`arm64_branchy`** — a `Bool`-valued predicate over exactly those seven
   conditions. It is a `def` rather than a theorem on purpose: what is wanted
   downstream is a **finite check over an image's words** ("is any reachable
   word one of these seven?"), and a `Bool` is exactly what the generator can
   evaluate. **It carries an explicit warning in its docstring that it is
   derived by reading the decoder and nothing in the tree checks the two
   agree** — it must not be read as a completeness claim until the lemma below
   lands.

#### The one hard member

3. **`arm64_branchy insn = false → arm64_step s code = some s' → s'.pc = s.pc`.**

   I attempted this and it is the real cost, so here is the exact obstruction
   with the exact state it reaches. `split_ifs` is unavailable (core Lean only,
   no Mathlib), and `split` cannot make progress on `arm64_step` until the
   opening `let insn := …` is zeta-reduced — without `dsimp only at h` the
   `repeat` exits on its first try having done nothing at all, which looks
   exactly like a hard proof and is not. After zeta, the chain does split, but
   an unrestricted `simp_all` **unfolds `mem_read_u64` and `arm64_reg`**, whose
   own `ite`s re-enter the chain and the term grows instead of shrinking. The
   restricted rewrite set
   (`simp_all only [arm64_branchy, arm64_set_reg_pc, Option.some.injEq,
   ite_self, …]`) splits ~20 branches correctly and then stalls with the rest
   of the chain intact in `h`.

   Two routes, and I recommend the second:

   - *Finish the split.* Roughly 30 more branches of the same mechanical loop.
     Cheap per branch, and every branch is a real check rather than a rewrite.
   - *Get it from the generator's opcode table instead.* `formal/arm64_proof_gen.py`
     already has `_STEP_CONDS`, `_step_branch_index(w)` and `_step_facts(w, idx)`,
     and `_check_step_conds` already enforces that the table **agrees** with
     the decoder. So "word `w` is not one of the seven" is already a decision
     the generator can make per instruction, per image, by `bv_decide` — no
     51-way split needed. Dispatch each in-image word to its `arm64_step_*`
     lemma and the conclusion is `rfl`. **This is strictly better**: it reuses a
     consistency check that already exists and is already tested, instead of
     adding a second, independent copy of the branch table to keep in sync.

#### Then, once (3) lands

4. **The alignment invariant — `st.pc ≡ entry (mod 4)`.** This is the part
   nobody should skip, and it is *not* a check. Progress is now free (a
   non-branching step gives `s'.pc = s.pc`, so `effNext = s.pc + 4`), but
   **containment is not**: `s.pc + 4 ≤ exit` needs `s.pc ≡ exit (mod 4)`, and
   without it a non-branching step at `exit - 1` walks past the exit — the
   overshoot hazard from §3.1, arriving by a different route. So the run needs
   a genuine loop invariant. For straight-line code it is a one-line invariant
   and induction on fuel; getting it right is why §6.1 is not "just a check".

5. **Dispatch over the reachable set.** Given the invariant, the reachable pcs
   are the aligned ones in `[entry, exit)`, computable in Python from the code
   bytes. Emit a *table* lemma keyed on membership in a literal list, then
   `rcases hp with rfl | rfl | …` — **linear, not exponential**. A `by_cases` per
   candidate would be `2^n` and must not be written.


### 6.2 `hnodrop` for a *bounded* number of backward edges

An intermediate result that is cheap and would let the generator close some
real exports: replace strict progress with a lexicographic measure
`(remaining fuel, pc)` and discharge termination whenever the export's control
flow has no cycle. The `hnodrop` statement is already the right interface — a
weaker `hnodrop'` with a *potential* instead of a strict inequality would
plug into the same `dylibExport_total_of` if the theorem is stated over the
potential rather than over `exit - st.pc`. Worth deciding the theorem's shape
with that in mind: a version generalised over an arbitrary `Φ : Arm64State →
Nat` costs almost nothing now and pays off there.

### 6.3 The x86 side

`x86_step_call_rel32` and the earlier call/proof fixes are already integrated.
The identical argument applies — `effNext` is the x86 analogue of the
pc-unchanged bump, and `runProgram`'s budget is a `Nat` in the same place. If
[2] picks up x86 next, the proof transfers almost line for line, and the
`hnodrop` overshoot hazard is worth re-checking there rather than assuming it
mirrors.

### 6.4 Making `Semantics_refutable` sharper

It currently refutes with a zero-length image. Now that `Total` is a real
termination claim, a stronger and more interesting refutation is available: a
code image whose entry is *outside* the code, showing `InImage` and `Total`
are genuinely independent clauses. Small, and it would pin down the distinction
the new docstrings rely on.

---

## 7. Notes for [3]

- **`Total`'s type changed shape.** `∀ n s, runExport … n = some s` became
  `∀ n, ∃ s, runExport … n = some s`. If anything in `lib/Refine.lean`,
  `lib/work.lean` or `lib/Contracts.lean` destructures a `Total` value, or if
  `export_result_spec` is stated in terms of it, it will need the existential.
  I have not touched those files. This is the one thing in this change that
  can break your build, and it is a one-line adaptation on your side rather
  than something I should have done inside your write set.
- The old shape was **false**, so any consumer that appeared to use it was
  either vacuous or already broken. The fix is not a behaviour change; it is
  the removal of an impossibility.
- `{ident}_semantics_total` is now a **derived** theorem rather than an
  obligation, and the two new emitted names are `{ident}_halts` and
  `{ident}_nodrop`. If your `export_result_spec` chains off
  `{ident}_semantics_total` by name, the name still exists and its type is
  still `DylibExport.Total dylib_image {ident}` — only the *body* changed, from
  `sorry` to an application of `dylibExport_total_of`. The hole count in your
  spec obligation is unaffected.

## 8. Honest status

- `Total` corrected, and the correction is a strict improvement: false → true.
- The step bound is **proved**, zero `sorry`, and the fuel bound is discharged
  down to one literal `native_decide`.
- `Total` is **derived** at every generated call site, with two precisely
  named, precisely stated residual obligations.
- `arm64_set_reg_pc` **proved**; `arm64_branchy` **defined** (with an explicit
  warning that it is unverified against the decoder). These are the two
  building blocks the close needs, landed and building.
- `hhalts` / `hnodrop` are **not yet discharged**. §6.1 is now a three-piece
  decomposition with the one hard member identified, its exact obstruction
  recorded down to the tactic that stalls, and a recommended route that
  reuses an existing consistency check instead of adding a second copy of the
  branch table. The alignment invariant (§6.1 step 4) is called out as the
  part that is a real theorem and must not be skipped.

### Corrections to earlier statements in this document

- §5.2 previously implied `arm64_step` might refuse to step on a `ret`. **It
  does not**; the bench's `code` function was malformed. `ret` is one of the
  seven pc-writing opcodes, which strengthens rather than weakens the case for
  the close. The RET-sentinel guard that caused the confusion is in `arm64_go`,
  not `arm64_go_exit`.
- An earlier draft of §6.1 claimed `arm64_step` is "not a function of the code
  bytes alone" because of an `st.x30` read. That was **wrong**, and it was the
  same misreading: the `x30` read is in `arm64_go`'s sentinel test. It matters
  because it wrongly implied `hhalts` was undecidable from the code; it is not.

