#!/usr/bin/env python3
"""Lift nested functions of a giant function to module level.

    python3 tools/hoist_nested.py --list FILE PARENT
    python3 tools/hoist_nested.py FILE PARENT PREFIX

A function defined inside PARENT can be lifted when the only names of
PARENT it reads are PARENT's own parameters and other liftable nested
functions. It then needs no closure: the parameters it read become its
first parameters and every call passes them.

    def parent(self, stmts):                 def _p_helper(self, x):
        def _helper(x):                          return self.f(x)
            return self.f(x)
        y = _helper(3)                       def parent(self, stmts):
                                                 y = _p_helper(self, 3)

The new name is PREFIX + the old name without its leading underscore.
`--list` prints which nested functions qualify and why the others do not.

Refused (left where it is):

  * it reads a local variable of PARENT (that needs a typed parameter;
    not done by this tool);
  * it is used as a VALUE (`key=_helper`, stored, returned), not only
    called;
  * it has `nonlocal`, a decorator, or the same name as another nested
    function or a module-level name;
  * it calls a nested function that is refused.

It does not run any test. Afterwards the generated C for a corpus must be
byte-identical (doc/GIR.md, section 4).
"""
import ast
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import extract_arm as E  # noqa: E402


def module_level_names(tree) -> set:
    """Names bound by the module's own top-level statements."""
    out = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(n):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    out.add(t.id)
    return out


class Plan:
    def __init__(self, src: str, parent: str):
        self.src = src
        self.arm = E.Arm(src, parent)
        fn = self.arm.fn
        self.fn = fn
        self.params = self.arm.params
        self.nested = [s for s in fn.body if isinstance(s, ast.FunctionDef)]
        counts = {}
        for s in self.nested:
            counts[s.name] = counts.get(s.name, 0) + 1
        module_names = module_level_names(self.arm.tree)
        names = {s.name for s in self.nested}
        par = {}
        for n in ast.walk(fn):
            for c in ast.iter_child_nodes(n):
                par[c] = n
        self.calls = []          # Call nodes whose callee is a nested name
        value_use = set()
        rebound = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and n.id in names:
                if not isinstance(n.ctx, ast.Load):
                    rebound.add(n.id)
                    continue
                p = par[n]
                if isinstance(p, ast.Call) and p.func is n:
                    self.calls.append(p)
                else:
                    value_use.add(n.id)
        reads = E.Reads(self.arm.locals)
        self.why = {}
        self.needs = {}
        self.callees = {}
        for s in self.nested:
            fr = reads.free_reads(s)
            why = []
            if counts[s.name] > 1:
                why.append('defined more than once')
            if s.name in module_names:
                why.append('a module-level name is spelled the same')
            if s.name in value_use:
                why.append('used as a value')
            if s.name in rebound:
                why.append('rebound')
            if s.decorator_list:
                why.append('decorated')
            if any(isinstance(x, (ast.Nonlocal, ast.Global)) for x in ast.walk(s)):
                why.append('has nonlocal/global')
            if s.args.vararg or s.args.kwarg or s.args.kwonlyargs or s.args.posonlyargs:
                why.append('has *args/**kwargs/keyword-only parameters')
            caps = sorted(fr - names - set(self.params))
            if caps:
                why.append('reads local(s) ' + ', '.join(caps[:6]))
            self.why[s.name] = why
            self.needs[s.name] = [p for p in self.params if p in fr]
            self.callees[s.name] = sorted(fr & names)
        changed = True
        while changed:
            changed = False
            for s in self.nested:
                if self.why[s.name]:
                    continue
                bad = [c for c in self.callees[s.name] if self.why[c]]
                if bad:
                    self.why[s.name] = ['calls ' + ', '.join(bad) + ' (not liftable)']
                    changed = True
        # A lifted function passes on what its lifted callees need.
        changed = True
        while changed:
            changed = False
            for s in self.nested:
                if self.why[s.name]:
                    continue
                for c in self.callees[s.name]:
                    for p in self.needs[c]:
                        if p not in self.needs[s.name]:
                            self.needs[s.name] = [q for q in self.params
                                                  if q in self.needs[s.name] or q == p]
                            changed = True
        self.ok = [s for s in self.nested if not self.why[s.name]]


def new_name(prefix: str, old: str) -> str:
    return prefix + old.lstrip('_')


def do_list(path: str, parent: str) -> None:
    p = Plan(open(path).read(), parent)
    total = 0
    for s in p.nested:
        n = s.end_lineno - s.lineno + 1
        if p.why[s.name]:
            print(f"{s.lineno}: {s.name}  {n} lines  NO ({'; '.join(p.why[s.name])})")
        else:
            total += n
            print(f"{s.lineno}: {s.name}  {n} lines  passes: {', '.join(p.needs[s.name]) or 'nothing'}")
    print(f"{len(p.ok)} of {len(p.nested)} nested functions can be lifted ({total} lines)")


def do_hoist(path: str, parent: str, prefix: str) -> None:
    src = open(path).read()
    p = Plan(src, parent)
    if not p.ok:
        raise SystemExit('nothing to lift')
    okn = {s.name for s in p.ok}
    taken = module_level_names(p.arm.tree)
    for s in p.ok:
        nn = new_name(prefix, s.name)
        if nn in taken:
            raise SystemExit(f"{nn} is already a module-level name; pick another PREFIX")
        taken.add(nn)
    lines = src.split('\n')
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)

    def off(lineno: int, col_bytes: int) -> int:
        # ast columns are UTF-8 byte offsets; convert within the line.
        text = lines[lineno - 1]
        return starts[lineno - 1] + len(text.encode('utf-8')[:col_bytes].decode('utf-8'))

    edits = []      # (start, end, replacement)
    for c in p.calls:
        name = c.func.id
        if name not in okn:
            continue
        a = off(c.func.lineno, c.func.col_offset)
        b = off(c.func.end_lineno, c.func.end_col_offset)
        if src[b] != '(':
            raise SystemExit(f"line {c.lineno}: expected `(` right after {name}")
        extra = ', '.join(p.needs[name])
        has_args = bool(c.args or c.keywords)
        ins = extra + (', ' if (extra and has_args) else '')
        edits.append((a, b + 1, new_name(prefix, name) + '(' + ins))
    for s in p.ok:
        # `def NAME(` on the def line
        text = lines[s.lineno - 1]
        key = 'def ' + s.name + '('
        k = text.find(key)
        if k < 0:
            raise SystemExit(f"line {s.lineno}: cannot find `{key}`")
        a = starts[s.lineno - 1] + k
        extra = ', '.join(p.needs[s.name])
        has_params = bool(s.args.args)
        ins = extra + (', ' if (extra and has_params) else '')
        edits.append((a, a + len(key), 'def ' + new_name(prefix, s.name) + '(' + ins))
    out = src
    for a, b, rep in sorted(edits, reverse=True):
        out = out[:a] + rep + out[b:]
    # Second step: move each renamed def (with the comment lines directly
    # above it) to just above PARENT, dedented.
    tree = ast.parse(out)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == parent][0]
    lines = out.split('\n')
    newn = {new_name(prefix, s.name) for s in p.ok}
    moved = []
    cut = []
    for s in fn.body:
        if not (isinstance(s, ast.FunctionDef) and s.name in newn):
            continue
        first = s.lineno - 1
        while first > 0 and lines[first - 1].strip().startswith('#') \
                and lines[first - 1].startswith(' ' * s.col_offset + '#'):
            first -= 1
        block = []
        for bl in lines[first:s.end_lineno]:
            if bl.strip() == '':
                block.append('')
            elif bl.startswith(' ' * s.col_offset):
                block.append(bl[s.col_offset:])
            else:
                raise SystemExit(f"cannot dedent: {bl!r}")
        moved.append(block + ['', ''])
        cut.append((first, s.end_lineno))
    top = fn.lineno - 1
    body = lines[:]
    for a, b in sorted(cut, reverse=True):
        del body[a:b]
    flat = []
    for blk in moved:
        flat += blk
    res = body[:top] + flat + body[top:]
    new_src = '\n'.join(res)
    ast.parse(new_src)
    open(path, 'w').write(new_src)
    n = sum(b - a for a, b in cut)
    print(f"{path}: lifted {len(cut)} nested functions of {parent} ({n} lines)")


def main(argv: list) -> None:
    if len(argv) == 3 and argv[0] == '--list':
        do_list(argv[1], argv[2])
    elif len(argv) == 3:
        do_hoist(argv[0], argv[1], argv[2])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
