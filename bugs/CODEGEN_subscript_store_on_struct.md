# CODEGEN: subscript store on user-defined struct without __setitem__

## Symptom
Subscript store on a struct with no `__setitem__` and no backing container field is not supported. Error: "`WeirdArray[...] = ...` subscript store on user-defined struct ... (no `__setitem__` method and no backing container field)".

## Affected files
- modular tests exercising WeirdArray / ExampleRegPassable

## Notes
- Need to support subscript store on structs (either via __setitem__ or backing field).
EOF