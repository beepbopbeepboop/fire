# CODEGEN_generator_function: Lib/typing.py

## Status (updated 2026-08-07)

Two of this doc's previously-open patterns are now FIXED — see
`bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
mismatches.md` for the full writeup:
- The "comprehension/`_quick_type`-family 'non-trivial conversion'
  pattern (lines 1275/1491)" mentioned below was actually
  `_isinstance_one_type`'s `isinstance(x, type)`-always-False stub
  emitting a bare `0` into a `_Bool`-declared temp (`_new_val`'s digit-
  literal auto-cast guard only covered `int64_t`, not `_Bool` — that
  doc's Mechanism 2). Fixed.
- The "`passing argument 1 of '..._dir__' from incompatible pointer
  type`" pattern was `super().method(...)` calls passing `self` typed
  as the DERIVED struct pointer to a BASE class method expecting the
  base struct pointer, with no actual C-level cast ever emitted (that
  doc's Mechanism 3). Fixed — an isolated `typing.py`-only compile went
  from 14 errors (with only Mechanism 2 fixed) to 2 once this landed
  too.
- Still open, untouched: the `module_toplev_struct_never_fully_defined`
  cluster (per that doc's own status — check there for current state),
  the textwrap.py tokenizer bug, `'_TypedDictMeta' has no member named
  '__orig_bases__'`, and one `non-register as LHS of unary operation`
  error (global-struct-field assignment) — none investigated further.

## Status (updated 2026-08-06, PARTIALLY STALE — see above)

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
