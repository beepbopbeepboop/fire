# PARSER: nested tuple unpacking in comptime assignment (`comptime a, (b, c) = ...`)

## Symptom
Comptime assignment with nested tuple unpacking on the left-hand side fails to parse: "Unexpected COMMA(',')".

## Repro
```mojo
comptime a, (b, c) = 1, (2, 3)
```

## Affected files
- mojo/test/mojo-integration/alias_unpack.mojo

## Notes
- Need parser support for nested tuple patterns in comptime assignment targets.
EOF