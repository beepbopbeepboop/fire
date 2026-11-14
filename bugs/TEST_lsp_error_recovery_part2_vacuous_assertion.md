# TEST_lsp_error_recovery_part2: the registered pin accepts an unrelated error

## Symptom

`test_lsp_error_recovery_part2.py` (registered as `reg-lsp-error-recovery-part2`)
is meant to pin "an unknown declaration is diagnosed while the following
`struct Good` is still emitted". It does not: its source never reaches the
unknown-declaration diagnostic, and its assertion accepts the unrelated error
that is actually raised.

## What was run

```
python3 tools/memslot.py --gb 8 --label lsp-part2 -- python3 test_lsp_error_recovery_part2.py
```

Before the fix in commit 80da6c9e7 (the `@align:` message change), with the
diagnostic still swallowed, this printed:

```
CAUGHT_IN_MAIN_LOOP: cannot compile module: a bracketed call Bad[...]() needs link-mode specialisatio
ok
```

The test passes because its assertion is

```python
assert "use of unknown declaration" in msg or "Bad" in msg
```

and the raised message contains `Bad`, from the *bracketed-call link-mode*
refusal — not from any unknown declaration. The source's `Bad` is a
non-parameterized struct, so `Bad[1]()` cannot be compiled by this build at all;
`@align(missing)` is never evaluated.

## Expected

The registered test should fail if the unknown-declaration diagnostic is
swallowed (that is exactly the state before 80da6c9e7). The part-3 pin landed by
80da6c9e7 (`reg-lsp-error-recovery-part3`, `test_lsp_error_recovery.py`) does
cover that behaviour with a parameterized `struct Bad[T: Int]` and a strict
`"use of unknown declaration 'missing'"` assertion, but this file remains a
green line that says nothing.

## Next step

Make `Bad` parameterized in the test source (`struct Bad[T: Int]:`) so
`@align(missing)` is evaluated at `Bad[1]()`, and replace the `or "Bad" in msg`
escape hatch with the strict assertion:

```python
assert "use of unknown declaration 'missing'" in msg, msg
```

Then it exercises the same path as the part-3 pin and fails if the diagnostic
is swallowed again.
