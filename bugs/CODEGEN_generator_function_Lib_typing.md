# CODEGEN_generator_function: Lib/typing.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-31 `_DeprecatedGenericAlias`/`_CallableType`/`_PlaceholderType`
errors no longer reproduce. `typing.py`'s own 4 generator sites (lines
1533, 3129, 3132, 3135) do not appear anywhere in the current (~100+
error) output and have no "not eligible" refusal — they appear to
compile cleanly.

**Classification: NOT a generator-codegen-cluster failure anymore.**
By far the dominant pattern (60+ occurrences) is the already-cross-
referenced `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md` (9th confirmed occurrence — `struct _tokenize_toplev`,
`struct _inspect_toplev` — this file has the largest RAW occurrence
count of that pattern seen in this cluster). Also present: the recurring
`stray '\' in program` textwrap.py tokenizer bug (7th occurrence), the
comprehension/`_quick_type`-family "non-trivial conversion" pattern
(lines 1275/1491), and several unrelated-looking errors (`'_TypedDictMeta'
has no member named '__orig_bases__'`, `redefinition of
'_collections_abc__CallableGenericAlias___repr__'`, `passing argument 1
of '..._dir__' from incompatible pointer type` — the same property/
bound-method-access family noted in `ipaddress.py`'s re-diagnosis).

None of this implicates typing.py's own generators. Not investigated
further — out of scope for this generator-codegen cluster.

## Build error

```
error: '_DeprecatedGenericAlias' does not name a type
error: '_CallableType' does not name a type
error: '_PlaceholderType' does not name a type
```

## Fixed errors (this session)
- `Unpack` not declared → fixed (package import scan)

Source file: `/Users/mrs/net/Python-3.14.6/Lib/typing.py`
