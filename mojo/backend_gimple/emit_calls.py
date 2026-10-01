# Moved from gimple_gen_calls.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""Call/constructor/subscript lowering for the GIMPLE backend.

Function-extraction architecture: former GimpleGen methods as module-level
functions taking `gen` first; delegates remain on the class; cross-module
references are qualified (single-emission closure rule).
"""
from __future__ import annotations

import os
import re

from fire_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, NonlocalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    _as_str, _sms_key, _as_ident_node,
)
import regex_compile
import mlir
import mojo.backend_gimple.device_glue as _gmi_glue
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import mojo.middle.lambdareduce as _gld
import gimple_codegen
import mojo.backend_gimple.emit_exprs as gex
import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.emit_calls as ggc

# Re-export shared helpers from mojo.middle.calls_shared via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.calls_shared import *  # noqa: F401,F403
from mojo.middle.types import _SCALAR_INT_TYPES, _SCALAR_FLOAT_TYPES  # underscore: `import *` won't carry them
from mojo.middle.calls_shared import (
    _as_str, _build_call_args_for_candidate, _default_expr_to_pair, _ident_call_name, _isinstance_type_name, _pack_kwargs_dict,
    _resolve_overload, _sms_key
)
from mojo.middle.methods_shared import _is_selfhost_source_file

def _emit_generator_start_call(gen, node: gimple_ctypes.CallExpr, api: dict,
                               fname_raw: str) -> str:
    """Shared lowering for every bare-call CONSTRUCTION of a compiled
    free-function generator (`counter(3)` on a local definition, or
    `walk_a("x")` where walk_a is an aliased import of another module's
    compiled generator): lowers each argument with the ordinary
    lower_expr-per-arg path, pads missing trailing params from keyword
    arguments / real defaults (see _lower_named_call's identical padding
    for ordinary functions), emits `<base>_start(args...)`, and records
    the result temp -> api in _generator_var_api so every later consumer
    of the handle (a `for` loop, next(), list()) recovers the right
    resume/value/destroy API. Consolidates what used to be two verbatim
    copies of this block (local-definition vs imported-binding branches
    of _lower_call) so the padding/kwslot/registration logic can't drift.
    """
    # Argument lowering reuses the exact same gen.lower_expr(a)-per-
    # arg + _call_expr/_emit_call path every ordinary function call
    # in this file uses — func_param_types[f"{base}_start"] (registered in
    # gen_module's generator pre-pass, or setdefault'd from the api entry's
    # own 'params' for a cross-module binding at its import site) is what
    # lets _emit_call's existing coercion logic (int literal -> int64_t,
    # etc.) apply here with no separate/duplicated coercion code.
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    # Pad missing trailing params with keyword args / real defaults,
    # mirroring _lower_named_call's identical padding for ordinary
    # functions (see its own comment on `greet()` vs `def greet(name
    # = "world")`). Without this, a generator call omitting any
    # keyword-or-defaulted param (e.g. `tokenize(src, filename=
    # filename)`, real code in Tools/cases_generator/lexer.py) only
    # ever passed the bare positional args straight through — the
    # keyword argument was silently DROPPED entirely and no default
    # value filled the gap either, producing a hard "too few
    # arguments to function '<base>_start'" compile error since
    # `<base>_start`'s real C signature has one slot per Python
    # parameter, unconditionally.
    _gen_kwargs = getattr(node, 'kwargs', []) or []
    _gen_expected = gen.func_param_types.get(f"{api['base']}_start", [])
    # Which C-signature slot (if any) is this generator function's
    # OWN `**kwargs` parameter — see _func_kwargs_slot's docstring.
    # A literal keyword argument destined for that slot must be
    # PACKED into a real MojoDict (via _pack_kwargs_dict), exactly
    # like _lower_named_call's identical `_kwslot_for_pack` handling
    # for ordinary (non-generator) functions — mirrored here rather
    # than duplicated differently. Without this, the loop below
    # just popped the next literal keyword argument's raw lowered
    # VALUE into whichever slot came next in sequence, with no
    # awareness that one particular slot is a `MojoDict *`:
    # `gen_forward(3, b=5)` emitted `_t4 = (MojoDict *)_t3` — the
    # integer 5 reinterpreted as a dict pointer — which segfaults
    # the moment the generator body reads its own `**kwargs`.
    _gen_kwslot = gen._func_kwargs_slot.get(
        fname_raw, gen._func_kwargs_slot.get(f"{api['base']}_start", -1))
    if _gen_expected and len(arg_pairs) < len(_gen_expected):
        _gen_kwarg_dict = {kn: gen.lower_expr(ke) for kn, ke in _gen_kwargs}
        _gen_kwarg_values = list(_gen_kwarg_dict.values())
        _gen_dflts = gen._func_param_defaults.get(f"{api['base']}_start", [])
        while len(arg_pairs) < len(_gen_expected):
            _pos = len(arg_pairs)
            if _gen_kwslot >= 0 and _pos == _gen_kwslot:
                arg_pairs.append(('MojoDict *', gen._pack_kwargs_dict(_gen_kwarg_dict)))
                _gen_kwarg_values = []
                continue
            if _gen_kwarg_values:
                arg_pairs.append(_gen_kwarg_values.pop(0))
                continue
            # Trailing-run offset via the shared helper (`param_defaults`
            # only covers params that HAVE one — `def prod(n, step=10)`
            # called as `prod(3)` must pad slot 1 with 10, not 0; plain
            # `_gen_dflts[_pos]` indexing missed every time here, silently
            # miscompiling the omitted arg to a typed zero).
            _dv = gimple_exprtypes._trailing_default_at(
                _gen_dflts, len(_gen_expected), _pos)
            if _dv is not None:
                arg_pairs.append(gen._default_expr_to_pair(_dv))
            else:
                arg_pairs.append(('int', '0'))
    else:
        for _, _ke in _gen_kwargs:
            gen.lower_expr(_ke)
    t = gen._call_expr('MojoGenerator *', f"{api['base']}_start", arg_pairs)
    gen._generator_var_api[t] = api
    return t


def _lower_generator_next(gen, av: str, api: dict) -> tuple[str, str]:
    base, vct = api['base'], api['value_ctype']
    resumed = gen._new_val('_Bool', f"{base}_resume ({av})")
    bb_ok = gen._new_bb(); bb_exhausted = gen._new_bb(); bb_merge = gen._new_bb()
    bb_stopiter = gen._new_bb()
    gen._emit(f"  if ({resumed}) goto {bb_ok}; else goto {bb_exhausted};")
    gen._emit_label(bb_exhausted)
    gen._emit_generator_pending_exc_check(av, base, False, bb_stopiter)
    gen._emit_label(bb_stopiter)
    gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('StopIteration')});")
    gen._emit("  mojo_raise ();")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_ok)
    result = gen._new_val(vct, f"{base}_value ({av})")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)
    return vct, result


def _gen_slot_box(gen, st: str, sv: str, vct: str) -> str:
    """Box a value into a generator's int64_t value/argument slot.

    The slot carries integers and pointers directly; a `double`-valued
    generator bit-casts (its `<base>_value`/`__mojo_gen_arg_d` counterparts
    memcpy the bits back out, exactly as the start-call site does for a
    double PARAMETER — see gimple_gen_coro's arg_fwd)."""
    if vct == 'double' and st in ('double', 'float'):
        box = gen._new_temp('int64_t')
        raw = gen._new_val('double', sv)
        gen._emit(f"  __builtin_memcpy (&{box}, &{raw}, 8);")
        return box
    return gen._to_int64(st, sv)


def _lower_generator_send(gen, node, av: str, api: dict) -> tuple[str, str]:
    """`g.send(v)` — resume the generator, handing it `v` as the value of
    the `yield` expression it is suspended on. Real Python's semantics,
    including the StopIteration on exhaustion (the generator protocol's
    uniform "ran out of values" signal, not a silent end).

    This is the SAME resume the `<base>_resume` trampoline performs, with a
    non-zero send payload: `__mojo_gen_resume(gen, send)` is the runtime
    entry both funnel into, so no new ABI is involved. The per-generator
    `<base>_resume(g)` wrapper hardcodes a 0 send, which is why this calls
    the runtime function directly rather than through the trampoline."""
    vct = api['value_ctype']
    if len(node.args) == 1:
        st, sv = gen.lower_expr(node.args[0])
        send = _gen_slot_box(gen, st, sv, vct)
    else:
        send = '0'
    handle = gen._to_int64('MojoGenerator *', av)
    resumed = gen._new_val('_Bool', f"__mojo_gen_resume ({handle}, {send})")
    bb_ok = gen._new_bb(); bb_exhausted = gen._new_bb(); bb_merge = gen._new_bb()
    bb_stopiter = gen._new_bb()
    gen._emit(f"  if ({resumed}) goto {bb_ok}; else goto {bb_exhausted};")
    gen._emit_label(bb_exhausted)
    gen._emit_generator_pending_exc_check(av, api['base'], False, bb_stopiter)
    gen._emit_label(bb_stopiter)
    gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('StopIteration')});")
    gen._emit("  mojo_raise ();")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_ok)
    result = gen._new_val(vct, f"{api['base']}_value ({av})")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)
    return vct, result


def _lower_generator_throw(gen, node, av: str, api: dict) -> tuple[str, str]:
    """`g.throw(Exc[, exc[, tb]])` — raise `Exc` inside the generator at its
    suspend point, exactly as if its body had raised it there. If the body
    catches it and yields again, that value is returned; if the exception
    propagates out of the generator or the generator ends, it is re-raised
    on the CALLER's frame through the same pending-exception mechanism
    `next()` uses, so an `except ValueError:` around the `.throw()` call
    matches exactly as it would in real Python.

    The exception is identified by the same CRC tag scheme
    `_exc_type_id`/`mojo_exc_type_set` use for every other raise/except in
    this backend. `g.throw(ValueError)` with no instance is treated as
    `ValueError()` — real Python's own normalization."""
    if not node.args:
        return _lower_generator_next(gen, av, api)
    exc_node = node.args[0]
    exc_name = None
    if isinstance(exc_node, gimple_ctypes.IdentExpr):
        exc_name = exc_node.name
    elif isinstance(exc_node, gimple_ctypes.CallExpr) and \
            isinstance(exc_node.func, gimple_ctypes.IdentExpr):
        exc_name = exc_node.func.name
    if exc_name is None or exc_name not in gen._KNOWN_EXCEPTION_NAMES:
        raise RuntimeError(
            f"generator .throw(): expected an exception class name "
            f"(e.g. g.throw(ValueError)), got {type(exc_node).__name__}")
    handle = gen._to_int64('MojoGenerator *', av)
    # `g.throw(ValueError("boom"))`: the message rides in the same exc_msg
    # slot a `raise ValueError("boom")` uses, so an `except ValueError as
    # e:` body reads the same text.
    msg = '0'
    if isinstance(exc_node, gimple_ctypes.CallExpr) and exc_node.args:
        mt, mv = gen.lower_expr(exc_node.args[0])
        msg = gen._to_int64(mt, mv)
    vct = api['value_ctype']
    thrown = gen._new_val(
        '_Bool',
        f"__mojo_gen_throw ({handle}, {gen._exc_type_id(exc_name)}, {msg}, 0)")
    bb_ok = gen._new_bb(); bb_exhausted = gen._new_bb(); bb_merge = gen._new_bb()
    bb_stopiter = gen._new_bb()
    gen._emit(f"  if ({thrown}) goto {bb_ok}; else goto {bb_exhausted};")
    gen._emit_label(bb_exhausted)
    # The body propagated something (or ended): re-raise it HERE, on the
    # consumer's own frame, exactly as _lower_generator_next does. The
    # runtime call itself does not longjmp — the injected exception is
    # caught by the body's own trampoline and handed back as the pending
    # flag, which is what makes the caller's `except` see it.
    gen._emit_generator_pending_exc_check(av, api['base'], False, bb_stopiter)
    gen._emit_label(bb_stopiter)
    gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('StopIteration')});")
    gen._emit("  mojo_raise ();")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_ok)
    result = gen._new_val(vct, f"{api['base']}_value ({av})")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)
    return vct, result


def _lower_generator_close(gen, node, av: str, api: dict):
    """`g.close()` — throw GeneratorExit into the generator so a
    `try`/`finally` in its body still runs its cleanup, then mark it
    finished. Real Python makes this a no-op on an already-exhausted
    generator, and raises RuntimeError if the body yields again instead of
    exiting (which is what `__mojo_gen_close`'s return value reports).
    Consuming a generator does not free it, so this deliberately does not
    destroy the handle either."""
    handle = gen._to_int64('MojoGenerator *', av)
    ignored = gen._new_val(
        '_Bool',
        f"__mojo_gen_close ({handle}, {gen._exc_type_id('GeneratorExit')})")
    bb_ok = gen._new_bb(); bb_ignored = gen._new_bb()
    gen._emit(f"  if ({ignored}) goto {bb_ignored}; else goto {bb_ok};")
    gen._emit_label(bb_ignored)
    # Real Python: "RuntimeError: generator ignored GeneratorExit" when a
    # close()d generator yields again instead of unwinding.
    gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('RuntimeError')});")
    gen._emit("  mojo_raise ();")
    gen._emit_label(bb_ok)
    return 'void', None


def _lower_pointer_ctor(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """BUG-2026-027: `UnsafePointer[T](x)` / `OwnedPointer[T](x)` /
    `ArcPointer[T](x)` / `Pointer[T](x)` — the generic pointer-wrapper
    constructor call. This codegen has no separate boxed representation for
    these types: `_mojo_type`/`_resolve_type` already erase `UnsafePointer[T]`
    straight to `T *` for any variable/parameter annotated with it, and
    `.data` on such a value is identity (see the `.data` fix in
    `gimple_gen_exprs.py`'s `_lower_MemberExpr`, which assumes the same
    thing). So constructing one is just producing a `T *` value from
    whatever the argument is — before this fix, `CallExpr(func=
    SubscriptExpr(...))` for this shape fell all the way through
    `_lower_call` to its final "indirect call via SubscriptExpr" catch-all,
    silently dropping the argument and always yielding NULL.
    """
    idx = node.func.index
    elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
    elem_ann = gen._type_expr_to_ann(elems[0]) if elems else None
    # Reconstruct the full "UnsafePointer[T]"-shaped annotation string and
    # hand it to `_resolve_type`, which already special-cases a struct
    # element type to a SINGLE `T *` (struct locals/globals/params are
    # themselves always `T *` — see BUG-2026-030 — so "a pointer to a
    # struct" is just `T *`, not `T **`). Recomputing that logic here (e.g.
    # naively appending " *" to `_resolve_type(elem_ann)`, which for a
    # struct elem_ann already returns `T *` on its own) would double the
    # pointer depth and mistype every `UnsafePointer[SomeStruct]` local as
    # `T **`.
    base = node.func.obj.name
    ptr_ctype = gen._resolve_type(f"{base}[{elem_ann}]") if elem_ann else 'int64_t *'
    if not node.args:
        # UnsafePointer[T]() — no-arg form: a null pointer.
        return ptr_ctype, gen._new_val(ptr_ctype, f"({ptr_ctype})0")
    at, av = gen.lower_expr(node.args[0])
    if at == ptr_ctype:
        return ptr_ctype, av
    if at.endswith(' *'):
        # Pointer-to-pointer reinterpret (e.g. wrapping another
        # UnsafePointer's raw value, or a `.unsafe_ptr()` result of a
        # different element type) — straight cast.
        return ptr_ctype, gen._new_val(ptr_ctype, f"({ptr_ctype}){av}")
    # Integer address -> pointer. GIMPLE rejects a direct int64_t->T* cast
    # in one statement ("invalid conversion"); go through void* in two
    # single-cast statements, the same pattern `_strided_data_ptr` uses.
    av64 = av if at == 'int64_t' else gen._new_val('int64_t', f"(int64_t){av}")
    vp = gen._new_val('void *', f"(void *){av64}")
    return ptr_ctype, gen._new_val(ptr_ctype, f"({ptr_ctype}){vp}")


def _lower_pointer_alloc(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """`UnsafePointer[T].alloc(n)` (also `OwnedPointer`/`ArcPointer`/`Pointer`)
    — the static heap-allocation constructor. `node.func` is a MemberExpr
    (`.alloc`) whose `.obj` is the SubscriptExpr `UnsafePointer[T]`.

    Before this, the `UnsafePointer[T]` receiver was lowered as an ordinary
    subscript (→ `mojo_list_get_int`) and `.alloc(n)` fell through to the
    generic "unknown method on a scalar receiver" stub, which hands the
    receiver value straight back — so the `.alloc()` result was a bogus
    list-get temp. In-function field access through it happened to still
    work in some shapes, but `Int(UnsafePointer[T].alloc(n))` read the
    bogus temp (0) and any round-trip of that handle through `Int()` back
    into a pointer produced a null deref. See
    `bugs/CODEGEN_int_of_alloc_struct_pointer_returns_zero.md`.

    Lowered to a per-element-type `_alloc_n_<T>` helper (plain C, emitted in
    the preamble alongside `_alloc_<T>` / `_mojo_at_<T>`): a `calloc(n,
    sizeof(T))` cast to `T *`, and — for a struct element type — every
    element's leading `__mojo_type_id` header is set, so struct-pointer
    field access (the sibling deref bug's fix, which reads that tag) keeps
    working on `.alloc()`'d memory too.
    """
    sub = node.func.obj  # SubscriptExpr: UnsafePointer[T]
    idx = sub.index
    elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
    elem_ann = gen._type_expr_to_ann(elems[0]) if elems else None
    base = sub.obj.name
    # Same struct-vs-scalar erasure as _lower_pointer_ctor: `_resolve_type`
    # already collapses `UnsafePointer[SomeStruct]` to a single `T *`.
    ptr_ctype = gen._resolve_type(f"{base}[{elem_ann}]") if elem_ann else 'int64_t *'
    if not ptr_ctype.endswith(' *'):
        ptr_ctype = ptr_ctype + ' *'
    elem_ctype = ptr_ctype[:-2].strip()
    # Count argument. Real Mojo's `.alloc(count)` requires it; default to 1
    # for the degenerate no-arg spelling rather than emit invalid C.
    if node.args:
        nt, nv = gen.lower_expr(node.args[0])
        n_val = nv if nt == 'int64_t' else gen._new_val('int64_t', f'(int64_t){nv}')
    else:
        n_val = gen._new_val('int64_t', '(int64_t)1')
    for a in node.args[1:]:
        gen.lower_expr(a)
    gen._ptr_alloc_n_needed.add(elem_ctype)
    t = gen._new_temp(ptr_ctype)
    gen._emit(f"  {t} = _alloc_n_{gimple_ctypes._c_id(elem_ctype)} ({n_val});")
    return ptr_ctype, t


def _future_done_callback_kind_tag(cb_ctype: str) -> int:
    """Tag stored with a `fut.add_done_callback(cb)` handle so the runtime
    (`__mojo_future_invoke_callback`, runtime/mojo_coro_gen.c) invokes it
    through the matching ABI:
      0 -- bare C function pointer: a top-level `def cb(fut)` by name or a
           non-capturing nested closure (`_funcptr_<csym>` / `void *`),
           called `((void(*)(int64_t))h)(fut)`.
      1 -- `MojoBoundMethod *`: a bound method `self.on_done` or a capturing
           closure (env carried as `self`), invoked `fn(self, fut)` a la
           runtime/fire_runtime.h's mojo_bound_method_call_1.
    Keyed off the lowered C type -- authoritative for both a syntactic
    `self.cb` and a capturing closure passed by name."""
    return 1 if cb_ctype == 'MojoBoundMethod *' else 0


def _lower_future_done_callback(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Lower `__mojo_future_add_done_callback` / `_remove_done_callback`,
    supplying the callable-kind tag as the 3rd argument from the lowered C
    type of the callback value (see _future_done_callback_kind_tag). The
    async-body hook (gimple_gen_coro._rewrite_async_expr) emits these calls
    with just (future, cb); this fills in the tag centrally so both the
    async and the sync (gimple_gen_methods) hooks agree."""
    fname = node.func.name
    fut_t, fut_v = gen.lower_expr(node.args[0])
    cb_t, cb_v = gen.lower_expr(node.args[1])
    tag = _future_done_callback_kind_tag(cb_t)
    args = [('int64_t', fut_v), (cb_t, cb_v), ('int64_t', str(tag))]
    if fname.endswith('add_done_callback'):
        gen._emit_call('void', '', fname, args)
        return 'void', ''
    return 'int64_t', gen._call_expr('int64_t', fname, args)


def _ggc_as_str(x) -> str:
    """Same-module `str`-view identity helper. The IMPORTED
    `fire_compiler._as_str`'s `-> str` return type is not resolved at a
    module-level call site in this file, so a key routed through it still
    quick-typed as int64_t and `_emit_dict_pair_store` stringified the
    pointer via `mojo_str_from_int` (see the `kwarg_dict` build in
    `_lower_named_call`). A SAME-MODULE `-> str` function resolves, so the
    key comes out `char *` and is stored by name."""
    return x


def _lower_device_launch(gen, node: gimple_ctypes.CallExpr):
    """A call whose target is an offloaded DEVICE function.

    A `@gpu` function has no C definition -- it is MSL, living in the
    sidecar's string -- so an ordinary call would emit a reference to an
    undefined C symbol and fail at link time. Instead the call is routed to
    the generated host wrapper `_mg_launch_<name>`, which the sidecar emits
    with the kernel's real parameter list. Keeping the *wrapper* named after
    the kernel and the *signature* mirroring it is what makes the host side
    look like an ordinary function call at the call site.

    Returns None when the callee is not a device kernel, so the caller falls
    through to the ordinary path. Returns (type, value) like every other
    lowering: kernels return void, so the value is a `void`-typed int64_t 0
    only if someone writes the call in value position -- which is an error
    the type layer should catch, and returning 0 is the honest "nothing"
    rather than a plausible-looking garbage int.
    """
    if not isinstance(node.func, gimple_ctypes.IdentExpr):
        return None
    if node.func.name not in getattr(gen, '_device_kernels', ()):
        return None
    _kname = node.func.name
    _wname = '_mg_launch_' + gimple_ctypes._safe_name(_kname)
    _argtypes = getattr(gen, '_device_launch_args', {}).get(_kname)
    if _argtypes is None:
        raise RuntimeError(
            f'cannot compile module: call to GPU kernel {_kname!r} has no '
            f'recorded parameter types, so the host marshalling wrapper '
            f'cannot be generated for it')
    # The kernel's length parameter indexes BOTH the device-side bound and the
    # host-side marshalling, so a list can be sized for the conversion. It is
    # recorded per kernel by the classification pass (module_gen), because a
    # DEVICE function never runs through gen_func and so has no inferred
    # signature to read a length out of.
    _count_idx = getattr(gen, '_device_launch_count', {}).get(_kname, -1)
    # Two passes, because the marshalling for buffer i needs the count
    # argument's C value, and the count argument is itself one of the lowered
    # arguments -- which does not exist until the first pass has run.
    _lowered = []
    for _a in node.args:
        _lowered.append(gen.lower_expr(_a))
    _count_val = _lowered[_count_idx][1] if 0 <= _count_idx < len(_lowered) else None

    _parts = []
    _unpacks = []
    _frees = []
    for _i, _a in enumerate(node.args):
        # `_device_launch_args` holds (name, c_type, is_buffer) triples so the
        # wrapper generator can tell buffers from scalars; the call site only
        # needs the C type and the is_buffer flag.
        _spec = _argtypes[_i]
        _want = _spec.ctype if isinstance(_spec, _gmi_glue.LaunchArg) else _spec[1]
        _is_buf = (_spec.is_buffer if isinstance(_spec, _gmi_glue.LaunchArg)
                   else (len(_spec) > 2 and _spec[2]))
        _t, _v = _lowered[_i]
        # PER-BUFFER LENGTH. A kernel may give a buffer its own element-count
        # expression (`LaunchArg.length`), because one count cannot describe a
        # GEMM: A is M*K, B is K*N, C is M*N. Falling back to the kernel's
        # single Int parameter keeps every existing kernel byte-identical.
        _len_expr = (_spec.length
                     if isinstance(_spec, _gmi_glue.LaunchArg) else None)
        if _is_buf and _t == 'MojoList *':
            # A boxed list where the kernel wants a `T *`.
            #
            # This is the conversion that MUST NOT be a cast: a MojoList is
            # a struct whose first field is a data pointer, so `(float *)l`
            # points at the struct HEADER and `p[i]` reads data/len/cap/the
            # inline buffer as floats. It links, runs, and returns garbage.
            # So the list is packed into a real contiguous buffer, dispatched
            # against that, and written back afterwards.
            if _count_val is None:
                raise RuntimeError(
                    f'cannot compile module: GPU kernel {_kname!r} was given a '
                    f'list for argument {_spec.name!r}, which needs the '
                    f"kernel's length parameter to size the buffer, but no "
                    f'length parameter was recorded')
            _elem = _want[:-2] if _want.endswith(' *') else 'float'
            _pack = _gmi_glue._c_helper_name(_elem)
            # A buffer the kernel declared with an IMMUTABLE origin is written
            # back by nobody, so the copy-back -- two O(n) passes plus a free,
            # per dispatch -- is pure waste. The pack is still needed: the
            # kernel reads a contiguous `T *` and a MojoList is not one.
            #
            # Conservative by construction: an annotation with no origin, or a
            # mutable one, is writable, so a kernel that writes through a
            # buffer without saying so still gets its write-back. Only an
            # explicit immutable promise skips it.
            _writable = (_spec.writable if isinstance(_spec, _gmi_glue.LaunchArg)
                         else True)
            _unpack = _gmi_glue._c_unpack_name(_elem) if _writable else None
            gen._list_marshalling_needed.add(_elem)
            _buf = gen._new_temp(f'{_elem} *')
            # The count handed to the unpacker is the SAME expression the
            # packer got. Both helpers clamp it to the list's length, and the
            # list cannot change length in between because the callee is
            # handed a plain buffer and has no way to reach the list -- so
            # recomputing the clamp on the other side is not an approximation
            # of a count the packer knew, it is the same count. (The first
            # design passed it back through an `int64_t *` out-parameter; that
            # needed an extra uninitialised pointer local at every call site,
            # which segfaults inside the helper. See _PACK_TEMPLATE.)
            _use = _len_expr if _len_expr else _count_val
            gen._emit(f'  {_buf} = {_pack}({_v}, (int64_t)({_use}));')
            _parts.append(_buf)
            if _unpack is not None:
                _unpacks.append((_v, _buf, _use, _unpack))
            else:
                # Still has to be released, just not written back -- and the
                # release must come AFTER the dispatch, like the write-back
                # does. Emitting the free here, next to the pack, frees the
                # buffer while the kernel is still reading it: measured, the
                # read-only inputs came back as garbage and the output list
                # was left at its sentinel.
                _frees.append(_buf)
            continue
        if _t != _want:
            # _safe_coerce_emit returns None -- it writes the coercion into
            # the lhs temp it is handed, so the value to pass on is the temp,
            # not a result.
            _tmp = gen._new_temp(_want)
            gen._safe_coerce_emit(_t, _want, _v, _tmp)
            _v = _tmp
        _parts.append(_v)
    gen._emit(f'  {_wname}(' + ', '.join(_parts) + ');')
    for _list_v, _buf_v, _n_v, _unpack in _unpacks:
        gen._emit(f'  if ({_buf_v}) {{')
        gen._emit(f'    {_unpack}({_list_v}, {_buf_v}, (int64_t){_n_v});')
        gen._emit(f'    free ({_buf_v});')
        gen._emit('  }')
    # Read-only buffers: released here, after the dispatch has finished
    # reading them.
    for _buf_v in _frees:
        gen._emit(f'  if ({_buf_v}) free ({_buf_v});')
    return 'void', '0'


def _lower_call(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    _dev = _lower_device_launch(gen, node)
    if _dev is not None:
        return _dev
    if (isinstance(node.func, gimple_ctypes.IdentExpr)
            and node.func.name in ('__mojo_future_add_done_callback',
                                   '__mojo_future_remove_done_callback')
            and len(node.args) == 2):
        return _lower_future_done_callback(gen, node)
    # Step I (create_task/Task/TaskGroup/RaisingTask project):
    # `create_task(f())` / `create_raising_task(f())` where `f` is a
    # supported compiled async function (top-level OR nested — a
    # nested one is only resolvable here while THIS enclosing
    # function's body is being compiled, via gen_module's scoped
    # push into self._async_api — see
    # _compile_nested_async_functions's docstring). Constructs the
    # coroutine via `{base}_start(args...)` (exactly like the
    # generator-call path elsewhere in this method) and schedules it
    # onto Step A's ready queue via `mojo_async_schedule_ready` -- but,
    # unlike `asyncio.run(...)`'s bridge, does NOT drive the scheduler
    # to completion here: real Mojo's own `create_task` returns a
    # `Task` immediately, without blocking, and this project's
    # single-threaded cooperative scheduler only actually RUNS
    # scheduled work when something later drains it (`.wait()` -- see
    # _lower_method_call's own `MojoAsync *`.`wait()` case -- or
    # another `await`). The resulting `MojoAsync *` handle is tracked
    # in self._async_var_api (mirrors self._generator_var_api's
    # identical "value -> api" side-table pattern exactly) so a later
    # `.wait()` on the variable it gets assigned to can recover which
    # extern "C" API/value_ctype to use. No structural difference is
    # made here between `create_task` and `create_raising_task` -- see
    # _lower_method_call's own docstring on why this codegen's promise
    # already stages ANY escaped exception generically regardless of a
    # `raises` annotation, so both map onto the identical handle shape.
    #
    # Checked FIRST, before ANY other dispatch in this method
    # (including the generic-import elaboration a little further
    # down): real Mojo's own `create_task`/`create_raising_task` are
    # themselves imported, generic-looking free functions from
    # `std.runtime.asyncrt` (`create_raising_task[type: Movable,
    # origins: OriginSet](...)`), so `_elaborate_generic_call` would
    # otherwise try to elaborate their REAL body (raw MLIR ops,
    # ThinAllocation, ...) instead of ever reaching this special case
    # — and worse, that path unconditionally lowers every argument
    # (`self.lower_expr(a) for a in node.args`, BEFORE its own
    # try/except) to drive type inference, which would eagerly
    # evaluate `f()` as a value-consuming call and hit THIS module's
    # own, unrelated "async function called as a value" honest
    # refusal a few hundred lines down — a confusing, wrong failure
    # for a perfectly supported create_task/create_raising_task shape.
    # Intercepting here, before that dispatch is even attempted, avoids
    # it entirely rather than trying to special-case around it deeper
    # in the shared generic-elaboration machinery.
    # `_create_task(f(...), desired_worker_id=<hint>)` (test_asyncrt.
    # mojo's `test_create_task_with_affinity_runs_coroutine`) is real
    # Mojo's own affinity-hinted variant of `create_task` -- the hint is
    # documented as purely advisory (correctness must hold whether or
    # not the runtime honours it; see that test's own docstring), and
    # this codegen's scheduler has no worker-affinity concept at all, so
    # the hint is simply dropped (still lowered via `self.lower_expr`
    # for its side effects, matching every other discarded-value
    # argument elsewhere in this file) and the call is treated exactly
    # like a bare `create_task(f(...))` -- an honest, documented
    # simplification (the hint's own contract permits this), not a
    # silent correctness gap.
    # `TaskGroup()` (test_locks.mojo's own idiom: `var tg = TaskGroup();
    # ...; tg.create_task(inc()); ...; tg.wait[origin]()`) -- real
    # Mojo's own `TaskGroup` (std/runtime/asyncrt.mojo) is a genuinely
    # deep struct (raw MLIR ops, an atomic counter, a `_Chain` low-
    # level completion primitive, a `List[_TaskGroupBox]`) nowhere near
    # reachable by this codegen's general (non-async) struct-compiling
    # path -- reinterpreted here exactly like `create_task`/
    # `create_raising_task` already are: not by compiling TaskGroup's
    # REAL body, but as a small set of intrinsics this codegen
    # understands directly. A TaskGroup is represented as a plain
    # `MojoList *` of `(int64_t)` `MojoAsync *` handles (this project's
    # EXISTING mojo_list_new/mojo_list_append_int/mojo_list_get_int/
    # mojo_list_len infrastructure, reused rather than inventing a
    # parallel dynamic-array type -- see CLAUDE.md's consolidation
    # principle) -- `self._taskgroup_var_api` (name -> {'base',
    # 'value_ctype'}, populated lazily by the FIRST `.create_task(...)`
    # call on it, see `_lower_method_call`) tags which names are really
    # task groups, mirroring `self._async_var_api`'s identical name-
    # keyed "value -> api" side-table pattern for a bare `create_task`
    # handle. Every task added to ONE group must compile to the SAME
    # async unit (an honest compile-time refusal if a second, different
    # one is ever added -- see `.create_task()`'s own check below) --
    # real Mojo's TaskGroup allows heterogeneous tasks (type-erased via
    # `_TaskGroupBox`), but every real target shape only ever adds ONE
    # kind of task to a given group, so this narrower contract is
    # honest (a hard refusal, not silent wrongness) rather than solving
    # the fully general heterogeneous case.
    # `collections.deque(...)` / `deque(...)` / `deque[T](...)` -- this
    # codegen represents a deque as a plain MojoList * (append / popleft /
    # appendleft lower onto mojo_list_* in gimple_gen_methods.py). asyncio
    # (queues.py, locks.py) uses deque as a FIFO of Future handles
    # (bugs/COMPILE_FAIL_asyncio_queues.md gap 2). Route it to the same
    # builtin lowering as list().
    _deque_base = node.func
    if isinstance(_deque_base, gimple_ctypes.SubscriptExpr):
        _deque_base = _deque_base.obj
    if ((isinstance(_deque_base, gimple_ctypes.IdentExpr)
         and _deque_base.name == 'deque'
         and not gen._locally_binds_name('deque'))
        or (isinstance(_deque_base, gimple_ctypes.MemberExpr)
            and _deque_base.member == 'deque'
            and isinstance(_deque_base.obj, gimple_ctypes.IdentExpr)
            and _deque_base.obj.name == 'collections')):
        if len(node.args) <= 1:
            return gen._lower_builtin_list(
                gimple_ctypes.CallExpr(func=gimple_ctypes.IdentExpr(name='list'),
                                       args=list(node.args), kwargs=[]))

    # Awaitable protocol (Future/Event) — BARE free-function call sites on
    # the synchronous compiled path (`create_future()` / `Event()` /
    # `Future()` called with no receiver, e.g. from a struct `__init__` or
    # any ordinary helper). Mirrors gimple_gen_methods.py's member-form
    # sync hook and gimple_gen_coro.py's async-body rewrite; same safety
    # scoping (only when this module emitted a stack-switch coroutine unit,
    # which is exactly when the shim externs are declared), and never when
    # a compiled struct defines its own same-named method/global collides.
    if (isinstance(node.func, gimple_ctypes.IdentExpr)
            and node.func.name in ('create_future', 'Event', 'Future')
            and not node.args and not getattr(node, 'kwargs', None)
            and os.environ.get('MOJO_CORO', 'stackswitch') != 'cpp'
            and (getattr(gen, '_stackswitch_coro_c_units', None)
                 or getattr(gen, '_native_future_bridge', False))
            and node.func.name not in gen.struct_field_types
            and node.func.name not in gen.func_return_types):
        shim = '__mojo_event_new' if node.func.name == 'Event' else '__mojo_future_new'
        return 'int64_t', gen._call_expr('int64_t', shim, [])

    if (isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name == 'TaskGroup'
            and not node.args and not getattr(node, 'kwargs', None)):
        handle = gen._call_expr('MojoList *', 'mojo_list_new', [])
        gen._taskgroup_var_api[handle] = {'base': None, 'value_ctype': None}
        return 'MojoList *', handle
    _ct_kwargs = getattr(node, 'kwargs', None) or []
    if (isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name == '_create_task'
            and len(node.args) == 1 and len(_ct_kwargs) == 1
            and _ct_kwargs[0][0] == 'desired_worker_id'):
        gen.lower_expr(_ct_kwargs[0][1])
        node = gimple_ctypes.CallExpr(func=gimple_ctypes.IdentExpr(name='create_task'), args=node.args, kwargs=[])
    if (isinstance(node.func, gimple_ctypes.IdentExpr)
            and node.func.name in ('create_task', 'create_raising_task')
            and len(node.args) == 1 and not getattr(node, 'kwargs', None)):
        _fname = node.func.name
        inner = node.args[0]
        # Resolve any keyword arguments on the inner call (e.g. real
        # Mojo's own `create_raising_task(conditional_raise(should_fail
        # =False))`) against the callee's real parameter order — see
        # _resolve_kwargs_for_known_async_call's own docstring; reused
        # here (not re-implemented) since this is the SAME "keyword-
        # argument call to a known async function" shape
        # _normalize_await_kwargs already handles for the `await
        # <call>` composition case, just reached from ordinary
        # (non-coroutine-body) code instead.
        gen._resolve_kwargs_for_known_async_call(inner)
        # A nested async def with no comptime bracket parameters is
        # normally captured by gen_module's own _compile_nested_async_
        # functions pass (registered into self._nested_async_api, then
        # scoped-pushed into self._async_api for this enclosing
        # function's body compile — see that pass's docstring) and
        # resolves via the self._async_api lookup just below. But
        # gen_module also has a SEPARATE, independently-built nested-
        # in-top-level-function discovery pass (the comptime-bracket-
        # parametrized one — see _async_closure_api's 'comptime_params'
        # key) that targets the identical parent shape (an ordinary
        # top-level function's body) and, for a param-less nested
        # async def, would produce an equally valid compiled unit —
        # gen_module's pass ORDERING already guarantees only one of the
        # two ever actually claims any given nested async def (each
        # pops its id out of the shared `_async_fns` on success, and
        # the other checks that first), so no double-compile occurs.
        # This fallback exists purely so create_task(...)'s own lookup
        # doesn't silently regress if a future change to that ordering
        # (or a bracket-param-free call to a function that happens to
        # be comptime-parametrized) ever lets the OTHER pass claim it
        # first instead.
        _resolved = gen._resolve_and_start_task(inner)
        if _resolved is not None:
            handle, api = _resolved
            gen._async_var_api[handle] = api
            return 'MojoAsync *', handle
        # DELIBERATE, DOCUMENTED SIMPLIFICATION (not silent wrongness —
        # see this project's own standing "honest, documented
        # simplification" standard, e.g. bugs/CODEGEN_device_context_
        # host_function_enqueue_synchronous_stub.md): the inner call
        # names a REAL `async def` somewhere in this module (found by
        # gen_module's own initial `_walk_ast` scan — self.
        # _all_async_fn_names — regardless of whether it ended up
        # eligible for this codegen's narrow C++20-coroutine path), but
        # it never got compiled (e.g. a non-scalar/String return type —
        # this codegen's shared coroutine-body emitter is deliberately
        # scalar-only throughout, see _gen_cpp_async_unit's docstring).
        # Concretely hit by test_raising_asyncrt.mojo's own
        # `test_raising_async_error_message_via_wrapper` — a test the
        # file's OWN author already disabled at its one call site in
        # `main()` (commented out, citing a genuine, separate upstream
        # Mojo MLIR bug, MOCO-3408) — so this specific function is
        # provably unreachable in that file, yet (unlike a function
        # body this codegen simply never emits) still has to COMPILE
        # since every top-level function gets a C definition regardless
        # of whether anything calls it.
        #
        # Rather than hard-refusing the WHOLE MODULE over one
        # genuinely-dead, upstream-acknowledged-broken function, this
        # emits a loud, honest RUNTIME failure in its place — a real
        # `abort()` with a diagnostic message, not a silently wrong
        # value — so if this specific call path were ever, contrary to
        # the analysis above, actually reached, it fails LOUDLY at run
        # time instead of returning a plausible-looking but bogus
        # result. Scoped narrowly to names already confirmed to be
        # real async functions (not a catch-all for any unresolved
        # name) — an undefined/typo'd name still hits the ordinary
        # hard compile-time refusal below.
        if inner.func.name in gen._all_async_fn_names:
            for a in inner.args:
                gen.lower_expr(a)  # side effects, if any
            gen._emit(
                f'  fprintf(stderr, "mojo: {_fname}({inner.func.name}(...)) '
                f'reached at runtime, but {inner.func.name!r} could not be '
                'compiled to a real coroutine by this codegen (deliberate '
                'stub -- see gimple_codegen.py\'s _lower_call comment on '
                'create_task/create_raising_task) -- aborting\\n");')
            gen._emit("  abort ();")
            handle = gen._new_val('MojoAsync *', '(MojoAsync *)0')
            # Marked 'stub' (no real base/value_ctype exists) so a
            # later `.wait()` on whatever variable this gets assigned
            # to (see _lower_method_call's own `MojoAsync *`.`wait()`
            # case) also degrades to the same abort()-based fallback
            # instead of trying to call a nonexistent extern "C" API.
            gen._async_var_api[handle] = {'stub': True}
            return 'MojoAsync *', handle
        raise RuntimeError(
            f"cannot compile module: {_fname}(...) is only "
            "supported for the shape "
            f"`{_fname}(<call to a supported compiled async "
            "function>)` -- falling back to interpreting this module "
            "from source instead")
    # __get_address_as_owned_value(addr)  →  *(int64_t *)addr
    # Mojo ownership intrinsic: load the value at a raw-pointer address.
    if isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name == '__get_address_as_owned_value' \
            and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        ptr = gen._new_temp('int64_t *')
        gen._safe_coerce_emit(at, 'int64_t *', av, ptr)
        val = gen._new_temp('int64_t')
        gen._emit(f"  {val} = *{ptr};")
        return 'int64_t', val
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr) \
            and node.func.obj.name in ('external_call', '_external_call_const'):
        return gen._lower_external_call(node)
    mlir_call = gen._maybe_lower_mlir_op(node)
    if mlir_call is not None:
        return mlir_call
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr) \
            and node.func.obj.name in gen._imported_generic_structs:
        res = gen._elaborate_generic_struct_call(node)
        if res is not None:
            return res
    if isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name in gen._imported_overloads:
        res = gen._elaborate_overload_call(node)
        if res is not None:
            return res
    _gen = (isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr)
            and node.func.obj.name in gen._imported_generics) or \
           (isinstance(node.func, gimple_ctypes.IdentExpr) and node.func.name in gen._imported_generics)
    if _gen:
        res = gen._elaborate_generic_call(node)
        if res is not None:
            return res
    # Bracket call to a nested async function/closure with its OWN
    # comptime bracket parameter(s), e.g. test_asyncrt.mojo's
    # `test_asyncrt_add[1](rhs)` (`test_asyncrt_add` is a sibling
    # nested `async def` inside the SAME enclosing function currently
    # being compiled — see gen_module's "Async closures/functions
    # NESTED INSIDE A TOP-LEVEL FUNCTION" discovery pass). The bracket
    # argument(s) were threaded through as ordinary trailing
    # parameters at definition time (in comptime_params order, before
    # any free-variable captures) — forward them here the same way.
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr):
        _acl_key2 = (gen.current_func_name, node.func.obj.name)
        _api2 = gen._async_closure_api.get(_acl_key2)
        if _api2 is not None and _api2.get('comptime_params'):
            _cp_list = _api2['comptime_params']
            _idx2 = node.func.index
            _elems2 = _idx2.elements if isinstance(_idx2, gimple_ctypes.TupleExpr) else [_idx2]
            if len(_elems2) == len(_cp_list):
                # Ordinary args FIRST, then bracket (comptime) elements,
                # then any trailing captures -- matches the callee's
                # REAL compiled signature order (_gen_cpp_async_unit:
                # `fn.params` then `extra_captures`), not bracket-
                # elements-first. See the sibling coroutine-body
                # composition site's own identical fix (a few thousand
                # lines down, `_bc9_args`) for the hand-verified repro
                # that caught this same ordering bug (masked here too
                # by every existing caller's own commutative arithmetic
                # -- never independently exercised until test_tracing.
                # mojo's real shape).
                arg_pairs2 = [gen.lower_expr(a) for a in node.args]
                arg_pairs2 += [gen.lower_expr(a) for a in _elems2]
                for cap_name, _cap_ctype in _api2['captures'][len(_cp_list):]:
                    arg_pairs2.append(gen.lower_expr(gimple_ctypes.IdentExpr(name=cap_name)))
                handle2 = gen._call_expr('MojoAsync *', f"{_api2['base']}_start", arg_pairs2)
                if _api2['value_ctype'] != 'void':
                    raise RuntimeError(
                        "cannot compile module: call to nested async "
                        f"function {node.func.obj.name!r} whose result "
                        "is consumed as a value and carries a real "
                        "return value — this codegen has no await/"
                        "top-level-run mechanism yet to drive it to "
                        "completion here (use asyncio.run(...) to "
                        "drive a single such call directly instead)")
                return 'MojoAsync *', handle2
    # bytes.fromhex / bytes.maketrans — the two CLASS-level constructors /
    # helpers with no receiver. Attribute reads on the builtin `bytes`
    # object itself have no other lowering, so they used to vanish and the
    # whole call expression came out as nothing.
    if (isinstance(node.func, gimple_ctypes.MemberExpr)
            and isinstance(node.func.obj, gimple_ctypes.IdentExpr)
            and node.func.obj.name in ('bytes', 'bytearray')
            and not gen._locally_binds_name(node.func.obj.name)):
        _cls = node.func.obj.name
        _meth = node.func.member
        if _meth == 'fromhex' and len(node.args) == 1:
            _, hv = gen.lower_expr(node.args[0])
            return 'MojoBytes *', gen._call_expr(
                'MojoBytes *', 'mojo_bytes_fromhex', [('char *', hv)])
        if _meth == 'maketrans' and len(node.args) in (2, 3):
            # `bytes.maketrans(a, b)` deletes the listed characters; the
            # three-argument form maps them onto a third value.
            ft, fv = gen.lower_expr(node.args[0])
            tt, tv = gen.lower_expr(node.args[1])
            fb = gmp._coerce_to_bytes(gen, ft, fv)
            if len(node.args) >= 3:
                # 3-arg form: the third value is a DELETE list. Python builds
                # its table by mapping the deleted bytes to THEMSELVES, which
                # is exactly the identity default the 2-arg table already has
                # — so a deleted byte is simply left untranslated, and there
                # is nothing extra to encode.
                gen.lower_expr(node.args[2])
            tb2 = gmp._coerce_to_bytes(gen, tt, tv)
            return 'MojoBytes *', gen._call_expr(
                'MojoBytes *', 'mojo_bytes_maketrans', [('MojoBytes *', fb), ('MojoBytes *', tb2)])
        if _meth == 'hex' and _cls == 'bytes' and len(node.args) == 1:
            bt, bv = gen.lower_expr(node.args[0])
            bb = gmp._coerce_to_bytes(gen, bt, bv)
            return 'char *', gen._call_expr('char *', 'mojo_bytes_hex', [('MojoBytes *', bb)])

    if isinstance(node.func, gimple_ctypes.MemberExpr):
        return gen._lower_method_call(node)
    # Subscripted method call: obj.method[TypeParam](...) — unwrap type param and route as method call.
    # A method whose comptime bracket parameter is function-typed and
    # actually used (registered in _method_threaded_comptime_params —
    # see its docstring / bugs/CODEGEN_device_context_captured_function_
    # parameter_closures_broken.md's Repro 1) is compiled with that
    # parameter as an ordinary TRAILING C parameter (_gen_struct_method),
    # so the bracket argument(s) here must be forwarded as extra
    # positional args, in the same order as the method's own
    # comptime_params — dropping them silently (the pre-existing
    # behavior, still correct for every OTHER bracket parameter: a pure
    # type-bound never referenced as a plain identifier, or an Int/Bool/
    # other comptime parameter this narrow mechanism doesn't touch)
    # left `func` unresolved inside the method body / its nested
    # closures, emitted as a bogus, never-defined bare C identifier call.
    # Python collections-module constructors: collections.Counter[T](...),
    # collections.defaultdict(...) / collections.OrderedDict(...) — in
    # bracketed AND bare form. These used to fall through to the
    # subscripted-MemberExpr METHOD dispatch below (receiver = the module
    # object's own boxed handle), whose generic fallback just ECHOED the
    # receiver back ("int64_t.Counter() stubbed") — so `stats =
    # collections.Counter[str]()` bound the MODULE handle itself as the
    # "counter", and every later `stats[k] += ...` store then wrote
    # through a bogus pointer (segfault; real repro:
    # Tools/scripts/summarize_stats.py's load_raw_data). A Counter IS a
    # dict in this codegen's model (str keys, subscript read/write, +=)
    # — construct a real MojoDict. The bracket parameter(s) are a typing
    # alias at runtime (real Python: `Counter[str]` is just Counter), so
    # they're lowered-and-discarded exactly like the List[T]/Dict[K,V]
    # block below.
    if ((isinstance(node.func, gimple_ctypes.MemberExpr)
         and isinstance(node.func.obj, gimple_ctypes.IdentExpr)
         and node.func.obj.name == 'collections'
         and node.func.member in ('Counter', 'defaultdict', 'OrderedDict'))
        or (isinstance(node.func, gimple_ctypes.SubscriptExpr)
            and isinstance(node.func.obj, gimple_ctypes.MemberExpr)
            and isinstance(node.func.obj.obj, gimple_ctypes.IdentExpr)
            and node.func.obj.obj.name == 'collections'
            and node.func.obj.member in ('Counter', 'defaultdict', 'OrderedDict'))):
        t = gen._new_val('MojoDict *', 'mojo_dict_new ()')
        for a in node.args: gen.lower_expr(a)
        return 'MojoDict *', t
    if (isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.MemberExpr)
            and node.func.obj.member in ('bitcast', 'unsafe_ptr_cast') and not node.args):
        # `ptr.bitcast[T]()` / `ptr.unsafe_ptr_cast[T]()` on a raw
        # UnsafePointer/Pointer/OwnedPointer/ArcPointer receiver — a
        # genuine pointer REINTERPRET, not a no-op. The generic
        # SubscriptExpr+MemberExpr routing just below this (shared with
        # ordinary struct methods' comptime bracket-parameter threading)
        # always stripped the bracket type entirely before forwarding to
        # `_lower_method_call`/`_lower_pointer_method` (whose own
        # `bitcast` case never saw it and could only pass the value
        # through UNCHANGED, keeping the receiver's OWN ctype) — wrong
        # whenever the receiver isn't already the requested type: e.g.
        # `UnsafePointer(to=sig).bitcast[UnsafePointer[SomeStruct]]()`
        # kept the ORIGINAL scalar pointer's ctype, so a later `[0].field`
        # dereference on the (wrongly still-scalar-pointer) result
        # mismatched (std/sys/_amdgpu.mojo's `hsa_signal_add`) — invisible
        # before `UnsafePointer(to=x)` itself worked (see bugs/CODEGEN_
        # unsafepointer_to_kwarg_dropped.md), since everything downstream
        # was already uniformly bogus. Resolved here directly, before the
        # generic bracket-stripping dispatch: a concrete target ctype
        # (from a `[T]` naming a known scalar/struct/pointer type) gets a
        # real cast; anything else (an opaque/unresolvable bracket) keeps
        # today's harmless same-type pass-through.
        _bc_ot, _bc_ov = gen.lower_expr(node.func.obj.obj)
        if _bc_ot.endswith(' *') and _bc_ot not in gen._RUNTIME_PTRS:
            _bc_idx = node.func.index
            _bc_elems = _bc_idx.elements if isinstance(_bc_idx, gimple_ctypes.TupleExpr) else [_bc_idx]
            _bc_ann = gen._type_expr_to_ann(_bc_elems[0]) if _bc_elems else None
            _bc_target = gen._resolve_type(_bc_ann) if _bc_ann else None
            # `_resolve_type` already special-cases a BARE struct name
            # (BUG-2026-030: this codegen represents every struct VALUE
            # as one level of pointer already) to `"StructName *"`
            # directly — that pointer level IS the struct's own value
            # representation, not a second indirection, so `bitcast[
            # SomeStruct]()`'s result needs no MORE pointer depth added.
            # A bracket type that's ITSELF a pointer-ctor annotation
            # (`UnsafePointer[Float32, ...]`, `Pointer[...]`, …) is
            # different: `_resolve_type` there ALSO gives one pointer
            # level (its own `X *` value representation — matching
            # `UnsafePointer[X]`'s own ctype), but `bitcast[UnsafePointer[
            # X]]()` genuinely means "reinterpret as a pointer THAT
            # HOLDS an `UnsafePointer[X]` value", i.e. a real SECOND
            # level of indirection over that already-one-level value —
            # unconditionally add one more `*` for this shape (confirmed
            # via test/asyncrt/test_nested_device_pointer_kernel.mojo's
            # `UnsafePointer(to=arg).bitcast[UnsafePointer[Float32,
            # MutAnyOrigin]]()[]`, which needs `float **`, not `float *`,
            # for the trailing `[]` deref to land on a real `float *`).
            _bc_ptr_ctor_target = (
                isinstance(_bc_ann, str) and '[' in _bc_ann
                and _bc_ann.split('[', 1)[0].strip() in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'))
            if _bc_target and _bc_ptr_ctor_target:
                _bc_target = f'{_bc_target} *'
            elif _bc_target and not _bc_target.endswith(' *') and _bc_target != 'void':
                _bc_target = f'{_bc_target} *'
            if _bc_target and _bc_target != _bc_ot:
                return _bc_target, gen._new_val(_bc_target, f'({_bc_target}){_bc_ov}')
            return _bc_ot, _bc_ov
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.MemberExpr):
        method_name = node.func.obj.member
        extra_args = []
        # Resolve the receiver's struct name cheaply (no side effects —
        # _quick_type is a pure lookup) so the (struct_name, method_name)
        # key can't cross-contaminate an unrelated struct's same-named
        # method (see _method_threaded_comptime_params' docstring for
        # why struct-name-blind keying is unsafe: std/builtin/
        # variadics.mojo's VariadicList.consume_elements — an ordinary,
        # non-generic method — vs. the unrelated VariadicPack.
        # consume_elements[elt_handler: def[idx: Int](...)]).
        _recv_ct = gen._quick_type(node.func.obj.obj)
        _struct_name = _recv_ct[:-2] if _recv_ct.endswith(' *') else _recv_ct
        orders_by_oid = gen._method_comptime_param_order.get((_struct_name, method_name))
        if orders_by_oid:
            idx = node.func.index
            # Keyword-form bracket arguments (`m[f_val=fmt.write_to[V]](...)`)
            # are kept in SubscriptExpr.attrs as (name, value) pairs — the
            # parser emits them there precisely so they survive (see its
            # "keyword-style bracket" branch); the index itself is just the
            # empty-subscript placeholder in that form. Positional form keeps
            # flowing through `index`. Dict.mojo/counter.mojo bind their
            # function-typed comptime params exclusively by keyword, so
            # ignoring attrs here silently forwarded NO function values — the
            # arity padder in _lower_struct_method_call then filled the gap
            # with literal zeros ("call through NULL" segfaults), while any
            # param NOT covered by threading degraded to the weak stub.
            _bracket_attrs = getattr(node.func, 'attrs', None) or []
            _kw_bracket = {nm: val for nm, val in _bracket_attrs if nm is not None}
            if _bracket_attrs:
                elems = [val for nm, val in _bracket_attrs if nm is None]
            else:
                elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
            # Which sibling overload does this call site's bracket-
            # argument COUNT match? Real overload resolution happens
            # deeper (in _lower_method_call, called below), which this
            # narrow, textual pre-scan doesn't have access to — but the
            # comptime-param arity alone is enough to disambiguate
            # honestly: if exactly one candidate overload's
            # comptime_params list is the same length as the bracket-
            # argument list actually supplied here, use its threaded-
            # parameter set; if zero or more than one match (genuinely
            # ambiguous), do nothing — the pre-existing "drop the
            # bracket" behavior — rather than guess and risk forwarding
            # an extra argument to an overload compiled WITHOUT a
            # matching trailing parameter.
            _candidates = [oid for oid, order in orders_by_oid.items()
                           if len(order) == len(elems) + len(_kw_bracket)]
            if len(_candidates) == 1:
                oid = _candidates[0]
                order = orders_by_oid[oid]
                threaded = gen._method_threaded_comptime_params.get((_struct_name, method_name), {}).get(oid, [])
                for i, cp_name in enumerate(order):
                    if cp_name not in threaded:
                        continue
                    _arg = _kw_bracket.get(cp_name)
                    if _arg is None and i < len(elems):
                        _arg = elems[i]
                    if _arg is not None:
                        extra_args.append(_arg)
        inner = gimple_ctypes.CallExpr(func=node.func.obj, args=list(node.args) + extra_args,
                         kwargs=getattr(node, 'kwargs', []), line=getattr(node, 'line', 0))
        return gen._lower_method_call(inner)
    # `UnsafePointer(to=x)` / `Pointer(to=x)` / `OwnedPointer(to=x)` /
    # `ArcPointer(to=x)` — the PLAIN-CALL keyword-argument constructor shape
    # (no `[T]` subscript), real Mojo's and this project's own
    # myinterpreter.py `_MojoUnsafePointerType.__call__(self, to=None,
    # **kwargs)` idiom for "address of a local". Previously this shape
    # matched none of `_lower_call`'s dispatch branches (only the
    # SubscriptExpr form `UnsafePointer[T](x)`, handled by
    # `_lower_pointer_ctor` above, was recognized) and fell all the way to
    # the generic "unresolved call" default, silently dropping the `to=`
    # argument entirely and yielding a null/zero pointer with no diagnostic.
    if (isinstance(node.func, gimple_ctypes.IdentExpr)
            and node.func.name in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer')
            and len(node.args or []) == 0):
        _to_kwargs = getattr(node, 'kwargs', None) or []
        # Explicit index loop, NOT `next((v for k, v in _to_kwargs if k ==
        # 'to'), None)`: the genexpr's 2-tuple unpack boxes both slots to
        # int64_t self-hosted, so `k == 'to'` never matched and `_to_expr`
        # stayed None — `UnsafePointer(to=value)` then fell through to the
        # null-pointer branch (`_t2 = (uint64_t *)0;` instead of `&value`;
        # repro: std/test/memory/uninit_check/test_uninit_check_float64_poison).
        _to_expr = None
        for _ki in range(len(_to_kwargs)):
            _kp = _to_kwargs[_ki]
            if _as_str(_kp[0]) == 'to':
                _to_expr = _kp[1]
                break
        if _to_expr is not None:
            # A bare-identifier `to=` target is ALWAYS already in
            # `_addressed_locals` by this point — `_seed_addressed_locals`
            # pre-scans the WHOLE function body for every such call before
            # any statement compiles (see its own docstring for why this
            # must be a whole-body pre-pass, not marked lazily here at the
            # call site). Resolved DIRECTLY to its raw C variable,
            # bypassing `_lower_IdentExpr`'s own materialize-through-a-
            # fresh-temp handling for that name (needed for ORDINARY value
            # reads of an addressed local, see that branch's own
            # docstring): taking `x`'s address needs `x`'s own identity,
            # not the address of a throwaway temp holding a copy of its
            # value at some other read site — a real, hand-hit segfault
            # from a naive first version of this fix that only bypassed
            # materialization for a name's SECOND `to=` occurrence.
            _is_ident = isinstance(_to_expr, gimple_ctypes.IdentExpr)
            _tname = ''
            if _is_ident:
                _tname = _as_str(_as_ident_node(_to_expr).name)
            if _is_ident and _tname in gen._addressed_locals:
                at = gen._type_of(_tname)
                av = gen._c_names.get(_tname, _tname)
            else:
                at, av = gen.lower_expr(_to_expr)
            if at.endswith(' *'):
                # `to=` names a struct-typed local/param/field: this
                # codegen already erases `SomeStruct`-typed values straight
                # to `SomeStruct *` (BUG-2026-030 — see _lower_pointer_ctor's
                # own docstring), so the value in hand IS already "the
                # address of the struct" — no separate address-of needed.
                return at, av
            # Scalar `to=`: need the real address of the C variable backing
            # it. Only a genuine declared local/parameter (not an arbitrary
            # expression's throwaway temp) is safely addressable this way.
            # NOT `_scalar_arg_is_addressable_local` (BUG-2026-016's
            # out-parameter-aliasing check): that helper excludes any name
            # tracked in `_actual_types`/`_global_var_types` because ITS
            # narrower purpose is telling an opaque-pointer-boxed-as-
            # int64_t handle apart from a genuine numeric local when `at
            # == 'int64_t'` — irrelevant here, since a struct/container
            # pointer already returned via the `at.endswith(' *')` branch
            # above, so reaching this point means `at` is ALREADY a
            # concrete non-pointer scalar ctype (uint64_t, double, …).
            # Reusing that helper wholesale rejected every well-typed
            # scalar PARAMETER whose ctype isn't literally 'int64_t' (ANY
            # UInt64/Float64/Int32/… parameter gets registered into
            # `_actual_types` purely so OTHER dispatch sites can recover
            # its real type — see the param-registration comment in
            # gimple_gen_funcs.py — which made `_scalar_arg_is_addressable_
            # local` treat it as a suspected disguised pointer and silently
            # fall through to the null-pointer branch below instead —
            # confirmed via std/sys/_amdgpu.mojo's `hsa_signal_add(sig:
            # UInt64, ...)`, `UnsafePointer(to=sig)`).
            if isinstance(_to_expr, gimple_ctypes.IdentExpr) and gen._addressable_to_target(at, av):
                # `-fgimple` rejects a stack local's address being taken
                # ANYWHERE in the function if that same local is also
                # cast-assigned or directly `return`ed/read-raw elsewhere
                # in the SAME function ("non-register as LHS of unary
                # operation" / "invalid operand in return statement" —
                # the identical restriction `_seed_mut_captured_local_
                # types` documents and works around by heap-boxing for
                # the `{mut}`-capture case). `_seed_addressed_locals`
                # already pre-registered this name in `_addressed_locals`
                # before this function's body started compiling, so
                # `_lower_IdentExpr` materializes every OTHER read of it
                # (before or after this statement) through a fresh
                # register temp instead of handing back the now-
                # addressable variable directly — sidesteps the
                # restriction for the realistic "take address, mutate via
                # callee, then read/return" idiom this constructor shape
                # exists for, without needing this local's ctype known
                # ahead of its own VarDecl (infeasible in general for an
                # unannotated `var result = Self()` — see bugs/CODEGEN_
                # unsafepointer_to_kwarg_dropped.md).
                ptr_ctype = f'{at} *'
                return ptr_ctype, gen._new_val(ptr_ctype, f'&{av}')
            # Not a directly-addressable lvalue (e.g. a call-result temp) —
            # an honest null pointer rather than aliasing dead storage.
            ptr_ctype = f'{at} *'
            return ptr_ctype, gen._new_val(ptr_ctype, f'({ptr_ctype})0')
    # Generic container constructors: List[T](...), Dict[K,V](...), Set[T](...), Optional[T](...)
    if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr):
        base = node.func.obj.name
        # An EMPTY `List[T]()` / `Dict[K, V]()` / `Set[T]()` is a container
        # literal in all but spelling: it takes the stack storage the solver
        # reserved for the statement, or a fresh heap one, and is registered
        # fresh, exactly as `[]` / `{}` are.
        _generic_ctype = {'List': 'MojoList *', 'Dict': 'MojoDict *',
                          'Set': 'MojoSet *'}.get(base, '')
        if _generic_ctype != '' and not node.args and len(node.kwargs or []) == 0:
            t = gen._new_temp(_generic_ctype)
            gen._emit_container_new(t, _generic_ctype)
            gen._note_fresh_result(t)
            return _generic_ctype, t
        if base in ('List', 'InlineList', 'SmallVector', 'DynamicVector', 'InlineArray',
                    'Buffer', 'NDBuffer'):
            t = gen._new_val('MojoList *', 'mojo_list_new ()')
            for a in node.args: gen.lower_expr(a)
            return 'MojoList *', t
        if base in ('Dict', 'OrderedDict'):
            t = gen._new_val('MojoDict *', 'mojo_dict_new ()')
            for a in node.args: gen.lower_expr(a)
            return 'MojoDict *', t
        if base in ('Set', 'FrozenSet'):
            t = gen._new_val('MojoSet *', 'mojo_set_new ()')
            for a in node.args: gen.lower_expr(a)
            return 'MojoSet *', t
        if base == 'Optional':
            if node.args:
                at, av = gen.lower_expr(node.args[0])
                t = gen._new_val('int64_t', f'(int64_t){av}' if at.endswith(' *') else av)
                return 'int64_t', t
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            return _lower_pointer_ctor(gen, node)
    if not isinstance(node.func, gimple_ctypes.IdentExpr):
        # Calling the RESULT of a call expression directly —
        # `factory()(5)`, `make_adder2(100)(2)`, `pick(1)(x)` — where the
        # inner call returns a first-class callable VALUE. Previously
        # stubbed to 0 (silently wrong; returned 0 instead of calling).
        # Dispatch on the inner value's type exactly like an ordinary
        # identifier-backed call: a `MojoBoundMethod *` (a capturing
        # closure / bound method bundle) re-supplies its env via
        # mojo_bound_method_call_N; a bare function pointer
        # (`void *`/int64_t-boxed, a non-capturing closure or free fn)
        # goes through mojo_fnptr_call_N.
        # ONLY a CallExpr callee (a genuine chained call) and a
        # LambdaExpr callee (an immediately-invoked lambda — a real
        # runtime callable value) are value-lowered here. A
        # SubscriptExpr callee is a GENERIC TYPE/constructor expression
        # (`Scalar[x.dtype](...)` — a comptime bracket argument, not a
        # runtime value), whose eager value-lowering would miscompile
        # (found via math.mojo's `Scalar[x.dtype](...)`); those keep the
        # old stub.
        if isinstance(node.func, (gimple_ctypes.CallExpr, gimple_ctypes.LambdaExpr)):
            _callee_t, _callee_v = gen.lower_expr(node.func)
            if _callee_t == 'MojoBoundMethod *':
                return gen._lower_bound_method_call_value(_callee_v, node)
            if _callee_t == 'void *' or _callee_t in ('int', 'int64_t', '_Bool'):
                return gen._lower_fnptr_call_value(_callee_t, _callee_v, node)
        # `SomeGeneric[ExplicitArg](args)` where SomeGeneric ALSO has
        # implicit/inferred bracket params this elaborator can't bind
        # (e.g. std.python.numpy.from_numpy_array[mut, //, dtype,
        # origin] — only `dtype` is ever passed explicitly; `mut`/
        # `origin` are inferred from the argument's own lifetime, which
        # this codegen has no model for) never reaches
        # _elaborate_generic_call's success path and falls all the way
        # here. Stubbing to a bare int64_t 0 (below) is fine on its
        # own, but a caller doing `for x in from_numpy_array(...):`
        # then hits _gen_for_iter's boxed-dict/list runtime-dispatch
        # fallback (the ONLY thing an opaque int64_t can mean there),
        # which unconditionally declares the loop var `char *` (the
        # dict-key type) — a hard C type error once the loop body uses
        # it as anything else (`total: Float64 ... total += value`,
        # real, in stdlib's test_numpy.mojo). Reading just the callee's
        # OWN `-> ReturnType:` annotation and resolving its outer
        # container shape (Span/List/Dict/Set) lets the stub return a
        # well-typed NULL of the right pointer kind instead — the for
        # loop then correctly takes the "no iterator protocol" path
        # and drops the loop body (still functionally a stub, but one
        # that compiles) rather than colliding types.
        if isinstance(node.func, gimple_ctypes.SubscriptExpr) and isinstance(node.func.obj, gimple_ctypes.IdentExpr):
            _static_ct = gen._static_generic_return_ctype(node.func.obj.name)
            if _static_ct is not None:
                for a in node.args: gen.lower_expr(a)
                t = gen._new_val(_static_ct, f'({_static_ct})0')
                gimple_ctypes._debug_note('un-elaboratable generic call statically-typed stub',
                            (node.func.obj.name, _static_ct))
                return _static_ct, t
        gimple_ctypes._debug_note('indirect call stubbed', type(node.func).__name__)
        t = gen._new_temp('int64_t')
        gen._emit(f'  {t} = (int64_t)0;  /* indirect call via {type(node.func).__name__} */')
        return 'int64_t', t

    fname_raw = gen._ident_call_name(node.func)
    # `String(x)` is the same operation as `str(x)`, and the interpreter
    # already treats it that way (`String(7)` -> '7' — see
    # myinterpreter's _setup_builtins). Normalize the name here, ONCE, so
    # every `str` special case below applies to the capitalized spelling
    # too, instead of each needing its own duplicate.
    #
    # Without it, `String(i)` fell through to the generic call path and was
    # emitted as a plain C cast of the argument — `"item" + String(i)`
    # became `mojo_str_cat("item", (char *)(int64_t)i)`, concatenating the
    # raw pointer/integer bits as a string (real repro: a generator building
    # 'item0'/'item1'/'item2' printed 'item' three times, then would have
    # crashed on a real pointer value).
    #
    # ONE argument only. `String(a, b, c, ...)` is real Mojo's multi-part
    # string builder (static_tuple.mojo's `return String("StaticTuple[",
    # reflect[...].name(), ", ", ...)`), NOT a `str()` call — aliasing it
    # routed those to `mojo_str` and produced "too many arguments to
    # function 'mojo_str'; expected 1, have 6" across a dozen stdlib files.
    # Those keep whatever lowering they had before.
    #
    # `Int`/`Float`/`Bool` are deliberately NOT aliased, even though the
    # interpreter maps them to `int`/`float`/`bool`: this codegen's own
    # generic call path already lowers them correctly, including for a
    # STRUCT argument (`Int(BFloat16(3.0))` in
    # test/builtin/test_bfloat16.mojo), where the `int` builtin's
    # stringifying path instead emitted "cannot convert to a pointer type".
    # Only `String` had a real wrong-answer bug to fix.
    #
    # Gated on the name not being locally bound, exactly like every
    # `str`/`int`/... special case below: a module may define its own
    # `def String(...)` (Lib/locale.py defines its own `str`), and the
    # alias must not steal that call.
    if (fname_raw == 'String' and len(node.args) == 1
            and not gen._locally_binds_name('String')
            and not gen._locally_binds_name('str')):
        fname_raw = 'str'
    if fname_raw.startswith('mojo_python_'):
        gen._python_api_needed = True
    # An async closure NESTED INSIDE THIS METHOD (device_context.mojo's
    # `async def wrapper(...) capturing -> None:` shape — see
    # gen_module's dedicated discovery pass / _async_closure_api).
    # Constructs via `{base}_start(<ordinary args>, <captures>)`,
    # mirroring the top-level-async-function construct convention
    # exactly (Step B: never runs the body immediately). Captures are
    # read HERE, at the call site, as ordinary already-in-scope
    # identifiers (this method's own param/threaded-comptime-param) —
    # not pre-populated into an env struct at the nested `async def`
    # statement itself (see _gen_stmt_FunctionDef's matching skip).
    _acl_key = (gen.current_func_name, fname_raw)
    if _acl_key in gen._async_closure_api:
        handle, vct = gen._lower_async_closure_construct(_acl_key, node)
        if vct != 'void':
            raise RuntimeError(
                "cannot compile module: call to nested async closure "
                f"{fname_raw!r} whose result is consumed as a value "
                "and carries a real return value — this codegen has no "
                "await/top-level-run mechanism yet to drive a nested "
                "async closure to completion and read a real value "
                "back out of it; only a void-returning nested async "
                "closure (device_context.mojo's own shape) may have its "
                "raw, un-driven handle captured this way")
        return 'MojoAsync *', handle
    # Milestone B: `counter()` where `counter` is a supported generator
    # function — constructs the coroutine (via its C++20-emitted
    # `<base>_start()`) WITHOUT running any body code yet, matching real
    # Python/Mojo "calling a generator function returns a generator
    # object" semantics. Checked before every other CallExpr special
    # case below (mirrors how `_gen_for_iter`'s .finditer() structural
    # check runs before the generic path) since a generator call must
    # never fall through to the ordinary function-call lowering (there is
    # no ordinary C function with this name to call — see gen_module's
    # Phase 2a skip for _supported_generators).
    if fname_raw in gen._generator_api:
        return 'MojoGenerator *', _emit_generator_start_call(
            gen, node, gen._generator_api[fname_raw], fname_raw)
    # Same construction, but the callee is a generator this module only
    # knows through an (optionally aliased) cross-module import (`from a
    # import walk as walk_a`): _imported_generator_bindings — populated at
    # each FromImportStmt site from the whole-program _generator_home_api
    # registry, keyed (defining module's qualifier, ORIGINAL function
    # name) so two sibling modules' same-named generators stay distinct —
    # carries the defining module's own api entry ('base' is already the
    # DEFINING module-qualified `_mojogen_<qual>_<name>`, matching the
    # coroutine translation unit that module's compile emitted). Without
    # this branch the call fell through to the ordinary-function lowering,
    # emitting a call to a plain `<qual>_<name>_<overload-suffix>` symbol
    # no module ever defines ("too many arguments to function 'a_walk_...';
    # expected 0" — Phase 2a skips ordinary emission for compiled
    # generators, and the arity came from a guessed bare extern).
    # func_param_types/_func_param_defaults are per-GimpleGen (the api's
    # params were registered in the DEFINING temp_gen's own dicts), so the
    # binding's own 'params'/'defaults' snapshot seeds THIS gen's dicts
    # before emission — setdefault, never overwrite: a same-named local
    # definition must keep winning (it takes the _generator_api branch
    # above first anyway).
    _imp_gen_api = getattr(gen, '_imported_generator_bindings', {}).get(fname_raw)
    if _imp_gen_api is not None:
        gen.func_param_types.setdefault(
            f"{_imp_gen_api['base']}_start", list(_imp_gen_api.get('params') or []))
        if _imp_gen_api.get('defaults'):
            gen._func_param_defaults.setdefault(
                f"{_imp_gen_api['base']}_start", list(_imp_gen_api['defaults']))
        return 'MojoGenerator *', _emit_generator_start_call(
            gen, node, _imp_gen_api, fname_raw)
    # Step B (revised — see bugs/CODEGEN_compiled_async_eager_execution_
    # semantic_mismatch.md): `f()` where `f` is a supported compiled
    # async function, with its result actually CONSUMED as a value
    # (assigned, passed as an argument, ...). Calling an async function
    # NEVER runs its body — it produces a not-yet-started coroutine
    # object (real Python semantics; this project's own interpreter's
    # MojoCoroutine matches). The correct lowering is therefore to
    # CONSTRUCT the coroutine handle ({base}_start) and return it as a
    # first-class MojoAsync* value — the body never runs until/unless
    # something later drives it (await / a top-level driver). Used for
    # real by types.py's metaprogramming idiom
    # `async def _c(): pass; _c = _c()` (a coroutine object created for
    # type(_c)/.close() without ever being run).
    if fname_raw in gen._async_api:
        api = gen._async_api[fname_raw]
        arg_pairs = [gen.lower_expr(a) for a in node.args]
        handle = gen._call_expr('MojoAsync *', f"{api['base']}_start", arg_pairs)
        gen._async_var_api[handle] = api
        return 'MojoAsync *', handle
    # next(g) where `g` is (or holds) a MojoGenerator* — the compiled-
    # generator "first-class value" gap (bugs/CODEGEN_compiled_generator_
    # not_first_class_value.md, second failure): previously `next` had NO
    # real lowering at all anywhere in this file (only a variadic FIXME
    # extern declaration for the generic builtin — see the `next` entry
    # in the always-declared-externs table — that has no definition
    # anywhere and fails at LINK time, not compile time, for ANY use of
    # next(), not just on generators; confirmed via grep, there is no
    # pre-existing "next() on some other iterable type" convention to
    # reuse here). Mirrors _gen_for_generator_iter's own resume()/value()
    # driving exactly (same "returns 2 things" scheme, not invented
    # fresh), but signals exhaustion as a real StopIteration exception
    # via the SAME mojo_exc_type_set()/mojo_raise() mechanism
    # _gen_stmt_RaiseStmt uses for `raise StopIteration`, rather than a
    # third, novel signaling convention — so `except StopIteration:`
    # around a next() call in the same function catches it correctly.
    # `next(<generator expression>[, default])` — checked before the two
    # MojoGenerator* forms below, which only match a real coroutine handle
    # and would otherwise let a comprehension argument fall through to the
    # undefined variadic `next(...)` stub. See _lower_next_over_comprehension.
    if (fname_raw == 'next' and 1 <= len(node.args) <= 2
            and isinstance(node.args[0], gimple_ctypes.Comprehension)
            and not gen._locally_binds_name('next')):
        return _lower_next_over_comprehension(gen, node)
    # `next(it)` / `next(it, default)` on a resumable list-iterator local
    # (bound earlier by `it = iter(<list>)`, tracked in `_list_iter_cursor`).
    # Reads the element at the shared cursor and advances it; exhaustion
    # raises a real tagged StopIteration via the SAME mojo_exc_type_set()/
    # mojo_raise() path `raise StopIteration` and next()-on-a-generator use
    # (so an enclosing `except StopIteration:` catches it), unless a 2nd
    # `default` argument opts out — real Python `next(it, default)` semantics.
    if (fname_raw == 'next' and 1 <= len(node.args) <= 2
            and isinstance(node.args[0], gimple_ctypes.IdentExpr)
            and node.args[0].name in getattr(gen, '_list_iter_cursor', {})
            and not gen._locally_binds_name('next')):
        return _lower_next_list_iter(gen, node)
    if fname_raw == 'next' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        at = gen._get_actual_type(at, av)
        if at == 'MojoGenerator *':
            api = gen._generator_var_api.get(av)
            if api is not None:
                return _lower_generator_next(gen, av, api)
            gimple_ctypes._debug_note('next() on MojoGenerator* with no known _generator_var_api entry '
                        '(unreachable in normal use — see assign-then-next() propagation)', av)
    # next(g, default) — same MojoGenerator* driving as the 1-arg form
    # above, but exhaustion returns `default` instead of raising
    # StopIteration (real Python semantics: the 2-arg form is exactly
    # how callers opt OUT of the exception — e.g. importlib/resources/
    # _itertools.py's `first_value = next(it, default)`). Before this,
    # the 2-arg form fell through to the SAME declared-but-never-
    # defined variadic `next(...)` stub the 1-arg form used to hit
    # (undefined symbol at link time), since the check above only
    # matched `len(node.args) == 1`.
    if fname_raw == 'next' and len(node.args) == 2:
        at, av = gen.lower_expr(node.args[0])
        at = gen._get_actual_type(at, av)
        if at == 'MojoGenerator *':
            api = gen._generator_var_api.get(av)
            if api is not None:
                base, vct = api['base'], api['value_ctype']
                resumed = gen._new_val('_Bool', f"{base}_resume ({av})")
                result = gen._new_temp(vct)
                bb_ok = gen._new_bb(); bb_exhausted = gen._new_bb(); bb_merge = gen._new_bb()
                gen._emit(f"  if ({resumed}) goto {bb_ok}; else goto {bb_exhausted};")
                gen._emit_label(bb_ok)
                ok_val = gen._new_val(vct, f"{base}_value ({av})")
                gen._safe_coerce_emit(vct, vct, ok_val, result)
                gen._emit(f"  goto {bb_merge};")
                gen._emit_label(bb_exhausted)
                # `default` is only evaluated on the exhausted branch —
                # real Python semantics (a non-trivial default expr must
                # not run when the iterator actually yields a value).
                dt, dv = gen.lower_expr(node.args[1])
                gen._safe_coerce_emit(dt, vct, dv, result)
                gen._emit(f"  goto {bb_merge};")
                gen._emit_label(bb_merge)
                return vct, result
    # A local variable of a callable struct type, invoked like a function:
    # obj(args) → obj.__call__(args).
    if (fname_raw in gen.var_types and fname_raw not in gen.func_return_types
            and fname_raw not in gen._global_inline_defs):
        _csn = gimple_exprtypes._struct_name_of(gen.var_types[fname_raw])
        if _csn and _csn in getattr(gen, '_callable_structs', set()):
            _cm = gimple_ctypes.MemberExpr(obj=node.func, member='__call__',
                             line=getattr(node, 'line', 0))
            return gen._lower_method_call(gimple_ctypes.CallExpr(
                func=_cm, args=node.args,
                kwargs=getattr(node, 'kwargs', []), line=getattr(node, 'line', 0)))
    # Only redirect to the synthesized entry point when 'main' really is
    # this module's own entry-point function. `from foo import main;
    # main()` (e.g. Lib/idlelib/idle.py) binds 'main' to an *imported*
    # function with its own real signature — rewriting that call to
    # _gimple_main/_lib_main mismatches the synthesized stub's signature
    # and produces "conflicting types for '_gimple_main'".
    if (fname_raw == 'main' and gen.current_func_name != 'main'
            and fname_raw not in gen.imported_symbols
            and fname_raw not in gen._unresolved_import_aliases):
        if gen.emit_entry_points:
            fname_raw = '_gimple_main'
        else:
            _mod_id = gen.module_name.replace('.', '_').replace('-', '_') if gen.module_name else ''
            fname_raw = f"_{_mod_id}_main" if _mod_id else '_lib_main'
        # _lower_named_call's missing-arg padding (below, via
        # self.func_param_types.get(fname_raw, [])) looks up the
        # RENAMED symbol, but _collect_function_param_types registered
        # main's arity under its original name 'main' — so a call with
        # fewer args than main declares (relying on a default, e.g.
        # `def main(args=None): ...` called as bare `main()`) found no
        # expected_params here and never got padded, unlike the exact
        # same call written as a bare top-level statement (a separate,
        # unaffected code path). Only reachable as a *nested* call
        # (`sys.exit(main())`, `identity(main())`, ...) — found via
        # mojolib BUG-2026-032's transpiler.mojo. Mirror the arity under
        # the new key too, so the lookup below succeeds either way.
        if 'main' in gen.func_param_types and fname_raw not in gen.func_param_types:
            gen.func_param_types[fname_raw] = gen.func_param_types['main']
        # Same problem one step further down _lower_named_call: its
        # "completely unknown name" auto-stub check
        # (fname_raw not in self.func_return_types and ...) also looks
        # up the renamed symbol, found nothing (func_return_types has
        # 'main', not '_gimple_main'), and treated the call as an
        # opaque external function — emitting a variadic
        # `int64_t _gimple_main (...);` stub that conflicts with the
        # real, concretely-typed definition ("conflicting types for
        # '_gimple_main'; have 'int64_t(int64_t)'").
        if 'main' in gen.func_return_types and fname_raw not in gen.func_return_types:
            gen.func_return_types[fname_raw] = gen.func_return_types['main']

    # Builtin dispatch
    if fname_raw == 'strided_load' and node.args:
        return gen._lower_strided(node, store=False)
    if fname_raw == 'strided_store' and len(node.args) >= 2:
        return gen._lower_strided(node, store=True)
    # `_locally_binds_name` gate: `len` is an ordinary identifier a
    # module could shadow with its own top-level def — same class of
    # gate as `open`/`filter`/`any`/`all` elsewhere in this file (no
    # confirmed real-world stdlib instance found for `len` specifically,
    # but the gate is a single cheap lookup and keeps this dispatch
    # consistent with every other BUILTIN_VALUE_MAP-adjacent name).
    if (fname_raw == 'len' and node.args
            and not gen._locally_binds_name('len')):
        return gen._lower_builtin_len(node)
    # BUG-2026-028: `addr(x)` had NO real lowering at all — any call fell
    # through to a declared-but-never-defined variadic stub
    # (`int64_t addr(...);`), an undefined symbol at link time (same shape
    # of gap `ord`/`chr` used to have, fixed just below). Struct locals/
    # globals/params, UnsafePointer values, and MojoList*/MojoDict*/
    # MojoSet* are ALL already represented as a real C pointer at this
    # codegen's C level (see BUG-2026-030's "structs are always T *"
    # convention and `_lower_pointer_ctor`/`.data` for UnsafePointer) — for
    # any of those, the value already IS its own address, so `addr(x)` is
    # just `x` reinterpreted as an integer, exactly like `.address`.
    # Scoped to that case only: taking the real address of a plain SCALAR
    # local's stack slot is a separate, harder problem this codegen has no
    # support for (`-fgimple` rejects an address-taken local that is later
    # cast or returned — see the general {mut}-capture-spec closure fix's
    # heap-boxing workaround for the same underlying constraint) and is
    # left as the pre-existing undefined-symbol gap for that shape.
    if fname_raw == 'addr' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        if at.endswith(' *'):
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')
    # ord()/chr() had NO real lowering at all — any call fell through to
    # a declared-but-never-defined variadic stub (`int64_t ord(...);`),
    # an undefined symbol at link time. Found via regex_compile.py's own
    # ord(c) calls. mojo_ord/mojo_chr operate on the first byte only
    # (this codebase's strings are plain bytes, not full Unicode).
    if fname_raw == 'ord' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        if at == 'char':
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')
        if at not in ('char *', 'MojoStr *'):
            av = gen._new_val('char *', f'(char *){gen._ensure_local(at, av)}')
        return 'int64_t', gen._call_expr('int64_t', 'mojo_ord', [('char *', av)])
    if fname_raw == 'chr' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        av64 = av if at == 'int64_t' else gen._new_val('int64_t', f'(int64_t){av}')
        return 'char *', gen._call_expr('char *', 'mojo_chr', [('int64_t', av64)])
    if fname_raw == 'isinstance'      and len(node.args) == 2:  return gen._lower_builtin_isinstance(node)
    # `_locally_binds_name` gate: a module can define its OWN top-level
    # `any`/`all` (e.g. tokenize.py's `def any(*choices): return
    # group(*choices) + '*'`, called with exactly 1 arg at
    # `Ignore = Whitespace + any(r'\\\r?\n' + Whitespace) + maybe(...)`).
    # Without this gate, that call was misrouted to the builtin
    # all-args-truthy/any-args-truthy runtime helper instead of the
    # user's own function — same class of bug as the `open` gate just
    # below, and the same fix.
    if (fname_raw in ('all', 'any') and len(node.args) == 1
            and not gen._locally_binds_name(fname_raw)):
        return gen._lower_builtin_all_any(fname_raw, node)
    # `_locally_binds_name` gates below: `dir`/`sorted`/`zip`/`set`/
    # `frozenset`/`dict`/`list`/`tuple` are all ordinary identifiers a
    # module could shadow with its own top-level def/import — same class
    # of gate as `open`/`filter`/`any`/`all`/`len` elsewhere in this
    # file. `__import__` is left unguarded: it is not a plausible name
    # for real Python source to redefine as an ordinary function.
    if fname_raw == 'dir' and not gen._locally_binds_name('dir'):
        return gen._lower_builtin_dir(node)
    if (fname_raw == 'sorted' and node.args
            and not gen._locally_binds_name('sorted')):
        return gen._lower_builtin_sorted(node)
    # `zip(...)` as a VALUE (not as a `for` iterable — that has its own
    # tuple-target lowering in emit_loops). The threshold is 2, not >2: the
    # 2-argument form used to fall through to BUILTIN_VALUE_MAP's `mojo_zip`
    # with its arguments UNMATERIALIZED, so a generator argument was walked
    # as if it were a list header (a hard crash).
    if (fname_raw == 'zip' and len(node.args) >= 2
            and not gen._locally_binds_name('zip')):
        return _lower_builtin_zip_n(gen, node)
    # map(f, xs) / filter(f, xs) in VALUE position. Intercepted only when the
    # name does NOT resolve to a real user/stdlib function, mirroring the
    # `reversed` gate below, and only for the one-iterable forms the lowering
    # implements (both refuse anything else honestly).
    if (fname_raw in ('map', 'filter') and len(node.args) == 2
            and not gen._locally_binds_name(fname_raw)
            and fname_raw not in gen.func_return_types
            and fname_raw not in getattr(gen, '_imported_func_home', ())
            and fname_raw not in getattr(gen, '_own_imported_func_home', ())):
        if fname_raw == 'map':
            return _lower_builtin_map(gen, node)
        return _lower_builtin_filter(gen, node)
    if (fname_raw == 'reversed' and len(node.args) == 1
            and not gen._locally_binds_name('reversed')
            and 'reversed' not in gen.func_return_types
            and 'reversed' not in getattr(gen, '_imported_func_home', ())
            and 'reversed' not in getattr(gen, '_own_imported_func_home', ())):
        # Only intercept `reversed(x)` when the name does NOT resolve to a real
        # (user/stdlib) `reversed` free function — the real stdlib
        # `std/builtin/reversed.mojo` defines overloads that call
        # `value.__reversed__()`, and those (plus `reversed(range(...))`,
        # `reversed(<deque>)`, `reversed(<Span>)`, ...) must keep routing to
        # the generic call path. This builtin lowering is for the
        # do_imports=False / no-prelude case (e.g. the zipfile probe:
        # `reversed(sorted(self.filelist, ...))`) where `reversed` is
        # otherwise an unresolved stub producing a silently-dropped loop.
        #
        # The argument's STATIC type is deliberately not part of this gate.
        # It used to be, and that is what made the named offender in
        # FORMAL.md §11.2 real: an unannotated parameter lowers to a boxed
        # `int64_t`, so `_quick_type` answered `int64_t`, the gate closed,
        # and the call fell to `BUILTIN_VALUE_MAP`'s `mojo_reversed` —
        # a `('void *', ['void *'])` identity stub. `for x in
        # reversed(scopes)` then iterated a `void *` this backend can only
        # refuse, so the loop ran zero times (emit_funcs.py's
        # `_in_any_import_frame` had to be rewritten to avoid `reversed`
        # for exactly this reason).
        #
        # The static-type test was also redundant: the guards above it —
        # the ones that stop a real user/stdlib `reversed` from being
        # hijacked — are the actual precondition, and
        # `_lower_builtin_reversed` handles every argument shape itself,
        # including (as of the boxed arm below) the one this gate used to
        # exclude.
        return gen._lower_builtin_reversed(node)
    if fname_raw == '__import__':                                return gen._lower_builtin_import(node)
    if (fname_raw in ('set', 'frozenset')
            and not gen._locally_binds_name(fname_raw)):
        return gen._lower_builtin_set(node)
    if fname_raw == 'dict' and not gen._locally_binds_name('dict'):
        return gen._lower_builtin_dict(node)
    if (fname_raw in ('list', 'tuple') and len(node.args) <= 1
            and not gen._locally_binds_name(fname_raw)):
        return gen._lower_builtin_list(node)
    if fname_raw == 'open'            and not gen._locally_binds_name('open'):
        return gen._lower_builtin_open(node)
    if fname_raw == 'Self':                                      return gen._lower_self_ctor(node)
    # iter(x) — the container is already iterable (for-loops consume it directly),
    # so model the builtin as identity rather than emitting an undefined `iter` call.
    if fname_raw == 'iter' and len(node.args) == 1 and 'iter' not in gen.func_return_types:
        return gen.lower_expr(node.args[0])

    # repr(x): dispatch by the argument's own static type instead of
    # boxing everything through one generic runtime function. The old
    # single mojo_repr(int) both truncated any 64-bit value AND treated
    # a string/list/struct pointer as a plain integer, printing a
    # plausible-looking-but-wrong decimal number for anything that wasn't
    # a small int. Real strings need quoting (Python's repr("hi") ==
    # "'hi'"); anything else (list/dict/set/struct pointer) has no
    # runtime field-metadata table to reconstruct a real Python repr
    # from, so it's formatted as an address rather than silently
    # mistaken for a number. Found via fire.py's own `--dump`'s
    # `repr(ast)` on a parsed AST list.
    if fname_raw == 'repr' and node.args:
        rat, rav = gen.lower_expr(node.args[0])
        return 'char *', gen._repr_value(rat, rav)

    # bytes(...): construct a MojoBytes value.
    #   bytes()            -> empty
    #   bytes(<int n>)     -> n zero bytes
    #   bytes(<list ints>) -> those bytes
    #   bytes(<bytes>)     -> copy (returned as-is; MojoBytes is immutable)
    #   bytes(<str>[, enc]) -> encode (utf-8 / ascii; source is already UTF-8)
    if (fname_raw == 'bytes' and not gen._locally_binds_name('bytes')
            and len(node.args) <= 3):
        if len(node.args) == 0:
            return 'MojoBytes *', gen._new_val('MojoBytes *', 'mojo_bytes_empty ()')
        at, av = gen.lower_expr(node.args[0])
        for _extra in node.args[1:]:
            gen.lower_expr(_extra)
        if gen._bytes_subclass_of(at):
            # `bytes(<X(bytes) instance>)` -> a plain copy of its payload.
            av = gen._new_val('MojoBytes *', f"{av}->_data")
            at = 'MojoBytes *'
        if at == 'MojoBytes *':
            # A real independent copy: the arg may be a bytearray (same C
            # type), and `bytes(ba)` must not alias its mutable buffer.
            return 'MojoBytes *', gen._call_expr(
                'MojoBytes *', 'mojo_bytes_copy', [('MojoBytes *', av)])
        if at == 'MojoMemoryView *':
            return 'MojoBytes *', gen._call_expr(
                'MojoBytes *', 'mojo_memoryview_tobytes', [('MojoMemoryView *', av)])
        if at in ('char *', 'MojoStr *'):
            sv = av if at == 'char *' else gen._stringify_value(at, av)
            enc = gen._new_val('char *', gen._intern_string('utf-8'))
            return 'MojoBytes *', gen._call_expr(
                'MojoBytes *', 'mojo_bytes_from_str',
                [('char *', sv), ('char *', enc)])
        if at in ('MojoList *', 'MojoDict *', 'MojoSet *', 'void *'):
            # `bytes(a_dict)`/`bytes(a_set)` of ints is real Python (an
            # iterable of ints is a valid bytes() source; a dict's own
            # iteration yields its keys) — DESIGN.html R1/R5, shares
            # _materialize_as_list with the tuple/list-unpack sites.
            lv = gen._materialize_as_list(at, av)
            return 'MojoBytes *', gen._call_expr(
                'MojoBytes *', 'mojo_bytes_from_list', [('MojoList *', lv)])
        # int / bool / other scalar -> zero-filled bytes of that length
        nv = gen._to_int64(at, av)
        return 'MojoBytes *', gen._call_expr(
            'MojoBytes *', 'mojo_bytes_zeros', [('int64_t', nv)])

    # bytearray(...): mutable bytes. Same C representation as bytes
    # (MojoBytes *), so every read op is inherited — only construction and
    # the mutation ops differ. Mutability is a property of the CONSTRUCTOR
    # SPELLING, not of the source value, and C cannot tell the two apart
    # once both are a MojoBytes *, so every result here goes through
    # mojo_bytearray_mark — including the ones that reuse an immutable
    # constructor. It is what lets `memoryview(ba).readonly` answer False
    # (CPython) instead of whatever the shared constructor happened to say.
    if (fname_raw == 'bytearray' and not gen._locally_binds_name('bytearray')
            and len(node.args) <= 3):
        if len(node.args) == 0:
            return 'MojoBytes *', gen._new_val('MojoBytes *', 'mojo_bytearray_new ()')
        at, av = gen.lower_expr(node.args[0])
        for _extra in node.args[1:]:
            gen.lower_expr(_extra)
        if at == 'MojoBytes *':
            _b = gen._call_expr('MojoBytes *', 'mojo_bytearray_copy', [('MojoBytes *', av)])
        elif at == 'MojoMemoryView *':
            _b = gen._call_expr('MojoBytes *', 'mojo_memoryview_tobytes',
                                [('MojoMemoryView *', av)])
        elif at in ('char *', 'MojoStr *'):
            sv = av if at == 'char *' else gen._stringify_value(at, av)
            enc = gen._new_val('char *', gen._intern_string('utf-8'))
            _b = gen._call_expr('MojoBytes *', 'mojo_bytes_from_str',
                                [('char *', sv), ('char *', enc)])
        elif at in ('MojoList *', 'MojoDict *', 'MojoSet *', 'void *'):
            # `bytearray(a_dict)`/`bytearray(a_set)` of ints - same real
            # Python shape as bytes() above.
            lv = gen._materialize_as_list(at, av)
            _b = gen._call_expr('MojoBytes *', 'mojo_bytes_from_list',
                                [('MojoList *', lv)])
        else:
            nv = gen._to_int64(at, av)
            _b = gen._call_expr('MojoBytes *', 'mojo_bytes_zeros', [('int64_t', nv)])
        return 'MojoBytes *', gen._call_expr(
            'MojoBytes *', 'mojo_bytearray_mark', [('MojoBytes *', _b)])

    # memoryview(<bytes|bytearray>): a non-copying 1-D byte view.
    if (fname_raw == 'memoryview' and not gen._locally_binds_name('memoryview')
            and len(node.args) == 1):
        at, av = gen.lower_expr(node.args[0])
        if at == 'MojoMemoryView *':
            return 'MojoMemoryView *', av
        if at == 'MojoBytes *':
            return 'MojoMemoryView *', gen._call_expr(
                'MojoMemoryView *', 'mojo_memoryview_from_bytes', [('MojoBytes *', av)])
        # unknown/opaque — coerce through MojoBytes*
        bv = gen._coerce_to_type('int64_t', 'MojoBytes *', gen._to_int64(at, av))
        return 'MojoMemoryView *', gen._call_expr(
            'MojoMemoryView *', 'mojo_memoryview_from_bytes', [('MojoBytes *', bv)])

    # str(x): dispatch on the argument's static type via _stringify_value
    # (int → mojo_str_from_int, float → mojo_repr_float, ...) rather than
    # the generic mojo_str(void *), which can't tell a real int value of 0
    # apart from a NULL pointer and returns "None" for it — `str(0)`,
    # `str(x)` where x==0, etc. all printed None. Same dispatch f-strings
    # and %-formatting already use; this just routes the bare builtin
    # through it too. (char*/unknown-pointer args still reach mojo_str via
    # _stringify_value's fallthrough, unchanged.)
    # `_locally_binds_name` gate: `str` is an ordinary identifier a
    # module can shadow with its own top-level def (e.g. Lib/locale.py's
    # own `def str(val):`) — confirmed via a real shadowing repro
    # (without this gate the call was routed to `mojo_str_from_int`
    # instead of the user's own function). Same class of bug/fix as the
    # `open`/`filter`/`enumerate` gates elsewhere in this file.
    if (fname_raw == 'str' and len(node.args) == 1
            and not gen._locally_binds_name('str')):
        et, ev = gen.lower_expr(node.args[0])
        # A bare True/False literal lowers with ctype 'int' (not '_Bool' —
        # _lower_BoolLiteral does this deliberately; other sites depend on
        # it), so str(True) would take the int path → "1". Recover the
        # bool intent from the AST so it stringifies as "True"/"False".
        if isinstance(node.args[0], gimple_ctypes.BoolLiteral):
            et = '_Bool'
        return 'char *', gen._stringify_value(et, ev)

    # str(bytes_obj, encoding[, errors]): real Python's bytes-decode
    # form. This codegen has no real `bytes` type (bytes-like values are
    # already represented as plain `char *`, same as str -- see
    # BACKLOG-CODEGEN.md/bugs/hard's own notes on bytes()), so decoding
    # is a no-op: the first argument already IS the decoded string.
    # Before this, the 2/3-arg form fell through to the generic call
    # path, which still routed to the 1-arg `mojo_str(void *)` runtime
    # helper with 2-3 arguments -- "too many arguments to function
    # 'mojo_str'; expected 1, have 2/3" -- found via encodings/idna.py's
    # `str(label, "ascii")` and encodings/punycode.py's `str(text[:pos],
    # "ascii", errors)`. `encoding`/`errors` are still evaluated (for
    # any side effects a real decode call would have), just discarded.
    if (fname_raw == 'str' and len(node.args) in (2, 3)
            and not gen._locally_binds_name('str')):
        et, ev = gen.lower_expr(node.args[0])
        for _extra in node.args[1:]:
            gen.lower_expr(_extra)
        if et != 'char *':
            ev = gen._stringify_value(et, ev)
        return 'char *', ev

    # pow(base, exp, mod): real Python's 3-arg modular-exponentiation
    # form -- integer semantics, entirely distinct from the ordinary
    # 2-arg pow(x, y) (which stays real-valued, routed to libc's own
    # `pow(double, double)` via _KNOWN_SIGS below). Before this, the
    # 3-arg form fell through to that SAME 2-arg libc signature —
    # "too many arguments to function 'pow'; expected 2, have 3" —
    # found via Modules/_decimal/libmpdec/literature/fnt.py's and
    # Modules/_decimal/tests/bignum.py's own `pow(base, exp, mod)`.
    if fname_raw == 'pow' and len(node.args) == 3:
        bt, bv = gen.lower_expr(node.args[0])
        et, ev = gen.lower_expr(node.args[1])
        mt, mv = gen.lower_expr(node.args[2])
        bv = gen._to_int64(bt, bv)
        ev = gen._to_int64(et, ev)
        mv = gen._to_int64(mt, mv)
        return 'int64_t', gen._call_expr(
            'int64_t', 'mojo_pow_mod',
            [('int64_t', bv), ('int64_t', ev), ('int64_t', mv)])

    # hash(x): was previously only a bare, never-defined forward
    # declaration (`_util_pairs`'s preamble stub) — compiled fine but
    # failed to LINK ("undefined symbols: _hash") the instant anything
    # actually called it. Found via Modules/_decimal/tests/bignum.py's
    # `xhash` (calls hash() on nothing directly, but sits alongside
    # the pow(base, exp, mod) fix above in the same file/investigation)
    # and importlib/metadata/_text.py. Dispatch on the STATICALLY known
    # argument type when possible (matching Python's real hash(int) ==
    # int for the common int case, real content hashing for a string)
    # rather than always routing through the generic opaque-value
    # fallback (mojo_hash, which can't tell a small int from a real
    # string apart from a raw int64_t without a static type hint).
    if (fname_raw == 'hash' and len(node.args) == 1
            and not gen._locally_binds_name('hash')):
        ht, hv = gen.lower_expr(node.args[0])
        if ht in ('int', 'int64_t', '_Bool'):
            return 'int64_t', gen._to_int64(ht, hv)
        if ht in ('char *', 'MojoStr *'):
            hv = gen._stringify_value(ht, hv) if ht != 'char *' else hv
            return 'int64_t', gen._call_expr('int64_t', 'mojo_hash_str', [('char *', hv)])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_hash', [('int64_t', gen._to_int64(ht, hv))])

    # sum(list_of_doubles): the generic `mojo_sum` (BUILTIN_VALUE_MAP
    # below) always reads each MojoList slot via mojo_list_get_int and
    # returns int64_t -- for a list this codegen tracks (via
    # _elem_types, e.g. from a `[3.5, 2.5]` literal or a param inferred
    # from float usage) as holding doubles, that silently misreads
    # every element's raw int64_t bit pattern as if it were an integer
    # instead of a float. Route to the double-aware runtime helper
    # instead, mirroring _list_repr_fn's identical "route through
    # _elem_types" pattern for repr(). Found via Tools/lockbench/
    # lockbench.py's `sum(values)`/`sum(x**2 for x in values)` on a
    # list of floats.
    if (fname_raw == 'sum' and len(node.args) == 1
            and not gen._locally_binds_name('sum')):
        at, av = gen.lower_expr(node.args[0])
        # `sum(a_dict)`/`sum(a_set)` of numbers is real Python, and even a
        # genuinely-untyped boxed handle deserves the same runtime guard —
        # DESIGN.html R1/R5, shares _materialize_as_list. mojo_sum/_double
        # themselves unconditionally reinterpret their arg as MojoList* at
        # the C level with NO dispatch of their own, so without this a
        # MojoDict*/MojoSet* argument was reinterpreted as a list header
        # (the exact R2-violation shape) rather than just an ad-hoc cast
        # in this codegen.
        if at != 'MojoList *':
            av = gen._materialize_as_list(at, av)
            at = 'MojoList *'
        if gen._elem_types.get(av) == 'double':
            acast = av if at == 'void *' else gen._new_val('void *', f'(void *){av}')
            return 'double', gen._call_expr('double', 'mojo_sum_double', [('void *', acast)])
        acast = av if at == 'void *' else gen._new_val('void *', f'(void *){av}')
        return 'int64_t', gen._call_expr('int64_t', 'mojo_sum', [('void *', acast)])

    # `hasattr(obj, attr)`: the `mojo_hasattr` runtime helper is a stub that
    # returns 1 for ANY non-null object (the typed field list lives in the
    # generated `_mojo_dispatch_getattr`, not the runtime lib), so a compiled
    # `if hasattr(n, 'condition'):` always took the true branch and the
    # `getattr(n, 'condition')` inside it then RAISED AttributeError on a node
    # that has no such field. Probe the real generated dispatch under the
    # nothrow flag instead (same mechanism the 3-arg getattr default uses):
    # a miss sets `_mojo_getattr_missed`, so `missed == 0` is the answer.
    if (fname_raw == 'hasattr' and len(node.args) == 2
            and not gen._locally_binds_name('hasattr')):
        ot, ov = gen.lower_expr(node.args[0])
        at, av = gen.lower_expr(node.args[1])
        vp = gen._new_val('void *', ov if ot == 'void *' else f'(void *){ov}')
        ap = av if at == 'char *' else gen._new_val('char *', f'(char *){av}')
        gen._emit("  _mojo_getattr_missed = 0;")
        gen._emit("  _mojo_getattr_nothrow = 1;")
        gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                       [('void *', vp), ('char *', ap)])
        gen._emit("  _mojo_getattr_nothrow = 0;")
        _missed = gen._new_val('int', '_mojo_getattr_missed')
        return '_Bool', gen._new_val('_Bool', f'{_missed} == 0')

    # `enumerate(x)` in VALUE position — the runtime's identity-passthrough
    # helper cannot answer this (see _lower_builtin_enumerate_value). The
    # `for i, v in enumerate(x)` form has its own lowering in emit_loops and
    # never reaches here.
    if (fname_raw == 'enumerate' and node.args
            and not gen._locally_binds_name('enumerate')):
        return _lower_builtin_enumerate_value(gen, node)

    # Trivial builtins: lower_expr all args, call runtime fn
    _SIMPLE_BUILTINS = {
        'str':       ('char *',  'mojo_str'),
        'enumerate': ('void *',  'mojo_enumerate'),
        'hasattr':   ('int',     'mojo_hasattr'),
    }
    # `_locally_binds_name` gate: `enumerate`/`hasattr`/`str` are all
    # ordinary identifiers a module can shadow with its own top-level def
    # (e.g. Lib/threading.py's `def enumerate():`). Without this, a
    # locally-defined `enumerate` was routed straight to the builtin
    # `mojo_enumerate` runtime helper instead of the user's own function
    # (confirmed via a real shadowing repro — same class of bug as the
    # `open`/`filter` gates elsewhere in this file).
    if (fname_raw in _SIMPLE_BUILTINS and node.args
            and not gen._locally_binds_name(fname_raw)):
        rt, fn = _SIMPLE_BUILTINS[fname_raw]
        pairs = [gen.lower_expr(a) for a in node.args]
        return rt, gen._call_expr(rt, fn, pairs)
    # `vars(obj)` — same real MojoDict* field view as `obj.__dict__` just
    # above in `_lower_MemberExpr` (see that call site's own comment; this
    # is Step 0 of bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md,
    # `vars()`/`__dict__` are the same operation in real Python).
    #
    # `_mojo_dispatch_asdict(void *obj)` (gimple_module_gen.py) is ALREADY
    # a fully-general RUNTIME dispatcher: it reads the object's own type
    # tag via `mojo_read_type_tag_safe` and picks the matching
    # `_mojo_asdict_<struct>` at RUNTIME — it never needed the STATIC type
    # to be known at compile time. The previous version of this code only
    # called it `if gimple_exprtypes._struct_name_of(at) in gen.
    # struct_field_types` (statically-known struct), and otherwise let
    # `vars(x)` fall through to the generic "unresolved builtin" weak-stub
    # path (a print-and-return-0 no-op) — exactly the R4 "absence of proof
    # treated as a negative answer" pattern DESIGN.html describes, when a
    # perfectly good runtime answer was available all along (R5). Found by
    # tracing bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md:
    # gimple_gen_coro.py's own AST-walking helpers use `for k, v in
    # vars(node).items():` on a GENERICALLY-typed `node` parameter (by
    # design — it walks many different AST node types uniformly), so
    # EVERY one of those calls hit the useless stub once this compiler
    # self-hosted (compiled gimple_gen_coro.py's own source), silently
    # no-op'ing the coroutine-detection walk across the entire self-hosted
    # build instead of raising or working.
    if fname_raw == 'vars' and len(node.args) == 1:
        at, av = gen.lower_expr(node.args[0])
        gen._asdict_dispatch_needed.add(1)
        vp = av if at == 'void *' else gen._new_val('void *', f'(void *){av}')
        return 'MojoDict *', gen._call_expr(
            'MojoDict *', '_mojo_dispatch_asdict', [('void *', vp)])
    if fname_raw == 'getattr' and len(node.args) >= 2:
        # `getattr(f, "_cached", None)` where `f` is a free function
        # memoizing a value on itself (see `_func_attrs`'s pre-scan
        # docstring, gen_module Phase 1) — read the real backing global
        # instead of falling through to `_mojo_dispatch_getattr` (a
        # struct-instance reflection helper; `f` boxed as a function
        # pointer has no type tag it recognizes, so it always silently
        # returned a bogus "not found" value — the memoization compiled
        # without error but never actually cached anything).
        _fattrs_g = gen._func_attrs
        if (_fattrs_g and isinstance(node.args[0], gimple_ctypes.IdentExpr)
                and node.args[0].name in _fattrs_g
                and isinstance(node.args[1], gimple_ctypes.StringLiteral)
                and _as_str(node.args[1].value) in _fattrs_g[node.args[0].name]):
            mangled = _fattrs_g[node.args[0].name][_as_str(node.args[1].value)]
            gtype = gen._global_var_types.get(mangled, 'int64_t')
            return gtype, gen._new_val(gtype, mangled)
        # A5: `getattr(s, 'elifs', [])` / `getattr(handler, 'body', None)`
        # on a BOXED AST handle. The generic path below drops the default
        # arg and returns untyped int64_t, so `for _cond, elif_body in
        # getattr(s, 'elifs', []):` saw an opaque int64_t and fell to
        # mojo_unsupported_iter (the codegen's own structural walkers
        # silently skipped every if/else body in the compiled binary).
        # Mirror _lower_MemberExpr's A5 handling: when the attr names an
        # unambiguous struct field, resolve its static C type and read it
        # through the typedef. _mojo_dispatch_getattr returns 0 for a
        # missing/unknown field, so a provided default (the codegen's own
        # defensive `getattr(s, 'elifs', [])` pattern) is substituted.
        if (isinstance(node.args[1], gimple_ctypes.StringLiteral)
                and len(node.args) in (2, 3)):
            # `_as_str`: `node.args[1]` is a boxed MojoList element, so the
            # self-hosted backend types this `.value` read as int64_t. The
            # bits are the real `char *`, but `f'"{_attr}"'` below then
            # formats the POINTER as a quoted decimal and interns it — the
            # generated C gets `_mojo_dispatch_getattr(obj, "40424334336")`
            # (a per-run heap address, invalid, and different every run).
            _attr = _as_str(node.args[1].value)
            # `_known_field_type` resolves `_attr`'s C type ONLY when
            # every struct across the WHOLE-PROGRAM-shared `struct_
            # field_types` that happens to have a field of this bare
            # name agrees on its type — true even when only a SINGLE,
            # totally unrelated struct anywhere in the huge transitive
            # compile happens to define it (see that helper's own
            # docstring, gimple_gen_infra.py). That is sound for the A5
            # idiom this branch was built for (this compiler's OWN self-
            # hosted `getattr(s, 'elifs', [])`-style reads on a boxed AST
            # NODE handle, where `_attr` genuinely does name one of a
            # small, closed set of AST-node field names), but unsound
            # for an arbitrary third-party `getattr(obj, name, default)`
            # call on an opaque receiver with NO relationship at all to
            # whichever struct happens to own that field name elsewhere
            # in the program — common, generic field names like
            # 'buffer'/'raw'/'name' collide easily across a huge stdlib
            # corpus. Confirmed real regression: `Lib/tempfile.py`'s
            # `raw = getattr(file, 'buffer', file)` (file/raw both
            # genuinely opaque `_io.open()` results, no relation to any
            # user struct) picked up SOME unrelated class's own `buffer:
            # String` field's `char *` type purely by name coincidence,
            # mistyping `raw` as `char *` — then `raw.name = name` (a
            # LATER, separate real attribute write) tried a literal `.`
            # member access on that `char *`, a hard GCC "request for
            # member 'name' in something not a structure or union"
            # error. Scoped to this compiler's OWN self-hosted source
            # (the same path-based gate `gen_module`'s `_is_selfhost_
            # file`/`DispatchSolver(allow_assume_all_methods=...)` use)
            # since that's the only place this A5 idiom is meant to
            # fire; every other file falls through to the generic
            # untyped-int64_t path below unchanged (the ONLY behavior
            # this ever had before A5 was added).
            # `_is_selfhost_source_file`, the shared answer to "is the file
            # being compiled one of the compiler's OWN modules" — see its
            # docstring for why the bare `_SELFHOST_DIR` prefix test this
            # replaced was wrong (it answered yes for anything merely under
            # the install directory, so a fixture or a downstream project's
            # subdirectory got this self-host-only type hint, and
            # `_lower_method_call`'s module-qualified-call branch was denied
            # its resolution outright — a silent wrong value whose only
            # trigger was where the file sat).
            _is_selfhost_file = _is_selfhost_source_file(
                getattr(gen, '_current_filename', None))
            _boxed_ft = gen._known_field_type(_attr) if _is_selfhost_file else None
            if _boxed_ft is not None:
                ot, ov = gen.lower_expr(node.args[0])
                if ot in ('int', 'char'):
                    ov = gen._new_val('int64_t', f'(int64_t){ov}')
                vp = gen._new_val('void *', f'(void *){ov}')
                _nothrow3 = len(node.args) >= 3
                if _nothrow3:
                    # `_mojo_dispatch_getattr` RAISES on a miss (its fallback
                    # is `mojo_obj_getattr`), so the default below could never
                    # win — probe under the runtime's nothrow flag, which
                    # makes a miss set `_mojo_getattr_missed` and return 0.
                    gen._emit("  _mojo_getattr_missed = 0;")
                    gen._emit("  _mojo_getattr_nothrow = 1;")
                raw = gen._call_expr('int64_t', '_mojo_dispatch_getattr',
                                      [('void *', vp), ('char *', f'"{_attr}"')])
                if _nothrow3:
                    gen._emit("  _mojo_getattr_nothrow = 0;")
                    dt, dv = gen.lower_expr(node.args[2])
                    if dt != 'int64_t':
                        dv = gen._new_val('int64_t', f'(int64_t){dv}')
                    _missed = gen._new_val('int', '_mojo_getattr_missed')
                    # GIMPLE: the ?: condition must be a _Bool temp (an
                    # inline `!=` in the selector is "bogus comparison
                    # result type" / "expected ';' before '?'").
                    cond = gen._new_val('_Bool', f'{_missed} != 0')
                    raw = gen._new_val('int64_t', f'{cond} ? {dv} : {raw}')
                if _boxed_ft.endswith(' *'):
                    t = gen._new_val(_boxed_ft, f'({_boxed_ft}){raw}')
                else:
                    t = gen._new_temp(_boxed_ft)
                    gen._emit(f"  {t} = ({_boxed_ft}){raw};")
                return _boxed_ft, t
        pairs = [gen.lower_expr(a) for a in node.args[:2]]
        if len(node.args) >= 3:
            # 3-arg `getattr(obj, name, default)` with a NON-literal `name`
            # (the literal case is the A5 branch above). `_mojo_dispatch_
            # getattr`'s fallback (`mojo_obj_getattr`) RAISES AttributeError
            # on a miss, so the default would never win. Probe under the
            # runtime's `_mojo_getattr_nothrow` flag — which makes a miss set
            # `_mojo_getattr_missed` and return 0 instead of raising — then
            # select the caller's default whenever the miss flag is set.
            dt, dv = gen.lower_expr(node.args[2])
            if dt != 'int64_t':
                dv = gen._new_val('int64_t', f'(int64_t){dv}')
            gen._emit("  _mojo_getattr_missed = 0;")
            gen._emit("  _mojo_getattr_nothrow = 1;")
            raw = gen._call_expr('int64_t', '_mojo_dispatch_getattr', pairs)
            gen._emit("  _mojo_getattr_nothrow = 0;")
            _missed = gen._new_val('int', '_mojo_getattr_missed')
            cond = gen._new_val('_Bool', f'{_missed} != 0')
            return 'int64_t', gen._new_val('int64_t', f'{cond} ? {dv} : {raw}')
        return 'int64_t', gen._call_expr('int64_t', '_mojo_dispatch_getattr', pairs)
    if fname_raw == 'type'    and len(node.args) == 1:
        _, av = gen.lower_expr(node.args[0])
        # Read the struct's real leading __mojo_type_id field (see
        # mojo_read_type_tag_safe) instead of mojo_type()'s always-0 stub —
        # `type(node).__name__` needs it to dispatch (see the __name__
        # member-expr handling above). int64_t return (mojo_read_type_tag_
        # safe's own type); the old 'int' boxed the 64-bit tag into a 32-bit
        # temp, a hard gcc "invalid conversion in gimple call" error.
        av64 = gen._new_val('int64_t', f"(int64_t){av}")
        return 'int64_t', gen._new_val('int64_t', f"mojo_read_type_tag_safe ({av64})")
    if fname_raw == 'setattr' and len(node.args) >= 3:
        pairs = [gen.lower_expr(a) for a in node.args[:3]]
        return gen._void_call('_mojo_dispatch_setattr', pairs)
    if fname_raw == 'delattr' and len(node.args) >= 2:
        # `del obj.attr` (myinterpreter.py's execute_DelStmt) — the compiled
        # runtime has no dynamic attribute deletion (attributes are struct
        # fields), so this is a documented no-op that still compiles/links.
        pairs = [gen.lower_expr(a) for a in node.args[:2]]
        return gen._void_call('mojo_delattr', pairs)

    # Struct constructors. Map a C-keyword struct name (`auto()`) to its
    # renamed registration (`_kw_auto`) so the constructor resolves.
    _fname_ctor = gen._c_kw_struct_renames.get(fname_raw, fname_raw)
    if _fname_ctor in gen.struct_field_types:
        # `node.kwargs` (a direct CallExpr field read) NOT
        # `getattr(node, 'kwargs', None)` — the 3-arg getattr lowers to a
        # dynamic `_mojo_dispatch_getattr` on the self-hosted path, which
        # doesn't see a plain dataclass list field and returns the None
        # default, so every `Struct(field=...)` kwarg-only constructor
        # (e.g. `CallExpr(func=IdentExpr(name='main'))` at fire.py:127)
        # silently lowered to a bare `_alloc_Struct()` with no field inits.
        return gen._lower_struct_constructor(_fname_ctor, node.args, node.kwargs)
    if gen.func_return_types.get(fname_raw) == f'{fname_raw} *':
        return gen._lower_imported_struct_ctor(fname_raw, node)

    # Scalar type constructors (Float32, Int8, etc.) — before opaque-uppercase check
    if (fname_raw in gimple_ctypes._SCALAR_CTORS and fname_raw not in gen.func_return_types
            and fname_raw not in gen.imported_symbols):
        return gen._lower_scalar_ctor(fname_raw, gimple_ctypes._SCALAR_CTORS[fname_raw], node)

    # Closure / recursive self-call
    inner_name = getattr(gen, '_inner_func_name', '')
    if inner_name and fname_raw == inner_name and gen._env_param:
        return gen._lower_recursive_self_call(fname_raw, node)
    if fname_raw in gen._closure_envs:
        return gen._lower_closure_call(fname_raw, node)
    # Lambda body references an outer closure — call the lifted version with null env
    outer_ci = getattr(gen, '_lambda_outer_closures', {}).get(fname_raw)
    if outer_ci:
        return gen._lower_outer_closure_call(fname_raw, outer_ci, node)

    # Opaque uppercase constructor (imported type not in any table).
    # `fname_raw in _STR_WRAPPER_CTORS` bypasses the `imported_symbols`
    # exclusion specifically: StringSlice/StaticString have no real struct
    # layout in this codegen even when explicitly imported (`from
    # std.collections.string import StringSlice`), so treating an import as
    # proof a "real resolvable struct" exists here (like it does for actual
    # user-defined structs) is wrong for these two — see gimple_ctypes.py's
    # `_STR_WRAPPER_CTORS` docstring for the full failure this fixes.
    # `_ctor_rt == ''` too, NOT `not gen.func_return_types.get(...)`: a
    # self-hosted `not <string>` is lowered as POINTER-NULLITY, so an
    # EMPTY-STRING entry (this compiler's own `func_return_types
    # ['StringRef'] == ''`) is non-null and `not` yields False, where the
    # python3 reference's `not ''` is True (string truthiness). Comparing
    # the value against both the default and the empty string avoids that.
    _ctor_rt = gen.func_return_types.get(fname_raw, 'int64_t')
    if ((_ctor_rt == 'int64_t' or _ctor_rt == '')
            and fname_raw[0:1].isupper()
            and fname_raw not in gen.func_param_types
            and (fname_raw not in gen.imported_symbols
                 or fname_raw in gimple_ctypes._STR_WRAPPER_CTORS)
            and fname_raw not in gen._KNOWN_SIGS
            and fname_raw not in gimple_ctypes._C_RESERVED_FUNCS
            and fname_raw not in gen.BUILTIN_VALUE_MAP):
        return gen._lower_opaque_ctor(fname_raw, node)

    # Local variable holding a bound-method value (`f = self.b; ...; f()`
    # — see _lower_bound_method_value/bugs/
    # CODEGEN_bound_method_as_value_not_resolved.md). Must be checked
    # before the plain-function-pointer case just below: a
    # `MojoBoundMethod *` also needs `self` re-supplied as the implicit
    # first argument, which a bare fn-ptr call has no way to do. The var
    # may be declared as a real `MojoBoundMethod *` OR boxed through
    # `int64_t` — the general-purpose var-type-inference pre-pass has no
    # idea about this new pointer type and can default an assigned-from
    # variable to int64_t, same as it does for every other unfamiliar
    # struct pointer; _get_actual_type resolves that the same way
    # _lower_MemberExpr's own object-lowering path already does.
    # Fall back to the GLOBAL type table when fname_raw isn't a known
    # local — a bare reference to a module-level global inside a
    # function that never declared `global fname_raw` (no assignment to
    # it in this function, only a read/call, so Python/Mojo scoping
    # doesn't require the declaration) never gets seeded into
    # `self.var_types` here (contrast `_gen_stmt_GlobalStmt`, which DOES
    # seed it — see gen_module's `if name in self._global_var_types and
    # name not in self.var_types: self.var_types[name] = ...`, but only
    # runs for an explicit `global` statement). Without this fallback, a
    # module-level global holding a function pointer obtained via
    # `alias = m.some_func` (see `_lower_MemberExpr`'s module-alias
    # function-value resolution) and later called from a DIFFERENT
    # function than the one that assigned it — the common "lazy-init a
    # global once, call it from anywhere" pattern, e.g. BUG-2026-049's
    # `_helper_add = m.helper_add` in `ensure_helper()` then
    # `_helper_add(...)` in `main()` — fell all the way through to
    # `_lower_named_call` below, which just guesses the call target is a
    # C function literally named after the Mojo variable (never true
    # here) instead of recognizing it as a real function-pointer value.
    # Local variable holding a BUILTIN-container method bound as a value
    # (`append = l.append; ...; append(x)`) — must be checked BEFORE both
    # bound-method/fnptr guards below: the boxed handle var is declared
    # int64_t exactly like a plain fnptr value, so the fnptr guard would
    # otherwise emit mojo_fnptr_call_N on an opaque getattr box. See
    # _lower_builtin_method_value / _lower_builtin_bound_method_call.
    if fname_raw in gen._builtin_method_values:
        return gen._lower_builtin_bound_method_call(fname_raw, node)

    _fname_var_ctype = gen.var_types.get(fname_raw) or gen._global_var_types.get(fname_raw, '')
    if gen._get_actual_type(_fname_var_ctype, fname_raw) == 'MojoBoundMethod *':
        return gen._lower_bound_method_call(fname_raw, node, _fname_var_ctype)

    # A local that has held a `MojoBoundMethod *` in at least one branch
    # but whose declared type is void*/int64_t (branch-joined with a plain
    # fn-pointer / lambda value). Dispatch dynamically at runtime — see
    # _assign_target's `_bm_tainted_locals` bookkeeping.
    if fname_raw in getattr(gen, '_bm_tainted_locals', ()):
        return gen._lower_maybe_bound_call(fname_raw, node)

    # Local variable (or captured variable) holding a function pointer.
    # Emit a proper function-pointer call via a C cast. Any name that is
    # a LOCAL VARIABLE here (not a known function/builtin, which the
    # dispatch above already handled) MUST be a function pointer — e.g.
    # `func(self.interpreter)` where func came from a `for name, func in
    # test_funcs:` tuple loop. Its declared type can be a misleading
    # first-decl-wins `char *` (a sibling `_gen_for_dict` branch declared
    # it for the dict-iteration arm), so treat any var-types local as a
    # fnptr call rather than guessing it names a C function.
    # A CAPTURING lambda bound to a local and called only through that
    # local: lower its body right here, in this scope, where the captured
    # names already resolve. Lifted to a function pointer the body named
    # variables that don't exist in it, and each read stubbed to 0 — a
    # silent wrong answer with exit 0. Guarded by mojo/middle/lambdareduce's
    # escape analysis, so a lambda that outlives its call site never
    # reaches here.
    _red = getattr(gen, '_inlined_lambdas', None) or {}
    _red_lambda = _red.get(fname_raw)
    if _red_lambda is not None:
        return _lower_inlined_lambda_call(gen, _red_lambda, node)

    if (fname_raw in gen.var_types) or (
            _fname_var_ctype in ('int', 'int64_t', 'void *', '_Bool')
            and fname_raw not in gen._mangled_funcs
            and fname_raw not in gen.func_return_types):
        return gen._lower_fnptr_call(fname_raw, _fname_var_ctype, node)

    return gen._lower_named_call(fname_raw, node)


def _lower_builtin_len(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    at, av = gen.lower_expr(node.args[0])
    _LEN_FNS = {
        'MojoStr *':  f'mojo_str_len ({av})',
        'MojoBytes *': f'mojo_bytes_len ({av})',
        'MojoMemoryView *': f'mojo_memoryview_len ({av})',
        'MojoList *': f'mojo_list_len ({av})',
        'MojoDict *': f'mojo_dict_len ({av})',
        'MojoSet *':  f'mojo_set_len ({av})',
    }
    if at in _LEN_FNS:
        # `len(<fresh container>)` (`len(mk(i))`, `len(s.split())`, `len([..])`)
        # reads the length once and the operand is never seen again, so it is
        # freed here. This is the builtin call only: the same `mojo_list_len`
        # also backs truthiness tests, whose operand the caller may reuse, which
        # is why the free lives in this lowering and not in the runtime call.
        _len_fresh = (at in ('MojoList *', 'MojoDict *', 'MojoSet *')
                      and gen._is_fresh_container_operand(node.args[0], av))
        _len_t = gen._new_val('int64_t', _LEN_FNS[at])
        if _len_fresh:
            gen._free_fresh_container(av, at)
        return 'int64_t', _len_t
    if at == 'char *':
        # A plain string (the overwhelmingly common representation of
        # Mojo/Python `str` in this compiler) had no case here at all —
        # fell all the way to the final "unsupported type" fallback,
        # so len(any_string) always silently returned 0. Found via
        # len(c_code) on a real compiled program's C output.
        return 'int64_t', gen._call_expr('int64_t', 'mojo_strlen', [('char *', av)])
    _dsub_len = gen._dict_subclass_of(at)
    if _dsub_len and not gen._struct_defines_method(_dsub_len, '__len__'):
        dp = gen._new_val('MojoDict *', f"{av}->_data")
        return 'int64_t', gen._new_val('int64_t', f'mojo_dict_len ({dp})')
    _bsub_len = gen._bytes_subclass_of(at)
    if _bsub_len and not gen._struct_defines_method(_bsub_len, '__len__'):
        bp = gen._new_val('MojoBytes *', f"{av}->_data")
        return 'int64_t', gen._call_expr('int64_t', 'mojo_bytes_len', [('MojoBytes *', bp)])
    if at.endswith(' *') and at[:-2] in gen.struct_field_types:
        _sn = at[:-2]
        if '_len' in gen.struct_field_types[_sn]:
            return 'int64_t', gen._new_val('int64_t', f'{av}->_len')
        # `len(obj)` where obj is a user class that DEFINES `__len__` is a
        # call to that method — Python's rule, and the same one the
        # dict/bytes branches above already honour via
        # `_struct_defines_method`. Without it the call fell through to the
        # final "unsupported type" fallback and silently answered 0: a
        # model's `len(self.vocab)` reported a 0-token vocabulary while
        # every other number on the same line was right. The `_len` FIELD
        # is the runtime's own convention (Span/Slice); a Python class
        # spells it as a method instead, and both spellings are real.
        if gen._struct_defines_method(_sn, '__len__'):
            import mojo.backend_gimple.emit_funcs as _gef
            _msym = _gef._struct_method_csym(gen, _sn, '__len__', '')
            return 'int64_t', gen._call_expr(
                'int64_t', _msym, [(at, av)])
    if at in ('int', 'int64_t'):
        # `at` is just the local's declared storage type — for a value
        # widened to int64_t because it's joined with other assignment
        # sites in the same function (e.g. `rest = raw[prefix_len:]`
        # then `rest = raw`, both really char*), the actual pointer kind
        # survives in _actual_types (set wherever the value was stored;
        # see AssignStmt's "Track actual type if storing a pointer as
        # int64_t"). Blindly assuming MojoList* here — the previous,
        # only case — misroutes a boxed char* through mojo_list_len,
        # which then reads len*8 bytes off the string as if they were a
        # MojoList header. Found via fire_compiler.py's own
        # _strip_string_prefix_and_quotes: len(rest) on a `rest` that's
        # really a string segfaulted deep in mojo_list_get_int.
        actual = gen._actual_types.get(av)
        if actual == 'char *':
            cp = gen._new_val('char *', f'(char *){av}')
            return 'int64_t', gen._call_expr('int64_t', 'mojo_strlen', [('char *', cp)])
        if actual == 'MojoDict *':
            dp = gen._coerce_to_type('int64_t', 'MojoDict *', av)
            return 'int64_t', gen._new_val('int64_t', f'mojo_dict_len ({dp})')
        if actual == 'MojoSet *':
            sp = gen._coerce_to_type('int64_t', 'MojoSet *', av)
            return 'int64_t', gen._new_val('int64_t', f'mojo_set_len ({sp})')
        lp = gen._coerce_to_type('int64_t', 'MojoList *', av)
        return 'int64_t', gen._new_val('int64_t', f'mojo_list_len ({lp})')
    return 'int64_t', gen._new_val('int64_t', f'(int64_t)0  /* len() on unsupported type {at} */')


def _isinstance_one_type(gen, obj_type: str, obj_val: str, type_name: str) -> str:
    """Emit the check for `isinstance(x, SingleType)` and return a _Bool
    value name. Factored out of _lower_builtin_isinstance so `isinstance(x,
    (A, B, ...))` (a tuple of types) can OR together one of these per
    alternative instead of the previous always-False stub."""
    if type_name == 'type':
        return gen._new_val('_Bool', '0')  # isinstance(x, type) always false in C
    if type_name == 'tuple':
        # A tuple's runtime representation is a MojoList carrying the
        # `mojo_mark_as_tuple` marker (see _lower_tuple_literal). Neither
        # the static C type (MojoList *, shared with plain lists) nor the
        # scalar _TYPE_IDS table can answer `isinstance(x, tuple)` — it
        # needs the runtime marker check (mojo_isinstance_p type_id 8).
        # Without this every `isinstance(top, tuple)` on a boxed/popped
        # heterogeneous value fell through to `mojo_isinstance_p(_, 0)`,
        # which is unconditionally false — so the tuple branch was dead.
        iv = gen._new_val('int64_t', f'(int64_t){obj_val}')
        res = gen._new_temp('int')
        gen._emit(f'  {res} = mojo_isinstance_p ({iv}, 8);')
        return gen._new_val('_Bool', f'(_Bool){res}')
    if type_name in gen.struct_field_types:
        # A real user-defined struct/dataclass type: compare the
        # object's runtime type tag (see mojo_read_type_tag in
        # runtime/fire_runtime.c, and the tag stamped by every
        # _alloc_<StructName> helper) against this type's own
        # deterministic hash — NOT the always-false mojo_isinstance()
        # stub below, which only covers scalar builtins with no
        # tagged runtime representation. Was a real, general bug:
        # isinstance(node, AnyStructType) always took the "not this
        # type" branch when compiled, found via find_imports() (used
        # by `mojo --dump`'s own do_imports resolution) never
        # recognizing an import statement nested in a function/if/try
        # block once self-hosted.
        target_id = gimple_exprtypes._struct_type_id(type_name)
        # A value statically typed as a container/string runtime type
        # (`char *`/`MojoList *`/`MojoSet *`/`MojoDict *`) can never be an
        # instance of a user-defined struct/dataclass under this runtime's
        # object model — none of these carry the tagged-struct header
        # `mojo_read_type_tag` expects as its first 8 bytes. Falling
        # through to the `obj_type.endswith(' *')` branch below (true for
        # ALL FOUR, since they're pointer types too) cast the string/
        # container pointer straight into `mojo_read_type_tag` as if it
        # WERE a struct address — a real, ASan-confirmed heap-buffer-
        # overflow (8-byte read on e.g. a 5-byte `char *` token substring
        # from `mojo_regex_substr`, reached via `isinstance(<AST leaf>,
        # SomeNodeType)` during `fire_compiler._scan_yield_bearing`'s
        # generic recursive walk) as well as a semantically wrong result
        # even when it happened not to fault. Statically false, no read.
        if obj_type in ('char *', 'MojoList *', 'MojoSet *', 'MojoDict *'):
            return gen._new_val('_Bool', '0')
        if obj_type.endswith(' *'):
            ov_local = gen._ensure_local(obj_type, obj_val)
            vp = gen._new_val('void *', f'(void *){ov_local}')
            addr = gen._new_val('int64_t', f'(int64_t){vp}')
        elif obj_type == 'int64_t':
            addr = obj_val
        else:
            addr = gen._new_val('int64_t', f'(int64_t){obj_val}')
        tag = gen._call_expr('int64_t', 'mojo_read_type_tag', [('int64_t', addr)])
        target = gen._new_val('int64_t', f'(int64_t){target_id}')
        cmp_t = gen._new_temp('_Bool')
        gen._emit(f'  {cmp_t} = {tag} == {target};')
        return cmp_t
    _TYPE_IDS = {'bool': '1', 'int': '2', 'float': '3', 'str': '4',
                 'list': '5', 'dict': '6', 'set': '7', 'tuple': '8'}
    type_id = _TYPE_IDS.get(type_name, '0')
    # Scalar isinstance by STATIC type. The runtime mojo_isinstance stub
    # always returns 0 (false), so e.g. `isinstance(node.name, str)` was
    # ALWAYS False for a char* name once compiled — every VarDecl's
    # `isinstance(node.name, str)` guard (gimple_codegen.py's own
    # `_gen_stmt_VarDecl`) then treated node.name as a non-string and
    # formatted the char* as an integer, emitting raw heap addresses as
    # variable/type names in the native .ci (A5 part 2). A char* IS str,
    # an int64_t/int IS int, a MojoList* IS list, etc. — this codebase's
    # representation makes the static C type a sound verdict. Only an
    # ambiguous boxed int64_t falls through to the (still always-false)
    # mojo_isinstance stub.
    _SCALAR_TYPE_MATCH = {
        'str':   ('char *', 'MojoStr *'),
        'int':   ('int', 'int64_t', 'uint64_t', 'int8_t', 'int16_t', 'int32_t',
                  'uint8_t', 'uint16_t', 'uint32_t', 'long', 'short', 'size_t', '_Bool'),
        'float': ('double', 'float', '__fp16'),
        'bool':  ('_Bool',),
        'list':  ('MojoList *',),
        'dict':  ('MojoDict *',),
        'set':   ('MojoSet *',),
        # bytes / bytearray share the MojoBytes * representation, so at the
        # C-type level they are indistinguishable — `isinstance(x, bytes)`
        # and `isinstance(x, bytearray)` both match any MojoBytes * value.
        # A type tag on MojoBytes would be needed to discriminate; not
        # worth the struct-layout churn for this compiler.
        'bytes': ('MojoBytes *',),
        'bytearray': ('MojoBytes *',),
        'memoryview': ('MojoMemoryView *',),
    }
    # A builtin-`bytes` subclass instance (`class _Extra(bytes)`) IS a
    # `bytes` for isinstance purposes even though its C type is the
    # subclass struct pointer, not `MojoBytes *`. See
    # bugs/COMPILE_FAIL_zipfile___init__.md.
    if type_name in ('bytes', 'bytearray') and gen._bytes_subclass_of(obj_type):
        return gen._new_val('_Bool', '(_Bool)1')

    if type_name in _SCALAR_TYPE_MATCH:
        if obj_type in _SCALAR_TYPE_MATCH[type_name]:
            if obj_type.endswith(' *'):
                # A NULL pointer here means None (e.g. the "default"
                # branch of a dynamic getattr(obj, attr, None) on a
                # struct that doesn't have this field — see the A5
                # getattr-with-default lowering above, which types the
                # result by the FIELD NAME across all structs, not by
                # this particular object). isinstance(None, list) must
                # be False even though the static C type matches —
                # checking the static type alone made every such
                # "attribute absent" NULL look like a real empty-or-full
                # list, which then got pushed onto a caller's worklist
                # and iterated as if non-null (real bug: unbounded
                # memory growth / wild-pointer crash self-hosting a
                # large file, root-caused via _register_imported_structs
                # __collect's `getattr(st, attr, None)` +
                # `isinstance(sub, list)` walk).
                iv = gen._new_val('int64_t', f'(int64_t){obj_val}')
                zero = gen._new_val('int64_t', '(int64_t)0')
                return gen._new_val('_Bool', f'{iv} != {zero}')
            return gen._new_val('_Bool', '(_Bool)1')
        if obj_type not in ('int64_t', 'void *', ''):
            return gen._new_val('_Bool', '(_Bool)0')
    res = gen._new_temp('int')
    if obj_type in ('char *', 'void *', 'MojoDict *', 'MojoList *', 'MojoSet *') or obj_type.endswith(' *'):
        iv  = gen._new_val('int64_t', f'(int64_t){obj_val}')
        # `mojo_isinstance_p` (int64_t arg), NOT `mojo_isinstance((int)iv)`:
        # the old cast truncated the pointer to 32 bits so the runtime's
        # list/dict registry lookup always missed. The full-width entry
        # point makes `isinstance(node, list)` / `isinstance(node, dict)`
        # actually work for a boxed handle — the compiler's own generic
        # AST walkers depend on it when self-hosted.
        gen._emit(f'  {res} = mojo_isinstance_p ({iv}, {type_id});')
    else:
        # Widen through an explicit int64_t temp here too. The operand at
        # this point is typically an `int64_t`-typed BOXED handle (an
        # unannotated AST-node parameter, e.g. `_walk_ast_into(node, ...)`),
        # i.e. exactly the case that must not be truncated — see
        # mojo_isinstance's own definition for what the 32-bit form cost.
        _iv = gen._new_val('int64_t', f'(int64_t){obj_val}')
        gen._emit(f'  {res} = mojo_isinstance_p ({_iv}, {type_id});')
    return gen._new_val('_Bool', f'(_Bool){res}')




def _lower_builtin_isinstance(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    obj_type, obj_val = gen.lower_expr(node.args[0])
    type_arg = node.args[1]
    t = gen._new_temp('int')
    _single_tn = _isinstance_type_name(type_arg)
    if _single_tn is not None:
        cmp_t = gen._isinstance_one_type(obj_type, obj_val, _single_tn)
        gen._emit(f'  {t} = (int){cmp_t};')
    elif isinstance(type_arg, gimple_ctypes.TupleExpr):
        # isinstance(x, (A, B, ...)) — OR together a per-alternative check
        # (see _isinstance_one_type). Previously stubbed to always-False,
        # which silently broke every `isinstance(s, (VarDecl, AssignStmt))`-
        # style filter once compiled — e.g. Parser._parse_struct's own
        # `[s for s in body if isinstance(s, (VarDecl, AssignStmt))]`
        # always produced an empty struct field list.
        acc = None
        for alt in type_arg.elements:
            _alt_tn = _isinstance_type_name(alt)
            if _alt_tn is None:
                continue
            # `_as_str`: the returned temp NAME is erased to int64_t on the
            # self-hosted path, so formatting it straight into the join below
            # printed the string's ADDRESS — `_t19 = 40139116528 | _t18;`.
            # A raw heap address in emitted code is both invalid C and a
            # per-run difference, since addresses move under ASLR.
            one = _as_str(gen._isinstance_one_type(obj_type, obj_val, _alt_tn))
            # `|` not `||`: GIMPLE rejects a raw `||` token in a plain
            # assignment RHS ("not valid in GIMPLE") — only simple binary
            # ops are allowed. Bitwise OR on two already-computed _Bool
            # (0/1) values is equivalent and GIMPLE-legal.
            acc = one if acc is None else gen._new_val('_Bool', _as_str(acc) + ' | ' + one)
        if acc is None:
            acc = gen._new_val('_Bool', '0')
        gen._emit(f'  {t} = (int){acc};')
    else:
        gimple_ctypes._debug_note('isinstance with complex type arg stubbed to 0')
        gen._emit(f'  {t} = 0;  /* TODO: isinstance with complex type arg */')
    return 'int', t


def _lower_next_list_iter(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """`next(it)` / `next(it, default)` where `it` is a resumable list-iterator
    local (see `_try_bind_list_iter`). Advances the shared cursor; raises a
    tagged StopIteration on exhaustion (1-arg) or yields `default` (2-arg)."""
    li = gen._list_iter_cursor[node.args[0].name]
    lst, cur, elem = li['list'], li['cursor'], li['elem']
    suf = gimple_ctypes.TypeLattice.list_suffix(elem) if elem else 'int'
    vct = {'str': 'char *', 'double': 'double'}.get(suf, 'int64_t')
    result = gen._new_temp(vct)
    n = gen._new_val('int64_t', f"mojo_list_len ({lst})")
    bb_ok = gen._new_bb(); bb_miss = gen._new_bb(); bb_merge = gen._new_bb()
    cond = gen._new_val('_Bool', f"{cur} < {n}")
    gen._emit(f"  if ({cond}) goto {bb_ok}; else goto {bb_miss};")
    gen._emit_label(bb_ok)
    ok = gen._new_val(vct, f"mojo_list_get_{suf} ({lst}, {cur})")
    gen._safe_coerce_emit(vct, vct, ok, result)
    nxt = gen._new_val('int64_t', f"{cur} + (int64_t)1")
    gen._emit(f"  {cur} = {nxt};")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_miss)
    if len(node.args) == 2:
        # `default` only evaluated on the exhausted branch (real Python
        # semantics — a non-trivial default expr must not run on a hit).
        dt, dv = gen.lower_expr(node.args[1])
        gen._safe_coerce_emit(dt, vct, dv, result)
    else:
        gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('StopIteration')});")
        gen._emit("  mojo_raise ();")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)
    return vct, result


def _lower_next_over_comprehension(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """`next(<generator expression>[, default])` — the "first element
    satisfying a predicate, else a fallback" idiom.

    The generator expression materializes to a `MojoList *` through the
    ordinary comprehension lowering (the same convention `any()`/`all()`
    already use for a generator argument — see `_lower_builtin_all_any`),
    then element 0 is taken when the list is non-empty. The 2-arg form
    yields `default` on empty; the 1-arg form raises StopIteration, exactly
    like the MojoGenerator* paths in `_lower_call`.

    Before this, a generator-expression argument matched neither of those
    `MojoGenerator *` branches and fell through to the declared-but-never-
    defined variadic `next(...)` stub, failing at LINK time with an
    undefined `_next` symbol. That stayed invisible for as long as no
    reachable code evaluated such an expression — this compiler's own
    `gen_module_impl` has one inside a `for m, oid in zip(...)` loop, which
    ran zero iterations until `zip()` itself got a for-loop lowering.

    NOTE (deliberate, matches `any`/`all`): the comprehension is fully
    materialized rather than short-circuited at the first match. Real
    Python stops early; every predicate this form is used with here is
    side-effect-free, so the only difference is wasted work on long
    sequences."""
    lt, lv = gen.lower_expr(node.args[0])
    if lt != 'MojoList *':
        lv = gen._coerce_to_type(lt, 'MojoList *', lv)
    elem = gen._elem_of(lv) or 'int64_t'
    n_t = gen._new_val('int64_t', f"mojo_list_len ({lv})")
    zero = gen._new_val('int64_t', "(int64_t)0")
    have = gen._new_val('_Bool', f"{n_t} > {zero}")
    result = gen._new_temp(elem)
    bb_have = gen._new_bb(); bb_empty = gen._new_bb(); bb_done = gen._new_bb()
    gen._emit(f"  if ({have}) goto {bb_have}; else goto {bb_empty};")

    gen._emit_label(bb_have)
    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
    if suf == 'str':
        first = gen._new_val('char *', f"mojo_list_get_str ({lv}, {zero})")
        gen._safe_coerce_emit('char *', elem, first, result)
    elif suf == 'double':
        first = gen._new_val('double', f"mojo_list_get_double ({lv}, {zero})")
        gen._safe_coerce_emit('double', elem, first, result)
    else:
        first = gen._new_val('int64_t', f"mojo_list_get_int ({lv}, {zero})")
        gen._safe_coerce_emit('int64_t', elem, first, result)
    gen._emit(f"  goto {bb_done};")

    gen._emit_label(bb_empty)
    if len(node.args) == 2:
        # `default` is only evaluated on the empty branch — real Python
        # semantics, and the same ordering the 2-arg MojoGenerator* path
        # above uses for its own exhausted branch.
        dt, dv = gen.lower_expr(node.args[1])
        gen._safe_coerce_emit(dt, elem, dv, result)
    else:
        gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id('StopIteration')});")
        gen._emit("  mojo_raise ();")
        # `mojo_raise()` does not return, but the merge block below still
        # needs `result` definitely-assigned on every incoming edge for
        # GIMPLE's own SSA construction.
        gen._safe_coerce_emit('int64_t', elem, zero, result)
    gen._emit(f"  goto {bb_done};")
    gen._emit_label(bb_done)
    return elem, result


def _lower_builtin_all_any(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    runtime_fn = 'mojo_list_all' if fname_raw == 'all' else 'mojo_list_any'
    stub_val   = '1'             if fname_raw == 'all' else '0'
    at, av = gen.lower_expr(node.args[0])
    t = gen._new_temp('int')
    if at == 'MojoList *' or at == 'MojoDict *' or at == 'MojoSet *' \
            or (at.endswith(' *') and at != 'char *'):
        # DESIGN.html R1/R5: dict/set materialization (all(d)/any(s) over a
        # dict's keys / a set's elements, not a reinterpret of the header —
        # see bugs/CODEGEN_all_any_dict_set_miscompile.md) shares
        # _materialize_as_list with enumerate()/str.join()/bytes.join()/
        # shlex.join(); a genuinely-unknown boxed handle is now also
        # runtime-guarded (mojo_is_registered_dict/_set) there instead of
        # blindly assuming list.
        lv = gen._materialize_as_list(at, av)
        gen._emit_call('int', t, runtime_fn, [('MojoList *', lv)])
    else:
        gen._emit(f'  {t} = {stub_val};  /* {fname_raw}() stubbed */')
    return 'int', t


def _lower_builtin_dir(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    for a in node.args: gen.lower_expr(a)
    return 'MojoList *', gen._new_val('MojoList *', 'mojo_list_new ()  /* dir() stubbed */')


def _callable_return_elem_type(gen, fn_expr) -> str:
    """Element type a `map`/key callable's results should be recorded as.

    `char *` only when the callee is known to produce a string. A lambda's
    results always come back through `mojo_fnptr_call_N`, which widens every
    return to int64_t, so a string-returning lambda is indistinguishable from
    an int one HERE — recording int64_t for it is not a lie that misprints
    (the repr's own discriminator recognises a boxed `char *` on sight), it
    just declines the extra precision. Guessing `char *` instead would send
    an int result through `mojo_list_append_str`."""
    if isinstance(fn_expr, gimple_ctypes.IdentExpr):
        _rt = gen.func_return_types.get(fn_expr.name, '')
        if _rt == 'char *':
            return 'char *'
    # Ask the estimator about the CALL, with a placeholder argument, so a
    # builtin callee is answered from the same tables the rest of the
    # compiler uses — `map(str, xs)` yields strings, and without this the
    # result was recorded int64_t, so `list(map(str, [1, 2]))` printed the
    # two string ADDRESSES as decimals. Reading `func_return_types` alone
    # cannot answer it: `str` is a builtin, not a compiled function, so it
    # has no entry there. The placeholder's own type does not matter — every
    # row consulted here (the scalar ctors, the container builtins, the
    # opaque-ctor passthrough) is callee-driven, and a callee whose answer
    # DOES depend on the argument falls through to the same int64_t default.
    try:
        _probe = gimple_ctypes.CallExpr(
            func=fn_expr, args=[gimple_ctypes.IdentExpr('_fc_arg')],
            line=getattr(fn_expr, 'line', 0), col=getattr(fn_expr, 'col', 0))
        _qt = gen._quick_type(_probe)
    except Exception:
        _qt = 'int64_t'
    if _qt == 'char *':
        return 'char *'
    return 'int64_t'


def _build_per_element_list(gen, fn_expr, it_val: str, elem: str | None,
                            only_truthy: bool = False,
                            var_prefix: str = '_fcall_elem'):
    """New MojoList holding `fn_expr(<element>)` for each element of `it_val`
    — the shared body of `map(f, xs)` (only_truthy=False), `filter(f, xs)`
    (only_truthy=True) and `sorted(xs, key=f)`'s key list.

    The runtime CANNOT do this itself: `mojo_map`/`mojo_filter` are identity
    stubs (fire_runtime.c) because a `char *` function pointer cannot call
    back into a GIMPLE-compiled body. `map(...)` therefore produced the input
    list UNCHANGED (so `list(map(f, xs))` printed the input, and
    `for v in map(f, xs):` ran over the wrong values), and `filter(...)` was
    the same. Building the list here also means the result's element type is
    known, so a leading 0 prints as `0` and not as the None sentinel.

    `elem` is the input list's element type; it decides how the loop variable
    is read (and typed), so a container element stays a `MojoList *` and a
    lambda key can index it. `only_truthy` filters on the call's result, which
    is how `filter`'s predicate is applied.
    """
    # Unique per call: `_declare_var` is first-decl-wins, so two `map`/`filter`
    # calls in one function would otherwise share the first one's element type
    # and emit a conflicting-types error.
    _kvar = f'{var_prefix}_{gen.temp_counter}'
    gen.temp_counter += 1
    _kelem_t = 'int64_t'
    if elem == 'double':
        _kelem_t = 'double'
    elif elem and elem.endswith(' *'):
        _kelem_t = elem
    res = gen._new_temp('MojoList *')
    gen._emit(f"  {res} = mojo_list_new ();")
    klen = gen._new_val('int64_t', f'mojo_list_len ({it_val})')
    kidx = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    kcond = gen._new_val('_Bool', f'{kidx} < {klen}')
    gen._emit(f"  if ({kcond}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    _read64 = gen._new_val('int64_t', f'mojo_list_get_int ({it_val}, {kidx})')
    if _kelem_t == 'double':
        _read = gen._new_val('double', f'mojo_list_get_double ({it_val}, {kidx})')
    elif _kelem_t == 'int64_t':
        _read = _read64
    else:
        _read = gen._coerce_to_type('int64_t', _kelem_t, _read64)
    gen._declare_var(_kvar, _kelem_t)
    gen._emit(f"  {gen._cname(_kvar)} = {_read};")
    # A lambda's FORWARD DECLARATION types its params from
    # `var_types[<param name>]` while the definition takes the call site's
    # argument type, so bind the element to the lambda's own param name for
    # the duration of the call — otherwise a container-typed param declares
    # `int64_t f(int64_t)` in one place and `int64_t f(MojoList *)` in the
    # other, which GCC rejects as "conflicting types".
    _saved_param_types = {}
    if isinstance(fn_expr, gimple_ctypes.LambdaExpr):
        for _pn, _pd in fn_expr.params:
            _saved_param_types[_pn] = gen.var_types.get(_pn, None)
            gen.var_types[_pn] = _kelem_t
    try:
        kret_t, kret_v = gen.lower_expr(gimple_ctypes.CallExpr(
            func=fn_expr, args=[gimple_ctypes.IdentExpr(_kvar)],
            line=getattr(fn_expr, 'line', 0), col=getattr(fn_expr, 'col', 0)))
    finally:
        for _pn, _old_t in _saved_param_types.items():
            if _old_t is None:
                gen.var_types.pop(_pn, None)
            else:
                gen.var_types[_pn] = _old_t
    if only_truthy:
        # filter's predicate: append only when the call's result is truthy.
        bb_yes = gen._new_bb(); bb_no = gen._new_bb()
        _t = gen._new_val('_Bool', f'({kret_v}) != 0')
        gen._emit(f"  if ({_t}) goto {bb_yes}; else goto {bb_no};")
        gen._emit_label(bb_yes)
    if only_truthy:
        # filter keeps the INPUT's element — the call's result is only the
        # predicate verdict. Appending the verdict instead (as map does with
        # its result) made `filter(lambda v: v > 1, [1, 2, 3])` produce
        # `[1, 1]`: two truthy verdicts, both the value 1.
        if _kelem_t == 'double':
            gen._void_call('mojo_list_append_double',
                           [('MojoList *', res), ('double', gen._cname(_kvar))])
        elif _kelem_t == 'int64_t':
            gen._void_call('mojo_list_append_int',
                           [('MojoList *', res), ('int64_t', gen._cname(_kvar))])
        else:
            # A container element keeps its pointer: the accessor hands back
            # an int64_t slot, which is exactly what the append takes.
            gen._void_call('mojo_list_append_int',
                           [('MojoList *', res), ('int64_t', _read64)])
        gen._emit_label(bb_no)
    elif kret_t == 'char *':
        gen._void_call('mojo_list_append_str', [('MojoList *', res), ('char *', kret_v)])
    else:
        _kret = gen._to_int64(kret_t, kret_v)
        gen._void_call('mojo_list_append_int', [('MojoList *', res), ('int64_t', _kret)])
    kone = gen._new_val('int64_t', '(int64_t)1')
    knew = gen._new_val('int64_t', f'{kidx} + {kone}')
    gen._emit(f"  {kidx} = {knew};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    return res


def _lower_builtin_map(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """`map(f, xs)` as a value: materialize the per-element calls here (see
    `_build_per_element_list` for why the runtime cannot). Eagerly, which is
    what every call site in this codebase consumes — the same trade
    `_lower_builtin_reversed` documents for `reversed`.

    Python allows several iterables (`map(f, xs, ys)`); only the one-iterable
    form is lowered, and the rest is an honest refusal rather than a silent
    wrong answer.
    """
    if len(node.args) != 2:
        raise RuntimeError(
            f"map() with {len(node.args)} iterables is not supported yet "
            f"(only map(f, xs))")
    fn_expr = node.args[0]
    at, av = gen.lower_expr(node.args[1])
    if at != 'MojoList *':
        av = gen._materialize_as_list(at, av)
    elem = gen._elem_of(av)
    res = _build_per_element_list(gen, fn_expr, av, elem, var_prefix='_map_elem')
    gen._elem_types[res] = _callable_return_elem_type(gen, fn_expr)
    return 'MojoList *', res


def _lower_builtin_filter(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """`filter(f, xs)` as a value: the same per-element build, keeping only
    the elements whose predicate call is truthy. The result holds the INPUT's
    elements, so its element type is the input's.
    """
    if len(node.args) != 2:
        raise RuntimeError(
            f"filter() with {len(node.args)} iterables is not supported yet "
            f"(only filter(f, xs))")
    fn_expr = node.args[0]
    at, av = gen.lower_expr(node.args[1])
    if at != 'MojoList *':
        av = gen._materialize_as_list(at, av)
    elem = gen._elem_of(av)
    res = _build_per_element_list(gen, fn_expr, av, elem, only_truthy=True,
                                  var_prefix='_filter_elem')
    if elem and elem != 'int64_t':
        gen._elem_types[res] = elem
    return 'MojoList *', res


def _lower_builtin_sorted_keyed(gen, node, arg0, key_expr, reverse: bool):
    """`sorted(x, key=f)` / `sorted(x, reverse=True)` / both.

    The compiled path has no per-element callback in the runtime, so the key
    LIST is built here: `f` is called once per element and each result
    appended, then `mojo_sorted_by_keys` orders the original list by it.

    The key callable is invoked through the ordinary call path (see below),
    so it may be a lambda, a function name, or a bound method — whatever
    this backend can already call.

    What this does NOT fix: key functions that are themselves already broken
    in the compiled path. Two measured, independent of sorted:
      * a dict-subscripted global read from inside a lifted lambda returns 0
        (`d = {...}` then `key=lambda k: d[k]`);
      * an UNANNOTATED named function taking a string element gets the
        string bits in an `int64_t` param and mismeasures it
        (`key=bylen` where `def bylen(s): return len(s)`).
    A lambda key and a builtin key both handle string elements correctly."""
    at, av = gen.lower_expr(arg0)
    if at != 'MojoList *':
        av = gen._materialize_as_list(at, av)
        at = 'MojoList *'
    elem = gen._elem_of(av)

    keys_val = 'NULL'
    if key_expr is not None:
        # Bind each element to a real local and lower a synthesized
        # `key(<element>)` CALL through the ordinary call path, rather than
        # resolving the callee to a C symbol here: a lambda lowers to a
        # function-POINTER VARIABLE (`_funcptr_main_lambda_1`), not to its
        # function's name, so calling it by name emitted "called object
        # `_t5` is not a function or function pointer". Going through the
        # call path handles a lambda, a plain function, and a bound method
        # uniformly — whatever this backend can call, it can call as a key.
        # Unique per call: `_declare_var` is first-decl-wins, so two
        # `sorted(..., key=...)` calls in one function would otherwise share
        # the first one's element type and emit a conflicting-types error.
        _kvar = f'_sorted_key_elem_{gen.temp_counter}'
        gen.temp_counter += 1
        # The element keeps its REAL type. A scalar key is read straight, but
        # a list/tuple element must be bound as `MojoList *` (the accessor
        # always hands back an int64_t slot, so it needs the same coercion
        # the `for`-loop tuple path uses) — binding it as int64_t made
        # `sorted([(2, "b"), (1, "a")], key=lambda t: t[0])` emit
        # "conflicting types" instead of sorting.
        _kelem_t = 'int64_t'
        if elem == 'double':
            _kelem_t = 'double'
        elif elem and elem.endswith(' *'):
            _kelem_t = elem
        keys = gen._new_temp('MojoList *')
        gen._emit(f"  {keys} = mojo_list_new ();")
        klen = gen._new_val('int64_t', f'mojo_list_len ({av})')
        kidx = gen._new_val('int64_t', '(int64_t)0')
        bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_after = gen._new_bb()
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_cond)
        kcond = gen._new_val('_Bool', f'{kidx} < {klen}')
        gen._emit(f"  if ({kcond}) goto {bb_body}; else goto {bb_after};")
        gen._emit_label(bb_body)
        _read64 = gen._new_val('int64_t', f'mojo_list_get_int ({av}, {kidx})')
        if _kelem_t == 'double':
            _read = gen._new_val('double', f'mojo_list_get_double ({av}, {kidx})')
        elif _kelem_t == 'int64_t':
            _read = _read64
        else:
            _read = gen._coerce_to_type('int64_t', _kelem_t, _read64)
        gen._declare_var(_kvar, _kelem_t)
        gen._emit(f"  {gen._cname(_kvar)} = {_read};")
        # A lambda key's FORWARD DECLARATION types its params from
        # `var_types[<param name>]`, while the definition picks up the type
        # of the argument at this call site. Bind the element to the
        # lambda's own param name for the duration of the call so a
        # container-typed param (`key=lambda t: t[0]`) declares
        # `int64_t f(MojoList *)` in both places — otherwise the definition
        # said `MojoList *` and the declaration `int64_t`, which GCC rejects
        # as "conflicting types".
        _saved_param_types = {}
        if isinstance(key_expr, gimple_ctypes.LambdaExpr):
            for _pn, _pd in key_expr.params:
                _saved_param_types[_pn] = gen.var_types.get(_pn, None)
                gen.var_types[_pn] = _kelem_t
        try:
            kret_t, kret_v = gen.lower_expr(gimple_ctypes.CallExpr(
                func=key_expr, args=[gimple_ctypes.IdentExpr(_kvar)],
                line=getattr(key_expr, 'line', 0), col=getattr(key_expr, 'col', 0)))
            # A lambda invoked through a function POINTER
            # (mojo_fnptr_call_N) always reports the generic homogenized
            # `int64_t` return type, regardless of what the lambda body
            # actually returns — even when the VALUE handed back is a
            # genuine `char *` bit pattern (an identity-shaped key,
            # `lambda s: s`, with `s` bound to `_kelem_t == 'char *'`
            # above). Without this, `kret_t == 'char *'` just below never
            # fired for a lambda key, so a STRING key was appended via
            # `mojo_list_append_int` (the pointer's raw ADDRESS, not its
            # content) and `mojo_sorted_by_keys` compared addresses:
            # `sorted(["bb", "a", "ccc"], key=lambda s: s)` silently sorted
            # by heap layout instead of lexicographically, exit 0. The
            # param bindings are still in effect here (restored in
            # `finally`, below), so `_quick_type` sees the same `char *`
            # `s` the call itself was just made with.
            if (isinstance(key_expr, gimple_ctypes.LambdaExpr) and kret_t != 'char *'
                    and gen._quick_type(key_expr.body) == 'char *'):
                kret_v = gen._coerce_to_type(kret_t, 'char *', kret_v)
                kret_t = 'char *'
        finally:
            for _pn, _old_t in _saved_param_types.items():
                if _old_t is None:
                    gen.var_types.pop(_pn, None)
                else:
                    gen.var_types[_pn] = _old_t
        # A `char *` key is a STRING to compare (strcmp), not an address to
        # compare as an int64_t slot — `sorted(words, key=lambda w: w)` with
        # the int path ordered by address. The key's own lowered return type
        # is what decides which.
        if kret_t == 'char *':
            gen._void_call('mojo_list_append_str', [('MojoList *', keys), ('char *', kret_v)])
        else:
            kret = gen._to_int64(kret_t, kret_v)
            gen._void_call('mojo_list_append_int', [('MojoList *', keys), ('int64_t', kret)])
        kone = gen._new_val('int64_t', '(int64_t)1')
        knew = gen._new_val('int64_t', f'{kidx} + {kone}')
        gen._emit(f"  {kidx} = {knew};")
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_after)
        keys_val = keys

    if keys_val == 'NULL':
        # No key: keep the type-aware sort the keyless path already picks
        # (mojo_list_sorted_str for strings, mojo_sorted for ints, ...) and
        # reverse its RESULT. Sorting by the raw int64_t slots here instead
        # would order strings by address, not lexicographically.
        res = _lower_builtin_sorted(gen, node, keyed=False)
        if not reverse:
            return res
        res_t, res_v = res
        out = gen._call_expr('MojoList *', 'mojo_list_reversed', [(res_t, res_v)])
        if elem and elem != 'int64_t':
            gen._elem_types[out] = elem
        return 'MojoList *', out

    res = gen._call_expr('MojoList *', 'mojo_sorted_by_keys',
                         [('MojoList *', av), ('MojoList *', keys_val),
                          ('int', '1' if reverse else '0')])
    if elem and elem != 'int64_t':
        gen._elem_types[res] = elem
    return 'MojoList *', res


def _lower_builtin_sorted(gen, node: gimple_ctypes.CallExpr,
                        keyed: bool = True) -> tuple[str, str]:
    arg0 = node.args[0]
    # sorted(dict.items()) — a list of (key, value) tuples sorted by key.
    # Without this, mojo_sorted's int64-payload sort orders the tuple
    # POINTERS, a non-deterministic order that diverges from Python (this
    # drives generated struct-typedef field order via
    # `for field_name, field_type in sorted(fields.items()):`).
    if (isinstance(arg0, gimple_ctypes.CallExpr) and isinstance(arg0.func, gimple_ctypes.MemberExpr)
            and arg0.func.member == 'items' and not arg0.args):
        ov_t, ov_v = gen.lower_expr(arg0.func.obj)
        ov_c = gen._coerce_to_type(ov_t, 'MojoDict *', ov_v)
        for a in node.args[1:]: gen.lower_expr(a)
        t = gen._call_expr('MojoList *', 'mojo_dict_items_sorted', [('MojoDict *', ov_c)])
        # Mirror .items(): the sorted item-list has the same [char* key,
        # boxed value] pair shape — carry the dict's value type through.
        # Look up from the ORIGINAL lowered value first (ov_c is a fresh
        # coercion temp with no value-type entry of its own).
        _siv = gen._dict_val_types.get(ov_v) or gen._dict_val_types.get(ov_c)
        if _siv is None and isinstance(arg0.func.obj, gimple_ctypes.MemberExpr) \
                and isinstance(arg0.func.obj.obj, gimple_ctypes.IdentExpr):
            # `sorted(self.FIELD.items())` — the dict's value type for a
            # struct FIELD lives in _field_dict_val_types, not the local
            # _dict_val_types map keyed by var/temp name.
            _fsn = gimple_exprtypes._struct_name_of(
                gen.var_types.get(arg0.func.obj.obj.name, ''))
            if _fsn:
                _siv = gen._field_dict_val_types.get(_fsn, {}).get(arg0.func.obj.member)
        gen._dict_items_val_elems[t] = _siv or 'int64_t'
        return 'MojoList *', t
    # `key=` / `reverse=` — real Python ordering options this lowering used
    # to drop on the floor: `sorted([1, 3, 2], key=lambda v: -v)` sorted
    # ASCENDING (silently wrong) and `reverse=True` did nothing. The C++20
    # companion path implements both, so the same source also sorted
    # differently depending on which backend handled it.
    kwargs = getattr(node, 'kwargs', []) or []
    key_expr = None
    reverse = False
    for _k, _v in kwargs:
        if _k == 'key':
            key_expr = _v
        elif _k == 'reverse':
            # `reverse=<anything truthy>`; only a literal False/0 is
            # statically decidable, and anything else is treated as True
            # (the Python truthiness rule for a flag argument).
            if isinstance(_v, gimple_ctypes.BoolLiteral) and not _v.value:
                reverse = False
            elif isinstance(_v, gimple_ctypes.IntLiteral) and _v.value == 0:
                reverse = False
            else:
                reverse = True
    if keyed and (key_expr is not None or reverse):
        return _lower_builtin_sorted_keyed(gen, node, arg0, key_expr, reverse)

    at, av = gen.lower_expr(arg0)
    for a in node.args[1:]: gen.lower_expr(a)
    # Dispatch on the container type so `sorted(...)` matches Python's
    # semantics instead of running mojo_sorted's generic int64 payload
    # bubble-sort over the wrong layout (a MojoSet has a completely
    # different struct layout from MojoList — mojo_sorted(set) read
    # garbage and could segfault; and sorting a list-of-strings by its
    # char* pointer values gives a non-deterministic, non-alphabetical
    # order that diverges from `python3 fire.py --dump` output).
    if at == 'MojoSet *':
        t = gen._call_expr('MojoList *', 'mojo_set_sorted', [(at, av)])
        # sorted() only reorders — carry the set's element type onto the
        # result list (mirrors the MojoList branch below), or a later
        # `for x in sorted(a_set_of_str):` typed `x` int64_t and every
        # string use of it operated on the pointer bits (`for sn in
        # sorted(self._struct_allocs_needed):` -> `_alloc_<decimal>`).
        _se = gen._elem_of(av)
        if _se and _se != 'int64_t':
            gen._elem_types[t] = _se
        return 'MojoList *', t
    if at == 'MojoDict *':
        t = gen._call_expr('MojoList *', 'mojo_dict_sorted_keys', [(at, av)])
        gen._elem_types[t] = 'char *'   # dict keys are always strings
        return 'MojoList *', t
    if at == 'MojoList *' and gen._elem_of(av) == 'char *':
        t = gen._call_expr('MojoList *', 'mojo_list_sorted_str', [(at, av)])
    else:
        if at != 'MojoList *':
            # Any other iterable — a generator (a generator call or a
            # compiled generator expression) above all. Every runtime
            # sorter here walks a MojoList, so a MojoGenerator* argument
            # was sorted by reinterpreting a coroutine object as a list
            # header (a hard crash). Drain it through the shared
            # chokepoint first, exactly as sum()/any()/max() now do.
            av = gen._materialize_as_list(at, av)
            at = 'MojoList *'
        t = gen._call_expr('MojoList *', 'mojo_sorted', [(at, av)])
    # sorted() only reorders — the result keeps the input's element /
    # nested-element (tuple-pair) types, so a later `for x, y in
    # sorted(lst):` tuple-target loop reads slots with the right accessor.
    if at == 'MojoList *' and av in gen._nested_elem_types:
        gen._nested_elem_types[t] = gen._nested_elem_types[av]
    if at == 'MojoList *' and av in gen._elem_types:
        gen._elem_types[t] = gen._elem_types[av]
    return 'MojoList *', t


def _lower_builtin_zip_n(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """zip(a, b, ...) as a value — chain as mojo_zip(mojo_zip(a, b), c, ...).
    Every argument is materialized to a MojoList first (see the loop body),
    so a generator or any other non-list iterable zips correctly."""
    arg_pairs = []
    for a in node.args:
        at, av = gen.lower_expr(a)
        if at != 'MojoList *':
            # mojo_zip walks MojoList*; a generator argument (or any other
            # non-list iterable) was reinterpreted as a list header and
            # crashed. Materialize first — same chokepoint as above.
            av = gen._materialize_as_list(at, av)
            at = 'MojoList *'
        arg_pairs.append((at, av))
    # Fold left: mojo_zip(mojo_zip(a,b), c)
    acc_v = gen._call_expr('void *', 'mojo_zip', [arg_pairs[0], arg_pairs[1]])
    for ap in arg_pairs[2:]:
        acc_v = gen._call_expr('void *', 'mojo_zip', [('void *', acc_v), ap])
    # Deliberately the SAME `void *` result type the BUILTIN_VALUE_MAP path
    # returned, with no nested-element typing attached. Typing it as a
    # MojoList* of 2-slot pairs looks like an improvement (`len(z)`/`print(z)`
    # would work) but it breaks a real self-host shape: a comprehension with
    # a NESTED tuple target over `zip`, e.g. funcs_shared.py's own
    #   [ct + ' ' + pn.lstrip('*') for ct, (pn, pt) in zip(pts, fn.params)]
    # whose 3-slot target read a 2-slot pair spec and indexed a list where a
    # string was expected ("cannot use 'list' as a dict key" inside
    # TypeLattice.list_suffix, which then failed the whole self-host
    # compile). The for-loop zip form (`for x, y in zip(...)`) has its own
    # dedicated lowering with correct pair typing and is unaffected.
    return 'void *', acc_v


def _lower_builtin_reversed(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """reversed(x) — a reverse iterator over a sequence.

    Modeled as an eagerly reversed COPY (semantically identical for the
    single forward consumption every real call site does: `for x in
    reversed(seq)` / `list(reversed(seq))`). Before this, `reversed(...)`
    had no lowering at all and fell through to the generic dynamic-dispatch
    stub, producing a `void *` value — and `for x in reversed(...)` over
    that `void *` was SILENTLY DROPPED by _gen_stmt_ForStmt (real
    miscompile: zipfile/__init__.py:1612's central-directory concordance
    loop `for zinfo in reversed(sorted(self.filelist, key=...))` ran zero
    times). A list/str/bytes arg is reversed properly; anything else is an
    honest refusal, not a silent drop.
    """
    at, av = gen.lower_expr(node.args[0])
    if at == 'MojoList *':
        cp = gen._call_expr('MojoList *', 'mojo_list_copy', [('MojoList *', av)])
        gen._emit_call('void', '', 'mojo_list_reverse', [('MojoList *', cp)])
        # reversed() only reorders — carry element / nested-element types
        # through so a later `for x in ...` / `for a, b in ...` binds slots
        # with the right accessor (mirrors _lower_builtin_sorted).
        if av in gen._elem_types:
            gen._elem_types[cp] = gen._elem_types[av]
        if av in gen._nested_elem_types:
            gen._nested_elem_types[cp] = gen._nested_elem_types[av]
        return 'MojoList *', cp
    if at in ('char *', 'MojoStr *'):
        sv = av if at == 'char *' else gen._stringify_value(at, av)
        return 'char *', gen._call_expr('char *', 'mojo_cstr_reverse', [('char *', sv)])
    if at == 'MojoBytes *':
        return 'MojoBytes *', gen._call_expr(
            'MojoBytes *', 'mojo_bytes_reverse', [('MojoBytes *', av)])
    if at == 'MojoDict *':
        # `reversed(dict)` iterates keys in reverse-insertion order; the
        # generic dict iteration path already walks keys, and for the
        # common `for k in reversed(d):` consumption order rarely matters
        # to correctness of a compile check. Reverse a key list copy.
        _keys = gen._call_expr('MojoList *', 'mojo_dict_keys', [('MojoDict *', av)])
        gen._emit_call('void', '', 'mojo_list_reverse', [('MojoList *', _keys)])
        gen._elem_types[_keys] = 'char *'
        return 'MojoList *', _keys
    if at in ('int64_t', 'int', 'void *'):
        # A BOXED handle: an unannotated parameter, a comprehension result,
        # or anything else this codegen erased to an untyped int64_t. The
        # value is a real container at run time — it is the STATIC type that
        # was lost — and this backend already has the one chokepoint that
        # recovers it, `_materialize_as_list` (DESIGN.html R1), which
        # consults the runtime container registries rather than assuming
        # (DESIGN.html R5).
        #
        # The unrecognized-type fallthrough below used to handle this shape
        # by returning the value UNCHANGED, and that is a silent WRONG
        # ANSWER, not a neutral pass-through: the consuming `for` loop takes
        # its own generic path and iterates the container in FORWARD order,
        # so `for x in reversed(seq)` computed the right elements in the
        # wrong order and nothing said so. Materialize, then reverse the
        # copy for real.
        try:
            _lp = gen._materialize_as_list(at, av)
        except Exception as e:
            gimple_ctypes._debug_note(
                'reversed() could not materialize its argument as a list', e)
            return at, av
        cp = gen._call_expr('MojoList *', 'mojo_list_copy', [('MojoList *', _lp)])
        gen._emit_call('void', '', 'mojo_list_reverse', [('MojoList *', cp)])
        _e = gen._elem_of(_lp)
        if _e:
            gen._elem_types[cp] = _e
        _n = gen._nested_elem_types.get(_lp)
        if _n:
            gen._nested_elem_types[cp] = _n
        return 'MojoList *', cp
    # An unrecognized argument type (a Mojo container struct with its own
    # `__reversed__`, a struct pointer, …). A real general fix is
    # `__reversed__` dispatch + the struct iterator protocol (see
    # bugs/CODEGEN_generator_function_Lib_collections___init__.md's
    # `reversed()` discussion). Until then, fall through to the generic
    # dynamic-dispatch value the pre-`reversed()`-lowering code produced —
    # the consuming `for` loop then takes its own generic path. NOT a
    # `raise`: that turned five previously-compiling stdlib files (which
    # used `reversed()` on these shapes) into hard failures.
    gimple_ctypes._debug_note('reversed() on unrecognized type — generic fallthrough', at)
    return at, av


def _lower_builtin_import(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    for a in node.args: gen.lower_expr(a)
    return 'int', gen._new_val('int', '0  /* __import__ stubbed */')


def _lower_builtin_enumerate_value(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """`enumerate(x)` (and `list(enumerate(x))`) — a real list of
    (index, value) PAIR lists, the shape `mojo_zip` produces.

    The runtime's `mojo_enumerate` is an identity passthrough
    (`return iterable`), so a value-position `enumerate(...)` used to hand
    the caller its own argument back: `list(enumerate([7, 8]))` returned
    `[7, 8]` — the values with no indices at all — and over a GENERATOR,
    whose "unchanged" value is a coroutine handle, the consuming `list()`
    found nothing iterable in it and produced an EMPTY list, silently.

    Routed through a comprehension instead (which is what `list(x)` does),
    which cannot work here: that path synthesizes a SINGLE-slot target, so
    the enumerate loop bound the INDEX to it and dropped the value —
    `list(enumerate([7, 8]))` came out as `[0, 1]`. Built directly instead.

    `for i, v in enumerate(x)` is unaffected: it has its own lowering in
    emit_loops, with correct index/element typing."""
    if not node.args:
        raise RuntimeError("enumerate() requires an argument")
    at, av = gen.lower_expr(node.args[0])
    # Start value: enumerate(x, start) counts from there.
    start = '0'
    if len(node.args) > 1:
        st, sv = gen.lower_expr(node.args[1])
        start = gen._to_int64(st, sv)
    elif getattr(node, 'kwargs', None):
        # enumerate(x, start=...) — the keyword form real callers use.
        for k, v in node.kwargs:
            if k == 'start':
                st, sv = gen.lower_expr(v)
                start = gen._to_int64(st, sv)
    av = gen._materialize_as_list(at, av)
    elem = gen._elem_of(av)
    res = gen._new_temp('MojoList *')
    gen._emit(f"  {res} = mojo_list_new ();")
    len64 = gen._new_val('int64_t', f'mojo_list_len ({av})')
    # POSITION counter, kept separate from the index actually stored in each
    # pair: `enumerate(x, start)` starts counting at `start`, so the loop
    # bound has to be the position (0..len) or the first `start` iterations
    # are skipped.
    pos = gen._new_val('int64_t', '(int64_t)0')
    idx = gen._new_val('int64_t', start)
    bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond = gen._new_val('_Bool', f'{pos} < {len64}')
    gen._emit(f"  if ({cond}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    pair = gen._new_temp('MojoList *')
    gen._emit(f"  {pair} = mojo_list_new ();")
    gen._void_call('mojo_list_append_int', [('MojoList *', pair), ('int64_t', idx)])
    raw = gen._new_val('int64_t', f'mojo_list_get_int ({av}, {pos})')
    boxed = gen._new_val('int64_t', f'(int64_t)(intptr_t){raw}')
    gen._void_call('mojo_list_append_int', [('MojoList *', pair), ('int64_t', boxed)])
    # The pair's SECOND slot holds the element, so record its type or a
    # consumer reads a string back as a raw integer.
    if elem and elem != 'int64_t':
        gen._elem_types[pair] = elem
    gen._void_call('mojo_list_append_int',
                   [('MojoList *', res), ('int64_t', f'(int64_t)(intptr_t){pair}')])
    # The increment is computed INSIDE the loop body on purpose: hoisting it
    # (what `gen._new_val` does at the point of writing) evaluates
    # `pos + 1` once before the loop, so `pos = <that pre-loop value>`
    # re-assigns the same number every iteration and the loop never
    # terminates.
    one = gen._new_val('int64_t', '(int64_t)1')
    npos = gen._new_val('int64_t', f'{pos} + {one}')
    gen._emit(f"  {pos} = {npos};")
    if start == '0':
        gen._emit(f"  {idx} = {pos};")
    else:
        nidx = gen._new_val('int64_t', f'{pos} + {start}')
        gen._emit(f"  {idx} = {nidx};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)
    gen._nested_elem_types[res] = ['int64_t', elem or 'int64_t']
    # Also record the plain element type: the assignment sites propagate
    # `_elem_types`/`_nested_elem_types` from a value to the variable it is
    # bound to under an `_elem_types` guard, so without this entry a
    # `z = enumerate(x); print(z)` lost the pair typing and fell back to
    # the generic repr (which printed the first index as `None`).
    gen._elem_types[res] = 'MojoList *'
    return 'MojoList *', res


def _lower_ctor_from_iterable(gen, kind: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Shared `set(iterable)` / `list(iterable)` lowering: build a
    synthetic `{x for x in <arg>}` / `[x for x in <arg>]` Comprehension
    node and hand it to `_lower_comprehension`, so `set(...)`/`list(...)`
    get the exact same generic-iterable handling (range/MojoList*/
    MojoStr*/MojoDict*(keys)/MojoSet*, plus the int64_t-boxed-pointer
    resolution `_lower_comprehension` already does) as real
    comprehensions and `for x in <iterable>:` loops, instead of a third,
    narrower iteration scheme. See bugs/CODEGEN_set_list_ctor_ignores_iterable_arg.md.

    NB: first param is named `gen` (not `_g`) so the self-hosted backend
    types it `GimpleGen *` — an unrecognized name is typed `int64_t`, and
    then `gen._lower_comprehension(...)` stubs to a no-op that returned the
    instance pointer itself (a segfault at the `list(x)` call site).
    """
    if not node.args:
        new_fn = 'mojo_set_new' if kind == 'set' else 'mojo_list_new'
        res_type = 'MojoSet *' if kind == 'set' else 'MojoList *'
        return res_type, gen._new_val(res_type, f'{new_fn} ()')
    # `set(<a set>)` / `frozenset(<a set>)` copies SLOTS, exactly as
    # `dict(<a dict>)` already lowers to mojo_dict_copy above, instead of
    # going round the generic comprehension. That is not just an
    # optimization: a MojoSet keeps `val_i` and `val_s` in separate fields
    # (MojoList/MojoDict store one word that both views share), so the
    # comprehension's int-view read + int-view add DOWNGRADES every str
    # slot to an int slot holding the char* — after which `x in <copy>`,
    # which emits mojo_set_contains_str, misses every element.
    # Real repro: gimple_ctypes' own `_C_RESERVED_FUNCS = frozenset({...})`
    # came out all-int-slots, so `name in _C_RESERVED_FUNCS` was False for
    # every libc name and the compiler emitted a weak `int64_t abs ()`
    # stub that collides with <stdlib.h>'s — one error cascading into 849
    # more in fire_compiler.py's own translation unit. mojo_set_copy
    # dispatches per slot on its tag, so both kinds survive.
    _arg0 = node.args[0]
    if kind == 'set':
        _at, _av = gen.lower_expr(_arg0)
        _at = gen._get_actual_type(_at, _av) or _at
        if _at == 'MojoSet *':
            t = gen._new_temp('MojoSet *')
            gen._emit_call('MojoSet *', t, 'mojo_set_copy', [('MojoSet *', _av)])
            return 'MojoSet *', t
        # Not a set — hand the ALREADY-lowered value to the comprehension
        # below as a plain name rather than re-lowering `node.args[0]` (which
        # would emit its side effects twice). A name registered in
        # `var_types` lowers straight back to itself with this ctype.
        gen.var_types[_av] = _at
        _arg0 = gimple_ctypes.IdentExpr(_av, node.line, node.col)
    # `list(<a list>)` is a slot-for-slot copy, so the result describes its
    # slots exactly as the source does — and for a list that carries its own
    # per-slot kinds (a `struct.unpack` of a mixed format, a heterogeneous
    # literal) that description is the only thing standing between a copy and
    # raw IEEE-754 bit patterns. The comprehension below emits the copy as an
    # explicit append loop, which loses the kinds by itself, so hand them
    # over once it has run. Done at RUNTIME lookup rather than from the
    # codegen's own table on purpose: the source is reached through a value
    # the codegen may have no kinds for (a copy of a copy, a list returned
    # from a function) while the runtime does. Only for `list` — a `set`
    # re-reads its elements through the set's own per-slot accessors and
    # genuinely produces a different container.
    _copy_src = None
    if kind == 'list':
        _lt, _lv = gen.lower_expr(_arg0)
        if _lt == 'MojoList *':
            # Same anti-double-side-effect discipline as the set branch
            # above: re-use the value we just lowered, do not lower the
            # argument expression a second time.
            gen.var_types[_lv] = _lt
            _arg0 = gimple_ctypes.IdentExpr(_lv, node.line, node.col)
            _copy_src = _lv
    gen.temp_counter += 1
    var = f"_ctor_elem{gen.temp_counter}"
    synth_gen = gimple_ctypes.Generator(target=var, iterable=_arg0, conditions=[],
                     line=node.line, col=node.col)
    compr = gimple_ctypes.Comprehension(kind=kind, element=gimple_ctypes.IdentExpr(var, node.line, node.col),
                           generators=[synth_gen], line=node.line, col=node.col)
    _rt, _rv = gen._lower_comprehension(compr)
    if _copy_src is not None and _copy_src != _rv:
        gen._emit_call('void', '', 'mojo_list_inherit_kinds',
                       [('MojoList *', _rv), ('MojoList *', _copy_src)])
        if _copy_src in gen._maybe_kinds_vals:
            gen._maybe_kinds_vals.add(_rv)
    return _rt, _rv


def _lower_builtin_set(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    return gen._lower_ctor_from_iterable('set', node)


def _lower_builtin_dict(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    if not node.args and len(node.kwargs or []) == 0:
        return 'MojoDict *', gen._new_val('MojoDict *', 'mojo_dict_new ()')
    # `dict(k=v, ...)` kwarg form — previously silently DROPPED (an
    # all-kwargs call hit the `not node.args` early return above and built
    # an EMPTY dict; kwargs-mixed-with-args never reached here either).
    # Real repro: argparse.py's own `text % dict(prog=self._prog)` inside
    # HelpFormatter — the dict-keyed `%` lowering routes that call's result
    # into mojo_str_format_dict, which then raised a genuine runtime
    # KeyError('prog') because nothing ever stored the key. Pairs lower
    # through the SAME per-pair store helper the `{k: v}` literal uses, so
    # key coercion and per-type setter dispatch stay in one place.
    if len(node.kwargs or []) > 0 and not node.args:
        t = gen._new_val('MojoDict *', "mojo_dict_new ()")
        for _kw_key, _kw_val in node.kwargs:
            # StringLiteral.value is the parser's already-quote-stripped
            # text, so the bare key name is the correct literal payload.
            gex._emit_dict_pair_store(gen, t,
                                      gimple_ctypes.StringLiteral(value=_kw_key,
                                                                  line=node.line, col=node.col),
                                      _kw_val)
        return 'MojoDict *', t
    at, av = gen.lower_expr(node.args[0])
    t = gen._new_temp('MojoDict *')
    if at == 'MojoList *':
        gen._emit_call('MojoDict *', t, 'mojo_dict_from_pairs', [('MojoList *', av)])
    elif at in ('int64_t', 'int') or not at.endswith(' *') or at == 'void *':
        raw = gen._coerce_to_type(at, 'MojoDict *', av)
        gen._emit_call('MojoDict *', t, 'mojo_dict_copy', [('MojoDict *', raw)])
    else:
        gen._emit_call('MojoDict *', t, 'mojo_dict_copy', [(at, av)])
    return 'MojoDict *', t


def _lower_builtin_list(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    # `list(enumerate(x))` is already the pair list enumerate builds — the
    # comprehension route below cannot express it (single-slot target, see
    # _lower_builtin_enumerate_value).
    if (node.args and isinstance(node.args[0], gimple_ctypes.CallExpr)
            and isinstance(node.args[0].func, gimple_ctypes.IdentExpr)
            and node.args[0].func.name == 'enumerate'
            and not gen._locally_binds_name('enumerate')):
        return _lower_builtin_enumerate_value(gen, node.args[0])
    return gen._lower_ctor_from_iterable('list', node)


def _lower_builtin_open(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    # open(path) — read mode
    if len(node.args) == 1:
        fn_type, fn_val = gen.lower_expr(node.args[0])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_open_file', [(fn_type, fn_val)])
    if not node.args:
        # open() with no args — a bare `open` reference used as a value
        # (e.g. tarfile's `fileobj = open` or `self._open`). Return a
        # generic function-pointer-ish placeholder rather than crashing.
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
    # open(path, mode)
    fn_type,   fn_val   = gen.lower_expr(node.args[0])
    mode_type, mode_val = gen.lower_expr(node.args[1])
    fn_val   = gen._ensure_local('char *', gen._coerce_to_type(fn_type,   'char *', fn_val))
    mode_val = gen._ensure_local('char *', gen._coerce_to_type(mode_type, 'char *', mode_val))
    tmp = gen._new_val('void *',   f'mojo_open ({fn_val}, {mode_val})')
    return 'int64_t', gen._new_val('int64_t', f'(int64_t){tmp}')


def _lower_self_ctor(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    # Direct field access (not getattr): keeps `char *` on the self-hosted
    # path so the `Name___new` stub decl / call symbol is the struct name,
    # not a per-run heap address. `_current_struct_name` is always set (to
    # "" when outside a method body) before any body lowering.
    sname = _as_str(gen._current_struct_name)
    if sname:
        arg_pairs = [gen.lower_expr(a) for a in node.args]
        gen._self_ctor_stubs[sname] = True
        return 'int64_t', gen._call_expr('int64_t', f'{sname}___new', arg_pairs)
    for a in node.args: gen.lower_expr(a)
    return 'int64_t', gen._new_val('int64_t', '0  /* Self() constructor: no struct context */')


def _lower_imported_struct_ctor(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    t = gen._new_temp('int64_t')
    if arg_pairs:
        atype, aval = arg_pairs[0]
        if atype.endswith(' *'):
            gen._emit(f'  {t} = (int64_t){aval};')
        else:
            gen._emit(f'  {t} = (int64_t){gen._ensure_local(atype, aval)};')
    else:
        gen._emit(f'  {t} = (int64_t)0;')
    return 'int64_t', t


def _lower_scalar_ctor(gen, fname_raw: str, ctype: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    t = gen._new_temp(ctype)
    if node.args:
        at, av = gen.lower_expr(node.args[0])
        for xa in node.args[1:]: gen.lower_expr(xa)
        if at.endswith(' *') and ctype in ('float', 'double', '__fp16', '_Bool'):
            # `Float64(some_struct)`/`Bool(some_struct)` is a genuinely
            # different call shape from `Int64(some_struct)` below — real
            # Mojo source uses it to invoke a `__float__`/conversion method
            # (e.g. FloatLiteral.__float__'s own `return Float64(self)`),
            # not to reinterpret an address. A *pointer*-to-floating-point
            # (or -to-_Bool) cast is invalid C, not just semantically wrong
            # a real `-fgimple` "invalid types in conversion to
            # floating-point" compile error (found via compile_stdlib.py
            # regressing on std/builtin/float_literal.mojo when the
            # BUG-2026-028 fix below first landed without this exclusion).
            # This codegen has no model for calling a user-defined
            # `__float__`/`__bool__` here, so keep the pre-existing (if
            # still "unsupported") placeholder for exactly this shape.
            gen._emit(f'  {t} = ({ctype})0;  /* {fname_raw}(struct) unsupported */')
        elif at.endswith(' *'):
            # BUG-2026-028: `Int64(x)`/`Int(x)`/etc. on a pointer-typed value
            # (a struct — struct locals/globals/params are ALWAYS `T *` in
            # this codegen's representation, see BUG-2026-030 — a
            # MojoList*/MojoDict*/MojoSet*, an UnsafePointer's already-erased
            # `T *`, ...) used to always drop the value and emit a constant 0
            # ("unsupported"). A pointer-to-INTEGER cast is a perfectly
            # ordinary single GIMPLE statement (the same pattern `.address`
            # in `gimple_gen_exprs.py` already relies on for exactly this),
            # so just take it — this is what callers actually want: the raw
            # bits of the object's address.
            gen._emit(f'  {t} = ({ctype}){av};')
        else:
            gen._emit(f'  {t} = ({ctype}){gen._ensure_local(at, av)};')
    else:
        gen._emit(f'  {t} = ({ctype})0;')
    return ctype, t


def _lower_opaque_ctor(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    # Single-STRING-argument opaque constructor passthrough (real:
    # `pathlib.Path(x)` / any imported class this compile never inlined,
    # constructed from one path-shaped string). This codegen represents
    # path-like values AS their char* string — the established convention
    # `/` on a char* receiver already relies on (lowered to mojo_path_join)
    # and every `.name`/`.parent`/`.resolve()` member/method dispatch below
    # consumes — so return the argument UNCHANGED with its own 'char *'
    # static type instead of re-boxing it to int64_t. Re-boxing broke that
    # convention end-to-end: the boxed result then reached member access as
    # an untyped int64_t, fell to the generic dynamic-getattr dispatch, and
    # raised a fatal runtime `AttributeError: name` (real:
    # Apple/__main__.py's module level `SCRIPT_NAME = Path(__file__).name`,
    # crashing the program before main()). Only the exact one-positional-
    # -arg, zero-kwargs, char*-argument shape takes this path; every other
    # opaque construction keeps the original first-arg-as-int64_t behavior
    # below unchanged.
    # `len(...) == 0`, NOT `not getattr(node, 'kwargs', None)`: an empty
    # kwargs list is a NON-NULL MojoList* pointer, which is truthy under
    # the self-hosted backend's pointer-nullity `not`, so the old gate was
    # False for a call with NO keywords and the char*-argument fast path
    # never ran (a real `StringRef("")` stage1-vs-stage2 divergence).
    _ctor_kw = getattr(node, 'kwargs', None) or []
    if (len(node.args) == 1 and len(_ctor_kw) == 0
            and gen._quick_type(node.args[0]) == 'char *'):
        at, av = gen.lower_expr(node.args[0])
        return at, av
    ctor_args = [gen.lower_expr(a) for a in node.args]
    t = gen._new_temp('int64_t')
    if ctor_args:
        at, av = ctor_args[0]
        if at.endswith(' *'):       gen._emit(f'  {t} = (int64_t){av};')
        elif at == 'int64_t':       gen._emit(f'  {t} = {av};')
        else:                       gen._emit(f'  {t} = (int64_t){gen._ensure_local(at, av)};')
    else:
        gen._emit(f'  {t} = (int64_t)0;')
    return 'int64_t', t


def _lower_recursive_self_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    lifted   = gen.current_func_name
    env_var  = gen._env_param
    ret_type = gen.func_ret_type or gen.func_return_types.get(lifted, 'int64_t')
    # Route through _emit_call/_call_expr (like _lower_closure_call's
    # sibling-closure-call path just below) so each argument is coerced
    # to the callee's DECLARED param type instead of passed as whatever
    # raw C type happened to fall out of lower_expr. This was always a
    # real gap here (never applied, unlike every other call-emission
    # path in this file) — previously invisible only because a
    # `__GIMPLE`-tagged lifted closure's raw pre-lowered GIMPLE body
    # bypasses gcc's normal call-argument type checking; a recursive
    # closure whose own body also contains try/except (and therefore
    # must drop `__GIMPLE`, see _reset_func's `_func_used_setjmp`
    # comment) gets compiled by the ordinary strict C frontend instead,
    # which correctly flags a mismatched arg (e.g. int64_t passed where
    # a struct pointer is declared) as a hard error. See
    # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md.
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    env_type = gen.func_param_types.get(lifted, ['void *'])[0]
    full_arg_pairs = [(env_type, env_var)] + arg_pairs
    fname_c  = gimple_ctypes._safe_name(lifted)
    if ret_type == 'void':
        return gen._void_call(fname_c, full_arg_pairs)
    return ret_type, gen._call_expr(ret_type, fname_c, full_arg_pairs)


def _lower_outer_closure_call(gen, fname_raw: str, ci, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Call a SIBLING nested closure of the same parent from inside another
    lifted closure/lambda body (`gen_module_impl`'s `_scan_body_for_local_
    field_access` calling `_scan_stmt_var_candidates`, both nested in
    `gen_module_impl`, both capturing `self`).

    The sibling's own env local belongs to the parent's scope and isn't
    visible here — but we ARE inside a lifted closure with its OWN env
    param, and sibling closures of one parent capture overlapping variables
    (`self` above all). Build a fresh env for the callee, copying each of
    its captured fields from the current env where the name matches (else
    from local scope). Only when neither source has a capture do we fall
    back to a NULL field. Previously this ALWAYS passed a NULL env — a
    documented "compiles and links, segfaults at runtime" stopgap that
    made the self-hosted `compile_to_gimple` crash the moment
    `gen_module_impl`'s field-scan helpers actually ran.
    """
    lifted    = ci.lifted_name
    ret_type  = gen.func_return_types.get(lifted, 'int64_t')
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    # Keyword arguments and omitted-with-default parameters bind here too,
    # through the same helper the direct closure-call path uses -- see
    # _bind_closure_kwargs's docstring for what silently went wrong when
    # this line stood alone.
    arg_pairs = _bind_closure_kwargs(gen, ci, node, arg_pairs)
    fname_c   = gimple_ctypes._safe_name(lifted)
    if ci.env_struct:
        _cur_env = getattr(gen, '_env_param', '')
        _cur_caps = getattr(gen, '_captures', {}) or {}
        if _cur_env and getattr(ci, 'captures', None):
            new_env = gen._new_temp(f'{ci.env_struct} *')
            gen._emit(f'  {new_env} = {gimple_ctypes._safe_name("_alloc_" + ci.env_struct)} ();')
            for vname, vtype in ci.captures:
                fld = gimple_ctypes._c_field_name(vname)
                if vname in _cur_caps:
                    tmp = gen._new_val(vtype, f'{_cur_env}->{fld}')
                    gen._emit(f'  {new_env}->{fld} = {tmp};')
                elif vname in gen.var_types:
                    gen._safe_coerce_emit(gen.var_types.get(vname, vtype), vtype,
                                          gen._write_dest(vname),
                                          f'{new_env}->{fld}')
            full_arg_pairs = [(f'{ci.env_struct} *', new_env)] + arg_pairs
        else:
            null_env = gen._new_val(f'{ci.env_struct} *', f'({ci.env_struct} *)0')
            full_arg_pairs = [(f'{ci.env_struct} *', null_env)] + arg_pairs
    else:
        full_arg_pairs = arg_pairs
    if ret_type == 'void':
        return gen._void_call(fname_c, full_arg_pairs)
    return ret_type, gen._call_expr(ret_type, fname_c, full_arg_pairs)


def _bind_closure_kwargs(gen, ci, node, arg_pairs):
    """Fill a lifted closure call's MISSING positional slots from the call's
    keyword arguments and the closure's own declared defaults.

    ONE implementation for both closure-call paths. It used to live only
    inline in `_lower_closure_call` (the direct path, where the call site
    sits in the closure's own enclosing function), which left
    `_lower_outer_closure_call` -- a call to a SIBLING closure from inside
    another lifted closure -- building its argument list from `node.args`
    alone and SILENTLY DROPPING every keyword argument. That is not a
    compile error: the callee's C prototype carries no defaults, so the
    omitted trailing parameters simply receive whatever happened to be in
    the argument registers and the callee falls back to its own defaults.
    Real: `module_gen.py`'s `_collect_method_scalar_obs` calling
    `_arg_scalar_type(caller_name, a, deep_str=True,
    prefer_refined_param=True)` observed neither flag -- and the
    resulting call, having three arguments against a six-parameter
    prototype, is only diagnosed by GCC at all when the CALLER's own
    return type is a pointer (GIMPLE's call check rides on that path), so
    it can sit here silently for a long time.

    `param_names` is the callee's OWN parameter names in declaration order
    (its `FunctionDef.params`, star prefixes stripped), which is what makes
    the name-keyed lookup below correct: `_func_param_defaults[lifted]`
    holds an entry only for the parameters that HAVE a default and starts
    at the first defaulted position, so indexing it by the call's absolute
    argument position silently mis-binds every default that follows a
    required parameter -- `def inner(a, deep=False, refine=False)` called
    `inner(x, deep=True, refine=True)` bound `refine`'s value to `deep` and
    passed a hard 0 for `refine`. The previous positional indexing was
    right only when the defaulted parameters happened to start at slot 0.

    `arg_pairs` is mutated in place and returned. An env-struct pointer
    prepended to `arg_pairs` by the caller is NOT one of the closure's own
    parameters, so callers must pass the argument list WITHOUT it (both
    call sites do: each prepends its env only after this returns).
    """
    param_names = _closure_param_names(ci)
    lifted = ci.lifted_name
    user_param_count = len(param_names)
    if user_param_count <= len(arg_pairs):
        return arg_pairs
    kwargs = getattr(node, 'kwargs', []) or []
    kwarg_dict = {kname: gen.lower_expr(kexpr) for kname, kexpr in kwargs}
    _dflt_by_name = {}
    for _dpn, _ddv in (gen._func_param_defaults.get(lifted) or []):
        _dflt_by_name[_dpn] = _ddv
    while len(arg_pairs) < user_param_count:
        _pname = param_names[len(arg_pairs)]
        if _pname in kwarg_dict:
            arg_pairs.append(kwarg_dict[_pname])
        elif _pname in _dflt_by_name:
            # Evaluate the default AST directly (self.lower_expr), not the
            # literal-only _default_expr_to_pair used for top-level free
            # functions: the extremely common
            # `def _inject(iterator=iterator, suffix=suffix): ...` idiom
            # binds the OUTER function's own live variable as the default,
            # and that variable is still in scope at the call site.
            arg_pairs.append(gen.lower_expr(_dflt_by_name[_pname]))
        else:
            arg_pairs.append(('int', '0'))
    return arg_pairs


def _closure_param_names(ci) -> list:
    """The callee closure's own parameter names, in declaration order, with
    `*`/`**` prefixes stripped (`_as_str` on each: the self-hosted backend
    erases a bare list-of-tuples element to a boxed int64_t, and a boxed
    name would miss every dict lookup in `_bind_closure_kwargs`).
    Non-`*args`/`**kwargs` positions only -- those are packed into a single
    trailing slot by `_gen_lifted_closure`'s own signature builder, so
    counting them as fillable positional slots would fabricate arguments.
    Falls back to an empty list, which makes the caller emit exactly the
    positional arguments it has, i.e. this helper's absence is never worse
    than the behaviour it replaces."""
    _names = []
    try:
        for _pp in (getattr(ci.inner_def, 'params', None) or []):
            _raw = gimple_ctypes._as_str(_pp[0])
            if _raw.startswith('*'):
                break
            _names.append(_raw.lstrip('*'))
    except Exception:
        return []
    return _names


def _lower_closure_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    lifted   = f'{gen.current_func_name}_{fname_raw}'
    env_var  = gen._closure_envs[fname_raw]
    ret_type = gen.func_return_types.get(lifted, 'int64_t')
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    # Pad missing positional args with the closure's own declared
    # defaults (`def _inject(iterator=iterator, suffix=suffix): ...`
    # called bare as `_inject()`) -- see the defaults registration in
    # the closure-scan pass (Pass 3) for why nested closures need
    # their own entry here rather than sharing the top-level
    # free-function one.
    # `len(env_var) > 0`, not a bare `if env_var`: a NON-capturing nested
    # closure has `_closure_envs[name] == ''`, and an empty C string is a
    # non-null pointer -> truthy in the self-hosted backend, so a bare
    # check wrongly prepended an empty env arg (`outer_inner (, x)`).
    _has_env = len(env_var) > 0
    _ci_here = (gen._all_closures.get(gen.current_func_name, {}) or {}).get(fname_raw)
    if _ci_here is not None:
        arg_pairs = _bind_closure_kwargs(gen, _ci_here, node, arg_pairs)
    fname_c  = gimple_ctypes._safe_name(lifted)
    if _has_env:
        # No slice inside the f-string: the self-hosted f-string parser
        # reads `[1:]` as a format spec and mis-parses the interpolation.
        env_base = env_var[1:]
        env_type = gen.func_param_types.get(lifted, [f"{env_base} *" if '_env_' in env_var else 'void *'])[0]
        full_arg_pairs = [(env_type, env_var)] + arg_pairs
    else:
        full_arg_pairs = arg_pairs
    if ret_type == 'void':
        return gen._void_call(fname_c, full_arg_pairs)
    return ret_type, gen._call_expr(ret_type, fname_c, full_arg_pairs)


def _ast_walk(body):
    """Yield every AST node under `body`. A local, structural walk: the
    lambda-capture check below only needs IdentExpr/AssignStmt/ForStmt/
    VarDecl/NamedExpr shapes, and reuses this file's existing node imports
    rather than the middle-tier walkers (whose results are self-hosted-boxed
    and would cost more than they explain here)."""
    # A lambda's `body` is a single EXPRESSION, not a statement list, so
    # normalize before walking.
    if body is None:
        return
    stack = list(body) if isinstance(body, list) else [body]
    while stack:
        n = stack.pop()
        yield n
        for _attr in ('body', 'value', 'target', 'args', 'func', 'obj',
                      'left', 'right', 'then_val', 'else_val', 'operand',
                      'key', 'val', 'elements', 'params', 'handler', 'finalbody'):
            _v = getattr(n, _attr, None)
            if _v is None:
                continue
            if isinstance(_v, list):
                stack.extend(x for x in _v if hasattr(x, '__class__') and not isinstance(x, (str, bytes, int, float)))
            elif hasattr(_v, '__class__') and not isinstance(_v, (str, bytes, int, float)):
                stack.append(_v)


def _bound_names(gen) -> set:
    """Names that are NOT enclosing locals: module globals, plus everything
    reachable as a builtin/attribute rather than a bare identifier."""
    out = set(getattr(gen, '_global_var_types', {}) or {})
    out |= set(getattr(gen, 'func_return_types', {}) or {})
    out |= set(getattr(gen, 'struct_field_types', {}) or {})
    out |= set(getattr(gen, 'imported_symbols', {}) or {})
    out |= set(getattr(gen, '_class_attrs', {}) or {})
    return out


def _lambda_site(node) -> str:
    _l = getattr(node, 'line', None)
    return f"line {_l}" if _l else "an unknown line"


def _lower_LambdaExpr(gen, node) -> tuple:
    """Lift a lambda expression to a top-level C function.

    Returns a (void *, static_ptr_name) pair so the lambda can be passed
    as a function pointer.  The actual body is accumulated in
    self._lambda_parts and flushed by gen_module into func_parts.
    """
    # A capturing lambda whose local never escapes is beta-reduced at its
    # call sites (see _lower_inlined_lambda_call), so it must NOT also be
    # lifted: the lifted pass would emit the same body a second time, as a
    # top-level function naming variables that do not exist in it.
    # Check the STAMP, not the map: the map is rebuilt per function and
    # cleared whenever a lifted closure calls `_reset_func`, so a lambda
    # lowered after that point would see an empty map even though the scan
    # already classified it. The stamp is set on the node once, at the
    # enclosing function's `_reset_func`, and persists.
    _bl = getattr(node, '_bound_local', None)
    if _bl:
        # Record the reduction under the LOCAL's name. The call site reads
        # this map rather than re-scanning, because by the time a call is
        # lowered `gen._cur_func_body` may belong to some other function: a
        # lifted closure calls `_reset_func` too, and a re-scan then sees
        # the closure's body instead of the enclosing one's. Recording at
        # the assignment is scope-correct by construction — that is
        # definitionally the enclosing function's own statement — and the
        # map is cleared at the real per-function entry points.
        _inl = getattr(gen, '_inlined_lambdas', None)
        if _inl is None:
            _inl = {}
            gen._inlined_lambdas = _inl
        _inl[_bl] = node
        return 'int64_t', gen._new_val('int64_t', '0')

    # A capturing lambda we could NOT reduce — because its local escapes, is
    # rebound, or it declares *args/**kwargs — still lifts to a top-level
    # function that does not contain the names it reads, and each such read
    # stubs to 0. That is a real remaining defect, and NOT fixed here.
    #
    # It was tempting to refuse these outright, as the generator and
    # nested-async paths do, but the escape analysis is new and static, and
    # the blast radius is not: it fires on real, CENTRAL stdlib modules —
    # importlib/util.py (8 sites, including the LazyLoader
    # `lambda *args, **kwargs: cls(loader(*args, **kwargs))` this bug doc
    # names), functools.py (4), enum.py (3). Refusing those would trade a
    # silently-wrong value inside an otherwise-compiling module for a module
    # that stops compiling, on the strength of a false positive in a
    # same-day heuristic. Not a good trade.
    #
    # So: land the unconditional win (an ordinary capturing lambda called
    # through its local is now inlined and CORRECT, verified below) and
    # record the rest as the remaining work, with the corpus instances named
    # so whoever extends this to the env-struct path starts from evidence
    # rather than a search. See
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.

    outer_ctx = gen.current_func_name or 'root'
    gen._lambda_counter += 1
    lifted_name = f'{outer_ctx}_lambda_{gen._lambda_counter}'

    # Build a synthetic FunctionDef whose body is `return <lambda.body>`
    syn_body = [gimple_ctypes.ReturnStmt(value=node.body)]
    # Lambda params are (pname, default_value) not (pname, type_ann).
    # Strip defaults so _gen_lifted_closure doesn't try to resolve them as types.
    # Plain unpack loop, NOT `[(p, None) for p, _ in node.params]` — a
    # comprehension's target unpack over a `list[tuple[str, str]]` boxes
    # both slots to int64_t self-hosted.
    syn_params = []
    for _pn, _pt in node.params:
        syn_params.append((_pn, None))
    syn_def  = gimple_ctypes.FunctionDef(
        name=lifted_name,
        params=syn_params,
        return_type=None,
        body=syn_body,
    )

    # Infer param types from captures + existing var_types context.
    # `node.params` elements are (pname, default_value_AST_or_None) —
    # NOT (pname, type_ann) — so the `pname` branch below only ever
    # fires for a default-less param; a defaulted param's second
    # element is an expression node (never `None`), so it always
    # skipped this loop entirely. That silently missed the standard
    # tkinter-callback idiom `lambda e, self=self: ...` (bind an
    # outer-scope value into the lambda without a real closure) —
    # including the common `lambda e, w=window: ...` shape where the
    # default's identifier differs from the param name — so a
    # captured struct-pointer param like `self` never got its real
    # ctype recorded here and fell back to a generic `int64_t` default
    # a few lines down in `_gen_lifted_closure`, while the forward
    # declaration built from THIS list (a few lines below) kept
    # whatever `pname` itself resolved to. Two lambdas differing only
    # in whether their default-bound param happened to coincide with
    # `pname` could each end up with a mismatched decl-vs-definition
    # ctype for the same lifted name, a "conflicting types" hard
    # error (real repro: Tools/unittestgui/unittestgui.py's
    # `errorListbox.bind("<Double-1>", lambda e, self=self: self.
    # showSelectedError())`).
    # Only an EXPLICIT default binds an outer value (`lambda e, self=self: ...`,
    # the tkinter idiom). The old `default is None and pname in var_types`
    # fallback treated ANY parameter that happened to share a name with a
    # visible variable as a capture — and a call site that types the callee's
    # parameters before lowering the call (map/filter/sorted keys bind the
    # element variable to the lambda's param name) makes that true for every
    # parameter. With the env-based capture below, such a param also got an
    # env FIELD it never read, and the body then emitted `_env->v` against a
    # struct with no such member ("'main_lambda_1_env' has no member named
    # 'v'"). A real default is the only thing that can capture here.
    captures = []
    for pname, default in node.params:
        if isinstance(default, gimple_ctypes.IdentExpr) and default.name in gen.var_types:
            captures.append((pname, gen.var_types[default.name]))

    # A lambda that reads an ENCLOSING FUNCTION'S LOCAL cannot be lifted to a
    # top-level C function as-is: there is no env to read it from, and the
    # bare-function-pointer calling convention (`mojo_fnptr_call_N`, which is
    # also what `map`/`filter`/`sorted(key=)` use) has nowhere to put one.
    # It used to be emitted anyway, with the local read as a hard 0:
    #     d = {"a": 1}
    #     f = lambda k: d[k]
    #     print(f("a"))          ->  0
    # so the program ran and produced a WRONG answer. Refuse instead, so the
    # module falls back to interpreting from source and the answer is right
    # (the same trade every other unsupported shape makes here).
    #
    # Module GLOBALS are not a capture — a lifted lambda reads those through
    # `_root_globals` and works — so they are excluded, as are the lambda's
    # own params/bindings and anything reachable only through a default
    # argument (`lambda e, self=self: ...`, the existing capture form).
    _bound = set()
    for _pn, _pd in node.params:
        _bound.add(_pn)
    for _n2 in _ast_walk(node.body):
        if isinstance(_n2, gimple_ctypes.AssignStmt) and isinstance(_n2.target, gimple_ctypes.IdentExpr):
            _bound.add(_n2.target.name)
        elif type(_n2).__name__ == 'ForStmt':
            _tg = getattr(_n2, 'target', None)
            for _tv in (_tg if isinstance(_tg, list) else [_tg]):
                if isinstance(_tv, gimple_ctypes.IdentExpr):
                    _bound.add(_tv.name)
        elif isinstance(_n2, gimple_ctypes.VarDecl):
            _bound.add(_n2.name)
        elif type(_n2).__name__ == 'NamedExpr':
            _bound.add(_n2.target.name)
    _captured = []
    for _n2 in _ast_walk(node.body):
        if isinstance(_n2, gimple_ctypes.IdentExpr):
            _nm = _n2.name
            if _nm in _bound or _nm in _bound_names(gen):
                continue
            if _nm in gen.var_types and _nm not in gen._global_var_types:
                if _nm not in _captured:
                    _captured.append(_nm)
    # Real captures. A lambda that reads the enclosing function's locals
    # cannot be a bare function pointer — the values have nowhere to live in
    # a code address — so it becomes a MojoBoundMethod: the lifted function
    # takes a heap env as its FIRST parameter (the same "self, then N
    # ordinary args" shape every compiled struct method and
    # mojo_bound_method_call_N already use) and the value materialized at the
    # reference site is `mojo_bound_method_new(fn, env)`. Every call site
    # already routes through mojo_fnptr_call_N, which dispatches on the
    # callee, so a closing lambda works anywhere a plain one does — as a
    # map/filter/sorted callable, called directly, or handed to code this
    # compiler never saw.
    #
    # It used to be emitted with every capture read as a hard 0:
    #     def cached(...):
    #         return cas.get_or_build_text(key, ext,
    #             lambda: compile_to_gimple(mojo_src, do_imports, filename), cache)
    # built the WRONG artifact from a null source. That stayed latent only
    # because the self-hosted binary compiles uncached and never calls the
    # builder.
    _capture_types = []
    for _cn in _captured:
        _ct = gen.var_types.get(_cn, 'int64_t')
        if _ct in ('int', 'int64_t', '_Bool', 'char', 'double') or _ct.endswith(' *'):
            _capture_types.append((_cn, _ct))
        else:
            _capture_types.append((_cn, 'int64_t'))
    # The env must have a field for EVERY name the body reads through it, and
    # `_gen_lifted_closure` sets `gen._captures` from the whole `ci.captures`
    # — which includes the default-argument captures (`lambda k, d=d: d[k]`).
    # Emitting fields for the implicit captures alone left the body reading
    # `_env->d` against a struct without one. So the env covers both, and the
    # materialization site fills both (a default's value is its own default
    # expression, evaluated where the lambda is referenced).
    _env_fields = [(pn, ct) for pn, ct in captures] + _capture_types
    _seen_f = set()
    _env_fields = [(n, c) for n, c in _env_fields if not (n in _seen_f or _seen_f.add(n))]
    _env_struct = f'{lifted_name}_env' if _env_fields else ''

    ci = gimple_solvers.ClosureInfo(
        lifted_name=lifted_name,
        env_struct=_env_struct,
        captures=_env_fields,
        inner_def=syn_def,
    )
    # Register return type and param types now so call sites resolve correctly
    ret_type = gen._infer_return_type(syn_body)
    gen.func_return_types[lifted_name] = ret_type
    param_ctypes = []
    seen_lambda_varargs = False
    for pname, ptype in node.params:
        # A lambda's own *args/**kwargs (e.g. `lambda *args, **kwargs:
        # cls(loader(*args, **kwargs))`, importlib/util.py's LazyLoader.
        # factory) must resolve to the SAME concrete MojoList*/MojoDict*
        # convention _gen_lifted_closure's real param-building loop
        # below uses for the actual definition (see its `pname.
        # startswith('**')`/`startswith('*')` branches) — this list
        # feeds the forward declaration / static fn-pointer cast type,
        # which must match the definition exactly or GCC rejects it as
        # "conflicting types". Previously this loop had no `*`/`**`-
        # prefix handling at all: a literal `'*args'`/`'**kwargs'` name (the
        # star baked into the string) never matched anything in
        # var_types below, so both fell through to the plain `int64_t`
        # default — a forward decl silently mismatched against the
        # real MojoList*/MojoDict* body it was declaring.
        if pname.startswith('**'):
            param_ctypes.append('MojoDict *')
        elif pname.startswith('*'):
            if not seen_lambda_varargs:
                param_ctypes.append('MojoList *')
                seen_lambda_varargs = True
        # Lambda params: second element is default value (AST node), not a type annotation.
        # Resolve from var_types context; default to int64_t.
        elif pname in gen.var_types:
            param_ctypes.append(gen.var_types[pname])
        else:
            param_ctypes.append('int64_t')
    gen.func_param_types[lifted_name] = param_ctypes

    # Generate the lifted function body and queue for emission
    # Save/restore per-function state around the nested codegen
    saved_decls          = gen.decls
    saved_body           = gen.body_lines
    saved_var_types      = dict(gen.var_types)
    saved_func_name      = gen.current_func_name
    saved_ret_type       = gen.func_ret_type
    saved_bb             = gen.bb_counter
    saved_temp           = gen.temp_counter
    saved_captures       = dict(gen._captures)
    saved_env            = gen._env_param
    saved_inner          = gen._inner_func_name
    saved_loop_stack     = list(gen.loop_stack)
    saved_loop_depth     = gen._loop_depth
    saved_closure_envs   = dict(gen._closure_envs)
    saved_func_decl_glob = set(gen._func_declared_globals)
    saved_func_decl_nonlocal = set(gen._func_declared_nonlocals)

    # Expose outer closure info so the lambda body can resolve calls to parent
    # nested functions (e.g. compile_one_object) via their lifted C names with
    # a null env pointer (safe at link time; runtime env is unavailable in lambda).
    outer_closures_for_lambda = {}
    outer_all_closures = gen._all_closures.get(outer_ctx, {})
    for _inner_n, _env_v in saved_closure_envs.items():
        _outer_ci = outer_all_closures.get(_inner_n)
        if _outer_ci:
            outer_closures_for_lambda[_inner_n] = _outer_ci
    gen._lambda_outer_closures = outer_closures_for_lambda

    body_code = gen._gen_lifted_closure(ci)
    gen._lambda_outer_closures = {}

    if _env_struct:
        # Built from `ci.captures` AFTER the body was generated, not from the
        # list computed up front, and unioned with the read set scanned out
        # of that body below: it is `ci.captures` that becomes
        # `gen._captures`, i.e. what the body reads as `_env-><name>`, and a
        # struct built from a shorter list compiles fine until the body
        # references a member the struct does not have. The definition is
        # emitted ahead of the forward declaration, so the typedef still
        # precedes both in the output.
        # The definitive read set is the generated body itself: with an env
        # present, `_lower_IdentExpr` emits `_env-><name>` for every name it
        # could not resolve locally, so the body names exactly the fields the
        # struct must have. Deriving them from the emitted text (rather than
        # from ci.captures or gen._captures, which are the SEED and neither
        # covers what the lowering went on to read) is what keeps the struct
        # and the body in agreement — a struct missing a field the body reads
        # is a hard "'X_env' has no member named 'Y'", and the names involved
        # are ordinary enclosing locals (`gcc`, `workdir`, `module_name`) plus
        # the genexp induction variables and whatever the C++ paths resolve
        # for themselves.
        import re as _re
        _read = set(_re.findall(r'_env->([A-Za-z_][A-Za-z_0-9]*)', body_code or ''))
        _final = []
        _seen_c = set()
        # …unioned with the two seeding sources, because not every lifted
        # lambda's body lands in `body_code`: the C++ emitters (async units,
        # for/zip-longest) emit theirs into their own text, and for those the
        # body scan sees nothing while `gen._captures`/`ci.captures` do.
        for _src in (getattr(gen, '_captures', None) or {},
                     getattr(ci, 'captures', None) or []):
            # `gen._captures` is a dict, `ci.captures` a list of pairs.
            _read |= set(_src.keys()) if isinstance(_src, dict) else {n for n, _c in _src}
        _known = {n: c for n, c in _env_fields}
        _known.update({n: c for n, c in (getattr(ci, 'captures', None) or [])})
        _known.update(dict(getattr(gen, '_captures', None) or {}))
        for _cn in sorted(_read):
            if _cn in _seen_c:
                continue
            _seen_c.add(_cn)
            _ct = _known.get(_cn)
            if not (_ct in ('int', 'int64_t', '_Bool', 'char', 'double') or
                    (_ct or '').endswith(' *')):
                _ct = 'int64_t'
            _final.append((_cn, _ct))
        # Dedupe the typedef as a BLOCK, keyed by its closing line — never
        # per line. The per-line form silently DROPPED a field whose
        # declaration text an EARLIER lambda in the same enclosing function
        # had already contributed, because a field line
        # (`  int64_t _IL;`) says nothing about which struct it belongs to:
        # `_gen_stmt_ForStmt`'s `_neg1 = lambda: ... _IL(1)` emitted
        # `_gen_stmt_ForStmt_lambda_1_env`'s block with `  int64_t _IL;`, and
        # the very next lambda (`_minus1 = lambda e: _BO('-', e, _IL(1))`,
        # which reads BOTH `_BO` and `_IL` through the env) then found its
        # own `  int64_t _IL;` "already emitted" and skipped it — so its
        # struct came out with `_BO` only, while the body still emitted
        # `_env->_IL`, a hard "'_gen_stmt_ForStmt_lambda_2_env' has no
        # member named '_IL'". Same shape for
        # `_gen_cpp_generator_unit_lambda_1_env`'s `  GimpleGen * gen;`
        # starving `_gen_cpp_async_unit_lambda_2_env` (empty struct, body
        # reading `_env->gen`), and for
        # `_gen_for_zip_longest_lambda_1_env`'s `  int64_t p;` starving
        # lambda_2/lambda_3 (three identical-field structs, so the last two
        # came out EMPTY). A repeated capture is the NORMAL case — sibling
        # lambdas in one function overwhelmingly share the enclosing
        # locals — so the per-line guard dropped a field in almost every
        # multi-lambda function. `} <name>;` is unique per struct, so
        # testing the closing line keys the block correctly, and appending
        # all-or-nothing keeps a struct's fields contiguous (appending a
        # late field line after another struct's `};` would not compile
        # either).
        _env_typedef = ([f'typedef struct {_env_struct} {{']
                        + [f'  {_ct} {_cn};' for _cn, _ct in _final]
                        + [f'}} {_env_struct};'])
        if _env_typedef[-1] not in gen._elaborated_externs:
            for _line in _env_typedef:
                gen._elaborated_externs.append(_line)
            # A closing lambda's env is heap-allocated from a `__GIMPLE` body,
            # and `sizeof` is not a valid GIMPLE operand — so the size comes
            # from a plain-C accessor, defined HERE, next to the typedef it
            # needs and ahead of every body that allocates one. This env's
            # typedef is emitted into the preamble rather than by
            # gen_module's closure-typedef passes, so the accessor has to be
            # registered here too or the beta-reduced/inlined form
            # (`_inlined_lambdas`, the shape that inlines the lambda body into
            # the enclosing function) calls an undefined helper.
            # See GimpleGen._c_sizeof_helper / _c_helper_def.
            _env_h = gen._c_sizeof_helper(_env_struct)
            _env_hd = gen._c_helper_def(_env_h)
            if _env_hd:
                gen._elaborated_externs.append(_env_hd)
                gen._elaborated_externs.append('')

    gen.decls                   = saved_decls
    gen.body_lines              = saved_body
    gen.var_types               = saved_var_types
    gen.current_func_name       = saved_func_name
    gen.func_ret_type           = saved_ret_type
    gen.bb_counter              = saved_bb
    gen.temp_counter            = saved_temp
    gen._captures               = saved_captures
    gen._env_param              = saved_env
    gen._inner_func_name        = saved_inner
    gen.loop_stack              = saved_loop_stack
    gen._loop_depth             = saved_loop_depth
    gen._closure_envs           = saved_closure_envs
    gen._func_declared_globals  = saved_func_decl_glob
    gen._func_declared_nonlocals = saved_func_decl_nonlocal

    gen._lambda_parts.append(body_code)
    gen._lambda_parts.append('')

    # Forward declaration so the preamble's static pointer initialiser can
    # reference the function before its definition appears in the output.
    # Param names must have their `*`/`**` prefix stripped here too (bare
    # `args`/`kwargs`, matching _gen_lifted_closure's real definition) —
    # left raw, `MojoList * *args` parses in C as `args: MojoList **`
    # (an extra, unintended level of pointer-ness from the literal `*`
    # character surviving into the declared NAME), a second, subtler
    # "conflicting types" mismatch beyond the ctype-only bug fixed above.
    params_str = ', '.join(
        f'{ct} {pn.lstrip("*")}' for ct, (pn, _) in zip(param_ctypes, node.params)
    ) or 'void'
    if _env_struct:
        # The env leads, matching both `_gen_lifted_closure`'s real
        # definition and the "self, then N ordinary args" convention
        # mojo_bound_method_call_N calls through.
        params_str = f'{_env_struct} * _env' + (', ' + params_str if params_str != 'void' else '')
    # Mirror the DEFINITION's own parameter resolution, which
    # `_gen_lifted_closure` caches in `ci.inferred_params` for precisely this
    # purpose. `param_ctypes` above is an INDEPENDENT computation, and the two
    # can disagree whenever a call site has typed the callee's parameters
    # before lowering the call — `sorted(d, key=lambda k: d[k])` binds the
    # dict's `char *` key element to the lambda's parameter, so the
    # declaration said `char * k` while the definition inferred `int64_t`,
    # and GCC rejected the pair as conflicting types.
    _inferred = getattr(ci, 'inferred_params', None)
    if _inferred:
        _mirrored = []
        for _pn, _ in node.params:
            if _pn.startswith('*'):
                continue
            _bare = _pn.lstrip('*')
            _ct = _inferred.get(_pn) or _inferred.get(_bare)
            if _ct:
                _mirrored.append(f'{_ct} {gen._param_safe_name(_bare)}')
        if _mirrored:
            params_str = ', '.join(_mirrored)
            if _env_struct:
                params_str = f'{_env_struct} * _env, ' + params_str
    # Re-read the return type from func_return_types instead of the
    # `ret_type` local computed above (BEFORE the body was generated):
    # `_gen_lifted_closure` (just above) independently re-infers the
    # real return type from the SAME body and overwrites `func_return_
    # types[lifted_name]` with its own answer (gimple_codegen.py's
    # `self.func_return_types[ci.lifted_name] = ret_type` inside
    # `_gen_lifted_closure`) — and the two inference calls can DISAGREE
    # (different `self` context/state at each call site: this one runs
    # before any capture/var_types seeding for the lifted function,
    # `_gen_lifted_closure`'s runs after). Using the stale early value
    # here produced a forward declaration with the WRONG return type,
    # invisible until the struct-method `_lambda_parts`-flush fix above
    # started actually emitting the (correct) definition next to it —
    # confirmed via Lib/zipfile/__init__.py's `ZipFile.open`'s `lambda:
    # self._writing`: forward-declared `_Bool ZipFile_open_lambda_1
    # (void)` (this function's own early, pre-body-gen guess) but
    # DEFINED `int64_t ZipFile_open_lambda_1 (void)` (the real,
    # post-body-gen answer) — a hard "conflicting types" error.
    ret_type = gen.func_return_types.get(lifted_name, ret_type)
    fwd_decl = f'{ret_type} {lifted_name} ({params_str});'
    if fwd_decl not in gen._elaborated_externs:
        gen._elaborated_externs.append(fwd_decl)
    # The closing-lambda reference site builds a `mojo_bound_method_new(fn,
    # env)`, and casting the function designator is not a valid GIMPLE
    # operand, so it goes through a plain-C accessor — defined HERE, after the
    # forward declaration above (which is what makes the name declared at this
    # point in the file) and before every body that takes its address.
    # See GimpleGen._c_fnaddr_helper / _c_helper_def.
    _fa_h = gen._c_fnaddr_helper(lifted_name)
    _fa_hd = gen._c_helper_def(_fa_h)
    if _fa_hd:
        gen._elaborated_externs.append(_fa_hd)
        gen._elaborated_externs.append('')
    if lifted_name not in gen.func_return_types:
        gen.func_return_types[lifted_name] = ret_type
    if not _env_struct:
        gen._funcptr_builtins_needed.add(lifted_name)
        static_name = f'_funcptr_{lifted_name}'
        t = gen._new_val('void *', static_name)
        return 'void *', t

    # A closing lambda's value: a heap env holding the captured values,
    # wrapped in the bound method that re-supplies it as the leading
    # argument. NOT registered in `_funcptr_builtins_needed` — the bare
    # static function-pointer form is wrong for this shape (its signature
    # now leads with the env), and nothing needs it.
    _vp = gen._new_temp('void *')
    _envp = gen._new_temp(f'{_env_struct} *')
    # The size comes from a non-GIMPLE accessor, and likewise the function
    # address below: `sizeof(S)` and `(void *)f` are both invalid GIMPLE
    # operands ("expected expression before 'sizeof'", "invalid operand in
    # unary operation"), so they are reached through tiny `static` accessors
    # the body calls. See GimpleGen._c_sizeof_helper / _c_fnaddr_helper.
    _sz = gen._new_temp('int64_t')
    gen._emit(f'  {_sz} = {gen._c_sizeof_helper(_env_struct)} ();')
    gen._emit(f'  {_vp} = malloc ({_sz});')
    gen._emit(f'  {_envp} = ({_env_struct} *) {_vp};')
    # Which names come from a default argument (value = that expression at
    # this reference site) rather than from an enclosing local (value = the
    # variable).
    _default_src = {pn: dv for pn, dv in node.params if dv is not None}
    for _cn, _ct in _env_fields:
        _src = _default_src.get(_cn)
        if _src is not None:
            _st, _sv = gen.lower_expr(_src)
            _cv = (gen._coerce_to_type(_st, _ct, _sv) if _ct.endswith(' *')
                   else gen._new_val('int64_t', f'(int64_t){_sv}'))
        elif _ct.endswith(' *'):
            # The env FIELD is a pointer, which on its own says nothing about
            # what belongs in it: two different captures both land here, and the
            # local's OWN C type is the only thing that tells them apart.
            #
            #   * local is itself a pointer (`MojoDict * d`) — a by-VALUE
            #     capture of a pointer. The field is the same pointer type, so
            #     it wants the local's VALUE. Storing `&d` here instead makes
            #     the body read `_env->d` as the first 8 bytes of the address
            #     of the local: stack garbage, so every lookup through it is
            #     wrong and it segfaults about half the time. Found by
            #     `sorted(d, key=lambda k: d[k])`, whose lambda captures `d`.
            #   * local is a scalar (`int64_t checksum`, `{mut checksum}`) — a
            #     capture taken BY REFERENCE, and the field is a pointer TO the
            #     local. Coercing the bare name emitted `_t8 = checksum;`
            #     against an `int64_t *` temp, a non-trivial conversion in
            #     'var_decl' and a hard error
            #     (benchmarks/memory/bench_heap_parallel).
            #
            # Neither the field's type nor "always coerce" nor "always take the
            # address" is right; branching on the local's type is.
            _local_t = gen.var_types.get(_cn, 'int64_t')
            if _local_t.endswith(' *'):
                _cv = gen._coerce_to_type(_local_t, _ct, _cn)
            else:
                _cv = gen._new_temp(_ct)
                gen._emit(f'  {_cv} = ({_ct}) &{_cn};')
        elif _ct == 'double':
            _cv = gen._new_val('double', f'(double){_cn}')
        else:
            _cv = gen._new_val('int64_t', f'(int64_t){_cn}')
        gen._emit(f'  {_envp}->{_cn} = {_cv};')
    _fnv = gen._new_temp('void *')
    gen._emit(f'  {_fnv} = {gen._c_fnaddr_helper(lifted_name)} ();')
    _bm = gen._call_expr('MojoBoundMethod *', 'mojo_bound_method_new',
                         [('void *', _fnv), ('void *', gen._new_val('void *', _envp))])
    return 'void *', gen._new_val('void *', f'(void *){_bm}')


def _lower_async_closure_construct(gen, key: tuple, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Construct (never run the body of) a nested async closure — see
    _async_closure_api's registration in gen_module and this call
    site's caller in _lower_call. Returns (handle_expr, value_ctype);
    the caller decides whether consuming that handle as a value is
    allowed (only when value_ctype == 'void' — see the caller)."""
    api = gen._async_closure_api[key]
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    for cap_name, cap_ctype in api['captures']:
        arg_pairs.append(gen.lower_expr(gimple_ctypes.IdentExpr(name=cap_name)))
    handle = gen._call_expr('MojoAsync *', f"{api['base']}_start", arg_pairs)
    return handle, api['value_ctype']


def _emit_asyncio_run_drive(gen, base: str, vct: str, arg_pairs: list) -> tuple[str, str]:
    """`asyncio.run(f(...))`'s real drive-to-completion sequence for
    ANY compiled-async-coroutine API sharing the `_start`/`_value`/
    `_destroy`/`_translate_pending_exc` shape (self._async_api's
    top-level functions AND self._async_closure_api's nested async
    closures/functions alike) — construct via `_start`, schedule +
    run Step A's scheduler to completion, translate any pending
    exception (Step E's own convention — see _gen_cpp_async_unit's
    promise exc/exc_pending fields), then read back the value (skipped
    for a genuinely void-returning coroutine, matching device_
    context.mojo's own wrapper closures — a `void` GIMPLE local is
    invalid C) and destroy the frame. Factored out of _lower_call's
    `asyncio.run(...)` branch so the nested-async-closure case (test_
    asyncrt.mojo's `asyncio.run(test_asyncrt_add[1](10))`) doesn't
    duplicate this same real sequence a second time."""
    handle = gen._call_expr('MojoAsync *', f"{base}_start", arg_pairs)
    gen._emit(f"  mojo_async_schedule_ready ({handle});")
    gen._emit(f"  mojo_async_run_until_complete ();")
    gen._emit(f"  {base}_translate_pending_exc ({handle});")
    pending_t = gen._new_val('int', "mojo_exc_pending_get ()")
    bb_pending = gen._new_bb()
    bb_ok = gen._new_bb()
    gen._emit(f"  if ({pending_t}) goto {bb_pending}; else goto {bb_ok};")
    gen._emit_label(bb_pending)
    gen._emit(f"  mojo_exc_pending_set (0);")
    gen._emit(f"  {base}_destroy ({handle});")
    gen._emit("  mojo_raise ();")
    gen._emit_label(bb_ok)
    if vct == 'void':
        gen._emit(f"  {base}_destroy ({handle});")
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
    result = gen._new_val(vct, f"{base}_value ({handle})")
    gen._emit(f"  {base}_destroy ({handle});")
    return vct, result


def _lower_inlined_lambda_call(gen, lam, node) -> tuple[str, str]:
    """Lower `f(args)` where `f` is a beta-reducible capturing lambda, by
    binding the lambda's parameters to the arguments as ordinary locals of
    the CURRENT scope and lowering its body expression right there.

    The parameters are declared and then un-declared around the body: a
    lambda's parameter names are its own scope, so leaving them in
    `var_types` would let a later statement in the enclosing function see
    a name that does not exist there. Restoring `var_types` (and only it)
    afterwards is what keeps the binding invisible."""
    pnames = _gld._param_names(lam)
    defaults = _gld._param_defaults(lam)
    saved = dict(gen.var_types)
    try:
        for i, pname in enumerate(pnames):
            if i < len(node.args):
                at, av = gen.lower_expr(node.args[i])
                gen._declare_var(pname, at)
                gen._safe_coerce_emit(at, at, av, gen._write_dest(pname))
            else:
                dv = defaults[i] if i < len(defaults) else None
                if dv is None:
                    continue
                dt, dvv = gen.lower_expr(dv)
                gen._declare_var(pname, dt)
                gen._safe_coerce_emit(dt, dt, dvv, gen._write_dest(pname))
        return gen.lower_expr(lam.body)
    finally:
        gen.var_types = saved


def _lower_fnptr_call(gen, fname_raw: str, var_ctype: str,
                      node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Emit a call through a function pointer stored in a local/captured variable.

    Uses mojo_fnptr_call_N() runtime helpers because __GIMPLE functions cannot
    cast-and-call in a single expression.  All args are widened to int64_t;
    the result is then narrowed to the expected return type.
    """
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    n = len(arg_pairs)
    # Load the raw function pointer value.
    # For captured vars, _lower_IdentExpr reads from _env->name.
    # For a module-level GLOBAL not shadowed by a same-named local (the
    # `fname_raw not in self.var_types` half of the caller's ctype
    # lookup — see _lower_call's `_global_var_types.get(...)` fallback,
    # added for BUG-2026-049), the raw Mojo name is NOT a valid C
    # identifier on its own: a global is stored in the `_root_globals`
    # struct (or a per-module globals struct — see `_global_to_module`),
    # not as a bare C variable, so `self._c_names.get(fname_raw,
    # fname_raw)` below would emit a reference to an undeclared local
    # named e.g. `_helper_add` instead of the real `_root_globals.
    # _helper_add` field. Route through the SAME general IdentExpr
    # lowering every other global read already uses (`_lower_IdentExpr`,
    # ~line 6521 "Module-level global variable") instead of
    # hand-rolling the field access here a second time.
    if fname_raw in gen._captures and gen._env_param:
        fp_type, fp_raw = gen.lower_expr(gimple_ctypes.IdentExpr(name=fname_raw))
    elif fname_raw not in gen.var_types and fname_raw in gen._global_var_types:
        fp_type, fp_raw = gen.lower_expr(gimple_ctypes.IdentExpr(name=fname_raw))
    else:
        fp_raw = gen._c_names.get(fname_raw, fname_raw)
        fp_type = var_ctype
    ret_type = gen.func_return_types.get(fname_raw, 'int64_t')
    # A libm call's C return type is a property of the C FUNCTION, not of
    # this module's inference: `sqrt` is `double sqrt(double)` whatever the
    # argument infers as. Without this the call was typed int64_t and the
    # double result was truncated on the way out — `sqrt(x) + exp(x) +
    # log(x)` at x=1.0 printed `3` where CPython prints 3.718281828459045.
    # Same table BUILTIN_VALUE_MAP's symbol entries come from, so the
    # symbol and its type cannot disagree.
    if fname_raw in gimple_ctypes._LIBM_FN_RETVALS and fname_raw not in gen.func_return_types:
        ret_type = gimple_ctypes._LIBM_FN_RETVALS[fname_raw]
    return gen._lower_fnptr_call_value(fp_type, fp_raw, node, ret_type)


def _lower_fnptr_call_value(gen, fp_type: str, fp_raw: str, node: gimple_ctypes.CallExpr,
                            ret_type: str = 'int64_t') -> tuple[str, str]:
    """Emit a call through an already-lowered function-pointer VALUE
    (`fp_raw`, of C type `fp_type`), the value-based twin of
    _lower_fnptr_call (shared so an arbitrary callable VALUE — e.g. the
    result of a chained `factory()(5)` call expression — dispatches
    through the same mojo_fnptr_call_N runtime helpers)."""
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    n = len(arg_pairs)
    # Cast to void * so the runtime helper receives a stable pointer type.
    if fp_type != 'void *':
        fp_void = gen._new_val('void *', f'(void *){fp_raw}')
    else:
        fp_void = fp_raw
    # Widen each arg to int64_t. Index the pair (`_ap[0]`/`_ap[1]`), don't
    # unpack it in the for-clause (`for at, av in arg_pairs`) — the
    # established boxing bug: a 2-tuple unpack re-boxes `av` to int64_t
    # even when it was a char*/pointer, and the erased value then landed
    # in `f'(int64_t){av}'` as a decimal address — confirmed via a real
    # --dump-full fire.py determinism diff at myinterpreter.py:1027's
    # `return func(interpreter, *args, **kwargs)`.
    widened = []
    for _ap in arg_pairs:
        at, av = _as_str(_ap[0]), _as_str(_ap[1])
        if at == 'int64_t':
            widened.append(av)
        else:
            widened.append(gen._new_val('int64_t', f'(int64_t){av}'))
    # Emit the runtime-helper call; helpers exist for 0..4 args.
    helper = f'mojo_fnptr_call_{min(n, 4)}'
    call_args = ', '.join([fp_void] + widened[:4])
    raw_t = gen._new_val('int64_t', f'{helper} ({call_args})')
    if ret_type in ('int64_t', 'int'):
        return ret_type, raw_t
    if ret_type == 'void':
        gen._emit(f'  {helper} ({call_args});')
        return 'int', gen._new_val('int', '0')
    # Narrow back to declared return type.
    t = gen._new_val(ret_type, f'({ret_type}){raw_t}')
    return ret_type, t


def _expand_sole_spread_into_fixed_slots(gen, node, fname, fname_raw,
                                          arg_pairs, expected_params):
    """`f(*iterable)` against a callee with KNOWN, FIXED positional params
    (no `*args`/`**kwargs` of its own — those forwarding shapes are
    deliberately excluded below): real Python unpacks the iterable's
    ELEMENTS positionally into f's parameter slots. This call shape
    previously fell out of _lower_UnaryOp's spread pass-through as a
    single ('MojoList *', lst) pair, which the generic coercion then
    cast to the FIRST fixed param's type and passed as argument 0 —
    so `convertdir(*sys.argv[1:])` (Tools/unicode/gencodec.py's main)
    received the whole argv-slice LIST POINTER as its `char * dir`
    parameter, every downstream os.path/os.listdir operation on it hit
    garbage, and the loop silently ran zero times because
    opendir(list-pointer-as-path) fails.

    Expands the spread across ALL fixed slots, each guarded by an in-range
    check: slot i past the list's end falls back to the callee's own
    recorded parameter DEFAULT (same _func_param_defaults source the
    missing-argument padding loops use), else a typed zero — mirroring
    `convertdir(dir)` leaving dirprefix/nameprefix/comments at their
    defaults. Surplus list elements beyond the fixed slots are ignored,
    matching _lower_named_call's documented surplus-drop convention.

    Narrow shape on purpose: exactly one '*'-spread as the SOLE positional
    argument, no '**'-spread, no literal keyword args, and only concrete
    fixed C param types. Returns arg_pairs unchanged for every other shape.

    Shared by `_lower_named_call` (value-consuming call sites) and
    _gen_stmt_ExprStmt's statement-level twin (bare, value-discarding
    calls — which never reach _lower_named_call at all)."""
    if not (len(node.args) == 1
            and isinstance(node.args[0], gimple_ctypes.UnaryOp)
            and node.args[0].op == '*'
            and not getattr(node, 'kwargs', None)
            and expected_params
            and not any('...' in p or p in ('MojoList *', 'MojoDict *')
                        for p in expected_params)):
        return arg_pairs
    if not (arg_pairs and arg_pairs[0][0] == 'MojoList *'):
        return arg_pairs
    # `_as_str`: `arg_pairs[0][1]` (the spread list's C-expr) and each
    # `expected_params` element re-box to int64_t when read out of a tuple /
    # `enumerate` pair on the self-hosted path — the emitted
    # `mojo_list_get_int (<list>, i)` list handle and the `(<ptype>)<raw>`
    # cast type then came out as decimal heap addresses, different every run.
    _lst_v = _as_str(arg_pairs[0][1])
    _dflts = gen._func_param_defaults.get(fname) or \
        gen._func_param_defaults.get(fname_raw) or []
    _first_dflt = len(expected_params) - len(_dflts)
    _expanded: list = []
    for _pos in range(len(expected_params)):
        _ptype = _as_str(expected_params[_pos])
        _idx64 = gen._new_val('int64_t', f"(int64_t){_pos}")
        _len64 = gen._call_expr('int64_t', 'mojo_list_len',
                                 [('MojoList *', _lst_v)])
        _inrange = gen._new_val('_Bool', f"{_idx64} < {_len64}")
        _bb_in, _bb_out, _bb_merge = gen._new_bb(), gen._new_bb(), gen._new_bb()
        # Result slot declared once, assigned in both branches (GIMPLE:
        # no phi nodes / no ternaries across divergent types).
        _slot = gen._new_temp(_ptype if _ptype != 'void *' else 'int64_t')
        gen._emit(f"  if ({_inrange}) goto {_bb_in}; else goto {_bb_out};")
        gen._emit_label(_bb_in)
        if _ptype == 'char *':
            gen._emit(f"  {_slot} = mojo_list_get_str ({_lst_v}, {_idx64});")
        elif _ptype == 'double':
            gen._emit(f"  {_slot} = mojo_list_get_double ({_lst_v}, {_idx64});")
        else:
            _raw = gen._new_val('int64_t',
                                 f"mojo_list_get_int ({_lst_v}, {_idx64})")
            gen._emit(f"  {_slot} = "
                       + (f"({_ptype}){_raw};" if _ptype != 'int64_t'
                          else f"{_raw};"))
        gen._emit(f"  goto {_bb_merge};")
        gen._emit_label(_bb_out)
        _dv = None
        if _dflts and 0 <= _pos - _first_dflt < len(_dflts):
            _dv = _dflts[_pos - _first_dflt][1]
        _dt, _dval = gen._default_expr_to_pair(_dv)
        if _ptype == 'char *':
            if _dt != 'char *':
                # No string default: NULL (real Python would have raised
                # TypeError for a genuinely-required arg left unfilled).
                _dval = '(char *)0'
            gen._emit(f"  {_slot} = {_dval};")
        elif _ptype == 'double':
            gen._emit(f"  {_slot} = (double){_dval};")
        else:
            gen._emit(f"  {_slot} = "
                       + (f"({_ptype}){_dval};" if _ptype != 'int64_t'
                          else f"(int64_t){_dval};"))
        gen._emit(f"  goto {_bb_merge};")
        gen._emit_label(_bb_merge)
        _expanded.append((_ptype, _slot))
    return _expanded




def _pack_vararg_trailing_params(gen, fname, fname_raw, arg_pairs, kwarg_dict,
                                  call_has_spread=False):
    """Shared by `_lower_named_call` (value-consuming call sites) and
    `_gen_stmt_ExprStmt` (bare, value-discarding statement call sites —
    see that function's own duplicated general-call-building path for
    why it needs this too, not just _lower_named_call).

    `def f(fixed, *args, trailing_kwonly=default, ...)` — a vararg
    followed by more (keyword-only, per Python syntax) params, but NO
    `**kwargs`. `_emit_call`'s own packing check only fires when the
    `'...'` sentinel is the LAST entry of param_types; here it isn't
    (the trailing params come after it), so that check silently never
    fires — the call's extra positional args get coerced 1:1 against
    the trailing params' concrete C types instead of packed, and the
    trailing params themselves never receive a value at all. Real
    instance: importlib/_bootstrap.py's `_verbose_message(message,
    *args, verbosity=1)` called as `_verbose_message(fmt, a, b)`
    (verbosity left at its default) — `"too many arguments"` / a
    pointer-from-integer cast error at the call site. Python syntax
    guarantees anything textually after `*args` in a `def` is
    keyword-only, so it can NEVER be filled positionally by a call
    site — every entry of `arg_pairs` at/after the vararg's own
    position is unambiguously a vararg-pack candidate; the trailing
    param(s) must come from an explicit keyword argument (already in
    `kwarg_dict`, keyed by the call site's own real argument names) or
    their own default (`_func_param_defaults`, keyed by declared name
    — the trailing keyword-only slots are always exactly its LAST
    `len(_trailing_ptypes)` entries, since a param before `*args` is
    never keyword-only and so never appears in that tail).

    `func_param_types[name]`'s sentinel gets overwritten with the
    concrete real signature once the function's forward declaration
    is finalized (see _emit_call's own "starts life ending in the
    packing sentinel... gets overwritten... Every OTHER call site
    compiled afterwards then sees the concrete signature and
    silently skips packing" comment a few hundred lines up) — a call
    site compiled AFTER that point (the overwhelmingly common case
    for any function called more than once, or called from code
    textually after its own definition) sees a signature with no
    `'...'` at all, not even in the middle. `_mangled_signature_
    ctypes` preserves the original sentinel form untouched, so it's
    consulted FIRST here — `_emit_call`'s own existing fallback to it
    only checks `mangled_sig[-1] == '...'`, which is exactly as blind
    to a NON-final sentinel as the primary check it's guarding, so
    this reimplements that preference for the non-final case too
    rather than assuming `_emit_call`'s narrower version covers it.

    Returns the (possibly repacked) `(arg_pairs, kwarg_dict)`.
    """
    if call_has_spread:
        return arg_pairs, kwarg_dict
    _vararg_ptypes = (gen._vararg_trailing_param_types.get(fname)
                      or gen._vararg_trailing_param_types.get(fname_raw)
                      or gen._mangled_signature_ctypes.get(fname)
                      or gen._mangled_signature_ctypes.get(fname_raw)
                      or gen.func_param_types.get(fname)
                      or gen.func_param_types.get(fname_raw))
    if not (_vararg_ptypes and '...' in _vararg_ptypes and _vararg_ptypes[-1] != '...'):
        return arg_pairs, kwarg_dict
    _sentinel_idx = _vararg_ptypes.index('...')
    _n_fixed2 = _sentinel_idx
    _trailing_ptypes = _vararg_ptypes[_sentinel_idx + 1:]
    _trailing_dflts = (gen._func_param_defaults.get(fname)
                       or gen._func_param_defaults.get(fname_raw) or [])
    _trailing_names_defaults = (_trailing_dflts[-len(_trailing_ptypes):]
                                if _trailing_ptypes else [])
    _fixed2 = arg_pairs[:_n_fixed2]
    _vararg2 = arg_pairs[_n_fixed2:]
    _lst2 = gen._new_val('MojoList *', "mojo_list_new ()")
    for _at2, _av2 in _vararg2:
        _av2 = gen._coerce_to_type(_at2, 'int64_t', _av2)
        gen._emit(f"  mojo_list_append_int ({_lst2}, {_av2});")
    _trailing_pairs = []
    for _i2, _tpt in enumerate(_trailing_ptypes):
        _tname = (_trailing_names_defaults[_i2][0]
                 if _i2 < len(_trailing_names_defaults) else None)
        if _tname is not None and _tname in kwarg_dict:
            _trailing_pairs.append(kwarg_dict.pop(_tname))
        elif (_i2 < len(_trailing_names_defaults)
              and _trailing_names_defaults[_i2][1] is not None):
            _trailing_pairs.append(
                gen._default_expr_to_pair(_trailing_names_defaults[_i2][1]))
        else:
            _trailing_pairs.append((_tpt, '0'))
    arg_pairs = _fixed2 + [('MojoList *', _lst2)] + _trailing_pairs
    return arg_pairs, kwarg_dict


def _ensure_libc_self_extern(gen, fname_raw: str) -> None:
    """Record a self-emitted prototype for a plain (unrenamed) libc call
    whose declaring header is NOT in this compile's prelude — the shared
    half of `_lower_named_call`'s and `_gen_stmt_ExprStmt's general-call
    path's identical needs (a bare `mkdir(name, mode)` reaches BOTH,
    depending on whether its result is consumed). No-op for every name
    outside `_NEEDS_SELF_EXTERN` and when something already recorded the
    symbol; see the call-site comment there for the full rationale."""
    if fname_raw not in gen._external_protos \
            and fname_raw in gen._NEEDS_SELF_EXTERN:
        _self_extern_sig = gen._LIBC_SIGS.get(fname_raw) \
            or gen._KNOWN_SIGS.get(fname_raw)
        if _self_extern_sig:
            gen._external_protos[fname_raw] = (
                _self_extern_sig[0], list(_self_extern_sig[1]))


def _lower_named_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Final dispatch for user-defined and C stdlib functions."""
    # `_locally_binds_name` gate: BUILTIN_VALUE_MAP's entries (open,
    # filter, enumerate, str, len, sorted, ...) are all ordinary
    # identifiers a module can legally shadow with its own top-level
    # def/import (e.g. Lib/fnmatch.py's `def filter(names, pat):`,
    # Lib/tokenize.py's `def open(filename):`). Every per-branch early
    # return above this point in `_lower_call` already special-cases the
    # handful of names it recognizes structurally (some gated on this
    # same check, some not — see each one's own comment), but ANY
    # BUILTIN_VALUE_MAP name that falls all the way through to this
    # final, generic dispatch (either because it has no dedicated early
    # branch at all — `filter`/`map`/`print`/`range`/`max`/`min`/... — or
    # because its own early branch's gate correctly declined to intercept
    # a locally-bound name and let it fall through) must NOT be re-routed
    # to the builtin runtime symbol here: `self.BUILTIN_VALUE_MAP.get(
    # fname_raw, self._func_csym(fname_raw))`'s `.get()` unconditionally
    # preferred the map entry whenever `fname_raw` was a key, completely
    # ignoring whether THIS module shadows it — e.g. `open`'s own
    # dedicated early-return gate (a few hundred lines up) correctly
    # skips `_lower_builtin_open` when shadowed, but the call then fell
    # through everything else unmatched and landed HERE, where `'open' in
    # BUILTIN_VALUE_MAP` won regardless, still emitting a call to
    # `mojo_open_file` instead of the user's own `_func_csym('open')`
    # symbol (confirmed via a real shadowing repro: `fn open(x: Int) ->
    # Int: ...` compiled to `mojo_open_0c85c9` but every call site still
    # read `mojo_open_file(...)`). `_func_csym` already produces the
    # exact right symbol for a shadowing definition (same `_safe_name` +
    # overload-suffix scheme the definition itself used), so route
    # straight to it, bypassing BUILTIN_VALUE_MAP entirely, whenever this
    # module locally binds the name.
    if fname_raw in gen.BUILTIN_VALUE_MAP and gen._locally_binds_name(fname_raw):
        fname = gen._func_csym(fname_raw)
    # C reserved function renaming
    elif (fname_raw in gimple_ctypes._C_RESERVED_FUNCS and fname_raw not in gen.func_return_types
            and fname_raw not in gimple_ctypes._FORCE_RENAME_RESERVED
            and (fname_raw not in gen.imported_symbols
                 or fname_raw in gen._unresolved_import_aliases)):
        # A real implementation recorded in BUILTIN_VALUE_MAP beats the
        # weak stub this branch otherwise binds to. `math` is the case that
        # needs it: `math` is not a resolvable module here
        # (module_loader's `can_resolve_module_path('math')` is False), so
        # every `from math import sqrt` lands in _unresolved_import_aliases
        # and the call bound to the stub's `mojo_sqrt` — a symbol nothing
        # defines, which linked only against the auto-stub in the small case
        # (answering 0, so `sqrt(x)+exp(x)+log(x)` printed 0) and failed to
        # link outright in the whole-closure build. BUILTIN_VALUE_MAP
        # exists precisely to record the names that DO have a backing
        # implementation, and the libm entries added there are that answer
        # for math, so consult it first. Every other name still routes to
        # the stub, which is the entire point of the branch.
        if fname_raw in gen.BUILTIN_VALUE_MAP:
            fname = gen.BUILTIN_VALUE_MAP[fname_raw]
        elif fname_raw in gen._unresolved_import_aliases:
            # A relative/external import this compile could never resolve
            # (`from .os_helper import unlink` at module scope — the name
            # lands in _unresolved_import_aliases, NOT imported_symbols).
            # The preamble's weak-stub pass names that stub via
            # `_func_csym(sym_name)` (= `_safe_name`, i.e. `mojo_unlink`);
            # the call site must bind to the SAME symbol. Emitting the raw
            # reserved name here instead silently retargeted the call at
            # libc's same-named function with no visible prototype —
            # "implicit declaration of function 'unlink'" (a hard error)
            # for Lib/test/support/import_helper.py's forget().
            fname = gen._func_csym(fname_raw)
        else:
            fname = gen.BUILTIN_VALUE_MAP.get(fname_raw, fname_raw)
    else:
        # _func_csym applies the same overload suffix the definition used.
        fname = gen.BUILTIN_VALUE_MAP.get(fname_raw, gen._func_csym(fname_raw))
    if fname == 'main' and fname_raw in gen._unresolved_import_aliases:
        # See bugs/hard/CODEGEN_aliased_external_import_no_backing_
        # symbol.md: `from X import Y as main; main()` — 'main' is kept
        # a fixed, unmangled C name for THIS module's own synthesized
        # entry point (see the NO_OVERLOAD_MANGLE note above), so an
        # imported name that merely happens to be ALIASED to 'main'
        # must never be emitted (stub or call) under that same literal
        # C symbol — "conflicting types for 'main'; have
        # 'int(int, const char **)'" otherwise. Mirrors _C_RESERVED_
        # FUNCS's own definition/call-site rename chokepoint pattern.
        fname = '_unresolved_import_main'
    # Plain (unrenamed) libc call whose declaring header is NOT in this
    # compile's prelude (<unistd.h>/<sys/stat.h>/<sys/wait.h>/<stdlib.h>'s
    # unsetenv): nothing else records a prototype for it — the
    # `_external_protos` recording at the external_call FFI path only
    # covers `external_call["..."]( ... )` shapes, and most stdlib code
    # reaches these through QUALIFIED `os.unlink(...)`-style member calls
    # whose own path handles declaration — so os.py's own BARE wrappers
    # (`mkdir(name, mode)`, `rmdir(name)`, `execv(file, args)`,
    # `execve(...)`, `fork()`, `unsetenv(key)`) emitted raw calls with no
    # visible declaration: "implicit declaration of function 'mkdir'"
    # plus pointer-coercion mismatches against GCC's builtin knowledge,
    # 9 errors in Lib/os.py in any whole-program build whose closure
    # includes it. Register the pinned signature into `_external_protos`
    # so gen_module's existing preamble pass emits `extern int mkdir
    # (char *, int);` exactly once per translation unit (its
    # _LIBC_DECLARED/_NEEDS_SELF_EXTERN gate is precisely what routes
    # these self-emitted prototypes through), and every later call site
    # sees a real prototype.
    _ensure_libc_self_extern(gen, fname_raw)
    ret_type = gen.func_return_types.get(fname_raw, 'int64_t')

    # Self-host hardcoded functions declared via concrete prototypes in
    # gen_module's `_is_selfhost_file` block.  Their return types are not
    # in `func_return_types` (they live in sibling modules), so fall back
    # to the known-correct type from _SELFHOST_FUNC_RETURN_TYPES to avoid
    # the `int64_t` default truncating pointer return values.
    if fname in gimple_codegen._SELFHOST_HARDCODED_FUNCS:
        ret_type = gimple_codegen._SELFHOST_FUNC_RETURN_TYPES.get(fname, 'int64_t')

    # Auto-stub completely unknown names (e.g. bracket params like `cmp_fn: fn(T,T)->Bool`
    # that the parser skips). Without a declaration GCC gives "implicit function declaration".
    # Skip the self-host hardcoded forward-declared symbols — gen_module's
    # `_is_selfhost_file` block declares those concretely, and a variadic
    # stub here would conflict ("conflicting types").
    _is_unknown = (fname_raw not in gen.func_return_types
                   and fname_raw not in gen.imported_symbols
                   and fname not in gen._KNOWN_SIGS
                   and fname_raw not in gen.BUILTIN_VALUE_MAP
                   and fname_raw not in gimple_ctypes._C_RESERVED_FUNCS
                   and fname not in gimple_codegen._SELFHOST_HARDCODED_FUNCS
                   and fname_raw not in gimple_codegen._SELFHOST_HARDCODED_FUNCS)
    if _is_unknown:
        _stub_key = gimple_ctypes._stub_guard_name(fname)
        if fname_raw in gen._unresolved_import_aliases:
            # See bugs/hard/CODEGEN_aliased_external_import_no_backing_
            # symbol.md: a name imported from a module load_module()
            # couldn't resolve (relative import, or a real external/
            # unmodeled package) will NEVER get a real definition
            # anywhere in this compile — unlike the ordinary "unknown
            # name" case just below (ret_type=int64_t bare forward
            # decl), which is fine because it's typically a same-TU
            # forward reference that a real definition follows later.
            # A bare decl here just moves the failure to link time
            # ("undefined symbols for architecture arm64"), exactly
            # the same shape _lower_struct_method_call's own auto-stub
            # path already hit and fixed (weak definition instead of
            # decl-only) for the analogous "inherited from an
            # unmodeled base class" case.
            _stub_decl = (f'#ifndef {_stub_key}\n#define {_stub_key}\n'
                          f'__attribute__((weak)) int64_t {fname} (...) '
                          f'{{ mojo_print ((char *)"{fname_raw}: unavailable in compiled mode '
                          f'(imported from an unresolved external/relative module)"); '
                          f'return (int64_t)0; }}\n#endif')
        else:
            # See the _unresolved_import_aliases branch just above for
            # the general reasoning (bugs/hard/CODEGEN_aliased_
            # external_import_no_backing_symbol.md). This is the SAME
            # "declared but never defined" shape for the remaining
            # _is_unknown cases (Python builtins this codegen has no
            # lowering for — `vars`/`bytes`/`hash`/`next`/`object`/
            # `divmod`/`callable`/... — and the "bracket params,
            # implicit fnptrs" placeholders the comment above
            # mentions). By construction, anything reaching this branch
            # is NOT in func_return_types — and every top-level
            # function's return type is pre-registered in an earlier
            # pass (well before any function body is lowered, see
            # gen_module's Pass 1/1.3 registration), so a genuine
            # same-TU forward reference to a function defined later in
            # this file can never actually reach `_is_unknown=True` —
            # only a name that will NEVER be defined anywhere in this
            # compile does. A bare decl here was therefore never
            # actually saving anything: it only postponed today's
            # inevitable "implicit declaration" compile failure into an
            # equally inevitable "undefined symbols" LINK failure for
            # any such name that's actually called at runtime (dead/
            # never-called placeholders are unaffected either way).
            # Confirmed empirically via the full quality gate (compile_
            # stdlib.py 664/664 unchanged, 0 new skips) before landing.
            _stub_decl = (f'#ifndef {_stub_key}\n#define {_stub_key}\n'
                          f'__attribute__((weak)) int64_t {fname} (...) '
                          f'{{ mojo_print ((char *)"{fname_raw}: unavailable in compiled mode"); '
                          f'return (int64_t)0; }}\n#endif')
        if _stub_decl not in gen._elaborated_externs:
            gen._elaborated_externs.append(_stub_decl)
    if fname in gen._KNOWN_SIGS:
        ret_type = gen._KNOWN_SIGS[fname][0]
    elif fname in gen._LIBC_SIGS and fname_raw not in gen.func_return_types:
        # A bare (unrenamed) libc call reaching this generic dispatch --
        # e.g. os.py's `unlink(name)`/`mkdir(name, mode)` -- otherwise
        # keeps the `int64_t` default set above, but the real libc
        # signature (`_LIBC_SIGS`, already consulted for the self-
        # emitted extern/prototype and for `_emit_call`'s argument
        # coercion) may declare a narrower C return type (e.g. `int`).
        # Assigning that call's actual `int` result into an `int64_t`-
        # declared GIMPLE temp is an invalid conversion GCC's `-fgimple`
        # frontend rejects outright ("invalid conversion in gimple
        # call") -- found via `unlink`'s real 4-byte `int` return
        # colliding with this default (save_env.py's
        # restore_urllib_requests__url_tempfiles). Only applies when no
        # local Mojo definition of the same bare name shadows it.
        ret_type = gen._LIBC_SIGS[fname][0]

    # A renamed C-reserved *builtin* passthrough (e.g. calling libm exp2 with
    # no local def) needs a variadic extern. But if there's a local Mojo def of
    # the same name (now overload-mangled), it already has a typed forward decl
    # — emitting the variadic stub too would conflict. Skip those.
    if (fname != fname_raw and fname_raw in gimple_ctypes._C_RESERVED_FUNCS
            and fname_raw not in gen._mangled_funcs):
        if fname not in gen._renamed_builtin_calls:
            gen._renamed_builtin_calls[fname] = ret_type

    # `object()` — the bare base-object constructor: this model has no
    # Python-object representation, so lower to a quiet null placeholder.
    # Before this, `object()` fell through to the unknown-name weak stub,
    # which PRINTS "object: unavailable in compiled mode" on every call —
    # and module-init code calls it eagerly (`c_common/__init__.py`'s
    # `NOT_SET = object()`), polluting stdout once per process for any
    # program whose transitive closure contains that idiom. Mirrors the
    # coroutine-body emitter's own existing `object()` case (which returns
    # an opaque allocation, same "no representation, stay quiet" intent).
    if (fname_raw == 'object' and not node.args
            and not gen._locally_binds_name('object')
            and 'object' not in gen.func_return_types):
        return 'int64_t', gen._new_val('int64_t', '0')

    arg_pairs = [gen.lower_expr(a) for a in node.args]
    kwargs    = getattr(node, 'kwargs', []) or []
    # `_as_str(kname)`: the dict-comprehension's tuple-unpack reads
    # `kwargs[i][0]` (the kwarg NAME, a str) via `mojo_list_get_int`, so
    # `kname` erases to int64_t and the old bare `{kname: ...}` key used
    # `mojo_dict_set_int(d, mojo_str_from_int(kname), v)` — the char*
    # POINTER stringified as its DECIMAL ADDRESS, not the name. Every
    # `'do_imports' in kwarg_dict` / `kwarg_dict['filename']` then missed
    # and the real kwarg was replaced by the callee's default. Real
    # stage1-vs-stage2 divergence: mojo.mojo's
    # `gimple_codegen.compile_to_gimple(src, do_imports=True,
    # filename=input_file)` compiled natively to `(src, 0, "")` instead of
    # `(src, 1, input_file)`. The `-> str` re-view restores the real key.
    kwarg_dict = {_ggc_as_str(kname): gen.lower_expr(kexpr) for kname, kexpr in kwargs}

    # Disambiguate a call to a `(*args, **kwargs)`-declared callee by
    # the CALL SITE's own shape, not the callee's signature alone (see
    # bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.
    # md). _signature_ctypes types such a callee's `*args` as a plain
    # concrete `MojoList *` (no packing) — correct for the spread-
    # forwarding idiom (`f(*a, **k)`: the parser wraps each spread in
    # UnaryOp(op='*'/'**', operand=...), and _lower_UnaryOp passes an
    # already-packed MojoList*/MojoDict* through UNCHANGED, so
    # `arg_pairs` already has the right shape and must be left alone)
    # — but WRONG for an ordinary literal-argument call to the same
    # shape (`CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_size_t)`, no
    # spreads at all): the extra positional args would otherwise be
    # coerced 1:1 against `*args`'s/`**kwargs`'s concrete param types
    # instead of being packed, producing an arity mismatch or a silent
    # type-confusion bug. Detect a real spread from the ORIGINAL AST
    # args — a UnaryOp(op='*'/'**', ...) survives lowering as a
    # same-shaped pass-through, so it can't be told apart from a real
    # packed value after the fact. `_func_kwargs_slot` is only
    # populated for genuine user free functions (gen_module's own
    # FunctionDef registration pass), so this never fires for struct
    # methods (a separate call-lowering path, out of scope here) or
    # unresolved/imported names with no recorded signature.
    _call_has_spread = any(isinstance(_a, gimple_ctypes.UnaryOp) and _a.op in ('*', '**')
                           for _a in node.args)
    _kwslot_for_pack = gen._func_kwargs_slot.get(fname)
    if _kwslot_for_pack is None:
        _kwslot_for_pack = gen._func_kwargs_slot.get(fname_raw, -1)
    if _kwslot_for_pack >= 0 and not _call_has_spread:
        # Whether the callee ALSO declares a real `*args` before its
        # `**kwargs` (the `f(self, *args, **kwargs)` forwarding pattern,
        # which gets a concrete `MojoList *` C param) — as opposed to
        # `**kwargs` being its only vararg-style parameter (`def
        # f(**kwargs)`, exactly one `MojoDict *` C param; see
        # `_func_kwargs_has_vararg`'s own docstring). Defaults to True
        # (the old, always-pack-a-list-too behavior) when unknown, since
        # every call site that reaches this branch at all necessarily
        # has a `_func_kwargs_slot` entry, and both dicts are populated
        # together at the exact same registration site — this fallback
        # only matters for some other, not-yet-audited path that might
        # populate `_func_kwargs_slot` without its sibling.
        _has_vararg = gen._func_kwargs_has_vararg.get(
            fname, gen._func_kwargs_has_vararg.get(fname_raw, True))
        _n_fixed = max(0, _kwslot_for_pack - 1) if _has_vararg else _kwslot_for_pack
        _fixed_pairs = arg_pairs[:_n_fixed]
        _vararg_pairs = arg_pairs[_n_fixed:]
        _packed_dict_pair = ('MojoDict *', gen._pack_kwargs_dict(kwarg_dict))
        if _has_vararg:
            _lst = gen._new_val('MojoList *', "mojo_list_new ()")
            for _at, _av in _vararg_pairs:
                _av = gen._coerce_to_type(_at, 'int64_t', _av)
                gen._emit(f"  mojo_list_append_int ({_lst}, {_av});")
            arg_pairs = _fixed_pairs + [('MojoList *', _lst), _packed_dict_pair]
        else:
            # No `*args` slot at all: any leftover positional args (a
            # real Python-level TypeError against a kwargs-only
            # signature, but this codegen has no type-checker to catch
            # it earlier) have nowhere valid to go — pass them through
            # unchanged ahead of the single `MojoDict *` param rather
            # than silently discarding them, mirroring `_fixed_pairs`'
            # existing "leave it to the generic arity/coercion handling
            # further down" convention for a genuinely malformed call.
            arg_pairs = _fixed_pairs + _vararg_pairs + [_packed_dict_pair]
        kwarg_dict = {}

    # `def f(fixed, *args, trailing_kwonly=default, ...)` — a vararg
    # followed by more (keyword-only) params but no `**kwargs`; see
    # `_pack_vararg_trailing_params`'s own docstring for the full
    # rationale (shared with `_gen_stmt_ExprStmt`'s statement-level
    # twin call path below).
    arg_pairs, kwarg_dict = gen._pack_vararg_trailing_params(
        fname, fname_raw, arg_pairs, kwarg_dict, _call_has_spread)

    # Keyword argument padding for known functions
    if fname_raw == 'compile_to_gimple':
        if 'do_imports' in kwarg_dict: arg_pairs.append(kwarg_dict['do_imports'])
        elif len(arg_pairs) < 2:       arg_pairs.append(('int', '0'))
        if 'filename' in kwarg_dict:   arg_pairs.append(kwarg_dict['filename'])
        elif len(arg_pairs) < 3:       arg_pairs.append(('char *', '0'))
    if fname_raw == 'interpret_and_execute':
        if 'filename' in kwarg_dict:   arg_pairs.append(kwarg_dict['filename'])
        elif len(arg_pairs) < 2:       arg_pairs.append(('int', '0'))
    if fname_raw == 'format_ast'  and len(arg_pairs) == 1: arg_pairs.append(('int', '0'))
    if fname_raw == 'emit_module' and len(arg_pairs) == 1: arg_pairs.append(('int', '0'))

    # General kwarg padding when expected param count is known. A call
    # compiled in isolation (e.g. monomorphize.py's instantiate(), which
    # builds a brand-new GimpleGen per generic instantiation with none of
    # the surrounding module's imports registered) never populates
    # func_param_types for an imported function — but a C-stdlib-style
    # function like `memcpy` still has its real arity in `_KNOWN_SIGS`.
    # Falling back to that (rather than leaving expected_params empty)
    # is what lets a keyword-only call like std.memory's
    # `memcpy(dest=.., src=.., count=..)` still get its arguments bound
    # here instead of silently emitting a bare, argument-less `memcpy()`
    # — confirmed cause of a cascading, confusing GCC error that broke
    # every cold-CAS-cache stdlib build (investigated 2026-07-15). Purely
    # additive/narrower than dropping kwargs outright: a name with no
    # entry in _KNOWN_SIGS either (e.g. a struct constructor like
    # ARM64JIT, called with stale/vestigial kwargs its real 0-arg
    # constructor ignores) is untouched, exactly as before.
    # BUG-2026-024: same tiered truth _overload_suffix/_func_csym's mirror
    # use — the raw bare-name slot oscillates whenever sibling homonyms
    # exist (refinedstorage: controller's start_crafting vs crafting_
    # monitor's start_crafting), and padding/truncating against whichever
    # sibling registered last produced both "too few" and "too many
    # arguments" GCC errors against the correctly-suffixed prototype.
    # Function-local import: gimple_gen_funcs already imports this module.
    import mojo.backend_gimple.emit_funcs as _ggf_eff
    expected_params = _ggf_eff._effective_param_types(gen, fname_raw)
    if not expected_params:
        expected_params = gen.func_param_types.get(fname_raw, [])
    if not expected_params and fname_raw in gen._KNOWN_SIGS:
        expected_params = gen._KNOWN_SIGS[fname_raw][1]
    elif not expected_params and fname in gen._KNOWN_SIGS:
        # `fname_raw` (the ORIGINAL Python name, e.g. 'eval') is never
        # itself a _KNOWN_SIGS key — only its BUILTIN_VALUE_MAP-renamed
        # C symbol ('mojo_eval') is. Python's 1-arg `eval(expr)` (the
        # overwhelmingly common form; globals/locals default to the
        # caller's own scope) called this renamed 3-arg C function with
        # only 1 argument, a hard "too few arguments" compile error —
        # found via Tools/build/generate_token.py's own `eval(string)`.
        # mojo_eval's own globals/locals params are unused anyway (a
        # documented eval() stub — real eval() can't run in a compiled
        # C bootstrap), so padding with NULL below is exactly right,
        # not just "doesn't crash."
        expected_params = gen._KNOWN_SIGS[fname][1]

    # `f(*iterable)` unpacking against a fixed-arity callee — shared with
    # _gen_stmt_ExprStmt's statement-level twin path (see that site).
    arg_pairs = gen._expand_sole_spread_into_fixed_slots(
        node, fname, fname_raw, arg_pairs, expected_params)

    if len(expected_params) > 0 and len(arg_pairs) < len(expected_params):
        kwarg_values = list(kwarg_dict.values()) if kwarg_dict else []
        # Free-function param defaults: `def greet(name: String = "world")`
        # called as `greet()` must pad with "world", not NULL/0.
        _dflts = gen._func_param_defaults.get(fname) or gen._func_param_defaults.get(fname_raw) or []
        _dflt_by_pos = {pn: _dv for pn, _dv in _dflts}
        # `param_defaults` only holds entries for params THAT HAVE one,
        # starting at the first defaulted position — i.e. the last
        # len(_dflts) slots (a leading required param like
        # `check_like(name, ok=True)` shifts the run off zero, and plain
        # `_dflts[_pos]` indexing then missed every time, padding the
        # omitted arg with 0 — BUG-2026-020).
        _first_dflt = len(expected_params) - len(_dflts)
        # `**kwargs` slot: pack the LITERAL keyword arguments into a real
        # MojoDict (see _func_kwargs_slot). `f(**d)` forwarding is a
        # different shape — the parser flattens the spread into a single
        # positional arg, so it never reaches this padding loop.
        _kw_slot = gen._func_kwargs_slot.get(fname)
        if _kw_slot is None:
            _kw_slot = gen._func_kwargs_slot.get(fname_raw, -1)
        # `f(a, b, **fwd)` forwarding shape: `fwd` already landed as the
        # LAST arg_pairs entry (a real MojoDict*, not literal kwargs --
        # `_lower_UnaryOp`'s spread pass-through), but when the callee has
        # one or more keyword-only params (with defaults) between the
        # last fixed positional and its own trailing `**kwargs` slot
        # (e.g. c_parser/info.py's `_fix_filename(filename, relroot, *,
        # formatted=True, **kwargs)`), `len(arg_pairs) < _kw_slot` here --
        # the loop below used to treat the forwarded dict as filling the
        # NEXT missing slot positionally (silently binding the real
        # kwargs dict to `formatted` instead of `kwargs`) and then
        # fabricate a brand new EMPTY dict for the real `**kwargs` slot,
        # losing every forwarded override and shifting the tail of the
        # signature by one (GCC: "makes pointer from integer without a
        # cast" on `formatted`/whatever else came after). Set the real
        # forwarded dict aside here so it lands at its own slot below
        # instead of a freshly-packed empty one.
        _fwd_kw_pair = None
        if (_call_has_spread and arg_pairs and arg_pairs[-1][0] == 'MojoDict *'
                and node.args and isinstance(node.args[-1], gimple_ctypes.UnaryOp)
                and node.args[-1].op == '**'
                and 0 <= len(arg_pairs) - 1 < _kw_slot):
            _fwd_kw_pair = arg_pairs.pop()
        while len(arg_pairs) < len(expected_params):
            if _kw_slot >= 0 and len(arg_pairs) == _kw_slot:
                arg_pairs.append(_fwd_kw_pair if _fwd_kw_pair is not None
                                  else ('MojoDict *', gen._pack_kwargs_dict(kwarg_dict)))
                kwarg_values = []
                continue
            if kwarg_values:
                arg_pairs.append(kwarg_values.pop(0))
                continue
            # Map the missing positional slot to its param name via the
            # C-type-list position (param names aren't in expected_params).
            _pos = len(arg_pairs)
            _dv = None
            if _dflts and 0 <= _pos - _first_dflt < len(_dflts):
                _dv = _dflts[_pos - _first_dflt][1]
            if _dv is not None:
                arg_pairs.append(gen._default_expr_to_pair(_dv))
            else:
                arg_pairs.append(('int', '0'))

    # Arity parity with myinterpreter.py (BUG-2026-024 follow-up,
    # test_primal_mod/test_refined_storage_mod): the interpreter binds
    # positional args loosely — SURPLUS positional args are evaluated and
    # silently discarded (`f(1, 2, 3)` against `def f(a: Int) -> Int`
    # returns 10; minimal repro confirmed). The compiled path forwarded
    # every lowered arg into the C call instead, tripping GCC's "too many
    # arguments to function" against the callee's real prototype. Drop the
    # round() — handled HERE, above the arity truncation below, because that
    # truncation clamps the argument list to the callee's known C signature
    # and `round`'s is libc's `double round(double)` — ONE parameter. So
    # `round(x, ndigits)` lost its second argument before the old
    # two-argument branch could ever run (it sat below the truncation, i.e.
    # dead code), and `round(2.567, 2)` silently computed `round(2.567)` and
    # printed `3`. Dispatch on the AST's arg count, not the (already
    # truncated) arg_pairs.
    # round(x) — the one-argument form, which Python answers with an INT
    # (round-half-to-even), not a float. It had no case at all and fell
    # through to the generic path, so `print(round(2.6))` printed `3.0`.
    # `rint` is the C half-to-even rounding (the default FP mode), matching
    # Python exactly: round(2.5) == 2 and round(-2.5) == -2, where C's
    # `round()` would give 3 and -3.
    if fname_raw == 'round' and len(node.args) == 1:
        (xt, xv), = arg_pairs
        xd = xv if xt == 'double' else gen._new_val('double', f'(double){xv}')
        _r = gen._new_val('double', f'rint ({xd})')
        return 'int64_t', gen._new_val('int64_t', f'(int64_t){_r}')

    # round(x, ndigits) → round(x*10^n)/10^n (libm round() takes 1 arg only)
    if fname_raw == 'round' and len(node.args) == 2:
        (xt, xv), (nt, nv) = arg_pairs
        xd = xv if xt == 'double' else gen._new_val('double', f'(double){xv}')
        nd = nv if nt == 'double' else gen._new_val('double', f'(double){nv}')
        p  = gen._new_val('double', f'pow (10.0, {nd})')
        scaled = gen._new_val('double', f'{xd} * {p}')
        r = gen._new_val('double', f'round ({scaled})')
        return 'double', gen._new_val('double', f'{r} / {p}')

    # surplus pairs here — each dropped arg's lower_expr already ran while
    # building arg_pairs, so its side effects still happen exactly once,
    # matching the interpreter's evaluate-then-ignore order. Never applied
    # to variadic callees: a '...' signature takes the extras by
    # convention, and a MojoList* parameter slot means this call was (or
    # will be) pack-lowered, where extras belong INSIDE the pack.
    # `len(...) > 0`, not a bare `if expected_params`: an empty list is
    # TRUTHY in the self-hosted compiler (container-truthiness gap), so
    # `if expected_params and len(arg_pairs) > 0` fired for a callee with
    # NO known signature and truncated `arg_pairs` to `[:0]` — every
    # such call (`py_tokenize(src)` in mojo_main.py, ...) emitted arity-0
    # and GCC rejected it against the runtime header's real prototype.
    if (len(expected_params) > 0 and len(arg_pairs) > len(expected_params)
            and not any('...' in p or p == 'MojoList *'
                        for p in expected_params)):
        arg_pairs = arg_pairs[:len(expected_params)]

    # exit(msg)/quit(msg): Python's builtin exit()/quit() (and
    # sys.exit(), which redirects here the same way) accept an
    # arbitrary object, not just an int — a string prints as an error
    # message (exit code 1), matching real Python's SystemExit(msg)
    # behavior on an uncaught exit. `exit`/`quit` are otherwise treated
    # as a direct passthrough to libc's real `exit(int status)` (see
    # _C_RESERVED_FUNCS), so `exit("some message")` — real code, e.g.
    # Tools/build/generate_token.py's own `exit('\n'.join(...))` —
    # passed a `char *` straight to libc exit(), a hard "makes integer
    # from pointer without a cast" compile error, not just wrong
    # behavior. A bare int arg (the common case) is unaffected: this
    # only intercepts when the argument ISN'T already int-shaped.
    if fname_raw in ('exit', 'quit') and len(arg_pairs) == 1:
        _ex_t, _ex_v = arg_pairs[0]
        if _ex_t not in ('int', 'int64_t', '_Bool'):
            _msg = gen._stringify_value(_ex_t, _ex_v)
            gen._emit_call('void', '', 'mojo_print_stderr', [('char *', _msg)])
            gen._emit("  exit (1);")
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')

    # int(s, base) — drop the base arg
    if fname_raw == 'int' and len(arg_pairs) > 1:
        arg_pairs = arg_pairs[:1]

    # abs of an integer → inline `x < 0 ? -x : x`.
    # We deliberately do NOT call the libc `llabs`: gcc -fgimple ICEs
    # (gimplify_var_or_parm_decl) when the recognized builtin llabs is applied
    # to a local computed temp. Inlining is also strictly better — no libc call
    # for a one-instruction operation.
    # TODO(gimple-builtins): revisit once the gcc -fgimple builtin-arg ICE is
    # fixed upstream; we could then route abs back through llabs if desired.
    if fname_raw in ('abs', 'mojo_abs') and len(arg_pairs) == 1:
        at, av = arg_pairs[0]
        # EVERY integer ctype, not just int64_t/long long. A narrower one
        # ('int' from a bool-typed comparison, 'int32_t' from an explicit
        # annotation) used to fall through to the real libc `abs`, whose
        # gimplified builtin gimple then refused to convert into the
        # int64_t local it was assigned to — "invalid conversion in gimple
        # call" at the enclosing statement, pointing at the wrong line
        # entirely. The inline has no such overload problem: it is an
        # ordinary conditional expression, widened once at the end.
        if at in _SCALAR_FLOAT_TYPES:
            # abs() of a FLOAT, not just an integer. This used to fall
            # through to the libc `abs`, which truncates to int: `abs(-3.5)`
            # returned `3` where CPython returns `3.5`. Wrong with no error
            # at all -- the one failure mode a test suite catches last --
            # and every float `abs()` in the tree hit it. Same inline shape
            # as the integer case, in the argument's own floating type so a
            # `float`/`__fp16` keeps its precision instead of being widened
            # and narrowed again.
            v = gen._ensure_local(at, av)
            zero = gen._new_val(at, '(%s)0' % at)
            neg = gen._new_val('_Bool', f'{v} < {zero}')
            negv = gen._new_val(at, f'-{v}')
            return at, gen._new_val(at, f'{neg} ? {negv} : {v}')
        if at in _SCALAR_INT_TYPES or at == 'long long' or at.endswith(' *'):
            v = gen._ensure_local('int64_t', av if not at.endswith(' *')
                                   else gen._new_val('int64_t', f'(int64_t){av}'))
            zero = gen._new_val('int64_t', '(int64_t)0')
            neg  = gen._new_val('_Bool', f'{v} < {zero}')
            negv = gen._new_val('int64_t', f'-{v}')
            return 'int64_t', gen._new_val('int64_t', f'{neg} ? {negv} : {v}')

    # range(stop) or range(start, stop, step)
    if fname_raw == 'range':
        if len(arg_pairs) == 1:
            _zero = gen._new_val('int64_t', '(int64_t) 0')
            arg_pairs = [('int64_t', _zero), arg_pairs[0]]
        elif len(arg_pairs) == 3:
            fname = 'mojo_range3'
        # `MojoList *`, not `void *`: mojo_range/mojo_range3 build a real
        # MojoList of int slots, and declaring the result `void *` left every
        # consumer with no type to work from — `z = range(3)` printed
        # `[None, 1, 2]`, because with no recorded element type the repr
        # walker hit its int-vs-pointer heuristic on the boxed 0 and printed
        # the None sentinel.
        _rng = gen._call_expr('MojoList *', fname, arg_pairs)
        gen._elem_types[_rng] = 'int64_t'
        return 'MojoList *', _rng

    # Single-arg min()/max() is ALWAYS the "reduce over an iterable" form in
    # Python — the scalar form needs >= 2 positional args. Route it to the
    # runtime mojo_min/mojo_max (which walk a MojoList*), before the scalar
    # ternary-fold below, which would otherwise see the lone `int64_t`-boxed
    # list handle as a "numeric arg" and hand it straight back unchanged
    # (returning the list POINTER as the min/max value — garbage). Real in an
    # A3 stack-switch generator body: `yield min(xs)` on an unannotated param.
    if (fname_raw in ('min', 'max') and len(arg_pairs) == 1
            and not gen._locally_binds_name(fname_raw)
            and 'key' not in {k for k, _ in getattr(node, 'kwargs', []) or []}):
        at, av = arg_pairs[0]
        # `MojoGenerator *` is in this list for the same reason the other
        # containers are: `max(x for x in xs)` / `max(some_generator())` is
        # real Python, and _materialize_as_list drains it. Without the case
        # it fell through to the scalar ternary-fold below, which returned
        # the coroutine handle itself as the "maximum" (a hard crash on the
        # next use).
        if at == 'MojoList *' or at == 'MojoDict *' or at == 'MojoSet *' \
                or at == 'MojoGenerator *' \
                or at in ('int', 'int64_t', 'void *'):
            # `min(a_dict)`/`max(a_set)` is real Python (min/max KEY, or
            # element) — DESIGN.html R1/R5, shares _materialize_as_list.
            lp = gen._materialize_as_list(at, av)
            if gen._elem_of(av) == 'double':
                return 'double', gen._call_expr(
                    'double', f"mojo_{fname_raw}_double", [('void *', lp)])
            return 'int64_t', gen._call_expr(
                'int64_t', f"mojo_{fname_raw}", [('void *', lp)])

    # min/max over scalar args → fold into nested ternaries (avoids the
    # mojo_min(void*) variadic-pack signature, which we don't emit packs for).
    _NUM = ('int64_t', 'int', '_Bool', 'double', 'float',
            'uint64_t', 'int32_t', 'uint32_t', 'int16_t', 'uint16_t',
            'int8_t', 'uint8_t', 'size_t', 'long', 'short')
    if (fname_raw in ('min', 'max') and arg_pairs
            and all(t in _NUM for t, _ in arg_pairs)):
        op = '<' if fname_raw == 'min' else '>'
        def _as_i64(t, v):
            # `_as_str(v)`: `v` is a C-expr string, but reading it out of the
            # 2-tuple (`arg_pairs[k][1]`) re-boxes the slot to int64_t on the
            # self-hosted path, so `f'(int64_t){v}'` emitted `(int64_t)<addr>`
            # (a live heap pointer as a GIMPLE integer constant) — different
            # every run. Index, don't unpack, and re-tag the slot.
            _v = _as_str(v)
            return _v if t == 'int64_t' else gen._new_val('int64_t', f'(int64_t){_v}')
        acc = _as_i64(_as_str(arg_pairs[0][0]), arg_pairs[0][1])
        for _ap in arg_pairs[1:]:
            bv = _as_i64(_as_str(_ap[0]), _ap[1])
            cond = gen._new_val('_Bool', f'{_as_str(acc)} {op} {bv}')
            acc = gen._new_val('int64_t', f'{cond} ? {_as_str(acc)} : {bv}')
        return 'int64_t', acc

    # min/max over string-ish (char* and/or single-char) args → same
    # ternary-fold approach as the numeric case above, but lexicographic
    # comparison needs a real strcmp-style call (`<`/`>` directly on two
    # char* pointers compares ADDRESSES, not string content) —
    # mojo_cstr_cmp mirrors the string-equality lowering above (`==`/
    # `!=`) doing the identical strcmp-based comparison for the same
    # char* representation. A bare 'char' operand (e.g. a value read via
    # `_mojo_at_char`/string indexing, as opposed to a char*-boxed
    # single-character string) is normalized to a real 1-char string via
    # mojo_char_to_str first, mirroring the equality lowering's own
    # `_to_char_star` helper immediately above. Without this, a 2-arg
    # call mixing these representations, like Tools/build/deepfreeze.py's
    # `maxchar = max(maxchar, c)` (maxchar: char*, c: char, from
    # iterating a str), fell through to the generic call-expr path
    # below, calling the real runtime's `mojo_max(void *args)`
    # (single-iterable-of-ints signature) with 2 scalar args — a hard
    # "too many arguments to function 'mojo_max'" -fgimple compile
    # error, not a subtler runtime bug.
    _STRINGY = ('char *', 'char')
    if (fname_raw in ('min', 'max') and len(arg_pairs) >= 2
            and all(t in _STRINGY for t, _ in arg_pairs)
            and any(t == 'char *' for t, _ in arg_pairs)):
        def _as_cstr(t, v):
            _v = _as_str(v)  # slot re-boxed by tuple read; re-tag (see numeric fold above)
            if t == 'char *':
                return _v
            return gen._call_expr('char *', 'mojo_char_to_str', [('char', _v)])
        acc = _as_cstr(_as_str(arg_pairs[0][0]), arg_pairs[0][1])
        for _ap in arg_pairs[1:]:
            cv = _as_cstr(_as_str(_ap[0]), _ap[1])
            cmp_i = gen._call_expr('int', 'mojo_cstr_cmp', [('char *', _as_str(acc)), ('char *', cv)])
            cmp64 = gen._new_val('int64_t', f'(int64_t){cmp_i}')
            zero = gen._new_val('int64_t', '(int64_t)0')
            # cmp64 < 0 means acc sorts strictly before cv (acc is the
            # lexicographically smaller string); max wants the larger of
            # the two, so max replaces acc with cv exactly when
            # cmp64 < 0, min replaces when cmp64 > 0 — equal strings
            # keep acc either way, matching the numeric fold's identical
            # "keep acc on tie" behavior above.
            replace_op = '<' if fname_raw == 'max' else '>'
            cond = gen._new_val('_Bool', f'{cmp64} {replace_op} {zero}')
            acc = gen._new_val('char *', f'{cond} ? {cv} : {_as_str(acc)}')
        return 'char *', acc

    # int(x) — direct cast for already-numeric types. Only a STRING
    # argument (`int("42")`) should route through the mojo_make_int
    # runtime helper (parses digits, _KNOWN_SIGS declares it as
    # `int64_t mojo_make_int(char *)`); a numeric argument
    # (`int(self.fraction * float(totalWidth))`, `int(True)`, an
    # already-int64_t value) previously fell through to that same
    # generic BUILTIN_VALUE_MAP['int'] = 'mojo_make_int' call
    # unconditionally, and generic arg coercion then blindly cast the
    # numeric value to the callee's declared `char *` param type
    # (`_t8 = (char *)_t6;` reinterpreting a double's bit pattern as a
    # pointer) instead of converting it — a `-fgimple` "invalid types
    # in conversion to integer" hard error at the following
    # `mojo_make_int(_t8)` call (real repro: Tools/unittestgui/
    # unittestgui.py's `ProgressBar.paint`: `width = int(self.fraction
    # * float(totalWidth))`). C's double->int64_t cast truncates
    # toward zero, matching Python's `int(float)` semantics, so a
    # straight cast is correct here — mirrors the analogous `float(x)`
    # direct-cast special case immediately below.
    if fname_raw == 'int' and len(arg_pairs) == 1:
        at, av = arg_pairs[0]
        # A var statically declared int64_t but _actual_types-tracked as
        # 'char *' holds a BOXED STRING (e.g. a tuple-unpack slot typed by
        # the loop machinery's int64_t convention while the runtime value
        # came from `line.split(":")`). Python `int(x)` on it must PARSE
        # the digits — returning x unchanged leaked that same
        # _actual_types['char *'] entry into the enclosing expression,
        # where binary '+' then dispatched to string concatenation
        # (`mojo_str_from_int(old) + str_cat(...)`) instead of integer
        # addition; even type-correct consumers read the pointer bits as
        # the "int". Route through mojo_make_int, exactly like the
        # statically-char* `int("42")` case this special case already
        # handles. Real repro: Tools/scripts/summarize_stats.py's
        # load_raw_data: `stats[key.strip()] += int(value)`.
        if at in ('int', 'int64_t', '_Bool') and gen._actual_types.get(av) == 'char *':
            cp = gen._new_val('char *', f'(char *){av}')
            return 'int64_t', gen._call_expr('int64_t', 'mojo_make_int', [('char *', cp)])
        if at == 'double':
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')
        if at == 'int64_t':
            return 'int64_t', av
        if at in ('int', '_Bool'):
            return 'int64_t', gen._new_val('int64_t', f'(int64_t){av}')

    # float(x) — direct cast for numeric types
    if fname_raw == 'float' and arg_pairs:
        at, av = arg_pairs[0]
        # Same boxed-string trap as int() above: `(double)<char*>` casts
        # pointer BITS, silently producing garbage; parse instead.
        if at in ('int64_t', 'int', '_Bool') and gen._actual_types.get(av) == 'char *':
            cp = gen._new_val('char *', f'(char *){av}')
            return 'double', gen._call_expr('double', 'mojo_make_float', [('char *', cp)])
        if at in ('int64_t', 'int', '_Bool'): return 'double', gen._new_val('double', f'(double){av}')
        if at == 'double':                    return 'double', av

    # bool(x) — Python truthiness is container LENGTH, not pointer
    # identity (`bool([])`/`bool({})`/`bool(set())` are False even though
    # each empty container's pointer is a real, non-NULL allocation). The
    # generic `bool(...)` → `mojo_make_bool((int)ptr)` path compared
    # pointer-non-nullness, so the self-hosted binary compiled `bool(empty
    # container)` to True — a native-vs-Python divergence (same semantics
    # `_ensure_bool_cond` already implements for if/while conditions via
    # _CONTAINER_LEN_FN, but a bool() CALL was the one path that never
    # used it). Mirror that here so both paths agree.
    if fname_raw == 'bool' and len(arg_pairs) == 1:
        _bt, _bv = arg_pairs[0]
        if _bt in gen._CONTAINER_LEN_FN:
            # GIMPLE-valid statement form, identical to
            # _ensure_bool_cond's own container branch (a bare
            # `len != 0` expression typed int is rejected as a "bogus
            # comparison result type").
            _n = gen._call_expr('int64_t', gen._CONTAINER_LEN_FN[_bt],
                                 [(_bt, _bv)])
            _b = gen._new_temp('_Bool')
            _z = gen._new_temp('int64_t')
            gen._emit(f'  {_z} = (int64_t)0;')
            gen._emit(f'  {_b} = {_n} != {_z};')
            return '_Bool', _b

    if ret_type == 'void':
        return gen._void_call(fname, arg_pairs)
    t = gen._call_expr(ret_type, fname, arg_pairs)
    # A multi-value return's per-slot types, carried across the call (see
    # gen._return_slot_types's declaration). Same reason and same shape as
    # the `_return_elem_types` block just below: the callee's slot types are
    # keyed by ITS internal value, so they have to be re-keyed by this
    # result for `a, b = f()` to read slot 0 with slot 0's type.
    if fname_raw in gen._return_slot_types:
        gen._tuple_slot_types[t] = gen._return_slot_types[fname_raw]
    if fname_raw in gen._return_elem_types:
        # Annotated `-> tuple[...]` functions resolve to boxed int64_t (see
        # _mojo_type), so unlike the MojoList*-typed case above the elem
        # must be recorded for ANY ret_type — consumers resolve the boxed
        # handle back via _actual_types. Keyed on the callee having a
        # recorded return elem type, which only true container returns get.
        gen._elem_types[t] = gen._return_elem_types[fname_raw]
        if ret_type == 'MojoList *':
            gen._actual_types[t] = ret_type
        elif ret_type in ('int', 'int64_t'):
            gen._actual_types[t] = 'MojoList *'
    # A function that RETURNS a generator (`def mk(): return counter(3)`,
    # typed `MojoGenerator *` by Pass 1.3e/1.3f) — record the underlying
    # generator function's api on the call's result temp (Pass 1.3f-gen
    # pre-pass populates self._fn_returns_generator), so any later
    # consumer of the value (`g = mk(); for x in g:`, `for x in mk():`,
    # `consume(mk())`) recovers the right base/value_ctype exactly like a
    # direct generator call's own call-site recording (see _lower_call's
    # generator branch). See bugs/CODEGEN_compiled_generator_not_first_
    # class_value.md.
    if ret_type == 'MojoGenerator *':
        _gf = gen._fn_returns_generator.get(fname_raw)
        if _gf is not None and _gf in gen._generator_api:
            gen._generator_var_api[t] = gen._generator_api[_gf]
    # A callee that RETURNS a kinds-carrying value: the result is still
    # described, but the compile-time NAME the per-slot kinds were recorded
    # against died with the callee's frame. Mark it so a read with no
    # compile-time index (iteration, a computed subscript) is lowered as a
    # BOXED read — `f = make_tuple(); f[0]`, `for x in make_tuple():`.
    # Inferred by the same whole-program scan that fills `_return_elem_types`
    # (see _infer_return_maybe_kinds in module_gen.py), so it is keyed by
    # the same bare callee name. A callee NOT in the set keeps the plain
    # accessor, which is what every other list-returning function has always
    # emitted.
    if ret_type == 'MojoList *' and fname_raw in getattr(gen, '_return_maybe_kinds', ()):
        gen._maybe_kinds_vals.add(t)
    return ret_type, t




def _lower_varargs_pack(gen, pack_args: list) -> tuple:
    """Lower the call-site positional args matched to a `*args` pack
    parameter into a single MojoList* value. A lone arg that already
    lowers to a MojoList* (e.g. `*args` re-forwarded from the caller's
    own pack param, as in `def f(*args): g(*args)`) is passed straight
    through unchanged; otherwise each value is boxed individually,
    mirroring _emit_call's trailing-'...' packing convention."""
    lowered = [gen.lower_expr(a) for a in pack_args]
    if len(lowered) == 1 and lowered[0][0] == 'MojoList *':
        return lowered[0]
    lst = gen._new_val('MojoList *', "mojo_list_new ()")
    for atype, aval in lowered:
        aval = gen._coerce_to_type(atype, 'int64_t', aval)
        gen._emit(f"  mojo_list_append_int ({lst}, {aval});")
    return ('MojoList *', lst)






def _lower_struct_constructor(gen, struct_name: str,
                              args: list, kwargs: list = None) -> tuple[str, str]:
    """
    Lower TypeName(field1, field2, ...) to allocation + field init + __init__ call.

    Uses _alloc_StructName() helper (emitted in preamble) because
    sizeof(T) is invalid in __GIMPLE body when T is not in the signature.
    """
    ctype  = f"{struct_name} *"
    t      = gen._new_temp(ctype)
    gen._struct_allocs_needed.add(struct_name)
    # An owned local that never escapes may have reserved frame storage for
    # this very constructor (maybe_stack_alloc_owned_ctor): initialise that in
    # place instead of allocating. Consumed at ENTRY, before the arguments are
    # lowered, so a nested constructor of the same struct never takes it.
    _st = gen._literal_storage
    if _st != '' and gen._literal_storage_ctype == ctype:
        gen._literal_storage = ''
        gen._emit(f"  _init_{struct_name} (&{_st});")
        gen._emit(f"  {t} = &{_st};")
    else:
        gen._emit(f"  {t} = _alloc_{struct_name} ();")

    # builtin-`bytes` subclass (`class _Extra(bytes)`): populate the
    # synthesized `_data: MojoBytes *` payload from the constructor
    # argument the subclass's `__new__` forwards to
    # `super().__new__(cls, <arg>)` (payload arg index precomputed in
    # gen_module_impl; defaults to 0). The `__new__` body itself is not
    # emitted as a callable method — its sole job in the scoped shape is
    # this payload construction. `__init__` still runs afterwards for any
    # extra instance attributes (`self.id = id`). See
    # bugs/COMPILE_FAIL_zipfile___init__.md.
    if struct_name in getattr(gen, '_bytes_subclass_structs', ()):
        _bidx = gen._bytes_subclass_payload_argidx.get(struct_name, 0)
        if args and 0 <= _bidx < len(args):
            _bt, _bv = gen.lower_expr(args[_bidx])
            _mb = gmp._coerce_to_bytes(gen, _bt, _bv)
            gen._emit(f"  {t}->_data = {_mb};")
        else:
            # No payload argument (`X()`): an empty bytes value, so
            # inherited ops never deref a NULL `_data`.
            _mb = gen._new_val('MojoBytes *', 'mojo_bytes_empty ()')
            gen._emit(f"  {t}->_data = {_mb};")

    # Explicit length-based flags — a bare `if kwargs:` / `kwargs or args`
    # on a `list`-typed param is unreliable on the self-hosted path (the
    # compiled `or` of two pointer operands can fold to a falsy int64_t
    # even when the list is non-empty), which silently skipped the
    # field-assignment branch for every no-__init__ struct kwarg ctor.
    _n_kw = len(kwargs) if kwargs else 0
    _n_args = len(args) if args else 0

    # Same-file overload resolution: if this struct's __init__ overloads
    # (including any @fieldwise_init-synthesized one) were registered from
    # the CURRENT file's own AST, pick the one matching this call site's
    # arity/types instead of assuming there's only one. Structs known only
    # via dylib reflection (_struct_has_init set without a
    # _struct_method_signatures entry — see ~line 2672) fall through to
    # the single-signature path below unchanged; cross-module overload
    # resolution is a separate follow-on (elaborate.py extension).
    _init_candidates = gen._struct_method_signatures.get(_sms_key(struct_name, '__init__'))
    if _init_candidates:
        _chosen = gen._resolve_overload(_init_candidates, args, kwargs)
        if _chosen is not None:
            init_fname = gen._struct_method_csym(struct_name, '__init__', _chosen['overload_id'])
            arg_pairs = [(f"{struct_name} *", t)] + \
                gen._build_call_args_for_candidate(
                    _chosen, args, kwargs,
                    gen._struct_init_defaults.get(struct_name, {}))
            gen._emit_call('void', '', init_fname, arg_pairs)
            return ctype, t
        # No candidate could be resolved — either no candidate's arity fits
        # this call at all, or (same arity, but every candidate erases to
        # an identical C signature — e.g. two structurally different Mojo
        # generics both boxed as int64_t — so there's no type signal to
        # pick between them). Either way, guessing a specific overload_id
        # would be worse than what this struct has always done before
        # same-file resolution existed: fall straight through to the
        # single-signature path below (unsuffixed call if __init__ exists
        # at all, field-assignment otherwise) rather than returning here.

    # If struct has __init__, call it with the provided arguments.
    # A plain `elif` after this (large) block is unreliable on the
    # self-hosted path — track whether we took it with an explicit flag
    # and gate the field-assignment fallback on `not _did_init_call`
    # instead.
    _did_init_call = False
    if struct_name in gen._struct_has_init:
        _did_init_call = True
        init_fname = gen._struct_method_csym(struct_name, '__init__', '')
        arg_pairs = [(f"{struct_name} *", t)]  # self parameter
        for arg in args:
            arg_pairs.append(gen.lower_expr(arg))
        full_params = gen.func_param_types.get(init_fname, [])
        expected = len(full_params) - 1  # -1 for self
        # Bind keyword args to the __init__ parameters. For a struct whose
        # source we have, init_pnames gives the parameter names, so a kwarg
        # binds at the position of its named parameter. For a reflected
        # struct (no param names from the C signature), bind kwargs in source
        # order after the positional args.
        init_pnames = gen._struct_init_params.get(struct_name, [])
        init_defaults = gen._struct_init_defaults.get(struct_name, {})
        # A cross-module struct whose __init__ signature was registered only
        # via _register_closure_struct_inits (do_imports closure) has the
        # param NAMES but not func_param_types, so `expected` above is -1 —
        # fall back to the name count so the padding loop below fills every
        # __init__ parameter (an under-filled call is `too few arguments to
        # GimpleGen___init__`).
        if expected < 0 and init_pnames:
            expected = len(init_pnames)
        if kwargs and init_pnames:
            kw = dict(kwargs)
            for idx, pname in enumerate(init_pnames):
                if pname not in kw:
                    continue
                pos = idx + 1  # +1 for self slot
                while len(arg_pairs) <= pos:
                    _gap_i = len(arg_pairs) - 1
                    _gap_dflt = (init_defaults.get(init_pnames[_gap_i])
                                 if 0 <= _gap_i < len(init_pnames) else None)
                    arg_pairs.append(gen._default_expr_to_pair(_gap_dflt))
                arg_pairs[pos] = gen.lower_expr(kw[pname])
            # `**kwargs`: pack every keyword that isn't a named parameter
            # into a real MojoDict (see _pack_kwargs_dict). Without this
            # the padding below left `(MojoDict *)0` in that slot, so
            # `def __init__(self, t, **fields): self.fields = fields`
            # stored a null dict — the compiled-path half of
            # ast_rewriter's `for fname in pat.fields:` failure.
            _kw_i = -1
            for _i, _pn in enumerate(init_pnames):
                if _pn.startswith('**'):
                    _kw_i = _i
                    break
            if _kw_i >= 0:
                _named = set(init_pnames)
                _rest = {}
                for _kn in kw:
                    if _kn not in _named:
                        _rest[_kn] = gen.lower_expr(kw[_kn])
                _pos = _kw_i + 1  # +1 for self slot
                while len(arg_pairs) <= _pos:
                    _gap_i = len(arg_pairs) - 1
                    _gap_dflt = (init_defaults.get(init_pnames[_gap_i])
                                 if 0 <= _gap_i < len(init_pnames) else None)
                    arg_pairs.append(gen._default_expr_to_pair(_gap_dflt))
                arg_pairs[_pos] = ('MojoDict *', gen._pack_kwargs_dict(_rest))
        elif kwargs:
            for _kn, kexpr in kwargs:
                arg_pairs.append(gen.lower_expr(kexpr))
        # Pad any still-missing args with their declared default value (or 0
        # when no default is known). Padding with a bare `('int', '0')`
        # unconditionally silently flipped every `bool`/string default to
        # FALSE/0 in the compiled binary (e.g. `GimpleGen(do_imports=...)`
        # lost emit_str_pool/emit_struct_defs/emit_entry_points=True, so the
        # self-hosted gen_module skipped its whole struct-typedef preamble),
        # while real Python kept the true defaults — an A/B divergence
        # (python3 fire.py --dump vs MOJO_NO_SHIM=1 ./mojoc --dump) that
        # dropped every struct typedef / dispatch helper from the native
        # output.
        while len(arg_pairs) - 1 < expected:
            _missing_pname = init_pnames[len(arg_pairs) - 1] if init_pnames and len(arg_pairs) - 1 < len(init_pnames) else None
            _dflt = init_defaults.get(_missing_pname) if _missing_pname else None
            arg_pairs.append(gen._default_expr_to_pair(_dflt))
        # Coerce each argument to its declared __init__ param C type — the
        # field-assignment fallback path below runs _safe_coerce_emit per
        # field, but this __init__-call path historically emitted the raw
        # arg_pairs, so a cross-module `Class(module_name=<boxed local>,
        # aset={..})` passed an int64_t into `char *` / a MojoSet* into
        # `int64_t` uncast (GCC -Wint-conversion, hard error under -fgimple).
        _init_full = gen.func_param_types.get(init_fname, [])
        if len(_init_full) == len(arg_pairs):
            for _ai in range(1, len(arg_pairs)):
                _want = _init_full[_ai]
                _have_t, _have_v = arg_pairs[_ai]
                if _want and _have_t and _want != _have_t:
                    _cv = gen._new_temp(_want)
                    gen._safe_coerce_emit(_have_t, _want, _have_v, _cv)
                    arg_pairs[_ai] = (_want, _cv)
        gen._emit_call('void', '', init_fname, arg_pairs)
    if (not _did_init_call) and (_n_kw > 0 or _n_args > 0):
        # Positional args + keyword args — assign fields by position then by
        # name. Iterate `gen.struct_field_types[struct_name]` (a real dict)
        # directly rather than `list(... .items())` / `dict(...)` — on the
        # self-hosted path a `.items()` 2-tuple comprehension + `list()`/
        # `dict()` round-trip boxes the field-name keys, so the
        # `kname in fields_dict` test below missed every kwarg and
        # `Point(x=3, y=4)` lowered to a bare `_alloc_Point()`.
        _sft = gen.struct_field_types.get(struct_name, {})
        _fnames = []
        for _fn0 in _sft:
            _fnames.append(_as_str(_fn0))
        # Assign positional args first (by field declaration order)
        for i, arg in enumerate(args):
            if i < len(_fnames):
                _fnm = _fnames[i]
                _ft = _sft[_fnm]
                at, av = gen.lower_expr(arg)
                gen._safe_coerce_emit(at, _ft, av, f"{t}->{gimple_ctypes._safe_field(_fnm)}")
        # Then assign kwargs by name (may override positional, as in Python)
        for kname, kexpr in (kwargs or []):
            _kn = _as_str(kname)
            if _kn in _sft:
                ftype = _sft[_kn]
                at, av = gen.lower_expr(kexpr)
                gen._safe_coerce_emit(at, ftype, av, f"{t}->{gimple_ctypes._safe_field(_kn)}")
    if struct_name == 'Span':
        # Span is erased to a hardcoded fat-pointer {_data, _len} struct
        # with no notion of its real element type (see struct_field_types
        # seed + _mojo_type's Span/StringSlice branch) — track it
        # ourselves, mirroring the existing _elem_types side-table
        # already used for MojoList *, so _lower_subscript's Span arm can
        # answer `span[i]` with the real element type instead of always
        # assuming a raw byte. Only covers the constructor shapes this
        # file actually needs (Span(ptr=.., length=..), Span(list_var),
        # Span(list=list_var)); anything else leaves _elem_types
        # untracked and _lower_subscript falls back to its existing
        # byte-oriented behavior unchanged.
        kw = dict(kwargs or [])
        elem_ct = None
        if 'ptr' in kw and isinstance(kw['ptr'], gimple_ctypes.IdentExpr):
            ptr_ct = gen.var_types.get(kw['ptr'].name)
            if ptr_ct:
                elem_ct = gimple_ctypes._elem_type(ptr_ct)
        elif 'list' in kw and isinstance(kw['list'], gimple_ctypes.IdentExpr):
            elem_ct = gen._elem_types.get(kw['list'].name)
        elif args and isinstance(args[0], gimple_ctypes.IdentExpr):
            elem_ct = gen._elem_types.get(args[0].name)
        if elem_ct:
            gen._elem_types[t] = elem_ct
    return ctype, t


def _array_field_elem_ptr(gen, member_expr) -> tuple[str, str] | None:
    """If `member_expr` (a MemberExpr, e.g. `world.blocks`) reads a
    fixed-size-array struct field (`var blocks: [Block; N]` — see
    _FIXED_ARRAY_ANN_RE and self._array_field_sizes, populated at struct
    registration in gen_module), return (elem_ptr_ctype, c_expr) where
    c_expr is the array field DECAYED to a real pointer to its first
    element (ordinary C array-to-pointer decay: `obj->field` used where
    a pointer value is expected). Returns None for every other MemberExpr
    (the ordinary field-read path handles those).

    This is the one place that understands the fixed-array field shape's
    C representation; both `_lower_subscript` (read: `obj.field[idx]`
    and, chained, `obj.field[idx].member`) and `_gen_stmt_AssignStmt`'s
    SubscriptExpr-target branch (write: `obj.field[idx] = ...`) call this
    BEFORE falling through to the ordinary `self.lower_expr(member_expr)`
    MemberExpr-read codegen, which has no notion of "this field is a
    whole embedded array, not a scalar or pointer" and could not
    otherwise produce it as a single valid C value. Once this returns a
    real pointer-to-element-type value, every existing pointer-based
    struct/array subscript mechanism elsewhere in this codegen (the
    working List[Struct]-element path, the generic `_mojo_at_` scaled-
    pointer-arithmetic helpers, and the existing whole-struct-array-
    element assignment field-by-field-copy branch) already handles it
    correctly with no further special-casing needed. See
    bugs/BUG-2026-008.md (box.3d/game) for the motivating real-world case
    (`World.blocks: [Block; MAX_BLOCKS]`)."""
    if not isinstance(member_expr, gimple_ctypes.MemberExpr):
        return None
    base_t, base_v = gen.lower_expr(member_expr.obj)
    if not base_t.endswith(' *'):
        return None
    sn = gimple_exprtypes._struct_name_of(base_t)
    info = gen._array_field_sizes.get(sn, {}).get(member_expr.member)
    if not info:
        return None
    elem_ct, _n = info
    safe_fn = gimple_ctypes._safe_field(member_expr.member)
    ptr_t = f"{elem_ct} *"
    # `-fgimple` rejects a bare array-typed component-ref assigned
    # directly to a pointer variable ("non-trivial conversion in
    # 'component_ref'") — ordinary C's implicit array-to-pointer decay
    # isn't a legal single GIMPLE rvalue; the address of the first
    # element (`&obj->field[0]`, an ADDR_EXPR of an ARRAY_REF) is.
    arr_base = gen._new_val(ptr_t, f"&{base_v}->{safe_fn}[0]")
    return ptr_t, arr_base


def _struct_data_field(gen, ctype: str):
    """Return (field_name, field_ctype) if ctype is a struct pointer with a pointer _data/data field, else (None, None)."""
    if not ctype.endswith(' *'):
        return None, None
    sn = gimple_exprtypes._struct_name_of(ctype)
    if sn in getattr(gen, '_dict_subclass_structs', ()):
        # A builtin-`dict` subclass's `_data` is a synthesized MojoDict *
        # backing store, NOT a Span/List-style raw element buffer —
        # subscript ops on it route through the dict-subclass path, not
        # `_mojo_at_` pointer arithmetic.
        return None, None
    if sn in getattr(gen, '_bytes_subclass_structs', ()):
        # A builtin-`bytes` subclass's `_data` is a synthesized MojoBytes *
        # payload, NOT a Span/List raw element buffer — inherited ops route
        # through the bytes-subclass path, not `_mojo_at_` arithmetic.
        return None, None
    sft = gen.struct_field_types.get(sn, {})
    for fname in ('_data', 'data'):
        ft = sft.get(fname, '')
        if ft.endswith(' *'):
            return fname, ft
    return None, None


def _bytes_subclass_of(gen, ctype: str) -> str:
    """If `ctype` is a pointer to a user struct that subclasses builtin
    `bytes` (see gen_module_impl), return the struct name, else ''."""
    if not ctype.endswith(' *'):
        return ''
    sn = gimple_exprtypes._struct_name_of(ctype)
    bsc = getattr(gen, '_bytes_subclass_structs', None)
    if bsc is not None and sn in bsc:
        return sn
    return ''


def _dict_subclass_of(gen, ctype: str) -> str:
    """If `ctype` is a pointer to a user struct that subclasses builtin
    `dict` (see gen_module_impl), return the struct name, else ''."""
    if not ctype.endswith(' *'):
        return ''
    sn = gimple_exprtypes._struct_name_of(ctype)
    dsc = getattr(gen, '_dict_subclass_structs', None)
    if dsc is not None and sn in dsc:
        return sn
    return ''


def _struct_defines_method(gen, sn: str, mname: str) -> bool:
    if not sn:
        return False
    sig = gen._struct_method_signatures.get(_sms_key(sn, mname))
    return sig is not None and len(sig) > 0


def _dict_subclass_defines(gen, sn: str, method: str) -> bool:
    """True if `sn` OR a local base up its inheritance chain defines its
    own `method` — an override that must win over builtin-`dict`
    delegation through the hidden `_data` backing store. The builtin
    terminal base (`dict`) contributes no method bodies of its own."""
    if not sn:
        return False
    seen = set()
    stack = [sn]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if gen._struct_defines_method(cur, method):
            return True
        for b in (getattr(gen, '_struct_bases', {}).get(cur) or []):
            stack.append(b)
    return False


def _emit_struct_subscript_write(gen, obj_v: str, obj_t: str, idx_v: str, val: str, val_t: str) -> bool:
    """Emit `obj[idx] = val` for a struct-with-_data pointer. Returns True if handled."""
    fname, ftype = gen._struct_data_field(obj_t)
    if fname is None:
        return False
    dp = gen._new_val(ftype, f"{obj_v}->{fname}")
    # GIMPLE: can't chain casts in one expr; split into two steps
    vp = gen._new_val('void *', f"(void *){dp}")
    i64p = gen._new_val('int64_t *', f"(int64_t *){vp}")
    idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
    gen._ptr_helpers_needed.add('int64_t')
    addr = gen._new_val('int64_t *', f"_mojo_at_int64_t ({i64p}, {idx64})")
    v64 = gen._new_temp('int64_t')
    gen._safe_coerce_emit(val_t, 'int64_t', val, v64)
    gen._emit(f"  *{addr} = {v64};")
    return True


def _lower_subscript(gen, node: gimple_ctypes.SubscriptExpr) -> tuple[str, str]:
    # Keyword-parametrized slice, e.g. `x[byte=:-1]` (slice by byte offset).
    # The parser stashes the real SliceExpr in node.attrs (obj=None, since
    # the object wasn't known yet at that point) and leaves node.index as a
    # dummy IntLiteral(0) placeholder — attach the real object and lower it
    # as an actual slice instead of falling through to the scalar-index path.
    if node.attrs:
        for _attr_name, _attr_val in node.attrs:
            if _attr_name == 'byte' and isinstance(_attr_val, gimple_ctypes.SliceExpr):
                _attr_val.obj = node.obj
                return gen._lower_slice(_attr_val)

    # Regular slice subscript: node.index is a bare SliceExpr (obj=None)
    # whose object is really the SubscriptExpr's own obj — forward it so
    # _lower_slice can determine the container type and call the correct
    # runtime function (mojo_list_slice, mojo_str_slice, etc.) instead of
    # falling through to the generic pointer-arithmetic path below which
    # would return the raw address of the first element as int64_t.
    if isinstance(node.index, gimple_ctypes.SliceExpr):
        node.index.obj = node.obj
        return gen._lower_slice(node.index)

    # Fixed-size-array struct field: `obj.field[idx]` (and, chained,
    # `obj.field[idx].member`). See _array_field_elem_ptr's own
    # docstring for why this must run BEFORE the generic
    # `self.lower_expr(node.obj)` just below.
    if isinstance(node.obj, gimple_ctypes.MemberExpr):
        _arr = gen._array_field_elem_ptr(node.obj)
        if _arr is not None:
            _ot, _ov = _arr
            _elem_ct = _ot[:-2]  # strip trailing ' *'
            _idx_type, _iv = gen.lower_expr(node.index)
            _idx64 = gen._new_val('int64_t', f"(int64_t) {_iv}")
            gen._ptr_helpers_needed.add(_elem_ct)
            _addr = gen._new_val(_ot, f"_mojo_at_{gimple_ctypes._c_id(_elem_ct)} ({_ov}, {_idx64})")
            if _elem_ct in gen.struct_field_types:
                # Struct-valued element: return a POINTER to it (this
                # codegen's universal struct-field convention — same
                # shape the working List[Struct]-element path returns),
                # so a chained `.member` read/write off this subscript
                # routes through the ordinary `ptr->member` path.
                return _ot, _addr
            _t = gen._new_val(_elem_ct, f"*{_addr}")
            return _elem_ct, _t

    ot, ov = gen.lower_expr(node.obj)

    # `self.prop[key]` where `prop` is a 0-arg property/method accessed
    # without call syntax lowers `self.prop` alone to a deferred,
    # uncalled `MojoBoundMethod *` value (see _lower_bound_method_
    # value) — correct when the consuming context is itself a call
    # (`self.prop()`), but a subscript is NOT a call: real Python
    # auto-invokes `prop` (the property getter / bound method) first,
    # THEN subscripts its actual return value. Left unhandled, the
    # generic "opaque/unknown pointer type" fallback further below
    # tried to treat the MojoBoundMethod* itself as an array base
    # pointer (a `_mojo_at_MojoBoundMethod` GIMPLE pointer-arithmetic
    # helper on a struct with no such element shape — "cannot convert
    # to a pointer type" / "non-trivial conversion") and, worse,
    # reinterpreted the subscript's STRING key as a raw integer byte
    # offset. Confirmed via Lib/importlib/metadata/__init__.py's
    # `Distribution.name`/`.version` properties, both `return self.
    # metadata['Name']`/`self.metadata['Version']` where `metadata` is
    # an inherited `@property` defined on the base class — the
    # subscript's own object expression is a bare, uncalled bound
    # method the same way any deferred `f = self.method` reference is.
    if ot == 'MojoBoundMethod *':
        ot, ov = gmp._auto_invoke_bound_method_value(gen, ov)

    idx_type, iv  = gen.lower_expr(node.index)

    # A USER-STRUCT instance whose class defines `__getitem__`: `obj[key]`
    # is real Python protocol dispatch to that method — NOT a container
    # read (see _lower_struct_subscript_dunder). Must sit after the
    # MojoList/MojoDict branches' guard conditions can't fire for user
    # structs anyway, but before the struct-pointer fallbacks below.
    _getitem_r = gmp._lower_struct_subscript_dunder(gen, ot, ov, '__getitem__',
                                                    [(idx_type, iv)])
    if _getitem_r is not None:
        return _getitem_r

    # `d[k]` on a builtin-`dict` subclass with no `__getitem__` override:
    # read from the backing MojoDict. On a miss, if the class defines
    # `__missing__`, `d[k]` is `type(d).__missing__(d, k)` (Counter uses
    # this to yield 0). See bugs/COMPILE_FAIL_collections___init__.md.
    _dsub_r = gen._dict_subclass_of(ot)
    if _dsub_r:
        dp = gen._new_val('MojoDict *', f"{ov}->_data")
        kt, kv = gen._char_to_cstr(idx_type, iv)
        if gen._struct_defines_method(_dsub_r, '__missing__'):
            has = gen._call_expr('int', 'mojo_dict_contains',
                                 [('MojoDict *', dp), (kt, kv)])
            res = gen._new_temp('int64_t')
            bb_hit = gen._new_bb()
            bb_miss = gen._new_bb()
            bb_done = gen._new_bb()
            gen._emit(f"  if ({has} != 0) goto {bb_hit}; else goto {bb_miss};")
            gen._emit_label(bb_hit)
            hv = gen._call_expr('int64_t', 'mojo_dict_get_int',
                                [('MojoDict *', dp), (kt, kv)])
            gen._emit(f"  {res} = {hv};")
            gen._emit(f"  goto {bb_done};")
            gen._emit_label(bb_miss)
            miss_mangled = gen._struct_method_csym(_dsub_r, '__missing__', '')
            mv = gen._call_expr('int64_t', miss_mangled, [(ot, ov), (kt, kv)])
            gen._emit(f"  {res} = {mv};")
            gen._emit(f"  goto {bb_done};")
            gen._emit_label(bb_done)
            return 'int64_t', res
        t = gen._call_expr('int64_t', 'mojo_dict_get_int',
                           [('MojoDict *', dp), (kt, kv)])
        return 'int64_t', t

    # `x[i]` on a builtin-`bytes` subclass with no `__getitem__` override:
    # a single-byte read (int) against the backing MojoBytes. See
    # bugs/COMPILE_FAIL_zipfile___init__.md.
    _bsub_r = gen._bytes_subclass_of(ot)
    if _bsub_r and not gen._struct_defines_method(_bsub_r, '__getitem__'):
        bp = gen._new_val('MojoBytes *', f"{ov}->_data")
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        return 'int64_t', gen._new_val('int64_t', f"mojo_bytes_get ({bp}, {idx64})")

    if ot == 'MojoList *':
        elem = gen._elem_of(ov)
        # A `struct.unpack(...)` result has ONE container ctype but a
        # per-slot real kind, known statically from the format. Prefer it
        # over the uniform element type so a format mixing ints and floats
        # reads each slot correctly instead of handing back a float's raw
        # IEEE bits. Needs a literal index (the overwhelmingly common shape:
        # `a, b = struct.unpack('<if', buf)` then `a`/`b`); a computed
        # index genuinely has no static answer, so it keeps the uniform
        # fallback rather than guessing.
        _sk = gen._struct_slot_kinds.get(ov)
        if _sk and isinstance(node.index, gimple_ctypes.IntLiteral):
            _si = node.index.value
            if 0 <= _si < len(_sk):
                _skd = _sk[_si]
                idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
                if _skd == 'double':
                    return 'double', gen._new_val(
                        'double', f"mojo_list_get_double ({ov}, {idx64})")
                if _skd == 'bytes':
                    _bt = gen._new_val('int64_t',
                                       f"mojo_list_get_int ({ov}, {idx64})")
                    return 'MojoBytes *', gen._new_val(
                        'MojoBytes *', f"(MojoBytes *)(uintptr_t){_bt}")
                return 'int64_t', gen._new_val(
                    'int64_t', f"mojo_list_get_int ({ov}, {idx64})")
        suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        # A list that records its OWN per-slot kinds, read at an index that is
        # not a compile-time constant, is the one read with no static answer:
        # the loop variable of `for x in struct.unpack('<if', buf)` and the
        # value of `struct.unpack('<if', buf)[i]` both used to come out of
        # one accessor, which hands back a float slot's raw IEEE-754 bits.
        # The runtime knows the kind, so read it there and let the box carry
        # it out of the slot; the consumer resolves it (see gen._boxed_vals).
        # Checked BEFORE the uniform-suffix branches, because a heterogeneous
        # list's tracked element type is its PROMOTED one — 'double' for
        # `[1, 2.5]` — which is exactly the answer that is wrong for its int
        # slot. A list with no kinds of its own is unaffected: a set
        # membership test at compile time, and the identical accessor
        # otherwise.
        if ov in getattr(gen, '_maybe_kinds_vals', ()):
            t = gen._new_val('int64_t', f"mojo_list_get_boxed ({ov}, {idx64})")
            gen._boxed_vals.add(t)
            return 'int64_t', t
        if suf == 'double':
            t = gen._new_val('double', f"mojo_list_get_double ({ov}, {idx64})")
            return 'double', t
        if suf == 'str':
            t = gen._new_val('char *', f"mojo_list_get_str ({ov}, {idx64})")
            return 'char *', t
        t = gen._new_val('int64_t', f"mojo_list_get_int ({ov}, {idx64})")
        # Return the actual pointer type for pointer elements (MojoDict*,
        # MojoList*, MojoSet*) so downstream consumers (subscript, method
        # dispatch) see the real type instead of raw int64_t.  Without this,
        # x = lst[0]; x["key"] on a list-of-dicts field fails because
        # var_types[x] is int64_t and x["key"] dispatches on int64_t instead
        # of MojoDict* — see BUG-2026-044.
        if elem and elem.endswith(' *'):
            gen._actual_types[t] = elem
            cast_t = gen._new_val(elem, f'({elem}){t}')
            gen._actual_types[cast_t] = elem
            # Propagate nested element types for MojoList* (list-of-lists)
            if elem == 'MojoList *':
                if ov in gen._nested_elem_types:
                    gen._elem_types[cast_t] = gen._nested_elem_types[ov]
                    gen._elem_types[t] = gen._nested_elem_types[ov]
                else:
                    gen._elem_types[t] = gen._elem_types.get(ov, 'int64_t')
                    if gen._elem_types[t] in ('int64_t',) and ov in gen._elem_types:
                        gen._elem_types[cast_t] = gen._elem_types[ov]
            # For MojoDict* elements, propagate dict value type from the
            # container (list variable) so subsequent ["key"] subscript
            # dispatches to mojo_dict_get_str instead of mojo_dict_get_int.
            if elem == 'MojoDict *' and ov in gen._dict_val_types:
                gen._dict_val_types[cast_t] = gen._dict_val_types[ov]
            return elem, cast_t
        return 'int64_t', t

    if ot == 'MojoStr *':
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        t = gen._new_val('char', f"mojo_str_char_at ({ov}, {idx64})")
        return 'char', t

    if ot == 'MojoBytes *':
        # b[i] -> int 0-255 (never a 1-char str; bytes is not conflated
        # with str). Negative index handled in mojo_bytes_get.
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        t = gen._new_val('int64_t', f"mojo_bytes_get ({ov}, {idx64})")
        return 'int64_t', t

    if ot == 'MojoMemoryView *':
        # mv[i] -> int (1-D byte view). Negative index handled in the helper.
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        t = gen._new_val('int64_t', f"mojo_memoryview_get ({ov}, {idx64})")
        return 'int64_t', t

    if ot == 'MojoDict *':
        # A bytes KEY reads from its own key domain (see _DictSlot.keykind);
        # `_char_to_cstr` on a `MojoBytes *` would cast the POINTER to char*
        # and probe for that address, which never matches what the write side
        # stored. Keyed by content, exactly like the str path.
        if idx_type == 'MojoBytes *':
            val_ctype = gen._dict_val_of(ov)
            if val_ctype == 'char *':
                return 'char *', gen._call_expr('char *', 'mojo_dict_get_bytes_str',
                                                [('MojoDict *', ov), ('MojoBytes *', iv)])
            if val_ctype == 'double':
                return 'double', gen._call_expr('double', 'mojo_dict_get_bytes_double',
                                                [('MojoDict *', ov), ('MojoBytes *', iv)])
            return 'int64_t', gen._call_expr('int64_t', 'mojo_dict_get_bytes_int',
                                             [('MojoDict *', ov), ('MojoBytes *', iv)])
        # Ensure index is char * for dict subscript access (all dict keys are strings in runtime)
        idx_type, iv = gen._char_to_cstr(idx_type, iv, True, True)
        val_ctype = gen._dict_val_of(ov)
        if val_ctype == 'double':
            t = gen._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', ov), (idx_type, iv)])
            return 'double', t
        if val_ctype == 'char *':
            t = gen._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', ov), (idx_type, iv)])
            return 'char *', t
        if val_ctype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            # Pointer value stored boxed as int64_t; recover the real type so a
            # later v[k2] / v.get(...) dispatches on the right container.
            raw = gen._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
            t = gen._new_val(val_ctype, f"({val_ctype}){raw}")
            # `d[k]` where `d: dict[K, dict[K2, V2]]` — carry V2 onto the inner
            # dict temp so `d[k][k2]` / `d[k].items()` type right (bug: every
            # `member in gen.struct_field_types[sn]` no-op'd on an int64_t).
            _nd = gen._dict_nested_val_types.get(ov)
            if _nd and val_ctype == 'MojoDict *':
                gen._dict_val_types[t] = _nd
            return val_ctype, t
        t = gen._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
        return 'int64_t', t

    # Opaque Python object (typed as int) — treat as MojoList via cast
    # `_Bool` is included here too: a SIMD comparison result (`simd_val.lt(...)`)
    # collapses to a scalar _Bool (SIMD itself has no width tracking — every
    # SIMD[dtype, N] value is scalar-erased regardless of N; subscripting the
    # vector directly, e.g. `simd_val[0]`, already goes through this exact
    # same MojoList-cast fakery below and "compiles" the same way). Without
    # this, `_Bool` falls to the final generic-pointer-deref fallback further
    # down, which assumes its receiver is a real pointer and errors trying to
    # dereference a bare _Bool.
    if ot in ('int', 'int64_t', '_Bool'):
        # Check actual type for globals loaded as int64_t
        actual_type = gen._get_actual_type(ot, ov)
        if actual_type == 'char *':
            # A string boxed as int64_t (its declared storage type was
            # widened joining with other assignment sites in the same
            # function — see _lower_builtin_len's identical blind spot,
            # fixed alongside this) still needs real char indexing, not
            # the MojoList* fallback below: that reinterprets the
            # string's own bytes as a MojoList header and segfaults deep
            # in mojo_list_get_int. Found via fire_compiler.py's own
            # `rest[0]` in _strip_string_prefix_and_quotes.
            cp = gen._new_val('char *', f'(char *){gen._ensure_local(ot, ov)}')
            idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
            gen._ptr_helpers_needed.add('char')
            addr = gen._new_val('char *', f"_mojo_at_char ({cp}, {idx64})")
            # `s[i]` on a str is a 1-char STRING, not a character code —
            # the same rule as _gen_for_cstr / _compr_cstr_loop (see those
            # for what returning a bare `char` broke). `mojo_char_to_str`
            # is the existing helper; `rest[0]` comparing against a quote
            # literal is the canonical use.
            # `mojo_cstr_slice` rather than a `char`-taking helper:
            # gimple rejects a `char` argument ("invalid argument to
            # gimple call" — a char is promoted to int64_t non-trivially).
# `1LL`, not `(int64_t)1`: a C-style cast is not a legal gimple
            # operand. `_t = _i + (int64_t)1` is rejected at gimplification
            # with "expected expression before '(' token" -- a HARD error
            # under `gcc -fgimple`, so it takes out the whole self-host
            # closure, not just this subscript. The `LL` suffix is the
            # tree's existing idiom for a width-correct int64_t literal
            # (`0LL` appears throughout the generated C) and needs no cast.
            _one_cs = gen._new_val('int64_t', f"{idx64} + 1LL")
            return 'char *', gen._new_val(
                'char *', f"mojo_cstr_slice ({cp}, {idx64}, {_one_cs})")
        # A STRING index proves the container is a dict even when its own
        # type is opaque: no list is indexable by a string. `pat.fields`
        # in ast_rewriter.py is exactly this — the A5 boxed-member read
        # can't type it (Node.fields is a boxed int64_t while
        # StructDef.fields is a MojoList*, so _known_field_type is
        # ambiguous), and `pat.fields[fname]` with `fname` a dict key then
        # fell to the MojoList* fallback below, reinterpreting the dict
        # header as a list and faulting inside mojo_list_get_int.
        _idx_is_str = (idx_type in ('char *', 'MojoStr *')
                       or gen._get_actual_type(idx_type, iv) == 'char *')
        if actual_type == 'MojoDict *' or (_idx_is_str and actual_type not in ('MojoList *', 'MojoSet *')):
            # Dict subscript: int64_t → MojoDict *
            dp = gen._coerce_to_type(ot, 'MojoDict *', gen._ensure_local(ot, ov))
            # Propagate dict value type from source (ov) so _dict_val_of
            # below returns the correct value type (char * etc.) instead
            # of defaulting to int64_t — fixes BUG-2026-043.
            if ov in gen._dict_val_types:
                gen._dict_val_types[dp] = gen._dict_val_types[ov]
            # Ensure index is char * for dict access (all dict keys are strings in runtime)
            idx_type_for_dict, idx_for_dict = gen._char_to_cstr(idx_type, iv, True, True)
            val_ctype = gen._dict_val_of(dp)
            if val_ctype == 'double':
                t = gen._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                return 'double', t
            if val_ctype == 'char *':
                t = gen._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                return 'char *', t
            t = gen._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
            return 'int64_t', t
        # Otherwise treat as MojoList* stored as int; cast and subscript
        lp = gen._coerce_to_type(ot, 'MojoList *', gen._ensure_local(ot, ov))
        idx64 = gen._to_int64(idx_type, iv)
        # Copy element type tracking from the int64_t temp to the MojoList * temp
        # This is critical for nested list access: when lp came from arr[i], we need to know
        # what elements lp contains so subsequent accesses like lp[j] use the right function
        if ov in gen._elem_types:
            gen._elem_types[lp] = gen._elem_types[ov]
        if ov in gen._nested_elem_types:
            gen._nested_elem_types[lp] = gen._nested_elem_types[ov]
        # Get element type: check _elem_types (if ov is a tracked temp), else check _nested_elem_types
        elem = gen._elem_of(ov)
        if not elem or elem == 'int64_t':
            # Check if ov came from a subscript that returned a list with tracked nested elements
            if ov in gen._elem_types:
                elem = gen._elem_types[ov]
            elif ov in gen._nested_elem_types:
                elem = gen._nested_elem_types[ov]
        if elem == 'char *':
            t = gen._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
            return 'char *', t
        if elem == 'double':
            t = gen._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
            return 'double', t
        t = gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        # Any OTHER pointer element type (struct pointers like Recipe*,
        # or MojoDict*/MojoList*/MojoSet*) was falling all the way
        # through to the plain int64_t return below, unlike the direct
        # `ot == 'MojoList *'` branch above which already casts back to
        # `elem` when it ends in ' *'. Every global container is boxed
        # as int64_t at the C struct level (see "Globals are stored at
        # C level as int64_t" elsewhere in this file), so a global
        # `List[Struct]` ALWAYS arrives here via this opaque-cast path,
        # never the direct branch -- meaning a struct-element global
        # list's reads always silently degraded to raw int64_t instead
        # of the real struct pointer, and a later `.field` access on
        # that mistyped int64_t fell back to dynamic `_mojo_dispatch_
        # getattr`, which only recognizes the FIRST field of the
        # boxed-int64_t "value" mojo_list_get_int actually returned
        # (the pointer's own low bytes were being read further, not the
        # struct's memory at all) -- e.g. `r.width`/`r.output_id` in
        # box.3d/game/lib/recipes.mojo's `match_shaped` reading garbage
        # for every recipe. See bugs/DYLIB_struct_list_index_reads_
        # first_field_only_wrong_craft_results.md.
        if elem and elem.endswith(' *'):
            gen._actual_types[t] = elem
            cast_t = gen._new_val(elem, f'({elem}){t}')
            gen._actual_types[cast_t] = elem
            if elem == 'MojoList *':
                if ov in gen._nested_elem_types:
                    gen._elem_types[cast_t] = gen._nested_elem_types[ov]
                    gen._elem_types[t] = gen._nested_elem_types[ov]
            if elem == 'MojoDict *' and ov in gen._dict_val_types:
                gen._dict_val_types[cast_t] = gen._dict_val_types[ov]
            return elem, cast_t
        return 'int64_t', t

    # Struct pointer subscript: Span[i] → Span->_data[i] etc. Guarded to
    # EXACTLY one level of pointer (`ot[:-2]` itself must not also end in
    # ' *'): `_struct_name_of` strips every ' *' occurrence, not just
    # one, so without this guard a genuine DOUBLE pointer (`amd_signal_t
    # * *` — e.g. `UnsafePointer(to=x).bitcast[UnsafePointer[T]]()[]`'s
    # own intermediate subscript, once `.bitcast[...]()` correctly
    # returns a real two-level pointer type — see the `bitcast`/
    # `unsafe_ptr_cast` handling in `_lower_call`) would ALSO match "bare
    # struct name amd_signal_t", treating a pointer-to-pointer as
    # Span-style struct sugar and mis-subscripting it (confirmed via
    # std/sys/_amdgpu.mojo's `hsa_signal_add`). A real double pointer
    # needs plain pointer-arithmetic dereference instead — falls through
    # to the generic "p[i] via _mojo_at_ helper" case below, which
    # already handles it correctly (strips exactly one level via
    # `_elem_type`).
    if (ot.endswith(' *') and not ot[:-2].endswith(' *')
            and gimple_exprtypes._struct_name_of(ot) in gen.struct_field_types):
        tracked = gen._elem_types.get(ov)
        if tracked and tracked in gen.struct_field_types:
            # Span's hardcoded {_data, _len} model always assumes a raw
            # byte element (see struct_field_types['Span'] and
            # _struct_data_field) — but this particular Span * was
            # constructed from a real struct-typed source and its element
            # type was tracked (_lower_struct_constructor's Span
            # handling), mirroring the existing _elem_types side-table
            # already used for MojoList *. Cast the raw byte _data
            # pointer through the real element pointer type and reuse the
            # same generic _mojo_at_ scaled-arithmetic helper (already
            # works for any element C type, struct or scalar — no new
            # helper-generation code needed) instead of the byte-oriented
            # fallback below.
            fname, ftype = gen._struct_data_field(ot)
            if fname is not None:
                raw = gen._new_val(ftype, f"{ov}->{fname}")
                et_ptr = tracked + ' *'
                dp = gen._new_val(et_ptr, f"({et_ptr}){raw}")
                cn = gimple_ctypes._c_id(tracked)
                gen._ptr_helpers_needed.add(tracked)
                idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
                addr = gen._new_val(et_ptr, f"_mojo_at_{cn} ({dp}, {idx64})")
                t = gen._new_val(tracked, f"*{addr}")
                return tracked, t
        fname, ftype = gen._struct_data_field(ot)
        if fname is not None:
            dp = gen._new_val(ftype, f"{ov}->{fname}")
            et = gimple_ctypes._elem_type(ftype)
            cn = gimple_ctypes._c_id(et)
            gen._ptr_helpers_needed.add(et)
            idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
            addr = gen._new_val(ftype, f"_mojo_at_{cn} ({dp}, {idx64})")
            if et == 'void':
                return ftype, addr
            t = gen._new_val(et, f"*{addr}")
            return et, t
        # No `_data`/`data` sugar field on this struct: this is NOT a
        # Span/List-style container providing `container[i]` sugar over
        # its own internal buffer — it's genuine pointer-to-struct-array
        # arithmetic, i.e. `p[i]` for a bare `p: UnsafePointer[T]` (or
        # `OwnedPointer`/`ArcPointer`/`Pointer`) whose pointee type T
        # simply doesn't happen to have a `_data` field. `p[i]` there
        # means "the T at this address plus i elements" — kept as a
        # `T *` (this codegen's universal "a struct value is always T *"
        # convention, BUG-2026-030), NOT collapsed to an opaque int64_t
        # handle, so a chained `.field` read/write off the result routes
        # through the ordinary `ptr->member` path instead of falling to
        # the dynamic/boxed `mojo_obj_getattr` fallback (which doesn't
        # know this struct's real layout and raises "AttributeError:
        # `<field>`" at runtime — see bugs/CODEGEN_struct_pointer_deref_
        # field_access_crash.md; previously EVERY struct-typed
        # UnsafePointer subscript without a `_data` field hit exactly
        # this bug, since `_struct_data_field` only recognizes the
        # Span/List sugar shape, not plain data structs).
        cn = gimple_ctypes._c_id(ot[:-2])
        gen._ptr_helpers_needed.add(ot[:-2])
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
        addr = gen._new_val(ot, f"_mojo_at_{cn} ({ov}, {idx64})")
        return ot, addr

    # p[i] via _mojo_at_ helper (ptr arithmetic not allowed in __GIMPLE)
    et = gimple_ctypes._elem_type(ot)
    cn = gimple_ctypes._c_id(et)
    gen._ptr_helpers_needed.add(et)
    idx64 = gen._new_val('int64_t', f"(int64_t) {iv}")
    addr = gen._new_val(ot, f"_mojo_at_{cn} ({ov}, {idx64})")
    # Can't dereference void* (no element type); return the pointer itself
    if et == 'void':
        return ot, addr
    # Struct types: return int64_t (opaque handle) — can't cast struct→int64_t in GIMPLE
    if et in gen.struct_field_types:
        t = gen._new_val('int64_t', f"(int64_t){addr}")
        return 'int64_t', t
    # A `char *` is this codegen's plain `str`, so `_elem_type` says `char`
    # and the generic branch below would hand back the character CODE. But
    # `s[i]` on a Python str is a 1-char STRING — the same rule as
    # _gen_for_cstr / _compr_cstr_loop / the boxed-string subscript branch
    # above, all of which now return `char *` via `mojo_char_to_str`.
    # Without it every string index disagreed with every string iteration:
    # `s[0]` was 97 while `for c in s` bound 'a'.
    if et == 'char':
        # `mojo_cstr_slice` rather than a `char`-taking helper: gimple
        # rejects a `char` argument ("invalid argument to gimple call"),
        # since a char is promoted to int64_t non-trivially.
# `1LL`, not `(int64_t)1`: a C-style cast is not a legal gimple
        # operand. `_t = _i + (int64_t)1` is rejected at gimplification
        # with "expected expression before '(' token" -- a HARD error
        # under `gcc -fgimple`, so it takes out the whole self-host
        # closure, not just this subscript. The `LL` suffix is the
        # tree's existing idiom for a width-correct int64_t literal
        # (`0LL` appears throughout the generated C) and needs no cast.
        _one_gs = gen._new_val('int64_t', f"{idx64} + 1LL")
        return 'char *', gen._new_val(
            'char *', f"mojo_cstr_slice ({ov}, {idx64}, {_one_gs})")
    t = gen._new_val(et, f"*{addr}")
    return et, t


def _lower_slice_bounds(gen, node: gimple_ctypes.SliceExpr) -> tuple[str, str]:
    """Compute (start_v, stop_v) C expressions for a SliceExpr's bounds
    — shared by _lower_slice (read a sub-range) and the DelStmt lowering
    for `del container[a:b]` (remove a sub-range in place), since both
    need the identical bound normalization."""
    if node.start is not None:
        _st, sv = gen.lower_expr(node.start)
        # Use the REAL type lower_expr just gave `sv`, not _quick_type's
        # static estimate — _quick_type(IntLiteral) always guesses
        # 'int64_t', but _lower_UnaryOp('-', IntLiteral) actually emits a
        # plain C `int`-typed temp for a negated literal (its "pointer
        # negate" special-case only widens to int64_t for pointer
        # operands). _to_int64 trusted the estimate and skipped the
        # int->int64_t cast, so `groups[:-1]` on a struct method (any
        # context where `_ensure_local` couldn't already coerce it)
        # passed a bare 32-bit -1 where mojo_list_slice's `int64_t stop`
        # expects one — GIMPLE calls don't do C's usual argument
        # promotion, so the raw bits got zero-extended into
        # 4294967295 instead of sign-extended into -1, `stop < 0` came
        # back false, and the slice silently returned the WHOLE list
        # instead of dropping the last element. Found via a from-scratch
        # minimal repro (struct method + `lst[:-1]` comprehension) while
        # chasing `make bootstrap`'s verify byte-identity failures.
        start_v = gen._to_int64(_st, sv)
    else:
        start_v = '0'
    if node.stop is not None:
        _et, ev = gen.lower_expr(node.stop)
        stop_v = gen._to_int64(_et, ev)
    else:
        # Sentinel for "to end" — must NOT be a plain -1, which a real
        # `x[:-1]` (drop the last char/element) also produces; see
        # MOJO_SLICE_STOP_OMITTED's doc comment in fire_runtime.h.
        stop_v = 'MOJO_SLICE_STOP_OMITTED'
    return start_v, stop_v


def _lower_slice(gen, node: gimple_ctypes.SliceExpr) -> tuple[str, str]:
    ot, ov = gen.lower_expr(node.obj)
    start_v, stop_v = gen._lower_slice_bounds(node)

    # `x[a:b]` on a builtin-`bytes` subclass instance -> a plain bytes
    # slice of its payload (CPython returns `bytes`, not the subclass).
    # See COMPILE_FAIL_zipfile___init__.md.
    if gen._bytes_subclass_of(ot) and not gen._struct_defines_method(
            gen._bytes_subclass_of(ot), '__getitem__'):
        ov = gen._new_val('MojoBytes *', f"{ov}->_data")
        ot = 'MojoBytes *'

    if ot == 'MojoStr *':
        t = gen._new_val('MojoStr *', f"mojo_str_slice ({ov}, {start_v}, {stop_v})")
        return 'MojoStr *', t

    if ot == 'MojoBytes *':
        if getattr(node, 'step', None) is not None:
            _kt, kv = gen.lower_expr(node.step)
            step_v = gen._to_int64(_kt, kv)
        else:
            step_v = '1'
        # Omitted start: pass the OMITTED sentinel (not 0) so mojo_bytes_slice
        # can pick the right endpoint for a negative step (`b[::-1]`).
        bstart_v = 'MOJO_SLICE_STOP_OMITTED' if node.start is None else start_v
        t = gen._new_val('MojoBytes *',
                         f"mojo_bytes_slice ({ov}, {bstart_v}, {stop_v}, {step_v})")
        return 'MojoBytes *', t

    if ot == 'MojoMemoryView *':
        # mv[a:b] -> a sub-view into the SAME buffer (no copy). Step not
        # supported for a non-contiguous view; sentinel start like bytes.
        bstart_v = 'MOJO_SLICE_STOP_OMITTED' if node.start is None else start_v
        t = gen._new_val('MojoMemoryView *',
                         f"mojo_memoryview_slice ({ov}, {bstart_v}, {stop_v}, 1)")
        return 'MojoMemoryView *', t

    if ot == 'MojoList *':
        t = gen._new_val('MojoList *', f"mojo_list_slice ({ov}, {start_v}, {stop_v})")
        # propagate elem type
        if ov in gen._elem_types:
            gen._elem_types[t] = gen._elem_types[ov]
        return 'MojoList *', t

    if ot == 'Span *':
        # Span is the fat-pointer {_data, _len} struct (see _mojo_type's
        # Span/StringSlice branch) — slicing it means allocating a new Span
        # whose _data is advanced by `start` bytes and whose _len is
        # shortened accordingly, not raw pointer-to-the-struct arithmetic
        # (which is what the generic fallback below would do, corrupting it).
        gen._struct_allocs_needed.add('Span')
        t = gen._new_temp('Span *')
        gen._emit(f"  {t} = _alloc_Span ();")
        old_data = gen._new_val('char *', f"{ov}->_data")
        old_data_i = gen._new_val('int64_t', f"(int64_t){old_data}")
        start_i = gen._new_val('int64_t', f"(int64_t){start_v}")
        new_data_i = gen._new_val('int64_t', f"{old_data_i} + {start_i}")
        new_data = gen._new_val('char *', f"(char *){new_data_i}")
        gen._emit(f"  {t}->_data = {new_data};")
        old_len = gen._new_val('int64_t', f"{ov}->_len")
        if node.stop is not None:
            # GIMPLE strict mode: a bare literal stop bound (e.g. `[:0]`)
            # comes back from _to_int64 uncast (its _ensure_local fast path
            # treats a bare digit as "already fine"), so re-cast defensively
            # here — mirroring start_i just above — or `stop_v - start_i`
            # mixes an untyped int literal with an int64_t and GIMPLE
            # rejects the binary expression outright.
            stop_i = gen._new_val('int64_t', f"(int64_t){stop_v}")
            new_len = gen._new_val('int64_t', f"{stop_i} - {start_i}")
        else:
            new_len = gen._new_val('int64_t', f"{old_len} - {start_i}")
        gen._emit(f"  {t}->_len = {new_len};")
        return 'Span *', t

    if ot == 'char *':
        # A plain (non-MojoStr-wrapped) Python str, boxed as char* — a
        # NUL-terminated C string has no length field to bound a slice
        # copy against, unlike MojoStr's `->len`. The generic "plain
        # pointer" fallback below just adds `start` to the pointer,
        # which happens to look right for `s[start:]` (the tail reads
        # correctly to the string's own real end) but silently drops
        # `stop` entirely for `s[:stop]`/`s[start:stop]` — no truncation
        # ever happens. See mojo_cstr_slice in runtime/fire_runtime.c.
        t = gen._new_val('char *', f"mojo_cstr_slice ({ov}, {start_v}, {stop_v})")
        return 'char *', t

    # Plain pointer: return pointer to start (no bounds check)
    # GIMPLE: no pointer+integer; cast pointer through int64_t; both operands
    # must be plain variables (no cast expressions in binary operands).
    t = gen._new_temp(ot)
    cast_t = gen._new_val('int64_t', f"(int64_t){ov}")
    # Cast start to int64_t in a separate statement (GIMPLE binary operands
    # must be variables, not cast expressions)
    if start_v.lstrip('-').isdigit():
        sv_cast = gen._new_val('int64_t', f"(int64_t){start_v}")
    else:
        # start_v is already a variable; ensure it's int64_t
        sv_cast = gen._new_val('int64_t', f"(int64_t){start_v}")
    add_t = gen._new_val('int64_t', f"{cast_t} + {sv_cast}")
    gen._emit(f"  {t} = ({ot}){add_t};")
    return ot, t
