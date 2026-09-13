# codeindex.py

## Problem

This repo is a ~65,000-line hand-written Mojo compiler in Python
(`myinterpreter.py`, `mojo_compiler.py`, and the `gimple_*.py` codegen
backend). Debugging it has repeatedly meant grepping for a name, adding
print statements, and rebuilding, taking many minutes per question. A
recurring, expensive bug class is a bare local-variable name reused for
two different container shapes within the same Python function scope
(e.g. `_found = {}` in one branch, `_found = [None]` later in the same
function) — a plain Python name collision that silently changes the
codegen behavior and takes a long instrument/rebuild cycle to spot by
eye.

`tools/codeindex.py` parses every top-level `.py` file with the stdlib
`ast` module into a local SQLite database (`.codeindex.sqlite3`, a
derived artifact — not committed, rebuild any time with `build`) so
these structural questions can be answered with a SQL query in
milliseconds instead.

## CLI

```
python3 tools/codeindex.py build                 # (re)build the index
python3 tools/codeindex.py query "<SQL>"          # run arbitrary read-only SQL
python3 tools/codeindex.py name-collisions        # canned report (see below)
```

## Schema

- `functions(file, name, qualname, enclosing, lineno, end_lineno, is_nested, args_json)`
  — every `def`/`async def`, including nested ones and methods
  (`qualname` is dotted, e.g. `outer.inner` or `ClassName.method`).
- `locals(file, func_qualname, name, lineno, kind, type_hint)`
  — every local assignment (`Assign`/`AnnAssign`/`AugAssign`/`For`
  targets/`with ... as`/walrus) within a function, not recursing into
  nested `def`s. `kind` is one of `dict_literal`, `list_literal`,
  `set_literal`, `dict_call`, `list_call`, `set_call`, `str_literal`,
  `int_literal`, `call`, `annotation`, `other`.
- `refs(file, nested_func_qualname, name, lineno)`
  — free-variable references made by a nested `def` (closure capture).
- `calls(file, caller_qualname, callee_name, lineno)`
  — every `Call` with a plain `Name`/`Attribute` callee (`callee_name`
  is dotted, e.g. `self.foo`); `caller_qualname` is NULL for
  module-level calls.
- `classes(file, name, lineno)` and
  `class_fields(file, class_name, field_name, lineno, annotation, in_init)`
  — class-body annotated fields and `self.<field>` assignments found in
  `__init__` (best-effort).
- `imports(file, module, names_json, lineno)` — every `Import`/`ImportFrom`.

## Example queries

Find every site that assigns a container via `dict(...)`/`list(...)`/`set(...)`:

```
python3 tools/codeindex.py query \
  "SELECT file, func_qualname, name, lineno, kind FROM locals WHERE kind LIKE '%_call'"
```

Find all callers of a given function (by bare or dotted name):

```
python3 tools/codeindex.py query \
  "SELECT DISTINCT file, caller_qualname FROM calls WHERE callee_name LIKE '%load_module%'"
```

Find the name-collision report (bare local names assigned conflicting
dict/list/set kinds within the same enclosing function — the exact bug
class that has cost real debugging time in this codebase):

```
python3 tools/codeindex.py name-collisions
```
