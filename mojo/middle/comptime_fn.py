"""Compile-time evaluation of a struct's `comptime` alias, through the generic functions it
calls.

A struct may declare a compile-time alias whose value comes from a call to a generic stdlib
function, e.g. `FastDiv[dtype]`'s `comptime uint_type = _uint_type_of_width[
bit_width_of[Self.dtype]()]()`. The monomorphizer substitutes the struct's type parameters
into the source but cannot give that alias its value, so the fields typed with it stay
erased. This module computes the value, so the instance's source can name the concrete
dtype (`Scalar[DType.uint32]`) and every type derived from it resolves.

A monomorphized FUNCTION instance has the same defect one layer out: a body that reads
ANOTHER struct's comptime member or calls its comptime-evaluable static method
(`FPUtils[dtype].integral_type`, `FPUtils[dtype].exponent_bias()` in the stdlib's
`_ldexp_impl`) is its own translation unit with no definition of the referenced struct, so
the reference left in the source reads as a zero word and the type derived from it erases
to the wrong dtype. `resolve_fn_comptime_refs` folds those references the same way the
struct path folds the struct's own aliases (`resolve_struct_aliases`).

The evaluator is small on purpose. It handles what such aliases and comptime bodies are
made of: integer and boolean arithmetic and comparisons, DType values (`DType.uint32`,
compared by name in every spelling a monomorphized body carries), ternary expressions,
`in`-tuple membership, a `bit_width_of[<dtype>]()` builtin (the bit width of a dtype),
DType predicate calls on a bound value (`dtype.is_integral()`), comptime control flow
(`comptime if/elif`, `comptime __match`, `comptime assert`, `comptime var`, `comptime
for` over a foldable range), a struct's own comptime members (`Struct[T].member`), its
comptime-evaluable static methods (`Struct[T].method()`, `DType.mantissa_width[T]()`),
and calls to generic functions whose body is a `return` of such an expression or of such
comptime control flow, with the function's own comptime parameters bound. Anything else
is handed to `comptime.eval_const`; a value it cannot decide is None, and the caller keeps
the existing behaviour.
"""
import re

from fire_compiler import (BinaryOp, BoolLiteral, CallExpr, CompareChain, FunctionDef,
                           IdentExpr, IntLiteral, MemberExpr, Parser, ReturnStmt,
                           SubscriptExpr, TernaryExpr, UnaryOp, py_tokenize, TupleExpr)
from mojo.middle import comptime as _ct

# Bit width of each dtype the codegen knows (the value of `bit_width_of[<dtype>]()`).
DTYPE_BITS = {
    'bool': 1, 'int8': 8, 'uint8': 8, 'int16': 16, 'uint16': 16,
    'int32': 32, 'uint32': 32, 'float32': 32, 'int64': 64, 'uint64': 64,
    'float64': 64, 'float16': 16, 'bfloat16': 16,
}

# Builtin struct name -> the stdlib module that DEFINES it. `DType` is a language
# builtin (usable without an import), and its source — the comptime aliases and the
# static-method bodies the evaluator runs — is the stdlib's own dtype module, where
# `mantissa_width`/`exponent_bias`/`max_exponent` live as comptime-parametrized methods.
# The map is the one place this module assumes a builtin's home; a name it does not
# list is looked up like any other (own module, then the import map) and left alone
# when it is nowhere to be found.
_BUILTIN_STRUCT_MODULES = {'DType': 'std.builtin.dtype'}

_module_cache = {}

# Parsed statements of a module by its SOURCE TEXT, for resolve_fn_comptime_refs
# (which is handed the text, not a dotted name, and runs once per generic-call
# elaboration — the same lookups _module_cache serves for the struct path's
# dotted names, so the two stay one parsed tree per module).
_SRC_STMTS_CACHE = {}


def dtype_name(v):
    """The lowercase dtype name a value denotes ('DType.uint32' -> 'uint32'), or None.

    Deliberately strict — only the `DType.x`/`dtype.x`/`.x` spellings count: a bare
    identifier is a name, not a dtype, until the surrounding comparison says so (see
    `_dtype_name_broad`, which is the one place the bare spelling a monomorphized body
    carries (`Float32`) is accepted, gated on the result being a dtype this evaluator
    knows)."""
    if isinstance(v, str):
        m = re.match(r'^(?:DType|dtype)\.(\w+)$', v.strip())
        if m:
            return m.group(1).lower()
        return None
    if isinstance(v, tuple) and len(v) == 2 and v[0] in ('DType', 'dtype', '.'):
        return str(v[1]).lower()
    return None


def _dtype_name_broad(v):
    """The lowercase dtype name ANY spelling a bound value may carry denotes, or None.

    `DType.float32`, `.float32` and the bare `Float32` are one dtype: a `dtype: DType`
    parameter is instantiated with whichever spelling the call site wrote, and the
    monomorphizer substitutes it textually — so the targs binding of an instantiated
    body holds the bare scalar spelling, and the stdlib's own definitions compare it
    against `DType.float32`. Normalized through comptime.py's spelling reader (the one
    every dtype comparison in the compiler shares) and gated on a KNOWN dtype name by
    the caller, so an ordinary identifier stays a name."""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        return _ct._dtype_spelling_name(s)
    if isinstance(v, tuple) and len(v) == 2 and v[0] in ('DType', 'dtype', '.'):
        return str(v[1]).lower()
    return None


def _param_name(p):
    """The NAME a comptime/bracket parameter entry carries: entries are plain
    strings in this parser, or (name, annotation) pairs where a richer parser
    kept the annotation (see elaborate._fn_type_param_bounds)."""
    if isinstance(p, (list, tuple)):
        return str(p[0])
    return str(p)


def _module_stmts(module):
    """The parsed top-level statements of a module by dotted name, or [] when it cannot be
    resolved to a source file."""
    if module in _module_cache:
        return _module_cache[module]
    stmts = []
    try:
        import imports
        path = imports.resolve_source(module)
        if path:
            with open(path, encoding='utf-8') as f:
                stmts = Parser(py_tokenize(f.read())).parse_module()
    except Exception:
        stmts = []
    _module_cache[module] = stmts or []
    return _module_cache[module]


def import_map(stmts):
    """{name: module} for the `from <module> import <name>` statements of a module."""
    out = {}
    for st in stmts or []:
        if type(st).__name__ == 'FromImportStmt' and not getattr(st, 'wildcard', False):
            for name, _alias in (st.names or []):
                out[str(name)] = str(st.module)
    return out


class _Evaluator:
    """Evaluates expressions of one module. `module_stmts` is that module's own statements;
    calls to a name it imports resolve in the imported module."""

    def __init__(self, module_stmts, depth=0):
        self.stmts = module_stmts or []
        self.imports = import_map(self.stmts)
        self.depth = depth

    def value(self, node, env):
        if node is None:
            return None
        if isinstance(node, (IntLiteral, BoolLiteral)):
            return node.value
        if isinstance(node, IdentExpr):
            name = str(node.name)
            if name in env:
                return env[name]
            return _ct.eval_const(node, env)
        if isinstance(node, MemberExpr):
            if isinstance(node.obj, IdentExpr) and str(node.obj.name) in ('DType', 'dtype'):
                return f'DType.{node.member}'
            if isinstance(node.obj, IdentExpr) and str(node.obj.name) == 'Self':
                # `Self.<param>` is the struct's own type parameter, bound for this instance.
                return env.get(str(node.member))
            if isinstance(node.obj, SubscriptExpr):
                # `Struct[<args>].member` — the comptime member of another struct for
                # this application (its initializer runs with the struct's type
                # parameters bound to the application's arguments).
                return self.struct_member(node, env)
            return _ct.eval_const(node, env)
        if isinstance(node, UnaryOp):
            v = self.value(node.operand, env)
            if v is None:
                return None
            if node.op == '-':
                return -v
            if node.op == 'not':
                return not v
            return None
        if isinstance(node, BinaryOp):
            op = str(node.op)
            if op in ('and', 'or'):
                l = self.value(node.left, env)
                if l is None:
                    return None
                if op == 'and' and not l:
                    return l
                if op == 'or' and l:
                    return l
                return self.value(node.right, env)
            l = self.value(node.left, env)
            r = self.value(node.right, env)
            return _binop(op, l, r)
        if isinstance(node, CompareChain):
            vals = [self.value(o, env) for o in node.operands]
            if any(v is None for v in vals):
                return None
            for i, op in enumerate(node.ops):
                if not _binop(str(op), vals[i], vals[i + 1]):
                    return False
            return True
        if isinstance(node, TernaryExpr):
            c = self.value(node.condition, env)
            if c is None:
                return None
            return self.value(node.then_val if c else node.else_val, env)
        if isinstance(node, CallExpr):
            return self.call(node, env)
        return _ct.eval_const(node, env)

    def call(self, node, env):
        if isinstance(node.func, IdentExpr):
            name = str(node.func.name)
            comptime_args = []
            value_args = list(node.args or [])
        elif isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, IdentExpr):
            name = str(node.func.obj.name)
            idx = node.func.index
            comptime_args = list(idx.elements) if isinstance(idx, TupleExpr) else [idx]
            value_args = list(node.args or [])
        elif isinstance(node.func, (SubscriptExpr, MemberExpr)):
            # A comptime-evaluable static call: `Struct[<args>].method()` or
            # `DType.mantissa_width[<dtype>]()` — no value arguments, so the
            # method body runs HERE (its comptime control flow decided with the
            # application's type args bound). A member call on a VALUE that is a
            # dtype (the `dtype.is_integral()` idiom) folds through the shared
            # predicate table instead.
            if not node.args and not node.kwargs:
                r = self.static_method_call(node, env)
                if r is not None:
                    return r
                if isinstance(node.func, MemberExpr):
                    rv = self.value(node.func.obj, env)
                    dn = _dtype_name_broad(rv)
                    if dn is not None and dn in _ct._KNOWN_DTYPE_NAMES:
                        return _ct._eval_dtype_predicate(dn, str(node.func.member))
            if isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, IdentExpr):
                name = str(node.func.obj.name)
                idx = node.func.index
                comptime_args = list(idx.elements) if isinstance(idx, TupleExpr) else [idx]
                value_args = list(node.args or [])
            else:
                return None
        else:
            return None
        if name == 'bit_width_of' and len(comptime_args) >= 1 and not value_args:
            # The bare spelling the targs binding carries (`Float32`) is a dtype
            # here, so it goes through the broad normalizer, not the strict one.
            dt = _dtype_name_broad(self.value(comptime_args[0], env))
            if dt is None or dt not in _ct._KNOWN_DTYPE_NAMES:
                return None
            return DTYPE_BITS.get(dt)
        if self.depth > 8:
            return None
        bound = [self.value(a, env) for a in comptime_args]
        if any(b is None for b in bound) or value_args:
            return None
        fdef, home = self._find(name)
        if fdef is None:
            return None
        params = list(getattr(fdef, 'comptime_params', None) or [])
        if len(params) != len(bound):
            return None
        callee_env = dict(zip([_param_name(p) for p in params], bound))
        inner = _Evaluator(home, self.depth + 1)
        # A single `return <expr>` body is the common shape; comptime control
        # flow (a `comptime if/elif` chain, `comptime __match`, a `comptime
        # assert` in a reached arm) is the stdlib's other spelling for the same
        # value (`_integral_type_of`, `DType.max_exponent`), and block() decides
        # it — evaluating the assert, which the old single-return fast path
        # merely filtered out.
        body = [s for s in (fdef.body or []) if type(s).__name__ != 'AssertStmt']
        if len(body) == 1 and isinstance(body[0], ReturnStmt) and body[0].value is not None:
            return inner.value(body[0].value, callee_env)
        return inner.block(fdef.body, callee_env)

    def struct_def(self, name):
        """(StructDef, that module's statements) for a struct visible to this
        module, or None: its own definition first, then the import map, then the
        builtin table (DType — a builtin with no import in most modules)."""
        for st in self.stmts:
            if type(st).__name__ == 'StructDef' and str(st.name) == name:
                return st, self.stmts
        module = self.imports.get(name)
        if module is not None:
            home = _module_stmts(module)
            for st in home:
                if type(st).__name__ == 'StructDef' and str(st.name) == name:
                    return st, home
        builtin = _BUILTIN_STRUCT_MODULES.get(name)
        if builtin is not None:
            home = _module_stmts(builtin)
            for st in home:
                if type(st).__name__ == 'StructDef' and str(st.name) == name:
                    return st, home
        return None

    def bind_struct_args(self, index, sdef, env):
        """The {bracket-param: value} binding of one application's type args,
        or None: positional, in the struct's bracket declaration order, so a
        trailing defaulted parameter (FPUtils's `_constraint`) stays unbound
        when the application omits it."""
        idx = index.elements if isinstance(index, TupleExpr) else [index]
        vals = []
        for a in idx:
            v = self.value(a, env)
            if v is None:
                return None
            vals.append(v)
        names = [str(n) for n in (getattr(sdef, 'type_param_names', None)
                                  or getattr(sdef, 'bracket_params', None) or [])]
        if len(vals) > len(names):
            return None
        bound = dict(env)
        for name, v in zip(names, vals):
            bound[name] = v
        return bound

    def struct_member(self, node, env):
        """`Base[<args>].member` — the comptime member of struct Base for this
        application, with the struct's type parameters bound to the application's
        (folded) arguments. node is the member expression whose obj is the
        application."""
        base = node.obj.obj
        if not isinstance(base, IdentExpr):
            return None
        found = self.struct_def(str(base.name))
        if found is None:
            return None
        sdef, home = found
        bound = self.bind_struct_args(node.obj.index, sdef, env)
        if bound is None:
            return None
        aliases = getattr(sdef, 'comptime_aliases', None) or {}
        alias = None
        try:
            alias = aliases.get(str(node.member))
        except Exception:
            alias = None
        if alias is None:
            return None
        return _Evaluator(home, self.depth + 1).value(alias, bound)

    def _find_method(self, sdef, member):
        for m in (getattr(sdef, 'methods', None) or []):
            if type(m).__name__ == 'FunctionDef' and str(m.name) == member:
                return m
        return None

    def static_method_call(self, node, env):
        """`Base[<args>].method()` and `Type.method[<args>](...)` with NO value
        arguments — a comptime-evaluable static call whose body runs here.

        The two spellings bind differently: in the first, the application's args
        are the STRUCT's type parameters (the method reaches them as
        `Self.<param>`); in the second, they are the METHOD's own comptime
        parameters. A method with value parameters is a runtime call: this
        declines and the caller keeps the existing behaviour."""
        if self.depth > 8:
            return None
        func = node.func
        if isinstance(func, MemberExpr) and isinstance(func.obj, SubscriptExpr) \
                and isinstance(func.obj.obj, IdentExpr):
            name = str(func.obj.obj.name)
            index = func.obj.index
            member = str(func.member)
            bind_to_method_params = False
        elif isinstance(func, SubscriptExpr) and isinstance(func.obj, MemberExpr) \
                and isinstance(func.obj.obj, IdentExpr):
            name = str(func.obj.obj.name)
            index = func.index
            member = str(func.obj.member)
            bind_to_method_params = True
        else:
            return None
        found = self.struct_def(name)
        if found is None:
            return None
        sdef, home = found
        idx = index.elements if isinstance(index, TupleExpr) else [index]
        vals = []
        for a in idx:
            v = self.value(a, env)
            if v is None:
                return None
            vals.append(v)
        bound = dict(env)
        if bind_to_method_params:
            method = self._find_method(sdef, member)
            if method is None:
                return None
            if method.params:
                return None
            cparams = [_param_name(p) for p in (getattr(method, 'comptime_params', None) or [])]
            if len(vals) > len(cparams):
                return None
            for pname, v in zip(cparams, vals):
                bound[pname] = v
        else:
            if len(vals) > len(getattr(sdef, 'type_param_names', None)
                               or getattr(sdef, 'bracket_params', None) or []):
                return None
            for pname, v in zip(getattr(sdef, 'type_param_names', None)
                                or getattr(sdef, 'bracket_params', None) or [], vals):
                bound[str(pname)] = v
            method = self._find_method(sdef, member)
            if method is None:
                return None
            if method.params:
                return None
        return _Evaluator(home, self.depth + 1).block(method.body, bound)

    def block(self, stmts, env):
        """The value a comptime statement block produces, or None when it cannot
        be decided. The bodies of the comptime-evaluable aliases/methods are
        written in comptime control flow — `comptime if/elif` chains,
        `comptime __match`, `comptime assert`, `comptime var`/`comptime for`
        bindings and a `return` of an expression — and this walks it the way the
        language does: the chosen arm only, the matched case only, a provably
        false assert as a failure (declined as None, so the caller keeps the
        existing behaviour rather than accept a wrong value). A runtime statement
        in a position that decides a value ends the evaluation: the body is not
        comptime-decidable, and pretending otherwise would invent a value."""
        env = dict(env)
        for st in (stmts or []):
            t = type(st).__name__
            if t == 'ReturnStmt':
                return self.value(getattr(st, 'value', None), env)
            if t == 'ComptimeIfStmt':
                c = self.value(getattr(st, 'condition', None), env)
                if c is None:
                    return None
                if c:
                    arm = getattr(st, 'then_body', None)
                else:
                    arm = None
                    for cond, body in (getattr(st, 'elifs', None) or []):
                        cv = self.value(cond, env)
                        if cv is None:
                            return None
                        if cv:
                            arm = body
                            break
                    if arm is None:
                        arm = getattr(st, 'else_body', None)
                if arm is None:
                    return None
                return self.block(arm, env)
            if t == 'MatchStmt':
                sv = self.value(getattr(st, 'subject', None), env)
                if sv is None:
                    return None
                for case in (getattr(st, 'cases', None) or []):
                    pats = getattr(case, 'patterns', None) or []
                    chosen = None
                    if not pats:
                        chosen = True  # `case _:` spelled with an empty pattern list
                    else:
                        for p in pats:
                            if isinstance(p, IdentExpr) and str(p.name) == '_':
                                chosen = True  # `case _:` (the parser keeps the `_`)
                                break
                            pv = self.value(p, env)
                            if pv is None:
                                return None
                            if _dtype_name_broad(sv) == _dtype_name_broad(pv) \
                                    or pv == sv:
                                chosen = True
                                break
                    if chosen is None:
                        continue
                    guard = getattr(case, 'guard', None)
                    if guard is not None:
                        gv = self.value(guard, env)
                        if gv is None or not gv:
                            continue
                    return self.block(getattr(case, 'body', None), env)
                return None  # no case matched (no wildcard): the value is undefined
            if t == 'ComptimeVarStmt':
                v = self.value(getattr(st, 'value', None), env)
                if v is None:
                    return None
                tgt = getattr(st, 'target', None)
                if isinstance(tgt, str) and tgt:
                    env[tgt] = v
                continue
            if t == 'ComptimeForStmt':
                env, v = self._comptime_for(st, env)
                if v is not None:
                    return v
                continue
            if t == 'AssertStmt':
                v = self.value(getattr(st, 'value', None), env)
                if v is False or v is None:
                    return None  # provably false, or undecidable: decline
                continue
            if t in ('ExprStmt', 'PassStmt', 'GlobalStmt', 'NonlocalStmt',
                     'ImportStmt', 'FromImportStmt', 'DelStmt'):
                continue
            return None  # a runtime statement: this block is not comptime-decidable
        return None  # fell off the end without a return

    def _comptime_for(self, st, env):
        """Unroll a `comptime for` over a foldable iterable (a `range` of
        foldable ints, or a foldable list/tuple), returning (env_after, value):
        the value is the body's own return when one arm produces it, else None
        (the loop carried no value and the enclosing block continues)."""
        it = getattr(st, 'iterable', None)
        items = None
        if isinstance(it, CallExpr) and isinstance(it.func, IdentExpr) \
                and str(it.func.name) == 'range':
            args = []
            for a in (it.args or []):
                v = self.value(a, env)
                if not isinstance(v, int) or isinstance(v, bool):
                    args = None
                    break
                args.append(v)
            if args is not None and 1 <= len(args) <= 3:
                if len(args) == 1:
                    items = list(range(0, args[0]))
                elif len(args) == 2:
                    items = list(range(args[0], args[1]))
                else:
                    items = list(range(args[0], args[1], args[2]))
        if items is None:
            w = self.value(it, env)
            if isinstance(w, (list, tuple)):
                items = list(w)
        if items is None:
            return env, None
        tgt = getattr(st, 'target', None)
        env_after = dict(env)
        for item in items:
            env_i = dict(env)
            if isinstance(tgt, str) and tgt:
                env_i[tgt] = item
            v = self.block(getattr(st, 'body', None), env_i)
            if v is not None:
                return env_i, v
            env_after = env_i
        return env_after, None

    def _find(self, name):
        for st in self.stmts:
            if type(st).__name__ == 'FunctionDef' and str(st.name) == name:
                return st, self.stmts
        module = self.imports.get(name)
        if module is None:
            return None, None
        home = _module_stmts(module)
        for st in home:
            if type(st).__name__ == 'FunctionDef' and str(st.name) == name:
                return st, home
        return None, None


def _binop(op, l, r):
    if l is None or r is None:
        return None
    if op == 'in':
        # `dtype in (DType.float8_e5m2, DType.float16)` — the membership idiom
        # of the stdlib's comptime if chains, decided by dtype name when the
        # left side is a dtype, else by plain membership.
        if isinstance(r, (list, tuple)):
            ln = _dtype_name_broad(l)
            if ln is not None and ln in _ct._KNOWN_DTYPE_NAMES:
                for el in r:
                    if ln == _dtype_name_broad(el):
                        return True
                return False
            try:
                return l in r
            except Exception:
                return None
        return None
    dl, dr = dtype_name(l), dtype_name(r)
    if dl is not None or dr is not None:
        if op in ('==', '!='):
            # Both sides may name the SAME dtype in different spellings — the
            # targs binding carries the bare scalar spelling a monomorphized
            # body substitutes (`Float32`) while the stdlib compares against
            # `DType.float32` — so when both sides name a dtype this evaluator
            # knows, compare the normalized names; otherwise keep the old
            # strict-spelling answer.
            if op == '==':
                dl2, dr2 = _dtype_name_broad(l), _dtype_name_broad(r)
                if dl2 in _ct._KNOWN_DTYPE_NAMES and dr2 in _ct._KNOWN_DTYPE_NAMES:
                    return dl2 == dr2
                return dl == dr
            dl2, dr2 = _dtype_name_broad(l), _dtype_name_broad(r)
            if dl2 in _ct._KNOWN_DTYPE_NAMES and dr2 in _ct._KNOWN_DTYPE_NAMES:
                return dl2 != dr2
            return dl != dr
        return None
    try:
        if op == '+': return l + r
        if op == '-': return l - r
        if op == '*': return l * r
        if op == '//': return l // r
        if op == '%': return l % r
        if op == '<<': return l << r
        if op == '>>': return l >> r
        if op == '&': return l & r
        if op == '|': return l | r
        if op == '^': return l ^ r
        if op == '==': return l == r
        if op == '!=': return l != r
        if op == '<': return l < r
        if op == '<=': return l <= r
        if op == '>': return l > r
        if op == '>=': return l >= r
    except Exception:
        return None
    return None


def evaluate(expr, bindings, module_src):
    """The compile-time value of EXPR (an AST node of the module whose source is
    MODULE_SRC) with the names in BINDINGS bound, or None when it cannot be decided.
    BINDINGS maps a name (a struct's type parameter, e.g. `dtype`) to its value
    ('DType.uint32', an int, a bool)."""
    stmts = Parser(py_tokenize(module_src)).parse_module()
    return _Evaluator(stmts).value(expr, dict(bindings))


_ALIAS_LINE = re.compile(r'^    comptime ([A-Za-z_]\w*) = (.+)$', re.M)


def resolve_struct_aliases(tmpl_src, targs, module_src):
    """Return TMPL_SRC with each `Self.<alias>` that a struct's single-line `comptime <alias> =
    <expr>` member can evaluate, for the instance whose type arguments are TARGS, replaced by
    its value. A value that cannot be decided is left as written, so the caller's existing
    handling applies unchanged. TARGS maps each type parameter to its value ('DType.uint32')."""
    if not tmpl_src or not module_src:
        return tmpl_src
    try:
        expr_of = {}
        for m in _ALIAS_LINE.finditer(tmpl_src):
            name, text = m.group(1), m.group(2).strip()
            expr_of[name] = text
        if not expr_of:
            return _fold_bit_widths(tmpl_src, targs)
        stmts = Parser(py_tokenize(module_src)).parse_module()
        ev = _Evaluator(stmts)
        out = tmpl_src
        for name, text in expr_of.items():
            try:
                expr = Parser(py_tokenize('__v = ' + text)).parse_module()[0].value
            except Exception:
                continue
            val = ev.value(expr, dict(targs))
            if isinstance(val, bool) or val is None:
                continue
            if isinstance(val, int):
                repl = str(val)
            elif dtype_name(val) is not None:
                repl = f'DType.{dtype_name(val)}'
            else:
                continue
            out = re.sub(rf'\bSelf\.{re.escape(name)}\b', repl, out)
        return _fold_bit_widths(out, targs)
    except Exception:
        return tmpl_src


_BIT_WIDTH_OF = re.compile(r'\bbit_width_of\[\s*(?:Self\.)?(\w+)\s*\]\(\s*\)')
_BIT_WIDTH_LIT = re.compile(r'\bbit_width_of\[\s*DType\.(\w+)\s*\]\(\s*\)')


def _fold_bit_widths(text, targs):
    """Fold `bit_width_of[<dtype>]()` to its integer. The bit width of a dtype is a
    compile-time constant, but the codegen's folder does not evaluate `bit_width_of`, so a
    `comptime if bit_width_of[Self.dtype]() <= 32` stayed live and emitted the 64-bit arm for a
    32-bit dtype. Folded here, the condition is an integer comparison the folder decides."""
    def repl_param(m):
        v = targs.get(m.group(1))
        dt = dtype_name(v) if v is not None else None
        if dt is None or dt not in DTYPE_BITS:
            return m.group(0)
        return str(DTYPE_BITS[dt])

    def repl_lit(m):
        dt = m.group(1).lower()
        if dt not in DTYPE_BITS:
            return m.group(0)
        return str(DTYPE_BITS[dt])

    text = _BIT_WIDTH_OF.sub(repl_param, text)
    return _BIT_WIDTH_LIT.sub(repl_lit, text)


_REF_NAME = re.compile(r'(?<![.\w])([A-Za-z_]\w*)\s*\[')


def _ref_spans(text):
    """(start, end, base, argtext, member, is_call) for every `Base[<balanced
    args>].member` reference in TEXT, and for every `Base[<balanced
    args>].member()` whose parens hold no arguments. A `Base[...]` with no
    member access (a constructor call, a runtime subscript) is not a
    reference, and neither is `.member(<args>)`: a value argument makes the
    call a runtime one. Scan stops at an unbalanced bracket."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        m = _REF_NAME.search(text, i)
        if m is None:
            break
        bstart = m.start(1)
        bopen = m.end() - 1  # the '[' is the match's last char
        j, depth = bopen, 0
        closed = False
        while j < n:
            c = text[j]
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    closed = True
                    break
            j += 1
        if not closed:
            break
        argtext = text[bopen + 1:j]
        mm = re.match(r'\s*\.([A-Za-z_]\w*)', text[j + 1:])
        if mm is None:
            i = j + 1
            continue
        member = mm.group(1)
        p = j + 1 + mm.end(1)
        pm = re.match(r'\s*\(', text[p:])
        if pm is not None:
            pj = p + pm.end() - 1  # the '(' is the match's last char
            q, d2 = pj, 0
            pclosed = False
            while q < n:
                c = text[q]
                if c == '(':
                    d2 += 1
                elif c == ')':
                    d2 -= 1
                    if d2 == 0:
                        pclosed = True
                        break
                q += 1
            if pclosed and text[pj + 1:q].strip() == '':
                out.append((bstart, q + 1, m.group(1), argtext, member, True))
                i = q + 1
                continue
            i = p  # a call with value args: not a reference; keep scanning after it
            continue
        out.append((bstart, p, m.group(1), argtext, member, False))
        i = p
    return out


def _value_text(v):
    """The source text a folded value rewrites to, or None: an int/bool as its
    literal, a dtype in its canonical `DType.<name>` spelling — the one every
    dtype reader in the compiler accepts (see _comptime_bound_text)."""
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, int):
        return str(v)
    dn = _dtype_name_broad(v)
    if dn is not None and dn in _ct._KNOWN_DTYPE_NAMES:
        return 'DType.' + dn
    return None


def resolve_fn_comptime_refs(tmpl_src, targs, module_src):
    """Return TMPL_SRC with every comptime reference to a struct's members that
    this instance can decide replaced by its value: `FPUtils[dtype].integral_type`
    -> `DType.int32`, `FPUtils[dtype].exponent_bias()` -> `127`.

    A monomorphized instance is its own translation unit with no definition of
    a struct its home module merely imports, so such a reference left in the
    source reads as a zero word and the type derived from it erases to the
    wrong dtype — the `float << float` that stopped the stdlib's _ldexp_impl
    family (bugs/CODEGEN_stdlib_syntax_six_files_red...). This is the
    function-body half of what resolve_struct_aliases does for the struct's
    own aliases: the same evaluator, the same TARGS/
    MODULE_SRC arguments, and the same rule that a reference which cannot be
    decided stays as written, so the caller's existing handling applies
    unchanged. TARGS maps each type parameter to its value; MODULE_SRC is the
    home module whose import map locates the referenced struct (a builtin such
    as DType is located by _BUILTIN_STRUCT_MODULES)."""
    if not tmpl_src or not module_src:
        return tmpl_src
    try:
        stmts = _SRC_STMTS_CACHE.get(module_src)
        if stmts is None:
            stmts = Parser(py_tokenize(module_src)).parse_module()
            _SRC_STMTS_CACHE[module_src] = stmts
        ev = _Evaluator(stmts)
        env = {}
        for k, v in dict(targs or {}).items():
            env[str(k)] = v
        repl = []
        for (start, end, base, argtext, member, is_call) in _ref_spans(tmpl_src):
            expr = base + '[' + argtext + '].' + member
            if is_call:
                expr += '()'
            try:
                node = Parser(py_tokenize('__v = ' + expr)).parse_module()[0].value
            except Exception:
                continue
            v = ev.value(node, dict(env))
            text = _value_text(v)
            if text is None:
                continue
            repl.append((start, end, text))
        # right-to-left so the earlier spans' offsets stay valid
        out = tmpl_src
        for idx in range(len(repl) - 1, -1, -1):
            start, end, text = repl[idx]
            out = out[:start] + text + out[end:]
        return out
    except Exception:
        return tmpl_src
