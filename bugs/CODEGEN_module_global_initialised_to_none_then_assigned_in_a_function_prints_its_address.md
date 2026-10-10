# CODEGEN: `x = None` at module scope, then `global x; x = "abc"` in a function, prints the string's ADDRESS

**Area:** CODEGEN. Found 2026-10-07 while checking the neighbouring shapes of the
fixed "bound method in a module global" bug (the module-global type came from
the method's return type; fixed in `_phase17_value_type` and the
`_gscan_declare_global` final arm).

## Reproduction

    x = None

    def setup():
        global x
        x = "abc"

    setup()
    print(x)

CPython prints `abc`. The compiled program (single TU, `compile_to_gimple`)
prints `4367113720` (the `char *` as a decimal), exit 0 -- a silent wrong
answer.

The same shape with a bound method (`f = None` / `global f; f = m.truthy` /
`print(f())`) prints `1` where CPython prints `True`.

## Cause (not yet traced past the declaration)

The global's field is declared from its FIRST assignment, `None`, which is an
integer-typed slot, and the function's store of a pointer-typed value into it
goes through the boxed `int64_t` path with no record that the slot now holds a
`char *` (`_actual_types` is set on the store but the read in `print` is typed
by the declared field). A global assigned only once does not hit this; a
global whose first assignment is `None` and whose real value is assigned in a
function is the standard lazy-initialised-singleton idiom.

## Next step

Make the Phase 1.7 scan join every assignment to a global across the whole
module -- including those inside functions that declare it `global` -- instead
of letting the first one (here `None`) fix the type. `_phase17_scan_try_branches`
already joins across try/except branches with `TypeLattice.join`; this wants the
same treatment for `global`-declared stores, with `None` joining to the other
side's pointer type (the local-variable twin is
`CODEGEN_a_local_declared_from_None_holds_a_boxed_pointer.md`).
