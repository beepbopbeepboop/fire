# An imported free function's overload suffix is the defining unit's suffix (part 2)

Part 2 of `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md`.
Class: easy. One ctype-table disagreement between the text scan and the real
lowering; no mangling change.

Measured 2026-11-13 on this tree. Compiling both halves of one call standalone
(the per-module `compile_module_to_c` path `build_stdlib_dylib.py` uses):

- `std/collections/string/_parsing_numbers/parsing_floats.mojo` defines
  `def _atof(x: StringSlice) raises -> Float64` and emits
  `double std_collections_string__parsing_numbers_parsing_floats__atof_d719e0 (char * x)`.
- `std/collections/string/string.mojo` calls `_atof(str_slice)` and emits
  `extern double std_collections_string__parsing_numbers_parsing_floats__atof_55072c (int64_t * x);`
  plus the call `..._atof_55072c (...)`.

Same suffix, different hash: the call site's `_effective_param_types` is not
the defining unit's signature, so the two halves of one mangled name disagree
and the dylib ships an undefined `_std_..._atof_55072c`. The parent doc
measured the same shape for the unicode helpers
(`_std_collections_string__unicode_is_lowercase_55072c` vs `..._fa3cf4`, same
for `is_uppercase`/`to_lowercase`/`to_uppercase`, and
`_std_collections_string__utf8__count_utf8_continuation_bytes_55072c`).

Root cause, located: a standalone compile's import registration sees the
source-only text scan (`module_loader.load_module`), whose
`_mojo_type_to_c` maps bare `Span`/`StringSlice` to `int64_t *` — an
opaque-handle boxing chosen because no `Span` typedef exists in the importing
translation unit. The defining unit's real GimpleGen lowering emits `char *`
for the same annotation. The text-scan `c_parameters` (`['int64_t * x']`) feed
`_import_entry_param_types` → `_overload_suffix` hashes `[int64_t *]` →
`_55072c`, while the definition hashed `['char *']` → `_d719e0`. (A
direct import whose text-scan ctype already agrees — e.g. `Int` →
`int64_t` — matches today; this part is about the family whose annotation
the scan boxes differently.)

## Goal

A reference to an imported free function hashes the same parameter list the
definition side hashes, so the caller's emitted extern and call carry exactly
the symbol the defining unit emits — qualifier and suffix.

## Acceptance

- `string.mojo`'s emitted C references `_atof` only with the suffix
  `parsing_floats.mojo`'s own definition carries (the probe compares the full
  symbols; today `..._atof_55072c` vs `..._atof_d719e0`).
- The rest of the parent doc's suffix group (the unicode helpers and
  `count_utf8_continuation_bytes`) clear the same way — same mechanism, same
  fix; they are not pinned by the probe.
- The emitted extern stays C-parseable in the importing TU: the `Span` boxing
  existed because a foreign TU has no `Span` typedef ("unknown type name
  'Span'"), so a fix that returns `Span *` from the scan is not acceptable;
  the defining unit's `char *` needs no typedef.
- No special-casing of `_atof`, `is_lowercase`, or any name; the fix is at the
  annotation-mapping level, and annotations that already agree (`Int`, `Float64`,
  ...) keep their exact mapping.
- The dylib-reflection import path (`read_reflection` / `reflect.py::_c_signature`,
  which reads the real table) is untouched.

## Done when

File: `test_stdlib_dylib_lazy_undefined_refs_probes.py` (repo root).

Command: `python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p2_imported`

It runs `test_p2_imported_suffix_matches_the_defining_unit` (red today:
`string.mojo` references `..._atof_55072c` while the defining unit emits
`..._atof_d719e0`). It must pass.

## Where to start

`module_loader.py::_mojo_type_to_c` — the `Span`/`StringSlice` arm (around
line 1408) that returns `int64_t *`, against the defining unit's real
lowering of the same annotation (`char *` here). Two honest routes, the probe
arbitrates: (a) make the text scan's `c_parameters` agree with the real
lowering for the affected annotation family (keeping the extern parseable —
`char *` is; `Span *` is not), or (b) give `_effective_param_types`
(`mojo/backend_gimple/emit_funcs.py`, tier 4 `_import_entry_param_types`)
the defining unit's real signature when it is reachable. Route (a) fixes the
whole measured family at once. Do not touch `_lower_struct_subscript_dunder`
(part 3) or the home-module registry (part 1).
