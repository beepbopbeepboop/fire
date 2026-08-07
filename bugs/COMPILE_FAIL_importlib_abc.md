# COMPILE_FAIL: Lib/importlib/abc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py`

## Status (updated 2026-08-06)

Two issues found, neither fixed.

### 1. Multiple-inheritance duplicate method-symbol emission (~20 errors)

```
error: redefinition of 'abc_FileLoader_get_data'
error: redefinition of 'abc_SourceLoader_get_data'
... (20 total, across FileLoader and SourceLoader)
```

`class FileLoader(_bootstrap_external.FileLoader, ResourceLoader,
ExecutionLoader):` (no methods of its own) and `class SourceLoader(
_bootstrap_external.SourceLoader, ResourceLoader, ExecutionLoader):`
both use multiple inheritance from the same base set, inheriting most of
their methods rather than defining them directly. Not fully root-caused
— leading hypothesis and investigation notes moved to a new hard-bug doc
given the structural scope: **bugs/hard/
CODEGEN_multiple_inheritance_duplicate_method_symbols.md**.

### 2. Dynamic-attribute hard-bug instance (#136, Sub-case C, already tracked)

```
error: expected identifier before '__func__'
```
at:
```python
if self.path_stats.__func__ is SourceLoader.path_stats:
```
`self.path_stats.__func__` — bound-method dunder-attribute access, same
shape as bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
existing Sub-case C examples (`Tools/c-analyzer/c_common/clsutil.py`'s
`__del__._slotted`, `Tools/scripts/var_access_benchmark.py`'s
`f.__name__`). Not a new finding — confirming another real-world
instance.
