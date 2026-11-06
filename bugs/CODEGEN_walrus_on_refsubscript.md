# CODEGEN: walrus operator on RefSubscript / RLValue targets

## Symptom
Walrus assignment to a subscript target without `__setitem__` (a memory location / RefSubscript / RLValue) is not handled. Error: "incompatible types when assigning to type 'RefSubscript' from type 'int'".

## Affected files
- mojo/test/mojo-integration/walrus.mojo

## Notes
- Need codegen support for walrus on RLValue/memory-location targets.
EOF