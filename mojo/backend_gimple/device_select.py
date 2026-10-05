"""Device-region selection: which functions become MSL instead of C.

A pass over the module's ``FunctionDef``s that partitions them into HOST
(emit as C, today's path) and DEVICE (emit as MSL). It runs *before*
emission, because "emit this function to a different target" is not a
decision an emitter can make about a function it has already started.

Three selection rules, in strict priority order -- explicit always beats
inferred, because an inferred wrong answer is a silently wrong kernel:

1. **Explicit marker.** ``'gpu' in fdef.decorators``. ``decorators`` is
   already a list of strings on ``FunctionDef`` and ``module_gen.py:3631``
   already reads it for ``'export'``, so this costs nothing and is the
   thing to write when you mean it.

2. **Stdlib reachability.** A function named as the callee of
   ``DeviceContext.compile_function[...]`` / ``enqueue_function`` is a
   kernel. This is the rule that makes the *hand-written* stdlib GPU code
   work without editing it: ``stdlib/test/asyncrt/
   test_device_pointer_kernel.mojo`` defines ``vec_add`` as an ordinary
   ``def`` with no marker at all, and the test hands it to
   ``ctx.compile_function[vec_add]()``. The function carries no signal, so
   the *call* is the only honest place to find the signal.

3. **Inferred loop nests.** Deliberately NOT implemented here. Recognising
   a parallel loop nest in ordinary Python is the increment-3 transform
   and the only rule that can be wrong in a way that matters; it should be
   built on a path already proven correct when explicitly asked for. The
   hook for it is :func:`classify_functions` returning DEVICE, so adding it
   is one more rule here and no change anywhere else.

Why a separate module rather than a flag in ``gen_module_impl``: the
selection has to be queryable by the plan's Seam 3 (to know whether a
module has any device region at all, and so whether to emit the MSL
sidecar and link the runtime), and by tests, without constructing a
GimpleGen. Same reason ``mlir.py`` is pure.
"""

from __future__ import annotations

from fire_compiler import (
    CallExpr, FunctionDef, IdentExpr, MemberExpr, SubscriptExpr, StructDef,
    _as_str,
)

#: HOST — emit as C. The default for everything.
HOST = 'host'

#: DEVICE — emit as MSL, and make the host call it through a dispatch.
DEVICE = 'device'

#: Method names whose ``[...]`` index names a device kernel. Matched on the
#: member name only -- the receiver type is not always statically known
#: (``ctx`` is usually a local of inferred type), and the alternative is
#: refusing to recognise the stdlib's own idiom because of it.
KERNEL_REGISTRARS = frozenset({'compile_function', 'enqueue_function'})

#: Decorators that mark a function as a device kernel explicitly.
KERNEL_DECORATORS = frozenset({'gpu', 'kernel'})


def _callee_name_from_registrar(node) -> str | None:
    """The function a ``<recv>.compile_function[<fn>]`` / ``enqueue_function[<fn>]``
    call names, or None if this is not that shape.

    The shape is a ``CallExpr`` whose callee is a ``SubscriptExpr`` over a
    ``MemberExpr`` -- the ``[...]`` carries the kernel as an explicit type
    parameter, which is why the name is syntactically recoverable here at
    all. Deliberately tolerant about the index's own form (bare name, or a
    name wrapped in a cast) because a kernel reference is written as a
    *value* and the parser's shape for that varies.
    """
    if not isinstance(node, CallExpr):
        return None
    func = node.func
    if not isinstance(func, SubscriptExpr):
        return None
    obj = func.obj
    if not isinstance(obj, MemberExpr):
        return None
    if _as_str(obj.member) not in KERNEL_REGISTRARS:
        return None
    idx = getattr(func, 'index', None)
    # A TupleExpr index would be a generic argument list, not a kernel.
    if idx is not None and isinstance(idx, IdentExpr):
        return _as_str(idx.name)
    return None


def _walk_calls(nodes, out: list) -> None:
    """Collect every CallExpr in a statement list, at any nesting depth.

    A registration is a single expression wherever it sits -- the top level
    of a function, inside a ``with``, under an ``if`` -- so a depth-limited
    walk would miss real ones. Iterative with an explicit stack, because
    comprehension bodies nest several levels deep in real stdlib code.
    """
    stack = list(reversed(list(nodes or [])))
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if isinstance(node, CallExpr):
            out.append(node)
        for child in _child_nodes(node):
            if isinstance(child, list):
                stack.extend(reversed(child))
            else:
                stack.append(child)


def _child_nodes(node) -> list:
    """The statement/expression children of an AST node, as a flat list of
    nodes and lists-of-nodes. Generic over the node's fields so it does not
    need to know every node class -- the alternative is a per-class visitor
    that silently goes stale when ``fire_compiler`` grows a node.
    """
    out = []
    fields = getattr(node, '__dataclass_fields__', None)
    if not fields:
        return out
    for fname in fields:
        val = getattr(node, fname, None)
        if isinstance(val, list):
            out.append(val)
        elif hasattr(val, '__dataclass_fields__'):
            out.append(val)
    return out


def _registered_kernels(stmts: list) -> set[str]:
    """Names of functions passed to a kernel registrar anywhere in `stmts`.

    Scans the whole module, not just function bodies, because a
    registration can live at top level (the common case) or inside any
    function -- and a kernel is just as much a kernel when registered from
    inside a test helper.
    """
    calls: list = []
    _walk_calls(stmts, calls)
    found = set()
    for call in calls:
        nm = _callee_name_from_registrar(call)
        if nm:
            found.add(nm)
    return found


def classify_functions(stmts: list) -> dict[str, str]:
    """Map every function name in `stmts` to HOST or DEVICE.

    Includes struct methods under their qualified ``Struct_method`` key, so
    the caller can look up exactly the key the emitter will use. A method
    is DEVICE only if it carries the explicit marker: the registrar rule
    names free functions, and a method reached through one is the method's
    own business, not something to infer.
    """
    registered = _registered_kernels(stmts)

    def _classify_one(fdef) -> str:
        if _decorator_names(fdef) & KERNEL_DECORATORS:
            return DEVICE
        if _as_str(fdef.name) in registered:
            return DEVICE
        return HOST

    out: dict[str, str] = {}
    for s in stmts or []:
        if isinstance(s, FunctionDef):
            out[_as_str(s.name)] = _classify_one(s)
        elif isinstance(s, StructDef):
            for m in (getattr(s, 'methods', None) or []):
                if isinstance(m, FunctionDef):
                    out[f'{_as_str(s.name)}_{_as_str(m.name)}'] = _classify_one(m)
    return out


def _explicit_marker(fdef) -> bool:
    """True when a human marked this function `@gpu`/`@kernel`."""
    return bool(_decorator_names(fdef) & KERNEL_DECORATORS)


def _decorator_names(fdef) -> set:
    """The NAMES a function's decorators carry, as a set of strings.

    A decorator is NOT always a bare name. `@gpu` and `@kernel` are, but
    `@functools.lru_cache(maxsize=1)` is a CALL, and its
    `FunctionDef.decorators` entry is a CallExpr node -- which is
    unhashable, so the obvious `{_as_str(d) for d in decorators}` dies
    with `TypeError: cannot use 'CallExpr' as a set element`.

    That is not hypothetical: `version.py` carried
        `@functools.lru_cache(maxsize=1)` on `version()`, and it was inside
        the self-host closure, so the whole closure failed to compile with
        that TypeError and the link then failed on an undefined
        `_version_version`. Any module with a parameterized decorator hit it.

        **`version.py` no longer carries that decorator** (`formal37-2`,
        2026-10-05 — it was the file's whole `functools` dependency, and it was
        the only call-shaped decorator in `fire.py`'s import closure), so this
        branch is now covered by
        `test_metal_codegen.py::TestDeviceSelect::test_a_parameterized_decorator_is_its_callees_name`
        rather than by a real file's incidental shape. Keep that test in step
        with this arm: it is the only thing exercising the `CallExpr` line
        below.

    So: take a string entry as itself, an `IdentExpr`/`MemberExpr` as its
    attribute name, and a call as its callee's name (`lru_cache` from
    `functools.lru_cache(...)`). A parameterized `@gpu(...)` is then
    still recognised, which the bare-string form silently was not.
    """
    names: set = set()
    for d in (getattr(fdef, 'decorators', None) or []):
        if isinstance(d, str):
            names.add(d)
            continue
        if isinstance(d, (IdentExpr, MemberExpr)):
            _n = getattr(d, 'name', None) or getattr(d, 'member', None)
            if _n:
                names.add(_as_str(_n))
            continue
        if isinstance(d, CallExpr):
            _f = getattr(d, 'func', None)
            if isinstance(_f, IdentExpr) and getattr(_f, 'name', None):
                names.add(_as_str(_f.name))
            elif isinstance(_f, MemberExpr) and getattr(_f, 'member', None):
                names.add(_as_str(_f.member))
    return names


def explicitly_marked_functions(stmts: list) -> set:
    """The names a HUMAN marked `@gpu`/`@kernel`, free functions and methods.

    Distinct from `classify_functions`, which also selects by INFERENCE -- a
    function reached through `compile_function[...]` / `enqueue_function[...]`
    is a kernel even though nothing marks it. The caller needs the
    difference because the two deserve different behaviour when the MSL
    emitter cannot lower them (see `module_gen`'s DEVICE branch).
    """
    out: set = set()
    for s in stmts or []:
        if isinstance(s, FunctionDef):
            if _explicit_marker(s):
                out.add(_as_str(s.name))
        elif isinstance(s, StructDef):
            for m in (getattr(s, 'methods', None) or []):
                if isinstance(m, FunctionDef) and _explicit_marker(m):
                    out.add(f'{_as_str(s.name)}_{_as_str(m.name)}')
    return out


def device_functions(stmts: list) -> list[str]:
    """Just the DEVICE names, in declaration order. The convenience form
    most callers want; :func:`classify_functions` is for when the host
    names matter too."""
    return [n for n, kind in classify_functions(stmts).items() if kind == DEVICE]
