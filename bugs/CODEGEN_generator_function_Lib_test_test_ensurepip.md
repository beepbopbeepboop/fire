# CODEGEN_generator_function: Lib/test/test_ensurepip.py

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

Still open for THIS test file (feature-sized, unchanged in substance):
1. The class attribute must capture the generator's own local at the moment the
   `class` statement executes. That is the plain-function silent case too:
   `bugs/CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md`.
2. A `class` with NO `__init__` and only class-level attributes must be
   constructible as `FakePip()` from inside a generator body. The
   generator-body constructor branch (`mojo/backend_gimple/cpp_core.py` near
   `fname in gen._struct_has_init`) only fires for a struct with an `__init__`.
3. `fake_pip` is a `@contextmanager`, so once 1 and 2 land, the `with fake_pip(...)`
   use in the test also has to lower through the existing `MojoGenerator *` `with`
   branch. Not yet exercised for this shape.

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
