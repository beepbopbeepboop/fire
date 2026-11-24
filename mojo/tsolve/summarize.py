"""The AST to `Program` pass of the whole-closure type solver (bugs/GIR_type_solver.md, 2.3).

`summarize_closure(root_path, root_stmts, load)` walks the import closure of the
root breadth-first, declares every module-level name, and then summarizes every
function body and every module's top-level code into flows (`summary.py`).

Three phases, so that a name can be used before the statement that binds it
in another module: (1) collect the closure, (2) declare each module's names and
the signatures of its functions and classes, (3) summarize bodies. Nothing in
phase 3 needs a later phase's answer.

A construct this pass does not model makes the function it sits in
UNDECIDABLE (`FnSummary.decidable = False`): no answer is claimed for it, and
its flows are not trusted. Missing a flow could make a type too narrow, so the
pass never guesses silently. An expression it does not model is `dyn` as well.

Rules (doc/GIR.md, rule 2): plain classes, annotated fields, no closures, no
lambdas, no `re`, no tuple unpacking, no `getattr`, no generators.
"""
from __future__ import annotations

import fire_compiler as N
from mojo.tsolve import sty
from mojo.tsolve.summary import (
    ClassSummary, FnSummary, Program, const_term, func_key, op_term, var_term,
    Term,
)


class _Binding:
    """What a name means in a scope.

    kind  'func' (key = FuncKey) | 'class' (key = class name) | 'module'
          (key = abspath) | 'var' (var = TVar) | 'alias' (src_mod, src_name:
          imported from another module) | 'dyn' (known to exist, type unknown)
    """

    def __init__(self, kind: str, key: str, var: int, src_mod: str, src_name: str):
        self.kind: str = kind
        self.key: str = key
        self.var: int = var
        self.src_mod: str = src_mod
        self.src_name: str = src_name


class _Mod:
    def __init__(self, path: str, stmts: list):
        self.path: str = path
        self.stmts: list = stmts
        self.names: dict = {}        # name -> _Binding (module level)
        self.imports: dict = {}      # module ref -> abspath, or '' when external
        self.wildcards: list = []    # abspaths of `from m import *`
        self.submods: dict = {}      # `from pkg import sub`: local name -> abspath of pkg.sub


class _Scope:
    """One function body (or the module's top level, when `fn` is None)."""

    def __init__(self, mod: _Mod, cls: str, cs, fn, parent):
        self.mod: _Mod = mod
        self.cls: str = cls          # the class of a method, else ''
        self.cs: object = cs         # its ClassSummary, else None
        self.fn: object = fn         # its FnSummary, else None (module level)
        self.parent: object = parent  # the enclosing _Scope, for a nested def/lambda
        self.locals: dict = {}       # name -> _Binding
        self.narrow: dict = {}       # name -> class, inside `isinstance(name, C)`
        self.globals: dict = {}      # names declared `global`
        self.nonlocals: dict = {}    # names declared `nonlocal`
        self.deferred: list = []     # nested defs, summarized after this body


def _is_node(x) -> bool:
    return type(x).__module__ == 'fire_compiler'


def _walk_stmts(stmts: list, out: list) -> None:
    """Append every statement of `stmts`, and of the blocks inside them, to `out`.

    A nested `def` or `struct` is appended but not entered: its body is a
    different scope."""
    for st in stmts:
        out.append(st)
        if isinstance(st, (N.FunctionDef, N.StructDef)):
            continue
        for block in _sub_blocks(st):
            _walk_stmts(block, out)


def _sub_blocks(st) -> list:
    blocks = []
    if isinstance(st, N.IfStmt):
        blocks.append(st.then_body)
        for pair in st.elifs:
            blocks.append(pair[1])
        if st.else_body is not None:
            blocks.append(st.else_body)
    elif isinstance(st, (N.WhileStmt, N.ForStmt)):
        blocks.append(st.body)
        if st.else_body is not None:
            blocks.append(st.else_body)
    elif isinstance(st, N.TryStmt):
        blocks.append(st.body)
        for h in st.handlers:
            blocks.append(h.body)
        if st.else_body is not None:
            blocks.append(st.else_body)
        if st.finally_body is not None:
            blocks.append(st.finally_body)
    elif isinstance(st, N.WithStmt):
        blocks.append(st.body)
    return blocks


def _terminates(stmts: list) -> bool:
    """True when control can never fall off the end of `stmts`."""
    if not stmts:
        return False
    last = stmts[len(stmts) - 1]
    if isinstance(last, (N.ReturnStmt, N.RaiseStmt)):
        return True
    if isinstance(last, N.IfStmt):
        if last.else_body is None:
            return False
        if not _terminates(last.then_body) or not _terminates(last.else_body):
            return False
        for pair in last.elifs:
            if not _terminates(pair[1]):
                return False
        return True
    if isinstance(last, N.TryStmt):
        if last.finally_body is not None and _terminates(last.finally_body):
            return True
        if not _terminates(last.body):
            return False
        for h in last.handlers:
            if not _terminates(h.body):
                return False
        return True
    if isinstance(last, N.WithStmt):
        return _terminates(last.body)
    if isinstance(last, N.WhileStmt):
        cond = last.condition
        forever = (isinstance(cond, N.BoolLiteral) and cond.value) or (
            isinstance(cond, N.IdentExpr) and cond.name == 'True')
        if forever:
            out: list = []
            _walk_stmts(last.body, out)
            for st in out:
                if isinstance(st, N.BreakStmt):
                    return False
            return True
    return False


def _target_names(target) -> list:
    """The names bound by a `for`/comprehension target, or None when it is not
    a plain name or a tuple of plain names. A target is a string such as `i`,
    `k, v` or `(i, j)`, or a node."""
    if isinstance(target, N.IdentExpr):
        return [target.name]
    if not isinstance(target, str):
        return None
    s = target.strip()
    if s.startswith('(') and s.endswith(')'):
        s = s[1:len(s) - 1]
    names = []
    for part in sty.split_top(s, ','):
        if part == '':
            continue
        if not part.isidentifier():
            return None
        names.append(part)
    return names


def _is_tuple_target(target) -> bool:
    if isinstance(target, str):
        return ',' in target
    return isinstance(target, N.TupleExpr)


def _fstring_body(value: str) -> str:
    """The text between the quotes of an f-string literal's value (`f"x{a}"` -> `x{a}`)."""
    i = 0
    while i < len(value) and value[i] in 'fFtT':
        i += 1
    body = value[i:]
    for q in ('\'\'\'', '"""', "'", '"'):
        if body.startswith(q) and body.endswith(q) and len(body) >= 2 * len(q):
            return body[len(q):len(body) - len(q)]
    return body


def _fstring_exprs(body: str):
    """The source text of each replacement field `{...}` of an f-string body, or None
    when a field is not closed. `{{` and `}}` are literal braces. A conversion (`!r`)
    or a format spec (`:>3`) at the field's top level is not part of the expression,
    and a trailing `=` (the `{x=}` form) is not either."""
    out = []
    i = 0
    n = len(body)
    while i < n:
        if body[i] != '{':
            i += 1
            continue
        if i + 1 < n and body[i + 1] == '{':
            i += 2
            continue
        j = i + 1
        depth = 0
        cut = -1
        while j < n:
            c = body[j]
            if c == '}' and depth == 0:
                break
            if c == '(' or c == '[' or c == '{':
                depth += 1
            elif c == ')' or c == ']' or c == '}':
                depth -= 1
            elif depth == 0 and cut < 0:
                if c == ':' or (c == '!' and j + 1 < n and body[j + 1] != '='):
                    cut = j
            j += 1
        if j >= n:
            return None
        end = cut if cut >= 0 else j
        expr = body[i + 1:end].strip()
        if expr.endswith('='):
            expr = expr[:len(expr) - 1].strip()
        out.append(expr)
        i = j + 1
    return out


def _parse_expression(text: str):
    """The expression node of `text`, or None when it does not parse."""
    try:
        return N.Parser(N.py_tokenize(text))._parse_expr(0)
    except Exception:
        return None


def _find_imports(obj, out: list) -> None:
    if isinstance(obj, (list, tuple)):
        for x in obj:
            _find_imports(x, out)
        return
    if not _is_node(obj):
        return
    if isinstance(obj, (N.ImportStmt, N.FromImportStmt)):
        out.append(obj)
    for v in vars(obj).values():
        _find_imports(v, out)


def _import_refs(node) -> list:
    if isinstance(node, N.ImportStmt):
        return [node.module]
    refs = [node.module]
    for pair in node.names:
        refs.append(node.module + '.' + pair[0])
    return refs


def _self_field_targets(stmts: list, out: list) -> None:
    """Append the names `X` of every `self.X = ...` (and `+=`, tuple targets) in `stmts`."""
    flat: list = []
    _walk_stmts(stmts, flat)
    for st in flat:
        targets = []
        if isinstance(st, N.AssignStmt):
            targets.append(st.target)
        elif isinstance(st, N.AugAssignStmt):
            targets.append(st.target)
        elif isinstance(st, N.MultiAssignStmt):
            for t in st.targets:
                targets.append(t)
        for t in targets:
            _self_target_names(t, out)


def _self_target_names(t, out: list) -> None:
    if isinstance(t, N.MemberExpr):
        if isinstance(t.obj, N.IdentExpr) and t.obj.name == 'self':
            if t.member not in out:
                out.append(t.member)
    elif isinstance(t, N.TupleExpr):
        for el in t.elements:
            _self_target_names(el, out)


def _assigned_names(stmts: list, out: dict) -> None:
    """Every name bound by an assignment, `for`, `with`, `except` or `var`
    anywhere in `stmts` (nested blocks included, nested defs excluded)."""
    flat: list = []
    _walk_stmts(stmts, flat)
    for st in flat:
        if isinstance(st, N.AssignStmt):
            _name_targets(st.target, st.type_ann, out)
        elif isinstance(st, N.AugAssignStmt):
            _name_targets(st.target, None, out)
        elif isinstance(st, N.MultiAssignStmt):
            for t in st.targets:
                _name_targets(t, None, out)
        elif isinstance(st, N.VarDecl):
            _add_ann(out, st.name, st.type_ann)
        elif isinstance(st, N.ForStmt):
            names = _target_names(st.target)
            if names is not None:
                for n in names:
                    _add_ann(out, n, None)
        elif isinstance(st, N.TryStmt):
            for h in st.handlers:
                if h.name:
                    _add_ann(out, h.name, None)
        elif isinstance(st, N.WithStmt):
            for item in st.items:
                if item.alias:
                    _add_ann(out, item.alias, None)


def _name_targets(t, ann, out: dict) -> None:
    if isinstance(t, N.IdentExpr):
        _add_ann(out, t.name, ann)
    elif isinstance(t, N.TupleExpr):
        for el in t.elements:
            _name_targets(el, None, out)


def _add_ann(out: dict, name: str, ann) -> None:
    """Record a bound name. `out[name]` is its annotation text (or '' for none),
    and a name annotated two different ways is marked `dyn` (the value `None`)."""
    if name not in out:
        out[name] = ann if ann else ''
        return
    prev = out[name]
    if prev is None:
        return
    if ann:
        if prev == '':
            out[name] = ann
        elif prev != ann:
            out[name] = None


class _Summarizer:
    def __init__(self, root_path: str, root_stmts: list, load):
        self.prog: Program = Program()
        self.load: object = load
        self.root_path: str = root_path
        self.root_stmts: list = root_stmts
        self.mods: dict = {}         # abspath -> _Mod
        self.order: list = []        # _Mod in breadth-first closure order
        self.class_names: dict = {}  # the names of the unique classes (for annotations)
        self.class_list: list = []   # every ClassSummary, duplicates included
        self.pending: list = []      # (FnSummary, node, mod, ClassSummary or None)

    # ── phase 1: the closure ────────────────────────────────────────────

    def collect(self) -> None:
        queue = [(self.root_path, self.root_stmts)]
        seen: dict = {self.root_path: True}
        head = 0
        while head < len(queue):
            path = queue[head][0]
            stmts = queue[head][1]
            head += 1
            mod = _Mod(path, stmts)
            self.mods[path] = mod
            self.order.append(mod)
            found: list = []
            _find_imports(stmts, found)
            for node in found:
                for ref in _import_refs(node):
                    if ref in mod.imports:
                        continue
                    res = self.load(ref, path)
                    if res is None:
                        mod.imports[ref] = ''
                        continue
                    apath = res[0]
                    mod.imports[ref] = apath
                    if apath not in seen:
                        seen[apath] = True
                        queue.append((apath, res[1]))

    # ── phase 2: declarations ───────────────────────────────────────────

    def declare(self) -> None:
        counts: dict = {}
        for mod in self.order:
            for st in mod.stmts:
                if isinstance(st, N.StructDef):
                    counts[st.name] = counts.get(st.name, 0) + 1
        for name in counts:
            if counts[name] == 1:
                self.class_names[name] = True
        for mod in self.order:
            self._declare_module(mod)
        for mod in self.order:
            self._resolve_wildcards(mod)
        for cs in self.class_list:
            for name in cs.fields:
                self.prog.field_index.setdefault(name, []).append(cs.fields[name])

    def _declare_module(self, mod: _Mod) -> None:
        for st in mod.stmts:
            if isinstance(st, N.FunctionDef):
                self._declare_module_fn(mod, st)
            elif isinstance(st, N.StructDef):
                self._declare_struct(mod, st)
            elif isinstance(st, N.ImportStmt):
                self._bind_import(mod.names, mod, st)
            elif isinstance(st, N.FromImportStmt):
                path = mod.imports.get(st.module, '')
                if st.wildcard:
                    if path:
                        mod.wildcards.append(path)
                for pair in st.names:
                    local = pair[1] if pair[1] else pair[0]
                    if path:
                        mod.names[local] = _Binding('alias', '', -1, path, pair[0])
                        sub = mod.imports.get(st.module + '.' + pair[0], '')
                        if sub:
                            mod.submods[local] = sub
                    else:
                        mod.names[local] = _Binding('dyn', '', -1, '', '')
            elif isinstance(st, N.AssignStmt):
                if isinstance(st.target, N.IdentExpr):
                    self._declare_module_var(mod, st.target.name, st.type_ann)
            elif isinstance(st, N.VarDecl):
                self._declare_module_var(mod, st.name, st.type_ann)
            elif isinstance(st, N.MultiAssignStmt):
                for t in st.targets:
                    if isinstance(t, N.IdentExpr):
                        self._declare_module_var(mod, t.name, None)

    def _bind_import(self, names: dict, mod: _Mod, st) -> None:
        """`import m` / `import m as x` binds the name to the module. A dotted
        `import a.b` without an alias binds `a` to a package it does not model
        as a module, so it is `dyn`."""
        path = mod.imports.get(st.module, '')
        name = st.alias if st.alias else st.module
        if path and '.' not in name:
            names[name] = _Binding('module', path, -1, '', '')
        else:
            names[name] = _Binding('dyn', '', -1, '', '')

    def _declare_module_var(self, mod: _Mod, name: str, ann) -> None:
        b = mod.names.get(name)
        if b is not None and b.kind == 'var':
            return
        var = self.prog.new_var(name)
        if ann:
            self.prog.pin(var, sty.from_annotation(ann, self.class_names))
        mod.names[name] = _Binding('var', '', var, '', '')

    def _declare_module_fn(self, mod: _Mod, node) -> None:
        key = func_key(mod.path, node.name)
        prev = mod.names.get(node.name)
        if prev is not None and prev.kind == 'func':
            # A second definition of one name: an overload set. Both are undecidable.
            self.prog.fns[prev.key].decidable = False
            mod.names[node.name] = _Binding('dyn', '', -1, '', '')
            fs = self._new_fn(mod.path, node.name, '', node, '')
            fs.decidable = False
            self.pending.append((fs, node, mod, None))
            return
        fs = self._new_fn(mod.path, node.name, '', node, key)
        self.prog.fns[key] = fs
        mod.names[node.name] = _Binding('func', key, -1, '', '')
        self.pending.append((fs, node, mod, None))

    def _declare_struct(self, mod: _Mod, node) -> None:
        name = node.name
        bases = []
        for b in node.bases:
            bases.append(b)
        cs = ClassSummary(name, mod.path, bases)
        self.class_list.append(cs)
        prev = self.prog.classes.get(name)
        if prev is not None:
            prev.unique = False
            cs.unique = False
        else:
            self.prog.classes[name] = cs
        mod.names[name] = _Binding('class', name, -1, '', '')
        for f in node.fields:
            if isinstance(f, N.VarDecl):
                var = self.prog.new_var(f.name)
                if f.type_ann:
                    self.prog.pin(var, sty.from_annotation(f.type_ann, self.class_names))
                cs.fields[f.name] = var
        for m in node.methods:
            if isinstance(m, N.FunctionDef):
                names: list = []
                _self_field_targets(m.body, names)
                for fname in names:
                    if fname not in cs.fields:
                        cs.fields[fname] = self.prog.new_var(fname)
        for m in node.methods:
            if isinstance(m, N.FunctionDef):
                key = func_key(mod.path, name + '.' + m.name)
                fs = self._new_fn(mod.path, m.name, name, m, '')
                if key in self.prog.fns:
                    fs.decidable = False
                else:
                    fs.key = key
                    self.prog.fns[key] = fs
                cs.methods[m.name] = fs
                self.pending.append((fs, m, mod, cs))

    def _new_fn(self, path: str, name: str, cls: str, node, key: str) -> FnSummary:
        fs = FnSummary(key, path, name, cls)
        fs.decidable = not (node.decorators or node.is_generator or node.is_async)
        for pair in node.params:
            pname = pair[0]
            ptype = pair[1]
            var = self.prog.new_var(pname)
            fs.params.append(var)
            fs.param_names.append(pname)
            if pname.startswith('*'):
                self.prog.pin(var, sty.DYN)
            elif pname == 'self' and cls and cls in self.class_names:
                self.prog.pin(var, sty.struct_of(cls))
            elif pname == 'self' and cls:
                self.prog.pin(var, sty.DYN)
            elif ptype:
                self.prog.pin(var, sty.from_annotation(ptype, self.class_names))
        fs.ret = self.prog.new_var(name + '.ret')
        if node.return_type:
            fs.annotated_ret = True
            self.prog.pin(fs.ret, sty.from_annotation(node.return_type, self.class_names))
        elif not fs.decidable:
            self.prog.pin(fs.ret, sty.DYN)
        return fs

    def _resolve_wildcards(self, mod: _Mod) -> None:
        for path in mod.wildcards:
            target = self.mods.get(path)
            if target is None:
                continue
            for name in target.names:
                if name.startswith('_') or name in mod.names:
                    continue
                mod.names[name] = _Binding('alias', '', -1, path, name)
        # `from pkg import sub` names the submodule when `pkg` has no such name.
        for name in mod.submods:
            b = mod.names.get(name)
            if b is None or b.kind != 'alias':
                continue
            if self.resolve_name(b.src_mod, b.src_name) is None:
                mod.names[name] = _Binding('module', mod.submods[name], -1, '', '')

    def resolve_name(self, path: str, name: str, depth: int = 0):
        """What `name` means at the top level of module `path` (following imports)."""
        mod = self.mods.get(path)
        if mod is None or depth > 32:
            return None
        b = mod.names.get(name)
        if b is None:
            return None
        if b.kind == 'alias':
            if not b.src_mod:
                return None
            return self.resolve_name(b.src_mod, b.src_name, depth + 1)
        return b

    # ── phase 3: bodies ─────────────────────────────────────────────────

    def summarize(self) -> None:
        for mod in self.order:
            scope = _Scope(mod, '', None, None, None)
            for st in mod.stmts:
                if isinstance(st, (N.FunctionDef, N.StructDef, N.ImportStmt, N.FromImportStmt)):
                    continue
                self._stmt(scope, st)
        for item in self.pending:
            self._summarize_fn(item[0], item[1], item[2], item[3], None)

    def _summarize_fn(self, fs: FnSummary, node, mod: _Mod, cs, parent) -> None:
        scope = _Scope(mod, fs.cls, cs, fs, parent)
        for i in range(len(node.params)):
            pname = node.params[i][0]
            bare = pname.lstrip('*')
            scope.locals[bare] = _Binding('var', '', fs.params[i], '', '')
        self._predeclare(scope, node.body)
        for pname in node.param_defaults:
            dexpr = node.param_defaults[pname]
            if dexpr is None:
                continue
            dterm = self._term(scope, dexpr)
            idx = _param_slot(fs, pname)
            if idx >= 0:
                self.prog.add_flow(dterm, fs.params[idx])
        for st in node.body:
            self._stmt(scope, st)
        self._run_deferred(scope)
        if not _terminates(node.body):
            self.prog.add_flow(const_term(sty.NONE), fs.ret)

    def _run_deferred(self, scope: _Scope) -> None:
        i = 0
        while i < len(scope.deferred):
            item = scope.deferred[i]
            i += 1
            self._summarize_fn(item[0], item[1], item[2], item[3], item[4])

    def _predeclare(self, scope: _Scope, body: list) -> None:
        """Create the variable of every name a body binds, before its statements.

        Flows are flow-insensitive, so a read that comes before the statement
        that binds the name in source order (a loop body) must still see the
        variable. An annotated name is pinned to its annotation."""
        flat: list = []
        _walk_stmts(body, flat)
        for st in flat:
            if isinstance(st, N.GlobalStmt):
                for n in st.names:
                    scope.globals[n] = True
            elif isinstance(st, N.NonlocalStmt):
                for n in st.names:
                    scope.nonlocals[n] = True
        names: dict = {}
        _assigned_names(body, names)
        for n in names:
            if n in scope.globals or n in scope.nonlocals or n in scope.locals:
                continue
            if names[n] is None:
                var = self.prog.new_var(n)
                self.prog.pin(var, sty.DYN)
            else:
                var = self.prog.new_var(n)
                if names[n]:
                    self.prog.pin(var, sty.from_annotation(names[n], self.class_names))
            scope.locals[n] = _Binding('var', '', var, '', '')

    # ── statements ──────────────────────────────────────────────────────

    def _undecidable(self, scope: _Scope) -> None:
        if scope.fn is not None:
            scope.fn.decidable = False

    def _block(self, scope: _Scope, stmts: list) -> None:
        for st in stmts:
            self._stmt(scope, st)

    def _stmt(self, scope: _Scope, st) -> None:
        if isinstance(st, N.ExprStmt):
            self._term(scope, st.value)
        elif isinstance(st, N.AssignStmt):
            v = self._term(scope, st.value)
            self._assign(scope, st.target, v)
        elif isinstance(st, N.MultiAssignStmt):
            v = self._term(scope, st.value)
            for i in range(len(st.targets)):
                self._assign(scope, st.targets[i], op_term('slot', str(i), [v]))
        elif isinstance(st, N.AugAssignStmt):
            cur = self._term(scope, st.target)
            val = self._term(scope, st.value)
            op = st.op
            if op.endswith('=') and len(op) > 1:
                op = op[:len(op) - 1]
            if op == '/':
                new = const_term(sty.FLOAT)
            elif op in _ARITH_OPS:
                new = op_term('join', '', [cur, val])
            else:
                new = const_term(sty.DYN)
            self._assign(scope, st.target, new)
        elif isinstance(st, N.VarDecl):
            var = self._local_var(scope, st.name)
            if st.value is not None:
                self.prog.add_flow(self._term(scope, st.value), var)
        elif isinstance(st, N.ReturnStmt):
            if scope.fn is None or scope.fn.ret < 0:
                return
            if st.value is None:
                self.prog.add_flow(const_term(sty.NONE), scope.fn.ret)
            else:
                self.prog.add_flow(self._term(scope, st.value), scope.fn.ret)
        elif isinstance(st, N.IfStmt):
            self._term(scope, st.condition)
            narrowed = self._isinstance_narrow(scope, st.condition)
            if narrowed is None:
                self._block(scope, st.then_body)
            else:
                name = narrowed[0]
                cls = narrowed[1]
                saved = scope.narrow.get(name)
                scope.narrow[name] = cls
                self._block(scope, st.then_body)
                if saved is None:
                    del scope.narrow[name]
                else:
                    scope.narrow[name] = saved
            for pair in st.elifs:
                self._term(scope, pair[0])
                self._block(scope, pair[1])
            if st.else_body is not None:
                self._block(scope, st.else_body)
        elif isinstance(st, N.WhileStmt):
            self._term(scope, st.condition)
            self._block(scope, st.body)
            if st.else_body is not None:
                self._block(scope, st.else_body)
        elif isinstance(st, N.ForStmt):
            if st.is_async:
                self._undecidable(scope)
            it = self._term(scope, st.iterable)
            self._bind_target(scope, st.target, op_term('elem', '', [it]))
            self._block(scope, st.body)
            if st.else_body is not None:
                self._block(scope, st.else_body)
        elif isinstance(st, N.TryStmt):
            self._block(scope, st.body)
            for h in st.handlers:
                if h.name:
                    self.prog.add_flow(const_term(sty.DYN), self._local_var(scope, h.name))
                self._block(scope, h.body)
            if st.else_body is not None:
                self._block(scope, st.else_body)
            if st.finally_body is not None:
                self._block(scope, st.finally_body)
        elif isinstance(st, N.WithStmt):
            if st.is_async:
                self._undecidable(scope)
            for item in st.items:
                self._term(scope, item.expr)
                if item.alias:
                    self.prog.add_flow(const_term(sty.DYN), self._local_var(scope, item.alias))
            self._block(scope, st.body)
        elif isinstance(st, N.RaiseStmt):
            if st.value is not None:
                self._term(scope, st.value)
        elif isinstance(st, N.AssertStmt):
            self._term(scope, st.value)
            if st.msg is not None:
                self._term(scope, st.msg)
        elif isinstance(st, (N.BreakStmt, N.ContinueStmt, N.PassStmt, N.NonlocalStmt)):
            return
        elif isinstance(st, N.GlobalStmt):
            return
        elif isinstance(st, N.DelStmt):
            for t in st.targets:
                self._term(scope, t)
        elif isinstance(st, N.ImportStmt):
            self._bind_local_import(scope, st)
        elif isinstance(st, N.FromImportStmt):
            self._bind_local_from_import(scope, st)
        elif isinstance(st, N.FunctionDef):
            self._nested_def(scope, st)
        else:
            self._undecidable(scope)

    def _bind_local_import(self, scope: _Scope, st) -> None:
        self._bind_import(scope.locals, scope.mod, st)

    def _bind_local_from_import(self, scope: _Scope, st) -> None:
        path = scope.mod.imports.get(st.module, '')
        for pair in st.names:
            local = pair[1] if pair[1] else pair[0]
            if path:
                scope.locals[local] = _Binding('alias', '', -1, path, pair[0])
            else:
                scope.locals[local] = _Binding('dyn', '', -1, '', '')
        if st.wildcard:
            self._undecidable(scope)

    def _nested_def(self, scope: _Scope, node) -> None:
        # A def inside a body is a value of unknown type; its own body still
        # contributes flows (its calls feed the parameters of what it calls).
        scope.locals[node.name] = _Binding('dyn', '', -1, '', '')
        fs = self._new_fn(scope.mod.path, node.name, '', node, '')
        fs.decidable = False
        scope.deferred.append((fs, node, scope.mod, scope.cs, scope))

    def _isinstance_narrow(self, scope: _Scope, cond):
        if not isinstance(cond, N.CallExpr):
            return None
        if not isinstance(cond.func, N.IdentExpr) or cond.func.name != 'isinstance':
            return None
        if len(cond.args) != 2:
            return None
        subject = cond.args[0]
        klass = cond.args[1]
        if not isinstance(subject, N.IdentExpr) or not isinstance(klass, N.IdentExpr):
            return None
        b = self._lookup(scope, klass.name)
        if b is None or b.kind != 'class':
            return None
        return [subject.name, b.key]

    def _assign(self, scope: _Scope, target, value: Term) -> None:
        if isinstance(target, N.IdentExpr):
            self.prog.add_flow(value, self._local_var(scope, target.name))
        elif isinstance(target, N.MemberExpr):
            self._term(scope, target.obj)
            var = self._member_target_var(scope, target)
            # None: no class in the closure declares this field, so no read of any
            # declared field can see the store. It flows nowhere.
            if var is not None:
                for v in var:
                    self.prog.add_flow(value, v)
        elif isinstance(target, N.SubscriptExpr):
            conts = self._lvalue_vars(scope, target.obj)
            key = self._term(scope, target.index)
            if not conts:
                self._undecidable(scope)
                return
            for v in conts:
                self.prog.add_flow(op_term('grow', 'setitem', [var_term(v), key, value]), v)
        elif isinstance(target, N.TupleExpr):
            for i in range(len(target.elements)):
                self._assign(scope, target.elements[i], op_term('slot', str(i), [value]))
        else:
            self._undecidable(scope)

    def _bind_target(self, scope: _Scope, target, el: Term) -> None:
        names = _target_names(target)
        if names is None:
            self._undecidable(scope)
            return
        if not _is_tuple_target(target):
            self.prog.add_flow(el, self._local_var(scope, names[0]))
            return
        for i in range(len(names)):
            self.prog.add_flow(op_term('slot', str(i), [el]), self._local_var(scope, names[i]))

    # ── names ───────────────────────────────────────────────────────────

    def _lookup(self, scope: _Scope, name: str):
        """The binding of `name` as seen from `scope`: a local of this body or an
        enclosing one, else the module's top level. None when it is not bound."""
        s = scope
        while s is not None:
            if name in s.globals:
                return self.resolve_name(scope.mod.path, name)
            b = s.locals.get(name)
            if b is not None:
                if b.kind == 'alias':
                    return self.resolve_name(b.src_mod, b.src_name)
                return b
            s = s.parent
        return self.resolve_name(scope.mod.path, name)

    def _local_var(self, scope: _Scope, name: str) -> int:
        """The variable an assignment to `name` writes."""
        if scope.fn is None:
            b = scope.mod.names.get(name)
            if b is not None and b.kind == 'var':
                return b.var
            var = self.prog.new_var(name)
            scope.mod.names[name] = _Binding('var', '', var, '', '')
            return var
        if name in scope.globals:
            b = scope.mod.names.get(name)
            if b is not None and b.kind == 'var':
                return b.var
            var = self.prog.new_var(name)
            scope.mod.names[name] = _Binding('var', '', var, '', '')
            return var
        if name in scope.nonlocals:
            s = scope.parent
            while s is not None:
                b = s.locals.get(name)
                if b is not None and b.kind == 'var':
                    return b.var
                s = s.parent
        b = scope.locals.get(name)
        if b is not None and b.kind == 'var':
            return b.var
        var = self.prog.new_var(name)
        scope.locals[name] = _Binding('var', '', var, '', '')
        return var

    def _lvalue_vars(self, scope: _Scope, node) -> list:
        """The variables a write through `node` (a container or an object) reaches."""
        if isinstance(node, N.IdentExpr):
            b = self._lookup(scope, node.name)
            if b is None:
                return [self._local_var(scope, node.name)]
            if b.kind == 'var':
                return [b.var]
            return []
        if isinstance(node, N.MemberExpr):
            return self._member_target_var(scope, node) or []
        return []

    def _member_target_var(self, scope: _Scope, node):
        """The field variables a store to `node.member` writes, or None."""
        if isinstance(node.obj, N.IdentExpr) and node.obj.name == 'self' and scope.cs is not None:
            v = self.prog.find_field_var_in(scope.cs, node.member)
            if v is None:
                return None
            return [v]
        found = self.prog.field_index.get(node.member)
        if not found:
            return None
        return list(found)

    # ── expressions ─────────────────────────────────────────────────────

    def _term(self, scope: _Scope, e) -> Term:
        """The term of expression `e`. Its sub-expressions' flows are added too."""
        if isinstance(e, N.IntLiteral):
            return const_term(sty.INT)
        if isinstance(e, N.FloatLiteral):
            return const_term(sty.FLOAT)
        if isinstance(e, N.BoolLiteral):
            return const_term(sty.BOOL)
        if isinstance(e, N.NoneLiteral):
            return const_term(sty.NONE)
        if isinstance(e, N.StringLiteral):
            if e.is_bytes or e.is_tstring:
                return const_term(sty.DYN)
            if e.is_interpolated:
                self._fstring_fields(scope, e.value)
            return const_term(sty.STR)
        if isinstance(e, N.IdentExpr):
            return self._ident(scope, e.name)
        if isinstance(e, N.CallExpr):
            return self._call(scope, e)
        if isinstance(e, N.BinaryOp):
            return self._binop(scope, e)
        if isinstance(e, N.CompareChain):
            for o in e.operands:
                self._term(scope, o)
            return const_term(sty.BOOL)
        if isinstance(e, N.UnaryOp):
            t = self._term(scope, e.operand)
            if e.op == 'not':
                return const_term(sty.BOOL)
            return t
        if isinstance(e, N.TernaryExpr):
            self._term(scope, e.condition)
            return op_term('join', '', [self._term(scope, e.then_val),
                                        self._term(scope, e.else_val)])
        if isinstance(e, N.LambdaExpr):
            return self._lambda(scope, e)
        if isinstance(e, N.MemberExpr):
            return self._member(scope, e)
        if isinstance(e, N.SubscriptExpr):
            obj = self._term(scope, e.obj)
            if isinstance(e.index, N.SliceExpr):
                self._slice_parts(scope, e.index)
                return obj
            if isinstance(e.index, N.IntLiteral):
                return op_term('slot', str(e.index.value), [obj])
            self._term(scope, e.index)
            return op_term('elem', '', [obj])
        if isinstance(e, N.ListExpr):
            return op_term('cont', 'list', self._terms(scope, e.elements))
        if isinstance(e, N.SetExpr):
            return op_term('cont', 'set', self._terms(scope, e.elements))
        if isinstance(e, N.TupleExpr):
            return op_term('cont', 'tuple', self._terms(scope, e.elements))
        if isinstance(e, N.DictExpr):
            flat = []
            for pair in e.pairs:
                flat.append(self._term(scope, pair[0]))
                flat.append(self._term(scope, pair[1]))
            return op_term('cont', 'dict', flat)
        if isinstance(e, N.WalrusExpr):
            var = self._local_var(scope, e.name)
            self.prog.add_flow(self._term(scope, e.value), var)
            return var_term(var)
        if isinstance(e, N.Comprehension):
            return self._comprehension(scope, e)
        if isinstance(e, (N.YieldExpr, N.YieldFromExpr, N.AwaitExpr)):
            self._undecidable(scope)
            if e.value is not None:
                self._term(scope, e.value)
            return const_term(sty.DYN)
        if isinstance(e, N.CastExpr):
            self._term(scope, e.value)
            return const_term(sty.DYN)
        if isinstance(e, N.SliceExpr):
            self._term(scope, e.obj)
            self._slice_parts(scope, e)
            return const_term(sty.DYN)
        if isinstance(e, (N.EllipsisLiteral, N.ImagLiteral, N.DottedLiteral)):
            return const_term(sty.DYN)
        if isinstance(e, N.TstringLiteral):
            # A template string's fields are not modelled: undecidable if it has any.
            if '{' in e.value:
                self._undecidable(scope)
            return const_term(sty.DYN)
        self._undecidable(scope)
        return const_term(sty.DYN)

    def _fstring_fields(self, scope: _Scope, value: str) -> None:
        """Walk the replacement fields of an f-string: each `{expr}` is parsed with
        the compiler's expression parser and its flows added. A field that does not
        parse makes the function undecidable."""
        body = _fstring_body(value)
        fields = _fstring_exprs(body)
        if fields is None:
            self._undecidable(scope)
            return
        for text in fields:
            node = _parse_expression(text)
            if node is None:
                self._undecidable(scope)
            else:
                self._term(scope, node)

    def _terms(self, scope: _Scope, exprs: list) -> list:
        out = []
        for x in exprs:
            out.append(self._term(scope, x))
        return out

    def _slice_parts(self, scope: _Scope, sl) -> None:
        for part in (sl.start, sl.stop, sl.step):
            if part is not None:
                self._term(scope, part)

    def _ident(self, scope: _Scope, name: str) -> Term:
        if name == 'None':
            return const_term(sty.NONE)
        if name == 'True' or name == 'False':
            return const_term(sty.BOOL)
        s = scope
        while s is not None:
            if name in s.narrow:
                b = self._lookup(scope, name)
                var = b.var if b is not None and b.kind == 'var' else -1
                return Term('narrow', None, var, s.narrow[name], [], [])
            s = s.parent
        b = self._lookup(scope, name)
        if b is None:
            return const_term(sty.DYN)
        if b.kind == 'var':
            return var_term(b.var)
        if b.kind == 'func':
            return const_term(sty.FUNC)
        return const_term(sty.DYN)

    def _member(self, scope: _Scope, e) -> Term:
        if isinstance(e.obj, N.IdentExpr):
            b = self._lookup(scope, e.obj.name)
            if b is not None and b.kind == 'module':
                mb = self.resolve_name(b.key, e.member)
                if mb is None:
                    return const_term(sty.DYN)
                if mb.kind == 'var':
                    return var_term(mb.var)
                if mb.kind == 'func':
                    return const_term(sty.FUNC)
                return const_term(sty.DYN)
        recv = self._term(scope, e.obj)
        return op_term('field', e.member, [recv])

    def _binop(self, scope: _Scope, e) -> Term:
        left = self._term(scope, e.left)
        right = self._term(scope, e.right)
        op = e.op
        if op == '%' and isinstance(e.left, N.StringLiteral) and not e.left.is_bytes:
            return const_term(sty.STR)
        if op in _ARITH_OPS:
            return op_term('join', '', [left, right])
        if op == '/':
            return const_term(sty.FLOAT)
        if op in _COMPARE_OPS:
            return const_term(sty.BOOL)
        return const_term(sty.DYN)

    def _lambda(self, scope: _Scope, e) -> Term:
        child = _Scope(scope.mod, scope.cls, scope.cs, scope.fn, scope)
        for pair in e.params:
            var = self.prog.new_var(pair[0])
            self.prog.pin(var, sty.DYN)
            child.locals[pair[0]] = _Binding('var', '', var, '', '')
            if pair[1] is not None:
                self._term(scope, pair[1])
        self._term(child, e.body)
        return const_term(sty.FUNC)

    def _comprehension(self, scope: _Scope, e) -> Term:
        for g in e.generators:
            it = self._term(scope, g.iterable)
            self._bind_target(scope, g.target, op_term('elem', '', [it]))
            for c in g.conditions:
                self._term(scope, c)
        if e.kind == 'list':
            return op_term('cont', 'list', [self._term(scope, e.element)])
        if e.kind == 'set':
            return op_term('cont', 'set', [self._term(scope, e.element)])
        if e.kind == 'dict':
            k = self._term(scope, e.element)
            v = self._term(scope, e.value)
            return op_term('cont', 'dict', [k, v])
        # A generator expression is an iterator: its type is not modelled.
        self._term(scope, e.element)
        return const_term(sty.DYN)

    def _call(self, scope: _Scope, e) -> Term:
        args = self._terms(scope, e.args)
        names = []
        kwvals = []
        for pair in e.kwargs:
            names.append(pair[0])
            kwvals.append(self._term(scope, pair[1]))
        func = e.func
        if isinstance(func, N.IdentExpr):
            b = self._lookup(scope, func.name)
            if b is None:
                return self._builtin(scope, func.name, e.args, args, names, kwvals)
            if b.kind == 'func':
                return self._static_call(b.key, args, names, kwvals)
            if b.kind == 'class':
                return self._construct(b.key, args, names, kwvals)
            return const_term(sty.DYN)
        if isinstance(func, N.MemberExpr):
            if isinstance(func.obj, N.IdentExpr):
                b = self._lookup(scope, func.obj.name)
                if b is not None and b.kind == 'module':
                    mb = self.resolve_name(b.key, func.member)
                    if mb is not None and mb.kind == 'func':
                        return self._static_call(mb.key, args, names, kwvals)
                    if mb is not None and mb.kind == 'class':
                        return self._construct(mb.key, args, names, kwvals)
                    return const_term(sty.DYN)
            recv = self._term(scope, func.obj)
            if func.member in _GROW_METHODS:
                for v in self._lvalue_vars(scope, func.obj):
                    grow_args = [var_term(v)] + args
                    self.prog.add_flow(op_term('grow', func.member, grow_args), v)
            all_args = [recv] + args + kwvals
            kwnames = [''] * len(args) + names
            return op_term('method', func.member, all_args, kwnames)
        self._term(scope, func)
        return const_term(sty.DYN)

    def _static_call(self, key: str, args: list, names: list, kwvals: list) -> Term:
        fs = self.prog.fns.get(key)
        if fs is None:
            return const_term(sty.DYN)
        self._feed(fs, 0, args + kwvals, [''] * len(args) + names)
        return Term('call', None, fs.ret, key, [], [])

    def _construct(self, cname: str, args: list, names: list, kwvals: list) -> Term:
        cs = self.prog.classes.get(cname)
        if cs is None or not cs.unique:
            return const_term(sty.DYN)
        init = cs.methods.get('__init__')
        if init is not None:
            self._feed(init, 1, args + kwvals, [''] * len(args) + names)
        return const_term(sty.struct_of(cname))

    def _feed(self, fs: FnSummary, offset: int, terms: list, names: list) -> None:
        targets = self.prog.param_targets(fs, offset, names)
        for i in range(len(terms)):
            if targets[i] >= 0:
                self.prog.add_flow(terms[i], targets[i])

    def _builtin(self, scope: _Scope, name: str, arg_nodes: list, args: list,
                 names: list, kwvals: list) -> Term:
        if name in ('str', 'repr', 'format', 'chr'):
            return const_term(sty.STR)
        if name in ('int', 'len', 'ord', 'hash', 'id'):
            return const_term(sty.INT)
        if name == 'float':
            return const_term(sty.FLOAT)
        if name in ('bool', 'isinstance', 'hasattr', 'callable', 'any', 'all'):
            return const_term(sty.BOOL)
        if name == 'print':
            return const_term(sty.NONE)
        if name in ('list', 'sorted', 'tuple', 'set'):
            cont = 'set' if name == 'set' else 'list'
            if not args:
                return op_term('cont', cont, [])
            return op_term('cont', cont, [op_term('elem', '', [args[0]])])
        if name == 'dict':
            if not args:
                return op_term('cont', 'dict', [])
            return args[0]
        if name in ('min', 'max'):
            if not args:
                return const_term(sty.DYN)
            if len(args) == 1:
                return op_term('elem', '', [args[0]])
            return op_term('join', '', args)
        if name == 'abs':
            return args[0] if args else const_term(sty.DYN)
        if name == 'range':
            return op_term('cont', 'list', [const_term(sty.INT)])
        if name == 'getattr' and len(arg_nodes) >= 2 and isinstance(arg_nodes[1], N.StringLiteral):
            got = op_term('field', arg_nodes[1].value, [args[0]])
            if len(args) == 3:
                return op_term('join', '', [got, args[2]])
            return got
        return const_term(sty.DYN)


_ARITH_OPS = ('+', '-', '*', '//', '%', '&', '|', '^', '<<', '>>', 'and', 'or')
_COMPARE_OPS = ('==', '!=', '<', '<=', '>', '>=', 'in', 'not in', 'is', 'is not')
_GROW_METHODS = ('append', 'add', 'extend')


def _param_slot(fs: FnSummary, name: str) -> int:
    for i in range(len(fs.param_names)):
        if fs.param_names[i] == name:
            return i
    return -1


def summarize_closure(root_path: str, root_stmts: list, load) -> Program:
    """The summary of the import closure of `root_stmts` (bugs/GIR_type_solver.md, 2.3).

    `load(ref, importer_path)` returns `(abspath, stmts)`, or None for a module
    that is not in the closure (an external one)."""
    s = _Summarizer(root_path, root_stmts, load)
    s.collect()
    s.declare()
    s.summarize()
    return s.prog
