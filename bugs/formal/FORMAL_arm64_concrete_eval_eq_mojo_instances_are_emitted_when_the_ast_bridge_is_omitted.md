# FORMAL_arm64_concrete_eval_eq_mojo_instances_are_emitted_when_the_ast_bridge_is_omitted: the fourth call site of `_ast_model_cannot_state` never consults the predicate, so five theorems reference an `ast` the file never wrote

**Status, 2026-11-01: discovered in the CSEL round (whose doc, `FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`, carries the pointer in its Status entry). A separate defect — the CSEL diff does not touch this path (§3, last paragraph) — and this doc is its round. The fix is one line, and everything in §3 was measured to prove it.**

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
