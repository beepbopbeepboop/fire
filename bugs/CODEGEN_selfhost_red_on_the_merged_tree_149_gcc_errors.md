# `selfhost` is red on the merged bug-batch tree: 149 gcc errors, two families, neither marked

## What was run

```sh
python3 tools/suite.py selfhost          # FAIL (490s) / FAIL (495s)
```

measured twice on this tree, `bc17a62b` + the three commits on
`work/bugs4-7`, with the branch's compiler changes reverse-applied in
between so the two runs differ only by them:

| | unique `error:` lines in `build/suite.log` |
|---|---|
| tree WITHOUT `work/bugs4-7`'s compiler changes | 149 |
| tree WITH them | 149 |

The two sets are identical apart from one line number
(`gimple_codegen.py:5530` → `:5535`, because the branch adds five lines
above it). So this is the merged tree's own state, not a regression from
that work — but it is *unmarked*: `selfhost` carries no `expect=` in
`tools/suite.py`, so `make check` and `make gate` are both red on it
today, on a test the registry reports as an ordinary one.

## What was seen

Two families, both "a definition the referencing code needs was never
emitted":

```
gimple_codegen.py:5535:11: error: '_mojo_elem_repr_GimpleGen' undeclared
    (first use in this function); did you mean '_mojo_sizeof_GimpleGen'?
ast_rewriter.py:613:9:  error: '_mojo_elem_repr_TrieNode' undeclared ...
fire_compiler.py:4796:11: error: '_mojo_elem_repr_IdentExpr' undeclared ...
build_config.py:151:30: error: 'struct _build_config_toplev' has no member named 'TEST_PATH'
build_stdlib_dylib.py:355:36: error: 'struct _build_stdlib_dylib_toplev' has no member named 'STDLIB_PATH'
mojo/backend_gimple/emit_funcs.py:410:50: error: 'struct _mojo_backend_gimple_emit_funcs_toplev' has no member named '_module_loader'
```

The `did you mean '_mojo_sizeof_X'` hint is the informative part: the
`_mojo_sizeof_*` accessor for the same struct IS in the unit. So the
per-TU "already emitted this" machinery is running for one helper and not
for the other — `_mojo_elem_repr_<Sn>` is emitted from
`module_gen.py`'s reflect block (`elem_repr_fwd_decls` /
`refl_parts`), whose guard is `_emitted_structs`, while `_mojo_sizeof_<Sn>`
goes through `_c_helper_def`'s separate `_emitted_c_helpers` set.

## Root-cause lead (not worked through)

Both families are the shape `_compile_imported_module`'s rollback exists
to prevent, and the leading candidate is the one registry its handler
deliberately does NOT roll back:

```python
# Note: _module_globals / _module_global_inits are intentionally NOT
# rolled back. Partial data from a failed compilation (e.g. build_stdlib_dylib
# failing but having populated its globals) is still needed so that the
# module's globals struct typedef can be emitted for callers that reference it.
```

`emit_resolve.py`, in the `except` handler. That decision explains the
`has no member named 'TEST_PATH'` / `'STDLIB_PATH'` / `'_module_loader'`
half exactly: a subtree that raised leaves a PARTIAL globals entry behind,
the root emits the struct from it, and the member the module's own
surviving code reads was never registered. `bugs/
COMPILE_FAIL_Tools_c-analyzer_c_parser_parser___init__.md` records the
mirror-image consequence of the same decision (a globals struct emitted and
called for a module whose body was discarded).

The `_mojo_elem_repr_*` half is the same failure wearing a different
guard: `work/bugs4-7` extended that rollback to seven more per-TU
registries (commit `d0350892`, `_str_pool_declared`, `_emitted_c_helpers`,
`_regex_progs_defined`, `_emitted_list_marshalling`, `_emitted_singletons`,
`_emitted_unresolved_stub_syms`, `_auto_stubbed`) and the error count did
not move at all here — so the reflect block's own guard (`_emitted_structs`,
already rolled back) is evidently not where its name is lost.

## Next step

1. Establish the floor first, because it decides everything else: find a
   MINIMAL closure that reproduces one `_mojo_elem_repr_X` undeclared (a
   three-module program where one submodule raises and a survivor holds a
   `list[X]`/`X` value), so the mechanism is observable without a 490 s
   run. `test_gimple_runner.py`'s
   `failed_submodule_rollback_string_pool_marks` is the shape to extend —
   it already builds a failing-submodule closure and asserts on the
   generated C.
2. Then bisect which guard loses the name, with the two candidates above
   (`_module_globals` partial data vs the reflect block's own emission
   condition) as the starting pair.
3. Only after that: whether `_module_globals` really can be rolled back, or
   needs a "complete this entry or drop it" rule instead — its comment's
   `build_stdlib_dylib` justification is a real one and a plain rollback
   would give it back.
4. `selfhost` will need `expect=` or `disabled=` either way until this
   lands; the doc's own gate-consequence note (the analogous link-time
   family takes out seven registered tests through `deps`) suggests
   checking which of those seven are currently red for this reason rather
   than than for `CODEGEN_module_toplevel_undefined_in_selfhost.md`'s.
