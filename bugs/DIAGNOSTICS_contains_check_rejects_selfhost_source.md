# DIAGNOSTICS: the new `__contains__` membership check rejects selfhost source

**Found:** 2026-11-13, running `python3 test_gimple.py` on branch
`work/bug-gate-stdlib-syntax` (base `bc71ee7e1`) for the `gate-stdlib-syntax`
round.

## What was run and what was seen

```
python3 tools/memslot.py --gb 8 --label gate-stdlib-named -- python3 test_gimple.py
Results: 454 passed, 1 failed
FAIL test_handwritten_selfhost_signature_tables_match_the_source (line 12708):
  RuntimeError: 'Int' does not implement the '__contains__' method
```

The log shows `CAUGHT_IN_MAIN_LOOP: 'Int' does not implement the '__contains__' method`
just before the FAIL line. The named stdlib-syntax test
(`gate_stdlib_syntax_float_bit_accessors`) passes.

## Expected

The test compiles the selfhost sources through the gimple lowering. Those
sources are valid Python/Mojo and contain `x in y` where `y` is a container.
The membership check should accept them, or reject only a real scalar
container. It should not raise on a container whose type inference is merely
wrong.

## Likely cause

Commit `03d4302ba` ("Reject membership on provably scalar containers without
__contains__") added the raise at `mojo/backend_gimple/emit_exprs.py:6408`:

    raise RuntimeError(f"'{_scalar_ct}' does not implement the '__contains__' method")

The check decides from the inferred type of `y`. Some container in the selfhost
closure is inferred as `Int`, so a valid `in` is rejected. This is a false
positive from the new check, not a missing `__contains__` in the source.

Not yet established: which `in` expression in the selfhost closure triggers it.
The `CAUGHT_IN_MAIN_LOOP` message does not name the module or line.

## Next step

1. Find the offending expression. Make the lowering report the module and the
   `in` source line in the message (or set a breakpoint on line 6408 and print
   the node), then run the test to see which module it is.
2. Fix the type inference that gives that container type `Int`, or narrow the
   membership check so that the inferred type is trusted only when it is
   certain. Do not special-case the module name.
3. The quick test is `python3 test_gimple.py` and the case
   `test_handwritten_selfhost_signature_tables_match_the_source` must pass.
   `test_contains_method_diagnostic.py` must keep passing, since it pins the
   intended diagnostic.

## Notes

- Not the same as `bugs/mid/CODEGEN_selfhost_sig_table_parse_module_recover.md`,
  which describes an arity mismatch in `_SELFHOST_SIGS` for `parse_module`. That
  failure was the one this test reported before. Its current failure is the
  membership raise above.
- Belongs to the DIAGNOSTICS lane. The claim
  `bug:DIAGNOSTICS_missing_validation_modular-part6` is held by another worker
  (`bug-mid-diagnostics-missing-validation-m-5`), so the owner of
  `emit_exprs.py`'s membership check should take this.
