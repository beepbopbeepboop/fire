"""Compile-time evaluation of a struct's `comptime` alias, through the generic functions it
calls.

A struct may declare a compile-time alias whose value comes from a call to a generic stdlib
function, e.g. `FastDiv[dtype]`'s `comptime uint_type = _uint_type_of_width[
bit_width_of[Self.dtype]()]()`. The monomorphizer substitutes the struct's type parameters
into the source but cannot give that alias its value, so the fields typed with it stay
erased. This module computes the value, so the instance's source can name the concrete
dtype (`Scalar[DType.uint32]`) and every type derived from it resolves.

The evaluator is small on purpose. It handles what such aliases are made of: integer and
boolean arithmetic and comparisons, DType values (`DType.uint32`, compared by name), ternary
expressions, a `bit_width_of[<dtype>]()` builtin (the bit width of a dtype), and calls to
generic functions whose body is a `return` of such an expression, with the function's own
comptime parameters bound. Anything else is handed to `comptime.eval_const`; a value it cannot
decide is None, and the caller keeps the existing behaviour.
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

_module_cache = {}


def dtype_name(v):
    """The lowercase dtype name a value denotes ('DType.uint32' -> 'uint32'), or None."""
    if isinstance(v, str):
        m = re.match(r'^(?:DType|dtype)\.(\w+)$', v.strip())
        if m:
            return m.group(1).lower()
        return None
    if isinstance(v, tuple) and len(v) == 2 and v[0] in ('DType', 'dtype', '.'):
        return str(v[1]).lower()
    return None


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
        else:
            return None
        if name == 'bit_width_of' and len(comptime_args) >= 1 and not value_args:
            dt = dtype_name(self.value(comptime_args[0], env))
            return DTYPE_BITS.get(dt) if dt is not None else None
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
        body = [s for s in (fdef.body or []) if type(s).__name__ != 'AssertStmt']
        if len(body) != 1 or not isinstance(body[0], ReturnStmt) or body[0].value is None:
            return None
        callee_env = dict(zip([str(p) for p in params], bound))
        inner = _Evaluator(home, self.depth + 1)
        return inner.value(body[0].value, callee_env)

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
    dl, dr = dtype_name(l), dtype_name(r)
    if dl is not None or dr is not None:
        if op == '==':
            return dl == dr
        if op == '!=':
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
