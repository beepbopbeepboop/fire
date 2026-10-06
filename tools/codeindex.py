#!/usr/bin/env python3
"""codeindex.py -- fast local code-intelligence index for this repo.

Walks every top-level *.py file, parses each with the stdlib `ast` module,
and populates .codeindex.sqlite3 with tables describing functions, local
variable assignments, closures, calls, classes/fields, and imports -- so
structural questions about the codebase can be answered via SQL in
milliseconds instead of grep/instrument/rebuild cycles.

Usage:
    python3 tools/codeindex.py build
    python3 tools/codeindex.py query "<SQL>"
    python3 tools/codeindex.py name-collisions

See tools/codeindex.md for schema details and example queries.
"""

import ast
import builtins
import json
import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, ".codeindex.sqlite3")
BUILTINS = set(dir(builtins))

SCHEMA = """
CREATE TABLE functions (
    file TEXT, name TEXT, qualname TEXT, enclosing TEXT,
    lineno INTEGER, end_lineno INTEGER, is_nested INTEGER, args_json TEXT
);
CREATE TABLE locals (
    file TEXT, func_qualname TEXT, name TEXT, lineno INTEGER,
    kind TEXT, type_hint TEXT
);
CREATE TABLE refs (
    file TEXT, nested_func_qualname TEXT, name TEXT, lineno INTEGER
);
CREATE TABLE calls (
    file TEXT, caller_qualname TEXT, callee_name TEXT, lineno INTEGER
);
CREATE TABLE classes (file TEXT, name TEXT, lineno INTEGER);
CREATE TABLE class_fields (
    file TEXT, class_name TEXT, field_name TEXT, lineno INTEGER,
    annotation TEXT, in_init INTEGER
);
CREATE TABLE imports (file TEXT, module TEXT, names_json TEXT, lineno INTEGER);

CREATE INDEX idx_functions_qualname ON functions(qualname);
CREATE INDEX idx_locals_func ON locals(func_qualname);
CREATE INDEX idx_locals_name ON locals(name);
CREATE INDEX idx_calls_caller ON calls(caller_qualname);
CREATE INDEX idx_calls_callee ON calls(callee_name);
CREATE INDEX idx_class_fields_class ON class_fields(class_name);
"""

# Kind-family grouping used by the name-collisions report.
KIND_FAMILY = {
    "dict_literal": "dict", "dict_call": "dict",
    "list_literal": "list", "list_call": "list",
    "set_literal": "set", "set_call": "set",
}


def dotted_name(node):
    """Dotted attribute chain for a Name/Attribute node ('self.foo'), else None."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def classify_rhs(value):
    """Classify an assignment's RHS expression. Returns (kind, type_hint)."""
    if value is None:
        return "other", None
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return "dict_literal", None
    if isinstance(value, (ast.List, ast.ListComp)):
        return "list_literal", None
    if isinstance(value, (ast.Set, ast.SetComp)):
        return "set_literal", None
    if isinstance(value, ast.Constant):
        if isinstance(value.value, str):
            return "str_literal", None
        if isinstance(value.value, int) and not isinstance(value.value, bool):
            return "int_literal", None
        return "other", None
    if isinstance(value, ast.Call):
        name = dotted_name(value.func)
        if name in ("dict", "list", "set"):
            return f"{name}_call", name
        return "call", name
    return "other", None


def own_bound_names(node):
    """Names bound directly within node's body (params + any Store-context
    Name, which covers Assign/AnnAssign/AugAssign/For/With-as/walrus/except-as/
    comprehension targets), not descending into nested def/lambda bodies
    beyond recording their own name."""
    names = set(_param_names(node.args))

    def walk(n):
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(child.name)  # nested scope: don't descend
                continue
            if isinstance(child, ast.Lambda):
                continue  # lambda params are its own scope
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            walk(child)

    for stmt in node.body:
        walk(stmt)
    return names


def _param_names(args):
    names = [a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


class ScopeScanner(ast.NodeVisitor):
    """Scans one function's (or the module's) body, shallowly: records local
    assignments and calls into `rows`, and recurses into nested defs as new
    scopes (recording their function/refs/locals/calls rows too)."""

    def __init__(self, file, qualname, rows):
        self.file = file
        self.qualname = qualname  # None for module scope
        self.rows = rows

    def _local(self, name, lineno, kind, hint):
        if self.qualname is not None:
            self.rows["locals"].append((self.file, self.qualname, name, lineno, kind, hint))

    def _bind(self, target, value, lineno):
        if isinstance(target, ast.Name):
            kind, hint = classify_rhs(value)
            self._local(target.id, lineno, kind, hint)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                self._bind(e, None, lineno)

    def _scan_calls(self, expr):
        if expr is None:
            return
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Call):
                name = dotted_name(sub.func)
                if name is not None:
                    self.rows["calls"].append((self.file, self.qualname, name, sub.lineno))

    def visit_Assign(self, node):
        for t in node.targets:
            self._bind(t, node.value, node.lineno)
        self._scan_calls(node.value)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name):
            kind, hint = classify_rhs(node.value)
            if node.value is None or kind == "other":
                if node.annotation is not None:
                    kind = "annotation"
                    try:
                        hint = ast.unparse(node.annotation)
                    except Exception:
                        hint = None
            self._local(node.target.id, node.lineno, kind, hint)
        self._scan_calls(node.value)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name):
            self._local(node.target.id, node.lineno, "other", None)
        self._scan_calls(node.value)

    def visit_NamedExpr(self, node):
        if isinstance(node.target, ast.Name):
            kind, hint = classify_rhs(node.value)
            self._local(node.target.id, node.lineno, kind, hint)
        self.generic_visit(node)

    def visit_For(self, node):
        self._bind(node.target, None, node.lineno)
        self._scan_calls(node.iter)
        for child in node.body + node.orelse:
            self.visit(child)

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._bind(item.optional_vars, item.context_expr, node.lineno)
            self._scan_calls(item.context_expr)
        for child in node.body:
            self.visit(child)

    def visit_Call(self, node):
        name = dotted_name(node.func)
        if name is not None:
            self.rows["calls"].append((self.file, self.qualname, name, node.lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._handle_nested(node)

    def visit_AsyncFunctionDef(self, node):
        self._handle_nested(node)

    def _handle_nested(self, node):
        nested_qual = f"{self.qualname}.{node.name}" if self.qualname else node.name
        args_json = json.dumps(_arg_names(node.args))
        self.rows["functions"].append((
            self.file, node.name, nested_qual, self.qualname,
            node.lineno, getattr(node, "end_lineno", node.lineno), 1, args_json,
        ))
        own = own_bound_names(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id not in own and sub.id not in BUILTINS:
                self.rows["refs"].append((self.file, nested_qual, sub.id, sub.lineno))
        for stmt in node.body:
            ScopeScanner(self.file, nested_qual, self.rows).visit(stmt)


def _arg_names(args):
    names = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def scan_class(file, node, rows):
    rows["classes"].append((file, node.name, node.lineno))
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            try:
                ann = ast.unparse(stmt.annotation) if stmt.annotation is not None else None
            except Exception:
                ann = None
            rows["class_fields"].append((file, node.name, stmt.target.id, stmt.lineno, ann, 0))
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__init__":
            for sub in ast.walk(stmt):
                target, ann = None, None
                if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
                    target = sub.targets[0]
                elif isinstance(sub, ast.AnnAssign):
                    target = sub.target
                    try:
                        ann = ast.unparse(sub.annotation) if sub.annotation is not None else None
                    except Exception:
                        ann = None
                if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    rows["class_fields"].append((file, node.name, target.attr, sub.lineno, ann, 1))


def index_file(file, tree, rows):
    """Populate rows[...] lists for one parsed module."""
    for stmt in ast.walk(tree):
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            if isinstance(stmt, ast.Import):
                for a in stmt.names:
                    rows["imports"].append((file, a.name, json.dumps([a.name]), stmt.lineno))
            else:
                module = "." * stmt.level + (stmt.module or "")
                names = [a.name for a in stmt.names]
                rows["imports"].append((file, module, json.dumps(names), stmt.lineno))
        elif isinstance(stmt, ast.ClassDef):
            scan_class(file, stmt, rows)

    def record_top_level_func(node, qualname):
        rows["functions"].append((
            file, node.name, qualname, None,
            node.lineno, getattr(node, "end_lineno", node.lineno), 0,
            json.dumps(_arg_names(node.args)),
        ))
        for stmt in node.body:
            ScopeScanner(file, qualname, rows).visit(stmt)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            record_top_level_func(node, node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    record_top_level_func(item, f"{node.name}.{item.name}")

    # Module-level calls (not inside any function/class body).
    class ModuleCalls(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            pass

        def visit_AsyncFunctionDef(self, n):
            pass

        def visit_ClassDef(self, n):
            pass

        def visit_Call(self, n):
            name = dotted_name(n.func)
            if name is not None:
                rows["calls"].append((file, None, name, n.lineno))
            self.generic_visit(n)

    ModuleCalls().visit(tree)


def iter_repo_py_files():
    for entry in sorted(os.listdir(REPO_ROOT)):
        full = os.path.join(REPO_ROOT, entry)
        if os.path.isfile(full) and entry.endswith(".py"):
            yield full


INSERTS = {
    "functions": "INSERT INTO functions VALUES (?,?,?,?,?,?,?,?)",
    "locals": "INSERT INTO locals VALUES (?,?,?,?,?,?)",
    "refs": "INSERT INTO refs VALUES (?,?,?,?)",
    "calls": "INSERT INTO calls VALUES (?,?,?,?)",
    "classes": "INSERT INTO classes VALUES (?,?,?)",
    "class_fields": "INSERT INTO class_fields VALUES (?,?,?,?,?,?)",
    "imports": "INSERT INTO imports VALUES (?,?,?,?)",
}


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    rows = {name: [] for name in INSERTS}
    file_count = 0
    for full_path in iter_repo_py_files():
        rel = os.path.relpath(full_path, REPO_ROOT)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            print(f"skip {rel}: parse error: {e}", file=sys.stderr)
            continue
        file_count += 1
        index_file(rel, tree, rows)

    for table, sql in INSERTS.items():
        conn.executemany(sql, rows[table])
    conn.commit()
    conn.close()

    print(f"codeindex: built {DB_PATH}")
    print(f"  files indexed: {file_count}")
    for table in INSERTS:
        print(f"  {table}: {len(rows[table])}")


def query(sql):
    if not os.path.exists(DB_PATH):
        print(f"error: {DB_PATH} missing. Run `python3 tools/codeindex.py build` first.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
    except sqlite3.Error as e:
        print(f"SQL error: {e}", file=sys.stderr)
        sys.exit(1)
    rows = cur.fetchall()
    if not rows:
        print("(no rows)")
        return
    print("\t".join(rows[0].keys()))
    for r in rows:
        print("\t".join("" if v is None else str(v) for v in r))
    conn.close()


def name_collisions():
    if not os.path.exists(DB_PATH):
        print(f"error: {DB_PATH} missing. Run `python3 tools/codeindex.py build` first.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    kinds = tuple(KIND_FAMILY.keys())
    rows = conn.execute(
        f"SELECT file, func_qualname, name, lineno, kind FROM locals "
        f"WHERE kind IN ({','.join('?' for _ in kinds)}) "
        f"ORDER BY file, func_qualname, name, lineno",
        kinds,
    ).fetchall()

    groups = {}
    for r in rows:
        key = (r["file"], r["func_qualname"], r["name"])
        groups.setdefault(key, []).append((r["lineno"], KIND_FAMILY[r["kind"]], r["kind"]))

    found = False
    for (file, func_qualname, name), entries in sorted(groups.items()):
        if len({fam for _, fam, _ in entries}) > 1:
            found = True
            enclosing = func_qualname or "<module level>"
            detail = ", ".join(f"line {ln}:{kind}" for ln, _, kind in entries)
            print(f"{file}: {enclosing}(): '{name}' assigned conflicting container kinds -> {detail}")
    if not found:
        print("(no name collisions found)")
    conn.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "build":
        build()
    elif cmd == "query":
        if len(sys.argv) < 3:
            print('usage: python3 tools/codeindex.py query "<SQL>"', file=sys.stderr)
            sys.exit(1)
        query(sys.argv[2])
    elif cmd == "name-collisions":
        name_collisions()
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
