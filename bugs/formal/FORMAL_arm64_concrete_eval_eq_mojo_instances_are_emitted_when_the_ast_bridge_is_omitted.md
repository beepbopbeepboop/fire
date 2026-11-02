# FORMAL_arm64_concrete_eval_eq_mojo_instances_are_emitted_when_the_ast_bridge_is_omitted: the fourth call site of `_ast_model_cannot_state` never consults the predicate, so five theorems reference an `ast` the file never wrote

**Status, 2026-11-01: discovered in the CSEL round (whose doc, `FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`, deleted, carried the pointer in its Status entry). A separate defect — the CSEL diff does not touch this path (§3, last paragraph) — and this doc is its round. The fix is one line, and everything in §3 was measured to prove it.**

**Status, 2026-11-02 (gate round): the gate LANDED, the named defect is RESOLVED and demonstrated before/after on the SAME machine, and the ternary — this doc's own named quick test — checks FULLY GREEN. The f3 re-check of §4 step 3 still does not reach a verdict on this machine: f3-scale `native_decide`s sit at the launcher's fixed per-check memory budget (`LEAN_MEMORY_MB = 6144`), a machine/budget-class bound breach that the tree's fixed Lean bounds make "not a verdict on the proof" — and the PRE-FIX f3 measured on this machine this morning hits the exact same class, so this doc stays open for one f3 verdict on a machine with headroom. No refusal-taxonomy row or census row changed: the gate changes no program's right to a proof (generation never depended on `eval_test_block`) and it removes only `native_decide`-decided theorems, so a verdict-reaching file's sorries count is unchanged.**

What landed, exactly per §4 step 1 (line numbers at HEAD `66ac017c`, the file having grown since this doc was filed):

* `formal/arm64_proof_gen.py` L12427 (`generate_arm64_proof`'s concrete-instances gate): `if (not is_typed) and not ast_cannot and _always_returns(fn.body) and not _has_while(fn.body):` — the doc's prescribed gate, verbatim, with the explanatory comment block above it stating the measured failure mode.
* The docstring of `_ast_model_cannot_state` (L3339) now counts the FOUR decisions (emit the bridge, build `ast_def`, run the call-gap check, emit the concrete `eval_eq_mojo_N` instances) and records that the concrete instances were the fourth caller that answered differently; the "read ONCE" comment at the `ast_cannot` computation (L12106-12110) says four, not three.

Evidence (all 2026-11-02, this tree, the 12 GB slot, `python3 tools/memslot.py --gb 12 --label astgate-* -- python3 -c "from formal.lean import check_proof_cached; print(check_proof_cached('<file>', repo_root='.'))"`, regenerating with the same `genonly.py` stub the CSEL round used):

* **Ternary regenerated and checked: GREEN.** `(True, '', False, 1)` — zero errors, the intended single admitted `sorry`, census "1 declaration(s) admitted a sorry, 0 vacuous", peak 4.9 GB. The regenerated file differs from the pre-fix regeneration of this morning (`.tmp/csel-close/ternary_proof.lean`, 00:03 — byte-sized exactly like the doc's 11-01 ternary, 488,743 bytes) by ONE hunk: the five concrete theorems (`eval_eq_mojo_0/1/2/5/test`) are gone; zero `evalFunc ast`, zero `def ast`, and the omission note at L22 stays. This is §4 step 2's expected end state.
* **Same-machine PRE-FIX controls (this morning, before the gate landed; untracked logs in `.tmp/csel-close/`)**: `tern_check.log` (00:13, 8 GB slot) — the pre-fix ternary reports EXACTLY the five `ast` free-variable errors (lines 29/34/39/44/49, the doc's §1 pattern) and nothing else, census 1 sorry / 0 vacuous, peak 5.6 GB. `f3_check.log` (00:38, 12 GB slot) — the pre-fix f3 reports the same five `ast` errors PLUS a second, pre-existing class: `(kernel) excessive memory consumption detected` on the runs/step `native_decide`s, peak 8.5 GB, `maxErrors` exit. `f3b_check.log` (00:53) — a nested-ternary f3 variant (`return 1 if n > 8 else 2 if …`), same pattern, peak 8.1 GB. Both the `ast` defect and the f3-scale kernel-memory behaviour were thus measured on this machine pre-fix, hours before this gate: the gate's effect is isolated.
* **f3 regenerated post-fix: the named defect is gone.** Zero `evalFunc ast` / `def ast` / `eval_eq_mojo_N`; the diff against the pre-fix f3 is one hunk (the five theorems). Its re-check on THIS machine (`astgate-f3`, 12 GB slot): NO `Expected type must not contain free variable` anywhere in the output — only the pre-existing kernel-memory class from the pre-fix control above (every `native_decide` of the runs tests and step results, lines 42-434, all outside the gate's diff; even the trivial `def run_pc_reached` trips it; Lean exits at `maxErrors` 100). The kernel's per-check memory budget is the launcher's fixed `LEAN_MEMORY_MB = 6144` (`-M 6144`, `LEAN_THREADS = 4` — `formal/lean.py`, deliberately not env-raisable), and ternary's smaller-scale `native_decide`s pass under it on this machine: f3's scale sits at that budget's boundary on this CPU, while the 2026-11-01 machine checked f3 at 560.1 s wall / 5.6 GB with the `ast` errors as its ONLY output. A second pre-fix datapoint on this machine: the pre-fix 161-instruction f3 (1,566,531 bytes) checked under `astgate-f3old` died at the 1500 s tree-CPU bound — "NOT a verdict on the proof" — the same class, one bound earlier.
* Regression checks on the tree side: `test_formal_eval_eq_mojo_bridge.py` 31/32 (the 1 failure is `TestTheNestedExprRoutes`, the known pre-existing red of 2026-11-02, failing identically in isolation), `test_formal_proof_breadth.py` 33/33, `G.check_step_conds()` OK.

What remains, and where the next round picks up:

1. **One f3 verdict on a verdict-reaching machine.** Litmus first: check the pre-fix f3 (`.tmp/csel-close/f3_proof.lean`, 12 GB slot) on the candidate machine. The 2026-11-01 machine reached a verdict there (560.1 s, errors = ONLY the five `ast` ones — i.e. a machine whose f3-scale `native_decide`s clear the 6144 MB per-check budget); a machine that instead hits the 1500 s CPU bound or the kernel-memory `maxErrors` exit cannot reach an f3 verdict and is the wrong machine. On a verdict-reaching machine, run §5's one-liner against the regenerated POST-FIX f3 (regenerate with the `genonly.py` stub, §4 step 2). Expected per §4 step 3: ok=True, sorries=1 (the universal theorem's admission), zero errors — the pre-fix file's five `ast` errors are the only difference the gate makes, so clean is the only outcome.
2. **If that machine instead reports the `-M 6144` kernel-memory class on f3's runs/step `native_decide`s** (rather than the old 560 s green), then f3's wall has moved to the launcher's per-check budget, which is a SEPARATE defect of the `LEAN_MEMORY_MB` policy (its own measurement and doc; note the docstring at that constant already records a `-M 4096` build failure of the same class on the library side). In that case the gate work of THIS doc is still done and the doc is deleted with the budget issue filed separately.
3. Then, either way, §4 step 5: delete this doc, regenerate `bugs/OPEN_WORK.md` (`python3 tools/formal_doc_index.py --write`), and `python3 tools/dangling_doc_refs.py --ratchet`. Only `bugs/OPEN_WORK.md` cites this doc, so no other citation work exists.
4. f4 stays out of scope per §4 step 4 (the certificate doc's walled leaf; its measurement is the wall, §3).

The arm64 e2e generator emits the concrete `eval_eq_mojo_N` theorems for a body the untyped AST model cannot state, and those theorems reference an `ast` the file never declared. Every generated proof for a loop-free conditional expression fails Lean with five `Expected type must not contain free variables` errors. Because a ternary compiles to CSEL, the defect sat across the whole CSEL class's Lean check. Measured on three programs: a ternary, a three-branch, a four-branch.

## 1. What was seen

```
$ python3 tools/memslot.py --gb 12 --label csel-f3 -- python3 -c "from formal.lean import check_proof_cached; print(check_proof_cached('<f3_proof.lean>', repo_root='.'))"
  [proof census: f3_proof.lean — 1 declaration(s) admitted a `sorry`, 0 vacuous (admitted by a complete proof and asserting nothing)]
F3 RESULT ok=False cached=False sorries=1 wall=560.1s
f3_proof.lean:29:2: error: Expected type must not contain free variables
  evalFunc ast (fun name arg => if name = "f3" then mojo arg else 0) [UInt64.ofNat 0] = mojo (UInt64.ofNat 0)

Hint: Use the `+revert` option to automatically clean up and revert free variables
f3_proof.lean:34:2: error: Expected type must not contain free variables
  evalFunc ast (fun name arg => if name = "f3" then mojo arg else 0) [UInt64.ofNat 1] = mojo (UInt64.ofNat 1)
  ... and four identical in total, at lines 29/34/39/44/49 ...
memcap: done, peak 5.6 GB across up to 2 procs (ceiling 12.0 GB), child exit 0
```

The file structure around the errors (identical in all three files):

```
19: /- AST for f3 (mirrors source code). -/
20:                                       <- `def ast` never written
22: /- A conditional expression (`MojoExpr` has no conditional form): the untyped AST-eval bridge is omitted; ... -/
26: theorem eval_eq_mojo_0 :
27:   evalFunc ast (fun name arg =>
```

`ast` is referenced five times and declared zero times in the file, and nothing imported declares it (no `ast` in `lib/ProofLib.lean`, none in `lib/work.lean`). The section comment directly above the theorems says the bridge is omitted; the theorems below it use it anyway.

## 2. Why the generator writes it

`_ast_model_cannot_state` (`formal/arm64_proof_gen.py` L3276) is documented as "ONE PREDICATE FOR THREE DECISIONS" — whether the `eval_eq_mojo` section is emitted, whether `ast_def` is built, whether the call-gap check runs — and its docstring names this exact failure mode: a caller that answers the decision differently produces "a bridge theorem over an `ast` that was never written".

The concrete-instances block (`eval_test_block`, L12298–12332) is a **FOURTH** call site of the same decision, and it does not consult the predicate. Its gate at L12300 is

    if (not is_typed) and _always_returns(fn.body) and not _has_while(fn.body):

and `ast_cannot` — computed at L12006, in scope — is nowhere in it.

The scope is exactly one of the predicate's two shapes: a `for`-range loop is already excluded by `_has_while` (which covers `ForStmt`), and a typed function by `is_typed`. What remains — and is the measured shape — is the **loop-free conditional expression**: a value-position ternary in a body that always returns. The docstring's referenced census measured that shape at 37 of 60 generated programs, so this is not a corner case.

Lean's diagnostic is the free-variable reading, not an "unknown identifier": the undeclared `ast` elaborates as an error placeholder, the goal's type is not closed, and `native_decide` — which evaluates the goal in a closed context — refuses it. Lean's own hint on the same line confirms the reading.

## 3. What was measured (all 2026-11-01, this tree, the 12 GB slot)

* **ternary** (`def tern(n): return 1 if n > 0 else 2`, 488,743 bytes, one CSEL word `0x1000004d8`): the check reports exactly the five errors (lines 29/34/39/44/49) plus the intended single admitted `sorry` (line 7069; census: "1 declaration(s) admitted a sorry, 0 vacuous"). Nothing else in the file — the walk, the `tern_sr_70` closer on `work_step_csel`, the run tests — is affected.
* **f3** (three branches, 772,883 bytes, three `work_step_csel` closers): ok=False, wall 560.1 s, peak 5.6 GB, sorries=1; the errors are EXACTLY the five `ast` ones — everything else in the file checks. That is the CSEL class's 3-branch discharge: with the gate in, f3 is green under this ceiling.
* **f4** (four branches, 1,063,840 bytes, four closers): killed at 1501 s CPU against the 1500 s bound, peak 6.3 GB, `sorries=None` — "this is NOT a verdict on the proof". That is the 4-branch boundary of `FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md` reached for a CSEL program — the CSEL row's named walled leaf. The five `ast` references are structurally present (five `evalFunc ast`, zero `def ast`); the kill predates their report.

**Pre-existing, not introduced by the CSEL round**: the gate and the machinery are in HEAD `d376fad2` (the gate at L12270 there, before the round's edits; the `ast_cannot` computation at L11976), and the CSEL round's diff in `arm64_proof_gen.py` is only the seven step-table hunks (`_STEP_CONDS`, `_step_rhs`, `_step_rhs_generic`, `_regs_written` ×2, `_WORK_STEP`) — none touches the emission path. The x86-64 generator emits no concrete instances at all (`eval_eq_mojo_` appears in that file only in its section builder's name and call), so this is the arm64 path's own gap.

## 4. The exact next step (one round)

1. `formal/arm64_proof_gen.py` L12300: the gate becomes
   `if (not is_typed) and not ast_cannot and _always_returns(fn.body) and not _has_while(fn.body):`
   (`ast_cannot` is L12006, already in scope); and the docstring at L3277–3286 counts the fourth decision instead of three.
2. Regenerate the ternary: the `eval_eq_mojo_N` theorems are gone (zero `ast` references; the omission note above them stays, as it does today — the `eval_eq_mojo_section` branch already respects the predicate). The check is expected fully green — f3 already proves the rest of the file checks.
3. Re-check f3 under the 12 GB slot: ok=True with the single intended admission is the expected census.
4. f4 is out of scope here: it is the certificate doc's walled leaf, and this doc's measurement of it is the wall, which is recorded in §3.
5. Delete this doc in the same commit, per CLAUDE.md, and run `python3 tools/dangling_doc_refs.py --ratchet`.

## 5. What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 12 --label csel-f3 -- python3 -c "from formal.lean import check_proof_cached; print(check_proof_cached('<f3_proof.lean>', repo_root='.'))"
python3 tools/memslot.py --gb 12 --label csel-f4 -- python3 -c "from formal.lean import check_proof_cached; print(check_proof_cached('<f4_proof.lean>', repo_root='.'))"
python3 tools/memslot.py --gb 8 --label ternary -- python3 -c "from formal.lean import check_proof_cached; print(check_proof_cached('<tern_proof.lean>', repo_root='.'))"   # verdict cached from the CSEL round's run
python3 -c "import formal.arm64_proof_gen as G; G.check_step_conds()"   # the CSEL diff does not touch this path
```
