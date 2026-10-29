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

## Status (2026-10-29, planning round: per-execution semantics)

Measured on this branch (`python3 tools/memslot.py --gb 8 -- python3
.tmp/measure_classattr.py`, which compiles and runs):

```python
def make(version: int):
    class Tag():
        __version__ = version
    return Tag()

def main():
    a = make(5)
    b = make(7)
    print(a.__version__)
    print(b.__version__)
    print(make(9).__version__)
    print(a.__version__)
```

Got `7 7 9 9`, exit 0. CPython gives `5 7 9 5`. This is still a silent wrong
answer. The single-call case (`tag(5)`, `tag(7)` in
`test_nested_class_attr_reads_enclosing_local_regression`) is correct.

The instance read `a.__version__` resolves to the `_classattr_Tag__version__`
GLOBAL (it printed the latest call's value, not the value seeded when `a` was
built), so the instance path is not reading a per-instance copy today.

Decision, with the readings:

- **Reading A: refuse.** Cannot be narrowed statically: any function may be
  called twice, and `return Tag()` escapes an instance whose attribute is then
  read after a later call. Refusing every function-hoisted class with a
  non-literal class attribute would also revoke the working single-call fix
  landed above. Honest, but it trades a silent error for a regression.
- **Reading B (recommended): per-instance seeding for function-hoisted
  classes.** Each instance carries its own copy of the non-literal class
  attribute, seeded at allocation from the execution that built it.

Plan for B, exact sites:

1. Find the instance-typed MemberExpr read path (where a struct-typed value's
   `.attr` lowers). It is NOT the bare-type-name path at
   `mojo/backend_gimple/emit_exprs.py` ~1818 (`ClassName.attr`) nor the `cls.`
   path at ~1473. Confirm it targets the `_classattr_` global; that is the
   measured behaviour above.
2. For a class whose name was hoisted out of a function (the
   `_gmi_nested_struct_defs` set, `mojo/middle/exprtypes.py`), seed the field
   at allocation in the `_alloc_<Cls>` emitter, `mojo/backend_gimple/module_gen.py`
   ~14878 (the `class_attrs` loop). The value is the one the class statement
   just stored (`_gen_stmt_StructDef`), which is the construction-time value in
   the common case (`return Tag()` in the same call).
3. Make the instance-typed read go to the instance field for those classes.

Residuals that B does NOT fix, to be written down rather than hidden:

- `Tag.__version__` on the CLASS object still reads the last execution's
  value.
- A class object returned out of its function and constructed in a LATER call
  still seeds from that later global. Closing this needs a per-execution class
  object as a runtime value: a separate, larger project. Until then, refuse it
  the way `mojo/middle/coro.py` `_nested_class_nonliteral_attr` refuses
  generators, keyed on the class name escaping the function (returned or
  stored).

Check before implementing B: a rebound class attribute on an existing instance
(`Tag.__version__ = 3` after `t = Tag()`, then `t.__version__`) must keep
Python's answer (3). Module-scope classes already seed per-instance
(`module_gen.py` ~14878), so first confirm what THEIR read path does and make
hoisted classes match it, not diverge from it.

Tests (land each with its fix, never red on the tree):

- `test_gimple_runner.py`: a new case beside
  `test_nested_class_attr_reads_enclosing_local_regression` using the program
  above, expected `"5\n7\n9\n5\n"`. Currently fails with `7 7 9 9`.
- The existing single-call regression must keep passing (`5\n7\n`).
- A rebound-after-construction case pinning the module-scope answer.

Generator path: unchanged. `_nested_class_nonliteral_attr` still refuses it
(`nested_class_local_attr_refused` in `test_gimple_generator_runner.py`).
Lifting that refusal needs the same store in the stack-switch body, after B.

See also `CODEGEN_nested_class_method_cannot_reach_an_enclosing_local.md`: the
same family (a nested class cannot see the enclosing function's locals).
