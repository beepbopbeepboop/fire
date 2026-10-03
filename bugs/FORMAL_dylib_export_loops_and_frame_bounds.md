# dylib exports: the loop-fuel obligation, the depth-indexed frame bound, and x86

**Status: OPEN, and no longer about termination.** The non-terminating obligation
this file used to be about is FIXED (`7d0ac990`, `0cfe0d16`) and its doc is
deleted; what is left is three pieces of real work that the same investigation
put on the table and that no fix closed. Everything here is measured or
committed, and the measurements say which.

**For an agent starting with no context.** The write set is
`lib/ProofLib.lean` and `formal/arm64_proof_gen.py`. Read §2 (the two rules that
have already cost this project real time) and §4 (the exact next step per item);
nothing else needs re-deriving.

## 1. What closed, and what it was

| was | now |
|---|---|
| `formal-dylib` RED on `default path emits a checked proof`; the emitted 210 KB proof "did not finish in 30 minutes", and at a 180 s CPU bound measured 177.1 s CPU in 79.9 s wall before `RLIMIT_CPU` fired | **GREEN.** `python3 tools/suite.py formal-dylib --no-cache` -> 3 passed / 0 failed. The generated proof of `def triple(n): return n * 3` checks in **9.0 s wall / 14.4 s CPU / 1.63 GB peak**, rc 0, **0 holes** |
| `OPUS-1` "`hreg` exhausts `maxHeartbeats`; raise it and measure the real cost" | **Not a budget question after all, and no budget was raised.** The goal had to get smaller: the emitter was writing a fourteen-fold nest of the runner's own `if pc = pc then .. else ..` around the whole composed `Arm64State`, and `bv_decide`'s internal normalisation of a case split per level is the loop that did not terminate. The emitter emits that `if` **resolved** for every step it knows moves no pc, and keeps it only for the closing `ret` |
| `OPUS-2` "`test_formal_dylib.py:402-410` pins the obligation set by EQUALITY" | **Fixed.** The check is now per export: terminates, and EITHER a proved contract OR a named `_spec`, never both and never neither, plus a per-namespace `sorry` grep |
| `OPUS-3` "the `noEarly` unfold I added is a suspected cost centre" | **It was one, and a bigger one than `hreg`.** With `bv_decide` replaced by `sorry` the contract region still did not finish: 79.7 s wall / 296 s CPU, killed at a 300 s bound. Fifteen `simp only [S15…, st0…]` blocks, each re-unfolding the composed state. They are now fifteen `omega`s off one per-step `pc` lemma |
| `OPUS-7`, `OPUS-8` | Closed before this file existed |
| the eight gate tests `disabled=` | Re-enabled (`0cfe0d16`) |

**The part nobody had looked for.** The contract had never been checked, and
checking it found it was **wrong**: `st_i` composed *itself* while `S_{i+1}`
feeds it the running state, so every step ran once per earlier step again. On
`triple` the `MUL` ran five times — the composed effect said `n * 243` where the
machine computes `n * 3`. That is a `sorry` over a false claim, which is §2's
second rule. Also wrong and also never elaborated: `body.step` was one step
short of the block it certifies, the `BlockCert` was an `instance` of a
`structure … : Prop` that is not a class, `runsTo0` was used but never emitted,
and `noEarly` split its `u` with `interval_cases`, which is a Mathlib tactic and
this toolchain has no Mathlib (`import Mathlib.Tactic` is "unknown module
prefix"; there is no `Std.Tactic.IntervalCases`). `test_formal_dylib.py`'s
`a wrong spec is rejected, not believed` is what keeps any of it back: a proof
that merely elaborates says nothing, and `n * 243` elaborated with every text
check in that file green.

## 2. The two rules that have already cost this project real time

### A `sorry` over a FALSE statement is indistinguishable from one over a true one

This has happened **four** times in this thread, which is why it is a rule and
not an anecdote:

1. `Total` was `∀ n s, runExport … n = some s` — not termination, but "returns
   every state". Refuted by a toy: `example : (∀ n s, f n = some s)` for
   `f := fun _ => some 0` reduces to `⊢ 0 = s`. Fixed to `∀ n, ∃ s, …`.
2. The constant `exportFuel` made `Total` **false** for `countdown`; a named
   `sorry` sat on the impossibility while the census reported it as an open
   obligation. Checked by `total_refuted_backward_branch`.
3. Every all-states theorem written here was false for any image containing a
   `ret` (arbitrary `x30`) or a pc below `image.base`. The census was counting
   holes no proof could ever fill.
4. `st_i`'s composed effect was `n * 243` for a machine computing `n * 3`, under
   a `hreg` that was a `sorry`.

The instrument that catches all four is the cheapest one there is: **state the
predicate at a concrete instance and see whether it survives.** The census counts
holes; `vacuous_declarations` counts vacuous *bodies*; neither asks whether a
statement is **inhabited**, and none of the three would have caught #4.

### Replacing a literal with a function hides it from every tactic

`fuel_lean` replaced the emitted fuel *literal* `100000` with the library
*function* `DylibExport.exportFuel dylib_image n`, so the two could not drift.
Good change. But the walk's step-accounting goals are `omega` calls, and `omega`
**cannot unfold a library function**: `15 + (exportFuel dylib_image n - 15) =
exportFuel dylib_image n` is true for any fuel `≥ 15`, and provable the moment
the definition is visible (`simp [DylibExport.exportFuel]; omega`).

The generalisable part: **both `omega` and `native_decide` work on literals.** A
no-drift property bought by swapping a literal for a function has to be paid for
by re-supplying the bounds the literal used to carry. `e0af987` fixed that
instance by going back to literal arithmetic (`200000 + 15 * n.toNat`); the
hazard is live for any future swap of the same shape, **x86 included**.

## 3. What is left

### `OPUS-4` — loops: `Total` is true, and still unproved

`e0af987` closed the *falsehood* (`exportFuel` is now `200000 + PATH * n`, and a
measured `countdown` halts through `n = 5000`, returns `none` at `8000`). It did
not produce a proof: `total_of_halts` consumes an acyclic, call-free CFG walk,
which is exactly what a loop is not, so `_dylib_total_proof` falls back to the
named `sorry` obligation for any export with a loop or a call.

Closing it is a **scheme extension, not a fix** — a ranking function, or a fuel
invariant the walk carries. Do not report "fuel grows with `n`" as termination:
that is the false-versus-unproved confusion this project has been bitten by
three times (§2).

### `OPUS-5` — `bl`: needs a depth-indexed `FrameBound`, not a flag

A constant budget does **not** discharge `hn` for free, which is the tempting
wrong argument. `FrameBound` is not a hypothesis the walk checks at the end; it
is threaded **through** the recursion. `hbnd` is an argument of the walk's own
statement, `frameBound_descend`/`_le` re-derive it per level, and
`contract_sound_tree` takes it as a parameter. **The callee's bound is *consumed*
on the way down, not discharged once at the top.**

The real fix: state and prove a depth-indexed frame bound
(`∀ k ≤ depth, FrameBound … at level k`) discharged from the instruction count,
and re-thread `hbnd` in terms of it. Not started; real work.

### `OPUS-6` — x86: never measured, and the arm64 lesson does not transfer free

`fuel`/`fuel_lean` were added to the **arm64 walker only**
(`IR-3-to-2-dylib-contract-emitter.md` §5). So "the same argument applies" is a
hypothesis, not a finding. **Measure** the acyclic/no-call boundary on x86 the
way §1 measured it for arm64: a dylib with one straight-line export, one that
calls, one that loops — read which `_semantics_total` are `total_of_halts` and
which are the named fallback. `formal/x86_64_proof_gen.py` is untouched by
everything above.

## 4. Exact next step per item

* **OPUS-4** — read `DylibExport.total_of_halts` and
  `formal/arm64_proof_gen.py::_dylib_total_proof`. The emitter's fallback is
  already the honest shape (a NAMED obligation, counted by the census), so
  nothing is red; this is a feature, and it should be scoped as one.
* **OPUS-5** — read `frameBound_descend` / `frameBound_le` in `lib/ProofLib.lean`
  first. The claim to check before writing anything is whether `depth` is
  already a parameter of the walk; if it is not, that is the change, and it is
  not small.
* **OPUS-6** — three dylibs, `fire.py dylib --formal`, grep the generated
  `_proof.lean` for `total_of_halts` versus `OBLIGATION, not proved`. Nothing
  needs Lean: this is a classification read off the emitted text.

## 5. State bits that will save a fresh context time

- **`lib/Contracts.lean` is registered** in `formal/lean.py`'s `LIBRARY_MODULES`
  and builds, so the emitter's `import Contracts` resolves.
- **`formal/arm64_proof_gen.py` has duplicated definitions** (`FORMAL.md` §10):
  `generate_arm64_proof`, `_gen_extern_test`, `_find_extern_call`. Byte-identical
  so behaviour is unaffected and Python binds the second — but **the live
  `_gen_extern_test` is the later one**, and any line number referring to the
  other copy is wrong. The proof generator is the wrong place to carry two
  copies of anything. `_dylib_contract_proof` is NOT duplicated.
- **Do not `rm lib/*.olean` or `*.srcsha256`.** They are shared and built under
  an exclusive `flock`; `ensure_library` rebuilds on its own.
- `test_formal_dylib.py` and `test_formal_sweep_truth.py` ARE registered
  (`formal-dylib`, `formal-sweep-truth`).
- `formal/lean.py` and `tools/suite.py` were integrator-owned when this thread
  ran; `formal/build.py` is in **nobody's** write set.
- **Never `git commit` a bare path in a tree with concurrent agents**: it commits
  everything STAGED, which is how the golden file `formal/golden/
  arm64_dylib_contract_triple.lean` was deleted by accident here (recoverable at
  `c967b5d`; defensible on the merits — [3] retracted it as invalid evidence —
  but not the author's judgement). Use `git commit -o <paths>`, or check
  `git status` first.
