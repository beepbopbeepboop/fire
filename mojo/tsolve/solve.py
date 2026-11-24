"""The fixpoint of the whole-closure type solver (bugs/GIR_type_solver.md, 2.3).

`solve(prog)` fills `prog.vars`. It is a worklist over the flows: each flow
evaluates its source term and joins the result into its destination variable.
When a variable changes, the flows that read it are queued again. Flows are
processed FIFO, in creation order, so the answer is deterministic.

The solver only ever GROWS a variable (`join`), so a flow evaluated early may
see less than it will later; that is the point of re-queueing. The one
deliberate exception is `pinned` variables, which keep their annotation.

Rules (doc/GIR.md, rule 2): plain classes, annotated fields, no closures, no
lambdas, no `re`, no tuple unpacking, no `getattr`, no generators.
"""
from __future__ import annotations

from mojo.tsolve import sty
from mojo.tsolve.summary import Flow, Program, Term

# How many flow evaluations a solve may take per flow before it is a bug.
# The lattice is finite (`sty.cap`), so a correct fixpoint is far below this.
STEP_FACTOR = 64


class SolveError(RuntimeError):
    pass


class _Solver:
    def __init__(self, prog: Program):
        self.prog: Program = prog
        self.queue: list = []       # FIFO of flow ids waiting to be evaluated
        self.head: int = 0
        self.queued: list = []      # per flow: is it in the queue?
        self.depends: dict = {}     # var -> {flow id: True} of the flows that read it
        self.cur: int = -1          # the flow being evaluated
        self.cur_reads: list = []   # the vars the current evaluation read
        self.resolved: dict = {}    # "flow|method key" -> True: arguments already flowed

    def enqueue(self, fid: int) -> None:
        if not self.queued[fid]:
            self.queued[fid] = True
            self.queue.append(fid)

    def add_flow(self, src: Term, dst: int) -> None:
        # The flow being evaluated created this one (a method's arguments flow to
        # the resolved method's parameters), so it inherits that flow's origin.
        origin = self.prog.flows[self.cur].origin if self.cur >= 0 else ''
        self.prog.flows.append(Flow(src, dst, origin))
        self.queued.append(False)
        self.enqueue(len(self.prog.flows) - 1)

    def read(self, var: int):
        if var < 0:
            return sty.DYN
        self.cur_reads.append(var)
        return self.prog.vars[var]

    def run(self) -> None:
        prog = self.prog
        for fid in range(len(prog.flows)):
            self.queued.append(False)
            self.enqueue(fid)
        steps = 0
        while self.head < len(self.queue):
            fid = self.queue[self.head]
            self.head += 1
            self.queued[fid] = False
            steps += 1
            if steps > STEP_FACTOR * len(prog.flows) + STEP_FACTOR:
                raise SolveError('tsolve: no fixpoint after %d evaluations' % steps)
            flow = prog.flows[fid]
            self.cur = fid
            self.cur_reads: list = []
            val = self.ev(flow.src)
            for v in self.cur_reads:
                if v not in self.depends:
                    self.depends[v] = {}
                self.depends[v][fid] = True
            dst = flow.dst
            if prog.pinned[dst] or val.kind == 'bot':
                continue
            old = prog.vars[dst]
            new = sty.join(old, val)
            if new.key != old.key:
                prog.vars[dst] = new
                readers = self.depends.get(dst, {})
                for g in readers:
                    self.enqueue(g)

    # ── term evaluation ────────────────────────────────────────────────

    def ev(self, t: Term):
        op = t.op
        if op == 'const':
            return t.ty
        if op == 'var' or op == 'call':
            return self.read(t.var)
        if op == 'narrow':
            if self.prog.class_is_unique(t.name):
                return sty.struct_of(t.name)
            return sty.DYN
        if op == 'join':
            out = sty.BOT
            for a in t.args:
                out = sty.join(out, self.ev(a))
            return out
        if op == 'cont':
            return self.cont(t)
        if op == 'elem':
            return elem_of(self.ev(t.args[0]))
        if op == 'slot':
            return slot_of(self.ev(t.args[0]), int(t.name))
        if op == 'field':
            return self.field(t)
        if op == 'method':
            return self.method(t)
        if op == 'grow':
            return self.grow(t)
        return sty.DYN

    def cont(self, t: Term):
        vals = []
        for a in t.args:
            vals.append(self.ev(a))
        if t.name == 'list':
            return sty.cap(sty.list_of(join_all(vals)))
        if t.name == 'set':
            return sty.cap(sty.set_of(join_all(vals)))
        if t.name == 'dict':
            k = sty.BOT
            v = sty.BOT
            for i in range(0, len(vals) - 1, 2):
                k = sty.join(k, vals[i])
                v = sty.join(v, vals[i + 1])
            return sty.cap(sty.dict_of(k, v))
        if t.name == 'tuple':
            return sty.cap(sty.tuple_of(vals))
        return sty.DYN

    def field(self, t: Term):
        recv = self.ev(t.args[0])
        if recv.kind == 'bot':
            return sty.BOT
        if recv.kind == 'struct':
            cs = self.prog.classes.get(recv.name)
            if cs is None or not cs.unique:
                return sty.DYN
            v = self.prog.find_field_var_in(cs, t.name)
            if v is None:
                return sty.DYN
            return self.read(v)
        if recv.kind == 'dyn':
            # The receiver's class is unknown: the field name is unanimous over
            # every class that declares it, so join those classes' fields.
            found = self.prog.field_index.get(t.name)
            if not found:
                return sty.DYN
            out = sty.BOT
            for v in found:
                out = sty.join(out, self.read(v))
            return out
        return sty.DYN

    def method(self, t: Term):
        recv = self.ev(t.args[0])
        if recv.kind == 'bot':
            return sty.BOT
        if recv.kind == 'struct':
            cs = self.prog.classes.get(recv.name)
            if cs is None or not cs.unique:
                return sty.DYN
            fs = self.prog.find_method_in(cs, t.name)
            if fs is None:
                return sty.DYN
            key = str(self.cur) + '|' + str(id(fs))
            if key not in self.resolved:
                self.resolved[key] = True
                self.flow_arguments(fs, t)
            return self.read(fs.ret)
        return builtin_method(recv, t.name, t, self)

    def flow_arguments(self, fs, t: Term) -> None:
        # The receiver is `args[0]` and `self` is `params[0]`, so the arguments
        # after it start at parameter 1. The names are for `kwnames`.
        terms = t.args[1:]
        targets = self.prog.param_targets(fs, 1, t.kwnames)
        for i in range(len(terms)):
            if targets[i] >= 0:
                self.add_flow(terms[i], targets[i])

    def grow(self, t: Term):
        cont = self.ev(t.args[0])
        if cont.kind == 'bot':
            return sty.BOT
        name = t.name
        if name == 'append' and cont.kind == 'list':
            x = self.ev(t.args[1])
            return sty.cap(sty.list_of(sty.join(cont.args[0], x)))
        if name == 'add' and cont.kind == 'set':
            x = self.ev(t.args[1])
            return sty.cap(sty.set_of(sty.join(cont.args[0], x)))
        if name == 'extend' and cont.kind in ('list', 'set'):
            x = elem_of(self.ev(t.args[1]))
            if cont.kind == 'list':
                return sty.cap(sty.list_of(sty.join(cont.args[0], x)))
            return sty.cap(sty.set_of(sty.join(cont.args[0], x)))
        if name == 'setitem' and cont.kind == 'list':
            v = self.ev(t.args[2])
            return sty.cap(sty.list_of(sty.join(cont.args[0], v)))
        if name == 'setitem' and cont.kind == 'dict':
            k = self.ev(t.args[1])
            v = self.ev(t.args[2])
            return sty.cap(sty.dict_of(sty.join(cont.args[0], k), sty.join(cont.args[1], v)))
        return cont


def join_all(types: list):
    out = sty.BOT
    for t in types:
        out = sty.join(out, t)
    return out


def elem_of(c):
    """The element type of a container value (a dict's element is its value)."""
    if c.kind == 'bot':
        return sty.BOT
    if c.kind == 'list' or c.kind == 'set':
        return c.args[0]
    if c.kind == 'dict':
        return c.args[1]
    if c.kind == 'str':
        return sty.STR
    if c.kind == 'tuple':
        return join_all(c.args)
    return sty.DYN


def slot_of(c, i: int):
    if c.kind == 'bot':
        return sty.BOT
    if c.kind == 'tuple' and 0 <= i < len(c.args):
        return c.args[i]
    if c.kind == 'list':
        return c.args[0]
    return sty.DYN


_STR_TO_STR = ('strip', 'lstrip', 'rstrip', 'replace', 'lower', 'upper', 'join', 'format')
_STR_TO_BOOL = ('startswith', 'endswith', 'isdigit', 'isalpha', 'isalnum', 'isspace',
                'isupper', 'islower')
_STR_TO_INT = ('find', 'index', 'count')
_LIST_TO_NONE = ('append', 'extend', 'insert', 'remove', 'sort', 'reverse', 'clear')
_SET_TO_NONE = ('add', 'discard', 'remove', 'clear', 'update')
_SET_TO_SELF = ('copy', 'union', 'intersection', 'difference', 'symmetric_difference')
_DICT_TO_NONE = ('update', 'clear')


def builtin_method(recv, name: str, t: Term, solver: _Solver):
    """The result of a method of a builtin container or string (bugs/GIR_type_solver.md, 2.3)."""
    if recv.kind == 'str':
        if name in _STR_TO_STR:
            return sty.STR
        if name in _STR_TO_BOOL:
            return sty.BOOL
        if name in ('split', 'splitlines'):
            return sty.list_of(sty.STR)
        if name in _STR_TO_INT:
            return sty.INT
        return sty.DYN
    if recv.kind == 'list':
        if name == 'pop':
            return recv.args[0]
        if name == 'copy':
            return recv
        if name in _LIST_TO_NONE:
            return sty.NONE
        if name in ('index', 'count'):
            return sty.INT
        return sty.DYN
    if recv.kind == 'set':
        if name == 'pop':
            return recv.args[0]
        if name in _SET_TO_SELF:
            return recv
        if name in _SET_TO_NONE:
            return sty.NONE
        return sty.DYN
    if recv.kind == 'dict':
        if name == 'get':
            if len(t.args) >= 3:
                return sty.join(recv.args[1], solver.ev(t.args[2]))
            return sty.join(recv.args[1], sty.NONE)
        if name == 'pop' or name == 'setdefault':
            return recv.args[1]
        if name == 'keys':
            return sty.list_of(recv.args[0])
        if name == 'values':
            return sty.list_of(recv.args[1])
        if name == 'items':
            return sty.list_of(sty.tuple_of([recv.args[0], recv.args[1]]))
        if name == 'copy':
            return recv
        if name in _DICT_TO_NONE:
            return sty.NONE
        return sty.DYN
    return sty.DYN


def solve(prog: Program) -> None:
    """Fill `prog.vars` with the least solution of the flows (bugs/GIR_type_solver.md, 2.3)."""
    if not prog.vars:
        return
    s = _Solver(prog)
    s.run()
