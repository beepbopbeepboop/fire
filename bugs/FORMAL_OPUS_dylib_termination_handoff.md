# OPUS handoff: dylib export termination (`Total`) and the per-export contract

**Read this first if you have no context.** State at `3a8cb0b`. Nothing here
needs re-deriving; every claim is measured or committed, and the measurements
say which. If you read two sections, read §1 and §3.

Work items are tagged **`OPUS`** on the line so the integration planner can
route them. Everything untagged is context, not a request.

---

## 1. Where the tree is right now

| fact | evidence |
|---|---|
| `formal-dylib` is **RED** | 11 PASS / 1 FAIL (measured 2026-10-01, `python3 test_formal_dylib.py`; the 2026-10-01 tree has one more passing case than the 10 recorded below). The FAIL is `default path emits a checked proof`: `default (prove) dylib build failed: … lean timed out`. |
| That red is **cached, and caching makes it stick** | `formal/lean.py::check_proof_cached` publishes FAIL verdicts as well as PASS ones, so the timeout is replayed in ~0.1 s on every later run and no amount of re-running on a quieter machine re-derives it. A direct `lean` run on the emitted file (`.tmp/dy/proved_proof.lean`, 210 KB, from `def triple(n): return n * 3`) did not finish in **30 minutes** on this box, so the red is real rather than a stale artefact — but it is also not cheap to re-measure, which is why it needs a deliberate measurement rather than a rerun. |
| `Total` is **proved** for acyclic, call-free exports | `DylibExport.total_of_halts` + the generator's CFG walk. 0 errors, 0 holes on `triple`. |
| `Total` is **true but unproved** for looping exports | `e0af987` made `exportFuel` n-dependent, so it stopped being false. A walk scoped to acyclic/call-free is what a loop is not, so no proof exists. |
| The one admitted `sorry` in a plain dylib proof is gone | the emitter derives the spec from the **source** AST, so `_spec` is a proved contract, not an obligation. |
| `x19` "callee-saved defect" | **[3]'s misreading** of one end-state of a 15-step trace. The frame round trip is exact. Do not re-investigate. |

**Do not make `formal-dylib` green by reverting `d9443ed`.** A green test that
does not do what we want is worse than a red that needs fixing: a red gets
fixed, a green lie is technical debt.

**Not the arm64 proof generator's bridge work.** `generate_dylib_proof` is a
self-contained 117-line function that calls none of `_go_defs_for`,
`emit_runs`, `_gen_dec_while_block`, `_gen_countdown_loop`, `_COND_LEMMA` or
`_VALUE_SIMP`, and the emitted dylib proof contains no `sKey` and no
`eval_eq_mojo` at all (checked by reading both). So the two generator changes
made on 2026-10-01 for the example suite (`003a4696`, `8c1011ae`) cannot have
moved this, and a future bisect of this red should not start there.

---

## 2. What is left, ranked

### `OPUS-1` — `hreg` exhausts `maxHeartbeats`; raise it and measure the real cost

The single remaining blocker on `formal-dylib`.

Measured, in order:

- `hreg` is **not** an arithmetic failure any more. The `omega` goal
  `15 + (fuel - 15) = fuel` that used to fail at line 1806 now reads
  `15 + ((200000 + 15 * n.toNat) - 15) = (200000 + 15 * n.toNat)`, and
  `omega` closes it — `e0af987` fixed that by making the emitted fuel literal
  arithmetic rather than an opaque function call.
- What remains is `(deterministic) timeout at whnf, maximum number of
  heartbeats (20000000) has been reached`, reported at the `hreg` declaration.
- **OPUS-1:** the first thing to try is exactly what
  `IR-3-to-2-dylib-contract-emitter.md` said — raise `maxHeartbeats` and
  measure. I started that at 400,000,000 and stopped the run rather than let
  it go an hour, so **the cost at 400M is unknown.** Measure it before
  concluding anything.
- The effect is finite and in principle reducible: 15 steps, a 6-entry memory
  list, constant addresses. So this should be a budget question rather than a
  missing decision procedure. If a large budget makes it pass, the honest
  follow-up is to find *why* it needs one — a `simp` set that over-unfolds, or
  a `bv_decide` on a term that could be `native_decide`d.

### `OPUS-2` — `test_formal_dylib.py:402-410` pins the obligation set by EQUALITY

**Not my write set** (`formal/arm64_proof_gen.py` and `lib/ProofLib.lean` are;
the integrator registers tests). Flagged because it will be red for a
*correct* reason and the check is wrong in a way that matters.

`_spec` is now emitted **only on the fallback path**. For a derivable export
the emitter emits a proved contract, so no `_spec` theorem exists and

```python
check(obligations == expected, ...)
```

no longer matches. Worse, an equality check **cannot distinguish "no
obligation because it is PROVED" from "no obligation because the emitter
forgot"** — a silently missing contract and a discharged obligation are the
same observation to it.

Fix: drop `| {f"{i}_spec" for i in idents}` from `expected`, and assert instead
that a derivable export's contract is **present and sorry-free** — `agrees_of_body`
appears and `theorem (\w+_spec)\b` does not, per export whose `_dylib_spec_lean`
returned a spec. A subset check fails in the direction that matters, the way
`KNOWN_LIB_HOLES` already does.

### `OPUS-3` — the `noEarly` unfold I added is a suspected cost centre

My `hreg` fix (`fe142b8`) applies a ~30-entry `simp only [...]` at **15**
`noEarly` sites, one per `interval_cases` branch. Each re-unfolds the whole
`S`/`st` chain. That is plausibly a large share of the heartbeat bill, and it is
**mine**, so it is the first thing to try if `OPUS-1` shows the budget is
structural rather than incidental.

Cheaper alternative, untested: unfold once in a `have` per branch instead of
`simp` inside the `omega` goal.

### `OPUS-4` — loops: `Total` is true, and still unproved

`e0af987` closed the *falsehood* (`exportFuel` is now
`200000 + PATH * n`, and a measured `countdown` halts through `n = 5000`,
returns `none` at `8000`). It did not produce a proof: `total_of_halts` consumes
an acyclic, call-free walk, which is exactly what a loop is not.

Closing it is a **scheme extension, not a fix** — a ranking function, or a fuel
invariant that the walk carries. Do not report "fuel grows with n" as
termination: that is the false-versus-unproved confusion this project has
already been bitten by twice (`Total`'s `∀ n s` form, and the constant-fuel
`countdown`).

### `OPUS-5` — `bl`: needs a depth-indexed `FrameBound`, not a flag

A constant budget does **not** discharge `hn` for free, which is the tempting
wrong argument. `FrameBound` is not a hypothesis the walk checks at the end; it
is threaded **through** the recursion. `hbnd` is an argument of the walk's own
statement, `frameBound_descend`/`_le` re-derive it per level, and
`contract_sound_tree` takes it as a parameter. The callee's bound is *consumed*
on the way down, not discharged once at the top.

The real fix: state and prove a depth-indexed frame bound
(`∀ k ≤ depth, FrameBound … at level k`) discharged from the instruction count,
and re-thread `hbnd` in terms of it. Not started; real work.

### `OPUS-6` — x86: never measured, and the lesson does not transfer for free

`fuel`/`fuel_lean` were added to the **arm64 walker only**.
`IR-3-to-2-dylib-contract-emitter.md` §5 confirms [3] did not touch
`formal/x86_proof_gen.py`. So "the same argument applies" is a hypothesis, not a
finding, and `OPUS.md` §4.3 now says so.

**OPUS-6:** measure the acyclic/no-call boundary on x86 the way §5.0 measures
it for arm64 (a dylib with one straight-line export, one that calls, one that
loops — read which `_semantics_total` are `total_of_halts` and which are
fallback).

### `OPUS-7` — `§4.4` is done; a sharper `Semantics_refutable` is not needed

Landed as a by-product: `backward_branch_in_image : InImage …` and
`total_refuted_backward_branch : ¬ Total …` are a checked pair on a
**well-formed** image, showing the two clauses are independent. Stronger than
the version §4.4 proposed, which used a *malformed* image.

---

## 3. The two lessons worth more than the items above

### `OPUS-8` — replacing a literal with a function hides it from every tactic

`fuel_lean` replaced the emitted fuel *literal* `100000` with the library
*function* `DylibExport.exportFuel dylib_image n`, so the two could not drift.
Good change. But the walk's step-accounting goals are `omega` calls, and
`omega` **cannot unfold a library function**:

```
15 + (exportFuel dylib_image n - 15) = exportFuel dylib_image n
```

True for any fuel `≥ 15`, and provable the moment the definition is visible.
Verified: `simp [DylibExport.exportFuel]; omega` fixes that line outright.

The generalisable part: **both `omega` and `native_decide` work on literals.**
A no-drift property bought by swapping a literal for a function has to be paid
for by re-supplying the bounds the literal used to carry — the
`fuel < _TOTAL` guard still runs on the Python side, but its *result* was never
emitted into the Lean text, so the lower-bound goals had nothing to work from.
Otherwise the change trades a silent-drift bug for an unsatisfiable-arithmetic
one. `e0af987` fixed this instance by going back to literal arithmetic
(`200000 + 15 * n.toNat`); the hazard is live for any future swap of the same
shape, x86 included.

### `OPUS-9` — a `sorry` over a FALSE statement is indistinguishable from one over a true one

This has now happened **three times in this thread**, which is why it is worth
stating as a rule rather than an anecdote:

1. `Total` was `∀ n s, runExport … n = some s` — not termination, but "returns
   every state". Refuted by a toy: `example : (∀ n s, f n = some s)` for
   `f := fun _ => some 0` reduces to `⊢ 0 = s`. Fixed to `∀ n, ∃ s, …`.
2. The constant `exportFuel` made `Total` **false** for `countdown`; a named
   `sorry` sat on the impossibility while the census reported it as an open
   obligation. Checked by `total_refuted_backward_branch`.
3. Every all-states theorem I wrote was false for any image containing a `ret`
   (arbitrary `x30`) or a pc below `image.base` (decodes nothing). The census
   was counting holes no proof could ever fill.

**The instrument that catches all three is the cheapest one there is: state the
predicate at a concrete instance and see whether it survives.** The census
counts holes; `vacuous_declarations` counts vacuous *bodies*; neither asks
whether a statement is **inhabited**.

**OPUS-9:** when a new `sorry` is emitted, check inhabitance at one concrete
instance before recording it as an obligation. Cheap, and it has caught three.

---

## 4. State bits that will save a fresh context time

- **Write set:** `lib/ProofLib.lean`, `formal/arm64_proof_gen.py`.
  `formal/lean.py` and `tools/suite.py` are integrator-owned (§11.3);
  `formal/build.py` is in **nobody's** write set; `lib/Contracts.lean`,
  `lib/Refine.lean`, `lib/work.lean` are [3]'s.
- **`lib/Contracts.lean` is registered** in `formal/lean.py`'s
  `LIBRARY_MODULES` and builds, so the emitter's `import Contracts` resolves.
  This was a one-line integrator change blocking two agents; it landed.
- **The golden file** `formal/golden/arm64_dylib_contract_triple.lean` is
  **gone**, deleted by me by accident: the deletion was already staged in the
  index and I ran a bare `git commit`, which commits everything *staged*, not
  just what I had `git add`ed. Recoverable at `c967b5d`. The deletion is
  defensible on the merits — the file's own header authorised it conditionally,
  and [3] retracted it as invalid evidence — but it was not my judgement.
  **Lesson: `git commit -o <paths>`, or `git commit` right after checking
  `git status`, in a tree with concurrent agents.**
- **`formal/arm64_proof_gen.py` has duplicated definitions** (FORMAL.md §10):
  `generate_arm64_proof` at `:6034` and `:7222`; `_gen_extern_test` at `:5661`
  and `:6849`; `_find_extern_call` at `:5556` and `:6744`. Byte-identical, so
  behaviour is unaffected and Python binds the second — but **the live
  `_gen_extern_test` is at `:6849`**, and any line number referring to the
  other copy is wrong. The proof generator is the wrong place to carry two
  copies of anything.
- **`test_formal_dylib.py` and `test_formal_sweep_truth.py` ARE registered** —
  `formal-dylib` at `tools/suite.py:683` and `formal-sweep-truth` at `:701`. So
  `OPUS-2` is collected and will be red for its (correct) reason. I checked
  this rather than trusting the old `ba0a61f` note, which no longer holds.
- **Do not `rm` `lib/*.olean` or `*.srcsha256`.** §11.3 forbids it; they are
  shared and built under an exclusive `flock`. `ensure_library`
  (`formal/lean.py`) rebuilds on its own. I deleted some to force a rebuild
  early in this thread and it was needless risk.

---

## 5. Documentation conflict, for whoever reconciles it

`OPUS.md` §4.1 and §4.1-MEASURED are **two accounts of one change** — the
former mine, recording the fuel change and its walk regression as fixed; the
latter [3]'s, with the `5000`–`8000` threshold. §5.7 is mine and measures the
same walk breakage, now superseded by `e0af987`. They should be folded or
cross-referenced so the next reader does not read two stories for one bug.

`OPUS.md` §5.5's advice ("try `+decide`, then suspect the memory round trip")
was a **guess and was wrong**; §5.7 is the measured answer. §5.5 is corrected to
point there. If `OPUS-1` shows a budget is genuinely needed, §5.5 should be
rewritten again — as a third revision, not a fourth.

---
