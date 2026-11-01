# Gate job `gimplerunner` is red: gimple runner: compiled programs disagree with expected output

## Status 2026-11-01 — one red left; its fix is the open receiver feature

Measured on branch `work/bug-codegen-gate-gimplerunner-red-3491` (behind master;
master carries more work): `python3 test_gimple_runner.py` (under
`tools/memslot.py --gb 8`, ~7 min) gives `507 passed, 1 failed`. The one failure:

    FAIL  gimple_ctor_param_polymorphic_slot_reads_receiver: expected stdout '2\n2\n', got '4344500992\n4344500656\n'

Six reds were fixed earlier (2026-10-30; see git history for `9bcc2c997`,
`8cda11b64`, `a98f133ed`). The remaining case is the polymorphic-method-receiver
gap, whose plan is `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`.
Its claim (`bug:CODEGEN_unresolved_method_receiver_returns_its_own_pointer`) is
no longer in `control.py claims` as of 2026-11-01, so the area is free to take.

Nothing of that plan has landed. Steps 1–5 in that doc (constructor observation
in `mojo/backend_gimple/module_gen.py` around the `_ctor_round` fixpoint, the
`_poly_slot_cands` record, `_mojo_poly_<m>` generation beside
`_emit_reflection_dispatch`, the `_lower_struct_method_call` dispatch in
`emit_methods.py`, and the AttributeError fallthrough) are the next step.

## Next step

1. Implement the receiver plan in `bugs/CODEGEN_unresolved_method_receiver_returns_its_own_pointer.md`.
   `gimple_ctor_param_polymorphic_slot_reads_receiver` is the test; it must print `2`/`2`.
2. Then delete this doc in the same commit and run
   `python3 tools/dangling_doc_refs.py --ratchet`.
