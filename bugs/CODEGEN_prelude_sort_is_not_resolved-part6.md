# CODEGEN: a module-level `comptime` constant erases to `0` in an isolated generic TU

Part 6 of `CODEGEN_prelude_sort_is_not_resolved` (see its SPLIT line). Depends on part 5 for the measured
symptom to appear in the `sort` chain; the reproduction below is independent of it.

## Goal

In the isolated translation unit of a generic instance, a reference to a module-level `comptime` constant
emits `(int64_t)0 /* ct param or undeclared */`. Measured on `std/builtin/sort.mojo`: `insertion_sort_threshold`
erases to `0`, so the `len < 32` small-sort branch of `_quicksort` is dead. Make a module `comptime` constant
that the instance's body reads resolve to its value in that TU, by the same mechanism a module constant
already uses in an ordinary (non-isolated) function.

## Acceptance

- A generic function whose body reads a module-level `comptime LIMIT = 32` (declared in the same module)
  emits `32` for `LIMIT` in its isolated instance C, not `(int64_t)0`.
- A name that is not a module `comptime` constant keeps the existing `/* ct param or undeclared */` output.

## Done when

Add `test_module_comptime_constant_resolves_in_an_isolated_instance` to `test_gimple.py` with a two-file or
single-file program as above, then run:

    python3 -m pytest test_gimple.py -k test_module_comptime_constant_resolves_in_an_isolated_instance -q

It must fail before the change and pass after.
