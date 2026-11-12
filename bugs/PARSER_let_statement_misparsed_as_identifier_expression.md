# PARSER: a statement-level `let` declaration is mis-parsed as an identifier expression

A `let` in statement position is not dispatched by `Parser._parse_stmt`
(fire_compiler.py): only `var` is (the `t.value == 'var'` branch that routes
to `_parse_var_decl`). The `let` keyword token falls through to
expression/assignment parsing, where it is read as a plain identifier, and the
rest of the line is parsed as a separate assignment.

## What was run

    def main():
        let y = 2.5
        print(y)

via `python3 fire.py run .tmp/let_probe.mojo` (2026-11-12), and via a direct
`Parser.parse_module` AST dump of

    def main():
        let a = 2.5

## What was seen

The AST dump shows the mis-parse: `ExprStmt(IdentExpr('let'))` followed by a
separate `AssignStmt(a = 2.5)` — the `let` keyword is silently dropped and
the declaration never exists in the tree. At runtime:

    .tmp/let_probe.mojo:2:5: name 'let' is not defined. Did you mean: 'len'?

## What was expected

`let` is the Mojo constant-declaration keyword (a sibling of `var`):
`let y = 2.5` should parse as a `VarDecl` (the comptime path already consumes
it as a declaration sigil, see `_parse_comptime`'s `("var", "let")` branch).
Measured with the real compiler (`tools/mojo`, 2026-11-12), `let y = 2.5`
declares a Float64 constant exactly like `var` does.

## Impact

Any `let`-declared local is invisible to static analyses that read `VarDecl`
nodes — in particular the MLIR annotation check
(`_check_mlir_type_argument_calls` in fire_compiler.py, whose type table
records only `var` declarations): `let y = 2.5; foo(y)` to a
`__mlir_type.index` parameter is not refused here, where the real compiler
refuses it. Note that once the dispatch is in place, that check needs no
change: `let` declarations will land as `VarDecl` nodes and flow through the
existing table.

## Next step

Dispatch `let` in `Parser._parse_stmt` like `var` (extend the
`t.value == 'var'` branch to `in ("var", "let")`, and teach
`_parse_var_decl` — whose `self._expect("KW", 'var')` pins the spelling — to
accept `let`, or add a parallel `_parse_let_decl`). Add a regression test
next to the `var`-declaration tests asserting `let y = 2.5` parses as a
`VarDecl` and runs, and a `let`-declared argument to an `__mlir_type`
parameter is refused.

Found while measuring the real-compiler ground truth for the MLIR
annotation diagnostics (`error: invalid call to 'foo'` at a `__mlir_type.*`
argument, 2026-11-12); that bug is fixed for `var` and is unaffected by this
gap.
