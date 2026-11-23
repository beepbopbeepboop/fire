# CODEGEN: a module global whose binding an AUGMENTED assignment widens is imported with the pre-widening type

**Found while fixing** the per-file (`do_imports=False`) compile's export of an
UNANNOTATED module-level scalar global (a bare `from helper import CONST`
read 0 for `CONST = 41`; fixed in `module_loader._ml_py_global_ctype`). That
fix teaches
`module_loader._ml_py_global_ctype` to type an unannotated scalar LITERAL
exactly as the defining module's own `__mojo_global_get_` accessor is typed.
This doc is the case that fix deliberately does NOT claim, because the honest
answer needs the definer's operator→type rule and the text scanner does not
have it.

## Symptom

In the per-file (`do_imports=False`) compile a bare `from helper import A`
reads 0, because no export entry is written (`ct param or undeclared: A` in
the importer's C). The value the definer actually holds is a widened type:

    helper.py:  A = 9
                A /= 2
    from helper import A
    print(A)                          # CPython: 4.5, compiled: 0

Before the part-1 fix, `int`-typed exports did not exist at all, so this was
one more silent 0 among many. It is now the ONE remaining class of that
family, and it exists because export `int` here would be WRONG: the read
would take an `int` return register from a function that returns `double`,
i.e. garbage rather than 0.

## Measured (2026-11-23, `build_stdlib_dylib.compile_module_to_c`)

`helper.py` compiled alone (its own module identity, no entry points) and the
`<helper>__mojo_global_get_<NAME> (void)` definition read out of its C:

| helper.py | accessor the definer emits |
|---|---|
| `A = 9` then `A /= 2` | `double` |
| `C = 3` then `C += 1` | `int64_t` |
| `A: int = 9` then `A /= 2` (ANNOTATED) | `double` |
| `B: str = 's'` then `B += 'x'` | `char *` (unchanged) |

The widening runs in `mojo/backend_gimple/module_gen.py:12366`
(`_phase17_apply_augmented_global_types`), after Phase 1.7 has typed every
global and BEFORE the first body emission, and it is value-typed by
`mojo/middle/resolve_shared.py:1736` (`_aug_assign_value_type`: true division
between ints is `double`, otherwise `TypeLattice.join` of target and RHS).
`_gscan_declare_global` then skips the name (`_aug_widened_globals`), so the
plain-RHS scan cannot freeze the old kind back.

## What part 1 landed instead, and why

`module_loader.py`'s scalar-global scan now collects every name the module
rebinds with an augmented assignment (`_ml_augmented_assign_target`, any
indentation — a function-scope `global A; A += 1` rebinds the same object) and
withholds the export for those names. Unexported keeps the OLD behaviour (a
stub read of 0); a wrong-typed extern would read garbage, which is strictly
worse. The over-approximation is deliberate: a LOCAL `A += 1` in a function
without `global A` also opts the module global out, and paying a missed
export (0, as before) is cheaper than paying a mismatched one.

## Next step (the production fix)

Give the text scan the widened type instead of skipping, from ONE source of
truth rather than a copy of the operator table:

1. **Preferred, two-pass:** the defining module's compile already knows its
   accessor types (`_module_globals` / the emitted `__mojo_global_get_`
   signatures). Record them in the per-module artifact the importer already
   consumes — or expose a small `augmented_scalar_ctype(base_ctype, op,
   rhs_shape)` in `mojo/middle` that both `_aug_assign_value_type` and the
   loader call — and have `module_loader` answer `int64_t` / `double` from it
   for the literal and `NAME = callee(...)` shapes it already classifies.
2. Minimum viable, cheaper but a second copy: in the text scan, on `A /= <int
   literal>` widen `int` → `double`; on `A += <int literal>` -> `int64_t`
   (the measured answers above). Do this only if (1) turns out to need more
   plumbing than the gap is worth, and add the `+=`/`-=`/`**=`/`>>=` rows
   from the same table, because `+=` boxing to `int64_t` is not guessable.

## Done when

A new case in `test_codegen_imported_global_unannotated_scalar.py` (its
`test_augmented_reassignment_withholds_the_export` is the current pin for the
conservative answer) builds `helper.py` with `A = 9` / `A /= 2`, compiles
both modules through `compile_module_to_c`, links with
`runtime/fire_runtime.c`, runs it, and requires `4.5` — CPython's answer —
instead of asserting that `A` has no export entry. Delete this doc in that
commit.
