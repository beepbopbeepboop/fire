# A separate compile of a bare imported `str` global reads `(int64_t)0`

## Status (2026-11-22, work/bug-codegen-imported-str-global-return-i-2): return-type half fixed

The return-type half (a def returning a bare imported `str` global typed
`int64_t`) is fixed with a definer compiled into the same unit
(`do_imports=True`): the def is now `char *` and pinned by
`test_imported_global_stub.py::test_def_returning_imported_str_global_is_char_ptr`.
The fix: the from-import homes are registered before return inference
(`module_gen.py`, `_gmi_scan_imported_global_homes` with
`_gmi_module_bound_names`), and `_quick_type` answers a bare imported name from
its home's registered field C type.

## Remaining (not fixed): the separate-compile shape for an outside-dir definer

Repro, fixture under `build/` (a definer OUTSIDE the compiler's own directory):

    # build/.../k_src.py
    NAME = "s"
    # build/.../d_def.py
    from k_src import NAME
    def f(x):
        return NAME

`gimple_codegen.compile_to_gimple(d_def_src, do_imports=False, ...)` emits:

    int64_t f_9f63a2 (int64_t x)
      _t1 = (int64_t)0;  /* ct param or undeclared: NAME */

Expected: `char *` return and a `k_src__mojo_global_get_NAME` read (the
definer's accessor is `char * k_src__mojo_global_get_NAME (void)`).

Cause: the module_loader export scan that types `NAME = "s"` as `char *` runs
only when the definer's directory is the compiler's `_selfhost_dir`
(`module_loader.py`, `_selfhost_gate`, ~1216). An outside-dir definer exports
nothing, so `_emit_imported_global_accessors` has no entry to write.

Decision for the owner (no code landed):
* A. Widen the gate to any local `.py` sibling the import resolver reaches.
  Each such module gets a text-scan export it did not have. Compare the
  `stdlib-dylib` `skip <module>:` count and `compile_stdlib.py`'s unexpected
  `U` before/after.
* B. Keep the gate closure-only (by design). Every compiler sibling is in the
  gate, and the closure's str globals are already exported
  (216004a13, `test_py_str_literal_global_is_read_through_accessor`).
  Recorded as a known scope limit.

Recommendation: B, unless a real build shows a `str`-global extern from an
outside-dir module.
