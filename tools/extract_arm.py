#!/usr/bin/env python3
"""Move one `if` arm of a giant function into its own top-level function.

    python3 tools/extract_arm.py FILE PARENT LINE NEWNAME "DOC" [name:ann ...]
    python3 tools/extract_arm.py --list FILE PARENT [MINLINES]

`--list` prints every top-level `if` arm of PARENT that this tool can move,
with the names the arm reads from PARENT. Run it first.

The other form rewrites FILE in place. LINE is the line of an `if` statement
that is a direct child of PARENT's body and has no `else`. The arm's body
becomes the body of a new function NEWNAME, written just above PARENT, and
the arm is replaced by a call:

    if <same test>:                    if <same test>:
        return NEWNAME(gen, node)          _arm_r = NEWNAME(gen, node)
                                           if _arm_r is not None:
                                               return _arm_r

The left form is used when every path through the arm returns or raises, the
right form when the arm can fall out of its end (the new function then ends
with `return None`).

What the tool checks, and refuses on:

  * every name the arm reads from PARENT is either a parameter of PARENT or
    is named on the command line as `name:annotation` (for example
    `ot:str`, or `ov:` for no annotation). The self-hosted compiler types a
    parameter from its annotation, and the new parameter must get the type
    the local had in PARENT. Read that type from the compiler's own output
    (`python3 fire.py --dump FILE`, then the declarations at the top of
    PARENT in the `.ci` file): `char * ot;` is `ot:str`, `_Bool b;` is
    `b:bool`, and `int64_t ov;` (an untyped word) is `ov:` with nothing
    after the colon. Dump again afterwards and check the new function's
    parameters have those same C types.
    Nested functions of PARENT cannot be passed; an arm that calls one is
    refused.
  * every such name is bound on EVERY path that reaches the arm (a name
    bound only inside an earlier `if` cannot be passed as an argument: the
    call would read it on the paths where it was never bound).
  * a fall-through arm binds no name that PARENT reads after the arm.
  * the arm has no `nonlocal`, `global`, `yield`, bare `return` or
    `return None`.
  * NEWNAME is not already a top-level name in FILE.
  * after the rewrite, the new function's body is the SAME syntax tree as
    the arm's body was.

It does not run any test. After using it, the generated C for a corpus must
be byte-identical (see doc/GIR.md, section 4).
"""
import ast
import sys


def own_bound(f) -> set:
    """Names bound in function `f`'s own scope (not in nested functions)."""
    out = set(a.arg for a in f.args.args)
    stack = list(f.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
            continue
        if isinstance(n, ast.Lambda):
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        stack.extend(ast.iter_child_nodes(n))
    return out


class Reads:
    """Upward-exposed reads: the names of `locals_` that a run of statements
    may read before binding them. Conservative: a name bound on only one
    branch of an `if`, or inside a loop body, still counts as read-first by
    whatever follows."""

    def __init__(self, locals_: set):
        self.locals = locals_
        self.ue: set = set()

    def free_reads(self, f) -> set:
        if isinstance(f, ast.Lambda):
            mine = {a.arg for a in f.args.args}
            body = [f.body]
        else:
            mine = own_bound(f)
            body = f.body
        out = set()
        stack = list(body)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.Lambda)):
                out |= self.free_reads(n) - mine
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in mine:
                out.add(n.id)
            stack.extend(ast.iter_child_nodes(n))
        return out & self.locals

    def expr(self, e, d: set) -> set:
        if e is None:
            return d
        if isinstance(e, ast.Name):
            if isinstance(e.ctx, ast.Load):
                if e.id in self.locals and e.id not in d:
                    self.ue.add(e.id)
                return d
            return d | {e.id}
        if isinstance(e, ast.Lambda):
            self.ue |= self.free_reads(e) - d
            return d
        if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            dd = set(d)
            for g in e.generators:
                dd = self.expr(g.iter, dd)
                dd = self.expr(g.target, dd)
                for c in g.ifs:
                    dd = self.expr(c, dd)
            if isinstance(e, ast.DictComp):
                self.expr(e.key, dd)
                self.expr(e.value, dd)
            else:
                self.expr(e.elt, dd)
            return d
        if isinstance(e, ast.NamedExpr):
            d = self.expr(e.value, d)
            return d | {e.target.id}
        if isinstance(e, ast.BoolOp):
            d0 = self.expr(e.values[0], d)
            for v in e.values[1:]:
                self.expr(v, d0)
            return d0
        if isinstance(e, ast.IfExp):
            d0 = self.expr(e.test, d)
            self.expr(e.body, d0)
            self.expr(e.orelse, d0)
            return d0
        for c in ast.iter_child_nodes(e):
            if isinstance(c, ast.expr):
                d = self.expr(c, d)
            elif isinstance(c, ast.keyword):
                d = self.expr(c.value, d)
        return d

    def stmts(self, ss, d: set) -> set:
        for s in ss:
            d = self.stmt(s, d)
        return d

    def stmt(self, s, d: set) -> set:
        if isinstance(s, ast.FunctionDef):
            self.ue |= self.free_reads(s) - d - {s.name}
            return d | {s.name}
        if isinstance(s, ast.Assign):
            d = self.expr(s.value, d)
            for t in s.targets:
                d = self.expr(t, d)
            return d
        if isinstance(s, ast.AnnAssign):
            d = self.expr(s.value, d)
            return self.expr(s.target, d)
        if isinstance(s, ast.AugAssign):
            if isinstance(s.target, ast.Name):
                if s.target.id in self.locals and s.target.id not in d:
                    self.ue.add(s.target.id)
            else:
                self.expr(s.target, d)
            return self.expr(s.value, d)
        if isinstance(s, ast.If):
            d0 = self.expr(s.test, d)
            a = self.stmts(s.body, d0)
            b = self.stmts(s.orelse, d0)
            return a & b
        if isinstance(s, ast.For):
            d0 = self.expr(s.iter, d)
            d1 = self.expr(s.target, d0)
            self.stmts(s.body, d1)
            self.stmts(s.orelse, d0)
            return d0
        if isinstance(s, ast.While):
            d0 = self.expr(s.test, d)
            self.stmts(s.body, d0)
            self.stmts(s.orelse, d0)
            return d0
        if isinstance(s, ast.Try):
            # Bound after the statement: what the body AND every handler
            # that can fall out of its end bind. A handler starts from `d`,
            # because the body may have raised before binding anything.
            after = self.stmts(s.body, d)
            after = self.stmts(s.orelse, after)
            for h in s.handlers:
                self.expr(h.type, d)
                hd = self.stmts(h.body, d | ({h.name} if h.name else set()))
                if not always_exits(h.body):
                    after = after & hd
            if s.finalbody:
                self.stmts(s.finalbody, d)
            return after
        if isinstance(s, ast.With):
            for it in s.items:
                d = self.expr(it.context_expr, d)
                d = self.expr(it.optional_vars, d)
            return self.stmts(s.body, d)
        if isinstance(s, (ast.Import, ast.ImportFrom)):
            return d | {(a.asname or a.name).split('.')[0] for a in s.names}
        for c in ast.iter_child_nodes(s):
            if isinstance(c, ast.expr):
                d = self.expr(c, d)
        return d


def bound_names(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
    return out


def always_exits(ss) -> bool:
    if not ss:
        return False
    s = ss[-1]
    if isinstance(s, (ast.Return, ast.Raise)):
        return True
    if isinstance(s, ast.If):
        return bool(s.orelse) and always_exits(s.body) and always_exits(s.orelse)
    return False


def own_nodes(s):
    """Nodes of statement `s` outside any nested function or lambda."""
    stack = [s]
    while stack:
        n = stack.pop()
        yield n
        for c in ast.iter_child_nodes(n):
            if not isinstance(c, (ast.FunctionDef, ast.Lambda)):
                stack.append(c)


class Arm:
    def __init__(self, src: str, parent: str):
        self.src = src
        self.tree = ast.parse(src)
        fns = [n for n in self.tree.body
               if isinstance(n, ast.FunctionDef) and n.name == parent]
        if len(fns) != 1:
            raise SystemExit(f"{parent}: expected one top-level function, found {len(fns)}")
        self.fn = fns[0]
        self.locals = own_bound(self.fn)
        self.params = [a.arg for a in self.fn.args.args]
        self.nested = {s.name for s in self.fn.body if isinstance(s, ast.FunctionDef)}

    def problems(self, i: int) -> tuple:
        """(inputs, tail, why_not) for body statement `i`."""
        s = self.fn.body[i]
        r = Reads(self.locals)
        r.stmts(s.body, set())
        # A name that nothing before the arm binds is the arm's own local,
        # however the arm's branches reach it: it is not an input.
        earlier = set(self.params)
        for t in self.fn.body[:i]:
            earlier |= bound_names(t)
        ins = sorted(r.ue & earlier)
        tail = always_exits(s.body)
        why = []
        before = Reads(self.locals)
        have = before.stmts(self.fn.body[:i], set(self.params))
        maybe = [x for x in ins if x not in have and x not in self.nested]
        if maybe:
            why.append('reads name(s) not bound on every path to the arm: '
                       + ', '.join(maybe))
        clos = [x for x in ins if x in self.nested]
        if clos:
            why.append('calls nested function(s) ' + ', '.join(clos))
        for n in own_nodes(s):
            if isinstance(n, (ast.Nonlocal, ast.Global, ast.Yield, ast.YieldFrom)):
                why.append('has ' + type(n).__name__.lower())
            if isinstance(n, ast.Return) and (
                    n.value is None
                    or (isinstance(n.value, ast.Constant) and n.value.value is None)):
                why.append(f'line {n.lineno} returns None')
        if not tail:
            later = Reads(self.locals)
            for t in self.fn.body[i + 1:]:
                one = Reads(self.locals)
                one.stmt(t, set())
                later.ue |= one.ue
            outs = sorted(bound_names(s) & later.ue)
            if outs:
                why.append('binds name(s) read later: ' + ', '.join(outs))
        return ins, tail, why


def list_arms(path: str, parent: str, minlines: int) -> None:
    a = Arm(open(path).read(), parent)
    total = 0
    for i, s in enumerate(a.fn.body):
        if not isinstance(s, ast.If) or s.orelse:
            continue
        n = s.end_lineno - s.lineno + 1
        if n < minlines:
            continue
        ins, tail, why = a.problems(i)
        extra = [x for x in ins if x not in a.params]
        test = ' '.join(ast.unparse(s.test).split())[:70]
        if why:
            print(f"{s.lineno}: {n} lines  NO ({'; '.join(why)})  if {test}")
            continue
        total += n
        print(f"{s.lineno}: {n} lines  {'returns' if tail else 'falls through'}"
              f"  extra inputs: {', '.join(extra) or 'none'}  if {test}")
    print(f"{total} lines can be moved")


def extract(path: str, parent: str, line: int, newname: str, doc: str,
            anns: dict) -> None:
    src = open(path).read()
    a = Arm(src, parent)
    idx = [i for i, s in enumerate(a.fn.body)
           if isinstance(s, ast.If) and s.lineno == line and not s.orelse]
    if not idx:
        raise SystemExit(f"line {line}: no else-less `if` directly in {parent}")
    i = idx[0]
    s = a.fn.body[i]
    ins, tail, why = a.problems(i)
    if why:
        raise SystemExit(f"line {line}: cannot move: {'; '.join(why)}")
    for n in a.tree.body:
        if getattr(n, 'name', None) == newname:
            raise SystemExit(f"{newname} is already defined in {path}")
    lines = src.split('\n')
    seg = {}
    for p in a.fn.args.args:
        seg[p.arg] = ast.get_source_segment(src, p)
    params = []
    args = []
    for p in a.params:
        if p in ins or p == a.params[0]:
            params.append(seg[p])
            args.append(p)
    for x in ins:
        if x in a.params:
            continue
        if x not in anns:
            raise SystemExit(f"line {line}: the arm reads `{x}`; pass `{x}:<annotation>`")
        params.append(f"{x}: {anns[x]}" if anns[x] else x)
        args.append(x)
    ret = ast.get_source_segment(src, a.fn.returns) if a.fn.returns else ''
    if ret and not tail:
        ret += ' | None'
    ind = s.col_offset
    first = s.test.end_lineno      # 0-based index of the line after the test
    while not lines[first - 1].rstrip().endswith(':'):
        first += 1
    body_lines = lines[first:s.end_lineno]
    new_body = []
    for bl in body_lines:
        if bl.strip() == '':
            new_body.append('')
            continue
        if not bl.startswith(' ' * (ind + 4)):
            raise SystemExit(f"cannot dedent: {bl!r}")
        new_body.append(bl[ind:])
    head = f"def {newname}({', '.join(params)})" + (f" -> {ret}" if ret else '') + ':'
    func = [head, f'    """{doc}', '',
            f"    One arm of `{parent}`, which tests the condition and calls this.\"\"\""]
    func += new_body
    if not tail:
        func.append('    return None')
    func += ['', '']
    pad = ' ' * ind
    call = f"{newname}({', '.join(args)})"
    if tail:
        site = [f"{pad}    return {call}"]
    else:
        site = [f"{pad}    _arm_r = {call}",
                f"{pad}    if _arm_r is not None:",
                f"{pad}        return _arm_r"]
    top = a.fn.lineno - 1
    if a.fn.decorator_list:
        top = a.fn.decorator_list[0].lineno - 1
    out = lines[:top] + func + lines[top:first] + site + lines[s.end_lineno:]
    new_src = '\n'.join(out)
    # The moved body must be the same syntax tree.
    nt = ast.parse(new_src)
    nf = [n for n in nt.body if isinstance(n, ast.FunctionDef) and n.name == newname][0]
    moved = nf.body[1:]
    if not tail:
        moved = moved[:-1]
    if ast.dump(ast.Module(body=moved, type_ignores=[])) != \
            ast.dump(ast.Module(body=s.body, type_ignores=[])):
        raise SystemExit("internal error: the moved body is not the same tree")
    open(path, 'w').write(new_src)
    print(f"{path}:{line}: {s.end_lineno - s.lineno + 1} lines -> {newname}"
          f"({', '.join(args)})  [{'returns' if tail else 'falls through'}]")


def main(argv: list) -> None:
    if len(argv) >= 3 and argv[0] == '--list':
        list_arms(argv[1], argv[2], int(argv[3]) if len(argv) > 3 else 30)
        return
    if len(argv) < 5:
        raise SystemExit(__doc__)
    anns = {}
    for p in argv[5:]:
        k, _, v = p.partition(':')
        anns[k] = v
    extract(argv[0], argv[1], int(argv[2]), argv[3], argv[4], anns)


if __name__ == '__main__':
    main(sys.argv[1:])
