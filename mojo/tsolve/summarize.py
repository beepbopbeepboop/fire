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
from mojo.tsolve import externs, sty
from mojo.tsolve.summary import (
    FILE_KIND,
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
        self.ann_names = None        # cache: the annotation names visible in this module (4.2b)


class _Scope:
    """One function body (or the module's top level, when `fn` is None)."""

    def __init__(self, mod: _Mod, cls: str, cs, fn, parent):
        self.mod: _Mod = mod
        self.cls: str = cls          # the class of a method, else ''
        self.cs: object = cs         # its ClassSummary, else None
        self.fn: object = fn         # its FnSummary, else None (module level)
        self.parent: object = parent  # the enclosing _Scope, for a nested def/lambda
        self.locals: dict = {}       # name -> _Binding
        self.narrow: dict = {}       # name -> STy, while a fact about it holds (4.2c)
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


def _items_of_text(s: str):
    """The items of a tuple target written as text (`a, *b, (c, d)`): a name, `*name` for a
    starred one, or a nested list of items. None when a part is not one of those."""
    items = []
    for part in sty.split_top(s, ','):
        p = part.strip()
        if p == '':
            continue
        if p.startswith('(') and p.endswith(')'):
            sub = _items_of_text(p[1:len(p) - 1])
            if sub is None:
                return None
            items.append(sub)
        elif p.startswith('*') and p[1:].strip().isidentifier():
            items.append('*' + p[1:].strip())
        elif p.isidentifier():
            items.append(p)
        else:
            return None
    return items


def _items_of_nodes(elems: list):
    """The items of a tuple target given as nodes (see `_items_of_text`)."""
    items = []
    for el in elems:
        if isinstance(el, N.IdentExpr):
            items.append(el.name)
        elif isinstance(el, N.UnaryOp) and el.op == '*' and isinstance(el.operand, N.IdentExpr):
            items.append('*' + el.operand.name)
        elif isinstance(el, N.TupleExpr):
            sub = _items_of_nodes(el.elements)
            if sub is None:
                return None
            items.append(sub)
        else:
            return None
    return items


def _target_items(target):
    """The items of a for/assignment target that is a tuple (text or node), else None."""
    if isinstance(target, N.TupleExpr):
        return _items_of_nodes(target.elements)
    if isinstance(target, str):
        s = target.strip()
        if s.startswith('(') and s.endswith(')'):
            s = s[1:len(s) - 1]
        return _items_of_text(s)
    return None


def _flatten_items(items: list, out: list) -> None:
    for it in items:
        if isinstance(it, str):
            out.append(it.lstrip('*'))
        else:
            _flatten_items(it, out)


def _plain_target_name(target):
    """The name of a plain (non-tuple) target, else None."""
    if isinstance(target, N.IdentExpr):
        return target.name
    if isinstance(target, str):
        s = target.strip()
        if s.startswith('(') and s.endswith(')'):
            s = s[1:len(s) - 1].strip()
        if ',' not in s and s.isidentifier():
            return s
    return None


def _target_names(target) -> list:
    """Every name a for/comprehension target binds, or None when it is not names or tuples
    of names (bugs/GIR_type_solver_precision.md, 4.2i: nested and starred targets included)."""
    plain = _plain_target_name(target)
    if plain is not None:
        return [plain]
    items = _target_items(target)
    if items is None:
        return None
    out = []
    _flatten_items(items, out)
    return out




def _is_cast_helper(node) -> bool:
    """A function with one parameter, an annotated return, and a body that (after its
    docstring) is exactly `return <that parameter>`: `def _as_dict(e: object) -> dict:
    return e`. Such helpers exist to tell the backend a type; the solver reads the type
    (bugs/GIR_type_solver_precision.md, 4.2h)."""
    if len(node.params) != 1 or not node.return_type:
        return False
    body = node.body
    if len(body) > 0 and isinstance(body[0], N.ExprStmt) and isinstance(body[0].value, N.StringLiteral):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], N.ReturnStmt):
        return False
    value = body[0].value
    return isinstance(value, N.IdentExpr) and value.name == node.params[0][0]


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


# The class a builtin name stands for as an isinstance target (4.2c); `None` for others.
_BUILTIN_CLASS_STY = {
    'str': sty.STR, 'int': sty.INT, 'float': sty.FLOAT, 'bool': sty.BOOL,
    'list': sty.list_of(sty.DYN), 'tuple': sty.list_of(sty.DYN),
    'dict': sty.dict_of(sty.DYN, sty.DYN), 'set': sty.set_of(sty.DYN),
}


def _exits(stmts: list) -> bool:
    """True when the block cannot fall through: it returns, raises, breaks or continues."""
    if not stmts:
        return False
    last = stmts[len(stmts) - 1]
    if isinstance(last, (N.BreakStmt, N.ContinueStmt)):
        return True
    return _terminates(stmts)


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
    elif isinstance(t, N.UnaryOp) and t.op == '*':
        _name_targets(t.operand, None, out)
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
        self.class_names: dict = {}  # unique class name -> class name (for annotations)
        self.class_list: list = []   # every ClassSummary, duplicates included
        self.pending: list = []      # (FnSummary, node, mod, ClassSummary or None)
        self.cur_origin: str = ''    # the origin of the statement being summarized

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
                self.class_names[name] = name
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
                        mod.names[local] = _Binding('extern', st.module + '.' + pair[0], -1, '', '')
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
        """`import m` / `import m as x` binds the name to the module. An EXTERNAL
        module (not in the closure) binds an `extern` of its dotted name, whose members
        have CPython's types (externs.py). `import a.b` without an alias binds `a`."""
        path = mod.imports.get(st.module, '')
        if not path:
            if st.alias:
                names[st.alias] = _Binding('extern', st.module, -1, '', '')
            else:
                root = st.module.split('.', 1)[0]
                names[root] = _Binding('extern', root, -1, '', '')
            return
        name = st.alias if st.alias else st.module
        if '.' not in name:
            names[name] = _Binding('module', path, -1, '', '')
        else:
            names[name] = _Binding('dyn', '', -1, '', '')

    def _declare_module_var(self, mod: _Mod, name: str, ann) -> None:
        b = mod.names.get(name)
        if b is not None and b.kind == 'var':
            return
        var = self.prog.new_var(name)
        if ann:
            self.prog.pin_ann(var, ann, self._names_for(mod))
        mod.names[name] = _Binding('var', '', var, '', '')

    def _declare_module_fn(self, mod: _Mod, node) -> None:
        key = func_key(mod.path, node.name)
        prev = mod.names.get(node.name)
        if prev is not None and prev.kind == 'func':
            # A second definition of one name: an overload set. Both are undecidable.
            self.prog.fns[prev.key].decidable = False
            mod.names[node.name] = _Binding('dyn', '', -1, '', '')
            fs = self._new_fn(mod.path, node.name, '', node, '', self._names_for(mod))
            fs.decidable = False
            self.pending.append((fs, node, mod, None))
            return
        fs = self._new_fn(mod.path, node.name, '', node, key, self._names_for(mod))
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
                    self.prog.pin_ann(var, f.type_ann, self._names_for(mod))
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
                fs = self._new_fn(mod.path, m.name, name, m, '', self._names_for(mod))
                if key in self.prog.fns:
                    fs.decidable = False
                else:
                    fs.key = key
                    self.prog.fns[key] = fs
                cs.methods[m.name] = fs
                self.pending.append((fs, m, mod, cs))

    def _new_fn(self, path: str, name: str, cls: str, node, key: str, names: dict) -> FnSummary:
        fs = FnSummary(key, path, name, cls)
        fs.node = node
        # A staticmethod or classmethod is an ordinary function with no receiver, or with
        # `cls` pinned to the class; any other decorator is not modelled (4.2e).
        if cls and len(node.decorators) == 1 and node.decorators[0] in ('staticmethod', 'classmethod'):
            fs.deco = node.decorators[0]
            fs.decidable = not (node.is_generator or node.is_async)
        else:
            fs.decidable = not (node.decorators or node.is_generator or node.is_async)
        for i in range(len(node.params)):
            pname = node.params[i][0]
            ptype = node.params[i][1]
            var = self.prog.new_var(pname)
            fs.params.append(var)
            fs.param_names.append(pname)
            if pname.startswith('*'):
                self.prog.pin(var, sty.DYN)
            elif i == 0 and fs.deco == 'classmethod':
                self.prog.pin(var, sty.DYN)
            elif pname == 'self' and cls and cls in names:
                self.prog.pin(var, sty.struct_of(names[cls]))
            elif pname == 'self' and cls:
                self.prog.pin(var, sty.DYN)
            elif ptype:
                self.prog.pin_ann(var, ptype, names)
        fs.ret = self.prog.new_var(name + '.ret')
        if not cls and _is_cast_helper(node):
            fs.cast_ty = sty.from_annotation(node.return_type, names)
        if node.return_type:
            fs.annotated_ret = True
            self.prog.pin_ann(fs.ret, node.return_type, names)
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

    def _names_for(self, mod: _Mod) -> dict:
        """The annotation names visible in `mod`: every unique closure class by its bare name,
        and `alias.Class` for each class a module binding `alias` (an `import m as alias` of a
        closure module) makes reachable (4.2b). Built from the imported module's statements,
        so it does not depend on the order the modules are declared in."""
        if mod.ann_names is not None:
            return mod.ann_names
        names = {}
        for name in self.class_names:
            names[name] = self.class_names[name]
        for st in mod.stmts:
            if not isinstance(st, N.ImportStmt):
                continue
            target_path = mod.imports.get(st.module, '')
            target = self.mods.get(target_path)
            if target is None:
                continue
            alias = st.alias if st.alias else st.module
            for tst in target.stmts:
                if isinstance(tst, N.StructDef) and tst.name in self.class_names:
                    names[alias + '.' + tst.name] = tst.name
        mod.ann_names = names
        return names

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
                self._flow(dterm, fs.params[idx])
        self._block(scope, node.body)
        self._run_deferred(scope)
        if not _terminates(node.body):
            fall = const_term(sty.NONE)
            fs.ret_terms.append(fall)
            self._flow(fall, fs.ret)

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
                    self.prog.pin_ann(var, names[n], self._names_for(scope.mod))
            scope.locals[n] = _Binding('var', '', var, '', '')

    # ── statements ──────────────────────────────────────────────────────

    def _undecidable(self, scope: _Scope) -> None:
        if scope.fn is not None:
            scope.fn.decidable = False

    def _block(self, scope: _Scope, stmts: list) -> None:
        # After `if c: <exits>` (no elif, no else), the rest of the block runs only when c
        # was false: `if not isinstance(x, D): return ...` then `x` is a D (4.2c).
        pushed = []
        for idx in range(len(stmts)):
            st = stmts[idx]
            self._stmt(scope, st)
            if isinstance(st, N.IfStmt) and not st.elifs and st.else_body is None:
                if _exits(st.then_body):
                    rest = stmts[idx + 1:]
                    neg = self._facts(scope, st.condition, False)
                    pushed.append(self._push(scope, neg, rest))
        for i in range(len(pushed)):
            self._pop(scope, pushed[len(pushed) - 1 - i])

    def _push(self, scope: _Scope, facts: list, region: list) -> list:
        """Apply `facts` (each a [name, STy]) while the region's statements run. A fact about a
        name the region rebinds is NOT applied: flows are flow-insensitive, so a rebound
        name would narrow the new value too (the soundness guard, 4.2c)."""
        rebound = {}
        _assigned_names(region, rebound)
        saved = []
        for f in facts:
            name = f[0]
            if name in rebound:
                continue
            saved.append([name, scope.narrow.get(name)])
            scope.narrow[name] = f[1]
        return saved

    def _pop(self, scope: _Scope, saved: list) -> None:
        for i in range(len(saved)):
            entry = saved[len(saved) - 1 - i]
            if entry[1] is None:
                scope.narrow.pop(entry[0], None)
            else:
                scope.narrow[entry[0]] = entry[1]

    def _facts(self, scope: _Scope, cond, positive: bool) -> list:
        """The [name, STy] facts that hold when `cond` is `positive` (4.2c).

        `isinstance(name, K)` with K a class, a builtin type, a `module.Class` or a tuple of
        those; `not`, `and` (when positive), `or` (when negative). Anything else proves nothing."""
        if isinstance(cond, N.UnaryOp) and cond.op == 'not':
            return self._facts(scope, cond.operand, not positive)
        if isinstance(cond, N.BinaryOp):
            if cond.op == 'and' and positive:
                return self._facts(scope, cond.left, True) + self._facts(scope, cond.right, True)
            if cond.op == 'or' and not positive:
                return self._facts(scope, cond.left, False) + self._facts(scope, cond.right, False)
            return []
        if not positive or not isinstance(cond, N.CallExpr):
            return []
        if not isinstance(cond.func, N.IdentExpr) or cond.func.name != 'isinstance':
            return []
        if len(cond.args) != 2 or not isinstance(cond.args[0], N.IdentExpr):
            return []
        ty = self._class_sty(scope, cond.args[1])
        if ty is None:
            return []
        return [[cond.args[0].name, ty]]

    def _class_name(self, scope: _Scope, node) -> str:
        """The class name `node` names (`C`, or `m.C` through a module binding), or ''."""
        if isinstance(node, N.IdentExpr):
            b = self._lookup(scope, node.name)
            if b is not None and b.kind == 'class':
                return b.key
            return ''
        if isinstance(node, N.MemberExpr) and isinstance(node.obj, N.IdentExpr):
            b = self._lookup(scope, node.obj.name)
            if b is None or b.kind != 'module':
                return ''
            mb = self.resolve_name(b.key, node.member)
            if mb is not None and mb.kind == 'class':
                return mb.key
        return ''

    def _class_sty(self, scope: _Scope, node):
        """The STy an `isinstance` second argument names, or None when it names nothing known."""
        if isinstance(node, N.TupleExpr):
            out = sty.BOT
            for el in node.elements:
                t = self._class_sty(scope, el)
                if t is None:
                    return None
                out = sty.join(out, t)
            return out
        if isinstance(node, N.MemberExpr) and isinstance(node.obj, N.IdentExpr):
            b = self._lookup(scope, node.obj.name)
            if b is None or b.kind != 'module':
                return None
            mb = self.resolve_name(b.key, node.member)
            if mb is None or mb.kind != 'class':
                return None
            return sty.struct_of(mb.key) if self.prog.class_is_unique(mb.key) else sty.DYN
        if isinstance(node, N.IdentExpr):
            b = self._lookup(scope, node.name)
            if b is None:
                return _BUILTIN_CLASS_STY.get(node.name)
            if b.kind == 'class':
                return sty.struct_of(b.key) if self.prog.class_is_unique(b.key) else sty.DYN
        return None

    def _flow(self, src: Term, dst: int) -> None:
        self.prog.add_flow(src, dst, self.cur_origin)

    def _stmt(self, scope: _Scope, st) -> None:
        # A statement's flows carry its line; a nested block's statements set their
        # own line and this one restores ours when they are done.
        prev = self.cur_origin
        self.cur_origin = scope.mod.path + ':' + str(st.line)
        self._stmt_body(scope, st)
        self.cur_origin = prev

    def _stmt_body(self, scope: _Scope, st) -> None:
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
                self._flow(self._term(scope, st.value), var)
        elif isinstance(st, N.ReturnStmt):
            if scope.fn is None or scope.fn.ret < 0:
                return
            if st.value is None:
                term = const_term(sty.NONE)
            else:
                term = self._term(scope, st.value)
            scope.fn.ret_terms.append(term)
            self._flow(term, scope.fn.ret)
        elif isinstance(st, N.IfStmt):
            conds = [st.condition]
            bodies = [st.then_body]
            for pair in st.elifs:
                conds.append(pair[0])
                bodies.append(pair[1])
            pushed = []
            for i in range(len(conds)):
                self._term(scope, conds[i])
                saved = self._push(scope, self._facts(scope, conds[i], True), bodies[i])
                self._block(scope, bodies[i])
                self._pop(scope, saved)
                # Once cond i is false, its negative facts hold for the later conditions and bodies.
                later = []
                for j in range(i + 1, len(bodies)):
                    later = later + bodies[j]
                if st.else_body is not None:
                    later = later + st.else_body
                pushed.append(self._push(scope, self._facts(scope, conds[i], False), later))
            if st.else_body is not None:
                self._block(scope, st.else_body)
            for i in range(len(pushed)):
                self._pop(scope, pushed[len(pushed) - 1 - i])
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
                    self._flow(const_term(sty.DYN), self._local_var(scope, h.name))
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
                    self._flow(self._with_value(scope, item.expr), self._local_var(scope, item.alias))
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
        elif isinstance(st, N.StructDef):
            scope.locals[st.name] = _Binding('dyn', '', -1, '', '')
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
                scope.locals[local] = _Binding('extern', st.module + '.' + pair[0], -1, '', '')
        if st.wildcard:
            self._undecidable(scope)

    def _nested_def(self, scope: _Scope, node) -> None:
        # A def inside a body is a value of unknown type; its own body still
        # contributes flows (its calls feed the parameters of what it calls).
        scope.locals[node.name] = _Binding('dyn', '', -1, '', '')
        fs = self._new_fn(scope.mod.path, node.name, '', node, '', self._names_for(scope.mod))
        fs.decidable = False
        scope.deferred.append((fs, node, scope.mod, scope.cs, scope))

    def _assign(self, scope: _Scope, target, value: Term) -> None:
        if isinstance(target, N.IdentExpr):
            self._flow(value, self._local_var(scope, target.name))
        elif isinstance(target, N.MemberExpr):
            self._term(scope, target.obj)
            var = self._member_target_var(scope, target)
            # None: no class in the closure declares this field, so no read of any
            # declared field can see the store. It flows nowhere.
            if var is not None:
                for v in var:
                    self._flow(value, v)
        elif isinstance(target, N.SubscriptExpr):
            conts = self._lvalue_vars(scope, target.obj)
            if isinstance(target.index, N.SliceExpr):
                self._slice_parts(scope, target.index)
                # `x[a:b] = v` extends x with the elements of v.
                for v in conts:
                    self._flow(op_term('grow', 'extend', [var_term(v), value]), v)
                return
            key = self._term(scope, target.index)
            # A store into a container that no modelled variable holds (`a[i][j] = v`,
            # `f()[k] = v`) flows nowhere: no read of a modelled name can see it. This is the
            # alias limitation, R2 in bugs/GIR_type_solver_precision.md.
            for v in conts:
                self._flow(op_term('grow', 'setitem', [var_term(v), key, value]), v)
        elif isinstance(target, N.TupleExpr):
            self._assign_seq(scope, target.elements, value)
        elif isinstance(target, N.SliceExpr):
            # `x[a:b] = v`, parsed with the slice as the target itself (4.2i).
            self._slice_parts(scope, target)
            for v in self._lvalue_vars(scope, target.obj):
                self._flow(op_term('grow', 'extend', [var_term(v), value]), v)
        else:
            self._undecidable(scope)

    def _assign_seq(self, scope: _Scope, elems: list, value: Term) -> None:
        """`a, *b, c = value`: `b` gets a list of the value's elements, and what comes after the
        star takes an element's type (its index is not known) (4.2i)."""
        star = -1
        for i in range(len(elems)):
            el = elems[i]
            if isinstance(el, N.UnaryOp) and el.op == '*':
                star = i
        for i in range(len(elems)):
            el = elems[i]
            if i == star:
                term = op_term('cont', 'list', [op_term('elem', '', [value])])
                self._assign(scope, el.operand, term)
            elif star >= 0 and i > star:
                self._assign(scope, el, op_term('elem', '', [value]))
            else:
                self._assign(scope, el, op_term('slot', str(i), [value]))

    def _bind_target(self, scope: _Scope, target, el: Term) -> None:
        plain = _plain_target_name(target)
        if plain is not None:
            self._flow(el, self._local_var(scope, plain))
            return
        items = _target_items(target)
        if items is None:
            self._undecidable(scope)
            return
        self._bind_items(scope, items, el)

    def _bind_items(self, scope: _Scope, items: list, el: Term) -> None:
        star = -1
        for i in range(len(items)):
            it = items[i]
            if isinstance(it, str) and it.startswith('*'):
                star = i
        for i in range(len(items)):
            it = items[i]
            if i == star:
                t = op_term('cont', 'list', [op_term('elem', '', [el])])
            elif star >= 0 and i > star:
                t = op_term('elem', '', [el])
            else:
                t = op_term('slot', str(i), [el])
            if isinstance(it, str):
                self._flow(t, self._local_var(scope, it.lstrip('*')))
            else:
                self._bind_items(scope, it, t)

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

    def _with_value(self, scope: _Scope, expr) -> Term:
        """The value a `with` alias gets: the file object for the builtin `open`, else dyn
        (`__enter__` is not modelled)."""
        if isinstance(expr, N.CallExpr) and isinstance(expr.func, N.IdentExpr):
            if expr.func.name == 'open' and self._lookup(scope, 'open') is None:
                return const_term(sty.struct_of(FILE_KIND))
        return const_term(sty.DYN)

    def _member_target_var(self, scope: _Scope, node):
        """The field variables a store to `node.member` writes, or None."""
        if isinstance(node.obj, N.IdentExpr) and node.obj.name == 'self' and scope.cs is not None:
            v = self.prog.find_field_var_in(scope.cs, node.member)
            if v is None:
                return None
            return [v]
        found = self.prog.field_index.get(node.member)
        if not found:
            # No class declares this field: the store goes to the loose variable of its name.
            return [self.prog.loose_var(node.member)]
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
            saved = self._push(scope, self._facts(scope, e.condition, True), [])
            then_t = self._term(scope, e.then_val)
            self._pop(scope, saved)
            saved = self._push(scope, self._facts(scope, e.condition, False), [])
            else_t = self._term(scope, e.else_val)
            self._pop(scope, saved)
            return op_term('join', '', [then_t, else_t])
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
                key = pair[0]
                if isinstance(key, N.UnaryOp) and key.op == '**':
                    # `{**d, ...}`: d's keys are not modelled (BOT), its values are d's.
                    splat = self._term(scope, key.operand)
                    flat.append(const_term(sty.BOT))
                    flat.append(op_term('elem', '', [splat]))
                    continue
                flat.append(self._term(scope, key))
                flat.append(self._term(scope, pair[1]))
            return op_term('cont', 'dict', flat)
        if isinstance(e, N.WalrusExpr):
            var = self._local_var(scope, e.name)
            self._flow(self._term(scope, e.value), var)
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
                return Term('narrow', s.narrow[name], var, '', [], [])
            s = s.parent
        b = self._lookup(scope, name)
        if b is None:
            return const_term(sty.DYN)
        if b.kind == 'var':
            return var_term(b.var)
        if b.kind == 'func':
            return const_term(sty.FUNC)
        return const_term(sty.DYN)

    def _dotted(self, scope: _Scope, node) -> str:
        """The dotted name of `node` when its root is an external module (`os.path.join`),
        else ''. A dotted name is never a field read (4.2a)."""
        if isinstance(node, N.IdentExpr):
            b = self._lookup(scope, node.name)
            if b is not None and b.kind == 'extern':
                return b.key
            return ''
        if isinstance(node, N.MemberExpr):
            base = self._dotted(scope, node.obj)
            if base == '':
                return ''
            return base + '.' + node.member
        return ''

    def _is_attr_method(self, scope: _Scope, func) -> bool:
        """True for `os.environ.get`: a method of an external ATTRIBUTE value, which has the
        attribute's type and so is an ordinary method call on that type."""
        if not isinstance(func, N.MemberExpr):
            return False
        return self._dotted(scope, func.obj) in externs.ATTRS

    def _member(self, scope: _Scope, e) -> Term:
        dotted = self._dotted(scope, e)
        if dotted != '':
            if dotted in externs.ATTRS:
                return const_term(sty.from_annotation(externs.ATTRS[dotted], self._names_for(scope.mod)))
            return const_term(sty.DYN)
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
        if e.op == 'and' or e.op == 'or':
            # The right operand runs only when the left one is true (and) or false (or).
            saved = self._push(scope, self._facts(scope, e.left, e.op == 'and'), [])
            right = self._term(scope, e.right)
            self._pop(scope, saved)
        else:
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
        dotted = self._dotted(scope, e.func)
        if dotted in externs.FUNCS:
            self._terms(scope, e.args)
            for pair in e.kwargs:
                self._term(scope, pair[1])
            return const_term(sty.from_annotation(externs.FUNCS[dotted], self._names_for(scope.mod)))
        if dotted != '' and not self._is_attr_method(scope, e.func):
            self._terms(scope, e.args)
            for pair in e.kwargs:
                self._term(scope, pair[1])
            return const_term(sty.DYN)
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
            cname = self._class_name(scope, func.obj)
            if cname != '' and self.prog.class_is_unique(cname):
                fs = self.prog.find_method_in(self.prog.classes[cname], func.member)
                if fs is not None and fs.deco != '':
                    # `C.m(...)`: a static or class method, called without an instance.
                    self._feed(fs, self.prog.receiver_offset(fs), args + kwvals,
                               [''] * len(args) + names)
                    return Term('call', None, fs.ret, fs.key, [], [])
            recv = self._term(scope, func.obj)
            if func.member in _GROW_METHODS:
                for v in self._lvalue_vars(scope, func.obj):
                    grow_args = [var_term(v)] + args
                    self._flow(op_term('grow', func.member, grow_args), v)
            all_args = [recv] + args + kwvals
            kwnames = [''] * len(args) + names
            return op_term('method', func.member, all_args, kwnames)
        self._term(scope, func)
        return const_term(sty.DYN)

    def _static_call(self, key: str, args: list, names: list, kwvals: list) -> Term:
        fs = self.prog.fns.get(key)
        if fs is None:
            return const_term(sty.DYN)
        if fs.cast_ty is not None and len(args) == 1 and len(kwvals) == 0:
            # A cast helper hands its argument back with the type it names (4.2h).
            return Term('cast', fs.cast_ty, -1, '', [args[0]], [])
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
                self._flow(terms[i], targets[i])

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
        if name in externs.INTERNAL:
            return const_term(sty.from_annotation(externs.INTERNAL[name], self._names_for(scope.mod)))
        if name == 'open':
            return const_term(sty.struct_of(FILE_KIND))
        if name == 'enumerate' and args:
            return op_term('cont', 'list', [op_term('cont', 'tuple',
                                                    [const_term(sty.INT), op_term('elem', '', [args[0]])])])
        if name == 'zip' and args:
            slots = []
            for a in args:
                slots.append(op_term('elem', '', [a]))
            return op_term('cont', 'list', [op_term('cont', 'tuple', slots)])
        if name == 'reversed' and args:
            return op_term('cont', 'list', [op_term('elem', '', [args[0]])])
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
