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

import os

import fire_compiler as gctypes
from typing import NamedTuple

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

#: `info.param` is a trip-count PARAMETER NAME. A `range(len(x))` bound
#: is not a name at all, so it is carried with this prefix and decoded
#: where the bound is needed. Prefixed rather than stored in a second
#: field because every existing consumer reads `.param` as a name, and a
#: silent second representation is how those would diverge.
_LEN_PREFIX = 'len:'


def _trip_is_len(param) -> bool:
    return isinstance(param, str) and param.startswith(_LEN_PREFIX)


def _trip_arg_name(param) -> str:
    """The HOST name of the trip-count argument, whatever form the bound took.

    A `len:`-prefixed bound is spelled `len(a)` in the source but reaches the
    call site as the plain identifier `a` -- the same list the kernel already
    reads, so it is already packed and needs no separate argument. Passing the
    literal string `len:a` instead would emit an undeclared identifier.
    """
    return param[len(_LEN_PREFIX):] if _trip_is_len(param) else param


#: Name of the host local a `len(x)` trip count is bound to. Prefixed so it
#: cannot collide with a user identifier, and named once here because the
#: rewrite introduces it and `host_call` names it -- two spellings of one
#: fact is how those drift.
_TRIP_LOCAL = '_mg_trip'


def _trip_local(param) -> str:
    return _TRIP_LOCAL if _trip_is_len(param) else param


def _trip_expr(param):
    """An AST expression for the trip count, as the source spelled it.

    Used for the profitability guard, which has to compare against the value
    the loop actually iterates: `len(a)` for a `range(len(a))` bound, and a
    bare name otherwise. Comparing against the name `a` would guard on a
    POINTER, which is not a trip count and would always pass.
    """
    if _trip_is_len(param):
        return gctypes.CallExpr(
            func=gctypes.IdentExpr(name='len', line=0, col=0),
            args=[gctypes.IdentExpr(name=_trip_arg_name(param), line=0, col=0)],
            line=0, col=0)
    return gctypes.IdentExpr(name=param, line=0, col=0)

_ALLOWED_EXPR_NODES = (
    'IdentExpr', 'IntLiteral', 'FloatLiteral', 'BoolLiteral', 'StringLiteral',
    'BinaryOp', 'UnaryOp', 'SubscriptExpr', 'CompareChain', 'ParenExpr',
)


#: Smallest trip count worth a dispatch, and WHY that number.
#:
#: Every number here is measured on the machine this was written on (M5 Max,
#: macOS 26, a virtualised GPU), with `clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)`
#: in-language -- `CLOCK_MONOTONIC` ticks at 1000 ns and is too coarse to time a
#: dispatch honestly. A single parallel-map loop, GPU vs the same loop with
#: `--no-gpu`:
#:
#:     n            GPU us/iter    CPU us/iter
#:     1024             195.6           3.6
#:     16384            299.6          37.0
#:     262144          1561.6         740.6
#:     4194304        22373.7        9354.5
#:
#: which fits `GPU = 190 us + 5.29 ns/elem` against `CPU = 2.23 ns/elem`.
#:
#: Read honestly, that fit says the synthesised kernel is 2.4x slower PER ELEMENT
#: than the CPU loop as well as carrying a 190 us fixed cost, so on this machine
#: the elementwise shape does not cross over AT ANY SIZE -- it asymptotes to
#: 0.42x, which is what the 4194304 row measures. A threshold cannot repair
#: that; it can only stop the pathological case, which is the one that actually
#: bites:
#:
#: `test_llm.py`'s `dot()` is 30.5% of that model's runtime and is called
#: 3,481,968 times per six steps, on 128-element slices, at 2.44 us a call.
#: Offloading it would spend ~195 us per call -- 80x slower -- and turn a 27.9 s
#: profile into roughly 700 s. A loop nest called in the millions is the case
#: where a fixed per-dispatch cost is fatal, and nothing about the loop's SHAPE
#: reveals it; only the trip count does.
#:
#: So this is a floor on the trip count, chosen as the point where the CPU loop's
#: own time reaches the dispatch's fixed cost:
#:
#:     2.23 ns/elem * n  >  190 us   =>   n > 85,200
#:
#: rounded to 90_000. It is a floor, not a promise: above it the GPU may still
#: lose, and on a machine with a real (not virtualised) GPU, or with MTL4's
#: low-overhead dispatch queue, the crossover moves left by more than an order of
#: magnitude. `MOJO_OFFLOAD_MIN_ELEMENTS` overrides it for exactly that reason --
#: this constant is a measurement of ONE machine, and hardcoding a machine's
#: dispatch latency as a universal truth is how it goes stale.
_MIN_PROFITABLE_ELEMENTS = 90_000


def _min_profitable_elements() -> int:
    """`_MIN_PROFITABLE_ELEMENTS`, overridable from the environment.

    Read at CALL time rather than import time so a test (or a user on a faster
    dispatch path) can change it without reimporting, and so the override is
    visible in `explain` output as the number actually in force.
    """
    import os
    raw = os.environ.get('MOJO_OFFLOAD_MIN_ELEMENTS')
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _MIN_PROFITABLE_ELEMENTS


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
    if isinstance(bound, gctypes.IdentExpr):
        return _as_str(bound.name)
    # `range(len(a))`: the trip count is a CONTAINER'S OWN LENGTH, which is
    # safe where a general expression would not be, and for a reason worth
    # stating. The host marshals by packing each buffer to the trip count, so
    # a trip count that IS a buffer length cannot under-pack the buffer the
    # length came from -- the failure the offset-index case has. `len(b) <
    # len(a)` reads past `b` here exactly as it would in the original loop, so
    # the offloaded semantics are the loop's own, not a new hazard.
    #
    # `range(self.cols)` is still refused: `self` is a host struct with a heap
    # header and cannot cross to the device at all, and admitting the
    # attribute would mean synthesising a local binding for it, which rewrites
    # the loop rather than reusing its body. `CallExpr` here is specifically
    # `len`, and `_check_expr`'s scope check still governs the body.
    if isinstance(bound, gctypes.CallExpr) and _is_name(bound.func, 'len'):
        largs = list(bound.args or ())
        if len(largs) == 1 and isinstance(largs[0], gctypes.IdentExpr):
            return _LEN_PREFIX + _as_str(largs[0].name)
    return None


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
            # An OFFSET index -- `gr[base + j]`, which is how
            # `test_llm.py`'s `add_grad_row` addresses its row -- is refused
            # HERE, deliberately, even though the arithmetic works. It was
            # implemented, measured, and reverted; the reason is the host
            # marshalling, and it is not fixable in the recogniser.
            #
            # `synthesise` reuses the loop body verbatim, so `gr[base + j]`
            # becomes `gr[base + i]` in MSL for free and `base` arrives as an
            # ordinary scalar parameter. The kernel is then correct AS A KERNEL
            # and wrong in the program: the host packs each buffer to the TRIP
            # COUNT, so for `base=1024, cols=262144` the kernel indexes up to
            # 263167 while the packed buffer ends at 262143.
            #
            # Measured, with a discriminating test (buffers that cannot tell
            # an honoured offset from a dropped one):
            #
            #     row[0]     expect 2024    got 2024.0   (correct)
            #     row[last]  expect 264167  got 1000.0   (CPU oracle: 264167.0)
            #
            # so the offset is silently dropped and the answer is wrong for
            # every element except the first. `base == 0` happens to work,
            # which is the worst kind of bug: it passes the obvious test.
            #
            # Making it correct means the host must pack each buffer to
            # `offset + trip` for the buffers an offset index reaches, which
            # needs the offset to be part of the marshalling contract --
            # `device_glue.launch_arg_types` currently takes the FIRST Int
            # parameter as THE element count, and that single rule is what the
            # whole launch path is built on. That is a change to the launch
            # ABI, not to this recogniser, and it is not worth making for a
            # shape that is 12.1% of one model.
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
        # Same offset-index refusal as in `_check_expr`, and for the same
        # measured reason.
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

#: The same, for a buffer the kernel only READS. See the parameter-ordering
#: note in `synthesise` for why the host marshalling acts on this.
_IMMUTABLE_SPELLING = 'UnsafePointer[%s, ImmutAnyOrigin]'

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
    # A `len(a)` bound names no parameter, so there is no annotation to check;
    # its type is the container's element count, which the launch path already
    # narrows. Checking it as if it were a parameter would look up `len:a` and
    # find nothing.
    scalar_ann = (None if _trip_is_len(info.param)
                  else _param_annotation(fdef, info.param))
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
    # ORDER IS A CONTRACT, and THREE of them have to agree here.
    #
    # 1. runtime/fire_metal.m binds buffers at indices 0..n_bufs-1 and the
    #    scalars after them.
    # 2. MSL gives a parameter WITHOUT a `[[buffer(N)]]` attribute the next
    #    free index BY DECLARATION POSITION, counting every preceding
    #    buffer-or-reference parameter. So a scalar declared BEFORE a buffer
    #    silently takes that buffer's index.
    # 3. `device_glue.launch_arg_types` takes the FIRST `Int`/`Int64`
    #    parameter as the element count for the copy-back.
    #
    # BUFFERS FIRST, THEN SCALARS satisfies all three: the explicit
    # `[[buffer(0..n)]]` on the buffers matches the runtime, the scalars land
    # implicitly at n_bufs.. where the runtime puts them, and the length is
    # still the first `Int` parameter (a buffer is not an `Int` parameter, so
    # its position does not matter for that rule -- only its being an `Int`
    # does).
    #
    # Length first WITHIN the scalars, so an `Int` coefficient cannot steal
    # count_idx. Measured: with the length before the buffers, `x`'s
    # [[buffer(0)]] and the scalar's implicit index collided and the real
    # runtime aborted with "Command encoder released without endEncoding".
    # Read containers are declared with the IMMUTABLE origin and the written
    # one with the mutable origin. The C type is `float *` either way, so this
    # changes nothing about the kernel's arithmetic -- it is a promise about
    # which buffers the kernel writes, and the host marshalling BELIEVES it.
    #
    # Why that is worth doing: the launch lowering packs every buffer and
    # unpacks every buffer back. For a read-only input the unpack is two
    # wasted O(n) passes (one to write the values it just read out, one to
    # free), on every dispatch, for no observable effect. The stdlib's own
    # spelling for this is `ImmutAnyOrigin` (see
    # std/gpu/host/device_graph.mojo), so this follows the convention rather
    # than inventing one.
    #
    # Note the existing hand-written kernels in this tree pass a BARE
    # `UnsafePointer[Float32]` for inputs and output alike, so nothing
    # changes for them: an annotation with no origin is treated as writable,
    # which is the conservative direction (an unnecessary write-back is
    # wasted work; a missing one is a wrong answer).
    params: list = []
    for nm in info.reads:
        params.append((nm, _IMMUTABLE_SPELLING % anns[nm]))
    params.append((info.writes, _POINTER_SPELLING % anns[info.writes]))
    params.append((_LENGTH_PARAM, 'Int'))
    for nm in sorted(carried):
        params.append((nm, _param_annotation(fdef, nm)))

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


# ---------------------------------------------------------------------------
# The host half: replace the loop with a call
# ---------------------------------------------------------------------------


def host_call(fdef, info: 'Offloadable') -> 'object':
    """A `CallExpr` replacing `fdef`'s loop, targeting the synthesised kernel.

    This is the other half of increment 3. The kernel alone is unreachable;
    this is what makes the offload real. It is a plain `CallExpr` to a
    function that is a DEVICE function, so `emit_calls._lower_device_launch`
    picks it up unchanged and does all the host-side work -- packing each list
    into a contiguous buffer, narrowing each scalar to the width the MSL
    declares, dispatching, writing the output back, freeing. Reusing that
    path rather than writing a second marshaller is the point: the marked
    `@gpu` path is already verified on real hardware, and a parallel
    implementation of the same marshalling is a second thing to get right.

    Argument order is the SYNTHESISED KERNEL's parameter order, which
    `synthesise` fixed: length, scalars, read buffers, written buffer. It is
    read back off that function rather than recomputed here, so the call site
    and the signature cannot disagree -- a mismatch would be a silent wrong
    answer, and it is exactly the class of bug the two ordering contracts in
    `synthesise` exist to prevent.

    The length argument is the trip-count PARAMETER (`n`), not the container
    length. They are the same whenever the caller passes a matching count,
    and when they differ the caller's `n` is the loop's own trip count, which
    is what `range(n)` said -- taking the container's length instead would
    silently change the loop's meaning.
    """
    kernel = synthesise(fdef, info)
    # The arguments are named in the HOST function's namespace, NOT the
    # kernel's. The kernel's length parameter is `_mg_len`, which exists only
    # inside the device function; naming it here produced
    #
    #     _t1 = (int64_t)0;  /* ct param or undeclared: _mg_len */
    #
    # i.e. a length of 0, so every list packed to one element, the kernel's
    # `i >= _mg_len` guard rejected every thread, and the zero-length buffer
    # allocation took runtime/fire_metal.m's early-return path -- which leaks
    # the command encoder and ABORTS the process. Measured end to end.
    #
    # So: read buffers, written buffer, the trip count under its OWN name,
    # then the scalars -- the same order `synthesise` gave the parameters,
    # which is what makes the two agree by construction.
    # For a `len(x)` bound the trip-count argument is the HOST LOCAL the
    # rewrite introduced, not `x` itself. Passing `x` hands the marshaller a
    # MojoList* where it expects an int, and it narrows the pointer's low bits
    # into the element count -- measured, a SIGBUS on the oversized allocation.
    # The local is an ordinary identifier, so everything downstream (the guard,
    # the packing, the signature) is unchanged.
    host_args = (list(info.reads) + [info.writes, _trip_local(info.param)]
                 + list(info.scalars))
    kernel_names = [_as_str(p[0]) for p in (kernel.params or ())]
    expected = (list(info.reads) + [info.writes, _LENGTH_PARAM]
                + sorted(info.scalars))
    if kernel_names != expected:
        # If these ever disagree the call would bind arguments to the wrong
        # parameters -- a silent wrong answer, not a build error. Refuse.
        raise SynthesisRefused(
            f'call argument order {expected!r} does not match the synthesised '
            f'kernel parameters {kernel_names!r}')
    args = [gctypes.IdentExpr(name=nm, line=0, col=0) for nm in host_args]
    return gctypes.CallExpr(
        func=gctypes.IdentExpr(name=_as_str(kernel.name), line=0, col=0),
        args=args, line=0, col=0)


def rewrite_to_dispatch(fdef, info: 'Offloadable') -> 'object | None':
    """`fdef` with its loop replaced by the dispatch call, or None.

    Returns a NEW FunctionDef; the original AST is not mutated, because the
    synthesised kernel copies nodes OUT of the original body and mutating it
    underneath would change what those copies contain.

    Refuses (returns None) when anything about the shape is not exactly what
    `host_call` assumed, because a partially-rewritten host function is the
    silent-wrong-answer case: the kernel would run over a list the host never
    finished preparing, or the host would keep the loop and the kernel would
    run too. Both compute something; neither is what the program said.
    """
    body = list(getattr(fdef, 'body', None) or ())
    loops = [s for s in body if isinstance(s, gctypes.ForStmt)]
    if len(loops) != 1:
        return None
    loop = loops[0]
    try:
        call = host_call(fdef, info)
    except (SynthesisRefused, AttributeError, TypeError):
        return None

    # The PROFITABILITY GUARD. The trip count is a runtime value, so whether a
    # dispatch is worth it cannot be decided here -- it has to be a branch the
    # program takes, with the original loop kept as the other arm. Emitting the
    # dispatch unconditionally is the footgun `_MIN_PROFITABLE_ELEMENTS`
    # documents: a nest called in the millions spends a fixed ~190 us per call
    # and gets slower by two orders of magnitude, with no diagnostic, because a
    # correct answer and a slow one look identical from the outside.
    #
    # The comparison is against the trip count EXPRESSION as written
    # (`info.param`), not the parameter name, so a future `range(len(a))` bound
    # guards on the length rather than on nothing.
    trip = gctypes.IdentExpr(name=_trip_local(info.param), line=0, col=0)
    floor = gctypes.IntLiteral(value=_min_profitable_elements(), line=0, col=0)
    guarded = gctypes.IfStmt(
        condition=gctypes.CompareChain(operands=[trip, floor], ops=['>='],
                                       line=0, col=0),
        then_body=[gctypes.ExprStmt(value=call, line=0, col=0)],
        elifs=[],
        else_body=[loop],
        line=0, col=0)

    new_body = []
    for st in body:
        if st is loop:
            if _trip_is_len(info.param):
                # `for i in range(len(x))` -> bind the length to a host local
                # first, so the trip count reaching the launch is an
                # IDENTIFIER like every other launch argument. The kernel body
                # is untouched: only the host gains a line, and the loop the
                # user wrote still means the same thing.
                new_body.append(gctypes.AssignStmt(
                    target=gctypes.IdentExpr(name=_TRIP_LOCAL, line=0, col=0),
                    value=_trip_expr(info.param), line=0, col=0))
            new_body.append(guarded)
            continue
        new_body.append(st)
    return gctypes.FunctionDef(
        name=_as_str(fdef.name),
        params=list(fdef.params or ()),
        return_type=fdef.return_type,
        body=new_body,
        decorators=list(fdef.decorators or ()),
        param_convs=dict(fdef.param_convs or {}),
        param_has_default=dict(fdef.param_has_default or {}),
        param_defaults=dict(fdef.param_defaults or {}),
        kwonly=list(fdef.kwonly or ()),
        comptime_params=list(fdef.comptime_params or ()),
        is_generator=bool(getattr(fdef, 'is_generator', False)),
        is_async=bool(getattr(fdef, 'is_async', False)),
        line=getattr(fdef, 'line', 0), col=getattr(fdef, 'col', 0))


# ── the matmul nest ─────────────────────────────────────────────────────────
#
# A GEMM is the second recognised shape, and it is NOT a special case of the
# first. The existing recogniser requires a single loop whose body is a single
# assignment, and reuses that body VERBATIM in the kernel. A GEMM is a triple
# nest with a scalar accumulator and affine indices, and its kernel is a
# completely different computation -- one thread per OUTPUT element, indexing
# (i, j) from a flat grid coordinate. Nothing about it can be reused verbatim,
# so this is a second synthesis path rather than a widening of the first.
#
# It is here because the naive triple loop is what people actually write, and
# the win is real: a synthesised parallel GEMM against the scalar path is the
# same 20x the hand-written tensor-core kernel already measures. The tensor
# cores themselves are a further step (see the module docstring).


class GemmInfo(NamedTuple):
    """A recognised `C[i*n + j] = sum_p A[i*k + p] * B[p*n + j]`.

    The names are the SOURCE's. `lengths` maps each of A, B, C to the C
    expression giving its element count, which is what the launch marshalling
    needs and what a single count parameter cannot express: A is M*K, B is K*N,
    C is M*N.
    """

    a: str
    b: str
    c: str
    m: str
    k: str
    n: str
    acc: str
    elem: str
    lengths: dict


def _affine_index(node, want: dict) -> bool:
    """Does `node` spell out the product/sum of `want`?

    `want` maps a variable name to its coefficient, e.g. {'i': 1, 'k': 1, 'p': 1}
    for `i*k + p`. Matching by STRUCTURE rather than by printing the source and
    comparing text, because multiplication is commutative and `k*i + p` is the
    same index. Every term must be accounted for exactly once, so a duplicated or
    dropped factor is a refusal rather than a silent wrong address.
    """
    remaining = dict(want)
    terms: list = []

    def walk(nd) -> bool:
        nm = type(nd).__name__
        if nm == 'BinaryOp':
            if nd.op in ('+', '-'):
                return walk(nd.left) and walk(nd.right)
            if nd.op == '*':
                # only single-variable products are matched; a product of two
                # compound terms would need distributing and is refused
                lv, rv = nd.left, nd.right
                if isinstance(lv, gctypes.IdentExpr):
                    terms.append(_as_str(lv.name))
                elif isinstance(rv, gctypes.IdentExpr):
                    terms.append(_as_str(rv.name))
                else:
                    return False
                return walk(lv if not isinstance(lv, gctypes.IdentExpr) else rv)
            return False
        if nm == 'IdentExpr':
            terms.append(_as_str(nd.name))
            return True
        if nm == 'IntLiteral' and nd.value == 1:
            return True          # an explicit *1 is a no-op
        return False

    if not walk(node):
        return False
    return sorted(terms) == sorted(remaining)


def _subscript_name(node):
    parts = _subscript_parts(node)
    return parts[0] if parts else None


def recognise_gemm(fdef) -> 'GemmInfo | None':
    """The textbook GEMM nest in `fdef`, or None.

        for i in range(m):
            for j in range(n):
                acc: T = 0.0
                for p in range(k):
                    acc = acc + A[i*k + p] * B[p*n + j]
                C[i*n + j] = acc

    Every clause is checked against the AST rather than assumed: the bounds are
    the right parameters, the accumulator is initialised to a literal zero and
    updated as `acc + (A * B)`, and all three indices are the expected affine
    forms. A nest that is nearly this -- a transposed B, a max() in the
    accumulator, a strided store -- is refused, because each of those computes
    something the kernel does not.
    """
    body = list(getattr(fdef, 'body', None) or ())
    if len(body) != 1 or not isinstance(body[0], gctypes.ForStmt):
        return None
    outer = body[0]
    m = _trip_count_param(outer.iterable)
    if m is None or not isinstance(outer.target, str):
        return None
    i = outer.target

    jbody = list(outer.body or ())
    if len(jbody) != 1 or not isinstance(jbody[0], gctypes.ForStmt):
        return None
    inner_outer = jbody[0]
    n = _trip_count_param(inner_outer.iterable)
    if n is None or not isinstance(inner_outer.target, str):
        return None
    j = inner_outer.target

    kbody = list(inner_outer.body or ())
    if len(kbody) != 3:
        return None
    init, kloop, store = kbody
    if not isinstance(init, gctypes.AssignStmt) or not isinstance(kloop, gctypes.ForStmt) \
            or not isinstance(store, gctypes.AssignStmt):
        return None
    k = _trip_count_param(kloop.iterable)
    if k is None or not isinstance(kloop.target, str):
        return None
    p = kloop.target

    # acc := 0.0
    if not isinstance(init.target, gctypes.IdentExpr):
        return None
    acc = _as_str(init.target.name)
    if not isinstance(init.value, (gctypes.FloatLiteral, gctypes.IntLiteral)):
        return None
    if getattr(init.value, 'value', 1) != 0.0:
        return None

    # acc := acc + (A[..] * B[..]), as the sole statement of the k loop
    kloop_body = list(kloop.body or ())
    if len(kloop_body) != 1 or not isinstance(kloop_body[0], gctypes.AssignStmt):
        return None
    upd = kloop_body[0]
    if not isinstance(upd.target, gctypes.IdentExpr) or _as_str(upd.target.name) != acc:
        return None
    add = upd.value
    if not isinstance(add, gctypes.BinaryOp) or add.op != '+':
        return None
    if not (isinstance(add.left, gctypes.IdentExpr) and _as_str(add.left.name) == acc):
        return None
    mul = add.right
    if not isinstance(mul, gctypes.BinaryOp) or mul.op != '*':
        return None
    a_sub, b_sub = mul.left, mul.right
    if _subscript_name(a_sub) is None or _subscript_name(b_sub) is None:
        return None
    if not (_affine_index(a_sub.index, {i: 1, k: 1, p: 1})
            and _affine_index(b_sub.index, {p: 1, n: 1, j: 1})):
        return None
    a_name, b_name = _subscript_name(a_sub), _subscript_name(b_sub)

    # C[i*n + j] := acc
    if _subscript_name(store.target) is None:
        return None
    c_name = _subscript_name(store.target)
    if not _affine_index(store.target.index, {i: 1, n: 1, j: 1}):
        return None
    if not (isinstance(store.value, gctypes.IdentExpr)
            and _as_str(store.value.name) == acc):
        return None

    # annotations: three same-element lists, three Int extents
    anns = {}
    for prm in (getattr(fdef, 'params', None) or ()):
        nm, ann = (prm[0], prm[1]) if isinstance(prm, tuple) else (prm, '')
        anns[_as_str(nm)] = _as_str(ann or '')
    for nm in (a_name, b_name, c_name):
        if not anns.get(nm, '').startswith('List['):
            return None
    elems = {anns[nm].split('[', 1)[1].rstrip(']') for nm in (a_name, b_name, c_name)}
    if len(elems) != 1:
        return None
    elem = elems.pop()
    if elem not in _ALLOWED_PARAM_TYPES:
        return None
    for nm in (m, k, n):
        if anns.get(nm) not in ('Int', 'Int64'):
            return None
    if len({a_name, b_name, c_name, m, k, n, acc}) != 7:
        return None
    return GemmInfo(a=a_name, b=b_name, c=c_name, m=m, k=k, n=n, acc=acc,
                    elem=elem,
                    lengths={a_name: f'{m} * {k}', b_name: f'{k} * {n}',
                             c_name: f'{m} * {n}'})


def _gemm_kernel_source(info: 'GemmInfo') -> str:
    """The synthesised kernel as Mojo source, for the record.

    Documentation only -- the AST below is what is actually emitted, and this
    is the shortest honest description of it. Kept because the emitted MSL is
    the thing worth reading and a reader should not have to reconstruct the
    source from the AST builder.
    """
    L = [
        '@gpu',
        'def _mg_offload_gemm(A: UnsafePointer[%s, ImmutAnyOrigin],' % info.elem,
        '                     B: UnsafePointer[%s, ImmutAnyOrigin],' % info.elem,
        '                     C: UnsafePointer[%s, MutAnyOrigin],' % info.elem,
        '                     m: Int, k: Int, n: Int):',
        '    idx = global_idx.x',
        '    i = idx / n',
        '    j = idx - i * n',
        '    acc: %s = 0.0' % info.elem,
        '    for p in range(k):',
        '        acc = acc + A[i * k + p] * B[p * n + j]',
        '    C[i * n + j] = acc',
    ]
    return '\n'.join(L)


#: The MMA fragment layout for an 8x8 simdgroup_matrix, taken from the layout
#: table verified by test_llm/frag_layout_probe.m. A lane q holds rows
#: (q/4 & 4) + (q/2 % 4) and (q/4 & 4) + (q/2 % 4) + 1; its first value is in
#: column (q/4 & 2)*2 + (q%2)*2, its second in the column after. Both are
#: CONSTANTS of the architecture, not of the matrix -- that is what makes the
#: MMA form what it is, and getting one row wrong transposes the result
#: silently.
_MMA_ROW = '((lane / 4) & 4) + ((lane / 2) % 4)'
_MMA_COL = '((lane / 4) & 2) * 2 + (lane % 2) * 2'


def _msl(x: str) -> str:
    return x


def gemm_tensor_core_msl(info: 'GemmInfo') -> str:
    """The whole tensor-core kernel body, as MSL text.

    One SIMDGROUP per 8x8 OUTPUT TILE, not one thread per output element --
    that is the whole point, and it is why the grid is not the runtime's
    inferred one. 32 lanes cooperate on 64 outputs.

    There is deliberately NO threadgroup staging here. test_llm/gemm_tiled.m
    measured the staged, double-buffered 64x64 kernel at 2-4% SLOWER than the
    unstaged one, so staging would be code that exists to be slower. Fragments
    are read straight from global memory into registers.

    Reads past the edge of a partial tile are replaced by 0.0 rather than
    predicated off, because a zeroed A or B row contributes exactly nothing to
    the product, so the stores below can be the only place bounds are checked.

    `lane` is __lid directly: the grid is one SIMDGROUP wide, so the
    thread's position in the threadgroup IS its lane. No division to recover it.
    """
    m, k, n = info.m, info.k, info.n
    A, B, C = info.a, info.b, info.c
    return f"""\
    int ntn = ({n} + 7) / 8;
    int tm = (__tgid / ntn) * 8;
    int tn = (__tgid - (__tgid / ntn) * ntn) * 8;
    int lane = int(__lid);
    int fr = {_MMA_ROW};
    int fc = {_MMA_COL};
    simdgroup_matrix<float, 8, 8> acc;
    reinterpret_cast<thread float2&>(acc.thread_elements()) = float2(0.0f);
    for (int k0 = 0; k0 < {k}; k0 += 8) {{
        simdgroup_matrix<float, 8, 8> Am;
        simdgroup_matrix<float, 8, 8> Bm;
        float2 av = float2(0.0f);
        float2 bv = float2(0.0f);
        if (tm + fr < {m} && k0 + fc < {k}) {{
            av.x = {A}[(tm + fr) * {k} + (k0 + fc)];
            if (k0 + fc + 1 < {k}) {{ av.y = {A}[(tm + fr) * {k} + (k0 + fc + 1)]; }}
        }}
        if (k0 + fr < {k} && tn + fc < {n}) {{
            bv.x = {B}[(k0 + fr) * {n} + (tn + fc)];
            if (tn + fc + 1 < {n}) {{ bv.y = {B}[(k0 + fr) * {n} + (tn + fc + 1)]; }}
        }}
        reinterpret_cast<thread float2&>(Am.thread_elements()) = av;
        reinterpret_cast<thread float2&>(Bm.thread_elements()) = bv;
        simdgroup_multiply_accumulate(acc, Am, Bm, acc);
    }}
    float2 r = reinterpret_cast<thread float2&>(acc.thread_elements());
    if (tm + fr < {m} && tn + fc < {n}) {{ {C}[(tm + fr) * {n} + (tn + fc)] = r.x; }}
    if (tm + fr < {m} && tn + fc + 1 < {n}) {{ {C}[(tm + fr) * {n} + (tn + fc + 1)] = r.y; }}"""


#: Grid for a tensor-core GEMM: one threadgroup per 8x8 output tile, one
#: SIMDGROUP wide. (nthreads, ngroups) as C expressions, because m/k/n are
#: runtime scalars in the wrapper's scope.
def gemm_tensor_core_grid(info: 'GemmInfo') -> tuple:
    return ('32', f'(({info.m} + 7) / 8) * (({info.n} + 7) / 8)')


#: Choose the tensor-core body. OFF by default, and that is a MEASUREMENT, not
#: caution. The MMA kernel is correct -- bit-exact, same checksum and elements
#: as the naive one on the same source -- and it is exactly as FAST as the
#: naive one, which is to say not fast:
#:
#:     512x512x512      ms/iter   TFLOPS
#:     tensor-core          2     0.134
#:     naive-parallel       2     0.134
#:     cpu (--no-gpu)     138       0.002
#:
#: One SIMDGROUP per 8x8 tile loads 64 A-elements and 64 B-elements to do
#: 1024 FLOP: an arithmetic intensity of 2 FLOP/byte. That is memory-bound by
#: a wide margin, so the MMA is never the thing being waited on and replacing
#: the scalar FMA with it buys nothing. The tile is too small to reuse anything.
#:
#: What the C kernel that reaches 0.96 TFLOPS does instead is a 64x64 tile
#: across 4 SIMDGROUPS, so each loaded element is reused 64 times and the
#: intensity is ~128 FLOP/byte. That is the change worth making, and it is
#: register pressure and an smem tile, not a better intrinsic. Until then the
#: AST-expressed naive kernel is the better default: same speed, and it is
#: Mojo rather than a raw MSL string.
TENSOR_CORES = os.environ.get('MOJO_GEMM_TENSOR_CORES', '') not in ('0', '')


def _raw_msl(text: str):
    """RawMslStmt, imported here so the parser/AST tier has no edge to the
    backend. `offload` already reaches the backend for the launch
    marshalling, so this is not a new dependency -- it just keeps the
    textual node out of the module that builds AST nodes."""
    from mojo.backend_gimple.emit_metal import RawMslStmt
    return RawMslStmt(text)


def synthesise_gemm(info: 'GemmInfo', tensor_cores: bool = False):
    """A `@gpu` FunctionDef computing the same product, one thread per output.

    The grid is 1-D and sized by the runtime from the OUTPUT buffer's element
    count (fire_metal.m: `use = nthreads > 0 ? nthreads : tptg`, and the
    threadgroup count comes from the output size), so thread `idx` covers
    exactly one C element and `i`/`j` fall out of a division. That division is
    why the index is derived rather than carried: a 2-D grid would avoid it,
    and the launch path is 1-D.

    Verified emitted MSL for this shape, from the existing backend with no
    changes to it:

        idx = __gid;  i = (idx / n);  j = (idx - (i * n));  acc = 0.0;
        for (p = 0; p < k; p += 1) { acc = (acc + (A[((i*k)+p)] * B[((p*n)+j)])); }
        C[((i * n) + j)] = acc;
    """
    params = [
        (info.a, f'UnsafePointer[{info.elem}, ImmutAnyOrigin]'),
        (info.b, f'UnsafePointer[{info.elem}, ImmutAnyOrigin]'),
        (info.c, f'UnsafePointer[{info.elem}, MutAnyOrigin]'),
        (info.m, 'Int'), (info.k, 'Int'), (info.n, 'Int'),
    ]

    def _fdef(body: list):
        # The signature is IDENTICAL for both bodies on purpose. The kernel
        # name, parameter list and address spaces are the recogniser's
        # contract, checked by recognise_gemm; only the computation differs,
        # so a divergence here could not be reached by a source that passes
        # recognition. That is what lets the two paths be A/B'd on one source.
        return gctypes.FunctionDef(
            name='_mg_offload_gemm', params=params, return_type=None,
            body=body,
            decorators=[gctypes.IdentExpr(name='gpu', line=0, col=0)],
            param_convs={}, param_has_default={}, param_defaults={},
            kwonly=[], comptime_params=[], is_generator=False, is_async=False,
            line=0, col=0)

    if tensor_cores:
        return _fdef([_raw_msl(gemm_tensor_core_msl(info))])

    I = gctypes.IdentExpr
    Lit = gctypes.IntLiteral
    FLit = gctypes.FloatLiteral

    def bin(op, l, r):
        return gctypes.BinaryOp(left=l, op=op, right=r, line=0, col=0)

    def assign(t, v):
        return gctypes.AssignStmt(target=t, value=v, line=0, col=0)

    idx, i, j, p = (I(name=x, line=0, col=0) for x in ('_mg_idx', 'i', 'j', 'p'))
    acc = I(name='_mg_acc', line=0, col=0)
    body = [
        assign(idx, gctypes.MemberExpr(
            obj=I(name='global_idx', line=0, col=0), member='x', line=0, col=0)),
        assign(i, bin('/', idx, I(name=info.n, line=0, col=0))),
        assign(j, bin('-', idx, bin('*', i, I(name=info.n, line=0, col=0)))),
        gctypes.AssignStmt(target=acc,
                           value=FLit(value=0.0, line=0, col=0),
                           line=0, col=0),
        gctypes.ForStmt(
            target='p',
            iterable=gctypes.CallExpr(func=I(name='range', line=0, col=0),
                                     args=[I(name=info.k, line=0, col=0)],
                                     line=0, col=0),
            body=[assign(acc, bin('+', acc, bin('*',
                    gctypes.SubscriptExpr(
                        obj=I(name=info.a, line=0, col=0),
                        index=bin('+', bin('*', i, I(name=info.k, line=0, col=0)), p),
                        attrs=None, line=0, col=0),
                    gctypes.SubscriptExpr(
                        obj=I(name=info.b, line=0, col=0),
                        index=bin('+', bin('*', p, I(name=info.n, line=0, col=0)), j),
                        attrs=None, line=0, col=0))))],
            else_body=None, is_async=False, line=0, col=0),
        assign(gctypes.SubscriptExpr(
            obj=I(name=info.c, line=0, col=0),
            index=bin('+', bin('*', i, I(name=info.n, line=0, col=0)), j),
            attrs=None, line=0, col=0), acc),
    ]
    return _fdef(body)


def rewrite_gemm(fdef, info: 'GemmInfo', kernel):
    """`fdef` with the whole nest replaced by a guarded call to `kernel`.

    The guard is on `m * n`, the OUTPUT element count, because that is the grid
    the dispatch will be sized from -- so it is the trip count that decides
    whether a dispatch is worth its fixed cost, exactly as the single-loop path
    guards on its own `n`.
    """
    I = gctypes.IdentExpr
    Lit = gctypes.IntLiteral

    def bin(op, l, r):
        return gctypes.BinaryOp(left=l, op=op, right=r, line=0, col=0)

    count = bin('*', I(name=info.m, line=0, col=0), I(name=info.n, line=0, col=0))
    args = [I(name=x, line=0, col=0)
            for x in (info.a, info.b, info.c, info.m, info.k, info.n)]
    call = gctypes.CallExpr(func=I(name=_as_str(kernel.name), line=0, col=0),
                            args=args, line=0, col=0)
    guarded = gctypes.IfStmt(
        condition=gctypes.CompareChain(
            operands=[count, Lit(value=_min_profitable_elements(), line=0, col=0)],
            ops=['>='], line=0, col=0),
        then_body=[gctypes.ExprStmt(value=call, line=0, col=0)],
        elifs=[],
        else_body=list(getattr(fdef, 'body', None) or ()),
        line=0, col=0)
    return gctypes.FunctionDef(
        name=_as_str(fdef.name), params=list(fdef.params or ()),
        return_type=fdef.return_type, body=[guarded],
        decorators=list(fdef.decorators or ()),
        param_convs=dict(fdef.param_convs or {}),
        param_has_default=dict(fdef.param_has_default or {}),
        param_defaults=dict(fdef.param_defaults or {}),
        kwonly=list(fdef.kwonly or ()), comptime_params=list(fdef.comptime_params or ()),
        is_generator=bool(getattr(fdef, 'is_generator', False)),
        is_async=bool(getattr(fdef, 'is_async', False)),
        line=getattr(fdef, 'line', 0), col=getattr(fdef, 'col', 0))


def offload_module(stmts: list, lengths_sink: dict | None = None,
                  grids_sink: dict | None = None) -> tuple:
    """Both halves of increment 3, over a whole module.

    Returns `(new_stmts, synthesised_kernels)`.

    For each free function whose whole body is one recognised parallel map:

      - a `@gpu` synthesised kernel is APPENDED, which seam 1 classifies as
        DEVICE and seams 2/3 turn into MSL plus a host wrapper;
      - the ORIGINAL function is REPLACED in place by a version whose loop has
        become a call to that kernel.

    Replacement rather than mutation: the synthesised kernel copies nodes out
    of the original body, so rewriting in place would change what those
    copies contain.

    The kernel is synthesised FIRST, from the untouched function, and the
    rewritten function is produced from the same `info`. The two therefore
    describe the same computation by construction rather than by agreement
    between two passes.
    """
    out: list = []
    kernels: list = []
    for s in (stmts or []):
        if not isinstance(s, gctypes.FunctionDef):
            out.append(s)
            continue
        if _decorator_names(s) & _EXPLICIT:
            out.append(s)
            continue
        info = recognise(s)
        if info is None:
            # The GEMM nest, as a FALLBACK within this same pass rather than a
            # second one. A second pass over the original statements appended
            # every statement twice -- measured, `main` appeared twice, its
            # prints vanished, and the program exited 0 printing NOTHING, which
            # is the worst possible symptom to debug. One pass, one append.
            ginfo = recognise_gemm(s)
            if ginfo is None:
                out.append(s)
                continue
            try:
                gkernel = synthesise_gemm(ginfo, tensor_cores=TENSOR_CORES)
            except (SynthesisRefused, AttributeError, TypeError):
                out.append(s)
                continue
            # The per-buffer lengths must be in place BEFORE the classification
            # pass builds the LaunchArgs, which is why this is a sink the
            # caller owns rather than something computed here and returned.
            if lengths_sink is not None:
                lengths_sink[_as_str(gkernel.name)] = dict(ginfo.lengths)
            # A tensor-core kernel needs a grid the runtime cannot infer: one
            # SIMDGROUP per 8x8 output tile. Recorded for the same reason as
            # the lengths -- BEFORE the classification pass builds the args.
            if grids_sink is not None and TENSOR_CORES:
                grids_sink[_as_str(gkernel.name)] = gemm_tensor_core_grid(ginfo)
            out.append(rewrite_gemm(s, ginfo, gkernel))
            kernels.append(gkernel)
            continue
        try:
            kernel = synthesise(s, info)
        except SynthesisRefused:
            out.append(s)
            continue
        rewritten = rewrite_to_dispatch(s, info)
        if rewritten is None:
            out.append(s)
            continue
        out.append(rewritten)
        kernels.append(kernel)

    return out, kernels
