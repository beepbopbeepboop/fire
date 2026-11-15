# Gate: defaulted-trait-method-conformance-diagnostic is red on master

**Job:** `defaulted-trait-method-conformance-diagnostic`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py defaulted-trait-method-conformance-diagnostic`), then fix the cause. Do not skip or mark the test.

## Status 2026-11-15: root cause identified; the fix is already on master

The job went red because commit `43bd3dcba` ("elaborate: @align is validated
when a generic struct appears in a signature") extended the signature
binding check to the RETURN type, and the trait-bound evidence check
(`elaborate.check_signature_param_bound_evidence`) treated a template
parameter constrained by a function type (`mapFn: fn(Strat.Value) ->
Dest`) as a list of traits to prove conformance against.
`test_positive_override_default` was the red case: its return annotation
`Map[Self, Dest, mapFn]` against the method's own `mapFn: fn(Self.Value)
-> Dest` is a valid declaration, but the two spellings differ, the
membership test fails, and the check reports `error: invalid bindings in
signature: lacking evidence`.

The false positive is fixed on master by `785c1cf2e` ("gate-mojoc: fix
false 'lacking evidence' in the signature-bound evidence check", landed
as `22e2c014e`): the evidence check skips non-trait bounds, strips
declared defaults from the fn-side bound text, and gates the unproven
verdict on a trait the module can decide. Measured: the job's file fails
at `43bd3dcba` (and at `1a2a2ff44`, pre-fix) with exactly that diagnostic,
passes at `785c1cf2e` and at the current master, and
`python3 tools/suite.py defaulted-trait-method-conformance-diagnostic` is
green on master. The same root cause is the one `785c1cf2e` documents for
the `gate-mojoc` red (false "lacking evidence" in real stdlib), so both
gate docs close on the same fix.

## Done when

`python3 test_defaulted_trait_method_conformance_diagnostic.py` passes —
all cases, including the red one (`test_positive_override_default`) and
the new minimal pin `test_positive_function_type_bound_bracket_param_in_return`
(a function-type-bound bracket parameter passed as its own same-named bound
in a return annotation; fails pre-fix with `lacking evidence`, passes
after).
