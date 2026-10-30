# CODEGEN: a class-level attribute that reads an enclosing local is silently 0

## Status (2026-10-29)

Found while fixing `CODEGEN_generator_function_Lib_test_test_ensurepip` (bug:CODEGEN_generator_function_Lib_test_test_ensurepip).
The generator form of this is now refused honestly (the ensurepip doc was deleted with its fix). The
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
- **Reading B: per-instance seeding for function-hoisted classes.** SUPERSEDED
  by the 2026-10-29 round-2 analysis below: a per-instance copy read off the
  instance field fails the rebind-after-construction requirement (a test now
  pins it), so B is not the fix.

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

## Status (2026-10-29, planning round 2: B refuted, per-execution storage)

Measured (`python3 tools/memslot.py --gb 8 -- python3 .tmp/measure_rebind.py`):

- Module-scope class, `t = Tag(); Tag.__version__ = 3; print(t.__version__)`:
  prints `3` (Python: `3`). Instance reads of a class attribute redirect to the
  `_classattr_` global: `mojo/backend_gimple/emit_exprs.py` ~2602, the
  `_lower_MemberExpr` branch `struct_name in class_attrs`. That is why the
  rebind is seen.
- The SAME rebind on a function-hoisted class (`make(version)` builds `t`,
  rebinds `Tag.__version__ = 3`, returns `t`): prints `3`. Correct today.

So plan B, which reads the instance field, would print `5` here and break a
working answer. B is withdrawn. The bug is only the cross-execution case
(`a = make(5); b = make(7); a.__version__` gives `7`, Python `5`).

Pinned now: `test_gimple_runner.py`
`test_nested_class_attr_rebind_after_construction_regression` (passes on this
tree; a per-instance design must keep it green).

Decision: **Reading C, per-execution attribute storage.** Each execution of a
function-hoisted class's `class` statement creates its own attribute block;
instances and the class name both reach the block of the execution they belong
to. This is the only shape that gives the 5/7/9/5 answer and keeps the rebind
answer, because rebinding writes the shared block that the instance also reads.

Implementation guide, in order:

1. Block type and storage. For each class in `_gmi_nested_struct_defs` with at
   least one non-literal class attribute (`module_gen.py` ~5899 registration),
   emit a struct `_cattrs_<Cls>` with one field per such attribute, plus a
   current-block global `_classattr_<Cls>__block` (`void *`, or typed
   `_cattrs_<Cls> *`). Declare both where the `_classattr_` globals are
   declared (`module_gen.py`, the `_global_var_types` registration near
   5899-5976).
2. Per-execution allocation. `_gen_stmt_StructDef` (`emit_stmts.py` ~3138):
   before the stores it currently emits, `calloc` a fresh
   `_cattrs_<Cls>` and assign it to `_classattr_<Cls>__block`; then store
   each value into `block->attr` (not the global). Heap is deliberate: the
   block outlives the frame, and the leak is the same class as
   `CODEGEN_closure_env_and_boxed_local_never_freed.md`.
3. Instance hidden pointer. The hoisted struct gets a `_cls_block` field
   (`struct_field_types`, `module_gen.py` ~5840s). `_alloc_<Cls>` /
   `_init_<Cls>` (`module_gen.py` ~15012-15060, `attr_inits`) seeds
   `_p->_cls_block = _classattr_<Cls>__block` (the execution building it).
4. Instance reads. `emit_exprs.py` ~2602: for a hoisted class, read
   `obj->_cls_block-><attr>` instead of the global. Module-scope classes keep
   the global unchanged.
5. Class-name reads and writes. `Tag.attr` (`emit_exprs.py` ~1824,
   `emit_methods.py` `_resolve_class_attr_write_target` ~183, and the
   `emit_stmts.py` write sites ~1768/2439) resolve to
   `_classattr_<Cls>__block-><attr>`: the most recent execution, which is the
   right answer while the class name is in scope.
6. C++ readers. `cpp_core.py` ~660/1963/3132 and `cpp_async.py` ~873 still
   read the global. They are on the legacy path; confirm whether they can
   reach a hoisted class before routing them. Generators stay refused
   (`coro.py` `_nested_class_nonliteral_attr`), so no stack-switch store is
   needed for this round.

Tests, in the order they land (each must be green when it lands):

- `test_nested_class_attr_rebind_after_construction_regression` (landed now).
- `test_nested_class_attr_reads_enclosing_local_regression` (landed earlier,
  `5\n7\n`, must stay green).
- New: the four-call program `make(5)`, `make(7)`, `make(9).__version__`, then
  `a.__version__`, expected `5\n7\n9\n5\n`. Currently prints `7 7 9 9`; lands
  with step 4.
- Residual, not fixed by C and to be written down, not hidden: a class object
  that escapes its function (`return Tag`) and is used in a LATER call reads
  that later call's block. Closing it needs the class object itself as a
  runtime value. Until then refuse the escape the way
  `coro.py` `_nested_class_nonliteral_attr` refuses generators, keyed on the
  class name being returned or stored.

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

## Status (2026-10-29, planning round 3: Reading C sites measured)

Re-measured on this branch. The four-call program still prints `7 7 9 9`
(Python `5 7 9 5`). Test is NOT committed: it is red and the rule is that a
test lands with its fix. The exact test is kept at
re-create it from the program below when the fix lands:

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
expected stdout `"5\n7\n9\n5\n"`, via `test_gimple_stdout`.

Generated C for it (`gimple_codegen.compile_to_gimple(src)` on the program):

- `int64_t _classattr_Tag____version__;` is a PLAIN file-scope C global
  (not a boxed struct field) in this shape.
- `make` emits `_classattr_Tag____version__ = version;` then
  `_alloc_Tag()`: the landed `_gen_stmt_StructDef` store is working.
- Reads are `_t5 = _classattr_Tag____version__;`, through the instance
  path (`emit_exprs.py` ~2602, `class_attrs` branch) and the class-name path.

Corrections to the round-2 plan, from reading the code:

1. The globals are NOT always plain. `module_gen.py` ~13818-14140 is a
   multi-path emitter (`global_decls`, `_gmi_declare_table_global` ~2731,
   container boxing as `int64_t` with a comment, `_own_overlay_global_ctype`
   ~12459). A block-pointer global must go through the same path or it will
   be typed differently from every other module global. Do not add it as a
   bare declaration beside them.
2. Minimal-touch design, preferred over the round-2 plan. Keep
   `gen._class_attrs[C][A]` returning the mangled name for every
   consumer that keys on it (`_global_var_types`, `_elem_types`, the alloc
   loop at `module_gen.py` ~15020, `_mojo_classattr_init`). Change only the
   sites that turn the name into C text, and make them emit
   `(*_classattr_C__block).A` (or `_classattr_C__block->A`) for a
   FUNCTION-SCOPED class. Those sites are: `emit_exprs.py` ~1473 (`cls.`),
   ~1824 (`ClassName.attr`), ~2602 (instance read, which should read
   `((_cattrs_C *) obj->_cls_block)->A`), and the write targets used by
   `emit_stmts.py` ~1768 and ~2439 via `_resolve_class_attr_write_target`
   (`emit_methods.py` ~183). A write site uses the returned gname as C
   lvalue text through `_safe_coerce_emit`; confirm that before relying on it.
3. Which classes are function-scoped: `_gmi_hoist_nested_structs`
   (`module_gen.py` ~3028-3085) has `found` (every nested class, with its
   enclosing function) and renames each into `renamed_to`. Record those
   final names on the generator (e.g. `self._fn_scoped_structs`) there. Do
   not infer it from `_class_attrs` alone: module-scope classes share the
   same registration and must keep the global.
4. Block type: `_cattrs_C` with one field per attribute, typed as the
   attribute's declared C type (`_global_c_decl_types[gname]` if present,
   else `_global_var_types[gname]`), so every read and write keeps the type
   it has today. The instance hidden field `_cls_block` is typed `void *`
   and cast at the one read site, so the struct C definition does not need
   the block's full type ordered before it.
5. Dead-global cleanup: after the switch, the old `_classattr_C__A` global
   of a function-scoped class is unused. Either skip its declaration in the
   emitter loop above or leave it and say so. Do not leave it unexplained.

Residual to write down, not fix: a class object that escapes its function
and is used in a later call (`return Tag` then `T = make(9); T.__version__`)
still reads the block of the most recent execution. Closing it needs the
class object as a runtime value.

Next round, in order: (1) fn-scoped set in the hoist; (2) block struct and
block global through the existing global emitter; (3) `_cls_block` seed in
`_init_C`; (4) the instance read site; (5) class-name read and write
sites. Land (1)-(5) together, because the four-call program needs all of
them, and run `test_gimple_runner.py` for the three nested-class tests
(`5\n7\n`, `3\n`, and the four-call case once re-added).
