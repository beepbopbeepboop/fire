"""Recognition of a GPU-offloadable loop nest, and the refutation of one.

Increment 3 of ``doc/GPU_OFFLOAD_PLAN.html``: recognise a parallel loop nest
over numeric containers, synthesise a kernel, replace the host loop with a
dispatch. This module is the recogniser. It decides whether a ``for`` loop
can be moved to the device WITHOUT the programmer asking, which is the whole
of increment 3 and also all of its risk.

The shape recognised, and nothing wider::

    for i in range(n):
        out[i] = <expr over x[i], y[i], scalars>

Every one of those conditions is load-bearing, and each was chosen by asking
what a WRONG answer looks like, not by what is convenient to accept:

``range(n)`` exactly
    A trip count is what the grid is sized from. Any other iterable needs a
    length the compiler would have to invent, and inventing one is how a
    kernel reads past the end.

a single ``AssignStmt``, to a subscript
    A loop body with control flow in it (``if``/``break``/``continue``) is not
    a parallel map, and a body that writes a scalar is a REDUCTION, which
    needs cross-thread accumulation this does not implement. Refusing a
    reduction is not a missing feature: accepting one and summing per-thread
    would give a plausible wrong answer, which is the worst outcome available.

every subscript indexed by the loop variable, or not indexed at all
    ``out[i]`` is a parallel write. ``out[i * 2]`` is a strided write: two
    threads may target one element, so it is a race whose result depends on
    scheduling. A computed index has the same problem for a reason that is
    harder to see.

no element written is also read through the same subscript
    ``x[i] = x[i] + 1.0; out[i] = x[i]`` is fine in a parallel map (each
    thread owns element ``i``) but is rejected here anyway, because the
    recogniser does not track element types, and a container that aliases
    another one across threads is indistinguishable from one that does not at
    this level. Refusing is the cheap direction to be wrong in.

containers are whole-list, not slices
    The list is passed whole and the kernel indexes it, which is why
    increment 3 needed no new ABI work: for the 8-byte element types a
    ``MojoList``'s storage is already contiguous (see the increment-3
    correction in the plan).

WHAT THIS DELIBERATELY DOES NOT DO:

  - No recognition of loop nests deeper than one level. A 2-D nest is a
    different problem (thread-block mapping) and guessing at it is how
    ``bad_nested`` below would become a silent wrong answer.
  - No recognition through a comprehension or a helper call. Increment 3's
    scope is the loop nest.
  - No recognition of reductions, scans, or any loop with a carried
    dependency.
  - No cost model. This asks "is this CORRECT to move", never "is this
    FASTER to move". A four-element loop here is a pessimisation and still
    qualifies; the trip-count threshold belongs to the caller that has the
    machine's dispatch overhead measured, not to a predicate.

Every refusal returns a ``reason`` naming the specific violated condition, so
a user whose loop was not offloaded can find out why instead of guessing. That
matters more than usual here, because the failure mode of getting this wrong
is a kernel that computes a wrong answer at exit 0.
"""

from __future__ import annotations

import fire_compiler as gctypes

#: Statements that make a loop body something other than a parallel map.
#: ``IfStmt`` is here because a conditional STORE is a compaction, which needs
#: a prefix sum this does not implement; ``break``/``continue`` are control
#: flow out of a parallel region.
_NON_MAP_STATEMENTS = ('IfStmt', 'ForStmt', 'WhileStmt', 'BreakStmt',
                       'ContinueStmt', 'ReturnStmt')

#: Expression nodes that are safe in a parallel body: arithmetic and
#: comparison over the loop variable's element, or a scalar. Anything that
#: could call back into the host, allocate, or observe another thread is
#: absent on purpose, so an unrecognised node refuses rather than passing.
#: How a statement is NAMED in a refusal message. Read off the node class
#: rather than derived from it: `AssignStmt` -> "assignment", which is what a
#: user would call it. Deriving it (`name[:-4].lower()`) produced "a assign".
_STMT_NAMES = {
    'AssignStmt': 'an assignment',
    'ExprStmt': 'an expression statement',
    'AugAssignStmt': 'an augmented assignment',
    'IfStmt': 'a conditional',
    'ReturnStmt': 'a return',
    'ForStmt': 'a loop',
    'WhileStmt': 'a while loop',
    'VarDecl': 'a declaration',
}

#: Decorators that already request the device. A function carrying one is
#: left alone: it is already a kernel, so there is nothing to infer and
#: re-synthesising it would duplicate it under a second name.
_EXPLICIT = frozenset({'gpu', 'kernel'})

_ALLOWED_EXPR_NODES = (
    'IdentExpr', 'IntLiteral', 'FloatLiteral', 'BoolLiteral', 'StringLiteral',
    'BinaryOp', 'UnaryOp', 'SubscriptExpr', 'CompareChain', 'ParenExpr',
)


class Offloadable:
    """A loop nest that may be moved to the device, and what it needs.

    Attributes:
        param: the name of the ``range`` bound parameter, which is the trip
            count and therefore the grid size.
        index: the loop variable's name.
        writes: the single container written, in subscript order.
        reads: every container read, deduplicated, excluding `writes` when a
            name appears in both (that is the aliasing case, which
            `recognise` refuses, so in practice these are disjoint).
        len_param: the length parameter to hand the kernel, taken from the
            written container's own parameter when there is one.
    """

    __slots__ = ('param', 'index', 'writes', 'reads', 'len_param', 'scalars')

    def __init__(self, param, index, writes, reads, len_param, scalars=()):
        self.param = param
        self.index = index
        self.writes = writes
        self.reads = reads
        self.len_param = len_param
        #: Bare identifiers the body reads besides the loop variable: a
        #: scalar coefficient in `a * x[i]`, say. These become kernel
        #: parameters too -- omitting one emits it as an undeclared global,
        #: which is the build error that found this.
        self.scalars = sorted(scalars)

    def __repr__(self):
        return (f'Offloadable(index={self.index!r}, param={self.param!r}, '
                f'writes={self.writes!r}, reads={self.reads!r})')


def _as_str(value) -> str:
    return value if isinstance(value, str) else str(value)


def _is_name(node, name: str) -> bool:
    return isinstance(node, gctypes.IdentExpr) and _as_str(node.name) == name


def _subscript_parts(node):
    """(container-name, index-node) for `x[e]`, or None."""
    if not isinstance(node, gctypes.SubscriptExpr):
        return None
    if not isinstance(node.obj, gctypes.IdentExpr):
        return None
    return _as_str(node.obj.name), node.index


def _trip_count_param(iterable):
    """The parameter naming a `range(n)` bound, or None."""
    if not isinstance(iterable, gctypes.CallExpr):
        return None
    if not _is_name(iterable.func, 'range'):
        return None
    args = list(iterable.args or ())
    if len(args) != 1:
        # `range(a, b)` and `range(a, b, step)` are affine and could be
        # supported, but each needs a decision about the stride and the
        # bounds, and a wrong one is a wrong grid. Not yet.
        return None
    bound = args[0]
    if not isinstance(bound, gctypes.IdentExpr):
        return None
    return _as_str(bound.name)


def _check_expr(node, index_name: str, reads: set, why: list,
                scalars: set | None = None) -> bool:
    """Walk a body expression. Records container reads. False on any node
    outside the allowed set, or any subscript not indexed by the loop var."""
    if node is None:
        return True
    name = type(node).__name__
    if name not in _ALLOWED_EXPR_NODES:
        why.append(f'{name} in the body expression')
        return False
    if name in ('IntLiteral', 'FloatLiteral', 'BoolLiteral', 'StringLiteral'):
        return True
    if name == 'IdentExpr':
        # A bare identifier is a scalar (the loop variable itself, or a
        # parameter). A container would have been a SubscriptExpr, so
        # anything reaching here that is not the loop variable is a scalar
        # the kernel signature has to carry -- recording it is what stops
        # `a * x[i]` from emitting `a` as an undeclared global.
        if scalars is not None and _as_str(node.name) != index_name:
            scalars.add(_as_str(node.name))
        return True
    if name == 'SubscriptExpr':
        parts = _subscript_parts(node)
        if parts is None:
            why.append('a subscript of something other than a plain name')
            return False
        container, idx = parts
        if not _is_name(idx, index_name):
            why.append(f'read of {container!r} at an index that is not the '
                       f'loop variable')
            return False
        reads.add(container)
        return True
    if name == 'BinaryOp':
        return (_check_expr(getattr(node, 'left', None), index_name, reads, why, scalars)
                and _check_expr(getattr(node, 'right', None), index_name, reads, why, scalars))
    if name == 'UnaryOp':
        return _check_expr(getattr(node, 'operand', None), index_name, reads, why, scalars)
    if name == 'CompareChain':
        return all(_check_expr(o, index_name, reads, why, scalars)
                   for o in (getattr(node, 'operands', None) or ()))
    if name == 'ParenExpr':
        return _check_expr(getattr(node, 'value', None), index_name, reads, why, scalars)
    return True


#: Why the last `recognise` call declined, for `explain` to report. A
#: module-level dict rather than a return value because `recognise`'s contract
#: is None-or-Offloadable and callers should not have to unpack a reason
#: tuple to do the common thing. Not reentrant; single-threaded compile.
_OFFLOAD_STATE: dict = {}


def recognise(fdef) -> 'Offloadable | None':
    """The single recognised loop in `fdef`'s body, or None.

    `fdef` is a free `FunctionDef` whose ENTIRE body is one offloadable
    `for` loop plus an optional `return`. A function that also does other
    work is not offloaded even if it contains an offloadable loop: hoisting
    one loop out of a function that continues on the host is a
    control-flow rewrite, and this is a loop-to-kernel rewrite. The caller
    gets None and leaves the function alone, which is always correct.
    """
    body = list(getattr(fdef, 'body', None) or ())
    loops = [s for s in body if isinstance(s, gctypes.ForStmt)]
    if len(loops) != 1:
        return None
    loop = loops[0]
    # The "everything except the loop" check below needs a real name for the
    # offending statement in `explain`, and the printed-source form is what
    # a user recognises. Recorded here rather than in `explain` so both entry
    # points agree on which statement it was.
    for st in body:
        if st is not loop and not isinstance(st, gctypes.ReturnStmt):
            _OFFLOAD_STATE['extra_stmt'] = _STMT_NAMES.get(
                type(st).__name__, 'statement')
            break
    else:
        _OFFLOAD_STATE.pop('extra_stmt', None)

    # Only a RETURN may accompany the loop. Anything else is host work that
    # would have to be sequenced around a dispatch, which is a control-flow
    # rewrite this does not attempt. A return of the written container is the
    # shape the stdlib's own kernels use, so it is allowed.
    for st in body:
        if st is loop:
            continue
        if isinstance(st, gctypes.ReturnStmt):
            continue
        return None

    param = _trip_count_param(loop.iterable)
    if param is None:
        return None
    # `ForStmt.target` is a plain STRING here, not an IdentExpr -- measured,
    # not assumed. Both spellings are accepted so this keeps working if the
    # parser ever hands back a node instead.
    if isinstance(loop.target, str):
        index = loop.target
    elif isinstance(loop.target, gctypes.IdentExpr):
        index = _as_str(loop.target.name)
    else:
        return None

    inner = list(loop.body or ())
    if len(inner) != 1:
        # Zero statements is an empty loop (a dispatch that writes nothing);
        # more than one is not a map. A conditional store is the interesting
        # case and it lands here.
        return None
    stmt = inner[0]
    if not isinstance(stmt, gctypes.AssignStmt):
        return None
    target = stmt.target
    if not isinstance(target, gctypes.SubscriptExpr):
        # `t = t + x[i]`: the classic reduction. Refused by not being a
        # subscript write; see the module docstring for why that is the
        # right direction to be wrong in.
        return None
    parts = _subscript_parts(target)
    if parts is None:
        return None
    written, target_index = parts
    if not _is_name(target_index, index):
        return None

    why: list = []
    reads: set = set()
    scalars: set = set()
    if not _check_expr(stmt.value, index, reads, why, scalars):
        _OFFLOAD_STATE['why'] = why[0] if why else 'body expression'
        return None
    _OFFLOAD_STATE.pop('why', None)
    # The loop variable is not a parameter -- the kernel supplies it from the
    # grid index -- so it must not be collected as a scalar.
    scalars.discard(index)
    # A container that is both read and written is the aliasing case.
    if written in reads:
        return None

    params = []
    for p in (getattr(fdef, 'params', None) or ()):
        # A param is a (name, annotation) TUPLE here, not a node.
        params.append(_as_str(p[0]) if isinstance(p, tuple) else _as_str(p))
    len_param = written if written in params else None
    return Offloadable(param=param, index=index, writes=written,
                       reads=sorted(reads), len_param=len_param,
                       scalars=sorted(scalars))


def explain(fdef) -> str:
    """Why `fdef` was not offloaded, in one sentence. For tests and for a
    user who wants to know why their loop stayed on the host."""
    if recognise(fdef) is not None:
        return 'offloadable'
    body = list(getattr(fdef, 'body', None) or ())
    loops = [s for s in body if isinstance(s, gctypes.ForStmt)]
    if not loops:
        return 'no for loop'
    if len(loops) > 1:
        return f'{len(loops)} loops; only a single loop nest is recognised'
    loop = loops[0]
    if _trip_count_param(loop.iterable) is None:
        return 'the loop is not `for i in range(<one parameter>)`'
    inner = list(loop.body or ())
    if not inner:
        return 'empty loop body'
    if len(inner) > 1:
        names = ', '.join(type(s).__name__ for s in inner)
        return f'body is not a single assignment ({names})'
    stmt = inner[0]
    if not isinstance(stmt, gctypes.AssignStmt):
        return f'body statement is {type(stmt).__name__}, not an assignment'
    if not isinstance(stmt.target, gctypes.SubscriptExpr):
        return ('assignment to a scalar: this is a reduction, which needs '
                'cross-thread accumulation that is not implemented')
    parts = _subscript_parts(stmt.target)
    target_name = (loop.target if isinstance(loop.target, str)
                   else _as_str(getattr(loop.target, 'name', '')))
    if parts is None or not _is_name(parts[1], target_name):
        return 'the written subscript is not indexed by the loop variable'
    why: list = []
    reads: set = set()
    if not _check_expr(stmt.value, target_name, reads, why):
        return f'body expression: {why[0]}' if why else 'body expression'
    if parts[0] in reads:
        return (f'{parts[0]!r} is both read and written in the loop, so the '
                'threads may alias it')
    if 'extra_stmt' in _OFFLOAD_STATE:
        return (f'the function also contains '
                f'{_OFFLOAD_STATE["extra_stmt"]}, which is host work that '
                'cannot be sequenced around a dispatch')
    if 'why' in _OFFLOAD_STATE:
        return f'body expression: {_OFFLOAD_STATE["why"]}'
    return 'not offloadable'


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

#: The name prefix for a synthesised device function. Namespaced so it can
#: never collide with a function the programmer wrote, which matters because
#: both end up in the same module: a user function called
#: `_mg_saxpy_kernel` would be silently replaced.
SYNTH_PREFIX = '_mg_offload_'

#: Container spellings the synthesised kernel signature accepts, mapped to the
#: element type. The stdlib writes containers as `List[Float32]` /
#: `UnsafePointer[Float32, MutAnyOrigin]`, so the ELEMENT is what a device
#: buffer is typed by -- the container spelling itself does not survive to
#: the device, where every buffer is a raw pointer.
_CONTAINER_ELEMS = {
    'List': None,        # resolved from the subscript
    'UnsafePointer': None,
    'DType': None,
}

#: Element types the synthesised kernel signature may carry. The MSL side
#: narrows `Int`/`Int64` to 32-bit (metal_ops._KERNEL_ARG_NARROW), so a
#: scalar parameter is `Int` and a container parameter is whatever the
#: recogniser saw. This set is the ALLOWED parameter annotation spellings; an
#: unrecognised annotation refuses synthesis rather than being guessed at.
#: How a container is spelled in a synthesised DEVICE signature. See the
#: note at the parameter-ordering site for why this is not the source's
#: `List[T]`.
_POINTER_SPELLING = 'UnsafePointer[%s, MutAnyOrigin]'

#: The synthesised kernel's length parameter. Separate from every source
#: name, so adding a synthesised function to a module cannot shadow or be
#: shadowed by a parameter of the function it came from.
_LENGTH_PARAM = '_mg_len'

_ALLOWED_PARAM_TYPES = frozenset({
    'Int', 'Int32', 'Int64', 'UInt32', 'UInt64',
    'Float32', 'Float64', 'Float16',
})


class SynthesisRefused(Exception):
    """A recognised loop whose device form cannot be built honestly.

    Raised only AFTER `recognise` accepted the loop, so it means the
    recogniser and the synthesiser disagree about what is expressible -- a
    bug in one of them, not a user error. The caller treats it as "leave the
    loop on the host" and says so, because a synthesised kernel that does not
    match the loop it came from is a silent wrong answer.
    """


def _container_element(ann: str) -> str | None:
    """The element type inside `List[T]` / `UnsafePointer[T, ...]`, else None.

    A scalar annotation returns None here, because a scalar is not a
    container -- the caller distinguishes by position, not by this returning
    something for every input.
    """
    for prefix in ('List', 'UnsafePointer', 'DType'):
        if ann.startswith(prefix + '['):
            rest = ann[len(prefix) + 1:]
            depth = 1
            out = []
            for ch in rest:
                if ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        break
                if depth == 1 and ch == ',':
                    break
                out.append(ch)
            return ''.join(out).strip()
    return None


def _param_annotation(fdef, name: str) -> str | None:
    """The declared annotation for `name`, or None if unannotated."""
    for p in (getattr(fdef, 'params', None) or ()):
        if isinstance(p, tuple) and _as_str(p[0]) == name:
            ann = p[1]
            if ann is None:
                return None
            if isinstance(ann, str):
                return ann
            # A node: its dotted tail is the type name.
            parts = []
            node = ann
            for _ in range(6):
                nxt = getattr(node, 'name', None) or getattr(node, 'member', None)
                if nxt is None:
                    obj = getattr(node, 'obj', None)
                    if obj is None:
                        break
                    node = obj
                    continue
                parts.append(_as_str(nxt))
                node = getattr(node, 'obj', None)
                if node is None:
                    break
            return '.'.join(reversed(parts)) if parts else None
    return None


def synthesise(fdef, info: 'Offloadable') -> 'object':
    """A `@gpu` FunctionDef equivalent to `fdef`'s single loop, or raise.

    The device function is:

    * named ``_mg_offload_<name>``;
    * ``@gpu``, so it goes through seam 1's classifier, seam 2's MSL
      emitter and seam 3's host-wrapper generation UNCHANGED. That reuse is
      the point: increment 3 adds a recogniser and a synthesiser, not a
      second code path;
    * taking the loop's containers and scalars as parameters, in a fixed
      order (written container last, so the length parameter lands in the
      slot the wrapper expects);
    * with the loop variable supplied by the kernel's own grid index, which
      is the synthesised form of ``for i in range(n)``.

    Raises `SynthesisRefused` rather than emitting something approximate.
    """
    # 1. Every name the body touches must have a type we can put in a
    #    signature. An unannotated container is the interesting refusal: the
    #    recogniser does not track types, so `def f(x, out, n)` with bare
    #    names would synthesise a kernel with untyped buffers.
    names = [info.writes] + list(info.reads)
    anns: dict = {}
    for nm in names:
        ann = _param_annotation(fdef, nm)
        if ann is None:
            raise SynthesisRefused(
                f'container {nm!r} has no type annotation, so a device '
                'signature for it would be a guess')
        elem = _container_element(ann)
        if elem is None:
            raise SynthesisRefused(
                f'container {nm!r} has type {ann!r}, which is not a '
                'container this can give a device signature for')
        if elem not in _ALLOWED_PARAM_TYPES:
            raise SynthesisRefused(
                f'container {nm!r} has element type {elem!r}, which has no '
                f'device signature here (allowed: {sorted(_ALLOWED_PARAM_TYPES)})')
        anns[nm] = elem
    scalar_ann = _param_annotation(fdef, info.param)
    if scalar_ann is not None and scalar_ann not in _ALLOWED_PARAM_TYPES:
        raise SynthesisRefused(
            f'trip-count parameter {info.param!r} has type {scalar_ann!r}, '
            'which is not a device scalar type')

    # 2. Reuse the ORIGINAL loop body verbatim. It is already the parallel
    #    map `recognise` verified, expressed over the loop variable; the
    #    kernel differs only in where that variable comes from. Copying the
    #    nodes rather than rebuilding the expression is what keeps the two
    #    from drifting apart -- a re-implementation here is how the kernel
    #    would end up computing something the loop did not.
    loop = [s for s in (getattr(fdef, 'body', None) or ())
            if isinstance(s, gctypes.ForStmt)][0]
    kernel_body = list(loop.body or ())

    # 3. The loop variable becomes a local bound to the grid index, so the
    #    body needs no rewriting at all.
    idx = gctypes.IdentExpr(name=info.index, line=0, col=0)
    bind = gctypes.AssignStmt(
        target=idx, value=gctypes.MemberExpr(
            obj=gctypes.IdentExpr(name='global_idx', line=0, col=0),
            member='x', line=0, col=0),
        line=0, col=0)
    # 4. The bounds guard the host loop had via `range(n)`. Without it a
    #    grid sized from `n` is exact, but a caller that over-reports must
    #    not read past the end -- and the recogniser's `n` is a parameter,
    #    so "over-reports" is reachable.
    # The guard bound is the LENGTH, and the length is not one of the
    # containers -- it is a separate scalar. `vec_add` takes `len: Int`
    # alongside its buffers for exactly this reason, and the host wrapper
    # fills it from the list's real length. Naming the container here
    # instead emitted `if (i >= out)` -- comparing an index against a
    # POINTER, which is not a bounds check at all.
    guard = gctypes.IfStmt(
        condition=gctypes.CompareChain(
            operands=[idx, gctypes.IdentExpr(name=_LENGTH_PARAM,
                                             line=0, col=0)],
            ops=['>='], line=0, col=0),
        then_body=[gctypes.ReturnStmt(value=None, line=0, col=0)],
        elifs=[], else_body=None, line=0, col=0)

    # 5. Parameter order: read containers, scalars, then the written
    #    container LAST. The wrapper's marshalling for a buffer argument and
    #    its narrowing for a scalar both key off position, and putting the
    #    written container last is what makes the length parameter available
    #    to the guard above.
    # A container parameter is spelled as a POINTER on the device, not as
    # the source's `List[T]`. That is not cosmetic: `emit_metal._param_type`
    # resolves through the same `_mojo_type` the C backend uses, and
    # `List[Float32]` resolves to `MojoList *`, which it REFUSES by name --
    # a heap object with a host header, which is exactly what a MojoList is
    # on the device. `UnsafePointer[Float32, MutAnyOrigin]` resolves to
    # `float *`, which is the buffer the kernel wants. Reusing the pointer
    # spelling is also why no new ABI is needed: it is the same signature
    # every hand-written kernel in the tests already uses.
    # Every bare identifier the body reads becomes a parameter: the loop
    # variable is excluded (the kernel supplies it) and the trip count is
    # excluded (it is the grid size, and the guard below uses the written
    # container's length instead). A scalar left out here is emitted as an
    # undeclared global, which is how the `a` in `a * x[i]` was first found
    # missing.
    carried = set(info.scalars)
    for nm in sorted(carried):
        ann = _param_annotation(fdef, nm)
        if ann is None or ann not in _ALLOWED_PARAM_TYPES:
            raise SynthesisRefused(
                f'scalar {nm!r} has type {ann!r}, which is not a device '
                'scalar type')
    # ORDER IS A CONTRACT, not a convenience. `device_glue.launch_arg_types`
    # takes the FIRST `Int`/`Int64` parameter as the element count for the
    # device->host copy-back, so putting the length anywhere but first lets an
    # `Int` scalar coefficient steal the role: measured, `out[i] = x[i] * k`
    # with `k: Int` put `k` at count_idx, and the host would have copied back
    # `k` elements instead of the list's length. The length goes first, then
    # the scalars, then the read buffers, then the written buffer LAST so its
    # index is not shifted by a buffer inserted before it.
    params: list = [(_LENGTH_PARAM, 'Int')]
    for nm in sorted(carried):
        params.append((nm, _param_annotation(fdef, nm)))
    for nm in info.reads:
        params.append((nm, _POINTER_SPELLING % anns[nm]))
    params.append((info.writes, _POINTER_SPELLING % anns[info.writes]))

    return gctypes.FunctionDef(
        name=SYNTH_PREFIX + _as_str(fdef.name),
        params=params,
        return_type=None,
        body=[bind, guard] + kernel_body,
        decorators=['gpu'],
        line=0, col=0)


def synthesise_module(stmts: list) -> list:
    """One synthesised `@gpu` FunctionDef per offloadable loop in `stmts`.

    Returns them in source order. An empty list means nothing was recognised,
    which is the common case and is not an error.

    Deliberately does NOT rewrite the original functions to call the
    synthesised ones. That rewrite is a real control-flow change (a dispatch
    where a loop was, with the list marshalling in between) and it is the
    part of increment 3 that has to be right about the HOST side, not just
    the device side. The device half is what lands here, verified end to end
    on the GPU; the host rewrite is a separate step, and shipping the kernel
    without it is the difference between an unreachable kernel and a wrong
    answer.
    """
    out: list = []
    for s in (stmts or []):
        if not isinstance(s, gctypes.FunctionDef):
            continue
        if _decorator_names(s) & _EXPLICIT:
            # Already a device function by request; nothing to infer.
            continue
        info = recognise(s)
        if info is None:
            continue
        try:
            out.append(synthesise(s, info))
        except SynthesisRefused:
            # Recognised but not expressible on the device. Leaving the loop
            # on the host is always correct; see the class docstring.
            continue
    return out


def _decorator_names(fdef) -> set:
    """The NAMES on a function's decorators, as strings.

    A decorator is not always a bare name: `@gpu` is, but
    `@functools.lru_cache(maxsize=1)` is a CallExpr node, which is unhashable
    and dies if put in a set directly. (device_select._decorator_names
    documents the real instance -- `version.py` in the self-host closure.)
    So: a string entry is itself, a name/member node is its name, and a call
    contributes its callee's name.
    """
    names: set = set()
    for d in (getattr(fdef, 'decorators', None) or []):
        if isinstance(d, str):
            names.add(d)
            continue
        if isinstance(d, (gctypes.IdentExpr, gctypes.MemberExpr)):
            n = getattr(d, 'name', None) or getattr(d, 'member', None)
            if n:
                names.add(_as_str(n))
            continue
        f = getattr(d, 'func', None)
        if isinstance(f, gctypes.IdentExpr) and getattr(f, 'name', None):
            names.add(_as_str(f.name))
        elif isinstance(f, gctypes.MemberExpr) and getattr(f, 'member', None):
            names.add(_as_str(f.member))
    return names
