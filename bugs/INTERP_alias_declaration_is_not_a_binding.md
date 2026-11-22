# INTERP: a module- or function-level `alias` declaration cannot run

**Area:** `myinterpreter.py` (the statement executor), with the parser's
`alias` handling as context.

## Measured (this tree, master HEAD 5adfcb546 + the alias/unknown-decl fix)

```
python3 fire.py run .tmp/alias_probe.mojo
```

with

```
alias LIMIT = 2
fn main():
    print(LIMIT)
```

exits 1 with

```
.tmp/alias_probe.mojo:1:1: error: use of unknown declaration 'alias'
alias LIMIT = 2
^~~~~
```

The compiled path (`fire.py build`) compiles the same program, and
the equivalent `comptime LIMIT = 2` runs and prints `2`, so the interpreter
is the only path that refuses it.

## Cause

The parser has no `alias` declaration node. `alias LIMIT = 2` parses as two
statements:

```
ExprStmt(IdentExpr(name='alias', line=1, col=1))
AssignStmt(target=IdentExpr(name='LIMIT', ...), value=IntLiteral(2), is_alias=True)
```

`unknown_decl_check` knows `alias` is a keyword and the binding is now marked
`is_alias`, so the compile path is happy. The interpreter's
`execute_ExprStmt` has no such notion: it evaluates `IdentExpr('alias')` as an
ordinary name read, `Scope.get` raises `NameError: name 'alias' is not
defined`, and the driver renders it as a Mojo unknown-declaration diagnostic.
The same failure hits a local alias (`alias x = 5` inside a function), which
`test_comptime_assert_diagnostic.py` compiles but never runs.

Reproduced in-process without the CLI:

```
stmts = Parser(py_tokenize(src)).parse_module()
Interpreter(filename='t.mojo').execute(stmts[0])
# myinterpreter.py:8963 execute_ExprStmt -> eval_IdentExpr -> NameError 'alias'
```

## Exact next step

Either

1. skip the `ExprStmt(IdentExpr('alias'))` sentinel in `execute_ExprStmt` when
   the next statement is the matching `AssignStmt(is_alias=True)`, or
2. (preferred, and what removes the sentinel for good) change the parser to
   emit only the marked `AssignStmt` for an `alias` declaration and update its
   one pair-shaped consumer, `mojo/backend_gimple/module_gen.py`'s
   `_type_aliases` harvest (the `ExprStmt(alias) + AssignStmt` walk near
   `_gmi_prefold_toplevel_comptime`) to key on `is_alias`.

Either way add a run test next to `test_where_alias_diagnostic.py`'s
compile-only cases that `fire.py run`s a program reading a module `alias`, and
run `test_comptime_assert_diagnostic.py` for the local form.
