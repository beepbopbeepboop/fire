"""Shared middle-end extracted from gimple_gen_calls.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _as_str, _sms_key
import regex_compile
import mlir
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

def _ident_call_name(gen, func_node) -> str:
    """`func_node.name` for a call whose callee is an IdentExpr, forced to
    `char *` by the return annotation. `CallExpr.func` is polymorphic
    (`object`), so a boxed handle's `.name` read stays typed int64_t and,
    used as a `func_return_types` / `imported_symbols` dict key, misses
    every lookup — the compiled compiler then treats a plain call to a
    local `def` as an unknown name and emits a bogus
    `__attribute__((weak)) "unavailable in compiled mode"` stub for it
    (`bump()`, `inner()`). Callers must have already checked
    `isinstance(func_node, IdentExpr)`."""
    return func_node.name

def _isinstance_type_name(ta):
    """Bare class name for an isinstance() type argument — `IdentExpr` name
    directly, or the trailing attribute of a `module.Class` `MemberExpr`
    (`gimple_ctypes.IdentExpr` → `IdentExpr`); the module qualifier is a
    Python-import artifact with no bearing on the runtime type tag."""
    if isinstance(ta, gimple_ctypes.IdentExpr):
        return ta.name
    if (isinstance(ta, gimple_ctypes.MemberExpr)
            and isinstance(ta.obj, gimple_ctypes.IdentExpr)):
        return ta.member
    return None

def _default_expr_to_pair(gen, _dflt) -> tuple:
    """Convert a default-arg expression AST node to a (ctype, rvalue) pair,
    for padding a call site that omitted the argument. Mirrors the struct
    ctor default handling in _build_call_args_for_candidate."""
    if _dflt is None:
        return ('int', '0')
    if isinstance(_dflt, gimple_ctypes.BoolLiteral):
        return ('_Bool', '1' if _dflt.value else '0')
    if isinstance(_dflt, gimple_ctypes.StringLiteral):
        if getattr(_dflt, 'is_bytes', False):
            # A `b'...'` default padded into an omitted-arg call site must
            # be a real `MojoBytes *`, not a bare `char *` — route through
            # the normal bytes-literal lowering (emits the octal-escaped
            # global loaded to a local + `mojo_bytes_new_lit`).
            return gen.lower_expr(_dflt)
        return ('char *', f'"{gimple_ctypes._c_escape(_dflt.value)}"')
    if isinstance(_dflt, gimple_ctypes.FloatLiteral):
        # A float default is a `double` value — returning it typed `int`
        # made the call-site coercion emit `(double)(int)0.5`, invalid in a
        # `__GIMPLE` body ("expected expression before '(' token"). Mirror
        # `_lower_FloatLiteral`.
        _s = repr(_dflt.value)
        if '.' not in _s and 'e' not in _s.lower():
            _s += '.0'
        return ('double', _s)
    if isinstance(_dflt, gimple_ctypes.IntLiteral):
        return ('int', str(_dflt.value))
    if isinstance(_dflt, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr, gimple_ctypes.DictExpr)):
        return ('int64_t', '0')
    if isinstance(_dflt, gimple_ctypes.IdentExpr) and _dflt.name in ('True',):
        return ('int', '1')
    if isinstance(_dflt, gimple_ctypes.IdentExpr) and _dflt.name in ('False', 'None'):
        return ('int', '0')
    return ('int', '0')

def _resolve_overload(gen, candidates: list, args: list, kwargs: list | None) -> dict | None:
    """Pick the candidate overload matching a call site's argument count/
    types, from a list of signature dicts as built by the Pass 2b-bis
    registration loop (each: overload_id, param_names, param_ctypes,
    min_arity, max_arity).

    Mirrors real Mojo's observed overload resolution closely enough for
    already-valid, already-typechecked source (which is all this compiler
    ever transpiles — genuine ambiguity is a hard error in real Mojo, so a
    real call site should never present one): filter by arity range
    (accounting for default parameters), then by keyword-argument names,
    then score remaining candidates by per-position exact C-type match.
    Only ever calls the side-effect-free `_quick_type` here — the actual
    `lower_expr` (which emits code) happens once, after the caller uses
    the chosen candidate to build the real call.
    """
    if not candidates:
        return None
    kwargs = kwargs or []
    call_arity = len(args) + len(kwargs)
    # Explicit accumulation loops, NOT the original one-line comprehensions
    # (`kwarg_names = [kn for kn, _ke in kwargs]` and
    # `survivors = [c for c in candidates if c['min_arity'] <= call_arity
    # <= c['max_arity'] and all(kn in c['param_names'] for kn in
    # kwarg_names)]`). On the self-hosted compiled path those came back as
    # the garbage non-list 1, so `len(survivors)`/`if not survivors`
    # SIGSEGV'd in mojo_list_len(0x1) while compiling
    # std/collections/dict.mojo (a kwargs method call reaching the
    # 2-candidate overload set). Same comprehension trap family as
    # `''.join(<genexpr>)` / fire_compiler.py's `CallExpr.kwargs` build.
    kwarg_names = []
    for _kn0, _ke0 in kwargs:
        kwarg_names.append(_kn0)
    survivors = []
    for _c0 in candidates:
        if not (_c0['min_arity'] <= call_arity and call_arity <= _c0['max_arity']):
            continue
        _allok = True
        for _kn1 in kwarg_names:
            if _kn1 not in _c0['param_names']:
                _allok = False
                break
        if _allok:
            survivors.append(_c0)
    if not survivors:
        return None
    if len(survivors) == 1:
        return survivors[0]

    # Explicit accumulation loop, NOT `[gen._quick_type(a) for a in args]`
    # — see the `survivors` note above: a list comprehension here can erase
    # to the garbage non-list 1 on the self-hosted path.
    arg_types = []
    for _a1 in args:
        arg_types.append(gen._quick_type(_a1))
    # Keyword args bind by name to whichever positional slot that name
    # occupies in a given candidate; scored per-candidate below since
    # candidates can disagree on where a name falls.
    def _score(cand: dict) -> int:
        score = 0
        # For a `*args` pack candidate, every positional arg at or past
        # pre_star_count is consumed by the pack, not by a fixed param —
        # param_ctypes past that point belongs to necessarily-keyword-only
        # params (Mojo syntax forbids positional args after a `*args`), so
        # comparing a pack-bound arg's type against one of those ctypes at
        # the same flat index is a category error, not a real type match
        # (confirmed: it let DeviceGraphBuilder.add_function's *args-pack
        # overload lose a tie to a same-arity sibling by a coincidental
        # int64_t/int64_t collision at a position that meant nothing).
        _cap = cand['pre_star_count'] if cand.get('has_varargs') else len(arg_types)
        for i, at in enumerate(arg_types):
            if i >= _cap:
                break
            if i < len(cand['param_ctypes']) and cand['param_ctypes'][i] == at:
                score += 1
        for kn, ke in kwargs:
            if kn in cand['param_names']:
                idx = cand['param_names'].index(kn)
                if idx < len(cand['param_ctypes']) and cand['param_ctypes'][idx] == gen._quick_type(ke):
                    score += 1
        return score

    # Explicit max-by-score loop, NOT `max(survivors, key=_score)` — the
    # builtin `max(..., key=...)` form is another self-host lowering
    # hazard alongside the comprehensions above.
    _best = None
    _bestv = None
    for _c3 in survivors:
        _c3v = _score(_c3)
        if _bestv is None or _c3v > _bestv:
            _bestv = _c3v
            _best = _c3
    best = _best
    best_score = _score(best)
    # Same arity, but (when best_score == 0) no candidate's declared param
    # type matched any argument's type at all — our type erasure genuinely
    # can't tell these overloads apart (e.g. two structurally-different
    # Mojo generic types, like Tuple[T,T] and Interval[T], both erasing to
    # int64_t in this codegen's type system today). This used to return
    # None here so the caller would fall back to an unsuffixed call
    # against a "catch-all variadic stub" — but survivors has 2+ entries
    # whenever we reach this point (the len(survivors)==1 case returns
    # above), and gimple_codegen always hash-suffixes a method once it has
    # 2+ overloads, so that stub is never actually defined: the fallback
    # call site links (against -undefined dynamic_lookup) but crashes at
    # dyld resolution the moment it's actually invoked (confirmed via
    # AMDBufferResource/String in build/libmojostdlib.dylib — the "use"
    # side's assumption didn't match what the "generate" side emits).
    # Picking a real, defined candidate deterministically — same
    # first-in-declaration-order rule already used for genuine ties below
    # — is strictly safer: a plausible overload beats a guaranteed crash.
    # Explicit accumulation loop, NOT `[c for c in survivors if
    # _score(c) == best_score]` — same self-hosted comprehension-erasure
    # trap as `survivors`/`arg_types` above.
    ties = []
    for _c2 in survivors:
        if _score(_c2) == best_score:
            ties.append(_c2)
    if len(ties) > 1:
        gimple_ctypes._debug_note('ambiguous or type-indistinguishable overload, picking first in declaration order',
                    f"candidates={[c['overload_id'] for c in ties]}")
    return ties[0]

def _pack_kwargs_dict(gen, kwarg_pairs) -> str:
    """Build a real MojoDict from a call site's LITERAL keyword arguments,
    for a callee whose `**kwargs` parameter is a concrete `MojoDict *`
    (see _func_kwargs_slot / gen_func's param loop).

    `kwarg_pairs` maps each keyword name to its ALREADY-LOWERED
    (ctype, value) pair — re-lowering here would emit the argument
    expression's side effects a second time.

    String values go through mojo_dict_set_str so the dict's own value
    type is right (mojo_dict_set_int would store the char* as an integer
    and later read it back as one). Everything else — ints, doubles,
    pointers — goes through mojo_dict_set_int, which _emit_call coerces,
    matching how `d[k] = v` already lowers a subscript store."""
    d = gen._new_val('MojoDict *', 'mojo_dict_new ()')
    _val_ty = ''
    _kwp = kwarg_pairs if kwarg_pairs else {}
    for kname in _kwp:
        # Index the (ctype, value) pair, NOT `kt, kv = _kwp[kname]`: on the
        # self-hosted path the 2-tuple unpack lowers `_kwp[kname]` through
        # `mojo_list_get_int` on a slot that can be boxed/garbage → SIGBUS
        # (crash-report bt: `mojo_list_get_int` ← `_pack_kwargs_dict` on a
        # shimless `--dump-full` of an imported struct method's
        # `return Struct(x=.., y=..)`).
        _pair = _kwp[kname]
        kt = _as_str(_pair[0])
        kv = _pair[1]
        _val_ty = kt if not _val_ty or _val_ty == kt else 'int64_t'
        if kt == 'char *':
            gen._emit_call('void', '', 'mojo_dict_set_str',
                            [('MojoDict *', d), ('char *', f'"{gimple_ctypes._c_escape(kname)}"'),
                             ('char *', kv)])
        else:
            gen._emit_call('void', '', 'mojo_dict_set_int',
                            [('MojoDict *', d), ('char *', f'"{gimple_ctypes._c_escape(kname)}"'),
                             (kt, kv)])
    if _val_ty:
        gen._dict_val_types[d] = _val_ty
    return d

def _build_call_args_for_candidate(gen, chosen: dict, args: list, kwargs: list | None,
                                   defaults: dict | None = None) -> list:
    """Build the C arg-value list (self excluded) for a resolved struct
    constructor/method overload. When the overload has a `*args` pack
    parameter (chosen['has_varargs']), the params before it are lowered
    positionally, the pack itself is boxed via _lower_varargs_pack, and
    every param after it is necessarily keyword-only (Mojo syntax) so is
    bound by name from kwargs, defaulting to 0 when omitted — the old flat
    by-position scheme had no slot for the pack at all. Otherwise,
    unchanged from before: args lowered positionally, kwargs overlaid by
    name, then zero-padded up to max_arity."""
    kw = dict(kwargs or [])
    if chosen.get('has_varargs'):
        pre_n = chosen['pre_star_count']
        param_names = chosen['param_names']
        # Pre-star params bind positionally first (an actual call-site
        # positional arg wins), then by keyword name, then their real
        # default. The old code only ever consulted `args[:pre_n]` —
        # real Python allows a pre-star param to be passed by KEYWORD
        # too (`def __init__(self, x=None, *args, **kwargs)` called as
        # `f(x=1)`), and when it was, this loop produced NO entry for
        # it at all (not even a placeholder), desyncing the whole
        # trailing arg list by one slot and dropping the value outright
        # — e.g. Lib/calendar.py's `_CLIDemoCalendar(highlight_day=today)`
        # against `def __init__(self, highlight_day=None, *args,
        # **kwargs)` silently lost `today` and emitted one argument too
        # few ("too few arguments ... expected 4, have 3").
        out = []
        for _i in range(pre_n):
            if _i < len(args):
                out.append(gen.lower_expr(args[_i]))
                continue
            _pname = param_names[_i] if _i < len(param_names) else None
            if _pname is not None and _pname in kw:
                out.append(gen.lower_expr(kw.pop(_pname)))
                continue
            _dflt = (defaults or {}).get(_pname) if _pname else None
            out.append(gen._default_expr_to_pair(_dflt))
        out.append(gen._lower_varargs_pack(args[pre_n:]))
        # Post-star params are necessarily keyword-only (Python/Mojo
        # syntax). A `**kwargs` slot among them is a real MojoDict*
        # param — pack every keyword arg left unconsumed by the
        # pre-star binding above and by other named post-star params
        # into it (mirrors the non-varargs branch below), instead of
        # always leaving it null.
        for pname in param_names[pre_n:]:
            if pname.startswith('**'):
                continue
            out.append(gen.lower_expr(kw.pop(pname)) if pname in kw else ('int', '0'))
        if any(pn.startswith('**') for pn in param_names[pre_n:]):
            out.append(('MojoDict *', gen._pack_kwargs_dict(
                {_kn: gen.lower_expr(_kv) for _kn, _kv in kw.items()})))
        return out
    out = [gen.lower_expr(a) for a in args]
    # A `**kwargs` parameter is a concrete `MojoDict *` (see
    # _gen_struct_method's param loop), so literal keyword arguments at
    # the call site must be PACKED into a real dict. Otherwise the
    # zero-padding below filled that slot with `(MojoDict *)0` and every
    # `**kwargs` field read a null dict — the compiled-path half of the
    # `for fname in pat.fields:` failure (A5-BUG.md section 1).
    _kw_idx = -1
    for _i, _pn in enumerate(chosen['param_names']):
        if _pn.startswith('**'):
            _kw_idx = _i
            break
    for idx, pname in enumerate(chosen['param_names']):
        if pname not in kw:
            continue
        # A keyword binding past the last lowered positional arg must fill
        # every SKIPPED intermediate param with ITS OWN declared default,
        # not a blanket 0 — `Derived(b=99)` against `(a=1, b=2, c=3)` was
        # emitting a=0 (see CODEGEN_keyword_only_ctor_call_skips_earlier_
        # default.md). No-default params still fall back to 0 here via
        # _default_expr_to_pair(None).
        while len(out) <= idx:
            out.append(gen._default_expr_to_pair(
                (defaults or {}).get(chosen['param_names'][len(out)])))
        out[idx] = gen.lower_expr(kw[pname])
    if _kw_idx >= 0:
        _named = set(chosen['param_names'])
        _rest = {}
        for _kn in kw:
            if _kn not in _named:
                _rest[_kn] = gen.lower_expr(kw[_kn])
        while len(out) <= _kw_idx:
            out.append(gen._default_expr_to_pair(
                (defaults or {}).get(chosen['param_names'][len(out)])))
        out[_kw_idx] = ('MojoDict *', gen._pack_kwargs_dict(_rest))
    # Pad up to max_arity, but never past the real parameter count — for a
    # `*args` overload max_arity is `float('inf')` (which the varargs
    # branch above already `return`ed for, but `chosen['has_varargs']` can
    # read falsy on the self-hosted path so a varargs candidate can still
    # arrive here; an unguarded `while len(out) < inf` then never
    # terminated — a hard hang, e.g. `MOJO_NO_SHIM=1 ./mojoc --dump
    # fire_compiler.py`).
    _pn_count = len(chosen['param_names'])
    _max_ar = chosen['max_arity']
    while len(out) < _pn_count and len(out) < _max_ar:
        _dflt = (defaults or {}).get(chosen['param_names'][len(out)])
        out.append(gen._default_expr_to_pair(_dflt))
    return out

