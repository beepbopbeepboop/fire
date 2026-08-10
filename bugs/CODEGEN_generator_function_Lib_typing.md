# CODEGEN_generator_function: Lib/typing.py

## Status (re-verified 2026-08-09)

Fresh from-scratch `python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/typing.py` on current master. Classification unchanged: **NOT a
generator-codegen-cluster failure** — typing.py's own 4 generator sites
(lines 1533, 3129, 3132, 3135, all bare `yield <name>` inside
`__iter__`-style methods) produce zero errors and no "not eligible"
refusal.

Two more previously-open patterns from this doc are now confirmed GONE:
- The `module_toplev_struct_never_fully_defined` cluster (`struct
  _tokenize_toplev`/`struct _inspect_toplev`, 9th occurrence as of
  2026-08-06): 0 occurrences in the current build output.
- The `stray '\' in program` textwrap.py tokenizer bug (7th occurrence
  as of 2026-08-06): 0 occurrences in the current build output.

The dominant pattern in the current build (412 of 650 total `error:`
lines) is now `Lib/contextlib.py` — a large cascade, not investigated
here, consistent with the already-tracked, separate
`bugs/COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_
something_not_a_structure_or_union.md` non-scalar-`__aenter__`-return
structural gap. typing.py's own remaining errors (20 lines, all
non-generator) are: `non-register as LHS of unary operation` (171),
`redefinition of 'traceback__Sentinel___repr__'` (424), `assignment to
'_Sentinel *' from 'int64_t'` (430), `passing argument 1 of
'_is_dunder_79c856' makes integer from pointer without a cast` (1300),
`'_CallableGenericAlias' has no member named '__parameters__'`/
`'__module__'` (1348/1353), `conflicting types for
'_collections_abc__CallableGenericAlias___getitem__'` (1371),
`redefinition of '_collections_abc__CallableGenericAlias___repr__'`/
`___reduce__` (1536/1624), and `'_TypedDictMeta' has no member named
'__orig_bases__'` (3357, unchanged from 2026-08-07). None of these
implicate typing.py's own generators — still out of scope for this
generator-codegen cluster; no code change made here.

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
