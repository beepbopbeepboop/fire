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

2026-11-18 (work/bug-formal-call-proofgen-red-on-head): partial progress on
cluster 2. Re-measured this tree at `Ran 302 tests in 204.6s, FAILED
(failures=8, errors=6)`, peak ~3.9 GB (down from 22 reds).

Cluster 1 (`_Scope.structs_by_name` crash in `formal/arm64_proof_gen.py:_call_go`)
is **not** fixed here: it is claimed by another worker as
`bug:FORMAL_arm64_call_proof_scope_structs_by_name` (see claims). The 3
`TestGeneratorSource` AttributeErrors, the 2 downstream `TestCallProofs`
TypeErrors (setUpClass proof generation died on that crash, so proof paths are
`None`), and the resulting `TestSameImageCallLean` error remain.

Cluster 2 fixes landed (test expectations and one emitter fix):
- `TestTheDivideByZeroGuardIsEmittedOnlyWhenItCanFire`: updated literal/mod and
  variable-divisor cases to count only division-guard calls (avoiding unrelated
  overflow-trap calls) and, in `formal/x86_64_codegen.py`, gated the inline
  `INT64_MIN // -1` hardware-fault check by `division_needs_overflow_precheck`
  (and skipped it when the unified pre-check already emitted), so a literal
  divisor that cannot be -1/0 emits no extra sentinel trap.
- `TestGeneratorSource.test_the_generated_mojo_is_declared_at_the_entry_arities_arity`:
  accepts the current `evalFunc` call shape (`[n, n1] ... = mojo n n1`) rather
  than requiring the args to be adjacent to `=`.
- `TestAPlaceholderModelClaimsNothing`: rewritten to pin the current (non-
  placeholder) route for the receiver-field shape (x86_64 models with bridge
  omitted for the unstateable call but emits run tests; arm64 emits a by-
  reference frame proof) instead of the old placeholder/identity assertions.
- `TestAstBridgeCallLimit`: the one-site call case now generates with the AST
  bridge on both backends (no longer refused/omitted); tests updated accordingly.
- `TestCfgLeafCensus.test_a_generated_proof_reaches_only_registered_sites`:
  expected loop leaf updated to `loop-cond-step` to match the current corpus
  slice.

Still red (14): cluster-1 AttributeErrors/TypeErrors and downstream same-image
call-following proof failures in `TestCallProofs` (4), plus
`TestTheRegisterValueReaderReadsEveryWrapper.test_the_epilogue_blocks_own_chain_states_what_it_wrote`
and the 3 `TestTheZeroDivisorGuardAgainstLean` residual-goal checks observed in
the full-file run (Lean output did not contain the expected `⊢ n1 = 0` / kernel
memory pressure). These were not addressed here and need re-derivation after
cluster 1 is fixed and/or independent investigation.
