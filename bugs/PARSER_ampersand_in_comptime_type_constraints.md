# PARSER: no support for `&` in comptime type constraints (`ImplicitlyCopyable & Movable`)

## Symptom
Modular Mojo allows `&` (intersection) in comptime type constraints. Our parser fails with "cannot parse the right-hand side of a `comptime` assignment: 'ImplicitlyCopyable & ...'".

## Affected files
- mojo/test/mojo-integration/unified_closure_structs.mojo

## Notes
- Need parser support for `&` in type expressions.
EOF