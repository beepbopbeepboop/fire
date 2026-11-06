# CODEGEN: `inf` undeclared (float constants)

## Symptom
Floating-point `inf` constant is not available; error: "'inf' undeclared".

## Affected files
- mojo/test/mojo-integration/floats.mojo

## Notes
- Need to provide `inf` (and likely `nan`) as builtin float constants.
EOF