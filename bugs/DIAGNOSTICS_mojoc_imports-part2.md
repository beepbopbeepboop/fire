# DIAGNOSTICS mojoc imports, part 2: dual-mount precompiled import resolution

Replanned from `bugs/hard/DIAGNOSTICS_mojoc_imports.md` (umbrella step 10 of
`docs/diagnostics-missing-validation-plan.md`). Covers
`import_dual_mount_mojoc.mojo`.

## Goal

When the same precompiled module (`.mojoc`) is visible through a dual-mount /
multiple-mount situation, importing it must resolve or diagnose according to the
modular test's expectation rather than succeeding silently in the wrong way or
crashing.

## Acceptance

For the modular fixture corresponding to `import_dual_mount_mojoc.mojo`,
compilation/import reproduces the file's expected `error:` line (or other
expected diagnostic outcome stated by that modular test) with a non-zero exit
where an error is expected.

## Done when

File: `test_mojoc_dual_mount_import.py` (repo root)
Command: `python3 test_mojoc_dual_mount_import.py`

This quick test sets up the dual-mount `.mojoc` fixture and asserts the modular
test's expected diagnostic/behavior for the import.
