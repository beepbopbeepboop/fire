"""The constraint IR of the whole-closure type solver (bugs/GIR_type_solver.md, 2.2).

A function body is summarized as FLOWS, `term -> var`: the value of the term may
reach the variable. Flows are flow-insensitive; statement order is ignored. The
only flow-sensitive rule is the `narrow` term (an `isinstance` branch).

Term ops (`Term.op`):
    const   `ty`                                   a fixed source type
    var     `var`                                  the solution of a variable
    call    `name` (FuncKey), `var` (its return)   a resolved static call
    method  `name` (method), args [recv, a1, ...], `kwnames` tails the args
    field   `name` (field), args [recv]
    elem    args [container]                       an element (dict: its value)
    slot    `name` (index as text), args [tuple]   one tuple slot
    narrow  `name` (class), `var`                  `n` inside `isinstance(n, C)`
    join    args                                   join of every argument
    cont    `name` (list|set|dict|tuple), args     a container literal
    grow    `name` (append|add|extend|setitem),    a container's write: its new
            args [container var term, ...]         type is the flow's `dst`

`cont` and `grow` are not in the design's list; they are the two forms a
container literal and a container write take. A `list` literal is
`cont('list', elements)`, a `dict` literal `cont('dict', k0, v0, k1, v1, ...)`,
and `x.append(e)` is a `grow` flow whose `dst` is `x`'s variable. Both are
needed because the type of a container is built from its elements, not
assigned to it.
"""
from __future__ import annotations

from mojo.tsolve import sty


class Term:
    def __init__(self, op: str, ty, var: int, name: str, args: list, kwnames: list):
        self.op: str = op          # see the module docstring
        self.ty: object = ty       # `const`: an STy; else None
        self.var: int = var        # `var`/`call`/`narrow`: a TVar id; else -1
        self.name: str = name      # see the module docstring; '' when unused
        self.args: list = args     # sub-terms
        self.kwnames: list = kwnames  # `method` only: keyword names of the args' tail


def const_term(ty) -> Term:
    return Term('const', ty, -1, '', [], [])


def var_term(var: int) -> Term:
    return Term('var', None, var, '', [], [])


def op_term(op: str, name: str, args: list, kwnames=None) -> Term:
    if kwnames is None:
        kwnames = []
    return Term(op, None, -1, name, args, kwnames)


class Flow:
    def __init__(self, src: Term, dst: int, origin: str):
        self.src: Term = src
        self.dst: int = dst
        self.origin: str = origin   # '<abspath>:<line>' of the statement that made it, or ''


class FnSummary:
    def __init__(self, key: str, path: str, name: str, cls: str):
        self.key: str = key        # FuncKey: path + '\x1f' + 'f' or 'Cls.m'
        self.path: str = path      # abspath of the defining module
        self.name: str = name      # the bare name ('f' or 'm')
        self.cls: str = cls        # the class of a method, else ''
        self.params: list = []     # TVar per parameter (`self` included)
        self.param_names: list = []
        self.ret: int = -1         # TVar of the return
        self.annotated_ret: bool = False  # the return is pinned to its annotation
        self.decidable: bool = True       # False: no answer is claimed for it
        self.ret_terms: list = []         # every term that flows into `ret` (returns and fall-off)
        self.deco: str = ''               # '' | 'staticmethod' | 'classmethod' (4.2e)


class ClassSummary:
    def __init__(self, name: str, path: str, bases: list):
        self.name: str = name
        self.path: str = path
        self.bases: list = bases        # base class names, as written
        self.fields: dict = {}          # field name -> TVar
        self.methods: dict = {}         # method name -> FnSummary
        self.unique: bool = True        # False: another class of this name exists


SEP = '\x1f'

# The struct kind of a builtin file object (`open(...)`). No closure class has this name.
FILE_KIND = '<file>'


def func_key(path: str, name: str) -> str:
    """The FuncKey of a definition: the module's abspath, SEP, then 'f' or 'Cls.m'."""
    return path + SEP + name


class Program:
    """The summary of a closure, and then (after `solve`) its solution."""

    def __init__(self):
        self.vars: list = []           # STy per TVar: the solution
        self.pinned: list = []         # bool per TVar: flows into it are ignored
        self.var_names: list = []      # debugging only
        self.flows: list = []
        self.fns: dict = {}            # FuncKey -> FnSummary
        self.classes: dict = {}        # class name -> ClassSummary (first definition)
        self.field_index: dict = {}    # field name -> [TVar] over every class
        self.loose: dict = {}          # field name -> TVar, for a field no class declares (4.2f)

    def new_var(self, name: str) -> int:
        self.vars.append(sty.BOT)
        self.pinned.append(False)
        self.var_names.append(name)
        return len(self.vars) - 1

    def pin(self, var: int, ty) -> None:
        self.vars[var] = ty
        self.pinned[var] = True

    def loose_var(self, name: str) -> int:
        """The one variable a store to a field NO class declares writes, and a read through a
        class that lacks the field reads (`gen.cache = c` in a helper, `gen.cache` elsewhere).
        Registered in field_index, so a read on an unknown receiver sees it too (4.2f)."""
        if name not in self.loose:
            var = self.new_var(name)
            self.loose[name] = var
            self.field_index.setdefault(name, []).append(var)
        return self.loose[name]

    def add_flow(self, src: Term, dst: int, origin: str = '') -> None:
        self.flows.append(Flow(src, dst, origin))

    def class_is_unique(self, name: str) -> bool:
        cs = self.classes.get(name)
        return cs is not None and cs.unique

    def find_field_var_in(self, cs, name: str, depth: int = 0):
        """The TVar of field `name` on class `cs` or a base, else None."""
        if name in cs.fields:
            return cs.fields[name]
        if depth > 16:
            return None
        for b in cs.bases:
            bc = self.classes.get(b)
            if bc is not None:
                v = self.find_field_var_in(bc, name, depth + 1)
                if v is not None:
                    return v
        return None

    def find_method_in(self, cs, name: str, depth: int = 0):
        """The FnSummary of method `name` on class `cs` or a base, else None."""
        if name in cs.methods:
            return cs.methods[name]
        if depth > 16:
            return None
        for b in cs.bases:
            bc = self.classes.get(b)
            if bc is not None:
                m = self.find_method_in(bc, name, depth + 1)
                if m is not None:
                    return m
        return None

    def receiver_offset(self, fs: FnSummary) -> int:
        """Where a method's first ARGUMENT lands: after `self` or `cls` (1), or at parameter 0
        for a staticmethod, which has no receiver parameter (4.2e)."""
        return 0 if fs.deco == 'staticmethod' else 1

    def param_targets(self, fs: FnSummary, offset: int, names: list) -> list:
        """Where each argument of a call flows: one entry per argument term.

        `names` is '' for a positional argument and the keyword's name for a
        keyword one (or an empty list when every argument is positional).
        `offset` is 1 for a method's receiver (`self` is `params[0]`) and for
        a constructor's `__init__`, else 0. An entry is the parameter's TVar,
        or -1 when the argument has no parameter (too many, `*args`, an
        unknown keyword): such an argument is not flowed anywhere.
        """
        out = []
        pos = 0
        for i in range(len(names)):
            nm = names[i]
            idx = -1
            if nm == '':
                idx = pos + offset
                pos += 1
            else:
                idx = _param_index(fs, nm)
            var = -1
            if idx >= 0 and idx < len(fs.params):
                if not fs.param_names[idx].startswith('*'):
                    var = fs.params[idx]
            out.append(var)
        return out


def _param_index(fs: FnSummary, name: str) -> int:
    for i in range(len(fs.param_names)):
        if fs.param_names[i] == name:
            return i
    return -1
