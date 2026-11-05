# plan/step-12: a `strlen` in the proof model

**Source:** `bugs/FORMAL_string_value_model.md` ("The proving arm64 build cannot
prove `len` or any string method").
**Master plan:** `doc/finish-formal.md` §"Step 12".

## Goal

The model can state a string's value (it is a `char *`, wave 7), but it has no
`strlen`, so `len(s) == 5` is unprovable. The doc is explicit that this is not
fixable by a lemma: it closes when the model gains a `strlen`.

## What to add

- A model of a string's length in the semantic model / AST bridge, reading the
  string's bytes from the image's interned text (the intern table already rides
  on `_Scope` as `info["str_addrs"]`).
- Replace the `_call_go` refusal for `len` where the model can now answer, or
  keep it with an updated reason where it cannot (a run-time string whose bytes
  are not in the image).
- The post-extern theorem suppression the doc prescribes where the callee leaves
  the image: a returning callee returns in `x0`, so no "every register as it
  found it" hypothesis supports the conclusion. Suppress on the same
  `_call_boundary` condition the concrete-run test already uses.

## Structure-only rule

State `strlen`'s contract with `sorry`. The win is that the *refusal* becomes an
*answerable obligation*, not that the proof is finished. Do not add a `sorry`
over a false statement (step-01's rule).

## Files

`formal/arm64_proof_gen.py`, `formal/x86_64_proof_gen.py`, `lib/ProofLib.lean`,
`test_formal_call_proof_gen.py`, ledger.

## Verification

`test_formal_call_proof_gen.py::TestStringValueInTheModel`;
`printf("hi")` still proves; `test_formal_proof_gaps.py`.

## Done when

- [ ] `len(<literal string>)` generates a statement about the literal's character
      count
- [ ] the false `printf("hi")` shape stays fixed
- [ ] any remaining `len` refusal names a run-time (non-image) string
- [ ] holes counted

## Dependencies

step-01; step-11 for run-time strings.
