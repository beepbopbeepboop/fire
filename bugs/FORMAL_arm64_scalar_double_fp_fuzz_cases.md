# FORMAL: the scalar-double FP class has a model and an `as` check but no fuzz case

Part of the arm64 instruction census (`tools/formal_isa_census.py`,
`test_formal_isa_census.py`). Class: easy-to-mid -- add the missing fuzz draws,
or record why the harness cannot.

## Symptom

`python3 test_formal_isa_census.py` fails two checks with the same ten rows:

    FAIL  test_every_emitted_form_has_a_model_a_fuzz_case_and_an_as_check
      [('encode_fadd_dd_dn_dm', ['fuzz']), ('encode_fsub_dd_dn_dm', ['fuzz']),
       ('encode_fmul_dd_dn_dm', ['fuzz']), ('encode_fdiv_dd_dn_dm', ['fuzz']),
       ('encode_fneg_dd_dn', ['fuzz']), ('encode_fcmp_dn_dm', ['fuzz']),
       ('encode_fmov_gpr_to_v', ['fuzz']), ('encode_fmov_v_to_gpr', ['fuzz']),
       ('encode_scvtf_dn_xn', ['fuzz']), ('encode_fcvtzs_xn_dn', ['fuzz'])]
    FAIL  test_the_arm64_backend_has_no_unexplained_gap_at_all
      ['encode_fadd_dd_dn_dm', 'encode_fsub_dd_dn_dm', ...]

Every row is missing **only** `fuzz`: each has a Lean model and an `as` check.
`BACKLOG` is empty, so the census has no exemption for them and reports the
gap as unexplained.

## What the class is

The scalar-double forms -- the four arithmetic ops (`fadd`/`fsub`/`fmul`/
`fdiv`, `dd_dn_dm`), `fneg_dd_dn`, `fcmp_dn_dm`, the two GPR<->V moves, and the
two conversions `scvtf_dn_xn` / `fcvtzs_xn_dn`. The model side landed with
`aca4f2bbf` (recorded as "the scalar-double FP class, entries 70-79" in the
since-retired `FORMAL_arm64_instruction_coverage` doc); the fuzz draws did not.

## Done when

`python3 test_formal_isa_census.py` exits 0 -- either because the ten rows have
fuzz coverage, or because `tools/formal_isa_census.py`'s `BACKLOG` names this
doc for exactly those rows (the mechanism's anti-rot requires the entry to keep
matching a row the census still reports missing, so a fixed row must drop its
entry).
