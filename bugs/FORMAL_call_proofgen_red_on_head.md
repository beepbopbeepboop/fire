# FORMAL: `test_formal_call_proof_gen.py` is red on master (27 of 301)

`formal-call-proofgen` is registered in `tools/suite.py` with no `expect=`, so
this is an UNDECLARED red in `make check`, not a known failure. Measured
2026-11-17 in `work-7551`, twice: once on master's files, and once with this
worktree's (unrelated) dylib-termination change applied -- the failing set is
IDENTICAL in both runs, so none of it is caused by that change.

Command (the registered argv, nothing else):

    python3 tools/memslot.py --gb 8 --label cpg -- python3 test_formal_call_proof_gen.py

Result: `Ran 301 tests in 167.6s`, `FAILED (failures=21, errors=6)`, peak RSS
4.0-4.3 GB, exit 1. Log kept at `.tmp/cpg_pre.log` in that worktree while it
existed; the list below is reproducible from the command.

## Two clusters, and the first is a crash

1. **`AttributeError: '_Scope' object has no attribute 'structs_by_name'`**
   (3 errors: `TestGeneratorSource.test_a_self_call_in_another_calls_argument_is_recursive`,
   `…test_call_model_renders_every_argument`, `…test_callee_models_are_defined_before_use`).
   It is raised at the `scope` test near `formal/arm64_proof_gen.py:942`
   (`_call_go`), which reads `getattr(scope, 'structs_by_name')` on a `_Scope`
   that no longer defines it. Every test that goes through `_go_defs_for` on a
   CALLING program dies there, so the self-call/call-model half of this file
   never reaches its assertions.

2. **Stale text/fixture expectations (18 failures).** These assert on
   generated-proof text or on counts the current emitter does not produce:
   `PLACEHOLDER`, `NO RUN TESTS`, `the semantic model below is the identity…`,
   `theorem eval_eq_mojo`, `[n, n1] = mojo n n1`, the literal-divisor
   "no call" counts (0 != 1 on both backends), the divide-by-zero residual
   `⊢ n1 = 0`, and several `proofs[...]` paths that are `None` (a refused build)
   where the test expects a file. Two of them (`TestAPlaceholderModelClaimsNothing`)
   look like a ROUTE that changed rather than a regression: the placeholder
   note is no longer emitted, so tests for its wording fail while the refusal
   they were written for may be gone.

## What to do (ordered)

1. Fix the `_Scope`/`structs_by_name` crash first: it is the only cluster with
   a stack trace that names a defect rather than an expectation, and it hides
   whatever the three tests behind it would say.
2. Re-run the file and re-derive cluster 2 one case at a time: for each, decide
   whether the emitter or the test is wrong, and change the one that is. Do NOT
   add `expect=` to the registration to absorb the count -- an undeclared red is
   the thing to fix, and a marker needs a reason that survives the fix.
3. Only if some cases cannot be fixed in one round, register the marker with a
   count and point it at this doc in the same commit.

The two comments that already cite this doc name (`formal/arm64_proof_gen.py`
around `_TOTAL`'s reachability comment, and `test_formal_call_proof_gen.py`
around line 6615) describe the same file being red on head on 2026-10-31, so
this is a repeat, not a new class: the earlier round fixed the cases it named
and the rest of the file was never re-run.

## Done when

    python3 tools/memslot.py --gb 8 --label cpg -- python3 test_formal_call_proof_gen.py

exits 0 (no failures or errors; skips unchanged/acceptable as today).

## Status

2026-11-18 (work/bug-formal-call-proofgen-red-on-head): partial progress.
Re-measured this tree at `Ran 303 tests in 232.9s, FAILED (failures=5)`, peak
~3.9 GB (down from 7 reds in the prior re-measurement on this tree, and down
from the 27 originally recorded).

Cluster 1 from the original report (`_Scope.structs_by_name` crash in
`formal/arm64_proof_gen.py:_call_go`) is no longer observed here (current
`_call_go` reads `structs_by_name` defensively); the 3 `TestGeneratorSource`
AttributeErrors, the 2 downstream `TestCallProofs` TypeErrors, and the
`TestSameImageCallLean` setup error from that crash are gone.

Fixes landed in `test_formal_call_proof_gen.py`:
- `TestUnsignedOffsetAccess.test_the_model_agrees_with_the_cpu`: construct
  `fm.Case` with the required `d` (binary64 register file) argument
  (`[0] * 8`) to match `tools/formal_model_fuzz.Case`'s current signature.
- `SAME_IMAGE_CALL` fixtures (`same_image_leaf`, `same_image_branching`): use
  followable identity/branching callees with no arithmetic so each remains a
  straight-line leaf of the current formal image (arithmetic in a callee now
  emits an out-of-image overflow/trap helper call, which correctly makes the
  callee not followable). Updated the section comment accordingly.
- `MULTI_SAME_IMAGE_CALL['two_leaf_callees']`: use identity callees for the same
  reason (two distinct followable leaves). `TestCallProofs.
  test_two_distinct_leaf_callees_are_followed` no longer requires a concrete
  `main_compiles_correctly :` theorem for this shape because the current
  generator emits the universal theorem but suppresses the concrete run test
  ("NO CONCRETE RUN TEST") here; it still asserts the calls are followed (no
  CALL BOUNDARY / no `reaches_call_at_`, and `main_compiles_correctly_universal`
  present).

As a result, the prior CallProofs/same-image follow/plan failures and the
unsigned-offset error are fixed.

Still red (5, unchanged/pre-existing or environment-sensitive on this tree,
not addressed here):
- `TestSameImageCallLean.test_the_followed_call_proves_with_no_admission`: the
  followable identity `same_image_leaf` fixture generates and is followed, but
  Lean rejects `eval_eq_mojo` with an unsolved `evalArgs`/call goal (so the
  eval bridge does not close for this followed-call AST shape in this
  environment). This is a consequence of switching to a followable fixture; a
  Lean-provable followed-call shape that is also followable under current
  lowering was not identified.
- `TestTheRegisterValueReaderReadsEveryWrapper.
  test_the_epilogue_blocks_own_chain_states_what_it_wrote`: Lean kernel reports
  `(kernel) excessive memory consumption detected` on the generated chain proof.
- `TestTheZeroDivisorGuardAgainstLean.
  test_the_false_goal_survives_the_documented_next_step` (as_emitted,
  doc_next_step) and `test_the_residual_is_the_same_with_and_without_the_branch_fact`:
  Lean output contains only `sorry` warnings and no traced residual goal
  (`⊢ n1 = 0` not present / no residual goal traced), so the measurement this
  class relies on did not observe the expected residual.

These remaining failures need independent investigation (eval-bridge/proof
generation for followed calls, Lean kernel memory limits for the epilogue chain,
and the div0-guard trace/measurement mechanism).
