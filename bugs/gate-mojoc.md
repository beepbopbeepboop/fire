# Gate: mojoc is red on master

**Job:** `mojoc`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py mojoc`), then fix the cause. Do not skip or mark the test.

## Done when

The root cause was false `error: invalid bindings in signature: lacking evidence`
rejections from the trait-bound evidence check (`elaborate.py`,
`check_signature_param_bound_evidence`), exposed for real code when commit
43bd3dcba extended the signature check to return types. The quick test:

- `python3 test_signature_bound_evidence_diagnostic.py` passes — all cases,
  including the three pre-fix-failing shapes (defaulted bound used in a
  return type, function-type bound, concrete-type constraint bound) and the
  negative control that must stay rejected.
- `python3 test_defaulted_trait_method_conformance_diagnostic.py` passes —
  `test_positive_override_default` was the red test.
- The stdlib-dylib compile runs with zero module fallbacks (`build_stdlib_dylib.py`
  no longer skips `std/simd.mojo`, `std/ffi/__init__.mojo` or
  `std/compile/compile.mojo`); `test_binding_deferral_diagnostic.py` exercises
  that path and stays green.

