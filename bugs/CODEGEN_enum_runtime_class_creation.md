# CODEGEN: `enum.py` (EnumType / Flag / IntFlag) needs run-time class creation

## State (2026-10-31)

Every generator of CPython 3.15's `Lib/enum.py` now compiles (`Flag._iter_member_`,
`_iter_member_by_value_`, `_iter_member_by_def_` for `Flag` and `IntFlag`; pinned by
`generator_classmethod_reads_runtime_class_attributes` and
`generator_yield_from_sorted_generator_call_with_attr_key`). The module still falls back to the
interpreter, and that is correct: `compile_to_gimple_with_cpp(enum.py)` now refuses with

    3-argument type(name, bases, namespace) creates a class at run time, which the compiled
    path does not model

`EnumType.__new__` builds every enum class that way, so `class Color(Enum): RED = 1` is
created at run time through the metaclass.

## What exists (stage 1, landed)

A run-time CLASS TABLE (`runtime/fire_runtime.c`: `mojo_class_register / setattr / getattr /
getattr_default / hasattr / delattr`). A class is its type tag (`_struct_type_id(name)`); every
module registers its classes and bases; attributes a class body never declares live in the
class's dict and are found through the bases (depth first, left to right). `cls.x`, `Cls.x`,
`Cls.x = v`, `setattr / getattr / hasattr / delattr(Cls, name)` use it. Struct reflection of
every module is reachable from a word with `mojo_getattr_any(obj, attr)`
(`mojo_register_getattr_dispatch`).

## Stages left (each lands with a CPython-diffed test)

2. dynamic INSTANCE attributes on objects of dynamic classes: `setattr(obj, n, v)` / `obj.n = v`
   for undeclared names write `mojo_obj_getattr`'s dynattr dict, `obj.__dict__`.
3. `type(name, bases, namespace)` / `type.__new__(metacls, name, bases, classdict)` at run
   time: a class-table entry (tag from the name, bases from the list) whose dict starts from the
   namespace; instances of such a class are dynamic objects (attribute dict + class tag), their
   method lookup goes through the class table.
4. the metaclass protocol `EnumType` uses: `__prepare__`, `__new__`, `__call__`, `__set_name__`,
   `__init_subclass__`, class-level `__getattr__`, `isinstance(x, cls)` for dynamic classes,
   `DynamicClassAttribute` / `property` on dynamic classes.
5. `Enum` / `Flag` / `IntFlag` end to end: `class Color(Enum): RED = 1` through the metaclass,
   `Color.RED`, `Color(1)`, `iter(Flag)`; then flip `enum` from interpreted to compiled and add
   a program (members, aliases, Flag combination, iteration) to an end-to-end test in the style
   of `test_glob_compiled.py`.

Quick test for the first stage that remains: an `Enum` subclass with two members compiled and
printed, diffed against CPython.
