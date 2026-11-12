# CODEGEN_module_scope_class_attr_nonliteral_unstored

## Summary

A module-scope class attribute whose value is NOT a literal — a reference to a
module global — is never stored at all, in ANY spelling: the `_classattr_`
global stays 0/NULL, so `C().name` reads back `0` (int) or `None` (str).
Literals work. This is distinct from the function-scoped per-execution-cell
case, whose doc (`CODEGEN_nested_class_var_attr_untyped_field`) was deleted
with its fix in this commit: there the `class` statement stored the right
value in its cell; here nothing is stored. A module-scope `class` statement
is emitted by `gen_module` directly, which seeds the `_classattr_` global
only from literal values.

## Measured (2026-11-11, this tree, after the fn-scoped cell fix — identical before it)

Compiled with `test_gimple_runner.compile_mojo_to_gimple_exe`:

| source | result | CPython |
|---|---|---|
| `S = "x"` / `class C(): var name = S` / `print(C().name)` | `0` | `x` |
| `S = "x"` / `class C(): name = S` (bare) | `0` | `x` |
| `S = "x"` / `class C(): var name: str = S` | `None` | `x` |
| `N = 7` / `class C(): var val = N` / `print(C().val)` | `0` | `7` |
| `class C(): var name = "hello"` (literal) | `hello` (right) | `hello` |

Every spelling fails the same way, so this is not a `var`-vs-bare divergence.

## Root cause (measured)

The generated C for the first row declares `int64_t _classattr_C__name;` and an
EMPTY `static void _mojo_classattr_init (void) {}` — the module-scope seeder in
`module_gen.py` (the `class_attr_inits` block that feeds
`_mojo_classattr_init`) emits init lines only for `StringLiteral` /
`IntLiteral` / `FloatLiteral` / container / `struct.Struct` literals; a
non-literal value falls into the `else: ctype = 'int64_t'` arm and emits
nothing. The module-level `class` statement itself is a no-op for this purpose
(`emit_stmts._gen_stmt_StructDef`'s docstring: "a module-level StructDef is
emitted by gen_module, never through here"), so no store `C.name = S` is
generated anywhere. For the `var` spellings there is a second compounding
mismatch: the visible field is typed `C *` (the "we don't know what this holds"
fallback) while the global is `int64_t`, so the allocator's per-instance init
(also gated on the two agreeing) never fires either. The read then hits the
unseeded field (`var` spellings) or the unseeded global (bare spelling).

## Next step

In the module-scope seeder, when the attribute's value is an `IdentExpr` that
names THIS module's own global, emit the store into `_mojo_classattr_init`
(the global is a static C variable in the same TU — `_classattr_C__name = S;`
is a plain assignment) and take the attribute's ctype from the module global's
own binding (the same table the module-globals struct/typedef block resolves
from), so the field/global type agreement the allocator init is gated on can
hold. A reference to another module's global, or an expression over globals
(`S + "!"`), is the harder half: it needs the value evaluated at module init
in the global's own type, which is where `_quick_type` with the module-globals
overlay would go, mirroring the fn-scoped parameter resolution the cell case
already has.

## Done when

```
S = "x"

class C():
    var name = S

def main():
    print(C().name)
```

prints `x` in `test_gimple_runner.py` (add the regression beside the
`gimple_nested_class_var_attr_*` cluster).
