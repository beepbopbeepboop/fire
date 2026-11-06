# PARSER: no support for `^` in closure capture lists (`{var^}`)

## Symptom
Modular Mojo's unified closure capture syntax uses `^` to denote a captured variable (e.g. `def copyMem() {var^}:`). Our parser fails with "Unexpected OP('^') in capture list".

## Affected files
- mojo/test/mojo-integration/unified_closures_mem.mojo
- mojo/test/mojo-integration/max_license/unified_closures.mojo

## Notes
- Need parser support for `^` in capture lists. Likely a new capture-mode token.
EOF