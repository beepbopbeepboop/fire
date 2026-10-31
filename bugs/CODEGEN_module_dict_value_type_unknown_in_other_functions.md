# A module-scope dict built empty and filled by subscript stores reads back wrong in any OTHER function

## Status (2026-10-30): OPEN

Same-scope reads are fixed (`_note_global_dict_store` in
`mojo/backend_gimple/emit_stmts.py`, test
`gimple_module_scope_dict_value_type_survives_read`). The remaining gap is a
READ from a function that does not contain the store.

## Repro

    d = {}
    d["a"] = "R"
    def show():
        print(d["a"], len(d))
    def main():
        show()
    main()

compiled `4375529048 1` (a string's address), CPython `R 1`. Same shape with a
float value (`d[(1, 2)] = 9.5`) prints the IEEE-754 bits.

Run with `.tmp/probe.py`-style harness: `compile_mojo_to_gimple_exe` then
`run_executable_stdout` from `test_gimple_runner.py`.

## Root cause

`_reset_func` (`mojo/backend_gimple/emit_infra.py`) seeds
`gen._dict_val_types` per function from `gen._global_dict_val_types`.
That table is filled by Phase 1.7 (`module_gen.py`, `_phase17_infer_global_type`)
only from a DictExpr literal WITH pairs (`d = {"a": 1}`). An empty `d = {}`
gets no entry, and nothing else in the pre-scan reads subscript stores into a
global, so a function that reads `d` cannot know its value type.

The append pre-scan (`_gmi_phase17_collect_appends`, `mojo/middle/module_shared.py`)
is the existing answer for LIST element types, function-independent. The dict
analogue (collect `d[k] = v` value types per module global, feed
`_global_dict_val_types`) does not exist.

## Exact next step

1. In `mojo/middle/module_shared.py` add `_gmi_phase17_collect_dict_stores`,
   a sibling of `_gmi_phase17_collect_appends` that walks the same node kinds
   and records, per bare global name, the joined `_quick_type` of every
   `AssignStmt` whose target is `SubscriptExpr(IdentExpr(name), ...)`.
2. Call it next to the append pass in `module_gen.py` (~line 13005) and set
   `self._global_dict_val_types[name]` only when the name is a
   `MojoDict *` global and has no entry yet, mirroring the list loop.
3. Test: the repro above, plus `show()` reading a `float` value and a bool
   value. Check both against CPython, not a hardcoded string.
4. Run `test_gimple_runner.py` (its own tests) and `test_module_cache.py`;
   this touches Phase 1.7, so the integrator's full gate is owed.
