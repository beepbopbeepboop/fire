# Plan: Enum run-time class creation (CODEGEN_enum_runtime_class_creation)

Source bug: bugs/hard/CODEGEN_enum_runtime_class_creation.md

## Decomposition

Step 1 — Dynamic instance attributes (stage 2)
  setattr(obj, n, v) / obj.n = v for undeclared names writes mojo_obj_getattr dynattr dict.
  Files: runtime/fire_runtime.c, mojo/backend_gimple/emit_stmts.py

Step 2 — Computed namespace type(name, bases, namespace) with variable ns
  Already landed for literal; extend mojo_type_fill_from_dict for variable ns.

Step 3 — EnumType.__new__ end-to-end
  class Color(Enum): RED = 1 creates class at runtime via metaclass.
  Files: mojo/backend_gimple/cpp_core.py or emit path

Step 4 — CPython-diffed test
  test_runtime_class_creation.py extended.
