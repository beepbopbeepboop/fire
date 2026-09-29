# Moved from gimple_gen_methods.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""Receiver-method dispatch lowering for the GIMPLE backend.

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
    _sms_key, _as_str,
)
import regex_compile
import mlir
import mojo.backend_gimple.emit_funcs as _ggf
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import gimple_codegen
import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.emit_calls as ggc

# Re-export shared helpers from mojo.middle.methods_shared via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.methods_shared import *  # noqa: F401,F403
from mojo.middle.methods_shared import (
    _SELFHOST_SIBLING_MODULE_PREFIXES, _as_str, _gmm_callexpr_node, _is_selfhost_sibling_alias, _sms_key
)

# Sentinel for "this api entry has no `receiver` key at all", so a
# missing key is distinguishable from a recorded empty string (which is a
# real, meaningful verdict: a @staticmethod generator method has no receiver).
# Same object identity the sibling consumer in cpp_core.py uses.
_MISSING = object()


# Module aliases bound in this compiler's own backend sources that name a
# sibling *implementation* module whose top-level functions are the former
# GimpleGen methods (see _selfhost_sibling_module_call). Any `import X as Y`
# in a `gimple*.py` file where X starts with one of these is in scope.
#
# `ownership_destruct` added after it was found missing here: without it,
# `gimple_gen_infra.py`'s `ownership_destruct.analyze_function(fn, {}, {})`
# call (a plain module-qualified free-function call) wasn't recognized as
# a self-host sibling call at all, so it fell through to the generic
# "call an unknown method on an unresolved-type receiver" path and got
# silently auto-stubbed (`int64_t.analyze_function() stubbed`) — a real,
# reproducible `make bootstrap` stage1-vs-stage2 divergence for every file
# with a local list/dict/set binding this analysis would otherwise flag as
# a destroy candidate (confirmed on t_list.mojo: stage1 emits `mojo_
# cleanup_push_list`/`mojo_list_free`/`mojo_cleanup_cancel_n`, stage2
# emits nothing, because the stubbed call always returns an empty set).
#
# `fire_compiler` added after the same gap hit `gimple_gen_coro.py`'s
# `import fire_compiler as N; N._as_str(...)` calls: not being a recognized
# sibling, they fell through to the same generic unresolved-receiver stub
# path, which mints a PER-CALL-SITE hash suffix from each call's locally
# inferred argument type instead of resolving to fire_compiler.py's one
# real `_as_str` definition. Two call sites inferring different argument
# types therefore emitted two DIFFERENT undeclared C symbols
# (`fire_compiler__as_str_d719e0` vs `..._9f63a2`, matching neither the
# real definition) — an implicit-int-declaration mismatch, then a
# pointer-from-int assignment, i.e. exactly the fake "overload" scheme
# hashing garbage where a plain sibling free-function call was needed.


def _gmm_as_str(x) -> str:
    """Same-module `str`-view identity helper (see gimple_gen_calls`
    `_ggc_as_str`). A dict comprehension over `node.kwargs`
    (`{k: v for k, v in node_kwargs}`) reads each kwarg NAME from a
    2-tuple via `mojo_list_get_int`, so `k` erases to int64_t and the
    key is stored as the pointer's decimal address unless re-viewed as
    `str` — which made `'do_imports' in kwarg_map` miss and silently
    default `gimple_codegen.compile_to_gimple(src, do_imports=True,
    filename=input_file)` to `(src, 0, "")` on the self-hosted path."""
    return x


def _gmm_sms_key(struct_name, method) -> str:
    """Same-module `str`-returning wrapper around the imported `_sms_key`
    (the `_gmm_as_str` pattern — see its docstring). A module-level call to
    the IMPORTED `fire_compiler._sms_key` has its `-> str` return type go
    UNRESOLVED, so the codegen types the result int64_t and the following
    `dict.get(...)` key-coercion (`_char_to_cstr`) rewrites it through
    `mojo_str_from_int(<pointer>)` — the key becomes the pointer's DECIMAL
    ADDRESS, never `"Struct_method"`, so `_struct_method_signatures` lookups
    miss and return the miss sentinel. Concretely:
    `_method_candidates = gen._struct_method_signatures.get(_sms_key(...))`
    got back 1, and `len(_method_candidates)` SIGSEGV'd in
    `mojo_list_len(0x1)`. A SAME-MODULE `-> str` function resolves, so the
    caller sees `char *` and passes the real key."""
    return _sms_key(struct_name, method)






def _resolve_class_attr_write_target(gen, target):
    """If `target` (a MemberExpr) is a class-level-attribute WRITE —
    `ClassName.ATTR = ...` / `ClassName.ATTR += ...`, optionally reached
    through one self-host sibling-module qualifier (e.g. `gimple_codegen.
    GimpleGen._cpp_kwfwd_counter`, `import gimple_codegen` then `.GimpleGen.
    _cpp_kwfwd_counter`) — return `(gtype, gname)` for its synthesized
    backing global, else None.

    Mirrors `_lower_MemberExpr`'s READ-side resolution (the sibling-alias
    qualifier strip, then the `_class_attrs` lookup) so a write lands on the
    exact same global a read of the same expression resolves to. Without
    this, `_gen_stmt_AssignStmt`/`_gen_stmt_AugAssignStmt`'s generic
    MemberExpr-write path lowers `target.obj` (here, the bare class
    reference `gimple_codegen.GimpleGen`, itself not a real value) as if it
    were a genuine struct-instance pointer, then writes `<garbage>-
    >_cpp_kwfwd_counter` — no hard GIMPLE rejection (the garbage base
    happens to already be an integer-shaped value), just a real, silent
    pointer<->int size-mismatch warning and a write that never reaches the
    real counter. Real repro: `gimple_cpp_core.py`'s `gimple_codegen.
    GimpleGen._cpp_kwfwd_counter += 1` under self-host compilation.
    """
    obj = target.obj
    if (isinstance(obj, gimple_ctypes.MemberExpr)
            and isinstance(obj.obj, gimple_ctypes.IdentExpr)
            and _is_selfhost_sibling_alias(gen, obj.obj.name)):
        # `_as_str`, not `isinstance(obj.member, str)`: `obj.member` is a
        # boxed AST field read, and the isinstance test is unreliable
        # self-hosted — it evaluated False, so `obj` became None and this
        # function returned None for exactly the case its own docstring
        # cites. The write then fell through to the generic MemberExpr
        # path, lowering the class ref `gimple_codegen.GimpleGen` as a
        # value (0, "class-as-value not modeled") and emitting
        # `_mojo_dispatch_setattr((void *)0, "_cpp_kwfwd_counter", old+1)`
        # — the counter never incremented (uid stayed 0) plus the real
        # "cast to pointer from integer of different size" warning at
        # `gimple_cpp_core.py:422` in a downstream GCC build.
        _cls_member = _as_str(obj.member)
        obj = gimple_ctypes.IdentExpr(name=_cls_member, line=getattr(target, 'line', 0)) \
            if _cls_member else None
    if not isinstance(obj, gimple_ctypes.IdentExpr):
        return None
    class_name = _as_str(obj.name)
    if class_name not in gen.struct_field_types or class_name in gen.var_types:
        return None
    cattrs = gen._class_attrs.get(_gmm_as_str(class_name))
    # `_as_str(target.member)` for the KEY: `target.member` is a boxed AST
    # field read, and a boxed pointer used as a dict key misses the
    # `_class_attrs` entry whose key is a real string — so this returned None
    # for a genuine class-attr write and the `+=` fell through to the generic
    # path (`_mojo_dispatch_setattr` on `target.obj`'s value — the counter's
    # int cast to `void *`, the "cast to pointer from integer of different
    # size" warning in a downstream GCC build).
    _member_s = _as_str(target.member)
    if not cattrs or _member_s not in cattrs:
        return None
    gname = cattrs[_member_s]
    gtype = gen._global_var_types.get(_gmm_as_str(gname), 'int64_t')
    return gtype, gname


def _selfhost_sibling_member_kind(gen, module_name: str, method_name: str):
    """`'func'` if `<module_name>.<method_name>` names a registered top-level
    function of a self-host sibling module, `'other'` if the alias is a
    self-host sibling but the member is something else (a re-exported struct /
    AST-node type, a constant, …), else None.

    When it's a self-host sibling alias the qualifier is ALWAYS a removable
    Python-import artifact, so both cases re-dispatch on the bare name — only
    the entry point into the bare-name machinery differs."""
    if not _is_selfhost_sibling_alias(gen, module_name):
        return None
    if (method_name in getattr(gen, 'func_param_types', {})
            or method_name in getattr(gen, 'func_return_types', {})):
        return 'func'
    return 'other'


def _lower_bound_method_value(gen, struct_name: str, method: str,
                               self_type: str, self_val: str) -> tuple[str, str]:
    """Lower a method referenced as a plain value (not called at this
    site): `f = self.b`, `readline.set_completer(self.complete)`.

    Produces a `MojoBoundMethod *` (runtime/fire_runtime.h) pairing the
    method's real C function pointer with the already-lowered `self`
    receiver, reusing the same static-void*-var mechanism `_lower_
    IdentExpr` already uses to take the address of a free function used
    as a value (GIMPLE forbids `&func_name` as an rvalue) — see the
    `func_return_types`/`BUILTIN_VALUE_MAP` branches above. A later call
    through the resulting value (`f(...)`) is lowered by
    _lower_bound_method_call, which re-supplies `self` as the method's
    implicit first argument.

    No call-site args exist yet at a bare-reference site, so overload
    resolution can't pick among candidates by arity/type — only the
    unambiguous case (a single overload) is resolved to its exact
    mangled symbol; anything else falls back to _struct_method_csym's
    own unsuffixed-name convention (matches its behavior for any other
    caller that has no candidate list to resolve against).

    Refuses (RuntimeError, the established "fall back to interpreting
    this module from source" convention — see e.g. the AwaitExpr
    RuntimeError a few hundred lines up) when `method` is itself a
    compiled GENERATOR method (registered in
    self._generator_method_api, Milestone C step 3): a generator
    method's real callable surface is 4 separate extern "C" functions,
    `<base>_start/_resume/_value/_destroy` (see
    _gen_cpp_generator_unit's docstring) — there is no ordinary
    `struct_method_csym`-mangled C function for it at all (gen_module's
    Phase 2a skips emitting one, see the `_supported_generator_methods`
    check there). Before this check, this method computed `mangled`
    via `_struct_method_csym` exactly as if it named an ordinary
    method, and unconditionally emitted `static void * _funcptr_
    {mangled} = (void *){mangled};` (via `_funcptr_builtins_needed`)
    referencing that never-emitted symbol -- a hard, confusing GCC
    "'<mangled>' undeclared here (not in a function)" failure at
    `-fgimple` compile time instead of a clean, honest refusal here.
    Real-world case: Lib/glob.py's `_GlobberBase.selector` does
    `return self.select_exists` (glob.py:399), a bare reference to
    the generator method `select_exists` (glob.py:534, itself `yield`s
    directly) as a plain VALUE, not a call — see
    bugs/CODEGEN_generator_function_Lib_glob.md. Even setting the
    undeclared-symbol crash aside, a `MojoBoundMethod*`'s own calling
    convention (`mojo_bound_method_call_N`, ONE call returning a
    single `int64_t`) has no way to represent "returns an iterable
    generator" at all -- correctly supporting this shape needs a new
    bound-method-value variant carrying the 4-function coroutine API
    through to a later call site, not just a declaration fix; out of
    scope for this narrow refusal.
    """
    if (struct_name, method) in gen._generator_method_api:
        raise RuntimeError(
            f"cannot compile module: `self.{method}` on struct "
            f"{struct_name!r} is a compiled GENERATOR method "
            "referenced as a plain value (not called here) -- a "
            "generator method's real callable surface is its "
            "`<base>_start/_resume/_value/_destroy` C++ coroutine "
            "API, which a MojoBoundMethod* (single-call, scalar-"
            "return) value can't represent -- falling back to "
            "interpreting this module from source instead")
    candidates = gen._struct_method_signatures.get(_gmm_sms_key(struct_name, method))
    overload_id = ''
    if candidates and len(candidates) == 1:
        overload_id = candidates[0].get('overload_id', '') or ''
    mangled = _gmm_as_str(_ggf._struct_method_csym(gen, struct_name, method, overload_id))
    ret_type = gen.func_return_types.get(
        _gmm_as_str(mangled), gen.func_return_types.get(f"{struct_name}_{method}", 'int64_t'))
    gen._funcptr_builtins_needed.add(mangled)
    static_name = f'_funcptr_{mangled}'
    fn_ptr = gen._new_val('void *', static_name)
    self_void = self_val if self_type == 'void *' else gen._new_val('void *', f'(void *){self_val}')
    t = gen._call_expr('MojoBoundMethod *', 'mojo_bound_method_new',
                         [('void *', fn_ptr), ('void *', self_void)])
    gen._bound_method_ret_types[t] = ret_type
    return 'MojoBoundMethod *', t


def _lower_builtin_method_value(gen, ot: str, ov: str, method: str) -> tuple[str, str]:
    """Lower a BUILTIN-CONTAINER method referenced as a plain value —
    `append = l.append` (python_mapdef_code's accumulator idiom in
    Tools/unicode/gencodec.py), `add = myset.add`, etc.

    Also covers `MojoBytes *` (bytes/bytearray) and `MojoMemoryView *`
    receivers — `append = result.append` on a bytearray held in a local
    (Lib/zipfile/__init__.py's `_ZipDecrypter.decrypter`).

    _lower_bound_method_value above covers USER-STRUCT methods only: a
    struct method has a real, statically-known mangled C symbol to take
    a function pointer of. A builtin container (MojoList*/MojoDict*/
    MojoSet*/MojoBytes*/MojoMemoryView*) has NO per-method C function at all — its methods are
    lowered inline at each direct call site (`mojo_list_append_int` vs
    `mojo_list_append_str` chosen by the ARGUMENT's type at that call),
    so there is nothing for a MojoBoundMethod*'s fn pointer to point at.
    Binding one therefore can't reuse the fn+self representation.

    What it CAN do is record the binding and lower every call THROUGH
    the value as a direct container-method call on the receiver:
    - the receiver pointer is materialized into its own hidden void*
      local ONCE here, so the bound value keeps pointing at the ORIGINAL
      list even if the source variable is rebound afterwards (Python
      aliasing semantics);
    - the value itself stays the established boxed-int64_t handle
      (exactly what the generic getattr fallback produced before), so
      variable declarations, coercions and ABI are all unchanged;
    - the (receiver ctype, hidden local, method name) triple rides in
      gen._builtin_method_values keyed by this temp's C name, propagated
      onto assigned variable names by the same side-table carry-through
      AssignStmt/VarDecl already do for _bound_method_ret_types;
    - a later call through such a var (_lower_builtin_bound_method_call)
      dispatches into _lower_list_method/_lower_dict_method/
      _lower_set_method verbatim — identical behavior and element-type
      tracking to spelling the call directly on the container.

    Uses of the value OTHER than calling it in the same function
    (returning it, storing it in a container, passing cross-function)
    keep today's opaque-handle behavior — unsupported there before,
    unchanged now."""
    recv = gen._new_val('void *', f'(void *){ov}')
    t = gen._new_temp('int64_t')
    gen._emit(f"  {t} = (int64_t){recv};")
    gen._builtin_method_values[t] = (ot, recv, method)
    return 'int64_t', t


def _lower_builtin_bound_method_call(gen, fname_raw: str,
                                     node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Call through a builtin-container method previously bound as a
    VALUE (`append = l.append; ...; append(x)`) — see
    _lower_builtin_method_value for why this can't go through the
    MojoBoundMethod* fn-pointer machinery. Dispatches to the exact same
    per-container lowering a direct `<recv>.<method>(...)` call uses, so
    argument typing (int vs str append), element-type propagation and
    return types all match the direct-call spelling exactly."""
    recv_ct, recv_v, method = gen._builtin_method_values[fname_raw]
    if recv_ct == 'MojoList *':
        return gen._lower_list_method(recv_v, method, node.args)
    if recv_ct == 'MojoDict *':
        return gen._lower_dict_method(recv_v, method, node.args)
    if recv_ct == 'MojoBytes *':
        return gen._lower_bytes_method(recv_v, method, node.args, node.kwargs)
    if recv_ct == 'MojoMemoryView *':
        return gen._lower_memoryview_method(recv_v, method, node.args, node.kwargs)
    return gen._lower_set_method(recv_v, method, node.args)


def _auto_invoke_bound_method_value(gen, bm_val: str) -> tuple[str, str]:
    """Auto-invoke a deferred, uncalled `MojoBoundMethod *` value (`ov`)
    and return the invoked result's (ctype, value) — the shared lowering
    for every direct-consumer context where real Python auto-invokes a
    bare 0-arg property/method read before using it (chained member
    access `self.prop.attr`, binary-operator operands `self.prop + x`,
    subscript reads `self.prop[key]`).

    `mojo_bound_method_call_0` always returns an int64_t-typed C value;
    the method's STATICALLY INFERRED return type (`_bound_method_ret_
    types`, recorded from func_return_types at bound-method construction)
    is what every other consumer of that inference sees. When the two
    disagree — most commonly an inferred plain 'int' (the unannotated-
    field/param default) against the int64_t call result — the claimed
    ctype MUST be materialized into its own correctly-typed temp via an
    explicit cast: claiming 'int' while handing callers the raw int64_t
    temp made every later use emit mismatched-operand GIMPLE (GCC:
    "type mismatch in binary expression", `int = int64_t + int64_t`;
    real repro Lib/pathlib/__init__.py's PurePath.anchor,
    `return self.drive + self.root`, both @property getters inferred
    'int' from their `_drv`/`_root` field defaults). 'int64_t' needs no
    temp (the call result already is one); 'void' degrades to a scalar
    0 like the pre-consolidation copies did.
    """
    ret_type = gen._bound_method_ret_types.get(bm_val, 'int64_t')
    raw_t = gen._call_expr('int64_t', 'mojo_bound_method_call_0',
                            [('MojoBoundMethod *', bm_val)])
    if ret_type == 'int64_t':
        return 'int64_t', raw_t
    if ret_type == 'void':
        return 'int', gen._new_val('int', '0')
    return ret_type, gen._new_val(ret_type, f'({ret_type}){raw_t}')


def _lower_struct_subscript_dunder(gen, ot: str, ov: str, method: str,
                                   arg_pairs: list) -> tuple[str, str] | None:
    """Dispatch `obj[key]` / `obj[key] = v` protocol on a USER-STRUCT
    instance to its own (or inherited, via the merged-methods view)
    `__getitem__` / `__setitem__` C method, with the arguments supplied
    as ALREADY-LOWERED (ctype, value) pairs so every call site keeps its
    existing single-evaluation guarantee (the surrounding statement
    lowering has usually already emitted code for the key/value exprs).

    Returns None when `ot` is not a known struct pointer or the class
    doesn't register that dunder — builtin containers (MojoList/
    MojoDict/MojoSet) never do, so their ordinary container branches are
    unaffected. Without this dispatch the struct-pointer fallbacks treat
    the instance itself as an array container (`_struct_data_field`
    pointer arithmetic) or degrade the read to an opaque int64_t handle;
    the latter is also a hard `-fgimple` error at any struct-valued
    element ("invalid types in nop conversion") and always silently-wrong
    semantics. Real: Lib/collections/__init__.py's `UserDict.get`
    (`return self[key]`) against UserDict's own `__getitem__`.
    """
    sn = gimple_exprtypes._struct_name_of(ot)
    cands = gen._struct_method_signatures.get(_gmm_sms_key(sn, method)) if sn else None
    if not (ot.endswith(' *') and sn in gen.struct_field_types and cands):
        return None
    chosen = None
    if len(cands) == 1:
        chosen = cands[0]
    else:
        n = len(arg_pairs)
        matching = [c for c in cands
                    if c.get('min_arity', 0) <= n <= c.get('max_arity')
                    if c.get('max_arity') is not None] or \
                   [c for c in cands if c.get('min_arity', 0) <= n]
        if len(matching) == 1:
            chosen = matching[0]
    overload_id = (chosen or {}).get('overload_id', '') or ''
    mangled = _gmm_as_str(_ggf._struct_method_csym(gen, sn, method, overload_id))
    ret_type = (chosen or {}).get('ret_type') or gen.func_return_types.get(
        _gmm_as_str(mangled), gen.func_return_types.get(f"{sn}_{method}", 'int64_t'))
    all_pairs = [(ot, ov)] + list(arg_pairs)
    if ret_type == 'void':
        gen._emit_call('void', '', mangled, all_pairs)
        if method == '__setitem__':
            # Statement-context store: the callers (AssignStmt/AugAssign
            # subscript-target branches) discard the pair wholesale.
            return 'void', ''
        # A subscript READ always yields a value in real Python — but a
        # raise-only `__getitem__` body (e.g. _collections_abc.Mapping's
        # abstract `raise KeyError`, whose inferred C signature correctly
        # collapses to `void`) gives this call no result to hand back.
        # Emitting `('void', '')` here made every value-consuming context
        # synthesize garbage C: a `void _tN;` temp plus an empty-RHS
        # assignment (`_tN = ;`) — "variable or field '_tN' declared
        # void" / "expected expression before ';' token", 22 errors in
        # _collections_abc.py alone (Mapping.get's `return self[key]`
        # inside try/except, MutableMapping.update, Sequence indices...).
        # Return a typed zero placeholder instead: unreachable at runtime
        # (the callee raises first), valid C everywhere.
        zero = gen._new_val('int64_t', '0')
        return 'int64_t', zero
    t = gen._call_expr(ret_type, mangled, all_pairs)
    if mangled in gen._return_elem_types:
        gen._elem_types[t] = gen._return_elem_types[mangled]
    return ret_type, t


def _lower_bound_method_call(gen, fname_raw: str, node: gimple_ctypes.CallExpr,
                              stored_ctype: str = 'MojoBoundMethod *') -> tuple[str, str]:
    """Call a `MojoBoundMethod *` value (see _lower_bound_method_value):
    `f = self.b; ...; f()`. Mirrors _lower_fnptr_call's runtime-helper
    indirection (GIMPLE can't cast-and-call in one expression), but
    through mojo_bound_method_call_N, which re-supplies the bound `self`
    as the method's implicit first argument.

    `stored_ctype` is `fname_raw`'s own declared C type — usually
    `MojoBoundMethod *` directly, but the var-type-inference pre-pass can
    default an assigned-from variable to `int64_t` (boxing the pointer,
    same convention every other unfamiliar struct pointer gets in this
    codegen); recover the real pointer through the same int64_t->void*->
    real-type cast dance `_lower_MemberExpr`'s object-lowering path uses
    for the identical situation.
    """
    bm_raw = gen._c_names.get(fname_raw, fname_raw)
    if stored_ctype == 'MojoBoundMethod *':
        bm_type, bm = 'MojoBoundMethod *', bm_raw
    else:
        ip = gen._ensure_local(stored_ctype, bm_raw)
        vp = gen._new_val('void *', f'(void *){ip}')
        bm = gen._new_val('MojoBoundMethod *', f'(MojoBoundMethod *){vp}')
    ret_type = gen._bound_method_ret_types.get(fname_raw, 'int64_t')
    return gen._lower_bound_method_call_value(bm, node, ret_type)


def _lower_maybe_bound_call(gen, fname_raw: str,
                            node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Call through a local that may hold EITHER a `MojoBoundMethod *` or a
    plain function pointer (see _assign_target's `_bm_tainted_locals`).
    Emits `mojo_maybe_bound_call_N`, which checks the runtime bound-method
    registry: a registered `MojoBoundMethod *` dispatches through
    `mojo_bound_method_call_N` (re-supplying `self`), anything else
    through `mojo_fnptr_call_N`. GIMPLE can't cast-and-call in one
    expression, hence the runtime helper — same indirection style as
    _lower_fnptr_call / _lower_bound_method_call."""
    fp_raw = gen._c_names.get(fname_raw, fname_raw)
    if fname_raw in gen._captures and gen._env_param:
        _t, fp_raw = gen.lower_expr(gimple_ctypes.IdentExpr(name=fname_raw))
    elif fname_raw not in gen.var_types and fname_raw in gen._global_var_types:
        _t, fp_raw = gen.lower_expr(gimple_ctypes.IdentExpr(name=fname_raw))
    fp_void = gen._new_val('void *', f'(void *){fp_raw}')
    widened = []
    for a in node.args:
        at, av = gen.lower_expr(a)
        widened.append(av if at == 'int64_t' else gen._new_val('int64_t', f'(int64_t){av}'))
    n = len(widened)
    helper = f'mojo_maybe_bound_call_{min(n, 4)}'
    ret_type = gen._bound_method_ret_types.get(fname_raw, 'int64_t')
    raw_t = gen._call_expr('int64_t', helper, [('void *', fp_void)] +
                             [('int64_t', w) for w in widened[:4]])
    if ret_type in ('int64_t', 'int'):
        return ret_type, raw_t
    if ret_type == 'void':
        return 'int', gen._new_val('int', '0')
    t = gen._new_val(ret_type, f'({ret_type}){raw_t}')
    return ret_type, t


def _lower_bound_method_call_value(gen, bm: str, node: gimple_ctypes.CallExpr,
                                    ret_type: str = 'int64_t') -> tuple[str, str]:
    """Emit a call through an already-lowered `MojoBoundMethod *` VALUE
    (`bm`), the value-based twin of _lower_bound_method_call (shared so
    an arbitrary callable VALUE — `make_adder2(100)(2)`'s inner call
    result, `f = self.b; f()` — dispatches through the same runtime
    helper). `mojo_bound_method_call_N` re-supplies `bm->self` as the
    lifted function's implicit first argument (the captured env / bound
    receiver)."""
    # Unpack `lower_expr`'s `tuple[str, str]` return DIRECTLY per arg,
    # not `for at, av in [<comprehension>]` — a nested unpack over a list
    # comprehension of tuple-returning calls boxes both slots on the
    # self-hosted path, so `f'(int64_t){av}'` stringified the boxed `av`
    # pointer (`add5(37)` -> `(int64_t)41453655152` instead of
    # `(int64_t)37`).
    widened = []
    for a in node.args:
        at, av = gen.lower_expr(a)
        widened.append(av if at == 'int64_t' else gen._new_val('int64_t', f'(int64_t){av}'))
    n = len(widened)
    helper = f'mojo_bound_method_call_{min(n, 4)}'
    raw_t = gen._call_expr('int64_t', helper, [('MojoBoundMethod *', bm)] +
                             [('int64_t', w) for w in widened[:4]])
    if ret_type in ('int64_t', 'int'):
        return ret_type, raw_t
    if ret_type == 'void':
        return 'int', gen._new_val('int', '0')
    t = gen._new_val(ret_type, f'({ret_type}){raw_t}')
    return ret_type, t


# The two `struct.Struct` attributes that are DATA, not methods — name mapped
# to the Python type CPython's "not callable" message names for its value.
# See _lower_struct_attr_call, which is the only consumer.
_STRUCT_FMT_DATA_ATTRS = {'format': 'str', 'size': 'int'}


def _struct_value_codes(fmt: str | None):
    """The per-VALUE format codes of a const-foldable struct format string
    ('4h' -> ['h','h','h','h'], 'x' padding dropped, '10s' -> ['s']), or
    None if the format isn't statically known. Used to pick the right
    MojoList append (int vs double vs bytes-pointer) per argument and the
    element type of an unpack result."""
    if not isinstance(fmt, str):
        return None
    codes = []
    i, n = 0, len(fmt)
    if i < n and fmt[i] in '<>=!@':
        i += 1
    while i < n:
        c = fmt[i]
        if c in ' \t\n':
            i += 1
            continue
        count = None
        if c.isdigit():
            count = 0
            while i < n and fmt[i].isdigit():
                count = count * 10 + int(fmt[i]); i += 1
            if i >= n:
                return None
            c = fmt[i]
        i += 1
        if c not in 'xbBhHiIlLqQfds?c':
            return None
        if c in 'sc':
            codes.append('s')
        elif c == 'x':
            continue
        else:
            codes.extend([c] * (1 if count is None else count))
    return codes


def _struct_slot_kinds(codes):
    """Per-slot element kind for an unpack format: one of 'int'/'double'/
    'bytes' per value, in wire order.

    A `MojoList` holds ONE element ctype, which is why a format mixing ints
    and floats used to degrade wholesale to int64 slots — the float came
    back as its raw IEEE bits (`struct.unpack('<if', ...)` giving
    `1 4607182418800017408`). But the format string is a compile-time
    constant here, so each slot's real kind is statically known and only
    the CONTAINER is untyped. Recording the per-slot kinds lets every
    statically-indexed read of the result pick the right accessor for that
    slot: the subscript (emit_calls.py's MojoList branch), the `a, b = t`
    destructuring target (loops_shared._tuple_elem_value), and the
    whole-result repr (`_list_repr_fn` -> `mojo_repr_list_kinds`). It is a
    property of the VALUE, not of whether it was bound to a local; a read
    with no compile-time slot index (iteration, a computed subscript) still
    has no single right C type, which is the residue named in
    bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md.
    """
    out = []
    for c in codes or ():
        if c in 'fd':
            out.append('double')
        elif c == 's' or c == 'c':
            out.append('bytes')
        else:
            out.append('int')
    return out


def _struct_elem_ctype(codes):
    """Uniform MojoList element ctype for an unpack tuple, or 'int64_t'
    when the codes are mixed / unknown (the common integer-format case is
    exact; a genuinely mixed int+float format degrades to int64 slots).

    That degradation is now confined to reads with no compile-time slot
    index: `_struct_slot_kinds` carries the real per-slot kinds, and the
    subscript, the `a, b = t` destructuring target and the whole-result repr
    all consult it. See
    bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md."""
    if not codes:
        return 'int64_t'
    kinds = set()
    for c in codes:
        if c in 'fd':
            kinds.add('double')
        elif c == 's':
            kinds.add('bytes')
        else:
            kinds.add('int')
    if kinds == {'double'}:
        return 'double'
    if kinds == {'bytes'}:
        return 'MojoBytes *'
    return 'int64_t'


def _struct_build_value_list(gen, arg_nodes, codes):
    """Lower `arg_nodes` into a fresh MojoList* suitable for
    mojo_struct_pack_list / mojo_struct_pack_h. `codes` (may be None)
    drives per-field coercion when the format is statically known."""
    lst = gen._new_val('MojoList *', 'mojo_list_new ()')
    if any(isinstance(a, UnaryOp) and a.op in ('*', '**') for a in arg_nodes):
        codes = None   # a splat arg makes the per-index code mapping meaningless
    for idx, a in enumerate(arg_nodes):
        if isinstance(a, UnaryOp) and a.op in ('*', '**'):
            # `struct.pack(fmt, a, *rest)` — extend from the iterable's raw
            # int64 slots (struct splat args are ints in practice:
            # zipfile `_write_end_record`'s `*extra`).
            _it, _iv = gen.lower_expr(a.operand)
            _ip = (gen._ensure_local('MojoList *', _iv) if _it == 'MojoList *'
                   else gen._coerce_to_type('int64_t', 'MojoList *', gen._to_int64(_it, _iv)))
            gen._emit_call('void', '', 'mojo_list_extend', [('MojoList *', lst), ('MojoList *', _ip)])
            continue
        at, av = gen.lower_expr(a)
        code = codes[idx] if (codes is not None and idx < len(codes)) else None
        want_bytes = (code == 's') or (code is None and at in ('char *', 'MojoBytes *'))
        want_double = (code in ('f', 'd')) or (code is None and at in ('double', 'float'))
        if want_bytes:
            if at == 'MojoBytes *':
                bp = gen._ensure_local('MojoBytes *', av)
            elif at == 'char *':
                bp = gen._call_expr('MojoBytes *', 'mojo_bytes_from_cstr', [('char *', av)])
            else:
                vp = gen._new_val('void *', f'(void *){av}')
                bp = gen._coerce_to_type('void *', 'MojoBytes *', vp)
            cp = gen._new_val('char *', f'(char *){bp}')
            gen._emit_call('void', '', 'mojo_list_append_str', [('MojoList *', lst), ('char *', cp)])
        elif want_double:
            gen._emit_call('void', '', 'mojo_list_append_double', [('MojoList *', lst), ('double', av)])
        else:
            gen._emit_call('void', '', 'mojo_list_append_int', [('MojoList *', lst), ('int64_t', av)])
    return lst


# ── `struct` argument binding: which parameters may arrive BY NAME ──────────
#
# `struct`'s call surface is POSITIONAL-ONLY, with three exceptions. This
# table is a MEASUREMENT of CPython 3.14, not an inference from the docs: every
# candidate name below was passed to the real module and to a real
# `struct.Struct` instance, and only the three rows with a non-empty `kw` came
# back without a TypeError. Getting this wrong is not cosmetic in either
# direction — the omission this replaces read `node.args` and never looked at
# `node.kwargs` at all, so `struct.unpack_from(fmt, buf, offset=2)` ran with
# offset 0 and returned well-formed data read from the WRONG PLACE, and
# `struct.calcsize(fmt='<HH')` returned 0 where CPython raises
# (bugs/hard/CODEGEN_struct_kwargs_and_inline_unpack.md).
#
# Per entry point:
#   kw       parameter name -> its positional index. A name absent from this
#            map is rejected with CPython's own message (see _struct_bind_args).
#   pos      the leading parameter names, in order (only used to name a
#            required parameter that a keyword left unfilled).
#   req      how many leading parameters are REQUIRED.
#   posonly  how many of those required leading parameters are
#            POSITIONAL-ONLY. This is why `struct.unpack_from` can accept
#            `offset=` but not `format=`: format is positional-only there, so
#            leaving it to a keyword reports "takes at least 1 positional
#            argument" rather than binding.
#   msg      the name CPython puts in its own message. Not derivable: the
#            module functions are `_struct.calcsize`/`_struct.pack`/... but
#            BOTH `unpack_from`s report as bare `unpack_from()`, because
#            `Struct.unpack_from` is the same C function reached through a
#            bound method.
_STRUCT_CALL_SIGS = {
    'calcsize':           {'kw': {}, 'pos': ('format',), 'req': 1, 'posonly': 1,
                          'msg': '_struct.calcsize'},
    'pack':               {'kw': {}, 'pos': ('format',), 'req': 1, 'posonly': 1,
                          'msg': '_struct.pack'},
    'unpack':             {'kw': {}, 'pos': ('format', 'buffer'), 'req': 2, 'posonly': 2,
                          'msg': '_struct.unpack'},
    'unpack_from':        {'kw': {'buffer': 1, 'offset': 2},
                          'pos': ('format', 'buffer', 'offset'), 'req': 2, 'posonly': 1,
                          'msg': 'unpack_from'},
    'iter_unpack':        {'kw': {}, 'pos': ('format', 'buffer'), 'req': 2, 'posonly': 2,
                          'msg': '_struct.iter_unpack'},
    'pack_into':          {'kw': {}, 'pos': ('format', 'buffer', 'offset'),
                          'req': 3, 'posonly': 3, 'msg': '_struct.pack_into'},
    'Struct':             {'kw': {'format': 0}, 'pos': ('format',), 'req': 1, 'posonly': 0,
                          'msg': 'Struct'},
    'Struct.pack':        {'kw': {}, 'pos': (), 'req': 0, 'posonly': 0,
                          'msg': 'Struct.pack'},
    'Struct.unpack':      {'kw': {}, 'pos': ('buffer',), 'req': 1, 'posonly': 1,
                          'msg': 'Struct.unpack'},
    'Struct.unpack_from': {'kw': {'buffer': 0, 'offset': 1},
                          'pos': ('buffer', 'offset'), 'req': 1, 'posonly': 0,
                          'msg': 'unpack_from'},
    'Struct.pack_into':   {'kw': {}, 'pos': ('buffer', 'offset'), 'req': 2, 'posonly': 2,
                          'msg': 'Struct.pack_into'},
}

# The never-taken value a `mojo_raise_type_error` call site hands back: a
# zero of whatever ctype the entry point's return type is, which is every
# ctype in `_STRUCT_MODULE_FN_RETVALS` plus the instance methods' `int`. A
# bare `0` initializes all of them, pointer temps included (C's null-pointer
# constant), so one entry covers the whole set.
_STRUCT_RAISE_STUB = '0'


def _struct_kwarg_rejection(sig, key, kw_name, npos, nkw):
    """CPython's TypeError text for a keyword `struct` call cannot accept.

    Which shape applies is decided by the ENTRY POINT, not by the name: an
    entry point with no nameable parameter at all is arg-clinic's
    `_struct.calcsize() takes no keyword arguments`, the two `unpack_from`s
    are hand-written FASTCALL|KEYWORDS C functions that name the offending
    keyword, and `struct.Struct` is arg-clinic over a single `format`
    parameter, whose first check is the total argument COUNT — so an unknown
    name there is reported as an overflow, never as an unknown keyword.
    """
    if not sig['kw']:
        return f"{sig['msg']}() takes no keyword arguments"
    if key == 'Struct':
        # `format` supplied positionally makes it a positional-argument
        # count; supplied by keyword (or absent) it is a keyword count.
        if npos:
            return f'Struct() takes at most 1 argument ({npos + nkw} given)'
        return f'Struct() takes at most 1 keyword argument ({nkw} given)'
    return f"{sig['msg']}() got an unexpected keyword argument '{kw_name}'"


def _struct_missing_required(sig, slots, npos):
    """CPython's TypeError text for a required parameter left unfilled, or
    None. A parameter that is POSITIONAL-ONLY and unfilled cannot be named,
    so CPython reports the whole call as short of positionals instead
    (`unpack_from() takes at least 1 positional argument (0 given)`); one
    that could have arrived by name is named outright (`unpack_from() missing
    required argument 'buffer' (pos 1)`)."""
    first_empty = 0
    while first_empty < len(slots) and slots[first_empty] is not None:
        first_empty += 1
    if first_empty >= sig['req']:
        return None
    if first_empty < sig['posonly']:
        plural = '' if sig['posonly'] == 1 else 's'
        return (f"{sig['msg']}() takes at least {sig['posonly']} positional "
                f"argument{plural} ({npos} given)")
    return (f"{sig['msg']}() missing required argument "
            f"'{sig['pos'][first_empty]}' (pos {first_empty + 1})")


def _struct_bind_args(node, key):
    """Bind a `struct` call's arguments into CPython's positional order.

    Returns `(slots, err)`: `slots[i]` is the expression node bound to
    positional parameter `i` (None where nothing was supplied), and `err` is
    CPython's TypeError text, or None when the call binds.

    Arguments are bound positionals-first and then keywords-by-name, because
    that is the order in which Python both evaluates the argument expressions
    and fills the parameters — so a rejected call still runs its arguments'
    side effects, which is what `_lower_struct_attr_call` already does for the
    same reason.

    The ORDER the three possible errors are reported in is CPython's, not
    this function's convenience, and it is measurable: an entry point with no
    nameable parameter refuses every keyword before anything else is
    examined (that is where `struct.unpack(fmt=..., buffer=...)` gets "takes
    no keyword arguments" rather than a complaint about a format it never
    received), while on `unpack_from` an unfilled REQUIRED parameter outranks
    an unknown keyword (`s.unpack_from(offset=2, bogus=1)` reports the missing
    `buffer`). A keyword that names an already-filled slot is third.

    Only the errors a KEYWORD can cause are reported. A purely positional call
    that is short an argument keeps reaching the lowerings below and fails
    there, exactly as it did before: CPython's own text for those is a
    different string per entry point ("unpack expected 2 arguments, got 1",
    "missing format argument", "pack_into expected offset argument"), and
    reproducing that catalogue is not what the keyword bug was about. The one
    exception is a required parameter left empty *by* a keyword, which is this
    function's own doing and is therefore its own message.
    """
    sig = _STRUCT_CALL_SIGS[key]
    npos = len(node.args)
    slots = list(node.args)
    kws = list(getattr(node, 'kwargs', None) or [])
    if kws and not sig['kw']:
        return slots, f"{sig['msg']}() takes no keyword arguments"
    if kws and key == 'Struct' and npos + len(kws) > 1:
        # `struct.Struct` takes at most ONE argument, and its binder checks
        # that COUNT before it looks at any name — so a second argument is
        # the same "takes at most 1 ..." message whether it is a positional,
        # a second keyword, or `format` supplied twice.
        return slots, _struct_kwarg_rejection(sig, key, kws[0][0], npos, len(kws))
    unknown = None
    conflict = None
    for kwname, kwexpr in kws:
        if kwname not in sig['kw']:
            if unknown is None:
                unknown = kwname
            continue
        i = sig['kw'][kwname]
        while len(slots) <= i:
            slots.append(None)
        if slots[i] is not None:
            if conflict is None:
                conflict = (kwname, i + 1)
            continue
        slots[i] = kwexpr
    err = _struct_missing_required(sig, slots, npos)
    if err is None:
        if conflict is not None:
            err = (f"argument for {sig['msg']}() given by name "
                   f"('{conflict[0]}') and position ({conflict[1]})")
        elif unknown is not None:
            err = _struct_kwarg_rejection(sig, key, unknown, npos, len(kws))
    return slots, err


def _struct_bind_or_raise(gen, node, key, rtype):
    """`_struct_bind_args`, with a rejected call turned into the CPython
    exception at RUNTIME.

    A call-arity error is a runtime raise, not a codegen error: real Python
    raises it while binding, and the surrounding program is expected to catch
    it (`try: struct.calcsize(fmt=f) except TypeError:`), which a codegen-time
    abort could not express. `mojo_raise` longjmps, so the zero this returns
    is only ever read on a path that cannot be reached — it exists so the
    enclosing expression still typechecks, the same convention
    `_lower_struct_attr_call` uses.
    """
    slots, err = _struct_bind_args(node, key)
    if err is None:
        return slots, None
    for a in node.args:
        gen.lower_expr(a)
    for _k, v in (getattr(node, 'kwargs', None) or []):
        gen.lower_expr(v)
    gen._emit_call('void', '', 'mojo_raise_type_error',
                   [('char *', gen._intern_string(gimple_ctypes._c_escape(err)))])
    return slots, gen._stub_result(rtype, _STRUCT_RAISE_STUB,
                                   f'struct {key} — {err}')


def _struct_buffer_arg(gen, node_arg):
    """Lower a struct unpack/pack_into buffer argument to a MojoBytes*."""
    bt, bv = gen.lower_expr(node_arg)
    if bt == 'MojoBytes *':
        return gen._ensure_local('MojoBytes *', bv)
    if bt == 'char *':
        return gen._call_expr('MojoBytes *', 'mojo_bytes_from_cstr', [('char *', bv)])
    if bt == 'MojoMemoryView *':
        return gen._call_expr('MojoBytes *', 'mojo_memoryview_tobytes', [('MojoMemoryView *', bv)])
    vp = gen._new_val('void *', f'(void *){bv}')
    return gen._coerce_to_type('void *', 'MojoBytes *', vp)


def _struct_tag_unpack_result(gen, t, codes):
    gen._actual_types[t] = 'MojoList *'
    gen._elem_types[t] = _struct_elem_ctype(codes)
    # Per-slot kinds, so a format that mixes ints and floats still reads
    # each slot with the right accessor (see _struct_slot_kinds). Recorded
    # for EVERY format, not just mixed ones: it is the precise answer, and
    # it costs one dict write.
    kinds = _struct_slot_kinds(codes)
    if kinds:
        gen._struct_slot_kinds[t] = kinds


def _lower_struct_module_call(gen, node, method_name):
    """`struct.<fn>(...)` module-level call lowering (Stage 1/2/3).

    Every `return` below yields the C type this codegen assigns to the call's
    VALUE, taken from `gimple_ctypes._STRUCT_MODULE_FN_RETVALS` rather than
    spelled out again: the type estimator `_quick_type` consults the same table
    to write the enclosing function's PROTOTYPE, and a prototype the body must
    box its real value to satisfy is how a returned `MojoStructFmt *` used to
    arrive at its consumers as an `int64_t` (and `s.size` with it). One table,
    both sides, no second place to forget to update.
    """
    _RT = gimple_ctypes._STRUCT_MODULE_FN_RETVALS
    rtype = _RT[method_name]
    # Bind positionals and keywords BEFORE touching `args`: a keyword the
    # entry point does not accept is CPython's TypeError, and the arguments
    # must still have been evaluated when it is raised.
    args, raised = _struct_bind_or_raise(gen, node, method_name, rtype)
    if raised is not None:
        return raised
    if method_name == 'Struct':
        st, sv = gen.lower_expr(args[0])
        if st != 'char *':
            sv = gen._new_val('char *', f'(char *){sv}')
        t = gen._call_expr(rtype, 'mojo_struct_new', [('char *', sv)])
        # Remember a const-foldable format against the handle it produced, so
        # the INSTANCE methods can recover the same per-slot kinds the module
        # functions read straight off their own format argument (see
        # _lower_struct_instance_method).
        _sfmt = gen._try_const_fold_str(args[0])
        if _sfmt is not None:
            gen._struct_formats[t] = _sfmt
        return rtype, t

    fmt_node = args[0]
    fmt_codes = _struct_value_codes(gen._try_const_fold_str(fmt_node))
    ft, fv = gen.lower_expr(fmt_node)
    if ft != 'char *':
        fv = gen._new_val('char *', f'(char *){fv}')

    if method_name == 'calcsize':
        return _RT['calcsize'], gen._call_expr(_RT['calcsize'], 'mojo_struct_calcsize', [('char *', fv)])

    if method_name == 'pack':
        lst = _struct_build_value_list(gen, args[1:], fmt_codes)
        return _RT['pack'], gen._call_expr(_RT['pack'], 'mojo_struct_pack_list',
                                           [('char *', fv), ('MojoList *', lst)])

    if method_name in ('unpack', 'unpack_from', 'iter_unpack'):
        buf = _struct_buffer_arg(gen, args[1])
        if method_name == 'unpack_from' and len(args) >= 3:
            ot, ov = gen.lower_expr(args[2])
            off = gen._new_val('int64_t', f'(int64_t){ov}') if ot != 'int64_t' else ov
            t = gen._call_expr(_RT['unpack_from'], 'mojo_struct_unpack_from',
                               [('char *', fv), ('MojoBytes *', buf), ('int64_t', off)])
        elif method_name == 'unpack_from':
            zero = gen._new_val('int64_t', '(int64_t)0')
            t = gen._call_expr(_RT['unpack_from'], 'mojo_struct_unpack_from',
                               [('char *', fv), ('MojoBytes *', buf), ('int64_t', zero)])
        else:
            t = gen._call_expr(_RT[method_name], 'mojo_struct_unpack',
                               [('char *', fv), ('MojoBytes *', buf)])
        _struct_tag_unpack_result(gen, t, fmt_codes)
        return _RT[method_name], t

    if method_name == 'pack_into':
        buf = _struct_buffer_arg(gen, args[1])
        ot, ov = gen.lower_expr(args[2])
        off = gen._new_val('int64_t', f'(int64_t){ov}') if ot != 'int64_t' else ov
        lst = _struct_build_value_list(gen, args[3:], fmt_codes)
        gen._emit_call('void', '', 'mojo_struct_pack_into',
                       [('char *', fv), ('MojoBytes *', buf), ('int64_t', off), ('MojoList *', lst)])
        return _RT['pack_into'], gen._new_val(_RT['pack_into'], '0')

    raise RuntimeError(f'struct.{method_name}: unsupported')


def _lower_struct_instance_method(gen, fmt_val, method, node):
    """`s.<method>(...)` where `s` holds a `MojoStructFmt *` (struct.Struct)."""
    rtype = {'pack': 'MojoBytes *', 'unpack': 'MojoList *', 'unpack_from': 'MojoList *',
             'iter_unpack': 'MojoList *', 'pack_into': 'int'}[method]
    # Same keyword binding as the module functions, against the `Struct.*`
    # rows of _STRUCT_CALL_SIGS: `s.unpack_from(buf, offset=2)` is a real
    # CPython call whose offset used to be dropped, so the unpack read offset
    # 0 and returned a well-formed tuple of the wrong fields.
    args, raised = _struct_bind_or_raise(gen, node, f'Struct.{method}', rtype)
    if raised is not None:
        return raised
    fp = gen._ensure_local('MojoStructFmt *', fmt_val)
    if method == 'pack':
        lst = _struct_build_value_list(gen, args, None)
        return rtype, gen._call_expr(rtype, 'mojo_struct_pack_h',
                                     [('MojoStructFmt *', fp), ('MojoList *', lst)])
    if method in ('unpack', 'unpack_from', 'iter_unpack'):
        buf = _struct_buffer_arg(gen, args[0])
        if method == 'unpack_from' and len(args) >= 2:
            ot, ov = gen.lower_expr(args[1])
            off = gen._new_val('int64_t', f'(int64_t){ov}') if ot != 'int64_t' else ov
            t = gen._call_expr(rtype, 'mojo_struct_unpack_from_h',
                               [('MojoStructFmt *', fp), ('MojoBytes *', buf), ('int64_t', off)])
        elif method == 'unpack_from':
            zero = gen._new_val('int64_t', '(int64_t)0')
            t = gen._call_expr(rtype, 'mojo_struct_unpack_from_h',
                               [('MojoStructFmt *', fp), ('MojoBytes *', buf), ('int64_t', zero)])
        else:
            t = gen._call_expr(rtype, 'mojo_struct_unpack_h',
                               [('MojoStructFmt *', fp), ('MojoBytes *', buf)])
        # The instance's format is only known at RUNTIME (it lives in the
        # compiled MojoStructFmt), so the per-slot kinds come from the
        # const-folded format recorded when this handle was built — the
        # same answer the module functions get for free, and the difference
        # between `s.unpack(buf)` reading a mixed format's float slot as its
        # IEEE-754 bits and reading it as a float.
        _struct_tag_unpack_result(
            gen, t, _struct_value_codes(gen._struct_formats.get(fmt_val)))
        return rtype, t
    if method == 'pack_into':
        buf = _struct_buffer_arg(gen, args[0])
        ot, ov = gen.lower_expr(args[1])
        off = gen._new_val('int64_t', f'(int64_t){ov}') if ot != 'int64_t' else ov
        lst = _struct_build_value_list(gen, args[2:], None)
        gen._emit_call('void', '', 'mojo_struct_pack_into_h',
                       [('MojoStructFmt *', fp), ('MojoBytes *', buf), ('int64_t', off), ('MojoList *', lst)])
        return rtype, gen._new_val(rtype, '0')
    raise RuntimeError(f'struct.Struct.{method}: unsupported')


# `struct.Struct`'s instance namespace is CLOSED, and this codegen models all
# of it, so a member call on a `MojoStructFmt *` receiver that is not one of
# the five pack/unpack methods is not "unknown" — it is a determinate error
# with a determinate exception, and this is the only place that can say which.
#
# Two shapes, and the split is real Python's, not a guess:
#
#   * `format` and `size` are DATA attributes. In CPython both are
#     getset_descriptors on the type (`struct.Struct.format` is the format
#     STRING, `struct.Struct.size` the computed byte count) — there is no
#     `Struct.format()` method for either to shadow, and the struct module
#     has no formatting entry point at all, so reading one is a `str`/`int`
#     and CALLING one is `TypeError: '<type>' object is not callable`. The
#     READ half is already correct and routed to `mojo_struct_format` /
#     `mojo_struct_size` (see emit_exprs.py's `MojoStructFmt *` +
#     ('size', 'format') attribute case); this is the call half of the same
#     fact.
#   * any other name is not an attribute of the type at all, so it is an
#     `AttributeError` — the same answer `mojo_obj_getattr` already gives on
#     a miss (see fire_runtime.c's mojo_raise_attribute_error).
#
# Before this, the caller's method-name whitelist let both shapes escape to
# the generic receiver dispatch, where they landed in one of two wrong
# places depending on nothing more than the spelling of the name:
#
#   * `format` is in the container-method name list further down in
#     `_lower_method_call`, so `s.format(70)` emitted
#     `mojo_obj_call1(handle, "format", 70)` — a runtime function that is a
#     documented hardcoded `return 0` ("Stub: dynamic method call on opaque
#     Python object"). A silent 0, exit 0, for a call CPython rejects
#     outright: the worst possible outcome, since nothing distinguishes it
#     from a real 0.
#   * `size` is NOT in that list, so `s.size()` fell all the way through to
#     `_lower_struct_method_call` and emitted a call to the phantom C symbol
#     `_MojoStructFmt_size` that nothing ever defines — a link failure on a
#     shape whose correct answer is a two-line try/except.
#
# Neither is reachable from real stdlib code, which is why both survived, but
# the point of closing the branch is that the NEXT name added to that
# container list cannot silently reopen the same hole on this closed type.
# Arguments are still lowered first: real Python evaluates them before it
# discovers the callee is not callable, so `s.format(side_effect())` must
# run `side_effect()`.
def _lower_struct_attr_call(gen, method, node):
    for a in node.args:
        gen.lower_expr(a)
    for _, kv in (getattr(node, 'kwargs', None) or []):
        gen.lower_expr(kv)
    # `_emit_call`, not a raw `gen._emit`: the detail is a string-pool global,
    # and passing a `_slit_N` straight as a call argument is rejected inside a
    # `__GIMPLE`-tagged function ("invalid argument to gimple call", gcc
    # -fgimple strict mode) — the pool global has to be loaded into a local
    # first, which is exactly what `_emit_call`'s coercion loop does for a
    # `_slit_` operand.
    if method in _STRUCT_FMT_DATA_ATTRS:
        # The CPython text names the type of the VALUE read, not the
        # receiver: `s.format` is a str and `s.size` is an int, so those are
        # the two messages, in the same order as the table.
        detail = f"'{_STRUCT_FMT_DATA_ATTRS[method]}' object is not callable"
        raiser = 'mojo_raise_type_error'
    else:
        detail = f"'_struct.Struct' object has no attribute '{method}'"
        raiser = 'mojo_raise_attribute_error'
    gen._emit_call('void', '', raiser,
                   [('char *', gen._intern_string(gimple_ctypes._c_escape(detail)))])
    # mojo_raise() longjmps and never returns, so this value is dead on every
    # path that reaches it; it exists only so the surrounding expression still
    # typechecks, exactly as the other never-taken raise sites in this file
    # return a zero of the shape their caller wanted.
    return gen._stub_result('int64_t', '(int64_t)0',
                            f'struct.Struct.{method}() — raises at runtime')


def _lower_method_call(gen, node: gimple_ctypes.CallExpr) -> tuple[str, str]:
    """Lower obj.method(args) — handles module calls, raw C pointers (UnsafePointer) and structs."""
    func = node.func  # MemberExpr

    # `mod_a.Dialog(...)` — a QUALIFIED CONSTRUCTOR CALL: the receiver names
    # a real module marker and the member names a real, already-inlined
    # STRUCT, so this is `Dialog(...)` reached through its owning module,
    # not a genuine method call. Checked first: none of the special-cases
    # below apply to a struct name (they key on specific method names like
    # 'send'/'alloc'), and the GENERIC receiver-lowering dispatch further
    # down has no "construct a class found via module attribute" case at
    # all — the receiver (the module marker, lowering to a placeholder
    # int64_t) was echoed straight back as the "result" (the same "generic
    # fallback just ECHOED the receiver back" class of bug the
    # collections.Counter special case in `_lower_call` documents), so
    # `x = mod_a.Dialog("a")` bound `x` to the MODULE HANDLE itself and a
    # later `x.widgetName` raised a genuine runtime `AttributeError`. See
    # bugs/hard/CODEGEN_same_bare_name_struct_collision_across_modules.md
    # §4 ("module.Class(...) construction is unresolved on every path").
    if (isinstance(func.obj, gimple_ctypes.IdentExpr)
            and func.obj.name in gen.imported_symbols
            and func.obj.name not in gen.struct_field_types
            and func.member in gen.struct_field_types
            and func.member not in gen.var_types):
        return gen._lower_struct_constructor(func.member, node.args, node.kwargs)

    # `g.send(v)` — resuming a compiled generator with a value for the
    # `yield` it is suspended on: the rest of Python's generator protocol
    # alongside `next(g)` (see _lower_call). Checked FIRST, before any of
    # the module/struct/pointer receiver dispatch below: a generator value
    # is a `MojoGenerator *` handle, and without this case `g.send(1)` fell
    # through to the generic scalar-method stub, which read it as a FIELD
    # access on that object and emitted a call to an undefined
    # `_MojoGenerator_send` symbol — a link-time failure, so every
    # `.send()` in a compiled program failed to build.
    if func.member == 'send':
        at, av = gen.lower_expr(func.obj)
        at = gen._get_actual_type(at, av)
        if at == 'MojoGenerator *':
            api = gen._generator_var_api.get(av)
            if api is None:
                raise RuntimeError(
                    f"generator .send() on a value with no known generator "
                    f"API ({av!r}) — bind the generator to a variable first "
                    f"(g = gen(); g.send(v))")
            return ggc._lower_generator_send(gen, node, av, api)

    if func.member in ('send', 'throw', 'close'):
        at, av = gen.lower_expr(func.obj)
        at = gen._get_actual_type(at, av)
        if at == 'MojoGenerator *':
            api = gen._generator_var_api.get(av)
            if api is None:
                raise RuntimeError(
                    f"generator .{func.member}() on a value with no known "
                    f"generator API ({av!r}) — bind the generator to a "
                    f"variable first (g = gen(); g.{func.member}(...))")
            if func.member == 'send':
                return ggc._lower_generator_send(gen, node, av, api)
            if func.member == 'throw':
                return ggc._lower_generator_throw(gen, node, av, api)
            return ggc._lower_generator_close(gen, node, av, api)

    # `UnsafePointer[T].alloc(n)` / `OwnedPointer[T].alloc(n)` etc. — the
    # static heap-allocation constructor, whose receiver is the type
    # subscript `UnsafePointer[T]` (a SubscriptExpr), not a value. Checked
    # before the receiver is lowered: lowering `UnsafePointer[T]` as an
    # ordinary subscript yields a bogus `mojo_list_get_int` temp and
    # `.alloc()` then falls through to the generic scalar-method stub (see
    # bugs/CODEGEN_int_of_alloc_struct_pointer_returns_zero.md).
    if (func.member == 'alloc'
            and isinstance(func.obj, gimple_ctypes.SubscriptExpr)
            and isinstance(func.obj.obj, gimple_ctypes.IdentExpr)
            and func.obj.obj.name in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer')):
        return gen._lower_pointer_alloc(node)

    # `sys.getfilesystemencoding()`/`sys.getdefaultencoding()` — like
    # the existing `sys.platform` comptime-constant special case just
    # below (obj.name == 'sys'), these are genuinely string-returning
    # calls with no real filesystem/locale model in this codegen, so a
    # fixed `"utf-8"` (this compiler's own real behavior on every
    # supported host) is a faithful stand-in. Without this, the call
    # fell through to the fully generic "unknown method on scalar
    # receiver" stub (`_stub_result(ot, ...)`, several hundred lines
    # below), which passes the RECEIVER's type through unchanged — the
    # `sys` module reference itself resolves to a placeholder
    # `int64_t`, so the stubbed call result was typed `int64_t` too.
    # Assigning that result directly to a real `char *`-typed target
    # (e.g. `tarfile.py`'s module-level `ENCODING = sys.
    # getfilesystemencoding()`) is invalid C ("assignment to 'char *'
    # from 'int' makes pointer from integer without a cast") — a hard
    # compile failure, not just an imprecise stub. Found via
    # bugs/CODEGEN_generator_function_Lib_tarfile.md.
    if (isinstance(func.obj, gimple_ctypes.IdentExpr) and func.obj.name == 'sys'
            and func.member in ('getfilesystemencoding', 'getdefaultencoding')):
        for a in node.args: gen.lower_expr(a)
        return 'char *', gen._intern_string('utf-8')

    # `hashlib.blake2b(...)`/`.md5(...)`/`.sha256(...)`: a mutable byte
    # accumulator (`h.update(x)` called repeatedly, `h.hexdigest()` read at
    # the end) — genuinely unsupported before this, so `h`'s type fell
    # through to opaque/unresolved, and its `.update()` call then matched
    # the receiver-type-unknown heuristic in _lower_call's dict/list/set
    # dispatch below (ANY unresolved receiver + method name 'update' was
    # guessed to be a dict) — a real self-host-only miscompile (see
    # DESIGN.html's R1/R4: guessing a concrete kind from a method NAME
    # alone, with no verification). Resolving `h`'s real type here as
    # `MojoBytes *` from construction sidesteps that heuristic entirely: a
    # correctly-typed receiver never reaches the guess. digest_size/
    # usedforsecurity kwargs are accepted and ignored — this only needs to
    # let hashlib-using source COMPILE under self-host; the compiled mojoc
    # binary never itself drives the Python-side build tooling
    # (cas.py/build_stdlib_dylib.py/py314_cache.py) that actually calls
    # hashlib, so exact digest-byte compatibility with CPython's real
    # blake2b/md5/sha256 is not required (see mojo_bytes_hash_hexdigest's
    # own comment in runtime/fire_runtime.c).
    if (isinstance(func.obj, gimple_ctypes.IdentExpr) and func.obj.name == 'hashlib'
            and func.member in ('blake2b', 'md5', 'sha1', 'sha256', 'sha512')):
        for a in node.args: gen.lower_expr(a)
        for _, kv in (getattr(node, 'kwargs', None) or []):
            gen.lower_expr(kv)
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytearray_new', [])

    # `<expr>.<SomeABCClass>.register(<arg>)` — real Python's
    # `abc.ABC.register()` virtual-subclass-registration idiom (real:
    # `os.PathLike.register(PurePath)`, pathlib/__init__.py:598).
    # `.register()` is a genuine behavioral no-op — it only affects
    # `isinstance()` checks against the registering ABC, never anything
    # this codegen's own control flow depends on — so this codegen has
    # ALWAYS stubbed a `.register()` call to a no-op (see the generic
    # scalar-method fallback's `_stub_result(ot, ov_local, ...)` further
    # below in this function). The bug: reaching that stub still requires
    # evaluating the RECEIVER first (`<expr>.<SomeABCClass>`), and for a
    # module-level ABC class never modeled as a real compiled struct
    # (`os.PathLike` — `os` itself is a stubbed/opaque module handle in
    # this codegen), that receiver evaluation goes through
    # `_mojo_dispatch_getattr`, which correctly raises a real, loud
    # `AttributeError` for an attribute name it has no registration for —
    # crashing the program before the (already-a-no-op) `.register()`
    # stub is ever reached, even though the stub's result is thrown away
    # unused either way. Skip evaluating the receiver entirely for this
    # exact shape rather than let a discarded value's evaluation crash
    # the program. Scoped narrowly to avoid stubbing a REAL user-defined
    # `.register()` method: only fires when the receiver is itself a
    # TWO-level member chain (`func.obj` a MemberExpr, e.g. `os.PathLike`,
    # not `self.register(x)`/`registry.register(x)`'s single-level
    # MemberExpr) whose own member name is PascalCase (the ABC/class-name
    # convention `os.PathLike` follows, not an ordinary lowercase
    # attribute like `self.registry.register(x)`'s `registry`) and isn't
    # itself a struct this codegen actually compiled (a real compiled
    # class's own `.register` classmethod, if one ever exists, still
    # dispatches normally below).
    if (func.member == 'register' and len(node.args) == 1
            and not getattr(node, 'kwargs', None)
            and isinstance(func.obj, gimple_ctypes.MemberExpr)
            and func.obj.member[:1].isupper()
            and func.obj.member not in gen.struct_field_types):
        for a in node.args:
            gen.lower_expr(a)
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0  /* ABC .register() no-op */')

    # Step I (create_task/Task/TaskGroup/RaisingTask project):
    # `task.wait()` or `task^.wait()` where `task` holds a
    # `MojoAsync *` handle produced by
    # `create_task(...)`/`create_raising_task(...)` (tracked in
    # self._async_var_api — see that dict's docstring). The `^`
    # transfer sigil (real Mojo's own idiom for `RaisingTask.wait(deinit
    # self)`'s ownership-transfer requirement) is NOT stripped by the
    # tokenizer — confirmed directly via the parser: `task^` produces
    # `UnaryOp(op='^', operand=IdentExpr('task'))` — so both shapes are
    # matched explicitly below; this codegen has no ownership/deinit
    # model to actually enforce, so `^` is simply unwrapped to the
    # underlying variable reference. Blocks the current (single-
    # threaded, cooperative) scheduler to completion — reuses the EXACT
    # SAME drive/translate/read/destroy sequence the `asyncio.run(...)`
    # bridge already uses (see _lower_call's `module_name == 'asyncio'
    # and method_name == 'run'` branch), since blocking-wait-for-
    # completion is semantically the same operation there and here,
    # just reached via a different Mojo-level spelling. No structural
    # distinction is made here between a plain `Task` and a
    # `RaisingTask` — this codegen's promise already stages ANY escaped
    # exception generically (Step E), regardless of whether the async
    # function was declared `raises`, so `create_raising_task(...)`
    # (below, in _lower_call) reuses this exact same tracking/handle
    # shape; the real Mojo-level `Task` vs. `RaisingTask` distinction
    # is a type-checking-only concern this codegen doesn't model.
    _wait_obj = func.obj
    if (isinstance(_wait_obj, gimple_ctypes.UnaryOp) and _wait_obj.op == '^'
            and isinstance(_wait_obj.operand, gimple_ctypes.IdentExpr)):
        _wait_obj = _wait_obj.operand
    if (isinstance(_wait_obj, gimple_ctypes.IdentExpr) and _wait_obj.name in gen._async_var_api
            and func.member == 'wait' and not node.args):
        api = gen._async_var_api[_wait_obj.name]
        if api.get('stub'):
            # See _lower_call's create_task/create_raising_task stub
            # branch — this handle names a real async function this
            # codegen couldn't compile (documented, narrow degrade for
            # provably-unreachable dead code, not silent wrongness).
            # `.wait()` on it degrades the exact same way: a loud,
            # honest runtime abort() instead of trying to call
            # nonexistent extern "C" API functions for a `base` that
            # was never generated.
            gen._emit(
                '  fprintf(stderr, "mojo: .wait() reached on a stub '
                'create_task/create_raising_task handle (deliberate '
                'stub -- see gimple_codegen.py\'s _lower_call comment) '
                '-- aborting\\n");')
            gen._emit("  abort ();")
            result = gen._new_val('int64_t', '(int64_t)0')
            return 'int64_t', result
        base, vct = api['base'], api['value_ctype']
        handle_expr = _wait_obj.name
        gen._emit(f"  mojo_async_run_until_complete ();")
        gen._emit(f"  {base}_translate_pending_exc ({handle_expr});")
        # 'int', not '_Bool': fire_runtime.h's real prototype is `int
        # mojo_exc_pending_get(void);` -- a '_Bool'-typed temp here is
        # invalid under STRICT `-fgimple` mode ("invalid conversion in
        # gimple call"), confirmed via a hand-reduced repro. Silently
        # tolerated everywhere this pattern was reached before (every
        # existing passing test's own `.wait()` call sites all
        # compile through gen_func's LENIENT, non-`__GIMPLE`-tagged
        # top-level function path, which accepts the implicit int->
        # _Bool narrowing the same way ordinary C does) -- first
        # surfaced for real once `.wait()` became reachable from
        # inside a strict-`__GIMPLE` NESTED closure (test_locks.mojo's
        # `test_atomic()` calling `tg.wait(...)` transitively via the
        # gap-(1) transitive-capture-propagation fix). `int` still
        # works identically as an `if (pending_t) ...` condition.
        pending_t = gen._new_val('int', "mojo_exc_pending_get ()")
        bb_pending = gen._new_bb()
        bb_ok = gen._new_bb()
        gen._emit(f"  if ({pending_t}) goto {bb_pending}; else goto {bb_ok};")
        gen._emit_label(bb_pending)
        gen._emit(f"  mojo_exc_pending_set (0);")
        gen._emit(f"  {base}_destroy ({handle_expr});")
        gen._emit("  mojo_raise ();")
        gen._emit_label(bb_ok)
        # A genuinely void-returning task (mutable-capture project:
        # `create_task(inc())` where `inc()`'s whole body is side
        # effects on a captured variable, no `return <value>` at all --
        # test_locks.mojo's own `inc()` shape) has no real `current_
        # value` to read back -- a `void` GIMPLE local is invalid C, and
        # `{base}_value`'s own C++ body has nothing meaningful to
        # return for this case anyway. Mirrors `_emit_asyncio_run_
        # drive`'s identical void-skip exactly (the same underlying
        # `_start`/`_value`/`_destroy` API, just reached via `.wait()`
        # instead of `asyncio.run(...)`) -- this exact combination
        # (`create_task`+`.wait()` on a VOID async function) was never
        # exercised before the mutable-capture work, since every prior
        # `create_task`/`.wait()` test drove a value-returning task.
        if vct == 'void':
            gen._emit(f"  {base}_destroy ({handle_expr});")
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
        result = gen._new_val(vct, f"{base}_value ({handle_expr})")
        gen._emit(f"  {base}_destroy ({handle_expr});")
        return vct, result

    # Step I (create_task/Task/TaskGroup/RaisingTask project):
    # `tg.create_task(<call>)` where `tg` is a `TaskGroup` (see
    # `_lower_call`'s `TaskGroup()` construction docstring / `self.
    # _taskgroup_var_api`'s own docstring). Constructs + schedules the
    # task exactly like a bare `create_task(...)` (via the shared
    # `_resolve_and_start_task` helper), then appends the resulting
    # handle (cast to int64_t) onto the group's own `MojoList *` so
    # `.wait()` (below) can later drain every task this group ever
    # created. Every task added to ONE group must resolve to the SAME
    # compiled async unit (`api['base']` must match whatever earlier
    # `.create_task()` calls on this SAME group already established) --
    # an honest compile-time refusal, not silent wrongness, for the
    # genuinely heterogeneous case real Mojo's own type-erased
    # `_TaskGroupBox` supports and this narrower reinterpretation
    # doesn't (see that docstring for why this is an acceptable scope
    # limit for every real target shape).
    if (isinstance(_wait_obj, gimple_ctypes.IdentExpr) and _wait_obj.name in gen._taskgroup_var_api
            and func.member == 'create_task' and len(node.args) == 1
            and not getattr(node, 'kwargs', None)):
        tg_api = gen._taskgroup_var_api[_wait_obj.name]
        _resolved = gen._resolve_and_start_task(node.args[0])
        if _resolved is None:
            raise RuntimeError(
                "cannot compile module: TaskGroup.create_task(...) is "
                "only supported for a call to another compiled async "
                "function this module already compiled -- falling "
                "back to interpreting this module from source instead")
        handle, api = _resolved
        if tg_api['base'] is not None and tg_api['base'] != api['base']:
            raise RuntimeError(
                "cannot compile module: this TaskGroup already holds "
                f"tasks of a different compiled async unit ({tg_api['base']!r} "
                f"vs {api['base']!r}) -- this codegen only supports a "
                "single, homogeneous task type per TaskGroup -- falling "
                "back to interpreting this module from source instead")
        tg_api['base'] = api['base']
        tg_api['value_ctype'] = api['value_ctype']
        if api.get('stackswitch'):
            tg_api['stackswitch'] = True
        handle_i64 = gen._new_val('int64_t', f"(int64_t){handle}")
        gen._emit(f"  mojo_list_append_int ({_wait_obj.name}, {handle_i64});")
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')

    # `tg.wait[origin]()` -- the bracket origin argument is already
    # dropped by the SubscriptExpr+MemberExpr routing a few thousand
    # lines up in `_lower_call` (no threaded-comptime-param entry ever
    # exists for `TaskGroup`'s intrinsic `wait`, so `extra_args` there
    # is always empty for it) -- reached here as a plain, no-argument
    # `.wait()` call, exactly like the ordinary `MojoAsync *` `.wait()`
    # case above, just over every handle the group has accumulated
    # instead of one. Drives Step A's SHARED scheduler to completion
    # exactly ONCE (it's a single global scheduler regardless of which
    # TaskGroup a task was created through, so one drive call finishes
    # every pending task, group or not), then walks the group's own
    # `MojoList *` (the same GIMPLE-safe goto-based length/index loop
    # `_compr_list_loop` already uses for iterating a MojoList),
    # translating/propagating any pending exception and destroying
    # each handle in turn -- mirrors the ordinary single-task `.wait()`
    # sequence above exactly, just looped.
    if (isinstance(_wait_obj, gimple_ctypes.IdentExpr) and _wait_obj.name in gen._taskgroup_var_api
            and func.member == 'wait' and not node.args):
        tg_api = gen._taskgroup_var_api[_wait_obj.name]
        list_expr = _wait_obj.name
        if tg_api.get('stackswitch'):
            # A3 stack-switch backend: each handle in the group is a
            # MojoGenerator constructed (not scheduled) by its
            # `{base}_start` call -- drive each to completion via
            # `__mojo_async_run_gen` (the same drive the single-task
            # stack-switch `.wait()` rewrite uses, see gimple_gen_coro.
            # _rewrite_asyncio_run), then destroy it. No cpp-scheduler
            # drain (`mojo_async_run_until_complete`) and no `{base}_
            # translate_pending_exc` (the stack-switch trampoline emits
            # neither) -- exception propagation matches the single-task
            # stack-switch path exactly (via the resume contract).
            len64 = gen._new_val('int64_t', f"mojo_list_len ({list_expr})")
            idx64 = gen._new_val('int64_t', "(int64_t)0")
            bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_after = gen._new_bb()
            gen._emit(f"  goto {bb_cond};")
            gen._emit_label(bb_cond)
            cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
            gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
            gen._emit_label(bb_body)
            raw_h = gen._new_val('int64_t', f"mojo_list_get_int ({list_expr}, {idx64})")
            gen._emit(f"  __mojo_async_run_gen ({raw_h});")
            gen._emit(f"  __mojo_gen_destroy ({raw_h});")
            one64 = gen._new_val('int64_t', "(int64_t)1")
            nxt = gen._new_val('int64_t', f"{idx64} + {one64}")
            gen._emit(f"  {idx64} = {nxt};")
            gen._emit(f"  goto {bb_cond};")
            gen._emit_label(bb_after)
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
        gen._emit(f"  mojo_async_run_until_complete ();")
        if tg_api['base'] is not None:
            base = tg_api['base']
            len64 = gen._new_val('int64_t', f"mojo_list_len ({list_expr})")
            idx64 = gen._new_val('int64_t', "(int64_t)0")
            bb_cond = gen._new_bb(); bb_body = gen._new_bb()
            bb_post = gen._new_bb(); bb_after = gen._new_bb()
            gen._emit(f"  goto {bb_cond};")
            gen._emit_label(bb_cond)
            cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
            gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
            gen._emit_label(bb_body)
            raw_h = gen._new_val('int64_t', f"mojo_list_get_int ({list_expr}, {idx64})")
            h_expr = gen._new_val('MojoAsync *', f"(MojoAsync *){raw_h}")
            gen._emit(f"  {base}_translate_pending_exc ({h_expr});")
            # 'int', not '_Bool' -- see the identical comment on this
            # same pattern a bit further up in this method.
            pending_t = gen._new_val('int', "mojo_exc_pending_get ()")
            bb_pending = gen._new_bb()
            bb_ok = gen._new_bb()
            gen._emit(f"  if ({pending_t}) goto {bb_pending}; else goto {bb_ok};")
            gen._emit_label(bb_pending)
            gen._emit(f"  mojo_exc_pending_set (0);")
            gen._emit(f"  {base}_destroy ({h_expr});")
            gen._emit("  mojo_raise ();")
            gen._emit_label(bb_ok)
            gen._emit(f"  {base}_destroy ({h_expr});")
            gen._emit(f"  goto {bb_post};")
            gen._emit_label(bb_post)
            one64 = gen._new_val('int64_t', "(int64_t)1")
            nxt = gen._new_val('int64_t', f"{idx64} + {one64}")
            gen._emit(f"  {idx64} = {nxt};")
            gen._emit(f"  goto {bb_cond};")
            gen._emit_label(bb_after)
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')

    # `super().method(args)` — resolve directly to the base struct's method
    # rather than falling through to the generic obj.method() dispatch below,
    # which would try to evaluate `super()` as an ordinary call to a bare
    # function named `super` (undefined symbol at link time — see
    # bugs/consolidated/COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md).
    # Mirrors myinterpreter.py's eval_IdentExpr/_eval_super: `super()` means
    # "the first base class of the struct the enclosing method belongs to".
    if (isinstance(func.obj, gimple_ctypes.CallExpr) and isinstance(func.obj.func, gimple_ctypes.IdentExpr)
            and func.obj.func.name == 'super' and not func.obj.args):
        base_name = None
        cur_struct = getattr(gen, '_current_struct_name', None)
        method = func.member
        # Walk the bases IN DECLARATION ORDER (Python MRO order for the
        # non-diamond hierarchies this codegen models) and pick the first
        # base that BOTH has a resolvable StructDef AND actually DEFINES
        # the called method (`{Base}_{method}` registered as a compiled
        # function, or a known method-signature entry). The old behavior
        # stopped at the FIRST struct-typed base regardless of what it
        # defines: zipfile/_path's `CompleteDirs(InitializedState,
        # zipfile.ZipFile)` then resolved `super().getinfo(...)`/
        # `super().namelist()` to `{InitializedState}_getinfo`/`_namelist`
        # — symbols NOTHING defines (the mix-in doesn't have those
        # methods; they live on the SECOND base) — satisfying -fgimple
        # against a weak stub declaration but failing the final LINK with
        # "Undefined symbols". A base whose own merged view carries the
        # method via inheritance still counts: its `{Base}_{method}`
        # C symbol may not exist, so ONLY bases with a direct definition
        # are eligible; if NO base directly defines the method there is
        # nothing to call — degrade to the same evaluate-args-and-no-op
        # convention the no-resolvable-base case below already uses
        # rather than emitting an unresolvable symbol.
        def _base_defines_method(b):
            return (f"{b}_{gimple_ctypes._safe_name(method)}" in gen.func_return_types
                    or _gmm_sms_key(b, method) in gen._struct_method_signatures)
        for b in (gen._struct_bases.get(_gmm_as_str(cur_struct)) or []) if cur_struct else ():
            # Only a base with an actual known definition (fields/methods
            # registered in struct_field_types) has a real C function to
            # call into. A base we never resolved a StructDef for — e.g.
            # an external/unmodeled class like html.parser.HTMLParser —
            # has no native method to link against.
            if b in gen.struct_field_types and _base_defines_method(b):
                base_name = b
                break
        if base_name is None:
            # No resolvable base DEFINES the method: there is nothing to
            # call. Still evaluate the arguments for side effects, then
            # no-op — the same "can't fully support this construct,
            # degrade gracefully" convention _stub_only_modules below
            # uses for symbols with no native definition, rather than
            # emitting an unresolvable call.
            for a in node.args:
                gen.lower_expr(a)
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
        self_type, self_val = gen.lower_expr(gimple_ctypes.IdentExpr(name='self', line=getattr(node, 'line', 0)))
        fake_obj_type = f"{base_name} *"
        # `self`'s REAL declared C type is the DERIVED struct (e.g.
        # `_LiteralGenericAlias *`), not `fake_obj_type` (the base
        # struct pointer type used below purely for method-resolution
        # bookkeeping in `_lower_struct_method_call`). Passing `self_val`
        # unchanged used to lie to `_emit_call`'s own arg-coercion pass
        # (gimple_codegen.py's `_emit_call`): since it saw the caller's
        # claimed arg type (`fake_obj_type`) already equal the callee's
        # declared param type (also `fake_obj_type`, i.e. `{base_name}
        # *`), it skipped emitting any cast — producing a real C
        # pointer-type mismatch at the call site GCC correctly flagged
        # ("passing argument 1 ... from incompatible pointer type"),
        # confirmed via a `super().__dir__()`/`__mro_entries__()`/
        # `copy_with()` multi-level-inheritance repro against
        # Lib/typing.py's `_LiteralGenericAlias`/`_SpecialGenericAlias`/
        # `_CallableType`/etc. chains (~11 occurrences in a `fire.py
        # build Lib/subprocess.py` run). A base-class pointer cast is
        # always a valid, safe C conversion (same struct-pointer-cast
        # convention every OTHER method-dispatch site in this file
        # already relies on for its own `(StructName *)obj_val` casts),
        # so materialize it here instead of merely asserting it via the
        # type label.
        if self_type != fake_obj_type:
            self_val = gen._new_val(fake_obj_type, f"({fake_obj_type}){self_val}")
        return gen._lower_struct_method_call(self_val, fake_obj_type, func.member, node)

    # `self.__class__(args)` / `<known struct instance>.__class__(args)` —
    # real Python CONSTRUCTS A NEW INSTANCE of the object's runtime class
    # (zipfile/_path's `Path._next`: `return self.__class__(self.root,
    # at)`). This codegen has no runtime class objects — `x.__class__`
    # read as a plain VALUE lowers to a runtime type-tag int64_t (see
    # gimple_gen_exprs.py's `_lower_MemberExpr` `__class__` case) — so
    # this call shape used to fall through to the unknown-struct-method
    # fallback and emit a call to the never-defined `{Struct}___class__`
    # symbol (`_Path___class__`), satisfying -fgimple against nothing at
    # all and failing the final LINK ("Undefined symbols"). When the
    # receiver's static struct type is known, lower as an ordinary struct
    # construction of THAT struct — the exact-type approximation this
    # static codegen makes for non-__class__-mutated instances.
    if func.member == '__class__':
        ot_cls, ov_cls = gen.lower_expr(func.obj)
        sn_cls = gimple_exprtypes._struct_name_of(ot_cls)
        if sn_cls in gen.struct_field_types:
            return gen._lower_struct_constructor(
                sn_cls, list(node.args), _gmm_callexpr_node(node).kwargs or [])
        for a in node.args:
            gen.lower_expr(a)
        return 'int64_t', gen._new_val('int64_t', '(int64_t)0')

    # `coro._set_noop_callback()` / `coro^._take_handle()` — the two
    # std.builtin.coroutine.Coroutine methods device_context.mojo's
    # `enqueue_cpu_function`/`enqueue_cpu_range` call on the coroutine
    # object a compiled async closure's call site produces (see
    # _lower_async_closure_construct — a `MojoAsync *` handle, this
    # codegen's own opaque coroutine-handle representation). Real
    # Mojo's `Coroutine`/`RaisingCoroutine` wrap a raw MLIR
    # `!co.routine` handle (`AnyCoroutine`) with these two methods;
    # since this codegen already represents ITS OWN coroutine handles
    # as a `MojoAsync *` (not a real `Coroutine` struct instance), the
    # two methods are modeled directly against that representation
    # rather than attempting to compile std.builtin.coroutine's own
    # Mojo source (which uses raw `__mlir_op.co.resume`/`co.destroy`
    # ops this codegen has no general lowering for):
    #   `_set_noop_callback()` — a no-op here. Real Mojo uses this to
    #     arm a callback for genuinely ASYNCHRONOUS dispatch; this
    #     codegen's own runtime stub (AsyncRT_DeviceContext_
    #     enqueueHostFunction(Range), runtime/mojo_async_runtime.cpp)
    #     is a deliberate synchronous simplification that always
    #     drives the coroutine to completion with one direct resume()
    #     call — see that stub's own docstring — so there is no
    #     separate callback state to arm.
    #   `_take_handle()` — returns the SAME `MojoAsync *` handle this
    #     coroutine's own construction (`_start()`) already produced,
    #     reinterpreted as the plain `int64_t` handle representation
    #     `mojo_coro_resume_generic`/`mojo_coro_destroy_generic` (and
    #     the AsyncRT_DeviceContext_enqueueHostFunction(Range) stubs)
    #     expect — see runtime/fire_async_runtime.h's own docstring on
    #     why handles are plain int64_t there, matching real Mojo's
    #     own AnyCoroutine representation.
    #
    # Under the A3 stack-switch backend (MOJO_CORO=stackswitch,
    # gimple_gen_coro.py) a nested `@parameter async def wrapper()`'s
    # construction (`wrapper()`) instead produces a `MojoGenerator *`
    # handle (this backend's own opaque coroutine-handle representation —
    # see gimple_gen_coro.py's `_C_TRAMPOLINE_TMPL`, `{base}_start` returns
    # `MojoGenerator *`), so the same two methods are modeled the same way
    # against THAT representation: `_set_noop_callback()` a no-op, and
    # `_take_handle()` the same handle bits reinterpreted as int64_t —
    # `__mojo_gen_resume_once`/`__mojo_gen_destroy` (runtime/mojo_coro_gen.c)
    # are the stack-switch equivalent of `mojo_coro_resume_generic`/
    # `destroy_generic`, substituted in by gimple_codegen.py's
    # `BUILTIN_VALUE_MAP` override for `_coro_resume_fn`/`_coro_destroy_fn`
    # when the stack-switch backend is enabled — see bugs/hard/CODEGEN_
    # coro_detached_async_take_handle.md.
    if isinstance(func.obj, (gimple_ctypes.IdentExpr, gimple_ctypes.UnaryOp)):
        _obj_type, _obj_val = gen.lower_expr(func.obj)
        if _obj_type in ('MojoAsync *', 'MojoGenerator *'):
            if func.member == '_set_noop_callback' and not node.args:
                return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
            if func.member == '_take_handle' and not node.args:
                t = gen._new_val('int64_t', f'(int64_t){_obj_val}')
                return 'int64_t', t

    # `m.group()`/`m.start()` where m is a regex-match for-loop variable
    # (see _gen_for_regex_iter / regex_compile.py / BACKLOG-CODEGEN.md §4f).
    # Only the no-arg forms py_tokenize's own `for m in _TOKEN_RE.finditer(...)`
    # uses are handled — `.group(n)`, `.span()`, etc. are not.
    if (isinstance(func.obj, gimple_ctypes.IdentExpr) and func.obj.name in gen._regex_match_vars
            and not node.args):
        ctx = gen._regex_match_vars[func.obj.name]
        if func.member == 'group':
            return 'char *', gen._call_expr('char *', 'mojo_regex_substr',
                                              [('char *', ctx['text_val']),
                                               ('int64_t', ctx['mstart_var']),
                                               ('int64_t', ctx['mend_var'])])
        if func.member == 'start':
            return 'int64_t', gen._call_expr('int64_t', 'mojo_utf8_codepoint_index',
                                                [('char *', ctx['text_val']),
                                                 ('int64_t', ctx['mstart_var'])])
        if func.member == 'end':
            return 'int64_t', gen._call_expr('int64_t', 'mojo_utf8_codepoint_index',
                                                [('char *', ctx['text_val']),
                                                 ('int64_t', ctx['mend_var'])])

    # `dataclasses.fields(x)`/`dataclasses.is_dataclass(x)` on a value
    # whose concrete struct type isn't known statically (e.g. any AST
    # node walked generically by ast_rewriter.py) — dispatch on the
    # runtime type tag via the _mojo_dispatch_* functions gen_module
    # emits once per program from struct_field_types (see there for why).
    # `fields()` returns a MojoList* of field-name strings rather than
    # real dataclasses.Field objects (the loop var's only ever-used
    # attribute in this codebase is `.name`; see the for-loop lowering's
    # _dataclass_fields_vars handling for how `f.name` resolves back to
    # `f` itself).
    if (gimple_ctypes._is_dataclasses_module_ref(func.obj)
            and func.member == 'fields' and len(node.args) == 1):
        at, av = gen.lower_expr(node.args[0])
        vp = gen._ensure_local(at, av)
        return 'MojoList *', gen._call_expr('MojoList *', '_mojo_dispatch_fields', [(at, vp)])
    if (gimple_ctypes._is_dataclasses_module_ref(func.obj)
            and func.member == 'is_dataclass' and len(node.args) == 1):
        at, av = gen.lower_expr(node.args[0])
        vp = gen._ensure_local(at, av)
        return 'int', gen._call_expr('int', '_mojo_dispatch_is_dataclass', [(at, vp)])
    # `dataclasses.replace(obj, **changes)` (used by this compiler's own
    # _subst_idents for comptime alias expansion): no generic struct-clone
    # runtime helper exists to build the real replaced copy, so — as
    # before this dispatch existed, when it fell through to the opaque
    # int/char* method-coercion path below and matched 'replace' there,
    # silently misrouting to a *string* .replace() and stubbing to 0 —
    # approximate with identity (the first positional arg unchanged).
    # Must be intercepted here, before the receiver ('dataclasses', an
    # opaque module reference) can reach the generic char*.replace()
    # dispatch and get a real but semantically wrong string-replace call.
    if (gimple_ctypes._is_dataclasses_module_ref(func.obj)
            and func.member == 'replace' and node.args):
        return gen.lower_expr(node.args[0])

    # Int/scalar MLIR accessors are identity on our scalar representation:
    # `x._int_mlir_index()` / `x.__mlir_index__()` just yield the machine word.
    # (For a real `Int *` receiver, the walked-in Int method handles it.)
    if func.member in ('_int_mlir_index', '__mlir_index__') and not node.args:
        rt, rv = gen.lower_expr(func.obj)
        if rt in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                  'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', '_Bool'):
            return rt, rv

    # Handle chained attribute calls: os.path.basename(arg) → int64_t_basename(arg)
    # TODO: move to ast_rewriter — this whole os.path.* block is the same
    # kind of "Python idiom -> concrete runtime call" mapping the rewriter
    # (see ast_rewriter.py, e.g. the os_environ_* rules) is meant to hold,
    # just not yet migrated.
    if isinstance(func.obj, gimple_ctypes.MemberExpr):
        inner_obj = func.obj.obj
        inner_member = func.obj.member
        outer_member = func.member

        # Self-hosting bootstrap, ONE LEVEL DEEPER than the plain
        # `gimple_ctypes.<module>.<method>(...)` strip just below:
        # `gimple_ctypes.os.path.dirname(source)` (a real shape in this
        # compiler's own `_register_link_imports` — `os` reached through
        # the `gimple_ctypes` hub, then `.path.dirname(...)` on top of
        # that) has `inner_obj` itself be a MemberExpr (`gimple_ctypes.
        # os`), so it never matched the single-level `isinstance(inner_obj,
        # IdentExpr)` check below at all — neither hub-strip branch fired,
        # and the whole 4-deep chain fell past the "Handle os.path.*
        # calls" block too (which itself requires a BARE `os` IdentExpr
        # receiver), landing in the generic dynamic-dispatch fallback: an
        # opaque `int`-typed stub (always `0`) standing in for `os.path.
        # dirname`'s real `char *` result. `_pkg_dir = gimple_ctypes.os.
        # path.dirname(source)` then declared its local as plain `int`
        # (4 bytes) from that stub's type, and every later use of
        # `_pkg_dir` as a path (`os.path.isdir(_pkg_dir)`, `os.listdir
        # (_pkg_dir)`, `os.path.join(_pkg_dir, ...)`) cast that 4-byte
        # `int` straight to a pointer type — a real `-Wint-to-pointer-
        # cast: cast to pointer from integer of different size` warning
        # for EVERY such site of a genuinely wrong value (path operations
        # on a truncated stub, not the intended real dirname), not just a
        # diagnostic. Peel off the LEADING `gimple_ctypes.` (or any other
        # sibling-hub alias) qualifier from the innermost MemberExpr,
        # leaving the rest of the chain (`.os.path.dirname(...)`) intact,
        # and re-dispatch — the single-level branch immediately below
        # then peels no further (its own `inner_obj` is already a bare
        # `os` IdentExpr) and the real `os.path.*` handling further down
        # this same function fires normally.
        if (isinstance(inner_obj, gimple_ctypes.MemberExpr)
                and isinstance(inner_obj.obj, gimple_ctypes.IdentExpr)
                and _is_selfhost_sibling_alias(gen, inner_obj.obj.name)):
            _rewritten = gimple_ctypes.CallExpr(
                func=gimple_ctypes.MemberExpr(
                    obj=gimple_ctypes.MemberExpr(
                        obj=gimple_ctypes.IdentExpr(
                            name=inner_obj.member, line=getattr(node, 'line', 0)),
                        member=inner_member),
                    member=outer_member),
                args=list(node.args),
                kwargs=list(getattr(node, 'kwargs', None) or []))
            return gen._lower_method_call(_rewritten)

        # Self-hosting bootstrap: `gimple_ctypes.ast_rewriter.rewrite(...)`,
        # `gimple_ctypes.mlir.lower_op(...)`, `gimple_ctypes.Parser(...)` etc.
        # — this compiler's own backend modules reach sibling modules through
        # the `gimple_ctypes` re-export hub. The hub qualifier plus the
        # re-exported module name are both Python-import artifacts; strip
        # them and re-dispatch on `<real_module>.<member>(...)`.
        if (isinstance(inner_obj, gimple_ctypes.IdentExpr)
                and _is_selfhost_sibling_alias(gen, inner_obj.name)):
            _rewritten = gimple_ctypes.CallExpr(
                func=gimple_ctypes.MemberExpr(
                    obj=gimple_ctypes.IdentExpr(
                        name=inner_member, line=getattr(node, 'line', 0)),
                    member=outer_member),
                args=list(node.args),
                kwargs=list(getattr(node, 'kwargs', None) or []))
            return gen._lower_method_call(_rewritten)

        # Handle os.path.* calls
        if isinstance(inner_obj, gimple_ctypes.IdentExpr) and inner_obj.name == 'os' and inner_member == 'path':
            if outer_member == 'basename' and len(node.args) == 1:
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('char *', 'int64_t_basename', [(arg_type, arg_val)])
                return 'char *', t
            elif outer_member == 'splitext' and len(node.args) == 1:
                arg_type, arg_val = gen.lower_expr(node.args[0])
                root = gen._call_expr('char *', 'int64_t_splitext', [(arg_type, arg_val)])
                # Python splitext(p) is a (root, ext) pair; every call site does
                # `splitext(p)[0]`. Model it as a 2-element string list so the
                # subscript recovers the root as a char* (not a single char from
                # indexing into a bare string). ext is unused by the compiler.
                lst = gen._new_val('MojoList *', "mojo_list_new ()")
                gen._emit_call('void', '', 'mojo_list_append_str',
                                [('MojoList *', lst), ('char *', root)])
                gen._emit_call('void', '', 'mojo_list_append_str',
                                [('MojoList *', lst), ('char *', '""')])
                gen._elem_types[lst] = 'char *'
                return 'MojoList *', lst
            elif outer_member == 'split' and len(node.args) == 1:
                # os.path.split(p) -> the real (head, tail) pair, materialized
                # as a 2-element string list exactly like the splitext case
                # above (runtime helper: int64_t_path_split mirrors cpython's
                # posixpath.split verbatim). Previously this call shape fell
                # through every os.path.* case to the generic module-receiver
                # dispatch: receiver = the opaque `os.path` module marker
                # (int64_t), method 'split' -> the generic string-.split()
                # path with the marker coerced to the SEPARATOR argument —
                # mojo_str_split((char *)0, p) — so `os.path.split(name)[1]`
                # indexed element 1 of a whitespace-split of the whole path
                # (usually out of range). Found via Tools/unicode/
                # gencodec.py's convertdir(): `name = os.path.split(mapname)[1]`.
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('MojoList *', 'int64_t_path_split',
                                    [(arg_type, arg_val)])
                gen._elem_types[t] = 'char *'
                return 'MojoList *', t
            elif outer_member == 'splitdrive' and len(node.args) == 1:
                # os.path.splitdrive(p) -> (drive, tail). POSIX: always
                # ('', p). Materialized as a 2-element string list exactly
                # like os.path.split above. Call site (zipfile/__init__.py:
                # `os.path.splitdrive(arcname)[1]`) subscripts element 1.
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('MojoList *', 'int64_t_path_splitdrive',
                                    [(arg_type, arg_val)])
                gen._elem_types[t] = 'char *'
                return 'MojoList *', t
            elif outer_member == 'splitroot' and len(node.args) == 1:
                # os.path.splitroot(p) -> (drive, root, tail); POSIX
                # posixpath.splitroot semantics (see the runtime helper).
                # Materialized as a 3-element string list.
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('MojoList *', 'int64_t_path_splitroot',
                                    [(arg_type, arg_val)])
                gen._elem_types[t] = 'char *'
                return 'MojoList *', t
            elif outer_member == 'expanduser' and len(node.args) == 1:
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('char *', 'int64_t_expanduser', [(arg_type, arg_val)])
                return 'char *', t
            elif outer_member == 'abspath' and len(node.args) == 1:
                # int_abspath's real runtime.c signature is genuinely
                # `int64_t int_abspath(int64_t, int64_t)` (a boxed char*,
                # like int_dirname below) — but gimple_exprtypes.py's own
                # local-variable-type inference (`fn_return_types`-style
                # scan, ~line 840) has always declared os.path.abspath()
                # results 'char *' for every CONSUMER of this call (matches
                # the real semantic: it's a path string). Returning the raw
                # 'int64_t' call result here left that declared-vs-actual
                # mismatch for the assignment/declaration lowering to
                # silently paper over, invisible until a caller's C
                # declared type and this call's C return type collided in
                # a single statement with no implicit int64_t->char*
                # conversion allowed. Cast explicitly here (same pattern
                # 'expanduser' a few lines up already uses, just via a
                # runtime function whose C signature already says char*
                # instead of needing this local cast) so this call's own
                # returned (type, value) pair matches what every caller
                # already assumes. Found via module_loader.py's
                # `cwd = os.path.abspath(os.getcwd())`.
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('int64_t', 'int_abspath', [('int64_t', '0'), (arg_type, arg_val)])
                cast = gen._new_val('char *', f'(char *){t}')
                return 'char *', cast
            elif outer_member == 'dirname' and len(node.args) == 1:
                # Same boxed-int64_t-vs-declared-char* mismatch as abspath
                # just above; identical fix.
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('int64_t', 'int_dirname', [('int64_t', '0'), (arg_type, arg_val)])
                cast = gen._new_val('char *', f'(char *){t}')
                return 'char *', cast
            elif outer_member == 'join':
                t = gen._new_temp('int64_t')
                _join_has_spread = any(
                    isinstance(_ja, UnaryOp) and _ja.op == '*'
                    for _ja in node.args)
                if len(node.args) == 0:
                    gen._emit(f'  {t} = (int64_t)0;')
                elif len(node.args) == 1 and not _join_has_spread:
                    # os.path.join(*list) — single arg is a MojoList*
                    arg_type, arg_val = gen.lower_expr(node.args[0])
                    if arg_type == 'MojoList *':
                        gen._emit_call('int64_t', t, 'int_join_list', [('int64_t', '0'), (arg_type, arg_val)])
                    else:
                        # Single non-list arg: just return it
                        gen._emit_call('int64_t', t, 'int_join', [('int64_t', '0'), (arg_type, arg_val), ('int64_t', '0')])
                elif _join_has_spread or len(node.args) > 2:
                    # `os.path.join(d, *parts, suffix)` (a `*` spread mixed
                    # with fixed args, or 3+ args): the old 2-arg fast path
                    # BELOW silently dropped every arg past the second, and
                    # the spread pass-through handed the raw MojoList to
                    # `int_join` as if it were one path part. Real divergence
                    # found via `_resolve_test_relative_module`'s
                    # `os.path.join(d, *rel_parts, '__init__.mojo')` under
                    # stage2: the candidate path came out wrong, so a sibling
                    # import from a `stage2` CWD never resolved and every
                    # imported function became a weak stub. Build ONE
                    # MojoList of all parts (expanding spreads) and join it.
                    _jl = gen._new_temp('MojoList *')
                    gen._emit(f'  {_jl} = mojo_list_new();')
                    for _ja in node.args:
                        if isinstance(_ja, UnaryOp) and _ja.op == '*':
                            _jat, _jav = gen.lower_expr(_ja.operand)
                            if _jat == 'MojoList *':
                                _jcat = gen._call_expr(
                                    'MojoList *', 'mojo_list_concat',
                                    [('MojoList *', _jl), ('MojoList *', _jav)])
                                gen._emit(f'  {_jl} = {_jcat};')
                                continue
                            _javs = _jav if _jat == 'char *' else gen._stringify_value(_jat, _jav)
                            gen._emit_call('void', '', 'mojo_list_append_str',
                                           [('MojoList *', _jl), ('char *', _javs)])
                        else:
                            _jat, _jav = gen.lower_expr(_ja)
                            _javs = _jav if _jat == 'char *' else gen._stringify_value(_jat, _jav)
                            gen._emit_call('void', '', 'mojo_list_append_str',
                                           [('MojoList *', _jl), ('char *', _javs)])
                    gen._emit_call('int64_t', t, 'int_join_list', [('int64_t', '0'), ('MojoList *', _jl)])
                else:
                    # os.path.join(a, b) — two path args
                    arg_type, arg_val = gen.lower_expr(node.args[0])
                    arg2_type, arg2_val = gen.lower_expr(node.args[1])
                    gen._emit_call('int64_t', t, 'int_join', [('int64_t', '0'), (arg_type, arg_val), (arg2_type, arg2_val)])
                return 'int64_t', t
            elif outer_member == 'exists' and len(node.args) == 1:
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('int', 'int_exists', [('int64_t', '0'), (arg_type, arg_val)])
                return 'int', t
            elif outer_member == 'isdir' and len(node.args) == 1:
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('int', 'int_isdir', [('int64_t', '0'), (arg_type, arg_val)])
                return 'int', t
            elif outer_member == 'isabs' and len(node.args) == 1:
                # os.path.isabs(p) → check if first char is '/'
                arg_type, arg_val = gen.lower_expr(node.args[0])
                if arg_type not in ('char *', 'void *'):
                    arg_cast = gen._new_temp('char *')
                    gen._emit(f'  {arg_cast} = (char *){arg_val};')
                    arg_val = arg_cast
                t = gen._new_temp('int')
                # `p != 0 && *p == '/'` short-circuits (must not deref a
                # NULL p), so it CANNOT be a compact C `&&` expression —
                # -fgimple rejects `_t = (p != 0 && *p == '/')` ("expected
                # expression before '('"). Branch: p non-null (via
                # _ensure_bool_cond's pointer check) gates the deref.
                bb_true = gen._new_bb(); bb_false = gen._new_bb(); bb_merge = gen._new_bb()
                nonnull = gen._ensure_bool_cond('char *', arg_val)
                gen._emit(f'  if ({nonnull}) goto {bb_true}; else goto {bb_false};')
                gen._emit_label(bb_true)
                # GIMPLE: a memory deref must be its own statement — load
                # *p into a char temp, then compare (a bare `_t = (*p ==
                # '/')` is rejected: "expected expression before '('").
                ch = gen._new_temp('char')
                gen._emit(f'  {ch} = *{arg_val};')
                # GIMPLE: compare as ints (a char-vs-char-literal compare
                # is a "mismatching comparison operand types").
                ci = gen._new_val('int', f'(int){ch}')
                eq = gen._new_temp('_Bool')
                gen._emit(f'  {eq} = {ci} == 47;')
                gen._emit(f'  {t} = (int){eq};')
                gen._emit(f'  goto {bb_merge};')
                gen._emit_label(bb_false)
                gen._emit(f'  {t} = (int)0;')
                gen._emit_label(bb_merge)
                return 'int', t
            elif outer_member == 'normpath' and len(node.args) == 1:
                # os.path.normpath(p) → stub: return p unchanged
                arg_type, arg_val = gen.lower_expr(node.args[0])
                return arg_type, arg_val
            elif outer_member == 'isfile' and len(node.args) == 1:
                # os.path.isfile(p) — real S_ISREG stat check (int_isfile in
                # runtime/fire_runtime.c), mirroring the isdir/exists cases
                # above. Previously a literal-0 stub ("not a file"), which
                # made `if not os.path.isfile(p): continue` unconditional —
                # every loop iteration silently skipped (found via
                # Tools/unicode/gencodec.py's convertdir()).
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('int', 'int_isfile', [('int64_t', '0'), (arg_type, arg_val)])
                return 'int', t
            elif outer_member == 'relpath' and len(node.args) >= 1:
                # os.path.relpath(p) → stub: return p unchanged
                arg_type, arg_val = gen.lower_expr(node.args[0])
                for a in node.args[1:]: gen.lower_expr(a)
                return arg_type, arg_val
            elif outer_member == 'realpath' and len(node.args) == 1:
                # os.path.realpath(p) — real runtime support via POSIX
                # realpath(3) (int64_t_realpath, already used by the
                # pathlib.Path.resolve() case above — see its docstring).
                # This os.path.* dispatch had every OTHER sibling
                # (basename/splitext/split/.../isfile/relpath) but no case
                # for 'realpath' at all, so it fell all the way through
                # this whole os.path.* chain (func.obj is the MemberExpr
                # `os.path`, not a plain IdentExpr, so the generic
                # "module_name.method(...)" dispatch just below never
                # matches either) to the final scalar-receiver fallback,
                # which stubs any unrecognized method to a literal `0` --
                # every self-hosted `os.path.realpath(x)` silently returned
                # NULL. Root cause of BLOW.md's ~15.8 GB/180 G-instruction
                # fixed compile-time cost: `_is_selfhost_source_dir`
                # (mojo/backend_gimple/module_gen.py) compares two
                # `os.path.realpath(...)` results, both of which came back
                # 0 == 0 (trivially equal) for ANY input directory once
                # compiled, so it always classified every compile as
                # "compiling the compiler's own source" and re-tokenized
                # this project's entire source tree on every invocation.
                arg_type, arg_val = gen.lower_expr(node.args[0])
                t = gen._call_expr('char *', 'int64_t_realpath', [(arg_type, arg_val)])
                return 'char *', t

    # Handle module method calls: module_name.function(args)
    if isinstance(func.obj, gimple_ctypes.IdentExpr):
        module_name = func.obj.name
        method_name = func.member

        # `struct` module (binary pack/unpack). Guarded so a local variable
        # named `struct` (or a real Mojo `struct` type used as a value)
        # can't be hijacked: `struct` must not be a known local/param. The
        # name set IS the shared return-type table (see
        # mojo/middle/types.py) — the lowering's gate and the type estimator's
        # rows are one dict, so a method this branch accepts can never be one
        # `_quick_type` answers `int64_t` for. Keyword arguments are NOT
        # excluded here: `_struct_bind_args` binds the three names CPython
        # accepts and raises CPython's TypeError for the rest, which is both
        # correct and strictly better than letting the call fall through to
        # the generic receiver dispatch (that answered `0`).
        if (module_name == 'struct'
                and method_name in gimple_ctypes._STRUCT_MODULE_FN_RETVALS
                and module_name not in gen.var_types):
            return _lower_struct_module_call(gen, node, method_name)

        # Self-hosting bootstrap: a module-qualified call to one of this
        # compiler's OWN extracted sibling backend modules'
        # (`import gimple_gen_calls as ggc` etc.) top-level functions —
        # `ggc._lower_call(self, node)`, `gmg.gen_module_impl(self, stmts)`,
        # `ginf._dedup_variadic_externs(parts)`, …. The function-extraction
        # refactor turned ~300 former GimpleGen methods into thin
        # `return <alias>.<impl>(self, ...)` delegates; without this the
        # `<alias>` module handle is an opaque int64_t and every one of
        # those calls stubbed to 0, so the self-hosted `compile_to_gimple`
        # returned an empty `.ci`. Resolve to the same mangled C symbol a
        # bare-name call would use (the `ast_rewriter.rewrite` special case
        # below is the original, hand-written instance of this — now
        # generalized). Gated to this compiler's own `gimple*.py` sources
        # so it can never intercept a real stdlib module method.
        if _selfhost_sibling_member_kind(gen, module_name, method_name) is not None:
            # Re-dispatch as a BARE-name call: the alias qualifier is a
            # Python-import artifact only. `_lower_call` owns struct-ctor
            # allocation, default-argument padding, keyword ordering and
            # vararg packing (and falls through to `_lower_named_call` for a
            # plain function) — none of which a hand-rolled call here would
            # get right (the sibling impls have many defaulted params, and
            # re-exported AST-node types register a `Name *` return type
            # that would otherwise look like a function).
            _bare_node = gimple_ctypes.CallExpr(
                func=gimple_ctypes.IdentExpr(
                    name=method_name, line=getattr(node, 'line', 0)),
                args=list(node.args),
                kwargs=list(getattr(node, 'kwargs', None) or []))
            return gen._lower_call(_bare_node)

        # Check if this is a known module method
        if module_name == 're' and method_name == 'escape' and len(node.args) == 1:
            # re.escape(p) — escape regex metacharacters so `p` can be embedded
            # as a literal in a larger pattern. Previously there was NO
            # lowering at all, so the call fell to the generic
            # scalar-receiver stub (`int64_t.escape() stubbed`) and returned
            # 0: every `rf'\b{re.escape(name)}\b'` pattern silently lost the
            # name it was supposed to anchor on (16 sites across this
            # backend, e.g. _emit_stdlib_import_externs' qualified-symbol
            # rename and _find_generic_source's struct/generic scans).
            arg_type, arg_val = gen.lower_expr(node.args[0])
            if arg_type not in ('char *', 'void *'):
                # A boxed/opaque string field (`node.name`, a param the
                # self-hosted backend erased to int64_t) — cast the bits back
                # to char* so the call's pointer parameter type-checks, the
                # same cast every other imported-string arg site uses.
                arg_cast = gen._new_temp('char *')
                gen._emit(f'  {arg_cast} = (char *){arg_val};')
                arg_type, arg_val = 'char *', arg_cast
            t = gen._call_expr('char *', 'mojo_re_escape', [(arg_type, arg_val)])
            return 'char *', t
        if module_name == 're' and method_name == 'sub':
            # re.sub(pattern, callback, src) → mojo_re_sub_fn(pattern, callback, env, src)
            if len(node.args) >= 3:
                cb_arg  = node.args[1]
                src_type, src_val = gen.lower_expr(node.args[2])
                if src_type not in ('char *', 'void *'):
                    src_cast = gen._new_temp('char *')
                    gen._emit(f'  {src_cast} = (char *){src_val};')
                    src_val = src_cast
                # A compile-time-foldable pattern (a literal, or a
                # concatenation/repetition of literals and already-folded
                # locals — see _try_const_fold_str) routes through this
                # codegen's own regex engine (mojo_regex_sub_fn) instead
                # of mojo_re_sub_fn's POSIX regcomp/regexec: POSIX ERE
                # has no \s/\S/\d/\w shorthand classes and no non-greedy
                # quantifiers, so any such pattern makes regcomp() fail,
                # and mojo_re_sub_fn silently returns its input UNCHANGED
                # on a compile failure — found via fire_compiler.py's own
                # replace_multiline_strings, whose `"""[\s\S]*?"""`-style
                # patterns (built as `lit + _dq + lit + _dq`, not a bare
                # literal, hence not caught by the simpler _regex_patterns
                # `X = re.compile("...")` scan used for .finditer()) were
                # silently never replacing anything, leaving a
                # multi-line docstring to be split into physical lines
                # and mis-tokenized one line at a time.
                folded_pattern = gen._try_const_fold_str(node.args[0])
                info = None
                if folded_pattern is not None:
                    info = gen._regex_progs.get(_gmm_as_str(folded_pattern))
                    if info is None:
                        try:
                            prog_id = f"re{len(gen._regex_progs)}"
                            info = gimple_ctypes.regex_compile.compile_pattern(folded_pattern, prog_id)
                            gen._regex_progs[folded_pattern] = info
                        except Exception as e:
                            # Not every real regex feature is implemented by this
                            # codegen's own engine (e.g. lookahead `(?=...)`, used
                            # by gimple_codegen.py's own inout/borrowed/... keyword
                            # pattern) — fall back to mojo_re_sub_fn (POSIX) below
                            # rather than letting compile_pattern's exception
                            # propagate. That propagation previously blew up an
                            # ancestor module's entire compile partway through
                            # (caught far up by _compile_imported_module's own
                            # generic except-and-rollback), which discarded that
                            # attempt's whole output — including any *other*,
                            # perfectly good regex declarations it had already
                            # emitted — while _regex_progs_defined (not part of
                            # that rollback) kept remembering them as "already
                            # emitted," so no later successful recompile ever
                            # emitted them either: real declarations silently
                            # missing from the final file for patterns that had
                            # nothing to do with the one that actually failed.
                            info = None
                            gimple_ctypes._debug_note(f're.sub compile-time regex compile failed for {folded_pattern!r}', e)
                is_callback = gen._re_sub_repl_is_callback(cb_arg)
                if info is not None:
                    prog_local = gen._new_val('const ReNode *', info['prog_var'])
                    ranges_local = gen._new_val('const ReRange *', info['ranges_var'])
                    classinfo_local = gen._new_val('const ReClassInfo *', info['classinfo_var'])
                    t = gen._new_temp('char *')
                    if is_callback:
                        fn_ptr_t, env_t = gen._lower_re_sub_callback(cb_arg)
                        gen._emit(f'  {t} = mojo_regex_sub_fn ({prog_local}, {ranges_local}, {classinfo_local}, '
                                   f'{info["root"]}, {info["ngroups"]}, {fn_ptr_t}, {env_t}, {src_val});')
                    else:
                        repl_type, repl_val = gen.lower_expr(cb_arg)
                        if repl_type not in ('char *', 'void *'):
                            repl_cast = gen._new_temp('char *')
                            gen._emit(f'  {repl_cast} = (char *){repl_val};')
                            repl_val = repl_cast
                        gen._emit(f'  {t} = mojo_regex_sub_str ({prog_local}, {ranges_local}, {classinfo_local}, '
                                   f'{info["root"]}, {info["ngroups"]}, {repl_val}, {src_val});')
                    return 'char *', t
                pat_type, pat_val = gen.lower_expr(node.args[0])
                # pattern/src may arrive as int64_t string handles; mojo_re_sub_fn
                # takes char * (passing an int is a -Wint-conversion error on GCC 14+).
                # Extract casts to temps (GIMPLE requires SSA values in call args).
                if pat_type not in ('char *', 'void *'):
                    pat_cast = gen._new_temp('char *')
                    gen._emit(f'  {pat_cast} = (char *){pat_val};')
                    pat_val = pat_cast
                t = gen._new_temp('char *')
                if is_callback:
                    fn_ptr_t, env_t = gen._lower_re_sub_callback(cb_arg)
                    gen._emit(f'  {t} = mojo_re_sub_fn ({pat_val}, {fn_ptr_t}, {env_t}, {src_val});')
                else:
                    repl_type, repl_val = gen.lower_expr(cb_arg)
                    if repl_type not in ('char *', 'void *'):
                        repl_cast = gen._new_temp('char *')
                        gen._emit(f'  {repl_cast} = (char *){repl_val};')
                        repl_val = repl_cast
                    gen._emit(f'  {t} = mojo_re_sub_str ({pat_val}, {repl_val}, {src_val});')
                return 'char *', t

        # shlex.join(iterable) — a *module-level* function (one arg: the
        # iterable), not a string method. Without this, `func.obj` being
        # the opaque, unresolved `shlex` module reference (an untyped
        # global that defaults to 0/NULL) fell through to the generic
        # char*.join() dispatch below, treating the module reference
        # itself as the separator string — `mojo_str_join(NULL, parts)`
        # returns "" unconditionally regardless of `parts`, silently
        # dropping every element. See
        # bugs/CODEGEN_map_over_untyped_param_arg.md (the `shlex.join(map(str,
        # args))` repro this surfaced in) — mojo_shlex_join is a real
        # runtime helper (space-joins its parts, POSIX-quoting each one
        # via shlex.quote's own rule) rather than reusing str.join's
        # separator-based mojo_str_join with a wrong/absent separator.
        if module_name == 'shlex' and method_name == 'join' and len(node.args) == 1:
            arg_type, arg_val = gen.lower_expr(node.args[0])
            # DESIGN.html R1: shared with all()/any()/enumerate()/
            # str.join()/bytes.join() - see _materialize_as_list.
            arg_val = gen._materialize_as_list(arg_type, arg_val)
            t = gen._call_expr('char *', 'mojo_shlex_join', [('MojoList *', arg_val)])
            return 'char *', t

        # os.getcwd() -> char* (runtime helper int_getcwd, a real getcwd(3)
        # call). This call shape had NO lowering case anywhere in this file
        # (or gimple_gen_exprs.py/gimple_gen_calls.py — confirmed via a full
        # grep for "getcwd" across every gimple_gen_*.py before adding this),
        # despite int_getcwd already existing and being correctly implemented
        # in runtime/fire_runtime.c and even documented as "looks correct" in
        # an earlier round of this investigation. With no case here, `os.
        # getcwd()` fell all the way through to the generic opaque-module-
        # call fallback, which stubs an UNRECOGNIZED module method call to a
        # bare `int64_t 0` — not a boxing/type-inference bug at all: the
        # runtime function was simply never called. That explains this
        # session's `len(os.getcwd())` reading back as exactly 0 self-hosted
        # (len() on a NULL char* returns 0) while every OTHER os.getcwd()
        # call site in the SAME compile (e.g. gimple_codegen.py's module-
        # level `_SELFHOST_DIR = os.path.dirname(os.path.abspath(__file__))`
        # constant) got the right answer only because the python3 SHIM
        # evaluates those call sites directly in real CPython — this bug is
        # compiled-path-only and was invisible to every shim-only check.
        # Found via module_loader.py's `load_module_from_path`'s self-host
        # directory gate (`_selfhost_dir = os.path.dirname(os.path.
        # abspath(__file__))` compared against a candidate path derived
        # ultimately from `os.getcwd()`).
        if module_name == 'os' and method_name == 'getcwd' and not node.args:
            # int_getcwd's real runtime.c signature (and its gimple_codegen.py
            # _KNOWN_SIGS table entry) is genuinely `int64_t int_getcwd(int64_t)`
            # (a boxed char*, same convention as int_abspath/int_dirname just
            # above) -- declaring the call's OWN C return type 'char *' here
            # directly (this case's first version) left the emitted temp
            # declared char* while _emit_call still emits a bare
            # `_t = int_getcwd(0);` (int64_t-returning call assigned straight
            # into a char*-declared temp) -- a hard `-fgimple`
            # "makes pointer from integer without a cast" error, invisible to
            # every one of this session's earlier isolated repros because
            # THIS exact call only gets compiled via fire.py build's
            # generator-aware `compile_to_gimple_with_cpp` path (taken
            # because fire.py's own source mentions `yield`/`async def`),
            # never through the plainer `compile_to_gimple_cached` path this
            # session's manual repros all happened to exercise. Same explicit
            # int64_t-call-then-cast fix as abspath/dirname.
            t = gen._call_expr('int64_t', 'int_getcwd', [('int64_t', '0')])
            cast = gen._new_val('char *', f'(char *){t}')
            return 'char *', cast

        # os.listdir(path) -> real list[str] of directory entries (runtime
        # helper mojo_listdir, opendir/readdir, "."/".." excluded). This call
        # shape previously fell through every module-method case to the
        # generic opaque-receiver stub, which returned the `os` module marker
        # ITSELF (int64_t) as the "list" — a for-loop over it then hit the
        # runtime's not-a-registered-container fallback and silently ran zero
        # times (mojo_unsupported_iter). Found via Tools/unicode/gencodec.py:
        # `mapnames = os.listdir(dir)` / `for mapname in mapnames:`.
        if module_name == 'os' and method_name == 'listdir' and len(node.args) == 1:
            arg_type, arg_val = gen.lower_expr(node.args[0])
            if arg_type not in ('char *', 'void *'):
                arg_cast = gen._new_temp('char *')
                gen._emit(f'  {arg_cast} = (char *){arg_val};')
                arg_val = arg_cast
            t = gen._call_expr('MojoList *', 'mojo_listdir', [('char *', arg_val)])
            gen._elem_types[t] = 'char *'
            return 'MojoList *', t

        # sysconfig.get_config_var(name) — real Python signature returns
        # `str | None` (the build-config value for `name`, e.g.
        # "BUILD_GNU_TYPE"/"BUILD_DIR"), never int. Not previously
        # modeled anywhere in this codegen at all (no _KNOWN_SIGS/
        # module-dispatch entry) — the whole `module_name == 'sysconfig'`
        # shape simply fell through every case in this if/elif chain to
        # the generic unresolved-module-call default (int64_t), so a
        # value that's genuinely a pointer at runtime got typed as a
        # scalar. That's silently wrong on its own, and a hard
        # `-fgimple` "invalid operands to binary /" error the moment the
        # result feeds a pathlib `/` join (real repro: Tools/wasm/wasi/
        # __main__.py's module-level `BUILD_DIR = CROSS_BUILD_DIR /
        # sysconfig.get_config_var("BUILD_GNU_TYPE")`). This codegen has
        # no real sysconfig data (that's a whole separate, much bigger
        # "model libpython's build config" project) — stub to an empty
        # string via the same `_stub_result` convention every other
        # not-really-implemented-but-correctly-typed call in this file
        # uses, rather than pretending to implement it.
        if module_name == 'sysconfig' and method_name == 'get_config_var':
            for _a in node.args:
                gen.lower_expr(_a)
            return gen._stub_result('char *', gen._intern_string(''),
                                      'sysconfig.get_config_var() stubbed')

        if (module_name == 'gimple_codegen' and method_name in (
                'compile_to_gimple', 'compile_to_gimple_cached')):
            # gimple_codegen.compile_to_gimple(src, do_imports=False, filename="") → returns char*
            # compile_to_gimple_cached lowers to the SAME C runtime wrapper
            # (gimple_codegen_compile_to_gimple, runtime/fire_runtime.c):
            # caching is a Python-process concern; the compiled wrapper just
            # calls the in-binary native compile_to_gimple directly (same
            # output, uncached, no subprocess involved at all).
            if len(node.args) >= 1:
                src_type, src_val = gen.lower_expr(node.args[0])
                # Cast to char* if needed (legacy int-cast strings)
                # Extract casts to temps (GIMPLE requires SSA values in call args).
                if src_type not in ('char *', 'void *'):
                    src_cast = gen._new_temp('char *')
                    gen._emit(f'  {src_cast} = (char *){src_val};')
                    src_val = src_cast
                # do_imports/filename are almost always passed as KEYWORD args
                # at the real call site (`compile_to_gimple(src, do_imports=True,
                # filename=input_file)`, e.g. fire.py's own --dump handler) —
                # node.args is positional-only, so len(node.args) >= 2/3 was
                # never true for that shape and both silently defaulted to
                # False/"" here, regardless of what the caller actually passed.
                # That meant every self-hosted `--dump`/`--dump-full` lost its
                # transitive-import closure: the compiled binary always asked
                # this subprocess-fallback for a do_imports=False single-file
                # compile. Check node.kwargs too, positional args still win.
                node_kwargs = getattr(node, 'kwargs', None) or []
                kwarg_map = {_gmm_as_str(k): v for k, v in node_kwargs}
                # Extract do_imports if provided, default to 0 (false)
                do_imports_val = '0'
                if len(node.args) >= 2:
                    di_type, di_val = gen.lower_expr(node.args[1])
                    do_imports_val = di_val
                elif 'do_imports' in kwarg_map:
                    di_type, di_val = gen.lower_expr(kwarg_map['do_imports'])
                    do_imports_val = di_val
                # Extract filename if provided, default to ""
                filename_val = '""'
                if len(node.args) >= 3:
                    fn_type, fn_val = gen.lower_expr(node.args[2])
                    filename_val = fn_val
                elif 'filename' in kwarg_map:
                    fn_type, fn_val = gen.lower_expr(kwarg_map['filename'])
                    filename_val = fn_val
                # Bare `os.environ.get`, NOT `gimple_ctypes.os.environ`: the
                # ast_rewriter `os.environ.get(...)` -> `mojo_c_getenv(...)`
                # rule only matches `obj=IdentExpr('os')`, so the qualified
                # form stayed a real attr access on the opaque `os` module
                # marker and raised `AttributeError: environ` when a
                # self-hosted mojoc lowered fire.py's own
                # `gimple_codegen.compile_to_gimple(...)` call sites (in
                # `build_executable` / the `--dump` handler) — silently
                # truncating those functions from the output.
                # Always emit a call to the C runtime wrapper
                # (gimple_codegen_compile_to_gimple), never the native
                # `compile_to_gimple` symbol directly: the wrapper calls the
                # native in-binary `compile_to_gimple` itself unconditionally
                # now (its own former python3-subprocess fallback was
                # deleted once check-native-dumpfull, formerly check-noshim-
                # dumpfull, proved the native path byte-identical to the
                # python3-interpreted reference for fire.py's whole
                # transitive closure). This codegen used to pick between
                # emitting a call to the native symbol directly vs the
                # wrapper based on `os.environ.get('MOJO_NO_SHIM')` at
                # COMPILE time (of whichever process was generating this C —
                # the python3 reference interpreter or a self-hosted `mojoc`
                # compiling itself) — a real, confirmed source of whole-
                # program `--dump-full` divergence between the two, since
                # they'd pick different call-site text for the identical
                # source line. Always emitting the wrapper call sidesteps
                # that entirely: there is now only one dispatch decision,
                # made once, inside the wrapper itself.
                t = gen._new_val('char *', f"gimple_codegen_compile_to_gimple ({src_val}, {do_imports_val}, {filename_val})")
                return 'char *', t

        # Calls to this module's own compiled sibling modules'
        # top-level FUNCTIONS (`ast_rewriter.rewrite(...)`,
        # `ast_rewriter.rewrite_node(...)`, `mlir.type_to_c(...)`,
        # `regex_compile.compile_pattern(...)`) — a module-qualified
        # call. Without this they fell through to the generic
        # "int64_t.<method>() stubbed" path, returning 0/garbage in the
        # self-hosted binary (the module global is an opaque int64_t
        # the generic dispatch can't call): the compiled
        # compile_to_gimple's `stmts = ast_rewriter.rewrite(...)` came
        # back NULL, so gen_module saw an empty statement list and the
        # whole native .ci lost every function body. Resolve to the
        # same mangled C symbol a bare-name call would use.
        if (module_name == 'ast_rewriter' and method_name in ('rewrite', 'rewrite_node')):
            arg_pairs = [gen.lower_expr(a) for a in node.args]
            _csym = gen._func_csym(method_name)
            _ret = 'MojoList *' if method_name == 'rewrite' else 'int64_t'
            return _ret, gen._call_expr(_ret, _csym, arg_pairs)

        # Step C (compiled-path async/await codegen project):
        # `asyncio.run(f())` — the explicit top-level bridge from sync
        # to async code, mirroring real Python's own idiom
        # (`asyncio.run(main())`) and this project's own interpreter's
        # precedent (real asyncio itself drives myinterpreter.py's
        # MojoCoroutine the same way — see test_async_execution.py).
        # This is the ONLY place a compiled async function's result may
        # actually be driven to completion and consumed as a value —
        # reusing Step A's own scheduler API exactly as Step B's
        # (reverted) eager-execution branch briefly did, now correctly
        # gated behind this EXPLICIT driver call instead of firing on
        # every value-consuming reference to `f()` (see
        # bugs/CODEGEN_compiled_async_eager_execution_semantic_mismatch.md
        # — that bug's fix, 9a3a62b, deliberately left bare `x = f()`
        # (no `asyncio.run`) refused, and this still does not touch
        # that: `fname_raw in self._async_api` in _lower_call, a few
        # thousand lines below, is untouched and still raises for that
        # shape). Narrow shape only: exactly one argument, itself a
        # bare, param-less call to a function this module actually
        # compiled to the C++20 coroutine path (registered in
        # self._async_api by gen_module's async pre-pass) — composing
        # `asyncio.run(...)` around anything else (a non-call
        # expression, a call to an unsupported/uncompiled async
        # function, extra arguments) is an honest whole-module refusal
        # instead of guessing at a lowering.
        if module_name == 'asyncio' and method_name == 'run':
            inner = node.args[0] if len(node.args) == 1 else None
            # A bracket call to a nested async function/closure with
            # its OWN comptime bracket parameter(s), e.g.
            # test_asyncrt.mojo's `asyncio.run(test_asyncrt_add[1]
            # (10))` — see gen_module's "Async closures/functions
            # NESTED INSIDE A TOP-LEVEL FUNCTION" discovery pass /
            # _async_closure_api's 'comptime_params' entry. Unlike the
            # bare-name, param-less-only case just below (the existing,
            # narrower Step C shape), this narrow addition allows real
            # ordinary arguments too, threaded the same way the direct-
            # call site (_lower_call's own SubscriptExpr+IdentExpr
            # branch, a few thousand lines up) does — bracket args
            # first (in comptime_params order), then ordinary call
            # args, then any free-variable captures.
            if (len(node.args) == 1 and not getattr(node, 'kwargs', None)
                    and isinstance(inner, gimple_ctypes.CallExpr) and not getattr(inner, 'kwargs', None)
                    and isinstance(inner.func, gimple_ctypes.SubscriptExpr)
                    and isinstance(inner.func.obj, gimple_ctypes.IdentExpr)):
                _acl_key3 = (gen.current_func_name, inner.func.obj.name)
                _api3 = gen._async_closure_api.get(_acl_key3)
                if _api3 is not None and _api3.get('comptime_params'):
                    _cp_list3 = _api3['comptime_params']
                    _idx3 = inner.func.index
                    _elems3 = _idx3.elements if isinstance(_idx3, gimple_ctypes.TupleExpr) else [_idx3]
                    if len(_elems3) == len(_cp_list3):
                        # Ordinary args FIRST, then bracket (comptime)
                        # elements, then any trailing captures --
                        # matches the callee's REAL compiled signature
                        # order (see the sibling composition sites'
                        # identical fix/comment: _gen_cpp_async_unit
                        # emits `fn.params` before `extra_captures`,
                        # never the reverse).
                        _arg_pairs3 = [gen.lower_expr(a) for a in inner.args]
                        _arg_pairs3 += [gen.lower_expr(a) for a in _elems3]
                        for _cap_name3, _ in _api3['captures'][len(_cp_list3):]:
                            _arg_pairs3.append(gen.lower_expr(gimple_ctypes.IdentExpr(name=_cap_name3)))
                        return gen._emit_asyncio_run_drive(
                            _api3['base'], _api3['value_ctype'], _arg_pairs3)
            if (len(node.args) == 1 and not getattr(node, 'kwargs', None)
                    and isinstance(inner, gimple_ctypes.CallExpr)
                    and isinstance(inner.func, gimple_ctypes.IdentExpr)
                    and inner.func.name in gen._async_api
                    and not inner.args):
                api = gen._async_api[inner.func.name]
                return gen._emit_asyncio_run_drive(api['base'], api['value_ctype'], [])
            raise RuntimeError(
                "cannot compile module: asyncio.run(...) is only "
                "supported for the shape `asyncio.run(<call to a "
                "supported, parameter-less compiled async function>)` "
                "-- async-awaits-async composition, arguments, or "
                "asyncio.run() of anything else is not supported yet "
                "-- falling back to interpreting this module from "
                "source instead")
        # A reference to `asyncio.sleep(...)` reaching THIS (ordinary,
        # non-coroutine-body) call-lowering path means it's being used
        # somewhere other than directly as `await asyncio.sleep(...)`
        # inside a compiled async function body (the only place
        # GimpleGen._cpp_stmt's own AwaitExpr case gives it real
        # meaning, translating it to a genuine co_await on Step A's
        # timer queue) — e.g. called without `await`, or from ordinary
        # sync code. There is no real `asyncio` module at compiled-
        # program runtime to fall back to (see _is_asyncio_sleep_call's
        # docstring), so honestly refuse rather than silently emitting
        # a nonsensical call to an undefined symbol.
        if module_name == 'asyncio' and method_name == 'sleep':
            raise RuntimeError(
                "cannot compile module: asyncio.sleep(...) is only "
                "supported directly as `await asyncio.sleep(...)` "
                "inside a compiled async function body -- falling "
                "back to interpreting this module from source instead")
        # Step F: same reasoning as the asyncio.sleep(...) refusal just
        # above, for asyncio.sock_recv(...) reaching this ordinary call-
        # lowering path (i.e. used without `await`, or outside a
        # compiled async function body) -- see _is_asyncio_sock_recv_
        # call's docstring.
        if module_name == 'asyncio' and method_name == 'sock_recv':
            raise RuntimeError(
                "cannot compile module: asyncio.sock_recv(...) is only "
                "supported directly as `await asyncio.sock_recv(<fd>)` "
                "inside a compiled async function body -- falling "
                "back to interpreting this module from source instead")

        # Generic module-qualified call to an ARBITRARY imported
        # module's plain top-level function (`base2.doubleval(21)`,
        # real: `from . import base2` then `base2.doubleval(...)`) —
        # the general case `_selfhost_sibling_member_kind` above only
        # covers this compiler's own 3 hardcoded internal sibling
        # modules for. Without this, `module_name` is an opaque
        # `int64_t` marker (see `_gen_stmt_FromImportStmt`'s "module
        # marker" branch a few thousand lines up) and the call fell all
        # the way through this function's generic scalar-receiver
        # dispatch, which matched `method_name` against unrelated
        # BUILTIN scalar-type method stubs by bare name coincidence
        # (`base2.doubleval(21)` renamed to `double` matched
        # `int64_t.double()`) — a silent WRONG VALUE, not a compile
        # error. See bugs/CODEGEN_link_mode_module_qualified_call_
        # silent_wrong_value.md.
        #
        # A prior attempt at this (2026-08-28, reverted) resolved
        # `method_name` directly against the shared, FLAT, bare-name-
        # keyed `func_return_types` table — which is exactly the
        # same-bare-name-collision hazard `bugs/hard/CODEGEN_same_
        # bare_name_struct_collision_across_modules.md` documents for
        # struct fields, and broke `make check-selfhost` for real
        # (`fire_compiler.py`'s own `re.compile(...)` silently called a
        # DIFFERENT, unrelated 2-argument `compile` elsewhere in the
        # self-hosted source). This version is safe against that
        # exact hazard: it registers the call's OWN, syntactically-known
        # module reference into `_own_imported_func_home` (via
        # `_note_own_func_home`, module-qualified) and resolves the C
        # symbol through `_func_csym`/`_func_qualifier`'s existing tier
        # system — the SAME qualifier-aware machinery every ordinary
        # `from X import f; f(...)` call already goes through — which
        # raises a loud, honest error on a genuine cross-module bare-
        # name collision instead of silently guessing (see
        # `_note_own_func_home`'s own `_AMBIGUOUS_FUNC_HOME` handling).
        #
        # Narrow guard, deliberately conservative: `module_name` must be
        # a REGISTERED import alias/marker (`_module_alias_names` —
        # covers both a bare `from . import SUBMODULE` marker and a
        # plain `import SUBMODULE as alias`), no keyword arguments (this
        # fallback, like the ast_rewriter/mlir/regex_compile cases
        # above, forwards only positional args), and `method_name` must
        # be independently confirmed — by actually reading and
        # regex-scanning the target module's OWN source, never guessed
        # — to be a plain (non-generic, non-overloaded, no sibling
        # struct of the same name) top-level `def`/`fn`, so this never
        # misfires on a name meant for a completely different
        # elaboration mechanism (generics, overloads, struct
        # construction) that some earlier, more specific branch in this
        # very function already owns.
        # Excluded entirely for this compiler's OWN self-hosting sources
        # (mirrors `_is_selfhost_sibling_alias`'s identical directory
        # gate): `_func_qualifier` deliberately returns '' (an
        # UNQUALIFIED bare symbol) for every function while compiling a
        # `_SELFHOST_DIR` file — self-hosting relies on flat, hand-
        # verified bare-name registration (see doc/ "self-host
        # hardcoded struct tables"), not module-qualified mangling.
        # `_note_own_func_home`/`_func_csym` still WORK in that mode
        # (returning the bare name), but calling `_call_expr` directly
        # here bypasses whatever separate bookkeeping the NORMAL bare-
        # name call path (`_lower_call`/`_lower_named_call`) performs to
        # get that bare symbol actually forward-declared/defined in the
        # self-hosted output — confirmed via a real regression: routing
        # `build_stdlib_dylib`'s `_imported_sigs`/`build` through this
        # branch during `imports.py`'s own self-host compile produced
        # `implicit declaration of function '_imported_sigs'` (no
        # forward decl ever emitted), where the pre-existing behavior
        # (falling through to whatever handled it before this branch
        # existed) at least compiled clean.
        _mgc_cur = getattr(gen, '_current_filename', None)
        _mgc_is_selfhost = False
        if _mgc_cur and _mgc_cur.endswith('.py'):
            _mgc_abs = gimple_ctypes.os.path.abspath(_mgc_cur)
            _mgc_is_selfhost = (_mgc_abs == gimple_codegen._SELFHOST_DIR
                                 or _mgc_abs.startswith(gimple_codegen._SELFHOST_DIR + '/'))
        if (not _mgc_is_selfhost
                and module_name in getattr(gen, '_module_alias_names', ())
                and not getattr(node, 'kwargs', None)):
            _mgc_info = gen.imported_symbols.get(module_name)
            _mgc_sub_ref = (_mgc_info.get('module')
                            if isinstance(_mgc_info, dict) else None) or module_name
            _mgc_path = None
            for _mgc_cand in gen._module_candidate_paths(_mgc_sub_ref):
                if gimple_ctypes.os.path.exists(_mgc_cand):
                    _mgc_path = _mgc_cand
                    break
            if _mgc_path:
                try:
                    _mgc_src = open(_mgc_path).read()
                except Exception:
                    _mgc_src = ''
                _mgc_name_re = gimple_ctypes.re.escape(method_name)
                _mgc_def_count = len(gimple_ctypes.re.findall(
                    rf'\b(?:fn|def)\s+{_mgc_name_re}\s*\(', _mgc_src))
                _mgc_is_plain_fn = (
                    _mgc_def_count == 1
                    and not gimple_ctypes.re.search(rf'\b(?:fn|def)\s+{_mgc_name_re}\s*\[', _mgc_src)
                    and not gimple_ctypes.re.search(rf'\bstruct\s+{_mgc_name_re}\s*(\[|\(|:)', _mgc_src))
                if _mgc_is_plain_fn:
                    # Re-dispatch as a BARE-name call through `_lower_call`
                    # (exactly `_selfhost_sibling_member_kind`'s own
                    # pattern above) rather than hand-rolling `_call_expr`
                    # here: `_lower_call`/`_lower_named_call` own ALL the
                    # supporting bookkeeping a plain call needs (forward
                    # declarations, default-argument padding, keyword
                    # ordering, vararg packing) — duplicating just the
                    # symbol-resolution half and skipping the rest is
                    # exactly what caused the self-host regression noted
                    # above.
                    gen._note_own_func_home(method_name, _mgc_sub_ref, record_scope=False)
                    _mgc_bare_node = gimple_ctypes.CallExpr(
                        func=gimple_ctypes.IdentExpr(
                            name=method_name, line=getattr(node, 'line', 0)),
                        args=list(node.args),
                        kwargs=list(getattr(node, 'kwargs', None) or []))
                    return gen._lower_call(_mgc_bare_node)

    ot, ov = gen.lower_expr(func.obj)
    # The receiver's RAW lowered pair, before the resolution blocks below
    # may retag `ot` (the classmethod-receiver block can retag an
    # int64_t-typed `cls` to `{Struct} *`). The generator-method call
    # branch needs this original scalar tag: a compiled @classmethod
    # GENERATOR's start function takes an opaque, never-read int64_t
    # `cls` placeholder in its receiver slot, so the raw int64_t pair is
    # what must be passed for it (see the branch's own comment).
    _recv_ot_raw, _recv_ov_raw = ot, ov
    # A receiver that lowers to a DEFERRED, uncalled bound-method value
    # (`self.name.rfind('.')` where `name` is a bare @property read —
    # pathlib/__init__.py's `PurePath.stem`) must be AUTO-INVOKED before
    # method dispatch: real Python evaluates `self.name` to its value,
    # then calls `.rfind(...)` on THAT. Left alone, the call fell through
    # to the generic unknown-receiver fallback which mangled
    # `{ot}_{method}` into a never-defined extern symbol
    # (`MojoBoundMethod_rfind`) — an undefined-symbol LINK failure.
    # Mirrors this file's own `_auto_invoke_bound_method_value`, already
    # used by the subscript/binary-operand/chained-member consumer paths
    # for the identical deferred-value shape; a stored local
    # (`f = self.b; f()`) is unaffected — it calls through the var path
    # (_lower_bound_method_call), never reaching this MemberExpr branch.
    if ot == 'MojoBoundMethod *':
        ot, ov = _auto_invoke_bound_method_value(gen, ov)
    method = func.member

    if (method == '__next__' and not node.args
            and not getattr(node, 'kwargs', None)
            and gen._get_actual_type(ot, ov) == 'MojoGenerator *'):
        api = gen._generator_var_api.get(ov)
        if api is not None:
            return ggc._lower_generator_next(gen, ov, api)

    # struct.Struct instance namespace — receiver holds a compiled
    # `MojoStructFmt *`. Deliberately TOTAL (not gated on a method-name
    # whitelist that falls through): see _lower_struct_attr_call.
    if ot == 'MojoStructFmt *':
        if method in ('pack', 'unpack', 'unpack_from', 'pack_into',
                      'iter_unpack'):
            return _lower_struct_instance_method(gen, ov, method, node)
        return _lower_struct_attr_call(gen, method, node)

    # ── Awaitable protocol (Future/Event) — sync (non-coroutine) call sites ──
    # gimple_gen_coro.py's `_rewrite_async_expr` already rewrites
    # `create_future()` / `Event()` / `.set_result(v)` / `.set()` / `.done()`
    # / `.is_set()` / `.clear()` to the A3 runtime shims
    # (runtime/mojo_coro_gen.c) INSIDE an async coroutine body. asyncio's own
    # ORDINARY methods touch the very same int64_t handles from plain
    # synchronous code — `Queue.put_nowait` → `_wakeup_next(waiters)` →
    # `waiter.set_result(None)`, `Queue.__init__`'s `self._finished =
    # Event()` / `self._finished.set()` — so the identical rewrite has to
    # fire here too or the handle is treated as an unknown-method scalar
    # stub and the two paths disagree (anchor: bugs/COMPILE_FAIL_asyncio_
    # queues.md gap 1).
    #
    # Safety scoping:
    #   * Only when this module actually emitted a stack-switch coroutine
    #     unit (`_stackswitch_coro_c_units`) — that is exactly the condition
    #     under which gimple_module_gen.py emits the `extern` decls for
    #     these shims, and no coroutine-free module ever needs them.
    #   * Never when the receiver is a compiled struct that itself defines a
    #     same-named method (a real user class with its own `.set()` /
    #     `.done()` still dispatches normally below).
    # The Future/Event API names are otherwise unambiguous: no `.mojo`
    # source and no non-asyncio stdlib module calls them (grep-confirmed),
    # and the runtime shims are callable from any C context.
    if (os.environ.get('MOJO_CORO', 'stackswitch') != 'cpp'
            and (getattr(gen, '_stackswitch_coro_c_units', None)
                 or getattr(gen, '_native_future_bridge', False))
            and not getattr(node, 'kwargs', None)):
        _fut_sn = (gimple_exprtypes._struct_name_of(ot)
                   if isinstance(ot, str) and ot.endswith(' *') else None)
        _fut_user_method = bool(
            _fut_sn and _fut_sn in gen.struct_field_types
            and method in (gen.struct_field_types.get(_gmm_as_str(_fut_sn)) or ()))
        # A container receiver's `.set()` / `.clear()` is dict/set/list
        # mutation, never an Event op. `ot` is often just `int64_t` for a
        # boxed module global (e.g. gimple_gen_coro.py's own `_PARAM_NAMES:
        # dict = {}` / `_TASK_VARS: set = set()`), so also consult the
        # semantic type of a bare-name / `self.`-field receiver — otherwise
        # `_PARAM_NAMES.clear()` lowered to `__mojo_event_clear` and the
        # next `_PARAM_NAMES[k] = v` hit a wrecked handle (SIGBUS in
        # `mojo_dict_set_int`, only under MOJO_NO_SHIM=1).
        _fut_recv_sem = ot
        _fut_recv_obj = getattr(func, 'obj', None)
        if (not isinstance(_fut_recv_sem, str)
                or _fut_recv_sem not in ('MojoDict *', 'MojoList *', 'MojoSet *')):
            if isinstance(_fut_recv_obj, IdentExpr):
                _fut_recv_sem = (gen.var_types.get(_fut_recv_obj.name)
                                 or gen._global_var_types.get(_fut_recv_obj.name)
                                 or _fut_recv_sem)
            elif (isinstance(_fut_recv_obj, MemberExpr)
                  and isinstance(_fut_recv_obj.obj, IdentExpr)
                  and _fut_recv_obj.obj.name == 'self'
                  and gen._current_struct_name):
                _fut_recv_sem = (gen.struct_field_types.get(_gmm_as_str(gen._current_struct_name), {})
                                 .get(_fut_recv_obj.member) or _fut_recv_sem)
        _fut_container_recv = (isinstance(_fut_recv_sem, str)
                               and _fut_recv_sem in ('MojoDict *', 'MojoList *', 'MojoSet *'))
        if not _fut_user_method and not _fut_container_recv:
            if method == 'create_future' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_new', [])
            if method in ('Future', 'Event') and not node.args:
                shim = '__mojo_event_new' if method == 'Event' else '__mojo_future_new'
                return 'int64_t', gen._call_expr('int64_t', shim, [])
            if method in ('set', 'clear') and not node.args:
                shim = '__mojo_event_set' if method == 'set' else '__mojo_event_clear'
                gen._emit_call('void', '', shim, [('int64_t', ov)])
                return 'void', ''
            if method == 'is_set' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_event_is_set', [('int64_t', ov)])
            if method == 'done' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_done', [('int64_t', ov)])
            if method == 'result' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_result', [('int64_t', ov)])
            if method == 'set_result' and len(node.args) == 1:
                # `set_result(None)` carries a 0 payload; the awaiting
                # coroutine reads it back via __mojo_future_result. _emit_call
                # runs the backend's standard →int64_t arg coercion (the same
                # path the shim's registered int64_t param type drives on the
                # async side).
                _at, _av = gen.lower_expr(node.args[0])
                gen._emit_call('void', '', '__mojo_future_set_result',
                               [('int64_t', ov), (_at, _av)])
                return 'void', ''
            if method == 'set_exception' and len(node.args) == 1:
                _ea = node.args[0]
                _ename = None
                _emsg = None
                if (isinstance(_ea, gimple_ctypes.CallExpr)
                        and isinstance(_ea.func, gimple_ctypes.IdentExpr)):
                    _ename = _ea.func.name
                    if len(_ea.args) == 1 and isinstance(_ea.args[0], gimple_ctypes.StringLiteral):
                        _emsg = _ea.args[0]
                elif (isinstance(_ea, gimple_ctypes.IdentExpr)
                      and _ea.name[:1].isupper()
                      and (_ea.name.endswith('Error') or _ea.name.endswith('Exception'))):
                    _ename = _ea.name
                _tag = gen._exc_type_id(_ename) if _ename else 0
                if _emsg is not None:
                    _mt, _mv = gen.lower_expr(_emsg)
                else:
                    _mt, _mv = 'char *', '(char *)""'
                gen._emit_call('void', '', '__mojo_future_set_exception',
                               [('int64_t', ov), ('int64_t', str(_tag)), (_mt, _mv)])
                return 'void', ''
            if method == 'exception' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_exception', [('int64_t', ov)])
            if method == 'cancel' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_cancel', [('int64_t', ov)])
            if method == 'cancelled' and not node.args:
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_cancelled', [('int64_t', ov)])
            if method == 'set_running_or_notify_cancel' and not node.args:
                return 'int64_t', gen._call_expr(
                    'int64_t', '__mojo_future_set_running_or_notify_cancel', [('int64_t', ov)])
            if method == 'add_done_callback' and len(node.args) == 1:
                _ct, _cv = gen.lower_expr(node.args[0])
                _tag = ggc._future_done_callback_kind_tag(_ct)
                gen._emit_call('void', '', '__mojo_future_add_done_callback',
                               [('int64_t', ov), (_ct, _cv), ('int64_t', str(_tag))])
                return 'void', ''
            if method == 'remove_done_callback' and len(node.args) == 1:
                _ct, _cv = gen.lower_expr(node.args[0])
                _tag = ggc._future_done_callback_kind_tag(_ct)
                return 'int64_t', gen._call_expr('int64_t', '__mojo_future_remove_done_callback',
                                                 [('int64_t', ov), (_ct, _cv), ('int64_t', str(_tag))])

    # `cls.method(...)` inside a @classmethod: resolve `cls` to the struct
    # enclosing the current classmethod (current_func_name is e.g.
    # `TypeLattice_join_all`). Without this, `cls` lowers to a boxed
    # int64_t, `_struct_name_of('int64_t')` is 'int64_t', and `cls.join`
    # falls into the generic `mojo_obj_call1` dispatch (which for a class
    # ref is a NULL obj -> miscompile to mojo_str_join). Route it to the
    # struct-method call so `TypeLattice_join(...)` is emitted.
    # NOTE: key off `ov` (the lowered C name) rather than `func.obj.name`
    # — in the compiled binary, reading `.name` on a boxed IdentExpr
    # handle falls back to mojo_obj_getattr -> NULL, so an isinstance+name
    # check never fires; `ov` is the reliable `'cls'` value from lower_expr.
    #
    # Gate on `self.current_func_name in self._classmethod_names` too —
    # a bare `ov == 'cls'` match alone fires for ANY parameter/local
    # merely NAMED `cls`, not just a real classmethod's implicit first
    # argument. The descriptor protocol's `__get__(self, instance,
    # cls=None)` has exactly such a parameter: real Mojo/Python code
    # (`Lib/string/__init__.py`'s `_TemplatePattern.__get__` calling
    # `cls._compile_pattern()`, where `cls` is whatever class touched the
    # descriptor at the call site -- `Template` here, but in general
    # unknowable statically) would otherwise get `_cns` resolved from
    # `current_func_name`'s OWN enclosing struct (`_TemplatePattern`,
    # since it's a real struct-field-types member and the longest-prefix
    # loop below has no way to tell "the enclosing struct" apart from
    # "the struct this dynamically-typed value actually holds") and emit
    # a call to `_TemplatePattern__compile_pattern`, a symbol nothing
    # defines (`_compile_pattern` is only ever a method of `Template`) —
    # an undefined-symbol link failure, not a compile error, so it
    # slipped past every gcc-level check for a long time. `_classmethod_
    # names` (populated in gen_module's Pass 1b, exact-mangled-name match
    # like `_static_methods` — a known, accepted limitation for
    # overloaded methods, see `_static_methods`'s own callers) is only
    # populated for real `@classmethod`s plus the two dunders Python
    # treats as implicit classmethods (`__init_subclass__`/
    # `__class_getitem__`), so ordinary methods with a same-named
    # parameter no longer match.
    if (ov == 'cls' and gen.current_func_name
            and gen.current_func_name in gen._classmethod_names):
        # Derive the enclosing struct name from current_func_name (the
        # mangled `<Struct>_<method>` form). A single rsplit('_', 1) is
        # WRONG when the METHOD name itself contains an underscore —
        # `TypeLattice_join_all` (join_all is the method) rsplit to
        # 'TypeLattice_join', so the `_cns`/`f'{_cns}_{method}'` checks
        # below saw a phantom struct and never fired, and cls.join fell
        # through to the string-`.join` path (mojo_str_join) — a hard
        # segfault (parts = a class ref read as a list). Match the
        # LONGEST `_`-separated prefix of current_func_name that names a
        # real struct (in struct_field_types) or a compiled classmethod
        # (`f'{prefix}_{method}'` in func_return_types). Longest-first
        # so a struct whose own NAME contains `_` (e.g. My_Class) still
        # resolves to the full name, not its leading fragment.
        _cns = None
        _parts = gen.current_func_name.split('_')
        for _k in range(len(_parts), 0, -1):
            _cand = '_'.join(_parts[:_k])
            if (_cand in gen.struct_field_types
                    or f'{_cand}_{method}' in gen.func_return_types):
                _cns = _cand
                break
        # Accept both real structs AND plain helper classes (TypeLattice,
        # etc.) whose static/classmethods are compiled functions.
        if (_cns is not None
                and (_cns in gen.struct_field_types
                     or f'{_cns}_{method}' in gen.func_return_types)):
            ot = f"{_cns} *"

    # Check if the value is a temp variable — if so, get its real type from var_types
    if ov.startswith('_t') and ov in gen.var_types:
        ot = gen.var_types[ov]

    # Resolve actual type for int64_t-stored pointers (e.g. char* returned as int64_t)
    ot_orig = ot
    ot = gen._get_actual_type(ot, ov)
    # If _get_actual_type resolved int64_t → a pointer type (MojoDict*, MojoList*, etc.),
    # emit an explicit cast so ov is a properly-typed local — otherwise _emit_call will
    # see matching types and skip the coercion, leaving GCC with an int64_t where a
    # pointer is expected.
    if ot != ot_orig and ot.endswith(' *') and ot_orig == 'int64_t':
        ov_local = gen._ensure_local('int64_t', ov)
        ip_cast = gen._new_temp('int64_t')
        np_cast = gen._new_temp(ot)
        gen._emit(f"  {ip_cast} = (int64_t){ov_local};")
        gen._emit(f"  {np_cast} = ({ot}){ip_cast};")
        if ov in gen._dict_val_types:
            gen._dict_val_types[np_cast] = gen._dict_val_types[ov]
        ov = np_cast

    # Try to resolve the actual type of the receiver by inspecting the
    # member-expression chain (e.g. self.items → look up items's field type
    # on self's struct).  Runs unconditionally so every struct field access
    # gets a chance at the real type before the method-dispatch logic below.
    if isinstance(func.obj, gimple_ctypes.MemberExpr):
        resolved_type = gen._resolve_member_expr_type(func.obj)
        if resolved_type:
            ot = resolved_type
        elif ot.endswith(' *') and gimple_exprtypes._struct_name_of(ot) not in gen.struct_field_types:
            # Member expression on an unknown struct — we can't resolve
            # the field type, so treat the receiver as an opaque int64_t
            # to enable the container-method coercion below (e.g. for
            # self.items.append(Y) where items's List type is untracked).
            ov_local = gen._ensure_local(ot, ov)
            ip = gen._new_temp('int64_t')
            gen._emit(f'  {ip} = (int64_t){ov_local};')
            ot = 'int64_t'
            ov = ip
    # compiled generator METHOD on obj's struct type (self._generator_
    # method_api, keyed by (struct_name, method_name) — see that dict's
    # docstring in __init__) — constructs the coroutine, binding `self`
    # to obj, via the C++20-emitted `<base>_start(self, args...)`,
    # mirroring the free-function generator call check in _lower_call
    # (`fname_raw in self._generator_api`) but routed through THIS
    # method-call path since the receiver is `obj.method(...)`, not a
    # bare identifier call. Checked here, after `ot` has been resolved
    # to the receiver's real struct-pointer type by the blocks just
    # above, and before every other struct-method special case below —
    # a generator-method call must never fall through to the ordinary
    # StructName_method(...) lowering (there is no such ordinary C
    # function for it; see gen_module's Phase 2a skip for
    # _supported_generator_methods).
    #
    # The lookup also fires for a CLASS-LEVEL receiver (`Widget.make_
    # range(...)` on a compiled @classmethod generator): there `ot` is
    # the class-ref lowering (int64_t), which never ends in ' *', so
    # the pointer-typed branch below used to miss it entirely and the
    # call fell through to the ordinary ClassName_method(...) lowering
    # — a symbol gen_module's Phase 2a deliberately never emits for a
    # compiled generator method ("implicit declaration of function
    # 'Widget_make_range'"). The api entry's emitted signature carries
    # an opaque int64_t placeholder in the receiver slot (never read by
    # the unit — see _gen_cpp_generator_unit's cls handling), so passing
    # the class-ref value positionally, exactly like the ordinary
    # classmethod branch below prepends `(ot, ov)`, is all the ABI
    # needs.
    _gm_struct_name = gimple_exprtypes._struct_name_of(ot) if isinstance(ot, str) and ot.endswith(' *') else None
    _gm_api = None
    if _gm_struct_name is not None:
        _gm_api = gen._generator_method_api.get((_gm_struct_name, method))
    elif (isinstance(func.obj, gimple_ctypes.IdentExpr)
            and func.obj.name not in gen.var_types
            and func.obj.name not in gen._compiled_modules
            and ot in ('int', 'int64_t')):
        _gm_api = gen._generator_method_api.get((func.obj.name, method))
    if _gm_api is not None:
        arg_pairs = [gen.lower_expr(a) for a in node.args]
        # A compiled @staticmethod GENERATOR has NO receiver slot: its start
        # signature's slot 0 is the method's first REAL parameter, so
        # prepending the class-ref here (which every other receiver-carrying
        # generator method needs) is a wrong-arity call. The api entry's
        # `receiver` key — fire_compiler.method_receiver_kind's verdict,
        # recorded at registration — is the authority; a MISSING key is
        # refused rather than guessed, because guessing wrong here is a
        # silent argument shift.
        _gm_rcv = _gm_api.get('receiver', _MISSING)
        if _gm_rcv is _MISSING:
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"generator method {method!r} has no recorded `receiver` in "
                "its api entry, so its call arity cannot be determined")
        if _gm_rcv == '':
            all_args = list(arg_pairs)
        # A compiled @classmethod GENERATOR's start function declares its
        # receiver slot as an opaque, never-read int64_t `cls` placeholder
        # (see gimple_cpp_async.py's param_ctypes cls handling — the unit
        # resolves every `cls.<...>` access purely by NAME, never by
        # reading the value). Slot 0 of a registered generator-method
        # start signature is 'int64_t' exactly when the method is such a
        # classmethod (an ordinary `self` generator's slot 0 is the real
        # `{Struct} *`; gimple_cpp_async refuses any other first param).
        # When the receiver ALSO lowered to a SCALAR (the `cls.split(data)`
        # shape inside another classmethod: `cls` is a plain int64_t C
        # parameter), pass that raw pair straight through. Passing the
        # post-resolution pair instead would coerce the struct-POINTER-
        # tagged type into the int64_t slot via
        # _ensure_local('{Struct} *', 'cls') — materializing a
        # `{Struct} *`-declared temp from an int64_t scalar ("assignment
        # to '_Extra *' from 'int64_t' makes pointer from integer without
        # a cast", zipfile's _Extra.strip calling cls.split(data)). A
        # class-level call (`Widget.make_range(...)`) already lowers its
        # receiver to int64_t so this swap is a no-op there, and a genuine
        # instance receiver (`obj.split(data)`) keeps the struct-pointer
        # pair below, whose ptr->int64_t coercion is legal C.
        elif (_recv_ot_raw in ('int', 'int64_t')
              and _gm_api.get('params')
              and _gm_api['params'][0] == 'int64_t'):
            all_args = [('int64_t', _recv_ov_raw)] + arg_pairs
        else:
            all_args = [(ot, ov)] + arg_pairs
        # Pad missing trailing params with keyword args / real
        # defaults — see the identical free-function generator-call
        # padding in _lower_call's `fname_raw in self._generator_api`
        # branch for the full rationale (same root cause: a keyword
        # or defaulted argument was silently dropped, producing "too
        # few arguments to function '<base>_start'"). `self` occupies
        # slot 0 here, so padding starts from `all_args`, not
        # `arg_pairs`.
        _gm_kwargs = getattr(node, 'kwargs', []) or []
        _gm_expected = gen.func_param_types.get(f"{_gm_api['base']}_start", [])
        if _gm_expected and len(all_args) < len(_gm_expected):
            # Explicit loop, NOT `{kn: gen.lower_expr(ke) for kn, ke in
            # _gm_kwargs}` — the comprehension's tuple-unpacked key `kn`
            # erases to int64_t (the pointer-decimal key trap) and the
            # comprehension itself is the documented self-host hazard.
            _gm_kwarg_dict = {}
            for _gm_kn, _gm_ke in _gm_kwargs:
                _gm_kwarg_dict[_gmm_as_str(_gm_kn)] = gen.lower_expr(_gm_ke)
            _gm_kwarg_values = list(_gm_kwarg_dict.values())
            _gm_dflts = gen._func_param_defaults.get(f"{_gm_api['base']}_start", [])
            while len(all_args) < len(_gm_expected):
                if _gm_kwarg_values:
                    all_args.append(_gm_kwarg_values.pop(0))
                    continue
                # -1 shifts BOTH the total-param count and the missing
                # slot index past `self`: `self` occupies slot 0 in
                # all_args but has no entry in param_defaults (defaults
                # are keyed by the ORIGINAL Python params, which exclude
                # `self`). The shared helper applies the trailing-run
                # offset — plain `_gm_dflts[_pos]` indexing missed every
                # time once a leading required non-self param exists
                # (`def m(self, n, step=2)` called as `obj.m(5)` padded
                # step with 0 instead of 2).
                _pos = len(all_args) - 1
                _dv = gimple_exprtypes._trailing_default_at(
                    _gm_dflts, len(_gm_expected) - 1, _pos)
                if _dv is not None:
                    all_args.append(ggc._default_expr_to_pair(gen, _dv))
                else:
                    all_args.append(('int', '0'))
        else:
            for _, _ke in _gm_kwargs:
                gen.lower_expr(_ke)
        t = gen._call_expr('MojoGenerator *', f"{_gm_api['base']}_start", all_args)
        gen._generator_var_api[t] = _gm_api
        return 'MojoGenerator *', t

    # ── Builtin-`dict` subclass container delegation ─────────────────────
    # A user struct whose transitive bases bottom out at builtin `dict`
    # (see gen_module_impl's `_dict_subclass_structs`) carries a hidden
    # `_data: MojoDict *` backing store. `.get()/.keys()/.values()/
    # .items()/.update()/.pop()/.setdefault()/.clear()` on such an instance
    # are real inherited `dict` methods — route them at `inst->_data`,
    # exactly like `d[k]` / `k in d` / `len(d)` already do — UNLESS this
    # struct (or a local base up its MRO) defines its own override, in
    # which case ordinary struct-method dispatch below wins. Counter /
    # OrderedDict / defaultdict use these heavily. See
    # bugs/COMPILE_FAIL_collections___init__.md. Checked here, right after
    # `ot` has been resolved to the receiver's real struct-pointer type
    # and BEFORE every generic fallback (opaque-int coerce, the
    # `_sn not in func_return_types` mojo_obj_call1 stub, struct-method
    # dispatch) that would otherwise mis-lower an inherited container call.
    if isinstance(ot, str) and ot.endswith(' *'):
        _dsub_m = gen._dict_subclass_of(ot)
        if (_dsub_m
                and method in ('get', 'keys', 'values', 'items',
                               'update', 'pop', 'setdefault', 'clear')
                and not gen._dict_subclass_defines(_dsub_m, method)):
            _dsub_dp = gen._new_val('MojoDict *', f"{ov}->_data")
            return gen._lower_dict_method(_dsub_dp, method, node.args)
        # ── Builtin-`bytes` subclass method delegation ──────────────────
        # An inherited bytes method (`.decode`/`.hex`/`.startswith`/
        # `.split`/`.replace`/`.strip`/`.find`/`.count`/...) on a
        # `class X(bytes)` instance routes to the backing MojoBytes,
        # unless the subclass defines its own override. See
        # bugs/COMPILE_FAIL_zipfile___init__.md.
        _bsub_m = gen._bytes_subclass_of(ot)
        if (_bsub_m
                and method in ('decode', 'hex', 'startswith', 'endswith',
                               'find', 'index', 'rfind', 'count', 'split',
                               'rsplit', 'splitlines', 'replace', 'strip',
                               'lstrip', 'rstrip', 'lower', 'upper', 'join',
                               '__len__', '__contains__')
                and not gen._struct_defines_method(_bsub_m, method)):
            _bsub_bp = gen._new_val('MojoBytes *', f"{ov}->_data")
            return gen._lower_bytes_method(_bsub_bp, method, node.args, node.kwargs)

    # ── Class/static method call: ClassName.method(args) → ClassName_method(args) ──────
    # Must intercept BEFORE the opaque-int coerce below, which would misidentify
    # 'join' as a string method and corrupt the class ref.
    # The historical gate only matched `ot == 'int'` + `name in struct_field_types`.
    # Two gaps in it, both of which made a REAL classmethod call silently fall
    # through to the opaque-int coerce / string-`.join` special case below and
    # miscompile:
    #   (a) a class ref lowers to ('int64_t', 0) (see _lower_IdentExpr's class-ref
    #       branch), never 'int' — so the `ot == 'int'` check never fired for a
    #       genuine classmethod call at all;
    #   (b) a classmethod that is a REAL compiled function
    #       (`ClassName_method` ∈ func_return_types) must be resolved even when
    #       the class's struct_field_types entry is empty of that method.
    #       `TypeLattice.join(lt, rt)` (a plain helper class, no `join` field)
    #       fell through, got its receiver cast to `char *`, and resolved
    #       `.join` as a STRING method — `mojo_str_join(NULL, (MojoList*)lt)` —
    #       a hard segfault (parts = the "int64_t" type-string literal read as
    #       a list).
    # Fix: gate on the METHOD being a real compiled function (`ot` in
    # int/int64_t is the class-ref lowering), NOT on struct_field_types
    # membership — that's what distinguishes a real classmethod from a
    # hardcoded ctypes-structure shim (e.g. `_ReflectTable.in_dll` → a `char *`
    # dlsym stub in the unimplemented-helpers preamble, which is NOT in
    # func_return_types and must keep its historical opaque-int handling).
    if (isinstance(func.obj, gimple_ctypes.IdentExpr)
            and func.obj.name not in gen.var_types
            and func.obj.name not in gen._compiled_modules
            and f"{func.obj.name}_{gimple_ctypes._safe_name(method)}" in gen.func_return_types
            and ot in ('int', 'int64_t')):
        struct_name = func.obj.name
        # _static_methods is keyed by the historical BARE mangled name
        # (populated elsewhere from source, never module-qualified), so
        # the membership check below must use that bare form even though
        # the actual emitted call target is qualified.
        bare_mangled = f"{struct_name}_{gimple_ctypes._safe_name(method)}"
        mangled = _gmm_as_str(_ggf._struct_method_csym(gen, struct_name, method, ''))
        ret_type = gen.func_return_types.get(f"{struct_name}_{method}", 'char *')
        actual_args = [gen.lower_expr(a) for a in node.args]
        # Keyword arguments (e.g. TestReport.skipped(name=...)) are real
        # parameters — append their values after the positional ones so the
        # call arity matches the definition.
        for _kn, _kexpr in (getattr(node, 'kwargs', None) or []):
            actual_args.append(gen.lower_expr(_kexpr))
        # Only a REAL classmethod (`self._classmethod_names`, populated
        # from an explicit `@classmethod` decorator or the two dunders
        # Python makes implicit classmethods) gets the class-ref value
        # implicitly prepended as `cls`. This call-site shape
        # (`IdentExpr(ClassName).method(args)`) also covers the common
        # unbound-instance-method idiom used for pre-`super()`
        # cooperative-inheritance dispatch — e.g.
        # `Mailbox.__init__(self, path, factory, create)` (real code,
        # Lib/mailbox.py:634) or `IPv4Address.__eq__(self, other)` (real
        # code, Lib/ipaddress.py:1435) — where `method` is an ORDINARY
        # instance method and the caller is REQUIRED by Python semantics
        # to already pass `self` explicitly as `actual_args[0]`.
        # Unconditionally prepending `(ot, ov)` for every non-static
        # method (the historical behavior) double-counted `self` in that
        # case, producing a call with one extra argument ("too many
        # arguments to function ..."). `self._static_methods` no longer
        # needs an explicit branch here: a real staticmethod is never in
        # `_classmethod_names` either (the two sets are populated by
        # mutually-exclusive checks — see their construction beside
        # Pass 1b), so it already falls into the `else` (no-prepend)
        # branch, same end result as before for that case.
        if bare_mangled in gen._classmethod_names:
            arg_pairs = [(ot, ov)] + actual_args
        else:
            arg_pairs = actual_args
        # A call that omits a trailing DEFAULTED parameter (e.g.
        # `P.call(func)` where `P.call(func, args=None)`) must still pass
        # the full arity — P_call's C signature expects every param. Fill
        # the missing trailing args with None (0), mirroring how a missing
        # default is Python-`None` in the common self-host helper classes.
        _ptypes = (gen.func_param_types.get(_gmm_as_str(mangled))
                   or gen.func_param_types.get(f"{struct_name}_{method}"))
        if _ptypes and len(arg_pairs) < len(_ptypes):
            for _pad_i in range(len(arg_pairs), len(_ptypes)):
                arg_pairs.append(('int64_t', gen._new_val('int64_t', '(int64_t)0')))
        if ret_type == 'void':
            return gen._void_call(mangled, arg_pairs)
        t = gen._call_expr(ret_type, mangled, arg_pairs)
        return ret_type, t

    # ── .copy() on Copyable scalars is an identity operation ──────────────
    # Must happen BEFORE the opaque-int→container coercion block, which
    # would cast int64_t to char* and route through _lower_str_method.
    if method == 'copy':
        return ot, ov

    # `.get(<float literal>)` on an opaque/unresolved int64_t receiver is
    # never real dict.get(key) usage (dict keys are essentially never
    # float literals in real Python) -- it's the AsyncResult.get(timeout)/
    # Queue.get(timeout)-style call (e.g. multiprocessing's `res.get(0.02)`,
    # a module this compiler doesn't model so `res` falls back to opaque
    # int64_t). The unconditional MojoDict coercion below then cast the
    # float timeout to `char *` as if it were a string dict key --
    # `(char *)0.02` is not a valid C cast (float->pointer), a hard GIMPLE
    # "cannot convert to a pointer type" error, not just a wrong answer.
    # Exclude only this narrow, unambiguous shape; every other `.get()`
    # call keeps going through the dict-coercion path below unchanged.
    _get_float_timeout = (
        method == 'get' and len(node.args) == 1
        and isinstance(node.args[0], gimple_ctypes.FloatLiteral)
    )

    # ── Opaque int → coerce to appropriate container type FIRST ──────────
    # Must happen before container-type checks so the casted type is seen below.
    if ot in ('int', 'int64_t') and not _get_float_timeout and method in (
        'remove', 'clear',
    ):
        # `.remove()` is a real method on BOTH list and set; `.clear()` is
        # real on list, dict, AND set. On a boxed/opaque receiver these
        # can't be resolved by method name alone the way the other names
        # below can — the old code picked ONE static guess (set for
        # remove, list for clear) with no runtime check, so e.g. a boxed
        # value that was actually a MojoList* had `.remove(x)` routed to
        # `_lower_set_method`, which has no 'remove' case at all and
        # silently no-op'd instead of removing the element. Runtime-
        # dispatch via the kind registries instead (DESIGN.html R5). See
        # bugs/CODEGEN_boxed_method_name_list_set_ambiguity.md.
        ip = gen._new_temp('int64_t')
        ov_local = gen._ensure_local(ot, ov)
        if ot == 'int64_t':
            gen._emit(f"  {ip} = {ov_local};")
        else:
            gen._emit(f"  {ip} = (int64_t){ov_local};")
        result = gen._new_temp('int')
        if method == 'clear':
            bb_dict = gen._new_bb(); bb_not_dict = gen._new_bb()
            bb_set = gen._new_bb(); bb_not_set = gen._new_bb()
            bb_after = gen._new_bb()
            isd = gen._call_expr('int', 'mojo_is_registered_dict', [('int64_t', ip)])
            gen._emit(f"  if ({isd}) goto {bb_dict}; else goto {bb_not_dict};")
            gen._emit_label(bb_dict)
            dp = gen._coerce_to_type('int64_t', 'MojoDict *', ip)
            gen._emit(f"  mojo_dict_clear ({dp});")
            gen._emit(f"  {result} = 0;")
            gen._emit(f"  goto {bb_after};")
            gen._emit_label(bb_not_dict)
            iss = gen._call_expr('int', 'mojo_is_registered_set', [('int64_t', ip)])
            gen._emit(f"  if ({iss}) goto {bb_set}; else goto {bb_not_set};")
            gen._emit_label(bb_set)
            sp = gen._coerce_to_type('int64_t', 'MojoSet *', ip)
            gen._emit(f"  mojo_set_clear ({sp});")
            gen._emit(f"  {result} = 0;")
            gen._emit(f"  goto {bb_after};")
            gen._emit_label(bb_not_set)
            lp = gen._coerce_to_type('int64_t', 'MojoList *', ip)
            gen._emit(f"  mojo_list_clear ({lp});")
            gen._emit(f"  {result} = 0;")
            gen._emit_label(bb_after)
            return 'int', result
        # method == 'remove'
        if not node.args:
            return 'int', gen._new_val('int', '0')
        at, av = gen.lower_expr(node.args[0])
        bb_set = gen._new_bb(); bb_not_set = gen._new_bb(); bb_after = gen._new_bb()
        iss = gen._call_expr('int', 'mojo_is_registered_set', [('int64_t', ip)])
        gen._emit(f"  if ({iss}) goto {bb_set}; else goto {bb_not_set};")
        gen._emit_label(bb_set)
        sp = gen._coerce_to_type('int64_t', 'MojoSet *', ip)
        if at == 'char *':
            gen._emit_call('void', '', 'mojo_set_discard_str', [('MojoSet *', sp), ('char *', av)])
        else:
            av64 = gen._to_int64(at, av)
            gen._emit_call('void', '', 'mojo_set_discard_int', [('MojoSet *', sp), ('int64_t', av64)])
        gen._emit(f"  {result} = 0;")
        gen._emit(f"  goto {bb_after};")
        gen._emit_label(bb_not_set)
        lp = gen._coerce_to_type('int64_t', 'MojoList *', ip)
        if at == 'char *':
            gen._emit_call('void', '', 'mojo_list_remove_str', [('MojoList *', lp), ('char *', av)])
        else:
            gen._emit_call('void', '', 'mojo_list_remove_int', [('MojoList *', lp), (at, av)])
        gen._emit(f"  {result} = 0;")
        gen._emit_label(bb_after)
        return 'int', result

    # `.update()` on a boxed/opaque receiver is genuinely ambiguous by
    # method name alone: it's real on BOTH dict and set (unlike
    # 'keys'/'values'/'items'/'get', which only exist on dict among this
    # runtime's builtin containers). The old code here unconditionally
    # guessed MojoDict* — correct for `d.update(...)` but silently wrong
    # for `s.update(...)` on a set whose static type never resolved (e.g.
    # a `gen`/`self`-typed struct field the self-hosting param-typing
    # pass didn't reach): the set was force-cast to MojoDict* and its
    # `update(<iterable-of-scalars>)` argument, correctly materialized as
    # a MojoList* for a real set, got coerced against `MojoDict *` —
    # DESIGN.html R2's chokepoint refusal ("incompatible container
    # kinds"). Runtime-dispatch via the kind registries instead, exactly
    # like the 'clear'/'remove' ambiguity fix above (DESIGN.html R5). See
    # bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md Finding 4.
    if ot in ('int', 'int64_t') and not _get_float_timeout and method == 'update' and node.args:
        ip = gen._new_temp('int64_t')
        ov_local = gen._ensure_local(ot, ov)
        if ot == 'int64_t':
            gen._emit(f"  {ip} = {ov_local};")
        else:
            gen._emit(f"  {ip} = (int64_t){ov_local};")
        other_type, other_val = gen.lower_expr(node.args[0])

        def _emit_set_update_loop(sp):
            lv = gen._materialize_as_list(other_type, other_val)
            _elem = gen._elem_of(lv)
            _suf = gimple_ctypes.TypeLattice.list_suffix(_elem) if _elem else 'int'
            _len = gen._new_val('int64_t', f"mojo_list_len ({lv})")
            _idx = gen._new_val('int64_t', "(int64_t)0")
            bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_loop_after = gen._new_bb()
            gen._emit(f"  goto {bb_cond};")
            gen._emit_label(bb_cond)
            cond_t = gen._new_val('_Bool', f"{_idx} < {_len}")
            gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_loop_after};")
            gen._emit_label(bb_body)
            if _suf == 'str':
                _elv = gen._new_val('char *', f"mojo_list_get_str ({lv}, {_idx})")
                gen._emit(f"  mojo_set_add_str ({sp}, {_elv});")
            else:
                _elv = gen._new_val('int64_t', f"mojo_list_get_int ({lv}, {_idx})")
                gen._emit(f"  mojo_set_add_int ({sp}, {_elv});")
            _one = gen._new_val('int64_t', "(int64_t)1")
            _nxt = gen._new_val('int64_t', f"{_idx} + {_one}")
            gen._emit(f"  {_idx} = {_nxt};")
            gen._emit(f"  goto {bb_cond};")
            gen._emit_label(bb_loop_after)

        # A statically MojoList*/MojoSet*-typed argument can NEVER be a
        # valid dict.update() argument in this runtime (mojo_dict_update
        # only ever accepts another MojoDict*) — unambiguous set.update()
        # evidence, so skip the runtime dict/set dispatch and its dict
        # branch entirely. Emitting that dict branch anyway would call
        # `_coerce_to_type(other_type, 'MojoDict *', ...)` with a
        # STATICALLY incompatible container-kind pair, which trips
        # DESIGN.html R2's chokepoint at EMISSION time regardless of the
        # runtime `if` guarding which branch actually executes — the
        # chokepoint is a compile-time check on the C being generated,
        # not a runtime one.
        if other_type in ('MojoList *', 'MojoSet *'):
            sp = gen._coerce_to_type('int64_t', 'MojoSet *', ip)
            _emit_set_update_loop(sp)
            return 'int', gen._new_val('int', '0')

        bb_set = gen._new_bb(); bb_not_set = gen._new_bb(); bb_after = gen._new_bb()
        iss = gen._call_expr('int', 'mojo_is_registered_set', [('int64_t', ip)])
        gen._emit(f"  if ({iss}) goto {bb_set}; else goto {bb_not_set};")
        gen._emit_label(bb_set)
        sp = gen._coerce_to_type('int64_t', 'MojoSet *', ip)
        _emit_set_update_loop(sp)
        gen._emit(f"  goto {bb_after};")
        gen._emit_label(bb_not_set)
        dp = gen._coerce_to_type('int64_t', 'MojoDict *', ip)
        _od_sub = gen._dict_subclass_of(other_type)
        if _od_sub:
            other_val = gen._new_val('MojoDict *', f"{other_val}->_data")
            other_type = 'MojoDict *'
        other_val_cast = gen._coerce_to_type(other_type, 'MojoDict *', other_val)
        gen._emit(f"  mojo_dict_update ({dp}, {other_val_cast});")
        gen._emit_label(bb_after)
        return 'int', gen._new_val('int', '0')

    if ot in ('int', 'int64_t') and not _get_float_timeout and method in (
        'keys', 'values', 'items', 'get', 'pop', 'copy',
        'append', 'extend', 'sort', 'reverse',
        'add', 'discard',
        'startswith', 'endswith', 'strip', 'lstrip', 'rstrip',
        'split', 'join', 'replace', 'find', 'lower', 'upper',
        'format', 'encode', 'count',
    ):
        ip = gen._new_temp('int64_t')
        ov_local = gen._ensure_local(ot, ov)
        if ot == 'int64_t':
            gen._emit(f"  {ip} = {ov_local};")  # same type, no cast
        else:
            gen._emit(f"  {ip} = (int64_t){ov_local};")
        if method in ('keys', 'values', 'items', 'get'):
            dp = gen._coerce_to_type('int64_t', 'MojoDict *', ip)
            if ov in gen._dict_val_types:
                gen._dict_val_types[dp] = gen._dict_val_types[ov]
            ot, ov = 'MojoDict *', dp
        elif method in ('append', 'extend', 'sort', 'reverse'):
            lp = gen._coerce_to_type('int64_t', 'MojoList *', ip)
            if ov in gen._struct_field_owners:
                gen._struct_field_owners[lp] = list(gen._struct_field_owners[ov])
            ot, ov = 'MojoList *', lp
        elif method in ('add', 'discard'):
            sp = gen._coerce_to_type('int64_t', 'MojoSet *', ip)
            ot, ov = 'MojoSet *', sp
        else:
            cp = gen._new_val('char *', f"(char *){ip}")
            ot, ov = 'char *', cp

    # ── Container / pointer / scalar dispatch ────────────────────────────
    if ot == 'MojoDict *':
        return gen._lower_dict_method(ov, method, node.args)
    if ot == 'MojoList *':
        return gen._lower_list_method(ov, method, node.args)
    if ot == 'MojoSet *':
        return gen._lower_set_method(ov, method, node.args)
    if ot == 'MojoBytes *':
        return gen._lower_bytes_method(ov, method, node.args, node.kwargs)
    if ot == 'MojoMemoryView *':
        return gen._lower_memoryview_method(ov, method, node.args, node.kwargs)
    _RAW_PTR_METHODS = frozenset({
        'load', 'store', 'offset', 'free', 'bitcast', 'address_of',
        'destroy_pointee', 'take_pointee', 'initialize_pointee',
        'init_pointee_copy', 'init_pointee_move', 'init_pointee_explicit_copy',
        'strided_load', 'gather', 'strided_store', 'scatter',
        'unsafe_mut_cast', 'unsafe_origin_cast', 'unsafe_ptr_cast',
        'origin_cast', 'mut_cast', 'decay', 'as_noalias_ptr',
    })
    if (ot.endswith(' *') and ot not in gen._RUNTIME_PTRS
            and ot[:-2] not in getattr(gen, '_structs_with_unresolved_base', ())
            and method in _RAW_PTR_METHODS):
        # NOTE the unresolved-base exclusion: a USER-STRUCT instance
        # whose class extends an external/unmodeled base (`class
        # DBUnpickler(pickle.Unpickler)` — Doc/includes/dbpickle.py)
        # calling an INHERITED method spelled like a raw-pointer
        # protocol method (`unpickler.load()`) must go to struct-method
        # dispatch (which auto-stubs the never-defined inherited symbol
        # honestly), NOT here — treating the struct pointer as an
        # UnsafePointer emitted `_t = *recv;` (a whole-struct BY-VALUE
        # copy) cast to whatever the surrounding context expected,
        # GCC: "cannot convert to a pointer type". A genuine Mojo
        # `UnsafePointer[T]` receiver keeps raw-pointer semantics: T
        # itself has no unresolvable base-class inheritance.
        return gen._lower_pointer_method(ov, ot, method, node.args)
    if ot == 'void *':
        return gen._lower_file_method(ov, method, node.args)

    # A raw single 'char' (this codegen's string-indexing/for-loop-over-
    # a-string result — see _gen_for_cstr/_lower_slice's `char` return
    # for `s[i]`) calling a str method (`c.isalnum()`, `c.isdigit()`,
    # ...): box it to a real 1-char string first and reuse the char*
    # method dispatch below rather than duplicating it. Without this,
    # `ot == 'char'` fell through every dispatch branch to the generic
    # struct-method fallback, which had no notion of a "char" struct
    # and mangled the call into a bogus, never-defined extern symbol
    # (e.g. `char_mojo_isalnum`) — an undefined-symbol LINK failure,
    # not a silent wrong answer. Only reachable at all once
    # _gen_for_cstr existed to compile `for c in some_str:` in the
    # first place — found via gimple_codegen.py's OWN `_lower_external_
    # call`, whose `cname = ''.join(... for c in cname)` self-hosts as
    # exactly this shape.
    if ot == 'char':
        ov = gen._call_expr('char *', 'mojo_char_to_str', [('char', ov)])
        ot = 'char *'

    # char* string method calls
    if ot == 'char *':
        return gen._lower_str_method(ov, method, node.args)

    # File handle operations (int64_t handles from mojo_open_file)
    if ot in ('int', 'int64_t'):
        if method == 'read' and not node.args:
            t = gen._new_val('char *', f"int_read ({ov})")
            return 'char *', t
        if method == 'write' and node.args:
            data_type, data_val = gen.lower_expr(node.args[0])
            # Generic coercion: int_write expects (int64_t, char*)
            ov_cast = gen._coerce_to_type(ot, 'int64_t', ov)
            if gimple_ctypes.TypeLattice.is_float(data_type):
                # This receiver type (int64_t) most often means a real fd +
                # char*/string-like payload, but an existential Writer
                # parameter (`mut writer: Some[Writer]`) erases to the same
                # int64_t here and can legitimately be asked to write a
                # Float64 (see test_interval.mojo's MyType.write_to). A
                # direct double -> char* cast is invalid C (hard error on
                # GCC 14+); no float-to-string formatting is available in
                # this generic dispatch, so box the value through int64_t
                # (explicit casts, so this only ever produces valid C —
                # correctness for this rare path is tracked separately).
                bits = gen._new_val('int64_t', f"(int64_t){data_val}")
                data_val_cast = gen._new_val('char *', f"(char *){bits}")
            else:
                data_val_cast = gen._coerce_to_type(data_type, 'char *', data_val)
            t = gen._new_val('int64_t', f"int_write ({ov_cast}, {data_val_cast})")
            return 'int64_t', t
        if method == 'close':
            # Stub: mojo_close is defined by stdlib and may not be visible here
            return gen._stub_result('int', '0', f'{ot}.close() — stubbed')

    # Methods on any scalar numeric type (int32_t, uint8_t, etc.) —
    # lower comparison/arithmetic methods to direct C expressions.
    _ALL_SCALARS = frozenset({
        'int', 'int64_t', 'int32_t', 'int16_t', 'int8_t',
        'unsigned int', 'uint64_t', 'uint32_t', 'uint16_t', 'uint8_t',
        '_Bool', 'double', 'float',
    })
    if ot in _ALL_SCALARS:
        # Load the object into a properly-typed local (GIMPLE: no compound exprs).
        if ot != gen.var_types.get(ov, ot):
            ov_local = gen._new_val(ot, f"({ot}){ov}")
        else:
            ov_local = gen._ensure_local(ot, ov)
        if node.args:
            at, av = gen.lower_expr(node.args[0])
            # Coerce argument to the same type; GIMPLE requires separate cast stmt.
            # Route through _coerce_to_type (not a raw C cast) since av may be a
            # pointer (e.g. os.path.isdir(char *) stubbed to this int branch) —
            # a direct (int)ptr cast is a -Wpointer-to-int-cast size mismatch.
            if at != ot:
                av_local = gen._coerce_to_type(at, ot, av)
            else:
                av_local = gen._ensure_local(at, av)
        else:
            av_local = ov_local
        _CMP_OPS = {
            'eq': '==', 'ne': '!=', '__ne__': '!=',
            'lt': '<',  '__lt__': '<',
            'le': '<=', '__le__': '<=',
            'gt': '>',  '__gt__': '>',
            'ge': '>=', '__ge__': '>=',
        }
        if method in _CMP_OPS:
            t = gen._new_temp('_Bool')
            op = _CMP_OPS[method]
            gen._emit(f"  {t} = {ov_local} {op} {av_local};")
            return '_Bool', t
        if method in ('cast', '__cast__', '__int__', '__index__', 'value', 'cast_value'):
            t = gen._new_temp(ot); gen._emit(f"  {t} = {ov_local};"); return ot, t
        if method == 'select' and len(node.args) >= 2:
            # Bool.select(true_val, false_val) — ternary. GIMPLE COND_EXPR
            # requires both branches and the result to share one type, so
            # unify them (e.g. a double and an int64_t branch → double).
            tt, tv = gen.lower_expr(node.args[0])
            ft, fv = gen.lower_expr(node.args[1])
            res_type = gimple_ctypes.TypeLattice.join(tt, ft)
            tv_local = gen._ensure_local(tt, tv)
            if tt != res_type:
                tmp = gen._new_temp(res_type)
                gen._safe_coerce_emit(tt, res_type, tv_local, tmp)
                tv_local = tmp
            fv_local = gen._ensure_local(ft, fv)
            if ft != res_type:
                tmp = gen._new_temp(res_type)
                gen._safe_coerce_emit(ft, res_type, fv_local, tmp)
                fv_local = tmp
            t = gen._new_val(res_type, f"{ov_local} ? {tv_local} : {fv_local}")
            return res_type, t
        # Other scalar methods: pass the receiver through unchanged
        for ea in node.args[1:]: gen.lower_expr(ea)
        return gen._stub_result(ot, ov_local, f'{ot}.{method}() stubbed')

    # Stub string-type methods when called on wrong receiver types
    if method == 'isdigit':
        return gen._stub_result('int', '0', f'{ot}.isdigit() stubbed')
    if method == 'endswith' and ot not in ('char *', 'void *') and (not ot.endswith(' *') or ot in ('MojoSet *', 'MojoList *', 'MojoDict *')):
        return gen._stub_result('int', '0', f'{ot}.endswith() stubbed')
    if method in ('strip', 'lstrip', 'rstrip') and ot not in ('char *', 'void *') and not ot.startswith('Mojo'):
        # strip/lstrip/rstrip on non-string: these already have TODO stubs,
        # but catch cases where they'd generate an invalid method name
        if ot in ('int', 'int64_t', '_Bool', 'double'):
            return gen._stub_result('char *', gen._intern_string(''), f'{ot}.{method}() stubbed')
    if method == 'get' and ot in ('_Bool', 'int', 'int64_t', 'double'):
        for a in node.args: gen.lower_expr(a)
        return gen._stub_result('int64_t', '(int64_t)0', f'{ot}.get() stubbed')
    if method in ('strip', 'lstrip', 'rstrip') and ot in ('MojoDict *', 'MojoList *', 'MojoSet *'):
        for a in node.args: gen.lower_expr(a)
        return gen._stub_result('int', '0', f'{ot}.{method}() stubbed')
    # Stub string methods called on Mojo container types (would generate invalid struct method)
    if method in ('replace', 'find', 'lower', 'upper', 'join', 'split', 'format',
                  'startswith', 'encode', 'decode') and ot in ('MojoSet *', 'MojoList *', 'MojoDict *'):
        for a in node.args: gen.lower_expr(a)
        return gen._stub_result('char *', gen._intern_string(''), f'{ot}.{method}() stubbed')

    # MojoSet.copy() → mojo_set_copy()
    if method == 'copy' and ot == 'MojoSet *':
        t = gen._call_expr('MojoSet *', 'mojo_set_copy', [('MojoSet *', ov)])
        return 'MojoSet *', t

    # .values()/.items() called on wrong receiver: unbox int64_t to MojoDict * first
    # NOT routed through the R2 chokepoint (DESIGN.html R3 exception): `ot`
    # can genuinely be 'MojoList *' here — this is a DELIBERATE reinterpret
    # of a value whose static type was wrongly inferred as a list, and it's
    # the whole point of this branch. gen._coerce_to_type('MojoList *',
    # 'MojoDict *', ...) would hard-raise (both are container-kind types),
    # breaking this recovery path for currently-working code.
    if method in ('values', 'items') and ot in ('MojoList *', 'int64_t', 'int'):
        vp = gen._new_temp('void *'); gen._emit(f"  {vp} = (void *){ov};")
        dp = gen._new_temp('MojoDict *'); gen._emit(f"  {dp} = (MojoDict *){vp};")
        rt = 'MojoList *'
        t = gen._new_temp(rt)
        fn = 'mojo_dict_values' if method == 'values' else 'mojo_dict_items'
        gen._emit_call(rt, t, fn, [('MojoDict *', dp)])
        return rt, t

    # Method calls on boxed int64_t values (dict/list elements stored as pointers-as-int64_t)
    # Unbox to the actual struct type and call the real method.
    if ot in ('int64_t', 'int') and method in ('emit_typedef', 'emit_table_init', 'emit_dispatch_call'):
        for a in node.args: gen.lower_expr(a)
        vp = gen._new_temp('void *'); gen._emit(f"  {vp} = (void *){ov};")
        dt = gen._new_temp('DispatchTable *'); gen._emit(f"  {dt} = (DispatchTable *){vp};")
        ret = 'char *'
        t = gen._call_expr(ret, f'DispatchTable_{method}', [('DispatchTable *', dt)])
        return ret, t

    # Boxed int64_t value that actually holds a struct pointer with a known method.
    # Common when accessing methods on list elements (e.g. errors[0].kind_name())
    # where the element type is known from _field_elem_types.
    if ot in ('int64_t', 'int') and ov in gen._actual_types:
        _actual_ptr_type = gen._actual_types[ov]
        _sn_method = gimple_exprtypes._struct_name_of(_actual_ptr_type)
        _sig_key = f'{_sn_method}_{method}'
        if _sn_method and _sig_key in gen.func_return_types:
            _obj = gen._new_val(_actual_ptr_type, f'({_actual_ptr_type}){ov}')
            arg_pairs = [(_actual_ptr_type, _obj)]
            for a in node.args:
                arg_pairs.append(gen.lower_expr(a))
            t = gen._call_expr(gen.func_return_types[_sig_key], _sig_key, arg_pairs)
            return gen.func_return_types[_sig_key], t

    # Opaque Python object (int-typed): use mojo_obj_call1 for generic method dispatch
    if ot in ('int', 'int64_t') and not (isinstance(func.obj, gimple_ctypes.IdentExpr)
                                           and func.obj.name in gen.struct_field_types):
        method_slit = gen._intern_string(gimple_ctypes._c_escape(method))
        method_key = gen._new_val('char *', f"{method_slit}")
        obj64 = gen._to_int64(ot, ov)
        # Lower the first argument (if any), or pass 0
        if node.args:
            arg_type, arg_val = gen.lower_expr(node.args[0])
            arg64 = gen._new_temp('int64_t')
            gen._safe_coerce_emit(arg_type, 'int64_t', arg_val, arg64)
        else:
            arg64 = gen._new_val('int64_t', "(int64_t)0")
        t = gen._call_expr('int64_t', 'mojo_obj_call1',
                        [('int64_t', obj64), ('char *', method_key), ('int64_t', arg64)])
        # Lower remaining args (for side effects) even though we can't pass them
        for extra_arg in node.args[1:]:
            gen.lower_expr(extra_arg)
        return 'int64_t', t

    # Unknown struct pointer with container method: use runtime dispatch
    # instead of generating StructName_method(...) that doesn't exist.
    # This handles e.g. a param reassigned `args = []` where var_types
    # still shows the original type but the actual value is a MojoList*.
    # NOT `... if ot.endswith(' *') else None`: that ternary's result type
    # is join(str, None) — which the self-hosted backend lowers as int64_t,
    # boxing the `char *` struct name so `f'{_sn}_{method}'` stringifies a
    # pointer decimal and the `in func_return_types` check below always
    # misses (a real compiled-path miscompile: `c.get()` on a genuine
    # user-struct instance fell through to `mojo_obj_call1` dynamic
    # dispatch instead of the real `Counter_get`).
    _sn = ''
    if ot.endswith(' *'):
        _sn = gimple_exprtypes._struct_name_of(ot)
    if _sn == 'MojoList':
        return gen._lower_list_method(ov, method, node.args)
    if _sn == 'MojoDict':
        return gen._lower_dict_method(ov, method, node.args)
    if _sn == 'MojoSet':
        return gen._lower_set_method(ov, method, node.args)
    if _sn == 'MojoStr':
        return gen._lower_str_method(ov, method, node.args)
    if _sn == 'MojoBytes':
        return gen._lower_bytes_method(ov, method, node.args, node.kwargs)
    if (len(_sn) > 0
            and (_sn not in gen.struct_field_types
                 or f'{_sn}_{method}' not in gen.func_return_types)
            and method in ('append', 'extend', 'sort', 'reverse', 'clear',
                           'keys', 'values', 'items', 'get', 'update', 'pop',
                           'add', 'discard', 'remove',
                           'startswith', 'endswith', 'strip', 'lstrip', 'rstrip',
                           'split', 'join', 'replace', 'find', 'lower', 'upper',
                           'format', 'encode')):
        obj64 = gen._to_int64(ot, ov)
        method_slit = gen._intern_string(gimple_ctypes._c_escape(method))
        method_key = gen._new_val('char *', f"{method_slit}")
        if node.args:
            arg_type, arg_val = gen.lower_expr(node.args[0])
            arg64 = gen._new_temp('int64_t')
            gen._safe_coerce_emit(arg_type, 'int64_t', arg_val, arg64)
        else:
            arg64 = gen._new_val('int64_t', "(int64_t)0")
        t = gen._call_expr('int64_t', 'mojo_obj_call1',
                        [('int64_t', obj64), ('char *', method_key), ('int64_t', arg64)])
        for extra_arg in node.args[1:]:
            gen.lower_expr(extra_arg)
        return 'int64_t', t

    # A call through a struct FIELD that holds a callable value
    # (`Wrapper.__call__`'s `self.func(*args)`,
    # `Stopwatch.__exit__`'s `stopwatch.get_time()` — the field assigned
    # in `__init__` from a constructor argument, e.g.
    # `self.func = func`). The old fallthrough below resolved ANY
    # member call on a struct-typed receiver as a same-named STRUCT
    # METHOD, emitting a call to a phantom `<Struct>_<field>` C symbol
    # nothing ever defines — it compiled against a bare variadic
    # declaration and then failed at LINK ("symbol(s) not found") for
    # every such site. When the name IS a declared field of the
    # receiver's struct and is NOT also a real compiled method, load
    # the field's VALUE and dispatch through the existing
    # mojo_fnptr_call_N indirect-call helpers instead
    # (_lower_fnptr_call_value).
    _recv_struct = gimple_exprtypes._struct_name_of(ot) if ot.endswith(' *') else None
    if (_recv_struct is not None and _recv_struct in gen.struct_field_types
            and method in gen.struct_field_types[_recv_struct]
            and f'{_recv_struct}_{method}' not in gen.func_return_types
            and _gmm_sms_key(_recv_struct, method) not in getattr(gen, '_struct_method_signatures', {})):
        _has_spread = any(isinstance(a, gimple_ctypes.UnaryOp) and a.op in ('*', '**')
                          for a in node.args)
        if _has_spread:
            # A `*`/`**`-forwarding shape needs dynamic arity this
            # fixed-arity fnptr-helper model can't express. Follow this
            # file's own established "evaluate arguments for side
            # effects, then no-op" degradation (see the unresolvable-
            # base case above) rather than emitting a bogus direct call.
            for a in node.args:
                gen.lower_expr(a)
            return 'int64_t', gen._new_val('int64_t', '(int64_t)0')
        fp_type, fp_val = gen.lower_expr(node.func)
        return gen._lower_fnptr_call_value(fp_type, fp_val, node, 'int64_t')

    # Struct method call: obj.method(args) → StructName_method(self, args)
    return gen._lower_struct_method_call(ov, ot, method, node)


def _dict_key_probe(gen, key_type: str, key_val: str) -> tuple[str, str, bool]:
    """Normalise a dict KEY operand to the domain it is probed in, as
    `(ctype, cvalue, is_bytes)`.

    A `bytes` key lives in its own key domain in the runtime (see
    _DictSlot.keykind) precisely so that `d[b'x']` and `d['x']` stay the two
    distinct entries Python says they are. Every read path therefore has to
    ask which domain it is in BEFORE choosing a runtime helper, and this is
    that one question: the old code had each of get/pop/setdefault answer
    it separately, and only setdefault remembered — the other two ran
    `_char_to_cstr` on the `MojoBytes *`, casting the POINTER to a `char *`
    and probing the str domain under an address, so `d[b'a'] = 7;
    d.get(b'a')` read 0 and `d.pop(b'a')` neither found nor removed the
    key. One function, so the next reader cannot forget."""
    if key_type == 'MojoBytes *':
        return 'MojoBytes *', key_val, True
    kt, kv = gen._char_to_cstr(key_type, key_val, True, True)
    return kt, kv, False


def _lower_dict_method(gen, ov: str, method: str, args: list) -> tuple:
    """Lower MojoDict * method calls."""
    if method == 'keys':
        t = gen._new_val('MojoList *', f"mojo_dict_keys ({ov})")
        gen._elem_types[t] = 'char *'
        return 'MojoList *', t
    if method == 'values':
        t = gen._new_val('MojoList *', f"mojo_dict_values ({ov})")
        # Carry the dict's VALUE type onto the value-list temp (mirrors
        # `keys()` recording 'char *') so `for v in d.values():` types `v`
        # from it instead of the int64_t default — without this a
        # `for sd in track_best.values()` over a dict of `StructDef *`
        # left `sd` boxed and every `sd.name` read a pointer-decimal.
        # Record int64_t EXPLICITLY too, not just the pointer-ish cases.
        # Leaving an int-valued dict's element type unset is what made
        # `z = {"a": 0}.values()` print `[None]`: with nothing recorded, the
        # repr walker hit its int-vs-pointer heuristic on the boxed 0. An
        # int list is an int list, and saying so is what every other
        # container lowering here does.
        _vt = gen._dict_val_of(ov)
        if _vt:
            gen._elem_types[t] = _vt
        return 'MojoList *', t
    if method == 'items':
        t = gen._new_val('MojoList *', f"mojo_dict_items ({ov})")
        # Record the dict's VALUE type on the item-list temp so the
        # for-loop tuple branch can read the (boxed) value slot with the
        # right accessor — the key slot is always a string (see
        # _dict_items_val_elems's docstring).
        gen._dict_items_val_elems[t] = gen._dict_val_of(ov)
        return 'MojoList *', t
    if method == 'get' and args:
        key_type, key_val, key_is_bytes = _dict_key_probe(gen, *gen.lower_expr(args[0]))
        default_ty = None
        default_val = None
        if len(args) > 1:
            default_ty, default_val = gen.lower_expr(args[1])
        val_type = gen._dict_val_of(ov)
        # `dict.get(k, <char* default>)` on a dict whose value type is
        # unknown (int64_t): the default must NOT be coerced through a
        # list accessor. If the caller supplied a char* default, treat the
        # result as char* — a plain pointer round-trip, never a
        # `mojo_list_get_int(default, 0)` (a hard segfault on the
        # self-hosted `--dump myinterpreter.py`).
        if val_type == 'int64_t' and default_ty == 'char *':
            val_type = 'char *'
        # The runtime keeps a bytes key in its own domain, so the VALUE
        # accessor has to be the bytes one too — the `_bytes` suffixed
        # helpers are the only ones that probe that domain at all. Pairing
        # the key domain with the value domain is the whole fix: both
        # halves existed and only the pairing was missing, so
        # `d[b'a'] = 7; d.get(b'a')` read the str domain and answered 0.
        _sfx = '_bytes' if key_is_bytes else ''
        if val_type == 'char *':
            raw = gen._call_expr('char *', f'mojo_dict_get{_sfx}_str', [('MojoDict *', ov), (key_type, key_val)])
        elif val_type == 'double':
            raw = gen._call_expr('double', f'mojo_dict_get{_sfx}_double', [('MojoDict *', ov), (key_type, key_val)])
        else:
            raw = gen._call_expr('int64_t', f'mojo_dict_get{_sfx}_int', [('MojoDict *', ov), (key_type, key_val)])
        if default_val is not None:
            # dict.get(key, default) must return the default when the key
            # is ABSENT — the plain mojo_dict_get_* helpers return 0/NULL
            # for a missing key, so the previous lowering silently DROPPED
            # the default (e.g. `BUILTIN_VALUE_MAP.get(fname_raw,
            # _func_csym(fname_raw))` → 0/NULL for every non-builtin
            # function name — a NULL `fname` that later crashed the
            # `fname in self.imported_symbols` containment check). Fall
            # back to the default when the raw get returns the absent
            # sentinel (0/NULL), matching how this codebase everywhere
            # treats 0 as the None/absent box. When the dict's value type
            # isn't statically known (defaults to int64_t), the default
            # argument's own type is the real result type. Lowered with
            # explicit if/else basic blocks (NOT a `cond ? a : b`
            # ternary): a GIMPLE cond_expr in a __GIMPLE body was silently
            # miscompiled by gcc here (the compiled mojoc then emitted raw
            # heap/static addresses as variable/type names), so the
            # default-application is spelled as branch-and-assign.
            result_type = val_type
            _container_vt = val_type in ('MojoDict *', 'MojoList *', 'MojoSet *')
            if result_type not in ('char *', 'double', '_Bool') and not _container_vt:
                result_type = default_ty if default_ty in ('char *', 'double', '_Bool') else 'int64_t'
            if _container_vt:
                # `d.get(k, {})` on `d: dict[K, <container>]` — keep the
                # container type (was collapsed to int64_t, losing every
                # downstream `x[k2]` / `x.items()` / `member in x`).
                raw_r = gen._new_val(result_type, f"({result_type}){raw}")
            else:
                raw_r = gen._coerce_to_type(val_type, result_type, raw)
            # `d.get(k, ())` / `d.get(k, [])` / `d.get(k, set())` used
            # purely as an "empty, container-kind-agnostic fallback" (real:
            # gimple_cpp_core.py/gimple_cpp_async.py's `d.get(k, ())` on a
            # dict[str, Set[...]], only ever consumed via `in`/iteration) —
            # see gimple_ctypes.reify_empty_container_literal.
            _reified = (gimple_ctypes.reify_empty_container_literal(gen, default_ty, result_type, args[1])
                        if _container_vt else None)
            if _reified is not None:
                default_r = _reified
            else:
                default_r = gen._coerce_to_type(default_ty, result_type, default_val)
            # Presence test on the RAW int64_t (0 == absent, per the comment
            # above) — NOT `_ensure_bool_cond(result_type, raw_r)`, which for
            # a container result type emits `mojo_list_len(raw_r)` and
            # dereferences: a dict whose value slot happens to hold a small
            # non-pointer int (a stale/garbage `func_param_types` entry) then
            # segfaulted in `mojo_list_len(1)` instead of falling to the
            # default.
            if _container_vt:
                cond = gen._ensure_bool_cond('int64_t', raw)
            else:
                cond = gen._ensure_bool_cond(result_type, raw_r)
            t = gen._new_temp(result_type)
            bb_true = gen._new_bb()
            bb_false = gen._new_bb()
            bb_done = gen._new_bb()
            gen._emit(f"  if ({cond}) goto {bb_true}; else goto {bb_false};")
            gen._emit_label(bb_true)
            gen._emit(f"  {t} = {raw_r};")
            gen._emit(f"  goto {bb_done};")
            gen._emit_label(bb_false)
            gen._emit(f"  {t} = {default_r};")
            gen._emit_label(bb_done)
            if _container_vt:
                _nd = gen._dict_nested_val_types.get(ov)
                if _nd:
                    if result_type == 'MojoDict *':
                        gen._dict_val_types[t] = _nd
                    else:
                        # `dict[K, list[E]]` / `dict[K, set[E]]`: E is the
                        # ELEMENT type of the container this .get() returns,
                        # so `d.get(k)[i]` / `for x in d.get(k)` reads with
                        # the right accessor rather than boxing the pointer.
                        gen._elem_types[t] = _nd
            return result_type, t
        if val_type == 'char *':
            return 'char *', raw
        elif val_type == 'double':
            return 'double', raw
        elif val_type in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            t = gen._new_val(val_type, f"({val_type}){raw}")
            _nd = gen._dict_nested_val_types.get(ov)
            if _nd:
                if val_type == 'MojoDict *':
                    gen._dict_val_types[t] = _nd
                else:
                    gen._elem_types[t] = _nd
            return val_type, t
        else:
            return 'int64_t', raw
    if method == 'update' and args:
        other_type, other_val = gen.lower_expr(args[0])
        # `d1.update(d2)` where d2 is itself a builtin-`dict` subclass
        # instance — the real dict lives in its hidden `_data` field, not
        # at the struct pointer itself.
        _od_sub = gen._dict_subclass_of(other_type)
        if _od_sub:
            other_val = gen._new_val('MojoDict *', f"{other_val}->_data")
            other_type = 'MojoDict *'
        ov_cast = gen._coerce_to_type('MojoDict *', 'MojoDict *', ov)
        other_val_cast = gen._coerce_to_type(other_type, 'MojoDict *', other_val)
        gen._emit(f"  mojo_dict_update ({ov_cast}, {other_val_cast});")
        return 'int', gen._new_val('int', '0')
    if method == 'pop' and args:
        # A bytes key pops from the bytes key domain, and its runtime
        # helper is the only one that takes the `dflt` argument Python's
        # `pop(k, default)` needs — the str-domain mojo_dict_pop_int
        # answers 0 for an absent key and cannot express a default at all.
        key_type, key_val, key_is_bytes = _dict_key_probe(gen, *gen.lower_expr(args[0]))
        val_type = gen._dict_val_of(ov)
        if key_is_bytes:
            # The bytes-domain pop helpers take the `dflt` Python's
            # `pop(k, default)` needs — the str-domain mojo_dict_pop_int
            # has no such parameter and answers 0 for an absent key, so a
            # default could not even be expressed there. The str/double
            # siblings exist because the slot is one int64_t of bits: without
            # them a bytes-keyed dict holding strings popped its value as a
            # raw pointer decimal.
            if val_type == 'char *':
                return 'char *', gen._call_expr(
                    'char *', 'mojo_dict_pop_bytes_str',
                    [('MojoDict *', ov), (key_type, key_val)])
            if val_type == 'double':
                return 'double', gen._call_expr(
                    'double', 'mojo_dict_pop_bytes_double',
                    [('MojoDict *', ov), (key_type, key_val)])
            dflt = gen._to_int64(*gen.lower_expr(args[1])) if len(args) > 1 else '0'
            return 'int64_t', gen._call_expr(
                'int64_t', 'mojo_dict_pop_bytes_int',
                [('MojoDict *', ov), (key_type, key_val), ('int64_t', dflt)])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_dict_pop_int', [('MojoDict *', ov), (key_type, key_val)])
    if method in ('copy',):
        return 'MojoDict *', gen._new_val('MojoDict *', f"mojo_dict_copy ({ov})")
    if method == 'clear':
        gen._emit(f"  mojo_dict_clear ({ov});")
        return 'int', gen._new_val('int', '0')
    if method == 'setdefault' and args:
        # `d.setdefault(key[, default])` — real Python: insert `default`
        # (None if omitted) under `key` when absent, then return the current
        # value. The previous lowering was just `mojo_dict_get_int`, which
        # returns 0 for an absent key and NEVER inserts — so the ubiquitous
        # `d.setdefault(k, []).append(x)` accumulator pattern (this compiler's
        # own `gen_module_impl` uses it) appended to a NULL list and
        # segfaulted the self-hosted binary.
        key_type, key_val, key_is_bytes = _dict_key_probe(gen, *gen.lower_expr(args[0]))
        if len(args) >= 2:
            dt, dv = gen.lower_expr(args[1])
        else:
            dt, dv = 'int64_t', '0'
        if key_is_bytes:
            # bytes keys live in their own dict key domain — see
            # _DictSlot.keykind. `_char_to_cstr` would have cast the
            # MojoBytes POINTER to char*, so the insert went into the str
            # domain under an address and the read-back never found it.
            dv64 = gen._to_int64(dt, dv)
            return 'int64_t', gen._call_expr(
                'int64_t', 'mojo_dict_setdefault_bytes_int',
                [('MojoDict *', ov), ('MojoBytes *', key_val), ('int64_t', dv64)])
        if dt == 'char *':
            return 'char *', gen._call_expr(
                'char *', 'mojo_dict_setdefault_str',
                [('MojoDict *', ov), (key_type, key_val), ('char *', dv)])
        dv64 = gen._to_int64(dt, dv)
        raw = gen._call_expr(
            'int64_t', 'mojo_dict_setdefault_int',
            [('MojoDict *', ov), (key_type, key_val), ('int64_t', dv64)])
        # Preserve a container/pointer default's static type so a chained
        # `.append(...)` / `[...]` resolves against the real runtime type.
        if dt not in ('int64_t', 'int', '_Bool', 'double', ''):
            typed = gen._new_val(dt, f"({dt}){raw}")
            gen._elem_types[typed] = gen._elem_types.get(dv, gen._elem_types.get(_gmm_as_str(raw)))
            return dt, typed
        return 'int64_t', raw
    return 'int64_t', gen._new_val('int64_t', '0')


def _lower_list_method(gen, ov: str, method: str, args: list) -> tuple:
    """Lower MojoList * method calls."""
    # list.insert(i, v) (BUG-2026-023 residual, box.3d/game's
    # FileSystem.current_dir_path): previously UNHANDLED — the unknown-method
    # fallback silently dropped the whole call, so `path_parts.insert(0,
    # name)` never stored anything and every built path stayed "/". Lower to
    # the runtime's typed insert helpers; element type comes from the same
    # _elem_of tracking every other list method uses.
    # collections.deque methods on the MojoList * representation
    # (bugs/COMPILE_FAIL_asyncio_queues.md gap 2): a deque field
    # (`self._getters = deque()`) is typed MojoList *, and asyncio
    # round-trips Future handles through popleft/append/appendleft.
    if method == 'popleft' and not args:
        _z = gen._new_val('int', '0')
        _z64 = gen._new_val('int64_t', f'(int64_t){_z}')
        raw = gen._call_expr('int64_t', 'mojo_list_pop_at',
                             [('MojoList *', ov), ('int64_t', _z64)])
        elem = gen._elem_of(ov)
        if gimple_ctypes.TypeLattice.list_suffix(elem) == 'str':
            return 'char *', gen._new_val('char *', f"(char *){raw}")
        return 'int64_t', raw
    if method == 'appendleft' and args:
        at, av = gen.lower_expr(args[0])
        nv = gen._to_int64(at, av)
        _z = gen._new_val('int', '0')
        _z64 = gen._new_val('int64_t', f'(int64_t){_z}')
        gen._emit_call('void', '', 'mojo_list_insert_int',
                       [('MojoList *', ov), ('int64_t', _z64), ('int64_t', nv)])
        if at.endswith(' *') and ov in gen._struct_field_owners:
            for _sn, _fn in gen._struct_field_owners[ov]:
                gen._field_elem_types.setdefault(_sn, {})[_fn] = at
        return 'int', gen._new_val('int', '0')
    if method == 'insert' and len(args) >= 2:
        it, iv_ = gen.lower_expr(args[0])
        at, av = gen.lower_expr(args[1])
        idx64 = gen._new_val('int64_t', f"(int64_t) {iv_}")
        elem = gen._elem_of(ov)
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        if suf == 'str':
            _, av_s = gen._char_to_cstr(at, av)
            gen._emit_call('void', '', 'mojo_list_insert_str',
                           [('MojoList *', ov), ('int64_t', idx64), ('char *', av_s)])
        elif suf == 'double':
            dv = gen._new_val('double', f"(double){av}" if at != 'double' else av)
            gen._emit_call('void', '', 'mojo_list_insert_double',
                           [('MojoList *', ov), ('int64_t', idx64), ('double', dv)])
        else:
            nv = gen._to_int64(at, av)
            gen._emit_call('void', '', 'mojo_list_insert_int',
                           [('MojoList *', ov), ('int64_t', idx64), ('int64_t', nv)])
        return 'int', gen._new_val('int', '0')
    if method == 'append' and args:
        at, av = gen.lower_expr(args[0])
        # A real Python `str[i]` result is itself a 1-character STRING
        # (not a scalar) — this compiler's `char` representation for it
        # (see mojo_str_char_at) breaks that invariant, so `.append(c)`
        # must still store a real string, not raw ASCII (mojo_list_append_int
        # would silently turn a `list[str]` accumulator into a list of
        # ints; a later `"".join(buf)` then reads each "string" as a
        # garbage pointer at its numeric value — e.g. crashing at address
        # 0x20 for a space). `at == 'char'` catches a direct `s[i]` call
        # result; `self._actual_types.get(av) == 'char'` catches reading it
        # back through a named variable whose declared type was widened to
        # int64_t by joining with other assignment sites in the same
        # function (see the AssignStmt fix tracking this). Found via
        # fire_compiler.py's own `_split_on_separators`'s `c = s[i]` then
        # `buf.append(c)` / `"".join(buf)`.
        if at == 'char' or gen._actual_types.get(av) == 'char':
            cv = av if at == 'char' else gen._new_val('char', f"(char){av}")
            av = gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
            at = 'char *'
        if at == 'char *':
            gen._emit_call('void', '', 'mojo_list_append_str', [('MojoList *', ov), ('char *', av)])
            gen._elem_types[ov] = 'char *'
            # Propagate _field_elem_types for char * append (was missing
            # — the str path had no propagation, only the int path did).
            if ov in gen._struct_field_owners:
                for _sn, _fn in gen._struct_field_owners[ov]:
                    if _sn not in gen._field_elem_types:
                        gen._field_elem_types[_sn] = {}
                    gen._field_elem_types[_sn][_fn] = 'char *'
        else:
            # Coerce a bare `int`/`_Bool` literal to `int64_t` HERE rather
            # than leaving it to `_emit_call`'s param-type lookup: in the
            # self-hosted compiler `_KNOWN_SIGS` is an empty dict and
            # `mojo_list_append_int` has no `func_param_types` entry, so
            # `_emit_call` skipped the widening and emitted `append_int(l, 4)`
            # instead of the `(int64_t)4` temp the Python reference builds
            # (byte-parity drift on `list_append`). `mojo_list_append_int`'s
            # 2nd param is always int64_t, so this is unconditionally correct.
            if at in ('int', '_Bool'):
                av = gen._coerce_to_type(at, 'int64_t', av)
                at = 'int64_t'
            gen._emit_call('void', '', 'mojo_list_append_int', [('MojoList *', ov), (at, av)])
            if at.endswith(' *') or (at == 'int64_t' and av in gen._actual_types and gen._actual_types[av].endswith(' *')):
                actual_elem = gen._actual_types.get(_gmm_as_str(av), at)
                gen._elem_types[ov] = actual_elem
                if actual_elem == 'MojoList *' and av in gen._elem_types:
                    gen._nested_elem_types[ov] = gen._elem_types[av]
                # Propagate to _field_elem_types when ov originated from a
                # struct field (e.g. self.errors / self.blocks). The
                # field-access read path in _lower_MemberExpr checks
                # _field_elem_types to recover element type info when the
                # list is read back later (possibly from a different
                # function/module entirely). This must fire for ANY
                # pointer-typed element (a plain struct pointer like
                # `Block *`, not just the nested-list `MojoList *` case
                # above) — previously this was nested inside the
                # `actual_elem == 'MojoList *'` check, so appending a
                # struct instance (e.g. `self.blocks.append(Block())`)
                # never recorded the element type, and a later read of
                # that field elsewhere fell back to opaque int64_t and
                # runtime dynamic-dispatch getattr instead of a direct
                # `->block_type` field access (AttributeError: block_type
                # in dlopen'd dylibs — box.3d/game's
                # DYLIB_dlopen_extern_fn_attributeerror.md).
                if ov in gen._struct_field_owners:
                    for _sn, _fn in gen._struct_field_owners[ov]:
                        if _sn not in gen._field_elem_types:
                            gen._field_elem_types[_sn] = {}
                        gen._field_elem_types[_sn][_fn] = actual_elem
        return 'int', gen._new_val('int', '0')
    if method == 'extend' and args:
        at, av = gen.lower_expr(args[0])
        # `mojo_list_extend` copies the elements out of its source, so a source
        # that is a fresh container (`l.extend([10, 20])`, `l.extend(s.split())`)
        # is dead once it returns.
        _ext_fresh = at == 'MojoList *' and gen._is_fresh_container_operand(args[0], av)
        gen._emit_call('void', '', 'mojo_list_extend', [('MojoList *', ov), (at, av)])
        if _ext_fresh:
            gen._free_fresh_container(av, 'MojoList *')
        if at == 'MojoList *' and av in gen._elem_types:
            gen._elem_types[ov] = gen._elem_types[av]
            if av in gen._nested_elem_types:
                gen._nested_elem_types[ov] = gen._nested_elem_types[av]
        return 'int', gen._new_val('int', '0')
    if method == 'pop':
        # Was `mojo_list_pop(ov)` unconditionally — any index argument
        # (e.g. `argv.pop(1)`, removing a specific element, not the
        # last) was silently ignored; always popped the last element.
        if args:
            idx_type, idx_v = gen.lower_expr(args[0])
            idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
        else:
            # GIMPLE rejects a bare `(int64_t)-1` initializer directly
            # ("non-trivial conversion in integer_cst") — needs the
            # int-then-cast two-step used elsewhere in this file.
            neg1 = gen._new_val('int', '-1')
            idx64 = gen._new_val('int64_t', f'(int64_t){neg1}')
        raw = gen._call_expr('int64_t', 'mojo_list_pop_at', [('MojoList *', ov), ('int64_t', idx64)])
        elem = gen._elem_of(ov)
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        if suf == 'str':
            t = gen._new_val('char *', f"(char *){raw}")
            return 'char *', t
        return 'int64_t', raw
    if method in ('sort', 'reverse', 'clear'):
        gen._emit(f"  mojo_list_{method} ({ov});")
        return 'int', gen._new_val('int', '0')
    if method == 'copy':
        return 'MojoList *', gen._new_val('MojoList *', f"mojo_list_copy ({ov})")
    if method == 'remove' and args:
        at, av = gen.lower_expr(args[0])
        if at == 'char *':
            return gen._void_call('mojo_list_remove_str', [('MojoList *', ov), ('char *', av)])
        return gen._void_call('mojo_list_remove_int', [('MojoList *', ov), (at, av)])
    if method == 'index' and args:
        at, av = gen.lower_expr(args[0])
        if at == 'char *':
            return 'int64_t', gen._call_expr('int64_t', 'mojo_list_index_str', [('MojoList *', ov), ('char *', av)])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_list_index_int', [('MojoList *', ov), ('int64_t', av)])
    if method == '__len__':
        # The builtin `len(x)` call form already lowers to mojo_list_len
        # (see the len() handling in _lower_call), but the dunder-method
        # CALL form `x.__len__()` fell through to this function's dummy
        # 0-stub with no dedicated case — e.g. `l.__len__() - 1` always
        # computed `-1` regardless of the list's real length.
        return 'int64_t', gen._new_val('int64_t', f'mojo_list_len ({ov})')
    return 'int', gen._new_val('int', '0')


def _lower_set_method(gen, ov: str, method: str, args: list) -> tuple:
    """Lower MojoSet * method calls."""
    if method == 'update' and args:
        other_type, other_val = gen.lower_expr(args[0])
        if other_type == 'MojoSet *':
            return gen._void_call('mojo_set_update', [('MojoSet *', ov), ('MojoSet *', other_val)])
        # `set.update(x)` accepts ANY iterable in real Python (a list, a
        # dict — its keys —, or a genuinely boxed/unknown handle), not
        # just another set; mojo_set_update only accepts a MojoSet*.
        # DESIGN.html R1/R5: materialize via the same shared helper
        # all()/any()/enumerate()/*.join() use (dict -> keys, boxed handle
        # -> runtime-guarded dict/set/list dispatch), then add each
        # element individually via mojo_set_add_str/int, picking the
        # accessor from the materialized list's tracked element type.
        lv = gen._materialize_as_list(other_type, other_val)
        _elem = gen._elem_of(lv)
        _suf = gimple_ctypes.TypeLattice.list_suffix(_elem) if _elem else 'int'
        _len = gen._new_val('int64_t', f"mojo_list_len ({lv})")
        _idx = gen._new_val('int64_t', "(int64_t)0")
        bb_cond = gen._new_bb(); bb_body = gen._new_bb(); bb_after = gen._new_bb()
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_cond)
        cond_t = gen._new_val('_Bool', f"{_idx} < {_len}")
        gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        gen._emit_label(bb_body)
        if _suf == 'str':
            _elv = gen._new_val('char *', f"mojo_list_get_str ({lv}, {_idx})")
            gen._emit(f"  mojo_set_add_str ({ov}, {_elv});")
        else:
            _elv = gen._new_val('int64_t', f"mojo_list_get_int ({lv}, {_idx})")
            gen._emit(f"  mojo_set_add_int ({ov}, {_elv});")
        _one = gen._new_val('int64_t', "(int64_t)1")
        _nxt = gen._new_val('int64_t', f"{_idx} + {_one}")
        gen._emit(f"  {_idx} = {_nxt};")
        gen._emit(f"  goto {bb_cond};")
        gen._emit_label(bb_after)
        return 'int', gen._new_val('int', '0')
    if method == 'add' and args:
        at, av = gen.lower_expr(args[0])
        # Record the set's element type on the RECEIVER the same way a
        # `{...}` literal does (`_lower_set_literal`) — `s = set()` then
        # `s.add(x)` in a loop never went through that literal path, so
        # `sorted(s)`/`for v in s:` later defaulted `s`'s element type to
        # `int64_t` unconditionally, silently misreading real string
        # elements as boxed addresses (a real, reproducible `make
        # bootstrap` crash chain: `ownership_destruct.py`'s `_FuncFacts.
        # candidates()` builds exactly this `out = set(); ...
        # out.add(name)` shape, and the caller's `sorted(candidates)`
        # loop var then fed a mis-typed `name` into a dict lookup that
        # segfaulted in `strcmp`).
        if at == 'char *' and ov not in gen._elem_types:
            gen._elem_types[ov] = 'char *'
        if at == 'MojoBytes *':
            # bytes elements live in their own slot domain (set tag 2), so
            # `s.add(b'a')` twice is still one element and `b'a' in s` hits —
            # an int slot would store the raw pointer and give both failures.
            if gen._elem_of(ov) in (None, 'int64_t'):
                gen._elem_types[ov] = 'MojoBytes *'
            return gen._void_call('mojo_set_add_bytes', [('MojoSet *', ov), ('MojoBytes *', av)])
        if at == 'char *':
            return gen._void_call('mojo_set_add_str', [('MojoSet *', ov), ('char *', av)])
        av64 = gen._to_int64(at, av)
        return gen._void_call('mojo_set_add_int', [('MojoSet *', ov), ('int64_t', av64)])
    if method == 'discard' and args:
        at, av = gen.lower_expr(args[0])
        if at == 'char *':
            return gen._void_call('mojo_set_discard_str', [('MojoSet *', ov), (at, av)])
        av64 = gen._to_int64(at, av)
        return gen._void_call('mojo_set_discard_int', [('MojoSet *', ov), ('int64_t', av64)])
    if method == 'copy':
        return 'MojoSet *', gen._call_expr('MojoSet *', 'mojo_set_copy', [('MojoSet *', ov)])
    if method == 'clear':
        gen._emit(f"  mojo_set_clear ({ov});")
        return 'int', gen._new_val('int', '0')
    return 'int', gen._new_val('int', '0')


def _lower_pointer_method(gen, ov: str, ot: str, method: str, args: list) -> tuple:
    """Lower raw pointer (UnsafePointer) method calls."""
    elem = gimple_ctypes._elem_type(ot)
    if method == 'load':
        return elem, gen._new_val(elem, f"*{ov}")
    if method == 'store' and args:
        at, av = gen.lower_expr(args[0])
        # Spill through a register: a pointer→int64_t coercion is a double cast
        # `(int64_t)(void*)x` which GIMPLE rejects inside `*p = ...`.
        ovl = gen._ensure_local(ot, ov)
        sv = gen._new_temp(elem)
        gen._safe_coerce_emit(gen._quick_type(args[0]), elem, av, sv)
        gen._emit(f"  *{ovl} = {sv};")
        return 'int', gen._new_val('int', '0')
    if method == 'offset' and args:
        _, nv = gen.lower_expr(args[0])
        cn = gimple_ctypes._c_id(elem)
        gen._ptr_helpers_needed.add(elem)
        idx64 = gen._new_val('int64_t', f"(int64_t) {nv}")
        return ot, gen._new_val(ot, f"_mojo_at_{cn} ({ov}, {idx64})")
    if method == 'free':
        gen._emit(f"  free ({ov});")
        return 'int', gen._new_val('int', '0')
    if method in ('bitcast', 'address_of',
                  'unsafe_mut_cast', 'unsafe_origin_cast', 'unsafe_ptr_cast',
                  'origin_cast', 'mut_cast', 'decay', 'as_noalias_ptr'):
        t = gen._new_temp(ot)
        gen._emit(f"  {t} = {ov};  /* {method}: pass-through */")
        return ot, t
    if method in ('destroy_pointee', 'take_pointee', 'initialize_pointee',
                  'init_pointee_copy', 'init_pointee_move', 'init_pointee_explicit_copy'):
        # Placement init/copy/move all write the value into the pointee.
        if args and method != 'destroy_pointee' and method != 'take_pointee':
            at, av = gen.lower_expr(args[0])
            # GIMPLE requires the pointer operand of `*` to be a register, so
            # spill ov (which may be a member access like self->_data) first.
            ovl = gen._ensure_local(ot, ov)
            if elem in gen.struct_field_types:
                # The constructed value (av) is itself a pointer to the
                # struct (struct constructors return `StructName *`, see
                # _lower_struct_constructor) — write through by
                # dereferencing it. Coercing into a by-value struct temp
                # (the scalar path below) would cast a pointer directly to
                # a VALUE type, which GCC rejects ("conversion to
                # non-scalar type requested") — a pointer needs a
                # dereference here, not a cast.
                elem_ptr = elem + ' *'
                av_ptr = av if at == elem_ptr else gen._new_val(elem_ptr, f"({elem_ptr}){av}")
                gen._emit(f"  *{ovl} = *{av_ptr};")
            else:
                # Spill the value too: a pointer→int64_t coercion is a
                # double cast `(int64_t)(void*)x` that GIMPLE rejects
                # inside `*p = ...`.
                sv = gen._new_temp(elem)
                gen._safe_coerce_emit(at, elem, av, sv)
                gen._emit(f"  *{ovl} = {sv};")
        return 'int', gen._new_val('int', '0')
    if method in ('strided_load', 'gather'):
        return gen._stub_result(elem, f'*{ov}', f'TODO: {method}')
    if method in ('strided_store', 'scatter'):
        return gen._stub_result('int', '0', f'TODO: {method}')
    return 'int', gen._new_val('int', '0')


def _lower_file_method(gen, ov: str, method: str, args: list) -> tuple:
    """Lower void * file-handle method calls."""
    if method == 'write' and args:
        data_type, data_val = gen.lower_expr(args[0])
        if data_type == 'char *':
            return 'int64_t', gen._new_val('int64_t', f"mojo_write ({ov}, {data_val}, -1)")
    if method == 'close':
        gen._emit(f"  mojo_close ({ov});")
        return 'int', gen._new_val('int', '0')
    return 'int', gen._new_val('int', '0')


def _lower_str_method(gen, ov: str, method: str, args: list) -> tuple:
    """Lower char * string method calls."""
    # Lower each argument exactly once. Calling self.lower_expr(a) twice
    # per argument (once for [0], once for [1]) used to re-run codegen for
    # the SAME subexpression, emitting it twice into the function body —
    # harmless for a pure literal, but for something with real codegen
    # side effects (e.g. `map(str, args)` inside `sep.join(map(str, args))`)
    # this duplicated the entire mojo_map(...) call and left the first,
    # unused copy's temp with a mismatched/dead type. See
    # bugs/CODEGEN_map_over_untyped_param_arg.md.
    arg_pairs = [gen.lower_expr(a) for a in args]
    loaded_args = []
    for at, av in arg_pairs:
        if av.startswith('_slit_') or av in gen._str_pool.values():
            av = gen._new_val(at, f'{av}')
        loaded_args.append(av)
    arg_vals = loaded_args
    stored_type = gen.var_types.get(ov, 'char *')
    if stored_type == 'int64_t':
        cstr_ov = gen._new_val('char *', f"(char *){ov}")
    else:
        cstr_ov = ov
    if method == '__len__':
        return 'int64_t', gen._new_val('int64_t', f'mojo_strlen ({cstr_ov})')
    if method == 'group':
        return 'char *', cstr_ov
    if method in ('as_c_string_slice', 'unsafe_cstr_ptr', 'unsafe_ptr', 'data'):
        # A Mojo string is already represented as a bare char* here, so
        # these C-string accessors are identity — return the same pointer.
        return 'char *', cstr_ov
    _CSTR_METHODS: dict[str, str] = {
        'lower': 'string_lower', 'upper': 'string_upper',
        'strip': 'string_strip',
        'lstrip': 'mojo_str_lstrip', 'rstrip': 'mojo_str_rstrip',
    }
    if method in _CSTR_METHODS:
        # `str.rstrip(chars)` / `str.lstrip(chars)` with a chars argument:
        # the plain mojo_str_rstrip/lstrip only strip whitespace and IGNORE
        # the argument, so `.rstrip(' *')` left the '*' on
        # ("MojoFunction *") — breaking gimple_codegen.py's own struct-
        # typedef dependency check (`base_type = field_type.rstrip(' *')`)
        # in the self-hosted binary and emitting structs out of order.
        if method in ('rstrip', 'lstrip') and arg_vals:
            fn = 'mojo_str_rstrip_chars' if method == 'rstrip' else 'mojo_str_lstrip_chars'
            _a0t, _a0v = arg_pairs[0]
            if _a0t != 'char *' and _a0t != 'void *':
                _a0v = gen._coerce_to_type(_a0t, 'char *', _a0v)
            return 'char *', gen._new_val('char *', f"{fn} ({cstr_ov}, {_a0v})")
        return 'char *', gen._new_val('char *', f"{_CSTR_METHODS[method]} ({cstr_ov})")
    if method == 'expandtabs':
        tabsize = arg_vals[0] if arg_vals else '8'
        return 'char *', gen._new_val('char *', f"mojo_str_expandtabs ({cstr_ov}, {tabsize})")
    if method == 'join':
        if arg_vals:
            iter_val = arg_vals[0]
            iter_type = arg_pairs[0][0] if arg_pairs else 'MojoList *'
            # DESIGN.html R1: shared with all()/any()/enumerate()/
            # bytes.join()/shlex.join() - see _materialize_as_list (real,
            # common Python idiom: `sep.join(some_dict)` joins its keys —
            # a real repro in std/builtin/simd.mojo).
            iter_val = gen._materialize_as_list(iter_type, iter_val)
            return 'char *', gen._call_expr('char *', 'mojo_str_join', [('char *', cstr_ov), ('MojoList *', iter_val)])
        t = gen._new_temp('char *')
        gen._emit(f"  {t} = {cstr_ov};  /* join: no iterable */")
        return 'char *', t
    if method == 'startswith' and arg_vals:
        t = gen._new_temp('int')
        arg0_type = arg_pairs[0][0] if arg_pairs else 'char *'
        arg0_val = arg_vals[0]
        if arg0_type == 'char':
            gen._emit_call('int', t, 'mojo_str_startswith_char', [('char *', cstr_ov), ('char', arg0_val)])
        else:
            gen._emit_call('int', t, 'mojo_str_startswith', [('char *', cstr_ov), (arg0_type, arg0_val)])
        return 'int', t
    if method == 'endswith' and arg_vals:
        t = gen._new_temp('int')
        arg0_type = arg_pairs[0][0] if arg_pairs else 'char *'
        arg0_val = arg_vals[0]
        if arg0_type == 'char':
            gen._emit_call('int', t, 'mojo_str_endswith_char', [('char *', cstr_ov), ('char', arg0_val)])
        else:
            gen._emit_call('int', t, 'mojo_str_endswith', [('char *', cstr_ov), (arg0_type, arg0_val)])
        return 'int', t
    if method == 'find' and arg_vals:
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        if len(arg_vals) >= 2:
            start_type = arg_pairs[1][0] if len(arg_pairs) >= 2 else 'int64_t'
            start_v = gen._to_int64(start_type, arg_vals[1])
            return 'int64_t', gen._call_expr('int64_t', 'mojo_str_find_from',
                [('char *', cstr_ov), (sep_type, arg_vals[0]), ('int64_t', start_v)])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_str_find', [('char *', cstr_ov), (sep_type, arg_vals[0])])
    if method == 'rfind' and arg_vals:
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        return 'int64_t', gen._call_expr('int64_t', 'mojo_str_rfind', [('char *', cstr_ov), (sep_type, arg_vals[0])])
    if method == 'rindex' and arg_vals:
        # str.rindex(sub) — like rfind but real Python raises ValueError on
        # a miss instead of returning -1; this codebase's `index`/`rindex`
        # callers never actually rely on that exception (they've already
        # checked `sub in s` or a bracket-match count first), so mapping to
        # the same mojo_str_rfind runtime helper as rfind (rather than
        # inventing a raising variant) is safe here, exactly like `index`
        # just below reuses mojo_str_find/mojo_str_find_from. Had NO
        # lowering case at all before this fix — confirmed via a full grep
        # for "rindex" across every gimple_gen_*.py — so it silently fell
        # through to the generic unknown-method stub, returning a bare
        # `int 0` regardless of the real string/substring. Found via
        # module_loader.py's own export-signature scanner: `paren_end =
        # sig.rindex(')')` read back 0 self-hosted (instead of the real
        # closing-paren index), truncating `params_str` to '' and silently
        # dropping every parameter from every scanned function's exported
        # C signature whose Mojo source used generic bracket parameters
        # (e.g. `def listdir[PathLike: stdPathLike](path: PathLike)`,
        # which has a second, later ')' the plain .index('(')-paired
        # .rindex(')') pattern needs to actually find).
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        return 'int64_t', gen._call_expr('int64_t', 'mojo_str_rfind', [('char *', cstr_ov), (sep_type, arg_vals[0])])
    if method == 'index' and arg_vals:
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        if len(arg_vals) >= 2:
            start_type = arg_pairs[1][0] if len(arg_pairs) >= 2 else 'int64_t'
            start_v = gen._to_int64(start_type, arg_vals[1])
            return 'int64_t', gen._call_expr('int64_t', 'mojo_str_find_from',
                [('char *', cstr_ov), (sep_type, arg_vals[0]), ('int64_t', start_v)])
        return 'int64_t', gen._call_expr('int64_t', 'mojo_str_find', [('char *', cstr_ov), (sep_type, arg_vals[0])])
    if method == 'count' and arg_vals:
        sub_type = arg_pairs[0][0] if arg_pairs else 'char *'
        return 'int64_t', gen._call_expr('int64_t', 'mojo_str_count', [('char *', cstr_ov), (sub_type, arg_vals[0])])
    if method == 'split':
        # No-arg split() (or split(None)) means whitespace-split — was
        # `and arg_vals`-gated, so the no-arg call fell through to the
        # unknown-method stub (silently an empty list). Real bug found
        # via py_cflags = getenv_output.strip().split() corrupting a
        # subprocess argv (see mojo_str_split's doc comment).
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        sep_val = arg_vals[0] if arg_vals else '0'
        t = gen._call_expr('MojoList *', 'mojo_str_split', [('char *', cstr_ov), (sep_type, sep_val)])
        gen._elem_types[t] = 'char *'
        return 'MojoList *', t
    if method == 'rsplit':
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        sep_val = arg_vals[0] if arg_vals else '0'
        maxsplit_val = arg_vals[1] if len(arg_vals) > 1 else '-1'
        t = gen._call_expr('MojoList *', 'mojo_str_rsplit',
                             [('char *', cstr_ov), (sep_type, sep_val), ('int64_t', maxsplit_val)])
        gen._elem_types[t] = 'char *'
        return 'MojoList *', t
    if method == 'splitlines':
        t = gen._call_expr('MojoList *', 'mojo_str_splitlines', [('char *', cstr_ov)])
        gen._elem_types[t] = 'char *'
        return 'MojoList *', t
    if method in ('partition', 'rpartition') and arg_vals:
        sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
        fn = 'mojo_str_partition' if method == 'partition' else 'mojo_str_rpartition'
        t = gen._call_expr('MojoList *', fn, [('char *', cstr_ov), (sep_type, arg_vals[0])])
        gen._elem_types[t] = 'char *'
        return 'MojoList *', t
    if method == 'replace' and len(arg_vals) >= 2:
        arg0_type = arg_pairs[0][0] if len(arg_pairs) > 0 else 'char *'
        arg1_type = arg_pairs[1][0] if len(arg_pairs) > 1 else 'char *'
        t = gen._new_temp('int64_t')
        gen._emit_call('int64_t', t, '_char_replace_impl',
                         [('char *', cstr_ov), (arg0_type, arg_vals[0]), (arg1_type, arg_vals[1])])
        return 'char *', gen._new_val('char *', f"(char *){t}")
    # Character-class predicates (str.isalnum/isdigit/...) — real runtime
    # helpers, previously hardcoded-0 stubs (always False), which broke
    # e.g. fire_compiler.py's own `raw[i].isdigit()` / `prev.isalnum()`.
    # All ten go through the runtime's one shared kernel, so this table and
    # the `bytes` one (_bytes_is_kind) cannot drift apart — they are the
    # same Python rules, and while they were two hand-written copies the
    # bytes copy answered `b''.isalpha()` True and `b'ab1'.islower()` False.
    # istitle/isascii/isprintable/isnumeric were missing here entirely and
    # fell to the generic stub as a raw int 0 — printed as `0`, not `False`,
    # and `True`/`False`-incompatible for `"".isprintable()`.
    _STR_PREDICATES = {
        'isalnum': 'mojo_str_isalnum', 'isdigit': 'mojo_str_isdigit',
        'isalpha': 'mojo_str_isalpha', 'isspace': 'mojo_str_isspace',
        'isupper': 'mojo_str_isupper', 'islower': 'mojo_str_islower',
        'istitle': 'mojo_str_istitle', 'isascii': 'mojo_str_isascii',
        'isprintable': 'mojo_str_isprintable', 'isnumeric': 'mojo_str_isnumeric',
    }
    if method in _STR_PREDICATES and not arg_vals:
        t = gen._new_temp('int')
        gen._emit_call('int', t, _STR_PREDICATES[method], [('char *', cstr_ov)])
        return '_Bool', gen._new_val('_Bool', f'{t} != 0')
    # pathlib.Path.readlink() — this codegen has no real symlink-target
    # resolution (no runtime helper exists), so honestly stub to an
    # identity passthrough of the receiver rather than falling to the
    # generic 'int' stub below — same simplification precedent as the
    # GIMPLE path's own isfile/normpath/relpath stubs elsewhere in this
    # file ("normpath/relpath -> identity"). Without this, ANY chained
    # `path / other_path.readlink()` (a real Path.readlink() call site
    # feeding straight into `/`, e.g. Apple/testbed/__main__.py's
    # symlink-rewriting helper) hit the generic 'int' stub, producing a
    # hard "invalid operands to binary / (have 'char *' and 'int')"
    # compile error instead of just an honestly-approximate stub value.
    if method == 'resolve':
        # pathlib.Path.resolve() (strict=False) on a path-shaped char*
        # value — real runtime support via POSIX realpath(3), mirroring
        # the os.path helper family this table already dispatches to
        # (int64_t_basename/int_dirname/...). Python's strict=False
        # convention (unresolvable tail returned as-is, never raised) is
        # implemented inside int64_t_realpath itself. Without this,
        # `Path(x).resolve()` fell to the scalar-stub passthrough (the
        # receiver typed int64_t), which silently kept a RELATIVE path
        # where real Python returns an absolute one.
        return 'char *', gen._call_expr('char *', 'int64_t_realpath',
                                        [('char *', cstr_ov)])
    if method in ('encode', 'decode', 'format', 'readlink'):
        return gen._stub_result('char *', cstr_ov, f'TODO: {method}')
    # Unknown method on char* — stub
    return gen._stub_result('int', '0', f'TODO: char*.{method}')


# Bytes methods that return a NEW bytes value (never a str).
_BYTES_RETURNING_METHODS = frozenset({
    'replace', 'strip', 'lstrip', 'rstrip', 'upper', 'lower',
    'split', 'rsplit', 'splitlines', 'join',  # (split family returns list — handled explicitly)
})


def _coerce_to_bytes(gen, t: str, v: str) -> str:
    """Coerce a lowered (type, value) to a `MojoBytes *` C value."""
    if t == 'MojoBytes *':
        return v
    if t == 'char *':
        return gen._call_expr('MojoBytes *', 'mojo_bytes_from_str',
                              [('char *', v), ('char *', '"utf-8"')])
    # narrow scalar: widen through int64_t then route through the
    # chokepoint (safe - a scalar can never be a different container kind).
    if t in ('int', 'char', '_Bool', 'int64_t'):
        v = gen._new_val('int64_t', f'(int64_t){v}')
        return gen._coerce_to_type('int64_t', 'MojoBytes *', v)
    # Genuinely unknown pointer (DESIGN.html R3 exception, NOT routed
    # through the chokepoint): `t` could in principle be another
    # container-kind type reaching this generic fallback (e.g. an
    # ill-typed `some_bytes.startswith(a_list)`), which would hard-raise
    # via gen._coerce_to_type. Left as a direct cast; no real corpus
    # example of this actually firing on a non-bytes-like value found
    # during this pass.
    return gen._new_val('MojoBytes *', f'(MojoBytes *){v}')


def _bytes_is_kind(method: str) -> int | None:
    """Map a `bytes.isX()` predicate name to its MOJO_IS_* code (see
    mojo_is_kind in fire_runtime.c). Returns None for a non-predicate name.

    This is EXACTLY CPython's set for `bytes` — isalnum, isalpha, isascii,
    isdigit, islower, isspace, istitle, isupper — and nothing else. The
    list used to carry ten names on the strength of "Python defines only
    the ASCII flavours of these on bytes", which is not what CPython does:
    `isprintable` and `isnumeric` are `str`-only and `b'a'.isprintable()`
    is an AttributeError in CPython and in this compiler's own interpreter
    reference (myinterpreter.py leaves it to Python's bytes). Implementing
    them here answered a question nobody asked with a value that could not
    be right, so they are raised instead (_BYTES_STR_ONLY_PREDICATES)."""
    return {
        'isalpha': 0, 'isalnum': 1, 'isdigit': 2, 'isspace': 3,
        'isupper': 4, 'islower': 5, 'istitle': 6, 'isascii': 8,
    }.get(method)


# `str`-only predicates: real names that are NOT `bytes` methods, so the
# honest answer is the same AttributeError the interpreter gives. Raising
# beats both alternatives this used to have — implementing them (a silent
# value that disagrees with CPython on the only inputs that reach it) and
# dropping them (the generic unknown-method stub, a silent int 0 that also
# happens to be `False` for two of the ten and not for the rest).
_BYTES_STR_ONLY_PREDICATES = ('isprintable', 'isnumeric')


def _raise_bytes_str_only_predicate(gen, method: str) -> None:
    """Emit the real AttributeError for a `str`-only predicate asked of a
    `bytes` receiver. `_lower_struct_attr_call` uses the same
    mojo_raise_attribute_error + dead-value convention: the raise longjmps,
    so the value the surrounding expression wants is dead on every path
    that reaches it and only has to typecheck."""
    gen._emit_call(
        'void', '', 'mojo_raise_attribute_error',
        [('char *', gen._intern_string(f"'bytes' object has no attribute '{method}'"))])


def _opt_arg(gen, args, kwargs, name, want, default):
    """Resolve one optional positional-or-keyword argument of a bytes /
    memoryview method: `args` is the positional list, `kwargs` the
    `[(str, Expr)]` pairs. Returns a lowered C value of type `want`.

    Positional lookup is by the parameter's position among the method's
    OPTIONAL parameters (`slot`, 0-based); an explicit keyword always wins
    over a positional, as in Python."""
    for k, v in (kwargs or []):
        if k == name:
            return gen.lower_expr(v)[1]
    if want == 'int64_t':
        lo, hi = _OPT_SLOTS.get(name, (None, None))
        if lo is not None and len(args) > lo:
            return gen._to_int64(*gen.lower_expr(args[lo]))
    elif want == 'char *' and args:
        t, v = gen.lower_expr(args[0])
        return v if t == 'char *' else default
    elif want == 'MojoBytes *':
        lo, hi = _OPT_SLOTS.get(name, (None, None))
        if lo is not None and len(args) > lo:
            return _coerce_to_bytes(gen, *gen.lower_expr(args[lo]))
    return default


def _bytes_fill_char(gen, args, kwargs) -> str:
    """`ljust`/`rjust`/`center`'s `fillchar`, as the C `int` byte value the
    runtime's pad helper wants.

    CPython accepts ONE spelling: a one-byte `bytes` (`b'a'.ljust(4, b'.')`);
    an int is a TypeError there. This compiler also accepts the bare int
    (a fire extension, kept because the repo's own corpus and its
    `gimple_bytes_case_and_affix_methods` case use it), so both spellings
    have to resolve — and they are different C domains.

    The bytes spelling used to be resolved by asking `_opt_arg` for an
    `int64_t`, i.e. running `_to_int64` on a `MojoBytes *`: a
    pointer-to-integer cast whose low byte is a heap address, so
    `b'a'.ljust(4, b'.')` emitted a DIFFERENT wrong byte on every run. The
    length check cannot live here — the fill is not a compile-time
    constant — so it is mojo_bytes_fill_byte's, in the runtime, where it
    raises TypeError instead of silently padding with the first byte."""
    lo, _hi = _OPT_SLOTS['fillchar']
    for k, v in (kwargs or []):
        if k == 'fillchar':
            ft, fv = gen.lower_expr(v)
            break
    else:
        if len(args) <= lo:
            return '32'  # Python's default fillchar is a single space
        ft, fv = gen.lower_expr(args[lo])
    if ft == 'MojoBytes *':
        return gen._call_expr('int', 'mojo_bytes_fill_byte', [('MojoBytes *', fv)])
    if ft == 'char *':
        # A str fillchar is what `b'a'.ljust(4, '.')` writes in Mojo's own
        # spelling; take its first byte, which for the one-character fill
        # this is written for is the whole thing.
        fv = _coerce_to_bytes(gen, ft, fv)
        return gen._call_expr('int', 'mojo_bytes_fill_byte', [('MojoBytes *', fv)])
    return gen._to_int64(ft, fv)


# Optional-parameter positional slots, per method family: (first_positional,
# last_positional) counted over the method's OPTIONAL parameters only (the
# required leading argument is handled separately by each case below).
_OPT_SLOTS = {
    'start': (0, 1), 'end': (1, 1), 'maxsplit': (1, 1), 'width': (0, 0),
    'fillchar': (1, 1), 'keepends': (0, 0), 'sep': (0, 0), 'upper': (1, 1),
    'do_left': (1, 2), 'do_right': (2, 2),
}


def _range_opts(gen, args, kwargs, first_optional):
    """Resolve the optional `[start[, end]]` of a find/index/count family
    call into a (start, stop) C pair, using the MOJO_SLICE_STOP_OMITTED
    sentinel for "not given" so the runtime's own clamping handles negatives
    and start > end exactly like Python's slice bounds."""
    start = '0'
    stop = 'MOJO_SLICE_STOP_OMITTED'
    for k, v in (kwargs or []):
        if k == 'start':
            start = gen._to_int64(*gen.lower_expr(v))
        elif k == 'end':
            stop = gen._to_int64(*gen.lower_expr(v))
    if len(args) > first_optional:
        start = gen._to_int64(*gen.lower_expr(args[first_optional]))
    if len(args) > first_optional + 1:
        stop = gen._to_int64(*gen.lower_expr(args[first_optional + 1]))
    return start, stop


def _lower_bytes_method(gen, ov: str, method: str, args: list, kwargs=None) -> tuple:
    """Lower `MojoBytes *` method calls (mirrors _lower_str_method, but
    bytes-typed: .decode/.hex return char*, everything else returns bytes,
    split-family returns list-of-bytes)."""
    arg_pairs = [gen.lower_expr(a) for a in args]

    if method == '__len__':
        return 'int64_t', gen._call_expr('int64_t', 'mojo_bytes_len', [('MojoBytes *', ov)])

    if method == 'decode':
        enc = '"utf-8"'
        for k, v in (kwargs or []):
            if k == 'encoding':
                enc = gen.lower_expr(v)[1]
        if not enc.startswith('"') and arg_pairs and arg_pairs[0][0] == 'char *':
            enc = arg_pairs[0][1]
        return 'char *', gen._call_expr('char *', 'mojo_bytes_decode',
                                        [('MojoBytes *', ov), ('char *', enc)])

    # hashlib(...)'s `.update(data)`/`.hexdigest()` — see _lower_method_call's
    # `hashlib.blake2b/md5/...` construction, which types the accumulator as
    # a real `MojoBytes *` so it lands here instead of the receiver-type-
    # unknown dict/list/set guess-by-method-name heuristic.
    if method == 'update' and arg_pairs:
        pv = _coerce_to_bytes(gen, *arg_pairs[0])
        gen._emit_call('void', '', 'mojo_bytearray_extend', [('MojoBytes *', ov), ('MojoBytes *', pv)])
        return 'int', gen._new_val('int', '0')
    if method == 'hexdigest':
        return 'char *', gen._call_expr('char *', 'mojo_bytes_hash_hexdigest', [('MojoBytes *', ov)])
    if method == 'hex':
        # `bytes.hex()` takes NO arguments in Python (unlike `str.hex(sep)`
        # and unlike `binascii.hexlify`, which is a different function).
        return 'char *', gen._call_expr('char *', 'mojo_bytes_hex', [('MojoBytes *', ov)])

    if method in ('startswith', 'endswith') and arg_pairs:
        pv = _coerce_to_bytes(gen, *arg_pairs[0])
        fn = 'mojo_bytes_startswith' if method == 'startswith' else 'mojo_bytes_endswith'
        t = gen._call_expr('int', fn, [('MojoBytes *', ov), ('MojoBytes *', pv)])
        return '_Bool', gen._new_val('_Bool', f'{t} != 0')

    # find/index/rindex/rfind/count. The needle is EITHER a bytes value or a
    # single byte as an int (`b.index(0x2c)` — the form bytearray's own
    # index/count are nearly always called with). Both take an optional
    # clamped [start[, end]] range.
    if method in ('find', 'index', 'rfind', 'rindex', 'count') and arg_pairs:
        backward = method in ('rfind', 'rindex')
        by_value = arg_pairs[0][0] in ('int64_t', 'int', 'char', '_Bool')
        st, sp = _range_opts(gen, args, kwargs, 1)
        full = st == '0' and sp == 'MOJO_SLICE_STOP_OMITTED'
        if by_value:
            v = gen._to_int64(*arg_pairs[0])
            if method == 'count':
                fn = 'mojo_bytes_count_int'
            elif method in ('index', 'rindex'):
                fn = 'mojo_bytes_rindex_int' if backward else 'mojo_bytes_index_int'
            else:
                # find/rfind over a byte VALUE is find_of a 1-byte needle;
                # express it through the int indexer, which is exact.
                fn = 'mojo_bytes_rindex_int' if backward else 'mojo_bytes_index_int'
            return 'int64_t', gen._call_expr('int64_t', fn,
                                             [('MojoBytes *', ov), ('int64_t', v),
                                              ('int64_t', st), ('int64_t', sp)])
        sv = _coerce_to_bytes(gen, *arg_pairs[0])
        if method == 'count':
            if full:
                return 'int64_t', gen._call_expr('int64_t', 'mojo_bytes_count',
                                                 [('MojoBytes *', ov), ('MojoBytes *', sv)])
            return 'int64_t', gen._call_expr('int64_t', 'mojo_bytes_count_from',
                                             [('MojoBytes *', ov), ('MojoBytes *', sv),
                                              ('int64_t', st), ('int64_t', sp)])
        if full and method in ('find', 'rfind'):
            fn = 'mojo_bytes_rfind' if backward else 'mojo_bytes_find'
            return 'int64_t', gen._call_expr('int64_t', fn,
                                             [('MojoBytes *', ov), ('MojoBytes *', sv)])
        fn = 'mojo_bytes_rfind_from' if backward else 'mojo_bytes_find_from'
        return 'int64_t', gen._call_expr('int64_t', fn,
                                         [('MojoBytes *', ov), ('MojoBytes *', sv),
                                          ('int64_t', st), ('int64_t', sp)])

    if method in ('split', 'rsplit'):
        sep = 'NULL'
        if arg_pairs and arg_pairs[0][0] != 'void':
            sep = _coerce_to_bytes(gen, *arg_pairs[0])
        maxsplit = 'MOJO_SLICE_STOP_OMITTED'
        for k, v in (kwargs or []):
            if k == 'maxsplit':
                maxsplit = gen._to_int64(*gen.lower_expr(v))
        if len(args) > 1:
            maxsplit = gen._to_int64(*arg_pairs[1])
        t = gen._call_expr('MojoList *', 'mojo_bytes_split_max',
                           [('MojoBytes *', ov), ('MojoBytes *', sep),
                            ('int64_t', maxsplit), ('int', '1' if method == 'rsplit' else '0')])
        gen._elem_types[t] = 'MojoBytes *'
        return 'MojoList *', t
    if method == 'splitlines':
        keepends = '0'
        for k, v in (kwargs or []):
            if k == 'keepends':
                keepends = gen._to_int64(*gen.lower_expr(v))
        if arg_pairs and arg_pairs[0][0] != 'void':
            keepends = gen._to_int64(*arg_pairs[0])
        t = gen._call_expr('MojoList *', 'mojo_bytes_splitlines_keep',
                           [('MojoBytes *', ov), ('int', keepends)])
        gen._elem_types[t] = 'MojoBytes *'
        return 'MojoList *', t
    if method in ('partition', 'rpartition') and arg_pairs:
        sep = _coerce_to_bytes(gen, *arg_pairs[0])
        fn = 'mojo_bytes_rpartition' if method == 'rpartition' else 'mojo_bytes_partition'
        t = gen._call_expr('MojoList *', fn, [('MojoBytes *', ov), ('MojoBytes *', sep)])
        gen._elem_types[t] = 'MojoBytes *'
        return 'MojoList *', t

    if method == 'join' and arg_pairs:
        # DESIGN.html R1/R5: shared with all()/any()/enumerate()/str.join()/
        # shlex.join() - see _materialize_as_list (`b''.join(some_dict)`
        # joins its keys, real Python semantics); a genuinely-unknown boxed
        # handle is now also runtime-guarded (mojo_is_registered_dict/_set)
        # there instead of blindly assuming list.
        it = gen._materialize_as_list(arg_pairs[0][0], arg_pairs[0][1])
        _je = gen._elem_types.get(_gmm_as_str(it)) or gen._elem_types.get(arg_pairs[0][1])
        if _je and gen._bytes_subclass_of(_je):
            # Elements are `class X(bytes)` instances — `b''.join(...)`
            # operates on their `_data: MojoBytes *` payloads, not the
            # struct pointers. Build a converted MojoBytes* list first.
            # See bugs/COMPILE_FAIL_zipfile___init__.md.
            _conv = gen._new_val('MojoList *', 'mojo_list_new ()')
            _jlen = gen._new_val('int64_t', f"mojo_list_len ({it})")
            _ji = gen._new_temp('int64_t')
            gen._emit(f"  {_ji} = 0;")
            _bc = gen._new_bb(); _bb = gen._new_bb(); _ba = gen._new_bb()
            gen._emit(f"  goto {_bc};")
            gen._emit_label(_bc)
            _jc = gen._new_val('_Bool', f"{_ji} < {_jlen}")
            gen._emit(f"  if ({_jc}) goto {_bb}; else goto {_ba};")
            gen._emit_label(_bb)
            _raw = gen._new_val(_je, f"({_je}) mojo_list_get_int ({it}, {_ji})")
            _pl = gen._new_val('int64_t', f"(int64_t) {_raw}->_data")
            gen._emit_call('void', '', 'mojo_list_append_int',
                           [('MojoList *', _conv), ('int64_t', _pl)])
            gen._emit(f"  {_ji} = {_ji} + 1;")
            gen._emit(f"  goto {_bc};")
            gen._emit_label(_ba)
            it = _conv
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_join',
                                             [('MojoBytes *', ov), ('MojoList *', it)])

    if method == 'replace' and arg_pairs:
        # `replace(old, new, count=-1)` — count 0 is a legal no-op replace.
        a0 = _coerce_to_bytes(gen, *arg_pairs[0])
        a1 = _coerce_to_bytes(gen, *arg_pairs[1])
        if len(arg_pairs) < 3 and not any(k == 'count' for k, _ in (kwargs or [])):
            return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_replace',
                                                [('MojoBytes *', ov), ('MojoBytes *', a0),
                                                 ('MojoBytes *', a1)])
        cnt = 'MOJO_SLICE_STOP_OMITTED'
        for k, v in (kwargs or []):
            if k == 'count':
                cnt = gen._to_int64(*gen.lower_expr(v))
        if len(arg_pairs) > 2:
            cnt = gen._to_int64(*arg_pairs[2])
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_replace_n',
                                            [('MojoBytes *', ov), ('MojoBytes *', a0),
                                             ('MojoBytes *', a1), ('int64_t', cnt)])

    if method in ('strip', 'lstrip', 'rstrip'):
        chars = 'NULL'
        if arg_pairs and arg_pairs[0][0] != 'void':
            chars = _coerce_to_bytes(gen, *arg_pairs[0])
        do_left = '1' if method in ('strip', 'lstrip') else '0'
        do_right = '1' if method in ('strip', 'rstrip') else '0'
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_strip',
                                             [('MojoBytes *', ov), ('MojoBytes *', chars),
                                              ('int', do_left), ('int', do_right)])

    if method in ('upper', 'lower'):
        fn = 'mojo_bytes_upper' if method == 'upper' else 'mojo_bytes_lower'
        return 'MojoBytes *', gen._call_expr('MojoBytes *', fn, [('MojoBytes *', ov)])

    if method in ('title', 'capitalize', 'swapcase'):
        return 'MojoBytes *', gen._call_expr('MojoBytes *', f'mojo_bytes_{method}',
                                             [('MojoBytes *', ov)])

    if method in ('ljust', 'rjust', 'center', 'zfill'):
        # `width` is a named parameter, so `b'a'.ljust(width=4, fillchar=b'.')`
        # is legal Python and must not read the KEYWORD's value as the width:
        # taking arg_pairs[0] unconditionally made that call pad with the
        # width taken from `fillchar` and answered b'a'. The keyword wins,
        # then the first positional, as in Python.
        width = None
        for k, v in (kwargs or []):
            if k == 'width':
                width = gen._to_int64(*gen.lower_expr(v))
        if width is None:
            width = gen._to_int64(*arg_pairs[0]) if arg_pairs else '0'
        if method == 'zfill':
            return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_zfill',
                                                [('MojoBytes *', ov), ('int64_t', width)])
        fill = _bytes_fill_char(gen, args, kwargs)
        return 'MojoBytes *', gen._call_expr('MojoBytes *', f'mojo_bytes_{method}',
                                             [('MojoBytes *', ov), ('int64_t', width),
                                              ('int', fill)])

    if method in ('removeprefix', 'removesuffix') and arg_pairs:
        pv = _coerce_to_bytes(gen, *arg_pairs[0])
        return 'MojoBytes *', gen._call_expr('MojoBytes *', f'mojo_bytes_{method}',
                                             [('MojoBytes *', ov), ('MojoBytes *', pv)])

    if method == 'translate' and arg_pairs:
        tbl = _coerce_to_bytes(gen, *arg_pairs[0])
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_translate',
                                             [('MojoBytes *', ov), ('MojoBytes *', tbl)])

    _is_kind = _bytes_is_kind(method)
    if _is_kind is not None:
        t = gen._call_expr('int', 'mojo_bytes_is', [('MojoBytes *', ov), ('int', str(_is_kind))])
        return '_Bool', gen._new_val('_Bool', f'{t} != 0')

    if method in _BYTES_STR_ONLY_PREDICATES:
        _raise_bytes_str_only_predicate(gen, method)
        return gen._stub_result('_Bool', '0', f'bytes.{method}() — raises at runtime')

    if method in ('encode',):
        return 'MojoBytes *', ov

    # ── bytearray mutation (bytearray shares the MojoBytes * C type) ──────
    if method == 'append' and arg_pairs:
        v = gen._to_int64(*arg_pairs[0])
        gen._emit(f"  mojo_bytearray_append ({ov}, {v});")
        return 'void', ov
    if method == 'extend' and arg_pairs:
        other = _coerce_to_bytes(gen, *arg_pairs[0])
        gen._emit(f"  mojo_bytearray_extend ({ov}, {other});")
        return 'void', ov
    if method == 'insert' and arg_pairs:
        i = gen._to_int64(*arg_pairs[0])
        v = gen._to_int64(*arg_pairs[1])
        gen._emit(f"  mojo_bytearray_insert ({ov}, {i}, {v});")
        return 'void', ov
    if method == 'remove' and arg_pairs:
        v = gen._to_int64(*arg_pairs[0])
        gen._emit(f"  mojo_bytearray_remove ({ov}, {v});")
        return 'void', ov
    if method == 'pop':
        i = gen._to_int64(*arg_pairs[0]) if arg_pairs else 'MOJO_SLICE_STOP_OMITTED'
        return 'int64_t', gen._call_expr('int64_t', 'mojo_bytearray_pop',
                                         [('MojoBytes *', ov), ('int64_t', i)])
    if method == 'clear':
        gen._emit(f"  mojo_bytearray_splice ({ov}, 0, mojo_bytes_len ({ov}), mojo_bytearray_new ());")
        return 'void', ov
    if method == 'copy':
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytearray_copy',
                                             [('MojoBytes *', ov)])
    if method == 'tobytes':
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_bytes_copy',
                                             [('MojoBytes *', ov)])

    return gen._stub_result('int', '0', f'TODO: bytes.{method}')


def _lower_memoryview_method(gen, ov: str, method: str, args: list, kwargs=None) -> tuple:
    """Lower `MojoMemoryView *` method calls (1-D byte view)."""
    arg_pairs = [gen.lower_expr(a) for a in args]
    if method == '__len__':
        return 'int64_t', gen._call_expr('int64_t', 'mojo_memoryview_len',
                                         [('MojoMemoryView *', ov)])
    if method == 'tobytes':
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_memoryview_tobytes',
                                             [('MojoMemoryView *', ov)])
    if method == 'hex':
        return 'char *', gen._call_expr('char *', 'mojo_memoryview_hex',
                                        [('MojoMemoryView *', ov)])
    if method == 'cast':
        fmt = '"B"'
        for k, v in (kwargs or []):
            if k == 'format':
                fmt = gen.lower_expr(v)[1]
        if arg_pairs and arg_pairs[0][0] == 'char *':
            fmt = arg_pairs[0][1]
        return 'MojoMemoryView *', gen._call_expr('MojoMemoryView *', 'mojo_memoryview_cast',
                                                  [('MojoMemoryView *', ov), ('char *', fmt)])
    if method == 'nbytes':
        return 'int64_t', gen._call_expr('int64_t', 'mojo_memoryview_nbytes',
                                         [('MojoMemoryView *', ov)])
    if method == 'itemsize':
        return 'int64_t', gen._call_expr('int64_t', 'mojo_memoryview_itemsize',
                                         [('MojoMemoryView *', ov)])
    if method == 'format':
        return 'char *', gen._call_expr('char *', 'mojo_memoryview_format',
                                        [('MojoMemoryView *', ov), ('char *', '"B"')])
    if method == 'obj':
        return 'MojoBytes *', gen._call_expr('MojoBytes *', 'mojo_memoryview_obj',
                                             [('MojoMemoryView *', ov)])
    if method == 'readonly':
        # A real query, not a fold: the answer is the mutability of the
        # object the view was taken over, which MojoMemoryView records from
        # its source (`readonly` field, see fire_runtime.h). It used to be
        # constant-folded to `0` on the grounds that "this representation is
        # always a writable 1-D byte window" — true of the WINDOW, wrong for
        # the ANSWER, and it made `memoryview(b'abcd').readonly` False where
        # CPython (correctly) says True, because the view is over an
        # immutable object.
        t = gen._call_expr('int', 'mojo_memoryview_readonly', [('MojoMemoryView *', ov)])
        return '_Bool', gen._new_val('_Bool', f'{t} != 0')
    if method in ('c_contiguous', 'f_contiguous', 'contiguous'):
        # Genuinely constant: a 1-D byte window over contiguous memory is
        # C-contiguous by construction, and `f_contiguous`/`contiguous` are
        # the same fact under this representation.
        return '_Bool', gen._new_val('_Bool', '1')
    if method in ('release', '__enter__', '__exit__'):
        # No refcount model — context-manager / release is a no-op that
        # yields the view itself (so `with memoryview(x) as m:` binds m).
        return 'MojoMemoryView *', ov
    return gen._stub_result('int', '0', f'TODO: memoryview.{method}')


def _repack_method_call_spread_args(gen, mangled: str, struct_name: str,
                                     method: str, call_args: list,
                                     arg_pairs: list) -> list:
    """Fix up `obj.method(fixed_arg, *args, **kwargs)` when `method`'s
    own declared signature is `(self, fixed_param, *args, **kwargs)`.

    `_lower_named_call` (free functions) already has an equivalent fix
    for the pure-forwarding shape `f(*a, **k)` — `_lower_UnaryOp`
    passes an already-packed `MojoList *`/`MojoDict *` straight
    through for a spread, which is exactly the right shape when the
    ONLY call-site args are spreads. But `_lower_struct_method_call`'s
    generic arg-building (`[self.lower_expr(a) for a in node.args]`)
    never had the analogous fix — that file's own comment on
    `_func_kwargs_slot` explicitly says so ("never fires for struct
    methods, a separate call-lowering path, out of scope") — so a
    MIXED call site with a real fixed positional arg (that doesn't
    correspond to one of the callee's own fixed params) followed by a
    `*args`/`**kwargs` spread produced one raw C argument per AST arg
    (arity/type mismatch against the callee's real, packed signature)
    instead of merging the extra leading arg into the vararg list.
    Real instance: `BoundMethod.__call__` (myinterpreter.py) calling
    `f(self.interpreter, self.instance, *args, **kwargs)` where `f` is
    a `MojoFunction` whose own `__call__(self, interpreter, *args,
    **kwargs)` has exactly ONE real fixed param (`interpreter`) — see
    bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
    "Segfault root-caused" section. Invisible under a `__GIMPLE`-
    tagged caller (raw GIMPLE bypasses gcc's normal call-argument
    arity/type checking); surfaced once the caller genuinely lost
    `__GIMPLE` for an unrelated, correct reason.

    A complete no-op unless `_func_kwargs_slot` has an entry for this
    exact method (never populated for ordinary struct methods today —
    only explicitly hardcoded self-host entries, e.g.
    `MojoFunction___call__` — so this can't affect any other call
    site), keeping the blast radius to exactly the shape it exists
    to fix.
    """
    kw_i = gen._func_kwargs_slot.get(
        mangled, gen._func_kwargs_slot.get(f"{struct_name}_{method}", -1))
    if kw_i < 0:
        return arg_pairs
    # Explicit loop, NOT `any(<genexpr>)` — the genexpr/`any` shape is the
    # established self-hosted trap (its materialized list came back garbage
    # and `mojo_list_get_int` on it SIGSEGV'd).
    has_spread = False
    for _ca0 in call_args:
        if isinstance(_ca0, gimple_ctypes.UnaryOp) and _ca0.op in ('*', '**'):
            has_spread = True
            break
    if not has_spread:
        return arg_pairs
    has_vararg = gen._func_kwargs_has_vararg.get(
        mangled, gen._func_kwargs_has_vararg.get(f"{struct_name}_{method}", True))
    # kw_i counts `self` at index 0 and the vararg (`*args`, collapsed
    # to one MojoList* slot) immediately before it -- so the real
    # number of ordinary fixed params AFTER self is kw_i - 2 (or
    # kw_i - 1 when there's no `*args`, just `**kwargs` directly).
    n_fixed = max(0, kw_i - (2 if has_vararg else 1))
    if len(arg_pairs) <= n_fixed:
        return arg_pairs  # already the right shape (e.g. f(*a, **k))
    fixed_pairs = arg_pairs[:n_fixed]
    rest_args = call_args[n_fixed:]
    rest_pairs = arg_pairs[n_fixed:]
    dict_pair = None
    # Indexed loops, NOT `zip(rest_args, rest_pairs)` with a nested
    # `for a_node, (a_t, a_v)` tuple unpack — that shape is the same
    # self-hosted tuple/zip boxing trap the rest of this codebase
    # documents (`_gen_for_zip`, `_as_str` element views).
    if has_vararg:
        lst = gen._new_val('MojoList *', "mojo_list_new ()")
        for _pi0 in range(len(rest_pairs)):
            a_node = rest_args[_pi0]
            _ap0 = rest_pairs[_pi0]
            a_t = _ap0[0]
            a_v = _ap0[1]
            if isinstance(a_node, gimple_ctypes.UnaryOp) and a_node.op == '*':
                gen._emit(f"  mojo_list_extend ({lst}, {a_v});")
            elif isinstance(a_node, gimple_ctypes.UnaryOp) and a_node.op == '**':
                dict_pair = (a_t, a_v)
            else:
                av = gen._coerce_to_type(a_t, 'int64_t', a_v)
                gen._emit(f"  mojo_list_append_int ({lst}, {av});")
        fixed_pairs.append(('MojoList *', lst))
    else:
        for _pi1 in range(len(rest_pairs)):
            a_node = rest_args[_pi1]
            _ap1 = rest_pairs[_pi1]
            a_t = _ap1[0]
            a_v = _ap1[1]
            if isinstance(a_node, gimple_ctypes.UnaryOp) and a_node.op == '**':
                dict_pair = (a_t, a_v)
    if dict_pair is None:
        dict_pair = ('MojoDict *', ggc._pack_kwargs_dict(gen, {}))
    fixed_pairs.append(dict_pair)
    return fixed_pairs


def _lower_struct_method_call(gen, ov: str, ot: str, method: str, node) -> tuple:
    """Lower struct/class method calls: obj.method(args) → StructName_method(self, args)."""
    func = node.func
    is_class_ref = False
    # `cls.method(...)` inside a @classmethod: the receiver `cls` (in `ov`)
    # IS a real argument that must be prepended, exactly like `self` on an
    # instance-method call — unlike `StructName.method(...)` (a name-call
    # with no receiver value). Tracked separately so the "first C param
    # isn't `Struct *`" heuristic below (which is meant for `StructName.
    # staticmethod()`) does not wrongly suppress the `cls` argument.
    _is_cls_receiver = False
    if isinstance(func.obj, gimple_ctypes.IdentExpr) and func.obj.name in gen.struct_field_types:
        struct_name = func.obj.name
        is_class_ref = True
    elif isinstance(func.obj, gimple_ctypes.IdentExpr) and func.obj.name == 'cls':
        # `cls` is the classmethod receiver — resolve it to the struct
        # enclosing the current classmethod (current_func_name is e.g.
        # `TypeLattice_join_all` for a @classmethod inside TypeLattice).
        # Without this, `cls.join(...)` inside a classmethod compiled to
        # mojo_str_join (the `cls` receiver lowered to an opaque int and
        # `.join` resolved as a string method) — a hard segfault once the
        # self-host gate made these classmethod bodies actually compile.
        _cn = gen.current_func_name
        # Longest `_`-separated prefix that names a real struct or a
        # compiled `{prefix}_{method}` — NOT `rsplit('_', 1)`, which is
        # wrong when the ENCLOSING method's own name has an underscore
        # (`TypeLattice_join_all` -> 'TypeLattice_join', so `cls.join`
        # fell through here, `is_class_ref` stayed false, and the "first
        # param isn't Struct *" heuristic then dropped the `cls` arg and
        # padded a NULL — `join_all`'s inner `cls.join(result, t)` became
        # `TypeLattice_join(result, t, 0)`, corrupting every multi-element
        # `_infer_list_elem_type` / return-type join).
        _sn = ''
        if _cn:
            _pp = _cn.split('_')
            for _kk in range(len(_pp), 0, -1):
                _cand = '_'.join(_pp[:_kk])
                if (_cand in gen.struct_field_types
                        or f'{_cand}_{method}' in gen.func_return_types):
                    _sn = _cand
                    break
        if _sn and (_sn in gen.struct_field_types
                    or f'{_sn}_{method}' in gen.func_return_types):
            struct_name = _sn
            # `cls.a_staticmethod(...)` inside a @classmethod: unlike an
            # ordinary/classmethod target, a @staticmethod takes NO
            # implicit receiver at all — `cls` here is just the lookup
            # path, not an argument. Without this check every such call
            # (e.g. tarfile.py's `TarInfo.create_pax_header`, a
            # @classmethod, calling `cls._create_header(...)`, a
            # @staticmethod) got `cls` wrongly prepended as arg 0,
            # producing "too many arguments; expected N, have N+1".
            _is_cls_receiver = (
                f"{_sn}_{gimple_ctypes._safe_name(method)}" not in gen._static_methods)
        else:
            struct_name = gimple_exprtypes._struct_name_of(ot)
    else:
        struct_name = gimple_exprtypes._struct_name_of(ot)
        if struct_name == 'int' and method in ('set', '__call__'):
            if isinstance(func.obj, gimple_ctypes.MemberExpr) and isinstance(func.obj.obj, gimple_ctypes.IdentExpr):
                if func.obj.obj.name == 'self':
                    if method == 'set' and func.obj.member == 'parent':
                        struct_name = 'Scope'
    # Same-file overload resolution: if this method's overloads were
    # registered from the CURRENT file's own AST (Pass 2b-bis), pick the
    # one matching this call site's arity/types instead of always
    # building the unsuffixed name — which is only ever actually defined
    # when the method isn't overloaded (see _struct_method_overload_ids:
    # overload_id is '' unless 2+ methods share this name). A struct
    # known only via dylib reflection has no entry here and falls
    # through to the unsuffixed name unchanged (cross-module overload
    # resolution is a separate follow-on, elaborate.py extension).
    _method_candidates = gen._struct_method_signatures.get(_gmm_sms_key(struct_name, method))
    _method_overload_suffix = ''
    _chosen_method = None
    # `len > 1` alone (the original gate) skipped overload resolution
    # entirely for a NON-overloaded method (the overwhelmingly common
    # case: exactly 1 registered candidate) -- fine for a positional-only
    # call site (the `else` branch below, `[gen.lower_expr(a) for a in
    # node.args]`, already handles that correctly), but a call site using
    # KEYWORD arguments against that single candidate fell through to the
    # SAME plain-positional `else` branch, which reads only `node.args`
    # and completely ignores `node.kwargs` -- every keyword argument was
    # silently dropped, later padded with the callee's own DEFAULT value
    # by the "pad missing trailing args" step below, regardless of what
    # was actually passed. `_resolve_overload` already handles a
    # single-entry candidate list correctly (returns it outright once
    # arity/kwarg-name checks pass), so also engaging it here for the
    # `node.kwargs` case reuses the same, already-correct,
    # kwargs-by-name-to-positional-slot binding
    # (`_build_call_args_for_candidate`) the genuinely-overloaded case
    # already relies on. Root-caused via `self._parse_funcdef(decs,
    # is_async=is_async)` in this compiler's own fire_compiler.py:
    # self-hosted, EVERY call site passing `is_async=True`/`is_async=
    # is_async` compiled to a hardcoded `(int64_t)0` regardless of the
    # real value, because `_parse_funcdef` has exactly one definition (no
    # overloads) -- confirmed by inspecting the generated GIMPLE C
    # directly (`_t60 = (int64_t)0;` at every one of the 5 real call
    # sites, even the literal `is_async=True` one). Downstream effect:
    # `FunctionDef.is_async` read back False for every genuinely-async
    # function parsed by the self-hosted compiler, corrupting the A3
    # stack-switch coroutine-detection prepass for any FILE COMPILED BY
    # THE SELF-HOSTED BINARY (gimple_gen_coro.py's `lower()`), a
    # plausible major contributor to the aside/bside sweep's CI-DIFF
    # backlog for any async-using file.
    # `_as_callexpr_node`: read `node.args`/`node.kwargs` as DIRECT struct
    # fields. A reflective `node.kwargs` read goes through
    # `_mojo_dispatch_getattr`, whose per-type table does not reliably carry
    # a CallExpr case (see bugs/CODEGEN_noshim_dumpfull_preexisting_
    # divergence.md continuation 7) — the miss sentinel 1 then made
    # `len(node.kwargs)` SIGSEGV in mojo_list_len(0x1). Same fix family as
    # `_gmm_as_str`/`_as_ident_node`.
    _cnode = _gmm_callexpr_node(node)
    # Compute counts into explicit ints and compare them, rather than
    # letting a MojoList-valued operand (`_cnode.kwargs`) participate in the
    # `or`/`and`. On the self-hosted path a boolean `or` whose operands are
    # `(<int> > <int>)` and a `MojoList *` was itself typed `MojoList *`, so
    # the enclosing `if` lowered to `mojo_list_len(<the boolean>)` and
    # SIGSEGV'd on `mojo_list_len(0x1)` for a 1-element candidate list
    # (std/collections/interval.mojo's IntervalTree.insert). All-bool
    # operands keep the condition's type bool.
    _n_candidates = 0
    if _method_candidates is not None:
        _n_candidates = len(_method_candidates)
    _n_kwargs = 0
    if _cnode.kwargs is not None:
        _n_kwargs = len(_cnode.kwargs)
    if _n_candidates > 0 and (_n_candidates > 1 or _n_kwargs > 0):
        _chosen_method = ggc._resolve_overload(gen, _method_candidates, _cnode.args, _cnode.kwargs)
        if _chosen_method is not None:
            _method_overload_suffix = _chosen_method['overload_id']
    # `_gmm_as_str`: `_struct_method_csym`'s `-> str` return type goes
    # UNRESOLVED at this call site (an imported/GimpleGen method), so the
    # codegen typed `mangled` int64_t and every following
    # `dict.get(mangled)` key-coercion rewrote the key through
    # `mojo_str_from_int(<pointer>)` — the pointer's DECIMAL ADDRESS, never
    # the real "Struct_method" key. Every `_func_param_defaults` /
    # `func_return_types` / `_KNOWN_SIGS` lookup by mangled name then
    # missed. Re-tag as `str`.
    mangled = _gmm_as_str(_ggf._struct_method_csym(gen, struct_name, method, _method_overload_suffix))
    # Prefer the candidate's own precomputed return type (Pass 2b-bis) over
    # func_return_types[suffixed_key], which is only populated once THAT
    # overload's own body is emitted (Phase 2a, declaration order) — a call
    # from an earlier sibling overload's body would otherwise see nothing
    # yet and silently default to int64_t below.
    # Check the actually-emitted (possibly module-qualified) name FIRST —
    # a struct known only via dylib reflection (_register_reflected_struct)
    # registers its return/param types ONLY under the qualified key, since
    # that's the only symbol name that really exists; the bare fallback
    # below still matters for in-file/same-module methods, whose entries
    # are registered under the bare key by the earlier pre-pass.
    # Fallback to func_return_types[mangled] for structs not covered by
    # _struct_method_signatures (imported/reflected structs registered
    # after Pass 2b-bis, notably via _register_imported_structs).
    ret_type = _chosen_method['ret_type'] if _chosen_method is not None else \
        gen.func_return_types.get(mangled,
            gen.func_return_types.get(f"{struct_name}_{method}{_method_overload_suffix}", None))
    if ret_type is None and mangled in gen._KNOWN_SIGS:
        ret_type = gen._KNOWN_SIGS[mangled][0]
    if (ret_type is None and method == 'copy'
            and f"{struct_name}_copy" not in gen.func_return_types
            and f"{struct_name}_copy" not in gen._KNOWN_SIGS):
        return 'int64_t', gen._new_val('int64_t', f"(int64_t){ov}")
    if ret_type is None:
        if method in ('get', 'get_symbol_type', 'pop', 'keys', 'values', 'items'):
            ret_type = 'char *' if method in ('get', 'get_symbol_type', 'pop') else 'MojoList *'
        elif method in ('load',):
            ret_type = 'int64_t'
        else:
            ret_type = 'int64_t'
    # Bind keyword args to the resolved overload's parameter positions,
    # and (when the overload has a `*args` pack, e.g. DeviceGraphBuilder.
    # add_function's *Ts-typed variadic overloads) box the pack-matched
    # positional args into the MojoList* the real signature expects
    # instead of trying to pass them one-for-one by flat position — see
    # _build_call_args_for_candidate. Previously a kwarg-only call always
    # went through the unsuffixed catch-all variadic stub, which silently
    # dropped kwargs since it accepts any args; now that a real,
    # concretely-typed candidate is resolved, the value must actually be
    # passed.
    # Recorded parameter defaults for this method (gimple_module_gen.py's
    # Pass 10 populates `_func_param_defaults[f"{struct}_{method}"]` from
    # `m.param_defaults` — same source `_lower_named_call` uses for free
    # functions). `[(pname, default_ast), ...]`, only params that HAVE a
    # default, starting at the first defaulted position.
    _gpd1 = gen._func_param_defaults.get(mangled)
    _method_dflts = (_gpd1
                     or gen._func_param_defaults.get(
                         f"{struct_name}_{method}{_method_overload_suffix}")
                     or gen._func_param_defaults.get(f"{struct_name}_{method}")
                     or [])
    # Explicit loop, NOT `{pn: dv for pn, dv in _method_dflts}` (self-host
    # comprehension trap; tuple-unpacked `pn` also erases to int64_t).
    _method_dflt_map = {}
    for _dflt in _method_dflts:
        if not isinstance(_dflt, tuple):
            continue
        _pn0, _dv0 = _dflt
        _method_dflt_map[_gmm_as_str(_pn0)] = _dv0
    if _chosen_method is not None:
        arg_pairs = ggc._build_call_args_for_candidate(
            gen, _chosen_method, _cnode.args, _cnode.kwargs, defaults=_method_dflt_map)
    else:
        # Explicit accumulation loop, NOT `[gen.lower_expr(a) for a in
        # _cnode.args]` — a list comprehension is the established
        # self-hosted trap (result erased to the garbage non-list 1).
        arg_pairs = []
        for _a2 in _cnode.args:
            arg_pairs.append(gen.lower_expr(_a2))
        arg_pairs = _repack_method_call_spread_args(
            gen, mangled, struct_name, method, _cnode.args, arg_pairs)
    full_param_list = gen.func_param_types.get(mangled,
        gen.func_param_types.get(f"{struct_name}_{method}{_method_overload_suffix}", []))
    # The method-parameter registration passes key `func_param_types` by
    # the RAW method name (`ZipFile_open`), but `mangled` runs the name
    # through `_safe_name`, which rewrites C-reserved names (`open` ->
    # `mojo_open`). `_emit_call` only looks up `func_param_types[fname]`
    # with `fname == mangled`, so for such a method it found nothing and
    # skipped ALL argument coercion — a `char *` filename passed straight
    # into an `int64_t name` slot ("makes integer from pointer without a
    # cast"). Mirror the known signature onto the mangled key here.
    # COMPILE_FAIL_zipfile___init__.md blocker 2.
    if full_param_list and mangled not in gen.func_param_types:
        gen.func_param_types[mangled] = list(full_param_list)
    if (not is_class_ref and not _is_cls_receiver
            and full_param_list and full_param_list[0] != f"{struct_name} *"):
        is_class_ref = True
    # A @staticmethod called THROUGH AN INSTANCE (`obj.my_staticmethod()`
    # — real Python allows this; the instance is simply not passed,
    # unlike an ordinary/classmethod call) still needs no implicit
    # receiver arg, exactly like the class-name-call path above already
    # special-cases via `_static_methods`. The `full_param_list[0] !=
    # "{struct_name} *"` heuristic just above can't detect this for a
    # TRULY zero-parameter static method (`full_param_list` itself is
    # empty, so the `and full_param_list` guard short-circuits) — found
    # via Tools/ftscalingbench/ftscalingbench.py's `obj.my_staticmethod()`
    # ("too many arguments... expected 0, have 1").
    if (not is_class_ref and not _is_cls_receiver
            and f"{struct_name}_{gimple_ctypes._safe_name(method)}" in gen._static_methods):
        is_class_ref = True
    # `_is_cls_receiver`: `cls` is prepended as arg 0 (like `self`), so one
    # C parameter is supplied by the receiver — same as `not is_class_ref`.
    expected_non_self = len(full_param_list) - (0 if (is_class_ref and not _is_cls_receiver) else 1)
    if full_param_list and len(arg_pairs) < expected_non_self:
        # Pad missing trailing args with the method's OWN recorded defaults
        # (`def _emit_label(self, label, freq_hint='')` called as
        # `gen._emit_label(label)` must pad with `""`, not `0`), mirroring
        # `_lower_named_call`'s free-function padding. `_method_dflts` holds
        # only the params that have a default, starting at the first
        # defaulted position, so it indexes from
        # `expected_non_self - len(_method_dflts)` (BUG-2026-020 shape).
        _first_dflt = expected_non_self - len(_method_dflts)
        while len(arg_pairs) < expected_non_self:
            _pos = len(arg_pairs)
            _dv = (_method_dflts[_pos - _first_dflt][1]
                   if 0 <= _pos - _first_dflt < len(_method_dflts) else None)
            arg_pairs.append(ggc._default_expr_to_pair(gen, _dv)
                             if _dv is not None else ('int', '0'))
    # Auto-stub if the mangled method name has no known declaration. Check
    # both the suffixed key (this specific overload) and the bare key
    # (set for ANY overload by Pass 2b's return-type inference, which
    # runs to a fixpoint before any method body is lowered) — a same-
    # struct call from one overload's body into a not-yet-processed
    # sibling overload only has the bare key available at this point,
    # since the suffixed key is only set when THAT overload's own
    # definition is emitted, which may happen later in emission order.
    if (mangled not in gen._KNOWN_SIGS
            and mangled not in gen.func_return_types
            and f'{struct_name}_{method}{_method_overload_suffix}' not in gen.func_return_types
            and f'{struct_name}_{method}' not in gen.func_return_types
            and mangled not in gen._auto_stubbed
            and mangled not in gimple_codegen._SELFHOST_HARDCODED_FUNCS
            and f'{struct_name}_{method}' not in gimple_codegen._SELFHOST_HARDCODED_FUNCS):
        _stub_guard = gimple_ctypes._stub_guard_name(f'{struct_name}_{method}')
        # A struct with at least one base class we couldn't resolve to a
        # known StructDef (e.g. `class IDGatherer(html.parser.HTMLParser)`
        # — an external/unmodeled class) may call inherited methods
        # (`self.feed(...)`) that are genuinely never defined anywhere in
        # this program — not now, not later in this TU, not in any other
        # module. A bare forward declaration below (`int64_t X (...);`)
        # is fine for the ordinary case this auto-stub exists for (a
        # same-struct sibling method not yet emitted, which gets a real
        # definition later), but here it just leaves an undefined symbol
        # at link time (bugs/consolidated/
        # COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md). Emit an
        # actual (weak) definition instead, matching the existing
        # "unavailable in compiled mode" convention _stub_only_modules
        # uses just below for imports from unresolvable modules.
        if struct_name in getattr(gen, '_structs_with_unresolved_base', ()):
            # The first parameter must match the real call site's actual
            # receiver type (`{struct_name} *`, the same struct this
            # method is being called on) — not int64_t. A bare int64_t
            # here mismatched the real pointer argument every call site
            # passes, producing a *new* `-Wint-conversion` "makes integer
            # from pointer without a cast" hard error (a different entry
            # in the same bugs/consolidated/ compile-fail catalog) in
            # place of the undefined-symbol error this stub exists to fix.
            _stub = (f'#ifndef {_stub_guard}\n#define {_stub_guard}\n'
                      f'__attribute__((weak)) int64_t {mangled} ({struct_name} *_self, ...) '
                      f'{{ (void)_self; mojo_print ((char *)'
                      f'"{struct_name}.{method}: unavailable in compiled mode '
                      f'(inherited from an unmodeled base class)"); return (int64_t)0; }}\n#endif')
        else:
            _stub = f'#ifndef {_stub_guard}\n#define {_stub_guard}\nint64_t {mangled} (...);\n#endif'
        if _stub not in gen._elaborated_externs:
            gen._elaborated_externs.append(_stub)
        gen._auto_stubbed.add(mangled)

    # For a `cls.` receiver the value passed is the classmethod's own
    # `int64_t cls` (a class-tag placeholder, not a real struct pointer) —
    # prepend it as `int64_t` so call-site parameter inference doesn't
    # decide the callee's `cls` param is a `Struct *`.
    _recv_pair = ('int64_t', ov) if _is_cls_receiver else (ot, ov)
    _prepend_recv = (not is_class_ref) or _is_cls_receiver
    # Explicit accumulation, NOT `([_recv_pair] + arg_pairs) if _prepend_recv
    # else arg_pairs`: a list-literal `+` concat is the established
    # self-hosted trap (element/element-type erasure; here it produced the
    # garbage non-list 1, which `_call_expr` then iterated -> `mojo_list_len
    # (0x1)` SIGSEGV compiling std/collections/dict.mojo).
    all_arg_pairs = []
    if _prepend_recv:
        all_arg_pairs.append(_recv_pair)
    for _ap0 in arg_pairs:
        all_arg_pairs.append(_ap0)
    if ret_type == 'void':
        return gen._void_call(mangled, all_arg_pairs)
    t = gen._call_expr(ret_type, mangled, all_arg_pairs)

    if mangled in gen._return_elem_types:
        gen._elem_types[t] = gen._return_elem_types[mangled]
        if ret_type in ('int', 'int64_t'):
            gen._actual_types[t] = 'MojoList *'
    return ret_type, t
