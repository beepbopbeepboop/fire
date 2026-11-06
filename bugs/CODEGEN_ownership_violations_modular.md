# CODEGEN: ownership violations in modular test files

## Symptom
Ownership violations reported when compiling modular test files. Two files affected.

## Affected files
- mojo/test/mojo-integration/closure_interior_origin_errors.mojo
- mojo/test/mojo-integration/aligned_alloc_on_gpu_error.o (related)

## Notes
- Need to investigate whether these are real ownership bugs or test-specific expectations.
EOF