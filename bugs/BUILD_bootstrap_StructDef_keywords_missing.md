# BUILD_bootstrap_StructDef_keywords_missing

## Summary
Self-build of fire (manual gcc bootstrap via `--dump-full`) failed with:
```
fire_compiler.py:5024:8: error: 'StructDef' has no member named 'keywords'
```

## Root cause
`StructDef` dataclass gained a `keywords` field (commit 49f807b48, for PEP 728 TypedDict extra_items),
but the hardcoded field map in `mojo/backend_gimple/module_gen.py` (~line 6308) that seeds
`struct_field_types['StructDef']` was not updated. Fire's codegen relies on this hardcoded map
(rather than scanning the dataclass definition) for core AST nodes, so the generated C struct
omitted `keywords`, while the constructor call passed `keywords=class_keywords`.

## Fix
Added `'keywords': 'MojoList *'` to the hardcoded StructDef field map.

## Files
- mojo/backend_gimple/module_gen.py

## Status
Fixed.