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

## Next step (the real fix, not yet started)

Make the `class` statement assign its class-level attributes when it executes,
the way Python does:

1. `mojo/backend_gimple/emit_stmts.py` `gen_stmt`: add a `StructDef` case that,
   for each class-level `AssignStmt`/`VarDecl` field with a non-literal value,
   emits `_classattr_<Struct>__<attr> = <lowered value>;` at that point.
2. `mojo/backend_gimple/module_gen.py` class-attribute registration: keep the
   `_classattr_` global for a function-hoisted class but do NOT seed it from the
   local's (non-existent at module scope) value; seed from the statement.
3. Decide per-execution semantics: Python builds a NEW class object each time the
   `class` statement runs. A single module-global `_classattr_` is shared across
   calls, so two live instances from different calls would alias. Either accept
   and document that for v0 or refuse when the class is executed more than once.
4. Tests, next to `test_gimple_generator_runner.py`'s
   `nested_class_literal_attr_compiles`: a plain-function case returning `5`,
   plus a case calling the function twice with different arguments.

See also `CODEGEN_nested_class_method_cannot_reach_an_enclosing_local.md`: the
same family (a nested class cannot see the enclosing function's locals).
