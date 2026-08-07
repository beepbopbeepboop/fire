# COMPILE_FAIL: Lib/importlib/abc.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/abc.py`

## Status (updated 2026-08-06)

Two issues found. **#1 is now FIXED.** #2 remains, separately tracked.

### 1. FIXED — whole-file self-referential import duplicated every symbol

Originally reported as "~20 `redefinition of 'abc_{ClassName}_{method}'`
errors, tracing to the two multiple-inheritance classes `FileLoader`/
`SourceLoader`". A full (not grepped-and-truncated) error log showed
this was an undercount: EVERY top-level class in the file was affected
equally (`MetaPathFinder`, `PathEntryFinder`, `ResourceLoader`,
`InspectLoader`, `ExecutionLoader`, `FileLoader`, `SourceLoader` — none
of which except the last two even use multiple inheritance), which is
the real signature of "the whole file got compiled twice into the one
flattened translation unit," not an inheritance-merge bug.

Root cause: this file's own `import abc` (an ordinary absolute import of
the real `Lib/abc.py`, for `abc.ABCMeta`) got resolved by
`_compile_imported_module`'s search-path order (importer's own directory
checked before anything that could reach the genuine top-level module)
back to **this same file** — `Lib/importlib/abc.py` also happens to be
named `abc.py`. The whole module was parsed and `gen_module`'d a second
time as if it were a distinct dependency, duplicating every symbol.
Fixed with a path-identity self-import guard
(`GimpleGen._compiling_file_paths`); full root-cause writeup, the
original (wrong) hypothesis, and verification detail moved to
**bugs/hard/CODEGEN_multiple_inheritance_duplicate_method_symbols.md**
(kept at that filename for history/traceability even though the real
cause turned out not to be inheritance-specific).

`python3 mojo.py build Lib/importlib/abc.py 2>&1 | grep error:` went
from ~26 errors (all `redefinition of 'abc_*'`, plus the 2 below) to
exactly the 2 below.

### 2. Dynamic-attribute hard-bug instance (#136, Sub-case C, already tracked) — still open, out of scope for the fix above

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
