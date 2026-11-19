# FORMAL: `test_formal_eval_eq_mojo_bridge.py` is red on head (5 failures)

`test_formal_eval_eq_mojo_bridge.py` is not registered in `tools/suite.py`, so
this is not a gate red — it is a standalone test file whose last recorded state
is unknown. Measured 2026-11-18 in `work-7647`, with `lib/ProofLib.olean`
built:

    python3 tools/memslot.py --gb 8 --label bridge -- python3 test_formal_eval_eq_mojo_bridge.py

Result: `Ran 32 tests in 539.8s`, `FAILED (failures=5)`, peak 6.1 GB, exit 1.
The failures were confirmed not to be caused by the work that touched
`formal/arm64_proof_gen.py` in the same tree: three of them are assertions on
`lib/ProofLib.lean` or on generated text that the change does not emit, and the
two Lean ones are a program (`bigbody`) with no calls at all.

## Status 2026-11-19 (`work-7663`): four of the five are fixed; `bigbody`'s
## kernel-memory wall is the machine half, not the bridge

Read the sections below as the original report; this entry corrects item 2's
attribution and records what landed.

**Fixed, and each was a real defect rather than a stale expectation:**

* item 1 (both `lib/ProofLib.lean` pins). The library gained the second call
  handler (`evalExpr callFunc callFunc2 …`) after the pins were written, so
  both regexes now include it: `evalExpr`'s `bnot` arm and `evalExpr_unop`'s
  `"bnot"` arm, and the signed-comparison count now matches
  `sKey (evalExpr callFunc callFunc2 l env) …`. The library's arms are right;
  the pins were reading a signature that no longer exists.
* item 3b (`TestTheNestedExprRoutes`' recursor fixture). Besides the `env`
  typing (`Nat` where the hypothesis applies it to a name), the fixture never
  declared `ev`/`evArgs` at all, so `E.rec` was being applied to unknown
  identifiers; and its list motive stated the fold at the accumulator `1`, which
  the `cons` case cannot use. The fixture is now self-contained (it reuses
  `MUTUAL_DEFS`), the environment is `String -> Nat` as `MojoEnv` is, and the
  list motive is `∀ acc, …`. `RECURSE_ROUTE` elaborates and the three routes
  typecheck.
* item 3a (`[n] = mojo n`). The emitted site now carries the arity-2 handler
  too, so the needle is `[n] ((fun name arg0 arg1 => 0)) = mojo n` — the
  argument list AND the handler, not a substring that would also match the old
  text.
* item 2's BRIDGE half. The two-phase emission (`by_cases` over half the
  conditions, `simp_all`, then the rest) is the failure: the mid-proof
  `simp_all` rewrites a goal whose `mojo`/`_go` are already unfolded but whose
  remaining `if` tests are still open, and the second pass exhausts simp's step
  budget (`simp` failed: maximum number of steps exceeded, 4 goals; measured on
  the isolated `bigbody` bridge with `lib/ProofLib.olean` built). One split and
  one `simp_all` closes the same bridge in one pass, so both generators emit
  that. A Lean-free pin (`test_a_many_condition_bridge_is_split_once`) fails on
  the two-phase text.

**Item 2's remaining half is NOT the universal bridge and NOT the call
bridge.** With the bridge replaced by `sorry`, the generated file still dies at
`(kernel) excessive memory consumption detected`, and the machine half alone
needs more than 7.9 GB at `-M` (the generated-proof budget is 6 144 MB). Three
real charges were found and removed on the way, all in
`formal/arm64_proof_gen.py`, with Lean-free pins in the same test:

* the universal emitter's decode lemmas ran to `len(code)` instead of
  `_exec_code_limit(code)`, emitting 43 lemmas for the interned trap messages
  (332 vs 289). Each is an `rfl` over the WHOLE code list;
* every `…_sr_{i}` re-derived its word with `native_decide` even though the
  file already declares `…_insn_{i}` by `rfl` (289 native compilations and
  289 full `List.getD` walks removed);
* `_step_facts`' closed `UInt32` discriminator and the "`BL` past the slice"
  word read were `native_decide`; they are `decide`/`rfl` now. The `BL` one is
  written once per CFG PATH, so `bigbody`'s 64 paths asked Lean's native
  compiler for the same closed decision 320 times. `native_decide` occurrences
  in the `bigbody` proof: 4 809 → 247.

That cuts the wall but does not close it: the machine proof enumerates all
2^6 paths of the six independent `if`s, and its 1 156 declarations still exceed
the 6 GB generated-proof ceiling on their own. The next step is the one the
earlier `FORMAL_eval_eq_mojo_is_undecidable_over_a_free_n` doc ended at -- a
compositional / contract-shaped machine proof instead of one certificate per
CFG path -- or a justified raise of a generated proof's `-M`, which is an
owner decision (`doc/POLICY_memory_over_4gb.md`). Until then `bigbody` cannot
be the fixture this file checks with `check_proof_cached`, and the named
command below does not exit 0.

## The five, grouped by root cause

1. **`lib/ProofLib.lean` no longer has either spelling the test pins.**
   - `TestBitwiseNotIsNotLogicalNot.test_eval_expr_renders_bnot_as_a_complement`
     wants `| MojoExpr.unop "bnot" operand => evalExpr callFunc operand env ^^^ (0xFFFFFFFFFFFFFFFF : UInt64)`
     in `evalExpr`. The regex matches nothing.
   - `TestBridgeSimpset.test_skey_is_what_evalexpr_compares_with` reports
     `n_signed == 0`: `evalExpr` renders no comparison as `sKey l < sKey r`.
   The two are one question — which `MojoExpr` arm spellings the library has —
   so read `evalExpr` and re-derive BOTH pins from what it actually says now
   (or re-add the arms if they were lost rather than renamed).

2. **`bigbody`'s universal bridge exceeds Lean's simp step budget, then its
   kernel memory ceiling.**
   - `TestBridgeTypechecks.test_bridge_typechecks_with_no_sorries(program='bigbody')`:
     `bigbody_proof.lean:28:104: error: simp failed: maximum number of steps
     exceeded`, then a cascade of
     `(kernel) excessive memory consumption detected` from line 1899 onward.
   `bigbody` has 8 independent `if (n & 2**k)` conditions and no calls, so this
   is the attr/condition-multiplication cost in the universal `eval_eq_mojo`
   the class is about, not the call bridge. Likely the same class as the
   bitops/pc-fact kernel-memory fix (unfolding more than the goal reads); the
   next step is to measure whether `_eval_eq_conds_tactic` splits into more
   `by_cases` than the proof's `simp_all +decide` set can carry.

3. **Two text expectations of the current emission changed.**
   - `TestTheBridgeBindsEveryParameter.test_the_generated_ast_carries_a_name_list_and_the_sites_pass_one`
     wants `[n] = mojo n` in a one-parameter proof; the emitted theorem ends
     `... ((fun name arg0 arg1 => 0)) = mojo n`, so the literal needle no longer
     matches the current (correct) shape.
   - `TestTheNestedExprRoutes.test_the_COMBINED_recursor_takes_a_motive_for_the_LIST_too`
     feeds a `MojoExpr.rec` hypothesis with the wrong argument order:
     `Case.lean:7:31: Function expected at env ... this term has type Nat`.
     That is the TEST's own fixture typing the recursor wrongly, not the library.

## What to do (ordered)

1. Fix the `MojoExpr.rec` fixture first (item 3b): it is the only failure with a
   type error that names the mistake, and a wrong fixture hides the library
   question.
2. Re-derive the two `lib/ProofLib.lean` pins (item 1) from the library text.
3. Re-derive the `[n] = mojo n` needle (item 3a) from the emitted file; do not
   weaken it to a substring that would also pass for the old text.
4. Only then attack item 2, and do it as a measurement (one Lean run per
   variant, `-M 6144`): the question is whether the condition split or the
   emitter's simp set is the cost.

## Done when

    python3 tools/memslot.py --gb 8 --label bridge -- python3 test_formal_eval_eq_mojo_bridge.py

exits 0.
