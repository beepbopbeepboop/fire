# GIR selfhost: an importer's extern return type is the scanned `int64_t` default

Part of the whole-closure self-host failure (`python3 test_selfhost.py`, gcc over the one
closure translation unit). See `doc/GIR.md`, section "Selfhost closure: remaining errors".

## Symptom

A function defined in one closure module and called from another gets an extern prototype in
the importer that says `int64_t`, while the definer emits `char *`, `MojoList *`, `MojoDict *`,
and so on. gcc then reports:

- `conflicting types for 'mojo_middle_<module>__<name>_<hash>'` (30 on master before the WIP,
  `selfhost_base.out` at `8f244354d`). The hash suffix is the same on both sides; only the
  return type differs.
- Call-site temporaries in the importer typed `int64_t` from the same default, then assigned
  a pointer: `assignment to 'int64_t' from 'MojoList *' / 'char *' / 'MojoDict *' makes integer
  from pointer without a cast` (2 + 3 + 0 before the WIP; 22 + 11 + 4 with it).
- `cannot convert to a pointer type` at `mojo/middle/infra_infer.py:3828-3829`
  (`_pb_names, _pb_dbl = ...` unpacks an `int64_t` extern for
  `resolve_shared._body_pybox_locals`, which the set union then boxes as a double).

## Root cause

An unannotated `def` gets `c_return_type` = `int64_t` from the export scan
(`module_loader` export table). The measured return (what the definer actually emits) is only
recorded when the definer is compiled, and the importer's preamble and call-site temporaries
are written before that. Three extern emitters each apply a partial version of "measured beats
default":

- `mojo/backend_gimple/module_gen.py` (`/* from <module> */` externs, ~line 12106),
- `mojo/backend_gimple/emit_infra.py` (import-extern prototypes, ~line 1666),
- `mojo/middle/funcs_shared.py` (`_resolved_export_entry`, `register_imported_symbol`), and
  `emit_funcs.py` (~line 520).

`func_return_types` is seeded from the same default, so call-site temporaries inherit it even
after the prototype is corrected.

Detection must go through the defining `FunctionDef`: the export scan's `return_type` is
`'int'` both for an absent annotation and for a literal `-> int`.

## State on master

- `e9e4ea4a9` (merged as `913aa3780`) is a WIP, RED commit: a placeholder
  `MOJO_EXTERN_RET_<n>_` is written for an importer's extern return type and resolved after the
  outermost `gen_module` completes. It removes the `conflicting types` errors and introduces the
  pointer-conversion errors above. The net selfhost error count goes UP on this commit.
- Files touched: `gimple_codegen.py`, `mojo/backend_gimple/emit_funcs.py`,
  `mojo/backend_gimple/emit_infra.py`, `mojo/backend_gimple/module_gen.py`.

## What is left (the fix)

1. A pre-pass, before any importer's preamble or call is generated, that records each closure
   definer's committed return type (`ctype` of the definer's own emitted signature), keyed by
   the same qualified/bare name the importer uses. It belongs next to the existing published
   registry (`funcs_shared._PUBLISHED_DEF_PTS`, `publish_definer_committed_pts`).
2. Every `/* from */` extern, import-extern prototype, `func_return_types` seed, and call-site
   temporary reads that one answer. Drop the placeholder mechanism and the three partial copies.
3. Check: a function whose annotated return is `char *` returns `char *` at its call sites in
   other modules, not `int64_t`.
4. `infra_infer.py:3828-3829` unpacks a real tuple return; with 1-3 it should be typed from the
   definer.

## Tests and checks

- `test_selfhost.py`: `conflicting types for` = 0 AND `makes integer from pointer` +
  `cannot convert to a pointer type` = 0 relative to master before the WIP (`selfhost_base.out`).
- `python3 test_gimple_lint.py`, `python3 test_type_string_ratchet.py`,
  `python3 test_gir_builder.py`: pass.
- `python3 tools/c_oracle.py check --base <pre-WIP sha>`: identical C on the pydiff and coroutine
  corpora, except where a corpus program had a default return type that the fix now types
  correctly (report each one).
- `python3 compile_stdlib.py`: `FAILED: 0`, no new skips.

## Status

- 2026-11-24: diagnosed (confirmed on the generated closure `.ci`), WIP committed red as
  `e9e4ea4a9` and merged to master by request. Not fixed.
- Next step: the pre-pass above. Start from `e9e4ea4a9` and remove its placeholder machinery as
  part of that change.
