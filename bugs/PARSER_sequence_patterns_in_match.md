# PARSER: pattern matching syntax (`case [a, b]`, `case (a, b)`)

## Symptom
Sequence patterns in match statements (`case [a, b]:`, `case (a, b):`, `case [a, *rest]:`) fail to parse: "a `case` pattern is a SEQUENCE PATTERN ... which decomposes the subject".

## Affected files
- mojo/test/mojo-parser/statements/match.mojo
- mojo/test/mojo-parser/statements/match_diags.mojo
- mojo/test/mojo-integration/pattern_matching.mojo

## Notes
- Need parser support for sequence patterns in match.
EOF