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
