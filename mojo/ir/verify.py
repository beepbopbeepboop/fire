"""Type-check a `Module`.

Every finding has a `code`.  The codes are the vocabulary the ratchet in
`tools/gimple_lint.py` counts, so keep them stable.

  <pos>-<class>   pos is copy | op | ret | arg | cast | cmp
                  class is a `types.mismatch_class` name, e.g. copy-int-widen
  lit-<class>     same, but the offending operand is a literal
                  (`x = 1` into an int64_t, `p != 0` on a pointer)
  cmp-result      a comparison stored into something that is not _Bool
  cast-illegal    a cast GIMPLE has no conversion for
  arg-count       wrong number of arguments

`unknown` things (an undeclared name, an unknown callee, an unmodelled
expression) never produce a finding: the checker only reports what it can
prove.  They are counted in `Report.unknown` so coverage is visible.
"""
from __future__ import annotations

from mojo.ir.types import (Type, VOID, BOOL, INT, I64, U64, F64, CHARP, FN, FNP,
                           ptr_to, mismatch_class, cast_is_legal, GIMPLE_ILLEGAL)
from mojo.ir.instr import Ex, Instr, Function, Module, Sig


class Finding:
    def __init__(self, code: str, fn: str, tagged: bool, src_line: int,
                 out_line: int, stmt: str, detail: str):
        self.code: str = code
        self.fn: str = fn
        self.tagged: bool = tagged
        self.src_line: int = src_line
        self.out_line: int = out_line
        self.stmt: str = stmt
        self.detail: str = detail


class Report:
    def __init__(self):
        self.findings: list[Finding] = []
        self.unknown: dict[str, int] = {}
        self.stmts: int = 0
        self.functions: int = 0
        self.functions_opaque: int = 0
        self.stmts_opaque: int = 0

    def note_unknown(self, what: str) -> None:
        self.unknown[what] = self.unknown.get(what, 0) + 1


_CMP_OPS: dict[str, bool] = {'<': True, '>': True, '<=': True, '>=': True,
                             '==': True, '!=': True}
_SHIFT_OPS: dict[str, bool] = {'<<': True, '>>': True}
_LOGIC_OPS: dict[str, bool] = {'&&': True, '||': True}


class _Ctx:
    def __init__(self, mod: Module, fn: Function, rep: Report):
        self.mod: Module = mod
        self.fn: Function = fn
        self.rep: Report = rep
        self.ins: Instr = Instr('opaque')
        self.unknown: bool = False     # set when typing met something unknown
        self.is_cmp: bool = False      # the last typed Ex was a comparison

    def report(self, code: str, detail: str) -> None:
        self.rep.findings.append(Finding(
            code, self.fn.name, self.fn.tagged, self.ins.src_line,
            self.ins.out_line, self.ins.show(), detail))


def _is_literal(e: Ex) -> bool:
    if e.kind == 'int' or e.kind == 'float':
        return True
    if e.kind == 'un' and e.op == '-':
        return _is_literal(e.a)
    return False


def _lookup_var(cx: _Ctx, name: str) -> Type:
    t = cx.fn.locals.get(name)
    if t is not None:
        return t
    t = cx.mod.globals.get(name)
    if t is not None:
        return t
    if name in cx.mod.sigs:
        return FN
    if name == 'NULL':
        cx.unknown = True
        return VOID
    cx.unknown = True
    if name not in cx.mod.consts:
        cx.rep.note_unknown('name')
    return VOID


def _field_type(cx: _Ctx, base: Type, name: str, arrow: bool) -> Type:
    st = base
    if arrow:
        if base.kind != 'ptr':
            cx.unknown = True
            return VOID
        st = base.pointee
    fields = cx.mod.structs.get(st.name)
    if fields is None:
        cx.unknown = True
        cx.rep.note_unknown('struct')
        return VOID
    ft = fields.get(name)
    if ft is None:
        cx.unknown = True
        cx.rep.note_unknown('field')
        return VOID
    return ft


def _check_use(cx: _Ctx, pos: str, dst: Type, src: Type, e: Ex) -> None:
    """`e` (of type `src`) is used where `dst` is expected."""
    if src is FN and dst.kind == 'ptr':
        return                      # a function name decays to its address
    cls = mismatch_class(dst, src)
    if cls == '':
        return
    if _is_literal(e):
        # an integer literal takes the type of its destination; only a
        # literal of the wrong KIND is a finding
        if cls == 'int-widen' or cls == 'int-narrow' or cls == 'int-sign':
            return
        if cls == 'float-width':
            return
        # GCC's GIMPLE reader gives a constant the type of its destination:
        # `p = 0`, `f (0)` for a pointer and `b = 1` for a _Bool are legal
        # (calibrated: 115 such statements sit in __GIMPLE functions that
        # compile).  An int literal as a double is not.
        if cls == 'int-ptr' and e.kind == 'int' and e.ival == 0:
            return
        if cls == 'bool-int' and e.kind == 'int' and (e.ival == 0 or e.ival == 1):
            return
        cx.report('lit-' + cls, pos + ': ' + src.name + ' literal used as ' + dst.name)
        return
    if pos == 'arg' and cls == 'int-sign':
        return      # same register, same bits: `malloc (int64_t)` is harmless
    if pos == 'arg' and cls == 'bool-int' and src.kind == 'bool':
        return      # a _Bool is 0 or 1 in a full register (rt_call.py agrees)
    cx.report(pos + '-' + cls, src.name + ' used as ' + dst.name)


def _type_call(cx: _Ctx, e: Ex) -> Type:
    callee = e.a
    sig: Sig = Sig('', VOID)
    found = False
    if callee.kind == 'var':
        if callee.name in cx.fn.locals:
            found = False
        else:
            s = cx.mod.sigs.get(callee.name)
            if s is not None:
                sig = s
                found = True
    # type every argument (finds nested problems, sets unknown flags locally)
    arg_types: list[Type] = []
    arg_unknown: list[bool] = []
    for a in e.args:
        saved = cx.unknown
        cx.unknown = False
        arg_types.append(type_of(cx, a))
        arg_unknown.append(cx.unknown)
        cx.unknown = saved
    cx.is_cmp = False
    if not found:
        cx.unknown = True
        cx.rep.note_unknown('callee')
        return VOID
    if sig.unchecked:
        return sig.ret
    n = len(sig.params)
    if len(e.args) < n or (len(e.args) > n and not sig.variadic):
        cx.report('arg-count', callee.name + ' takes ' + str(n) + ', given '
                  + str(len(e.args)))
        return sig.ret
    i = 0
    while i < n:
        if not arg_unknown[i]:
            _check_use(cx, 'arg', sig.params[i], arg_types[i], e.args[i])
        i += 1
    return sig.ret


def type_of(cx: _Ctx, e: Ex) -> Type:
    """The type of `e`.  When something is unknown, sets cx.unknown and
    returns VOID; the caller must then skip its check."""
    cx.is_cmp = False
    k = e.kind
    if k == 'var':
        return _lookup_var(cx, e.name)
    if k == 'int':
        if 'u' in e.suffix:
            return U64
        if 'l' in e.suffix:
            return I64
        if e.ival > 2147483647 or e.ival < -2147483648:
            return I64
        return INT
    if k == 'float':
        return F64
    if k == 'str':
        return CHARP
    if k == 'field':
        bt = type_of(cx, e.a)
        if cx.unknown:
            return VOID
        return _field_type(cx, bt, e.name, e.arrow)
    if k == 'index':
        bt = type_of(cx, e.a)
        type_of(cx, e.b)
        cx.is_cmp = False
        if cx.unknown:
            return VOID
        if bt.kind != 'ptr':
            cx.unknown = True
            return VOID
        return bt.pointee
    if k == 'addr':
        bt = type_of(cx, e.a)
        if cx.unknown:
            return VOID
        if bt is FN:
            return FNP
        return ptr_to(bt)
    if k == 'deref':
        bt = type_of(cx, e.a)
        if cx.unknown:
            return VOID
        if bt.kind != 'ptr':
            cx.unknown = True
            return VOID
        return bt.pointee
    if k == 'un':
        bt = type_of(cx, e.a)
        cx.is_cmp = False
        if e.op == '!':
            return INT              # C, not GIMPLE: only hand-written helpers
        return bt
    if k == 'cast':
        st = type_of(cx, e.a)
        cx.is_cmp = False
        if cx.unknown:
            cx.unknown = False      # the cast's own type is known
            return e.ty
        if st is FN:
            return e.ty
        if not cast_is_legal(e.ty, st):
            cx.report('cast-illegal', st.name + ' cast to ' + e.ty.name)
        return e.ty
    if k == 'call':
        return _type_call(cx, e)
    if k == 'bin':
        at = type_of(cx, e.a)
        au = cx.unknown
        cx.unknown = False
        bt = type_of(cx, e.b)
        bu = cx.unknown
        cx.is_cmp = False
        if e.op in _LOGIC_OPS:
            cx.unknown = False
            return INT              # C, not GIMPLE: only hand-written helpers
        if e.op in _CMP_OPS:
            cx.unknown = False
            if not au and not bu:
                if _is_literal(e.b):
                    _check_use(cx, 'cmp', at, bt, e.b)
                elif _is_literal(e.a):
                    _check_use(cx, 'cmp', bt, at, e.a)
                else:
                    _check_use(cx, 'cmp', at, bt, e.b)
            cx.is_cmp = True
            return BOOL
        cx.unknown = au or bu
        if cx.unknown:
            return VOID
        if e.op in _SHIFT_OPS:
            return at
        if at.kind == 'ptr' or bt.kind == 'ptr':
            # pointer arithmetic: not modelled
            if at.kind == 'ptr':
                return at
            return bt
        if _is_literal(e.b):
            _check_use(cx, 'op', at, bt, e.b)
            return at
        if _is_literal(e.a):
            _check_use(cx, 'op', bt, at, e.a)
            return bt
        _check_use(cx, 'op', at, bt, e.b)
        return at
    if k == 'cond':
        type_of(cx, e.a)
        cx.unknown = False
        bt = type_of(cx, e.b)
        bu = cx.unknown
        cx.unknown = False
        ct = type_of(cx, e.c)
        cu = cx.unknown
        cx.is_cmp = False
        cx.unknown = bu or cu
        if cx.unknown:
            return VOID
        if _is_literal(e.b) and not _is_literal(e.c):
            _check_use(cx, 'op', ct, bt, e.b)
            return ct
        _check_use(cx, 'op', bt, ct, e.c)
        return bt
    cx.unknown = True
    cx.rep.note_unknown('expr')
    return VOID


def _check_instr(cx: _Ctx, ins: Instr) -> None:
    cx.ins = ins
    cx.unknown = False
    k = ins.kind
    if k == 'assign':
        lt = type_of(cx, ins.lhs)
        lu = cx.unknown
        cx.unknown = False
        rt = type_of(cx, ins.rhs)
        is_cmp = cx.is_cmp
        if lu or cx.unknown:
            return
        r = ins.rhs
        if is_cmp:
            if lt.kind != 'bool':
                cx.report('cmp-result', 'comparison stored into ' + lt.name)
            return
        if r.kind == 'cast':
            # GCC ignores the written type: the LHS type decides the
            # conversion.  A cast whose written type is not the LHS type is
            # therefore two conversions in C and one in GIMPLE.
            cls = mismatch_class(lt, r.ty)
            if cls != '' and cls != 'ptr-kind':
                cx.report('cast-' + cls, 'cast to ' + r.ty.name + ' stored into ' + lt.name)
            return
        if r.kind == 'call' and lt.kind == 'ptr' and rt.kind == 'ptr':
            return
        if rt.kind == 'void' and r.kind == 'call':
            cx.report('copy-kind', 'void call result stored into ' + lt.name)
            return
        _check_use(cx, 'copy', lt, rt, r)
        return
    if k == 'expr':
        type_of(cx, ins.rhs)
        return
    if k == 'cgoto':
        type_of(cx, ins.rhs)
        return
    if k == 'return':
        if ins.rhs.kind == 'none':
            return
        rt = type_of(cx, ins.rhs)
        if cx.unknown:
            return
        want = cx.fn.sig.ret
        if cx.is_cmp:
            if want.kind != 'bool':
                cx.report('cmp-result', 'comparison returned as ' + want.name)
            return
        if ins.rhs.kind == 'cast':
            return
        _check_use(cx, 'ret', want, rt, ins.rhs)
        return


def verify_function(mod: Module, fn: Function, rep: Report) -> None:
    rep.functions += 1
    if fn.opaque > 0:
        rep.functions_opaque += 1
    cx = _Ctx(mod, fn, rep)
    for ins in fn.body:
        if ins.kind == 'opaque':
            rep.stmts_opaque += 1
            continue
        if ins.kind == 'label' or ins.kind == 'goto':
            continue
        rep.stmts += 1
        _check_instr(cx, ins)


def verify_module(mod: Module, rep: Report) -> None:
    """Check every modelled statement of every function.  A statement the
    reader could not model (hand-written C in a reflection helper, `main`) is
    counted in `Report.stmts_opaque` and not checked."""
    for fn in mod.functions:
        verify_function(mod, fn, rep)


def is_gimple_illegal(code: str) -> bool:
    """Would GCC's verifier reject this in a __GIMPLE function?"""
    if code == 'cmp-result' or code == 'cast-illegal':
        return True
    i = code.find('-')
    if i < 0:
        return False
    pos = code[:i]
    cls = code[i + 1:]
    if pos == 'arg':
        return False        # GCC does not check call arguments at all
    return cls in GIMPLE_ILLEGAL
