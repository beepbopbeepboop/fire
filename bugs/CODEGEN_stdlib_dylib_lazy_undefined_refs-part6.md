# CODEGEN: a bracketed `Span`/`StringSlice` parameter gets a `char *` reference and a `Span *` definition

Parent: `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (its
`## Replan (2026-11-15)` table is the measured state). This is part 6.

## Goal

For an imported free function whose parameter is written with a bracket
(`StringSlice[_]`, `Span[UInt8, _]`), the symbol the caller references must be
the one the defining unit emits. The measured mismatch is:

    caller:  std_collections_string__unicode_is_lowercase_d719e0 (char * s)
    definer: std_collections_string__unicode_is_lowercase_fa3cf4 (Span * s)

and the same for `is_uppercase`, `to_lowercase`, `to_uppercase`,
`_count_utf8_continuation_bytes`, and `std_sys__amdgpu_printf_append_string_n`
(`char * data` vs `Span * data`).

## Evidence (measured 2026-11-15, this tree)

`std/collections/string/string_span.mojo` imports these from
`_unicode.mojo` / `_utf8.mojo`; `std/builtin/debug_assert.mojo` imports
`printf_append_string_n` from `std/sys/_amdgpu.mojo`. Each defining unit's own
compile emits

    _Bool std_collections_string__unicode_is_lowercase_fa3cf4 (Span * s)
    uint64_t std_sys__amdgpu_printf_append_string_n_bdbef0 (uint64_t, Span *, _Bool)

while the caller's text-scan import signature spells `char *` and so derives a
different suffix (`_d719e0`, `_c43adc`).

The cause is `module_loader.py`'s `_imported_type_ctype` (the Span/StringSlice
arm, around lines 1393-1409): it maps the base name `Span`/`StringSlice` to
`char *` unconditionally, on the stated premise that this is "the defining
unit's real lowering". That premise holds for the BARE annotation
(`parsing_floats._atof(x: StringSlice)` really is `char *`), and part 2's fix
depends on it, but a BRACKETED annotation lowers to the `Span` struct pointer.

## Work

1. In `_imported_type_ctype`, split the two forms: a bare `Span` /
   `StringSlice` keeps `char *` (part 2's `_atof` case must stay green); a
   bracketed form returns the defining unit's lowering (`Span *`).
2. Keep the extern parseable in a translation unit that has no local `Span`
   typedef: check how the caller's preamble reaches the `Span` typedef (the
   module preamble GimpleGen seeds) and use the same spelling a real definition
   uses. Do not introduce a third spelling.
3. Do not re-derive the signature from the annotation when the defining unit
   can be asked: `module_loader` already loads the defining module for
   reflection; the production-quality shape is one source of truth for the
   lowered parameter type. The minimal form above is acceptable only if the
   bare/bracketed split is the whole difference.

## Acceptance

- Every reference from `string_span.mojo` to the four `_unicode.mojo` functions
  and `_count_utf8_continuation_bytes` names a symbol `_unicode.mojo` /
  `_utf8.mojo` defines.
- `debug_assert.mojo`'s `printf_append_string_n` reference names the symbol
  `_amdgpu.mojo` defines.
- `parsing_floats.mojo`'s `_atof` reference and definition still agree
  (`..._atof_d719e0`, `char *`), i.e. part 2's probe still passes.

## Done when

`python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p6_bracketed` exits 0.
It compiles those five modules through `compile_module_to_c` (no gcc, no link,
~10 s) and compares each caller symbol with the defining unit's symbol.
