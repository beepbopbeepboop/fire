"""MSL emitter: a second target for the same AST the C emitter walks.

Selected by ``gen.target == 'metal'``; see ``doc/GPU_OFFLOAD_PLAN.html`` for
why the transform is split across three seams and why this one is
statement-level. MSL is C-like for expressions, so much of an expression
lowers to itself -- what is NOT the same is everything in
``mojo.middle.metal_ops``: no ``double``, no libc, and address spaces that
are not pointers.

**Scope is deliberately narrow and says so.** This handles the subset a
first kernel needs -- scalars, ``device``/``threadgroup`` pointers, indexed
load/store, the usual control flow, and the intrinsics. Anything outside it
raises :class:`MetalUnsupported` rather than emitting something plausible.
That is the whole design rule here: a kernel that silently computes the
wrong thing on a GPU is far worse than one that refuses to build, because
the host's own reference will disagree and the disagreement will be
attributed to the GPU.

Emission targets ``kernel void`` entry points, which is what a compute
kernel is; MSL also has ``vertex``/``fragment``, which this does not model.
"""

from __future__ import annotations

from fire_compiler import (
    AssignStmt, AugAssignStmt, BinaryOp, BoolLiteral, BreakStmt, CallExpr,
    CompareChain, ContinueStmt, FloatLiteral, ForStmt, FunctionDef,
    IdentExpr, IfStmt, IntLiteral, MemberExpr, NoneLiteral,
    ReturnStmt, StringLiteral, SubscriptExpr, TernaryExpr, UnaryOp,
    WhileStmt, _as_str,
)
import mojo.middle.metal_ops as mops
import gimple_codegen as gimple_ctypes


class MetalUnsupported(Exception):
    """A construct with no honest MSL lowering. Carries the reason, because
    the message is the only thing the user sees when a kernel will not
    build and it has to say WHICH construct and WHY."""


_UNSUPPORTED_TYPES = frozenset({'MojoList *', 'MojoDict *', 'MojoSet *',
                                'MojoBytes *', 'MojoStr *'})


class MetalEmitter:
    """Emit MSL for one function body.

    Not a `gen` method: it needs none of the C backend's state (no
    ``var_types``, no ``_elem_types``, no block labels), because a kernel is
    straight-line-ish code over typed memory. Keeping it independent of
    `gen` is what makes it testable without a GimpleGen -- the same reason
    ``mlir.py`` and ``metal_ops.py`` are pure.
    """

    def __init__(self, name: str, params, kernel: bool = True):
        self.name = name
        self.params = list(params or [])
        self.kernel = kernel
        self.lines: list[str] = []
        self._ind = 1 if kernel else 0
        # param name -> MSL type, so a body's identifiers can be typed
        # without a symbol table walk.
        self._ptypes: dict[str, str] = {}
        # Body locals, name -> MSL type. A kernel is a small function over
        # typed memory, so a flat scope is the honest model -- there are no
        # nested closures to shadow with, and MSL's own scoping is block
        # structured anyway. Tracked because the type is LOAD-BEARING: a
        # loop index declared as `float` would silently lose precision past
        # 2^24, and a `tid` compared against an `int` bound would promote
        # the whole comparison.
        self._ltypes: dict[str, str] = {}

    # -- output helpers ----------------------------------------------------

    def _emit(self, text: str) -> None:
        self.lines.append('    ' * self._ind + text)

    def text(self) -> str:
        return '\n'.join(self.lines)

    def _type_of(self, node) -> str:
        """Infer an expression's MSL type.

        Conservative and structural. The cases that matter are the ones
        where guessing wrong is silent: an integer-typed expression must
        not become a ``float`` (2^24 precision cliff on a loop index), and
        a division must not become an ``int`` (truncation). Anything not
        recognised is ``float``, which is the right default for a numeric
        kernel and is recorded here rather than left implicit.
        """
        if isinstance(node, IntLiteral):
            return 'int'
        if isinstance(node, FloatLiteral):
            return 'float'
        if isinstance(node, BoolLiteral):
            return 'bool'
        if isinstance(node, UnaryOp):
            if _as_str(node.op) == 'not':
                return 'bool'
            return self._type_of(node.operand)
        if isinstance(node, BinaryOp):
            op = _as_str(node.op)
            if op in mops.DEVICE_CMPOPS:
                return 'bool'
            # Integer-only operators keep integer-ness; `/` is the one
            # arithmetic op Python makes a float.
            if op in ('%', '<<', '>>', '&', '|', '^'):
                return 'int'
            return self._type_of(node.left) if mops.is_float_type(self._type_of(node.left)) \
                else self._type_of(node.right)
        if isinstance(node, CompareChain):
            return 'bool'
        if isinstance(node, TernaryExpr):
            return self._type_of(node.then_expr)
        if isinstance(node, SubscriptExpr):
            # A subscript's type is the pointed-to type of its base. Asking
            # the param table rather than guessing is what keeps
            # `out[tid] = a[tid] + b[tid]` from silently storing an int
            # into a float buffer (or the reverse).
            base = node.obj
            if isinstance(base, IdentExpr):
                pt = self._ptypes.get(_as_str(base.name))
                if pt and pt.endswith('*'):
                    elem = pt[:-1].strip().split()[-1]
                    em = mops.msl_type('int64_t' if elem in ('int', 'uint') else elem)
                    if em in ('float', 'half'):
                        return em
                    if em:
                        return em
            return 'float'
        if isinstance(node, CallExpr) and isinstance(node.func, SubscriptExpr):
            # `llvm_intrinsic[name, ReturnType, ...]()`. The stdlib declares
            # the return type as the second template argument, so read it
            # rather than defaulting: the emitter's fallback is `float`, and
            # an `Int32` index intrinsic silently declared `float` is a
            # wrong answer that only shows on large values. See
            # metal_ops.LLVM_AIR_RET_TYPES.
            el = list(getattr(node.func.index, 'elements', None) or ())
            if len(el) >= 2 and isinstance(el[1], IdentExpr):
                rt = mops.llvm_air_ret_type(_as_str(el[1].name))
                if rt is not None:
                    return rt
            return 'float'
        if isinstance(node, CallExpr) and isinstance(node.func, IdentExpr):
            nm = _as_str(node.func.name)
            if nm in ('abs', 'min', 'max', 'clamp', 'sign'):
                return self._type_of(node.args[0]) if node.args else 'float'
            if mops.intrinsic(nm) is not None:
                return 'float'
        if isinstance(node, IdentExpr):
            nm = _as_str(node.name)
            # A generated index parameter is a `uint`, which is an INTEGER;
            # defaulting it to float would put the 2^24 precision cliff on
            # every global index.
            if nm in self._ptypes and self._ptypes[nm] in ('uint', 'int', 'long'):
                return 'int'
            return self._ltypes.get(nm, 'float')
        if isinstance(node, MemberExpr):
            # `global_idx.x` and friends: an index, so an integer. Asking
            # here is what stops `tid = global_idx.x` declaring `float tid`
            # and then indexing a buffer with it.
            if mops.index_var(_as_str(node.obj.name)
                              if isinstance(node.obj, IdentExpr) else '') is not None:
                return 'int'
        return 'float'

    def _bind(self, name: str, msl_type: str) -> None:
        self._ltypes[name] = msl_type

    # -- entry point -------------------------------------------------------

    #: MSL preamble every generated kernel needs. `metal_stdlib` is what
    #: brings in `metal::sqrt` and friends, and `using namespace metal` is
    #: what lets the intrinsic table emit a bare `sqrt` -- the working
    #: hand-written kernels in test_llm/kernels.metal open with exactly
    #: these two lines.
    PREAMBLE = ('#include <metal_stdlib>\n'
                'using namespace metal;\n')

    def emit_function(self, fdef: FunctionDef) -> str:
        """The whole MSL function, signature included.

        Locals are declared in one block at the top of the body, which is
        what the rest of this compiler's host output does too and keeps the
        emission a single pass: MSL is C-like and does not need
        interleaved declarations, so there is no reason to thread a scope
        stack through the statement walk.
        """
        sig = self._signature()
        body: list[str] = []
        saved, self.lines = self.lines, body
        self._ind = 1
        try:
            for st in (fdef.body or []):
                self._stmt(st)
        finally:
            self.lines = saved
        self.lines = []
        self._ind = 0
        for pline in self.PREAMBLE.rstrip('\n').split('\n'):
            self._emit(pline)
        self._emit('')
        self._emit(sig)
        self._emit('{')
        self._ind = 1
        for name, t in self._ltypes.items():
            self._emit(f'{t} {name};')
        self._ind = 1
        self.lines.extend(body)
        self._ind = 0
        self._emit('}')
        return self.text()

    def _signature(self) -> str:
        parts = []
        for pname, _ptype in self.params:
            pname = _as_str(pname)
            # Kernel arguments are scalars or device/constant pointers by
            # construction. An unannotated parameter is `float`: MSL has no
            # double, and a kernel that silently narrowed an int index to a
            # float would be a nightmare to find. An explicit annotation is
            # honoured, and anything MSL cannot express is REFUSED.
            msl_t = self._param_type(pname, _ptype)
            self._ptypes[pname] = msl_t
            if msl_t.endswith('*'):
                # A buffer argument: the address space is part of the type
                # and the index binds it.
                _bidx = len(parts)
                parts.append(f'{msl_t} {pname} [[buffer({_bidx})]]')
            else:
                # A SCALAR kernel argument is passed BY REFERENCE into the
                # constant address space: `constant int &n`. This is not a
                # style choice -- MSL 3.2 rejects the by-value form
                # outright ("invalid type 'int' for input declaration in a
                # kernel function"), and accepts only the reference form.
                # Probed against the real compiler rather than assumed.
                parts.append(f'constant {msl_t} &{pname}')
        # The index parameters, unconditionally. A kernel's parallelism IS
        # its index space, so these are not optional decoration -- and
        # emitting all five always keeps the signature a function of the
        # KERNEL rather than of the body's current text, so editing a body
        # cannot silently change the ABI the host marshals against.
        for _pname, _decl in mops.INDEX_PARAMS:
            self._ptypes[_pname] = 'uint'
            parts.append(_decl)
        kw = 'kernel ' if self.kernel else ''
        return f'{kw}void {self.name}({", ".join(parts)})'

    def _param_type(self, pname: str, ptype) -> str:
        """MSL type for a kernel parameter.

        Resolved through ``_mojo_type`` -- the SAME resolver the C backend
        uses -- rather than through a second, Metal-only annotation
        grammar. That is deliberate: if the two resolved annotations
        independently they would agree today and drift the first time
        either added a type, and the divergence would show up as a kernel
        silently reading the wrong bytes rather than as a build error.
        """
        if ptype is None:
            # An unannotated kernel parameter is a float. There is no way
            # to know it was meant to be a pointer, and defaulting to a
            # pointer would be far worse: a scalar where a buffer was meant
            # is a wrong answer, and a buffer where a scalar was meant is a
            # crash inside the driver.
            return 'float'
        ann = _as_str(ptype)
        c_type = gimple_ctypes._mojo_type(ann)
        # Checked on the RESOLVED type, not the annotation: `List[Float32]`
        # and `MojoList *` are the same thing to this backend, and only one
        # of them is what a user writes. Testing the annotation would let
        # the informative message through for the spelling people use and
        # give the vague one for the other.
        if c_type in _UNSUPPORTED_TYPES or ann in _UNSUPPORTED_TYPES:
            raise MetalUnsupported(
                f'kernel {self.name}: parameter {pname!r} is {ann!r} '
                f'(C type {c_type!r}), which cannot be passed to a GPU -- it '
                'is a heap object with a host header. Kernel arguments must '
                'be scalars or contiguous device/constant pointers.')
        msl_t = mops.kernel_arg_type(c_type)
        if msl_t is None:
            raise MetalUnsupported(
                f'kernel {self.name}: parameter {pname!r} is {ann!r}, which '
                f'resolves to the C type {c_type!r} and has no MSL equivalent.')
        if msl_t.endswith('*'):
            # A pointer is NOT just a pointer on a device: the address
            # space is part of the type and conflating them is silent. The
            # host collapses every space to `void *` (mlir.py:71-77); this
            # is where it is undone, and the default space is `device`
            # because that is what a kernel argument is.
            return f'{mops.address_space(None)} {msl_t}'
        return msl_t

    # -- statements --------------------------------------------------------

    def _stmt(self, st) -> None:
        if isinstance(st, ReturnStmt):
            # A compute kernel's return type is void; a `return` with a
            # value in one is a real error, not something to drop.
            if getattr(st, 'value', None) is not None:
                raise MetalUnsupported(
                    f'kernel {self.name}: a compute kernel returns void, but '
                    'this return has a value.')
            self._emit('return;')
        elif isinstance(st, AssignStmt):
            tgt, val = st.target, st.value
            if isinstance(tgt, SubscriptExpr):
                obj = self._expr(tgt.obj)
                idx = self._expr(tgt.index)
                self._emit(f'{obj}[{idx}] = {self._expr(val)};')
            else:
                lhs = self._lvalue(tgt)
                if isinstance(tgt, IdentExpr):
                    self._bind(lhs, self._type_of(val))
                self._emit(f'{lhs} = {self._expr(val)};')
        elif isinstance(st, AugAssignStmt):
            cur = self._expr(st.target)
            op = _as_str(st.op)
            if op not in mops.DEVICE_BINOPS:
                raise MetalUnsupported(
                    f'kernel {self.name}: augmented {op!r} has no MSL form.')
            self._emit(f'{self._lvalue(st.target)} {op}= {self._expr(st.value)};')
        elif isinstance(st, IfStmt):
            # IfStmt's fields are `then_body` / `elifs` / `else_body` -- NOT
            # `body` (WhileStmt and ForStmt do use `body`). Getting this
            # wrong is an AttributeError rather than a silent miscompile,
            # which is the good kind of wrong.
            self._emit(f'if ({self._expr(st.condition)}) {{')
            self._ind += 1
            for s in (getattr(st, 'then_body', None) or []):
                self._stmt(s)
            self._ind -= 1
            for _elif in (getattr(st, 'elifs', None) or []):
                self._emit(f'}} else if ({self._expr(_elif.condition)}) {{')
                self._ind += 1
                for s in (getattr(_elif, 'then_body', None) or []):
                    self._stmt(s)
                self._ind -= 1
            if getattr(st, 'else_body', None):
                self._emit('} else {')
                self._ind += 1
                for s in st.else_body:
                    self._stmt(s)
                self._ind -= 1
            self._emit('}')
        elif isinstance(st, WhileStmt):
            self._emit(f'while ({self._expr(st.condition)}) {{')
            self._ind += 1
            for s in (st.body or []):
                self._stmt(s)
            self._ind -= 1
            self._emit('}')
        elif isinstance(st, ForStmt):
            self._for(st)
        elif isinstance(st, ContinueStmt):
            self._emit('continue;')
        elif isinstance(st, BreakStmt):
            self._emit('break;')
        else:
            raise MetalUnsupported(
                f'kernel {self.name}: statement {type(st).__name__} has no '
                'MSL lowering yet.')

    def _for(self, st: ForStmt) -> None:
        """`for i in range(n)` -- the only loop form a kernel gets.

        A kernel's parallelism IS its index space, so a general iterable
        loop has no meaning here: it would be sequential work on a
        thousands-of-threads device. Rather than emit something that looks
        right, this refuses a non-`range` iterable and says so.
        """
        it = st.iterable
        if not (isinstance(it, CallExpr) and isinstance(it.func, IdentExpr)
                and _as_str(it.func.name) == 'range'):
            raise MetalUnsupported(
                f'kernel {self.name}: only `for i in range(...)` lowers on a '
                f'device, not {type(it).__name__}. On a GPU the index space '
                'IS the parallelism, so a general iterable loop would be '
                'sequential work run on thousands of threads.')
        if len(it.args) == 1:
            start, stop, step = '0', self._expr(it.args[0]), '1'
        elif len(it.args) == 2:
            start, stop, step = self._expr(it.args[0]), self._expr(it.args[1]), '1'
        elif len(it.args) == 3:
            start, stop, step = (self._expr(a) for a in it.args)
        else:
            raise MetalUnsupported(f'kernel {self.name}: range() with {len(it.args)} arguments.')
        var = self._lvalue(st.target)
        # A loop index is an integer, always -- it is the induction
        # variable, and letting it infer `float` from the bound would put
        # the 2^24 precision cliff on every trip count.
        if isinstance(st.target, (IdentExpr, str)):
            self._bind(var, 'int')
        self._emit(f'for ({var} = {start}; {var} < {stop}; {var} += {step}) {{')
        self._ind += 1
        for s in (st.body or []):
            self._stmt(s)
        self._ind -= 1
        self._emit('}')

    # -- expressions -------------------------------------------------------

    def _lvalue(self, node) -> str:
        # ForStmt.target is a bare NAME STRING, not an IdentExpr (unlike
        # AssignStmt.target, which is a node) -- so the two spellings of
        # "an assignable name" both have to be accepted here.
        if isinstance(node, str):
            return node
        if isinstance(node, IdentExpr):
            return _as_str(node.name)
        if isinstance(node, MemberExpr):
            return f'{self._expr(node.obj)}.{_as_str(node.member)}'
        if isinstance(node, SubscriptExpr):
            return f'{self._expr(node.obj)}[{self._expr(node.index)}]'
        raise MetalUnsupported(f'kernel {self.name}: {type(node).__name__} is not assignable.')

    def _expr(self, node) -> str:
        if isinstance(node, IntLiteral):
            return f'{int(node.value)}'
        if isinstance(node, FloatLiteral):
            return _msl_float_literal(node.value)
        if isinstance(node, BoolLiteral):
            return 'true' if node.value else 'false'
        if isinstance(node, NoneLiteral):
            return 'nullptr'
        if isinstance(node, StringLiteral):
            raise MetalUnsupported('kernel string literals are not modelled.')
        if isinstance(node, IdentExpr):
            return self._ident(_as_str(node.name))
        if isinstance(node, MemberExpr):
            return self._member(node)
        if isinstance(node, SubscriptExpr):
            return f'{self._expr(node.obj)}[{self._expr(node.index)}]'
        if isinstance(node, UnaryOp):
            return self._unary(node)
        if isinstance(node, BinaryOp):
            return self._binary(node)
        if isinstance(node, CompareChain):
            return self._compare(node)
        if isinstance(node, TernaryExpr):
            return (f'({self._expr(node.condition)} ? {self._expr(node.then_expr)}'
                    f' : {self._expr(node.else_expr)})')
        if isinstance(node, CallExpr):
            return self._call(node)
        raise MetalUnsupported(
            f'kernel {self.name}: expression {type(node).__name__} has no MSL lowering yet.')

    def _ident(self, name: str) -> str:
        if name in self._ptypes or name in self._ltypes:
            return name
        # An undeclared bare name is a global. On a device there are no
        # globals to read -- a `constant` address space is a kernel
        # ARGUMENT, not a module variable -- so this is refused rather than
        # silently emitted as an undefined identifier.
        raise MetalUnsupported(
            f'kernel {self.name}: {name!r} is not a parameter. A device '
            'function has no globals: pass it in as an argument, or declare '
            'it threadgroup-local.')

    def _member(self, node: MemberExpr) -> str:
        """`x.y` -- a thread index, an intrinsic call, or a real member."""
        obj = node.obj
        member = _as_str(node.member)
        if isinstance(obj, IdentExpr):
            base = _as_str(obj.name)
            # `global_idx.x` and friends: the stdlib's index VARIABLES,
            # rewritten onto MSL. This is the speciality-code transform --
            # see metal_ops.INDEX_VARS. Guarded on the base NOT being a
            # parameter, so a user variable called `global_idx` still
            # means their variable.
            if base not in self._ptypes:
                idx = mops.index_var(base)
                if idx is not None:
                    # Only x/y/z are addressable; the stdlib exposes those
                    # three components, and anything else is a mistake worth
                    # naming rather than silently taking the x of.
                    if member not in ('x', 'y', 'z'):
                        raise MetalUnsupported(
                            f'kernel {self.name}: {base}.{member} -- a GPU '
                            'index has three components, x, y and z.')
                    return idx
                ti = mops.thread_index_fn(member)
                if ti is not None:
                    return ti
            flag = mops.mem_flag(member)
            if flag is not None and base == 'mem_flags':
                return flag
        if isinstance(obj, CallExpr):
            # `thread_idx()` / `global_idx()` -- the callable form.
            inner = self._expr(obj)
            ti = mops.thread_index_fn(member)
            if ti is not None:
                return ti
            if inner.endswith('()'):
                return f'{inner[:-2]}'
        return f'{self._expr(obj)}.{member}'

    def _unary(self, node: UnaryOp) -> str:
        op = _as_str(node.op)
        operand = self._expr(node.operand)
        if op == '-':
            return f'-({operand})'
        if op == '+':
            return operand
        if op == 'not':
            return f'!({operand})'
        if op == '~':
            return f'~({operand})'
        raise MetalUnsupported(f'kernel {self.name}: unary {op!r} has no MSL form.')

    def _binary(self, node: BinaryOp) -> str:
        op = _as_str(node.op)
        if op in mops.DEVICE_CMPOPS:
            return f'({self._expr(node.left)} {op} {self._expr(node.right)})'
        if op not in mops.DEVICE_BINOPS:
            raise MetalUnsupported(f'kernel {self.name}: binary {op!r} has no MSL form.')
        return f'({self._expr(node.left)} {op} {self._expr(node.right)})'

    def _compare(self, node: CompareChain) -> str:
        """`a < b < c` is CHAINED in Python, which MSL/C do not have.

        Semantically `a < b < c` is `(a < b) and (b < c)`, and that is
        emitted as such rather than as the nested-and someone would guess.
        """
        ops = [_as_str(o) for o in (node.operands or [])]
        cmp_ops = [o for o in node.ops] if hasattr(node, 'ops') else []
        terms = []
        for i, o in enumerate(cmp_ops):
            o = _as_str(o)
            if o not in mops.DEVICE_CMPOPS:
                raise MetalUnsupported(f'kernel {self.name}: comparison {o!r} has no MSL form.')
            terms.append(f'({self._expr(ops[i])} {o} {self._expr(ops[i + 1])})')
        if not terms:
            raise MetalUnsupported(f'kernel {self.name}: empty comparison chain.')
        return ' && '.join(terms) if len(terms) > 1 else terms[0]

    def _llvm_intrinsic_call(self, node: CallExpr) -> str | None:
        """`llvm_intrinsic["llvm.air...", Type, ...](args)` on a device.

        The stdlib reaches the GPU ONLY through this shape
        (`std/sys/intrinsics.mojo`, called from the `is_apple_gpu()` branches
        of `std/gpu/primitives/id.mojo` and friends), so without it no real
        stdlib GPU code can lower at all -- increment 2 of
        `doc/GPU_OFFLOAD_PLAN.html` is exactly this.

        The callee is a `SubscriptExpr` whose index is a TUPLE of the
        template arguments: the intrinsic NAME first (a string literal), then
        the return type, then any argument types, then the flags. Only the
        name matters here; the type arguments are compile-time and have no
        MSL spelling, and the runtime arguments are the call's own `args`.

        Returns the MSL expression, or None if this is not an
        `llvm_intrinsic` subscript call (so the caller reports it normally).
        A recognised AIR name with no MSL form RAISES, naming the
        intrinsic: an unimplemented GPU intrinsic must not quietly become
        something that computes a plausible wrong answer.
        """
        sub = node.func
        if not isinstance(sub, SubscriptExpr):
            return None
        base = sub.obj
        if not isinstance(base, IdentExpr) or _as_str(base.name) != 'llvm_intrinsic':
            return None
        tup = sub.index
        elements = list(getattr(tup, 'elements', None) or ())
        if not elements:
            return None
        first = elements[0]
        if not isinstance(first, gimple_ctypes.StringLiteral):
            # A name built at runtime (`"llvm.air..." + dim` in the stdlib,
            # where `dim` is a `StaticString` parameter) does not reach here
            # as a literal. Refuse with that said plainly rather than
            # treating a non-literal as some default name.
            raise MetalUnsupported(
                f'kernel {self.name}: the llvm_intrinsic name is not a string '
                'literal, so the AIR intrinsic it names cannot be resolved. '
                'A device kernel must name its intrinsic statically.')
        name = _as_str(first.value)
        args = [self._expr(a) for a in (node.args or [])]
        msl = mops.llvm_air(name)
        if msl is None:
            if mops.llvm_air_is_intrinsic(name):
                raise MetalUnsupported(
                    f'kernel {self.name}: {name!r} has no MSL lowering on this '
                    'target. See metal_ops.LLVM_AIR_FNS for what is '
                    'implemented, and the omission note there for why the '
                    'simdgroup-matrix and shuffle forms are not in it.')
            # A non-AIR intrinsic (llvm.nvvm.*, rocdl.*, llvm.masked.*).
            # Naming it is the useful part: it says the program reached for
            # a vendor intrinsic this target does not have.
            raise MetalUnsupported(
                f'kernel {self.name}: intrinsic {name!r} has no MSL lowering. '
                'Only llvm.air.* (Apple) intrinsics are implemented; this '
                'name is not one of them.')
        # An index family is a bare parameter, not a call.
        if msl.startswith('__') and not args:
            return msl
        return f'{msl}({", ".join(args)})' if args else msl

    def _call(self, node: CallExpr) -> str:
        air = self._llvm_intrinsic_call(node)
        if air is not None:
            return air
        if not isinstance(node.func, IdentExpr):
            raise MetalUnsupported(
                f'kernel {self.name}: only a bare function call lowers on a '
                f'device, not {type(node.func).__name__}.')
        name = _as_str(node.func.name)
        args = [self._expr(a) for a in (node.args or [])]
        if name == 'range':
            raise MetalUnsupported(
                f'kernel {self.name}: range() is only a loop form, not a value.')
        sp = mops.intrinsic(name)
        if sp is not None:
            return f'{sp}({", ".join(args)})'
        if name in self._ptypes:
            raise MetalUnsupported(
                f'kernel {self.name}: {name!r} is a kernel parameter, not a '
                'callable -- a device function pointer cannot be called here.')
        raise MetalUnsupported(
            f'kernel {self.name}: no MSL lowering for {name}(). On a device '
            'only metal:: intrinsics and the builtins are callable.')


def _msl_float_literal(value) -> str:
    """A float literal MSL will accept.

    MSL wants a digit either side of the point (`1.0`, not `.5` or `1.`),
    and has no `inf`/`nan` literals, so those are refused rather than
    turned into something that means a different number.
    """
    v = float(value)
    if v != v:
        raise MetalUnsupported('kernel float literals: NaN has no MSL spelling.')
    if v in (float('inf'), float('-inf')):
        raise MetalUnsupported('kernel float literals: infinity has no MSL spelling.')
    s = repr(v)
    if s.endswith('.0') is False and '.' not in s and 'e' not in s:
        s += '.0'
    if s.startswith('.'):
        s = '0' + s
    if s.startswith('-.'):
        s = '-0' + s[1:]
    return s


def emit_kernel(fdef: FunctionDef, kernel: bool = True) -> str:
    """MSL text for one device function. The whole of Seam 2's public API."""
    em = MetalEmitter(_as_str(fdef.name), fdef.params, kernel=kernel)
    return em.emit_function(fdef)
