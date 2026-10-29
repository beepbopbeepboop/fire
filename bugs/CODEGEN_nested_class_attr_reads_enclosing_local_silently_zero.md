# CODEGEN: a class-level attribute that reads an enclosing local is silently 0

## Status (2026-10-29)

Found while fixing `CODEGEN_generator_function_Lib_test_test_ensurepip.md`.
The generator form of this is now refused honestly (see that doc). The
PLAIN-FUNCTION form is still silent and is open here.

Repro (`compile_to_gimple_with_cpp(src, do_imports=False)`):

```python
def plain_local(version=5):
    class A():
        __version__ = version
    return A().__version__
```

Observed: the generated C declares `int64_t _classattr_A____version__;` and
reads it (`_t2 = _classattr_A____version__;`) but NEVER assigns it. The
`class` statement lowers to `/* TODO: StructDef */` (emit_stmts.gen_stmt's
"unknown statement dropped" fallback), so the attribute is 0 and the program
exits 0 with the wrong answer. Expected: `5`, the value of `version` at the
moment the `class` statement runs.

Why: `module_gen.py`'s class-attribute registration (`self._class_attrs[
s.name][aname] = mangled`) seeds each `_classattr_` global from the class-body
value at MODULE scope, but a class hoisted out of a function body (the
2026-10-02 hoist, `_gmi_nested_struct_defs` now in `mojo/middle/exprtypes.py`)
has a value that names a function-LOCAL. Nothing evaluates that value at the
point the `class` statement executes.

What it is NOT: a literal (`__version__ = 7`) works, the same in a generator
and in a plain function. Only a non-literal value that reads a local is broken.

Generator bodies are guarded already: `mojo/middle/coro.py`
`_nested_class_nonliteral_attr` refuses a generator whose nested class has a
non-literal class attribute, so the stack-switch path no longer compiles it
silently. The plain-function path has no such guard.

## Status (2026-10-29, partial fix landed)

Landed (plain-function path):

- `mojo/backend_gimple/emit_stmts.py` `_gen_stmt_StructDef` (dispatched from
  `gen_stmt`, delegate in `gimple_codegen.py`): a `class` statement inside a
  function body now stores each registered class attribute with a value into
  its `_classattr_` global, as `ClassName.attr = <value>`, via the existing
  `_resolve_class_attr_write_target` path. The repro now emits
  `_classattr_A____version__ = version;` before the read.
- Regression: `test_gimple_runner.py` `test_nested_class_attr_reads_enclosing_
  local_regression` (two calls, `tag(5)` and `tag(7)`, must print `5` and `7`).
  Before the fix: `got '0\n0\n'`. After: PASS.

Still open (step 3 below, not done):

- Per-execution semantics. Python builds a new class object each time the
  `class` statement runs; here there is one module-global `_classattr_` per
  class, so an instance built by one call and read AFTER a later call of the
  same function sees the later value. The single-call and read-right-after
  cases are correct. Decide: give the class per-call storage, or refuse a
  function-hoisted class whose non-literal attribute can be re-executed.
- The generator path is unchanged: `mojo/middle/coro.py`
  `_nested_class_nonliteral_attr` still refuses it (test
  `nested_class_local_attr_refused` in `test_gimple_generator_runner.py`).
  Lifting that refusal needs the same store in the stack-switch body.

## Next step

Decide the per-execution semantics above (step 3), then either lift the
generator refusal by emitting the same store in the coroutine body, or leave
the refusal as the documented limit for generators.

See also `CODEGEN_nested_class_method_cannot_reach_an_enclosing_local.md`: the
same family (a nested class cannot see the enclosing function's locals).
