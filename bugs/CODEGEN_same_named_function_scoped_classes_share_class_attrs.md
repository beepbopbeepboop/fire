# CODEGEN: two classes with the same name in different functions share class-attribute reads

## Status (2026-10-29)

Found while fixing `CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero`.
NOT caused by the per-execution cell work: it reproduces with LITERAL class
attributes, which never use a cell.

Repro (compiled path, `test_gimple_runner.compile_mojo_to_gimple_exe`):

```python
def f():
    class T():
        x = 1
    return T.x

def g():
    class T():
        x = 2
    return T.x

def main():
    print(f())
    print(g())
```

Observed: `1` and `1`, exit 0. CPython: `1` and `2`. A silent wrong answer.

Where, by reading (not yet confirmed by a fix):

- `mojo/middle/exprtypes.py` / `module_gen.py` `_gmi_hoist_nested_structs`
  renames the second class `T` to `T__g` (`renamed_to`) and records the rename
  in `self._nested_struct_names`.
- Only the constructor call consults that map (`emit_calls.py` ~3485). A
  class-name attribute read does not: `emit_exprs.py` ~1831 looks up
  `gen._class_attrs.get(module_name)` with the SOURCE name `T`, which resolves
  to the first class's attribute global.

Next step: make the class-name read path (`emit_exprs.py` ~1831, and the
`ClassName.attr` write path in `emit_methods.py` `_resolve_class_attr_write_target`)
resolve through the same rename the constructor uses, keyed by the enclosing
function, then add a regression next to `test_nested_class_attr_cross_execution_regression.py`
with the program above (expected `1\n2\n`). Also check that
`_class_attrs` is keyed by the final (renamed) name, which the per-execution
cell code already relies on.
