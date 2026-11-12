# DIAGNOSTICS missing-validation part 3: `in` / `not in` on a type with no `__contains__`

Class: **mid** (this doc lives in `bugs/mid/`). It adds a type-directed
membership check in the gimple lowering, and the hard part is not the message
— it is distinguishing a provably scalar right operand from the type-erased
`int64_t` that may be a boxed container.

Parent: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`. This covers the
`__contains__` half of the umbrella's "constraint diagnostics on tuple methods
(`__contains__` / `first_of`)"; `first_of` has no source in this tree and is
not part of this doc.

## Goal

`x in y` / `x not in y` must be a compile error when `y`'s type has no
`__contains__`, with modular's message:
`'<Type>' does not implement the '__contains__' method`
(`new-modular/Mojo/test/mojo-parser/exprs/expressions_errors.mojo`,
`testInExpr`). Today both spellings compile silently for `Int` operands and
only fail (or answer wrongly) at run time.

## Current state (measured 2026-11-12)

- `def f(x: Int, y: Int): _ = x in y` compiles with no diagnostic, and the
  same for `not in`.
- `def f(a: Int, b: Int)` with a following call also builds
  (`fire.py build` succeeds).
- Positive membership already compiles: `1 in (1, 2)`, `"a" in s`,
  `1 in some_list`. The interpreter evaluates membership at run time
  (`myinterpreter.py`, ~7845: `elif op == 'in': return left in right`), so the
  reference interpreter is not the acceptance target here.
- The lowering is `mojo/backend_gimple/emit_exprs.py`:
  `CompareExpr` `in`/`not in` dispatch at ~3408 calls
  `_lower_in_impl` (~6249) / `_lower_in_dispatch` (~6287). The container's C
  type selects an arm; an unknown/boxed container falls through to
  `mojo_in_dispatch_int` / `mojo_in_dispatch_str` (~6490-6530), which is how
  a type-erased module-global container still answers correctly. A blanket
  "reject `int64_t`" would regress exactly that path (the comment there names
  `name in _C_RESERVED_FUNCS` as the case that must keep working).

## Scope

Add `_membership_container_type(gen, right_node) -> str | None` beside the
`_lower_in_*` family: the definitive scalar type name of the right operand, or
`None` when it is not provably a scalar. Reject before choosing an arm.

- Provably scalar by SHAPE: `BoolLiteral` → `Bool`, `IntLiteral` → `Int`,
  `FloatLiteral` → `Float64`; arithmetic/comparison expressions whose result
  is a known scalar; a call whose return type is a known scalar.
- Provably scalar by BINDING: an `IdentExpr` whose entry in `gen.var_types`
  (parameters and locals) is `int64_t` / `double` / `_Bool`. Do NOT reject a
  name that is only in `gen._global_var_types`: module-global reads are
  declared `int64_t` and may be a boxed list/dict/set (the erased-container
  arm above). A local known to hold a container (`MojoList *`, `MojoDict *`,
  `MojoSet *`, `char *`, tuple/struct types) is not scalar.
- Unknown (`AnyType` parameter, unresolved name, erased global) → `None`, so
  the runtime dispatch stays.
- Raise `RuntimeError` with the container type's spelling:
  `'Int' does not implement the '__contains__' method` (and likewise
  `Float64`/`Bool`). Both `in` and `not in` reject; `not in` must not be left
  answering the positive question.
- Keep every existing arm and its `negate` tail intact.

## Acceptance

- `x in y` and `x not in y` with `Int` operands fail to compile with
  `'Int' does not implement the '__contains__' method`; the same through
  `fire.py build` (exit nonzero, message in the output).
- `Float64` and `Bool` right operands report their own type names.
- These keep compiling and behaving as today: `1 in (1, 2)`,
  `"a" in s`, `1 in some_list`, `1 in some_dict`, and a membership test on a
  type-erased module-global container.
- A parameter whose type is an unresolved generic parameter still compiles
  (conservative).

## Done when

Add `test_contains_method_diagnostic.py` beside the other
`test_*_diagnostic.py` files (do NOT register it in `tools/suite.py`) and run
exactly:

    python3 tools/memslot.py --gb 8 --label contains-method -- python3 test_contains_method_diagnostic.py

The test compiles each case with `compile_to_gimple`, checks the exact message
and the positive controls, and includes one `fire.py build` (through
`diagnostic_build.build_refusal`) for the statement form.

## Not in this part

`first_of` (no source in this tree), and membership in the interpreter. No test
registration.

## Status

- **Open.**
