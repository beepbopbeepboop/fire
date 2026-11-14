# `issubclass(...)` lowers instead of emitting a weak stub (part 4)

Part 4 of 5 of `bugs/hard/GATE_red_recover-land_2026-11-02.md`. Class: easy —
one builtin arm beside the existing `isinstance` arm, plus its test. This is the
parent doc's `issubclass` stub.

## Measured (2026-11-13, this tree)

    class Base:
        pass

    class Derived(Base):
        pass

    def f():
        print(issubclass(Derived, Base))
        print(issubclass(Base, Derived))
        print(issubclass(Derived, object))

    f()

Compiled (`compile_to_gimple`, `do_imports=False`), the `.ci` contains one weak
stub —

    __attribute__((weak)) int64_t issubclass (...) {
      mojo_print ((char *)"issubclass: unavailable in compiled mode"); return (int64_t)0; }

— and the built binary prints

    issubclass: unavailable in compiled mode0
    issubclass: unavailable in compiled mode0
    issubclass: unavailable in compiled mode0

where CPython prints `True\nFalse\nTrue`, exit 0: a silent wrong value.

`isinstance` has a real lowering (`_lower_builtin_isinstance`,
`emit_calls.py:5953`, with the runtime class table behind
`_isinstance_one_type`, `emit_calls.py:5685`). `issubclass` has none: it is
named in `_NON_FORWARDING_BUILTINS` (`module_gen.py:140`) but there is no arm
for it anywhere in the backend. The compiler's own use is
`myinterpreter.py:7102` (`isinstance(value, type) and issubclass(value, BaseException)`),
which is why the closure dump names `issubclass`.

## Goal

Lower `issubclass(a, b)` in one arm next to `_lower_builtin_isinstance`:

- both operands a statically known class (`Base`/`Derived`, including through a
  module qualifier) -> the answer is known at compile time by walking the
  parsed class hierarchy (directly and through bases): `True`/`False`.
- an operand that is a runtime class word (the `_rtobj_kinds[…]=='class'` /
  `mojo_is_classobj` model the `isinstance` arm already uses) -> a runtime
  call over the same class table (`_class_derives` in `runtime/fire_runtime.c`);
  `object` is the top of every hierarchy.
- an operand proven NOT to be a class value (an `IntLiteral`, a string, a known
  container/struct instance) -> a compile-time `RuntimeError` naming the
  operand, the same honest-refusal convention `asyncio.sleep(...)` uses. Never
  a weak stub, never a silent `0`.
- keyword/arity errors follow the existing builtin arms.

## Acceptance

- The probe above compiles with zero `unavailable in compiled mode` and the
  built binary prints exactly CPython's `True\nFalse\nTrue`, exit 0.
- `issubclass(D, Base)` / `issubclass(D, object)` through a module-qualified
  class name (`m.Derived`) answers the same as the bare name.
- The compiler's own shape
  `isinstance(value, type) and issubclass(value, BaseException)` compiles with
  no stub (the class table answers `0` for a word that is not a class object,
  which is what the `isinstance(value, type)` guard already guarantees there).
- `issubclass(1, object)` is a compile-time refusal (RuntimeError), not a
  silent `False` and not a stub.
- `isinstance` behaviour is unchanged (reuse `_isinstance_one_type`; do not
  write a second class-hierarchy walk).

## Done when

File: `test_issubclass_builtin.py` (repo root; created by this part).

Command: `python3 test_issubclass_builtin.py`

It compiles the three-class probe with `compile_to_gimple`, asserts no
`unavailable in compiled mode`, asserts the refusal for `issubclass(1, object)`,
builds the probe with `build_config.find_gcc()` and compares stdout to
CPython's. Red today: 1 stub, the three diagnostic lines instead of
`True\nFalse\nTrue`.

## Where to start

- `mojo/backend_gimple/emit_calls.py:5953` `_lower_builtin_isinstance` and
  `emit_calls.py:5685` `_isinstance_one_type` — the arms to sit beside and the
  runtime queries to reuse.
- `runtime/fire_runtime.c:17960` `_class_derives` (static, depth-limited),
  `mojo_isinstance_rtclass`, `mojo_isinstance_type`, `mojo_type_of` — the
  existing class table; add the `issubclass` entry point there rather than a
  second hierarchy walk in generated C.
- `module_gen.py:140` `_NON_FORWARDING_BUILTINS` already lists `issubclass`,
  so an argument's static type is not forwarded to it.
