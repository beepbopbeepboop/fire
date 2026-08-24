"""Expression/type-inference helper layer for the GIMPLE backend (extracted M3).

Verbatim extraction of the module-level free-function region of
gimple_codegen.py covering AST walking, generator/async shape eligibility,
await/yield ctype inference, simple-expression ctype inference, and
struct/bracket-parameter annotation utilities. Bodies, comments, and
module-level constants are byte-identical to their originals.
"""
from __future__ import annotations

import re
# --- Wave-2 leaf re-imports (deduped constants + still-owned-by-codegen helpers) ---
from gimple_ctypes import (
    _C_RESERVED_FUNCS, _FORCE_RENAME_RESERVED, _split_top_level_commas,
    _used_idents_node, _CPP_CALLABLE_CTYPE, _CPP_CALLABLE_CTYPE_1ARG,
)
import dataclasses

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, BoolLiteral,
    IdentExpr, BinaryOp, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    FunctionDef, ReturnStmt,
    YieldExpr, YieldFromExpr, AwaitExpr,
)

def _walk_ast(node):
    """Recursively return a list of every AST node (statement or expression)
    reachable from `node`, generically — walks every dataclasses.field of a
    dataclass node and every element of a list/tuple, rather than a
    hand-maintained per-node-type attribute list. Used where struct-field
    inference needs to see *every* `self.x` reference regardless of which
    statement kind it's nested under (elif bodies, try/except handlers,
    finally blocks, match cases, with-bodies, ...) — the previous hand-rolled
    traversals in this file each covered only a handful of body-bearing
    attribute names and silently missed the rest, which is exactly how fields
    assigned only inside e.g. a `try:`/`except:` or `elif:` branch went
    unregistered and produced 'no member named ...' errors from the C
    compiler on the generated struct."""
    if node is None:
        return []
    if isinstance(node, (list, tuple)):
        result = []
        for item in node:
            result.extend(_walk_ast(item))
        return result
    result = [node]
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for f in dataclasses.fields(node):
            result.extend(_walk_ast(getattr(node, f.name)))
    return result


class _UnsupportedGeneratorShape(Exception):
    """Raised by GimpleGen._gen_cpp_generator_unit (and nothing else) when a
    generator FunctionDef gen_module already flagged as "worth trying" turns
    out to need something outside Milestone B's narrow C++20-coroutine
    allowlist (a statement/expression kind the .cpp emitter doesn't handle,
    a bare `yield` with no value, `return <value>` inside the body, or a
    `yield` whose value type can't be pinned to one consistent int64_t/double
    across every `yield` site). gen_module's pre-pass catches this ONE
    exception type to decide "fall back to the honest whole-module refusal
    for this function" — deliberately narrow (not a bare `except Exception`)
    so a real bug in the emitter still surfaces as a hard failure instead of
    being silently absorbed into "unsupported shape"."""


class _UnsupportedAsyncShape(_UnsupportedGeneratorShape):
    """Raised by GimpleGen._gen_cpp_async_unit (and nothing else) when an
    `async def` FunctionDef gen_module's pre-pass already flagged as "worth
    trying" (see _async_quick_eligible) turns out to need something outside
    this step's deliberately tiny allowlist: any parameter, any `await`, a
    body whose final statement isn't a `return <scalar-expr>`, or a `return`
    value whose type can't be pinned to one scalar (int64_t/double/_Bool).
    Subclasses _UnsupportedGeneratorShape (not a sibling exception) so
    gen_module's single `except _UnsupportedGeneratorShape` catch already
    used by the generator pre-pass loop also correctly catches this one if
    ever reused verbatim for async — see the dedicated async pre-pass loop's
    own catch, immediately below the generator one, for where this is
    actually caught in practice."""


def _is_asyncio_sleep_call(node) -> bool:
    """True iff `node` is the exact call shape `asyncio.sleep(<one
    positional arg, no kwargs>)` — the ONE recognized special-call shape
    Step C's codegen understands, mirroring the textual os.path.*/re.sub-
    style special-call-shape recognition convention `_lower_method_call`
    already uses elsewhere in this file (grep for "Handle os.path.* calls")
    rather than any general "call into a real Python module" mechanism —
    there isn't one for compiled code, and there shouldn't be: real
    `asyncio` doesn't exist at compiled-program runtime, only Step A's
    mojo_async_runtime scheduler does, so this is a deliberately narrow,
    purely textual/structural match on the exact source shape, not a
    resolution of `asyncio` as an actual importable module."""
    return (isinstance(node, CallExpr)
            and isinstance(node.func, MemberExpr)
            and isinstance(node.func.obj, IdentExpr)
            and node.func.obj.name == 'asyncio'
            and node.func.member == 'sleep'
            and len(node.args) == 1
            and not getattr(node, 'kwargs', None))


def _is_asyncio_sock_recv_call(node) -> bool:
    """True iff `node` is the exact call shape `asyncio.sock_recv(<one
    positional fd expr>)` — Step F's ONE recognized real-socket-I/O call
    shape, chosen after confirming (grep across myinterpreter.py and every
    stdlib test file this project's interpreter/compiled paths already
    cover) that this project has NEVER built any Mojo-level `socket` type or
    module, at either the interpreter or compiled layer — this is genuinely
    new ground, not a port of an existing Mojo-level API. Real Python's
    asyncio exposes this operation as `await loop.sock_recv(sock, nbytes)`
    (the low-level, loop-method API — see asyncio.AbstractEventLoop); this
    textually mirrors that spelling minus two things this step deliberately
    narrows away: the `loop.` receiver indirection (this file's own
    `_is_asyncio_sleep_call` precedent already elides the same kind of
    indirection — real `asyncio.sleep` needs no loop at all, but the
    convention of "textually recognize `asyncio.<op>(...)`, not a real
    resolved-module/method-lookup" is the established one this mirrors) and
    `nbytes` (fixed at exactly 1 byte — the smallest useful real transfer
    that still proves genuine reactor-driven suspension end-to-end; see
    _mojoasync_SockRecvAwaiter's docstring in gen_module for why a fixed
    1-byte transfer, not a real short-read-safe buffered `nbytes` read, is
    this step's deliberately narrow scope). `<fd expr>` is an ordinary
    already-supported scalar (int64_t) expression — a plain int literal or a
    local/param already declared in the coroutine body — exactly like
    `asyncio.sleep`'s own single scalar argument; there is no Mojo-level
    socket TYPE (`socket.socket()`) for it to come from yet, so a raw
    integer fd is this step's whole "socket handle" representation,
    mirroring how a raw fd is exactly what a real POSIX `recv(2)`/`read(2)`
    needs anyway."""
    return (isinstance(node, CallExpr)
            and isinstance(node.func, MemberExpr)
            and isinstance(node.func.obj, IdentExpr)
            and node.func.obj.name == 'asyncio'
            and node.func.member == 'sock_recv'
            and len(node.args) == 1
            and not getattr(node, 'kwargs', None))


def _async_quick_eligible(fn: FunctionDef, known_async_names=frozenset()) -> bool:
    """Cheap pre-filter before attempting the real _gen_cpp_async_unit
    translation, mirroring _generator_quick_eligible's role exactly: is_async,
    not is_generator (an `async def f(): yield x` async generator is its own
    combined-refusal category, handled entirely separately below). Step B
    required NO `await` anywhere in the body at all (proving the zero-
    suspension-point pipeline end-to-end first); Step C narrowed that rule
    instead of keeping it absolute (every `AwaitExpr` had to be the one
    recognized `asyncio.sleep(<scalar seconds>)` shape — see
    _is_asyncio_sleep_call); Step D narrows it once more: an `AwaitExpr` is
    ALSO eligible when it's a call to another `async def` this same module
    compile has ALREADY successfully compiled to the C++20-coroutine path
    (`known_async_names` — self._async_api's keys at the time of this check,
    passed by gen_module's async pre-pass loop, which runs in module source
    order — see _is_async_call_to_known_fn's docstring for the resulting
    "callee must be defined first" ordering constraint). Step H (the
    create_task/Task/TaskGroup/RaisingTask project) widens this once more:
    params ARE now allowed through this quick filter, mirroring
    _generator_quick_eligible's own identical widening for the exact same
    reason (parameters are simply ordinary by-value C++20 coroutine-frame
    locals — see _gen_cpp_async_unit's docstring for the empirical
    confirmation this is safe for async too, not just generators) — whether
    a given param's TYPE is actually compilable (scalar int64_t/double/_Bool
    only) is decided by _gen_cpp_async_unit itself, the single source of
    truth, not duplicated here. Call-WITH-arguments composition
    (`await inner(x, y)`) is correspondingly also now allowed (see
    _is_async_call_to_known_fn). Awaiting anything else (a socket operation,
    an arbitrary non-async expression) is still out of scope and correctly
    makes the whole function ineligible here, falling back to the honest
    whole-module refusal exactly as an unsupported `await` always has.
    Whether the body's actual STATEMENTS are otherwise compilable (only the
    shared _cpp_stmt/_cpp_expr whitelist, ending in one `return
    <scalar-expr>`) is decided by _gen_cpp_async_unit itself, the single
    source of truth, not duplicated here."""
    if fn.is_generator or not fn.is_async:
        return False
    for n in _walk_ast(fn.body):
        if isinstance(n, AwaitExpr):
            v = n.value
            if _is_asyncio_sleep_call(v):
                continue
            if _is_async_call_to_known_fn(v, known_async_names):
                continue
            # Step F: `await asyncio.sock_recv(<fd>)` -- the one recognized
            # real-socket-I/O shape (see _is_asyncio_sock_recv_call's
            # docstring for why this exact shape/scope was chosen).
            if _is_asyncio_sock_recv_call(v):
                continue
            # Step I (create_task/Task/TaskGroup/RaisingTask project):
            # `await create_task(<call>)`/`await create_raising_task(
            # <call>)` used directly (no intermediate `var` -- see
            # GimpleGen._cpp_expr's AwaitExpr case, the single source of
            # truth for whether the WRAPPED call itself is actually
            # compilable) and `await <call to a sibling comptime-bracket-
            # parametrized nested async def>` (a CallExpr whose `func` is a
            # SubscriptExpr, resolved against self._async_closure_api --
            # this module-level function has no `self` to check that dict
            # against, so, mirroring this whole filter's own "cheap and
            # optimistic, not a second checklist" design, both shapes are
            # let through here unconditionally; an inner call this project
            # genuinely can't compile still correctly falls back to the
            # honest whole-module refusal once _gen_cpp_async_unit actually
            # attempts it, exactly like any other not-yet-supported shape).
            if (isinstance(v, CallExpr) and isinstance(v.func, IdentExpr)
                    and v.func.name in ('create_task', 'create_raising_task')
                    and len(v.args) == 1 and not getattr(v, 'kwargs', None)):
                continue
            if (isinstance(v, CallExpr) and isinstance(v.func, SubscriptExpr)
                    and isinstance(v.func.obj, IdentExpr)):
                continue
            return False
    return True


def _generator_quick_eligible(fn: FunctionDef) -> bool:
    """Cheap pre-filter before attempting the real (and more expensive)
    _gen_cpp_generator_unit translation: is_generator, not is_async, and
    nothing in the body that this milestone explicitly excludes by design
    (try/except, with — richer generator semantics left for a later
    milestone; see the module docstring on _UnsupportedGeneratorShape for
    the rest of the narrowing, which is enforced by actually attempting the
    translation rather than duplicated here as a second hand-maintained
    checklist). Params ARE allowed through this quick filter as of the
    parameter-support step — whether a given param's TYPE is actually
    compilable (scalar int64_t/double/_Bool only; *args/**kwargs and
    string/pointer params are refused) is decided by
    _gen_cpp_generator_unit itself, the single source of truth, not
    duplicated here.

    `yield from` is ALSO allowed through this quick filter as of the
    yield-from-delegation step — whether a given `yield from` actually
    targets a plain call to another generator this same compile already
    supports (the only delegation shape this step handles; delegating to a
    list/other iterable, to an unsupported-shape generator, or to a call
    qualified by a module/attribute access, are all still refused) is,
    again, decided by _cpp_stmt/_gen_cpp_generator_unit — the single source
    of truth — not duplicated here as a second checklist.

    `try`/`except`/`raise` are ALSO allowed through this quick filter as of
    Milestone D (real C++ exceptions confined to the generator's own .cpp
    translation unit, translated to the existing mojo_exc_type/msg/obj
    global state only at the extern "C" `_resume` boundary — see
    _cpp_try_stmt/_cpp_raise_stmt). `with` is also allowed as of Phase 3,
    implemented via __enter__/__exit__ calls in _cpp_with_stmt."""
    if fn.is_async or not fn.is_generator:
        return False
    return True


def _async_gen_quick_eligible(fn: FunctionDef, known_async_names=frozenset()) -> bool:
    """Cheap pre-filter for the final step of the async/await codegen
    project: `async def f(): ... yield ... ...` (is_async AND is_generator
    both true).

    Parameters ARE supported (see bugs/hard/
    CODEGEN_async_gen_params_silent_regression.md for the full history).
    Phase 7 (commit 1b736d7) first taught `_gen_cpp_async_generator_unit`
    to emit a real parametrized C++ signature, but the ONLY real
    consumption path -- `_cpp_async_for_stmt` (`async for x in f(<args>):`)
    -- was never updated in that same commit to thread call-site arguments
    through, so this gate was temporarily restored to `if fn.params: return
    False` as a safety net (an honest front-door refusal beats letting
    invalid C++ reach g++, or a same-shape correct call get refused via the
    generic whole-module fallback). The follow-up fix landed
    `_cpp_async_for_stmt` support for real positional arguments (threaded
    into `{base}_impl(...)` exactly like the sibling `AwaitExpr`
    async-awaits-async composition call site, PLUS an argument-count
    validation against `api['params']` that sibling site doesn't itself do
    -- see that method's own docstring), so this gate no longer needs to
    exclude `fn.params` at all: any real mismatch between a call site's
    argument count and this generator's own parameter count is now caught
    by `_cpp_async_for_stmt` itself, with a clear, specific
    `_UnsupportedAsyncShape` message, not by refusing every parametrized
    async generator here regardless of how it's actually called. no `yield
    from` (delegation composed with async suspension is genuinely new risk
    this step doesn't take on), `with` still excluded (same reason
    `_generator_quick_eligible` excludes it). Every `await` must be one of
    the same recognized shapes `_async_quick_eligible` already accepts
    (asyncio.sleep, a bare call to an already-compiled plain async
    function, asyncio.sock_recv) -- an async generator awaiting ANOTHER
    async generator is out of scope this step (composed `async for`-of-
    `async for` isn't this step's target shape); try/except/raise ARE
    allowed through (Milestone D's exception machinery, reused verbatim by
    this step's promise -- see `_gen_cpp_async_generator_unit`)."""
    if not (fn.is_async and fn.is_generator):
        return False
    for n in _walk_ast(fn.body):
        if isinstance(n, YieldFromExpr):
            return False
        if isinstance(n, AwaitExpr):
            if _is_asyncio_sleep_call(n.value):
                continue
            if _is_async_call_to_known_fn(n.value, known_async_names):
                continue
            if _is_asyncio_sock_recv_call(n.value):
                continue
            return False
    return True


def _await_call_ctype(e: 'AwaitExpr', async_api: dict | None,
                       closure_api: dict | None = None) -> str | None:
    """Resolves `await <call>`'s contributed scalar type when `<call>` is a
    bare, no-argument call to ANOTHER async function this same module
    compile has already itself lowered to the C++20-coroutine path
    (`async_api`, threaded from self._async_api) — Step D (async-awaits-
    async composition). Mirrors _yield_from_delegate_ctype's identical role
    for `yield from <call>` exactly (same "resolve via the sibling API
    dict, None if unresolvable" shape), not a fresh pattern. `await
    asyncio.sleep(...)` deliberately is NOT resolved here — it contributes
    no value (real Python: None) and is only ever reachable as a bare
    statement via GimpleGen._cpp_stmt's own AwaitExpr case, never as a
    value-producing sub-expression — so a caller that reaches this helper
    with a sleep-shaped `e.value` still correctly falls through to None
    (unsupported) below, exactly like any other unresolvable shape."""
    call = e.value
    # Step F: `await asyncio.sock_recv(<fd>)` always contributes int64_t (a
    # byte value 0-255, or -1/-2 for EOF/error -- see
    # _mojoasync_SockRecvAwaiter's docstring in gen_module). Checked before
    # the IdentExpr-only known-async-fn shape below since sock_recv's
    # `call.func` is a MemberExpr (`asyncio.sock_recv`), not an IdentExpr.
    if _is_asyncio_sock_recv_call(call):
        return 'int64_t'
    # Step I (create_task/Task/TaskGroup/RaisingTask project): `await
    # create_task(<call>)`/`await create_raising_task(<call>)` contributes
    # the SAME type as awaiting `<call>` directly -- see GimpleGen._cpp_expr
    # AwaitExpr case's identical unwrap for the full equivalence rationale.
    if (isinstance(call, CallExpr) and isinstance(call.func, IdentExpr)
            and call.func.name in ('create_task', 'create_raising_task')
            and len(call.args) == 1 and not getattr(call, 'kwargs', None)):
        call = call.args[0]
    if not isinstance(call, CallExpr):
        return None
    if getattr(call, 'kwargs', None):
        return None
    if isinstance(call.func, IdentExpr):
        if async_api is None:
            return None
        # Step H: call-WITH-arguments composition is now allowed (see
        # _is_async_call_to_known_fn) -- the callee's return type doesn't
        # depend on how many arguments were passed, so no argument-count
        # check is needed here beyond what _is_async_call_to_known_fn
        # already enforces (kwargs are still refused there).
        api = async_api.get(call.func.name)
        return api.get('value_ctype') if api else None
    # Step I: `await <call to a sibling comptime-bracket-parametrized nested
    # async def>` (test_asyncrt.mojo's `test_asyncrt_add[1](a)`, `return_
    # value[1]()`) -- resolved via `closure_api`, a plain name -> api dict
    # ALREADY scoped to the current enclosing top-level function (built by
    # the caller from self._async_closure_api -- see _gen_cpp_async_unit's
    # own call site), mirroring `async_api`'s identical bare-name-keyed
    # shape so this function doesn't need the (enclosing, name) tuple key
    # or any `self` access itself.
    if (isinstance(call.func, SubscriptExpr) and isinstance(call.func.obj, IdentExpr)
            and closure_api is not None):
        api = closure_api.get(call.func.obj.name)
        if api is None or not api.get('comptime_params'):
            return None
        idx = call.func.index
        elems = idx.elements if isinstance(idx, TupleExpr) else [idx]
        if len(elems) != len(api['comptime_params']):
            return None
        return api.get('value_ctype')
    return None


def _is_async_call_to_known_fn(node, known_async_names) -> bool:
    """True iff `node` is a call `g(...)` where `g` names ANOTHER `async
    def` this same module compile has already successfully lowered to the
    C++20-coroutine path (registered by name in `known_async_names` —
    self._async_api's keys at the time this is checked, threaded through by
    both _async_quick_eligible's caller and GimpleGen._cpp_expr's own
    AwaitExpr case). This makes async-awaits-async composition source-
    order-dependent: the callee must be DEFINED (and have already compiled
    successfully) before the caller in the module's own top-level statement
    order — gen_module's single forward pass over `stmts` (see the Step B/C
    compile-attempt loop this reuses verbatim) never builds a two-pass/
    topological ordering, so a forward reference (caller textually before
    its not-yet-registered callee) correctly falls back to the honest
    whole-module refusal, exactly like any other not-yet-supported shape,
    instead of ever emitting a dangling/forward C++ type reference.

    Step H (create_task/Task/TaskGroup/RaisingTask project) widens this
    from Step D's original argument-LESS-only shape to allow real
    positional arguments (`await inner(x, y)`) — the callee's own
    parameters are now compiled as ordinary C++20 coroutine-frame locals
    (see _gen_cpp_async_unit's Step H parameter-support addition), so the
    caller just needs to pass the same argument expressions through to
    `{callee_base}_impl(...)` at the composition call site (see
    GimpleGen._cpp_expr's AwaitExpr case). Keyword arguments are still
    refused here (this codegen's scalar-arg call convention throughout this
    file is positional-only; no keyword-arg support exists for ANY call
    shape here, not just this one)."""
    return (isinstance(node, CallExpr)
            and isinstance(node.func, IdentExpr)
            and node.func.name in known_async_names
            and not getattr(node, 'kwargs', None))


def _local_literal_ctype(value) -> str | None:
    """The REAL declared C type `_gen_stmt_VarDecl` gives an unannotated
    `var name = <value>` whose `value` is a bare literal -- mirrors
    `GimpleGen._lower_IntLiteral`/`_lower_FloatLiteral`/`_lower_BoolLiteral`'s
    own exact rules (a SMALL int literal lowers to plain C `int`, NOT
    `int64_t` -- unlike this file's other two "guess a scalar type"
    estimators, `_quick_type`/`_infer_simple_expr_ctype`, which both assume
    `int64_t` for any integer literal and disagree with the real lowering)
    rather than reusing either of those broader, already-established-
    elsewhere estimators and risking the same disagreement `_enclosing_
    scope_with_locals`'s own docstring describes hitting the hard way.
    Deliberately narrow: only the three literal kinds `_gen_stmt_VarDecl`
    actually special-cases via a bare lowered literal are recognized here;
    anything else returns None (not a guess)."""
    if isinstance(value, IntLiteral):
        return 'uint64_t' if value.value > 0x7FFFFFFFFFFFFFFF else 'int'
    if isinstance(value, FloatLiteral):
        return 'double'
    if isinstance(value, BoolLiteral):
        return '_Bool'
    return None


def _receiver_key(e) -> str | None:
    """Stable string identity for a "receiver" sub-expression whose STORED
    per-name type info (`dict_val_types`, below) was recorded under that
    same identity — a bare local/param name (`d`), or `self.<field>`
    (`self.d`). Anything else (a nested attribute chain, a subscript, a
    call result used as a receiver, ...) has no such stored identity and
    returns None — used by `_infer_simple_expr_ctype`'s dict-`.get()`
    struct-pointer-yield case (below) to look a receiver up in
    `dict_val_types` the exact same way `self.<field>` reads are already
    looked up in `self_fields`, not a new convention."""
    if isinstance(e, IdentExpr):
        return e.name
    if isinstance(e, MemberExpr) and isinstance(e.obj, IdentExpr) and e.obj.name == 'self':
        return 'self.' + e.member
    if isinstance(e, MemberExpr) and isinstance(e.obj, IdentExpr) and e.obj.name == 'cls':
        # `cls.<class-attr>` — the class-level analogue of `self.<field>`
        # just above, for a @classmethod generator (e.g. Lib/enum.py's
        # `Flag._iter_member_by_value_`: `cls._value2member_map_.get(val)`).
        # See `_gen_cpp_generator_unit`'s `_dict_val_types` construction,
        # which seeds a matching `'cls.' + attr` key from
        # `self._class_attrs`/`self._global_dict_val_types` for exactly
        # this receiver shape.
        return 'cls.' + e.member
    return None


def _is_known_struct_ptr_ctype(ctype, known_structs) -> bool:
    """True iff `ctype` is a real pointer-to-a-known-struct C type (e.g.
    'Flag *') rather than one of this file's scalar/container ctypes or an
    arbitrary/unvalidated pointer-ish string — `known_structs` (a set of
    struct names this compile actually has a layout for, e.g.
    `self.struct_field_types.keys()`) is the single source of truth this
    checks against, mirroring `_gen_cpp_generator_unit`'s own identical
    `ctype.endswith(' *') and ctype[:-2] in self.struct_field_types` check
    for a struct-typed generator PARAMETER — reused here rather than
    re-deriving a second notion of "is this really a struct pointer"."""
    return (known_structs is not None and isinstance(ctype, str)
            and ctype.endswith(' *') and ctype[:-2] in known_structs)


def _infer_simple_expr_ctype(e, known: dict | None = None,
                              self_fields: dict | None = None,
                              async_api: dict | None = None,
                              closure_api: dict | None = None,
                              known_structs: frozenset | None = None,
                              dict_val_types: dict | None = None,
                              method_return_types: dict | None = None,
                              fn_return_types: dict | None = None) -> str | None:
    """Best-effort scalar C++ type of a narrow-generator-body expression —
    used both to pick each first-assigned local's declared type and to infer
    a generator's single yielded-value type. Deliberately conservative:
    returns None (== "don't know, refuse this shape") rather than guessing,
    for anything beyond plain int/float/bool literals, a bare identifier
    (looked up in `known` — a name -> ctype map of the generator's own
    parameters and/or already-declared locals, threaded through by both
    call sites so a parameter/local's REAL scalar type is used instead of
    always guessing int64_t; falls back to the int64_t default, matching
    this codegen's own untyped-local default — see _param_ctype's identical
    default elsewhere in this file — for any name not in `known`, e.g. a
    module-level global), a `self.<field>` attribute read (generator
    METHODS only — `self_fields`, non-None exactly when this is a generator
    method, is a name -> ctype map of the enclosing struct's OWN fields;
    resolves to None, not a guess, for a field whose real type isn't scalar
    or a known struct pointer, and for a bare `self` with no `.field` at all
    — self is never itself a scalar value, unlike an ordinary
    parameter/local, so it must NOT fall through to the int64_t default
    below), or +-*/ arithmetic/unary ops over those.

    `known_structs`/`dict_val_types`/`method_return_types` (all optional,
    default None — every EXISTING caller that doesn't pass them keeps this
    function's original scalar-only behavior unchanged) widen this beyond
    pure scalars to also recognize a real STRUCT POINTER value, the same
    "this generator yields/returns a genuine pointer, not a scalar" category
    a bare struct-typed parameter/local already gets via `known` — see the
    CallExpr/MemberExpr branch below for the two shapes this covers: a dict
    `.get()` call whose stored value type (`dict_val_types`) is a known
    struct pointer, and an arbitrary struct METHOD call chain whose return
    type (`method_return_types` — this file's own existing
    `self.func_return_types`, keyed `f"{struct_name}_{method_name}"` exactly
    like every other compiled struct-method call site already resolves it)
    is one. Reuses this codegen's ALREADY-established per-struct dict-value-
    type/method-return-type registries rather than inventing new tracking —
    see CODEGEN_generator_function_Lib_enum.md's 2026-08-20 update."""
    if isinstance(e, IntLiteral):
        return 'int64_t'
    if isinstance(e, FloatLiteral):
        return 'double'
    if isinstance(e, BoolLiteral):
        return '_Bool'
    if isinstance(e, StringLiteral):
        return 'char *'
    if isinstance(e, MemberExpr) and isinstance(e.obj, IdentExpr) and e.obj.name == 'self':
        if self_fields is None:
            return None
        ft = self_fields.get(e.member)
        if ft in ('int64_t', 'double', '_Bool', 'char *'):
            return ft
        if _is_known_struct_ptr_ctype(ft, known_structs):
            return ft
        return None
    if isinstance(e, IdentExpr):
        if e.name in ('None', 'True', 'False'):
            return 'int64_t'
        if self_fields is not None and e.name == 'self':
            return None
        if known is not None and e.name in known:
            return known[e.name]
        return 'int64_t'
    if isinstance(e, UnaryOp):
        return _infer_simple_expr_ctype(e.operand, known, self_fields, async_api, closure_api, fn_return_types=fn_return_types)
    if isinstance(e, TernaryExpr):
        ct = _infer_simple_expr_ctype(e.condition, known, self_fields, async_api, closure_api, fn_return_types=fn_return_types)
        tt = _infer_simple_expr_ctype(e.then_val, known, self_fields, async_api, closure_api, fn_return_types=fn_return_types)
        et = _infer_simple_expr_ctype(e.else_val, known, self_fields, async_api, closure_api, fn_return_types=fn_return_types)
        if tt is not None: return tt
        if et is not None: return et
        return 'int64_t'
    if isinstance(e, BinaryOp):
        lt = _infer_simple_expr_ctype(e.left, known, self_fields, async_api, closure_api, fn_return_types=fn_return_types)
        rt = _infer_simple_expr_ctype(e.right, known, self_fields, async_api, closure_api, fn_return_types=fn_return_types)
        if lt is None or rt is None:
            return None
        if 'char *' in (lt, rt):
            return 'char *'
        if 'double' in (lt, rt):
            return 'double'
        return 'int64_t'
    if isinstance(e, CallExpr) and isinstance(e.func, IdentExpr):
        if e.func.name in ('str', 'repr', 'os.path.join', 'os.path.basename',
                           'os.path.dirname', 'os.path.splitext'):
            return 'char *'
        # `len()`/`ord()` always return a plain int regardless of their
        # argument's type — unlike every other builtin call, their result
        # type needs no argument-type inspection at all, so they're safe to
        # recognize unconditionally here (narrow fix — see
        # bugs/COMPILE_FAIL_Apple___main__.md: Apple/__main__.py's `group()`
        # generator has `print(f"..." + "=" * (70 - len(text)))`; the
        # nested `len(text)` fell through this whole function to the `None`
        # "don't know" default, which poisoned the enclosing `-`/`*`/`+`
        # BinaryOp chain to `None` too, and the print()-argument-type check
        # in `_cpp_stmt` treats `None` as "not a scalar, refuse the whole
        # generator" — even though the actual runtime value is an ordinary
        # char* string).
        if e.func.name in ('len', 'ord'):
            return 'int64_t'
        # `sorted(iterable, ...)` always returns a real list (a `MojoList
        # *` in this codegen's own container representation), regardless of
        # the iterable's own type or an accompanying `key=`/`reverse=`
        # kwarg — see the matching `_cpp_expr` CallExpr/'sorted' case's new
        # inline-sort codegen below, added alongside the 1-arg-lambda `key=`
        # support (bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md).
        if e.func.name == 'sorted' and e.args:
            return 'MojoList *'
        if known is not None and e.func.name in known:
            # A call through a declared CALLABLE-VALUE local (`getpos()`,
            # where `getpos`'s own storage type is `_CPP_CALLABLE_CTYPE` —
            # see that constant's docstring) always RETURNS int64_t (its
            # fixed signature), never the callable's own storage type —
            # unlike the general case just below, where `known[name]`
            # doubles as "this name is a callable local; its call result
            # has this SAME scalar type" (the tokenize.py `encode =
            # detect_encoding` idiom, where the boxed-function-pointer
            # local's own int64_t storage type and its call's real
            # (also-int64_t) result happen to coincide). Checked first so
            # that coincidence doesn't misfire for the callable category.
            if known[e.func.name] == _CPP_CALLABLE_CTYPE:
                return 'int64_t'
            return known[e.func.name]
        # A call to a MODULE-LEVEL function whose inferred return ctype is
        # a real pointer-shaped value (`char *`/`MojoList *`/...): the
        # assigned local must carry that same type, not the int64_t
        # default — otherwise `fallback_framework_path =
        # dyld_fallback_framework_path(env)` (dyld.py's generator body)
        # declared the local int64_t while the callee's extern (and the
        # .c side's real definition) return MojoList*, producing an
        # invalid-C++ pointer-to-int assignment and a bogus "range
        # expression of type 'int64_t'" at the later for-loop over it.
        # ONLY pointer-shaped entries are trusted: an int64_t entry is
        # indistinguishable from "no information" (the default), so
        # consulting it could never change anything anyway. `None` when
        # not threaded (every existing caller keeps its exact prior
        # behavior).
        if fn_return_types is not None:
            _frt = fn_return_types.get(e.func.name)
            if isinstance(_frt, str) and (
                    _frt in ('char *', 'MojoList *', 'MojoDict *', 'MojoSet *')
                    or (_frt.endswith(' *') and known_structs is not None
                        and _frt[:-2] in known_structs)):
                return _frt
    if isinstance(e, CallExpr) and isinstance(e.func, MemberExpr):
        # Module-attribute call type inference: os.path.join → char* (the
        # GIMPLE path's `os.path.*` handling types these as char*), math
        # isnan/isinf/isfinite → _Bool. Without this, a local assigned from
        # one in a generator body defaulted to int64_t and a later use as a
        # string (yield, concat, subscript) emitted invalid C++.
        if (isinstance(e.func.obj, MemberExpr)
                and isinstance(e.func.obj.obj, IdentExpr)
                and e.func.obj.obj.name == 'os' and e.func.obj.member == 'path'):
            if e.func.member in ('join', 'basename', 'dirname', 'split', 'splitext',
                                 'normpath', 'abspath', 'realpath'):
                return 'char *'
        if isinstance(e.func.obj, IdentExpr) and e.func.obj.name == 'math':
            if e.func.member in ('isnan', 'isinf', 'isfinite', 'isclose'):
                return '_Bool'
            if e.func.member in ('floor', 'ceil', 'fabs', 'sqrt', 'log', 'log10',
                                 'exp', 'sin', 'cos', 'tan', 'fsum'):
                return 'double'
        # `.format(...)` on a string literal (e.g. compileall.py's        # `print('Listing {!r}...'.format(dir))`) — mirrored from the
        # ordinary GIMPLE path's identical `_lower_string_method_call`
        # stub, which types `.format()`/`.encode()`/`.decode()` as
        # char* (see _stub_result's docstring: a diagnosed stub, not a
        # silent wrong answer). Without this, the print() argument-type
        # check above would refuse the whole generator.
        if e.func.member == 'format':
            return 'char *'
        # `<str>.replace(old, new)` — mirrors `_cpp_expr`'s CallExpr/
        # MemberExpr `.replace(...)` case (routes through the same
        # `_char_replace_impl` runtime helper, always returns `char *`):
        # without a matching entry here, a first-assigned local like
        # `method_suffix = name.replace('.', '_')` (save_env.py's
        # `resource_info`) defaulted to the int64_t fallback below, so a
        # LATER string-concat use of `method_suffix` (`'get_' +
        # method_suffix`) missed the `_is_str_operand` check in `_cpp_expr`'s
        # BinaryOp case (which reads THIS same `known`/`declared` map) and
        # emitted a raw, invalid C++ `+` instead of `mojo_str_cat`.
        if e.func.member == 'replace' and len(e.args) == 2:
            return 'char *'
        # `<dict>.get(key)` / `<dict>.get(key, default)` where `<dict>` is a
        # bare local/param or `self.<field>` whose STORED dict value type
        # (`dict_val_types` — the enclosing struct's per-field dict-value-
        # type registry, `self._field_dict_val_types`, threaded through
        # exactly like `self_fields` already is, NOT a fresh tracking
        # mechanism) is a known struct pointer. Real: Lib/enum.py's
        # `Flag._iter_member_by_value_`: `cls._value2member_map_.get(val)`
        # returns a `Flag *` (an enum-member reference), not a scalar — see
        # CODEGEN_generator_function_Lib_enum.md's 2026-08-20 update for the
        # full root-cause history (this was previously silently defaulting
        # to int64_t, a genuine miscompile risk this recognizes instead of
        # guessing).
        if e.func.member == 'get' and len(e.args) in (1, 2) and dict_val_types is not None:
            key = _receiver_key(e.func.obj)
            if key is not None and key in dict_val_types:
                vt = dict_val_types[key]
                if vt in ('int64_t', 'double', '_Bool', 'char *'):
                    return vt
                if _is_known_struct_ptr_ctype(vt, known_structs):
                    return vt
        # General case: an arbitrary `<receiver>.<method>(...)` call where
        # `<receiver>` itself resolves (recursively, via this SAME function
        # — a bare struct-typed local/param via `known`, or a `self.<field>`
        # struct-pointer field via the branch above) to a known struct
        # pointer type. Its return type is resolved via
        # `method_return_types` — this file's OWN existing
        # `self.func_return_types`, keyed `f"{struct_name}_{method_name}"`
        # exactly like every other compiled struct-method CALL site already
        # resolves it (see e.g. the ordinary CallExpr/MemberExpr lowering's
        # identical `f'{struct_name}_{method}' in self.func_return_types`
        # lookup) — reused here, not a second/parallel resolution scheme.
        if (method_return_types is not None and not getattr(e, 'kwargs', None)
                and e.func.member != 'get'):
            recv_ctype = _infer_simple_expr_ctype(
                e.func.obj, known, self_fields, async_api, closure_api,
                known_structs, dict_val_types, method_return_types)
            if _is_known_struct_ptr_ctype(recv_ctype, known_structs):
                rt = method_return_types.get(f"{recv_ctype[:-2]}_{e.func.member}")
                if rt in ('int64_t', 'double', '_Bool', 'char *'):
                    return rt
                if _is_known_struct_ptr_ctype(rt, known_structs):
                    return rt
    if isinstance(e, (ListExpr, DictExpr, SetExpr)):
        # A list/dict/set LITERAL used as a plain local's RHS (`lines =
        # []`, `entry = {}` — ftplib.py's `FTP.mlsd`, and the single most
        # common accumulator idiom in real stdlib generator bodies): this
        # is a genuine container value, not an unknown scalar. Returning
        # the real container pointer type here lets _cpp_stmt's AssignStmt
        # case declare the local with it AND emit a real runtime
        # construction (`mojo_list_new()`/`mojo_dict_new()`), instead of
        # declaring `int64_t` while assigning the raw C++ brace-init text
        # `_cpp_expr`'s literal cases produce ("request for member 'append'
        # in 'lines', which is of non-class type 'int64_t'" at the first
        # later `.append`). Must stay consistent with those two emission
        # sites — see gimple_cpp_core.py's AssignStmt container branch.
        return ('MojoList *' if isinstance(e, ListExpr)
                else 'MojoDict *' if isinstance(e, DictExpr) else 'MojoSet *')
    if isinstance(e, Comprehension):
        # A list/dict/set comprehension used as a plain local's RHS
        # (`items = [x for x in ... ]`, as opposed to the already-handled
        # "comprehension is the DIRECT RHS of a list/tuple-unpack target"
        # shape in _cpp_stmt's AssignStmt case) — _cpp_expr's own
        # Comprehension case (just above in this file) always lowers to a
        # genuine `mojo_list_new ()` call, i.e. a real `MojoList *` value
        # (an honest always-empty-collection stub, not a real loop
        # translation — see that case's own comment), never a scalar.
        # Before this, a first-assigned local's type fell through to the
        # int64_t default below, so `_cpp_stmt` declared it `int64_t` while
        # actually assigning it a `MojoList *` — g++: "invalid conversion
        # from 'MojoList*' to 'int64_t' [-fpermissive]", plus a second,
        # equally invalid `int64_t[int]` subscript error at any later
        # `items[i]`/unpack use. Mirrors the identical, already-fixed gap
        # in the separate main-path return-type estimator, `_quick_type`
        # (task #145, bugs/hard/CODEGEN_comprehension_return_type_
        # defaults_int64.md) — this is the same root cause recurring in
        # this file's OTHER, narrower type estimator.
        return 'MojoList *'
    if isinstance(e, SliceExpr):
        return 'char *'  # string slice produces a string
    if isinstance(e, SubscriptExpr):
        # A declared MojoList*/MojoDict* subject (`d[0]` where `d` is a
        # known container, not a string) reads via the real runtime getter
        # (mojo_list_get_int/mojo_dict_get_int -- see _cpp_expr's own
        # SubscriptExpr case, the single source of truth for the actual
        # emission this type must agree with) and produces int64_t, NOT a
        # string -- this narrow model has no per-container element-type
        # tracking (mirrors the tuple-unpack branch's own `mojo_list_get_
        # int` "assume int64_t" convention), but it must NOT still default
        # to the char*-subscript guess below, which is only valid for a
        # genuine string subject. Without this, a generator that both
        # reads and yields `d[0]` (`known` here is threaded from
        # _generator_yield_ctype, which also gets `self._cpp_declared` at
        # the SEPARATE point _cpp_expr's own read-side fix already
        # believes `d[0]` is int64_t) had these two independent estimators
        # DISAGREE -- the promise's `yield_value(char * v)` parameter type
        # this function drove, fed a genuine int64_t argument by _cpp_
        # expr's own runtime-getter call, a real g++ type-mismatch error.
        # See CODEGEN_generator_non_plain_assignment_target_refused.md's
        # 2026-08-19 update.
        if known is not None and isinstance(e.obj, IdentExpr) \
                and known.get(e.obj.name) in ('MojoList *', 'MojoDict *'):
            return 'int64_t'
        return 'char *'  # string subscript produces a char (string of len 1)
    if isinstance(e, AwaitExpr):
        # Step D (async-awaits-async composition): `await <call to another
        # compiled async function>` used as a value-producing sub-expression
        # (e.g. `x = await inner()`) — see _await_call_ctype's docstring.
        return _await_call_ctype(e, async_api, closure_api)
    return None


# The coroutine-body ("C++20 generator") codegen's ONE declared-type
# category for a CALLABLE value -- a local first assigned a zero-argument
# `lambda` literal or a bound-method-as-VALUE read (`self.<method>` /
# `<struct-pointer local>.<method>`, not immediately called), later invoked
# as a plain `name()`. See bugs/hard/CODEGEN_generator_lambda_expr_
# unsupported.md's own "(1)(2)(3)" minimal-design list -- this is (1).
#
# `std::function<int64_t()>`, not `MojoBoundMethod *` (the ordinary
# non-coroutine GIMPLE path's own bound-method-as-value representation,
# `_lower_bound_method_value`/mojo_runtime.h): a real capturing C++ lambda

def _c_to_cpp_scalar_type(ctype: str) -> str:
    """'_Bool' is a valid C99 type but NOT a valid C++ type name (`bool` is)
    — used wherever a scalar ctype from _infer_simple_expr_ctype/
    _generator_yield_ctype needs to appear INSIDE the .cpp text (local var
    decls, the promise's current_value field, yield_value's parameter, the
    `<base>_value` C++ return type). The .c-side extern declaration for
    `<base>_value` keeps the original '_Bool' — see gen_module's preamble
    emission — since that side genuinely is C and bool/_Bool are ABI-
    identical there (1-byte, same representation), only the SPELLING needs
    to differ per language."""
    if ctype == '_Bool': return 'bool'
    if ctype == 'char *': return 'char *'
    return ctype


def _yield_from_delegate_ctype(n: 'YieldFromExpr', generator_api: dict | None) -> str | None:
    """The C type a `yield from <expr>` site contributes to its enclosing
    generator's overall yield-value type, for _generator_yield_ctype's
    same-type-everywhere check — None if `<expr>` isn't a bare call to a
    plain name (e.g. `yield from [1, 2, 3]`, `yield from mod.gen()`) or that
    name isn't (yet — see the source-order note on the yield-from-delegation
    step) a generator this same compile has already itself compiled via the
    C++20-coroutine path (`generator_api`, threaded through from
    self._generator_api by _gen_cpp_generator_unit/_generator_yield_ctype's
    caller). Delegating to anything else remains out of this step's scope
    and is refused here, at the same single-source-of-truth chokepoint as
    every other unsupported generator-body shape."""
    call = n.value
    # yield from over a plain collection: infer element type from the
    # first element (int64_t default if unknown)
    if isinstance(call, (ListExpr, TupleExpr)):
        if call.elements:
            et = _infer_simple_expr_ctype(call.elements[0])
            return et if et is not None else 'int64_t'
        return 'int64_t'
    # yield from itertools.repeat(value, times) (the finite 2-arg form):
    # contributes VALUE's own type, e.g. the `0` in Lib/calendar.py's
    # `yield from repeat(0, days_before)` — an int64_t, which must agree
    # with that same generator's other yield sites (`yield from range(...)`
    # also contributes int64_t). Checked before the generator_api/None
    # check below since this shape needs no generator_api lookup at all.
    if isinstance(call, CallExpr) and _is_itertools_repeat2_call(call):
        et = _infer_simple_expr_ctype(call.args[0])
        return et if et is not None else 'int64_t'
    # yield from range(...): always yields plain integers, regardless of
    # arg count/type — same builtin `range()` `_cpp_for_stmt`'s own
    # (non-`yield from`) indexed-loop special case already recognizes.
    # Needed alongside the `repeat` case just above: Lib/calendar.py's
    # `Calendar.itermonthdays` does `yield from repeat(0, days_before)` /
    # `yield from range(1, ndays + 1)` / `yield from repeat(0, days_after)`
    # in the SAME generator, all of which must agree on one promise type
    # — without this case, `range(...)`'s yield-from fell to the generic
    # "anything else -> char *" default below, clobbering the whole
    # function's promise type to char* even though every site here is
    # actually an int, which used to be silently masked by `repeat` itself
    # raising _UnsupportedGeneratorShape first (via the undeclared-symbol
    # compile failure) before this mismatch was ever reached.
    if (isinstance(call, CallExpr) and isinstance(call.func, IdentExpr)
            and call.func.name == 'range' and not call.kwargs
            and len(call.args) in (1, 2, 3)):
        return 'int64_t'
    # yield from sorted(<inner>, key=..., reverse=...): the emitted sort
    # codegen (`_cpp_expr`'s CallExpr/'sorted' case) ALWAYS materializes
    # its result as an int64_t-payload MojoList (`mojo_list_append_int`,
    # even for a struct-pointer element — the same "store a struct pointer
    # as a boxed int64_t, cast back on read" convention this codegen
    # already uses everywhere else, e.g. the `for x in self.<field>:`
    # struct-pointer-element loop case), so its OWN contributed type is
    # never char* — regardless of what the INNER iterable's element type
    # actually is. Recurse into the inner iterable using this same
    # dispatch (so `yield from sorted(range(...), key=...)` still
    # correctly contributes int64_t, `yield from sorted(<known-generator-
    # call>(...), key=...)` still contributes that generator's own real
    # value_ctype, etc.) — falling back to int64_t, NOT the generic
    # char* default below, when the inner iterable's type genuinely can't
    # be determined, since int64_t is what THIS list is actually storing
    # either way. Without this case, `yield from sorted(...)` fell into
    # the generic "char*" default and `_cpp_yield_from`'s consumer read
    # every element back via `mojo_list_get_str` on what's actually an
    # int64_t (or boxed-struct-pointer) payload — a real, confirmed
    # segfault (garbage char* dereference), not just a wrong-value bug.
    if (isinstance(call, CallExpr) and isinstance(call.func, IdentExpr)
            and call.func.name == 'sorted' and call.args):
        _inner = call.args[0]
        _inner_yf = YieldFromExpr(value=_inner) if not isinstance(_inner, YieldFromExpr) else _inner
        _inner_ctype = _yield_from_delegate_ctype(_inner_yf, generator_api)
        return _inner_ctype if _inner_ctype not in (None, 'char *') else 'int64_t'
    if generator_api is None:
        return None
    # yield from over a known compiled generator call: use its value type
    if isinstance(call, CallExpr) and isinstance(call.func, IdentExpr):
        api = generator_api.get(call.func.name)
        if api is not None:
            return api.get('value_ctype')
    # yield from over anything else (a method call, a bare name, a
    # non-generator function call returning a collection): the yielded
    # values are strings (char*).
    return 'char *'


def _is_itertools_repeat2_call(call: 'CallExpr') -> bool:
    """True for the FINITE 2-argument form of `itertools.repeat(value,
    times)` — either bare `repeat(value, times)` (the common shape after
    `from itertools import repeat`, e.g. Lib/calendar.py's
    `Calendar.itermonthdays`: `yield from repeat(0, days_before)`) or the
    qualified `itertools.repeat(value, times)` form, with exactly 2
    positional arguments and no keyword arguments. The 1-argument INFINITE
    form (`repeat(value)`, no `times` — yields forever) is a different,
    harder shape (would need a `while (true)` loop) and is deliberately
    NOT matched here; callers fall through to whatever generic handling
    they already have for it. Shared by `_yield_from_delegate_ctype` (type
    inference for `yield from repeat(...)`), `GimpleGen._cpp_yield_from`
    (emission for the same), and `GimpleGen._cpp_for_stmt` (the analogous
    plain `for x in repeat(...):` consumption path) so all three agree on
    exactly which call shapes count."""
    if not isinstance(call, CallExpr) or call.kwargs or len(call.args) != 2:
        return False
    fn = call.func
    if isinstance(fn, IdentExpr):
        return fn.name == 'repeat'
    if isinstance(fn, MemberExpr):
        return (fn.member == 'repeat' and isinstance(fn.obj, IdentExpr)
                and fn.obj.name == 'itertools')
    return False


def _walk_own_body(node):
    """Recursively return a list of every AST node reachable from `node`,
    generically (same walk shape as `_walk_ast`) — EXCEPT it does NOT
    descend into nested FunctionDef/LambdaExpr bodies (a nested def's own
    `yield`/`return` belongs to ITS scope, not the enclosing generator's,
    and would corrupt any caller's own-body-only scan). Factored out of
    `_generator_yield_ctype`'s formerly-inline `_own_walk` (identical
    logic) so `_generator_tuple_yield_slot_ctypes` (below) can reuse the
    exact same own-body walk instead of maintaining a second copy — both
    need to see precisely the same set of a generator's own top-level
    YieldExpr sites."""
    if isinstance(node, (FunctionDef, LambdaExpr)):
        return []
    if node is None:
        return []
    if isinstance(node, (list, tuple)):
        result = []
        for item in node:
            result.extend(_walk_own_body(item))
        return result
    if hasattr(node, '__dataclass_fields__'):
        result = [node]
        for fname in node.__dataclass_fields__:
            result.extend(_walk_own_body(getattr(node, fname)))
        return result
    return [node]


def _generator_tuple_yield_slot_ctypes(fn: FunctionDef, known: dict | None = None,
                                        self_fields: dict | None = None,
                                        async_api: dict | None = None,
                                        closure_api: dict | None = None,
                                        generator_api: dict | None = None) -> tuple[bool, list | None]:
    """Companion to `_generator_yield_ctype` for the tuple-valued-yield
    case (`yield a, b` / `yield a, b, c`): computes the unified per-SLOT
    C++ element type list every tuple-yield site in `fn`'s own body must
    agree on, the way `_generator_yield_ctype` unifies one overall scalar
    type across every (non-tuple) yield site. A tuple-valued yield is
    boxed at its own site into a real runtime `MojoList *` (see
    `_cpp_yield_tuple` — the SAME representation `_lower_tuple_literal`
    already builds for an ordinary, non-generator tuple literal), so the
    promise's own value type just needs to be the ALREADY-supported
    `MojoList *` scalar (`_generator_yield_ctype`'s TupleExpr branch
    contributes exactly that) — but a consumer unpacking that pointer back
    into `for a, b in gen():`'s loop variables needs to know each slot's
    REAL type (int64_t/double/char*) to pick the right accessor
    (mojo_list_get_int/_double/_str), which this function supplies.

    Returns `(has_tuple_yield, slot_ctypes)`:
      - `(False, None)`: `fn` has no tuple-valued yield at all — the
        ordinary, unrelated case for every scalar/list/string-yielding
        generator this codegen already supports; callers must not treat
        this as a refusal.
      - `(True, None)`: `fn` DOES have at least one tuple-valued yield,
        but two sites disagree irreconcilably on ONE SLOT's TYPE (a
        pair the same char*-preference rule `_generator_yield_ctype`
        itself uses doesn't resolve — e.g. int64_t vs double). Callers
        must treat this exactly like `_generator_yield_ctype` returning
        None for any other unsupported shape: refuse the whole generator.
        Differing element COUNTS across sites are NOT a refusal anymore:
        they're unified to the LONGEST site's shape by padding every
        shorter site's slot list with the longer site's tail types
        (first-contributing-site-wins per tail position) — the producer
        side (`_cpp_yield_tuple`, via the pre-pass
        `_cpp_pending_tuple_slots` stash its callers set before body
        emission) boxes each site's real elements and then appends
        zero/empty padding values so EVERY co_yield'd list carries
        exactly the unified arity, keeping every consumer-side per-slot
        accessor read in bounds. A consumer unpacking fewer names than
        the unified arity simply ignores the tail slots; unpacking more
        than some site really produced reads that site's zero padding
        (real Python would raise ValueError there — compiled consumers
        in practice always unpack the common prefix). Real: Lib/
        pickletools.py's `_genops` yielding a 3-tuple (`opcode, arg,
        pos`) at one site and a 4-tuple (`opcode, arg, pos, getpos()`,
        gated by `yield_end_pos`) at another.
      - `(True, [ctype, ...])`: every tuple-yield site agreed (directly or
        via the char*-preference rule) on both arity and each slot's type
        — the list to hand to the consumer-side unpacking helper.

    Per-element types are inferred the exact same way
    `_generator_yield_ctype`'s own per-scalar-yield case does (via
    `_infer_simple_expr_ctype`, defaulting an unresolvable element to
    int64_t — e.g. save_env.py's `getattr(self, get_name)` slot, which
    `_infer_simple_expr_ctype` has no case for): a slot this function
    can't precisely type still gets a usable, consistent int64_t
    convention rather than aborting the whole tuple-yield feature over
    one unresolvable element.

    `generator_api` (self._generator_api, threaded through the same way
    `_generator_yield_ctype`'s own `generator_api` param is) lets a
    `yield from <call>` SITE contribute its delegate's own already-
    resolved slot shape when that delegate is itself a tuple-yielding
    compiled generator — e.g. `def outer(): yield from inner()` where
    `inner()` tuple-yields: `outer`'s own body has no DIRECT `yield a,
    b`, so without this it would (wrongly) come back `(False, None)` —
    "not a tuple yielder at all" — even though every value `outer`
    actually produces at runtime IS one of `inner`'s boxed tuples
    (`_generator_yield_ctype`'s OWN `_yield_from_delegate_ctype` call
    already resolves `outer`'s overall promise value type to `inner`'s
    'MojoList *' via this exact mechanism — this function just needed
    the same propagation for the per-slot metadata a consumer's `for a,
    b in outer():` needs to unpack it). A self-recursive `yield from
    <this-same-function>(...)` site is skipped here for the identical
    reason `_generator_yield_ctype` skips it (see that function's own
    YieldFromExpr branch): `fn` hasn't registered itself into
    `generator_api` yet, and a self-recursive site contributes no
    independent shape opinion of its own anyway."""
    found = False
    slots: list | None = None
    for n in _walk_own_body(fn.body):
        if isinstance(n, YieldExpr) and isinstance(n.value, TupleExpr):
            site = [_infer_simple_expr_ctype(el, known, self_fields, async_api, closure_api) or 'int64_t'
                    for el in n.value.elements]
        elif (isinstance(n, YieldFromExpr) and generator_api is not None
                and isinstance(n.value, CallExpr) and isinstance(n.value.func, IdentExpr)
                and n.value.func.name != fn.name):
            delegate_api = generator_api.get(n.value.func.name)
            delegate_slots = delegate_api.get('tuple_slot_ctypes') if delegate_api else None
            if delegate_slots is None:
                continue
            site = list(delegate_slots)
        else:
            continue
        found = True
        if slots is None:
            slots = list(site)
        else:
            if len(site) != len(slots):
                if len(site) > len(slots):
                    slots = slots + site[len(slots):]
                else:
                    site = site + slots[len(site):]
            merged = []
            for a, b in zip(slots, site):
                if a == b:
                    merged.append(a)
                elif 'char *' in (a, b):
                    merged.append('char *')
                else:
                    return True, None
            slots = merged
    return found, slots


def _generator_yield_ctype(fn: FunctionDef, known: dict | None = None,
                            generator_api: dict | None = None,
                            self_fields: dict | None = None,
                            async_api: dict | None = None,
                            closure_api: dict | None = None,
                            known_structs: frozenset | None = None,
                            dict_val_types: dict | None = None,
                            method_return_types: dict | None = None,
                            fn_return_types: dict | None = None) -> str | None:
    """The single scalar C++ type every `yield <value>` / `yield from
    <call>` in fn's own body must agree on (mixed types, a bare `yield` with
    no value, or a `yield from` that doesn't resolve to a known compiled
    generator's value type, all return None == unsupported). Milestone B
    only supports numeric generators — see the milestone writeup's "Value
    type crossing the boundary" section. `known` (a name -> ctype map,
    passed by _gen_cpp_generator_unit for its own generator's parameters)
    lets `yield <param>` resolve to the param's real type instead of always
    guessing int64_t — see _infer_simple_expr_ctype's docstring.
    `generator_api` (self._generator_api, passed the same way) resolves a
    `yield from <call>`'s contributed type via _yield_from_delegate_ctype.
    `self_fields` (generator METHODS only) lets `yield self.<field>` resolve
    the field's real scalar type — see _infer_simple_expr_ctype. `async_api`
    (self._async_api, Step D) lets an async function's `return await
    <call>` resolve the awaited call's contributed type via
    _await_call_ctype — mirrors `generator_api`'s role for `yield from`
    exactly, kept as its own parameter (not reusing the `generator_api`
    slot) since the two dicts serve genuinely different node shapes
    (YieldFromExpr vs. AwaitExpr) that can never both appear in the same
    function body (a generator can't `await`, an async function can't
    `yield` — see gen_module's combined-refusal category). `known_structs`/
    `dict_val_types`/`method_return_types` (struct-pointer-yield support —
    see CODEGEN_generator_function_Lib_enum.md's 2026-08-20 update) are
    threaded straight through to every `_infer_simple_expr_ctype` call
    below unchanged — see that function's own docstring for what each
    widens."""
    ctype = None
    # Walk only this function's own body — do NOT descend into nested
    # FunctionDef/LambdaExpr bodies (a nested def's `return <value>` is its
    # own, not this generator's, and would corrupt the yield-type check).
    for n in _walk_own_body(fn.body):
        if isinstance(n, YieldExpr):
            if n.value is None:
                if ctype is None:
                    ctype = 'int64_t'  # bare yield yields None → 0
                continue
            if isinstance(n.value, TupleExpr):
                # `yield a, b, c` — a real multi-element tuple yield.
                # Boxed at its own site (see `_cpp_yield_tuple`, called
                # from `_cpp_stmt`'s YieldExpr case) into a real runtime
                # `MojoList *` — the exact representation
                # `_lower_tuple_literal` already builds for an ordinary,
                # non-generator tuple literal, marked via
                # `mojo_mark_as_tuple` — and co_yield'd as that ONE
                # pointer. A `MojoList *` is already a supported co_yield
                # scalar payload (any generator that yields a plain
                # list/string value already relies on this), so the
                # overall promise/value-ctype machinery needs no change at
                # all for this shape beyond contributing 'MojoList *' to
                # the usual unify-across-every-yield-site check below —
                # exactly like any other yield-site type does. The per-
                # SLOT element types (int64_t vs double vs char* per tuple
                # position) are a SEPARATE concern this function doesn't
                # need to resolve — see `_generator_tuple_yield_slot_
                # ctypes`, this function's dedicated companion, which
                # `_gen_cpp_generator_unit`/`_gen_cpp_async_generator_unit`
                # both call right alongside this one and use to drive the
                # consumer-side (`for a, b in gen():`) unpacking.
                # Real: Lib/test/libregrtest/save_env.py's
                # `resource_info`: `yield name, getattr(self, get_name),
                # getattr(self, restore_name)`. See
                # CODEGEN_generator_function_Lib_test_libregrtest_save_env.md.
                #
                # A NESTED collection literal as one of the tuple's own
                # elements (`yield "store", (name,)` — modulefinder.py's
                # `scan_opcodes`, a tuple whose second slot is itself a
                # 1-tuple) has no scalar representation `_cpp_yield_tuple`'s
                # per-element boxing can build: `_cpp_expr` lowers a bare
                # TupleExpr/ListExpr/DictExpr/SetExpr to a raw C++ braced-
                # init-list (`{name}`), which is not a valid argument to
                # `mojo_list_append_int/_double/_str` (nor castable to
                # int64_t/double/char*) — attempting it anyway would
                # reproduce this exact family's original malformed-C++
                # failure mode ONE LEVEL DEEPER instead of fixing it.
                # Refuse the whole shape honestly here, before it ever
                # reaches emission, exactly like any other unsupported
                # yield shape in this function already does.
                if any(isinstance(el, (TupleExpr, ListExpr, DictExpr, SetExpr))
                       for el in n.value.elements):
                    return None
                t = 'MojoList *'
            else:
                t = _infer_simple_expr_ctype(n.value, known, self_fields, async_api, closure_api,
                                             known_structs, dict_val_types, method_return_types,
                                             fn_return_types)
                if t is None:
                    t = 'int64_t'  # default when type can't be inferred
            if ctype is None:
                ctype = t
            elif ctype != t:
                # Type disagreement: prefer char* if either is a string
                if ctype == 'char *' or t == 'char *':
                    ctype = 'char *'
                else:
                    return None
        elif isinstance(n, YieldFromExpr):
            # Self-recursive `yield from <this-same-function>(...)` (real:
            # Tools/c-analyzer/c_common/fsutil.py's/test_exception_group.
            # py's own generators recursing into themselves for the
            # non-leaf case) — `fn` (this call's own first argument) hasn't
            # registered itself into `generator_api` yet (registration only
            # happens once the WHOLE function has finished compiling, in
            # gen_module's calling loop), so _yield_from_delegate_ctype can
            # never resolve it as a known compiled generator and would
            # otherwise fall to its "anything else -> char *" default —
            # silently corrupting the WHOLE function's inferred value type
            # even when a DIRECT `yield <value>` site elsewhere in the same
            # body (the base-case leaf, e.g. `yield root`) unambiguously
            # wants int64_t/double/_Bool. A self-recursive site contributes
            # NO independent type opinion of its own — by definition, a
            # self-recursive generator's value type is whatever its OTHER
            # (non-recursive) yield site(s) agree on — so skip it entirely
            # here rather than let it default to char* and clobber the
            # real answer. See
            # CODEGEN_generator_recursive_yield_from_no_arg_forwarding.md.
            if (isinstance(n.value, CallExpr) and isinstance(n.value.func, IdentExpr)
                    and n.value.func.name == fn.name):
                continue
            t = _yield_from_delegate_ctype(n, generator_api)
            if t is None:
                return None
            if ctype is None:
                ctype = t
            elif ctype != t:
                # Prefer char* if either is a string (same as YieldExpr above)
                if ctype == 'char *' or t == 'char *':
                    ctype = 'char *'
                else:
                    return None
        elif isinstance(n, ReturnStmt):
            # Step B (compiled async codegen) reuses this same unify-across-
            # every-site walk for an async function's `return <expr>` sites
            # instead of a second, parallel "_async_return_ctype" helper
            # that would just duplicate this exact logic under a different
            # name. Unreachable in generator-translation mode: _cpp_stmt's
            # ReturnStmt case already raises _UnsupportedGeneratorShape for
            # any value-carrying `return` inside a generator body before
            # this function is ever called for that body, so this branch
            # only actually fires while translating an async function.
            if n.value is None:
                continue
            t = _infer_simple_expr_ctype(n.value, known, self_fields, async_api, closure_api,
                                             known_structs, dict_val_types, method_return_types,
                                             fn_return_types)
            if t is None:
                return None
            if ctype is None:
                ctype = t
            elif ctype != t:
                return None
    return ctype


def _struct_name_of(ctype: str) -> str:
    """Extract the bare struct name from a C type like 'const Foo *' → 'Foo'."""
    s = ctype
    if s.startswith('const '):
        s = s[6:]
    return s.replace(' *', '').strip()

def _struct_type_id(name: str) -> int:
    """Deterministic runtime type tag for a struct name — a pure function of
    the name, so the allocation site (which stamps this into the struct's
    leading `__mojo_type_id` field) and any isinstance(x, name) call site
    (which compares against it) always agree without a shared registry, even
    across separately-compiled modules. See mojo_read_type_tag in
    runtime/mojo_runtime.c for the read side.

    Deliberately a plain `while`-loop over `name[i]` + `ord(c)`, NOT
    `for c in name` — the self-hosted compiler has no lowering for iterating
    a char* string (mojo_unsupported_iter, body runs zero times), which made
    the COMPILED _struct_type_id return 0 for every name and broke
    `type(x).__name__` dispatch / isinstance in the self-hosted backend."""
    h = 0
    i = 0
    n = len(name)
    while i < n:
        c = name[i]
        # Python: name[i] is a 1-char str → ord() it. The COMPILED binary:
        # char* subscript lowering dereferences and yields the char's integer
        # value already, and `ord()` on that int64_t is mis-lowered to
        # `mojo_ord((char*)c)` — dereferencing the small char value as a
        # pointer (SEGFAULT at address 0x42 for 'B'). Branch on the actual
        # runtime type so the arithmetic is identical on both paths.
        if isinstance(c, str):
            c = ord(c)
        h = (h * 31 + c) & 0x7FFFFFFF
        i = i + 1
    return h

# libc/system symbols a Mojo *function definition* must not shadow: the library
# itself defines e.g. `fn exit(...)` whose body calls libc `exit` via
# external_call. Emitting that as C `exit` would self-recurse and clash with the
# stdlib.h prototype. So a Mojo function with one of these names is mangled to
# `mojo_<name>` (definition AND call sites, via this chokepoint), while
# external_call keeps emitting the raw libc symbol.
_C_RESERVED_FUNCS = frozenset({
    # Core libc functions that Mojo stdlib may redefine.
    # At DEFINITION sites these are always renamed (fn abs → mojo_abs).
    # At CALL sites they are only renamed when a local definition exists
    # (see _lower_CallExpr: the rename is gated on func_return_types).
    'exit', 'abort', 'write', 'read', 'close',
    'malloc', 'calloc', 'realloc', 'free',
    'printf', 'fprintf', 'snprintf', 'sprintf', 'dprintf', 'puts', 'putchar',
    'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
    'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat',
    'strchr', 'strrchr', 'strstr', 'strtok', 'strerror',
    'atoi', 'atol', 'atoll', 'atof',
    'strtol', 'strtoll', 'strtod', 'strtof',
    'setvbuf', 'setbuf',
    'remainderf', 'remainderl',
    'posix_spawn', 'posix_spawnp',
    'index', 'rindex',
    # Math functions (from <math.h>) that the Mojo stdlib may redefine
    'cos', 'cosf', 'sin', 'sinf', 'tan', 'tanf',
    'acos', 'acosf', 'asin', 'asinf', 'atan', 'atanf', 'atan2', 'atan2f',
    'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf', 'trunc', 'truncf',
    'sqrt', 'sqrtf', 'cbrt', 'cbrtf',
    'pow', 'powf', 'exp', 'expf', 'exp2', 'exp2f', 'log', 'logf',
    'log2', 'log2f', 'log10', 'log10f',
    'fabs', 'fabsf', 'fmod', 'fmodf',
    'erf', 'erff', 'erfc', 'erfcf', 'tgamma', 'lgamma',
    'ldexp', 'ldexpf', 'frexp', 'frexpf', 'modf', 'modff',
    'sinh', 'sinhf', 'cosh', 'coshf', 'tanh', 'tanhf',
    'asinh', 'acosh', 'atanh', 'asinhf', 'acoshf', 'atanhf',
    'nextafter', 'nextafterf', 'copysign', 'copysignf',
    'nan', 'nanf', 'hypot', 'hypotf', 'fma', 'fmaf', 'remainder',
    'expm1', 'expm1f', 'log1p', 'log1pf',
    'scalb', 'scalbf', 'scalbn', 'scalbnf', 'logb', 'logbf',
    'j0', 'j1', 'y0', 'y1',
    # Environment / system functions
    'getenv', 'setenv', 'unsetenv', 'putenv', 'realpath',
    # File I/O
    'open',
    'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind', 'fflush',
    'getline', 'getdelim', 'fgets', 'fputs', 'feof', 'ferror', 'clearerr',
    'vprintf', 'vfprintf', 'vsnprintf', 'vsprintf',
    'fdopen', 'popen', 'pclose',
    'remove', 'rename',
    # Random / stdlib math
    'rand', 'srand', 'random', 'srandom',
    # Process / unix
    'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork', 'execv',
    'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown', 'unlink', 'rmdir',
    'ioctl', 'fcntl', 'dup', 'dup2', 'pipe',
    # Dynamic linking
    'dlopen', 'dlsym', 'dlclose', 'dlerror',
    # Other stdlib
    'access', 'stat', 'lstat', 'fstat',
    'qsort', 'bsearch',
    # Integer / float math
    'abs', 'labs', 'llabs',
    'fabsf', 'fmodf', 'sqrtf', 'powf', 'ceilf', 'floorf', 'roundf', 'truncf',
    # Math classification macros (<math.h>)
    'isfinite', 'isinf', 'isnan', 'isnormal', 'signbit', 'fpclassify',
    # ctype
    'isalpha', 'isdigit', 'isalnum', 'isspace', 'isupper', 'islower',
    'toupper', 'tolower',
    # POSIX/BSD extras
    'strdup', 'strndup', 'strtok_r',
    # Time
    'time', 'clock', 'difftime', 'mktime', 'strftime',
    'gmtime', 'localtime',
    # Signal
    'signal', 'raise',
    # GCC GIMPLE FE keywords — calling these inside __GIMPLE triggers a parse error.
    '_end',
})

# Names in _C_RESERVED_FUNCS where the real libc signature is incompatible with how
# the Mojo stdlib prelude redefines them (return type, e.g. char *, or arity, e.g.
# atol(s, base) vs libc atol(s)) — so a call site with no local def or explicit import
# (the common case: these are prelude symbols, and we don't model implicit prelude
# imports) must still be treated as a Mojo call, not real libc. Always renamed to
# mojo_X, which needs a matching variadic stub in _util_pairs below.
_FORCE_RENAME_RESERVED = frozenset({'index', 'rindex', 'getenv', 'atol', 'frexp', 'abort'})

def _is_concrete_type_arg(ann: str) -> bool:
    """Whether a generic type argument is a concrete type (Int64, String, a struct,
    DType.int64) rather than an unbound type parameter (T, U, T0, *Ts, Self.T,
    Self.Types[i]). Only concrete args may be instantiated — substituting one
    symbol for another never converges and blows up the elaborator."""
    if not isinstance(ann, str) or not ann:
        return False
    base = ann.split('[', 1)[0].strip()
    if base.startswith('Self') or base.startswith('*') or not base:
        return False                       # Self.T, Self.Types[i], *Ts
    if re.fullmatch(r'[A-Z][0-9]?', base):
        return False                       # lone type param: T, U, K, T0, T1
    return True


_BRACKET_HEAD_RE = re.compile(r'\b(?:fn|def)\s+(\w+)\s*\[([^\]]*)\]')


def _bracket_param_type_annotations(gsrc: str, name: str, occurrence: int = 0) -> dict:
    """For `def/fn name[p1: T1, p2: T2, ...](...)` (a method or free function
    with a bracket/comptime parameter list), map each bracket parameter name
    to its raw type-annotation text (e.g. {'func': 'def() capturing -> None'}
    or {'FuncType': 'def() -> None'}). Used to distinguish a FUNCTION-TYPED
    comptime bracket parameter (see _method_threaded_comptime_params) from an
    Int/Bool/other comptime parameter — a function-typed one carries no
    compile-time-varying information this codegen's monomorphization needs
    (it's always just an opaque callable pointer, regardless of which
    concrete function is bound at a given call site — see bugs/CODEGEN_
    device_context_captured_function_parameter_closures_broken.md's Repro 1),
    so it can be threaded through as an ordinary trailing C parameter instead
    of needing per-call-site specialization. Purely textual (mirrors
    elaborate.py's own `_HEAD`/`type_param_names`), since the parser itself
    only records comptime PARAM NAMES (FunctionDef.comptime_params), not
    their type annotations.

    `occurrence` selects the Nth (0-based) `def/fn name[...]` match in
    source order — REQUIRED when `name` is overloaded (multiple sibling
    definitions sharing one name, e.g. std/memory/span.mojo's two
    `binary_search_by` overloads with completely different bracket-parameter
    shapes): matching by name alone would always return the FIRST overload's
    bracket text regardless of which one is actually being processed,
    silently applying its parameter-threading decision to every sibling
    overload too. Returns {} if `name`'s `occurrence`-th match isn't found or
    has no bracket parameter list."""
    m = _BRACKET_HEAD_RE.search(gsrc)
    seen = -1
    while m:
        if m.group(1) == name:
            seen += 1
            if seen == occurrence:
                break
        m = _BRACKET_HEAD_RE.search(gsrc, m.end())
    if not m:
        return {}
    out = {}
    for part in _split_top_level_commas(m.group(2)):
        part = part.strip()
        if not part or part in ('/', '*') or ':' not in part:
            continue
        pname, ptype = part.split(':', 1)
        out[pname.strip()] = ptype.strip()
    return out


def _used_idents_deep(node) -> set:
    """Like _used_idents_node, but ALSO recurses into nested FunctionDef
    bodies (a nested closure's own free-identifier references count as
    "used" by the enclosing function too) — needed to detect a comptime
    bracket parameter that's referenced only inside a nested closure (e.g.
    device_context.mojo's `async def wrapper() capturing -> None: func()`,
    where `func` is the enclosing method's own comptime bracket parameter,
    never referenced directly in the method's own top-level body)."""
    if isinstance(node, FunctionDef):
        r = set()
        for b in node.body:
            r |= _used_idents_deep(b)
        return r
    if isinstance(node, list):
        r = set()
        for b in node:
            r |= _used_idents_deep(b)
        return r
    base = _used_idents_node(node)
    for attr in ('then_body', 'else_body', 'body', 'finally_body'):
        sub = getattr(node, attr, None)
        if isinstance(sub, list):
            for s in sub:
                base |= _used_idents_deep(s)
    for _cond, elif_body in getattr(node, 'elifs', []) or []:
        for s in elif_body:
            base |= _used_idents_deep(s)
    for handler in getattr(node, 'handlers', []) or []:
        hbody = getattr(handler, 'body', None)
        if isinstance(hbody, list):
            for s in hbody:
                base |= _used_idents_deep(s)
    return base
