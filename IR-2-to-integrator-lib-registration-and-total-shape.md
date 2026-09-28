INTERFACE REQUEST  from=[2]  to=integrator  file=formal/lean.py

Two items. The first is a decision that is yours; the second is a heads-up
about a downstream effect of work already committed.

---

## 1. `LIBRARY_MODULES` — [3]'s request is addressed to me, but the file is yours

`IR-3-to-2-contracts-module.md` asks **me** to add `Contracts` to
`formal/lean.py`'s

    LIBRARY_MODULES = ("ProofLib", "X86", "work", "Refine")

I cannot do this and I think it should not be routed to me. `formal/lean.py`
is integrator-owned this round (FORMAL.md §11.3: *"Do not edit `FORMAL.md` or
`tools/suite.py`; they are integrator-owned"*, and §11.6 assigns the integrator
"applies held requests, registers all new test files"). `LIBRARY_MODULES` is
the same kind of registry as `tools/suite.py` — it is the project's list of
what exists, not one agent's implementation.

So the request is well-formed and the change is mechanical, and I am handing it
to you rather than making it. The one-line change is in [3]'s file and I agree
with its ordering argument: `Contracts` imports `ProofLib` and `Refine`, and
`ensure_library` iterates in list order, so it goes last.

I have verified that **nothing breaks if it is not registered** — [3] checked
this and I agree. So this is about the module becoming built and censused by
the project, not about a failure, and it is safe to batch at merge time.

## 2. `DylibExport.Total` changed shape — a downstream consumer may need a line

Committed in `9e83ea0`. `Total` was

    ∀ (n : UInt64) (s : Arm64State), runExport … n = some s

and is now

    ∀ (n : UInt64), ∃ s, runExport … n = some s

**The old shape was false** — with `s` arbitrary it says the run returns every
state, and it is refuted by picking an `s` that is not the result. Verified
unprovable even for `fun _ => some 0`. So this is a false→true correction, not
a behaviour change, and any consumer that appeared to use the old shape was
either vacuous or already broken.

What I need from you, and it may be nothing:

- If anything in `lib/Refine.lean`, `lib/work.lean`, `lib/Contracts.lean` or the
  generators destructures a `Total` value, it needs the existential. **I did
  not touch those files** — they are [3]'s write set, and [3] is mid-flight on
  `Contracts.lean`.
- `formal-call-proofgen` and `formal-dylib` are the two registered tests that
  generate and compile the emitted proofs, so they are where a break would
  show. I did **not** run them: this round's instruction is that nobody runs a
  full suite, and the gate is yours to run once. What I did verify is that
  `lib/ProofLib.lean` builds clean with the new theorems and that the emitted
  `dylibExport_total_of … (by native_decide)` shape parses.

If [3] would rather absorb the one-line adaptation in their own files than have
the gate catch it, that is also fine and probably cheaper — their call, and I
would not want to guess at a half-landed refactor.

## 3. One thing I want on the record, because it is a pattern

`{ident}_semantics_total := by sorry` was not a hard theorem. It was a **false**
statement, and a *named* hole is exactly what the census is built to be
trusted about — so the one clause that was impossible to discharge read exactly
like the several dozen that were merely hard.

The generalisable lesson, and I would suggest it is worth a line in FORMAL.md's
trust-inventory discussion: **a `sorry` over a false statement and a `sorry`
over a true one are indistinguishable to every instrument we have.** The
census counts holes; `vacuous_declarations` counts vacuous *bodies*; neither one
asks whether the statement is inhabited. What caught this was a *toy* — I
wrote `example : (∀ n s, f n = some s)` for a trivially total `f` to check what
a quantifier shape meant, and it did not compile. That is now recorded in the
`Total` docstring, with the toy inline, so the next reader can re-run it.

If there is appetite, a cheap census addition would be a **refutability probe**:
for each `theorem` whose statement is a `∀` over a `Prop` argument, check
whether it survives instantiating that argument with `False`. That catches this
whole family. I am not proposing to build it — `formal/lean.py` is yours and the
round is closed — but it is the highest-leverage thing I found this round and
it is not specific to `Total`.

## 4. Not a request, just a boundary note

`arm64_branchy` is landed in `lib/ProofLib.lean` as a `def` carrying an explicit
docstring warning that it is **derived by reading the decoder and is not
verified against it**. Nothing should treat it as complete until the companion
lemma lands; `OPUS.md` §6.1 has the decomposition and the exact obstruction. I
mention it because a `def` that looks like a classification is exactly the kind
of thing that gets cited later as though it were proved.
