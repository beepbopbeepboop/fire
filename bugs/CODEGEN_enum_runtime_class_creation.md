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
   slots boxed); pinned by `computed_namespace_dict_variable`. A call-result namespace (`type(n, b, ns())`) landed 2026-11-01 too (dict-typed result; pinned by
   `call_result_namespace`; the name argument is now lowered first, left to right).
   **Computed bases landed 2026-11-01**: `type(n, bases, ns)` with `bases` a tuple/list-typed
   variable/attribute is walked at run time by `mojo_type_add_bases_from_list` (pinned by
   `computed_bases_list_variable`; a static class inside such a list is not yet covered).
   **Static base body attributes landed 2026-11-01**: `class B: y = 5` / `s = 'hi'` / `f = 2.5` and
   `type('F', (B,), {}).y` - each module emits `_mojo_classattr_read(tag, name, &word)` (the LIVE
   class-attribute global as a word: float boxed, string registered, container by address) and
   registers it with `mojo_register_classattr_reader`; `_class_lookup` asks the readers at every
   class it visits, so a later `B.y = 8` is seen through `F`. Pinned by
   `static_base_body_attributes_are_inherited` / `static_base_attribute_is_read_live`. Not
   covered: methods of a static base reached through a dynamic class.
   **Static class in a computed bases list landed 2026-11-01**: a bare static class name used as a
   VALUE (`bases = (A, B)`) now lowers to its type tag (`emit_exprs._lower_IdentExpr`) instead of the
   shared zero placeholder, so `mojo_type_add_bases_from_list` files it correctly; pinned by
   `static_class_in_computed_bases_list`.
   **Instances of a dynamic class landed 2026-11-01**: `Foo = type(..); o = Foo()` - a call on a
   class handle (`mojo_fnptr_call_0..4` checks the `_reg_classobj` registry) makes an instance
   (`mojo_classobj_call`: a registered `{MOJO_INSTOBJ_MAGIC, class tag}` block, `__init__` from the
   class table called with it if the namespace names one). `o.y = v` / `setattr` use the per-object
   dynattr dict; a read that misses it is found through the class and its bases
   (`mojo_instobj_class_lookup` in `mojo_obj_getattr`), so `Foo.x = 9` is seen by every instance.
   `emit_calls._lower_call`'s uppercase-name "opaque constructor" guess no longer fires for a LOCAL
   (`Foo` was lowered to the literal 0). Pinned by `instance_of_a_run_time_class` /
   `instance_reads_through_the_class_bases`. Not covered then (methods, `isinstance` since landed, below): `repr(o)`, a call with more than 4
   arguments.
   **Methods and `isinstance` on dynamic classes landed 2026-11-01**: a local bound to `type(..)` (or
   to a call of such a local) is recorded in `gen._rtobj_kinds` (`('l', name)` -> `'class'`/`'inst'`,
   set by `stmts_shared._note_rtobj_binding`, dropped when the name is rebound to anything else).
   `o.m(a, b)` / `Foo.m(x)` on such a local is `mojo_rtobj_method_call` (class-table lookup through
   the bases, the instance passed first as `self`, a miss is AttributeError) - before, `o.get()` was
   lowered as `dict.get` and printed 0 - and `isinstance(o, Foo)` (also inside a tuple) is
   `mojo_isinstance_rtclass`. Pinned by `methods_in_the_namespace_are_called_on_instances` /
   `isinstance_of_a_run_time_class`. **Up to 7 call arguments landed 2026-11-01** (constructor `Foo(a..g)` and `o.m(a..g)`/`Foo.m(a..g)`:
   `mojo_classobj_call` / `mojo_rtobj_method_call` carry 7 argument words, `mojo_fnptr_call_5..7` check
   for a class handle; pinned by `methods_and_constructor_take_up_to_seven_arguments`; more than 7 is
   still refused by name). Not covered: keyword/star arguments, a method returning a float or string (the word is an untyped
   `_dyn_word_vals` word), a class or instance reached through a parameter/attribute rather than
   a local, `repr(o)`.
   **`isinstance(o, StaticBase)` landed 2026-11-01**: once a module lowers any `type(n, bases, ns)`
   (`gen._rt_classes_made`), the static-struct `isinstance` ORs the tag compare with
   `mojo_isinstance_rtclass(obj, tag)`; pinned by `isinstance_of_a_static_base_of_a_run_time_class`.
   Limit: the flag is set when the `type(..)` call is lowered, so an `isinstance` in a function
   emitted BEFORE any such call is not covered.
   Separate finding, not fixed: for a STATIC class `p.b = 5` outside `__init__` infers a struct
   field, so `hasattr(q, 'b')` is True on an instance that never set it (CPython: False).
   **`type.__new__(type, name, bases, ns)` landed 2026-11-01**: the same lowering as the 3-argument
   `type(..)` (`emit_calls._lower_type_new(gen, node, args)`), pinned by
   `type_dunder_new_with_the_type_metaclass`. A user metaclass as the first argument
   (`type.__new__(Meta, ..)`) is refused by name
   (`type_dunder_new_with_a_user_metaclass_is_refused_by_name`) - it is stage 4: the class must be
   an instance of `Meta` and `Meta.__call__ / __getattr__` must see it.
4. the metaclass protocol `EnumType` uses: `__prepare__`, `__new__`, `__call__`, `__set_name__`,
   `__init_subclass__`, class-level `__getattr__`, `isinstance(x, cls)` for dynamic classes,
   `DynamicClassAttribute` / `property` on dynamic classes.
5. `Enum` / `Flag` / `IntFlag` end to end: `class Color(Enum): RED = 1` through the metaclass,
   `Color.RED`, `Color(1)`, `iter(Flag)`; then flip `enum` from interpreted to compiled and add
   a program (members, aliases, Flag combination, iteration) to an end-to-end test in the style
   of `test_glob_compiled.py`.

Quick test for the first stage that remains: an `Enum` subclass with two members compiled and
printed, diffed against CPython.
