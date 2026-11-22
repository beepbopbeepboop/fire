# DIAGNOSTICS: an `alias` whose value is an unknown name is a hard error, so an undecided `where` clause cannot be undecided

**Area:** `unknown_decl_check.py` (`check_module`), with the expectation owned
by `test_where_alias_diagnostic.py::test_unfolderable_alias_clause_stays_accepted`.
**Where the branch shows:** the registered job `reg-where-alias-diagnostic`
(`python3 test_where_alias_diagnostic.py`) fails before it reaches its last
cases. Nothing to do with constant folding — see the control below.

## Measured (this tree, master HEAD 217ed8239 + an unrelated comptime change)

```
python3 tools/memslot.py --gb 8 --label w-alias -- python3 test_where_alias_diagnostic.py
```

runs silently through the first five cases (they print nothing on success) and
then raises:

```
SyntaxError: .../t.mojo:1:15: error: use of unknown declaration 'some_unknown_name'
alias LIMIT = some_unknown_name
              ^~~~~~~~~~~~~~~~~
```

for

```
alias LIMIT = some_unknown_name
def f[x: Int]() where x < LIMIT:
    pass
fn main():
    f[5]()
```

which the test requires to COMPILE: the alias value is not a foldable literal,
so the `where` clause is undecided and must not become a false positive. The
docstring at the top of the file says the same thing ("an undecided clause and
an ordinary module-level assignment must remain accepted"), and
`test_module_assignment_not_treated_as_constant` right below it passes, so the
alias form is the only one the unknown-declaration pass rejects.

## Control: pre-existing, not introduced by the fold change

The same snippet raises with **master's** `mojo/middle/comptime.py` exec'd over
the live module (so no branch edit is in play), and `unknown_decl_check.py`
grep for `comptime`/`fold`/`const` finds no folding dependency at all. Filed by
the `bug-comptime-declined-fold-condition-rep` lane as a separate bug, not
fixed there.

## Exact next step

`unknown_decl_check.check_module` walks reads and reports names no declaration
provides. The RHS of a module-level `alias` is a USE of whatever name it
spells, and the test's whole point is that an alias whose value cannot be
resolved must leave its consumer clause UNDECIDED rather than error.

The parser gives the statement no marker to key on: `alias LIMIT = X` is
`ExprStmt(IdentExpr 'alias')` at line 1 col 1 immediately followed by
`AssignStmt(target=IdentExpr LIMIT, value=IdentExpr X)` at line 1 col 7 (the
`alias` keyword is a bare identifier, as `_KEYWORDS` already records). So the
pair is identifiable by the keyword expression and the same `line`; the
narrowest fix is to teach `_Scan`/`unknown_reads` that the value subtree of an
`AssignStmt` in that pair is a declaration site (like `var`/`let`), not a read,
while a plain `X = <unknown name>` stays a read as today. Prefer giving the
parser an explicit marker over the line-pairing heuristic if either is cheap,
since two statements on one line would otherwise collide. Then re-run the one
job:

```
python3 tools/memslot.py --gb 8 --label w-alias -- python3 test_where_alias_diagnostic.py
```

and check that the sibling where-clause diagnostic tests
(`test_where_clause_diagnostic.py`, `test_predicate_where_diagnostic.py`,
`test_inferred_where_clause_diagnostic.py`) stay green — they pin the
provably-false refusals the same pass feeds.
