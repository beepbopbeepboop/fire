# GATE: give the stage2 AttributeError pin a bucket so it cannot rot (replan part 4 of 4)

## Goal

`test_codegen_module_alias_function_value.py` is the named quick pin for
`bugs/hard/CODEGEN_selfhost_stage2_attributeerror_comptimevar_node.md`: the per-file
(`do_imports=False`) compile's module-alias function VALUE, 18 end-to-end shapes each compared
with CPython. It is currently declared in `test_suite.py`'s `UNREGISTERED` table and no gate
bucket runs it, so a regression in the exact lowering the stage2 dump died on would be caught by
nothing.

Register it as a suite job and remove the `UNREGISTERED` declaration, so the pin runs in the
gate and its anti-rot check (a test that stops being red/being covered is visible) is live.

## Where and what was measured (2026-11-23)

- The file is `test_codegen_module_alias_function_value.py`; run directly it prints
  `PASS: ... (18 shapes)` in 27.8 s at a measured peak of 0.2 GB (memslot label `pin`), so it
  belongs in a cheap class (`tiny`).
- `test_suite.py` (~line 4510) carries it in `UNREGISTERED` with `_STANDALONE_TEST_REASON` and
  a comment saying it "wants a bucket beside `linkmode` when one is next touched".
- `tools/suite.py` has no `test(...)` entry for it, and its `regressions` bucket list does not
  name it. The neighbouring pin `test_module_attr_module_call.py` is registered as
  `reg-module-attr-module-call` (`mem='tiny'`), which is the pattern to follow.

## Acceptance

- `tools/suite.py` registers the file as `reg-module-alias-function-value` with `mem='tiny'`,
  in the `regressions` bucket, with a `desc=` naming this bug doc.
- The `UNREGISTERED` entry for the file is gone.
- `python3 test_suite.py` passes: its estate check requires every test file to be registered or
  declared, and its registry checks require the job to be in a bucket with a memclass.
- `python3 tools/suite.py reg-module-alias-function-value` runs the test and reports it PASSED
  (18 shapes).

## Done when

File: `test_codegen_module_alias_function_value.py` (existing; this part only gives it a gate
home).

Command:

    python3 tools/suite.py reg-module-alias-function-value

It runs the 18-shape pin through the suite (27.8 s, 0.2 GB measured on HEAD). RED on HEAD only
in the sense that the job does not exist; after this part it is a registered, passing job, and
`python3 test_suite.py` must still pass.
