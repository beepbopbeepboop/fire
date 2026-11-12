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

## Status (2026-11-12): partially fixed — module-global references

Landed: a module-scope class attribute whose value reads a global OF THIS
MODULE is now stored. `gen_module`'s top-level loop emits `C.attr = <value>`
at the class statement's position (`_module_class_attr_global_stores` in
`mojo/backend_gimple/module_gen.py`), after the global is assigned; the
`_classattr_` global and the struct field take the global's C type
(`_module_class_attr_global_ctype`, `_quick_type` over this module's
`_own_global_var_types`). Covered by `test_gimple_runner.py`:
`gimple_module_class_attr_from_module_global` (the Done-when case, passes),
`..._bare_and_int_from_module_global` (`name = S`, `val = N` → `x`, `7`), and
`..._expr_over_module_globals` (`S + "!"`, `N + 1`). All three fail on the
pre-fix tree (0 / blank output).

Still open:
- A value naming a global of ANOTHER module (`from m import S` then
  `class C(): var name = S`). The helper answers None for it (it only accepts
  this module's own globals), so it stays unstored, as before. Not measured
  this session. Next step: resolve the imported global's C storage
  (`<mod>_toplev.S` via `_global_to_module`) and type from the shared table
  under the same test, then store it at the class statement.
- A value calling a function or reading a name that is not a module global
  (`len(S)`, a builtin): answered None, unstored, unchanged.

## Done when (remaining)

The cross-module case above prints the imported value from a module-scope
class attribute, checked by a regression beside the `gimple_module_class_attr_*`
cluster. The three module-local cases already pass.
