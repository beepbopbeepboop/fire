# CODEGEN_generator_function: Lib/test/test_ensurepip.py

## Status (2026-10-29, planning round: instance-read path for the captured-local class attribute)

Still the same single blocker: this file's `fake_pip` needs
`class FakePip: __version__ = version` to read the enclosing local, which is
`bugs/CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md` (plan B
there). This round did not change code; it located the lever for that plan's
step 3 so the next round can start editing directly.

Measured (`python3 tools/memslot.py --gb 8 --label measure -- python3
.tmp/measure_classattr.py`, `compile_to_gimple_with_cpp(src, do_imports=False)`,
the `make(version)` / `Tag()` program from the nested-class doc):

- `make()` emits `_classattr_Tag____version__ = version;` in the body (the
  single-call fix is present), and `_alloc_Tag` does not seed it.
- Each instance read `a.__version__` lowers to `_t = _classattr_Tag____version__;`,
  i.e. the GLOBAL, not a field of `a`. That is why `a` prints the latest call's value.

Why the read goes to the global: `mojo/backend_gimple/emit_exprs.py`
`_lower_MemberExpr` (~2472-2610) checks the instance field map
(`if node.member in field_map`) BEFORE the class-attribute branch
(`class_attrs[struct_name]`, ~2602). The class-attr branch wins only because
`Tag` has no `__version__` entry in `gen.struct_field_types['Tag']`. So the
lever is to register that entry for function-hoisted classes, not to change the
read branch.

Next round (plan B, concrete):

1. Confirm `struct_field_types['Tag']` lacks `__version__` (dump it right after
   `module_gen`'s field-typing pass, ~module_gen.py:5950-5990: the "UPGRADE an
   already-registered instance field" block only upgrades, it never creates).
   For a hoisted class, create the field there, keyed on
   `_gmi_nested_struct_defs` membership, with the type from `_class_attr_ctype`.
2. Seed it at allocation: the `_alloc_<Cls>` emitter's class-attr loop
   (module_gen.py ~15012-15030 `for _aname in sorted(class_attrs)`) writes
   `_p-><attr> = <global>` only when the field type and global type agree, so
   the field created in step 1 gets the seed for free if the types match.
3. Verify the instance read now emits `_p->__version__`
   (`_lower_MemberExpr` field branch) and rerun the measure script. Expected
   `7 7 9 9` becomes `5 7 9 5`. Note the residual: `Tag.__version__` on the
   class object still reads the last global (the nested-class doc's residual).
4. Rebinding check before committing: `t = Tag(); Tag.__version__ = 3;
   print(t.__version__)` with no instance-level assignment. CPython prints 3
   (the instance has no own value, so the class value wins). Match the
   module-scope class's answer for the same program, and pin it.
5. Tests, in `test_gimple_runner.py` next to
   `test_nested_class_attr_reads_enclosing_local_regression`: the `make`/`Tag`
   program expecting `"5\n7\n9\n5\n"`, which fails today with `7 7 9 9`.

Until steps 1-3 land, `coro.py` `_nested_class_nonliteral_attr` keeps refusing
the generator form, so this file stays on the honest interpreted path.

## Status (2026-10-29 — the silent miscompile is now an honest refusal; the file still does not compile)

The nested-class shape in `fake_pip` no longer refuses on `StructDef`. It was
REMOVED from the refusal path by the stack-switch cutover, and what replaced it
was worse: the generator compiled, with the `class FakePip` statement lowered to
`/* TODO: StructDef */` and `__version__ = version` never assigned. The
attribute read 0 at exit 0.

Measured today, `compile_to_gimple_with_cpp` on a minimal `fake_pip` shape,
before the fix: `__mgco_fake_pip_*` emitted, `_classattr_FakePip____version__`
declared and never assigned, debug line `unknown statement dropped: StructDef`.

Landed (this round):
- `mojo/middle/coro.py` `_nested_class_nonliteral_attr`, checked in `_eligible`:
  a generator whose nested class has a non-literal class-level attribute is
  refused with `nested class 'FakePip' has a non-literal class attribute
  '__version__'`. The generator falls back, and the module is interpreted from
  source. Now the minimal shape reports `cannot compile module: ... generator
  function(s) fake_pip`, not a silent 0.
- The nested-class walker `_gmi_nested_struct_defs` (and its slot tuple) moved
  from `mojo/backend_gimple/module_gen.py` to `mojo/middle/exprtypes.py`, so the
  gate and the hoist share one walker.
- Tests in `test_gimple_generator_runner.py` (`run_callable_param_tests`):
  `nested_class_local_attr_refused` (failed before the gate, passes after) and
  `nested_class_literal_attr_compiles` (literal class attribute still lowers to 7).

### 2026-10-29 round — items 2 and 3 measured as already working; item 1 is the only blocker

Measured on the minimal `fake_pip` shapes, under `tools/memslot.py --gb 8`:

- A no-`__init__` class with a LITERAL class attribute, constructed as
  `FakePip()` inside a generator body: compiles and prints `7`. The
  `_struct_has_init`-gated branch in `cpp_core.py` is not the path taken; the
  ordinary struct-constructor path handles it. Item 2 does not need a fix.
- The same class used through a `@contextmanager` generator in a
  `with fake_pip() as v:`: compiles and prints `7`. Item 3 does not need a fix.
- The captured-local shape (`def g(version): class FakePip(): __version__ = version`)
  is still refused at the generator gate with `unsupported sta...`, and the
  module falls back to interpretation, as designed.

Pinned by two tests in `test_gimple_generator_runner.py`:
`nested_class_noinit_ctor_in_generator_compiles` and
`nested_class_literal_attr_contextmanager_compiles`. Both pass now (263/263 in
that file); they are coverage pins, not fail-before-fix tests, because there
was no behaviour to change.

Still open for THIS test file, and only this:
1. The class attribute must capture the generator's own local at the moment the
   `class` statement executes. The plain-function silent case is the same root
   cause: `bugs/CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md`.
   That bug is claimed by another worker, so it was not edited here. Once it
   lands, the captured-local shape above should compile, and the `with` path is
   already known to work for a literal attribute.

Next step: item 1 (see the linked doc). Until it lands, this file stays refused
at the generator and the module is interpreted, which is the honest path.

The struct-discovery half of the older plan (hoisting a nested class out of a
generator body) landed on 2026-10-02 (`_gmi_nested_struct_defs`); the older
status history that said otherwise has been removed.

Measured on a minimal reproducer of the `fake_pip` shape (not a full
`fire.py build` of the file, which was not run this round), after the gate:

```
RuntimeError cannot compile module: function(s) fake_pip (generator function(s), contain a `yield`/`yield from`) — ...
```

Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_ensurepip.py
