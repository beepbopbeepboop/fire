"""Shared middle-end extracted from gimple_gen_calls.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _as_str, _sms_key
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

def _callable_value_symbol(gen, node, cxx: bool = False):
    """`(ctype, rvalue)` for `node` used as a CALLABLE VALUE — a reference
    to a function this compile knows the address of — or None when `node`
    is not such a reference.

    This is the one place that decides what "the function `f`" means as a
    bare C value, because two callers need exactly that answer and used to
    each answer `0` instead: `_default_expr_to_pair` (a parameter whose
    default IS a function — `def consume(root, *, walk=leaf)`) and
    `_lower_IdentExpr`'s own "C function name used as a value" arm. Both
    missing answers are the same crash: the padded/loaded value is a NULL
    function pointer that the body then CALLS, so `def apply_it(x, *,
    f=leaf): return f(x)` invoked as `apply_it("q")` compiled, linked,
    and died with SIGSEGV on `mojo_fnptr_call_1(NULL, ...)` — exit 139,
    no diagnostic, and the doc that recorded the *generator* instance of
    this shape (`bugs/hard/COMPILE_FAIL_Tools_c-analyzer_c_common_fsutil.md`)
    never saw it, because it is reachable from an ordinary `def` too.

    Two spellings, matching the two the corpus actually uses:
      * a bare name — this module's own `def`, or any transitively
        inlined imported module's (`from os import walk` / `import os as
        o; o.walk`). Membership is `func_return_types` (ordinary defs) OR
        `_generator_api` (a generator this compile already lowered to its
        `<base>_start` entry point).
      * `module.attr` — the same, for a name reached through an `import
        ... as m` / `from pkg import submod` alias.

    A name shadowed by a local, a module-level global, or a struct/class
    name is NOT a function reference (Python scoping decides that first),
    so those return None and the caller keeps its own behaviour.

    `cxx` selects the textual form only. Under `-fgimple` a bare function
    name is not a legal rvalue, so the value goes through the pre-declared
    `static void * _funcptr_<sym>` this codegen already uses for every
    other "function as a value" site (registered in
    `_funcptr_builtins_needed`; gen_module's own `_funcptr_target`
    redirects a generator's bare csym to `<base>_start` at emission time —
    see its docstring for why, which is the same reason `_funcptr_` is the
    right vehicle here). In the C++20-coroutine body there is no such
    restriction, so the address is spelled directly — against the
    REDIRECTED symbol, because `_funcptr_`'s statics live in the .c
    translation unit and are not visible from the separately-compiled .cpp.
    """
    _fname = None
    if isinstance(node, gimple_ctypes.IdentExpr):
        _fname = _as_str(node.name)
    elif (isinstance(node, gimple_ctypes.MemberExpr)
            and isinstance(node.obj, gimple_ctypes.IdentExpr)
            and _as_str(node.obj.name) in getattr(gen, 'imported_symbols', ())):
        _fname = _as_str(node.member)
    if not _fname:
        return None
    # A local shadows a module-level name, a global shadows a function of
    # the same name, and a struct/class name is a type, not a callable —
    # all three are decided by Python scoping before "is it a function?"
    # ever matters.
    if _fname in getattr(gen, 'var_types', ()) or \
            _fname in getattr(gen, '_global_var_types', ()) or \
            _fname in getattr(gen, 'struct_field_types', ()):
        return None
    _gen_api = getattr(gen, '_generator_api', None) or {}
    _is_gen = _fname in _gen_api
    if not _is_gen and _fname not in getattr(gen, 'func_return_types', ()):
        return None
    _c_name = gen._func_csym(_fname)
    if _fname in gen._c_names:
        _c_name = gen._c_names[_fname]
    _c_name = _as_str(_c_name)
    if cxx:
        # gen_module's `_funcptr_target` rule, reused rather than
        # restated: a supported compiled generator has NO ordinary C
        # definition under its bare csym (only `<base>_start/_resume/
        # _value/_destroy`), so the address that means "call this to get
        # the generator object" is `<base>_start`.
        _target = _c_name
        if _is_gen:
            _target = f"{_gen_api[_fname]['base']}_start"
        return ('void *', f'(void *){_target}')
    gen._funcptr_builtins_needed.add(_c_name)
    return ('void *', f'_funcptr_{_c_name}')


def _callable_default_generator(gen, default_node):
    """The generator's registration api when `default_node` names a
    compiled generator of THIS compile, else None.

    This is what makes a higher-order parameter's RESULT type knowable:
    `def walk_tree(root, *, walk=_walk_tree)` hands the body a callable
    whose only in-source value is a generator this compile already
    turned into a `MojoGenerator *` with a registered api (`base`,
    `value_ctype`, `tuple_slot_ctypes`), so `for f in walk(root)` has a
    real, static answer for how to drive and how to read the loop target
    — exactly the answer `_gen_for_generator_iter` uses for a DIRECT
    generator call. Returns None (and the consumer then keeps refusing /
    zero-iterating, unchanged) for every other default: an ordinary
    function, an unresolvable reference, a lambda, a local.

    The residual this trades away is stated at its one consumer
    (`_lower_fnptr_call`); it is the same residual `fn_returns_generator`
    already carries for a first-class generator value, and it is strictly
    smaller, because a default only names ONE callable while a returned
    value can come from any of several.
    """
    if not isinstance(default_node, gimple_ctypes.IdentExpr):
        return None
    _fname = _as_str(default_node.name)
    _api = (getattr(gen, '_generator_api', None) or {}).get(_fname)
    return _api


def _callable_param_generator_apis(gen, fn_node) -> dict:
    """`{param name: generator api}` for the parameters of `fn_node` whose
    declared default names a compiled generator of this compile. See
    `_callable_default_generator`; the keys are this FUNCTION's parameter
    names, so the result is per-function state and is reset in
    `_reset_func` alongside every other per-function map.
    """
    _out = {}
    _dflts = getattr(fn_node, 'param_defaults', None) or {}
    for _pn, _pann in (getattr(fn_node, 'params', None) or []):
        _pn = _as_str(_pn)
        if _pn.startswith('*'):
            continue
        _api = _callable_default_generator(gen, _dflts.get(_pn))
        if _api is not None:
            _out[_pn] = _api
    return _out


def _default_expr_to_pair(gen, _dflt, cxx: bool = False) -> tuple:
    """Convert a default-arg expression AST node to a (ctype, rvalue) pair,
    for padding a call site that omitted the argument. Mirrors the struct
    ctor default handling in _build_call_args_for_candidate.

    `cxx` = the caller is lowering into the C++20-coroutine body, which
    spells a callable value as a direct address rather than through the
    .c-side `_funcptr_` statics; see `_callable_value_symbol`.

    A default that is a FUNCTION (`def walk_tree(root, *, walk=_walk_tree)`,
    `Tools/c-analyzer/c_common/fsutil.py`'s whole higher-order-parameter
    idiom) used to fall off the end of this function and become `('int',
    '0')` — a NULL function pointer that the callee then CALLS, so every
    such call site compiled clean, linked, and took SIGSEGV at run time.
    `_callable_value_symbol` now answers it with the real address. A
    function reference this compile cannot resolve stays `('int', '0')`:
    that is the pre-existing documented convention for an unrepresentable
    default (and `None`/`False` legitimately lower to the same 0), so it
    is deliberately not made louder here — what changed is that every
    RESOLVABLE callable default stopped being indistinguishable from it.
    """
    if _dflt is None:
        return ('int', '0')
    _cv = _callable_value_symbol(gen, _dflt, cxx=cxx)
    if _cv is not None:
        return _cv
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
    # A `module.attr` default (`def probe(x, *, g=os.walk)`) is a reference to
    # something this compile cannot resolve: whether `os.walk` was translated
    # into this translation unit at all is a property of the whole import
    # closure, not of the expression. The `('int', '0')` fallthrough below
    # therefore delivered address 0, and a callee that CALLS the parameter
    # called through it — `mojo_fnptr_call_1((void *)0, x)` — a SIGSEGV with
    # exit 139 and no output. Padding 0 is the one answer that is always
    # available and always wrong.
    #
    # So: a stub address, armed with the name. The diagnostic is inside the
    # stub, so a callee that never calls the parameter is COMPLETELY
    # unaffected — no message, no behaviour change — and one that does gets a
    # greppable line and a 0 instead of a signal. That is the same
    # loud-but-continuing shape as `mojo_unsupported_iter`, and for the same
    # reason: continuing with the previous behaviour beats taking the process
    # down.
    #
    # Scoped to MemberExpr on purpose. A bare `IdentExpr` default
    # (`g=some_helper`) is NOT routed here: a module-level constant lowers to
    # an int64 and is indistinguishable at this point from a function, and 0
    # is already the right answer for a constant this compile could not see.
    if (isinstance(_dflt, gimple_ctypes.MemberExpr)
            and isinstance(_dflt.obj, gimple_ctypes.IdentExpr)):
        _nm = f'{_dflt.obj.name}.{_dflt.member}'
        _slit = gen._new_val('char *',
                             gen._intern_string(gimple_ctypes._c_escape(_nm)))
        gen._emit(f'  mojo_set_unavailable_callable_name ({_slit});')
        return ('void *', gen._new_val('void *', 'mojo_unavailable_callable_ptr ()'))
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

def user_dunder_repr_call(gen, struct_name: str, ctype: str, cval: str, prefer):
    """`char *` expression calling a struct RECEIVER'S OWN `__repr__` /
    `__str__`, or None when it defines neither (or the one it defines is not
    registered as returning `char *`).

    THE shared dunder lookup for both spellings that have one, so they
    cannot disagree about which dunder wins: `_repr_value` (`repr(x)`, `%r`)
    passes `('__repr__',)` and `_stringify_value` (`str(x)`, `%s`, and every
    f-string interpolation) passes `('__str__', '__repr__')` — CPython's own
    order for `str`, which prefers `__str__` and falls back to `__repr__`
    before the default object repr.

    `cval` is materialized as a local of `ctype` first, because the emitted
    NULL check needs it twice.

    Returns None rather than a fallback expression: the caller then keeps its
    OWN pre-existing lowering for the no-dunder case (the generated field
    dump, `mojo_repr_obj`), which is what makes this a strict improvement —
    it can only replace a wrong answer with a right one.

    Deliberately conservative, exactly as `_repr_value`'s own copy of this
    logic was: every condition is one "we know this is right" — a struct
    this compile registered, a method it actually emitted, a return type it
    actually registered as `char *` — and anything unproven falls through.
    """
    _have = gen._struct_method_names.get(struct_name) or ()
    _local = gen._ensure_local(ctype, cval)
    for _dunder in prefer:
        if _dunder not in _have:
            continue
        _csym = gen._struct_method_csym(struct_name, _dunder, '')
        if gen.func_return_types.get(_csym) != 'char *':
            continue
        _call = gen._call_expr('char *', _csym, [(ctype, _local)])
        # Same null semantics the generated field-dump has: a NULL object
        # reprs as "None" rather than crashing. Interned through
        # `_intern_string` because a bare `"None"` literal is not a GIMPLE
        # r-value (see its own docstring).
        _none = gen._intern_string('None')
        return gen._new_val('char *', f'({_local} ? {_call} : {_none})')
    return None
