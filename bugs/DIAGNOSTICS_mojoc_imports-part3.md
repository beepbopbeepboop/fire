# DIAGNOSTICS mojoc imports: dual-mount import resolves to one package (part 3)

## Goal

Ensure one `.mojoc` artifact reached under two names (e.g. via a symlink/duplicate mount) is treated as one package, matching modular's `import_dual_mount_mojoc.mojo` behavior.

## Acceptance

- Importing via both names warns that they name the same package and notes the canonical name used in diagnostics/debug info.
- The import is not rejected as missing or ambiguous due to being reached under two names, and the artifact is not loaded twice.
- A regression test covering this case exists and passes.

## Done when

File: `test_mojoc_dual_mount_import.py`

Command: `python3 test_mojoc_dual_mount_import.py`

This test must pass, demonstrating dual-mount import resolution and warning behavior.
