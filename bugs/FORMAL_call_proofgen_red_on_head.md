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
