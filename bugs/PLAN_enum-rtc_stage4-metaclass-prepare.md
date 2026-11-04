# enum-rtc — stage4-metaclass-prepare: Implement __prepare__ on run-time metaclass

Parent: bugs/hard/CODEGEN_enum_runtime_class_creation.md
Plan: docs/enum-runtime-class-plan.md

## Scope
Implement __prepare__ on run-time metaclass.

## Files
mojo/backend_gimple/cpp_core.py, runtime/fire_runtime.c

## Acceptance
Meta.__prepare__ returns namespace dict.
