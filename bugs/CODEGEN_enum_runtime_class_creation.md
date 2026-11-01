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
   time. **Landed 2026-10-31 for the literal shape** (`type('N', (B1, B2), {'a': v, ..})`:
   literal base tuple/list, literal dict of string keys; anything else is still refused by name):
   `mojo_type_new` returns a class HANDLE word (`{MOJO_CLASSOBJ_MAGIC, class-table tag}`, magic
   inside the 31-bit range `mojo_read_type_tag_safe` accepts), `mojo_type_add_base`,
   `mojo_classobj_setattr`; `Foo.x`, `Foo.x = v`, `setattr/getattr`, `Foo.__name__` on the handle
   go through `mojo_obj_getattr / mojo_getattr_any / mojo_setattr` to the class table, found
   through the bases. Pinned by `test_runtime_class_creation.py` (CPython-diffed).
   **Computed namespace landed 2026-10-31**: `type(n, (B,..), ns)` with `ns` a dict-typed
   variable/attribute is walked at run time by `mojo_type_fill_from_dict` (insertion order, float
   slots boxed); pinned by `computed_namespace_dict_variable`. A call-result namespace is still
   refused by name.
   **Computed bases landed 2026-11-01**: `type(n, bases, ns)` with `bases` a tuple/list-typed
   variable/attribute is walked at run time by `mojo_type_add_bases_from_list` (pinned by
   `computed_bases_list_variable`; a static class inside such a list is not yet covered).
   STILL MISSING in stage 3: inheriting a STATIC base's class-body attributes through a dynamic class (`class B: y = 5`,
   `type('F', (B,), {}).y` - body attributes are static globals, not table entries; register
   them as words in `_mojo_classattr_init` or fall back to the struct's static read);
   `type.__new__(metacls, ..)`; instances of a dynamic class (stage 2 is its prerequisite).
4. the metaclass protocol `EnumType` uses: `__prepare__`, `__new__`, `__call__`, `__set_name__`,
   `__init_subclass__`, class-level `__getattr__`, `isinstance(x, cls)` for dynamic classes,
   `DynamicClassAttribute` / `property` on dynamic classes.
5. `Enum` / `Flag` / `IntFlag` end to end: `class Color(Enum): RED = 1` through the metaclass,
   `Color.RED`, `Color(1)`, `iter(Flag)`; then flip `enum` from interpreted to compiled and add
   a program (members, aliases, Flag combination, iteration) to an end-to-end test in the style
   of `test_glob_compiled.py`.

Quick test for the first stage that remains: an `Enum` subclass with two members compiled and
printed, diffed against CPython.
