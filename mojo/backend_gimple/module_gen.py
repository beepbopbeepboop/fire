# Moved from gimple_module_gen.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""gen_module implementation.

Entire original GimpleGen.gen_module body, hoisted verbatim.
Takes `self` (GimpleGen instance) and `stmts` (top-level AST
statements); returns the generated C source string.
"""
from __future__ import annotations

import os
import re
import sys

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
    py_tokenize, Parser, _as_str, _as_dict, _as_list, _sms_key, _pair_key, _as_funcdef_node, _ptr_slot_in_range,
    _as_int, _as_intlit_node, _as_boollit_node, _as_structdef_node, _signed_int64, _signed_int64_c_literal,
)
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import mojo.middle.coro as gimple_gen_coro
# `mojo.middle.infra_infer` is imported at its USE SITE, not here, and that is
# the layering rule rather than a style choice. The middle tier's own
# `module_shared` says it: the direction that stays top-level is
# `middle -> gimple_codegen`, and every edge back down into the middle tier is
# deferred. This file is DOWNSTREAM of `gimple_codegen`, so a top-level
# `import mojo.middle.infra_infer` here starts the chain before
# `gimple_codegen` has defined anything, and `infra_infer`'s own top-level
# `import gimple_codegen` then leads `emit_infra`'s top-level
# `from mojo.middle.infra_infer import _FC_SEP, ...` back into a half-built
# `infra_infer`:
#
#   ImportError: cannot import name '_FC_SEP' from partially initialized
#   module 'mojo.middle.infra_infer' (most likely due to a circular import)
#
# So this module could not be a process's FIRST `mojo.*` import at all — the
# one thing `test_suite.py`'s `imports: every real entry point imports first`
# exists to catch, and the shape of it is identical for the eight middle
# modules that exemption list already names. `gimple_codegen` imports THIS
# module at its own top level, so the re-entrancy it causes is already here
# and already works; what has to stay away is the edge that begins the chain
# in the wrong direction. Same rule and same precedent as
# `emit_funcs._struct_method_qualifier`'s function-local
# `from mojo.middle.module_shared import module_qualifier`.
from mojo.middle.exprtypes import _walk_ast, expr_provably_str as _gmi_expr_provably_str
import gimple_codegen
import mojo.backend_gimple.emit_funcs as _ggf_dup
from mojo.middle.closures import discover_closures, closure_lifted_name
import mojo.backend_gimple.device_select as _gmi_device_select
import mojo.middle.offload as _gmi_offload
import mojo.backend_gimple.device_glue as _gmi_device_glue
import mojo.backend_gimple.elab_intu as _elab_intu
import mojo.backend_gimple.emit_metal as _gmi_emit_metal
import mojo.middle.funcs_shared as funcs_shared
from mojo.middle.types import _unpack_target_leaf_names
from mojo.middle.methods_shared import _is_selfhost_source_file
from gimple_codegen import ClosureInfo, DispatchSolver, TypeLattice, _CPP_KEYWORD_FIELDS, _C_KEYWORDS, _C_PARAM_EXTRA_KEYWORDS, _C_RESERVED_FUNCS, _EXPR_DISPATCH, _FIXED_ARRAY_ANN_RE, _LIST_RETURNING_METHODS, _PSEUDO_DUNDER_ATTRS, _RUNTIME_FUNCS, _SELFHOST_DIR, _SELFHOST_KWARGS_HAS_VARARG, _SELFHOST_KWARGS_SLOTS, _STMT_DISPATCH, _STR_RETURNING_METHODS, _TYPE_MAP, _UnsupportedGeneratorShape, _async_gen_quick_eligible, _async_quick_eligible, _bracket_param_type_annotations, _c_escape, _c_field_name, _c_id, _class_attr_ctype, _compute_exc_descendants, _debug_note, _declared_vars_body, _extract_init_expr, _generator_quick_eligible, _import_targets, _merge_struct_inheritance, _module_init_name, _module_toplevel_name, _mojo_type, _safe_field, _safe_name, _struct_type_id, _stub_guard_name, _used_idents_deep, _used_idents_node

# Re-export shared helpers from mojo.middle.module_shared via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.module_shared import *  # noqa: F401,F403
# `import *` skips underscore-prefixed names, and this is the single accessor
# the three dispatch-global sites below read. From `mojo.middle.types` rather
# than `module_shared`, which `gimple_codegen` imports at ITS line 70:
# reading it from there would close the cycle
# `module_gen -> module_shared -> gimple_codegen -> module_gen`, and the
# name would be unavailable at the moment the import ran.
from mojo.middle.types import _COMPILE_TIME_CALL_MODULES, dispatch_table_global_ctype
from mojo.middle.module_shared import (
    _LIST_RETURNING_METHODS, _STR_RETURNING_METHODS, _UNKNOWN_FIELD_CTYPE, _as_boollit_node, _as_dict,
    _as_funcdef_node, _as_int, _as_intlit_node, _as_str, _as_structdef_node, _bytes_subclass_new_payload_name,
    _collect_import_modules, _collect_import_modules_rec, _cpp_method_receiver_name, _extract_init_expr, _gmi_all_stmts_nonfunc, _gmi_as_str, _gmi_collect_global_stmts,
    _gmi_collect_return_values, _gmi_collect_self_assigns, _gmi_container_ctype, _gmi_find_comptime_one, _gmi_global_init_code, _gmi_phase17_collect_appends, _gmi_prefold_toplevel_comptime,
    _gmi_scan_cpp_nested_imports, _gmi_scan_func_body_for_self_attr, _gmi_scan_import_modules, _gmi_scan_imported_global_homes, _gmi_scan_try_imports, _gmi_self_member, _import_targets,
    _mojo_type, _pair_key, _ptr_slot_in_range, _register_sym, _selfhost_fn_reassigns_method, _selfhost_homogeneous_tuple_ret_funcs,
    _selfhost_modglobal_is_pathcall, _selfhost_module_scalar_globals, _selfhost_struct_dict_field_val_types, _sms_key, _walk_ast
)
# Module-qualified struct identity (the same-bare-name collision fix) — see
# `_struct_cname_by_id` in GimpleGen.__init__ and the collision pass in
# `gen_module_impl` below. Imported from funcs_shared, the same module
# `_struct_method_qualifier` lives in, so the C-name qualifier and the
# method-symbol qualifier are one function on one input.
import mojo.middle.funcs_shared as _ggfs
from mojo.middle.funcs_shared import _resolve_struct_cname, _sanitize_cname_qualifier


def _gmi_literal_ctype(node):
    """The ctype of an UNAMBIGUOUS container/string literal, else None.

    "Unambiguous" is the whole point. A string literal is never a list and a
    list literal is never a string, so either one is ground truth about what
    the callee's parameter really is. Anything whose ctype depends on context
    (an identifier, an arithmetic expression, a call result) returns None
    rather than guessing.
    """
    if isinstance(node, (gimple_ctypes.StringLiteral,
                        gimple_ctypes.TstringLiteral)):
        # A BYTES literal is a `StringLiteral` too (`is_bytes` is the only
        # difference), and answering `char *` for it types every unannotated
        # `bytes` parameter at its call sites as a C string: `fn tail(b:
        # bytes) -> bytes: return b` emitted
        #
        #     MojoBytes * tail (MojoBytes * b);      /* the definition */
        #     MojoBytes * tail (char *);             /* the forward decl */
        #
        # a "conflicting types" hard error. It used to be invisible because
        # this answer only ever fed the str-vs-container ambiguity below,
        # which a `char *` cannot match against; the answer is now consulted
        # for parameters the BODY says nothing about, and that is a place
        # where a wrong ctype is a wrong compile.
        #
        # `is_bytes`, checked through `getattr` because the field only exists
        # on the literal classes that carry one, and this function also sees
        # `TstringLiteral`.
        if getattr(node, 'is_bytes', False):
            return 'MojoBytes *'
        return 'char *'
    # `fire_compiler` also exports `ListLiteral`/`SetLiteral`/... but those are
    # ALIASES of the `*Expr` classes, not subclasses, so naming them in an
    # isinstance tuple raises `AttributeError` against `mojo.middle.types` --
    # which is what `gimple_ctypes` re-exports here. Only the `*Expr` spellings
    # are real attributes.
    if isinstance(node, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr)):
        return 'MojoList *'
    if isinstance(node, gimple_ctypes.SetExpr):
        return 'MojoSet *'
    if isinstance(node, gimple_ctypes.DictExpr):
        return 'MojoDict *'
    return None


def _gmi_iter_calls(stmts, _seen=None):
    """Every CallExpr in the tree, via a generic walk over node attributes."""
    if _seen is None:
        _seen = set()
    for st in (stmts or []):
        stack = [st]
        while stack:
            node = stack.pop()
            if node is None or id(node) in _seen:
                continue
            _seen.add(id(node))
            if isinstance(node, gimple_ctypes.CallExpr):
                yield node
            for attr in ('body', 'args', 'value', 'func', 'iterable',
                         'obj', 'left', 'right', 'operand', 'target', 'elt',
                         'key', 'results', 'statements', 'expr'):
                sub = getattr(node, attr, None)
                if sub is None:
                    continue
                if isinstance(sub, (list, tuple)):
                    stack.extend(sub)
                else:
                    stack.append(sub)


def _gmi_apply_call_site_param_evidence(gen, stmts):
    """Ground an unannotated parameter in what its CALLERS actually pass.

    `_infer_param_types` infers a parameter's type from how the body USES it,
    and for an iterable-consuming builtin that inference has to collapse
    "iterable" onto one concrete container. That is lossy: `str` is iterable
    too, so `reversed(seq)` says "container" and cannot say WHICH.

    Real regression this fixes, introduced with the
    `_ITERABLE_CONSUMING_BUILTINS` signal: `def rev(seq): for c in
    reversed(seq): ...` called as `rev("abc")` inferred `seq` as
    `MojoList *`, so the call passed a `char *` into `mojo_list_copy()` and
    the process SEGFAULTED (exit -11) on ordinary Python. The parent commit
    inferred `char *` here and worked.

    The call site is the only input that can settle it, and nothing consulted
    it. This pass records the ctype of *unambiguous literal* arguments and,
    when a parameter's use-derived type contradicts every call site, believes
    the callers.

    Deliberately narrow, because this runs on every module:
      - free-function calls only (`IdentExpr` callee), so there is no
        `self`-offset ambiguity in positional alignment;
      - only when the call's arity equals the declared param count, so
        positional alignment cannot silently shift;
      - only to resolve str-vs-container, and only when the call sites are
        UNANIMOUS. One ambiguous or absent call site leaves the inference
        exactly as it was.
    A wrong override here would silently re-type a parameter, so anything
    less than unanimous evidence declines to act.
    """
    ipt = gen._inferred_param_types
    if not ipt:
        return
    names = getattr(gen, '_func_param_names', {})
    # (func, param) -> {ctype, ...} for unambiguous literal arguments only
    evidence: dict = {}
    for call in _gmi_iter_calls(stmts):
        if not isinstance(call.func, gimple_ctypes.IdentExpr):
            continue
        fname = _as_str(call.func.name)
        params = names.get(fname)
        if not params:
            continue
        args = call.args or []
        if len(args) != len(params):
            # Arity mismatch means positional alignment (an optional or
            # defaulted param, a *args call) is not trustworthy here.
            continue
        for pname, arg in zip(params, args):
            ctype = _gmi_literal_ctype(arg)
            if ctype is not None:
                evidence.setdefault((fname, pname), set()).add(ctype)

    containers = ('MojoList *', 'MojoSet *', 'MojoDict *')
    for (fname, pname), ctypes in evidence.items():
        if len(ctypes) != 1:
            continue  # not unanimous
        # `list(ctypes)[0]`, NOT `next(iter(ctypes))`: this function is part
        # of the self-host closure, and `next` is not one of the runtime
        # symbols the compiled path links (caught by `selfhost` as an
        # undefined-symbol link failure -- `_next`, referenced from
        # `_gmi_apply_call_site_param_evidence`). The set is known to hold
        # exactly one element here, so a literal subscript is both equivalent
        # and linkable.
        call_type = list(ctypes)[0]
        cur = ipt.get(fname, {}).get(pname)
        # Every UNANIMOUS literal container also grounds the callee's
        # `==` / `!=` lowering, which cannot see through an erased
        # int64_t parameter: record the KIND separately, in a table of its
        # own, so a container-typed parameter reaches
        # `mojo_value_eq`/`mojo_set_eq` instead of a pointer comparison.
        # Separate table because `_inferred_param_types` above re-types
        # parameters all over the backend and a container entry there has
        # effects far past comparison; this one is read only by the
        # comparison lowering. A unanimous CHAR * proves nothing about
        # equality (two separately-built strings compare by content through
        # a different, already-correct path), so only containers are kept.
        if call_type in containers:
            kinds = gen._container_param_kinds.setdefault(fname, {})
            kinds[pname] = ('list' if call_type == 'MojoList *' else
                            'set' if call_type == 'MojoSet *' else 'dict')
        if cur == call_type:
            continue
        # A parameter with NO use-derived evidence at all (`cur is None` —
        # `_infer_param_types` records an entry only when the BODY says
        # something, and this body says nothing) is not contradicted by
        # anything, so unanimous literal call sites are all the evidence
        # there is and this pass should believe them. That is the ordinary
        # case for a FORWARDER: `def mid(a, b): return sink(a, b, None)`
        # called as `mid('readme', 'b')` has no body evidence for `a`/`b`
        # (they are only handed to another unannotated callee), and the
        # callee `sink` therefore never saw a string at any of ITS call
        # sites — the one call site there is `sink(a, b, None)`, whose
        # arguments are exactly the names whose types this pass is about to
        # resolve. Without this arm the observation was recorded as silence,
        # `sink`'s parameters kept the `int64_t` default, and
        # `'%s and %s' % (x, y)` formatted the boxed `char *` as a decimal
        # address: `4301506648 and 4301506656`, exit 0, no diagnostic.
        #
        # Scoped to `cur is None` AND unannotated. A parameter the body DID
        # type is decided on evidence this pass does not have — the
        # container arm below already overrides one of those on purpose (an
        # iterable-consuming builtin cannot tell `str` from `list`), and a
        # parameter typed as something else entirely (`double` from a
        # `+ 1`, a struct from a field match) must not be retyped by a
        # literal. An ANNOTATED parameter is excluded because `_param_ctype`
        # gives `_inferred_param_types` no say over an annotation, so an
        # entry written here reaches the forward declaration and not the
        # definition — see `_annotated_params`' own comment for the
        # "conflicting types" that produces.
        _ann_for = (getattr(gen, '_annotated_params', {}) or {}).get(fname)
        if cur is None and not (_ann_for and _ann_for.get(pname)):
            # ...but ONLY for the two shapes this pass exists to choose
            # between. A CONTAINER member is not one of them: `char *` and
            # `double` are the scalar resolutions and a container is a
            # different KIND, and `bugs4-4-c`'s Pass-1.3d records `void *` for
            # a container literal at a call site precisely so its whitelist
            # REJECTS the pair and drops the slot to the `int64_t` box. This
            # arm runs BEFORE that pass, so without the veto it wrote the
            # container ctype into `_inferred_param_types` and the parameter
            # was declared `MojoList *`:
            #
            #     def f(x): print(x)
            #     f(2.5)
            #     f([1, 2])
            #
            #     prog.py:5:3: error: cannot convert to a pointer type
            #     5 | f(2.5)
            #
            # Note it is the container that is declined here, never a scalar:
            # `_gmi_literal_ctype` answers None for `2.5`, `5`, `None` and an
            # identifier alike, and a declined SCALAR is not evidence against
            # anything — `pct('s')` + `pct(5)` must still resolve to `char *`,
            # which is `test_gimple.py`'s
            # `a_forwarded_string_argument_keeps_its_type`. So the veto is on
            # the member's shape, not on how many members there are.
            if call_type not in ('char *', 'double'):
                continue
            ipt.setdefault(fname, {})[pname] = call_type
            continue
        if not ((cur in containers and call_type == 'char *')
                or (cur == 'char *' and call_type in containers)):
            # The two agree, or the disagreement is not the str/list
            # ambiguity this pass exists to settle. Leave it alone.
            continue
        ipt.setdefault(fname, {})[pname] = call_type


def _free_func_param_ctypes(self, s) -> list:
    """`[self._param_ctype(pn, pt, s) for pn, pt in s.params]` as an
    EXPLICIT loop with a per-element unpack: the list-comprehension form
    with a 2-tuple target miscompiled in the self-hosted backend (the
    `pn`/`pt` slots boxed to int64_t), so `_param_ctype`'s
    `pname in _inferred_param_types[func_key]` lookup missed on the boxed
    key and every unannotated free-function parameter fell back to the
    int64_t default even after usage inference had resolved it."""
    out: list = []
    for _pp in (s.params or []):
        _pn, _pt = _pp
        out.append(self._param_ctype(_pn, _pt, s))
    return out






def _seed_selfhost_module_globals(self):
    """Populate the shared `_global_to_module` / `_global_var_types` /
    `_global_c_decl_types` from `_selfhost_module_scalar_globals` — see that
    helper's docstring."""
    for _n, (_mod, _sem, _cdecl) in _selfhost_module_scalar_globals(_SELFHOST_DIR).items():
        self._global_to_module.setdefault(_n, _mod)
        self._global_var_types.setdefault(_n, _sem)
        self._global_c_decl_types.setdefault(_n, _cdecl)




def _seed_selfhost_struct_dict_field_types(self):
    """Seed `_field_dict_val_types` from `_selfhost_struct_dict_field_val_types`
    so a sibling compiler struct's annotated `dict[str, str]` field keeps its
    value type through a per-module `fire.py build` compile."""
    for _sn, _fields in _selfhost_struct_dict_field_val_types(_SELFHOST_DIR).items():
        _dst = self._field_dict_val_types.setdefault(_sn, {})
        for _fn, _vt in _fields.items():
            _dst.setdefault(_fn, _vt)




def _seed_selfhost_return_elem_types(self):
    """Seed `_return_elem_types` from `_selfhost_homogeneous_tuple_ret_funcs`."""
    for _k, _e in _selfhost_homogeneous_tuple_ret_funcs(self, _SELFHOST_DIR).items():
        if self._return_elem_types.get(_k) is None:
            self._return_elem_types[_k] = _e


def _param_slot_kinds(params) -> dict:
    """`{parameter name: per-slot kind byte}` for the ANNOTATED parameters of
    a function definition.

    This pre-pass runs over every body BEFORE the per-function locals exist,
    so `gen._quick_type(IdentExpr('x'))` for a parameter answers the erased
    `int64_t` for every parameter in the program — which is exactly what
    made the list-literal arm of `_returns_kinds_valued` answer "homogeneous"
    for `return [x, 1, s]` and hand a float's bits to `strlen`. A parameter's
    DECLARED type is not erased: it is the annotation, and it is what the
    slot will hold. Unannotated parameters contribute nothing, so the answer
    stays as weak as it was for them rather than being invented.

    `gimple_ctypes._mojo_type` is the shared annotation-to-C-type answer
    (`_quick_type` itself goes through `_TYPE_MAP`), so the kind byte comes
    from the same table the emitter's own `slot_kind_byte` mapping uses.
    """
    out = {}
    if not params:
        return out
    for _p in params:
        try:
            _nm, _ann = _p[0], _p[1]
        except (TypeError, IndexError):
            continue
        if not isinstance(_ann, str) or not _ann:
            continue
        out[_as_str(_nm)] = gimple_ctypes.TypeLattice.slot_kind_byte(
            gimple_ctypes._mojo_type(_ann))
    return out


def _list_literal_slot_kinds(gen, node, param_kinds=None) -> list:
    """`gen._struct_slot_kinds`' long-form spelling (`'double'` / `'str'` /
    `'bytes'` / `'int'`) of a heterogeneous list LITERAL's per-slot kinds, or
    `[]` for anything that is not one.

    This is the per-index half of `_returns_kinds_valued`'s list arm, and it has
    to be computed from the same inputs or the two disagree about which
    literals are heterogeneous — so it shares `_param_slot_kinds` and
    `TypeLattice.slot_kind_byte`, and the one-byte runtime alphabet
    (`'d'`/`'p'`/`'s'`/`'l'`/`'i'`, `mojo_list_set_kinds`'s) is translated to
    the long form `_struct_slot_kinds` uses. `'l'` (a nested container slot)
    and `'n'` (`None`) fold to `'int'`: a raw word IS the right read for
    both — the pointer, and 0 — and the alternative would be a per-slot
    pointer type this table has never carried.

    Both spellings are translated through ONE `_long` table rather than by
    appending `param_kinds`' value and `slot_kind_byte(...)`'s value
    side-by-side: `_param_slot_kinds` answers in the runtime's one-byte
    alphabet, so an `IdentExpr` element and a literal element of the same type
    have to reach this list in the same spelling or the same `a[1]` reads
    through two different accessors depending on which arm filled its slot.

    `[]` for a `*`-unpack element, matching the boolean arm: no compile-time
    slot count means no per-slot kinds at all."""
    if not isinstance(node, gimple_ctypes.ListExpr):
        return []
    _long = {'d': 'double', 'p': 'str', 's': 'bytes'}
    out = []
    for _el in node.elements:
        if isinstance(_el, gimple_ctypes.UnaryOp) and _el.op == '*':
            return []
        if (isinstance(_el, gimple_ctypes.NoneLiteral) or (
                isinstance(_el, gimple_ctypes.IdentExpr)
                and _el.name == 'None')):
            out.append('int')
            continue
        if isinstance(_el, gimple_ctypes.IdentExpr) and param_kinds:
            _pk = param_kinds.get(_as_str(_el.name))
            if _pk is not None:
                out.append(_long.get(_pk, 'int'))
                continue
        out.append(_long.get(gimple_ctypes.TypeLattice.slot_kind_byte(
            gen._quick_type(_el)), 'int'))
    return out

def _returns_kinds_valued(gen, node, param_kinds=None) -> bool:
    """True when `node` is an expression that produces a value whose
    per-slot element kinds are recorded on the VALUE itself — a
    `struct.unpack` of a format that mixes kinds, a `Struct` handle's
    `unpack`/`iter_unpack` on such a format, or a heterogeneous list
    LITERAL. The kinds then survive a `return` even though the compile-time
    NAME they were recorded against does not, which is the whole reason this
    question needs answering at the callee (see `_infer_return_maybe_kinds`).

    Only literal formats answer, the same bar `_struct_ctor_format` sets:
    a computed format is not statically known, and guessing would be the
wrong-static-answer failure the whole table exists to avoid.

    The list-literal arm was MISSING, and the omission is what
    `CODEGEN_list_element_read_defaults_to_str_across_a_call` is:
    `_lower_list_literal` records the per-slot kinds of a heterogeneous
    literal on the value (`mojo_list_set_kinds`) and marks it in
    `gen._maybe_kinds_vals` — but only while THAT function is being
    lowered. A `return [x, 1, s]` therefore described itself perfectly
    and lost every word of it at the boundary, because this function
    (which decides the cross-function half) did not recognise the one
    producer that is not a `struct.unpack`. So
    `def mixed(x: Float64, s: String): return [x, 1, s]` bound to a local in
    the caller left that local's element type at the unknown-element default
    `str`, and every read of it went through `mojo_list_get_str` — so `a[0]`,
    which holds `2.5`'s IEEE-754 bit pattern `0x4004000000000000`, was handed
    to `strlen` and the program died with SIGSEGV. Marking the callee makes
    the call site register the result in `_maybe_kinds_vals`
    (`emit_calls.py`'s `_lower_named_call`), which is the flag the subscript
    and iteration lowerings already consult for `mojo_list_get_boxed`.

    The heterogeneous-literal case is what makes
    `def mixed(x: Float64, s: String) -> List: return [x, 1, s]` readable
    through a call. Its elements' joined type is `char *` (`TypeLattice.join`
    resolves double-vs-char* to char*), so the caller binds the result's
    element type from `_return_elem_types` and `a[p]` lowers to
    `mojo_list_get_str` — a float slot's IEEE-754 bits handed to `strlen`,
    which SIGSEGVs. The kinds ARE recorded, by the callee's own literal
    lowering; marking the call result makes the read a boxed one and lets the
    runtime answer per slot.

    The "not all the same kind" test is the emitter's own, applied
    statically: one kind byte per element, from `_param_slot_kinds` where the
    element is a bare parameter, else `_quick_type`. A `*`-unpack element has
    no compile-time slot count and so no static per-slot kinds at all —
    answering False for it keeps that case exactly where it was.

    `gen is None` is the predicate's own no-type-context mode, which
    test_gimple.py's struct-format case calls it in (that case is about the
    CallExpr arm below and needs no types). With no context an identifier
    element cannot be typed, so the literal half answers what it can — LITERAL
    elements only — rather than claiming to have seen the whole literal. That
    is also why the `gen is None` test sits where it does: a mode that
    silently guessed `int64_t` for every element would answer "homogeneous"
    for `return [1, 2, 3]` on a wrong premise rather than declining.

    `TupleExpr` is in the isinstance test for the same reason it is in
    `_lower_list_literal`'s: a tuple literal is a list literal that prints
    with parentheses, and its per-slot kinds are recorded the same way."""
    if isinstance(node, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr)):
        _kinds = set()
        _saw_typed = False
        for _el in (node.elements or []):
            if isinstance(_el, gimple_ctypes.UnaryOp) and _el.op == '*':
                return False
            if (isinstance(_el, gimple_ctypes.NoneLiteral) or (
                    isinstance(_el, gimple_ctypes.IdentExpr)
                    and _el.name == 'None')):
                _kinds.add('n')
                _saw_typed = True
                continue
            if gen is None:
                continue
            if isinstance(_el, gimple_ctypes.IdentExpr) and param_kinds:
                _pk = param_kinds.get(_as_str(_el.name))
                if _pk is not None:
                    _kinds.add(_pk)
                    _saw_typed = True
                    continue
            _kinds.add(gimple_ctypes.TypeLattice.slot_kind_byte(
                gen._quick_type(_el)))
            _saw_typed = True
        return _saw_typed and len(_kinds) > 1
    if not isinstance(node, gimple_ctypes.CallExpr):
        return False
    f = node.func
    # A call to a function ALREADY KNOWN to hand back a kinds-carrying value
    # (`fn drop_one() -> List: var kept = mixed(1.5, "aa"); return kept`).
    # This is the transitive half and it is why the caller above runs a second
    # pass: the callee has to be in `_return_maybe_kinds` before the function
    # calling it can be answered, and either may come first in the module.
    _callee = getattr(f, 'name', None)
    if (_callee is not None
            and _callee in getattr(gen, '_return_maybe_kinds', ())
            and getattr(gen, 'func_return_types', {}).get(_callee) == 'MojoList *'):
        return True
    # `struct.unpack(fmt, buf)` / `struct.unpack_from(fmt, buf, off)` /
    # `struct.iter_unpack(fmt, buf)` — fmt is the first argument, read
    # back only when it is a literal (see `_struct_literal_format`).
    if (isinstance(f, gimple_ctypes.MemberExpr)
            and isinstance(f.obj, gimple_ctypes.IdentExpr)
            and f.obj.name == 'struct'
            and f.member in ('unpack', 'unpack_from', 'iter_unpack')
            and node.args):
        return gimple_ctypes._struct_format_is_mixed(
            gimple_ctypes._struct_literal_format(node.args[0]))
    # `H.unpack(buf)` where H is `struct.Struct('mixed-format')`.
    if (isinstance(f, gimple_ctypes.MemberExpr)
            and f.member in ('unpack', 'unpack_from', 'iter_unpack')):
        return gimple_ctypes._struct_format_is_mixed(
            gimple_ctypes._struct_ctor_format(f.obj))
    return False


def _infer_return_maybe_kinds(gen, body, params=None,
                            callee_kinds=None) -> tuple:
    """Does any `return` in this body hand back a kinds-carrying value?

    The cross-function half of the per-slot-kinds mechanism. A
    `struct.unpack` result records its kinds on the VALUE (runtime side,
    `mojo_list_set_kinds`), which is what keeps the whole-result repr right
    through a function boundary — but a read with no compile-time slot index
    (iteration, a computed subscript) has to be lowered as a BOXED read
    (mojo_list_get_boxed), and whether it may be is a compile-time
    decision. Inside one function the marker rides along on the local name
    (`gen._maybe_kinds_vals`); across a `return` it cannot, so it is
    inferred here and read back at the call site, the same
    whole-program-then-lower-the-callee shape Pass 2c already uses for
    `_return_elem_types`.

    One round of intra-body propagation: a local bound from such a call and
    then returned by name counts. Two hops (`a = f(); b = a; return b`) do
    not — recorded rather than approximated, since over-approximating here
    would only cost a boxed read on a value the runtime then reports as
    unboxed, while under-approximating costs a wrong answer, and a missing
`case is a missing case either way.

    Returns `(maybe_kinds, slot_kinds)`:
    `maybe_kinds` is the BOOLEAN half, which reaches the call site as
    `gen._return_maybe_kinds` and becomes a `mojo_list_get_boxed` read for a
    subscript or iteration with no compile-time index;
    `callee_kinds` is the set of function names ALREADY known to hand one
    back, so a value that travels out through TWO returns is found rather than
    missed — see `_valued` below;
    `slot_kinds` is the PER-INDEX half, the long-form kind name of every slot
    of a returned heterogeneous list literal (`'double'` / `'str'` / `'bytes'`
    / `'int'`, the spelling `gen._struct_slot_kinds` already uses). That one
    is what makes a STATICALLY indexed read exact — `a[2]` on
    `[x, 1, s]` has to come back as a `char *`, and the boolean alone can only
    say "ask the runtime", which for a `char *` slot answers with the raw word.
    `[]` when nothing per-index is known.

    `params` is the definition's own parameter list, and it is threaded in for
    the same reason `_infer_return_elem_type` takes `func_def`: the
    heterogeneous-literal test reads each element's type, and a parameter is
    the most ordinary element there is — `return [x, 1, s]` in
    `def mixed(x: Float64, s: String) -> List` is three elements of which two
    are params. This pre-pass runs before the per-function locals exist, so
    `gen._quick_type(IdentExpr('x'))` answers the erased `int64_t` for every
    parameter in the program and all three elements read as one kind.

    It is read TWO ways, deliberately, because a parameter's type is needed by
    two different consumers. `_param_slot_kinds` answers for a bare
    `IdentExpr` element with no `gen` state at all, which is what makes the
    `gen is None` no-type-context mode still able to say "heterogeneous"; and
    `var_types` is overlaid with the same annotations so an element that is an
    ARITHMETIC expression over a parameter (`return [x + 1, s]`) is typed too.
    The overlay is saved and restored exactly as `_infer_return_elem_type`
    does it, because this function is called from inside a fixpoint that owns
    `gen.var_types`."""
    _pk = _param_slot_kinds(params)
    _ck = callee_kinds if callee_kinds is not None else ()
    _saved_vt = gen.var_types if gen is not None else None
    if gen is not None:
        gen.var_types = dict(_as_dict(_saved_vt))
        for _p in (params or []):
            try:
                _pname, _ptype = _p[0], _p[1]
            except (TypeError, IndexError):
                continue
            if isinstance(_ptype, str) and _ptype:
                gen.var_types[_as_str(_pname)] = gimple_ctypes._mojo_type(_ptype)

    def _valued(node) -> bool:
        """Does this EXPRESSION produce a value whose per-slot kinds were
        recorded on it?

        `_returns_kinds_valued` answers from the expression's own shape. This
        adds the one hop it cannot see: a call to a function that ITSELF
        hands back such a value. `mixed` records the kinds on the literal it
        returns, and `drop_one`'s `kept = mixed(...)` / `return kept` carries
        that value out through a SECOND frame — which is the shape
        test_gimple_runner.py's `gimple_kinds_survive_a_sibling_list_being_
        freed` is, and with the hop missing `drop_one` was not marked, so
        `b = drop_one()` was not registered in `_maybe_kinds_vals` and
        `print(b[i])` reached for `mojo_list_get_str` on a list whose slot 0
        holds `9.5`'s IEEE-754 bits: SIGSEGV after the first line. The whole
        list's repr was right (the kinds ARE on the value), so the row looked
        like a repr bug and was not one.

        The callee's OWN name is what is matched, and both spellings the
        method-mangling scheme produces are spelled here: a bare free
        function and the `Struct_method` form `_mk` registers methods under.
        """
        if _returns_kinds_valued(gen, node, _pk):
            return True
        if not isinstance(node, gimple_ctypes.CallExpr):
            return False
        _f = node.func
        if isinstance(_f, gimple_ctypes.IdentExpr):
            return _as_str(_f.name) in _ck
        if (isinstance(_f, gimple_ctypes.MemberExpr)
                and isinstance(_f.obj, gimple_ctypes.IdentExpr)):
            return f'{_as_str(_f.obj.name)}_{_as_str(_f.member)}' in _ck
        return False
    bound: set = set()
    kinds_out: list = []
    try:
        for _round in range(2):
            found = False
            for nd in _walk_ast(body):
                if (isinstance(nd, gimple_ctypes.AssignStmt)
                        and isinstance(nd.target, gimple_ctypes.IdentExpr)):
                    if _valued(nd.value) or (
                            isinstance(nd.value, gimple_ctypes.IdentExpr)
                            and nd.value.name in bound):
                        bound.add(nd.target.name)
                elif (isinstance(nd, gimple_ctypes.VarDecl) and nd.name
                        and _valued(getattr(nd, 'value', None))):
                    bound.add(nd.name)
                elif isinstance(nd, gimple_ctypes.ReturnStmt):
                    v = getattr(nd, 'value', None)
                    if _returns_kinds_valued(gen, v, _pk):
                        found = True
                        kinds_out = (_list_literal_slot_kinds(gen, v, _pk)
                                     or kinds_out)
                    elif _valued(v):
                        found = True
                    elif (isinstance(v, gimple_ctypes.IdentExpr)
                          and v.name in bound):
                        found = True
            if found:
                return True, kinds_out
        return False, kinds_out
    finally:
        # The `var_types` overlay above is this function's, and the fixpoint
        # that calls it owns the real one; leaving the overlay behind would
        # make every later round answer from annotations this body invented.
        if gen is not None:
            gen.var_types = _saved_vt


# The container kinds a `return` slot can hold, as one name. A function whose
# `return`s can produce MORE THAN ONE of these has no single container type,
# so its return slot is the box — see `_infer_multi_kind_return` beside it,
# and `DESIGN.html` R2 for why a cast between two of them is a reinterpreting
# of one struct's memory rather than a conversion. A tuple, not a set,
# because this file is in the subset the self-hosted backend lowers and that
# subset has no set literals (see `_ast_child_nodes`' own note).
_CONTAINER_RETURN_KINDS = ('MojoDict *', 'MojoList *', 'MojoSet *')


def _infer_multi_kind_return(gen, body, params=None,
                             callee_set=None,
                             callee_kinds=None,
                             sibling_lifted=None) -> tuple:
    """The set of container KINDS this body can hand back through a `return`.

    The whole-program half of the multi-kind box, and the same question
    `_infer_return_maybe_kinds` asks about per-slot kinds: whether a value
    travelling out through a `return` still needs the runtime registries to
    be read. Where that one is about a value that CARRIES kinds, this is
    about the container KIND itself — `MojoList *` / `MojoDict *` /
    `MojoSet *` are three distinct runtime structs with three distinct slot
    layouts (DESIGN.html R2), so a caller's "`MojoList *`" is a guess, and a
    wrong guess reads another container's memory rather than converting it.

    The answer is the SET rather than a boolean because a function with a
    single container return is NOT this shape, and the caller needs to be
    able to tell those two apart from the other side: a callee that returns
    one kind is passed that kind to its own callers (`callee_kinds` below),
    which is how a function whose two branches return calls to DIFFERENT
    single-kind functions is itself found.

    Four ways the disagreement arrives, each needing its own test:

      * two `return`s of container literals of different kinds
        (`if k: return [1, 2]` / `return {"a": 1}`);
      * two `return`s of CALLS to functions of different kinds
        (`if k: return as_list(x)` / `return as_dict(x)`) — the literal test
        cannot see it and the callee test below cannot either, because
        neither callee is multi-kind; only comparing the two answers can;
      * one `return` of a LOCAL bound to two kinds (`box = [1, 2]` in one
        arm, `box = {"a": 1}` in another, `return box`) — the disagreement
        is in the local's BINDINGS and never appears in the returns at all,
        which is why the local-shaped case needs the body walk below;
      * one `return` FORWARDING another function's box
        (`def outer(k): return inner(k)`) — a callee's answer, one hop
        away, and what `callee_set` carries.

    `callee_set` is the set of names already known to hand back MORE THAN ONE
    kind, exactly the role it plays in `_infer_return_maybe_kinds`, and for
    the same reason: a value that travels out through two frames must be
    found rather than missed. `callee_kinds` is the weaker fact — each known
    callee's own single kind, if it has one — which is what lets shape 2 be
    answered without a fixpoint, since a callee's own kind is known from its
    own body in the same round.

    `sibling_lifted` maps a BARE nested-`def` name to the `Outer_inner`
    spelling the rest of this mechanism uses, for the call shapes where the
    bare name is what the AST carries and the lifted name is what the answer
    is filed under: a closure calling a SIBLING closure, and an enclosing
    free function calling its own closure. Both are the same spelling
    mismatch `_infer_return_maybe_kinds`' `_valued` handles by matching both
    forms; it is a parameter rather than a lookup inside this function
    because the map is a property of the CLOSURE SET and threading it
    through the fixpoint's callee arguments would have made the memo key
    depend on the enclosing name.

    Runs BEFORE any body is lowered, which is the whole point. The lowering
    handler (`emit_stmts._gen_stmt_ReturnStmt`) records the same verdict into
    `gen._multi_kind_return_funcs`, and that recording is only visible to a
    caller emitted LATER: a caller declared BEFORE its callee saw an empty
    set, applied the `int64_t`-returning branch's default of "`_actual_types`
    says `MojoList *`", and printed `[0]` where CPython prints `{'a': 1}` —
    silent, exit 0, and order-dependent, which is the worst property a
    typing rule can have. The lowering recording is kept, because it is the
    only place the local-shaped verdict can be read against the ACTUAL
    lowered value kinds; this pre-pass is what makes it order-independent.

    `params` is threaded for the same reason as in `_infer_return_maybe_kinds`
    — a `return` of a parameter or of an expression over one is the most
    ordinary shape there is, and without them every parameter reads as the
    erased `int64_t`.
    """
    _ck = callee_set if callee_set is not None else set()
    _cg = callee_kinds if callee_kinds is not None else {}
    _sl = sibling_lifted if sibling_lifted is not None else {}
    _saved_vt = gen.var_types if gen is not None else None
    _saved_cur = getattr(gen, 'current_func_name', '')
    _saved_body = getattr(gen, '_cur_func_body', None)
    kinds: set = set()
    if gen is not None:
        gen.var_types = dict(_as_dict(_saved_vt))
        for _p in (params or []):
            try:
                _pname, _ptype = _p[0], _p[1]
            except (TypeError, IndexError):
                continue
            if isinstance(_ptype, str) and _ptype:
                gen.var_types[_as_str(_pname)] = gimple_ctypes._mojo_type(_ptype)
    _saved_cur = getattr(gen, 'current_func_name', '')
    _saved_body = getattr(gen, '_cur_func_body', None)
    kinds: set = set()
    try:
        # The local-shaped case: a name this function binds to more than one
        # container kind has no container type of its own, so returning it
        # hands back the box whatever its `ReturnStmt` says. Asked of
        # `gen._cur_func_body` for the same reason `mixed_container_locals`
        # asks it there — it is the body of the function being emitted, and
        # it is what makes the answer about THIS function rather than
        # whichever one happened to be lowered last.
        gen._cur_func_body = body
        gen._mixed_container_locals = None
        # Imported HERE rather than at module scope: `gimple_codegen.py`
        # imports this module before it imports `emit_infra`, so a top-level
        # `import ... emit_infra` in this file is a circular import that
        # raises `cannot import name '_FC_SEP' from partially initialized
        # module 'mojo.middle.infra_infer'` on the `import
        # mojo.backend_gimple.module_gen` path. Same reason
        # `emit_infra`'s own sibling imports are function-local.
        import mojo.backend_gimple.emit_infra as _ein
        _mixed = _ein.mixed_container_locals(gen)
        gen._cur_func_body = _saved_body
        for nd in _walk_ast(body):
            if not isinstance(nd, gimple_ctypes.ReturnStmt):
                continue
            _v = getattr(nd, 'value', None)
            if _v is None:
                continue
            if isinstance(_v, gimple_ctypes.CallExpr):
                # The forwarding case first: it is the cheapest test and the
                # one that makes the fixpoint move, since a chain of
                # forwarders is only settled once its last real producer is
                # known. The bare name is checked against `_sl` first
                # because that is the spelling the AST has and `_ck` alone
                # would miss a closure.
                _f = _v.func
                if isinstance(_f, gimple_ctypes.IdentExpr):
                    _fn = _as_str(_f.name)
                    if _fn in _ck or _sl.get(_fn) in _ck:
                        # Kind genuinely unknown: every container kind is a
                        # possible answer, which is what stops a caller's
                        # single-kind guess from being trusted.
                        return tuple(_CONTAINER_RETURN_KINDS)
                    _k = _cg.get(_fn)
                    if _k:
                        kinds.add(_k)
                    continue
                if (isinstance(_f, gimple_ctypes.MemberExpr)
                        and isinstance(_f.obj, gimple_ctypes.IdentExpr)):
                    _mn = f'{_as_str(_f.obj.name)}_{_as_str(_f.member)}'
                    if _mn in _ck:
                        return tuple(_CONTAINER_RETURN_KINDS)
                    _k = _cg.get(_mn)
                    if _k:
                        kinds.add(_k)
                continue
            if isinstance(_v, gimple_ctypes.IdentExpr):
                _vn = _as_str(_v.name)
                if _vn in _mixed:
                    return tuple(_CONTAINER_RETURN_KINDS)
                if _vn in _ck:
                    return tuple(_CONTAINER_RETURN_KINDS)
                # A local's container kind is NOT resolvable from this body
                # walk — the pre-pass has none of the local-type tables the
                # lowering path builds as it goes — so a returned local
                # contributes NOTHING unless it is known mixed, rather than
                # contributing a guess. Guessing here would file a single-kind
                # answer for `return names` and a caller would trust it, which
                # is the same wrong answer this whole mechanism exists to
                # prevent; contributing nothing only costs this function the
                # single-kind credit that lets ITS caller compare kinds.
                #
                # The lowering-time recording (`emit_stmts.
                # _gen_stmt_ReturnStmt`) reads the real lowered type and is
                # kept for exactly this, so the two together lose nothing and
                # the pre-pass is only responsible for what it can answer
                # without a lowering pass.
                continue
            # A container literal handed straight back. `_quick_type` is the
            # same estimator the lowering path uses for the value, so the two
            # cannot disagree about what this arm holds.
            _qt = gen._quick_type(_v) if gen is not None else None
            if _qt in _CONTAINER_RETURN_KINDS:
                kinds.add(_qt)
        return tuple(sorted(kinds))
    finally:
        if gen is not None:
            gen.var_types = _saved_vt
            gen.current_func_name = _saved_cur
            gen._cur_func_body = _saved_body
            gen._mixed_container_locals = None


def _homogeneous_tuple_ann_elem(self, _ret_ann):
    """`tuple[T, T, ...]` / `Tuple[...]` return annotation whose slots are all
    the SAME resolved C type → that element ctype (else None). Used to seed
    `_return_elem_types` when body inference misses a tuple return (a slot
    that is a reassigned local or a ternary), so the caller unpacks each slot
    with the right `mojo_list_get_<T>` accessor instead of the int64_t default.
    Only a non-`int64_t` element is worth recording (int64_t is the fallback
    every unpack already assumes)."""
    if not isinstance(_ret_ann, str):
        return None
    _s = _ret_ann.strip()
    if not ((_s.startswith('tuple[') or _s.startswith('Tuple[')) and _s.endswith(']')):
        return None
    _inner = _s[_s.index('[') + 1:-1]
    _parts = [p.strip() for p in gimple_ctypes._split_top_level_commas(_inner) if p.strip()]
    if len(_parts) < 2:
        return None
    # No set()/next() — this file is compiled by the self-host backend, which
    # lowers neither. Resolve slot 0, then require every other slot to match.
    _ct0 = None
    for _p in _parts:
        if _p == '...':
            return None
        _ct = self._resolve_type(_p)
        if _ct0 is None:
            _ct0 = _ct
        elif _ct != _ct0:
            return None
    return _ct0 if _ct0 and _ct0 != 'int64_t' else None




def _render_struct_typedef_body(struct_name, fields):
    """Render just the `typedef struct NAME { ... } NAME;` body lines for
    one struct, given its resolved {field_name: field_ctype} map (the same
    per-field rendering gen_module_impl's own emit_struct_defs pass uses,
    hoisted out so a SECOND, independent caller — the compiled-generator
    C++ preamble's "struct layout(s) needed" block, which must synthesize
    a typedef on demand for a struct whose OWN home module never ran with
    emit_struct_defs=True (see that block's `_struct_typedef_texts` miss
    case) — can produce byte-identical text without duplicating the
    field-rendering rules (array-typed fields, self-referential `NAME *`
    fields, C-keyword-colliding field names) and silently drifting out of
    sync with them over time. Returns a list of text lines, EXCLUDING the
    guard #define gen_module_impl's own caller appends separately."""
    lines = [f"typedef struct {struct_name} {{", f"  int64_t __mojo_type_id;"]
    if fields:
        # REVERTED an attempted `for field_name in fields:` + indexed-
        # lookup rewrite here: `fields.items()` isn't just iteration
        # syntax, it's the self-hosted backend's ONLY signal that `fields`
        # (an unannotated parameter) is a dict rather than a list — bare
        # `for x in fields:` is genuinely ambiguous to it, and dropping
        # `.items()` made an ORDINARY struct's fields dict (e.g.
        # "ARM64JIT", never involved in the GimpleGen bug this was meant
        # to fix) get inferred as a list, so `fields[field_name]` compiled
        # as `mojo_list_get_int` and segfaulted on the very next --dump-
        # full fire.py run. The real fix for the GimpleGen-only corrupted-
        # key symptom lives at the SOURCE of those keys instead (the
        # `dict(x)` copy replaced by an indexed loop + _as_str a few
        # hundred lines below, in gen_module_impl) — this loop shape was
        # never actually the bug.
        for field_name, field_type in fields.items():
            field_name = _as_str(field_name)
            ft = '' + _as_str(field_type)
            if ft == f"{struct_name} *":
                ft = f"struct {struct_name} *"
            safe_fn = _safe_field(field_name)
            _arr_dm = re.match(r'^(.+)\[(\d+)\]$', ft)
            if _arr_dm:
                lines.append(f"  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];")
            else:
                lines.append(f"  {ft} {safe_fn};")
    else:
        lines.append(f"  int _dummy;")
    lines.append(f"}} {struct_name};")
    return lines






def _reflect_struct_names(self) -> list:
    """The structs `_emit_reflection_dispatch` emits helpers for, in content
    order, as an explicitly `_as_str`-typed list.

    Cached on the gen, and computed ONCE for the whole emission, because two
    passes now need the identical list: `_emit_reflection_fwd_decls` (which
    runs BEFORE the imported modules' code is spliced into the preamble,
    because that code CALLS these helpers) and `_emit_reflection_dispatch`
    (which emits their definitions). A forward declaration for a struct the
    definition pass skipped is a `static` function declared and never defined,
    and C's error for that is "used but never defined" — a different hard
    failure from today's "implicit declaration", so a disagreement between
    the two passes would trade one broken program for another. One list, one
    cache, no possibility of drift.

    NOT `sorted(setA & setB & setC)`. `self._emitted_structs` /
    `self._struct_allocs_needed` carry int64_t-tagged / boxed slots on
    the self-hosted backend, so the set intersection and the resulting
    `sorted()` loop var typed to int64_t — every `f"..._mojo_repr_{sn}"`
    / `f"..._mojo_getattr_{sn}"` f-string then concatenated a
    boxed pointer, crashing in `mojo_str_cat` → `strlen()` on garbage
    (crash-report bt: `_platform_strlen` ← `mojo_str_cat` ←
    `gen_module_impl`, recursing through `_compile_imported_module` on
    a shimless `--dump-full`).

    Iterate `struct_field_types`' keys in CONTENT order and filter in
    place — the result list is already sorted, no trailing `sorted()`.

    `sorted(self.struct_field_types)` (the dict itself, not `.keys()`)
    lowers to `mojo_dict_sorted_keys` → `mojo_list_sorted_str`, a genuine
    string-content sort — the container-type dispatch in `_lower_sorted`
    keys on `MojoDict *`, which `.keys()` would have already unwrapped. An
    earlier revision built `_rs_names` as a `set()` and did
    `sorted(_rs_names)` to reach `mojo_set_sorted` instead — but this
    compiler stores these boxed `char *` names through the set's INT view,
    so every slot carries `tag == 0` and `mojo_set_sorted` sorted them as
    raw int64_t ADDRESSES and handed back pointer-ints; the reflection
    emit loop's `self.struct_field_types.get(sn)` then missed on every one
    and silently skipped ALL the `_mojo_repr_*`/`_mojo_getattr_*` helpers
    (regressed struct_def/class_methods in test_ab_native).

    Ordering here is load-bearing beyond determinism: it drives the struct
    walk order, hence the `_str_pool` intern order, hence every `_slit_N` in
    the output."""
    _cached = getattr(self, '_reflect_structs_cache', None)
    if _cached is not None:
        return _cached
    _es_str = set()
    for _esx in self._emitted_structs:
        _es_str.add(_as_str(_esx))
    _san_str = set()
    for _sanx in self._struct_allocs_needed:
        if _ptr_slot_in_range(_sanx):
            _san_str.add(_as_str(_sanx))
    _rs_names = []
    for _rsk in sorted(self.struct_field_types):
        _rsk = _as_str(_rsk)
        if _rsk in _es_str and _rsk in _san_str:
            _rs_names.append(_rsk)
    # ...plus every struct a CONTAINER store asked an element-repr shim for
    # (`_elem_repr_needed`, recorded by `struct_elem_repr_shim` at the store,
    # where the shim's NAME went into the generated C). The filter above is
    # NARROWER than "the struct has fields" on purpose -- an imported struct a
    # module only stores somewhere gets no `_mojo_repr_<sn>` here -- so a store
    # that named a shim the filter would have skipped left the module with an
    # undefined-function reference, and the self-host closure failed to LINK
    # with `'_mojo_elem_repr_TrieNode' undeclared` (ast_rewriter.py). The
    # request and the emission therefore cannot be decided independently: this
    # is the emitter answering what it was asked for.
    for _ern in sorted(self._elem_repr_needed):
        _ern = _as_str(_ern)
        if _ern in self.struct_field_types and _ern not in _rs_names:
            _rs_names.append(_ern)

    self._reflect_structs_cache = _rs_names
    return _rs_names


def _reflect_emitted_names(self) -> list:
    """`_reflect_struct_names` minus the field-less structs — the ones
    `_emit_reflection_dispatch` actually emits a helper for, and therefore
    the only ones that may be forward-declared. Every dispatch table in that
    function is driven from this list rather than re-deriving the same
    condition, so a table can never reference a helper that was skipped.

    It used to re-test `if self.struct_field_types.get(sn)` inside each
    join's generator expression; self-hosted, those genexpr `if` clauses
    did not filter, so the tables listed EVERY reflect struct while this
    loop correctly skipped the field-less ones — emitting
    `return _mojo_getattr_Layout((Layout *)obj, attr);` against a helper
    that was never generated ("implicit declaration of function
    '_mojo_getattr_Layout'", the head of fire_compiler.py's error list).

    Cached for `_reflect_struct_names`'s reason: the forward-declaration pass
    and the definition pass must agree exactly."""
    _cached = getattr(self, '_reflect_emitted_cache', None)
    if _cached is not None:
        return _cached
    _out = []
    for _rsn in _reflect_struct_names(self):
        if len(self.struct_field_types.get(_rsn, {})) > 0:
            _out.append(_rsn)
    self._reflect_emitted_cache = _out
    return _out


def _emit_reflection_fwd_decls(self, parts):
    """Every DECLARATION `_emit_reflection_dispatch`'s definitions need,
    emitted ahead of the imported modules' code.

    C has no two-pass declarations, so in one translation unit a call must be
    preceded by its declaration. `gen_module_impl` splices every inline-
    compiled module's whole output — function bodies included — into the
    preamble, and that code CALLS these helpers by name
    (`mojo_list_set_elem_repr(t, _mojo_elem_repr_IntLiteral)` from a list
    literal in an imported module), while the block emitting both the
    forward declarations and the definitions ran after the splice. Measured
    on the self-host closure: 59 `'_mojo_elem_repr_<Struct>' undeclared`
    errors, every one of them an implicit declaration gcc resolves to
    `int` — so the call compiled, the pointer it returned was truncated to
    32 bits, and every such container's element repr in the SELF-HOSTED
    compiler was garbage.

    Kept as declarations-only and kept in ONE place — this function — rather
    than duplicated ahead of the splice, so the definition pass emits
    definitions and nothing else and the two halves cannot drift.
    """
    parts.append("static int64_t _mojo_dispatch_getattr (void *, char *);")
    parts.append("static void _mojo_dispatch_setattr (void *, char *, int64_t);")
    parts.append("static char * _mojo_dispatch_repr (void *);")
    parts.append("static char * _mojo_repr_list (MojoList *);")
    parts.append("static char * _mojo_repr_dict (MojoDict *);")
    parts.append("static char * _mojo_generic_elem_repr (int64_t);")
    parts.append("static char * _mojo_repr_pair (MojoList *);")
    _emitted = _reflect_emitted_names(self)
    repr_fwd_decls = [f"static char * _mojo_repr_{sn} ({sn} *obj);"
                      for sn in _emitted]
    if repr_fwd_decls:
        parts.append("/* Forward decls for generic repr() (mutual struct references) */")
        parts.append("\n".join(repr_fwd_decls))
        parts.append('')
    elem_repr_fwd_decls = [f"static char * _mojo_elem_repr_{sn} (int64_t v);"
                           for sn in _emitted]
    # No `void *` alias of each shim is declared here: inside a `__GIMPLE`-
    # tagged function gcc's raw GIMPLE parser cannot name a function
    # designator at all (a bare assignment is a "non-trivial conversion in
    # 'function_decl'", a C-style cast is "invalid operand in unary
    # operation" — see `_inc_val`'s docstring — and naming it as a call
    # argument is "invalid argument to gimple call"). The conversion is made ONCE
    # per target by `emit_infra.elem_repr_operand`, which requests a
    # file-scope `static void *_funcptr_<shim> = (void *)<shim>;` through
    # `_funcptr_builtins_needed` -- the ONE mechanism every function-pointer
    # target in this backend already goes through, rather than a second alias
    # scheme that only the element-repr shims used.
    # The `__repr__` each shim calls, when the struct has one. A declaration
    # only, so it is safe here for the same reason the rest of this block is;
    # whether a given struct HAS a `char *`-returning `__repr__` is
    # `_struct_method_csym` + `func_return_types`, both of which are already
    # complete at the splice point (every function body in the closure, root
    # and imported, was emitted above it). Appended BEFORE the join below —
    # a declaration added to the list after it has been emitted is a
    # declaration that is not there, which is how this shim's call came out
    # an implicit declaration while the declaration half looked correct.
    for _sn in _emitted:
        _erep = self._struct_method_csym(_sn, '__repr__', '')
        if self.func_return_types.get(_erep) == 'char *':
            elem_repr_fwd_decls.append(f'extern char *{_erep} ({_sn} *);')
    if elem_repr_fwd_decls:
        parts.append("/* Forward decls for the per-struct ELEMENT REPR shims "
                     "(a container of structs) */")
        parts.append("\n".join(elem_repr_fwd_decls))
        parts.append('')
    return elem_repr_fwd_decls


def _emit_reflection_dispatch(self, parts):
    """Emit the generic reflection dispatch (getattr/setattr/repr/
    dataclasses.fields/asdict). Extracted from gen_module_impl so its
    `sn` struct-name loop variable lives in a fresh function scope: in
    gen_module_impl's ~6000-line body `sn` was cross-unified to int64_t
    by unrelated integer uses on the self-hosted backend, so every
    `f"..._mojo_repr_{sn}"` here concatenated a boxed pointer and
    crashed in mojo_str_cat/strlen on the shimless --dump-full path.

    DECLARATIONS live in `_emit_reflection_fwd_decls`, which
    `gen_module_impl` calls BEFORE the imported modules' code is spliced into
    the preamble — this function emits definitions only."""
    reflect_structs = _reflect_struct_names(self)
    refl_parts = []
    reflect_emitted = _reflect_emitted_names(self)
    # Every struct that gets an element-repr shim below. A SET rather than the
    # list, because the field-dump arm above asks "is there a shim for this
    # field's type?" once per field of every reflected struct, and a `sn not in
    # list` test is a linear scan of a list that can hold every struct in the
    # closure.
    elem_repr_names = set()
    for sn in reflect_structs:
        fields = self.struct_field_types.get(sn, {})
        if len(fields) == 0:
            continue
        get_lines = []
        set_lines = []
        name_lits = []
        asdict_lines = []
        for fname, ftype in fields.items():
            if fname == '__mojo_type_id':
                continue
            safe_f = _safe_field(fname)
            if re.match(r'^.+\[\d+\]$', ftype):
                name_lits.append(f'"{fname}"')
                continue
            if ftype.endswith(' *'):
                get_lines.append(
                    f'  if (strcmp(attr, "{fname}") == 0) return (int64_t)(intptr_t)obj->{safe_f};')
                set_lines.append(
                    f'  if (strcmp(attr, "{fname}") == 0) {{ obj->{safe_f} = ({ftype})(intptr_t)val; return; }}')
                asdict_lines.append(
                    f'  mojo_dict_set_int(_r, "{fname}", (int64_t)(intptr_t)obj->{safe_f});')
            else:
                get_lines.append(
                    f'  if (strcmp(attr, "{fname}") == 0) return (int64_t)obj->{safe_f};')
                set_lines.append(
                    f'  if (strcmp(attr, "{fname}") == 0) {{ obj->{safe_f} = ({ftype})val; return; }}')
                asdict_lines.append(
                    f'  mojo_dict_set_int(_r, "{fname}", (int64_t)obj->{safe_f});')
            name_lits.append(f'"{fname}"')
        # Inlined `_fieldnames_append_lines` (was a separate function
        # taking `name_lits: list`, called once, at the single call site
        # below) — self-hosted codegen has no mechanism that carries a
        # list's ELEMENT type across a plain function-call parameter
        # boundary (confirmed repeatedly this session: `.append()`'s own
        # elem-type tracking only reaches consumers in the SAME function
        # scope the list was built in). Across that boundary, `nl` in
        # the old `for nl in name_lits: out += f'...{nl});\n'` defaulted
        # to `int64_t`, and the f-string printed the raw pointer decimal
        # instead of the quoted field-name string literal (`mojo_list_
        # append_str(_r, 46390516016);` instead of `mojo_list_append_
        # str(_r, "x");` — a real, reproducible `make bootstrap`
        # stage1-vs-stage2 divergence on any struct with real fields).
        fieldnames_lines = ''
        for nl in name_lits:
            fieldnames_lines += f'  mojo_list_append_str(_r, {nl});\n'
        asdict_part = (
            f"static MojoDict * _mojo_asdict_{sn} ({sn} *obj) {{\n"
            f"  MojoDict *_r = mojo_dict_new();\n"
            + "".join(asdict_lines) +
            f"\n  return _r;\n}}\n"
        ) if self._asdict_dispatch_needed else ""
        refl_parts.append(
            f"static int64_t _mojo_getattr_{sn} ({sn} *obj, char *attr) {{\n"
            + "\n".join(get_lines) +
            f"\n  return mojo_obj_getattr((void *)obj, attr);\n}}\n"
            f"static void _mojo_setattr_{sn} ({sn} *obj, char *attr, int64_t val) {{\n"
            + "\n".join(set_lines) +
            f"\n  mojo_setattr((void *)obj, attr, val);\n}}\n"
            f"static MojoList * _mojo_fieldnames_{sn} (void) {{\n"
            f"  MojoList *_r = mojo_list_new();\n"
            + fieldnames_lines +
            f"  return _r;\n}}\n"
            + asdict_part
        )
    # Same list as the getattr/setattr helpers above: this loop had its own
    # copy of the "skip field-less structs" condition, and
    # `_emit_reflection_fwd_decls` had a fourth — which self-hosted does not
    # filter. One list, one decision: `reflect_emitted` above.
    for sn in reflect_emitted:
        fields = self.struct_field_types.get(sn, {})
        boxed = self.struct_boxed_fields.get(sn, set())
        bool_fields = self.struct_bool_fields.get(sn, set())
        nullable_containers = self.struct_nullable_container_fields.get(sn, set())
        part_exprs = []
        # `owned` is the answer to ONE question per field: is the string this
        # field's expression produces a heap buffer the dump owns? It cannot be
        # derived from the emitted text afterwards, because the shapes differ in
        # ownership (`mojo_repr_int` strdups; `"True"` is a literal; a NULL list
        # renders as a literal `[]` while a non-NULL one renders as a cat chain),
        # and a wrong `free()` here is a crash rather than a leak. So it is
        # decided where the expression is BUILT, below, next to the shape it
        # describes, and `None` (undecided) is never a legal answer: every branch
        # sets it. `owned` is `True`, `False`, or `('if', cond)` for "owned only
        # when `cond` holds", which is what a NON-NULLABLE container field needs
        # (its helper returns a literal for a null pointer, and the dump must not
        # free that).
        for fname, ftype in fields.items():
            if fname == '__mojo_type_id':
                continue
            safe_f = _safe_field(fname)
            fref = f'obj->{safe_f}'
            # IntLiteral.value used to be repr'd from `raw` via
            # `mojo_int_literal_decimal` so it printed the exact
            # arbitrary-precision decimal the reference's bignum `.value`
            # showed. `_parse_int_literal` now SIGNED-WRAPS `.value` on BOTH
            # sides (`0xFFFFFFFFFFFFFFFF` -> -1), so the reference prints the
            # wrapped int and the raw-decimal path made them disagree
            # (3 AST-DIFFs: value=-1 vs value=18446744073709551615). Fall
            # through to the ordinary int repr.
            if fname in bool_fields:
                val_expr = f'({fref} ? "True" : "False")'
                owned = False
            elif fname in boxed and ftype in (
                    'int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                val_expr = f'_mojo_generic_elem_repr((int64_t){fref})'
                owned = True
            elif ftype == 'char *':
                val_expr = f'({fref} ? mojo_repr_str({fref}) : _mojo_repr_none())'
                owned = True
            elif ftype == '_Bool':
                val_expr = f'({fref} ? "True" : "False")'
                owned = False
            elif ftype in ('double', 'float'):
                val_expr = f'mojo_repr_float((double){fref})'
                owned = True
            elif ftype == 'MojoList *':
                if self._field_elem_types.get(sn, {}).get(fname) == 'double':
                    list_repr = f'mojo_repr_list_doubles({fref})'
                else:
                    list_repr = f'_mojo_repr_list({fref})'
                if fname in nullable_containers:
                    val_expr = f'({fref} ? {list_repr} : _mojo_repr_none())'
                    owned = True
                else:
                    val_expr = list_repr
                    # A null list renders as a LITERAL `"[]"`/`"()"` in every
                    # `mojo_repr_list_*` helper, so the dump owns this field's
                    # string only when the pointer is there to make it.
                    owned = ('if', fref)
            elif ftype == 'MojoDict *':
                if fname in nullable_containers:
                    val_expr = f'({fref} ? _mojo_repr_dict({fref}) : _mojo_repr_none())'
                    owned = True
                else:
                    val_expr = f'_mojo_repr_dict({fref})'
                    owned = ('if', fref)
            elif ftype in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                           'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                val_expr = f'mojo_repr_int((int64_t){fref})'
                owned = True
            elif ftype.endswith(' *'):
                # A field whose declared type is a struct this compile
                # reflected is rendered through that struct's ELEMENT REPR
                # shim, not through the tag-based dispatch: the field's type is
                # written down right here, so there is nothing to discover at
                # runtime, and `_mojo_dispatch_repr` cannot use it anyway for a
                # struct-allocated value (no runtime type tag -- the same gap
                # that made `[p]` print a pointer decimal). A field of a type
                # with no shim keeps the dispatch, which is what reaches a
                # non-reflected struct's own dumper.
                _fsn = ftype[:-2].strip()
                if _fsn and f'_mojo_elem_repr_{_fsn}' in elem_repr_names:
                    val_expr = (f'({fref} ? _mojo_elem_repr_{_fsn}'
                                f'((int64_t)(intptr_t){fref}) : _mojo_repr_none())')
                    owned = True
                else:
                    # `strdup` around the dispatch, and this is the same remedy
                    # `_mojo_repr_dict` applies to its two non-owned answers (and
                    # `_key_slot_str` on the dict-key path): `_mojo_dispatch_repr`
                    # ends in `mojo_repr_obj`, which hands back a shared static
                    # buffer, so its result is not uniformly ours to free.
                    # Copying it here gives the FIELD dump one ownership answer
                    # for every branch without inventing a second ownership
                    # story for the function itself, which its other caller (the
                    # `repr()` site) also has no release point for.
                    val_expr = (f'({fref} ? strdup(_mojo_dispatch_repr((void *){fref}))'
                                f' : _mojo_repr_none())')
                    owned = True
            else:
                val_expr = f'mojo_repr_int((int64_t){fref})'
                owned = True
            part_exprs.append((f'"{fname}="', val_expr, owned))
        # The body is STATEMENTS, not one nested `return`, whenever at least one
        # field's string is the dump's to release: GIMPLE has no comma operator,
        # so a per-field `free()` cannot live inside the expression that cats it,
        # and the value has to be materialized in a temp first. That is the shape
        # `_mojo_repr_dict` and `_mojo_repr_list` already use for exactly this
        # reason. A struct with no owned field keeps the old single-expression
        # body, so nothing that cannot leak here is churned.
        _any_owned = any(_o is not False for _n, _v, _o in part_exprs)
        if not _any_owned:
            cat_chain = f'strdup("{sn}(")'
            for i, pe in enumerate(part_exprs):
                sep = ', ' if i > 0 else ''
                if sep:
                    cat_chain = f'mojo_str_cat_free({cat_chain}, ", ")'
                name_lit, val_e, _own = pe
                cat_chain = f'mojo_str_cat_free({cat_chain}, {name_lit})'
                cat_chain = f'mojo_str_cat_free({cat_chain}, {val_e})'
            cat_chain = f'mojo_str_cat_free({cat_chain}, ")")'
            repr_body = f"  if (!obj) return strdup(\"None\");\n  return {cat_chain};\n"
        else:
            body_lines = []
            body_lines.append(f'  if (!obj) return strdup("None");')
            body_lines.append(f'  char *_buf = strdup("{sn}(");')
            body_lines.append('  char *_v;')
            for i, (name_lit, val_e, own) in enumerate(part_exprs):
                if i > 0:
                    body_lines.append(f'  _buf = mojo_str_cat_free(_buf, ", ");')
                body_lines.append(f'  _buf = mojo_str_cat_free(_buf, {name_lit});')
                body_lines.append(f'  _v = {val_e};')
                body_lines.append('  _buf = mojo_str_cat_free(_buf, _v);')
                if own is True:
                    body_lines.append('  free(_v);')
                elif isinstance(own, tuple) and own and own[0] == 'if':
                    body_lines.append(f'  if ({own[1]}) free(_v);')
                elif own is False:
                    # A LITERAL, and the only shape that is not ours to free.
                    # Its own answer, at the site that knows it.
                    body_lines.append('  /* a string literal: not ours to free */')
            body_lines.append('  return mojo_str_cat_free(_buf, ")");')
            repr_body = "\n".join(body_lines) + "\n"
        refl_parts.append(
            f"static char * _mojo_repr_{sn} ({sn} *obj) {{\n"
            + repr_body +
            f"}}\n"
        )
        # The ELEMENT REPR shim for a list/tuple of this struct: the walker
        # holds one `char *(*)(int64_t)` for a slot it reads as a word, and
        # this is the typed function behind it. A shim rather than a cast of
        # the real symbol into that pointer type, because calling
        # `char *(Foo *)(void)` through a `char *(int64_t)` is undefined
        # behaviour even where every ABI this targets passes it in the same
        # register.
        #
        # A user's own `__repr__` wins, which is CPython's rule for a
        # container element (a list reprs its elements with `repr`, not with
        # `str`, and not with a field dump) and the reason this is a shim and
        # not just `_mojo_repr_{sn}`: the field dump cannot see the dunder, and
        # a struct-allocated element has no type tag for
        # `_mojo_dispatch_repr` to dispatch on.
        _erep = self._struct_method_csym(sn, '__repr__', '')
        _erep_ok = self.func_return_types.get(_erep) == 'char *'
        elem_repr_names.add(sn)
        # Published on the emitter, because "is there a shim for this struct?"
        # is asked from the STORE lowerings (a list or a dict literal /
        # subscript store of this struct) and the emitter's condition is
        # NARROWER than "the struct has fields" — `reflect_structs` above is
        # `struct_field_types` filtered by `_emitted_structs` and
        # `_struct_allocs_needed` too, so a struct with fields can still get no
        # shim. Re-deriving that condition at the store site produced
        # `'_mojo_elem_repr_TrieNode' undeclared` in ast_rewriter.py's
        # self-host compile, i.e. an undefined-function reference at C link
        # time; this list is the emitter's own answer.
        self._elem_repr_shims.add(sn)
        refl_parts.append(
            f"static char * _mojo_elem_repr_{sn} (int64_t v) {{\n"
            f"  {sn} *o = ({sn} *)(intptr_t)v;\n"
            f"  if (!o) return strdup(\"None\");\n"
            + (f"  return {_erep} (o);\n" if _erep_ok
               else f"  return _mojo_repr_{sn} (o);\n")
            + f"}}\n"
        )
    if True:
        parts.append("/* Generic reflection dispatch (getattr/setattr/dataclasses.fields/is_dataclass) */")
        # The OWNED spelling of "None", for the field dumps below. A literal in a
        # `p ? <allocating repr> : "None"` ternary is what stopped that dump from
        # having ONE ownership answer per field: the chain could not release a
        # field's string without risking a `free()` of static storage, so it
        # released none of them. One helper, defined once beside the walkers that
        # use it, puts the fallback on the same footing as every other branch —
        # and it is a literal-to-owned adapter, not a second implementation of
        # any repr rule (`_mojo_generic_elem_repr`'s own comment records the same
        # remedy for the same reason).
        parts.append(
            "static char * _mojo_repr_none (void) {\n"
            "  return strdup(\"None\");\n"
            "}\n")
        parts.extend(refl_parts)
        tag_cases_get = "\n".join(
            f'  if (_tag == {_struct_type_id(sn)}) return _mojo_getattr_{sn}(({sn} *)obj, attr);'
            for sn in reflect_emitted)
        tag_cases_set = "\n".join(
            f'  if (_tag == {_struct_type_id(sn)}) {{ _mojo_setattr_{sn}(({sn} *)obj, attr, val); return; }}'
            for sn in reflect_emitted)
        tag_cases_fields = "\n".join(
            f'  if (_tag == {_struct_type_id(sn)}) return _mojo_fieldnames_{sn}();'
            for sn in reflect_emitted)
        tag_cases_asdict = "\n".join(
            f'  if (_tag == {_struct_type_id(sn)}) return _mojo_asdict_{sn}(({sn} *)obj);'
            for sn in reflect_emitted)
        tag_set_literal = ", ".join(
            str(_struct_type_id(sn)) for sn in reflect_emitted)
        if len(tag_set_literal) == 0:
            tag_set_literal = "0"
        asdict_dispatch_part = (
            "static MojoDict * _mojo_dispatch_asdict (void *obj) {\n"
            "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n"
            + f"{tag_cases_asdict}\n"
            + "  return mojo_dict_new();\n"
            "}\n"
        ) if self._asdict_dispatch_needed else ""
        parts.append(
            ("static int64_t _mojo_dispatch_getattr (void *obj, char *attr) {\n"
             "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
            + f"{tag_cases_get}\n"
            + ("  return mojo_obj_getattr(obj, attr);\n"
               "}\n"
               "static void _mojo_dispatch_setattr (void *obj, char *attr, int64_t val) {\n"
               "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
            + f"{tag_cases_set}\n"
            + ("  mojo_setattr(obj, attr, val);\n"
               "}\n"
               "static MojoList * _mojo_dispatch_fields (void *obj) {\n"
               "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
            + f"{tag_cases_fields}\n"
            + ("  return mojo_list_new();\n"
               "}\n")
            + asdict_dispatch_part
            + ("static int _mojo_dispatch_is_dataclass (void *obj) {\n"
               "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
            + f"  static const int64_t _known[] = {{{tag_set_literal}}};\n"
            + ("  if (_tag == 0) return 0;\n"
               "  for (size_t _i = 0; _i < sizeof(_known)/sizeof(_known[0]); _i++)\n"
               "    if (_known[_i] == _tag) return 1;\n"
               "  return 0;\n"
               "}\n")
        )
        tag_cases_repr = "\n".join(
            f'  if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)obj);'
            for sn in reflect_emitted)
        tag_cases_repr_elem = "\n".join(
            f'    if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)(intptr_t)val);'
            for sn in reflect_emitted)
        parts.append(
            ("static char * _mojo_dispatch_repr (void *obj) {\n"
             "  if (!obj) return \"None\";\n"
             "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
            + f"{tag_cases_repr}\n"
            + ("  return mojo_repr_obj((int64_t)(intptr_t)obj);\n"
               "}\n"
               # DESIGN.html R3 exception, NOT routed through the chokepoint:
               # this is static C SOURCE TEXT for a runtime helper function,
               # not per-call-site codegen through `gen` (no `gen` in scope
               # here at all). Already exactly the R5-recommended pattern —
               # each cast is guarded by its own `mojo_is_registered_list`/
               # `_dict` runtime check immediately above it.
               "static char * _mojo_generic_elem_repr (int64_t val) {\n"
               "  /* OWNS its return, on EVERY branch — see the note below the\n"
               "     function body. */\n"
               "  if (val == 0) return strdup(\"None\");\n"
               "  if (val > 65536) {\n"
               "    if (mojo_is_registered_list(val))\n"
               "      return _mojo_repr_list((MojoList *)(intptr_t)val);\n"
               "    if (mojo_is_registered_dict(val))\n"
               "      return _mojo_repr_dict((MojoDict *)(intptr_t)val);\n"
               "    int64_t _tag = mojo_read_type_tag_safe(val);\n")
            + f"{tag_cases_repr_elem}\n"
            + ("    return mojo_repr_str((char *)(intptr_t)val);\n"
               "  }\n"
               "  return mojo_repr_int(val);\n"
               "}\n"
               # The two returns above and below the dispatch switch are the
               # only ones that were NOT owned: `mojo_repr_obj` hands back a
               # shared static, and "None" is a literal. Every walker in the
               # four functions below therefore had to leave its per-slot
               # string alone, which is why a printed N-element container
               # leaked N of them on top of the N+1 cat buffers (a bug doc
               # since deleted with the fix, which is what this comment used to
               # cite by path).
               # Copying the two non-owned answers on the way out is the same
               # remedy `_key_slot_str` already applies on the dict-key path
               # (runtime/fire_runtime.c), for the same reason.
               #
               # `_mojo_dispatch_repr` keeps its shared returns: its other
               # caller (the `repr(x)` site) has no release point for them, so
               # making it own its result would trade one leak for another.
               # The per-struct `_mojo_repr_{sn}` field dump no longer has that
               # problem — it COPIES this dispatch's answer, the same way it
               # gets its `"None"` fallback from `_mojo_repr_none()`, so the
               # dump can release every one of its fields.
               "static char * _mojo_repr_list (MojoList *lst) {\n"
               "  /* A list that carries its own per-slot element kinds — a\n"
               "     `struct.unpack` result for a format that MIXES int/float/\n"
               "     bytes fields, or a heterogeneous list literal — describes\n"
               "     its slots one at a time, and the generic walker below\n"
               "     cannot: it reads every slot through mojo_list_get_int, so a\n"
               "     float prints as its raw IEEE-754 bit pattern. The codegen\n"
               "     picks the kinds-aware helper for a value whose kinds it\n"
               "     knows statically, but every DERIVED value (list(t), t[:],\n"
               "     t returned from a function) has no compile-time name to\n"
               "     look them up by — the runtime recorded them on the value\n"
               "     itself instead, so ask it here. One failed probe for a\n"
               "     list with no kinds, which is every other list. */\n"
               "  if (mojo_list_get_kinds(lst))\n"
               "    return mojo_repr_list_kinds(lst, 0);\n"
               "  int _is_tup = lst && mojo_is_tuple(lst);\n"
               "  if (!lst) return strdup(_is_tup ? \"()\" : \"[]\");\n"
               "  int64_t _n = mojo_list_len(lst);\n"
               "  char *_buf = strdup(_is_tup ? \"(\" : \"[\");\n"
               "  for (int64_t _i = 0; _i < _n; _i++) {\n"
               "    if (_i > 0) _buf = mojo_str_cat_free(_buf, \", \");\n"
               "    int64_t _e = mojo_list_get_int(lst, _i);\n"
               "    /* The list's own ELEMENT REPR, when the codegen recorded\n"
               "       one: this list's elements are a registered struct, and the\n"
               "       generic reader below cannot know that -- a struct-allocated\n"
               "       value carries no runtime type tag, so _mojo_dispatch_repr\n"
               "       never finds it and the slot printed as a raw pointer\n"
               "       decimal (bugs/CODEGEN_user_defined_dunder_repr_not_\n"
               "       consulted_by_str_and_container_spellings.md). Asked FIRST\n"
               "       because it is the most specific answer available; NULL\n"
               "       means this list says nothing and the path below is\n"
               "       unchanged. */\n"
               "    char *_re = mojo_list_repr_elem(lst, _e);\n"
               "    if (_re) { _buf = mojo_str_cat_free(_buf, _re); free(_re); continue; }\n"
               "    /* A registered 2-element element is a runtime-built PAIR\n"
               "       (zip / dict.items() / enumerate) and prints through the\n"
               "       pair walker, which gets slot 0 right where the generic\n"
               "       element repr cannot (see _mojo_repr_pair's own comment). */\n"
               "    char *_es = (_e > 65536 && mojo_is_registered_list(_e)\n"
               "       && mojo_list_len((MojoList *)(intptr_t)_e) == 2)\n"
               "        ? _mojo_repr_pair((MojoList *)(intptr_t)_e)\n"
               "        : _mojo_generic_elem_repr(_e);\n"
               "    _buf = mojo_str_cat_free(_buf, _es);\n"
               "    free(_es);\n"
               "  }\n"
               "  if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, \",\");\n"
               "  return mojo_str_cat_free(_buf, _is_tup ? \")\" : \"]\");\n"
               "}\n"
               "/* One 2-slot pair-list as `(a, b)`. Lives HERE, beside\n"
               "   _mojo_generic_elem_repr, because it reuses that function's\n"
               "   value reading (string / list / dict / tagged struct / int)\n"
               "   rather than keeping a second, drifting copy of it in the\n"
               "   runtime. The one thing it overrides is slot 0 when the value\n"
               "   is small: _mojo_generic_elem_repr answers \"None\" for a 0\n"
               "   slot, which is right for a genuinely dynamic list (0 can be a\n"
               "   boxed null there) and wrong for a pair, whose first slot is a\n"
               "   real value — the 0 INDEX of the first zip/enumerate pair, or a\n"
               "   small-int dict key. Without this, `zip([0, 1], [2, 3])` printed\n"
               "   `[(None, 2), (1, 3)]`. A first slot that IS a string (a dict\n"
               "   key) or a container still goes through the generic reader. */\n"
               "static char * _mojo_repr_pair (MojoList *p) {\n"
               "  if (!p) return strdup(\"()\");\n"
               "  int64_t _n = mojo_list_len(p);\n"
               "  char *_b = strdup(\"(\" );\n"
               "  for (int64_t _i = 0; _i < _n; _i++) {\n"
                "    if (_i > 0) _b = mojo_str_cat_free(_b, \", \");\n"
                "    int64_t _v = mojo_list_get_int(p, _i);\n"
                "    /* The list's own ELEMENT REPR, asked FIRST for slot 1 and ONLY for\n"
                "     * slot 1: `dict.items()` records the dict's struct repr on each\n"
                "     * PAIR (mojo_dict_items), and in a (key, value) pair that\n"
                "     * function describes the VALUE. Asking it for slot 0 as well\n"
                "     * handed the KEY -- a char * -- to the struct's own `__repr__`,\n"
                "     * which read it as a `P *` and printed `R<>` for the key 'k'.\n"
                "     * NULL means this pair says nothing. */\n"
                "    char *_pr = NULL;\n"
                "    if (_i == 1) _pr = mojo_list_repr_elem(p, _v);\n"
                "    if (_pr) { char *_o = mojo_str_cat_free(_b, _pr); free(_pr); _b = _o; continue; }\n"
                "    char *_s = (_i == 0 && !(_v > 65536))\n"
                "      ? mojo_repr_int(_v) : _mojo_generic_elem_repr(_v);\n"
                "    _b = mojo_str_cat_free(_b, _s);\n"
                "    free(_s);\n"
               "  }\n"
               "  if (_n == 1) _b = mojo_str_cat_free(_b, \",\");\n"
               "  return mojo_str_cat_free(_b, \")\");\n"
               "}\n"
"static char * _mojo_dict_val_repr (MojoDict *d, int64_t v) {\n"
                "  /* The dict repr's STRUCT-VALUE arm as ONE expression: this\n"
                "   * slot's recorded struct repr (mojo_dict_repr_val), or the\n"
                "   * generic element repr when the dict records none. A helper\n"
                "   * rather than two statements in the walker because gcc -fgimple\n"
                "   * does not take a braced block as an `else if` arm, and the arm\n"
                "   * has to be one statement to sit in the value-kind chain at all.\n"
                "   * It RETURNS rather than concatenating, so the walker's single\n"
                "   * `mojo_str_cat_free` + `free` pair releases every value-kind row\n"
                "   * the same way -- which is the whole of the leak this replaced,\n"
                "   * where only the struct arm released its temporary. */\n"
                "  char *_r = mojo_dict_repr_val(d, v);\n"
                "  if (_r) return _r;\n"
                "  return _mojo_generic_elem_repr(v);\n"
                "}\n"
               "static char * _mojo_repr_dict (MojoDict *d) {\n"
                "  if (!d) return strdup(\"{}\");\n"
                "  char *_buf = strdup(\"{\");\n"
                "  int64_t *_order = mojo_dict_order_indices(d);\n"
               "  for (int64_t _oi = 0; _oi < d->used; _oi++) {\n"
               "    int64_t _i = _order[_oi];\n"
                "    if (_oi > 0) _buf = mojo_str_cat_free(_buf, \", \");\n"
                "    /* NOTE the ABSENT arm here. `keykind == 2` means \"this\n"
                "     * key's text is a canonical decimal\", NOT \"the source\n"
                "     * wrote an integer\" -- `_canon_int` canonicalises a STR\n"
                "     * key into that slot too, deliberately, so `d[5]` and\n"
                "     * `d[\"5\"]` stay the one integer slot they have always\n"
                "     * been (see _canon_int's comment). Printing `ikey`\n"
                "     * unquoted for every keykind==2 slot therefore fixes\n"
                "     * `{10: \"a\"}` and breaks `{\"10\": \"a\"}`, which\n"
                "     * CPython prints as `{'10': 'a'}` -- and CPython's own\n"
                "     * answer depends on which spelling was inserted LAST, so\n"
                "     * the slot has to REMEMBER that. Not attempted; see\n"
                "     * bugs/CODEGEN_dict_comprehension_repr_is_separately_\n"
                "     * broken.md. */\n"
                "    char *_k = mojo_repr_str(mojo_dict_slot_key(d, _i));\n"
                "    _buf = mojo_str_cat_free(_buf, _k);\n"
                "    free(_k);\n"
                "    _buf = mojo_str_cat_free(_buf, \": \");\n"
                "    char *_s;\n"
                "    if (d->slots[_i].kind == 3)\n"
                "      /* A Python bool value (mojo_dict_set_bool): the same 0/1\n"
                "       * int64_t a real int stores, so only this per-SLOT tag\n"
                "       * separates them. The tag was once a whole-DICT flag,\n"
                "       * which meant one bool value reformatted every OTHER\n"
                "       * value too — `{'name': p.name, 'ok': p.ok}` printed\n"
                "       * `{'name': True, 'ok': True}`. A literal, so `_s` is not\n"
                "       * owned and must not be freed. */\n"
                "      _s = d->slots[_i].val ? \"True\" : \"False\";\n"
                  "    else if (d->slots[_i].kind == 2)\n"
                  "      /* A str value stored via mojo_dict_set_str carries its\n"
                  "       * pointer in `val` with kind==2; `_mojo_generic_elem_repr`\n"
                  "       * would read that pointer as an int64_t, so a dict LITERAL's\n"
                  "       * string values printed as garbage/0 (the `param_convs=`\n"
                  "       * / `comptime_aliases=` / `_CONST_NAME` .ast divergence).\n"
                  "       * Emit the real quoted string instead. */\n"
                  "      _s = mojo_repr_str((char *)(intptr_t)d->slots[_i].val);\n"
                  "    else if (d->slots[_i].kind == 1)\n"
                  "      /* A double value stores its IEEE-754 BITS in `val` with\n"
                  "       * kind==1, and those bits are a pointer-shaped word: 1.5 is\n"
                  "       * 0x3FF8000000000000 and 3.5 is 0x400C000000000000, which\n"
                  "       * `_mojo_generic_elem_repr` sends to\n"
                  "       * `mojo_read_type_tag_safe`, and that dereferences it (its\n"
                  "       * own guard only rejects words below 2 GiB). So\n"
                  "       * `print({'x': 1.5})` SEGFAULTED (rc -11, no output, no\n"
                  "       * diagnostic). The slot's own kind says what the word is;\n"
                  "       * read it that way, through the runtime's bits->double helper\n"
                  "       * rather than a C cast (a cast is not a legal gimple\n"
                  "       * operand). */\n"
                  "      _s = mojo_repr_float(mojo_double_from_bits(d->slots[_i].val));\n"
                  "    else if (d->slots[_i].kind == 4)\n"
                  "      /* A `None` value is int64_t 0 with kind==4 (see\n"
                  "       * mojo_dict_set_none): the same word a plain `0` stores,\n"
                  "       * and only this tag tells them apart. The generic value\n"
                  "       * repr below DOES answer \"None\" for a zero word -- it has\n"
                  "       * to, for a NULL pointer slot -- so every plain zero in\n"
                  "       * every dict printed as None until the store learned to\n"
                  "       * tag itself. */\n"
                  "      _s = strdup(\"None\");\n"
                  "    else if (d->slots[_i].val == 0)\n"
                  "      /* A kind-0 slot holding the word 0 is the INTEGER 0:\n"
                  "       * `None` now has kind 4 and a pointer slot is non-zero.\n"
                  "       * The generic value repr below cannot say so -- its\n"
                  "       * `val == 0` arm answers \"None\", correctly for the NULL\n"
                  "       * pointer it was written for -- so `{'z': 0}`,\n"
                  "       * `{'i': 0}` and `{k: 0 for k in ks}` all printed\n"
                  "       * `None`. A zero word with no tag says 0. */\n"
                  "      _s = strdup(\"0\");\n"
                  "    else if (d->slots[_i].kind == 5)\n"
                  "      /* A STRUCT value (mojo_dict_set_struct): the boxed pointer,\n"
                  "       * tagged so the walker asks the dict's own recorded repr\n"
                  "       * instead of dispatching on a runtime type tag -- which a\n"
                  "       * stack-allocated struct does not carry, its first word being\n"
                  "       * its first field. That is why this row printed the generated\n"
                  "       * field dump `P(x='a')` where CPython prints the user's\n"
                  "       * `__repr__` (`R<a>`), and why a LIST of the same struct needed\n"
                  "       * `mojo_list_set_elem_repr` for the same reason. Asked BEFORE\n"
                  "       * the `val == 0` arm above, which is about kind-0 slots: a NULL\n"
                  "       * struct pointer is `None`, which is what the recorded shim\n"
                  "       * says for it. */\n"
                  "      _s = _mojo_dict_val_repr(d, d->slots[_i].val);\n"
                  "    else\n"
                  "      _s = _mojo_generic_elem_repr(d->slots[_i].val);\n"
                  "    _buf = mojo_str_cat_free(_buf, _s);\n"
                  "    /* Only the kind==3 branch is a LITERAL; every other row is a\n"
                  "       * repr helper's heap return and is ours to release. */\n"
                  "    if (d->slots[_i].kind != 3) free(_s);\n"
               "  }\n"
               "  free(_order);\n"
               "  return mojo_str_cat_free(_buf, \"}\");\n"
               "}\n"
               "static char * _mojo_repr_set (MojoSet *s) {\n"
               "  if (!s || s->used == 0) return strdup(\"set()\");\n"
               "  char *_buf = strdup(\"{\");\n"
               "  int64_t *_order = mojo_set_order_indices(s);\n"
               "  for (int64_t _oi = 0; _oi < s->used; _oi++) {\n"
               "    int64_t _i = _order[_oi];\n"
               "    if (_oi > 0) _buf = mojo_str_cat_free(_buf, \", \");\n"
               "    char *_s = s->slots[_i].tag == 1\n"
               "        ? mojo_repr_str(s->slots[_i].val_s)\n"
               "        : mojo_repr_int(s->slots[_i].val_i);\n"
               "    _buf = mojo_str_cat_free(_buf, _s);\n"
               "    free(_s);\n"
               "  }\n"
               "  free(_order);\n"
               "  return mojo_str_cat_free(_buf, \"}\");\n"
               "}\n"
            )
        )
        parts.append('')










# Placeholder ctype for a struct field whose value type this pass could not
# resolve. MUST be machine-word sized: it is the "I don't know yet" marker
# (the `_existing_fn_ft in ('int', 'int64_t')` re-resolution test below treats
# it as provisional and lets a later, better-informed assignment overwrite
# it), and a real Python int already resolves to 'int64_t' via the IntLiteral
# branch — so 'int' was never the right answer for any KNOWN value, only the
# unknown one.
#
# It used to be plain `int`, which is 32 bits: a field holding an unresolved
# POINTER was then declared `int`, and the load `_tN = obj->field` truncated
# the top 32 bits before anything downstream could recover it. Concretely,
# ast_rewriter.py's `class Var: self.name = _as_str(name)` — `_as_str` is not
# one of the shapes the cascade below recognises — emitted
# `typedef struct Var { int64_t __mojo_type_id; int name; }`, so `pat.name`
# read back 0x001c7538 for a real `char *` at 0x1001c7538 and
# `mojo_dict_contains(bindings, _vn)` faulted on that truncated address.
# Note this also explains why wrapping the READ in `_as_str(...)` (the
# static-view cast idiom used throughout this codebase) could never fix such a
# field: the bits are already gone at the load, before the cast is applied.
# Widening the unknown placeholder to int64_t makes that idiom work as
# intended — the full pointer survives in an opaque word and `_as_str`
# re-views it — and cannot lose information for any value that fit in `int`.




def _class_field_decl(field):
    """`(name, value)` for a class-body field declaration in EITHER
    spelling, or None if this field is not that shape.

    `NAME = <value>` (an AssignStmt) and `var NAME = <value>` (a VarDecl)
    are the same declaration to Python — `var` only suppresses a type
    inference the class body never performed — but the class-attribute
    registration and global-declaration passes both used to match only the
    bare AssignStmt. A `var FIELD = struct.Struct('<HH')` therefore got a
    struct FIELD with the right ctype and NO initializer anywhere, leaving
    it NULL: the first `self.FIELD.size` was a live segfault, not a wrong
    value. Both spellings now reach both passes. Returns None for a bare
    `var x` with no value, which neither pass can initialize."""
    if isinstance(field, AssignStmt) and isinstance(field.target, IdentExpr):
        return field.target.name, field.value
    if isinstance(field, VarDecl) and field.name and field.value is not None:
        return field.name, field.value
    return None


def _own_class_field_index(fields, name) -> int:
    """Index of `name`'s OWN class-body declaration in `fields`, or -1.

    `_merge_struct_inheritance` (gimple_codegen.py) builds a subclass's
    `.fields` as BASE declarations FIRST and the class's own LAST — its own
    docstring: "own members override every base". So after the merge a
    subclass that OVERRIDES a base member has TWO declarations of that name
    in `.fields`, and the subclass's own is the LAST one. Every
    "first declaration of this name wins" scan over `.fields` therefore
    resolves to the BASE's, which is the opposite of the rule the merge
    documents.

    Measured, silent wrong value at exit 0:

        class Base:
            tag = 7
        class Child(Base):
            tag = 9

    emitted `_classattr_Child__tag = 7`, so `Child.tag` read 7, every
    `cls.tag` inside `Child`'s own methods read 7, and
    `class Grand(Child): tag = 11` read 7 too — the whole inheritance chain
    took the ROOT's value.

    The comparison is `_cfd[0] == name`, exactly as the scanning loops
    already spell it, so the self-hosted answer for a boxed field read is
    unchanged; `range(len(...))` rather than `reversed()` because the
    self-hosted backend has no lowering for the lazy reverse iterator.
    """
    _pick = -1
    _fl = _as_list(fields)
    for _i in range(len(_fl)):
        _cfd = _class_field_decl(_fl[_i])
        if _cfd is not None and _cfd[0] == name:
            _pick = _i
    return _pick


def _ctor_param_evidence(gen, struct_name, param, xf_own) -> str:
    """The literal-evidence ctype for `<struct>::<param>` of an UNANNOTATED
    `__init__` parameter, or `''` when there is none.

    One reader for the two tables that carry it, in the one precedence they
    agree on — this module's own call sites
    (`gen._ctor_lit_param_types`) first, an IMPORTING module's literal call
    sites (`_xf_own_ctor_params`) second — because the two consumers have to
    reach the SAME answer or the store and the declaration disagree:
    `gen_module_impl`'s field pass types `self.f = f`'s FIELD from it, and the
    struct-method signature loop types the PARAM from it. When the param was
    left at the `int64_t` default in the signature while the field said
    `double`, `B(2.5)` truncated the argument to 2 at the call and read back
    as 2.0 (bugs/CODEGEN_literal_evidence_param_field_typed_but_signature_
    not.md). Both halves must come from one function for that to stay fixed.

    Module-level, not a closure in `gen_module_impl`: a nested closure here
    emitted NOTHING once the self-hosted binary compiled the compiler (see
    `_with_emit_exits`'s docstring for the same failure mode).
    """
    _key = _as_str(struct_name) + '::' + _as_str(param)
    _own = getattr(gen, '_ctor_lit_param_types', None) or {}
    _t = _own.get(_key)
    if _t:
        return _as_str(_t)
    _xf = xf_own or {}
    _t = _xf.get(_key)
    if _t:
        return _as_str(_t)
    return ''


def _gmi_collect_self_reads(_method_names: set, body, found: dict) -> None:
    """Hoisted out of `gen_module_impl` — see `_gmi_collect_self_assigns`."""
    for node in _walk_ast(body):
        fn = _gmi_self_member(node)
        if (fn is not None and fn not in found and fn not in _method_names
                and fn not in _PSEUDO_DUNDER_ATTRS):
            found[fn] = _UNKNOWN_FIELD_CTYPE








def _gmi_emit_closure_recursive(self, func_parts: list, _emitted_closures: set,
                                _emitted_env_allocs: set, ci, outer_name) -> None:
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Recursive (emits sub-closures depth-first).
    The `func_parts` LIST and the two `_emitted_*` SETS are threaded and
    annotated per the hoist GOTCHA; `outer_name` was a `= None` default,
    now an explicit required arg (the default-param shape is exactly what
    produces the call-site arity flip)."""
    if ci.lifted_name in _emitted_closures:
        return
    _emitted_closures.add(ci.lifted_name)
    for sub_ci in self._all_closures.get(ci.lifted_name, {}).values():
        _gmi_emit_closure_recursive(self, func_parts, _emitted_closures,
                                    _emitted_env_allocs, sub_ci, ci.lifted_name)
    if ci.env_struct and ci.env_struct not in _emitted_env_allocs:
        _emitted_env_allocs.add(ci.env_struct)
        alloc_fn = f"_alloc_{ci.env_struct}"
        # Plain-C size accessor, immediately before its only caller — see
        # GimpleGen._c_sizeof_helper / _c_helper_def.
        _env_sz = self._c_sizeof_helper(ci.env_struct)
        _env_sz_def = self._c_helper_def(_env_sz)
        if _env_sz_def:
            func_parts.append(_env_sz_def)
            func_parts.append('')
        func_parts.append(
            f"{ci.env_struct} * __GIMPLE {alloc_fn} (void)\n"
            f"{{\n"
            f"  {ci.env_struct} * _e;\n"
            f"  void * _vp;\n"
            f"  int64_t _vs;\n"
            f"\nbb_2:\n"
            f"  _vs = {_env_sz} ();\n"
            f"  _vp = malloc (_vs);\n"
            f"  _e = ({ci.env_struct} *) _vp;\n"
            f"  return _e;\n"
            f"}}"
        )
        func_parts.append('')
    # A LAMBDA inside this closure's body is lifted by `_lower_LambdaExpr`
    # into `gen._lambda_parts` — a side table that only `gen_module` flushes
    # into the output, and it used to be flushed only by the top-level-
    # function, struct-method and toplevel paths. This path did not, so a
    # lambda nested inside a nested `def` was DECLARED and had its address
    # taken (`static void * _funcptr_X = (void *)X;`) but was never defined:
    # `Undefined symbols ...: "__make_make_lambda_1", referenced from:
    # __funcptr__make_make_lambda_1` at link time. Clear the table BEFORE
    # generating the body (so nothing pending from an earlier function is
    # misattributed to this one) and flush it AFTER (so this one's lambdas
    # are emitted) — the same reset-then-flush the sibling paths do, and the
    # reason their comments all repeat it.
    self._lambda_parts = []
    func_parts.append(self._gen_lifted_closure(ci, outer_name))
    func_parts.append('')
    if self._lambda_parts:
        func_parts.extend(self._lambda_parts)
        self._lambda_parts = []

# `_gmi_expr_provably_str` is NOT defined here: it is
# `mojo.middle.exprtypes.expr_provably_str`, imported above under that local
# spelling so this file's own call sites read unchanged. This module carried a
# byte-for-byte copy of it from the mojo/middle restructure, which is exactly
# the duplication that shared predicate exists to prevent -- its two callers
# here (the `_gmi_prefold_toplevel_comptime` str-evidence collector and
# `_lower_LambdaExpr`'s untyped-slot check) widen a parameter's evidence, so a
# second implementation could disagree with `emit_calls.py`'s about whether a
# `char *` was observed, and that disagreement is invisible.
#
# The compiler-internal dispatch/type-table globals (`_STMT_DISPATCH` etc.)
# that get a bare `MojoDict *` / `MojoList *` / `MojoSet *` module-global field
# rather than the boxed `int64_t` convention. Membership is
# `dispatch_table_global_ctype`'s (the ONE table the global-declaration and
# seed sites also read, so a name added there is declared here too). This used
# to be a module-level tuple of names with an explicit `==` loop, and before
# that a set literal: `name in <a set literal>` returned True for UNRELATED
# names on the self-hosted compiled path (`'arr' in _dispatch_names`),
# declaring an ordinary `arr = [1,2,3]` global as a bare `MojoList *` field (a
# stage1-vs-stage2 parity break under MOJO_NO_SHIM=1, array_ops_jit.mojo). The
# `... is not None` form keeps the dict's own lookup as the only membership
# test, so the loop that outranked `in` is no longer reachable at all.
def _is_dispatch_name(_n) -> bool:
    return dispatch_table_global_ctype(_as_str(_n)) is not None


def _gmi_declare_table_global(gen, gname, global_decls) -> bool:
    """Declare the module global `gname` with the C type
    `dispatch_table_global_ctype` gives it, and record that type in BOTH of
    `gen`'s global tables. Returns False — declaring nothing — for an ordinary
    global, so the caller falls through to its own RHS-derived conclusion.

    ONE place, called at the TOP of both module-global declaration scans, and
    the reason it is at the top rather than per-RHS-shape is that the answer
    has to be the same whichever scan reaches the name first. The home module's
    own scan and every importer's re-declaration of the same name have to agree
    about the field's C type, because a bare read of a dispatch global is
    emitted as a direct `_<mod>_globals.NAME` load typed from
    `_global_var_types` — so a home that boxes the field while an importer
    declares it bare is a hard
    "assignment to 'MojoSet *' from 'int64_t' makes pointer from integer
    without a cast", once per read.

    That is what consulting the table only from the DictExpr/ListExpr/SetExpr
    rows did: `module_loader.py`'s `_C_KEYWORDS = frozenset({...})` is a CALL,
    so its own scan never reached one of those rows, fell to the generic
    int64_t fallback, and declared `int64_t _C_KEYWORDS` in
    `_module_loader_toplev` while `gimple_codegen`/`module_gen`/`module_shared`
    all declared the same name `MojoSet *`.
    """
    _forced = dispatch_table_global_ctype(gname)
    if _forced is None:
        return False
    global_decls.append(f"{_forced} {gname};")
    gen._global_var_types[gname] = _forced
    gen._global_c_decl_types[gname] = _forced
    return True


# The container C types a constructor argument is allowed to resolve a
# struct field to. A field is pinned to exactly ONE ctype
# (`struct_field_types[struct][field]`), which is why the constructor-argument
# observation passes below must be conservative in a way the free-function
# parameter pass (`_infer_param_types`, which types a parameter per use site
# and is free to widen) is not: an answer here is acted on only when it is
# unanimous across every call site, and "no evidence" always beats a guess.
# Kept as a tuple + explicit `==` chain (not a `in <set literal>` test) for
# the same self-hosted reason `_is_dispatch_name` above documents.
_CTOR_CONTAINER_CTYPES = ('MojoList *', 'MojoDict *', 'MojoSet *')


def _gmi_is_ctor_container_ctype(t) -> bool:
    _ts = _as_str(t)
    for _ct in _CTOR_CONTAINER_CTYPES:
        if _ts == _ct:
            return True
    return False


def _lambda_ret_type(gen, node) -> str:
    """The C return type `_lower_LambdaExpr` will declare for this lambda.

    That lowering builds the synthetic body `return <node.body>` and calls
    `_infer_return_type` on it, which is `TypeLattice.join_all` over
    `_quick_type` of that one expression. Computed here from the same two
    facts, so the answer is the lifted definition's declared type by
    construction rather than by coincidence -- and available without
    lifting, which is what lets the Phase 1.7 pre-scan record it.

    `void` (a `None` body) is normalized to `int64_t`, matching the
    lifted definition: `_collect_return_types` yields the `void` string for
    a value-less `return`, and `_lower_fnptr_call_value`'s `ret_type ==
    'void'` arm already handles it, so it needs no special case here."""
    if node.body is None:
        return 'int64_t'
    return _as_str(TypeLattice.join_all([_as_str(gen._quick_type(node.body))]))


def _lambda_pairs_ret_type(gen, pairs) -> str:
    """The single callable return type stored in a dict LITERAL of lambdas,
    or '' when they disagree (or are not all lambdas).

    The unanimity-or-nothing rule is `note_container_callable_ret`'s, applied at
    the one site that knows every element before the dict exists. '' is the
    ambiguous answer, and every consumer reads it with `or 'int64_t'`, so
    this can only preserve the pre-existing behaviour, never invent one."""
    agreed = ''
    for _pair in pairs:
        _val = _pair[1]
        if not isinstance(_val, LambdaExpr):
            return ''
        _rt = _lambda_ret_type(gen, _val)
        if agreed == '':
            agreed = _rt
        elif agreed != _rt:
            return ''
    return agreed










def _gmi_has_unresolved_base(_struct_bases_map: dict, _all_struct_names: set,
                             _memo: dict, _name, _stack: list):
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Recursive; the memo dict, the name set, and the
    cycle-guard `_stack` (a LIST, not a frozenset — `_stack | {_name}` set
    union with a literal crashed the self-hosted backend the same way the
    `_coro_generic_names` set-intersection did; list concat is reliable)
    are threaded explicitly. EXPLICIT param annotations are load-bearing:
    the hoisted function's body uses `_memo[_name]`/`_name in _memo` with
    no dict-literal or `.items()` signal anywhere, so without `_memo: dict`
    the self-hosted backend inferred it as a LIST and `_memo[_name] =
    result` lowered to `mojo_list_set_int` -> Bus error (lldb-confirmed).
    The original nested closure inherited the type from the enclosing
    `_unresolved_base_memo: dict = {}` declaration; a hoisted param has no
    such context."""
    if _name in _memo:
        return _memo[_name]
    if _name in _stack:
        return False  # inheritance-cycle guard; shouldn't normally happen
    result = False
    _next_stack = _stack + [_name]
    for _b in _struct_bases_map.get(_name, ()):
        if _b not in _all_struct_names or _gmi_has_unresolved_base(
                _struct_bases_map, _all_struct_names, _memo, _b, _next_stack):
            result = True
            break
    _memo[_name] = result
    return result


# The statement-lists a `class` statement can be nested inside. A tuple of
# names, not a dict of attribute name -> is-a-list: the walk has to try EVERY
# slot on every node type (only the statement types that carry one of them
# actually have it, and `getattr(..., None)` answers the rest), so the test is
# "does this attribute hold a statement list", not "is this node a kind that
# does". Written out rather than reusing the shared `_walk_ast`, for the
# reason `_gmi_collect_self_assigns`'s own nested-def descent documents:
# `_walk_ast` does not reliably recurse into a nested `StructDef`/`FunctionDef`
# self-hosted (the node is misclassified as a scalar leaf), so a walker built
# on it would find nested classes in the CPython shim and miss them under
# `mojoc`. Every consumer of "is there a class declared in here" has to be
# written out, so it is written out once here.
_NESTED_CLASS_BODY_SLOTS = (
    'body', 'then_body', 'else_body', 'finally_body', 'items',
)


def _gmi_nested_struct_defs(body, enclosing, out: list, top: bool = False) -> None:
    """Every `StructDef` written INSIDE `body`, in source order, as
    `[node, enclosing_key]` PAIRS rather than 2-tuples.

    The pairs are index-addressed by the one caller for the reason the rest of
    this file writes index loops instead of `zip()`: the self-hosted backend
    has no `zip()` lowering, and a 2-tuple unpack in a `for` header boxes both
    slots to `int64_t` — which here would box the `StructDef` POINTER (losing
    the node) and the string (losing the name). A list element read by index
    keeps each slot's own type.

    Recursive over the statement-lists a class can hide in: a plain function
    body, an `if`/`else`/`while`/`for`/`try`/`with`/`match` body, and a nested
    `def` or `class` body. `enclosing` is the `current_func_name`-shaped key of
    the innermost enclosing function — which is exactly the value
    `current_func_name` holds while that function's body is lowered, so the
    rename map the caller builds is keyed the same way the constructor call
    site reads it. `top` is True only for the module-level statement list,
    whose classes are already module scope and must not be collected again.
    """
    for _nc in (body or []):
        if isinstance(_nc, StructDef):
            if not top:
                out.append([_nc, enclosing])
            # A struct METHOD's enclosing key is `current_func_name`, which the
            # method emitter sets to `<struct>_<method>` — the class's own name
            # with no enclosing-function prefix (`closures.discover_closures`
            # composes it the same way).
            _cname = _as_str(_nc.name)
            for _ncm in (_nc.methods or []):
                if isinstance(_ncm, FunctionDef):
                    _gmi_nested_struct_defs(
                        _ncm.body, _cname + '_' + _as_str(_ncm.name), out)
            continue
        if isinstance(_nc, FunctionDef):
            # A nested `def` is LIFTED as `<outer>_<name>`, and `current_func_name`
            # is the lifted name while its body is lowered — so the key
            # composes rather than replacing. `closures.discover_closures`'s
            # `lifted = f"{outer_name}_{inner.name}"` is the other half of
            # that fact.
            _gmi_nested_struct_defs(
                _nc.body,
                enclosing + '_' + _as_str(_nc.name) if enclosing else _as_str(_nc.name),
                out)
            continue
        if isinstance(_nc, IfStmt):
            _gmi_nested_struct_defs(_nc.then_body, enclosing, out)
            # `elifs` is a list of (condition, body) PAIRS, so the body is an
            # indexed slot read and not another statement list — the same
            # shape `_gmi_collect_self_assigns` walks.
            for _nce in range(len(_nc.elifs or [])):
                _gmi_nested_struct_defs(_nc.elifs[_nce][1], enclosing, out)
            _gmi_nested_struct_defs(_nc.else_body, enclosing, out)
            continue
        if isinstance(_nc, MatchStmt):
            for _ncmc in (_nc.cases or []):
                _gmi_nested_struct_defs(
                    getattr(_ncmc, 'body', None), enclosing, out)
            continue
        for _slot in _NESTED_CLASS_BODY_SLOTS:
            _gmi_nested_struct_defs(
                getattr(_nc, _slot, None), enclosing, out)


def _gmi_target_leaf_names(target, out: set) -> None:
    """Add every NAME a binding target introduces to `out`. Handles the three
    shapes a target has: a bare `IdentExpr`, a `TupleExpr`/`ListExpr` of them
    (`(a, b) = ...`), and the PARENTHESISED-TEXT form the parser preserves for
    a `for q, w in ...` loop target and for `*rest` / `**kw` — flattened by the
    one reader `types._unpack_target_leaf_names` already is, rather than by a
    second walk (its own docstring records the `(a)`-versus-`(a,)` bug a
    second walk would reintroduce)."""
    if target is None:
        return
    if isinstance(target, str):
        for _leaf in _unpack_target_leaf_names(target):
            if _leaf:
                out.add(_leaf)
        return
    if isinstance(target, (TupleExpr, ListExpr)):
        for _el in (target.elements or []):
            _gmi_target_leaf_names(_el, out)
        return
    _tname = getattr(target, 'name', None)
    if isinstance(_tname, str) and _tname:
        out.add(_tname)


def _gmi_local_binding_names(stmts, out: set) -> None:
    """Every name a LOCAL binding can introduce anywhere in `stmts` — the
    parameters of every function and method, and every `VarDecl`,
    assignment target, `for`/`with`/`except`/comprehension target, at any
    nesting depth inside a body.

    Its only consumer is `_gmi_hoist_nested_structs`, and the question it
    answers is a C one: a local variable named `K` SHADOWS the typedef
    `typedef struct K { ... } K;`, so every type use of that struct inside that
    function stops compiling (`_alloc_K`'s `K * _t4;` becomes "K undeclared",
    and gcc then cascades over the rest of the function). The rule follows
    from that: a hoisted class keeps its bare name only when no local in the
    module can shadow the typedef.

    Written out over the node types rather than delegated to `_walk_ast` for
    the reason `_gmi_collect_self_assigns` documents: `_walk_ast` does not
    reliably recurse self-hosted. It is deliberately over-broad — a
    comprehension's element is a local even where the comprehension lowers to
    something else, and naming a few names that turn out not to become C
    locals can only make a hoist be SKIPPED, never make it be wrong.
    """
    if not isinstance(stmts, list):
        return
    for _lb in (stmts or []):
        if isinstance(_lb, VarDecl):
            if _lb.name:
                out.add(_as_str(_lb.name))
        elif isinstance(_lb, FunctionDef):
            # Indexed param slots, never `isinstance(_p, list)`: a param is a
            # (name, annotation) TUPLE under CPython, so a list test is False
            # for every one of them and a PARAMETER would never be counted as
            # a local — which for `_gmi_hoist_nested_structs` means a
            # parameter shadowing a hoisted struct's typedef goes unnoticed.
            for _lbp in range(len(_lb.params or [])):
                _gmi_target_leaf_names(_lb.params[_lbp][0], out)
            _gmi_local_binding_names(_lb.body, out)
        elif isinstance(_lb, StructDef):
            for _lbm in (_lb.methods or []):
                if isinstance(_lbm, FunctionDef):
                    for _lbmp in range(len(_lbm.params or [])):
                        _gmi_target_leaf_names(_lbm.params[_lbmp][0], out)
                    _gmi_local_binding_names(_lbm.body, out)
        elif isinstance(_lb, (AssignStmt, AugAssignStmt)):
            _gmi_target_leaf_names(_lb.target, out)
            if isinstance(_lb.value, Comprehension):
                _gmi_comprehension_targets(_lb.value, out)
        elif isinstance(_lb, MultiAssignStmt):
            for _lbt in (_lb.targets or []):
                _gmi_target_leaf_names(_lbt, out)
        elif isinstance(_lb, ForStmt):
            _gmi_target_leaf_names(_lb.target, out)
            _gmi_local_binding_names(_lb.body, out)
            _gmi_local_binding_names(_lb.else_body, out)
        elif isinstance(_lb, WhileStmt):
            _gmi_local_binding_names(_lb.body, out)
            _gmi_local_binding_names(_lb.else_body, out)
        elif isinstance(_lb, WithStmt):
            for _lbi in (_lb.items or []):
                _gmi_target_leaf_names(getattr(_lbi, 'alias', None), out)
            _gmi_local_binding_names(_lb.body, out)
        elif isinstance(_lb, TryStmt):
            _gmi_local_binding_names(_lb.body, out)
            for _lbh in (_lb.handlers or []):
                if getattr(_lbh, 'name', None):
                    out.add(_as_str(_lbh.name))
                _gmi_local_binding_names(getattr(_lbh, 'body', None), out)
            _gmi_local_binding_names(_lb.else_body, out)
            _gmi_local_binding_names(_lb.finally_body, out)
        elif isinstance(_lb, IfStmt):
            _gmi_local_binding_names(_lb.then_body, out)
            for _lbe in range(len(_lb.elifs or [])):
                _gmi_local_binding_names(_lb.elifs[_lbe][1], out)
            _gmi_local_binding_names(_lb.else_body, out)
        elif isinstance(_lb, MatchStmt):
            for _lbc in (_lb.cases or []):
                _gmi_local_binding_names(getattr(_lbc, 'body', None), out)


def _gmi_comprehension_targets(comp, out: set) -> None:
    """The locals a comprehension introduces: each generator's target plus its
    `element` / `key` binding."""
    for _cg in (getattr(comp, 'generators', None) or []):
        _gmi_target_leaf_names(getattr(_cg, 'target', None), out)
        for _cgc in (getattr(_cg, 'conditions', None) or []):
            _gmi_target_leaf_names(getattr(_cgc, 'target', None), out)
    _gmi_target_leaf_names(getattr(comp, 'element', None), out)
    _gmi_target_leaf_names(getattr(comp, 'key', None), out)


def _gmi_hoist_nested_structs(self, stmts: list) -> list:
    """Return `stmts` with every class declared inside a function body HOISTED
    to module scope, so the ordinary struct pipeline treats it exactly like a
    class written at module level.

    Why this has to happen here, at all: a `class` statement is a TYPE
    declaration, and every consumer of the module's struct set — the
    `struct_field_types` seed, `_merge_struct_inheritance`, the `_alloc_X`
    helper, the `typedef struct X` and the method-BODY emission loop — reads
    the module-level statement list. A `StructDef` nested in a
    `FunctionDef.body` was in none of them, so the class had no layout and no
    emitted methods, and `_lower_MemberExpr`'s method-call arm (which resolves
    the receiver's struct through `struct_field_types`) found nothing and fell
    into its stub branch, which yields the RECEIVER. That made every method
    call on a class defined inside a function answer with the object itself at
    exit 0 with no diagnostic. (Fixed 2026-10-02; the residue — a nested
    class's method cannot read the enclosing function's locals, so
    `functools.cmp_to_key`'s comparison dunders compare with a stubbed
    comparator — is bugs/CODEGEN_nested_class_method_cannot_reach_an_
    enclosing_local.md.)

    Hoisting APPENDS and does not move: the original statement stays in the
    function body, where it lowers to the same `TODO: StructDef` no-op it
    always has. That is deliberate. `_gmi_collect_self_assigns` folds a nested
    class's `self.<f> = ...` onto the ENCLOSING struct as a workaround for the
    nested class having no layout of its own
    (`mojo/middle/module_shared.py`, whose comment says so); removing the
    statement from the body would silently withdraw that folded field and break
    every consumer of it. Appending is purely additive — the nested class gains
    the layout it should have had, and nothing else changes.

    NAME COLLISION. Two things can stop a hoisted class from using its bare
    name, and both rename it to `<Name>__<enclosing>` with the mapping recorded
    in `_nested_struct_names` (keyed by `_pair_key(current_func_name,
    bare_name)` — the composite-key convention the closure tables use, so the
    constructor call site inside the defining function resolves the RIGHT
    class):

    * **another struct already claims the name** — a module-level class of the
      same name, or a second function's nested one. `_struct_name_owner`'s
      first-wins would DROP the loser's method symbols, so the second class
      would silently borrow the first one's layout.
    * **a LOCAL binding in this module has the name** — and this one is a hard
      build failure rather than a wrong answer. A C local named `K` SHADOWS
      `typedef struct K { ... } K;`, so every type use of that struct inside
      that function stops compiling (`K * _t4;` becomes "K undeclared" and gcc
      cascades over the rest of the function). `functools.cmp_to_key`'s `K` is
      the real-world instance: the class is nested, and the conventional
      `K = cmp_to_key(cmp)` binds a local named `K` in the caller.

    The bare name survives whenever neither applies, which is the
    overwhelmingly common case and leaves every existing name-keyed lookup
    (constructor, method symbol, field table) untouched.
    """
    _taken = set(self._imported_struct_home)
    for _t_src in (list(stmts) + list(self._imported_typedef_structs)):
        if isinstance(_t_src, StructDef):
            _taken.add(_as_str(_t_src.name))
    _locals_named: set = set()
    _gmi_local_binding_names(stmts, _locals_named)
    found: list = []
    _gmi_nested_struct_defs(stmts, '', found, True)
    if not found:
        return stmts
    _nested_names: dict = getattr(self, '_nested_struct_names', None)
    if _nested_names is None:
        _nested_names = {}
        self._nested_struct_names = _nested_names
    out = list(stmts)
    renamed_from: list = []
    renamed_to: list = []
    for _h_i in range(len(found)):
        _h_node = found[_h_i][0]
        _h_encl = _as_str(found[_h_i][1])
        _h_bare = _as_str(_h_node.name)
        if _h_bare not in _taken and _h_bare not in _locals_named:
            _taken.add(_h_bare)
            renamed_from.append(_h_bare)
            renamed_to.append(_h_bare)
            out.append(_h_node)
            continue
        _h_base = _h_bare + '__' + _h_encl
        _h_new = _h_base
        _h_n = 2
        while _h_new in _taken:
            _h_new = _h_base + str(_h_n)
            _h_n += 1
        _taken.add(_h_new)
        renamed_from.append(_h_bare)
        renamed_to.append(_h_new)
        _h_node.name = _h_new
        out.append(_h_node)
    # The alias keys need the FINAL struct names, because a method's enclosing
    # key contains the name of the class it belongs to — so they are computed
    # on a SECOND walk, after the renames above have landed. The two walks
    # visit the same nodes in the same order (only `.name` changed, which no
    # branch of the walk reads), so position correlates them; that is why this
    # is positional rather than an `id()` keyed side table, which the rest of
    # this codebase treats as unreliable self-hosted.
    again: list = []
    _gmi_nested_struct_defs(stmts, '', again, True)
    for _h_i in range(len(again)):
        if renamed_to[_h_i] != renamed_from[_h_i]:
            _nested_names[_pair_key(
                _as_str(again[_h_i][1]), renamed_from[_h_i])] = renamed_to[_h_i]
    return out









def gen_module_impl(self, stmts):

    # A class written INSIDE a function body is a type declaration like any
    # other, and the struct pipeline reads the module-level statement list, so
    # it is hoisted there before anything consumes the list. See
    # `_gmi_hoist_nested_structs` for why it appends rather than moves.
    stmts = _gmi_hoist_nested_structs(self, stmts)

    # ── GPU offload, Seam 1 ──────────────────────────────────────────────
    # Classified ONCE, at the very top, because three different places
    # need the answer and they run at different times: the preamble (to emit
    # the runtime include and the prototypes the compiled program calls),
    # the function-body loop (to route a device function to the MSL emitter
    # instead of gen_func), and the tail (to emit the sidecar). Deciding
    # "emit this one to a different target" is not something an emitter can
    # do about a function it has already started, which is why this is a
    # pre-pass and not a check inside gen_func.
    _device_kinds = _gmi_device_select.classify_functions(stmts)

    # Increment 3 (doc/GPU_OFFLOAD_PLAN.html): synthesise a device function
    # for a recognised parallel loop nest, so ordinary Python offloads with
    # no marker. The synthesised FunctionDef is appended to `stmts` and
    # carries `@gpu`, which is what makes it flow through seam 1's
    # classifier, seam 2's MSL emitter and seam 3's host wrappers with no
    # change to any of them -- increment 3 adds a recogniser and a
    # synthesiser, not a second code path.
    #
    # The synthesised functions are added AFTER the classifier has run and
    # then the classification is refreshed, because a synthesised function is
    # not in `stmts` when classify_functions sees it.
    #
    # `--no-gpu` (`self.auto_gpu` False) skips the synthesis entirely. It
    # does NOT change `_device_kinds`: a marked or registrar-reached function
    # is still DEVICE, because that was an explicit request and the flag is
    # about inference.
    # BOTH halves: the synthesised kernels AND the host rewrite that calls
    # them. The kernel alone is unreachable, which would make the whole
    # feature dead code that compiles and never runs.
    if getattr(self, 'auto_gpu', True):
        # The synthesiser needs somewhere to record per-buffer element counts
        # (a GEMM's A is M*K, B is K*N, C is M*N, and one count cannot say
        # that). Created HERE, before the synthesis, and read by the
        # classification pass below -- which is why that pass creates it only if
        # absent rather than re-initialising it.
        if not hasattr(self, '_device_launch_lengths'):
            self._device_launch_lengths = {}
        if not hasattr(self, '_device_launch_grids'):
            self._device_launch_grids: dict = {}
        stmts, _synth_names = _gmi_offload.offload_module(
            stmts, lengths_sink=self._device_launch_lengths,
            grids_sink=self._device_launch_grids)
    else:
        _synth_names = []
    if _synth_names:
        stmts = list(stmts) + list(_synth_names)
        _device_kinds = _gmi_device_select.classify_functions(stmts)

    _device_parts: list[str] = []
    # A shared SET, not a bool, because this has to be shared by REFERENCE
    # with every temp_gen the closure creates -- exactly like
    # `_emitted_ptr_helpers` and `_module_stmts` (see the share block in
    # emit_resolve._compile_imported_module, which is where the flag has to be
    # wired in). A bool assigned across would copy its value, so an inner
    # module's "I emitted it" would not reach the outer one and every module
    # would emit its own copy -- which is the bug this fixes: a single-TU
    # closure carries ~160 modules, and 18 redefinitions of
    # `_mojo_gpu_kernel_count` failed `mojoc` and `selfhost` outright.
    _mg_introspected = self.__dict__.setdefault(
        '_mg_introspection_emitted', set())
    _device_names = sorted(n for n, k in _device_kinds.items()
                           if k == _gmi_device_select.DEVICE)
    # The host-side marshalling signature of every device kernel, computed
    # HERE, off the AST, because a device function never runs through
    # gen_func and so never gets an inferred C signature to read back. It
    # feeds two emissions at different times: the prototypes in the
    # preamble, and the wrapper definitions in the tail sidecar.
    self._device_kernels = {n: True for n in _device_names}
    # Which of those a HUMAN marked, and which merely matched by inference --
    # see the DEVICE branch's own note. A function that falls back to the host
    # is recorded here so the reason is visible instead of silent.
    _device_explicit = _gmi_device_select.explicitly_marked_functions(stmts)
    _device_fallbacks: list = []
    self._device_launch_args = {}
    self._device_launch_count: dict = {}
    # Per-BUFFER element-count expressions, recorded by the SYNTHESISER:
    # {kernel_name: {param_name: "m * k"}}. It is synthesis metadata and not
    # something a type annotation can carry -- a GEMM's A is M*K, B is K*N and
    # C is M*N, and no spelling of `List[Float32]` says which. Applied to the
    # LaunchArgs just below, where they are built.
    # Created ONCE, not reset here: the synthesiser records into this table
    # BEFORE the module is generated, and a plain `= {}` in the classification
    # pass silently wiped it -- measured, every buffer came out sized to the
    # kernel's single Int parameter and two tests failed while the plumbing
    # looked correct. The other two tables ARE reset per module and should be;
    # this one carries information from an earlier pass.
    if not hasattr(self, '_device_launch_lengths'):
        self._device_launch_lengths: dict = {}
    _device_kernels_meta: dict = {}
    for _s in stmts:
        if (isinstance(_s, FunctionDef)
                and _device_kinds.get(_as_str(_s.name)) == _gmi_device_select.DEVICE):
            _nm = _as_str(_s.name)
            _tys, _ci = _gmi_device_glue.launch_arg_types(_s.params)
            # Apply any per-buffer lengths the synthesiser recorded for this
            # kernel. A NamedTuple._replace keeps every other field, so this
            # cannot silently drop `writable` -- which is the field whose loss
            # would skip a copy-back and leave the output list untouched.
            _lens = self._device_launch_lengths.get(_nm) or {}
            if _lens:
                _tys = [_a._replace(length=_lens[_a.name]) if _a.name in _lens
                        else _a for _a in _tys]
            # Fail here, at the classification pass, rather than at the first
            # call site: an un-marshallable kernel is a build error either
            # way, and failing before anything is emitted gives a file and
            # line instead of a stack through the call-site lowering.
            try:
                _gmi_device_glue.element_count_index(_nm, _ci)
            except _gmi_device_glue.LaunchError as _le:
                # No length parameter means the host has no way to size the
                # copy-back, so this kernel cannot be dispatched -- a real
                # limitation, and for an EXPLICIT `@gpu` a build error is the
                # right answer (the check exists so a silently-empty
                # copy-back cannot pass for a result).
                #
                # For an INFERRED stdlib kernel it is not: nobody asked for
                # the device path, and raising here made the module
                # uncompilable. Same rule as the emitter's own
                # MetalUnsupported branch -- explicit is honoured, inference
                # falls back to the host with the reason recorded.
                if _nm in _device_explicit:
                    raise
                _device_fallbacks.append(f'{_nm}: {_le}')
                continue
            self._device_launch_args[_nm] = _tys
            # A kernel's buffer parameters are `T *`, and a list argument at
            # a call site is a MojoList -- so the kernel's own element types
            # need the pack/unpack pair, whether or not any call site in this
            # module has been reached yet. The call-site pass adds to the
            # same set, so the preamble emits whichever is larger.
            for _a in _tys:
                if _a.is_buffer:
                    self._list_marshalling_needed.add(_a.ctype[:-2])
            # (name, c_type, is_buffer) triples, plus the element-count
            # index. The wrapper generator needs to tell a buffer from a
            # scalar; emit_calls.py reads only the c_types, from
            # `_device_launch_args`, plus the count index from here, which is
            # what it needs to size a list-to-buffer marshalling.
            self._device_launch_count[_nm] = _ci
            _device_kernels_meta[_nm] = (_tys, _ci)
    self._actual_types['stmts'] = 'MojoList *'
    if self._current_filename:
        self._inline_module_qualifiers[os.path.abspath(self._current_filename)] = self.module_name
    self._toplevel_dep_init_modules: list[str] = []
    _gmi_prefold_toplevel_comptime(self, stmts)
    for _fis in stmts:
        if not isinstance(_fis, FromImportStmt):
            continue
        try:
            _imp_path, _imp_src, _imp_stmts = self._parsed_import(_fis.module)
        except Exception:
            continue
        if not _imp_stmts:
            continue
        for _fip12 in (getattr(_fis, 'name_alias_strs', None) or []):
            _iname = gimple_ctypes._fi_name(_fip12)
            _ialias = gimple_ctypes._fi_alias(_fip12)
            _isym = _ialias if _ialias else _iname
            if _isym in self._comptime_vals:
                continue   # a same-named local binding always wins
            _found = {}
            _gmi_find_comptime_one(self, _imp_stmts, _iname, _found)
            if 'v' in _found:
                self._comptime_vals[_isym] = _found['v']
    self._import_scope_stack.append({})
    _generator_fns: dict[int, FunctionDef] = {}
    _async_fns: dict[int, FunctionDef] = {}
    for n in _walk_ast(stmts):
        if isinstance(n, FunctionDef):
            if n.is_generator: _generator_fns[id(n)] = n
            if n.is_async: _async_fns[id(n)] = n
    # The node ids of every FunctionDef that is a STRUCT METHOD. The
    # free-function generator loops below iterate `_generator_fns` (built
    # from `_walk_ast`, so it necessarily includes methods) and must not
    # claim a method: a method's coroutine unit is namespaced
    # `_mojogen_<Struct>_<name>` and registered in `_generator_method_api`
    # under a `(struct, name)` key, while a free function's is
    # `_mojogen_<name>` registered in `_generator_api` under the bare name.
    # The old filter — skip a generator whose `params[0][0]` is `self`/`cls` —
    # was a proxy for "is a method" that a `@staticmethod` (whose first
    # parameter is a REAL argument) does not satisfy, so a staticmethod
    # generator was registered as a free function under its bare name and
    # its call sites (`C.gen(...)`) were never recognised as generator calls:
    # `C.gen(5)` lowered to an ordinary int64_t call and consuming the
    # "result" raised `mojo_unsupported_iter` at run time. Real:
    # `Lib/importlib/resources/readers.py`'s `@staticmethod` generator
    # `_resolve_zip_path`. Membership is the honest test, and
    # `_method_receiver_kind` (not the parameter name) then decides whether
    # the method has a receiver at all.
    _struct_method_ids: set = set()
    for _s in stmts:
        if not isinstance(_s, StructDef):
            continue
        for _m in (getattr(_s, 'methods', None) or []):
            if isinstance(_m, FunctionDef):
                _struct_method_ids.add(id(_m))
    self._all_generator_names: set = {n.name for n in _generator_fns.values()}
    self._all_async_fn_names: set[str] = {n.name for n in _async_fns.values()}

    for _s in stmts:
        if isinstance(_s, StructDef) and _s.name in _C_KEYWORDS:
            _safe = f'_kw_{_s.name}'
            self._c_kw_struct_renames[_s.name] = _safe
            _s.name = _safe
    # Explicit loop, NOT `{s.name for s in stmts if isinstance(s, StructDef)}`:
    # the self-hosted set comprehension came back EMPTY, so
    # `_struct_method_qualifier` never saw this file's OWN structs as local
    # and qualified their methods with the module prefix instead of the bare
    # name (a real stage1-vs-stage2 divergence: fire_compiler.py's own
    # `Parser___init__` emitted as `fire_compiler_Parser___init__` natively).
    # `_as_str` the name too — a boxed `s.name` would key the set by pointer.
    self._local_struct_names = set()
    for _lsn_s in stmts:
        if isinstance(_lsn_s, StructDef):
            self._local_struct_names.add(_as_str(_lsn_s.name))
    # Each StructDef's HOME module, the input to the collision test in the
    # module-qualified-identity pass further down (see `_struct_cname_by_id`
    # in GimpleGen.__init__). THIS gen_module call IS the compile of
    # `self.module_name`, so every StructDef in `stmts` is that module's own.
    # Keyed by node identity, which is what `_struct_name_owner` compares when
    # it decides "same class", so the two agree on what that means. The ROOT
    # module compiles with `module_name == ''`; it is not a peer of any
    # imported module, so it claims the bare name like any other first-wins
    # owner rather than being qualified against itself.
    for _hms in stmts:
        if isinstance(_hms, StructDef) and self.module_name:
            self._struct_home_by_id[id(_hms)] = _as_str(self.module_name)
    # Overloaded / duplicated top-level functions (same name, multiple defs)
    # can't all be emitted as distinct C symbols. Two genuinely different
    # situations hide behind that one description, with OPPOSITE correct
    # handling (BUG-2026-021):
    #
    # - GENUINE OVERLOADS — same name, DIFFERENT parameter signatures
    #   (`can_craft(t: Tuff, ...)` vs `can_craft(t: TuffBricks, ...)` in two
    #   copies of a mod family). Still dropped entirely here: the elaborator
    #   selects and instantiates the right overload per call site (slice 4),
    #   so no single C definition exists to emit.
    # - REDEFINITIONS — identical signature, e.g. test suites whose tail was
    #   accidentally pasted twice (`def main():` twice). myinterpreter.py's
    #   module dict binding means the INTERPRETER silently runs the LAST
    #   definition; stripping every copy here instead left the program with
    #   no `main` at all — entry-point synthesis fell back to an empty
    #   `_gimple_main { return 0; }` and the whole --jit run exited 0 with
    #   zero output. Keep exactly the LAST copy (interpreter semantics).
    #
    # dup_def_signature_key is the shared classifier (reflect.
    # collect_exports_src uses it too, so the reflection table advertises
    # exactly the one survivor this pass keeps). One filter at the top keeps
    # every downstream loop collision-free. No-op otherwise.
    _dup_defs: dict = {}
    for _s in stmts:
        if isinstance(_s, FunctionDef):
            _dup_defs.setdefault(_s.name, []).append(_s)
    _dup_drop_ids: set = set()
    for _dup_list in _dup_defs.values():
        if len(_dup_list) < 2:
            continue
        if len({_ggf_dup.dup_def_signature_key(_d) for _d in _dup_list}) == 1:
            _dup_drop_ids.update(id(_d) for _d in _dup_list[:-1])
        else:
            _dup_drop_ids.update(id(_d) for _d in _dup_list)
    if _dup_drop_ids:
        stmts = [s for s in stmts if id(s) not in _dup_drop_ids]
    # BUG-2026-019 seeding: THIS compile unit's own surviving top-level
    # FunctionDefs by bare name, plus the memo _local_def_pts fills lazily.
    # A same-named free function defined by several sibling modules of one
    # import closure gets its C symbol suffix AND its call-site argument
    # coercion from THIS map first (_overload_suffix/_func_csym), never from
    # the shared func_param_types[bare] slot those siblings' registration
    # passes overwrite once per module — the off-by-one-sibling wrong-struct
    # cast (`Tuff *` passed where tuff_bricks.mojo's own can_craft wanted
    # `TuffBricks *`). Resolved LAZILY (empty memo here): struct-typed
    # parameter annotations need the struct registration passes further down
    # gen_module to have run before _signature_ctypes can resolve them, and
    # the first suffix computation happens during body emission, long after.
    self._local_def_nodes = {s.name: s for s in stmts if isinstance(s, FunctionDef)}
    self._local_def_param_types: dict = {}
    self._prepare_analysis_funcs(stmts)

    def _toplev_bound_names(_tb_body):
        _names = set()
        for _tb_s in (_tb_body or []):
            if isinstance(_tb_s, FromImportStmt):
                for _fip13 in (getattr(_tb_s, 'name_alias_strs', None) or []):
                    _tb_nm = gimple_ctypes._fi_name(_fip13)
                    _tb_alias = gimple_ctypes._fi_alias(_fip13)
                    _names.add(_tb_alias if _tb_alias else _tb_nm)
            elif isinstance(_tb_s, ImportStmt):
                for _tb_mod0, _tb_alias0 in _import_targets(_tb_s):
                    _tb_mod = _as_str(_tb_mod0); _tb_alias = _as_str(_tb_alias0)
                    if _tb_alias:
                        _names.add(_tb_alias)
                    elif '.' in _tb_mod:
                        _names.add(_tb_mod[:_tb_mod.index('.')])
                    else:
                        _names.add(_tb_mod)
            elif isinstance(_tb_s, FunctionDef):
                _names.add(_tb_s.name)
        return _names

    _try_replaced: list = []
    for _s in stmts:
        if isinstance(_s, TryStmt):
            _try_names = _toplev_bound_names(_s.body)
            _handler_names: set = set()
            for _h in (_s.handlers or []):
                _handler_names |= _toplev_bound_names(_h.body)
            if _try_names and (_try_names & _handler_names):
                _try_replaced.extend(_s.body or [])
            else:
                _try_replaced.append(_s)
        else:
            _try_replaced.append(_s)
    stmts = _try_replaced

    for _tls in stmts:
        if (isinstance(_tls, AssignStmt) and isinstance(_tls.target, IdentExpr)):
            _tlv = self._eval_const(_tls.value)
            if _tlv is not None:
                self._comptime_vals.setdefault(_tls.target.name, _tlv)
    _cond_fn_counts: dict = {}
    _cond_worklist = [s for s in stmts if isinstance(s, IfStmt)]
    while _cond_worklist:
        _wi = _cond_worklist.pop()
        for _s in (_wi.then_body or []):
            if isinstance(_s, FunctionDef):
                _cond_fn_counts[_s.name] = _cond_fn_counts.get(_s.name, 0) + 1
            elif isinstance(_s, IfStmt):
                _cond_worklist.append(_s)
        for _cond, _elif_body in (getattr(_wi, 'elifs', None) or []):
            for _s in (_elif_body or []):
                if isinstance(_s, FunctionDef):
                    _cond_fn_counts[_s.name] = _cond_fn_counts.get(_s.name, 0) + 1
                elif isinstance(_s, IfStmt):
                    _cond_worklist.append(_s)
        if _wi.else_body:
            for _s in _wi.else_body:
                if isinstance(_s, FunctionDef):
                    _cond_fn_counts[_s.name] = _cond_fn_counts.get(_s.name, 0) + 1
                elif isinstance(_s, IfStmt):
                    _cond_worklist.append(_s)
    # TODO(real fix, not this approximation): the promotion below
    _cond_collisions = {n for n, c in _cond_fn_counts.items() if c > 1}
    _direct_toplevel_names = {s.name for s in stmts if isinstance(s, FunctionDef)}
    _cond_unique = {n for n, c in _cond_fn_counts.items()
                    if c == 1 and n not in _direct_toplevel_names}
    _promote_names = _cond_collisions | _cond_unique
    if _promote_names:
        _already_promoted_names: set = set()
        _replaced: list = []
        for _s in stmts:
            if not isinstance(_s, IfStmt):
                _replaced.append(_s)
                continue
            _promoted: list = []
            _seen_names: set = set()
            _stack: list = [([_s], 0)]
            while _stack:
                _frame_body, _frame_idx = _stack[-1]
                if _frame_idx >= len(_frame_body):
                    _stack.pop()
                    continue
                _frame_stmt = _frame_body[_frame_idx]
                _stack[-1] = (_frame_body, _frame_idx + 1)
                if isinstance(_frame_stmt, FunctionDef):
                    if (_frame_stmt.name in _promote_names
                            and _frame_stmt.name not in _seen_names
                            and _frame_stmt.name not in _already_promoted_names):
                        _promoted.append(_frame_stmt)
                        _seen_names.add(_frame_stmt.name)
                        _already_promoted_names.add(_frame_stmt.name)
                elif isinstance(_frame_stmt, IfStmt):
                    _resolved = False
                    _resolved_body = []
                    _cond_val = self._eval_const_bool(_frame_stmt.condition)
                    if _cond_val is True:
                        _resolved = True
                        _resolved_body = _frame_stmt.then_body or []
                    elif _cond_val is False:
                        _resolved = True
                        for _cond2, _elif_body2 in (getattr(_frame_stmt, 'elifs', None) or []):
                            _elif_val = self._eval_const_bool(_cond2)
                            if _elif_val is True:
                                _resolved_body = _elif_body2 or []
                                break
                            if _elif_val is None:
                                _resolved = False  # an unresolvable elif — fall back below
                                break
                        else:
                            _resolved_body = _frame_stmt.else_body or []
                    if _resolved:
                        _nested_body = _resolved_body
                    else:
                        _nested_body = (_frame_stmt.then_body or [])
                        for _cond2, _elif_body2 in (getattr(_frame_stmt, 'elifs', None) or []):
                            _nested_body = _nested_body + _elif_body2
                        if _frame_stmt.else_body:
                            _nested_body = _nested_body + _frame_stmt.else_body
                    _stack.append((_nested_body, 0))
            if _promoted:
                _replaced.extend(_promoted)
            else:
                _replaced.append(_s)
        stmts = _replaced

    _gsrc = ''
    if getattr(self, '_current_filename', None):
        try:
            _gsrc = open(self._current_filename).read()
        except Exception:
            _debug_note('cannot read source for generics scan', self._current_filename)
            _gsrc = ''
    if _gsrc:
        _local_generics = {
            s.name for s in stmts
            if isinstance(s, FunctionDef)
            and s.name not in self._NO_OVERLOAD_MANGLE
            and re.search(rf'\b(?:fn|def)\s+{re.escape(s.name)}\s*\[', _gsrc)
        }
        for _gn in _local_generics:
            self._imported_generics.setdefault(_gn, self._current_filename)
        if _local_generics:
            _stripped_generic_fns = [s for s in stmts
                                      if isinstance(s, FunctionDef) and s.name in _local_generics]
            stmts = [s for s in stmts
                     if not (isinstance(s, FunctionDef) and s.name in _local_generics)]
            for _sgf in _stripped_generic_fns:
                for _n in _walk_ast(_sgf.body):
                    if isinstance(_n, FunctionDef):
                        _async_fns.pop(id(_n), None)
                        _generator_fns.pop(id(_n), None)

    if _gsrc:
        for _s in stmts:
            if not isinstance(_s, StructDef):
                continue
            try:
                import elaborate as _elaborate_mod
                _struct_src = _elaborate_mod.extract_struct_source(_gsrc, _s.name) or _gsrc
            except Exception:
                _struct_src = _gsrc
            _moids_pre = self._struct_method_overload_ids(_s)
            _name_occurrence: dict = {}  # method name -> next occurrence index to consume
            for _zmi in range(len(_s.methods)):
                _m = _as_funcdef_node(_s.methods[_zmi]); _oid = _as_str(_moids_pre[_zmi]) if _zmi < len(_moids_pre) else ""
                _occ = _name_occurrence.get(_m.name, 0)
                _name_occurrence[_m.name] = _occ + 1
                if not _m.comptime_params:
                    continue
                _bp_types = _bracket_param_type_annotations(_struct_src, _m.name, occurrence=_occ)
                _func_typed = {p for p in _m.comptime_params
                               if _bp_types.get(p, '').startswith('def')}
                if not _func_typed:
                    continue
                _used = set()
                for _b in _m.body:
                    _used |= _used_idents_deep(_b)
                _threaded = [p for p in _m.comptime_params if p in _func_typed and p in _used]
                if _threaded:
                    _key = (_s.name, _m.name)
                    self._method_threaded_comptime_params.setdefault(_key, {})[_oid] = _threaded
                    self._method_comptime_param_order.setdefault(_key, {})[_oid] = list(_m.comptime_params)

    self._callable_structs = {
        s.name for s in stmts
        if isinstance(s, StructDef) and any(m.name == '__call__' for m in s.methods)
    }

    self._register_imported_structs(stmts)
    self._register_imported_generics(stmts)
    self._register_imported_generic_structs(stmts)

    # In-TU generic instantiation: materialize an imported generic as a REAL
    # definition in this translation unit rather than an `extern` beside a
    # separately-compiled CAS object. Must run HERE, and this position is
    # load-bearing in both directions:
    #
    #   AFTER `_local_struct_names` (above) so a materialized struct is NOT
    #   claimed as this module's own — `_struct_method_qualifier` then leaves
    #   its method symbols BARE, which is what every call site composes via
    #   `_struct_method_csym(name, m, '')` for a struct with no module
    #   identity, and what the elaboration TU's own `module_name=''` build
    #   emits. Qualifying here instead would be consistent within the TU but
    #   would break the agreement with a CAS object.
    #   AFTER `_local_top_level_func_names` is NOT required (a materialized
    #   function SHOULD be claimed, so its symbol gets this module's
    #   qualifier, consistently at both its definition and its call sites).
    #   BEFORE `all_struct_defs` (below) and every pass derived from it:
    #   struct registration, `func_return_types`, the struct-typedef emission
    #   and `_local_top_level_func_names` all read `stmts` ONCE, so a struct
    #   materialized after them would have a name and no layout.
    #
    # See mojo/backend_gimple/elab_intu.py for why the `.o` route cannot serve
    # the `std/iter` iterator family at all, and
    # bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md for
    # the experiment this replaces (which narrowed the feature instead of
    # fixing the cause, and so produced `conflicting types` regressions).
    stmts = list(stmts) + _elab_intu.run(self, stmts)

    for _s in stmts:
        if isinstance(_s, ComptimeVarStmt) and isinstance(_s.value, ListExpr):
            self._comptime_list_asts.setdefault(_s.target, _s.value)

    # `_as_funcdef_node`, not a bare `s`: `stmts` is a heterogeneous
    # statement list, so its self-hosted element type is opaque int64_t
    # regardless of the isinstance filter — `s.name` then went through
    # the dynamic getattr path and (being read as an int64_t rather than
    # the real char*) got stringified into this set as a decimal ADDRESS
    # instead of the real function name. `_func_qualifier`'s tier-1 check
    # (`bare_name in gen._local_top_level_func_names`) then always missed
    # for a genuinely local top-level function, falling through to tiers
    # that don't apply to a module compiling ITS OWN definition, and
    # ultimately returning '' (no qualifier) — so an imported sibling
    # module's own function definition compiled under its BARE name
    # while every caller correctly called the QUALIFIED name, an
    # undefined-symbol link failure for any --dump-full/fire.py build
    # closure with more than one module defining free functions.
    self._local_top_level_func_names = {
        _as_funcdef_node(s).name for s in stmts if isinstance(s, FunctionDef)}
    # The same set of statements, by identity rather than by name — read only
    # by `_record_home_def_return_type`, and needed because the NAME set cannot
    # answer the question that publisher asks. Every return-type inference pass
    # below walks `all_functions` (= these `stmts` + the flat transitive
    # closure), so it visits sibling modules' definitions of the same bare
    # name; "is this statement MINE" is the only question that decides which
    # module's answer belongs under a per-definition key, and only identity
    # answers it. `stmts` holds these objects for this gen's lifetime (and
    # `_all_transitive_stmts_ordered` holds them unit-wide), so the IDs cannot
    # be recycled under a later allocation — the same argument
    # `_struct_cname_by_id` / `_all_transitive_stmts_ids` rest on.
    self._local_top_level_func_stmt_ids = {
        id(s) for s in stmts if isinstance(s, FunctionDef)}

    for _s in stmts:
        if isinstance(_s, FunctionDef):
            self._global_inline_defs.add(_s.name)
        elif isinstance(_s, StructDef):
            for _m in _s.methods:
                self._global_inline_defs.add(_m.name)
                self._global_inline_defs.add(f"{_s.name}_{_m.name}")
            _al = getattr(_s, 'comptime_aliases', None)
            if _al:
                self._struct_comptime_aliases[_s.name] = _al

    self._link_import_decl_list = []
    if self.link_imports:
        self._link_import_decl_list = self._register_link_imports(stmts)

    self._link_import_decl_list = list(self._link_import_decl_list)
    self._emit_stdlib_import_externs(stmts)
    self._emit_imported_global_accessors(stmts)

    # Self-host bootstrap pre-pass: seed the shared module-global maps for
    # every sibling `.py` compiler module BEFORE any function body lowers,
    # so a `gimple_codegen.STRING_POOL_BASE`-style qualified read inside a
    # cyclically-imported dependency resolves instead of falling to a NULL
    # dynamic getattr. Gated on this compile actually being one of this
    # compiler's own `.py` files (same DIR check `_is_selfhost_file` uses,
    # computed inline here since that flag is set further below).
    if (self.do_imports or self.link_imports):
        _sg_cf = getattr(self, '_current_filename', None)
        # The FILE, not its directory: see the `_is_selfhost_file` comment
        # at the other call site below for why the dir variant was over-broad.
        if _sg_cf and _is_selfhost_source_file(_sg_cf):
            _seed_selfhost_module_globals(self)
            _seed_selfhost_struct_dict_field_types(self)
            _seed_selfhost_return_elem_types(self)

    imported_code = []
    imported_stmts = []
    # ONE inline-compile loop, TWO sources for the module set. The do_imports
    # (single-translation-unit) path inlines every module any import in this
    # closure names; link mode inlines only the ones Phase 0's
    # `_register_link_imports` could NOT satisfy from a dylib
    # (`self._link_inline_modules` — everything else is already a recorded
    # dylib + extern decl, and inlining those too would emit a second
    # definition of a symbol the dylib defines). Everything downstream of
    # that choice — the cross-module hint pre-passes below, which MUST run
    # before the first module is inlined, and the compile loop itself — is
    # shared. This used to be a second, hand-rolled copy of the loop placed
    # AFTER this block, which inlined the module correctly but skipped the
    # pre-passes entirely; the concrete consequence was that a struct defined
    # in a link-inlined sibling compiled with int64_t field defaults, so a
    # client `Class('v', 7)` call site became a real GIMPLE "non-trivial
    # conversion" hard error instead of a correctly-typed constructor call
    # (the cross-module-import report's rows 2/4/6/8; see the 2026-09-29
    # section of bugs/hard/README.md).
    if self.do_imports or self.link_imports:
        modules_to_compile = {}  # dict not set: `sorted(<set>)` self-hosted is address order -> nondeterministic module COMPILE order in --dump-full (whole modules emitted vs stubbed run to run; also feeds the OOM per comment below)
        if self.do_imports:
            _collect_import_modules(modules_to_compile, stmts)
        else:
            for _lmi in sorted(self._link_inline_modules):
                modules_to_compile[_as_str(_lmi)] = True

        # Cross-module generator scalar contracts (pre-pass, MUST run
        # before any imported module is inlined): for every bare-name call
        # whose callee is bound by a `from M import name [as alias]`
        # anywhere in THIS module, where M's own `name` is a top-level
        # GENERATOR FunctionDef, record the unanimous literal-scalar type
        # of each argument — exactly Pass 1.3d's same-module contract rule,
        # just collected early enough to be visible to the imported
        # module's temp_gen (which runs BEFORE this module's inference
        # passes and would otherwise generate the unit with int64_t
        # defaults, mis-typing every char */double argument and yielded
        # value). Literal args only: at this point none of this module's
        # local-variable inference has run, so an identifier argument has
        # no trustworthy type yet; non-unanimous or non-literal sites hint
        # nothing and keep today's behavior.
        #
        # Ungated since the block above already established that this is a
        # do_imports OR link_imports compile: these pre-passes are pure
        # functions of `self` + `stmts` (they never read
        # `modules_to_compile`), and the link-mode path inlines real modules
        # through the very same loop, so it needs them for exactly the same
        # reason.
        if self.do_imports or self.link_imports:
            _xg_alias_mod: dict = {}
            _xg_alias_orig: dict = {}
            # Bound-MODULE bindings for `<module>.<gen>(...)` attribute
            # calls: as-bound name -> the FromImportStmt module string it
            # came from (`from . import strutil` binds 'strutil' -> '.').
            _xg_module_binding: dict = {}
            for _xg_n in _walk_ast(stmts):
                if isinstance(_xg_n, FromImportStmt) and not getattr(_xg_n, 'wildcard', False):
                    for _fip15 in (getattr(_xg_n, 'name_alias_strs', None) or []):
                        _xg_name = gimple_ctypes._fi_name(_fip15)
                        _xg_alias = gimple_ctypes._fi_alias(_fip15)
                        _xg_bound = _xg_alias if _xg_alias else _xg_name
                        _xg_pm = _xg_alias_mod.get(_xg_bound)
                        if _xg_pm is None:
                            _xg_alias_mod[_xg_bound] = _xg_n.module
                            _xg_alias_orig[_xg_bound] = _xg_name
                        elif _xg_pm != _xg_n.module or _xg_alias_orig.get(_xg_bound) != _xg_name:
                            _xg_alias_mod[_xg_bound] = None  # ambiguous binding — no hints
                        # Every from-import binding COULD name a submodule;
                        # recorded unconditionally — an attribute call through
                        # a binding that actually names an ordinary symbol
                        # simply finds no registry entry and hints nothing.
                        if _xg_module_binding.get(_xg_bound, _xg_n.module) != _xg_n.module:
                            _xg_module_binding[_xg_bound] = None  # ambiguous
                        else:
                            _xg_module_binding[_xg_bound] = _xg_n.module

            def _xg_homog_elem(_xa):
                """Unanimous scalar element ctype of a collection LITERAL
                argument, or None (mixed / empty / non-scalar elements hint
                nothing)."""
                _xel = None
                for _xle in _xa.elements:
                    if isinstance(_xle, StringLiteral):
                        _let = 'char *'
                    elif isinstance(_xle, IntLiteral):
                        _let = 'int64_t'
                    elif isinstance(_xle, FloatLiteral):
                        _let = 'double'
                    else:
                        return None
                    if _let is None or (_xel is not None and _xel != _let):
                        return None
                    _xel = _let
                return _xel

            def _xg_parse_mod(_xm):
                """Parsed top-level stmts of module string `_xm`, or [] —
                via the cached _parsed_import when its resolver can see the
                module, else via the SAME candidate-path resolution
                _compile_imported_module uses (imports.resolve_source doesn't
                see every plain project sibling the do_imports pipeline
                itself compiles)."""
                try:
                    _xp = self._parsed_import(_xm)[2] or []
                except Exception:
                    _xp = []
                if _xp:
                    return _xp
                for _xc in self._module_candidate_paths(_xm):
                    if not gimple_ctypes.os.path.exists(_xc):
                        continue
                    try:
                        with open(_xc, 'r') as _xf:
                            _xs = _xf.read()
                        return (gimple_ctypes.ast_rewriter.rewrite(
                            gimple_ctypes.Parser(
                                gimple_ctypes.py_tokenize(_xs))
                            .parse_module()) or [])
                    except Exception:
                        return []
                return []

            def _xg_gen_fn(_xm, _xorig):
                """The generator FunctionDef named `_xorig` in module `_xm`'s
                own source, or None."""
                for _xs in _xg_parse_mod(_xm):
                    if isinstance(_xs, FunctionDef) and _xs.name == _xorig:
                        return _xs if _xs.is_generator else None
                return None

            def _xg_record_hint(_xkey, _xpname, _xct):
                """Record one list-elem contract into _xmod_gen_elem_hints;
                disagreeing sites hint nothing (same unanimity rule as the
                scalar param hints)."""
                if not _xct or not _xpname:
                    return
                _xe_map = self._xmod_gen_elem_hints.setdefault(_xkey, {})
                if _xe_map.get(_xpname, _xct) != _xct:
                    _xe_map[_xpname] = None
                else:
                    _xe_map[_xpname] = _xct

            # ONE-LEVEL FORWARDING CONTRACTS: a call to THIS module's own
            # function with a homogeneous collection-literal argument fixes
            # that CALLEE param's element type (`main` calling
            # `read_table(["a"])` proves read_table's `lines` holds strings).
            # Recorded per callee so an IMPORTED-GENERATOR call site one
            # level deeper (`read_table`'s body forwarding its `lines` param
            # to the foreign generator) can contribute a hint from an
            # IDENTIFIER argument — without this, a foreign generator
            # reached through any wrapper always compiled an int64_t-boxed
            # promise and was unusable via next()/for consumption. Pure AST
            # analysis over THIS module's own parsed bodies; still runs
            # strictly before any imported module is inlined.
            _xg_local_param_elems: dict = {}  # callee fn name -> {param -> elem ct}
            _xg_local_fns = {s.name: s for s in stmts if isinstance(s, FunctionDef)}
            for _xg_fd in stmts:
                if not isinstance(_xg_fd, FunctionDef):
                    continue
                for _xg_n2 in _walk_ast(_xg_fd.body):
                    if not (isinstance(_xg_n2, CallExpr) and isinstance(_xg_n2.func, IdentExpr)):
                        continue
                    _xg_callee = _xg_local_fns.get(_xg_n2.func.name)
                    if _xg_callee is None:
                        continue
                    _xg_cparams = gimple_ctypes._param_names_stripped(_xg_callee.params)
                    for _xi2, _xa2 in enumerate(_xg_n2.args):
                        if _xi2 >= len(_xg_cparams):
                            break
                        if not isinstance(_xa2, (ListExpr, TupleExpr)):
                            continue
                        _xg_record_hint_local = _xg_homog_elem(_xa2)
                        if _xg_record_hint_local is None:
                            continue
                        _xg_own_map = _xg_local_param_elems.setdefault(_xg_callee.name, {})
                        if _xg_own_map.get(_xg_cparams[_xi2], _xg_record_hint_local) != _xg_record_hint_local:
                            _xg_own_map[_xg_cparams[_xi2]] = None
                        else:
                            _xg_own_map[_xg_cparams[_xi2]] = _xg_record_hint_local

            # Per-call-site hint collection WITH enclosing-function context
            # (a flat module-level walk would descend into these bodies
            # anyway but lose which FunctionDef each call sits in). Both
            # callee shapes are collected: bare-name calls to a from-import
            # binding AND `<bound-module>.<gen>(...)` attribute calls — the
            # latter being exactly c_common/tables.py's
            # `strutil._iter_significant_lines(infile)` shape.
            _xg_calls = []
            for _xg_fd in stmts:
                if isinstance(_xg_fd, FunctionDef):
                    for _xg_n3 in _walk_ast(_xg_fd.body):
                        if isinstance(_xg_n3, CallExpr):
                            _xg_calls.append((_xg_n3, _xg_fd))
            # MODULE-level statements, with a `None` enclosing context. These
            # were simply not in the set of sites either contract below saw,
            # which is the whole of
            # the module-scope cross-module constructor case:
            # a module-scope `insp.Parameter('v', 7)` / `Parameter('v', 7)`
            # records no cross-module constructor field hint, so the imported
            # module compiled `self.v = v` at the `int64_t` default against a
            # `char *` field and the client's own `x.v` read back the boxed
            # pointer's decimal with exit 0. The function-scope spelling of
            # the same two lines was always right, which is what made this
            # look scope-dependent rather than like a missing site.
            #
            # `None` is already a value both consumers handle: the generator
            # contract's `_xg_enc_map` lookup is guarded by
            # `_xg_enclosing is not None`, and the constructor contract below
            # ignores the enclosing context entirely.
            #
            # A `StructDef` is skipped rather than descended into, because its
            # methods' bodies are already covered above with the method as the
            # enclosing context; walking it here would re-record every one of
            # them with `None`, and a container-typed field forwarded through
            # a method parameter is a case the enclosing context decides.
            for _xg_top in stmts:
                if isinstance(_xg_top, (FunctionDef, StructDef)):
                    continue
                for _xg_n3 in _walk_ast(_xg_top):
                    if isinstance(_xg_n3, CallExpr):
                        _xg_calls.append((_xg_n3, None))

            for _xg_call, _xg_enclosing in _xg_calls:
                if isinstance(_xg_call.func, gimple_ctypes.IdentExpr):
                    _xg_cname = _xg_call.func.name
                    if _xg_cname not in _xg_alias_mod:
                        continue
                    _xg_mod = _xg_alias_mod.get(_xg_cname)
                    if not _xg_mod:
                        continue
                    _xg_orig = _xg_alias_orig.get(_xg_cname)
                elif isinstance(_xg_call.func, gimple_ctypes.MemberExpr) \
                        and isinstance(_xg_call.func.obj, gimple_ctypes.IdentExpr):
                    _xg_bname = _xg_call.func.obj.name
                    _xg_bmod = _xg_module_binding.get(_xg_bname)
                    if not _xg_bmod:
                        continue
                    # The binding names a SUBMODULE FILE: its own compiled
                    # module_name is the member-path join of the FROM-IMPORT
                    # module and the BINDING ('.' + 'strutil_like' ->
                    # '.strutil_like') — exactly how find_imports synthesized
                    # that file's compilation candidate, so the temp_gen's
                    # module_name (and registry qualifier) matches. The called
                    # FUNCTION lives inside that file.
                    _xg_mod_joined = gimple_ctypes._join_import_member(
                        _xg_bmod, _xg_bname)
                    _xg_fn = _xg_gen_fn(_xg_mod_joined, _xg_call.func.member)
                    if _xg_fn is None:
                        continue
                    # Composite "<qualifier>::<name>" key — same string
                    # convention as every other _generator_home_api /
                    # hint-dict consumer (see _xmod_gen_param_hints's
                    # docstring for why not a real tuple).
                    _xg_key = (_xg_mod_joined.replace('.', '_').replace('-', '_')
                               + '::' + _xg_call.func.member)
                    _xg_pnames = gimple_ctypes._param_names_stripped(_xg_fn.params)
                    _xg_enc_map = (_xg_local_param_elems.get(_xg_enclosing.name, {})
                                   if _xg_enclosing is not None else {})
                    for _xi, _xa in enumerate(_xg_call.args):
                        if _xi >= len(_xg_pnames):
                            break
                        if isinstance(_xa, (ListExpr, TupleExpr)):
                            _xg_record_hint(_xg_key, _xg_pnames[_xi], _xg_homog_elem(_xa))
                        elif (isinstance(_xa, gimple_ctypes.IdentExpr)
                              and _xg_enc_map.get(_xa.name)):
                            _xg_record_hint(_xg_key, _xg_pnames[_xi], _xg_enc_map[_xa.name])
                    continue
                else:
                    continue
                _xg_fn = _xg_gen_fn(_xg_mod, _xg_orig)
                if _xg_fn is None:
                    continue  # ordinary callees keep Pass 1.3d's own ordering
                # Composite string key ("<qualifier>::<name>"), not a
                # genuine tuple — see _xmod_gen_param_hints's docstring
                # (gimple_codegen.py) for why a real tuple key breaks this
                # dict's self-hosted compilation.
                _xg_key = _xg_mod.replace('.', '_').replace('-', '_') + '::' + _xg_orig
                _xg_pnames = gimple_ctypes._param_names_stripped(_xg_fn.params)
                # The ENCLOSING function's own param-elem contracts (from the
                # literal-list call sites recorded above), for identifier
                # arguments forwarded straight through to the generator.
                _xg_enc_map = (_xg_local_param_elems.get(_xg_enclosing.name, {})
                               if _xg_enclosing is not None else {})
                for _xi, _xa in enumerate(_xg_call.args):
                    if _xi >= len(_xg_pnames):
                        break
                    if isinstance(_xa, (ListExpr, TupleExpr)):
                        _xg_record_hint(_xg_key, _xg_pnames[_xi], _xg_homog_elem(_xa))
                    elif (isinstance(_xa, gimple_ctypes.IdentExpr)
                          and _xg_enc_map.get(_xa.name)):
                        # An IDENTIFIER argument whose value this module's own
                        # call sites prove is a homogeneous list (the
                        # one-level forwarding contract): same elem hint,
                        # just derived transitively.
                        _xg_record_hint(_xg_key, _xg_pnames[_xi], _xg_enc_map[_xa.name])

            # Cross-module CONSTRUCTOR field-type hints (pre-pass, same
            # "must run before any imported module is inlined" constraint as
            # the generator contracts above): a scalar/container LITERAL
            # constructor argument is a PROOF of that field's C type exactly
            # like it is for a same-module call (the literal pass in the
            # `_ctor_init_params` block further down, and its `_ctxlit_*`
            # companion for a local/self.field one hop away) — but when the
            # STRUCT is defined in an imported module, neither of those runs
            # against THIS call site at all: the same-module pass only scans
            # `stmts`/`imported_stmts` of the gen that ends up compiling the
            # struct's own module, which never includes a DIFFERENT module's
            # call sites. Mirrors `_xmod_gen_param_hints` exactly, one struct
            # field deeper: parse the target module's OWN source (it has not
            # been compiled yet) to find the constructor's param names, then
            # record each literal argument's ctype under
            # "<home-qualifier>::<struct>::<FIELD>", for the defining
            # temp_gen to apply directly into its own struct_field_types.
            #
            # The key's last segment is the FIELD each constructor parameter
            # FEEDS, not the parameter's own name, and the two are not the
            # same thing: `def __init__(self, tokens): self.toks = tokens`
            # is the ordinary spelling of a class whose field is named after
            # what it holds. Keying on the parameter minted a FIELD the class
            # does not have — `struct_field_types` grows it, so the struct
            # typedef, the generated `_mojo_getattr_`/`_mojo_setattr_` and
            # the field dump all answer for an attribute that was never
            # assigned — and `getattr(obj, '<param>')` returned that
            # never-written slot instead of raising. Exit 0, no diagnostic,
            # and the value was a plausible-looking empty container because
            # that is what an unwritten container slot is initialised to.
            #
            # So the walk reads the `self.<field> = <param>` assignments, and
            # a parameter that feeds NO field records nothing: there is no
            # field for the argument's type to be evidence about, which is
            # the same reason the same-module `_ctor_init_params` pass has
            # always keyed on real field names reached through an assignment.
            # ONE parameter can feed SEVERAL fields (`self.s = s` plus
            # `self.n = s`), and every one of them is the same value, so the
            # answer is a LIST of fields per parameter and the hint is
            # recorded once per field — that is the same coverage the
            # `cross_module_ctor_param_types_every_field` case pins, and
            # keying on one field per parameter would have narrowed it.
            # Source order, no dedup: `self.n = s` twice is one hint applied
            # to the same field, which the conflict rule then sees as
            # agreement rather than as a disagreement with itself.
            def _xf_struct_init_params(_xfm, _xfs):
                """[(param_name, [field, ...])] for the struct's `__init__`."""
                for _xfstmt in _xg_parse_mod(_xfm):
                    if isinstance(_xfstmt, StructDef) and _as_str(_xfstmt.name) == _xfs:
                        for _xfmeth in _xfstmt.methods:
                            if _as_str(_xfmeth.name) == '__init__':
                                _xfnames = gimple_ctypes._param_names_stripped(_xfmeth.params)
                                _xfout = {n: [] for n in _xfnames if n != 'self'}
                                for _xfn in _walk_ast(_xfmeth.body):
                                    if not isinstance(_xfn, AssignStmt):
                                        continue
                                    _xff = _gmi_self_member(_xfn.target)
                                    if not _xff or not isinstance(_xfn.value, IdentExpr):
                                        continue
                                    _xfv = _as_str(_xfn.value.name)
                                    if _xfv in _xfout and _xff not in _xfout[_xfv]:
                                        _xfout[_xfv].append(_xff)
                                return [(n, _xfout[n]) for n in _xfout]
                        return None
                return None

            def _xf_lit_ctype(_xfa):
                if isinstance(_xfa, StringLiteral):
                    return 'char *'
                if isinstance(_xfa, FloatLiteral):
                    return 'double'
                return _gmi_container_ctype(_xfa)

            def _xf_record(_xfkey, _xfct):
                _xfprev = self._xmod_ctor_field_hints.get(_xfkey, '')
                if not _xfprev:
                    self._xmod_ctor_field_hints[_xfkey] = _xfct
                elif _xfprev != _xfct:
                    self._xmod_ctor_field_conflict[_xfkey] = True

            # Bound name -> the module's own real dotted name, for a PLAIN
            # `import mod_a [as alias]` (`mod_a.Dialog(...)`). Deliberately
            # SEPARATE from `_xg_module_binding` above: that dict's value is
            # the enclosing PACKAGE of a `from PKG import submodule` binding
            # (its consumer joins package+binding to get the submodule's own
            # dotted name via `_join_import_member`) — a plain `import`'s
            # binding already IS the target module's own real name, joining
            # it again would mangle it (`_join_import_member('mod_a',
            # 'mod_a')` is not `'mod_a'`).
            _xf_plain_import_mod: dict = {}
            for _xf_n in _walk_ast(stmts):
                if not isinstance(_xf_n, ImportStmt):
                    continue
                for _xf_im_mod, _xf_im_alias in [(_xf_n.module, _xf_n.alias)] + list(_xf_n.extra or []):
                    _xf_im_bound = _xf_im_alias if _xf_im_alias else _as_str(_xf_im_mod).split('.', 1)[0]
                    if _xf_plain_import_mod.get(_xf_im_bound, _xf_im_mod) != _xf_im_mod:
                        _xf_plain_import_mod[_xf_im_bound] = None  # ambiguous
                    else:
                        _xf_plain_import_mod[_xf_im_bound] = _as_str(_xf_im_mod)

            for _xf_call, _xf_enclosing in _xg_calls:
                _xf_mod = None
                _xf_orig = None
                if isinstance(_xf_call.func, gimple_ctypes.IdentExpr):
                    _xf_cname = _xf_call.func.name
                    if _xf_cname not in _xg_alias_mod:
                        continue
                    _xf_mod = _xg_alias_mod.get(_xf_cname)
                    _xf_orig = _xg_alias_orig.get(_xf_cname)
                elif (isinstance(_xf_call.func, gimple_ctypes.MemberExpr)
                        and isinstance(_xf_call.func.obj, gimple_ctypes.IdentExpr)):
                    _xf_plain_mod = _xf_plain_import_mod.get(_xf_call.func.obj.name)
                    if _xf_plain_mod:
                        _xf_mod = _xf_plain_mod
                        _xf_orig = _xf_call.func.member
                    else:
                        _xf_bmod = _xg_module_binding.get(_xf_call.func.obj.name)
                        if not _xf_bmod:
                            continue
                        _xf_mod = gimple_ctypes._join_import_member(_xf_bmod, _xf_call.func.obj.name)
                        _xf_orig = _xf_call.func.member
                if not _xf_mod or not _xf_orig:
                    continue
                # The module the binding NAMES is not necessarily the module
                # that DEFINES the struct: a package `__init__.py` that
                # re-exports (`from .sub import Dialog`) is a re-exporting
                # module. Both consumers below are keyed on the DEFINING
                # module — `_xf_struct_init_params` has to find a real
                # StructDef to read `__init__`'s param names from (a
                # re-exporting module has none, so it returned None and the
                # hint was silently never recorded), and `_xf_key_base`'s
                # qualifier half is matched by the defining temp_gen against
                # its OWN `module_name` when it merges the hint. Without
                # this, a `from pkg import Struct as Alias; Alias("s")` left
                # the struct's unannotated `self.f = f` field at the
                # `int64_t` default (a hard `gcc -fgimple` "non-trivial
                # conversion in 'var_decl'" when unaliased, and a `char *`
                # laundered through `int64_t` and printed as a pointer
                # decimal when aliased). Resolving to the defining module
                # first makes both spellings correct, which is what
                # `_find_symbol_home_module` exists for; a None answer (no
                # reachable module defines the name, e.g. the call is not a
                # struct constructor at all) leaves `_xf_mod` untouched.
                # TWO spellings of the defining module, for two different
                # jobs: `_xf_struct_init_params` has to OPEN the module, and
                # the hint KEY below has to spell it the way the defining
                # gen spells itself. See `_find_symbol_home_module`'s own
                # docstring for why a relative spelling resolved against
                # this importing module is the wrong file.
                _xf_home = self._find_symbol_home_module(_xf_mod, _xf_orig, 'struct')
                if _xf_home:
                    _xf_home_abs = self._find_symbol_home_module(
                        _xf_mod, _xf_orig, 'struct', want_abs=True) or _xf_home
                    _xf_mod = _xf_home
                    _xf_open = _xf_home_abs
                else:
                    _xf_open = _xf_mod
                _xf_pnames = _xf_struct_init_params(_xf_open, _xf_orig)
                if not _xf_pnames:
                    continue  # not a known struct constructor in that module
                # `lstrip('.')` on the qualifier half, matching
                # `_note_own_func_home`'s canonicalization of the module key
                # the DEFINING gen was keyed by (and so the spelling its own
                # `_note_own_func_home` call recorded) — see
                # `_find_symbol_home_module`'s docstring. Without it a module
                # reached as `.sub` produced the key `_sub::Struct::field`
                # while the defining gen compared against `sub`, so a
                # package whose `__init__.py` re-exports never saw its own
                # struct's field hints.
                _xf_key_base = _xf_mod.lstrip('.').replace('.', '_').replace('-', '_') + '::' + _xf_orig
                for _xfi, _xfa in enumerate(_xf_call.args):
                    if _xfi >= len(_xf_pnames):
                        break
                    _xfct = _xf_lit_ctype(_xfa)
                    if not _xfct:
                        continue
                    # `_xf_pnames[_xfi][1]` is the list of FIELDS this argument
                    # feeds, and empty when the parameter feeds no field at
                    # all — then the argument's type is not evidence about
                    # any field, so there is nothing to record. See
                    # `_xf_struct_init_params`'s own docstring.
                    for _xf_fld in _xf_pnames[_xfi][1]:
                        _xf_record(_xf_key_base + '::' + _xf_fld, _xfct)

        for _mc_iter in sorted(modules_to_compile):
            # FRESH `_mn` local, NOT `module_name = _as_str(module_name)`:
            # reassigning the `for x in sorted(<set of str>)` loop variable
            # doesn't win against its int64_t loop-var type under whole-
            # function unification, so `_compiled_modules.add(module_name)`
            # still lowered to `mojo_set_add_int` while the `not in` check
            # used `mojo_set_contains_str` — the set filled with int-tagged
            # entries the check never matched, so every module (os, pathlib,
            # gimple_codegen, ...) got recompiled once per importer: an
            # exponential blowup that OOM'd `MOJO_NO_SHIM=1 --dump-full`.
            _mn = _as_str(_mc_iter)
            if _mn not in self._compiled_modules:
                self._compiled_modules.add(_mn)
                code, module_stmts = self._compile_imported_module(_mn)
                if code:
                    imported_code.append(f"/* ─── Imported module: {_mn} ───────────────────── */")
                    imported_code.append(code)
                    imported_code.append('')
                    imported_stmts.extend(module_stmts)
                    for _ms in module_stmts:
                        if isinstance(_ms, FunctionDef):
                            self._global_inline_defs.add(_ms.name)
                            # `_imported_func_home` ONLY, and never
                            # `_note_own_func_home`: this observation is
                            # "module _mn DEFINES a function named _ms.name"
                            # — a whole-program fact about a SIBLING, which
                            # is exactly what tier 3 (`_imported_func_home`,
                            # setdefault/first-wins) is for. Recording it in
                            # tier 2 as well put a sibling's definition into
                            # the dict documented as "THIS exact gen_module
                            # call's own FromImportStmt scan", so two
                            # siblings each defining a common name collided
                            # it to `_AMBIGUOUS_FUNC_HOME` and `_func_qualifier`
                            # then refused EVERY reference to that name in the
                            # whole program — including a bare `open(...)` in
                            # a module that lexically imports nothing of the
                            # kind, where the reference is the builtin.
                            # Measured: `Lib/zipfile/__init__.py`, whose bare
                            # `open(...)` uses are the builtin, was refused
                            # outright because six unrelated siblings
                            # (codecs, tokenize, bz2, lzma,
                            # compression.zstd._zstdfile, tarfile) each define
                            # `open` — see
                            # bugs/COMPILE_FAIL_open_is_ambiguous_from_
                            # transitive_registrations.md.
                            self._imported_func_home.setdefault(_ms.name, _mn)
                        elif isinstance(_ms, StructDef):
                            for _m in _ms.methods:
                                self._global_inline_defs.add(_m.name)
                                self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                            self._imported_struct_home.setdefault(_ms.name, _mn)
                self._compiled_modules.add(_mn)

        if self.do_imports:
            already_in_stmts = set(id(s) for s in imported_stmts)
            for s in self._all_transitive_stmts_ordered:
                if id(s) not in already_in_stmts:
                    imported_stmts.append(s)
                    already_in_stmts.add(id(s))

    self.struct_field_types['Span'] = {
        '_data': 'char *',
        '_len': 'int64_t',
    }

    _cur_file = getattr(self, '_current_filename', None)
    # `_is_selfhost_source_file`, not `_is_selfhost_source_dir`. The question
    # is "is the file being compiled the compiler's own source?", and the file
    # is right here. The dir variant walked UP looking for a `fire_compiler.py`
    # ancestor, so it answered True for every descendant of this checkout —
    # `.tmp/`, `build/`, `tools/`, `formal/`, anything — and a user program that
    # merely sat inside the checkout was then handed the COMPILER's own
    # AST-node struct layouts below (`Scope`, `Token`, `Parser`, ...). That
    # was a 355-line difference in the generated C for a program with no AST
    # in it at all, changing only because of where the file was written. See
    # CODEGEN_selfhost_source_dir_claims_any_file_under_the_checkout.
    _is_selfhost_file = _is_selfhost_source_file(_cur_file)
    if _is_selfhost_file:
        self.struct_field_types['Scope'] = {
            'parent': 'Scope *',
            'vars': 'MojoDict *',
        }
        self.struct_field_types['Token'] = {
            'kind':  'char *',
            'value': 'char *',
            'line':  'int64_t',
            'col':   'int64_t',
        }
        self.struct_field_types['ReturnValue'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['BreakException'] = {}
        self.struct_field_types['ContinueException'] = {}
        self.struct_field_types['MojoFunction'] = {
            'name': 'char *',
            'params': 'MojoList *',
            'body': 'MojoList *',
            'closure_scope': 'Scope *',
            'comptime_params': 'MojoList *',
            '_pd': 'MojoList *',
            'is_generator': '_Bool',
            'is_async': '_Bool',
        }
        self.struct_field_types['_MojoSortFn'] = {
            '_impl': 'int64_t',
            '_interpreter': 'Interpreter *',
        }
        self.struct_field_types['_MojoSortPartial'] = {
            '_impl': 'int64_t',
            '_cmp_fn': 'int64_t',
        }
        self.struct_field_types['_ComplexFloat'] = {
            'bits': 'int64_t',
        }
        self.struct_field_types['_MojoComplex'] = {
            '_r': 'double',
            '_i': 'double',
        }
        self.struct_field_types['_AutoStubValue'] = {}
        self.struct_field_types['_AutoStubNamespace'] = {}
        self.struct_field_types['_AutoStubCheckNamespace'] = {}
        self.struct_field_types['_MojoBoundComptimeFunction'] = {
            'func': 'MojoFunction *',
            'comptime_bindings': 'MojoDict *',
        }
        self.struct_field_types['MojoClass'] = {
            'name': 'char *',
            'fields': 'MojoList *',
            'methods': 'MojoDict *',
            'interpreter': 'Interpreter *',
            'bases': 'MojoList *',
            'comptime_aliases': 'MojoDict *',
            'static_methods': 'MojoSet *',
            # `class_methods` is the @classmethod set, the mirror of
            # `static_methods` above. Read by myinterpreter's
            # `MojoClass.__getattr__` and `_eval_member_of` to decide that a
            # method's receiver is the CLASS; a hardcoded layout entry is
            # required because the self-hosted compiler has no other way to
            # know this struct's field types.
            'class_methods': 'MojoSet *',
            'def_scope': 'Scope *',
        }
        self.struct_field_types['MojoInstance'] = {
            '_mojo_class': 'MojoClass *',
        }
        self.struct_field_types['BoundMethod'] = {
            'bound_func': 'MojoFunction *',
            'instance': 'MojoInstance *',
            'interpreter': 'Interpreter *',
        }
        # The @classmethod counterpart (myinterpreter.py's BoundClassMethod).
        # A separate struct, not a second field kind on BoundMethod: the
        # receiver here is a `MojoClass *` where that one's is a
        # `MojoInstance *`, and every struct field gets exactly ONE C type.
        self.struct_field_types['BoundClassMethod'] = {
            'bound_func': 'MojoFunction *',
            'cls': 'MojoClass *',
            'interpreter': 'Interpreter *',
        }
        self.struct_field_types['MojoOverloadSet'] = {
            'name': 'char *',
            'candidates': 'MojoList *',
        }
        self.struct_field_types['Interpreter'] = {
            'scope': 'Scope *',
            'filename': 'char *',
            'argv': 'MojoList *',
            '_mojo_module_cache': 'MojoDict *',
            '_func_specs': 'MojoDict *',
            '_raised_mojo_value': 'int64_t',
            # NOT `_INT_TYPE_NAMES` / `_FLOAT_TYPE_NAMES`: both are CLASS-level
            # constants (`Interpreter._INT_TYPE_NAMES = {...}`,
            # myinterpreter.py), read as `self._INT_TYPE_NAMES`. Listing them
            # here made those reads hit a never-initialized struct field
            # instead of their `_classattr_Interpreter__*` globals — the same
            # `Parser._CONV_KWS` bug fixed alongside this.
            '_gen_tls': 'void *',
        }
        # Interpreter is DEFINED in myinterpreter.py — same reasoning
        # as Parser above: register in _imported_struct_home so
        # _struct_method_qualifier returns 'myinterpreter' for
        # Interpreter methods at call sites that hardcode the layout.
        self._imported_struct_home['Interpreter'] = 'myinterpreter'
        self.struct_field_types['Parser'] = {
            '_tok': 'MojoList *',
            '_pos': 'int64_t',
            '_filename': 'char *',
            '_pending_decs': 'MojoList *',
            '_known_traits': 'MojoSet *',
            # NOT `_CONV_KWS`: that is a CLASS-level constant
            # (`Parser._CONV_KWS = {...}`, fire_compiler.py), not an instance
            # field. Listing it here made `self._CONV_KWS` read this
            # never-initialized struct field instead of its
            # `_classattr_Parser___CONV_KWS` global — `_lower_MemberExpr`
            # returns the struct-field branch before its class-attr branch —
            # so `_peek().value in self._CONV_KWS` tested against NULL and
            # the self-hosted parser stopped recognizing the convention
            # keywords: `for ref handle in ...` failed with "Expected KW got
            # NAME('handle')" and 38 stdlib files --dump'd to nothing while
            # the python3 shim accepted them. `_known_traits` above IS a real
            # instance field (`self._known_traits = set(...)`), so it stays.
        }
        # Parser is DEFINED in fire_compiler.py, so its methods are
        # mangled with the fire_compiler qualifier (e.g.
        # fire_compiler_Parser___init__). Register it in
        # _imported_struct_home so _struct_method_qualifier returns
        # 'fire_compiler' for Parser methods at call sites in modules
        # that hardcode the struct layout above but don't directly
        # `from fire_compiler import Parser` — without this, those call
        # sites emit bare Parser___init__ while the definition is
        # fire_compiler_Parser___init__, producing undefined-symbol link
        # errors. See _struct_method_qualifier's three-tier lookup.
        self._imported_struct_home['Parser'] = 'fire_compiler'

        self.func_param_types['Scope_define'] = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope_get']    = ['Scope *', 'char *']
        self.func_param_types['Scope_set']    = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope___init__'] = ['Scope *', 'Scope *']
        # Runtime helpers whose real C signature (fire_runtime.h) takes
        # int64_t-boxed pointers. `_KNOWN_SIGS` carries these for the
        # Python build but is an EMPTY dict once mojoc runs its own
        # codegen (the class-attr emitter only populates str->str dict
        # literals, not this str->tuple one), so `_emit_call` fell back to
        # whatever the call site passed (char *) and skipped the boxing —
        # a `-Wint-conversion` warning and a byte-parity divergence.
        self.func_param_types['_char_replace_impl'] = ['int64_t', 'int64_t', 'int64_t']
        self._selfhost_locked_param_types.update((
            'Scope_define', 'Scope_get', 'Scope_set', 'Scope___init__',
            '_char_replace_impl',
        ))
        # The hand-written `**kwargs`-slot rows for self-host callables the
        # derived registration pass below cannot reach (it is `isinstance(s,
        # FunctionDef)` at MODULE level, so a struct METHOD never reaches it).
        # One table, in `gimple_codegen` beside `_SELFHOST_SIGS`, so
        # `test_gimple.py` checks it against the real `inspect` signature the
        # way it checks those: it read 3 against an older
        # `MojoFunction.__call__(self, interpreter, *args, **kwargs)` and the
        # method is now `(self, *args, **kwargs)`, so `**kwargs` is at index
        # 2. A stale index is not an imprecision —
        # `_lower_struct_method_call`'s vararg merge keeps
        # `kw_i - (2 if has_vararg else 1)` leading positionals as "fixed"
        # arguments, so 3 made it keep `f(self.interpreter, ...)`'s FIRST
        # positional and pack only the rest, and the call went out with one
        # argument too many against a 3-parameter definition:
        #
        #     myinterpreter_MojoFunction___call__ (f, _t29, _t30, kwargs);
        #     too many arguments to function; expected 3, have 4
        #
        # Two of those, one per `f(self.interpreter, self.instance, *args,
        # **kwargs)` call site (`BoundMethod.__call__` and
        # `BoundClassMethod.__call__`), the `**kwargs` materialisation passed
        # POSITIONALLY as well as in its own slot.
        # BARE names from the module-level `from gimple_codegen import`
        # above, NOT `gimple_codegen._SELFHOST_KWARGS_SLOTS`. A qualified
        # module-attribute read of a module-level CONSTANT does not survive
        # the self-hosted compiled path: `_lower_MemberExpr` deliberately
        # lowers `gimple_ctypes.X` as a bare `X` ("the qualifier is a
        # Python-import artifact"), so the read lands on a name this module
        # never declares. Every other `gimple_codegen.` read in this file is
        # a FUNCTION call (`_selfhost_syms()`), which lowers by name and so
        # was never affected; a bare `from`-import is the spelling this
        # file's other gimple_codegen constants already use (`_EXPR_DISPATCH`,
        # `_TYPE_MAP`, `_SELFHOST_DIR`).
        for _kwrow, _kwidx in _SELFHOST_KWARGS_SLOTS.items():
            self._func_kwargs_slot[_kwrow] = _kwidx
            self._func_kwargs_has_vararg[_kwrow] = (
                _SELFHOST_KWARGS_HAS_VARARG[_kwrow])

        self.struct_field_types['CallExpr'] = {
            'func': 'int64_t',
            'args': 'MojoList *',
            'kwargs': 'MojoList *',
        }
        self.struct_field_types['BinaryOp'] = {
            'op': 'char *',
            'left': 'int64_t',
            'right': 'int64_t',
        }
        self.struct_field_types['CompareChain'] = {
            'operands': 'MojoList *',
            'ops': 'MojoList *',
        }
        self.struct_field_types['UnaryOp'] = {
            'op': 'char *',
            'operand': 'int64_t',
        }
        self.struct_field_types['TernaryExpr'] = {
            'condition': 'int64_t',
            'then_val': 'int64_t',
            'else_val': 'int64_t',
        }
        self.struct_field_types['MemberExpr'] = {
            'obj': 'int64_t',
            'member': 'char *',
        }
        self.struct_boxed_fields['CallExpr'] = {'func'}
        self.struct_boxed_fields['BinaryOp'] = {'left', 'right'}
        self.struct_boxed_fields['UnaryOp'] = {'operand'}
        self.struct_boxed_fields['TernaryExpr'] = {'condition', 'then_val', 'else_val'}
        self.struct_boxed_fields['MemberExpr'] = {'obj'}
    self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}
    self.struct_boxed_fields['WalrusExpr'] = {'value'}
    self.struct_boxed_fields['YieldExpr'] = {'value'}
    self.struct_boxed_fields['YieldFromExpr'] = {'value'}
    self.struct_boxed_fields['AwaitExpr'] = {'value'}

    self.struct_field_types['IfStmt'] = {
        'condition': 'int64_t',
        'then_body': 'MojoList *',
        'elifs': 'MojoList *',
        'else_body': 'MojoList *',
    }
    self.struct_field_types['WhileStmt'] = {
        'condition': 'int64_t',
        'body': 'MojoList *',
        'else_body': 'MojoList *',
    }
    self.struct_field_types['ForStmt'] = {
        'target': 'int64_t',
        'iterable': 'int64_t',
        'body': 'MojoList *',
        'else_body': 'MojoList *',
        'is_async': '_Bool',
    }
    self.struct_field_types['FunctionDef'] = {
        'name': 'char *',
        'params': 'MojoList *',
        'return_type': 'int64_t',
        'body': 'MojoList *',
        'decorators': 'MojoList *',
        'param_convs': 'MojoDict *',
        'param_has_default': 'MojoDict *',
        'param_defaults': 'MojoDict *',
        'kwonly': 'MojoList *',
        'comptime_params': 'MojoList *',
        'is_generator': '_Bool',
        'yield_bearing_node_ids': 'int64_t',
        'is_async': '_Bool',
        # The explicit capture list and the flag that says one was written.
        # Both are needed: `captures` alone cannot distinguish `{}` from no
        # list. `has_capture_list` is `_Bool` for the same reason `is_async`
        # is — it is a real Python bool on the dataclass.
        'captures': 'MojoList *',
        'has_capture_list': '_Bool',
    }
    self.struct_field_types['ExprStmt'] = {
        'value': 'int64_t',
    }
    self.struct_field_types['AssignStmt'] = {
        'target': 'int64_t',
        'value': 'int64_t',
        'line': 'int64_t',
        'col': 'int64_t',
        'type_ann': 'int64_t',
    }
    self.struct_field_types['AugAssignStmt'] = {
        'target': 'int64_t',
        'op': 'char *',
        'value': 'int64_t',
    }
    self.struct_field_types['ReturnStmt'] = {
        'value': 'int64_t',
    }
    self.struct_field_types['VarDecl'] = {
        'name': 'char *',
        'type_ann': 'int64_t',
        'value': 'int64_t',
    }
    self.struct_field_types['MultiAssignStmt'] = {
        'targets': 'MojoList *',
        'value': 'int64_t',
    }
    self.struct_field_types['BreakStmt'] = {}
    self.struct_field_types['ContinueStmt'] = {}
    self.struct_field_types['PassStmt'] = {}
    self.struct_field_types['AssertStmt'] = {
        'value': 'int64_t',
        'msg': 'int64_t',
        'is_comptime': '_Bool',
    }
    self.struct_field_types['RaiseStmt'] = {
        'value': 'int64_t',
    }
    self.struct_field_types['TryStmt'] = {
        'body': 'MojoList *',
        'handlers': 'MojoList *',
        'else_body': 'MojoList *',
        'finally_body': 'MojoList *',
    }
    self.struct_field_types['WithStmt'] = {
        'items': 'MojoList *',
        'body': 'MojoList *',
        'is_async': '_Bool',
    }
    self.struct_field_types['ImportStmt'] = {
        'module': 'char *',
        'alias': 'char *',
        'extra': 'MojoList *',
    }
    self.struct_field_types['FromImportStmt'] = {
        'module': 'char *',
        'names': 'MojoList *',
        'wildcard': '_Bool',
    }
    self.struct_field_types['ComptimeIfStmt'] = {
        'condition': 'int64_t',
        'then_body': 'MojoList *',
        'elifs': 'MojoList *',
        'else_body': 'MojoList *',
    }
    self.struct_field_types['ComptimeForStmt'] = {
        'target': 'char *',
        'iterable': 'int64_t',
        'body': 'MojoList *',
    }
    self.struct_field_types['ComptimeVarStmt'] = {
        'target': 'char *',
        'value': 'int64_t',
    }
    self.struct_field_types['GlobalStmt'] = {
        'names': 'MojoList *',
    }
    self.struct_field_types['DelStmt'] = {
        'targets': 'MojoList *',
    }
    self.struct_field_types['MatchStmt'] = {
        'subject': 'int64_t',
        'cases': 'MojoList *',
    }
    # `MatchCase` must be registered (and `MatchStmt.cases`'s element type
    # seeded below) or `for i, match_case in enumerate(node.cases):` binds
    # `match_case` as an opaque int64_t, leaving `match_case.patterns` an
    # untyped dynamic-getattr result. `_gen_stmt_MatchStmt`'s wildcard
    # detection then can't statically resolve the pattern list at all, and
    # the self-hosted binary emits `case _:` as `case 0:` — a real
    # native-vs-python3 `--dump match_stmt.mojo` divergence.
    self.struct_field_types['MatchCase'] = {
        'patterns': 'MojoList *',
        'body': 'MojoList *',
        'guard': 'int64_t',
        'line': 'int64_t',
        'col': 'int64_t',
    }
    self.struct_field_types['LambdaExpr'] = {
        'params': 'MojoList *',
        'body': 'int64_t',
    }
    self.struct_field_types['SubscriptExpr'] = {
        'obj': 'int64_t',
        'index': 'int64_t',
        'attrs': 'MojoList *',
    }
    self.struct_field_types['SliceExpr'] = {
        'obj': 'int64_t',
        'start': 'int64_t',
        'stop': 'int64_t',
        'step': 'int64_t',
    }
    self.struct_field_types['Comprehension'] = {
        'kind': 'char *',
        'element': 'int64_t',
        'key': 'int64_t',
        'generators': 'MojoList *',
    }
    # `Generator` (fire_compiler.py) — the comprehension's per-`for`-clause
    # node (`target`/`iterable`/`conditions`), and the struct
    # `gimple_gen_calls._lower_ctor_from_iterable` synthesizes for
    # `list(x)`/`set(x)`. This table is the self-hosted backend's reliable
    # field-layout source for AST nodes; without an entry here the module-
    # qualified constructor `gimple_ctypes.Generator(...)` found no
    # registered layout, fell through to the opaque 0 placeholder, and the
    # synthesized comprehension's `generators` list ended up holding a NULL
    # — `_lower_comprehension`'s `gen0.iterable` then raised
    # `AttributeError: iterable` and the whole module was dropped (5
    # modules lost from a self-hosted fire.py --dump-full: gimple_codegen,
    # gimple_solvers, imports, jit.arm64, myinterpreter). `Comprehension`
    # directly above was the only node of the pair that was listed.
    self.struct_field_types['Generator'] = {
        'target': 'char *',
        'iterable': 'int64_t',
        'conditions': 'MojoList *',
        'line': 'int64_t',
        'col': 'int64_t',
    }
    self.struct_field_types['IdentExpr'] = {
        'name': 'char *',
    }
    self.struct_field_types['IntLiteral'] = {
        'value': 'int64_t', 'line': 'int64_t', 'col': 'int64_t', 'raw': 'char *',
    }
    self.struct_field_types['FloatLiteral'] = {
        'value': 'double',
    }
    self.struct_field_types['BoolLiteral'] = {
        'value': '_Bool',
    }
    self.struct_field_types['EllipsisLiteral'] = {}
    self.struct_field_types['NoneLiteral'] = {}
    self.struct_field_types['StringLiteral'] = {
        'value': 'char *',
        # `line`/`col` must stay in the seed AHEAD of `is_bytes`: the
        # reflection repr iterates `struct_field_types` in insertion order
        # and the later self-host augmentation appends any missing dataclass
        # fields, so the seed has to remain a PREFIX of
        # `StringLiteral(value, line, col, is_bytes, is_raw)` or the native
        # repr emits `value, is_bytes, line, col` and every file with a
        # string literal diverges from the reference (64 `.ast` diffs).
        # `is_raw` is appended at the END for the same reason: it was added
        # after `is_bytes` (it records an `r` prefix, so
        # `_strip_string_prefix_and_quotes` no longer carries it), and putting
        # it anywhere else would reorder the fields the prefix rule protects.
        'line': 'int64_t',
        'col': 'int64_t',
        'is_bytes': '_Bool',
        'is_raw': '_Bool',
    }
    self.struct_field_types['TstringLiteral'] = {
        'value': 'char *',
    }
    self.struct_field_types['ImagLiteral'] = {
        'value': 'double',
    }
    self.struct_field_types['TupleLiteral'] = {
        'elements': 'MojoList *',
    }
    self.struct_field_types['TupleExpr'] = {
        'elements': 'MojoList *',
    }
    self.struct_field_types['ListLiteral'] = {
        'elements': 'MojoList *',
    }
    self.struct_field_types['ListExpr'] = {
        'elements': 'MojoList *',
    }
    self.struct_field_types['SetLiteral'] = {
        'elements': 'MojoList *',
    }
    self.struct_field_types['SetExpr'] = {
        'elements': 'MojoList *',
    }
    self.struct_field_types['DictLiteral'] = {
        'pairs': 'MojoList *',
    }
    self.struct_field_types['DictExpr'] = {
        'pairs': 'MojoList *',
    }
    self.struct_field_types['WalrusExpr'] = {
        'name': 'char *', 'value': 'int64_t',
    }
    self.struct_field_types['YieldExpr'] = {
        'value': 'int64_t',
    }
    self.struct_field_types['YieldFromExpr'] = {
        'value': 'int64_t',
    }
    self.struct_field_types['AwaitExpr'] = {
        'value': 'int64_t',
    }
    self.struct_field_types['StructDef'] = {
        'name': 'char *', 'fields': 'MojoList *', 'methods': 'MojoList *',
        'decorators': 'MojoList *', 'comptime_aliases': 'MojoDict *',
        'bases': 'MojoList *', 'line': 'int64_t', 'col': 'int64_t',
        '_fieldwise_ctor_synthesized': '_Bool',
    }
    self.struct_field_types['TraitDef'] = {
        'name': 'char *', 'methods': 'MojoList *', 'decorators': 'MojoList *',
    }
    self.struct_boxed_fields['IfStmt'] = {'condition'}
    self.struct_boxed_fields['WhileStmt'] = {'condition'}
    self.struct_boxed_fields['ForStmt'] = {'target', 'iterable'}
    self.struct_boxed_fields['FunctionDef'] = {'return_type', 'yield_bearing_node_ids'}
    self.struct_boxed_fields['ExprStmt'] = {'value'}
    self.struct_boxed_fields['AssignStmt'] = {'target', 'value', 'type_ann'}
    self.struct_boxed_fields['AugAssignStmt'] = {'target', 'value'}
    self.struct_boxed_fields['ReturnStmt'] = {'value'}
    self.struct_boxed_fields['VarDecl'] = {'type_ann', 'value'}
    self.struct_boxed_fields['MultiAssignStmt'] = {'value'}
    self.struct_boxed_fields['AssertStmt'] = {'value', 'msg'}
    self.struct_boxed_fields['RaiseStmt'] = {'value'}
    self.struct_boxed_fields['ComptimeIfStmt'] = {'condition'}
    self.struct_boxed_fields['ComptimeForStmt'] = {'iterable'}
    self.struct_boxed_fields['ComptimeVarStmt'] = {'value'}
    self.struct_boxed_fields['MatchStmt'] = {'subject'}
    self.struct_boxed_fields['LambdaExpr'] = {'body'}
    self.struct_boxed_fields['SliceExpr'] = {'obj', 'start', 'stop', 'step'}
    self.struct_boxed_fields['Comprehension'] = {'element', 'key'}
    # `Generator` (fire_compiler.py) — the comprehension's per-`for`-clause
    # node. Its `iterable` is `object` (any AST node), so it must be marked
    # boxed like Comprehension's `element`/`key`: the generated
    # `_mojo_repr_<Struct>` then routes it through `_mojo_generic_elem_repr`
    # (runtime type-tag dispatch) instead of `mojo_repr_int`. Without this,
    # `repr(ast)` printed the raw boxed pointer as a decimal — the exact
    # stage1-vs-stage2 `fire_compiler.ast` / `fire.ast` / `module_loader.ast`
    # / `myinterpreter.ast` mismatches `make bootstrap`'s verify step reports
    # (`Generator(target='c', iterable=47038764864, ...)` instead of the
    # nested `IdentExpr(...)` repr).
    self.struct_boxed_fields['Generator'] = {'iterable'}
    self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}

    # ELEMENT types for the homogeneous list fields of the AST tables above.
    # `struct_field_types` records only that a field IS a `MojoList *`; with
    # no element type every `for m in struct_def.methods:` binds its loop
    # variable as an opaque int64_t, so `m.name` goes through the boxed
    # dynamic-getattr path and `m.params` cannot be typed at all. These
    # mirror the `list[FunctionDef]` / `list[tuple[str, str]]` annotations on
    # the corresponding dataclasses in fire_compiler.py (the single source of
    # truth) — the same declarative seed the field-type tables above already
    # are, kept here because those tables are what a compile of an arbitrary
    # user file has available. Only genuinely HOMOGENEOUS fields are listed:
    # `StructDef.fields` (VarDecl | AssignStmt) and `FunctionDef.body` (any
    # statement) have no single element type and are deliberately absent.
    self._field_elem_types.setdefault('StructDef', {})['methods'] = 'FunctionDef *'
    self._field_elem_types.setdefault('TraitDef', {})['methods'] = 'FunctionDef *'
    # `MatchStmt.cases` is `list[MatchCase]` (see fire_compiler.py) — without
    # this the `enumerate(node.cases)` loop variable is an opaque int64_t and
    # `match_case.patterns` can't be typed (see the MatchCase table entry
    # above for the concrete `case _:` divergence this caused).
    self._field_elem_types.setdefault('MatchStmt', {})['cases'] = 'MatchCase *'
    # `params` is a list of (name, annotation) STRING pairs — the element is
    # itself a 2-slot tuple, so the slot type goes in the nested table.
    self._field_nested_elem_types.setdefault('FunctionDef', {})['params'] = 'char *'
    self._field_nested_elem_types.setdefault('LambdaExpr', {})['params'] = 'char *'

    self.struct_nullable_container_fields['SubscriptExpr'] = {'attrs'}
    self.struct_nullable_container_fields['IfStmt'] = {'else_body'}
    self.struct_nullable_container_fields['WhileStmt'] = {'else_body'}
    self.struct_nullable_container_fields['ForStmt'] = {'else_body'}
    self.struct_nullable_container_fields['TryStmt'] = {'else_body', 'finally_body'}
    self.struct_nullable_container_fields['ComptimeIfStmt'] = {'else_body'}
    self.struct_nullable_container_fields['ImportStmt'] = {'extra'}

    # Self-hosting bootstrap: register `class GimpleGen` (parsed once by
    # gimple_codegen._selfhost_register_gimplegen, shared into every nested
    # temp_gen) for the backend `.py` files that reference it but don't
    # emit it. Field layout goes straight into the shared struct_field_types;
    # the StructDef rides `_imported_typedef_structs` so passes 5-10 build
    # its method param/return types, `_struct_method_signatures`, defaults
    # and externs — exactly like `_materialize_imported_struct`. Skipped
    # where `class GimpleGen` arrives naturally (its own compile, the root).
    _gg_stmts = self._selfhost_gimplegen_stmts   # direct field — see __init__ (getattr erased it)
    _gg_sigs = self._selfhost_gimplegen_sigs
    _gg_have_infile = False
    for _ggs in (stmts + imported_stmts):
        if isinstance(_ggs, StructDef) and _as_str(_as_structdef_node(_ggs).name) == 'GimpleGen':
            _gg_have_infile = True
            break
    # Gated on a DEDICATED flag (`_gg_synth_struct_registered`), not on
    # `'GimpleGen' not in self.struct_field_types` — that dict key now
    # gets seeded deterministically and unconditionally, once, by
    # `gimple_codegen._selfhost_register_gimplegen` (before ANY temp_gen
    # processes ANY file), specifically so the field SET converges
    # regardless of self-hosted-vs-shim temp_gen processing order (see
    # that function's own docstring and bugs/CODEGEN_noshim_dumpfull_
    # preexisting_divergence.md's Finding 4 Bug C). Using the dict key as
    # this gate too — its ORIGINAL role — would make this whole block
    # (which does far more than seed fields: it registers the SYNTHETIC
    # StructDef into `_imported_typedef_structs`, required for method
    # extern emission) permanently skip for every temp_gen once the key
    # exists, even ones that still need it because they never encounter
    # the real `class GimpleGen` in their own `stmts + imported_stmts` —
    # confirmed via `make check-selfhost` regressing to hundreds of
    # "implicit declaration of function 'GimpleGen__*'" errors.
    if (_gg_stmts is not None and _is_selfhost_file
            and not getattr(self, '_gg_synth_struct_registered', False)
            and not _gg_have_infile):
        self._gg_synth_struct_registered = True
        self._imported_struct_names.add('GimpleGen')
        self._struct_name_owner.setdefault('GimpleGen', _gg_stmts)
        self._imported_typedef_structs.append(_gg_stmts)
    # Apply + LOCK the frozen GimpleGen signature table BEFORE any of the
    # method-registration / Pass-2b-bis / forward-decl passes run, in EVERY
    # temp_gen (including the root, where `class GimpleGen` is in-file) — so
    # every `GimpleGen_*` symbol's params/return/defaults are identical
    # across the whole closure by construction (`_infer_param_types` is not
    # pure). Also union in the extracted-helper field writes.
    if _gg_sigs and 'GimpleGen' in self.struct_field_types:
        _gg_ft = self.struct_field_types['GimpleGen']
        # `for _f, _c in (...).items():` — a 2-tuple unpack IN THE FOR-
        # CLAUSE — is the SAME established tuple-boxing bug pattern as
        # gimple_gen_exprs.py's `[at for (at, _) in arg_pairs]` fix
        # (4d922cc): this exact site, re-merging the SAME
        # `_selfhost_gimplegen_extra_fields` dict into `_gg_ft` a second
        # time, is why fixing only the earlier copy-construction
        # (e8598e1) didn't stop the erased `int64_t <address>;` struct-
        # field-name corruption — this later merge re-introduced it.
        # Keep `.items()` itself (it's the only dict-vs-list signal for
        # this `getattr(...)`-sourced value — see _render_struct_typedef_
        # body's reverted attempt at dropping it, a42ee7e), just don't
        # destructure the pair in the for-clause.
        for _fc_pair in (self._selfhost_gimplegen_extra_fields).items():
            _f = _as_str(_fc_pair[0])
            _c = _as_str(_fc_pair[1])
            _cur = _gg_ft.get(_f)
            if _cur is None or (_cur in ('int', 'int64_t', '_Bool') and _c.endswith(' *')):
                _gg_ft[_f] = _c
        for _mangled, (_rc, _pcs, _dflts) in _gg_sigs.items():
            self.func_param_types[_mangled] = list(_pcs)
            self.func_return_types[_mangled] = _rc
            self._mangled_signature_ctypes[_mangled] = list(_pcs)
            if _dflts:
                self._func_param_defaults[_mangled] = list(_dflts)
            self._selfhost_locked_param_types.add(_mangled)
        # Recover the `_annotation_dict_val_type` seeding of
        # `_field_dict_val_types` / `_field_dict_nested_val_types` that
        # `_seed_struct_field_types` would have done had `class GimpleGen`'s
        # StructDef reached its annotation loop — parsed from the real
        # declared field annotations (see _selfhost_gimplegen_dict_val_types).
        _gg_dvts = self._selfhost_gimplegen_dict_vts
        for _f, (_outer_vt, _nested_vt, _raw_ann) in _gg_dvts.items():
            if _outer_vt and _outer_vt != 'int64_t':
                self._field_dict_val_types.setdefault('GimpleGen', {}).setdefault(_f, _outer_vt)
            if _nested_vt and _nested_vt != 'int64_t':
                self._field_dict_nested_val_types.setdefault('GimpleGen', {}).setdefault(_f, _nested_vt)
            if _raw_ann:
                self._field_annotations.setdefault('GimpleGen.' + _f, _raw_ann)

    # The synthetic `class GimpleGen` rides `_imported_typedef_structs`, which
    # only wires method externs + typedef layout — it never reaches the
    # `all_struct_defs` class-attr / alloc-seed / field loops below. `_class_
    # attrs` is per-instance (not shared), so replicate the class-body-
    # assignment registration in EVERY temp_gen where the synthetic struct is
    # in play, so whichever TU ends up emitting `_alloc_GimpleGen` /
    # `_mojo_classattr_init` still seeds `_p->_X = _classattr_GimpleGen__X`
    # and builds the membership tables (`_NO_OVERLOAD_MANGLE` etc). Skipped
    # where `class GimpleGen` arrives naturally (loop 1274 handles it).
    if (_gg_stmts is not None and 'GimpleGen' in self.struct_field_types
            and not any(isinstance(s, StructDef) and s.name == 'GimpleGen'
                        for s in (stmts + imported_stmts))):
        _gg_ft1 = self.struct_field_types['GimpleGen']
        # Mirror the proven-working pattern at loop 1274 (`self._class_attrs
        # [s.name] = {}` then subscript-write through the fresh dict) rather
        # than `.setdefault('GimpleGen', {})` + a double-subscript write in
        # one expression (`self._class_attrs['GimpleGen'][_ca_n] = _ca_m`) —
        # the latter crashed the self-hosted compiled backend with a SIGBUS
        # inside `mojo_list_set_int`, confirmed via lldb: unlike loop 1274's
        # shape, this one's inner dict never got a type-inferred `MojoDict *`
        # container and the subscript write lowered as a LIST-index store
        # instead. Only reachable once GimpleGen registration stopped being
        # limited to fire.py/mojo_main.py (see _run_pipeline's own registry
        # gate) — `--dump-full fire_compiler.py` is the first entry point
        # to exercise this branch at all.
        if 'GimpleGen' not in self._class_attrs:
            self._class_attrs['GimpleGen'] = {}
        _gg_ca_map = self._class_attrs['GimpleGen']
        for _caf in _gg_stmts.fields:
            if not (isinstance(_caf, AssignStmt) and isinstance(_caf.target, IdentExpr)):
                continue
            _ca_n = _caf.target.name
            _ca_m = f"_classattr_GimpleGen__{_ca_n}"
            _gg_ca_map[_ca_n] = _ca_m
            _ca_ct = _class_attr_ctype(_caf.value)
            if _ca_ct is not None:
                self._global_var_types[_ca_m] = _ca_ct
                _ca_cur = _gg_ft1.get(_ca_n)
                if _ca_cur is None or _ca_cur in ('int', 'int64_t'):
                    _gg_ft1[_ca_n] = _ca_ct
            elif isinstance(_caf.value, StringLiteral):
                self._global_var_types[_ca_m] = 'char *'
                _gg_ft1.setdefault(_ca_n, 'char *')
            else:
                self._global_var_types[_ca_m] = 'int64_t'
                _gg_ft1.setdefault(_ca_n, 'int64_t')

    self._selfhost_hardcoded_struct_names = frozenset(self.struct_field_types.keys())

    all_struct_defs = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    self._struct_bases = {s.name: list(getattr(s, 'bases', None) or [])
                           for s in all_struct_defs if isinstance(s, StructDef)}
    _all_struct_names = {_as_str(_as_structdef_node(s).name) for s in all_struct_defs if isinstance(s, StructDef)}
    _struct_bases_map = {}
    for _sbm in all_struct_defs:
        if isinstance(_sbm, StructDef):
            _sbm = _as_structdef_node(_sbm)
            _struct_bases_map[_as_str(_sbm.name)] = list(getattr(_sbm, 'bases', None) or [])
    _unresolved_base_memo: dict = {}
    self._structs_with_unresolved_base = {
        _name for _name in _struct_bases_map
        if _gmi_has_unresolved_base(_struct_bases_map, _all_struct_names,
                                   _unresolved_base_memo, _name, [])
    }
    # Remember each struct's OWN method-node identities before the merge, so
    # the ones the merge later injects can be recognised as INHERITED (the
    # merge mutates `s.methods` in place and keeps no record of provenance).
    # Their nodes belong to the base's module and are emitted a second time
    # as `Sub___m`; `_inherited_method_src` below maps each such node to the
    # module it actually came from, which the method-body emission loop uses
    # to attribute `#line` directives to the right FILE.
    _own_method_ids: dict = {}
    for _omo in all_struct_defs:
        if isinstance(_omo, StructDef):
            _omo = _as_structdef_node(_omo)
            _own_method_ids[id(_omo)] = {
                id(_as_funcdef_node(_m)) for _m in _omo.methods}
    _merge_struct_inheritance(all_struct_defs)
    # id(inherited method node) -> home module name, resolved by finding
    # which struct ORIGINALLY declared it.
    _inherited_method_src: dict = {}
    if _own_method_ids:
        _decl_home: dict = {}
        for _dh in all_struct_defs:
            if not isinstance(_dh, StructDef):
                continue
            _dh = _as_structdef_node(_dh)
            _hm = self._imported_struct_home.get(_as_str(_dh.name))
            if not _hm:
                continue
            for _hmeth in _dh.methods:
                _decl_home.setdefault(id(_as_funcdef_node(_hmeth)), _hm)
        for _is in all_struct_defs:
            if not isinstance(_is, StructDef):
                continue
            _is = _as_structdef_node(_is)
            _own = _own_method_ids.get(id(_is), ())
            for _im in _is.methods:
                _imid = id(_as_funcdef_node(_im))
                if _imid in _own:
                    continue
                _hm2 = _decl_home.get(_imid)
                if _hm2:
                    _inherited_method_src[_imid] = _hm2
    self._inherited_method_src = _inherited_method_src
    self._exc_descendants = _compute_exc_descendants(all_struct_defs)
    for _s in all_struct_defs:
        if isinstance(_s, StructDef):
            # `_as_str(_s.name)` — `_s.name` is a boxed self-hosted AST
            # field read; comparing/keying on it directly can silently
            # miss an already-present entry (e.g. one seeded elsewhere
            # via a properly `_as_str()`-normalized key, like
            # `gimple_codegen._selfhost_register_gimplegen`'s GimpleGen
            # field-dict seed), making this `not in` guard spuriously
            # True and WIPING that entry back to `{}` right here. See
            # bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md
            # Finding 4 Bug C.
            _s_name = _as_str(_s.name)
            if _s_name not in self.struct_field_types:
                self.struct_field_types[_s_name] = {}

    # --- builtin `dict` subclassing: `class Counter(dict)`, `class
    # OrderedDict(dict)`, and transitive subclasses of those ---
    # A user struct whose transitive base list bottoms out at the builtin
    # `dict` (directly, or via another local dict-subclass) has no
    # container storage of its own — the compiled struct is just its
    # `__mojo_type_id` header plus whatever scalar fields its methods
    # assign. Synthesize a hidden `_data` field of type `MojoDict *`
    # (allocated by `_alloc_<struct>`); inherited container operations
    # (`d[k]`, `d[k] = v`, `k in d`, `len(d)`) route to it unless the
    # subclass overrides the corresponding dunder. See
    # bugs/COMPILE_FAIL_collections___init__.md.
    _BUILTIN_DICT_BASES = ('dict', 'OrderedDict', 'defaultdict', 'Counter')
    _dict_subclass: set = set()
    _dsc_changed = True
    while _dsc_changed:
        _dsc_changed = False
        for _dsc_k in _struct_bases_map:
            _dsc_name = _as_str(_dsc_k)
            if _dsc_name in _dict_subclass:
                continue
            _dsc_hit = False
            for _dsc_bk in _struct_bases_map.get(_dsc_name) or ():
                _dsc_b = _as_str(_dsc_bk)
                if _dsc_b in _BUILTIN_DICT_BASES or _dsc_b in _dict_subclass:
                    _dsc_hit = True
                    break
            if _dsc_hit:
                _dict_subclass.add(_dsc_name)
                _dsc_changed = True
    self._dict_subclass_structs = _dict_subclass
    for _s in all_struct_defs:
        if not isinstance(_s, StructDef):
            continue
        _dsc_name = _as_str(_s.name)
        if _dsc_name not in _dict_subclass:
            continue
        _dsc_fm = self.struct_field_types.get(_dsc_name)
        if _dsc_fm is None:
            _dsc_fm = {}
            self.struct_field_types[_dsc_name] = _dsc_fm
        _dsc_fm['_data'] = 'MojoDict *'
        _dsc_has = False
        for _f in _s.fields:
            if _as_str(getattr(_f, 'name', '')) == '_data':
                _dsc_has = True
                break
        if not _dsc_has:
            _s.fields.insert(0, VarDecl(name='_data', type_ann=None, value=None))

    # --- builtin `bytes` subclassing: `class _Extra(bytes)` (zipfile) ---
    # A user struct whose transitive base list bottoms out at the builtin
    # `bytes` has no payload storage of its own. Synthesize a hidden
    # `_data: MojoBytes *` field; `__new__` / `super().__new__(cls, val)`
    # populates it (a bytes value is immutable, set once at construction —
    # so unlike the dict case `_alloc_` need NOT pre-allocate it), and
    # inherited bytes ops (`len(x)`, `x[i]`, `x[a:b]`, `for c in x`,
    # `x == y`, `x + y`, `x in y`, `b''.join(...)`, `bytes(x)`, `.decode()`,
    # `.hex()`, `.startswith`/`.split`/...) route to `inst->_data` unless
    # the subclass overrides the corresponding dunder/method. See
    # bugs/COMPILE_FAIL_zipfile___init__.md.
    _BUILTIN_BYTES_BASES = ('bytes',)
    _bytes_subclass: set = set()
    _bsc_changed = True
    while _bsc_changed:
        _bsc_changed = False
        for _bsc_k in _struct_bases_map:
            _bsc_name = _as_str(_bsc_k)
            if _bsc_name in _bytes_subclass:
                continue
            _bsc_hit = False
            for _bsc_bk in _struct_bases_map.get(_bsc_name) or ():
                _bsc_b = _as_str(_bsc_bk)
                if _bsc_b in _BUILTIN_BYTES_BASES or _bsc_b in _bytes_subclass:
                    _bsc_hit = True
                    break
            if _bsc_hit:
                _bytes_subclass.add(_bsc_name)
                _bsc_changed = True
    self._bytes_subclass_structs = _bytes_subclass
    # Which positional constructor argument becomes the bytes payload:
    # the argument that `__new__`'s `return super().__new__(cls, <name>)`
    # forwards (mapped back to `__new__`'s own param position, minus the
    # leading `cls`); defaults to 0 (`class X(bytes)` with no `__new__`,
    # or an unrecognised `__new__` shape — `X(val)` treats `val` as the
    # payload).
    self._bytes_subclass_payload_argidx: dict = {}
    for _s in all_struct_defs:
        if not isinstance(_s, StructDef):
            continue
        _bsc_name = _as_str(_s.name)
        if _bsc_name not in _bytes_subclass:
            continue
        _bsc_fm = self.struct_field_types.get(_bsc_name)
        if _bsc_fm is None:
            _bsc_fm = {}
            self.struct_field_types[_bsc_name] = _bsc_fm
        _bsc_fm['_data'] = 'MojoBytes *'
        _bsc_has = False
        for _f in _s.fields:
            if _as_str(getattr(_f, 'name', '')) == '_data':
                _bsc_has = True
                break
        if not _bsc_has:
            _s.fields.insert(0, VarDecl(name='_data', type_ann=None, value=None))
        _bsc_new = None
        for _m in _s.methods:
            if _as_str(getattr(_m, 'name', '')) == '__new__':
                _bsc_new = _m
                break
        _bsc_idx = 0
        if _bsc_new is not None:
            # Plain unpack loop, NOT a comprehension — see
            # bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md.
            _bsc_pnames = []
            for _bpn, _bpt in (_bsc_new.params or []):
                _bsc_pnames.append(_as_str(_bpn))
            # drop the leading cls/self
            _bsc_body_pnames = _bsc_pnames[1:] if _bsc_pnames else []
            _bsc_fwd = _bytes_subclass_new_payload_name(_bsc_new)
            if _bsc_fwd is not None and _bsc_fwd in _bsc_body_pnames:
                _bsc_idx = _bsc_body_pnames.index(_bsc_fwd)
            # `__new__` of a bytes subclass returns a new instance pointer
            self.func_return_types[f"{_bsc_name}___new__"] = f"{_bsc_name} *"
        self._bytes_subclass_payload_argidx[_bsc_name] = _bsc_idx

    self._ctor_lit_param_types: dict[str, dict[str, str]] = {}
    # Raw container-literal evidence from the pass above, kept for the
    # `_arg_scalar_type`-based observer to VETO on (a field holds exactly one
    # ctype, so a slot seen as a list by one observer and a string by the
    # other is a conflict, not a preference). Declared here rather than
    # created inside that pass so the veto is always defined, including when
    # no struct has an `__init__` at all.
    self._ctor_container_lit_obs: dict = {}
    self._ctor_container_lit_conflict: dict = {}
    _ctor_init_params = {}
    _ctor_init_methods = {}
    for _s in all_struct_defs:
        if isinstance(_s, StructDef):
            _init = None
            for _m in _s.methods:
                # `_as_str(_m.name) == '__init__'`: `_m.name` is a boxed AST
                # field read and the bare compare missed self-hosted, leaving
                # `_ctor_init_params` empty and skipping the whole
                # constructor-literal-evidence pass below.
                if _as_str(_m.name) == '__init__':
                    _init = _m
                    break
            if _init is not None:
                # `_as_str` on the KEY: two reads of the same struct name are
                # different boxed pointers, so the later
                # `_ctor_init_params.get(<call's own boxed name>)` missed for
                # every struct — no constructor literal-evidence type was ever
                # recorded (`Lit.value` stayed `int64_t` where the shim
                # inferred `char *` from `Lit('environ')` call sites; the
                # whole-program --dump-full's first divergence at offset
                # 21577).
                _cs_key = _as_str(_s.name)
                # Plain unpack loop, NOT a comprehension — see
                # bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md.
                _cip_list = []
                for _cipn, _cipt in (_init.params or []):
                    if _cipn != 'self' and not _cipn.startswith('*'):
                        _cip_list.append(_cipn)
                _ctor_init_params[_cs_key] = _cip_list
                _ctor_init_methods[_cs_key] = _init
    if _ctor_init_params:
        # FLAT dicts keyed by "<struct>::<param>", NOT a nested
        # `dict[str, dict[str, set]]`. The previous
        # `_ctor_lit_obs.setdefault(a, {}).setdefault(b, set()).add(...)`
        # chain was lowered self-hosted with `mojo_dict_setdefault_int` for
        # the nested NEW-dict value (a dict-of-dicts whose values are
        # created by `{}` is not modeled), so `_ctor_lit_obs` stayed empty,
        # no constructor literal-evidence type was ever recorded, and an
        # unannotated `self.value = value` field stayed `int64_t` where the
        # shim inferred `char *` from `Lit('environ')` call sites (`Lit.value`
        # — the whole-program --dump-full's first divergence at offset
        # 21577). Every accumulator below is a plain `dict[str, str]` /
        # `dict[str, bool]`, the shape this codebase compiles reliably.
        _obs_kind: dict = {}
        _obs_conflict: dict = {}
        # The RAW, pre-unanimity container evidence, kept so the LATER
        # `_arg_scalar_type`-based observer (the method-body / free-body
        # scan, `_ctor_scalar_obs` further down) cannot resolve a slot this
        # one saw as a container. The two observers are separate because
        # they see different things -- this one only syntactic literals, the
        # other anything `_arg_scalar_type` can type -- and a field holds
        # exactly ONE ctype, so `Thing([1, 2])` beside `Thing("s")` is a
        # conflict exactly as `Thing("s")` beside `Thing(3.5)` already is.
        # Without this the scalar channel saw only its own half of the
        # evidence, found it unanimous, and typed the field `char *` -- a
        # silent wrong answer where the documented rule is "not unanimous →
        # leave unresolved". Consulted as a VETO only, never as a source:
        # the container answer itself still has to travel through
        # `_ctor_lit_param_types` (the channel that provably reaches the
        # field type in the module that owns the struct).
        # Aliased, not copied: these are the SAME dicts the later
        # `_arg_scalar_type` observer reads as its veto (see their comment).
        _obs_container = self._ctor_container_lit_obs
        _obs_container_conflict = self._ctor_container_lit_conflict
        _ctor_calls: list = []
        self._calls_in_stmts(stmts, _ctor_calls)
        if self.do_imports or self.link_imports:
            self._calls_in_stmts(imported_stmts, _ctor_calls)
        for _call in _ctor_calls:
            if not isinstance(_call.func, IdentExpr):
                continue
            _cs_cname = _as_str(_call.func.name)
            _pnames = _ctor_init_params.get(_cs_cname)
            if not _pnames:
                continue
            for _i, _a in enumerate(_call.args):
                if _i >= len(_pnames):
                    break
                _lit_ct = ''
                if isinstance(_a, StringLiteral):
                    _lit_ct = 'char *'
                elif isinstance(_a, FloatLiteral):
                    _lit_ct = 'double'
                else:
                    # A container LITERAL argument is a PROOF, exactly like a
                    # string/float literal is: `[1, 2, 3]` passed to
                    # `__init__(self, items)` makes the field a `MojoList *`,
                    # not the `int64_t` default this observation used to leave
                    # it -- a field the compiler then happily iterated as a
                    # raw integer (SIGSEGV). Same rule, same unanimity
                    # bookkeeping, same annotation/default respect below; the
                    # only thing this adds is a third answer to "what C type is
                    # this argument", drawn from the one shared classifier
                    # `_gmi_collect_self_assigns` already uses for the direct
                    # `self.<f> = [1, 2, 3]` spelling of the same assignment.
                    _lit_ct = _gmi_container_ctype(_a) or ''
                if not _lit_ct:
                    continue
                _okey = _cs_cname + '::' + _pnames[_i]
                if _gmi_is_ctor_container_ctype(_lit_ct):
                    _cprev = _obs_container.get(_okey, '')
                    if not _cprev:
                        _obs_container[_okey] = _lit_ct
                    elif _cprev != _lit_ct:
                        _obs_container_conflict[_okey] = True
                _prev = _obs_kind.get(_okey, '')
                if not _prev:
                    _obs_kind[_okey] = _lit_ct
                elif _prev != _lit_ct:
                    _obs_conflict[_okey] = True

        # CONTEXT-TRACED container evidence (residue recorded in
        # “the constructor-call-site field-typing pass understood only scalars”): an
        # argument that is a LOCAL bound to a container literal
        # (`def mk(src): return Ident(src)` after `src = [1, 2, 3]`), or a
        # `self.<field>` read of a field the caller's OWN struct sets to a
        # container literal (`Reader(self._items)`), is exactly as much a
        # proof as the argument being the literal itself -- the value just
        # travels through one extra hop. Purely syntactic tracing, on
        # purpose: `self._inferred_var_types`/`self.struct_field_types`
        # (the "context" observer down at `_arg_scalar_type`) aren't
        # populated yet at this point in the pipeline, and threading THIS
        # evidence through the SAME _obs_kind/_obs_container dicts the
        # unanimity gate just below already consumes means no new admission
        # rule is needed -- a traced container answer is adjudicated
        # identically to a literal one.
        # NOTE ON NAMING: every local here is `_ctxlit_`-prefixed, including
        # ones that would ordinarily get a short generic name (`_key`,
        # `_found`, `_ct`, ...). This whole outer function (`gen_module_impl`)
        # compiles self-hosted as ONE C function, so a short name shared with
        # some unrelated nested closure elsewhere in this ~9000-line body
        # unifies to ONE C variable across both -- measured: `_key` collided
        # with the unrelated string-typed `_key = f"..."` a couple thousand
        # lines down and broke `test_selfhost.py` with "assignment to
        # 'MojoList *' from 'int64_t'" pointing at an entirely different,
        # untouched function. See this project's established `_xg_`/`_cl_`
        # prefix convention above for the identical reason.
        def _ctxlit_ident_container(_ctxlit_body, _ctxlit_name):
            for _ctxlit_node in _walk_ast(_ctxlit_body):
                if (isinstance(_ctxlit_node, AssignStmt) and isinstance(_ctxlit_node.target, IdentExpr)
                        and _ctxlit_node.target.name == _ctxlit_name):
                    _ctxlit_ct = _gmi_container_ctype(_ctxlit_node.value)
                    if _ctxlit_ct:
                        return _ctxlit_ct
            return None

        _ctxlit_field_cache: dict = {}

        def _ctxlit_self_field_container(_ctxlit_sdef, _ctxlit_field):
            _ctxlit_cachekey = _as_str(getattr(_ctxlit_sdef, 'name', '')) + '::' + _as_str(_ctxlit_field)
            if _ctxlit_cachekey in _ctxlit_field_cache:
                return _ctxlit_field_cache[_ctxlit_cachekey]
            _ctxlit_result = None
            for _ctxlit_method in _ctxlit_sdef.methods:
                for _ctxlit_node2 in _walk_ast(_ctxlit_method.body):
                    if isinstance(_ctxlit_node2, AssignStmt) and _gmi_self_member(_ctxlit_node2.target) == _ctxlit_field:
                        _ctxlit_ct2 = _gmi_container_ctype(_ctxlit_node2.value)
                        if _ctxlit_ct2:
                            _ctxlit_result = _ctxlit_ct2
                            break
                if _ctxlit_result:
                    break
            _ctxlit_field_cache[_ctxlit_cachekey] = _ctxlit_result
            return _ctxlit_result

        _ctxlit_bodies: list = []   # (body, enclosing StructDef or None)
        for _ctxlit_topstmt in all_struct_defs:
            if isinstance(_ctxlit_topstmt, FunctionDef):
                _ctxlit_bodies.append((_ctxlit_topstmt.body, None))
            elif isinstance(_ctxlit_topstmt, StructDef):
                for _ctxlit_meth in _ctxlit_topstmt.methods:
                    _ctxlit_bodies.append((_ctxlit_meth.body, _ctxlit_topstmt))

        for _ctxlit_callerbody, _ctxlit_enclosing in _ctxlit_bodies:
            for _ctxlit_callnode in _walk_ast(_ctxlit_callerbody):
                if not (isinstance(_ctxlit_callnode, CallExpr) and isinstance(_ctxlit_callnode.func, IdentExpr)):
                    continue
                _ctxlit_cname = _as_str(_ctxlit_callnode.func.name)
                _ctxlit_pnames = _ctor_init_params.get(_ctxlit_cname)
                if not _ctxlit_pnames:
                    continue
                for _ctxlit_argidx, _ctxlit_argnode in enumerate(_ctxlit_callnode.args):
                    if _ctxlit_argidx >= len(_ctxlit_pnames):
                        break
                    _ctxlit_argct = None
                    if isinstance(_ctxlit_argnode, IdentExpr):
                        _ctxlit_argct = _ctxlit_ident_container(_ctxlit_callerbody, _ctxlit_argnode.name)
                    elif _ctxlit_enclosing is not None:
                        _ctxlit_selffld = _gmi_self_member(_ctxlit_argnode)
                        if _ctxlit_selffld:
                            _ctxlit_argct = _ctxlit_self_field_container(_ctxlit_enclosing, _ctxlit_selffld)
                    if not _ctxlit_argct:
                        continue
                    _okey = _ctxlit_cname + '::' + _ctxlit_pnames[_ctxlit_argidx]
                    _cprev = _obs_container.get(_okey, '')
                    if not _cprev:
                        _obs_container[_okey] = _ctxlit_argct
                    elif _cprev != _ctxlit_argct:
                        _obs_container_conflict[_okey] = True
                    _prev = _obs_kind.get(_okey, '')
                    if not _prev:
                        _obs_kind[_okey] = _ctxlit_argct
                    elif _prev != _ctxlit_argct:
                        _obs_conflict[_okey] = True

        for _cs_name2 in _ctor_init_params:
            _init = _ctor_init_methods.get(_cs_name2)
            if not _init:
                continue
            _ann = {}
            for _ap in (_init.params or []):
                _ann[_as_str(_ap[0])] = _ap[1]
            for _pname in _ctor_init_params[_cs_name2]:
                _okey2 = _cs_name2 + '::' + _pname
                _kind = _obs_kind.get(_okey2, '')
                if _kind != 'char *' and _kind != 'double' \
                        and _kind not in _CTOR_CONTAINER_CTYPES:
                    continue                    # none, or not unanimous
                if _obs_conflict.get(_okey2) or _obs_container_conflict.get(_okey2):
                    continue                    # mixed char*/double evidence
                if _ann.get(_pname) is not None:
                    continue                    # respect explicit annotation
                # FLAT composite key "<struct>::<param>": a nested
                # `dict[str, dict[str, str]]` is unreliable here because
                # `dict.get(...)` on it returns an untyped int self-hosted, so
                # the outer `.get(name)` result can't be used for an inner
                # membership test at all (see the consumer in the field-write
                # pass). Same composite-string-key convention this codebase
                # already uses elsewhere.
                self._ctor_lit_param_types[_cs_name2 + '::' + _pname] = _kind

    # The synthetic `class GimpleGen` StructDef registered above (shared into
    # every nested temp_gen) must yield ownership to the REAL node whenever it
    # arrives naturally in this TU's closure (the root compile and
    # gimple_codegen.py's own compile). The shared `_struct_name_owner` would
    # otherwise keep the synthetic id set by some sibling temp_gen, and every
    # class-attr / method / field pass below (`!= id(s)`) would skip the struct
    # — dropping e.g. `_classattr_GimpleGen___NO_OVERLOAD_MANGLE` and its
    # `_alloc_GimpleGen` seed, leaving the field NULL at runtime.
    for s in all_struct_defs:
        s = _as_structdef_node(s)
        if isinstance(s, StructDef) and s.name == 'GimpleGen':
            self._struct_name_owner['GimpleGen'] = s
            break
    # Module-qualified struct IDENTITY. See `_struct_cname_by_id` in
    # GimpleGen.__init__ for what a cname is and why the bare StructDef.name
    # used to BE it was the bug.
    #
    # Every StructDef gets an entry in `_struct_cname_by_id`, and
    # `_struct_cname_of_name[bare]` is the WINNER's cname — for a struct that
    # never collided that is simply the bare name, so every non-colliding
    # struct's `struct_field_types` key, `typedef struct X` name, `_alloc_X`
    # helper and `{X}_{method}` symbol stay byte-identical to what they were
    # before. Only a GENUINE cross-module collision mints a qualified cname,
    # and even then the loser's METHOD SYMBOLS do not move: its cname is
    # `{qualifier}_{Name}`, and `_struct_method_qualifier` answers '' for an
    # already-qualified spelling, so the composer emits exactly the
    # `{qualifier}_{Name}_{method}` this codegen has always emitted for such a
    # struct. Nothing but the C *type* identity moves.
    #
    # A same-home same-named pair is NOT a collision: that is one file
    # redefining a class (Python semantics — the second binding replaces the
    # first), which is what `_struct_name_owner`'s first-wins already models,
    # and it is the shape this compiler's own two byte-identical
    # `class StringLiteral` definitions take (see this doc's §5). Keying the
    # qualification on the genuine cross-module case, NOT on the name loss,
    # is what keeps the self-hosting closure's struct set unchanged.
    for s in all_struct_defs:
        s = _as_structdef_node(s)
        if not isinstance(s, StructDef):
            continue
        _sid = id(s)
        if _sid in self._struct_cname_by_id:
            continue
        _sname = _as_str(s.name)
        _shome = self._struct_home_by_id.get(_sid, '')
        _owner = self._struct_name_owner.get(_sname)
        if _owner is None:
            # First claim on this bare name: it OWNS it, under the bare name.
            self._struct_name_owner[_sname] = s
            self._struct_cname_by_id[_sid] = _sname
            self._struct_cname_of_name[_sname] = _sname
            if _shome:
                self._struct_cname_by_home[_shome + '::' + _sname] = _sname
            continue
        if _owner is s:
            self._struct_cname_by_id[_sid] = _sname
            continue
        # A different StructDef already owns this bare name. Genuine collision?
        _ohome = self._struct_home_by_id.get(id(_owner), '')
        if not _shome or not _ohome or _shome == _ohome:
            # Same file (or an unresolvable home): a redefinition, not a
            # cross-module collision. Leave it to the first-wins skip below.
            continue
        # Real cross-module collision: give the loser a module-qualified cname,
        # uniquified against any cname already handed out.
        _q = _sanitize_cname_qualifier(_shome)
        _cname = _q + '_' + _sname
        _n = 2
        while _cname in self._struct_cname_of_name or _cname in self._struct_name_owner:
            _cname = _q + '_' + _sname + str(_n)
            _n += 1
        self._struct_cname_by_id[_sid] = _cname
        self._struct_name_owner[_cname] = s
        self._struct_cname_by_home[_shome + '::' + _sname] = _cname
        self._struct_qualified_cnames.add(_cname)
    for s in all_struct_defs:
        s = _as_structdef_node(s)
        if isinstance(s, StructDef):
            _sname = _as_str(s.name)
            _cname = self._struct_cname_by_id.get(id(s), _sname)
            if self._struct_name_owner.get(_cname) is not s:
                continue
            if _cname not in self.struct_field_types:
                self.struct_field_types[_cname] = {}
    # This module's OWN structs' constructor-param types, as proven by an
    # IMPORTING module's literal call sites — the same table shape and the same
    # key as `self._ctor_lit_param_types` above ("<struct>::<param>"), so the
    # `pm` chain in the field pass below reads one key from one place and
    # cannot tell (and does not need to) which module the evidence came from.
    #
    # Filtered to hints whose qualifier half is THIS module and which carry no
    # conflict, mirroring the `_xmod_ctor_field_hints` merge further down: same
    # `lstrip('.')` canonicalization, same "not unanimous → leave unresolved"
    # rule. Built here, before the loop below replaces each `s.name` with its
    # cname, and keyed by the same bare struct name the hint's own middle
    # segment is (so a genuinely colliding pair — two modules both defining
    # `Dialog` — resolves as neither does today, rather than as one of them
    # twice).
    _xf_own_ctor_params: dict = {}
    if getattr(self, '_xmod_ctor_field_hints', None) and self.module_name:
        _xfq = self.module_name.lstrip('.').replace('.', '_').replace('-', '_')
        for _xfk in self._xmod_ctor_field_hints:
            if self._xmod_ctor_field_conflict.get(_xfk):
                continue
            _xfhq, _xfhs, _xfhp = _xfk.split('::', 2)
            if _xfhq != _xfq:
                continue
            _xfpct = self._xmod_ctor_field_hints[_xfk]
            if _xfpct:
                _xf_own_ctor_params[_xfhs + '::' + _xfhp] = _xfpct
    # Also on `self`, because the struct-method SIGNATURE loop below reads
    # the same evidence and this local is out of scope by then. The field
    # pass in between reads the local; both go through
    # `_ctor_param_evidence`, which takes the table as an argument, so
    # neither can quietly diverge from the other.
    self._xf_own_ctor_params = _xf_own_ctor_params
    for s in all_struct_defs:
        s = _as_structdef_node(s)
        if isinstance(s, StructDef):
            # The struct's C IDENTITY from here on. Every `s.name` that keys a
            # whole-program table (field table, class attrs, boxed/bool field
            # sets, per-struct elem/array/annotation side tables) is this, not
            # the bare name — and that substitution IS the fix: a collision
            # loser's fields land in its OWN table instead of being dropped,
            # and its `self.<field>` accesses then read the ctype IT declared.
            _sname = _as_str(s.name)
            s.name = self._struct_cname_by_id.get(id(s), _sname)
            if self._struct_name_owner.get(s.name) is not s:
                continue
            if s.name not in self.struct_field_types:
                self.struct_field_types[s.name] = {}
            for field in (s.fields if hasattr(s, 'fields') else []):
                if isinstance(field, VarDecl) and field.name and field.name != 'self':
                    if not field.type_ann and field.name not in self.struct_field_types[s.name]:
                        _inherited_ft = None
                        for _base_name in (getattr(s, 'bases', None) or []):
                            _base_ft = self.struct_field_types.get(_base_name, {})
                            if field.name in _base_ft:
                                _inherited_ft = _base_ft[field.name]
                                break
                        # A recognisable value-typed default (e.g.
                        # `var FIELD_STRUCT = struct.Struct('<HH')`) — take
                        # its ctype rather than the `Struct *`-self fallback.
                        _fval = getattr(field, 'value', None)
                        _val_ct = _class_attr_ctype(_fval)
                        if _val_ct is None:
                            # A literal default states its own type, and the
                            # `s.name + ' *'` fallback below ("we don't know
                            # what this field holds") is what made the `var`
                            # spelling of a class attribute unusable: a `var
                            # NAME = 'hello'` field was typed as a
                            # `struct <Cls> *`, so the allocator's
                            # per-instance init — gated on the field type and
                            # the `_classattr_` global type agreeing — never
                            # fired and `self.NAME` read back 0. The BARE
                            # `NAME = 'hello'` spelling never hit this path
                            # (it is an AssignStmt, not a VarDecl) and worked,
                            # which is exactly the asymmetry this closes.
                            if isinstance(_fval, StringLiteral):
                                _val_ct = 'char *'
                            elif isinstance(_fval, FloatLiteral):
                                _val_ct = 'double'
                            elif isinstance(_fval, (IntLiteral, BoolLiteral)):
                                _val_ct = 'int64_t'
                        self.struct_field_types[s.name][field.name] = (
                            _inherited_ft if _inherited_ft is not None
                            else _val_ct if _val_ct is not None
                            else s.name + ' *')
            self._struct_generator_method_names.setdefault(s.name, set()).update(
                m.name for m in s.methods if getattr(m, 'is_generator', False))
            self._class_attrs[s.name] = {}
            for field in s.fields:
                # A `var NAME = <value>` class-body field and a bare
                # `NAME = <value>` one are the SAME declaration to Python —
                # `var` only suppresses a type inference the class body
                # doesn't do anyway — but only the bare spelling was
                # registered here. A `var FIELD = struct.Struct('<HH')`
                # therefore got a struct FIELD (right ctype, from the loop
                # above) with NO initializer emitted anywhere, so the field
                # stayed NULL and the first `self.FIELD.size` dereferenced
                # it: a live SEGFAULT, not a wrong value. Accept both
                # spellings; the VarDecl case just reads name/value off the
                # node instead of off `.target`/`.value`.
                _is_assign = isinstance(field, AssignStmt) and isinstance(field.target, IdentExpr)
                if _is_assign:
                    aname = field.target.name
                    v = field.value
                elif isinstance(field, VarDecl) and field.name and field.value is not None:
                    # Only for a value this block can actually INITIALIZE. A
                    # bare `var x` (no value), or one whose value is not a
                    # shape handled below, must NOT become a class
                    # attribute: the field-init path further down owns
                    # those, and minting a `_classattr_` global for them
                    # would shadow the field exactly the way the `_CONV_KWS`
                    # comment below describes.
                    if not isinstance(field.value, (StringLiteral, IntLiteral,
                                                    BoolLiteral, ListExpr, TupleExpr,
                                                    DictExpr, SetExpr, FloatLiteral)) \
                            and _class_attr_ctype(field.value) is None:
                        continue
                    aname = field.name
                    v = field.value
                else:
                    continue
                mangled = f"_classattr_{s.name}__{aname}"
                self._class_attrs[s.name][aname] = mangled
                ctype = _class_attr_ctype(v)
                # A class attribute holding a `struct.Struct('<fmt>')` with a
                # literal format: remember the format under the attribute
                # NAME, so `self.F.unpack(buf)` on it can recover the same
                # per-slot kinds the module-level `struct.unpack` path reads
                # straight off its own format argument. Without it, a mixed
                # format read through a class attribute gave its float slot
                # back as raw IEEE-754 bits on every statically-indexed read
                # (`t[1]`), because the handle is a runtime `MojoStructFmt *`
                # with no local name to record the format against.
                #
                # Keyed by NAME and not by (class, attr) on purpose, and only
                # recorded when that name is unambiguous: the read site
                # reaches the attribute through a lowered C value whose owning
                # type is not always recoverable (a free function's local, a
                # `Class.attr` spelled three different ways), and guessing
                # between two DIFFERENT formats is exactly the wrong-static-
                # answer failure this table exists to remove. A collision
                # records nothing and the read falls back to the runtime's
                # own kinds, which is right for the whole-result repr and
                # merely untyped for the rest.
                # Keyed BOTH ways, because the read site can usually name the
                # owner and sometimes cannot: `(cls, attr)` is the precise
                # key, and the name-only entry is what a read whose owner is
                # not recoverable falls back to — recorded only while it
                # stays unambiguous, and set to None the moment a second
                # class declares the same name with a DIFFERENT format, so a
                # guess is never made between two of them.
                _sfmt = gimple_ctypes._struct_ctor_format(v)
                if _sfmt is not None:
                    self._struct_attr_formats_scoped[(s.name, aname)] = _sfmt
                    if aname not in self._struct_attr_formats:
                        self._struct_attr_formats[aname] = _sfmt
                    elif self._struct_attr_formats[aname] != _sfmt:
                        self._struct_attr_formats[aname] = None
                if ctype is None:
                    if isinstance(v, StringLiteral):
                        ctype = 'char *'
                    elif isinstance(v, FloatLiteral):
                        ctype = 'double'
                    else:
                        ctype = 'int64_t'
                self._global_var_types[mangled] = ctype
                # A container-valued class attribute keeps its ELEMENT
                # type on the `_classattr_...` global, the same side-table
                # a local list uses. Without it a class-level registry of
                # objects (`T.registry = []` ... `T.registry.append(self)`)
                # reads back as an untyped handle, and every element of it
                # types as int64_t — so `p.numel()` became
                # `int64_t.numel() stubbed` and a model's parameter count
                # came back as a pointer-sized garbage number. An EMPTY
                # literal has no evidence and is left alone; the first
                # `.append()` on the attribute records the type (see
                # `_lower_list_method`'s pointer branch, which writes
                # `_elem_types[ov]`).
                if isinstance(v, (ListExpr, TupleExpr, SetExpr)) and v.elements:
                    _cel = self._infer_list_elem_type(v.elements)
                    if _cel and _cel != 'int64_t':
                        self._elem_types[mangled] = _cel
                # UPGRADE an already-registered instance field's type —
                # do NOT create one for a pure class-level attribute. A
                # container-valued class attr (`Parser._CONV_KWS = {...}`)
                # otherwise gets a struct field here, and `_lower_MemberExpr`
                # returns its struct-FIELD branch before its class-attr
                # branch — so `self._CONV_KWS` read the (never-initialized)
                # field, not the `_classattr_<Cls>__<X>` global, and the
                # self-hosted parser stopped recognizing convention keywords
                # (`for ref x in ...`).
                #
                # This runs for the SCALAR defaults too, not just container
                # ones: `_lower_MemberExpr` also prefers the struct field for
                # `self.NAME`, so a `var NAME = 'hello'` whose field stayed
                # at the generic `int64_t` default never got the per-instance
                # init (the allocator's init is gated on the field type and
                # the global type agreeing) and read back 0. Resolving the
                # type ONCE above, then upgrading from it, is what makes the
                # two agree for every spelling.
                cur = self.struct_field_types[s.name].get(aname)
                if cur is not None and cur in ('int', 'int64_t') and ctype != 'int64_t':
                    self.struct_field_types[s.name][aname] = ctype
                if ctype == 'MojoList *' and isinstance(v, (ListExpr, TupleExpr)):
                    self._field_elem_types.setdefault(s.name, {})[aname] = (
                        self._infer_list_elem_type(v.elements))
                if getattr(field, 'type_ann', None) is not None:
                    _dv_cls_early = self._annotation_dict_val_type(_as_str(field.type_ann))
                    if _dv_cls_early is not None:
                        self._global_dict_val_types[mangled] = _dv_cls_early
                        # An annotated container class-attr
                        # (`_str_pool: dict[str, str] = {}`) is ALSO an
                        # instance field — the typed-assign loop below skips
                        # it (already registered here), so record its dict
                        # VALUE type for `_lower_MemberExpr` field reads too,
                        # or `for k, v in self._str_pool.items()` unpacks `v`
                        # as int64 and `str()`s the pointer (garbage `_slit_N`
                        # names).
                        self._field_dict_val_types.setdefault(
                            s.name, {})[aname] = _dv_cls_early
            for field in s.fields:
                _is_typed_assign = (isinstance(field, AssignStmt)
                                     and isinstance(field.target, IdentExpr)
                                     and field.type_ann is not None)
                if isinstance(field, VarDecl) or _is_typed_assign:
                    # Explicit if/else, NOT a ternary: the self-hosted
                    # compiler's isinstance-narrowing only fires for a bare
                    # `if isinstance(...)` statement, so a ternary
                    # `field.name if isinstance(field, VarDecl) else ...`
                    # left `field` type-erased and `field.name` boxed —
                    # the struct-field-types dict then got a pointer-decimal
                    # key and the emitted C struct read `int64_t <address>;`
                    # for the field name.
                    if isinstance(field, VarDecl):
                        f_name = field.name
                    else:
                        f_name = field.target.name
                    if _as_str(s.name) == 'StringLiteral':
                        _ind = f_name in self.struct_field_types[s.name]
                    if f_name not in self.struct_field_types[s.name]:
                        ft = _mojo_type(_as_str(field.type_ann))
                        # BUG-2026-014 (box.3d/game): a bare capitalized
                        _fann_s = _as_str(field.type_ann).strip() if field.type_ann else ''
                        # `X | None` / `Optional[X]` on a struct field (very
                        # common in this compiler's own source, e.g.
                        # `self._dispatch_solver: DispatchSolver | None = None`)
                        # — unwrap to the payload type so the CapWord →
                        # `X *` resolution below fires. Without this the field
                        # stays int64_t and every `self._dispatch_solver.m()`
                        # call is stubbed to a no-op returning garbage.
                        _opt_m = re.match(r'^Optional\[\s*(.+?)\s*\]$', _fann_s)
                        if _opt_m:
                            _fann_s = _opt_m.group(1).strip()
                        elif '|' in _fann_s:
                            _parts_s = [p.strip() for p in _fann_s.split('|')]
                            _non_none_s = [p for p in _parts_s if p and p != 'None']
                            if len(_non_none_s) == 1:
                                _fann_s = _non_none_s[0]
                        if ft == 'int64_t' and _fann_s and _fann_s != _as_str(field.type_ann).strip():
                            ft = _mojo_type(_fann_s)
                        if (_fann_s and _fann_s[0].isupper() and '[' not in _fann_s
                                and '.' not in _fann_s and '*' not in _fann_s
                                and _fann_s not in self._IMPORTED_STRUCT_SKIP_BASENAMES
                                and _TYPE_MAP.get(_fann_s) is None):
                            if _fann_s in self.struct_field_types:
                                ft = f"{_fann_s} *"
                            else:
                                for _ist in stmts:
                                    if not (isinstance(_ist, FromImportStmt)
                                            and not getattr(_ist, 'wildcard', False)):
                                        continue
                                    for _fip16 in (getattr(_ist, 'name_alias_strs', None) or []):
                                        _inm = gimple_ctypes._fi_name(_fip16)
                                        _ialias = gimple_ctypes._fi_alias(_fip16)
                                        if (_ialias or _inm) != _fann_s:
                                            continue
                                        if self._materialize_imported_struct(
                                                _ist.module, _inm, _fann_s):
                                            ft = f"{_fann_s} *"
                                        break
                                    else:
                                        continue
                                    break
                        _arr_m = (_FIXED_ARRAY_ANN_RE.match(_as_str(field.type_ann).strip())
                                  if field.type_ann else None)
                        if _arr_m:
                            _elem_nm, _size_txt = _arr_m.group(1), _arr_m.group(2)
                            _n = (int(_size_txt) if _size_txt.isdigit()
                                  else self._module_const_int(_size_txt, stmts, imported_stmts))
                            if _n is not None and _n > 0:
                                _elem_ct = (_elem_nm if _elem_nm in self.struct_field_types
                                            else _mojo_type(_elem_nm))
                                ft = f"{_elem_ct}[{_n}]"
                                self._array_field_sizes.setdefault(s.name, {})[f_name] = (_elem_ct, _n)
                        if f_name == 'value' and s.name == 'Generator':
                            ft = 'int'  # boxed object field
                        _ann_bare = _as_str(field.type_ann).strip() if field.type_ann else ''
                        if _ann_bare in ('object', 'Any') or (
                                ' | ' in _ann_bare
                                and any(p.strip()[:1].isupper()
                                        for p in _ann_bare.split(' | ') if p.strip() != 'None')):
                            self.struct_boxed_fields.setdefault(s.name, set()).add(f_name)
                        if _ann_bare == 'bool':
                            self.struct_bool_fields.setdefault(s.name, set()).add(f_name)
                        if field.type_ann and not _arr_m:
                            _ann_str = _as_str(field.type_ann)
                            _outer_base = _ann_str.split('[')[0].strip()
                            _ptr_wrappers = ('UnsafePointer', 'OwnedPointer',
                                             'ArcPointer', 'Pointer', 'Reference')
                            if _outer_base in _ptr_wrappers and '[' in _ann_str:
                                _inner = _ann_str.split('[', 1)[1]
                                _inner_base = _inner.split('[')[0].strip()
                                if _inner_base in self.struct_field_types:
                                    ft = f'{_inner_base} *'
                            elif ft.endswith(' *') and _outer_base in self.struct_field_types:
                                ft = f'{_outer_base} *'
                        self.struct_field_types[s.name][f_name] = ft
                        if field.type_ann:
                            self._field_annotations[s.name + '.' + f_name] = _as_str(field.type_ann)
                        _dv_early = self._annotation_dict_val_type(_as_str(field.type_ann))
                        if _dv_early is not None:
                            self._field_dict_val_types.setdefault(s.name, {})[f_name] = _dv_early
                        if _dv_early in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                            _nv_early = self._annotation_dict_nested_val_type(_as_str(field.type_ann))
                            if _nv_early is not None and _nv_early != 'int64_t':
                                self._field_dict_nested_val_types.setdefault(
                                    s.name, {})[f_name] = _nv_early
                        # BUG-2026-023 residual (box.3d/game's
                        # ComputerCase.variables: List[String]): seed
                        # `_field_elem_types` from this field's OWN declared
                        # annotation too, exactly mirroring `_dv_early`
                        # above for dict value types. The only previous
                        # seeding path was `.append()` call sites tracked
                        # through `self.`-prefixed field owners
                        # (_lower_list_method's _struct_field_owners
                        # branch), so a List[...] field appended through a
                        # NON-self parameter name (`c.variables.append(..)`
                        # inside a free function taking `c: ComputerCase`)
                        # never recorded its element type — a later
                        # `c.variables[i]` read then fell back to int64_t
                        # and yielded raw boxed handles instead of strings
                        # ("set_variable(x,10)" then "get_variable(x)"
                        # returning 0 across test_computer_mod). The
                        # annotation is static truth available right here;
                        # only non-default element types need recording
                        # (int64_t is what every fallback already assumes).
                        if (ft in ('MojoList *', 'MojoSet *') and field.type_ann
                                and '[' in _as_str(field.type_ann)):
                            _li = gimple_ctypes._split_top_level_commas(
                                _as_str(field.type_ann).split('[', 1)[1].rstrip(']').strip())
                            if _li:
                                _et = self._resolve_type(_li[0].strip())
                                if _et and _et not in ('int64_t', 'MojoList *'):
                                    self._field_elem_types.setdefault(s.name, {})[f_name] = _et
                                elif _et == 'MojoList *':
                                    self._field_elem_types.setdefault(s.name, {})[f_name] = _et
                                # `list[tuple[T, T]]` — a list whose elements
                                # are themselves tuples. Record the inner
                                # SLOT type so `for a, b in obj.field:`
                                # unpacks with the right accessor instead of
                                # boxing both slots (see
                                # `_field_nested_elem_types`). Only a
                                # homogeneous tuple has one slot type; a
                                # heterogeneous one is deliberately skipped.
                                _inner_ann = _li[0].strip()
                                _inner_base = _inner_ann.split('[', 1)[0].strip()
                                if (_inner_base in ('tuple', 'Tuple')
                                        and '[' in _inner_ann):
                                    _slots = gimple_ctypes._split_top_level_commas(
                                        _inner_ann.split('[', 1)[1].rstrip(']').strip())
                                    # Explicit homogeneity loop, NOT
                                    # `len(set(...)) == 1`: this file's own
                                    # code has to compile under the
                                    # self-hosted backend, which lowers
                                    # neither `set()` nor a comprehension
                                    # over a generator here.
                                    _slot_ct = None
                                    _slot_same = True
                                    for _sl in _slots:
                                        _sl = _sl.strip()
                                        if not _sl:
                                            continue
                                        _sct = self._resolve_type(_sl)
                                        if _slot_ct is None:
                                            _slot_ct = _sct
                                        elif _sct != _slot_ct:
                                            _slot_same = False
                                            break
                                    if (_slot_same and _slot_ct is not None
                                            and _slot_ct != 'int64_t'):
                                        self._field_nested_elem_types.setdefault(
                                            s.name, {})[f_name] = _slot_ct

            _method_names = {m.name for m in s.methods}

            already = set(self.struct_field_types[s.name].keys())
            for method in s.methods:
                pm = {}
                # Which of this method's parameters say `bool` in their
                # annotation. `_gmi_collect_self_assigns` reads it through
                # `self` (see `GimpleGen._gmi_bool_params`) because that walk
                # is the only place that knows which FIELD a parameter feeds,
                # and re-walking the body here to recover that is exactly the
                # quadratic-rescan cost
                # bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
                # rescan.md is about. Rebuilt per method, so one method's
                # answer can never leak into the next one's fields.
                self._gmi_bool_params = set()
                _defaults = getattr(method, 'param_defaults', {}) or {}
                for _mpj in (method.params or []):
                    # Indexed loop + `_as_str`, NOT `for pname, ptype in
                    # method.params:` — a 2-tuple unpack over a boxed element
                    # list miscompiles self-hosted (the pname/ptype slots box
                    # to int64_t; see _free_func_param_ctypes' docstring), so
                    # the `pname in self._ctor_lit_param_types...` lookup
                    # missed on the boxed key and every unannotated
                    # `self.value = value` field fell back to `int64_t`.
                    pname = _as_str(_mpj[0])
                    ptype = _mpj[1]
                    if pname != 'self':
                        if ptype:
                            if _as_str(ptype).strip() == 'bool':
                                self._gmi_bool_params.add(pname)
                            pm[pname] = self._resolve_type(ptype)
                        elif pname in _defaults:
                            _dv = _defaults[pname]
                            if isinstance(_dv, StringLiteral):
                                pm[pname] = 'char *'
                            elif isinstance(_dv, BoolLiteral):
                                pm[pname] = '_Bool'
                            else:
                                pm[pname] = 'int64_t'
                        # Literal evidence, from this module's own call
                        # sites and from an IMPORTING module's (the same two
                        # tables, one reader — `_ctor_param_evidence`, which
                        # the struct-method SIGNATURE loop below also calls,
                        # because a param typed here and left `int64_t` there
                        # truncates the argument at the call: `B(2.5)` stored
                        # the int 2 into a field declared `double` and read
                        # back 2.0).
                        elif _as_str(method.name) == '__init__' and _ctor_param_evidence(
                                self, s.name, pname, _xf_own_ctor_params):
                            # The same evidence, one module away: a constructor
                            # called from an IMPORTING module with a literal
                            # argument of this type. It has to be consulted
                            # HERE, on the PARAM, rather than only in the
                            # `_xmod_ctor_field_hints` merge further down,
                            # because that merge is keyed by param name and
                            # applied to the FIELD of the same name — so
                            #
                            #     class Dialog:
                            #         def __init__(self, s):   # unannotated
                            #             self.s = s
                            #             self.n = s
                            #
                            # imported and called as `mb.Dialog("hi")` typed
                            # `self.s` and left `self.n` at the `int64_t`
                            # default: `b.s` printed `hi`, `b.n` printed a heap
                            # address. Same class, ONE module, was already
                            # right — and the reason is this line: typing the
                            # PARAM is what lets `_gmi_collect_self_assigns`
                            # (three lines below) type EVERY field the
                            # constructor assigns that param to. It also keeps
                            # the store and the field declaration agreeing: the
                            # merge alone typed a field `double` while the
                            # param stayed `int64_t`, and `self.g = f` then
                            # stored 2.5 as the int 2, which read back as 2.0.
                            #
                            # The one-module table above is consulted FIRST, so
                            # a module's own literal evidence still wins over
                            # another module's; and an explicit annotation beats
                            # both (the `if ptype:` arm above).
                            pm[pname] = _ctor_param_evidence(
                                self, s.name, pname, _xf_own_ctor_params)
                        else:
                            pm[pname] = 'int64_t'
                new_fields = {}
                _gmi_collect_self_assigns(self, s.name, method.body, pm,
                                          new_fields)
                for _nf_k in new_fields:
                    fn = _as_str(_nf_k)
                    ft = _as_str(new_fields[_nf_k])
                    existing_ft = self.struct_field_types[s.name].get(fn)
                    # Two "we did not know" answers may be REPLACED by this
                    # pass's evidence, and both are exactly as contentless:
                    #   * `'int'` — the struct emitter's own placeholder for a
                    #     field with no annotation, so a pointer answer is
                    #     strictly more information (the rule's own words).
                    #   * `f"{s.name} *"` — what the `s.fields` VarDecl walk
                    #     above writes when a field has neither annotation,
                    #     inherited type, nor readable default ("we don't know
                    #     what this field holds"). It is NOT a weaker spelling
                    #     of the same ignorance, and letting it win is what
                    #     typed a self-host field with a POINTER TO THE
                    #     RECEIVER'S OWN STRUCT: that walk runs FIRST for each
                    #     struct, so by the time a `self.X = <expr>`
                    #     assignment is examined here the placeholder is
                    #     already the field's declared type and the `can_override`
                    #     test below let it stand. Measured, six hard gcc
                    #     errors in the self-host closure, all one answer:
                    #     `MojoFunction._interp`, `MojoOverloadSet._interp`
                    #     (an UNANNOTATED `__init__` parameter, so the honest
                    #     answer is the box) and `Parser._comptime_rhs_failures`
                    #     (ANNOTATED `list`, so `MojoList *`) came out as
                    #     `MojoFunction *` / `MojoOverloadSet *` / `Parser *`.
                    #     It only reaches those three because the field's
                    #     evidence lives in ANOTHER module's compile: the
                    #     `VarDecl` placeholder this walk finds in `s.fields`
                    #     was appended by the pass below while a SIBLING
                    #     module was compiled, so the outer gen's own
                    #     `struct_field_types` has no entry to protect — the
                    #     two tables are per-gen while `StructDef.fields` is
                    #     shared, which is why the placeholder is the only
                    #     thing that survives.
                    # `ft != existing_ft` keeps a field whose real type IS the
                    # receiver's own struct (`self.next = other`, `self.parent
                    # = owner`) exactly where it is: both sides answer the same
                    # and nothing changes.
                    can_override = ((existing_ft == 'int' and ft.endswith(' *'))
                                    or (existing_ft == s.name + ' *'
                                        and ft != existing_ft))
                    if fn not in self.struct_field_types[s.name] or can_override:
                        self.struct_field_types[s.name][fn] = ft
                        if fn not in already:
                            s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                            already.add(fn)
            # A method that returns a `bool`-annotated FIELD hands back an
            # `int`, because that is what the field's ctype is, so
            # `print(b.get())` printed `1` where CPython prints `True`. Its
            # own body is the evidence: EVERY `return` in it reads a bool
            # field, which is the only shape recorded here -- a method that
            # merely READS a bool field and returns something else is left
            # alone, because answering True for that would trade a wrong
            # value for a differently wrong one.
            #
            # A SEPARATE loop over the methods, not a step inside the one
            # above: `__init__` is what registers the field, and a class may
            # spell its getter first, so recording inside that loop would
            # make the answer depend on declaration order.
            if self.struct_bool_fields.get(s.name):
                for _bm in s.methods:
                    _rets = [_rn for _rn in _walk_ast(_bm.body)
                             if isinstance(_rn, ReturnStmt)]
                    if not _rets:
                        continue
                    # Which bare receiver names in this method denote a
                    # struct: `self`, and any parameter annotated with a
                    # struct name. Both come from the declaration, so
                    # `return other.flag` in `def echo(self, other: Box)`
                    # is recognised the same as `return self.flag`. A
                    # receiver this cannot name is simply not claimed, which
                    # is why the field check below is against the RECEIVER's
                    # own bool fields and not this struct's.
                    _recv_sn = {'self': _as_str(s.name)}
                    for _mpj2 in (_bm.params or []):
                        _pt2 = _mpj2[1]
                        if _pt2 and _as_str(_pt2).strip() in self.struct_field_types:
                            _recv_sn[_as_str(_mpj2[0])] = _as_str(_pt2).strip()
                    _all_bool_field = True
                    for _rn2 in _rets:
                        _rv = _rn2.value
                        _rname = ''
                        if isinstance(_rv, MemberExpr) and isinstance(_rv.obj, IdentExpr):
                            _rname = _as_str(_rv.obj.name)
                        _rsn2 = _recv_sn.get(_rname)
                        if not (_rsn2 is not None
                                and _as_str(_rv.member) in (
                                    self.struct_bool_fields.get(_rsn2) or ())):
                            _all_bool_field = False
                            break
                    if _all_bool_field:
                        self.struct_bool_methods.setdefault(
                            s.name, set()).add(_as_str(_bm.name))
            if s.name in self._selfhost_hardcoded_struct_names:
                continue

            # Same __getattr__ rule as _scan_body_for_local_field_access
            # below: a read of a member this struct never ASSIGNS is a
            # dynamic-attribute read on a __getattr__ struct — it must
            # reach the compiled `__getattr__` at runtime, not be minted
            # into an uninitialized phantom `int` field first. (Fields the
            # methods DO assign were already registered by the write pass
            # just above, so those reads keep resolving statically.)
            if any(m.name == '__getattr__' for m in s.methods):
                continue
            for method in s.methods:
                read_fields = {}
                _gmi_collect_self_reads(_method_names, method.body, read_fields)
                for fn, ft in read_fields.items():
                    # A class-level constant read as `self.STACK` (e.g.
                    # LayoutSolver's `STACK = 'stack'`) resolves through
                    # `_class_attrs` to its own `_classattr_<Cls>__<X>`
                    # global — it is NOT an instance field. Minting a phantom
                    # `int64_t STACK;` here grew the shim's C struct by two
                    # extra members (`int64_t HEAP; int64_t STACK;`) the
                    # self-hosted build correctly omitted, the first
                    # byte-level divergence of check-native-dumpfull (offset
                    # 21086). The class-body-attribute pass above has already
                    # populated `_class_attrs[s.name]`, so this lookup makes
                    # the outcome independent of pass ordering.
                    if fn in self._class_attrs.get(s.name, {}):
                        continue
                    if fn not in self.struct_field_types[s.name]:
                        _base_ft = None
                        for _base_name in (getattr(s, 'bases', None) or []):
                            _cand = self.struct_field_types.get(_base_name, {}).get(fn)
                            if _cand is not None:
                                _base_ft = _cand
                                break
                        self.struct_field_types[s.name][fn] = _base_ft if _base_ft is not None else ft
                        if fn not in already:
                            s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                            already.add(fn)

    _struct_by_name = {st.name: st for st in all_struct_defs
                        if isinstance(st, StructDef)
                        and self._struct_name_owner.get(st.name) is st}

    def _scan_stmt_var_candidates(stmt):
        sid = id(stmt)
        cached = self._field_scan_var_cache.get(sid)
        if cached is not None:
            return cached
        cands = []
        for node in _walk_ast(stmt):
            if isinstance(node, VarDecl) and node.type_ann:
                cands.append((node.name, str(node.type_ann).strip()))
            elif (isinstance(node, AssignStmt) and isinstance(node.target, IdentExpr)
                  and isinstance(node.value, CallExpr) and isinstance(node.value.func, IdentExpr)):
                cands.append((node.target.name, node.value.func.name))
        self._field_scan_var_cache[sid] = cands
        return cands

    def _scan_stmt_member_candidates(stmt):
        sid = id(stmt)
        cached = self._field_scan_member_cache.get(sid)
        if cached is not None:
            return cached
        cands = []
        for node in _walk_ast(stmt):
            if not (isinstance(node, MemberExpr) and isinstance(node.obj, IdentExpr)):
                continue
            fn = node.member
            if fn.startswith('__') and fn.endswith('__'):
                continue
            cands.append((node.obj.name, fn))
        self._field_scan_member_cache[sid] = cands
        return cands

    def _scan_stmt_member_assigns(stmt):
        """`[(obj name, member, value node)]` for every `o.m = <value>`
        whose receiver is a bare identifier — the assignment EVIDENCE the
        phantom-field mint below types the field from. A sibling of the two
        scans above, and memoized the same way (`_walk_ast` is the expensive
        part, and this runs over every top-level statement twice)."""
        sid = id(stmt)
        cached = self._field_scan_assign_cache.get(sid)
        if cached is not None:
            return cached
        cands = []
        for node in _walk_ast(stmt):
            if (isinstance(node, AssignStmt)
                    and isinstance(getattr(node, 'target', None), MemberExpr)
                    and isinstance(node.target.obj, IdentExpr)
                    and node.value is not None):
                cands.append((node.target.obj.name, node.target.member,
                              node.value))
        self._field_scan_assign_cache[sid] = cands
        return cands

    def _scan_body_for_local_field_access(body, own_struct_name):
        # Collect EVERY struct type each local name is ever bound to, then
        # keep only unambiguous names. The candidate scan is flow-insensitive
        # (it unions assignments across the whole body), so a name rebound to
        # different node types in one function — `_parse_expr`'s `left` holds
        # UnaryOp/CompareChain/BinaryOp/WalrusExpr/TernaryExpr as the loop
        # refines the expression — must not mint fields on ANY of them: a
        # member access guarded by `isinstance(left, CompareChain)` at runtime
        # (`left.operands`, fire_compiler.py:3292) otherwise registered
        # phantom `operands`/`ops`/`name` fields on TernaryExpr/UnaryOp,
        # growing their C structs (typed `int`) and making compiled repr() of
        # every such node print extra "operands=0, ops=0, name=0" tail fields
        # Python's dataclass repr never emits — a verify-visible
        # stage1-vs-stage2 .ast divergence.
        local_type_sets = {}
        for stmt in body:
            for name, ann in _scan_stmt_var_candidates(stmt):
                if (ann in self.struct_field_types and ann != own_struct_name
                        and ann not in self._selfhost_hardcoded_struct_names):
                    local_type_sets.setdefault(name, {})[ann] = True
        # Plain dicts throughout (no set()/next()): this file is itself
        # compiled by the self-host backend, which lowers neither.
        local_types = {}
        for name, ts in local_type_sets.items():
            if len(ts) == 1:
                for only_type in ts:
                    local_types[name] = only_type
        if not local_types:
            return
        # `{(obj name, member): ctype}` for every `o.m = <value>` in this
        # body, keyed like the mint that consumes it. Built BEFORE the mint
        # loop so an assignment that appears textually AFTER the read (the
        # `print(o.x)` line, then `o.x = "hello"`) still counts — the same
        # flow-insensitive union `local_type_sets` above is built on, and
        # for the same reason: a struct's field set is a whole-program
        # fact, not a statement-order one. First answer wins, so a member
        # written twice keeps the first write's type; conflicting writes are
        # not represented, exactly as `local_type_sets` drops an ambiguous
        # name rather than guessing.
        _assigned_member_ctypes = {}
        for stmt in body:
            for obj_name, fn, value in _scan_stmt_member_assigns(stmt):
                _k = (obj_name, fn)
                if _k in _assigned_member_ctypes:
                    continue
                try:
                    _assigned_member_ctypes[_k] = self._quick_type(value)
                except Exception:
                    pass
        for stmt in body:
            for obj_name, fn in _scan_stmt_member_candidates(stmt):
                target_struct = local_types.get(obj_name)
                if target_struct is None:
                    continue
                if fn in self.struct_field_types[target_struct]:
                    continue
                # A class-level constant read as `self.X` (e.g.
                # LayoutSolver's `STACK = 'stack'`) resolves through
                # `_class_attrs` to its own `_classattr_<Cls>__<X>` global —
                # it is NOT an instance field, so this read-only phantom mint
                # must not shadow it with an uninitialized scalar. (The same
                # guard is applied to the sibling self-READ pass above; both
                # are read-mint sites for the same class of member.)
                if fn in self._class_attrs.get(target_struct, {}):
                    continue
                # A struct that defines its own `__getattr__` resolves every
                # unknown member dynamically (ctypes's LibraryLoader:
                # `cdll.msvcrt` = load that DLL). Minting a phantom `int`
                # field here would make the member-read lowering take the
                # plain known-field branch (`->msvcrt`, an uninitialized
                # scalar) instead of routing through the compiled
                # `__getattr__` — silently wrong at runtime, and it also
                # polluted this struct's generated getattr/setattr dispatch
                # tables and repr() with dead fields. Reads of members that
                # are genuinely ASSIGNED elsewhere still register via the
                # `self.X = ...` write pass above; only read-only unknowns
                # were minted here, and for a __getattr__ struct those have
                # a real resolution story that must win.
                target_def = _struct_by_name.get(target_struct)
                if target_def is not None and any(
                        m.name == '__getattr__' for m in target_def.methods):
                    continue
                # A builtin-`dict` subclass instance's `.get`/`.keys`/
                # `.values`/`.items`/`.update`/`.pop`/`.setdefault` are
                # inherited container methods delegated to the hidden
                # `_data` backing store (see gimple_gen_methods.py's
                # dict-subclass delegation) — NOT phantom scalar fields.
                # Minting an `int` field named `get` here would make
                # `d.get(k)` lower as a function-pointer field call.
                if (fn in ('get', 'keys', 'values', 'items', 'update',
                           'pop', 'setdefault', 'clear')
                        and target_struct in getattr(
                            self, '_dict_subclass_structs', ())
                        and not any(m.name == fn for m in
                                    (target_def.methods if target_def else ()))):
                    continue
                # `fn` is a genuinely declared METHOD on this struct (or one
                # of its bases) — an ordinary `obj.method(...)` call, not a
                # field access at all. `_scan_stmt_member_candidates` walks
                # every `MemberExpr` regardless of whether it's the callee
                # of a CallExpr or a bare value read, so a real method whose
                # name isn't one of the narrow builtin-container names above
                # (e.g. `DispatchPattern.add_call_site`/`.add_callee`) fell
                # through to the unconditional phantom-field mint below —
                # a determinism gap between the shim and the self-hosted
                # binary's own (differently-ordered) struct/method
                # registration passes, whichever run happened to resolve
                # `target_struct`'s method list before vs after this scan.
                # See bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md.
                if target_def is not None and any(
                        m.name == fn for m in target_def.methods):
                    continue
                if target_def is not None and any(
                        m.name == fn
                        for _base_name in (getattr(target_def, 'bases', None) or [])
                        for m in getattr(_struct_by_name.get(_base_name), 'methods', ())):
                    continue
                # The minted field's TYPE, from the value actually assigned to
                # this member, when there is one. The `int` below is the
                # "nothing is known about this member" answer, and it is
                # right for a read-only phantom — but a member that IS
                # assigned is not read-only, and storing a `char *` or a
                # `double` through a 4-byte `int` field TRUNCATES the value:
                # `o.x = "hello"; print(o.x)` printed the low 32 bits of the
                # string's address as a decimal, and `len(o.x)` then
                # dereferenced that truncated value and SEGFAULTED. Only
                # POINTER-shaped and floating answers override `int` — those
                # are the ones an `int` slot is provably wrong for — so a
                # member assigned an ordinary integer keeps exactly the
                # declaration it has always had.
                _mft = 'int'
                _afn = _assigned_member_ctypes.get((obj_name, fn))
                if _afn and (_afn.endswith(' *') or _afn in ('double', 'float')):
                    _mft = _afn
                self.struct_field_types[target_struct][fn] = _mft
                if target_def is not None and not any(
                        isinstance(f, VarDecl) and f.name == fn for f in target_def.fields):
                    target_def.fields.append(VarDecl(name=fn, type_ann=None, value=None))

    _scan_body_for_local_field_access(stmts, None)
    if self.do_imports or self.link_imports:
        _scan_body_for_local_field_access(imported_stmts, None)

    # Aliased CLASS imports (`from M import Class as Alias`) for the WHOLE
    # module, module scope AND function bodies, resolved HERE rather than
    # only where the from-import statement is later lowered. The reason is
    # ordering, not tidiness: `_note_struct_import_alias` is gated on
    # `struct_field_types`, which is only populated by the struct passes
    # above, and the alias has to be known to every inference pass that
    # runs after this point — a function-scoped `from M import C as A`
    # whose `return A("s")` feeds the free-function RETURN-type inference
    # (below, in `_gmi_collect_return_values`' consumers) otherwise infers
    # `int64_t`, and the caller then reads the struct through an integer
    # (`assignment to 'char *' from 'int64_t' ... makes pointer from
    # integer without a cast`). `_gen_stmt_FromImportStmt` keeps its own
    # call for the `not do_imports` shape, where this pass does not run;
    # `_note_struct_import_alias` is first-writer-wins, so the two can
    # never disagree about what an alias names.
    #
    # The SAME walk collects the assignment spelling of the same fact —
    # `Alias = <module>.<Class>` (`_note_struct_attr_alias`), which is how
    # this compiler's own source reaches an AST node class
    # (`mojo/middle/offload.py`'s `I = gctypes.IdentExpr`,
    # `emit_stmts.py`'s `_IL = gimple_ctypes.IntLiteral`). The pairs are
    # only RESOLVED below, after the plain-`import X as Y` scan has filled
    # `_module_alias_names`: "is this base a module namespace" is not
    # answerable until that scan has run, and a guess made here would have
    # to be a second guess later. Both spellings write the same table
    # first-writer-wins, so a name claimed by either is claimed once.
    _attr_alias_candidates: list = []
    for _al_n in _walk_ast(stmts):
        if isinstance(_al_n, FromImportStmt) and not getattr(_al_n, 'wildcard', False):
            for _al_ip in (getattr(_al_n, 'name_alias_strs', None) or []):
                _al_name = gimple_ctypes._fi_name(_al_ip)
                _al_alias = gimple_ctypes._fi_alias(_al_ip)
                if _al_alias:
                    self._note_struct_import_alias(_al_n.module, _al_alias, _al_name)
        elif (isinstance(_al_n, AssignStmt)
                and isinstance(getattr(_al_n, 'target', None), IdentExpr)
                and isinstance(getattr(_al_n, 'value', None), MemberExpr)):
            _al_mem = _al_n.value
            if isinstance(getattr(_al_mem, 'obj', None), IdentExpr):
                _attr_alias_candidates.append(
                    (_as_str(_al_mem.obj.name), _as_str(_al_n.target.name),
                     _as_str(_al_mem.member)))

    _phase0_func_types = dict(self.func_return_types)   # save Phase 0 registrations
    _phase0_imported   = dict(getattr(self, 'imported_symbols', {}))  # save Phase 0 imported_symbols
    self.func_return_types = dict(_RUNTIME_FUNCS)
    self.func_return_types.update(_phase0_func_types)   # Phase 0 types win over defaults
    all_struct_defs_for_types = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    for s in all_struct_defs_for_types:
        s = _as_structdef_node(s)
        if isinstance(s, StructDef):
            self.func_return_types[s.name] = f"{s.name} *"

    self.imported_symbols = dict(_phase0_imported)   # restore Phase 0 imported_symbols

    # A plain MODULE-TOP-LEVEL `import X as Y` (an `ImportStmt` node, as
    # opposed to `from X import Y` below) never reaches `_gen_stmt_
    # ImportStmt` — the ONLY other site that registers `imported_symbols`
    # for it — because a top-level ImportStmt is silently `pass`ed over
    # by this same function's later toplevel-statement filter ("Imports
    # processed in pre-pass"; that "pre-pass" is supposed to be THIS
    # scan). Without this, `imported_symbols` stayed empty for any
    # top-level `import X as Y` alias, so every `_lower_MemberExpr`/
    # `_lower_IdentExpr` branch gated on `module_name in gen.
    # imported_symbols` (module-attribute-access special cases: a
    # function value read off a module, `submod.GLOBAL`, a known class
    # read off a module, ...) was silently unreachable for it — only a
    # `from X import Y` or a NESTED (function-body) `import X as Y`
    # actually worked. Concretely: Tools/cases_generator/plexer.py's
    # top-level `import lexer as lx` / `Token = lx.Token` fell through
    # every special case to the generic dynamic-dispatch fallback, which
    # raises a genuine (uncaught) runtime `AttributeError: Token` the
    # instant that assignment executes — see
    # “COMPILE_FAIL: Tools/cases_generator/parser.py”. Must run BEFORE
    # `_gen_toplevel` (this scan does; a second, later, defensive-only
    # copy of this same registration also lives in this file's toplevel
    # global-declaration scan, which runs AFTER `_gen_toplevel` and so
    # cannot fix this by itself). Mirrors `_gen_stmt_ImportStmt`'s own
    # dict shape exactly; guarded so it never overwrites a richer entry
    # a `from X import Y` already set for the same local name.
    for s in stmts:
        if isinstance(s, ImportStmt):
            # `(module, local-name)` with DIRECT field reads for the primary
            # target (`s.module` / `s.alias`), not a `for _m,_a in
            # _import_targets` unpack whose boxed `None` alias slot comes back
            # a stray truthy pointer -> `imported_symbols[<decimal addr>]`.
            _im_prim_alias = _as_str(s.alias)
            _im_pairs = [(_as_str(s.module),
                          _im_prim_alias if _im_prim_alias else _as_str(s.module))]
            for _ex in (getattr(s, 'extra', None) or []):
                _ex_a = _as_str(_ex[1])
                _im_pairs.append((_as_str(_ex[0]), _ex_a if _ex_a else _as_str(_ex[0])))
            for _im_mod, _im_local in _im_pairs:
                if _im_local == _im_mod and '.' in _im_mod:
                    _im_local = _im_mod[:_im_mod.index('.')]
                if _im_local not in self.imported_symbols:
                    self.imported_symbols[_im_local] = {
                        'module': _im_mod,
                        'return_type': 'unknown',
                    }
                self._module_alias_names.add(_im_local)

    # `_module_alias_names` is finally populated, so the `Alias = <module>.
    # <Class>` candidates collected by the alias walk above can be resolved.
    for _aa_base, _aa_alias, _aa_member in _attr_alias_candidates:
        self._note_struct_attr_alias(_aa_base, _aa_alias, _aa_member)

    for s in stmts:
        if isinstance(s, FromImportStmt):
            _sib_qualifier = None
            # Guard BEFORE calling load_module, not just try/except around
            # it: this codegen's compiled try/except does not reliably
            # catch a raised exception, so a genuine sibling `.py` compiler
            # module (e.g. `from gimple_exprtypes import ...` inside
            # gimple_gen_coro.py) reached module_loader's `raise ValueError
            # ("Only stdlib and test imports supported")` UNCAUGHT and
            # aborted the whole imported-module compile on
            # `MOJO_NO_SHIM=1 --dump-full` (invisible to the shimmed
            # `make bootstrap` path). See ModuleLoader.can_resolve_
            # module_path's docstring.
            import module_loader as _mlmod_fims
            if _mlmod_fims.can_resolve_module_path(s.module):
                try:
                    exports = load_module(s.module)
                except Exception:
                    exports, _sib_qualifier = self._local_sibling_module_exports(s.module)
            else:
                exports, _sib_qualifier = self._local_sibling_module_exports(s.module)
            _sib_is_local_project = False
            if _sib_qualifier:
                try:
                    import module_loader as _mlmod_chk
                    _sib_path0 = self._parsed_import(s.module)[0]
                    _sib_is_local_project = bool(_sib_path0) and not (
                        _sib_path0.startswith(_mlmod_chk.STDLIB_PATH)
                        or _sib_path0.startswith(_mlmod_chk.TEST_PATH))
                except Exception:
                    _sib_is_local_project = False
            if _sib_is_local_project and _sib_qualifier not in self._toplevel_dep_init_modules:
                self._toplevel_dep_init_modules.append(_sib_qualifier)
            if exports is not None:
                try:
                    if not s.names:
                        for _wc_key in exports:   # not `.items()` — 2-tuple unpack boxes the key on the self-hosted path
                            _register_sym(self, s, _wc_key, _wc_key, exports[_wc_key], _sib_qualifier, _sib_is_local_project)
                    else:
                        for _fip17 in (getattr(s, 'name_alias_strs', None) or []):
                            _rs_nm = gimple_ctypes._fi_name(_fip17)
                            alias = gimple_ctypes._fi_alias(_fip17)
                            # `_as_str` on the ternary: without it the
                            # self-hosted backend erased `sym_name` to
                            # int64_t, so `_register_sym`'s `self.imported_
                            # symbols[sym_name] = {...}` stringified the
                            # `char *` bits as a DECIMAL and stored the
                            # address as the dict key — every downstream
                            # `sorted(imported_symbols.keys())` (the
                            # `/* from .<mod> */` re-export extern block)
                            # then ordered by ADDRESS, differently each run.
                            sym_name = _as_str(alias if alias else _rs_nm)
                            sym_info = exports.get(_rs_nm, {})
                            # Genuine overload (2+ `def <name>(...)` in the
                            # exporting module's own source, distinguished
                            # only by parameter TYPE — `exports`/`sym_info`
                            # above is a single-signature reflection/scan
                            # result, whichever overload the loader happened
                            # to pick, almost always the first declared).
                            # Register into `_imported_overloads` so
                            # `_lower_call` (gimple_gen_calls.py) routes each
                            # CALL SITE through `_elaborate_overload_call`'s
                            # real per-argument-type signature match instead
                            # of blindly emitting a call to this one cached
                            # signature's mangled symbol regardless of the
                            # actual argument types. Previously this
                            # registration only ever happened in link-mode's
                            # separate `_register_link_imports` pass — a
                            # plain (non-link-mode) top-level `from X import
                            # f` never populated it at all, so an overloaded
                            # free function reached this way silently always
                            # called whichever overload `exports.get(name)`
                            # returned. Real repro: pwd.mojo's `from ._macos
                            # import _getpw_macos` — `_getpw_macos(uid:
                            # UInt32)` / `_getpw_macos(var name: String)` —
                            # `getpwnam(name: String)`'s `_getpw_macos(name)`
                            # called the `(UInt32)` overload, truncating the
                            # `char *` argument to `uint32_t` (a real
                            # `-Wpointer-to-int-cast` warning, not just a
                            # diagnostic).
                            try:
                                _ov_pi = self._parsed_import(s.module)
                                _ov_path = _ov_pi[0]
                                if _ov_path:
                                    # The source `_parsed_import` already read and
                                    # cached for this module, not a fresh
                                    # `open(...).read()` per imported symbol (each
                                    # read was a whole file that nothing freed:
                                    # ~800 MB on `--dump-full fire.py`).
                                    _ov_src = _as_str(_ov_pi[1])
                                    if len(re.findall(
                                            rf'\b(?:fn|def)\s+{re.escape(_rs_nm)}\s*\(',
                                            _ov_src)) > 1:
                                        self._imported_overloads.setdefault(sym_name, _ov_path)
                            except Exception:
                                pass
                            # A compiled free-function generator in another
                            # module of this whole-program compile: bind the
                            # alias to that module's api (via the shared
                            # (home-qualifier, name) registry) instead of
                            # registering an ORDINARY imported symbol —
                            # Phase 2a skipped ordinary emission for it in
                            # its defining module, so an ordinary extern +
                            # call site would reference a symbol nothing
                            # defines ("too many arguments to function
                            # 'a_walk_...'; expected 0"). do_imports-only:
                            # cross-module generator units are only emitted/
                            # linked on the inline-compile pipeline.
                            if not s.wildcard and self.do_imports:
                                # Two candidate defining-module spellings,
                                # probed in order: (1) the MODULE ITSELF
                                # (`from pkg import gen_fn` — the generator
                                # lives IN pkg's own source, registry key
                                # '<pkg>::gen_fn'); (2) the MEMBER-PATH form
                                # (_join_import_member: `from . import sub`
                                # binds the SUBMODULE FILE compiled under
                                # '.sub', whose own generators register as
                                # '<_sub>::<fn>'). The blind f"{module}.{name}"
                                # spelling double-counted depth for bare-
                                # relative modules ('.' + '.' + 'sub' ==
                                # '..sub', level 2) and never matched.
                                _gmh_api = (
                                    self._generator_home_api.get(
                                        s.module.replace('.', '_').replace('-', '_') + '::' + _rs_nm)
                                    or self._generator_home_api.get(
                                        gimple_ctypes._join_import_member(s.module, _rs_nm)
                                        .replace('.', '_').replace('-', '_') + '::' + _rs_nm))
                                if _gmh_api is not None:
                                    self._imported_generator_bindings[sym_name] = _gmh_api
                                    continue
                            _register_sym(self, s, sym_name, _rs_nm, sym_info, _sib_qualifier, _sib_is_local_project)
                except Exception:
                    _debug_note('error registering sibling module imports', s.module)
            else:
                _debug_note('module load failed while registering imports')
                if not s.wildcard:
                    for _fip18 in (getattr(s, 'name_alias_strs', None) or []):
                        _fb_name = gimple_ctypes._fi_name(_fip18)
                        _fb_alias = gimple_ctypes._fi_alias(_fip18)
                        _fb_sym = _fb_alias if _fb_alias else _fb_name
                        # Same generator-binding rule as the resolved-exports
                        # branch above: exports can fail to load while the
                        # module itself still compiled fine as part of this
                        # same program's closure (its generators are in the
                        # registry either way).
                        if self.do_imports:
                            # Same two-candidate probe as the resolved-exports
                            # branch above (module-itself key first, then the
                            # _join_import_member member-path key for a
                            # bare-relative submodule binding).
                            _fb_gmh = (
                                self._generator_home_api.get(
                                    s.module.replace('.', '_').replace('-', '_') + '::' + _fb_name)
                                or self._generator_home_api.get(
                                    gimple_ctypes._join_import_member(s.module, _fb_name)
                                    .replace('.', '_').replace('-', '_') + '::' + _fb_name))
                            if _fb_gmh is not None:
                                self._imported_generator_bindings[_fb_sym] = _fb_gmh
                                continue
                        if self._from_import_name_is_submodule(s.module, _fb_name):
                            self.imported_symbols[_fb_sym] = {
                                # Same canonical member-module string the
                                # submodule's temp_gen was compiled under (see
                                # _join_import_member) — the coroutine emitter's
                                # bound-module generator resolution reads THIS.
                                'module': gimple_ctypes._join_import_member(s.module, _fb_name),
                                'return_type': 'unknown',
                            }
                            self._module_alias_names.add(_fb_sym)
                            continue
                        self._unresolved_import_aliases.add(_fb_sym)

    all_functions = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    self._cpp_module_fn_asts = {}
    for _fn_ast in all_functions:
        if isinstance(_fn_ast, FunctionDef):
            self._cpp_module_fn_asts.setdefault(_fn_ast.name, _fn_ast)
    def _is_foreign_main(s):
        return isinstance(s, FunctionDef) and s.name == 'main' and s not in stmts
    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef) and s.return_type is not None:
            self.func_return_types[s.name] = self._resolve_type(s.return_type)
            _ggf_dup._record_home_def_return_type(
                self, s, s.name, self.func_return_types[s.name])
        _s_pts = None
        if isinstance(s, FunctionDef) and s.params:
            if gimple_ctypes._params_have_vararg(s.params):
                _s_pts = self._signature_ctypes(s.params, s)
                self.func_param_types[s.name] = _s_pts
                self._note_vararg_trailing_param_types(s)
            else:
                _s_pts = _free_func_param_ctypes(self, s)
                self.func_param_types[s.name] = _s_pts
        # Does THIS gen's resolution tiers (`_func_csym`/`_effective_param_
        # types`: own top-level defs first, then lexical import scopes, then
        # home-module records, then the oscillating shared slot) resolve
        # `s.name` to `s` ITSELF? Only then may `s` register its per-def
        # auxiliary tables under the tiers-derived mangled key.
        # BUG-2026-052: this loop iterates EVERY module's stmts of the whole
        # transitive closure (`all_functions = stmts + imported_stmts`), but
        # `_func_csym(s.name)` resolves by BARE NAME — so when two sibling
        # modules both define a same-named free function, each unit's own
        # def claims those tiers (tier 1), and a FOREIGN homonym flowing
        # through this same loop later registered ITS data under the LOCAL
        # def's mangled symbol. Real instance: re/_compiler.py's
        # `_compile(code, pattern, flags)` (no defaults) vs codeop.py's
        # unrelated homonym `_compile(source, filename, symbol,
        # incomplete_input=True, *, flags=0)` — codeop's trailing defaults
        # landed under re/_compiler's mangled key
        # (`__compiler__compile_132aaf`), and every default-padding lookup
        # at re/_compiler's own call sites then found TWO spurious trailing
        # slots to fill (GCC "too many arguments ... expected 3, have 5" at
        # all 20 recursive `_compile(...)` statement calls). The owning
        # unit's OWN pass already registers each def under the symbol ITS
        # tiers derive — skipping a foreign homonym here is purely
        # de-poisoning; single-definition names (the overwhelming common
        # case, incl. every cross-module default-padding consumer) still
        # register exactly as before.
        # Deliberately an IDENTITY check only, with no tier-SHAPE probe:
        # consulting `_effective_param_types` here would resolve through
        # `_local_def_pts`, whose lazy memo would then freeze every def's
        # param ctypes at this loop's EARLY point — before Pass 1.x param
        # inference (and the struct registration passes further down
        # gen_module) have settled them — and `_emit_call`'s argument
        # coercion reads exactly that memoized shape via `_func_csym`'s
        # mangled-key mirror, so an early freeze regressed every
        # unannotated-param callee's call sites to int64_t coercion
        # ("makes pointer from integer without a cast" across typing.py's
        # `_type_check` callers) before the probe idea was reverted.
        _s_owns_tiers = True
        if isinstance(s, FunctionDef):
            _ldn_owner = (getattr(self, '_local_def_nodes', None) or {}).get(s.name)
            if _ldn_owner is not None and _ldn_owner is not s:
                _s_owns_tiers = False
        if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
            _dflts = getattr(s, 'param_defaults', None) or {}
            if _dflts and _s_owns_tiers:
                try:
                    _mangled = self._func_csym(s.name)
                except Exception:
                    _mangled = None
                if _mangled:
                    self._func_param_defaults[_mangled] = [
                        (pn, _dv) for pn, _dv in _dflts.items()]
        if isinstance(s, FunctionDef):
            _kw_i = -1
            _ci = 0
            _seen_star = False
            for _pn, _pt in (s.params or []):
                if _pn.startswith('**'):
                    _kw_i = _ci
                    break
                if _pn.startswith('*'):
                    if _seen_star:
                        continue
                    _seen_star = True
                _ci += 1
            if _kw_i >= 0:
                self._func_kwargs_slot[s.name] = _kw_i
                self._func_kwargs_has_vararg[s.name] = _seen_star
                if _s_owns_tiers:
                    try:
                        _mangled_kw_name = self._func_csym(s.name)
                        self._func_kwargs_slot[_mangled_kw_name] = _kw_i
                        self._func_kwargs_has_vararg[_mangled_kw_name] = _seen_star
                    except Exception:
                        pass
            # Same walk, recording the packed-parameter shape for a function
            # taken as a VALUE (see `_variadic_func_shape`'s own comment).
            # `_kw_i` above stops at the first `**`; this one needs the
            # leading ordinary-parameter count too, so it is its own loop.
            _vf_nfixed = 0
            _vf_kind = -1
            for _pn, _pt in (s.params or []):
                if _pn.startswith('**'):
                    _vf_kind = 1 if _vf_kind == 0 else 2
                elif _pn.startswith('*'):
                    if _vf_kind < 0:
                        _vf_kind = 0
                elif _vf_kind < 0:
                    _vf_nfixed += 1
            if _vf_kind >= 0 and _vf_nfixed <= 4:
                self._variadic_func_shape[s.name] = (_vf_nfixed, _vf_kind)
                if _s_owns_tiers:
                    try:
                        self._variadic_func_shape[self._func_csym(s.name)] = (
                            _vf_nfixed, _vf_kind)
                    except Exception:
                        pass
        if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
            self._mangled_funcs.add(s.name)
        if isinstance(s, FunctionDef) and 'export' in (getattr(s, 'decorators', None) or []):
            self._extra_no_mangle.add(s.name)

    _own_top_level_func_names = {s.name for s in stmts if isinstance(s, FunctionDef)}

    for s in stmts:
        if isinstance(s, FunctionDef) and s.name in _own_top_level_func_names:
            _gmi_scan_func_body_for_self_attr(self, s.name, s.body)

    def _scan_module_level_for_func_attrs(body):
        """`f.attr = value` written at MODULE level (not inside `f`'s own
        body) — e.g. Lib/test/support/__init__.py's
        `print_warning.orig_stderr = sys.stderr`, a statement directly in
        the module body AFTER the def. The per-function scans above only
        ever looked at each function's OWN body, so such writes were never
        registered into `_func_attrs`: the write fell through to dynamic
        setattr on the boxed function pointer, and the matching read
        (`stream = print_warning.orig_stderr`) fell through to "call the
        bare function name then runtime-getattr the result" — emitting an
        undeclared, un-mangled C symbol ("implicit declaration of function
        'print_warning'"). One walk over the module-level statement tree,
        NOT entering FunctionDef bodies (those are covered by the
        per-function scans above), registering every hit whose target name
        is one of this module's own top-level functions."""
        _stack = list(body)
        while _stack:
            _fstmt = _stack.pop(0)
            if isinstance(_fstmt, (FunctionDef, ImportStmt, FromImportStmt)):
                continue
            if (isinstance(_fstmt, AssignStmt)
                    and isinstance(_fstmt.target, MemberExpr)
                    and isinstance(_fstmt.target.obj, IdentExpr)
                    and _fstmt.target.obj.name in _own_top_level_func_names):
                fname = _fstmt.target.obj.name
                attr = _fstmt.target.member
                self._func_attrs.setdefault(fname, {})
                if attr not in self._func_attrs[fname]:
                    mangled = f"_funcattr_{fname}__{attr}"
                    self._func_attrs[fname][attr] = mangled
                    self._global_var_types.setdefault(mangled, 'int64_t')
                    self._global_c_decl_types.setdefault(mangled, 'int64_t')
            elif isinstance(_fstmt, IfStmt):
                _stack.extend(_fstmt.then_body)
                for _, _eb in _fstmt.elifs:
                    _stack.extend(_eb)
                if _fstmt.else_body:
                    _stack.extend(_fstmt.else_body)
            elif isinstance(_fstmt, (WhileStmt, ForStmt)):
                _stack.extend(_fstmt.body)
            elif isinstance(_fstmt, TryStmt):
                _stack.extend(_fstmt.body)
                for _h in (_fstmt.handlers or []):
                    _stack.extend(_h.body)
                if _fstmt.else_body:
                    _stack.extend(_fstmt.else_body)
                if _fstmt.finally_body:
                    _stack.extend(_fstmt.finally_body)

    if _own_top_level_func_names:
        _scan_module_level_for_func_attrs(stmts)

    all_structs_for_methods = (stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
                                + self._imported_typedef_structs)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            s = _as_structdef_node(s)  # boxed loop var -> direct field access on the compiled path
            # Record every (struct, method) whose name is OVERLOADED — declared
            # more than once — because the UNSUFFIXED C symbol for it is
            # defined by NEITHER overload: two overloads of one source name are
            # two symbols, each suffixed by a hash of its real C parameter
            # types (`__iter___0120be`, `__iter___0120be_2`).
            #
            # `func_return_types` still gets its bare `{Struct}_{method}` entry
            # (removing it was measured and it is WRONG: the
            # forward-declaration emitter falls back to its variadic-sentinel
            # parameter list for the suffixed names and then the definition and
            # the declaration disagree — `error: conflicting types for
            # 'std_collections_set_Set___iter___0120be'; have 'int64_t(Set *)'
            # ... previous definition ... with type 'int64_t(Set *, ...)'` on
            # std/collections/set.mojo). So the ambiguity is published as its
            # OWN registry instead, and the two consumers that dispatch THROUGH
            # a method by its bare name consult that:
            #
            #   emit_loops._gen_for_struct_iter's `if iter_fn in
            #   gen.func_return_types:` then emits `{Struct}___iter__(obj)` —
            #   measured, test/itertools/test_repeat.mojo linked with
            #   `Undefined symbols: __RepeatIterator_11_ElementType_5_Int64_
            #   ___iter__` called from both of its `for` loops, while the object
            #   defined only `_0120be` and `_0120be_2`.
            #   emit_calls._lower_call's `next(<struct>)` branch reads the same
            #   key for `__iter__` to discover a possibly-different iterator
            #   type — harmless there only because the value it then reads
            #   (`_rit`) resolves to nothing, so the receiver's own type is
            #   kept. Correct by accident rather than by construction.
            #
            # With the entry consulted, `__iter__` behaves as it must for an
            # ambiguous method: the consumer keeps the receiver's own type,
            # which is the correct answer for every iterator in `std/iter`
            # (`__iter__` returns `Self` / `Self.IteratorOwnedType`, and
            # `comptime IteratorOwnedType: Iterator = Self`).
            _dup_names: set = set()
            _seen_m: set = set()
            for _dm in s.methods:
                if _dm.name in _seen_m:
                    _dup_names.add(_dm.name)
                _seen_m.add(_dm.name)
            for _dn in _dup_names:
                self._ambiguous_struct_methods.add((_as_str(s.name), _dn))
            for m in s.methods:
                mangled = f"{s.name}_{m.name}"
                if m.return_type is not None:
                    self.func_return_types[mangled] = self._resolve_type(m.return_type)
                if hasattr(m, 'decorators') and 'staticmethod' in (m.decorators or []):
                    self._static_methods.add(mangled)
                if ((hasattr(m, 'decorators') and 'classmethod' in (m.decorators or []))
                        or m.name in ('__init_subclass__', '__class_getitem__')):
                    self._classmethod_names.add(mangled)
                if m.params:
                    ctypes = []
                    for i, (pn, pt) in enumerate(m.params):
                        if i == 0 and pn == 'self':
                            ctypes.append(f"{s.name} *")
                        else:
                            ctypes.append(self._param_ctype(pn, pt, m))
                    if mangled not in self.func_param_types:
                        self.func_param_types[mangled] = ctypes

    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef) and s.return_type is None:
            # `current_func_name` save/set/restore, mirroring the identical,
            # already-correct pattern a few hundred lines below (the
            # `_p3b_s` pass) — without it, `_infer_return_type`'s
            # `_collect_return_types` -> `_quick_type` -> `_closure_info_
            # for_ident` lookup keys `_all_closures` by `gen.current_func_
            # name`, which was left at WHATEVER unrelated value (often "")
            # an earlier pass last set it to. A `return <nested_fn>` (e.g.
            # `make_adder`'s `return add`) then couldn't find its own
            # nested function's ClosureInfo and fell to the plain int64_t
            # default instead of the real `MojoBoundMethod *`/`void *` —
            # a closure-returning function's return type silently
            # mistyped on this pass (later passes may re-derive it
            # correctly, but any reader between the two sees the wrong
            # value, and self-hosted output showed the wrong one winning).
            # `_as_funcdef_node`, not the bare `s`: `all_functions` is a
            # heterogeneous statement list, so its element type is opaque
            # int64_t regardless of the isinstance filter — `s.params`
            # would otherwise go through the dynamic getattr path.
            _as_s_p1 = _as_funcdef_node(s)
            _saved_fcn_p1 = self.current_func_name
            self.current_func_name = _as_s_p1.name
            # Index, don't unpack: `for pname, ptype in params:` boxes the
            # tuple elements to int64_t on the self-hosted path even when
            # `params` itself is a properly-typed MojoList* (the
            # established boxing bug this file works around everywhere
            # else — see e.g. the AssignStmt-target zip comment in
            # gimple_gen_resolve.py).
            #
            # NOTE: this loop's `self.var_types[pname[1:]] = 'MojoList *'`
            # was ALSO hit by a real, separate parser bug (now fixed in
            # `_parse_postfix`, fire_compiler.py): `X[Y[a:b]]` — a subscript
            # whose single index is itself a nested slice expression —
            # mis-attached the nested slice's already-resolved `.obj` (Y)
            # to the OUTER object (X), silently turning `self.var_types
            # [pname[1:]]` into `self.var_types[1:]` (pname discarded
            # entirely). That miscompiled the very statement below into a
            # slice-ASSIGNMENT on `self.var_types` itself, calling
            # `mojo_list_splice` with a bogus target/bounds and SIGSEGV'ing
            # — reproducible only once compilation actually reached a real
            # sibling module (myinterpreter.py) whose own `def f(*args,
            # **kwargs)` shape exercised this exact line. See
            # `_parse_postfix`'s `if isinstance(only, SliceExpr) and
            # only.obj is None:` fix for the real root cause; the
            # index-don't-unpack change here remains worth keeping since
            # `params`-tuple-unpack boxing is a real, independent gap.
            _p1_params = _as_s_p1.params
            for _p1i in range(len(_p1_params)):
                pname = _as_str(_p1_params[_p1i][0])
                ptype = _p1_params[_p1i][1]
                if pname.startswith('**'):
                    self.var_types[pname[2:]] = 'MojoDict *'
                elif pname.startswith('*'):
                    self.var_types[pname[1:]] = 'MojoList *'
                else:
                    self.var_types[pname] = self._resolve_type(ptype)
            inferred = self._infer_return_type(_as_s_p1.body)
            if _as_s_p1.name == 'main' and inferred == 'void':
                inferred = 'int64_t'
            self.func_return_types[_as_s_p1.name] = inferred
            _ggf_dup._record_home_def_return_type(
                self, s, _as_s_p1.name, inferred)
            self.var_types.clear()
            self.current_func_name = _saved_fcn_p1

    for _pass2b_iter in range(4):
        _changed = False
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                s = _as_structdef_node(s)  # boxed loop var -> direct field access on the compiled path
                for m in s.methods:
                    self._struct_method_names.setdefault(s.name, set()).add(m.name)
                    if 'property' in (getattr(m, 'decorators', None) or []):
                        self._struct_property_names.setdefault(s.name, set()).add(m.name)
                    if m.name == '__init__':
                        self._struct_has_init.add(s.name)
                        # Plain unpack loops, NOT comprehensions — see
                        # bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md.
                        _sip_list = []
                        for _sipn, _sipt in m.params:
                            if _sipn != 'self':
                                _sip_list.append(_sipn)
                        self._struct_init_params[s.name] = _sip_list
                        _init_defaults = getattr(m, 'param_defaults', {}) or {}
                        _sid_dict = {}
                        for _sidn in _init_defaults:
                            if _sidn != 'self':
                                _sid_dict[_sidn] = _init_defaults[_sidn]
                        self._struct_init_defaults[s.name] = _sid_dict
                    if m.return_type is None:
                        _mangled_key = f"{s.name}_{m.name}"
                        for i, (pname, ptype) in enumerate(m.params):
                            if pname == 'self':
                                self.var_types[pname] = f"{s.name} *"
                            elif (i == 0 and pname == 'cls'
                                    and _mangled_key in self._classmethod_names):
                                # `cls`, a real @classmethod's implicit first
                                # param, statically names THIS enclosing
                                # struct — mirrors the `self` seed just
                                # above. Without this, `_quick_type`'s
                                # return-type scan saw `cls` as an
                                # unresolved bare identifier (falling to
                                # the int64_t default), so a classmethod
                                # whose body does `return cls.<method>(...)`
                                # (Lib/tarfile.py's `TarInfo.fromtarfile`:
                                # `return cls._fromtarfile(tarfile)`) never
                                # got its real struct-pointer return type —
                                # `_quick_type`'s existing
                                # `gen.var_types.get(mod, '')`-based struct-
                                # method-call resolution (used by ordinary
                                # `obj.method(...)` calls) already handles
                                # this correctly once `cls` is seeded the
                                # same way `self` is; only the seed was
                                # missing. See CODEGEN_generator_function_
                                # Lib_tarfile.md.
                                self.var_types[pname] = f"{s.name} *"
                            else:
                                self.var_types[pname] = self._resolve_type(ptype)
                        # Seed inferred LOCAL var types (see
                        # `gimple_ctypes._seedable_local_ctype` for the rule
                        # and for why the three call sites share it):
                        # `return <local>` where the local holds a pointer
                        # value must not fall to the int64_t default.
                        # COMPILE_FAIL_zipfile___init__.md.
                        try:
                            for _vn, _vt in self._infer_local_var_types(m).items():
                                if gimple_ctypes._seedable_local_ctype(_vt):
                                    self.var_types.setdefault(_vn, _vt)
                        except Exception:
                            pass
                        inferred = self._infer_return_type(m.body)
                        key = _mangled_key
                        if self.func_return_types.get(key) != inferred:
                            self.func_return_types[key] = inferred
                            _changed = True
                        self.var_types.clear()
        if not _changed:
            break

    _p2c_base_var_types = dict(self.func_return_types)
    # Which functions hand back a value whose per-slot kinds are recorded
    # on the VALUE (see _infer_return_maybe_kinds). Answered ONCE, before the
    # fixpoint below, and NOT inside it: it is a pure function of a body, so
    # the 8 iterations could only ever repeat the same walk, and they do —
    # measured, putting it in the loop made `test_silent_noop_iter.py` go
    # from 5m00s to 19m48s on the same machine, because `_walk_ast`
    # materialises the WHOLE body as a node list and Pass 2c already runs it
    # over every function (twice: free functions and methods) up to 8 times
    # per nesting level. Memoised by body identity so a body is walked once
    # per compile even when the enclosing structure revisits it.
    def _mk_round(callee_kinds):
        # A FRESH cache per round, and that is load-bearing rather than
        # wasteful: the answer depends on `callee_kinds`, so a cache shared
        # across rounds would hand round 2 round 1's answers and the
        # fixpoint would never move. Within a round the cache is what keeps
        # it cheap — memoised by body identity, NOT by `(body, params)`,
        # because two definitions never share a body node and the params
        # are that node's own.
        _mk_cache: dict = {}

        def _mk(name, body, params=None):
            _k = id(body)
            _v = _mk_cache.get(_k)
            if _v is None:
                _v = _mk_cache[_k] = _infer_return_maybe_kinds(
                    self, body, params, callee_kinds)
            _maybe, _slotkinds = _v
            if _maybe:
                self._return_maybe_kinds.add(name)
            if _slotkinds:
                # A returned HETEROGENEOUS list literal, per slot. The
                # boolean table above only reaches the call site as "ask
                # the runtime", which is enough for a computed subscript
                # and not enough for `a[2]`; this one reaches it as the
                # exact kind of every slot, in the same long-form spelling
                # `gen._struct_slot_kinds` carries for a `struct.unpack`
                # result, so the statically indexed reads pick their
                # accessor from it unchanged.
                self._return_value_slot_kinds[name] = _slotkinds

        for s in all_functions:
            if not _is_foreign_main(s) and isinstance(s, FunctionDef):
                _mk(s.name, s.body, s.params)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                _sk = _as_structdef_node(s)
                for _m in _sk.methods:
                    if _m.name != '__init__':
                        _mk(f"{_sk.name}_{_m.name}", _m.body, _m.params)

    # Fixpoint, because the second half of the question is "does this
    # function hand back what ANOTHER function hands back", and one
    # function's answer can depend on another's. Bounded at four rounds:
    # `self._return_maybe_kinds` only ever GROWS here, so the loop is
    # monotone and the bound is a depth limit rather than a convergence
    # guess. Round 1 passes no callee set (it is the round that finds the
    # producers); rounds 2+ read the set the earlier rounds filled.
    # Deliberately NOT inside Pass 2c's fixpoint below: `_walk_ast`
    # materialises a whole body as a node list and that loop already runs
    # over every function eight times per nesting level — putting a walk
    # in there cost test_silent_noop_iter 5m00s -> 19m48s when it was tried.
    _mk_round(None)
    for _mk_iter in range(3):
        _mk_before = len(self._return_maybe_kinds)
        _mk_round(self._return_maybe_kinds)
        if len(self._return_maybe_kinds) == _mk_before:
            break
    for _pass2c_iter in range(8):
        _c_changed = False
        for s in all_functions:
            if _is_foreign_main(s) or not isinstance(s, FunctionDef):
                continue
            # `def ident(x): return x` — the one shape whose result IS an
            # argument, so a call site can answer for itself instead of
            # inheriting the one program-wide answer `_return_elem_types`
            # can hold. Recorded here, beside that table, because both are
            # facts about a function's BODY read in the same pass; see
            # `_passthrough_param_idx`'s own comment for what the answer is
            # worth without it.
            #
            # The whole body must be the `return`, and the returned name must
            # be one of the declared parameters: `return x` where `x` is a
            # LOCAL, or a body with a second statement, is a different
            # function and gets no entry (the conservative answer, which is
            # what every other caller relies on).
            if (isinstance(s.body, list) and len(s.body) == 1
                    and type(s.body[0]).__name__ == 'ReturnStmt'):
                _pv = getattr(s.body[0], 'value', None)
                if isinstance(_pv, IdentExpr):
                    # `enumerate`, not a value unpack: the POSITION is half
                    # the answer (the call site looks its argument up by
                    # index), and a `[a for a, b in xs]`-shaped unpack of a
                    # `list[tuple[str, str]]` boxes both slots to int64_t on
                    # the self-hosted compiled path.
                    for _ppi, _ppair in enumerate(s.params or []):
                        if _as_str(_ppair[0]) == _as_str(_pv.name):
                            self._passthrough_param_idx[s.name] = _ppi
                            break
            _ret_elem = self._infer_return_elem_type(
                s.body, func_def=s, _base_var_types=_p2c_base_var_types)
            if _ret_elem is None:
                _ret_elem = _homogeneous_tuple_ann_elem(self, s.return_type)
            if _ret_elem is not None and self._return_elem_types.get(s.name) != _ret_elem:
                self._return_elem_types[s.name] = _ret_elem
                _c_changed = True
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                s = _as_structdef_node(s)  # boxed loop var -> direct field access on the compiled path
                self._prepass_struct = s.name
                for m in s.methods:
                    if m.name == '__init__':
                        continue
                    _ret_elem = self._infer_return_elem_type(
                        m.body, _base_var_types=_p2c_base_var_types)
                    _key = f"{s.name}_{m.name}"
                    # A homogeneous `tuple[T, T[, ...]]` return annotation is
                    # authoritative for the caller's unpacking accessor — body
                    # inference can miss it when a slot is a reassigned local
                    # or a ternary (e.g. GimpleGen._decode_str_literal_text's
                    # `return val, ('1' if is_fstring else '')`, both char*,
                    # was unpacked via mojo_list_get_int → the boxed char* read
                    # back as 0 → empty string-pool entries for every user
                    # StringLiteral once self-hosted).
                    if _ret_elem is None:
                        _ret_elem = _homogeneous_tuple_ann_elem(self, m.return_type)
                    if _ret_elem is not None and self._return_elem_types.get(_key) != _ret_elem:
                        self._return_elem_types[_key] = _ret_elem
                        _c_changed = True
        self._prepass_struct = None
        if not _c_changed:
            break

    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            s = _as_structdef_node(s)  # boxed loop var -> direct field access on the compiled path
            _moids = self._struct_method_overload_ids(s)
            for _zmi in range(len(s.methods)):
                m = _as_funcdef_node(s.methods[_zmi]); _oid = _as_str(_moids[_zmi]) if _zmi < len(_moids) else ""
                _has_self_first = bool(m.params) and m.params[0][0] == 'self'
                _params_no_self = m.params[1:] if _has_self_first else m.params
                # Sentinel is -1, NOT None: this compiler models None as 0,
                # so a `def m(self, *args)` whose star param IS at index 0
                # would be indistinguishable from "no star param" once
                # self-hosted (`_star_idx is not None` -> `0 != 0` -> False),
                # silently giving a varargs method max_arity 0. -1 is
                # unambiguous for an index under both evaluators.
                # Plain loops throughout this block, NOT comprehensions/
                # genexprs with tuple-unpack targets — see
                # bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md.
                _star_idx = -1
                for _psi in range(len(_params_no_self)):
                    _psn = _params_no_self[_psi][0]
                    if _psn.startswith('*') and not _psn.startswith('**'):
                        _star_idx = _psi
                        break
                real_params = []
                for _rpn, _rpt in _params_no_self:
                    if not (_rpn.startswith('*') and not _rpn.startswith('**')):
                        real_params.append((_rpn, _rpt))
                _defaults = m.param_has_default or {}
                if _star_idx >= 0:
                    _pre_star = _params_no_self[:_star_idx]
                    min_arity = 0
                    for _psn2, _pst2 in _pre_star:
                        if _psn2 not in _defaults:
                            min_arity += 1
                    max_arity = float('inf')
                else:
                    min_arity = 0
                    for _rpn2, _rpt2 in real_params:
                        if _rpn2 not in _defaults and not _rpn2.startswith('**'):
                            min_arity += 1
                    max_arity = len(real_params)
                # Call the FREE `_signature_ctypes(gen, ...)`, NOT the
                # `GimpleGen` method `self._signature_ctypes(...)`: this
                # module's `gen_module_impl(self, stmts)` has its `self`
                # parameter boxed to opaque int64_t (its signature is cached
                # before the GimpleGen registry pre-pass runs, so
                # `_selfhost_gen_self_param_ctype` cannot type it), which
                # makes every `self.<method>()` here a scalar-receiver stub
                # that just returns the receiver — so `_all_ctypes` became
                # `self` reinterpreted as a list and `param_ctypes` garbage,
                # and a later `len(cand['param_ctypes'])` in
                # `_resolve_overload`'s `_score` SIGSEGV'd in
                # `mojo_list_len(0x1)` while compiling
                # std/collections/dict.mojo. The free function names its
                # first param `gen`, which IS typed `GimpleGen *`.
                _all_ctypes = _ggf_dup._signature_ctypes(self, m.params, m, s.name)
                param_ctypes = _all_ctypes[1:] if _has_self_first else _all_ctypes
                if _star_idx >= 0:
                    param_ctypes = [c for c in param_ctypes if c != '...']
                if m.return_type is not None:
                    _ret_base = m.return_type.split('[', 1)[0].strip() if isinstance(m.return_type, str) else ''
                    if (_ret_base == s.name
                            and s.name in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer')):
                        _ret_type = f"{s.name} *"
                    else:
                        _ret_type = self._resolve_type(m.return_type)
                else:
                    _saved_var_types = self.var_types
                    _scratch_mark_sm: int = self._scan_scratch_top
                    self.var_types = self._scratch_dict_copy(_saved_var_types)
                    self.var_types['self'] = f"{s.name} *"
                    for _pn, _pt in real_params:
                        self.var_types[_pn] = self._resolve_type(_pt)
                    # Seed inferred LOCAL variable types too, so a
                    # `return <local>` whose local holds a pointer value
                    # (`out = self._buf[a:]; out += chunk; return out` ->
                    # MojoBytes *, or the plain `t = self.<field>; return
                    # t` -> char *) picks the right C return type instead
                    # of the int64_t default — a wrong int64_t return then
                    # makes every caller treat the pointer as a scalar
                    # (COMPILE_FAIL_zipfile). Same shared rule as the
                    # Pass-2b site above; see
                    # `gimple_ctypes._seedable_local_ctype`.
                    try:
                        for _vn, _vt in self._infer_local_var_types(m).items():
                            if gimple_ctypes._seedable_local_ctype(_vt):
                                self.var_types.setdefault(_vn, _vt)
                    except Exception:
                        pass
                    _ret_type = self._infer_return_type(m.body)
                    self.var_types = _saved_var_types
                    self._scan_scratch_top = _scratch_mark_sm
                # Self-hosting bootstrap: the frozen GimpleGen signature
                # table is authoritative — override this pass's per-instance
                # inference so `_struct_method_signatures`, the method
                # externs, the forward decl and the definition all agree.
                _gg_sig = (self._selfhost_gimplegen_sigs or {}).get(
                    f"GimpleGen_{m.name}") if s.name == 'GimpleGen' and not _oid else None
                if _gg_sig is not None:
                    _fz_ret, _fz_params, _ = _gg_sig
                    _ret_type = _fz_ret
                    _all_ctypes = list(_fz_params)
                    param_ctypes = _all_ctypes[1:] if _has_self_first else _all_ctypes
                    max_arity = len(param_ctypes)
                key = _sms_key(s.name, m.name)
                # Plain unpack loop, NOT a comprehension.
                _rp_names = []
                for _rpn3, _rpt3 in real_params:
                    _rp_names.append(_rpn3)
                self._struct_method_signatures.setdefault(key, []).append({
                    'overload_id': _oid,
                    'param_names': _rp_names,
                    'param_ctypes': param_ctypes,
                    'min_arity': min_arity,
                    'max_arity': max_arity,
                    'ret_type': _ret_type,
                    'has_varargs': _star_idx >= 0,
                    'pre_star_count': _star_idx if _star_idx >= 0 else None,
                })
                self._mangled_signature_ctypes[f"{s.name}_{m.name}{_oid}"] = _all_ctypes

    for s in self._imported_typedef_structs:
        # `_as_structdef_node`: `s` is a boxed loop var on the self-hosted
        # compiled path, so `s.methods` / `s.name` erased to
        # `_mojo_dispatch_getattr` and `range(len(s.methods))` was `range(0)`
        # — NO `GimpleGen__*` method externs emitted at all (~1400 lines of
        # the MOJO_NO_SHIM=1 stage1-vs-stage2 fire.ci divergence).
        s = _as_structdef_node(s)
        if not s.methods:
            continue
        _s2850_oids = self._struct_method_overload_ids(s)
        for _zmi in range(len(s.methods)):
            m = _as_funcdef_node(s.methods[_zmi]); _oid = _as_str(_s2850_oids[_zmi]) if _zmi < len(_s2850_oids) else ""
            bare_mangled = f"{s.name}_{m.name}{_oid}"
            mangled = self._struct_method_csym(s.name, m.name, _oid)
            param_ctypes = self._mangled_signature_ctypes.get(bare_mangled)
            if param_ctypes is None:
                continue
            ret_type = None
            for _cand in self._struct_method_signatures.get(_sms_key(s.name, m.name), []):
                if _cand.get('overload_id') == _oid:
                    ret_type = _cand.get('ret_type')
                    break
            if ret_type is None:
                ret_type = self.func_return_types.get(f"{s.name}_{m.name}", 'void' if m.name == '__init__' else 'int64_t')
            if any('...' in p for p in param_ctypes):
                params_str = '...'
            else:
                params_str = ', '.join(param_ctypes) or 'void'
            sig = f"{ret_type} {mangled} ({params_str})"
            guard = _stub_guard_name(mangled)
            decl = f"#ifndef {guard}\n#define {guard}\nextern {sig};\n#endif"
            if decl not in self._elaborated_externs:
                self._elaborated_externs.append(decl)
            if _oid:
                no_oid = self._struct_method_csym(s.name, m.name, '')
                bare_guard = _stub_guard_name(no_oid)
                bare_decl = f"#ifndef {bare_guard}\n#define {bare_guard}\nextern {ret_type} {no_oid} (...);\n#endif"
                if bare_decl not in self._elaborated_externs:
                    self._elaborated_externs.append(bare_decl)

    self._inferred_param_types: dict[str, dict[str, str]] = {}  # func_name -> {param_name -> type}
    # Function name -> parameter name -> container kind ('list'/'dict'/'set'),
    # for parameters every unambiguous literal CALL SITE agrees is a
    # container. Read only by the `==` / `!=` lowering, which cannot see
    # through an erased int64_t parameter and would otherwise emit a pointer
    # comparison for it. Filled by `_gmi_apply_call_site_param_evidence`
    # beside `_inferred_param_types` — a table of its own because THAT one
    # re-types parameters all over the backend, and a container entry there
    # has effects far past comparison.
    self._container_param_kinds: dict[str, dict[str, str]] = {}
    # Function name -> the NAMES of its parameters left at the `int64_t`
    # default whose call sites DISAGREE and include at least one string.
    # That set is exactly the provably-may-be-string set: a slot is in it
    # only because a `char *` literal was actually observed at one of its
    # call sites and an `int64_t` at another. It is the ONLY input the
    # runtime discriminator `mojo_cstr_or_int_str` may be applied to, because
    # that discriminator is unsound for an arbitrary int64_t: a value in
    # `[2^31, 2^47)` is pointer-SHAPED, so `print(2**40)` would hand a bare
    # integer to `strlen` and trade a SIGSEGV for a worse one. Keyed by
    # function name for the same reason `_container_param_kinds` is — a
    # forwarding chain's second hop is a DIFFERENT slot with the same shape.
    self._int64_may_hold_str: dict[str, set] = {}
    # Functions whose RETURN VALUE may hold a string, by the same route (a
    # `return` of a name in `_int64_may_hold_str`, or of another such
    # function's result). The other half of the same property: the sets above
    # are per-CALLING-scope names, and this is the whole-program answer for a
    # call site's own result, which is where most consumers meet the value —
    # `print(f(x))` never reads a parameter at all.
    self._ret_may_hold_str: set = set()
    # Function name -> its parameter NAMES in order. Populated here, in the
    # same pass that fills `_inferred_param_types`, because that map is keyed
    # by param NAME while a call site identifies a callee's parameter only by
    # POSITION: `analyze_param_usage` records `callee + _FC_SEP + arg_index`
    # and the decision step needs to turn that index back into a name to ask
    # "what did the callee infer for that parameter?". Looked up, never
    # computed, so there is no inference recursion.
    self._func_param_names: dict[str, list[str]] = {}
    # Which (function, param) pairs carry an EXPLICIT annotation. Needed
    # because "no use-derived evidence" and "annotated" look identical in
    # `_inferred_param_types` — `_infer_param_types` records an entry only
    # when the BODY says something — and `_param_ctype` consults that map
    # only for an UNANNOTATED parameter. So writing an entry for an
    # annotated one is not a no-op: it reaches the forward declaration
    # (`_signature_ctypes`, which does not have the annotation guard) and
    # not the definition, and the pair disagrees:
    #
    #     MojoList * make (MojoList *);      /* the declaration */
    #     MojoList * make (int64_t buf)      /* the definition */
    #
    # "conflicting types", a hard error. Real:
    # `fn make(buf: DynamicVector)` (test_gimple_runner.py's
    # `gimple_struct_mixed_reads_survive_a_function_boundary`), where the
    # annotation resolves to the generic box and the single call site
    # passes a list literal.
    # Nested dicts, NOT a set of `(fn, param)` tuples: a tuple key is hashed,
    # and on the self-hosted compiled path a str slot read out of an AST field
    # can arrive boxed, which is the whole reason `_as_str` guards every name
    # read in this file. Two dict lookups on an `_as_str`'d name each are the
    # pattern that does not depend on hashing (see `_inferred_param_types`).
    self._annotated_params: dict = {}
    for s in all_functions:
        if isinstance(s, FunctionDef):
            _sfn = _as_str(s.name)
            self._func_param_names[_sfn] = [
                _as_str(pn) for pn, _pt in (s.params or []) if not _as_str(pn).startswith('*')]
            _ann_for = self._annotated_params.get(_sfn)
            for _spn, _spt in (s.params or []):
                if _spt is not None:
                    if _ann_for is None:
                        _ann_for = {}
                        self._annotated_params[_sfn] = _ann_for
                    _ann_for[_as_str(_spn)] = True
    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_param_types[s.name] = self._infer_param_types(s)
    # Ground those use-derived parameter types in what callers pass, where the
    # two disagree and a call site is unambiguous. See
    # `_gmi_apply_call_site_param_evidence`.
    _gmi_apply_call_site_param_evidence(self, stmts)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            s = _as_structdef_node(s)
            for m in s.methods:
                m = _as_funcdef_node(m)
                key = f"{_as_str(s.name)}_{_as_str(m.name)}"
                self._inferred_param_types[key] = self._infer_param_types(
                    m, owner_struct=s.name)
    # Cross-module generator scalar contracts (see the pre-pass beside the
    # modules_to_compile loop that collects them): entries whose
    # home-module qualifier matches THIS compile's own module_name are
    # this module's own generators as seen from an importing module.
    # Merged here — AFTER the body-evidence pass above (which REPLACES
    # each function's whole entry, so an earlier merge would be wiped) and
    # before every consumer: the generator eligibility pass resolves each
    # unannotated param via _param_ctype from these, so the emitted
    # coroutine unit's signature and yield type carry the caller's real
    # char */double instead of int64_t defaults. Only ever non-empty for a
    # temp_gen compiling an imported module of a whole-program build (the
    # sharing block in _compile_imported_module); a root/self-host
    # compile's own qualifier never matches its own collected keys.
    if self._xmod_gen_param_hints and self.module_name:
        _xg_self_q = self.module_name.replace('.', '_').replace('-', '_')
        for _xg_key in self._xmod_gen_param_hints:
            # Composite "<qualifier>::<name>" string key, not a tuple —
            # see _xmod_gen_param_hints's docstring (gimple_codegen.py).
            _xg_hq, _xg_hfn = _xg_key.split('::', 1)
            if _xg_hq != _xg_self_q:
                continue
            _xg_pmap = self._xmod_gen_param_hints[_xg_key]
            _xg_tgt = self._inferred_param_types.setdefault(_xg_hfn, {})
            for _xg_pn in _xg_pmap:
                _xg_ct = _xg_pmap[_xg_pn]
                if _xg_ct and _xg_tgt.get(_xg_pn) in (None, 'int', 'int64_t'):
                    _xg_tgt[_xg_pn] = _xg_ct
    # Companion list-ELEMENT hints merge: same qualifier match as the scalar
    # hints above, applied into this gen's own _param_list_elem_types for
    # _gen_cpp_generator_unit to seed the coroutine-body emitter with.
    if getattr(self, '_xmod_gen_elem_hints', None) and self.module_name:
        _xe_self_q = self.module_name.replace('.', '_').replace('-', '_')
        for _xe_key in self._xmod_gen_elem_hints:
            _xe_hq, _xe_hfn = _xe_key.split('::', 1)
            if _xe_hq != _xe_self_q:
                continue
            _xe_pmap = self._xmod_gen_elem_hints[_xe_key]
            _xe_tgt = self._param_list_elem_types.setdefault(_xe_hfn, {})
            for _xe_pn in _xe_pmap:
                _xe_ct = _xe_pmap[_xe_pn]
                if _xe_ct and not _xe_tgt.get(_xe_pn):
                    _xe_tgt[_xe_pn] = _xe_ct
    # Cross-module CONSTRUCTOR field-type hints merge (see
    # _xmod_ctor_field_hints' docstring, gimple_codegen.py): same qualifier
    # match as the two hint merges above, but the key has a THIRD segment
    # (struct name) and the target is `struct_field_types` directly rather
    # than a per-function param map — this fires for THIS gen's own structs
    # as seen from an IMPORTING module's call sites, which the same-module
    # ctor-literal pass below (and its `_ctxlit_*` one-hop companion) can
    # never observe since neither scans a DIFFERENT module's call sites.
    # Applied here, before struct methods are emitted, so both the typedef
    # preamble (reads struct_field_types directly) and the `__init__` body's
    # own store codegen (reads it at emission time, later still) agree.
    if getattr(self, '_xmod_ctor_field_hints', None) and self.module_name:
        # `lstrip('.')` — the same canonicalization `_find_symbol_home_module`
        # documents and the producer above applies: this gen's `module_name`
        # is the import string that first pulled the module in, and a
        # RELATIVE spelling (`.sub`) canonicalizes with its leading dots
        # stripped, exactly as `_note_own_func_home` does when it records
        # this module's own free functions' home.
        _xf_self_q = self.module_name.lstrip('.').replace('.', '_').replace('-', '_')
        for _xf_key in self._xmod_ctor_field_hints:
            _xf_hq, _xf_hstruct, _xf_hfield = _xf_key.split('::', 2)
            if _xf_hq != _xf_self_q:
                continue
            if self._xmod_ctor_field_conflict.get(_xf_key):
                continue
            _xf_ct = self._xmod_ctor_field_hints[_xf_key]
            if not _xf_ct or _xf_hstruct not in self.struct_field_types:
                continue
            _xf_cur = self.struct_field_types[_xf_hstruct].get(_xf_hfield)
            if _xf_cur in (None, 'int', 'int64_t'):
                self.struct_field_types[_xf_hstruct][_xf_hfield] = _xf_ct

    self._inferred_var_types: dict[str, dict[str, str]] = {}  # func_name -> {var_name -> type}
    def _reconcile_param_container_kinds():
        """Rewrite `_inferred_param_types` where a parameter's USAGE evidence
        and its own body BINDINGS disagree about the container kind.

        The two estimators see different things, and only one of them can see
        the body: `_infer_param_types` reads uses (a subscript, an iteration, a
        method call, a call the name is passed to) and runs before this
        function exists; `resolve_shared._infer_local_var_types` reads
        bindings, every assignment to the name in the whole body through every
        branch. When they disagree about which CONTAINER it is, the binding
        answer wins — see `funcs_shared.param_binding_ctype` for the rule and
        why it is that narrow.

        Applied to the shared table rather than at a reader, because that
        table feeds the forward DECLARATION as well as the definition.
        Correcting only the definition is `conflicting types for 'pick'` at
        every call site, which is what the first attempt at this did.

        Must run after `_inferred_var_types` is populated and before any
        signature is emitted, which is why it is called from both of that
        table's population loops rather than from one of them.
        """
        for _rn in list(getattr(self, '_inferred_var_types', None) or {}):
            _rp = self._inferred_param_types.get(_rn)
            if not _rp:
                continue
            for _rpn in list(_rp.keys()):
                _fixed = funcs_shared.param_binding_ctype(self, _rn, _rpn, _rp[_rpn])
                if _fixed != _rp[_rpn]:
                    _rp[_rpn] = _fixed

    for s in all_functions:
        if isinstance(s, FunctionDef):
            # `_as_funcdef_node`, not the isinstance-narrowed `s` directly:
            # `all_functions` is a heterogeneous statement list (FunctionDef/
            # StructDef/ImportStmt/...), so its loop var erases to opaque
            # int64_t on the self-hosted path — the isinstance guard proves
            # it's a FunctionDef at the Python level but doesn't give this
            # CALL ARGUMENT a static FunctionDef type. `_infer_local_var_
            # types`'s own nested `for node in nodes:` scan then compiled
            # every isinstance(node, ...) check against an untyped node too,
            # and a real VarDecl's runtime type tag was read correctly but
            # fell through an unrelated elif branch (MultiAssignStmt) with
            # mismatched field offsets for `.targets` — a garbage-pointer
            # SIGSEGV in strcmp on virtually every program with at least one
            # function, once `_ensure_bool_cond`'s fix above stopped an
            # earlier, unrelated crash from masking this one. Mirrors this
            # file's own established fix for the identical bug shape at
            # every `m = _as_funcdef_node(...)` call site a few lines below.
            self._inferred_var_types[_as_str(s.name)] = self._infer_local_var_types(_as_funcdef_node(s))
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{_as_str(s.name)}_{_as_str(m.name)}"
                self._inferred_var_types[key] = self._infer_local_var_types(m)
                # Same key, for the sibling table the ASSIGNMENT SITE reads
                # mid-body under `current_func_name` — see
                # `ginf.alias_multi_kind_locals`, imported here rather than at
                # this module's top level so that `import
                # mojo.backend_gimple.module_gen` can be a process's FIRST
                # `mojo.*` import (see the import block's comment).
                import mojo.middle.infra_infer as ginf
                ginf.alias_multi_kind_locals(self, key, m)
    _reconcile_param_container_kinds()

    def _arg_scalar_type(caller_name, a, deep_str=False,
                         prefer_refined_param=False, caller_struct=None):
        """Observed scalar C type of one call argument, or None.

        Both extension flags are used ONLY by the struct-METHOD observation
        pass below; the free-function Pass 1.3d and constructor observers
        keep the plain behavior. Rationale per flag:

        - deep_str extends literal recognition to computed-but-provably-str
          expressions (`"OPTS MLST " + ";".join(facts) + ";"`) via
          _expr_provably_str.

        - prefer_refined_param lets a REFINED cross-call scalar contract for
          the caller's own parameter outrank a possibly-stale
          _inferred_var_types entry (_infer_local_var_types can record a
          method's unannotated param as plain int64_t, shadowing the char*
          the contract passes resolved for it one round earlier — freezing
          pure forwarding chains like sendcmd's cmd → putcmd's line →
          putline's line at the first hop forwarded through such a param).
          Scoped to the method pass because its observations land ONLY on
          method parameters; giving the free-function pass the same
          precedence changed what Pass 1.3d observed about FREE callees
          (real instance: ntpath.split refined to char* from forwarded
          arguments while its own forwarders basename/dirname stayed
          int64_t-typed — new -Wint-conversion errors at those forwards),
          and a free function's full caller set is not visible to any
          fixpoint here, so such a flip cannot be made consistent.
        """
        # Unary +/- in front of a literal: `-1` and `-3.5` parse as
        # UnaryOp('-', <literal>), NOT as a negative literal node, so
        # without looking through them every NEGATIVE literal argument was
        # invisible here — a param reached only from `f(-3.5)` got no
        # observation and kept its int64_t default, so `abs(x)` inside `f`
        # truncated the double (printed 3 for 3.5). The sign cannot change
        # the type, so the operand's own answer is the answer.
        if isinstance(a, UnaryOp) and a.op in ('-', '+'):
            return _arg_scalar_type(caller_name, a.operand, deep_str, prefer_refined_param, caller_struct)
        if isinstance(a, FloatLiteral):
            return 'double'
        if isinstance(a, StringLiteral):
            return 'char *'
        if deep_str and _gmi_expr_provably_str(a):
            return 'char *'
        if isinstance(a, IdentExpr):
            # `_as_str`: `caller_name` comes boxed from the `for caller_name,
            # body in _caller_bodies` unpack, and `a.name` is a boxed AST
            # field read — an unwrapped either one decimal-stringifies its
            # pointer as the dict key and every lookup misses, so the
            # cross-call scalar contract never saw a caller local's type.
            _cn = _as_str(caller_name)
            _an = _as_str(a.name)
            t = self._inferred_var_types.get(_cn, {}).get(_an)
            if prefer_refined_param:
                _pt = self._inferred_param_types.get(_cn, {}).get(_an)
                if _pt in ('char *', 'double'):
                    return _pt
                return t or _pt
            return t or self._inferred_param_types.get(_cn, {}).get(_an)
        if isinstance(a, MemberExpr):
            # `self.<field>` / `<local>.<field>` — the shape a constructor
            # call most often forwards in real code (importlib/
            # _bootstrap_external.py's `NamespaceReader(self._path)`).
            # Without it the observation is None, the slot resolves to
            # nothing, and the field keeps its int64_t default, so the
            # compiled binary prints the string's POINTER VALUE.
            # `caller_struct` is the owning StructDef when the call site is
            # inside one of its methods; otherwise the receiver must be a
            # local whose own inferred type is a `<Struct> *` pointer.
            # Anything else (attribute chains, unknown receivers) is
            # no-evidence, matching every sibling pass.
            _own = caller_struct
            _obj = a.obj
            if isinstance(_obj, IdentExpr):
                _on = _as_str(_obj.name)
                if _on == 'self':
                    if not _own:
                        return None
                else:
                    _ot = self._inferred_var_types.get(_as_str(caller_name), {}).get(_on)
                    if not (isinstance(_ot, str) and _ot.endswith(' *')):
                        return None
                    _own = _ot[:-2]
            else:
                return None
            _ft = self.struct_field_types.get(_own, {}).get(_as_str(a.member))
            return _ft if _ft in ('char *', 'double') else None
        if isinstance(a, BinaryOp) and a.op == '+':
            # `self._path + "!"` — a concat with a str literal on either
            # side proves the whole expression is a `char *` (str.__add__
            # rejects non-str operands, so a literal str on one side settles
            # the other; the same disambiguation _gmi_expr_provably_str
            # documents). Only reached when one side is otherwise
            # unresolvable — a resolvable side is handled by the cases
            # above, and this is what closes the last common gap.
            for _side in (a.left, a.right):
                if not isinstance(_side, MemberExpr):
                    continue
                if _arg_scalar_type(caller_name, _side,
                                    deep_str, prefer_refined_param,
                                    caller_struct) == 'char *':
                    if isinstance(a.left, StringLiteral) or isinstance(a.right, StringLiteral):
                        return 'char *'
            return None
        return None

    def _arg_struct_ptr_type(caller_name, a, caller_struct=None):
        """Observed STRUCT-POINTER C type of one call argument, or None.

        The struct-typed sibling of `_arg_scalar_type`, kept separate rather
        than folded into it because the two feed DIFFERENT application rules:
        `_scalar_obs` resolves a param to `char *`/`double` only when that is
        the unanimous observation, and a struct pointer mixed into the same
        set would suppress an otherwise-unanimous `char *` — a real behaviour
        change to a pass that has its own history. This observer's answers
        only ever reach the struct contract below.

        The case that matters is a struct CONSTRUCTOR passed straight to the
        call — `use(Box('x'))`, and its cross-module spelling `show(insp.
        Parameter('v', 7))`. The call site is the only place this codegen ever
        learns the argument's struct type: a free-function parameter used as a
        method RECEIVER contributes no field accesses, so
        `_infer_param_types`' struct-inference branch (which requires
        `len(fields_accessed) > 0`) never runs for it, and the parameter fell
        through to a chain of name-based builtin-container heuristics that
        cannot express "user struct" at all. A user class defining a method
        named `get`/`items`/`keys` was therefore declared `MojoDict *` and
        either crashed in a dict runtime helper or — silently, exit 0 — was
        boxed and printed as a decimal address.

        `caller_struct` is passed by exactly ONE caller, the constructor
        observation pass below, and only so its `self.<field>` argument shape
        resolves — the same argument, and the same `caller_struct` value,
        `_arg_scalar_type`'s own MemberExpr arm already handles (see the
        `NamespaceReader(self._path)` note there). The free-function Pass
        1.3d caller leaves it None, which is exactly the "no owning struct"
        reading the arm falls back to, so its behaviour is unchanged.

        `IdentExpr` delegates to `_arg_scalar_type` (whose IdentExpr arm
        already returns the caller's own inferred type verbatim, whatever it
        is) and keeps only the `<Struct> *` answers. Everything it cannot
        prove is None — no-evidence, never wrong evidence, matching every
        sibling pass.
        """
        if isinstance(a, gimple_ctypes.IdentExpr):
            # All FIVE arguments passed explicitly, not just the two this
            # call needs: a call into a sibling nested closure from inside
            # another nested closure does not get its DEFAULTS filled in on
            # the self-hosted path (`too few arguments to function
            # 'gen_module_impl__arg_scalar_type'; expected 6, have 3`), and
            # the one existing in-closure recursion in this file already
            # forwards all of them for the same reason.
            st = _arg_scalar_type(caller_name, a, False, False, None)
            if not (isinstance(st, str) and st.endswith(' *')):
                return None
            if st[:-2] in self.struct_field_types:
                return st
            return None
        if isinstance(a, gimple_ctypes.MemberExpr):
            # `<local>.<field>` whose local is a known `<Struct> *` — the
            # shape a receiver forwards most often — plus `self.<field>` when
            # the call site is inside a method of a known struct. Same
            # resolution `_arg_scalar_type`'s MemberExpr arm does, minus its
            # `char *`/`double` whitelist.
            _obj = a.obj
            if not isinstance(_obj, gimple_ctypes.IdentExpr):
                return None
            _own2 = caller_struct
            if _as_str(_obj.name) == 'self':
                if not _own2:
                    return None
                _ft2 = self.struct_field_types.get(_own2, {}).get(_as_str(a.member))
                if (isinstance(_ft2, str) and _ft2.endswith(' *')
                        and _ft2[:-2] in self.struct_field_types):
                    return _ft2
                return None
            _ot = self._inferred_var_types.get(_as_str(caller_name), {}).get(
                _as_str(_obj.name))
            if not (isinstance(_ot, str) and _ot.endswith(' *')):
                return None
            _ft = self.struct_field_types.get(_ot[:-2], {}).get(_as_str(a.member))
            if (isinstance(_ft, str) and _ft.endswith(' *')
                    and _ft[:-2] in self.struct_field_types):
                return _ft
            return None
        if isinstance(a, gimple_ctypes.CallExpr):
            # `Box('x')` / `insp.Parameter('v', 7)`. `_as_str` on the callee
            # name for the same reason the IdentExpr arm needs it: an untyped
            # AST field read is an int64_t box, and a boxed pointer never
            # matches a string dict key. The `.name`/`.member` reads are
            # direct, matching `_collect_method_scalar_obs`'s own receiver
            # read below, which is the same shape.
            _cname = None
            if isinstance(a.func, gimple_ctypes.IdentExpr):
                _cname = _as_str(a.func.name)
            elif isinstance(a.func, gimple_ctypes.MemberExpr):
                _cname = _as_str(a.func.member)
            if (_cname is not None
                    and _cname in self.struct_field_types
                    # The scalar newtypes (Int, UInt8, Bool, ...) ARE real
                    # `struct X(...)` definitions in the stdlib and so can
                    # appear in struct_field_types, but the codegen erases
                    # them to raw C scalars everywhere via _TYPE_MAP; that
                    # convention must win or `Int64(n)` would be observed as a
                    # boxed struct. Same exclusion `_resolve_type` and
                    # `_quick_type`'s `_SCALAR_CTORS` row apply.
                    and _cname not in gimple_ctypes._TYPE_MAP):
                return f'{_cname} *'
            return None
        return None

    _TOPLEVEL_CALLER = '<toplevel>'
    _caller_bodies: list = []
    for _cb_s in all_functions:
        if isinstance(_cb_s, FunctionDef):
            _caller_bodies.append((_as_str(_cb_s.name), _cb_s.body))
    _caller_bodies.append((_TOPLEVEL_CALLER, stmts))

    # Pass 1.3e: struct-METHOD cross-call scalar contract — the same
    # unanimity-over-call-sites refinement Pass 1.3d below provides for
    # FREE functions (and Pass 1.3d-ctor provides for constructor calls),
    # extended to `receiver.method(...)` call sites. Without it, an
    # ordinary method whose unannotated parameter is only ever FORWARDED
    # deeper (`FTP.sendcmd(self, cmd)` doing nothing but `self.putcmd(cmd)`)
    # has zero body-level usage signal for _infer_param_types, so its
    # func_param_types entry — read by the .c definition AND by every
    # forward/extern declaration, including the coroutine .cpp emitter's
    # _cpp_struct_method_refs loop — stays at the int64_t default even when
    # every call site in the module passes a genuine string expression
    # (Lib/ftplib.py: sendcmd('TYPE A'), voidcmd('QUIT'), ...; see bugs/
    # CODEGEN_generator_function_Lib_ftplib.md gap #1). Receiver resolution
    # is deliberately narrow: a bare `self` inside a method of a known
    # StructDef, or an identifier whose own _inferred_var_types entry is a
    # "<Struct> *" pointer. Everything else (attribute chains, unknown
    # receivers, container receivers like MojoList/MojoDict, methods with no
    # StructDef anywhere in this compile — i.e. inherited-from-an-unmodeled-
    # base shapes) contributes NOTHING, matching how every sibling pass
    # treats unrecognized shapes as no-evidence rather than wrong evidence.
    # Application mirrors Pass 1.3d exactly: only unanimous {'double'} /
    # {'char *'} observation sets resolve, explicit annotations are
    # respected, defaulted parameters keep their default-derived type (a
    # call site omitting the argument would otherwise feed the default
    # value through the refined C type), and an already-resolved non-default
    # entry is never overwritten. Collection+application iterates to a small
    # bounded fixpoint so pure forwarding chains resolve one hop per round
    # (sendcmd's cmd from its string-literal call sites, then putcmd's line
    # from sendcmd/voidcmd's now-resolved cmd); the per-statement call walk
    # is memoized (_calls_in_stmts_cache), so rounds after the first are
    # cheap. Results land under the SAME qualified "Struct_method" key
    # everything else uses for method params; the func_param_types
    # registration loop directly below consults that key before falling back
    # to _param_ctype.
    # _method_scalar_ann deliberately covers only AST-visible StructDefs
    # (this module's own + inlined-import structs) — NOT
    # _imported_typedef_structs. A typedef struct's method externs were
    # already baked into _elaborated_externs from Pass 2b-bis's pre-inference
    # ctypes; refining such a param here would desynchronize those stale
    # declarations from newly-refined call-site conversions.
    _method_scalar_ann: dict = {}   # struct name -> {method name -> FunctionDef}
    for s in (stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])):
        if isinstance(s, StructDef):
            for m in s.methods:
                _method_scalar_ann.setdefault(s.name, {})[m.name] = m

    _method_caller_bodies = []
    for s in all_structs_for_methods:
        if not isinstance(s, StructDef):
            continue
        s = _as_structdef_node(s)
        for m in s.methods:
            m = _as_funcdef_node(m)
            _method_caller_bodies.append((f"{_as_str(s.name)}_{_as_str(m.name)}", _as_str(s.name), m.body))
    for name, body in _caller_bodies:
        _method_caller_bodies.append((name, None, body))

    def _collect_method_scalar_obs():
        obs: dict = {}
        for caller_name, caller_struct, cbody in _method_caller_bodies:
            calls = []
            self._calls_in_stmts(cbody, calls)
            for call in calls:
                if not isinstance(call.func, MemberExpr):
                    continue
                recv = call.func.obj
                rstruct = None
                if isinstance(recv, IdentExpr):
                    if recv.name == 'self':
                        rstruct = caller_struct
                    else:
                        t = self._inferred_var_types.get(caller_name, {}).get(recv.name)
                        if isinstance(t, str) and t.endswith(' *'):
                            rstruct = t[:-2]
                meth = (_method_scalar_ann.get(rstruct, {}) if rstruct else {}) \
                    .get(call.func.member)
                if meth is None:
                    continue
                # A @classmethod's FIRST param (`cls`) is bound by the
                # receiver, exactly like an instance method's `self` —
                # call arguments map onto the params AFTER it. Not
                # excluding it here made an instance-called classmethod
                # (`self._sanitize_windows_name(arcname, os.path.sep)`,
                # zipfile) observe its first ARG's type as cls's type AND
                # shift every later observation one slot up: cls got
                # typed 'char *' from arcname's string evidence, and the
                # method body's `cls.<attr> = ...` write then emitted a
                # raw `cls->_attr` field store on a non-struct ("request
                # for member ... in something not a structure or union").
                _meth_is_cls = 'classmethod' in (getattr(meth, 'decorators', None) or [])
                # `[pn for pn, _ in (meth.params or [])...]` doesn't
                # compile self-hosted (comprehension target unpack), but
                # the fix is a plain for-loop unpack, NOT indexed access
                # (`meth.params[_pi][0]`) — that double-subscript form is
                # itself broken (working `==` but broken `len()`/dict-key
                # hashing; see `ann`'s identical fix above). `pnames[i]`
                # ends up used as an `obs` DICT KEY below, and later
                # matched by `.get(pname)` against `ann` (now a properly-
                # hashed dict), so a corrupted-hash key here would break
                # that match even though `ann` itself is fixed.
                pnames = []
                for _pn, _pt in (meth.params or []):
                    if (_pn != 'self' and not (_meth_is_cls and _pn == 'cls')
                            and not _pn.startswith('*')):
                        pnames.append(_pn)
                for i, a in enumerate(call.args):
                    if i >= len(pnames):
                        break
                    st = _arg_scalar_type(caller_name, a, deep_str=True,
                                          prefer_refined_param=True)
                    if st:
                        obs.setdefault((rstruct, call.func.member), {}) \
                            .setdefault(pnames[i], set()).add(st)
        return obs

    def _apply_method_scalar_obs(obs):
        changed = False
        for (rstruct, mname), pmap in obs.items():
            meth = _method_scalar_ann.get(rstruct, {}).get(mname)
            if meth is None:
                continue
            key = f"{rstruct}_{mname}"
            # `{pn: pt for pn, pt in (meth.params or [])}` doesn't even
            # COMPILE self-hosted (a comprehension's target unpack over a
            # `list[tuple[str, str]]` boxes both slots to int64_t, which
            # GCC then rejects as undeclared C identifiers) — but the fix
            # is a plain multi-line for-loop unpack, NOT indexed access
            # (`meth.params[_ai][0]`): that double-subscript form is
            # itself broken (confirmed via unescape_c.py's `s` parameter —
            # a working `==`/`.startswith()` but a broken `len()` and
            # broken dict-key hashing), and `ann` here is looked up by
            # `.get(pname)` below using a properly-typed string, which
            # would miss every entry inserted under a corrupted-hash key.
            ann = {}
            for _ap, _at in (meth.params or []):
                ann[_ap] = _at
            defaults = getattr(meth, 'param_defaults', {}) or {}
            for pname, types in pmap.items():
                if types not in ({'double'}, {'char *'}):
                    continue                 # not unanimous double / char *
                if ann.get(pname) is not None:
                    continue                 # respect explicit annotation
                if pname in defaults:
                    continue                 # respect default-value inference
                cur = self._inferred_param_types.get(key, {}).get(pname)
                # A usage-heuristic 'MojoList *' is a GUESS on the str/list
                # ambiguity axis, not resolved knowledge: _infer_param_types
                # (gimple_gen_infra.py) types any subscripted/sliced-but-
                # otherwise-unsignaled param 'MojoList *' — its own docstrings
                # record several prior misfires of exactly this guess. When
                # every OBSERVABLE call site passes an expression that is
                # PROVABLY a string (a string literal, f-string, or provably-
                # str join/concat — the only sources of a {'char *'} entry),
                # that observation outranks the guess: real Python could not
                # even run with a genuine list there. Narrow on purpose — only
                # {'char *'} flips 'MojoList *' (never double, never any other
                # resolved type), so annotation/default/other-scalar respect
                # above is untouched. Found via Tools/gdb/libpython.py's
                # TruncatedStringIO.write(self, data): `data[0:n]` slicing was
                # its only body signal → inferred MojoList* → the body lowered
                # len()/slice as list ops while self._val stayed char*, so
                # `self._val += data[...]` emitted raw `char * + MojoList *`
                # pointer addition and gcc -fgimple died with "internal
                # compiler error: in build2, at tree.cc" (bugs/
                # COMPILE_FAIL_Tools_gdb_libpython.md).
                if cur in (None, 'int', 'int64_t') \
                        or (cur == 'MojoList *' and types == {'char *'}):
                    self._inferred_param_types.setdefault(key, {})[pname] = (
                        'double' if types == {'double'} else 'char *')
                    changed = True
        return changed

    for _mse_round in range(4):
        if not _apply_method_scalar_obs(_collect_method_scalar_obs()):
            break

    # Refresh Pass 2b-bis's precomputed per-overload signature ctypes for
    # methods whose parameters the pass above just resolved. Pass 2b-bis
    # runs BEFORE any inference exists, so its _mangled_signature_ctypes
    # entries hold the int64_t defaults; for a `*args` method _emit_call
    # deliberately prefers that sentinel form over func_param_types (the
    # Parser__is_kw packing-sentinel fix), so without this refresh a
    # pre-definition call site converts its arguments against the stale
    # boxed types while the definition/declaration carry the refined ones
    # ("passing argument N of 'X' makes pointer from integer without a
    # cast", self-hosted myinterpreter.py's Interpreter__call_dunder).
    # Same AST-visible universe as the observation pass above — typedef
    # structs' baked externs must stay in sync with their entries.
    for s in (stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])):
        if not isinstance(s, StructDef):
            continue
        _s3189_oids = self._struct_method_overload_ids(s)
        for _zmi in range(len(s.methods)):
            m = _as_funcdef_node(s.methods[_zmi]); _oid = _as_str(_s3189_oids[_zmi]) if _zmi < len(_s3189_oids) else ""
            _sigkey = f"{s.name}_{m.name}{_oid}"
            _old_ct = self._mangled_signature_ctypes.get(_sigkey)
            if _old_ct is None:
                continue
            _new_ct = self._signature_ctypes(m.params, m, s.name)
            if _new_ct != _old_ct:
                self._mangled_signature_ctypes[_sigkey] = _new_ct

    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef):
            if gimple_ctypes._params_have_vararg(s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = _free_func_param_ctypes(self, s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            s = _as_structdef_node(s)
            for m in s.methods:
                m = _as_funcdef_node(m)
                method_full_name = f"{_as_str(s.name)}_{_as_str(m.name)}"
                if method_full_name in self._selfhost_locked_param_types:
                    continue
                if gimple_ctypes._params_have_vararg(m.params):
                    self.func_param_types[method_full_name] = self._signature_ctypes(m.params, m, s.name)
                else:
                    param_ctypes = []
                    for i, (pname, ptype) in enumerate(m.params):
                        if pname.startswith('**'):
                            continue  # skip **kwargs
                        if pname == 'self':
                            param_ctypes.append(f"{s.name} *")
                        else:
                            # Usage/call-site inference for struct methods is
                            # stored under the QUALIFIED "Struct_method" key,
                            # but _param_ctype consults the bare node.name —
                            # so a resolved entry was invisible here and every
                            # such param silently fell to the int64_t default.
                            # Consult the qualified key first, mirroring the
                            # forward-declaration loop's own precedence below;
                            # Pass 1.3e feeds it (and _infer_param_types's
                            # results under this same key finally reach both
                            # the .c definition and every extern/forward
                            # declaration derived from func_param_types).
                            _mipt = None
                            if ptype is None:
                                _mipt = self._inferred_param_types.get(
                                    method_full_name, {}).get(pname)
                                if _mipt is None and _as_str(m.name) == '__init__':
                                    # An unannotated `__init__` param with
                                    # literal call-site evidence gets that
                                    # evidence's ctype HERE — the signature —
                                    # and not only in the field pass below,
                                    # which reached the FIELD and left this
                                    # param at `int64_t`. The two then
                                    # disagreed, and the disagreement was the
                                    # bug: `B(2.5)` stored the truncated
                                    # integer 2 into a field declared `double`
                                    # and printed 2.0 where CPython prints 2.5.
                                    # `_ctor_param_evidence` is the same reader
                                    # the field pass uses, in the same
                                    # precedence, so an explicit annotation
                                    # still wins over both (the `ptype is None`
                                    # guard) and the two cannot drift.
                                    # `emit_calls.py`'s constructor path reads
                                    # THIS table to coerce each argument
                                    # ("Coerce each argument to its declared
                                    # `__init__` param C type"), so the
                                    # coercion and the field declaration now
                                    # agree by construction.
                                    _mipt_ev = _ctor_param_evidence(
                                        self, s.name, pname,
                                        getattr(self, '_xf_own_ctor_params', None))
                                    if _mipt_ev:
                                        _mipt = _mipt_ev
                            param_ctypes.append(
                                _mipt if _mipt is not None
                                else self._param_ctype(pname, ptype, m))
                    self.func_param_types[method_full_name] = param_ctypes
                # Struct-METHOD parameter defaults, keyed by the same bare
                # mangled name func_param_types just used — the coroutine-
                # body (.cpp) emitter's own `self.<method>(...)`/`cls.<method>(
                # ...)`/`<struct-ptr-local>.<method>(...)` call lowering reads
                # this via the SAME bare-or-qualified lookup convention
                # `_func_param_defaults.get(fsym) or .get(fname_raw)` already
                # established for free functions (gimple_cpp_core.py's
                # `_cpp_try_kwargs_forward_call`). Without it, an omitted
                # defaulted trailing argument (`mailbox.py`'s
                # `_singlefileMailbox.iterkeys` calling `self._lookup()` on
                # `def _lookup(self, key=None)`) produced a call with fewer C
                # arguments than the callee's real signature ("too few
                # arguments to function '_singlefileMailbox__lookup'").
                # Mirrors the free-function registration at ~line 1351:
                # `param_defaults` holds ONLY the params that have one,
                # starting at the first defaulted position (BUG-2026-020's
                # finding), so consumers index from
                # `len(expected) - len(defaults)`. Vararg/`**kwargs`-taking
                # methods are skipped — their flat positional model doesn't
                # apply (same exclusion `_signature_ctypes`' branch above
                # already makes).
                if not (gimple_ctypes._params_have_vararg(m.params)):
                    _m_dflts = getattr(m, 'param_defaults', None) or {}
                    if _m_dflts:
                        self._func_param_defaults.setdefault(method_full_name,
                                                             [(pn, dv) for pn, dv in _m_dflts.items()])

    for s in all_structs_for_methods:
        if not isinstance(s, StructDef):
            continue
        s = _as_structdef_node(s)
        if _as_str(s.name) != 'GimpleGen':
            continue
        for m in s.methods:
            m = _as_funcdef_node(m)
            mangled = f"GimpleGen_{_as_str(m.name)}"
            fpt = self.func_param_types.get(mangled)
            inferred = self._inferred_param_types.get(mangled)
            if not fpt or not inferred:
                continue
            idx = 0
            for pname, ptype in (m.params or []):
                if pname.startswith('**') or pname.startswith('*') and pname != 'self':
                    continue
                if pname == 'self':
                    idx += 1
                    continue
                if idx < len(fpt) and pname in inferred and fpt[idx] == 'int64_t':
                    fpt[idx] = inferred[pname]
                idx += 1

    # Re-assert the frozen GimpleGen table after the per-instance method
    # passes (they run between the early apply above and here and rewrite
    # `func_param_types` / `func_return_types` from local inference).
    if _gg_sigs:
        for _mangled, (_rc, _pcs, _dflts) in _gg_sigs.items():
            self.func_param_types[_mangled] = list(_pcs)
            self.func_return_types[_mangled] = _rc
            if _dflts:
                self._func_param_defaults[_mangled] = list(_dflts)

    self._param_elem_types: dict[str, dict[str, tuple]] = {}
    # The dict-VALUE twin of the table above: callee -> {pname -> the dict
    # value ctype every one of its call sites agrees on}. A dict is stored
    # as one `int64_t` slot per key plus a per-slot `kind` tag, so a callee
    # that only ever receives `{'x': '1'}` reads that slot back through
    # `mojo_dict_get_str`, and one that receives `{'x': 1}` through
    # `mojo_dict_get_int` -- both without a static type anywhere to consult.
    # There is no binding SITE inside the callee to record it (unlike a
    # local `d = {...}`, which `_lower_dict_literal` types as it lowers it),
    # so it has to come from the call sites. Read by `gen_func` /
    # `_gen_struct_method` at the same `_param_elem_types` seeding, into
    # `gen._dict_val_types`. `''` means the call sites disagreed, which the
    # reader treats as "unknown" exactly as `(None, None)` does for the
    # element contract.
    self._param_dict_val_types: dict[str, dict[str, str]] = {}
    # ...and the raw per-call-site OBSERVATIONS behind it, kept apart exactly
    # as `_scalar_obs` is kept apart from `_inferred_param_types`: a call site
    # holding `{'x': 2}` contributes `int64_t`, which is the table's default
    # answer and therefore worthless on its own — but its SILENCE next to a
    # sibling site's `{'x': '1'}` is what makes the pair a disagreement
    # instead of a vacuous agreement. Collapsing that into one table at
    # collection time is what made `f({'x': '1'}); f({'x': 2})` resolve to
    # `char *` and read the integer through `mojo_dict_get_str`.
    self._param_dict_val_obs: dict[str, dict[str, set]] = {}
    _free_params: dict = {}
    for _fp_s in all_functions:
        if not isinstance(_fp_s, FunctionDef):
            continue
        _fp_names: list = []
        for _fp_pn, _ in (_fp_s.params or []):
            _fp_pn = _as_str(_fp_pn)
            if not _fp_pn.startswith('*'):
                _fp_names.append(_fp_pn)
        _free_params[_as_str(_fp_s.name)] = _fp_names
        # A synthesized coroutine BODY (`__mgco_<g>_body`) carries the C
        # element ctype its generator's list parameters had, decided from the
        # unanimous cross-call-site contract before the lowering REPLACED the
        # generator's own FunctionDef — so this is the last point at which
        # that evidence exists at all. Folded into the same table, under the
        # body's own name, because `emit_funcs.gen_func` already seeds
        # `_elem_types` from exactly this table for every function it
        # lowers: one consumer, one table, no second seeding path. (Iterate
        # the dict + index, not `.items()`: a tuple-unpacking `for` target
        # is not lowered correctly when this file is self-compiled — see
        # `gen_func`'s own note on `_pe`.)
        _pe_body = getattr(_fp_s, '_mojo_coro_param_elem_kinds', None)
        if _pe_body:
            _pe_d = self._param_elem_types.setdefault(_as_str(_fp_s.name), {})
            for _pe_k in _pe_body:
                _pe_d[_as_str(_pe_k)] = (_as_str(_pe_body[_pe_k]), None)

    def _record_param_elem(callee, pname, e, ne):
        # `_as_str` on both NAME params: a nested function's untyped params
        # lift to int64_t on the self-hosted path, so `setdefault(callee, {})`
        # keyed `_param_elem_types` by the raw POINTER and every later
        # string-keyed lookup (`_pe.get('compare_stages')` in gen_func) MISSED
        # — the callee's container param then never inherited its element
        # type, so `for ext in extensions:` typed `ext` int64_t instead of
        # `char *` (the `bootstrap-validate.mojo` stage1-vs-stage2
        # divergence). Same boxing trap the sibling loops in this pass
        # already guard against.
        callee = _as_str(callee)
        pname = _as_str(pname)
        d = self._param_elem_types.setdefault(callee, {})
        if pname in d and d[pname] != (e, ne):
            d[pname] = (None, None)   # conflicting call sites → unknown
        else:
            d[pname] = (e, ne)

    def _record_param_dict_val(callee, pname, vt):
        """Record ONE call site's dict-value ctype for one parameter.

        The dict-value twin of `_record_param_elem`, collecting into a SET
        rather than collapsing to a value: `int64_t` is this table's default
        answer and so carries no information by itself, but a sibling call
        site holding `{'x': '1'}` must still be able to disagree with it. The
        scalar contract faces the identical asymmetry and resolves it by
        keeping `_scalar_obs` as sets until its own application loop; this is
        that, spelled for dict values. Resolution happens in
        `_resolve_param_dict_vals`, once both walks are done.
        """
        callee = _as_str(callee)
        pname = _as_str(pname)
        # Split the chained setdefault so the intermediate result has a static
        # type -- the same trap the two sibling `_record_*` blocks below the
        # collection loop already document.
        _dv_inner = self._param_dict_val_obs.setdefault(callee, {})
        _dv_set = _dv_inner.setdefault(pname, set())
        _dv_set.add(_as_str(vt))

    def _resolve_param_dict_vals():
        """Turn the collected observations into the contract codegen reads.

        Only a UNANIMOUS observation resolves, and an `int64_t` one resolves
        to the `int64_t` default the reader already had -- i.e. it is a no-op,
        recorded only so that a mixed set collapses to unknown rather than to
        whichever side happened to be seen first.
        """
        for _callee, _pm in self._param_dict_val_obs.items():
            _dst = self._param_dict_val_types.setdefault(_callee, {})
            for _pname, _types in _pm.items():
                if len(_types) == 1:
                    # `sorted(...)` + index, NOT `next(iter(...))`, and this
                    # file's own reason for it: `next(<CallExpr>)` is REFUSED
                    # outright by the self-hosted codegen ("`next(...)` on
                    # next(CallExpr) has no lowering in this codegen"), which
                    # made this module — and so the whole self-host closure —
                    # uncompilable, while iterating a str-SET lowers to
                    # `mojo_set_iter_val_int` (0 for every string slot) and so
                    # cannot answer the question either. `sorted` on the same
                    # set sorts string CONTENT and indexes like a list; this is
                    # the same two lines the struct-evidence loop above uses for
                    # the same set-of-observations question.
                    _sole = sorted(_types)
                    _dst[_pname] = _as_str(_sole[0])
                else:
                    _dst[_pname] = ''      # disagreeing call sites → unknown

    def _static_arg_dict_val(a, dict_val, caller_name=None):
        """The dict-VALUE ctype provable for one call argument, or None.

        `dict_val` is the caller body's own pre-scanned local-dict map (the
        third thing `_scan_container_elems` returns, previously discarded at
        both call sites). A dict LITERAL written in place is decidable on the
        spot through the SAME rule `_lower_dict_literal` stores it with, and a
        bare name defers to the caller's scan -- the same two shapes
        `_static_arg_elems` accepts, and deliberately the same two: an
        argument that is neither has no value type to propagate, and guessing
        one is what makes the pre-existing sibling contracts refuse instead.

        `caller_name` adds the one shape the local scan structurally cannot
        see: a name that is a PARAMETER of the caller, so its type came from
        the caller's own contract rather than from a binding site. That is a
        forwarding chain (`def g(d): return f(d)`), which is why the
        collection loop runs to a bounded fixpoint for this table alone --
        the same reason the scalar and element contracts iterate.
        """
        if isinstance(a, gimple_ctypes.DictExpr):
            return gimple_exprtypes.dict_literal_val_ctype(self, a.pairs)
        if isinstance(a, gimple_ctypes.IdentExpr):
            _n = _gmi_as_str(a.name)
            if _n in dict_val:
                return _gmi_as_str(dict_val[_n])
            if caller_name is not None:
                _fwd = self._param_dict_val_types.get(_as_str(caller_name), {})
                if _n in _fwd and _fwd[_n]:
                    return _fwd[_n]
            return None
        if isinstance(a, gimple_ctypes.BinaryOp) and a.op == '|':
            # `f(env_defaults | os.environ | updates)` — the shape the whole
            # dict-value contract exists for, and the one a merge produces.
            # The union's value type is an AGREEMENT between its operands'
            # (ginf._dict_union_val_type's own rule, for the same reason and
            # with the same `int64_t`-is-the-default caveat); disagreement
            # yields nothing rather than a guess.
            _l = _static_arg_dict_val(a.left, dict_val, caller_name)
            _r = _static_arg_dict_val(a.right, dict_val, caller_name)
            if _l is None or _r is None:
                return None
            if _l == _r:
                return _l
            if _l == 'int64_t':
                return _r
            if _r == 'int64_t':
                return _l
            return None
        return None

    def _literal_arg_elems(a):
        """`(elem, nested)` C types for a container LITERAL passed as a call
        argument, or None when `a` is not one whose element type is statically
        decidable. The same two answers `note_list_literal` inside
        `_scan_container_elems` derives for a literal bound to a local, so the
        two observation sources of this table cannot drift: a list-of-lists is
        `('MojoList *', <inner elem>)`, anything else is `(<joined elem>,
        None)`.

        Why this exists at all: `_param_elem_types` was fed ONLY from an
        argument that is a bare identifier naming a tracked local, so
        `show(xs)` inherited xs's element type while `show([1.5, 2.5])` —
        the SAME call with the list written in place — inherited nothing. The
        callee then read every element through `mojo_list_get_int` and
        `print(r)` emitted the floats' raw IEEE-754 bit patterns with exit 0.
        That was "Item 8" of `CODEGEN_coro_yield_kind_unresolved_callsite`, a
        bugs/hard doc since FIXED and DELETED with this contract; the cases
        that pin it are `gimple_for_over_list_param_from_float_literal`,
        `..._from_keyword_literal`, `..._from_str_literal` and
        `..._nested_list_param_from_literal` in test_gimple_runner.py."""
        if not isinstance(a, ListExpr):
            return None
        els = a.elements
        if not els:
            return None
        if isinstance(els[0], ListExpr):
            return ('MojoList *', self._infer_list_elem_type(els[0].elements))
        return (self._infer_list_elem_type(els), None)

    def _informative_elem_ctype(e):
        """True when an observed element ctype tells the callee something the
        `int64_t` default would not already do.

        `int64_t` is this table's "no information" answer, not a fact about
        the value: the consumer seeds `_elem_types[bare] = e` and every
        absent entry falls back to exactly the same `int64_t`
        (`_elem_of`), so an int list is read identically with or without a
        contract. Recording it as EVIDENCE can therefore only ever destroy
        information — it collides with a `char *`/`double` observation from a
        sibling call site and turns a resolvable param into
        `(None, None)` = unknown = `int64_t` again, which is what the int
        observation alone already gave. So a literal argument contributes its
        element ctype only when it is one the default gets wrong.

        Deliberately NOT applied to the bare-identifier branch below, which
        predates this: dropping `int64_t` there flips which side of a
        genuinely-heterogeneous param (`f(int_list)` and `f(str_list)` from
        different call sites) reads correctly, and that is a coin flip
        either way — not worth re-rolling real stdlib code on while the
        breadth number is unmeasured."""
        return e != 'int64_t' and e != ''

    def _note_literal_arg_elems(callee, pname, a):
        """Record `pname`'s element ctype from a container-literal argument.
        No-op unless the literal's element ctype is one the `int64_t` default
        gets wrong (see `_informative_elem_ctype`)."""
        pair = _literal_arg_elems(a)
        if pair is None:
            return
        e = pair[0]
        ne = pair[1]
        if not _informative_elem_ctype(e):
            return
        import os as _os
        if _os.environ.get('MOJO_TRACE_PARAM_ELEM'):
            print('TRACE', _as_str(callee), _as_str(pname), e, ne, file=sys.stderr)
        _record_param_elem(callee, pname, e, ne)

    _fn_by_name: dict = {}
    for _fbn_s in all_functions:
        if isinstance(_fbn_s, FunctionDef):
            _fn_by_name[_as_str(_fbn_s.name)] = _fbn_s

    # Per-callee memo of "what container ELEMENT type does this function
    # RETURN", read by `_static_arg_elems`'s CallExpr arm below. Memoized
    # because `_infer_return_elem_type` walks the whole body and this arm sits
    # inside a per-call-site walk over every caller body, so an unmemoized
    # call would re-scan the same function once per call site that passes its
    # result onward. Keyed by name, not by node id: the same FunctionDef is
    # reached from every call site in the program and there is exactly one
    # answer per name.
    _callee_ret_elem_memo: dict = {}

    def _callee_return_elem(fname):
        """The container element C type `fname` returns, or None.

        The callee's OWN body is the only evidence there is for this, and it
        is the same evidence Pass 2c's `_return_elem_types` table is built
        from — which does not exist yet at Pass 1.3d, so it is asked directly.
        A callee this compile has no FunctionDef for (an imported extern, a
        method reached through a receiver) answers None, i.e. no evidence,
        never a guess. One try/except: `_infer_return_elem_type` runs a whole
        nested scan over AST shapes this pass has no stake in, and a decline
        there must be silence rather than an exception out of a pre-pass.
        """
        if fname in _callee_ret_elem_memo:
            return _callee_ret_elem_memo[fname]
        _fd = _fn_by_name.get(fname)
        if _fd is None:
            _callee_ret_elem_memo[fname] = None
            return None
        try:
            _e = self._infer_return_elem_type(_fd.body, _fd)
        except Exception:
            _e = None
        _callee_ret_elem_memo[fname] = _e
        return _e
    _scalar_obs: dict[str, dict[str, set]] = {}   # callee -> {pname -> {types}}
    # Struct-pointer observations, collected in their own map (see
    # `_arg_struct_ptr_type`'s docstring for why they must not share
    # `_scalar_obs`' set) and applied by the struct contract below.
    _struct_obs: dict[str, dict[str, set]] = {}


    # ...and the METHOD half of the same contract. The walk above only
    # recognises a callee spelled as a bare `IdentExpr`, so every
    # `self.q.backward(gq, n)` / `obj.method(xs)` call site was invisible:
    # a container passed into a METHOD kept no element type, and the
    # callee read it with mojo_list_get_int whatever the caller stored.
    # For a list of doubles that returns the raw IEEE-754 bit pattern,
    # which then flows through arithmetic as a perfectly ordinary-looking
    # int64_t — a SILENT wrong answer, exit 0 (real: a hand-written
    # neural-net's `g[i]` incoming-gradient read in a Linear.backward,
    # where `gi == 0.0` then compared a bit pattern against zero and never
    # matched, so every gradient silently went the wrong way).
    #
    # Receiver resolution mirrors `_collect_method_scalar_obs` exactly
    # (self.<field> via the caller's own struct, a local via
    # _inferred_var_types), because it answers the same question: which
    # struct owns this method call.
    def _static_arg_elems(a, elem, nested):
        """(element, nested-element) C types provable for one argument
        expression, or (None, None). IdentExpr defers to the caller's
        scanned local map; a container LITERAL is provable on the spot,
        which is what the IdentExpr-only walk above could not see either
        (`total([1.0, 2.0])` read its argument as int64 bits); and a CALL
        RESULT resolves through the callee's own return element type.

        The CallExpr arm is the third shape of the same question, and its
        absence was a hole rather than a limit: `total([T(1), T(2)])` typed
        its argument from the literal and `total(mylist)` from the caller's
        scan, but `total(build(10))` — a parameter whose EVERY call site is
        handed a function's return value — had no evidence at all, fell to
        `int64_t`, and the callee's `for t in xs:` read the elements with
        `mojo_list_get_int`, so `t.numel()` degraded to the no-op stub and `s`
        accumulated a `T *`'s own bits. Exit 0, no diagnostic: a heap address
        where CPython prints `21`. Both one-hop neighbours of that shape were
        already right, which is what makes it a gap.

        What is NOT interchangeable with a callee's own parameter type: the
        element type comes from the RETURN (`build`'s `return [T(n), T(n+1)]`
        list literal), so this asks `_callee_return_elem` and nothing else.
        Admission discipline is the sibling arms' unchanged: `int64_t` is
        never positive evidence (see the IdentExpr arm), and `_record_param_
        elem`'s conflict rule still erases rather than merges."""
        if isinstance(a, gimple_ctypes.IdentExpr):
            _n = _gmi_as_str(a.name)
            if _n in elem:
                _e = _gmi_as_str(elem[_n])
                # An `int64_t` element type is NOT positive evidence: it is
                # both the honest answer for a list of ints AND this
                # codegen's "cannot tell" default (an empty literal, an
                # int/double join, a subscript store whose value type was
                # unresolvable). Recording it changes nothing at the read --
                # the default accessor already is mojo_list_get_int -- but
                # it DOES collide in `_record_param_elem`'s conflict rule
                # and erase the real answer from a sibling call site, so a
                # method reached from both a float-list and a not-yet-typed
                # call site lost its element type outright (real:
                # Linear.backward's incoming gradient -- three double call
                # sites in GatedLinearAttention, two untyped ones in
                # SwiGLU -- joined to (None, None), and every `g[i]` in it
                # read back as raw int64 bits).
                if _e == 'int64_t':
                    return None, None
                return _e, _gmi_as_str(nested.get(_n))
            return None, None
        if isinstance(a, gimple_ctypes.ListExpr):
            _e = self._infer_list_elem_type(a.elements)
            if _e == 'int64_t':
                return None, None
            if not self._literal_elements_include_none(a.elements):
                if a.elements and isinstance(a.elements[0], gimple_ctypes.ListExpr):
                    return 'MojoList *', self._infer_list_elem_type(a.elements[0].elements)
                return _gmi_as_str(_e), None
        if isinstance(a, gimple_ctypes.CallExpr) and isinstance(a.func, gimple_ctypes.IdentExpr):
            # Only a bare-name callee: a `module.f(...)` / `recv.m(...)` has
            # no FunctionDef in `_fn_by_name`, so it answers None, the same
            # no-evidence answer every other unrecognised shape gives.
            _e = _callee_return_elem(_gmi_as_str(a.func.name))
            if _e is None or _e == 'int64_t' or _e == '':
                return None, None
            return _gmi_as_str(_e), None
        return None, None

    for caller_name, body in _caller_bodies:
        elem, nested, dval = self._scan_container_elems(body)
        calls = []
        self._calls_in_stmts(body, calls)
        for call in calls:
            if not isinstance(call.func, IdentExpr):
                continue
            callee = _as_str(call.func.name)
            pnames = _free_params.get(callee)
            if not pnames:
                continue
            for i, a in enumerate(call.args):
                if i >= len(pnames):
                    break
                _fe, _fne = _static_arg_elems(a, elem, nested)
                if _fe is not None:
                    _record_param_elem(callee, pnames[i], _fe, _fne)

                _dv = _static_arg_dict_val(a, dval, caller_name)
                if _dv is not None:
                    _record_param_dict_val(callee, pnames[i], _dv)

                st = _arg_scalar_type(caller_name, a)
                if not st:
                    # An int/bool/None literal contributes NOTHING above, and
                    # that silence is the bug this records against: `f(1)`
                    # alongside `f("s")` yielded `_scalar_obs['f']['x'] ==
                    # {'char *'}` — one OBSERVING call site, vacuously
                    # unanimous, resolved to `char *`, while the int call site
                    # contributed absence that counted as agreement. The
                    # parameter then declared `char * f(char *)`, and
                    # `mojo_print((char *)1)` strlen'd a small integer:
                    # SIGSEGV (exit -11) for a program CPython prints
                    # `1` / `s`. Silence is asymmetric by construction here:
                    # `g(1.5)` and `g("s")` are typed correctly, and `g(1)`
                    # lands on `int64_t` only because `{'int64_t'}` fails the
                    # `_has_dbl or _has_cs` whitelist below — nobody observed
                    # it as one.
                    #
                    # LOCAL to this walk, deliberately NOT in
                    # `_arg_scalar_type`: its other four consumers (the
                    # struct-pointer observer, the struct-METHOD contract and
                    # the two constructor observers) each whitelist its
                    # answers differently, so widening what it returns changes
                    # all four. That is a separate decision, deliberately not
                    # taken here.
                    if isinstance(a, (gimple_ctypes.IntLiteral,
                                       gimple_ctypes.BoolLiteral,
                                       gimple_ctypes.NoneLiteral)):
                        st = 'int64_t'
                    elif isinstance(a, (gimple_ctypes.ListExpr,
                                        gimple_ctypes.DictExpr,
                                        gimple_ctypes.SetExpr,
                                        gimple_ctypes.TupleExpr,
                                        gimple_ctypes.Comprehension)):
                        # A CONTAINER literal is the one argument shape that
                        # is provably a POINTER and still contributes nothing
                        # above, so a slot reached from `f(2.5)` and
                        # `f([1, 2])` observed only `{'double'}` — unanimous,
                        # and the parameter declared `double f(double)` while
                        # the list's `MojoList *` went to a `double` formal:
                        # "pointer value used where a floating-point was
                        # expected", a hard GCC error and no binary at all.
                        # The same hole with `char *` instead of `double` is
                        # worse, because it is silent: `char * f(char *)` plus
                        # a list argument is `mojo_print` over the list
                        # HEADER's bytes.
                        #
                        # `void *` is the shape that makes both vetoes, and it
                        # is deliberately a string this pass's own whitelist
                        # (`len(types) != 1 or not (_has_dbl or _has_cs)`)
                        # already rejects: one non-scalar member in the set
                        # drops the slot to the `int64_t` box, which is the
                        # same answer every other disagreeing pair gets and
                        # the one the `_tagged_dyn_` machinery is built for.
                        # Recorded HERE rather than in `_arg_scalar_type` for
                        # the reason the IntLiteral arm above gives: that
                        # function's four other consumers each whitelist its
                        # answers differently.
                        #
                        # The pointer is real information and is NOT
                        # discarded: `mojo_list_set_kinds`/`_elem_types`
                        # already record the container's element type for the
                        # call-site walk, and the printed value being a
                        # pointer decimal here is the same class this doc's
                        # remaining rows describe.
                        st = 'void *'
                if st:
                    # Split the chained `_scalar_obs.setdefault(callee, {})
                    # .setdefault(pnames[i], set()).add(st)` into typed
                    # locals: the chained form's INTERMEDIATE results have
                    # no static type on the self-hosted path, so `.add(st)`
                    # lowered as `mojo_set_add_int` on the inner DICT
                    # pointer (`_set_slot_int` SIGSEGV in
                    # `./mojoc fire.py --dump-full`, gimple_module_gen.py's
                    # gen_module_impl). Named locals get the chokepoint's
                    # container-kind preservation (`_lower_dict_method`'s
                    # "Preserve a container/pointer default's static type").
                    _so_inner = _scalar_obs.setdefault(callee, {})
                    _so_set = _so_inner.setdefault(pnames[i], set())
                    _so_set.add(_gmi_as_str(st))
                spt = _arg_struct_ptr_type(caller_name, a)
                if spt:
                    # Same "split the chained setdefault so the intermediate
                    # result has a static type" reason as the block above.
                    _sp_inner = _struct_obs.setdefault(callee, {})
                    _sp_set = _sp_inner.setdefault(pnames[i], set())
                    _sp_set.add(_gmi_as_str(spt))
            # Keyword arguments name the parameter directly, so the element
            # contract reads them the same way — `show(data=[1.5, 2.5])` is
            # the same call as `show([1.5, 2.5])` and used to inherit exactly
            # as little. The dict-value contract reads them the same way for
            # the same reason; the scalar and struct-pointer observations
            # above are a separate pre-existing contract with its own
            # coverage, and widening those is not this change's business.
            for _kw in (getattr(call, 'kwargs', None) or []):
                _kwn = _as_str(_kw[0])
                for _ki in range(len(pnames)):
                    if pnames[_ki] == _kwn:
                        _note_literal_arg_elems(callee, _kwn, _kw[1])
                        _kwdv = _static_arg_dict_val(_kw[1], dval, caller_name)
                        if _kwdv is not None:
                            _record_param_dict_val(callee, _kwn, _kwdv)
                        break

    # A CONSTRUCTOR call is a `CallExpr` whose callee is a bare `IdentExpr`
    # (`C({...})`), so the MemberExpr-only walk below cannot see it -- which is
    # why the `_ctor_lit_param_types` pass exists separately for this
    # contract's scalar half. The dict-value half had no such fallback, and a
    # constructor is THE way a dict reaches a user class (`self.d = d`), so
    # without it every method's `self.d[k]` read the slot through
    # `mojo_dict_get_int` and printed the stored `char *`'s own digits.
    # Keyed `<Struct>___init__`, the same key `_method_caller_bodies` uses for
    # that method and therefore the same key `_gen_struct_method` reads its
    # seeds from -- one key, one consumer.
    _ctor_init_by_struct: dict = {}
    for _cs in (stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])):
        if not isinstance(_cs, StructDef):
            continue
        for _cm in (_cs.methods or []):
            if _as_str(_cm.name) == '__init__':
                _ctor_init_by_struct[_as_str(_cs.name)] = _cm
                break

    for caller_name, caller_struct, cbody in _method_caller_bodies:
        _melem, _mnested, _mdval = self._scan_container_elems(cbody)
        _mcalls = []
        self._calls_in_stmts(cbody, _mcalls)
        for _mcall in _mcalls:
            if isinstance(_mcall.func, IdentExpr):
                _minit = _ctor_init_by_struct.get(_as_str(_mcall.func.name))
                if _minit is None:
                    continue
                _mcallee0 = _as_str(_mcall.func.name) + '___init__'
                _mpn0 = []
                for _pn0, _ in (_minit.params or []):
                    _pn0 = _as_str(_pn0)
                    if _pn0 != 'self' and not _pn0.startswith('*'):
                        _mpn0.append(_pn0)
                for _mi0, _ma0 in enumerate(_mcall.args):
                    if _mi0 >= len(_mpn0):
                        break
                    _mdv0 = _static_arg_dict_val(_ma0, _mdval, caller_name)
                    if _mdv0 is not None:
                        _record_param_dict_val(_mcallee0, _mpn0[_mi0], _mdv0)
                continue
            if not isinstance(_mcall.func, MemberExpr):
                continue
            _mrecv = _mcall.func.obj
            _mrstruct = None
            if isinstance(_mrecv, IdentExpr):
                if _mrecv.name == 'self':
                    _mrstruct = caller_struct
                else:
                    _mt = self._inferred_var_types.get(caller_name, {}).get(_mrecv.name)
                    if isinstance(_mt, str) and _mt.endswith(' *'):
                        _mrstruct = _mt[:-2]
            elif (isinstance(_mrecv, MemberExpr) and isinstance(_mrecv.obj, IdentExpr)
                    and _mrecv.obj.name == 'self' and caller_struct
                    and caller_struct in self.struct_field_types):
                _mft = self.struct_field_types[caller_struct].get(_mrecv.member)
                if isinstance(_mft, str) and _mft.endswith(' *'):
                    _mrstruct = _mft[:-2]
            if not _mrstruct:
                continue
            _mmeth = _method_scalar_ann.get(_mrstruct, {}).get(_mcall.func.member)
            if _mmeth is None:
                continue
            _mpn = []
            _meth_is_cls = 'classmethod' in (getattr(_mmeth, 'decorators', None) or [])
            for _pn, _pt in (_mmeth.params or []):
                _pn = _gmi_as_str(_pn)
                # `self` (and a classmethod's `cls`) is bound by the
                # RECEIVER, not by any argument, so it must not consume
                # call-arg slot 0 — `_collect_method_scalar_obs` drops them
                # for exactly this reason, and copying its rule is what
                # keeps the two contracts aligned. Getting it wrong
                # records arg 0's element type against `self` and shifts
                # every later argument one slot up.
                if _pn != 'self' and not (_meth_is_cls and _pn == 'cls') \
                        and not _pn.startswith('*'):
                    _mpn.append(_pn)
            if not _mpn:
                continue
            _mcallee = f"{_gmi_as_str(_mrstruct)}_{_gmi_as_str(_mcall.func.member)}"
            for _mi, _ma in enumerate(_mcall.args):
                if _mi >= len(_mpn):
                    break
                _me, _mne = _static_arg_elems(_ma, _melem, _mnested)
                if _me is not None:
                    _record_param_elem(_mcallee, _mpn[_mi], _me, _mne)
                _mdv = _static_arg_dict_val(_ma, _mdval, caller_name)
                if _mdv is not None:
                    _record_param_dict_val(_mcallee, _mpn[_mi], _mdv)

    # ...and resolve the collected dict-value observations into the contract
    # codegen reads, then re-run the collection once so a FORWARDING chain
    # (`def g(d): return f(d)`) resolves through the hop this pass just
    # settled. One extra round, not a loop to a fixpoint: `g` can only forward
    # a dict value type that some call site of `g`'s already proved, so a
    # second pass settles every chain that exists and a third would add
    # nothing. `_calls_in_stmts` is memoized, so the repeat is cheap.
    _resolve_param_dict_vals()
    for caller_name, body in _caller_bodies:
        elem, nested, dval = self._scan_container_elems(body)
        calls = []
        self._calls_in_stmts(body, calls)
        for call in calls:
            if not isinstance(call.func, IdentExpr):
                continue
            callee = _as_str(call.func.name)
            pnames = _free_params.get(callee)
            if not pnames:
                continue
            for i, a in enumerate(call.args):
                if i >= len(pnames):
                    break
                _dv = _static_arg_dict_val(a, dval, caller_name)
                if _dv is not None:
                    _record_param_dict_val(callee, pnames[i], _dv)
    _resolve_param_dict_vals()


    # A container param whose ELEMENTS the callee `isinstance()`-checks
    # against struct types (`for s in stmts: if isinstance(s, FunctionDef)`)
    # holds boxed AST-node handles, never strings — retract any `char *`
    # element-type conclusion for it (a caller-side `_scan_container_elems`
    # mis-read, e.g. from `{s.name for s in stmts}` string comprehensions
    # elsewhere). Without this the callee's loop var is declared `char *`
    # and `s.name` lowers to `os.path.basename(s)` — the exact reason the
    # compiled `gen_module_impl` emitted no function bodies at all.
    _struct_names_here = ({_as_str(_as_structdef_node(s).name) for s in all_struct_defs if isinstance(s, StructDef)}
                          | set(getattr(self, '_imported_struct_names', ()) or ())
                          | {'FunctionDef', 'StructDef', 'IfStmt', 'ForStmt', 'WhileStmt',
                             'AssignStmt', 'ExprStmt', 'ImportStmt', 'FromImportStmt',
                             'TryStmt', 'ClassDef', 'ReturnStmt', 'AugAssignStmt',
                             'MatchStmt', 'WithStmt', 'ComptimeVarStmt', 'VarDecl'})
    for _callee, _pm in list(self._param_elem_types.items()):
        _cfn = _fn_by_name.get(_callee)
        if not _cfn:
            continue
        for _pn, (_e, _ne) in list(_pm.items()):
            if _e != 'char *':
                continue
            _isinst_elem = False
            for _bn in _walk_ast(_cfn.body):
                # `for <lv> in <pn>:` then `isinstance(<lv>, <StructName>)`
                if (isinstance(_bn, ForStmt)
                        and isinstance(_bn.iterable, IdentExpr)
                        and _bn.iterable.name == _pn):
                    _lv = _bn.target if isinstance(_bn.target, str) else getattr(_bn.target, 'name', None)
                    for _in in _walk_ast(_bn.body):
                        if (isinstance(_in, CallExpr) and isinstance(_in.func, IdentExpr)
                                and _in.func.name == 'isinstance' and len(_in.args) >= 2
                                and isinstance(_in.args[0], IdentExpr)
                                and _in.args[0].name == _lv):
                            _tgt = _in.args[1]
                            _tnames = ([_tgt] if isinstance(_tgt, IdentExpr)
                                       else list(getattr(_tgt, 'elements', [])))
                            if any(isinstance(_t, IdentExpr) and _t.name in _struct_names_here
                                   for _t in _tnames):
                                _isinst_elem = True
                                break
                if _isinst_elem:
                    break
            if _isinst_elem:
                _pm[_pn] = (None, None)

    for callee in sorted(_scalar_obs):
        pmap = _scalar_obs[callee]
        fn = _fn_by_name.get(callee)
        if not fn:
            continue
        ann: dict = {}
        for _an_pn, _an_pt in (fn.params or []):
            ann[_as_str(_an_pn)] = _an_pt
        for pname in sorted(pmap):
            types = pmap[pname]
            _has_dbl = 'double' in types
            _has_cs = 'char *' in types
            if len(types) != 1 or not (_has_dbl or _has_cs):
                # Disagreeing call sites (or evidence for nothing) → left at
                # the `int64_t` default. If one of the observers was a `char *`
                # this slot provably MAY hold a string, and that is the only
                # fact a consumer is allowed to act on: record it, so
                # `_gen_print` can route it through `mojo_cstr_or_int_str`
                # rather than casting the raw bits to `char *`.
                #
                # The `continue`s below (annotated parameter, or a
                # `_infer_param_types` resolution this pass is not entitled
                # to overturn) are NOT here on purpose — those slots are
                # already typed by real evidence, not by the int64_t
                # default, so they never need the discriminator. Only a slot
                # actually left at `int64_t` is recorded.
                if _has_cs and ann.get(pname) is None:
                    self._int64_may_hold_str.setdefault(callee, set()).add(pname)
                continue                         # not unanimous double / char *
            if ann.get(pname) is not None:
                continue                         # respect explicit annotation
            cur = self._inferred_param_types.get(callee, {}).get(pname)
            if cur in (None, 'int', 'int64_t'):
                resolved_type = 'double' if _has_dbl else 'char *'
                self._inferred_param_types.setdefault(callee, {})[pname] = resolved_type

    # The same "this untyped int64_t slot PROVABLY may hold a string"
    # property, for the callable kind the tables above cannot see at all: a
    # `def` NESTED in another function's body.
    #
    # It is invisible for a structural reason. `all_functions` is the
    # module's top-level statement list, and `_free_params` / `_fn_by_name` /
    # `_caller_bodies` are all built from it, so a nested `def` has no entry
    # in any of the three. Its call sites WERE reachable -- `_calls_in_stmts`
    # descends into a nested body from the enclosing function's own entry --
    # so the evidence was collected and then dropped at the
    # `_free_params.get(callee)` lookup, one line above.
    #
    # The consequence was an untyped parameter that a real string was passed
    # into, printed as its own pointer decimal:
    #     def outer():
    #         def inner(s):
    #             print(s)
    #         inner("A")
    # `s` is physically `int64_t` (`_gen_lifted_closure` types a parameter with
    # no annotation that way whatever it is handed), `_actual_types` has
    # nothing to say about it inside the lifted body, and `_gen_print` fell
    # through to the generic `%ld` arm.
    #
    # This is the one place in the pipeline that still has the whole module's
    # AST in hand: when the lifted closure's body is emitted the evidence is
    # gone, so it is collected here and keyed by the name the C function
    # ACTUALLY GETS -- `ClosureInfo.lifted_name`, which is also what
    # `gen.current_func_name` is while that body is lowered, which is what
    # `_is_may_hold_str_param` asks with. Keying by the source name would
    # record a fact nobody can look up.
    #
    # Deliberately narrow, in three ways, each of which is the difference
    # between this and a new guess:
    #   * POSITIVE evidence only -- a call site whose argument type is
    #     positively `char *`. `_arg_scalar_type` answers that for a string
    #     literal and (with `deep_str`) for a provably-str expression, and is
    #     silence for anything it cannot prove, exactly as for a top-level
    #     callee. The scope it is given is the one the call site is really
    #     inside, so an `IdentExpr` argument resolves against the right
    #     function's locals.
    #   * IT CHANGES NO C SIGNATURE. Nothing here resolves a parameter to
    #     `char *`; the slot stays `int64_t` and the consumer asks the
    #     runtime's own discriminator (`mojo_cstr_or_int_str`), whose
    #     documented bound -- an int64 in `[2^31, 2^47)` reads as a pointer --
    #     is the bound this whole table already accepts.
    #   * ANNOTATED parameters are skipped, the same rule the loop above
    #     applies: a real annotation is real evidence, so the slot never needs
    #     the discriminator.
    def _gmi_scope_bodies(body, outer_lifted: str) -> list:
        """(compiled-under name, body) for `body` and every `def` nested in
        it, at any depth. The name is what `_arg_scalar_type(caller_name, ...)`
        has to be given for a call inside that scope: the enclosing function's
        OWN name for a top-level `def`, its lifted `<outer>_<name>` for a
        nested one. Getting it wrong is how an `IdentExpr` argument would
        resolve against an unrelated function's locals."""
        out = [(outer_lifted, body)]
        for _n in _walk_ast(body):
            if not isinstance(_n, FunctionDef):
                continue
            _nf = _as_funcdef_node(_n)
            if (getattr(_nf, 'is_async', False)
                    and not getattr(_nf, 'is_generator', False)):
                continue
            out.extend(_gmi_scope_bodies(_as_list(_nf.body),
                                         closure_lifted_name(outer_lifted,
                                                             _as_str(_nf.name))))
        return out

    _gmi_scopes: list = [(_TOPLEVEL_CALLER, stmts)]
    for _cs_s in all_functions:
        if isinstance(_cs_s, FunctionDef):
            _cs_fn = _as_funcdef_node(_cs_s)
            _gmi_scopes.extend(_gmi_scope_bodies(_as_list(_cs_fn.body),
                                                 _as_str(_cs_fn.name)))
    # PARALLEL LISTS, not tuples indexed positionally through a for-target
    # unpack: on the self-hosted path a multi-element `for` target erases
    # each element to int64_t (`discover_closures` and `lambdareduce` both
    # document that trap at length, and `_walk_own_body`'s own comment
    # records the generator variant of it), so a `(owner, src, lifted, …)`
    # tuple would arrive here with boxed strings that never compare equal to
    # the name they should and a silent no-op in the compiled compiler.
    _gmi_own: list = []
    _gmi_src: list = []
    _gmi_lift: list = []
    _gmi_pn: list = []
    _gmi_def: list = []
    for _gscope_i in range(len(_gmi_scopes)):
        _scope_ent = _gmi_scopes[_gscope_i]
        _scope_name = _as_str(_scope_ent[0])
        _scope_body = _scope_ent[1]
        for _lsc in _walk_ast(_scope_body):
            if not isinstance(_lsc, FunctionDef):
                continue
            _lsf = _as_funcdef_node(_lsc)
            if (getattr(_lsf, 'is_async', False)
                    and not getattr(_lsf, 'is_generator', False)):
                continue
            _lpn: list = []
            _lpar = _as_list(_lsf.params) or []
            for _lp_i in range(len(_lpar)):
                _lpp = _as_str(_lpar[_lp_i][0])
                _lpt = _lpar[_lp_i][1]
                if _lpp.startswith('*'):
                    continue
                if _lpt is not None:
                    continue                    # respect explicit annotation
                _lpn.append(_lpp)
            if not _lpn:
                continue
            _lname = _as_str(_lsf.name)
            _gmi_own.append(_scope_name)
            _gmi_src.append(_lname)
            _gmi_lift.append(closure_lifted_name(_scope_name, _lname))
            _gmi_pn.append(_lpn)
            _gmi_def.append(_lsf)
    _gmi_rec: dict = {}
    for _gscope_i in range(len(_gmi_scopes)):
        _scope_ent = _gmi_scopes[_gscope_i]
        _scope_name = _as_str(_scope_ent[0])
        _scope_body = _scope_ent[1]
        _gmi_calls: list = []
        self._calls_in_stmts(_scope_body, _gmi_calls)
        for _gcall in _gmi_calls:
            if not isinstance(_gcall.func, IdentExpr):
                continue
            _gcallee = _as_str(_gcall.func.name)
            # The def's OWN scope wins over a same-named one elsewhere: two
            # unrelated functions can each nest a `helper`, and the enclosing
            # scope is what says which of them this call site means.
            # The def's OWN scope wins over a same-named one elsewhere: two
            # unrelated functions can each nest a `helper`, and the enclosing
            # scope is what says which of them this call site means. Index
            # walks over the parallel lists above, never a for-target unpack
            # (see their own note).
            _gmatch = -1
            for _gni in range(len(_gmi_src)):
                if _as_str(_gmi_src[_gni]) != _gcallee:
                    continue
                if _gmatch < 0:
                    _gmatch = _gni
                if _as_str(_gmi_own[_gni]) == _scope_name:
                    _gmatch = _gni
                    break
            if _gmatch < 0:
                continue
            _glift = _as_str(_gmi_lift[_gmatch])
            _gpn = _gmi_pn[_gmatch]
            _gargs = _as_list(_gcall.args) or []
            _gslot = _gmi_rec.setdefault(_glift, set())
            for _gi in range(len(_gargs)):
                if _gi >= len(_gpn):
                    break
                if _arg_scalar_type(_scope_name, _gargs[_gi], deep_str=True) != 'char *':
                    continue
                _gslot.add(_gpn[_gi])
    for _grk in _gmi_rec:
        # `setdefault` into a NAMED local, then merge into it: the chained
        # `d.setdefault(k, set()).update(...)` form has no static type on its
        # intermediate result self-hosted, which is why the `_scalar_obs`
        # loop above splits its own out (see its comment).
        _grk_names = self._int64_may_hold_str.setdefault(_grk, set())
        _grk_names.update(_gmi_rec[_grk])
    # Pass 1.3d-struct: the same unanimity-over-call-sites contract as the
    # loop above, for a REGISTERED STRUCT pointer.
    #
    # The override policy is deliberately WIDER than the scalar loop's, and
    # that is the whole point: the types it replaces are not inferences, they
    # are the name-based builtin-container FALLBACKS. `_infer_param_types` has
    # no way to express "this receiver is a user struct", so a parameter used
    # as a method receiver — which contributes no field accesses, so the
    # struct-inference branch requiring `len(fields_accessed) > 0` never even
    # runs — was decided purely by the method's NAME: `get`/`items`/`keys` ->
    # `MojoDict *`, `hex`/`decode` -> `MojoBytes *`, `find`/... -> `char *` or
    # nothing, everything else -> the `int64_t` default. A user class may
    # define a method with any of those names, and when it does the callee's
    # receiver reached a dict/bytes runtime helper (SIGBUS/SIGSEGV) or, worse,
    # was boxed and passed straight through (`4328331776` — the `Box *`
    # printed as a decimal, exit 0).
    #
    # So the entries that may be replaced are exactly the no-evidence ones.
    # A param `_infer_param_types` resolved to anything else — a real struct
    # from the field match, `char *` from a subscription or a `char`-compare,
    # a container from iteration — was decided on evidence this pass does not
    # have, and unanimity over call sites is not grounds to overturn it.
    #
    # And the refinement is scoped to parameters that are actually used as a
    # METHOD RECEIVER (`p.<m>(...)`), because that is the shape whose only
    # other possible typing is a name-based guess. Widening it to every
    # unanimous struct argument retypes dynamic-attribute receivers too:
    # `def get_or_init(cls): cls.__slot_names__` called as
    # `get_or_init(Holder())` is a DYNAMIC attribute read whose whole point
    # is that it must stay opaque until an AttributeError says otherwise, and
    # typing it `Holder *` turned `_mojo_dispatch_getattr` into a direct
    # `->__slot_names__` field read on a struct with no such field — a hard
    # GCC "'Holder' has no member named '__slot_names__'" failure
    # (test_gimple_runner.py's
    # `gimple_dynamic_attribute_real_storage_and_attributeerror`). A method
    # call, by contrast, has exactly one lowering — the struct's own mangled
    # method — so there is nothing for the name-based fallback to get right.

    # Past 1.3d proper: propagate the may-hold-a-string property out of the
    # slots recorded above. It is one property of a VALUE, and a value is not
    # confined to the slot it arrived in -- `y = x` copies it, `return x`
    # publishes it to every caller, and a caller hands its own property to the
    # callee it calls. Without this, `print` only learns about a parameter read
    # DIRECTLY (`print(x)`), so every shape that moves the value first printed
    # the boxed pointer's decimal and exited 0 -- exactly the
    # silent-wrong-value shape that recording the slot exists to prevent. That
    # was measured for a local alias (`y = x`), a direct return (`return x`,
    # printed at the call site), and a forwarding chain (`def g(x): return
    # f(x)`), none of which the collection loop alone can reach: a callee like
    # `f` in the third case has no call site of its own passing a literal, so
    # it appears in no `_scalar_obs` entry at all.
    #
    # So this is an interprocedural fixed point with edges in three directions,
    # each monotone in one direction only (a name is added, never removed):
    #
    #   forward-in-body       `y = x` within one function
    #   backward-along-call   a caller's argument property becomes the callee's
    #                         parameter property -- this is what carries `g`'s
    #                         evidence into `f` in the forwarding chain
    #   forward-along-call    a returned expression's property becomes the
    #                         function's own return property
    #
    # Termination is by construction rather than by a visit budget: the only
    # mutation anywhere is adding a name to one of a bounded number of sets,
    # and a cycle (`def f(x): return f(x)`) simply never adds anything.
    # Deliberately order-insensitive and conservative elsewhere: an assignment
    # anywhere in the body adds its target, and a later overwrite is not
    # subtracted. That is sound for the one consumer there is --
    # `mojo_cstr_or_int_str` is exact for a small integer (it prints the
    # integer) and wrong only for one in `[2^31, 2^47)`, and that bound is what
    # the collection loop above exists to enforce by only ever seeding a slot a
    # `char *` was really observed at.
    _int_maybe = self._int64_may_hold_str
    _ret_maybe: set = set()
    # Per-function walk results, computed ONCE: the fixed point below re-scans
    # them every round, and `_walk_ast` over every body of a 60-module closure
    # is not something to repeat until convergence.
    _calls: dict = {}        # fname -> [(callee, [arg nodes])]
    _rets: dict = {}         # fname -> [returned expression nodes]
    _copies: dict = {}       # fname -> [(target name, source name)]
    _params: dict = {}       # fname -> [param names in order]
    # A nested `def`'s C name, per OWNING scope: source name -> lifted name.
    # The fixed point below resolves a call site by looking its callee up in
    # `_params`, so a call to a nested `def` — spelled with the SOURCE name
    # at the call site, emitted under the LIFTED name — has to be recorded
    # under the latter, and it has to be the enclosing scope's entry: two
    # unrelated functions can each nest a `helper`.
    _nested_lifted: dict = {}
    for _gni in range(len(_gmi_src)):
        _gown = _as_str(_gmi_own[_gni])
        _gsrc = _as_str(_gmi_src[_gni])
        _glift = _as_str(_gmi_lift[_gni])
        _gpair = _nested_lifted.setdefault(_gown, {})
        _gpair[_gsrc] = _glift

    def _gmi_param_names(params) -> list:
        # A plain loop, not a comprehension with a two-element for-target
        # unpack: both halves of that idiom are individually documented traps
        # on the self-hosted path (a comprehension's target unpack boxes both
        # slots -- `discover_closures`' `self_/moa/` example -- and this
        # file's own `_record_param_elem` comment repeats it).
        out = []
        par = _as_list(params) or []
        for i in range(len(par)):
            pn = _as_str(par[i][0])
            if pn.startswith('*'):
                continue
            out.append(pn)
        return out

    for _fname, _fn in _fn_by_name.items():
        _params[_fname] = _gmi_param_names(_fn.params)
        _calls[_fname] = []
        _rets[_fname] = []
        _copies[_fname] = []
        _fname_rename = _nested_lifted.get(_fname, {})
        for _nd in _walk_ast(_fn.body):
            if (isinstance(_nd, gimple_ctypes.AssignStmt)
                    and isinstance(_nd.target, IdentExpr)
                    and isinstance(_nd.value, IdentExpr)):
                _copies[_fname].append((_as_str(_nd.target.name),
                                        _as_str(_nd.value.name)))
            elif isinstance(_nd, gimple_ctypes.ReturnStmt):
                if _nd.value is not None:
                    _rets[_fname].append(_nd.value)
            elif (isinstance(_nd, gimple_ctypes.CallExpr)
                    and isinstance(_nd.func, gimple_ctypes.IdentExpr)):
                _cname = _as_str(_nd.func.name)
                if _cname not in _fn_by_name and _cname not in _fname_rename:
                    continue
                _calls[_fname].append((_fname_rename.get(_cname, _cname),
                                       list(_nd.args or [])))
    # The same four tables for every nested `def`, which the loop above cannot
    # see: its body IS reached (the walk descends into it) but it is credited
    # to the enclosing function, and its own name is in neither `_fn_by_name`
    # nor `_params`. One fixed point, fed both — not a second one.
    # Index-walk, NOT a tuple-unpack `for` target: a multi-element unpack
    # in a for target erases each element to int64_t on the self-hosted
    # path (the trap `discover_closures` and `lambdareduce` each
    # document at length), and a boxed name never compares equal.
    for _gni in range(len(_gmi_src)):
        _glift = _as_str(_gmi_lift[_gni])
        _gpn = _gmi_pn[_gni]
        _params[_glift] = list(_gpn)
        _calls[_glift] = []
        _rets[_glift] = []
        _copies[_glift] = []
        _glift_rename = _nested_lifted.get(_glift, {})
        _gdef = _gmi_def[_gni]
        for _nd in _walk_ast(_as_list(_gdef.body)):
            if (isinstance(_nd, gimple_ctypes.AssignStmt)
                    and isinstance(_nd.target, IdentExpr)
                    and isinstance(_nd.value, IdentExpr)):
                _copies[_glift].append((_as_str(_nd.target.name),
                                        _as_str(_nd.value.name)))
            elif isinstance(_nd, gimple_ctypes.ReturnStmt):
                if _nd.value is not None:
                    _rets[_glift].append(_nd.value)
            elif (isinstance(_nd, gimple_ctypes.CallExpr)
                    and isinstance(_nd.func, gimple_ctypes.IdentExpr)):
                _cname = _as_str(_nd.func.name)
                if _cname not in _fn_by_name and _cname not in _glift_rename:
                    continue
                _calls[_glift].append((_glift_rename.get(_cname, _cname),
                                       list(_nd.args or [])))

    def _expr_may(fname, expr) -> bool:
        """Does `expr`, read in `fname`'s own scope, carry the property?"""
        if isinstance(expr, gimple_ctypes.IdentExpr):
            return _as_str(expr.name) in _int_maybe.get(fname, ())
        if (isinstance(expr, gimple_ctypes.CallExpr)
                and isinstance(expr.func, gimple_ctypes.IdentExpr)):
            return _as_str(expr.func.name) in _ret_maybe
        return False

    _changed = True
    while _changed:
        _changed = False
        for _fname, _pairs in _copies.items():
            _names = _int_maybe.setdefault(_fname, set())
            for _t, _v in _pairs:
                if _v in _names and _t not in _names:
                    _names.add(_t)
                    _changed = True
        for _fname, _sites in _calls.items():
            for _callee, _args in _sites:
                _pn = _params.get(_callee)
                if not _pn:
                    continue
                for _i, _a in enumerate(_args):
                    if _i >= len(_pn):
                        break
                    if _expr_may(_fname, _a):
                        _names = _int_maybe.setdefault(_callee, set())
                        if _pn[_i] not in _names:
                            _names.add(_pn[_i])
                            _changed = True
        for _fname, _exprs in _rets.items():
            if _fname in _ret_maybe:
                continue
            for _e in _exprs:
                if _expr_may(_fname, _e):
                    _ret_maybe.add(_fname)
                    _changed = True
                    break
    self._ret_may_hold_str = _ret_maybe

    _STRUCT_FALLBACKS = ('MojoDict *', 'MojoList *', 'MojoSet *', 'MojoBytes *',
                         'MojoStr *', 'char *', 'int', 'int64_t')
    for callee in sorted(_struct_obs):
        pmap = _struct_obs[callee]
        fn = _fn_by_name.get(callee)
        if not fn:
            continue
        ann: dict = {}
        for _an_pn, _an_pt in (fn.params or []):
            ann[_as_str(_an_pn)] = _an_pt
        # A METHOD RECEIVER, a direct argument to a struct CONSTRUCTOR call,
        # or an argument FORWARDED to another function in this body.
        # Receiver: not rooted at a subscript/slice of the param, which is a
        # container (`p[0].m()`) and not this param at all.
        #
        # Constructor argument: `def mk(t): return L(t, 'hi')` called as
        # `mk(T(8))` is the same one-hop shape with no receiver anywhere —
        # the struct is learned at `mk`'s call site and has to travel one more
        # hop to reach `L.__init__`'s own parameter. This used to stop at the
        # receiver restriction, so `L`'s slot got no evidence from `mk`'s body
        # at all and `mk`'s parameter stayed `int64_t`: the pointer was
        # re-boxed on the way in and `x.numel()` printed the box's decimal
        # (the module-scope/module-global cases of the same family).
        #
        # Forwarding: the same one-hop shape again, one level of pure
        # indirection further out. `def b(w): return a(w).numel()` with
        # `a(w) -> L(w)` is a dataclass travelling through two thin wrappers,
        # and `w` is in `b`'s body only as `a(w)`'s argument — a bare
        # identifier, which is the shape whose own type IS the callee's
        # parameter type. Without this arm `b`'s parameter kept the `int64_t`
        # default, `a`'s argument was read as a boxed integer at `a`'s call
        # site, and `L.__init__`'s slot saw no struct anywhere, so every
        # `self.<field>.<method>()` down the chain hit the generic no-op stub
        # and returned the pointer's own bits: exit 0, no diagnostic.
        #
        # All three arms are scoped to a BARE identifier argument (`L(t)`,
        # `a(t)`, never `L(t.n)` or `a(self.t)`), because that is the shape
        # where the argument's own type IS the parameter's type; any
        # derivation would make the observation about the derived expression
        # rather than about `pname`. Widening WHICH callee a bare identifier
        # may be forwarded to does not widen the EVIDENCE: every gate below
        # still has to pass, and it now also has to survive the propagation
        # fixpoint that follows.
        struct_evidence_params: set = set()
        _rcalls: list = []
        self._calls_in_stmts(fn.body, _rcalls)
        for _rc in _rcalls:
            if isinstance(_rc.func, MemberExpr):
                if isinstance(_rc.func.obj, IdentExpr):
                    struct_evidence_params.add(_as_str(_rc.func.obj.name))
            elif isinstance(_rc.func, IdentExpr):
                for _rc_a in _rc.args:
                    if isinstance(_rc_a, IdentExpr):
                        struct_evidence_params.add(_as_str(_rc_a.name))
        for pname in sorted(pmap):
            if pname not in struct_evidence_params:
                continue
            types = pmap[pname]
            # Not unanimous -> the parameter is genuinely polymorphic here and
            # nothing about it is provable; same refusal the scalar loop makes.
            if len(types) != 1:
                continue
            # `sorted(...)` + index, NOT `next(iter(...))`: iterating a
            # str-SET lowers to mojo_set_iter_val_int (0 for every string
            # slot) on the self-hosted path, exactly as the struct-evidence
            # list in `_infer_param_types` documents. It sorts string CONTENT.
            _sole = sorted(types)
            if len(_sole) != 1:
                continue
            _st = _gmi_as_str(_sole[0])
            if not _st.endswith(' *'):
                continue
            if _st[:-2] not in self.struct_field_types:
                continue
            if ann.get(pname) is not None:
                continue                         # respect explicit annotation
            cur = self._inferred_param_types.get(callee, {}).get(pname)
            if cur is not None and cur not in _STRUCT_FALLBACKS:
                continue
            self._inferred_param_types.setdefault(callee, {})[pname] = _st

    # The same contract one hop FURTHER OUT, and the reason the arm above is
    # not enough on its own. Admission above resolves a parameter from its own
    # CALL SITES; `a`'s parameter in `b(w) -> a(w) -> L(w)` has none, because
    # nothing in the module calls `a` directly. The evidence is one level up —
    # in `b`'s body, where `w`'s own type is now known — so it has to be
    # PROPAGATED, and propagation has to run to a fixpoint because each hop can
    # only see the previous one.
    #
    # This is the struct-pointer twin of the container rule
    # `_infer_param_types` already applies ("passing the param to a user
    # function whose own parameter at that position was inferred as a
    # container is iteration evidence"), and of the ctor caller-side twin
    # further down this function, which does the same one hop for a
    # constructor argument. All three are the same rule at three positions in
    # the call graph, and this is the only one that could cross free
    # functions.
    #
    # Every gate the ctor twin uses is reused here, unchanged: an explicit
    # annotation wins, a defaulted parameter keeps its default-derived type
    # (a call site that omits the argument would otherwise feed the default
    # through the refined C type), only a no-evidence type is replaced, and —
    # the gate the twins do not need — CONTRARY call-site evidence vetoes the
    # hop. That last one is what keeps the chain honest: if `a`'s own callers
    # unanimously pass something other than a `T *`, this hop is refused even
    # though `b` says otherwise, which is the same disagreement a real
    # overload would produce.
    #
    # Bounded, for the reason the ctor fixpoint is: a chain longer than a
    # handful of hops is a closure, and an unbounded walk here is a loop over a
    # graph being mutated by the walk. Four rounds is the same bound the
    # constructor fixpoint uses, for the same reason. Idempotent by
    # construction: a second round over the same evidence finds every hop
    # already at its final value.
    for _fwd_round in range(4):
        _fwd_changed = False
        for _fcaller, _fbody in _caller_bodies:
            _fcalls: list = []
            self._calls_in_stmts(_fbody, _fcalls)
            for _fc in _fcalls:
                if not isinstance(_fc.func, IdentExpr):
                    continue
                _fcallee = _as_str(_fc.func.name)
                _fpns = self._func_param_names.get(_fcallee)
                _ffn = _fn_by_name.get(_fcallee)
                if not _fpns or not _ffn:
                    continue
                _fann: dict = {}
                for _fp, _fpt in (_ffn.params or []):
                    _fann[_as_str(_fp)] = _fpt
                _fdflt = getattr(_ffn, 'param_defaults', {}) or {}
                for _fi, _fa in enumerate(_fc.args):
                    if _fi >= len(_fpns):
                        break
                    if not isinstance(_fa, IdentExpr):
                        continue
                    _fan = _as_str(_fa.name)
                    _fst = self._inferred_param_types.get(
                        _fcaller, {}).get(_fan)
                    if not (isinstance(_fst, str) and _fst.endswith(' *')
                            and _fst[:-2] in self.struct_field_types):
                        continue
                    _fq = _as_str(_fpns[_fi])
                    if _fann.get(_fq) is not None:
                        continue            # respect explicit annotation
                    if _fq in _fdflt:
                        continue            # respect default-value inference
                    _fcur = self._inferred_param_types.get(
                        _fcallee, {}).get(_fq)
                    if _fcur is not None and _fcur not in _STRUCT_FALLBACKS:
                        continue            # only a no-evidence type
                    _fobs = (_struct_obs.get(_fcallee) or {}).get(_fq)
                    if _fobs:
                        # Contrary call-site evidence vetoes the hop. Compared
                        # through `sorted(...)` + index for the same
                        # self-hosted reason as the admission loop above.
                        _fsole = sorted(_fobs)
                        if len(_fsole) != 1 or _fsole[0] != _fst:
                            continue
                    if _fcur == _fst:
                        continue
                    _fwd_changed = True
                    self._inferred_param_types.setdefault(
                        _fcallee, {})[_fq] = _fst
        if not _fwd_changed:
            break

    # Coroutine-bound functions (generators/async defs about to go down the
    # C++20-coroutine pre-pass) never get an ordinary gen_func compile, so
    # the usage-based parameter inference `_gen_lifted_closure` relies on
    # (`_infer_param_types`) never ran for them: their unannotated params
    # all defaulted to int64_t in the emitted coroutine signature, so a
    # string param hit "invalid conversion from 'int64_t' to 'char*'" at
    # every co_yield/str-method site (Lib/ctypes/macholib/dyld.py's
    # dyld_default_search(name) et al). Seed the SAME shared
    # _inferred_param_types registry here — call-site literal evidence
    # (just above) deliberately wins, explicit annotations are respected,
    # and ambiguous 'int' results are skipped — so `_param_ctype`, read by
    # BOTH the coroutine unit builder and func_param_types registration
    # below, sees the real inferred types. Scoped strictly to functions
    # still bound for the coroutine path: ordinary functions keep their
    # existing evidence pipeline untouched.
    for _cs_fn in all_functions:
        if not isinstance(_cs_fn, FunctionDef):
            continue
        if id(_cs_fn) not in _generator_fns and id(_cs_fn) not in _async_fns:
            continue
        _cs_inferred = self._infer_param_types(_cs_fn)
        for _pn, _ct in _cs_inferred.items():
            if _ct == 'int':
                continue
            if _pn in ('self', 'cls'):
                continue
            _cur = self._inferred_param_types.get(_cs_fn.name, {}).get(_pn)
            if _cur is None:
                self._inferred_param_types.setdefault(_cs_fn.name, {})[_pn] = _ct

    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef):
            if gimple_ctypes._params_have_vararg(s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = _free_func_param_ctypes(self, s)

    _ctor_scalar_obs: dict = {}          # "<struct>::<pname>" -> scalar type
    _ctor_scalar_conflict: dict = {}     # "<struct>::<pname>" -> True (mixed)
    # This is the CONSTRUCTOR direction of
    # the ctor-direction cross-call struct contract. The repro's
    # receiver is `self.w` inside `L.numel`, whose type is whatever `__init__`'s
    # own unannotated `w` was typed — so the evidence this pass needs is at
    # the `L(T(15))` CALL SITE, and no free-function signature pass can see
    # it. `_arg_scalar_type` returns None for a struct-constructor argument
    # (`L(T(15))`'s `T(15)` is a CallExpr, and the IdentExpr arm's answer is
    # filtered to nothing unless it is `char *`/`double`), so before this the
    # slot had no evidence at all: `__init__`'s `w` stayed `int64_t`, the field
    # `w` inherited it, and `self.w.numel()` degraded to the generic no-op
    # stub — a pointer's own bits printed as a decimal, exit 0.
    #
    # A struct pointer shares `_ctor_scalar_obs` rather than getting its own
    # map, unlike Pass 1.3d's `_struct_obs`/`_scalar_obs` split, because here
    # a slot holds exactly ONE ctype and any two different answers are a
    # genuine conflict of equal standing. Pass 1.3d's split exists only because
    # its `_scalar_obs` set is shared across a whole free function's params
    # and its scalar admission rule is a `char *`/`double` whitelist; a
    # `<Struct> *` landing in that same set would suppress an otherwise
    # unanimous `char *` on a DIFFERENT parameter. Here the comparison is
    # always against the same `<struct>::<param>` key, so one map with the
    # existing "different from what is already recorded → conflict" rule
    # expresses both cases correctly and needs no second set of maps.
    #
    # Both `_method_caller_bodies` (below) and `_caller_bodies` are walked,
    # for the reason the scalar observer's own comment gives: a `S(...)`
    # constructed from a method body is a real and common shape
    # (`NamespaceReader(self._path)` in importlib/_bootstrap_external.py),
    # and `_method_caller_bodies` additionally carries the owning StructDef,
    # which is what resolves a `self.<field>` argument.
    #
    # COLLECTION and APPLICATION run to a small bounded fixpoint, because each
    # can feed the other and neither sees the other's output within one pass.
    # The concrete case that needs it is the `self.<field>` argument above: a
    # `Box(self.t)` inside `Holder.go` can only be observed once `Holder.t`
    # itself has a `T *` field type, and that type is written by the
    # APPLICATION half below from the very same observation map. One pass sees
    # `Holder.t` as the `int64_t` default and records no evidence for
    # `Box.w`; the second sees the `T *` and resolves it. The same one-hop
    # structure Pass 1.3e solves for pure method-forwarding chains, and the
    # same bound, for the same reason (a bounded number of hops is all real
    # code has; an unbounded one would be a closure). Re-collecting is
    # idempotent by construction: `_ctor_scalar_obs` records the first answer
    # per key and only ever adds a conflict flag on a DISAGREEMENT, so a
    # second round over the same evidence cannot change any key.
    for _ctor_round in range(4):
        _ctor_changed = False
        for _cname, _cstruct, _cbody in _method_caller_bodies:
            calls = []
            self._calls_in_stmts(_cbody, calls)
            for call in calls:
                if not isinstance(call.func, IdentExpr):
                    continue
                struct_name = _as_str(call.func.name)
                pnames = _ctor_init_params.get(struct_name)
                if not pnames:
                    continue
                for i, a in enumerate(call.args):
                    if i >= len(pnames):
                        break
                    _skey = struct_name + '::' + _as_str(pnames[i])
                    st = _arg_scalar_type(_cname, a, caller_struct=_cstruct)
                    if not st:
                        st = _arg_struct_ptr_type(_cname, a, _cstruct)
                    if not st:
                        continue
                    _sprev = _ctor_scalar_obs.get(_skey, '')
                    if not _sprev:
                        _ctor_scalar_obs[_skey] = st
                    elif _sprev != st:
                        _ctor_scalar_conflict[_skey] = True
        for caller_name, body in _caller_bodies:
            calls = []
            self._calls_in_stmts(body, calls)
            for call in calls:
                if not isinstance(call.func, IdentExpr):
                    continue
                struct_name = _as_str(call.func.name)
                pnames = _ctor_init_params.get(struct_name)
                if not pnames:
                    continue
                for i, a in enumerate(call.args):
                    if i >= len(pnames):
                        break
                    _skey = struct_name + '::' + _as_str(pnames[i])
                    st = _arg_scalar_type(caller_name, a)
                    if not st:
                        st = _arg_struct_ptr_type(caller_name, a, None)
                    if not st:
                        continue
                    _sprev = _ctor_scalar_obs.get(_skey, '')
                    if not _sprev:
                        _ctor_scalar_obs[_skey] = st
                    elif _sprev != st:
                        _ctor_scalar_conflict[_skey] = True

        for _csn in _ctor_init_params:
            _init = _ctor_init_methods.get(_csn)
            if not _init:
                continue
            _ann = {}
            for _ap2 in (_init.params or []):
                _ann[_as_str(_ap2[0])] = _ap2[1]
            _init_defaults = getattr(_init, 'param_defaults', {}) or {}
            for pname in _ctor_init_params[_csn]:
                _skey2 = _csn + '::' + pname
                # VETO: this observer only ever produces `char *` / `double`
                # / a `<Struct> *`, so it cannot see the container-literal
                # evidence the pass above collected. Without the veto,
                # `Thing([1, 2])` beside `Thing("s")` found this observer's own
                # evidence unanimous and typed the field `char *` — a silent
                # wrong answer where the documented rule is "not unanimous →
                # leave unresolved, the int64_t default". Veto-only by
                # construction: it can refuse a slot, never resolve one, so it
                # cannot widen what this pass already accepted.
                _lit_ct_obs = self._ctor_container_lit_obs.get(_skey2, '')
                if self._ctor_container_lit_conflict.get(_skey2) or (
                        _lit_ct_obs and _lit_ct_obs != _ctor_scalar_obs.get(_skey2, '')):
                    continue
                _st2 = _ctor_scalar_obs.get(_skey2, '')
                # FLAT dicts + string comparison, NOT `types not in ({'double'},
                # {'char *'})` over a nested `dict[str, dict[str, set]]`: the
                # set-of-sets membership test is unreliable self-hosted, and a
                # nested dict's `.get` returns an untyped int, so neither the
                # inner membership nor the set comparison worked.
                #
                # A `<Struct> *` observation is admitted here too, and only that
                # one extra shape: the observer above can now return a struct
                # pointer, and admitting it here is what carries that evidence
                # into `pm` (the `__init__` parameter's own C type) and hence
                # into the field `self.w = w` writes. It stays a strictly
                # narrower widening than Pass 1.3d-struct's, which required the
                # parameter to be a METHOD RECEIVER in the callee's body —
                # there is no such requirement here, because for a CONSTRUCTOR
                # the whole point is that the parameter is only ever stored in
                # a field and read back through it, and refusing to admit it is
                # what left `self.w.numel()` reading `int64_t.numel()`
                # (the ctor-direction cross-call struct contract).
                # Admission still requires unanimity (the conflict dict above),
                # a registered struct, and no container-literal veto.
                if _st2 != 'double' and _st2 != 'char *':
                    if not (_st2.endswith(' *') and _st2[:-2] in self.struct_field_types):
                        continue                # none, or not unanimous
                if _ctor_scalar_conflict.get(_skey2):
                    continue                    # mixed scalar evidence
                _resolved_type = _st2
                if _ann.get(pname) is not None:
                    continue                    # respect explicit annotation
                if pname in _init_defaults:
                    continue                    # respect default-value inference
                if self._ctor_lit_param_types.get(_csn + '::' + pname) == _resolved_type:
                    continue
                _ctor_changed = True
                self._ctor_lit_param_types[_csn + '::' + pname] = _resolved_type
                for node in _walk_ast(_init.body):
                    if not isinstance(node, AssignStmt):
                        continue
                    tgt = node.target
                    if not (isinstance(tgt, MemberExpr) and isinstance(tgt.obj, IdentExpr)
                            and tgt.obj.name == 'self'):
                        continue
                    v = node.value
                    if isinstance(v, IdentExpr) and v.name == pname:
                        _fld_types = self.struct_field_types.setdefault(_csn, {})
                        if _fld_types.get(tgt.member) in (None, 'int', 'int64_t'):
                            _fld_types[tgt.member] = _resolved_type

        # The CALLER-side twin of the same fixpoint: a free function's
        # unannotated parameter that is FORWARDED straight into a
        # constructor slot now knows what that slot holds, so it is that
        # struct pointer. Without this the constructor is typed correctly at
        # its own definition but the forwarding function's parameter stays
        # `int64_t`, and the value is re-boxed on the way in —
        # `def mk(t): return L(t, 'hi')` called as `mk(T(8))` printed
        # `L`'s receiver's own pointer bits instead of `8`.
        #
        # This is the mirror image of the rule `_infer_param_types` already
        # applies to containers ("a parameter passed to a callee whose own
        # parameter was inferred as a container is a container"), and it needs
        # the same admission discipline Pass 1.3d-struct's application loop
        # documents: an explicit annotation wins, a defaulted parameter keeps
        # its default-derived type (a call site omitting the argument would
        # otherwise feed the default through the refined C type), and only a
        # no-evidence type is replaced.
        for _cpn, _cbody2 in _caller_bodies:
            _cpcalls: list = []
            self._calls_in_stmts(_cbody2, _cpcalls)
            for _cpc in _cpcalls:
                if not isinstance(_cpc.func, IdentExpr):
                    continue
                _cp_pnames = _ctor_init_params.get(_as_str(_cpc.func.name))
                if not _cp_pnames:
                    continue
                for _cp_i, _cp_a in enumerate(_cpc.args):
                    if _cp_i >= len(_cp_pnames):
                        break
                    if not isinstance(_cp_a, IdentExpr):
                        continue
                    _cp_argn = _as_str(_cp_a.name)
                    _cp_fn = _fn_by_name.get(_as_str(_cpn))
                    if not _cp_fn:
                        continue
                    _cp_ann = None
                    _cp_isdef = False
                    for _cp_p, _cp_pt in (_cp_fn.params or []):
                        if _as_str(_cp_p) == _cp_argn:
                            _cp_ann = _cp_pt
                            break
                    if _cp_ann is not None:
                        continue                # respect explicit annotation
                    _cp_dfl = getattr(_cp_fn, 'param_defaults', {}) or {}
                    if _cp_argn in _cp_dfl:
                        continue                # respect default-value inference
                    _cp_slot = _as_str(_cpc.func.name) + '::' + _as_str(_cp_pnames[_cp_i])
                    _cp_st = self._ctor_lit_param_types.get(_cp_slot, '')
                    if not (_cp_st.endswith(' *') and _cp_st[:-2] in self.struct_field_types):
                        continue
                    _cp_cur = self._inferred_param_types.get(_as_str(_cpn), {}).get(_cp_argn)
                    if _cp_cur is not None and _cp_cur not in _STRUCT_FALLBACKS:
                        continue
                    if _cp_cur == _cp_st:
                        continue
                    _ctor_changed = True
                    self._inferred_param_types.setdefault(_as_str(_cpn), {})[_cp_argn] = _cp_st
        if not _ctor_changed:
            break

    for _gm_stmt in stmts:
        if isinstance(_gm_stmt, AssignStmt) and isinstance(_gm_stmt.target, IdentExpr):
            self._cpp_early_global_names.add(_gm_stmt.target.name)
        elif isinstance(_gm_stmt, ImportStmt):
            for _tm, _ta in _import_targets(_gm_stmt):
                self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
        elif isinstance(_gm_stmt, FromImportStmt):
            # `FromImportStmt.names` is `[(name, alias|None), ...]`
            # (fire_compiler.py) -- NOT a flat list of bound-name
            # strings. Adding the raw `(name, alias)` TUPLE here (the
            # previous code) meant `_cpp_early_global_names` never
            # actually contained the real local binding name for ANY
            # `from X import Y` / `from X import Y as Z` at module
            # level -- a plain string membership check like `e.name in
            # gen._cpp_early_global_names` (every consumer of this set)
            # can never match a tuple element, so EVERY such import was
            # invisible to the coroutine-body module-name resolution
            # this set exists for (found via `from os import path as
            # os_helper`; `os_helper.unlink(...)` inside a generator
            # emitted literal, undeclared `os_helper` text instead of
            # resolving through the "known early-global -> stub" path).
            # Unpack each tuple to the real bound name (alias when
            # present, else the imported name itself), mirroring the
            # ImportStmt branch just above's identical `_ta if _ta else
            # ...` pattern.
            for _nm in getattr(_gm_stmt, 'names', []) or []:
                _in, _ia = _nm if isinstance(_nm, tuple) else (_nm, None)
                self._cpp_early_global_names.add(_ia if _ia else _in)
        elif isinstance(_gm_stmt, FunctionDef):
            self._cpp_early_global_names.add(_gm_stmt.name)
            self._cpp_module_fn_names.add(_gm_stmt.name)

    _gmi_scan_cpp_nested_imports(self, stmts)

    def _register_free_generator(s, cpp_text, base, value_ctype, param_ctypes):
        """Shared registration for one supported free-function generator
        (both eligibility passes below call this — the blocks were verbatim
        duplicates): records the api under the bare name, seeds THIS gen's
        func_param_types/_func_param_defaults for `<base>_start`, appends
        the coroutine translation unit, and — for cross-module discovery —
        files the same api dict into _generator_home_api keyed by the
        composite "<home-module qualifier>::<original name>" string, the
        whole-program view
        FromImportStmt sites consult to bind aliased imports of another
        module's compiled generator (_imported_generator_bindings). The
        qualifier half uses _func_qualifier tier 1 — the exact same
        computation _gen_cpp_generator_unit used to build `base` itself,
        so registry key and emitted symbol always agree."""
        self._supported_generators[s.name] = s
        self._generator_api[s.name] = {
            'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
            'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            # Value-carrying `return` support (asyncio/futures.py's
            # `__await__`): True when this unit stored its return value
            # into the promise slot before co_return, so a `yield from`
            # consumer reading `{base}_value` AFTER the sub-generator
            # reports done gets that return value.
            'has_return_value': self._cpp_last_has_return_value,
        }
        _gq = self._func_qualifier(s.name)
        if _gq:
            self._generator_home_api[_gq + '::' + s.name] = self._generator_api[s.name]
        self.func_param_types[f"{base}_start"] = param_ctypes
        _gen_dflts = getattr(s, 'param_defaults', None) or {}
        if _gen_dflts:
            # Indexed key lookup, NOT `[(pn, dv) for pn, dv in
            # _gen_dflts.items()]` — same self-hosted boxed-tuple-unpack
            # trap: a comprehension target unpack over `.items()`'s
            # (key, value) pairs boxes both slots to int64_t.
            _dflt_list = []
            for _dk in _gen_dflts:
                _dflt_list.append((_dk, _gen_dflts[_dk]))
            self._func_param_defaults[f"{base}_start"] = _dflt_list
            # Cross-module call sites register from this snapshot (their own
            # _func_param_defaults never saw the defining module's pass).
            # The home-registry value IS this api dict (same object), so
            # both views see the key.
            self._generator_api[s.name]['defaults'] = _dflt_list
        self._generator_cpp_units.append(cpp_text)
        _generator_fns.pop(id(s), None)

    # Seed container-element C types for TOP-LEVEL literal-container
    # globals BEFORE any generator unit compiles. Generator units run
    # ahead of the Phase 1.7 / module-globals-declaration passes (this
    # function's own pass ordering), so a coroutine body iterating a
    # module-level container global (`for flagname, flagvalue in
    # _flags:`) cannot consult `_global_var_types` yet — and until now
    # had NO source for the iterable's per-slot element types either,
    # forcing int64_t-default reads that print raw pointers where the
    # real element is a string. This scan records ONLY what is statically
    # decidable from the initializing literal itself (same `_quick_type`
    # + TypeLattice.join_all primitives every other element-type
    # inference here uses): per-slot ctypes when every element is a flat
    # equal-length tuple/list literal (the tuple-unpack shape), else the
    # joined whole-container element type. Additive-only: nothing reads
    # this map except the coroutine-body for-loop lowering's
    # module-global branches; later passes keep full authority over
    # `_global_var_types` itself.
    self._global_literal_slot_ctypes = {}
    for _s in stmts:
        _tgts = []
        if isinstance(_s, AssignStmt):
            _t = _s.target.name if isinstance(_s.target, IdentExpr) else _s.target
            if isinstance(_t, str):
                _tgts = [_t]
        elif isinstance(_s, MultiAssignStmt):
            _tgts = [(t.name if isinstance(t, IdentExpr) else t)
                     for t in _s.targets]
            _tgts = [t for t in _tgts if isinstance(t, str)]
        if not _tgts or not isinstance(_s.value, (ListExpr, TupleExpr, SetExpr)):
            continue
        _els = _s.value.elements
        if not _els:
            continue
        _outer = None
        _slots = None
        try:
            if all(isinstance(e, (ListExpr, TupleExpr)) and e.elements
                   for e in _els):
                # `_elens`, NOT `_lens`: this used to share a name with the
                # dict `_lens` in `gen_module_impl`'s device-kernel pass
                # (per-buffer launch lengths), two functions apart in this
                # same file. They are a `MojoSet *` and a `MojoDict *`, and
                # the compiled path froze the NAME as the set, so the dict
                # assignment raised "cannot coerce MojoSet * to MojoDict *
                # (incompatible container kinds)" — which took out
                # `module_gen.py`'s own compile, and with it (silently, see
                # `_compile_imported_module`'s rollback) the four GPU sibling
                # modules it had already inlined. Symptom: four undefined
                # `__mojo_*_toplevel` symbols at link, blaming four modules
                # for one module's bug. Distinct names is the whole fix; the
                # collision was silent precisely because nothing checks that
                # two locals of one name agree.
                _elens = {len(e.elements) for e in _els}
                if len(_elens) == 1:
                    _n = _elens.pop()
                    _slots = [gimple_ctypes.TypeLattice.join_all(
                        [self._quick_type(e.elements[j]) for e in _els])
                        for j in range(_n)]
                    _slots = [st for st in _slots
                              if st in ('int64_t', 'double', '_Bool', 'char *')]
                    if len(_slots) != _n:
                        _slots = None
            if _slots is None:
                _joined = gimple_ctypes.TypeLattice.join_all(
                    [self._quick_type(e) for e in _els])
                if _joined in ('int64_t', 'double', '_Bool', 'char *'):
                    _outer = _joined
        except Exception:
            _slots = None
            _outer = None
        if _slots is None and _outer is None:
            continue
        for _t in _tgts:
            self._global_literal_slot_ctypes[_t] = _slots if _slots is not None else _outer

    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) in _generator_fns
                and id(s) not in _async_fns):
            continue
        if id(s) in _struct_method_ids:
            continue                    # a METHOD: see _struct_method_ids
        if not _generator_quick_eligible(s):
            continue
        try:
            cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_generator_unit(s)
        except _UnsupportedGeneratorShape as e:
            # Latest-wins, matching the retry passes below: the reasons
            # dict is only ever read for generators STILL pending after
            # every retry, and each pending generator is re-attempted at
            # least once more, so its final entry always reflects the last
            # actual attempt.
            self._cpp_refusal_reasons[s.name] = str(e)
            _debug_note(f'generator {s.name!r} not eligible for C++ '
                        'coroutine path, falling back to honest refusal', e)
            continue
        _register_free_generator(s, cpp_text, base, value_ctype, param_ctypes)

    # Multi-pass retry loop for generators whose pass-1 attempt raised
    # _UnsupportedGeneratorShape only because a consumed/delegated-to
    # SIBLING generator wasn't registered yet ("defined LATER in this
    # module" — registration happens as each generator's unit succeeds, so
    # a consumer earlier in source order can only succeed on a later pass).
    # Runs to a FIXED POINT rather than a fixed small pass count: each
    # iteration re-attempts every still-pending generator in source order,
    # and any chain of forward references (a1 -> a2 -> ... -> aN) needs up
    # to N-1 retries to fully resolve — one per link, since a pass only
    # registers the tail a later pass unblocked. The old hard-coded
    # `range(3)` silently left chains deeper than 4 refusing (real repro:
    # a 6-generator chain left its 2 head generators refused; the module
    # then fell back to whole-module interpretation). Termination is
    # deterministic: each iteration either registers >= 1 generator
    # (shrinking _generator_fns) or breaks, so at most len(_generator_fns)
    # iterations run — mutual-recursion cycles (A consumes B consumes A)
    # make no progress and break out to the honest whole-module refusal,
    # unchanged.
    for _pass in range(max(len(_generator_fns), 1)):
        if not _generator_fns:
            break
        _registered_this_pass = 0
        for _gm_id, s in list(_generator_fns.items()):
            if _gm_id in _async_fns:
                continue
            if _gm_id in _struct_method_ids:
                continue                # a METHOD: see _struct_method_ids
            if not _generator_quick_eligible(s):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_generator_unit(s)
            except _UnsupportedGeneratorShape as e:
                # Latest-wins (not setdefault): an early pass's reason is
                # frequently stale by the final failure — e.g. pass 1 says
                # "does not consume a generator ... defined LATER", while
                # the retry that actually decided the outcome failed on a
                # DIFFERENT shape (argument arity, an unsupported body
                # expression). Reporting the FIRST message sent real
                # diagnoses down the wrong path (the consumption-ordering
                # bug docs all quote it). A generator that ultimately
                # SUCCEEDS keeps no refusal reason that matters — the
                # reasons dict is only read for names still pending below.
                self._cpp_refusal_reasons[s.name] = str(e)
                _debug_note(f'generator {s.name!r} not eligible for C++ '
                            f'coroutine path (retry pass {_pass+2}), falling back', e)
                continue
            _register_free_generator(s, cpp_text, base, value_ctype, param_ctypes)
            _registered_this_pass += 1
        if not _registered_this_pass:
            break

    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) in _async_fns
                and id(s) in _generator_fns):
            continue
        if not _async_gen_quick_eligible(s, frozenset(self._async_api.keys())):
            continue
        try:
            cpp_text, value_ctype, base, param_ctypes = \
                self._gen_cpp_async_generator_unit(s)
        except _UnsupportedGeneratorShape as e:
            self._cpp_refusal_reasons.setdefault(s.name, str(e))
            _debug_note(f'async generator {s.name!r} not eligible for '
                        'C++ coroutine path, falling back to honest '
                        'refusal', e)
            continue
        self._supported_async_gen[s.name] = s
        self._async_gen_api[s.name] = {
            'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
            'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
        }
        self.func_param_types[f"{base}_start"] = param_ctypes
        self._generator_cpp_units.append(cpp_text)
        _async_fns.pop(id(s), None)
        _generator_fns.pop(id(s), None)

    if _async_fns:
        for _gm_id, s in list(_async_fns.items()):
            if _gm_id not in _generator_fns:
                continue
            if not _async_gen_quick_eligible(s, frozenset(self._async_api.keys())):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = \
                    self._gen_cpp_async_generator_unit(s)
            except _UnsupportedGeneratorShape as e:
                self._cpp_refusal_reasons.setdefault(s.name, str(e))
                _debug_note(f'async generator {s.name!r} not eligible '
                            '(pass 2)', e)
                continue
            self._supported_async_gen[s.name] = s
            self._async_gen_api[s.name] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            self._generator_cpp_units.append(cpp_text)
            _async_fns.pop(_gm_id, None)
            _generator_fns.pop(_gm_id, None)

    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) in _async_fns
                and id(s) not in _generator_fns):
            continue
        s.body = self._inline_single_use_task_composition(s.body)
        # Hoist any `await` still nested inside a call's argument list
        # into statement position. The A3 stack-switch backend normalizes
        # the same shape from its own shared eligibility chokepoint
        # (`gimple_gen_coro._eligible_async_common`, which calls
        # `hoist_awaits_from_call_args` on the same AST node in place);
        # this call is the C++20-coroutine backend's own explicit one, so
        # this pass does not depend on the A3 pass having run first.
        # Idempotent, so a double application is a no-op.
        gimple_gen_coro.hoist_awaits_from_call_args(s)
        self._normalize_await_kwargs(s.body)
        if not _async_quick_eligible(s, frozenset(self._async_api.keys())):
            continue
        try:
            cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_async_unit(s)
        except _UnsupportedGeneratorShape as e:
            self._cpp_refusal_reasons.setdefault(s.name, str(e))
            _debug_note(f'async function {s.name!r} not eligible for '
                        'C++ coroutine path, falling back to honest '
                        'refusal', e)
            continue
        self._supported_async[s.name] = s
        self._async_api[s.name] = {
            'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
        }
        self.func_param_types[f"{base}_start"] = param_ctypes
        self._generator_cpp_units.append(cpp_text)
        _async_fns.pop(id(s), None)
    _nested_in_fn_ids: set = set()
    for _st in stmts:
        if not (isinstance(_st, FunctionDef)
                and id(_st) not in _async_fns
                and id(_st) not in _generator_fns):
            continue
        for _nf in _walk_ast(_st):
            if isinstance(_nf, FunctionDef):
                _nested_in_fn_ids.add(id(_nf))
    for _st in stmts:
        if not isinstance(_st, StructDef):
            continue
        for _sm in _st.methods:
            if not isinstance(_sm, FunctionDef):
                continue
            for _nf in _walk_ast(_sm.body):
                if isinstance(_nf, FunctionDef):
                    _nested_in_fn_ids.add(id(_nf))
    if _async_fns:
        for _gm_id, s in list(_async_fns.items()):
            if _gm_id in _generator_fns:
                continue  # async generator — separate path
            if _gm_id in _nested_in_fn_ids:
                continue  # nested-in-function — Step I/closure pass's job
            s.body = self._inline_single_use_task_composition(s.body)
            gimple_gen_coro.hoist_awaits_from_call_args(s)
            self._normalize_await_kwargs(s.body)
            if not _async_quick_eligible(s, frozenset(self._async_api.keys())):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_async_unit(s)
            except _UnsupportedGeneratorShape as e:
                self._cpp_refusal_reasons.setdefault(s.name, str(e))
                _debug_note(f'async function {s.name!r} not eligible '
                            '(pass 2)', e)
                continue
            self._supported_async[s.name] = s
            self._async_api[s.name] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            self._generator_cpp_units.append(cpp_text)
            _async_fns.pop(_gm_id, None)

    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) not in _async_fns
                and id(s) not in _generator_fns):
            continue
        self._compile_nested_async_functions(s, _async_fns)

    # A compiled generator METHOD gets one C++ coroutine unit PER RECEIVER
    # CLASS, not per defining FunctionDef.
    #
    # `_merge_struct_inheritance` (gimple_codegen.py) gives every StructDef's
    # `.methods` the fully-merged view, so a subclass's list holds the very
    # SAME FunctionDef object its base's does. The unit's `cls` is an opaque
    # int64_t placeholder that is passed positionally and NEVER dereferenced —
    # every supported `cls.<...>` shape resolves purely BY NAME against the
    # struct the unit was emitted for (`_gen_cpp_generator_unit`'s
    # `_cls_refs_supported`) — so a subclass needs its OWN unit. Sharing the
    # base's would read `_classattr_Base__tag` where CPython reads Child's,
    # which is why this is a per-class unit and not just a lookup.
    #
    # Keying the work on `id(m)` — as this loop's predecessor did, popping
    # `_generator_fns` as it went — therefore registered only the DEFINING
    # class: `Child`'s turn never came, because its `id(m)` had already been
    # popped. `Child.gen(4)` then fell through to the ordinary
    # `Child_gen(...)` lowering, a struct method gen_module's Phase 2a
    # deliberately never emits for a generator method, so its `yield`s were
    # dropped on the floor and the consuming `for` got a void value and
    # answered `mojo_unsupported_iter` at run time. Registering per
    # (struct, method) closes both halves: `_supported_generator_methods` also
    # suppresses that stub (both GIMPLE emission sites skip on membership —
    # module_gen.py's Phase 2a), and the call site
    # (emit_methods.py's `_lower_method_call`, whose class-level-receiver arm
    # looks up `(func.obj.name, method)`) finds its unit.
    #
    # This also REPLACES two byte-identical loops that ran back to back with
    # nothing between them — the second's only difference was a "(pass 2)"
    # debug string, and with the work keyed on the pair rather than on
    # `id(m)` a second identical pass could only ever find nothing new.
    _gen_method_keys_done: set = set()
    _gen_method_ids_done: set = set()
    for _sd in stmts:
        if not isinstance(_sd, StructDef):
            continue
        for m in _sd.methods:
            if not (isinstance(m, FunctionDef) and id(m) in _generator_fns
                    and id(m) not in _async_fns):
                continue
            key = (_sd.name, m.name)
            if key in _gen_method_keys_done:
                continue
            if not _generator_quick_eligible(m):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = \
                    self._gen_cpp_generator_unit(m, struct_name=_sd.name)
            except _UnsupportedGeneratorShape as e:
                self._cpp_refusal_reasons.setdefault(m.name, str(e))
                _debug_note(f'generator method {_sd.name}.{m.name!r} not '
                            'eligible for C++ coroutine path, falling '
                            'back to honest refusal', e)
                continue
            _gen_method_keys_done.add(key)
            _gen_method_ids_done.add(id(m))
            self._supported_generator_methods[key] = m
            self._generator_method_api[key] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                # Which SOURCE parameter, if any, is the receiver slot a
                # caller must fill -- see mojo/middle/coro.py's identical
                # key for why the registered `params` (bare ctype strings)
                # cannot carry it. `m.params[0][0]` is the only place the
                # name survives, so it is read here, at registration.
                'receiver': (_cpp_method_receiver_name(m)),
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            _gen_dflts = getattr(m, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f"{base}_start"] = [
                    (pn, dv) for pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
    # The ids come out only here, after EVERY struct has had its turn. Popping
    # inside the loop is precisely what stopped a subclass from being reached.
    for _gm_done in _gen_method_ids_done:
        _generator_fns.pop(_gm_done, None)

    if _gsrc:
        for _od in stmts:
            if not isinstance(_od, FunctionDef):
                continue
            _outer_scope2 = {}
            for _pname, _ptype in (_od.params or []):
                _sh_ct2 = (None if _selfhost_fn_reassigns_method(_od)
                           else _ggf_dup._selfhost_gen_self_param_ctype(self, _pname, _ptype, _od))
                _outer_scope2[_pname] = _sh_ct2 or self._resolve_type(_ptype)
            for _inner in _od.body:
                if not (isinstance(_inner, FunctionDef) and id(_inner) in _async_fns):
                    continue
                _cp_ctypes = {}
                if _inner.comptime_params:
                    _bp_types2 = _bracket_param_type_annotations(_gsrc, _inner.name)
                    for _cp in _inner.comptime_params:
                        _ann = _bp_types2.get(_cp, '')
                        _cp_ctypes[_cp] = ('int64_t' if _ann.startswith('def')
                                           else self._resolve_type(_ann))
                if not _async_quick_eligible(_inner, frozenset(self._async_api.keys())):
                    continue
                _captures2 = self._compute_nested_closure_captures(_inner, _outer_scope2)
                _extra2 = [(cp, _cp_ctypes.get(cp, 'int64_t')) for cp in _inner.comptime_params] + _captures2
                _base_override2 = f"{_od.name}_{_inner.name}"
                try:
                    cpp_text, value_ctype, base, param_ctypes = \
                        self._gen_cpp_async_unit(_inner, extra_captures=_extra2,
                                                 base_name_override=_base_override2,
                                                 enclosing_scope=_od.name)
                except _UnsupportedGeneratorShape as e:
                    self._cpp_refusal_reasons.setdefault(_inner.name, str(e))
                    _debug_note(f'nested async function {_od.name}.'
                                f'{_inner.name!r} not eligible for C++ '
                                'coroutine path, falling back to honest '
                                'refusal', e)
                    continue
                key = (_od.name, _inner.name)
                self._supported_async_closures[key] = _inner
                self._async_closure_api[key] = {
                    'base': base, 'value_ctype': value_ctype,
                    'params': param_ctypes, 'captures': _extra2,
                    'comptime_params': list(_inner.comptime_params),
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                self._generator_cpp_units.append(cpp_text)
                _async_fns.pop(id(_inner), None)

    for _sd in stmts:
        if not isinstance(_sd, StructDef):
            continue
        _moids_ac = self._struct_method_overload_ids(_sd)
        for _zmi in range(len(_sd.methods)):
            _m = _as_funcdef_node(_sd.methods[_zmi]); _oid = _as_str(_moids_ac[_zmi]) if _zmi < len(_moids_ac) else ""
            _outer_scope = {_sd.name.lower(): f"{_sd.name} *",
                             'self': f"{_sd.name} *"}
            for _pname, _ptype in _m.params:
                if _pname != 'self':
                    _outer_scope[_pname] = self._resolve_type(_ptype)
            for _cp_name in self._method_threaded_comptime_params.get(
                    (_sd.name, _m.name), {}).get(_oid, []):
                _outer_scope[_cp_name] = 'int64_t'
            for _inner in _m.body:
                if not (isinstance(_inner, FunctionDef) and id(_inner) in _async_fns):
                    continue
                if not _async_quick_eligible(_inner, frozenset(self._async_api.keys())):
                    continue
                _captures = self._compute_nested_closure_captures(_inner, _outer_scope)
                _base_override = f"{_sd.name}_{_m.name}{_oid}_{_inner.name}"
                try:
                    cpp_text, value_ctype, base, param_ctypes = \
                        self._gen_cpp_async_unit(_inner, extra_captures=_captures,
                                                 base_name_override=_base_override)
                except _UnsupportedGeneratorShape as e:
                    self._cpp_refusal_reasons.setdefault(_inner.name, str(e))
                    _debug_note(f'nested async closure {_sd.name}.{_m.name}.'
                                f'{_inner.name!r} not eligible for C++ '
                                'coroutine path, falling back to honest '
                                'refusal', e)
                    continue
                outer_ctx = f"{_sd.name}_{_m.name}{_oid}"
                key = (outer_ctx, _inner.name)
                self._supported_async_closures[key] = _inner
                self._async_closure_api[key] = {
                    'base': base, 'value_ctype': value_ctype,
                    'params': param_ctypes, 'captures': _captures,
                }
                self.func_param_types[f"{base}_start"] = param_ctypes
                self._generator_cpp_units.append(cpp_text)
                _async_fns.pop(id(_inner), None)

    _gen_only_names: list = []
    for _gm_id, _gm_fn in _generator_fns.items():
        if _gm_id not in _async_fns:
            _gen_only_names.append(_gm_fn.name)
    _async_only_names: list = []
    for _gm_id, _gm_fn in _async_fns.items():
        if _gm_id not in _generator_fns:
            _async_only_names.append(_gm_fn.name)
    _async_gen_names: list = []
    for _gm_id, _gm_fn in _generator_fns.items():
        if _gm_id in _async_fns:
            _async_gen_names.append(_gm_fn.name)
    _gen_only = sorted(_gen_only_names)
    _async_only = sorted(_async_only_names)
    _async_gen = sorted(_async_gen_names)
    if _gen_only or _async_only or _async_gen:
        _categories = []
        if _gen_only:
            _categories.append(
                f"{', '.join(_gen_only)} (generator function(s), contain "
                "a `yield`/`yield from`)")
        if _async_only:
            _categories.append(
                f"{', '.join(_async_only)} (async function(s), declared "
                "`async def`)")
        if _async_gen:
            _categories.append(
                f"{', '.join(_async_gen)} (async generator function(s), "
                "declared `async def` AND contain a `yield`/`yield from`)")
        if self.relaxed_imports:
            _debug_note('relaxed_imports: skipping unsupported functions',
                        '; '.join(_categories))
            for _fn_name in _gen_only + _async_only + _async_gen:
                _csym = self._func_csym(_fn_name)
                _g = _stub_guard_name(_csym)
                # A WEAK DEFINITION, not a bare declaration: the skipped
                # generator/async function has no ordinary C definition
                # anywhere in this compile, so any plain call site that
                # reaches it (`find_name_in_mro` calling the skipped
                # `iter_name_in_mro` generator) would satisfy -fgimple's
                # name check against a decl-only stub and then fail at
                # LINK ("symbol(s) not found"). Mirrors
                # _lower_named_call's own identical weak-stub reasoning
                # for never-defined names: an actual call prints an
                # honest "unavailable in compiled mode" diagnostic and
                # returns 0 instead of breaking the whole build.
                _stub = (f'#ifndef {_g}\n#define {_g}\n'
                         f'__attribute__((weak)) int64_t {_csym} (...) '
                         f'{{ mojo_print ((char *)"{_fn_name}: unavailable in compiled mode '
                         f'(unsupported generator/async function skipped)"); '
                         f'return (int64_t)0; }}\n#endif')
                if _stub not in self._elaborated_externs:
                    self._elaborated_externs.append(_stub)
                self._unsupported_generator_names.add(_fn_name)
        else:
            _reason_bits = []
            for _fn_name in _gen_only + _async_only + _async_gen:
                _rr = self._cpp_refusal_reasons.get(_fn_name)
                if _rr:
                    _reason_bits.append(f"{_fn_name}: {_rr}")
            _reason_suffix = ""
            if _reason_bits:
                _reason_suffix = (" Unsupported shape(s): "
                                  + "; ".join(_reason_bits) + ".")
            raise RuntimeError(
                "cannot compile module: function(s) "
                + "; ".join(_categories) +
                " — this codegen compiles every function into a single "
                "straight-line C function and has no suspend/resume "
                "state-machine transform for generators, nor an event loop "
                "/ suspend-resume codegen for async functions, yet, so "
                "these cannot be represented as compiled C without "
                "emitting silently wrong or broken code; falling back to "
                "interpreting this module from source instead"
                + _reason_suffix)

    for s in all_functions:
        if isinstance(s, FunctionDef) and s.return_type is None:
            # `_as_funcdef_node` — see the identical fix + comment at the
            # other `for s in all_functions:` return-type-inference pass
            # above: `all_functions` is a heterogeneous statement list, so
            # `s`'s self-hosted element type is opaque int64_t regardless
            # of the isinstance filter.
            s = _as_funcdef_node(s)
            _saved_vt_23e = self.var_types
            _scratch_mark_23e: int = self._scan_scratch_top
            self.var_types = self._scratch_dict_copy(_saved_vt_23e)
            # Index, don't unpack — see the identical fix + comment at the
            # earlier return-type-inference pass above.
            _p23e_params = s.params
            for _p23ei in range(len(_p23e_params)):
                pname = _as_str(_p23e_params[_p23ei][0])
                ptype = _p23e_params[_p23ei][1]
                bare = pname.lstrip('*')
                if pname.startswith('*'):
                    self.var_types[bare] = 'MojoList *'
                elif ptype is None:
                    self.var_types[bare] = (self._inferred_param_types.get(s.name, {}).get(bare)
                                             or self._resolve_type(ptype))
                else:
                    self.var_types[bare] = self._resolve_type(ptype)
            inferred = self._infer_return_type(s.body)
            if s.name == 'main' and inferred == 'void':
                inferred = 'int64_t'
            self.var_types = _saved_vt_23e
            self._scan_scratch_top = _scratch_mark_23e
            self.func_return_types[s.name] = inferred
            _ggf_dup._record_home_def_return_type(self, s, s.name, inferred)

    for s in all_functions:
        if isinstance(s, FunctionDef):
            # See the identical fix + comment at this file's other
            # `for s in all_functions: ... self._infer_local_var_types(s)`
            # site above.
            self._inferred_var_types[_as_str(s.name)] = self._infer_local_var_types(_as_funcdef_node(s))
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{_as_str(s.name)}_{_as_str(m.name)}"
                self._inferred_var_types[key] = self._infer_local_var_types(m)
                # Same key, for the sibling table the ASSIGNMENT SITE reads
                # mid-body under `current_func_name` — see
                # `ginf.alias_multi_kind_locals`, imported here rather than at
                # this module's top level so that `import
                # mojo.backend_gimple.module_gen` can be a process's FIRST
                # `mojo.*` import (see the import block's comment).
                import mojo.middle.infra_infer as ginf
                ginf.alias_multi_kind_locals(self, key, m)
    _reconcile_param_container_kinds()

    self._param_generator_api: dict[str, dict[str, str]] = {}
    self._fn_returns_generator: dict[str, str] = {}

    def _walk_gen_prov(body, target_name, known_params):
        """Return the single generator function name assigned to
        `target_name` anywhere in `body` (recursively, skipping nested
        defs), or None (never assigned a generator, or a conflict — two
        different generator functions assigned to the same variable, or a
        pass-through of a param whose own provenance is unresolved).
        `known_params` maps a caller param already proven to hold a
        generator to its function name, for the chained shape
        `def outer(g): consume(g)`."""
        # 1-element list, not a `nonlocal` scalar: a container captured by
        # reference propagates the nested `_scan`'s writes cleanly in the
        # self-hosted backend, where a `nonlocal` scalar mut-capture does
        # not (it silently kept `_walk_gen_prov` returning None always).
        _genprov_found = [None]

        def _scan(stmts):
            for st in stmts:
                val = None
                if isinstance(st, AssignStmt) and isinstance(st.target, IdentExpr):
                    if st.target.name == target_name:
                        val = st.value
                elif isinstance(st, VarDecl) and st.name == target_name:
                    val = st.value
                if val is not None:
                    prov = None
                    if isinstance(val, CallExpr) and isinstance(val.func, IdentExpr):
                        if val.func.name in self._generator_api:
                            prov = val.func.name
                        else:
                            prov = self._fn_returns_generator.get(val.func.name)
                    elif isinstance(val, IdentExpr):
                        prov = known_params.get(val.name)
                    if prov is not None:
                        if _genprov_found[0] is None:
                            _genprov_found[0] = prov
                        elif _genprov_found[0] != prov:
                            _genprov_found[0] = '<conflict>'
                    continue
                if isinstance(st, FunctionDef):
                    continue
                for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                    sub = getattr(st, attr, None)
                    if isinstance(sub, list):
                        _scan(sub)
                for _eb_cond, _eb_body in (getattr(st, 'elifs', None) or []):
                    _scan(_eb_body)
                for _h in (getattr(st, 'handlers', None) or []):
                    hb = getattr(_h, 'body', None)
                    if isinstance(hb, list):
                        _scan(hb)

        _scan(body)
        return _genprov_found[0]

    def _arg_generator_prov(caller_name, arg):
        """The generator function name behind call-site argument `arg`
        (typed `MojoGenerator *` in the caller), or None."""
        if isinstance(arg, IdentExpr):
            t = (self._inferred_var_types.get(caller_name, {}).get(arg.name)
                 or self._inferred_param_types.get(caller_name, {}).get(arg.name))
            if t != 'MojoGenerator *':
                return None
            fn = _fn_by_name.get(caller_name)
            if fn is not None:
                p = _walk_gen_prov(fn.body, arg.name,
                                   self._param_generator_api.get(caller_name, {}))
                if p is not None:
                    return p
            return self._param_generator_api.get(caller_name, {}).get(arg.name)
        if isinstance(arg, CallExpr) and isinstance(arg.func, IdentExpr):
            if arg.func.name in self._generator_api:
                return arg.func.name
            return self._fn_returns_generator.get(arg.func.name)
        return None

    for _rf in all_functions:
        if not isinstance(_rf, FunctionDef):
            continue
        acc_rt = []
        _gmi_collect_return_values(acc_rt, _rf.body)
        rt_prov = None
        for _rv in acc_rt:
            if (isinstance(_rv, CallExpr) and isinstance(_rv.func, IdentExpr)
                    and _rv.func.name in self._generator_api):
                if rt_prov is None:
                    rt_prov = _rv.func.name
                elif rt_prov != _rv.func.name:
                    rt_prov = '<conflict>'
            else:
                rt_prov = '<conflict>'
        if rt_prov not in (None, '<conflict>'):
            self._fn_returns_generator[_rf.name] = rt_prov

    _param_gen_obs: dict[str, dict[str, dict]] = {}  # callee -> {pname -> {fname: count}}
    for _round in range(4):
        _changed = False
        for _cl_name, _cl_body in _caller_bodies:
            _calls = []
            self._calls_in_stmts(_cl_body, _calls)
            for _call in _calls:
                if not isinstance(_call.func, IdentExpr):
                    continue
                _callee = _call.func.name
                _pnames = _free_params.get(_callee)
                if not _pnames:
                    continue
                for _i, _a in enumerate(_call.args):
                    if _i >= len(_pnames):
                        break
                    prov = _arg_generator_prov(_cl_name, _a)
                    if prov is None:
                        continue
                    _pobs = _param_gen_obs.setdefault(_callee, {})
                    _fmap = _pobs.setdefault(_pnames[_i], {})
                    _fmap[prov] = _fmap.get(prov, 0) + 1
        for _callee, _pmap in _param_gen_obs.items():
            _fn = _fn_by_name.get(_callee)
            if _fn is None:
                continue
            for _pname, _fmap in _pmap.items():
                _keys = []
                for _k in _fmap:
                    _keys.append(_k)
                _annot = None
                for _p, _pt in (_fn.params or []):
                    if _p == _pname:
                        _annot = _pt
                        break
                if _annot is not None:
                    continue  # respect an explicit annotation
                _cur = self._inferred_param_types.get(_callee, {}).get(_pname)
                if _cur not in (None, 'int', 'int64_t', 'MojoList *'):
                    continue  # body evidence already picked a real type
                self._inferred_param_types.setdefault(_callee, {})[_pname] = 'MojoGenerator *'
                if len(_keys) == 1 and _keys[0] != '<conflict>':
                    self._param_generator_api.setdefault(_callee, {})[_pname] = _keys[0]
                _changed = True
        if not _changed:
            break

    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef):
            if gimple_ctypes._params_have_vararg(s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = _free_func_param_ctypes(self, s)

    # `not _is_selfhost_file`: SKIP dispatch-table solving entirely when
    # compiling this compiler's own `.py` sources. `DispatchTable`'s own
    # fields (`dispatch_type`/`struct_fields`) do not carry their types
    # across the self-host boundary (see the validation just below), so the
    # self-hosted binary's `emit_typedef()` returns malformed text, the
    # validation drops EVERY planned table, and it falls back to dynamic
    # dispatch. The python3 reference path has no such erasure, so it KEEPS
    # the tables and emits `parser_struct_dispatch_t` + devirtualised call
    # sites the native side never emits — a direct stage1-vs-stage2
    # divergence on every self-host file (fire_compiler/fire/module_loader/
    # myinterpreter `.ci`). Skipping the solve for self-host files makes the
    # decision identical on both sides (dynamic dispatch, always correct).
    if self.emit_struct_defs and not _is_selfhost_file:  # Only main module does dispatch solving
        self._dispatch_solver = DispatchSolver(
            self.struct_field_types, self.func_return_types,
            allow_assume_all_methods=_is_selfhost_file,
            generator_method_api=self._generator_method_api)
        all_stmts_for_dispatch = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        self._dispatch_solver.analyze(all_stmts_for_dispatch)
        self._dispatch_tables = self._dispatch_solver.get_dispatch_tables()
        # Self-hosted-codegen safety: DispatchTable / DispatchSolver live in
        # gimple_solvers.py, and when the compiler self-compiles, those
        # classes' field types don't propagate here — `dispatch_type` /
        # `struct_fields` erase, so `emit_typedef()` returns a few bytes of
        # raw heap garbage instead of a `typedef struct {...}` (invalid C
        # in `MOJO_NO_SHIM=1 --dump myinterpreter.py`, ~4 corrupt lines
        # before `_alloc_BoundMethod`). If ANY planned table can't emit a
        # well-formed typedef, drop the whole dispatch-table optimisation
        # for this module and fall back to dynamic dispatch — always
        # correct, just not devirtualised.
        if self._dispatch_tables:
            _dt_ok = True
            for _dt_chk in self._dispatch_tables.values():
                _td = _dt_chk.emit_typedef()
                if not (isinstance(_td, str) and (_td.startswith('typedef') or _td.startswith('/*'))):
                    _dt_ok = False
                    break
            if not _dt_ok:
                self._dispatch_tables = {}
                self._dispatch_solver = None
        # Dispatch-table callee qualification: each planned row's symbol was
        # registered BARE (`f"{struct}_{method}"`, see DispatchSolver's
        # struct_methods population), but Phase 2a emits a non-root module's
        # methods under `{home_module}_{Struct}_{method}` via
        # _struct_method_csym — a table initializer naming the bare spelling
        # references an undeclared symbol (the 11 `Repr_repr*` "undeclared
        # here" GCC errors reprlib.Repr's prefix-shaped
        # `getattr(self, 'repr_' + typename)` pattern produced inside the
        # whole-program Lib/socket.py build, and generally this hard-bug
        # doc's residual "option 3" gap). Re-resolve every row through that
        # same composer now: root-local and self-host structs qualify to ''
        # and keep the bare spelling byte-identical, so only genuinely
        # imported structs' rows change.
        if self._dispatch_tables:
            _ds = self._dispatch_solver
            for _dt in self._dispatch_tables.values():
                _rows = []
                for _mn, _sig, _full in _dt.methods:
                    _home = _ds.callee_home.get(_full)
                    _meth = _ds.callee_method.get(_full)
                    if _home and _meth:
                        _full = self._struct_method_csym(_home, _meth)
                    _rows.append((_mn, _sig, _full))
                _dt.methods = _rows

    # Shared closure discovery (one copy for gimple + formal + future archs).
    # The selfhost param-ctype hook is the module-level, NON-capturing
    # `_selfhost_gen_self_param_ctype(gen, pname, ptype, node)` itself —
    # assigned directly, NOT via a nested `def` wrapper. A nested (capturing)
    # wrapper is stored as a closure value (a DATA pointer); calling it
    # through the dynamically-typed `getattr(ctx, ...)` result lowered to
    # `mojo_fnptr_call_3`, which jumped to that data pointer and SIGBUS'd
    # (repro: std/atomic/atomic.mojo). The module-level function is a raw
    # code pointer, and discover_closures passes `ctx` explicitly.
    self.selfhost_param_ctype = _ggf_dup._selfhost_gen_self_param_ctype
    try:
        discover_closures(self, stmts)
    finally:
        try:
            del self.selfhost_param_ctype
        except AttributeError:
            pass

    # `self._multi_kind_return_funcs` names the functions whose return slot
    # is the box because they hand back a container whose kind a caller cannot
    # know statically. Recorded during lowering by
    # `emit_stmts._gen_stmt_ReturnStmt` — which is right about the ACTUAL
    # lowered value kinds, and is the only place the local-shaped verdict can
    # be read — but a recording made while lowering function B is invisible
    # to a caller A emitted BEFORE B, and A's `_lower_named_call` then
    # applied the `int64_t`-returning branch's default of "`_actual_types`
    # says `MojoList *`": another container's memory, read out of bounds,
    # printing `[0]` where CPython prints `{'a': 1}`. Silent, exit 0, and
    # dependent on which of two functions is spelled first — which is why
    # this is a whole-program PRE-PASS rather than a comment on the lowering
    # recording, which is kept.
    #
    # HERE and not beside `_mk_round` above, because `self._all_closures` is
    # empty until `discover_closures` has run, and a closure whose return is
    # a box is one of the three shapes `_infer_multi_kind_return` tests: put
    # it earlier and the closure arm walked nothing, which is measured, and
    # the caller still printed the box's own decimal address.
    #
    # A fixpoint for the same reason `_mk_round` above is one: the third shape
    # (`def outer(k): return inner(k)`) makes a function's answer depend on
    # its callee's, so a chain of forwarders is only settled once its last
    # real producer is known. Bounded at four rounds for the same reason:
    # `self._multi_kind_return_funcs` only ever GROWS, so the bound is a
    # depth limit rather than a convergence guess.
    def _mkrf_round(callee_set):
        _mkrf_cache: dict = {}
        # Each KNOWN function's single container return kind, filled as this
        # round walks. A function that returns containers of more than one
        # kind is recorded in `self._multi_kind_return_funcs` instead and
        # deliberately gets NO entry here: "more than one" and "one" must
        # stay distinguishable, because that is the whole difference between
        # a caller's single-kind answer and the box.
        _cg: dict = {}
        for _nm in _mkrf_callee_kinds:
            _cg[_nm] = _mkrf_callee_kinds[_nm]

        def _mkrf(name, body, params=None, sibling_lifted=None):
            # Memo key includes the sibling map's ID: the answer depends on
            # it, and two functions can share a body node identity while
            # their enclosing scopes give different maps.
            _k = (id(body), id(sibling_lifted))
            _kinds = _mkrf_cache.get(_k)
            if _kinds is None:
                _kinds = _mkrf_cache[_k] = _infer_multi_kind_return(
                    self, body, params, callee_set, _cg, sibling_lifted)
            if len(_kinds) > 1:
                self._multi_kind_return_funcs[name] = True
            elif len(_kinds) == 1:
                _cg[name] = _kinds[0]
            return _kinds

        # Every closure's BARE nested-def name paired with the `Outer_inner`
        # name it is filed under, passed to EVERY function in this round. Two
        # call shapes need it and neither can see the other spelling: a
        # closure calling a sibling (`return f()` inside `outer`, both bare),
        # and an enclosing free function calling its own closure
        # (`return consume(flag)` inside `outer`). Both spell the callee bare
        # in the AST while the answer is filed under the lifted name, so
        # without the pair neither matched and the caller printed the box's
        # own decimal address.
        #
        # Deliberately ONE map for all outers rather than one per enclosing
        # scope: a bare name shared by two different outers is already a
        # bare-name collision that `_func_csym` documents as outside this
        # mechanism's reach, and resolving it here could only over-approximate
        # -- which is safe in this direction because `_repr_boxed_container`
        # falls back to `mojo_str_from_int` for a value that turns out not to
        # be a container, so a false positive costs a boxed read and a false
        # negative costs a wrong answer.
        #
        # Index by outer name and NOT unpack through a nested `.items()`, for
        # the reason the identical walk at the closure forward-declaration
        # site gives: the SECOND unpack target boxes on the self-hosted path
        # and its attributes then read off a mis-typed handle.
        _mkrf_bare: dict = {}
        for _outer_name in self._all_closures:
            _inner_map = self._all_closures[_outer_name]
            for _bare in _inner_map:
                _mkrf_bare[_bare] = _inner_map[_bare].lifted_name
        for s in all_functions:
            if not _is_foreign_main(s) and isinstance(s, FunctionDef):
                _mkrf(s.name, s.body, s.params, _mkrf_bare)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                _sk = _as_structdef_node(s)
                for _m in _sk.methods:
                    _mkrf(f"{_sk.name}_{_m.name}", _m.body, _m.params,
                          _mkrf_bare)
        # Lifted CLOSURES under the same `Outer_inner` spelling the lowering
        # records them and the call sites read (`_lower_closure_call`'s
        # `lifted`, and `emit_stmts`' `gen.current_func_name`) -- a different
        # spelling from the free-function `s.name` above, which is why this is
        # its own arm and not the same call.
        for _outer_name in self._all_closures:
            _inner_map = self._all_closures[_outer_name]
            for _ci in _inner_map.values():
                _mkrf(_ci.lifted_name, _ci.inner_def.body,
                      _ci.inner_def.params, _mkrf_bare)
        _mkrf_callee_kinds.clear()
        for _nm in _cg:
            _mkrf_callee_kinds[_nm] = _cg[_nm]

    # Round 1 reads an empty set and an empty kind map -- it is the round that
    # finds the producers; rounds 2+ read what the earlier rounds filed.
    _mkrf_callee_kinds: dict = {}
    _mkrf_round(set())
    for _mkrf_iter in range(3):
        _mkrf_before = len(self._multi_kind_return_funcs)
        _mkrf_round(set(self._multi_kind_return_funcs))
        if len(self._multi_kind_return_funcs) == _mkrf_before:
            break

    # The RAW loop var is `_p3b_raw` and the node is bound to `_p3b_s` on the
    # first line below, because `_record_home_def_return_type`'s identity test
    # is the one thing here that must see the ORIGINAL node.
    for _p3b_raw in all_functions:
        if isinstance(_p3b_raw, FunctionDef) and _p3b_raw.return_type is None:
            # `_as_funcdef_node` — see the identical fix + comment at the
            # earlier `for s in all_functions:` return-type-inference
            # passes above: `all_functions` is a heterogeneous statement
            # list, so its element type is opaque int64_t regardless of
            # the isinstance filter. The RAW loop var is kept in `_p3b_raw`
            # for `_record_home_def_return_type`'s identity test below,
            # which is the one thing here that must see the original node.
            _p3b_s = _as_funcdef_node(_p3b_raw)
            _saved_vt_3b = self.var_types
            _saved_fcn_3b = self.current_func_name
            self.current_func_name = _p3b_s.name
            _scratch_mark_3b: int = self._scan_scratch_top
            self.var_types = self._scratch_dict_copy(_saved_vt_3b)
            # Index, don't unpack — see the identical fix + comment at the
            # earlier return-type-inference passes above.
            _p3b_params = _p3b_s.params
            for _p3bi in range(len(_p3b_params)):
                pname = _as_str(_p3b_params[_p3bi][0])
                ptype = _p3b_params[_p3bi][1]
                bare = pname.lstrip('*')
                if pname.startswith('*'):
                    self.var_types[bare] = 'MojoList *'
                elif ptype is None:
                    self.var_types[bare] = (self._inferred_param_types.get(_p3b_s.name, {}).get(bare)
                                            or self._resolve_type(ptype))
                else:
                    self.var_types[bare] = self._resolve_type(ptype)
            for _cln, _clt in self._closure_value_locals(_p3b_s.body).items():
                if _cln not in self.var_types:
                    self.var_types[_cln] = _clt
            inferred = self._infer_return_type(_p3b_s.body)
            if _p3b_s.name == 'main' and inferred == 'void':
                inferred = 'int64_t'
            self.var_types = _saved_vt_3b
            self._scan_scratch_top = _scratch_mark_3b
            self.current_func_name = _saved_fcn_3b
            self.func_return_types[_p3b_s.name] = inferred
            _ggf_dup._record_home_def_return_type(
                self, _p3b_raw, _p3b_s.name, inferred)

    def _flatten_resolved_conditionals(_root_list):
        _out = []
        _stack = [(_root_list, 0)]
        while _stack:
            _frame_body, _frame_idx = _stack[-1]
            if _frame_idx >= len(_frame_body):
                _stack.pop()
                continue
            _frame_stmt = _frame_body[_frame_idx]
            _stack[-1] = (_frame_body, _frame_idx + 1)
            if isinstance(_frame_stmt, IfStmt):
                _resolved = False
                _resolved_body = []
                _cond_val = self._eval_const_bool(_frame_stmt.condition)
                if _cond_val is True:
                    _resolved = True
                    _resolved_body = _frame_stmt.then_body or []
                elif _cond_val is False:
                    _resolved = True
                    for _cond2, _elif_body2 in (getattr(_frame_stmt, 'elifs', None) or []):
                        _elif_val = self._eval_const_bool(_cond2)
                        if _elif_val is True:
                            _resolved_body = _elif_body2 or []
                            break
                        if _elif_val is None:
                            _resolved = False
                            break
                    else:
                        _resolved_body = _frame_stmt.else_body or []
                if _resolved:
                    _stack.append((_resolved_body, 0))
                else:
                    _out.append(_frame_stmt)
            else:
                _out.append(_frame_stmt)
        return _out

    _pre_declared_globals = set()
    _phase17_mod = self.module_name if len(self.module_name) > 0 else "root"  # module name for _global_to_module mapping
    _phase17_own_stmts = _flatten_resolved_conditionals(stmts)
    _phase17_stmts = (_phase17_own_stmts
                       + (_flatten_resolved_conditionals(imported_stmts)
                          if (self.do_imports or self.link_imports) else []))
    _phase17_own_ids = set(id(s) for s in _phase17_own_stmts)

    def _phase17_value_type(_value):
        """Pure mapping from an RHS AST value to the C type
        _phase17_infer_global_type would assign it — no dict writes,
        no side effects. Factored out of _phase17_infer_global_type
        (below) so the TryStmt-branch join logic (_phase17_scan_try_
        branches, further below) can compute each branch's candidate
        type using the IDENTICAL rules without duplicating this table
        under a second name that would inevitably drift out of sync.
        (List/tuple element-type tracking (_elem_types) is NOT done
        here — that's a side effect specific to the direct-assignment
        caller, not part of "what C type does this value have.")"""
        if isinstance(_value, DictExpr):
            return 'MojoDict *'
        elif isinstance(_value, (ListExpr, TupleExpr)):
            return 'MojoList *'
        elif isinstance(_value, SetExpr):
            return 'MojoSet *'
        elif isinstance(_value, IntLiteral):
            value64 = _signed_int64(_value.value)
            return 'int' if -0x80000000 <= value64 <= 0x7FFFFFFF else 'int64_t'
        elif isinstance(_value, BoolLiteral):
            return 'int'
        elif isinstance(_value, StringLiteral):
            return 'char *'
        elif isinstance(_value, CallExpr):
            if (isinstance(_value.func, IdentExpr)
                    and _value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set', 'frozenset')):
                return {'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                        'list': 'MojoList *', 'List': 'MojoList *',
                        'set': 'MojoSet *', 'Set': 'MojoSet *',
                        'frozenset': 'MojoSet *'}[_value.func.name]
            if isinstance(_value.func, IdentExpr) and _value.func.name in self.struct_field_types:
                return f"{_value.func.name} *"
            elif isinstance(_value.func, IdentExpr):
                ret = self.func_return_types.get(_value.func.name, '')
                if ret.endswith(' *'):
                    return ret
                elif ret == 'char *':
                    return 'char *'
                else:
                    # Delegate the unknown-callee fallback to _quick_type,
                    # which knows shape-specific results this table has no
                    # row for — notably the one-char*-arg opaque-constructor
                    # passthrough (`X = Path(some_str)` → the value IS its
                    # char* argument at runtime, see _lower_opaque_ctor).
                    # Its container-builtin rows (`_BUILTIN_CTORS`) are the
                    # same kind of fact. Honor every POINTER result, not just
                    # `char *`: keeping only char* and defaulting every
                    # other pointer to int64_t declared the global as an
                    # integer, so a module-level `z = sorted([3, 1])` /
                    # `enumerate(...)` / `reversed(...)` / `zip(...)` /
                    # `d.keys()` printed the list's ADDRESS — the value was
                    # correct, the global's type was not. Non-pointers
                    # (int64_t/double/_Bool) still land on int64_t, matching
                    # this branch's old unconditional default.
                    qt2 = self._quick_type(_value)
                    return qt2 if (qt2 == 'char *' or qt2.endswith(' *')) else 'int64_t'
            elif (isinstance(_value.func, MemberExpr)
                    and _value.func.member in ('read', 'readline')
                    and not _value.args):
                return 'char *'
            elif (isinstance(_value.func, MemberExpr)
                    and _value.func.member == 'readlines'):
                return 'MojoList *'
            elif (isinstance(_value.func, MemberExpr)
                    and _value.func.member in ('encode', 'decode', 'format')):
                # str.encode()/str.decode()/str.format() all lower to a
                # real `char *` everywhere else in this codegen (see
                # gimple_gen_methods.py's char*-method table, which
                # stubs all three as identity passthroughs of the
                # receiver). Without this case the global got declared
                # int64_t against a char*-producing RHS — a hard
                # "assignment to 'int64_t' from 'char *'" in
                # whole-program mode (real: Lib/mailbox.py:32,
                # `linesep = os.linesep.encode('ascii')`), and a
                # pointer-stored-as-int64 (garbage on every later read,
                # e.g. `len(linesep)`) where coercion happened silently.
                return 'char *'
            else:
                # Any other method call: delegate to _quick_type, the single
                # source of truth for method-result shapes, and honor its
                # POINTER results. Hardcoding int64_t here (the old
                # behaviour) is what made a module-level
                # `z = d.keys()` / `z = s.split(",")` declare the global as
                # an integer and print the list's ADDRESS — the same
                # discarded-pointer bug as the unknown-callee case above,
                # and with the same fix. Non-pointers still land on int64_t.
                qt4 = self._quick_type(_value)
                return qt4 if (qt4 == 'char *' or qt4.endswith(' *')) else 'int64_t'
        elif (isinstance(_value, MemberExpr) and isinstance(_value.obj, IdentExpr)
                and _value.obj.name in self.imported_symbols):
            _mx_mod = self.imported_symbols[_value.obj.name].get('module')
            if (_mx_mod and _value.member in self._global_var_types
                    and getattr(self, '_global_to_module', {}).get(_value.member) == _mx_mod):
                _mx_t = self._global_var_types[_value.member]
                if _mx_t.endswith(' *'):
                    return _mx_t
                elif _mx_t == '_Bool':
                    return 'int'
                else:
                    return 'int64_t'
            # Not a known imported-module global: delegate to _quick_type,
            # whose shape rows (e.g. `.name`/`.parent` on a path-shaped
            # char* value → 'char *', matching _lower_MemberExpr) are the
            # single source of truth for these RHS types.
            qt3 = self._quick_type(_value)
            return qt3 if qt3 == 'char *' else 'int64_t'
        else:
            qt = self._quick_type(_value) or 'int64_t'
            if qt.endswith(' *'):
                return qt
            elif qt == '_Bool':
                return 'int'
            else:
                return 'int64_t'

    def _phase17_set_gtype(_gname: str, _ctype: str, _own: bool = True):
        """Record a Phase 1.7 global-type conclusion into the
        whole-program-shared dict, and — only when the statement is THIS
        module's own — into its own overlay too (see
        `_own_global_var_types`/`_global_dst_ctype` for why the overlay must
        exist alongside the shared dict).

        The `_own` split is the same distinction the callers already draw for
        `_global_to_module` three lines below each of these call sites, via
        `id(stmt) in _phase17_own_ids` — this function's own docstring says
        why `_phase17_stmts` deliberately includes `imported_stmts`: the
        SHARED table has to be a superset so cross-module `mod.attr` reads
        resolve. `_own_global_var_types` has no such cross-module purpose. It
        is read by `_lower_IdentExpr` as the answer to "is this bare name
        THIS module's own global", and an imported module's top-level
        `STDLIB_PATH = ...` is emphatically not — writing it there made a
        bare `STDLIB_PATH` in the importing module's body load
        `_build_stdlib_dylib_globals.STDLIB_PATH`, a field that module never
        declares ("'struct _build_stdlib_dylib_toplev' has no member named
        'STDLIB_PATH'", one per read site, 26 distinct names across 15
        modules of the self-host closure). The bare read
        now routes such a name to its OWNER's field via
        `_own_imported_global_home`, which this split is what lets it
        distinguish from a same-named global this module never imported.

        `_gname: str` is load-bearing: without it the self-hosted compiler
        typed the param int64_t and `_own_global_var_types[_gname] = ...`
        keyed by the boxed pointer, so `_own_overlay_global_ctype` missed
        and a `var counter: Int = 0` module global was declared `int` (the
        IntLiteral default) instead of `int64_t` (the annotation)."""
        self._global_var_types[_gname] = _ctype
        if _own:
            self._own_global_var_types[_gname] = _ctype

    def _phase17_infer_global_type(_gname, _value, _own: bool = True):
        """Infer & record a global's C type (self._global_var_types,
        plus element type for list/tuple literals) from its assigned
        RHS value. Factored out of the AssignStmt branch below so
        MultiAssignStmt (`a = b = expr`) can share the identical
        inference logic for every one of its targets — real Python
        chained-assignment semantics: all targets receive the SAME
        value, so they must all receive the SAME inferred type. Before
        this, MultiAssignStmt was entirely invisible to this pre-scan,
        so every chained-assignment global target fell through to
        whatever default 'not seen at all' implies (int64_t, via the
        unconditional "Globals are stored at C level as int64_t"
        fallback), even for an obviously-pointer-typed RHS. See
        CODEGEN_multi_assign_local_var_type_not_inferred
        (that doc covers the LOCAL-variable analogue of this same
        gap; this is the GLOBAL/module-scope sibling)."""
        _phase17_set_gtype(_gname, _phase17_value_type(_value), _own)
        if isinstance(_value, (ListExpr, TupleExpr)) and _value.elements:
            _elt = self._quick_type(_value.elements[0])
            for _e in _value.elements[1:]:
                _elt = TypeLattice.join(_elt, self._quick_type(_e))
            self._elem_types[_gname] = _elt
            self._global_elem_types[_gname] = _elt
        elif isinstance(_value, DictExpr) and _value.pairs:
            _vt = self._quick_type(_value.pairs[0][1])
            for _k, _v in _value.pairs[1:]:
                _vt = TypeLattice.join(_vt, self._quick_type(_v))
            self._global_dict_val_types[_gname] = _vt
            # A dict literal of LAMBDAS: what a later `d['k'](...)` call site
            # needs is the callee's return type, and the dict's own value
            # type (`void *`) does not carry it. Recorded with the same
            # unanimity-or-nothing rule `note_container_callable_ret` applies at a
            # runtime store (a dict has one value slot, so the answer is only
            # usable when every callable in it agrees).
            self._global_container_callable_ret[_gname] = \
                _lambda_pairs_ret_type(self, _value.pairs)
        elif isinstance(_value, LambdaExpr):
            # `e = lambda: False` at module scope. The lambda's own C return
            # type is `join_all([_quick_type(body)])` -- exactly what
            # `_infer_return_type` computes for the synthetic
            # `return <body>` body `_lower_LambdaExpr` builds -- so this
            # records the lifted definition's declared return type without
            # lifting anything. It has to be here, in the pre-scan, because
            # a function that CALLS `e` is emitted before `_toplevel`
            # lowers the lambda at all.
            self._global_callable_ret_types[_gname] = _lambda_ret_type(self, _value)

    def _phase17_scan_try_branches(_try_stmt):
        """Collect {name: C type} for every AssignStmt/MultiAssignStmt
        target living inside a top-level TryStmt's try/except/else/
        finally bodies, TypeLattice.join-ing the type across every
        branch that assigns the same name.

        Unlike an IfStmt (where _flatten_resolved_conditionals already
        picks the ONE platform-correct branch, mirroring how real
        CPython only ever executes one side of an `if sys.platform ==
        ...`), every branch of a try/except genuinely CAN execute at
        runtime -- the `try` body if nothing raises, one `except`
        handler if a matching exception is raised, or the `else` body
        if the try body succeeds -- so a correct global type must be
        the LUB across every branch that assigns the name, not just
        the first one found textually the way the flat top-level scan
        (which only ever sees a linear sequence of unconditionally-
        executed statements) is content to do.

        Deliberately NOT self-recursive (does not call itself for a
        nested TryStmt) -- mirrors _flatten_resolved_conditionals's
        own documented reason: a nested function calling itself here
        doesn't survive this file's own self-host build. A TryStmt
        nested inside another TryStmt's branch is left unscanned by
        this pass (out of scope for this fix -- no observed real-world
        instance needs it; see bugs/hard/CODEGEN_global_prescan_
        blind_to_trystmt_and_bare_annotation.md)."""
        _branch_lists = [_try_stmt.body or []]
        for _h in (_try_stmt.handlers or []):
            _branch_lists.append(getattr(_h, 'body', None) or [])
        if isinstance(_try_stmt.else_body, list):
            _branch_lists.append(_try_stmt.else_body)
        if isinstance(getattr(_try_stmt, 'finally_body', None), list):
            _branch_lists.append(_try_stmt.finally_body)
        _joined = {}
        for _blist in _branch_lists:
            for _bstmt in _flatten_resolved_conditionals(_blist):
                _pairs = []
                if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                    _pairs.append((_as_str(_bstmt.target.name), _bstmt.value))
                elif isinstance(_bstmt, MultiAssignStmt):
                    for _tgt in _bstmt.targets:
                        if isinstance(_tgt, IdentExpr):
                            _pairs.append((_as_str(_tgt.name), _bstmt.value))
                # Indexed iteration + `_as_str`, NOT `for _gname, _gvalue in
                # _pairs:` — a 2-tuple unpack over a boxed list miscompiles
                # self-hosted (both slots box to int64_t), so `_joined` got a
                # DECIMAL pointer key and the global was registered into
                # `_global_var_types` under that key instead of its name; the
                # field-freeze loop's `gname in _global_var_types` then missed
                # and the struct field never appeared.
                for _pi in range(len(_pairs)):
                    _gname = _as_str(_pairs[_pi][0])
                    _gvalue = _pairs[_pi][1]
                    _t = _phase17_value_type(_gvalue)
                    _joined[_gname] = (TypeLattice.join(_joined[_gname], _t)
                                       if _gname in _joined else _t)
        return _joined

    def _phase17_scan_if_branches(_if_stmt):
        """The IfStmt sibling of `_phase17_scan_try_branches`, for a
        top-level `if`/`elif`/`else` whose condition
        `_flatten_resolved_conditionals` could NOT fold to a
        compile-time constant (e.g. `if os.name == "nt": ENCODING =
        "utf-8" else: ENCODING = sys.getfilesystemencoding()` —
        `os.name` isn't one of the handful of comptime-foldable
        expressions `_eval_const_bool` recognizes, unlike
        `sys.platform`). An unresolved IfStmt is left as a single
        nested node in `_phase17_stmts` (never flattened into its
        branches the way a resolved one is), so the flat top-level
        scan loop never saw any of its branches' assignments at all —
        a global ONLY ever assigned inside such an if/else fell
        through to the unconditional 'globals are int64_t' default,
        same failure shape as the already-fixed TryStmt gap this
        mirrors. Concretely: `ENCODING`'s struct field was correctly
        inferred `char *` from OTHER evidence (the `"utf-8"` literal
        branch happened to be visible via a different path), but
        because THIS assignment-statement-type join never ran, this
        branch's own `sys.getfilesystemencoding()` RHS kept
        defaulting through the generic int64_t/`int` fallback,
        producing an invalid `char *`-field-assigned-from-`int`
        mismatch at both branches. See
        “CODEGEN_generator_function: Lib/tarfile.py”.

        Deliberately NOT self-recursive for the same reason
        `_phase17_scan_try_branches` isn't (a nested function calling
        itself here doesn't survive this file's own self-host build)
        — a nested if/elif/else inside one of THIS if's own branches
        is left unscanned (out of scope; no observed real-world
        instance needs it)."""
        _branch_lists = [_if_stmt.then_body or []]
        # Indexed, NOT `for _cond2, _elif_body2 in ...` (2-tuple unpack over a
        # boxed list miscompiles self-hosted).
        _elif_list = getattr(_if_stmt, 'elifs', None) or []
        for _eci in range(len(_elif_list)):
            _branch_lists.append(_elif_list[_eci][1] or [])
        if isinstance(_if_stmt.else_body, list):
            _branch_lists.append(_if_stmt.else_body)
        _joined = {}
        for _blist in _branch_lists:
            for _bstmt in _flatten_resolved_conditionals(_blist):
                _pairs = []
                if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                    _pairs.append((_as_str(_bstmt.target.name), _bstmt.value))
                elif isinstance(_bstmt, MultiAssignStmt):
                    for _tgt in _bstmt.targets:
                        if isinstance(_tgt, IdentExpr):
                            _pairs.append((_as_str(_tgt.name), _bstmt.value))
                # Indexed iteration + `_as_str` for the same reason as the
                # TryStmt sibling: the 2-tuple unpack boxed the name into a
                # decimal key, so the global landed in `_global_var_types`
                # under that key and the field-freeze loop missed the field
                # entirely — a top-level `if cond(): y = "a"` got no
                # `char * y` struct field self-hosted (the shim did).
                for _pi in range(len(_pairs)):
                    _gname = _as_str(_pairs[_pi][0])
                    _gvalue = _pairs[_pi][1]
                    _t = _phase17_value_type(_gvalue)
                    _joined[_gname] = (TypeLattice.join(_joined[_gname], _t)
                                       if _gname in _joined else _t)
        return _joined

    def _phase17_scan_global_reassignments() -> dict:
        """`{name: {pointer-shaped C type, ...}}` for every assignment any
        FUNCTION BODY in this compile makes to a name it declared `global`.

        The one thing the flat module-level scans above structurally cannot
        see. Under real Python scoping

            FW_VERSION_PREFIX = "--undefined--"        # module level
            def parseOptions():
                global FW_VERSION_PREFIX
                FW_VERSION_PREFIX = FW_PREFIX[:] + ["Versions", getVersion()]

        is two assignments to ONE binding, so the two types must be JOINED —
        but every Phase 1.7 pass walks module-level statements only
        (`_phase17_own_stmts`), so the name was frozen at `char *` from its
        first line forever. That is not a cosmetic mismatch: the field
        emitter, the assignment-site coercion and the read path all route
        through one conclusion, so the reassignment was coerced to `char *`
        (a silent re-typing of a `MojoList *`) and the NEXT line — which
        slices the same global as the list it has just become — sliced a
        `char *` and then emitted `char * + MojoList *`, a g++ error naming
        two types the source never mixed.

        Deliberately NOT `ginf._each_binding`, which is the one walker for the
        three LOCAL overlays and which deliberately stops at a nested
        `FunctionDef` because a nested def's names are its own locals. Here
        the relationship is exactly inverted: a `global N` inside a nested
        `def` still names the MODULE binding, at any nesting depth, so this
        walker descends. Same traversal order as `_each_binding` (pre-order,
        every branch that can bind), so the two cannot disagree about which
        statements bind what.

        Types come from `self._quick_type`, the SAME estimator every other
        global scan consults, and only a pointer-shaped answer counts as
        evidence. That is deliberate in both directions: an `int64_t`
        (unknown) answer contributes nothing rather than being read as a
        third kind, and no new RHS-type table is introduced for a question
        the shared estimator already answers. `_quick_type` already resolves
        `FW_PREFIX[:] + ["Versions", ...]` to `MojoList *` — its BinaryOp
        row unions the operand kinds with `int64_t` neutral — so this needs
        no Phase 1.7 table change of its own, and therefore cannot change
        what any OTHER caller of `_phase17_value_type` sees."""
        out: dict = {}

        def collect(body) -> list:
            """Every statement of `body` (and of any `def` nested in it) as a
            flat pre-order list. Lists, never a generator: this file is in
            the self-host closure, where a coroutine's symbols are
            referenced but never defined (`_each_binding`'s own docstring)."""
            seq: list = []
            def walk(stmts):
                for s in (stmts or []):
                    seq.append(s)
                    if isinstance(s, FunctionDef):
                        walk(s.body)
                    elif isinstance(s, IfStmt):
                        walk(s.then_body)
                        walk(getattr(s, 'else_body', None))
                        for _c, eb in (getattr(s, 'elifs', None) or []):
                            walk(eb)
                    elif isinstance(s, (WhileStmt, ForStmt)):
                        walk(getattr(s, 'body', None))
                        walk(getattr(s, 'else_body', None))
                    elif isinstance(s, WithStmt):
                        walk(s.body)
                    elif isinstance(s, TryStmt):
                        walk(s.body)
                        for h in (getattr(s, 'handlers', None) or []):
                            walk(getattr(h, 'body', None))
                        walk(getattr(s, 'else_body', None))
                        walk(getattr(s, 'finally_body', None))
            walk(body)
            return seq

        for _fn_stmt in _phase17_stmts:
            if not isinstance(_fn_stmt, FunctionDef):
                continue
            # Two rounds over one collected list rather than threading the
            # declared set through the walk: Python scoping makes `global N`
            # cover the WHOLE function regardless of where the statement
            # sits relative to the assignments, so the answer cannot depend
            # on traversal order and does not need to.
            _seq = collect(_fn_stmt.body)
            _declared: set = set()
            for _s in _seq:
                if isinstance(_s, GlobalStmt):
                    for _nm in (_s.names or []):
                        _declared.add(_as_str(_nm))
            if not _declared:
                continue
            for _s in _seq:
                if isinstance(_s, AssignStmt):
                    _targets = [_s.target]
                elif isinstance(_s, MultiAssignStmt):
                    _targets = list(_s.targets or [])
                else:
                    continue
                for _tgt in _targets:
                    if not isinstance(_tgt, IdentExpr):
                        continue
                    _tn = _as_str(_tgt.name)
                    if _tn not in _declared:
                        continue
                    _qt = self._quick_type(_s.value)
                    if _qt and _qt.endswith('*'):
                        out.setdefault(_tn, set()).add(_qt)
        return out

    for _scan_stmt in _phase17_stmts:
        # "_phase17_stmts" deliberately spans this module's OWN top-level
        # statements AND every inline-compiled imported module's (the SHARED
        # `_global_var_types` has to be a superset so cross-module `mod.attr`
        # reads resolve at all). `_phase17_own_ids` is the boundary, and it
        # gates BOTH things an "is this name MINE" question feeds: the
        # `_global_to_module` claim (each branch below) and, since this
        # commit, the `_own_global_var_types` overlay `_phase17_set_gtype`
        # writes. Named once so the two can never drift apart again.
        _scan_own = id(_scan_stmt) in _phase17_own_ids
        if isinstance(_scan_stmt, AssignStmt) and isinstance(_scan_stmt.target, IdentExpr):
            _gname = _scan_stmt.target.name
            if (isinstance(_scan_stmt.value, CallExpr)
                    and isinstance(_scan_stmt.value.func, MemberExpr)
                    and isinstance(_scan_stmt.value.func.obj, IdentExpr)
                    and _scan_stmt.value.func.obj.name in _COMPILE_TIME_CALL_MODULES
                    and _scan_stmt.value.func.member == 'compile'
                    and _scan_stmt.value.args
                    and isinstance(_scan_stmt.value.args[0], StringLiteral)):
                self._regex_patterns[_gname] = _scan_stmt.value.args[0].value
            if _gname in _pre_declared_globals:
                continue
            _pre_declared_globals.add(_gname)
            if _gname not in self._global_to_module and _scan_own:
                self._global_to_module[_gname] = _phase17_mod
            _phase17_infer_global_type(_gname, _scan_stmt.value, _scan_own)
        elif isinstance(_scan_stmt, MultiAssignStmt):
            for _tgt in _scan_stmt.targets:
                if not isinstance(_tgt, IdentExpr):
                    continue
                _gname = _tgt.name
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and _scan_own:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_infer_global_type(_gname, _scan_stmt.value, _scan_own)
        elif isinstance(_scan_stmt, VarDecl) and _scan_stmt.name not in _pre_declared_globals:
            _pre_declared_globals.add(_scan_stmt.name)
            if _scan_stmt.name not in self._global_to_module:
                self._global_to_module[_scan_stmt.name] = _phase17_mod
            if _scan_stmt.type_ann:
                _resolved = self._resolve_type(_scan_stmt.type_ann)
                _phase17_set_gtype(_scan_stmt.name, _resolved, _scan_own)
                if _resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
            else:
                if hasattr(_scan_stmt, 'value') and _scan_stmt.value:
                    if isinstance(_scan_stmt.value, DictExpr):
                        _phase17_set_gtype(_scan_stmt.name, 'MojoDict *', _scan_own)
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, (ListExpr, TupleExpr)):
                        _phase17_set_gtype(_scan_stmt.name, 'MojoList *', _scan_own)
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, SetExpr):
                        _phase17_set_gtype(_scan_stmt.name, 'MojoSet *', _scan_own)
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, StringLiteral):
                        _phase17_set_gtype(_scan_stmt.name, 'char *', _scan_own)
                    elif (isinstance(_scan_stmt.value, CallExpr)
                            and isinstance(_scan_stmt.value.func, IdentExpr)
                            and _scan_stmt.value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set', 'frozenset')):
                        _phase17_set_gtype(_scan_stmt.name, {
                            'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                            'list': 'MojoList *', 'List': 'MojoList *',
                            'set': 'MojoSet *', 'Set': 'MojoSet *',
                            'frozenset': 'MojoSet *',
                        }[_scan_stmt.value.func.name], _scan_own)
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, CallExpr):
                        if isinstance(_scan_stmt.value.func, IdentExpr):
                            ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                            if ret and ret.endswith(' *'):
                                _phase17_set_gtype(_scan_stmt.name, ret, _scan_own)
                            elif ret == 'char *':
                                _phase17_set_gtype(_scan_stmt.name, 'char *', _scan_own)
                            else:
                                _phase17_set_gtype(_scan_stmt.name, 'int64_t', _scan_own)
                        elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                and _scan_stmt.value.func.member in ('read', 'readline')
                                and not _scan_stmt.value.args):
                            _phase17_set_gtype(_scan_stmt.name, 'char *', _scan_own)
                        elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                and _scan_stmt.value.func.member == 'readlines'):
                            _phase17_set_gtype(_scan_stmt.name, 'MojoList *', _scan_own)
                        else:
                            _phase17_set_gtype(_scan_stmt.name, 'int64_t', _scan_own)
                    else:
                        qt = self._quick_type(_scan_stmt.value) or 'int64_t'
                        _phase17_set_gtype(_scan_stmt.name, qt if (qt.endswith(' *') or qt == '_Bool') else 'int64_t', _scan_own)
                else:
                    _phase17_set_gtype(_scan_stmt.name, 'int64_t', _scan_own)
        elif isinstance(_scan_stmt, TryStmt):
            for _gname, _gtype in _phase17_scan_try_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and _scan_own:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_set_gtype(_gname, _gtype, _scan_own)
        elif isinstance(_scan_stmt, IfStmt):
            for _gname, _gtype in _phase17_scan_if_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and _scan_own:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_set_gtype(_gname, _gtype, _scan_own)
        elif (isinstance(_scan_stmt, ComptimeVarStmt)
                and isinstance(_scan_stmt.value, (ListExpr, TupleExpr))
                and _scan_stmt.target not in _pre_declared_globals):
            _pre_declared_globals.add(_scan_stmt.target)
            if _scan_stmt.target not in self._global_to_module and _scan_own:
                self._global_to_module[_scan_stmt.target] = _phase17_mod
            _phase17_infer_global_type(_scan_stmt.target, _scan_stmt.value, _scan_own)

    _phase17_append_hits: dict = {}
    _gmi_phase17_collect_appends(self, _phase17_stmts, _phase17_append_hits)
    for _gname, _gargs in _phase17_append_hits.items():
        if self._global_var_types.get(_gname) != 'MojoList *':
            continue
        if _gname in self._global_elem_types:
            continue
        _elt = None
        for _at in _gargs:
            _elt = _at if _elt is None else TypeLattice.join(_elt, _at)
        if _elt:
            self._elem_types[_gname] = _elt
            self._global_elem_types[_gname] = _elt

    _gmi_scan_try_imports(
        self, _phase17_mod,
        stmts + (imported_stmts if (self.do_imports or self.link_imports) else []))

    # Indexed iteration + `_as_str`, NOT `for _gn, _gt in ....items()`: the
    # self-hosted 2-tuple unpack boxes BOTH slots to int64_t, so `_gn in
    # self._global_c_decl_types` (plain-str keys) missed, the dispatch-name
    # test missed, and the final `else` wrote a decimal-address key with an
    # erased value — `_BIN_OPS`/`_CMP_OPS` never got their cdecl entry this
    # loop exists to seed, `_own_overlay_global_ctype`'s container rule could
    # not return it, and the module struct field came out `int64_t _BIN_OPS`
    # where the shim emits `MojoDict *`.
    _early_gvt_items = list(self._global_var_types.items())
    for _egi in range(len(_early_gvt_items)):
        _gn = _as_str(_early_gvt_items[_egi][0])
        _gt = _early_gvt_items[_egi][1]
        # Dispatch-table lookup BEFORE the `already in _global_c_decl_types`
        # skip: the Phase-1.7 scan (above) writes the generic scalar
        # `int64_t` placeholder for any global whose RHS it cannot resolve
        # (`_BIN_OPS = _GD_BIN_OPS`, an imported alias), so testing
        # membership first would skip exactly the names this loop exists to
        # preserve. `_own_overlay_global_ctype`'s documented rule 1 is that
        # these container entries WIN over a scalar own-conclusion — which is
        # exactly why the answer has to be the name's REAL type and not a
        # blanket `MojoDict *`: this lands in the SHARED bare-name-keyed
        # `_global_c_decl_types`, so a wrong kind here re-types the OWNING
        # module's own correct conclusion ("cannot coerce MojoSet * to
        # MojoDict *", four modules of the self-host closure). A name the table
        # does not carry is not forced at all, which is the honest "this scan
        # knows nothing about it" and leaves the owner's conclusion standing.
        _forced = dispatch_table_global_ctype(_gn)
        if _forced is not None:
            self._global_c_decl_types[_gn] = _forced
        elif _gn in self._global_c_decl_types:
            continue
        elif _gt in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            self._global_c_decl_types[_gn] = 'int64_t'  # boxed by default
        else:
            self._global_c_decl_types[_gn] = _gt

# A global whose BINDING carries values of more than one C type has no
    # single C type, and the box is the honest declaration — the same answer
    # `resolve_shared._infer_local_var_types` reaches for a LOCAL bound to
    # containers of more than one kind. Two tables get two different answers
    # on purpose, because they answer two different questions:
    #
    #  * the C FIELD is the box (`_global_c_decl_types`), because a
    #    `int64_t` slot is the only field that can hold either kind. This is
    #    already the convention for every container global (see
    #    `_gscan_declare_global`'s DictExpr/ListExpr/SetExpr rows and
    #    `_own_overlay_global_ctype`'s container rule), and it is what
    #    `_global_dst_ctype` coerces the cross-function store to, so the
    #    store no longer re-types a `MojoList *` through a `char *` cast.
    #  * the SEMANTIC type (`_global_var_types`, which the read path uses)
    #    is the kind the FUNCTION bodies store, when they agree on one. A
    #    read of this global in any path that reaches the reassignment sees
    #    that kind, and the read path's own convention (`_lower_IdentExpr`:
    #    a container `gtype` reads back as an `int64_t` temp carrying the
    #    container in `_actual_types`) is exactly what every consumer —
    #    slice, subscript, `in`, print — already dispatches on. With the box
    #    in `_global_var_types` instead, every one of those consumers saw a
    #    bare `int64_t` and fell through to its scalar path: `L[:]` became
    #    INTEGER arithmetic on the box.
    #
    # When the function bodies store MORE THAN ONE kind there is no semantic
    # answer to give, so that case keeps the box in both tables and every
    # consumer falls back to what it already did for an untracked `int64_t`.
    # Stated rather than papered over: a read that precedes the reassignment
    # sees the reassigned kind. That is a real residual of any static answer
    # here, it is the same trade `_infer_local_var_types` makes for a
    # multi-kind local, and the alternative — refusing the file — helps
    # nobody.
    #
    # Runs LAST among the global passes, and overwrites all three tables,
    # because the decision is only knowable once the module-level kinds are
    # in: `_global_c_decl_types` is set above from `_global_var_types`, and
    # `_own_overlay_global_ctype` reads both. Setting only one of the three
    # would leave the field freeze and the assignment site disagreeing — the
    # exact failure `_own_overlay_global_ctype` exists to prevent.
    #
    # A name with no module-level pointer kind is left alone: `global N` with
    # no `N =` at module scope names no binding this codegen materializes, so
    # there is nothing to reconcile.
    _mgk: set = set()
    for _rgname, _rgkinds in _phase17_scan_global_reassignments().items():
        _rgbase = self._global_var_types.get(_rgname, '')
        _rgall = set(_rgkinds)
        if _rgbase.endswith('*'):
            _rgall.add(_rgbase)
        elif _rgbase:
            # A scalar module-level kind cannot conflict with a pointer:
            # every cross-function kind here IS pointer-shaped, so this is a
            # genuine re-typing (an int global replaced by a container, or the
            # reverse) rather than two kinds in conflict. Out of scope here:
            # nothing downstream can represent it and it is not what the
            # box answers.
            continue
        if len(_rgall) < 2:
            continue
        _rgsem = (_rgkinds.pop() if len(_rgkinds) == 1 else 'int64_t')
        self._global_var_types[_rgname] = _rgsem
        self._own_global_var_types[_rgname] = _rgsem
        self._global_c_decl_types[_rgname] = 'int64_t'
        _mgk.add(_rgname)
    self._multi_kind_globals = _mgk

    # Which of THIS module's bare names are really another module's globals
    # field. Placed HERE, after every writer of the two tables its answer is
    # built from — the Phase 1.7 scan above is what populates
    # `_global_to_module`/`_own_global_var_types`, and the multi-kind global
    # join immediately above is the last writer of the overlay — and before
    # the first function-body emission below, because the bare-name reads it
    # fixes live in those bodies. `stmts`, NEVER the `imported_stmts`
    # concatenation: the question is "did THIS module import it", and a
    # sibling's own `from c import K` says nothing about what this module's
    # `K` means.
    _gmi_scan_imported_global_homes(self, stmts)

    func_parts: list[str] = []

    _emitted_closures: set[str] = set()
    _emitted_env_allocs: set[str] = set()  # `_alloc_<env>` bodies — a merged
    # mutually-recursive sibling-closure GROUP shares one env struct, so its
    # allocator must be emitted exactly once (a second definition is a hard
    # C redefinition error).

    toplevel_stmts = []

    _toplevel_types = (AssignStmt, AugAssignStmt, ExprStmt,
                       IfStmt, WhileStmt, ForStmt,
                       TryStmt, WithStmt, PassStmt,
                       BreakStmt, ContinueStmt, ReturnStmt,
                       RaiseStmt, AssertStmt, VarDecl)
    self._has_toplevel_code = False
    for _ts in stmts:
        if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
            self._has_toplevel_code = True
            break
        if isinstance(_ts, ComptimeVarStmt) and isinstance(_ts.value, (ListExpr, TupleExpr)):
            self._has_toplevel_code = True
            break
    self._toplevel_calls_main = False
    # Direct shallow scan FIRST — the generic `_walk_ast` recursion below
    # has proven unreliable on the self-hosted compiled path (its
    # `dataclasses.fields()` handling did not recurse into `ExprStmt.value`),
    # so `_toplevel_calls_main` stayed False and the C wrapper emitted a
    # SECOND `_gimple_main ()` after `_toplevel ()` (the double-invocation
    # the branch comment in `_gen_func` warns about) — a stage1-vs-stage2
    # parity break under MOJO_NO_SHIM=1. Covers the two real shapes: a bare
    # top-level `main()` and `if __name__ == '__main__': main()` (one level
    # into an IfStmt then/elif/else body).
    def _sm_stmt_calls_main(_st) -> bool:
        _v = getattr(_st, 'value', None) if isinstance(_st, ExprStmt) else None
        if not isinstance(_v, CallExpr):
            return False
        _f = _v.func
        if isinstance(_f, IdentExpr) and _as_str(_f.name) == 'main':
            return True
        # `sys.exit(main())` / `raise SystemExit(main())`: the `main()` call
        # is an ARGUMENT of the outer call, not the whole expression. The
        # generic `_walk_ast` pass below is supposed to catch this but does
        # not reliably on the self-hosted path, so `_toplevel_calls_main`
        # stayed False natively and the wrapper emitted a SECOND
        # `_gimple_main ()` after `_toplevel ()` (repro:
        # test_no_new_container_casts.py). One argument level covers the
        # real `sys.exit(main())` idiom.
        for _a in (_v.args or []):
            if (isinstance(_a, CallExpr) and isinstance(_a.func, IdentExpr)
                    and _as_str(_a.func.name) == 'main'):
                return True
        return False
    for _ts in stmts:
        if _sm_stmt_calls_main(_ts):
            self._toplevel_calls_main = True
            break
        if isinstance(_ts, IfStmt):
            _if_bodies = list(getattr(_ts, 'then_body', None) or [])
            for _ep in (getattr(_ts, 'elifs', None) or []):
                _if_bodies.extend(_ep[1] or [])
            _eb = getattr(_ts, 'else_body', None)
            if isinstance(_eb, list):
                _if_bodies.extend(_eb)
            for _ib in _if_bodies:
                if _sm_stmt_calls_main(_ib):
                    self._toplevel_calls_main = True
                    break
            if self._toplevel_calls_main:
                break
    for _ts in stmts:
        if self._toplevel_calls_main:
            break
        if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
            for _n in _walk_ast(_ts):
                if isinstance(_n, CallExpr) and isinstance(_n.func, IdentExpr) and _as_str(_n.func.name) == 'main':
                    self._toplevel_calls_main = True
                    break
            if self._toplevel_calls_main:
                break

    # Register return types and param types for self-host hardcoded
    # forward-declared symbols BEFORE any function body is lowered.
    # These symbols are defined in sibling self-host modules (fire_compiler,
    # myinterpreter) but called from THIS module's bodies — the types aren't
    # in func_return_types/imported_symbols (the defining module owns those),
    # so _emit_call's argument coercion would leave temps as int64_t,
    # causing -Wint-conversion errors (e.g. int64_t -> char * / Parser *).
    # Seeded from gimple_codegen._selfhost_syms(), the same table the
    # forward-declaration strings further down are emitted from: the two used
    # to be independent hand-written copies (plus a return-type-only dict in
    # gimple_codegen.py and emit_calls.py consulting that), and they
    # disagreed — `Parser__parse_expr` was `int64_t` in all of them while the
    # definition the codegen infers is `UnaryOp *`, which broke every
    # `--dump-full` self-host closure with "conflicting types" plus a
    # -Wint-conversion error per call site.
    if _is_selfhost_file:
        for _shn, _shr, _shp in gimple_codegen._selfhost_syms():
            if _shn not in self.func_return_types:
                self.func_return_types[_shn] = _shr
            if _shn not in self.func_param_types:
                self.func_param_types[_shn] = list(_shp)

    # ── GPU offload, Seam 1 + Seam 3 ──────────────────────────────────────
    # Which functions are DEVICE is decided ONCE, here, before any body is
    # emitted -- "emit this one to a different target" is not a decision an
    # emitter can make about a function it has already started, which is why
    # device_select is a separate pre-pass rather than a check inside
    # gen_func. Cheap when there are no device functions (the overwhelmingly
    # common case), and it only walks the AST for functions, never bodies.

    for stmt in stmts:
        if isinstance(stmt, FunctionDef):
            if (stmt.name in self._supported_generators or stmt.name in self._supported_async
                    or stmt.name in self._supported_async_gen):
                continue
            if stmt.name in self._unsupported_generator_names:
                continue
            # A DEVICE function becomes MSL, accumulated into
            # `_device_parts` and embedded as a C string at the end of the
            # module -- the same trick `test_llm/kernels.metal.inc` uses, and
            # the reason this needs no offline metallib step at all. It is
            # NOT emitted as C, because a C definition of a kernel would be
            # dead code that still has to typecheck.
            if _device_kinds.get(_as_str(stmt.name)) == _gmi_device_select.DEVICE:
                _msl = None
                try:
                    _msl = _gmi_emit_metal.emit_kernel(stmt, kernel=True)
                except _gmi_emit_metal.MetalUnsupported as _me:
                    if _as_str(stmt.name) in _device_explicit:
                        # EXPLICIT `@gpu` that will not lower is a build
                        # error, not a silently-stubbed C function: the user
                        # asked for the GPU, the whole point of the path is
                        # that the GPU runs the code they wrote, and quietly
                        # running it on the CPU is a lie with exit 0.
                        raise RuntimeError(
                            f'GPU kernel {_as_str(stmt.name)!r} did not lower '
                            f'to MSL: {_me}') from _me
                    # INFERRED (a stdlib kernel reached through
                    # `compile_function[...]`) that will not lower is
                    # different in kind: nobody asked for the device path for
                    # this function, and erroring here made the module
                    # uncompilable. Measured: 10 stdlib/test files died on it
                    # -- std/gpu's `abort_kernel`/`_read_back_kernel`, the
                    # test/asyncrt and test/algorithm/gpu device-pointer
                    # kernels -- so `stdlib-syntax` was 91 unexpected and the
                    # whole stdlib could not be built. Falling back to the
                    # host costs nothing that was asked for: the function
                    # compiles and runs as ordinary C, and the GPU path simply
                    # does not engage for it until the emitter covers it
                    # (`doc/GPU_OFFLOAD_PLAN.md` increment 2).
                    _device_fallbacks.append(
                        f'{_as_str(stmt.name)}: {_me}')
                    _device_kinds[_as_str(stmt.name)] = _gmi_device_select.HOST
                if _msl is not None:
                    _device_parts.append(_msl)
                    continue
            _nested_pushed = []
            _prefix = f"{stmt.name}::"
            for _qn, _info in self._nested_async_api.items():
                if _qn.startswith(_prefix):
                    _nm = _info['nested_name']
                    self._async_api[_nm] = _info
                    _nested_pushed.append(_nm)
            for _cvs in stmt.body:
                if isinstance(_cvs, ComptimeVarStmt):
                    _cv = self._eval_const(_cvs.value)
                    if _cv is not None:
                        self._comptime_vals.setdefault(_cvs.target, _cv)
            _func_outer_scope = self._push_import_scope()
            self._collect_body_import_bindings(stmt.body, _func_outer_scope)
            try:
                for ci in self._all_closures.get(stmt.name, {}).values():
                    _gmi_emit_closure_recursive(self, func_parts, _emitted_closures, _emitted_env_allocs, ci, stmt.name)
                self._lambda_parts = []
                func_parts.append(self.gen_func(stmt))
            finally:
                self._pop_import_scope()
                for _nm in _nested_pushed:
                    self._async_api.pop(_nm, None)
            if self._lambda_parts:
                func_parts.extend(self._lambda_parts)
                self._lambda_parts = []
            func_parts.append('')
        elif isinstance(stmt, StructDef):
            _moids = self._struct_method_overload_ids(stmt)
            # Index loop, NOT `zip(stmt.methods, _moids)`: the self-hosted
            # backend has no `zip()` lowering (`mojo_unsupported_iter`, body
            # runs zero times), so this method-BODY emission loop silently
            # emitted nothing — every struct method was missing from compiled
            # mojoc's output. `_moids` is length-aligned with `stmt.methods`.
            _z7_meths = stmt.methods
            for _z7k in range(len(_z7_meths)):
                m = _z7_meths[_z7k]
                overload_id = _moids[_z7k] if _z7k < len(_moids) else ''
                if (stmt.name, m.name) in self._supported_generator_methods:
                    continue
                if (m.name == '__new__'
                        and stmt.name in getattr(self, '_bytes_subclass_structs', ())):
                    # A builtin-`bytes` subclass's `__new__` is handled
                    # inline at the construction site (payload synthesis);
                    # its `return super().__new__(cls, val)` body is not a
                    # callable C method. See _lower_struct_constructor.
                    continue
                method_outer_name = f"{stmt.name}_{m.name}{overload_id}"
                _method_outer_scope = self._push_import_scope()
                self._collect_body_import_bindings(m.body, _method_outer_scope)
                for ci in self._all_closures.get(method_outer_name, {}).values():
                    _gmi_emit_closure_recursive(self, func_parts, _emitted_closures, _emitted_env_allocs, ci, method_outer_name)
                self._lambda_parts = []
                # An INHERITED method body physically belongs to the base
                # class's module (the merge copied the node), so its `#line`
                # directives must name that file — see gen_stmt's
                # `_line_src_file` and _inherited_method_src above.
                _imh_src = getattr(self, '_inherited_method_src', {}).get(id(m))
                _prev_line_src = getattr(self, '_line_src_file', None)
                if _imh_src:
                    self._line_src_file = (self._module_source_paths.get(_imh_src)
                                           or self._current_filename)
                func_parts.append(self._gen_struct_method(stmt.name, m, overload_id))
                func_parts.append('')
                self._line_src_file = _prev_line_src
                self._pop_import_scope()
                if self._lambda_parts:
                    func_parts.extend(self._lambda_parts)
                    self._lambda_parts = []
        elif isinstance(stmt, TraitDef):
            lines = [f"typedef struct {stmt.name}_vtable {{"]
            _seen_vtable_members: set = set()
            for m in stmt.methods:
                safe_mname = _safe_name(m.name)
                if safe_mname in _seen_vtable_members:
                    continue
                _seen_vtable_members.add(safe_mname)
                ret    = self._resolve_type(m.return_type)
                if gimple_ctypes._params_have_vararg(m.params):
                    ptypes = 'MojoList *'
                else:
                    if m.params:
                        # Plain unpack loop, NOT a genexpr with a
                        # tuple-unpack target joined into a string.
                        _vt_parts = []
                        for _vtpn, _vtpt in m.params:
                            _vt_parts.append(self._resolve_type(_vtpt))
                        ptypes = ', '.join(_vt_parts)
                    else:
                        ptypes = 'void'
                lines.append(f"  {ret} (*{safe_mname}) ({ptypes});")
            lines.append(f"}} {stmt.name}_vtable;")
            func_parts.extend(lines)
            func_parts.append('')
        elif isinstance(stmt, (ImportStmt, FromImportStmt)):
            pass  # Imports processed in pre-pass; extern declarations generated in preamble
        elif (isinstance(stmt, ComptimeVarStmt)
                and isinstance(stmt.value, (ListExpr, TupleExpr))):
            toplevel_stmts.append(AssignStmt(
                target=IdentExpr(stmt.target, line=stmt.line, col=stmt.col),
                value=stmt.value, line=stmt.line, col=stmt.col))
        elif isinstance(stmt, (AssignStmt, AugAssignStmt, MultiAssignStmt,
                               ExprStmt, IfStmt, WhileStmt, ForStmt,
                               TryStmt, WithStmt, PassStmt,
                               BreakStmt, ContinueStmt, ReturnStmt,
                               RaiseStmt, AssertStmt, VarDecl)):
            toplevel_stmts.append(stmt)
        else:
            _debug_note('top-level statement dropped', type(stmt).__name__)
            func_parts.append(f"/* TODO: top-level {type(stmt).__name__} */")

    # `_as_funcdef_node`, not a bare `s`: `stmts` is a heterogeneous
    # statement list, so its self-hosted element type is opaque int64_t
    # regardless of the isinstance filter — every `fdef.name`/`fdef.body`
    # read below then went through the dynamic getattr path instead of a
    # direct struct-field load. Concretely, `.get(fdef.name, ...)` treated
    # `fdef.name`'s (wrongly int64_t) result as a raw integer needing
    # `mojo_str_from_int()` conversion into a dict key — looking up
    # func_return_types by a stringified ADDRESS ("54073494352") instead
    # of the real name ("make_adder"), always missing and always falling
    # to the 'int64_t' default. A closure-returning function's forward
    # declaration was silently wrong on every compile as a result.
    func_defs = [_as_funcdef_node(s) for s in stmts if isinstance(s, FunctionDef)]
    for fdef in func_defs:
        if fdef.name == 'main':
            continue
        # `gimple_ctypes._params_have_vararg` — NOT `for pn, _ in
        # fdef.params`: a genexpr/comprehension target unpack over a
        # tuple-of-tuples built ad hoc boxes both slots to int64_t on the
        # self-hosted path (see analyze_param_usage's `==`/`+` operand
        # scans). But the actual `pn in inferred_params` / `pn, pt in
        # fdef.params` loop just below is left as a PLAIN unpack, not
        # converted to `fdef.params[_pi][0]` indexing: that double-
        # subscript form was tried and is itself broken here — confirmed
        # via unescape_c.py's `s` parameter, where `fdef.params[_pi][0]`
        # came back with a working `==` but a broken `len()` (reported 0
        # for a real 1-char string) and every `in inferred_params` dict-
        # membership check against it missed, whereas the plain unpack's
        # `pn` hashes correctly. Do not "index-ify" this loop.
        if gimple_ctypes._params_have_vararg(fdef.params):
            self.func_param_types[fdef.name] = self._signature_ctypes(fdef.params, fdef)
            self._note_vararg_trailing_param_types(fdef)
        else:
            inferred_params = self._inferred_param_types.get(fdef.name, {}) if hasattr(self, '_inferred_param_types') else {}
            param_ctypes = []
            for pn, pt in (fdef.params or []):
                if pn in inferred_params:
                    param_ctypes.append(inferred_params[pn])
                else:
                    param_ctypes.append(self._param_ctype(pn, pt, fdef))
            self.func_param_types[fdef.name] = param_ctypes

    has_toplevel_code = len(toplevel_stmts) > 0
    # Reconcile toplevel global C types with LATE-resolved callee return
    # types before the toplevel body is generated. The early global scans
    # freeze an unannotated-call RHS (`protect_ident = ident(protect)`) at
    # int64_t because func_return_types isn't populated yet; by now every
    # function's return type IS final (the gen_func loop above completed),
    # so an int64_t-frozen global whose callee returns a pointer would
    # otherwise be stored through `_safe_coerce_emit` as a boxed int64 into
    # a globals-struct FIELD the later assembly correctly declares as the
    # real pointer type — "assignment to 'MojoList *' from 'int64_t'"
    # (test_sys_setprofile.py:415). Only ever WIDENS int->pointer; never
    # downgrades an already-correct pointer entry.
    for _rs in stmts:
        if (isinstance(_rs, AssignStmt) and isinstance(_rs.target, IdentExpr)
                and isinstance(_rs.value, CallExpr)
                and isinstance(_rs.value.func, IdentExpr)):
            _gn = _rs.target.name
            if self._global_c_decl_types.get(_gn) in ('int64_t', 'int'):
                _crt = self.func_return_types.get(_rs.value.func.name, '')
                if isinstance(_crt, str) and _crt.endswith(' *'):
                    self._global_c_decl_types[_gn] = _crt
                    self._global_var_types[_gn] = _crt
                    # Mirror into this instance's own overlay: the widened
                    # pointer is NEWER information than the Phase 1.7 scan's
                    # int64_t scalar freeze, and `_global_dst_ctype` trusts
                    # own SCALAR conclusions over the shared dicts — without
                    # this mirror that trust would suppress exactly the
                    # widening this loop exists to perform at every
                    # global-assignment emission site.
                    self._own_global_var_types[_gn] = _crt
    if has_toplevel_code:
        self._lambda_parts = []
        toplevel_func = self._gen_toplevel(toplevel_stmts)
        func_parts.append(toplevel_func)
        func_parts.append('')
        # Flush the lambdas lifted by the TOP-LEVEL body. The function and
        # struct-method paths above each reset-then-flush `_lambda_parts`
        # after emitting their body; the top-level path had no flush at all,
        # so a lambda written at module scope was lowered and registered but
        # its lifted definition never made it into the output — the call site
        # then linked against a symbol nothing defined and the link failed
        # with "Undefined symbols ... main_lambda_1". Reachable before this
        # only through a module-level `sorted(xs, key=lambda v: -v)`, whose
        # key call lowers the lambda while emitting the top-level body.
        if self._lambda_parts:
            func_parts.extend(self._lambda_parts)
            self._lambda_parts = []
        if not self.emit_entry_points:
            sub_fn = _module_toplevel_name(self.module_name)
            if sub_fn not in self._sub_toplevels:
                self._sub_toplevels.append(sub_fn)
            if not self.do_imports:
                init_fn = _module_init_name(self.module_name)
                func_parts.append(f"__attribute__((constructor)) static void {sub_fn}_ctor (void)")
                func_parts.append("{")
                func_parts.append(f"  {sub_fn} ();")
                func_parts.append("}")
                func_parts.append('')
                func_parts.append(f"void {init_fn} (void)")
                func_parts.append("{")
                func_parts.append(f"  {sub_fn} ();")
                func_parts.append("}")
                func_parts.append('')

    if self.emit_entry_points:
        has_main = False
        for _hs in stmts:
            if isinstance(_hs, FunctionDef) and _hs.name == 'main':
                has_main = True
                break
        if not has_main:
            func_parts.append("int _gimple_main (void)")
            func_parts.append("{")
            func_parts.append("  return 0;")
            func_parts.append("}")
            func_parts.append("")
            func_parts.append("int main (int argc, const char **argv) {")
            func_parts.append("  mojo_set_argv(argc, argv);")
            func_parts.append("#if USE_PYTHON")
            func_parts.append("  Py_Initialize ();")
            func_parts.append("#endif")
            for sub_fn in self._sub_toplevels:
                func_parts.append(f"  {sub_fn} ();")
            if has_toplevel_code:
                func_parts.append("  _toplevel ();")
            func_parts.append("#if USE_PYTHON")
            func_parts.append("  Py_Finalize ();")
            func_parts.append("#endif")
            func_parts.append("  return 0;")
            func_parts.append("}")

    parts = [
        '/* Generated by gimple_codegen.py */',
        '/* Compile with: gcc -fgimple -fsyntax-only file.c (uses gcc-15 if available) */',
        '#define USE_PYTHON 1' if self._python_api_needed else '#define USE_PYTHON 0',
        '#include <stdint.h>',
        '#include <stdlib.h>',
        '#include <string.h>',
        '#include <math.h>',
        '#include <stdio.h>',
        '#include <setjmp.h>',
        '#include <dlfcn.h>',
        '#if USE_PYTHON',
        '#include <Python.h>',
        '#endif',
        '#include <fire_runtime.h>',
        # Only when this module actually offloads something. A module with
        # no kernels must not acquire a dependency on the Metal runtime, or
        # it stops being linkable against a plain fire_runtime. Header first,
        # then the launch prototypes -- these are plain C signatures and do
        # not need the header, but the sidecar's own definitions call through
        # it and reading them in the order they are used is worth more than
        # the dependency they do not have. The star-unpack-of-a-conditional
        # is the same shape as the coroutine shim just below.
        *(['#include <fire_metal.h>',
           _gmi_device_glue.emit_launch_prototypes(_device_kernels_meta)]
          if _device_kernels_meta
          # The introspection prototypes are unconditional; the launch
          # prototypes and the Metal include are not (see device_glue).
          else [_gmi_device_glue.emit_introspection_prototypes()]),
        '#include <fire_sqlite3.h>',
        '#include <fire_zlib.h>',
        '#include <fire_ssl.h>',
        '#include <fire_ncurses.h>',
        *(( '/* A3 stack-switch coroutine shim (runtime/mojo_coro_gen.c) */',
            'extern int64_t __mojo_coro_yield_i (int64_t, int64_t);',
            'extern int64_t __mojo_coro_yield_p (int64_t, void *);',
            'extern int64_t __mojo_coro_yield_d (int64_t, double);',
            'extern int64_t __mojo_gen_arg (int64_t, int64_t);',
            'extern double  __mojo_gen_arg_d (int64_t, int64_t);',
            'extern void    __mojo_gen_set_return (int64_t, int64_t);',
            # The generator protocol as driven from ordinary
            # (non-coroutine) code: `g.send(v)` resumes the generator with
            # a payload for the yield it is suspended on (see
            # _lower_generator_send in emit_calls.py — the per-generator
            # `<base>_resume` trampoline hardcodes a zero send, so this
            # path calls the runtime entry both funnel into directly).
            'extern int64_t __mojo_gen_resume (int64_t, int64_t);',
            'extern int64_t __mojo_gen_value (int64_t);',
            'extern double  __mojo_gen_send_d (int64_t);',
            # The rest of the generator protocol, driven from ordinary
            # (non-coroutine) code: `g.throw(Exc)` injects an exception at
            # the suspend point, `g.close()` throws GeneratorExit so the
            # body's `finally` still runs. See _lower_generator_throw /
            # _lower_generator_close in emit_calls.py.
            'extern int64_t __mojo_gen_throw (int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_gen_close (int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_2 (int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_3 (int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_4 (int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_5 (int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_6 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_7 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_8 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_1 (int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_2 (int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_3 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_4 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_5 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_6 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_7 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_tuple_box_tag_8 (int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t);',
            'extern int64_t mojo_tagged_int (int64_t, int64_t);',
            'extern int64_t mojo_tagged_word_dyn (int64_t, int64_t);',
            'extern int64_t mojo_tagged_tag_dyn (int64_t, int64_t);',
            'extern char *  mojo_tagged_str (int64_t, int64_t);',
            'extern int64_t mojo_tagged_list (int64_t, int64_t);',
            'extern double  mojo_tagged_double (int64_t, int64_t);',
            'extern void    __mojo_async_await_sleep (int64_t, double);',
            'extern int64_t __mojo_async_await_sock_recv (int64_t, int64_t);',
            'extern int64_t __mojo_gen_retval (int64_t);',
            'extern int64_t __mojo_gen_resume (int64_t, int64_t);',
            'extern int64_t __mojo_gen_value (int64_t);',
            'extern double  __mojo_gen_send_d (int64_t);',
            'extern void    __mojo_gen_destroy (int64_t);',
            'extern void    __mojo_async_run_gen (int64_t);',
            'extern _Bool   __mojo_async_iscoroutine (int64_t);',
            'extern void    __mojo_async_task_schedule (int64_t);',
            'extern int64_t __mojo_async_await_task (int64_t, int64_t);',
            '/* Awaitable protocol: Future/Event handles */',
            'extern int64_t __mojo_future_new (void);',
            'extern int64_t __mojo_future_done (int64_t);',
            'extern int64_t __mojo_future_result (int64_t);',
            'extern void    __mojo_future_set_result (int64_t, int64_t);',
            'extern void    __mojo_future_set_exception (int64_t, int64_t, char *);',
            'extern int64_t __mojo_future_exception (int64_t);',
            'extern int64_t __mojo_future_cancel (int64_t);',
            'extern int64_t __mojo_future_cancelled (int64_t);',
            'extern int64_t __mojo_future_set_running_or_notify_cancel (int64_t);',
            'extern void    __mojo_future_add_done_callback (int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_future_remove_done_callback (int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_async_await_future (int64_t, int64_t);',
            'extern int64_t __mojo_event_new (void);',
            'extern void    __mojo_event_set (int64_t);',
            'extern int64_t __mojo_event_is_set (int64_t);',
            'extern void    __mojo_event_clear (int64_t);',
            'extern int64_t __mojo_async_await_event_wait (int64_t, int64_t);',
            'extern int64_t __mojo_gen_yield_tagged (int64_t, int64_t, int64_t);',
            'extern int64_t __mojo_gen_last_yield_was_wd (int64_t);',
            # Nested-async mutable closure capture (bugs/hard/CODEGEN_coro_
            # nested_async_closure_capture.md) -- v0 int-literal-local heap
            # box; see gimple_gen_coro.py's _nested_async_capture_plan.
            'extern int64_t __mojo_box_new_i64 (int64_t);',
            'extern int64_t __mojo_box_get_i64 (int64_t);',
            'extern void    __mojo_box_set_i64 (int64_t, int64_t);',
            # Increment C: typed capture-box cells (float / string).
            'extern int64_t __mojo_box_new_d (double);',
            'extern double  __mojo_box_get_d (int64_t);',
            'extern void    __mojo_box_set_d (int64_t, double);',
            'extern int64_t __mojo_box_new_p (char *);',
            'extern char *  __mojo_box_get_p (int64_t);',
            'extern void    __mojo_box_set_p (int64_t, char *);',
          ) if (getattr(self, '_stackswitch_coro_c_units', None)
                or getattr(self, '_native_future_bridge', False)) else ()),
        '/* Disable security wrappers: sprintf/snprintf/memcpy/memmove/memset/',
        '   strcpy/strncpy/strcat/strncat macros expand to nested',
        '   __builtin___*_chk calls which GIMPLE rejects (confirmed for memcpy:',
        '   a bare memcpy(dst, src, n) call expanded to',
        '   __builtin___memcpy_chk(dst, src, n, __builtin_object_size(dst, 0))',
        '   and broke every cold-CAS-cache stdlib build via List[T].extend,',
        '   investigated 2026-07-15 — the other _FORTIFY_SOURCE-wrapped libc',
        '   functions below are the same class of bug, pre-empted before they',
        '   bite the same way). */',
        '#ifdef sprintf',
        '#undef sprintf',
        '#endif',
        '#ifdef snprintf',
        '#undef snprintf',
        '#endif',
        '#ifdef memcpy',
        '#undef memcpy',
        '#endif',
        '#ifdef memmove',
        '#undef memmove',
        '#endif',
        '#ifdef memset',
        '#undef memset',
        '#endif',
        '#ifdef strcpy',
        '#undef strcpy',
        '#endif',
        '#ifdef strncpy',
        '#undef strncpy',
        '#endif',
        '#ifdef strcat',
        '#undef strcat',
        '#endif',
        '#ifdef strncat',
        '#undef strncat',
        '#endif',
        '/* Undefine exception-name macros from fire_runtime.h that clash with',
        '   Mojo struct/class names in generated code. */',
        '#ifdef StopIteration',
        '#undef StopIteration',
        '#endif',
        '#ifdef ValueError',
        '#undef ValueError',
        '#endif',
        '#ifdef TypeError',
        '#undef TypeError',
        '#endif',
        '#ifdef IndexError',
        '#undef IndexError',
        '#endif',
        '#ifdef KeyError',
        '#undef KeyError',
        '#endif',
        '#ifdef NotImplementedError',
        '#undef NotImplementedError',
        '#endif',
        'void mojo_print(char *str);',
    ]
    if self.emit_entry_points:
        for sub_fn in self._sub_toplevels:
            parts.append(f'void {sub_fn}(void);')
        if has_toplevel_code:
            parts.append('void _toplevel(void);')
    else:
        if has_toplevel_code:
            fn_name = _module_toplevel_name(self.module_name)
            parts.append(f'void {fn_name}(void);')
    _local_structs = set(self.struct_field_types.keys())
    _imported_names = set(self.imported_symbols.keys())
    _skip_ctors = _local_structs | _imported_names
    _builtin_ctors = [
        ('String',   'int64_t String(...);'),             # FIXME: should be char *String(void *value) [takes any Python object, returns char *]
        ('Int',      'int64_t Int(...);'),                # FIXME: should be int64_t Int(void *value) [takes any Python object, returns int64_t]
        ('UInt',     'int64_t UInt(...);'),               # FIXME: should be uint64_t UInt(void *value)
        ('Bool',     'int64_t Bool(...);'),               # FIXME: should be _Bool Bool(void *value)
        ('Int8',     'int64_t Int8(...);'),
        ('Int16',    'int64_t Int16(...);'),
        ('Int32',    'int64_t Int32(...);'),
        ('Int64',    'int64_t Int64(...);'),
        ('UInt8',    'int64_t UInt8(...);'),
        ('UInt16',   'int64_t UInt16(...);'),
        ('UInt32',   'int64_t UInt32(...);'),
        ('UInt64',   'int64_t UInt64(...);'),
        ('Float16',  'int64_t Float16(...);'),            # FIXME: should be float16_t Float16(void *value)
        ('BFloat16', 'int64_t BFloat16(...);'),           # FIXME: should be bfloat16_t BFloat16(void *value)
        ('Float32',  'int64_t Float32(...);'),            # FIXME: should be float Float32(void *value)
        ('Float64',  'int64_t Float64(...);'),            # FIXME: should be double Float64(void *value)
        ('Error',    'int64_t Error(...);'),              # FIXME: should be Error *Error(void *value)
    ]
    def _guarded_ctor(name, decl):
        guard = f'_MOJO_CTOR_{name.upper()}'
        stub_guard = _stub_guard_name(name)
        return (f'#ifndef {stub_guard}\n#ifndef {guard}\n#define {guard}\n'
                + (decl + '\n#endif\n#endif'))
    _ctor_lines = [_guarded_ctor(name, decl) for name, decl in _builtin_ctors if name not in _skip_ctors]
    if _ctor_lines:
        parts.append('/* Mojo built-in type constructors */')
        parts.extend(_ctor_lines)
        parts.append('')
    _local_funcs = {s.name for s in stmts
                    if isinstance(s, FunctionDef) and s.name not in _C_RESERVED_FUNCS}
    for _s in stmts:
        if isinstance(_s, StructDef):
            for _m in (_s.methods or []):
                if isinstance(_m, FunctionDef):
                    _local_funcs.add(f'{_s.name}_{_m.name}')
    _local_funcs_renamed = {_safe_name(s.name) for s in stmts if isinstance(s, FunctionDef)}
    _imported_names_renamed = {_safe_name(n) for n in _imported_names}
    _all_defined_funcs = (set(self.func_return_types.keys()) | self._global_inline_defs) - _C_RESERVED_FUNCS
    _skip_util = (_local_structs | _imported_names | _local_funcs | _all_defined_funcs
                  | _local_funcs_renamed | _imported_names_renamed)
    _util_pairs = [
        ('iter',    'int64_t iter(...);'),         # FIXME: should be MojoList *iter(MojoList *obj) [current code boxes pointers as int64_t]; variadic so both int and pointer call sites typecheck
        ('next',    'int64_t next(...);'),           # FIXME: should be MojoList *next(MojoList *it) [current code boxes pointers as int64_t]; variadic so both int and pointer call sites typecheck
        ('swap',    'void swap(...);'),    # FIXME: should be void swap(int64_t *a, int64_t *b) [takes pointer arguments boxed as int64_t]; variadic so both int and pointer call sites typecheck
        ('op',      'int64_t op(...);'),
        ('U128',    'int64_t U128(...);'),
        ('Pointer', '#ifndef _MOJO_POINTER_STRUCT_DEF\nint64_t Pointer(...);\n#endif'),
        ('UnsafePointer',    'int64_t UnsafePointer(...);'),
        ('StringSlice',      'int64_t StringSlice(...);'),
        ('StaticString',     'int64_t StaticString(...);'),
        ('debug_assert',     'void debug_assert(...);'),
        ('__get_mvalue_as_litref', 'int64_t __get_mvalue_as_litref(...);'),
        ('__get_litref_as_mvalue', 'int64_t __get_litref_as_mvalue(...);'),
        ('MojoList_unsafe_ptr',    'int64_t MojoList_unsafe_ptr(...);'),
        ('MojoList_unsafe_get',    'int64_t MojoList_unsafe_get(...);'),
        ('Span_unsafe_ptr',        'int64_t Span_unsafe_ptr(...);'),
        ('Optional',               'int64_t Optional(...);'),
        ('int64_t_init_pointee_move', 'void int64_t_init_pointee_move(...);'),
        ('conforms_to',            '_Bool conforms_to(int64_t a, int64_t b);'),
        ('Codepoint',              'int64_t Codepoint(...);'),
        ('stat_result',            'int64_t stat_result(...);'),
        ('UInt128',                'int64_t UInt128(...);'),
        ('SIMDSize',               'int64_t SIMDSize(...);'),
        ('List',                   'int64_t List(...);'),
        ('MojoDict__reserved',     'int64_t MojoDict__reserved(...);'),
        ('ord',                    'int64_t ord(...);'),         # FIXME: should be int64_t ord(char *c) [takes char * boxed as int64_t]; variadic so both int and pointer call sites typecheck
        ('chr',                    'int64_t chr(...);'),        # FIXME: should be char *chr(int64_t i) [returns char * boxed as int64_t]; variadic so both int and pointer call sites typecheck
        ('sort',                   'void sort(...);'),       # FIXME: should be void sort(MojoList *list) [takes MojoList * boxed as int64_t]; variadic so both int and pointer call sites typecheck
        ('Span_byte_length',       'int64_t Span_byte_length(...);'),
        ('_stat_macos',            'int64_t _stat_macos(...);'),
        ('_getpw_macos',           'int64_t _getpw_macos(...);'),
        ('Passwd',                 'int64_t Passwd(...);'),
        ('create_test_device_context', 'int64_t create_test_device_context(...);'),
        ('check_write_to',         'void check_write_to(...);'),
        ('_unsupported_mma_op',    'void _unsupported_mma_op(...);'),
        ('IntType',                'int64_t IntType(...);'),
        ('Byte',                   'int64_t Byte(...);'),
        ('hash',                   'int64_t hash(...);'),
        ('MojoList___contains__',  'int64_t MojoList___contains__(...);'),
        ('MojoList_get_loaded_kgen_pack', 'int64_t MojoList_get_loaded_kgen_pack(...);'),
        ('_stat_linux_x86',        'int64_t _stat_linux_x86(...);'),
        ('func',                   'int64_t func(...);'),
        ('mojo_getenv',            'int64_t mojo_getenv(...);'),
        ('mojo_atol',              'int64_t mojo_atol(...);'),
        ('mojo_frexp',             'int64_t mojo_frexp(...);'),
        ('mojo_abort',             'void mojo_abort(...);'),
        ('Span_as_bytes',          'int64_t Span_as_bytes(...);'),
        ('Span_get_immutable',     'int64_t Span_get_immutable(...);'),
        ('_Bool___mlir_i1__',      'int64_t _Bool___mlir_i1__(...);'),
        ('sync_parallelize',       'void sync_parallelize(...);'),
        ('main_func',              'void main_func(void);'),
        ('scalar',                 'int64_t scalar(...);'),
        ('Scalar',                 'int64_t Scalar(...);'),
        ('type_of',                'int64_t type_of(...);'),
        ('align_up',               'int64_t align_up(...);'),
        ('align_down',             'int64_t align_down(...);'),
        ('clamp',                  'int64_t clamp(...);'),
        ('serialize',              'void serialize(...);'),
        ('slice',                  'int64_t slice(...);'),
        ('_getpw_linux',           'int64_t _getpw_linux(...);'),
        ('_lstat_macos',           'int64_t _lstat_macos(...);'),
        ('getuid',   'unsigned int getuid (void);'),
        ('getgid',   'unsigned int getgid (void);'),
        ('getpid',   'int getpid (void);'),
        ('getppid',  'int getppid (void);'),
        ('isatty',   'int isatty (int fd);'),
        ('sysconf',  'long sysconf (int name);'),
        ('_log2_ceil',             'int64_t _log2_ceil(...);'),
        ('int64_t_unsafe_value',   'int64_t int64_t_unsafe_value(...);'),
        ('MojoDict_unsafe_ptr',    'int64_t MojoDict_unsafe_ptr(...);'),
        ('_Empty_copy',            'void _Empty_copy(...);'),
        ('_get_global_or_null',    'int64_t _get_global_or_null(...);'),
    ]
    def _guarded_stub(name, decl):
        guard = _stub_guard_name(name)
        return f'#ifndef {guard}\n#define {guard}\n' + (decl + '\n#endif')
    _util_stubs = [_guarded_stub(name, decl) for name, decl in _util_pairs if name not in _skip_util]
    # Explicit accumulation loop, NOT the
    # `[{rt} {fn}(...); for fn, rt in sorted(...)]` comprehension that used
    # to live inline in the `parts.extend` below: the 2-tuple unpack of a
    # dict `.items()` element boxes both slots to int64_t on the
    # self-hosted path, so `rt` (a C TYPE NAME) f-stringed as its POINTER
    # DECIMAL — the emitted prototype was
    # `4370499496 mojo_index(...);` instead of `int64_t mojo_index(...);`
    # (repro: std/test/builtin/test_uint). `_as_str` keeps both as strings.
    _renamed_lines = []
    for _rb_fn, _rb_rt in sorted(self._renamed_builtin_calls.items()):
        _rb_fn = _as_str(_rb_fn)
        _rb_rt = _as_str(_rb_rt)
        if (_rb_fn not in _skip_util and _rb_fn not in _imported_names
                and _rb_fn not in _local_funcs and _rb_fn not in _local_funcs_renamed
                and _rb_fn not in _imported_names_renamed):
            _renamed_lines.append(f'{_rb_rt} {_rb_fn}(...);')
    parts.extend([
        '/* Mojo iterator and utility functions */',
        *_util_stubs,
        '',
        '/* Struct ___new stubs (for Self(...) call sites) */',
        *[f'int64_t {_as_str(s)}___new(...);' for s in sorted(self._self_ctor_stubs)],
        '',
        '/* Renamed C-reserved builtins called without import (e.g. abs→mojo_abs) */',
        *_renamed_lines,
        '',
        '',
        'char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename);',
        # The self-host forward declaration must match the definition's
        # arity or the closure fails with "conflicting types for
        # 'compile_to_gimple'". `auto_gpu` is keyword-with-default at every
        # call site, but a 4th PARAMETER still changes the type.
        'char *compile_to_gimple(char *mojo_src, int do_imports, char *filename, int auto_gpu);',
        'int64_t mojo_open_file(char *path);',
        *([] if ('open' in self.func_return_types or 'open' in self.imported_symbols) else ['void *mojo_open(char *filename, char *mode);']),
        'int64_t int_write (int64_t, char *);',
        'int64_t int_parse_module (int);',
        '#ifndef _MOJO_UNIMPL_STUBS',
        '#define _MOJO_UNIMPL_STUBS',
        'static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }',
        'static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }',
        'static int64_t id (int64_t x) { return x; }',
        '#endif',
    ])

    for _decl in self._link_import_decl_list:
        parts.append(_decl)

    our_mod = self.module_name if len(self.module_name) > 0 else "root"
    if not self.module_name and self._current_filename:
        our_mod = os.path.splitext(os.path.basename(self._current_filename))[0]

    # dict not set: `sorted(all_modules_to_declare)` below drives the
    # `extern struct _<mod>_toplev` block order in a --dump-full closure;
    # self-hosted `sorted(<set>)` sorts boxed str slots by ADDRESS, so the
    # whole block (and everything after it) reshuffled every run.
    all_modules_to_declare = {}

    if our_mod != "root":
        all_modules_to_declare["root"] = True

    # `_mgmod`, NOT `_mgk`: the latter is this function's own
    # `self._multi_kind_globals` local (`_mgk: set = set()`, above), and on the
    # self-hosted compiled path a `for` target REBINDS the slot rather than
    # introducing a new one — so this loop assigned a `char *` module name into
    # a slot the type table had declared `MojoSet *`, and every module of the
    # self-host closure whose globals struct was declared after this point
    # failed gcc with "assignment to 'MojoSet *' from incompatible pointer type
    # 'char *'".
    for _mgmod in self._module_globals:
        all_modules_to_declare[_as_str(_mgmod)] = True

    # Scan `stmts`/`imported_stmts` for `import`/`from ... import` targets
    # through the hoisted `_gmi_scan_import_modules` helper, NOT
    # `for _ms in stmts + (imported_stmts if ... else [])`. That list
    # CONCATENATION result carried a `char *` element type from the left
    # operand, so `_ms` was declared `char *` and `isinstance(_ms,
    # ImportStmt)` constant-folded to FALSE under self-hosting (the
    # static-false `isinstance(<char *>, ...)` guard) — every imported
    # module therefore lost its `struct _<mod>_toplev`/`extern ..._globals`
    # forward declaration, the exact stage1-vs-stage2 `make bootstrap`
    # divergence (`import sys` in t1.mojo missing `_sys_toplev`). A plain
    # unannotated LIST PARAMETER (the helper's `mod_stmts`) binds its loop
    # element as int64_t, for which `isinstance` emits a real
    # `mojo_read_type_tag` check.
    _gmi_scan_import_modules(stmts, all_modules_to_declare)
    if self.do_imports or self.link_imports:
        _gmi_scan_import_modules(imported_stmts, all_modules_to_declare)

    if self._current_filename:
        parts.append(f'#line 1 "{self._current_filename}"')

    if self.emit_struct_defs and hasattr(self, 'struct_field_types') and self.struct_field_types:
        parts.append('')
        emitted = set()
        max_iterations = len(self.struct_field_types) + 1
        iteration = 0
        while emitted != set(self.struct_field_types.keys()) and iteration < max_iterations:
            iteration += 1
            for struct_name in sorted(self.struct_field_types.keys()):
                if struct_name in emitted:
                    continue
                fields = self.struct_field_types[struct_name]
                dependencies_met = True
                for field_type in fields.values():
                    base_type = re.sub(r'\[\d+\]$', '', ('' + field_type).rstrip(' *'))
                    if base_type == struct_name:
                        continue  # Self-reference is OK
                    if base_type in self.struct_field_types and base_type not in emitted:
                        dependencies_met = False
                        break
                if not dependencies_met:
                    continue
                _td_start = len(parts)
                if struct_name == 'Pointer':
                    parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    _td_start = len(parts)
                parts.extend(_render_struct_typedef_body(struct_name, fields))
                self._struct_typedef_texts[struct_name] = '\n'.join(parts[_td_start:])
                parts.append(f"#define {_stub_guard_name(struct_name)}")  # suppress any later variadic stub
                emitted.add(struct_name)
                self._emitted_structs.add(struct_name)  # track for dedup in Section 2
        parts.append('')

    if self._needs_type_name_table and 'type_name_table' not in self._emitted_singletons:
        self._emitted_singletons.add('type_name_table')
        parts.append("static char * _mojo_type_name (int64_t tag)")
        parts.append("{")
        # dict not set: `sorted(<set>)` self-hosted is address order, so the
        # `_mojo_type_name` if-arm sequence reshuffled every --dump-full run.
        _type_name_set = {}
        for _tnk in self.struct_field_types:
            _type_name_set[_as_str(_tnk)] = True
        for _dspk in _STMT_DISPATCH.keys():
            _type_name_set['' + _dspk] = True
        for _dspk in _EXPR_DISPATCH.keys():
            _type_name_set['' + _dspk] = True
        for _tn in sorted(_type_name_set):
            _tn_s = '' + _tn
            parts.append(f"  if (tag == {_struct_type_id(_tn_s)}) return \"{_tn_s}\";")
        parts.append("  return \"<type>\";")
        parts.append("}")
        parts.append('')
    for mod_name in sorted(all_modules_to_declare):
        mod_s = '' + mod_name
        if mod_s == our_mod:
            continue
        mod_str = _as_str(mod_s if mod_s else "root")
        safe_mod = _c_field_name(mod_str) if mod_str else "root"
        struct_name = f"_{safe_mod}_toplev"
        global_var = f"_{safe_mod}_globals"
        _known_fields = self._module_globals.get(mod_str)
        if _known_fields:
            _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_mod}'
            parts.append(f'#ifndef {_toplev_guard}')
            parts.append(f'#define {_toplev_guard}')
            parts.append(f'typedef struct {struct_name} {{')
            for _kf in _known_fields:
                # Index, don't unpack: reading `_kf_ctype`/`_kf_name` out of the
                # 3-tuple re-boxes the str slots to int64_t on the self-hosted
                # path, so the field decl came out `<addr> ANY;` — a live heap
                # pointer as the C type, different every run (only visible in the
                # multi-module `--dump-full` closure, where OTHER modules' toplev
                # structs are emitted). Broke stage2-vs-stage3 bootstrap identity.
                parts.append(f'  {_as_str(_kf[1])} {_c_field_name(_as_str(_kf[0]))};')
            parts.append(f'}} {struct_name};')
            parts.append('#endif')
            parts.append(f'extern struct {struct_name} {global_var};')
        else:
            parts.append(f'struct {struct_name} __attribute__((incomplete));  /* extern module globals struct */')
            parts.append(f'extern struct {struct_name} {global_var};')

    for _decl in self._elaborated_externs:
        parts.append(_decl)

    for _ecname in sorted(self._external_protos):
        if _ecname in self._LIBC_DECLARED and _ecname not in self._NEEDS_SELF_EXTERN:
            continue
        _eret, _eargs = self._external_protos[_ecname]
        # `_eret` is the str return-type, but unpacking it out of the 2-slot
        # tuple re-boxes the slot to int64_t on the self-hosted path -> the
        # decl emitted `extern <decimal-address> chdir (...)`, address-ordered
        # and different every run. `_as_str` re-tags the intact char* bits.
        if _eargs:
            # Plain unpack loop, NOT a list comprehension — see this
            # file's other genexpr/comprehension-join fixes for why.
            _ea_parts = []
            for _ea in _eargs:
                _ea_parts.append(_as_str(_ea))
            _argstr = ', '.join(_ea_parts)
        else:
            _argstr = 'void'
        parts.append(f'extern {_as_str(_eret)} {_ecname} ({_argstr});')

    # Every declaration the reflection block's definitions need, BEFORE the
    # imported modules' code goes in below. That code CALLS those helpers by
    # name from its own function bodies, and C has no two-pass declarations,
    # so a declaration emitted after the splice is an implicit declaration —
    # gcc resolves it to `int`, the returned `char *` is truncated to 32
    # bits, and the self-hosted compiler's own container-of-struct element
    # reprs came out garbage (59 `'_mojo_elem_repr_<Struct>' undeclared`
    # errors on this closure; see `_emit_reflection_fwd_decls`'s own
    # docstring). The `struct_field_types` walk at the top of this function
    # has already run, so `self._emitted_structs` — one of the three inputs
    # to the reflect-struct set — is complete here.
    if self.emit_struct_defs:
        _emit_reflection_fwd_decls(self, parts)

    _module_globals_insert_idx = len(parts)
    if imported_code:
        parts.append('')
        parts.extend(imported_code)

    # `sorted(<set>)` + `_as_str(et)` — a raw `<set> - <set>` difference /
    # bare `for x in <str set>` reads each str slot as a boxed int64_t on
    # the self-hosted path, so `et` came out a decimal-stringified pointer
    # in the emitted `static <ptr> * _mojo_at_<ptr> (...)` (non-deterministic
    # C — a stage2-vs-stage3 idempotency failure).
    # Build a clean, value-deduped, value-SORTED list of element type
    # names first: `sorted(self._ptr_helpers_needed)` alone orders by the
    # boxed pointer VALUE when the set has int-tagged slots (element type
    # erased on the self-hosted path) — non-deterministic run to run. And
    # `_ptr_slot_in_range` drops an entry that is raw garbage rather than
    # a boxed-but-valid string pointer.
    #
    # list<->buffer helpers for exactly the element types some call site or
    # kernel needed. Same value-dedup-then-sort treatment as `_ptr_helpers_`
    # just below, for the same reason: iterating the raw set orders by the
    # boxed pointer VALUE on the self-hosted path, which is non-deterministic
    # run to run and would show up as a stage2-vs-stage3 idempotency failure.
    _lmn: list = []
    for _lm in self._list_marshalling_needed:
        if not _ptr_slot_in_range(_lm):
            continue
        _lm_s = _as_str(_lm)
        if _lm_s and _lm_s not in _lmn:
            _lmn.append(_lm_s)
    # SHARED, like _emitted_ptr_helpers: a pack/unpack pair is per-TU (one
    # definition serves every module and every kernel), so a LOCAL set here
    # emitted one per module and two GPU modules in one translation unit
    # collided -- `redefinition of '_mg_pack_float'`, six such errors, from a
    # two-module program. Same wrong-scope mistake as the introspection
    # sidecar: state whose scope is the translation unit, tracked per module.
    _emitted_list_marshalling = self._emitted_list_marshalling
    for _lm_s in sorted(_lmn):
        if _lm_s in _emitted_list_marshalling:
            continue
        _emitted_list_marshalling.add(_lm_s)
        parts.append(_gmi_device_glue.list_marshalling_definitions([_lm_s]))
    _pth_names: list = []
    for _pth in self._ptr_helpers_needed:
        if not _ptr_slot_in_range(_pth):
            continue
        _pth_s = _as_str(_pth)
        if _pth_s and _pth_s not in _pth_names:
            _pth_names.append(_pth_s)
    _new_helper_count = 0
    for et in sorted(_pth_names):
        if et in self._emitted_ptr_helpers:
            continue
        cn = _c_id(et)
        parts.append(
            f"static {et} * _mojo_at_{cn} ({et} * p, int64_t n) {{ return p + n; }}"
        )
        self._emitted_ptr_helpers.add(et)
        _new_helper_count += 1
    if _new_helper_count > 0:
        parts.append('')

    # `UnsafePointer[T].alloc(n)` — per-element-type heap allocator. Plain
    # C (like `_mojo_at_<T>` just above), so `sizeof(T)` is unrestricted
    # even for a struct T not in any __GIMPLE signature. For a struct
    # element type every slot's leading `__mojo_type_id` header is set so
    # struct-pointer field access keeps working on `.alloc()`'d memory.
    _pan_names: list = []
    for _pan in self._ptr_alloc_n_needed:
        if not _ptr_slot_in_range(_pan):
            continue
        _pan_s = _as_str(_pan)
        if _pan_s and _pan_s not in _pan_names:
            _pan_names.append(_pan_s)
    _new_alloc_n_count = 0
    for et in sorted(_pan_names):
        if et in self._emitted_ptr_alloc_n:
            continue
        self._emitted_ptr_alloc_n.add(et)
        cn = _c_id(et)
        _sn = et[:-2].strip() if et.endswith('*') else et
        if _sn in self.struct_field_types:
            parts.append(
                f"static {et} * _alloc_n_{cn} (int64_t n) {{\n"
                f"  {et} * _p = ({et} *) calloc (n < 1 ? 1 : n, sizeof({et}));\n"
                f"  for (int64_t _i = 0; _i < n; _i++) _p[_i].__mojo_type_id = (int64_t){_struct_type_id(_sn)};\n"
                f"  return _p;\n"
                f"}}"
            )
        else:
            parts.append(
                f"static {et} * _alloc_n_{cn} (int64_t n) {{ return ({et} *) calloc (n < 1 ? 1 : n, sizeof({et})); }}"
            )
        _new_alloc_n_count += 1
    if _new_alloc_n_count > 0:
        parts.append('')

    global_decls = []  # kept for compatibility, but won't be emitted
    _this_mod_inits: dict = {}  # flat {name: init_code} for THIS invocation — see its use below
    current_mod_name = self.module_name if len(self.module_name) > 0 else "root"
    if current_mod_name not in self._module_globals:
        self._module_globals[current_mod_name] = []
        self._module_global_inits[current_mod_name] = {}
    # Set of composite "name\0ctype\0mtype" strings mirroring
    # `_module_globals[mod]`, so the registration loop below can test
    # "already registered" by VALUE. It cannot do that against the tuple
    # list itself once self-hosted: a tuple lowers to a MojoList, so `in`
    # compares handles rather than contents and never matches.
    if getattr(self, '_module_global_names', None) is None:
        self._module_global_names = {}
    if current_mod_name not in self._module_global_names:
        # Seed from whatever is already registered: `_module_globals[mod]`
        # survives across calls on the same generator (the guard above only
        # creates it once), so an empty set here would re-append entries
        # already in that list.
        _seed = set()
        for _e in self._module_globals[current_mod_name]:
            _seed.add(_as_str(_e[0]) + '\x00' + _as_str(_e[1])
                      + '\x00' + _as_str(_e[2]))
        self._module_global_names[current_mod_name] = _seed
    _declared_globals = {}  # dict not set: self-hosted `sorted(<set>)` at the field-order loop below sorts boxed str slots by ADDRESS (nondeterministic _<mod>_toplev field order in --dump-full); dict keys sort by content via mojo_dict_sorted_keys
    all_scan = stmts
    for stmt in all_scan:
        if isinstance(stmt, FromImportStmt):
            # Rebuilt fresh on every iteration of this loop, NOT hoisted
            # above it, and as plain LISTS with a manual membership loop,
            # NOT `set` literals checked with `in`: a `set`/`dict` literal
            # here (whether hoisted above this whole `for stmt in
            # all_scan:` loop or rebuilt fresh per-FromImportStmt — both
            # tried) intermittently (not every run — heap-layout/ASLR-
            # dependent, ~3 times out of 4) came back invalid by the time
            # it was READ, always while compiling module_loader.py
            # (reached partway through fire.py's `--dump-full` transitive
            # closure, i.e. after at least one prior recursive
            # `_compile_imported_module` call — this loop's OTHER branch,
            # `elif isinstance(stmt, ImportStmt)` below, re-enters this
            # very function for a nested import — had already returned).
            # Real memory corruption (`mojo_set_contains_str`/`_str_hash`
            # segfault reading the MojoSet's own bucket array), not a
            # value-correctness issue, and neither hoisting location fixed
            # it — plain lists + `==` sidestep the MojoSet/MojoDict
            # runtime entirely for this specific (tiny, cold) check.
            # Same ONE table (`dispatch_table_global_ctype`, from
            # `mojo.middle.types`), for the same reason: this copy was written
            # before the globals moved out of gimple_codegen.py and had not
            # been updated, so a `from mojo.middle.types import _TYPE_MAP`
            # declared nothing and every read of it failed at C compile time.
            # It needs NO list of its own — not even the dict/set split the
            # two hand-kept lists used to carry, because the type is now the
            # table's answer rather than a property of which list a name was
            # written into.
            # `stmt.name_alias_strs` + `_fi_name`/`_fi_alias`, NOT
            # `stmt.names`/`alias[0]`/`alias[1]` — `FromImportStmt.names`
            # is `list[(str, str|None)]`, and its OWN dataclass docstring
            # (fire_compiler.py) already documents that these tuples "box
            # their str slots to int64_t self-hosted"; `name_alias_strs`
            # (a flat `list[str]` of `"name"`/`"name|alias"` composites,
            # with `_fi_name`/`_fi_alias` as the established accessors —
            # see `_register_sym`'s call above in this same file) is the
            # existing, already-correct workaround. Confirmed via `mojoc
            # fire.py --dump-full`: the OLD `alias[0]`/`alias[1]` pattern
            # (even after `_as_str`-guarding both slots, and after trying
            # both a tuple-literal loop AND a plain list loop over the
            # extracted names) produced a garbage `char *` about 3 times
            # out of 4 runs — `len(alias)` itself came back 5 for a plain
            # `from pathlib import Path` (should be a 2-tuple) — a real
            # self-hosted tuple-representation bug in `stmt.names` itself,
            # not fixable by guarding what's read FROM it.
            for _fip in (getattr(stmt, 'name_alias_strs', None) or []):
                orig_name = gimple_ctypes._fi_name(_fip)
                _alias_local = gimple_ctypes._fi_alias(_fip)
                local_name = _alias_local if _alias_local else orig_name
                _check_names = [orig_name]
                if local_name != orig_name:
                    _check_names.append(local_name)
                for check_name in _check_names:
                    _forced = dispatch_table_global_ctype(check_name)
                    if _forced is not None and check_name not in _declared_globals:
                        # THE TABLE is the answer, by the same helper both
                        # declaration scans use.
                        #
                        # The blanket `MojoDict *` this replaced declared a
                        # frozenset global (`_C_KEYWORDS`, `_C_RESERVED_FUNCS`)
                        # as a dict, and because the answer lands in the SHARED
                        # bare-name-keyed `_global_c_decl_types`,
                        # `_own_overlay_global_ctype`'s rule 1 then made that
                        # FOREIGN answer beat the owning module's own correct
                        # `MojoSet *` — "cannot coerce MojoSet * to MojoDict *
                        # (incompatible container kinds)" for four modules of
                        # the self-host closure.
                        #
                        # THE TABLE, not `_global_var_types`, is the second half
                        # of the same fix: this loop runs BEFORE the
                        # AssignStmt/VarDecl scans below, so whatever it writes
                        # into `_declared_globals` stops them from re-deriving
                        # the name. Preferring the seeded `_global_var_types`
                        # here therefore decided the FIELD for the whole module
                        # — and for an alias RHS (`_BIN_OPS = _GD_BIN_OPS`) the
                        # seeded value is the useless `int64_t` the Phase-1.7
                        # scan could not resolve, so `_mojo_middle_types_toplev`
                        # and `_gimple_codegen_toplev` both declared
                        # `int64_t _BIN_OPS` where the toplevel body then stored
                        # the accessor's real `MojoDict *` ("assignment to
                        # 'int64_t' from 'MojoDict *'", 5 sites). One helper
                        # across this site, the two declaration scans and the
                        # early-cdecl seed is what makes them one answer.
                        _declared_globals[check_name] = True
                        _gmi_declare_table_global(self, check_name, global_decls)
        elif isinstance(stmt, ImportStmt):
            for local_name in gimple_ctypes._import_local_names(stmt):
                if local_name not in _declared_globals:
                    global_decls.append(f"int64_t {local_name};")
                    _declared_globals[local_name] = True
                    self._global_var_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name
                # A plain MODULE-TOP-LEVEL `import X as Y` never reaches
                # `_gen_stmt_ImportStmt` (the only other site that
                # populates `imported_symbols`, see its own docstring) —
                # `gen_module_impl`'s toplevel-statement filter (below,
                # this same file) silently `pass`es every top-level
                # ImportStmt/FromImportStmt node ("Imports processed in
                # pre-pass"), so a top-level import's own alias is left
                # registered only as a bare int64_t global marker here,
                # never as a real module alias — `imported_symbols` stays
                # populated ONLY for a `from X import Y` (a different
                # node type, handled by its own separate pre-pass further
                # up this same function) or an import NESTED inside a
                # function/method body (never filtered, so its own
                # `_gen_stmt_ImportStmt` call fires normally). Any
                # `_lower_MemberExpr`/`_lower_IdentExpr` branch gated on
                # `module_name in gen.imported_symbols` for a plain
                # top-level `import X as Y` alias was therefore silently
                # unreachable — e.g. `lx.Token` (Tools/cases_generator/
                # plexer.py's top-level `Token = lx.Token`, `import lexer
                # as lx`) fell through every module-attribute special
                # case straight to the generic dynamic-dispatch fallback,
                # which raises a genuine (uncaught) runtime
                # `AttributeError: Token` the instant that assignment
                # executes. Mirrors `_gen_stmt_ImportStmt`'s own dict
                # shape exactly; guarded so it never overwrites a
                # richer/already-correct entry (e.g. one a FromImportStmt
                # or nested-body import already set for this exact name).
                # See “COMPILE_FAIL: Tools/cases_generator/parser.py”.
                if local_name not in self.imported_symbols:
                    self.imported_symbols[local_name] = {
                        'module': _tm,
                        'return_type': 'unknown',
                    }
                self._module_alias_names.add(local_name)

    all_global_scan = stmts

    def _gscan_declare_global(gname, value):
        """Infer a global's C type from its assigned RHS `value` and
        append the literal struct-field declaration text to
        `global_decls` (this is the pass that actually determines
        which fields exist on the module's `_<mod>_toplev` struct —
        see `_module_globals` below, built from `_declared_globals`).
        Factored out of the AssignStmt branch so MultiAssignStmt
        (`a = b = expr`) can share the identical logic for every one
        of its targets — mirrors the identical refactor done for the
        separate Phase 1.7 pre-scan above (`_phase17_infer_global_type`)
        for the exact same reason: a chained assignment was invisible
        to THIS scan too, so a global only ever assigned via `a = b =
        expr` (e.g. `Lib/codecs.py`'s `BOM_LE = BOM_UTF16_LE = ...`)
        never got a struct field here at all, even after Phase 1.7
        (elsewhere) learned about it — the two scans must agree on
        which names are real struct fields, or code that resolves a
        name via Phase 1.7's `_global_var_types`/`_global_to_module`
        emits `_<mod>_toplev.NAME` for a field this scan never
        declared, i.e. 'struct _X_toplev has no member named NAME'.

        A name in `self._multi_kind_globals` is left ALONE, and that guard is
        load-bearing rather than an optimisation. This scan runs AFTER the
        `global`-reassignment join (which is the only pass that can see a
        cross-function assignment, so its conclusion is strictly newer), and
        every branch below writes `_global_var_types[gname]` /
        `_global_c_decl_types[gname]` from the MODULE-LEVEL RHS — re-freezing
        the narrow kind the join had just reconciled. The two scans are the
        re-derivation sites the analysis in
        `“COMPILE_FAIL: Mac/BuildScript/build-installer.py”` named, and this
        is the second one; the first (the field-freeze loop's
        `_own_overlay_global_ctype`) already prefers the own-overlay
        conclusion, which only helps once this scan stops overwriting it.
        Real: `FW_VERSION_PREFIX = "--undefined--"` at module level and a list
        at :703 — without the guard the field came out `char *` again and the
        next line's slice of the same name was typed as a string."""
        if gname in getattr(self, '_multi_kind_globals', ()):
            return
        # The dispatch/type-table globals answer from the ONE table, before
        # any RHS-shape row below — see `_gmi_declare_table_global`.
        if _gmi_declare_table_global(self, gname, global_decls):
            return
        if isinstance(value, DictExpr):
            global_decls.append(f"int64_t {gname};  /* MojoDict * */")
            self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoDict *'
        elif isinstance(value, ListExpr) or isinstance(value, TupleExpr):
            # `isinstance(v, ListExpr) or isinstance(v, TupleExpr)`, NOT a
            # 2-tuple isinstance — the tuple form evaluated False on the
            # self-hosted compiled path, so `arr = [1,2,3]` fell through
            # this scan and `_global_c_decl_types` was never set to
            # `int64_t`; the field-freeze loop's fallback then declared it
            # a bare `MojoList *` (array_ops_jit stage1-vs-stage2 parity
            # under MOJO_NO_SHIM=1).
            global_decls.append(f"int64_t {gname};  /* MojoList * */")
            self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoList *'
        elif isinstance(value, SetExpr):
            global_decls.append(f"int64_t {gname};  /* MojoSet * */")
            self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoSet *'
        elif isinstance(value, IntLiteral) or isinstance(value, BoolLiteral):
            global_decls.append(f"int {gname};")
            self._global_var_types[gname] = 'int'
            self._global_c_decl_types[gname] = 'int'
        elif isinstance(value, StringLiteral):
            global_decls.append(f"char * {gname};")
            self._global_var_types[gname] = 'char *'
            self._global_c_decl_types[gname] = 'char *'
        elif isinstance(value, CallExpr):
            if (isinstance(value.func, SubscriptExpr)
                    and isinstance(value.func.obj, IdentExpr)
                    and value.func.obj.name in ('list', 'List', 'dict', 'Dict', 'set', 'Set')):
                # `g_seen: List[Int] = List[Int]()` / plain `g = Dict[K, V]()`
                # — a SUBSCRIPTED generic constructor call. `value.func` here
                # is a SubscriptExpr (`List[Int]`), not a bare IdentExpr, so
                # this shape fell through every branch below to the int64_t/
                # plain-`int` fallback further down, mis-declaring the
                # module-global struct field as scalar `int` instead of the
                # boxed-pointer `int64_t` every write/read site already
                # assumes — a 64-bit pointer written through a 32-bit `int`
                # field truncates to garbage (observed: box.3d game's
                # DYLIB_module_global_list_scratch_segfault.md, EXC_BAD_ACCESS
                # in mojo_list_append_int on a corrupted receiver pointer).
                _ctype = 'MojoDict *' if value.func.obj.name in ('dict', 'Dict') else (
                    'MojoSet *' if value.func.obj.name in ('set', 'Set') else 'MojoList *')
                global_decls.append(f"int64_t {gname};  /* {_ctype} */")
                self._global_var_types[gname] = _ctype
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(value.func, IdentExpr) and value.func.name in self.struct_field_types:
                struct_name = value.func.name
                global_decls.append(f"{struct_name} * {gname};")
                self._global_var_types[gname] = f"{struct_name} *"
                self._global_c_decl_types[gname] = f"{struct_name} *"
            elif isinstance(value.func, IdentExpr):
                ret = self.func_return_types.get(value.func.name, '')
                if ret.endswith(' *'):
                    if ret in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                        # A CONTAINER global is BOXED at the C level
                        # (`int64_t`, semantic type kept in
                        # `_global_var_types`) -- the same convention the
                        # DictExpr/ListExpr/SetExpr rows above follow, and
                        # the one `_lower_IdentExpr`'s global read path
                        # assumes ("globals are stored at C level as
                        # int64_t (boxed pointers) except for char * and
                        # simple int globals"). Declaring the field as a
                        # bare `MojoList *` here made it the ONE container
                        # global with an unboxed field, which only shows up
                        # as an error when something writes it through a
                        # path that boxes: `ownership_check.py`'s
                        # `check_module` has a LOCAL `diags` and a
                        # module-level `diags = check_module(stmts)`, and
                        # the local-vs-global name collision routes the
                        # local's writes to the global field (see
                        # `_gen_stmt_AssignStmt`'s own BUG-2026-018
                        # branch), so the boxed `int64_t` store landed in an
                        # unboxed `MojoList *` field -- a hard
                        # `-Wint-conversion` on four lines.
                        global_decls.append(f"int64_t {gname};  /* {ret} */")
                        self._global_c_decl_types[gname] = 'int64_t'
                    else:
                        global_decls.append(f"{ret} {gname};")
                        self._global_c_decl_types[gname] = ret
                    self._global_var_types[gname] = ret
                else:
                    # Final fallback consults the shared Phase 1.7 RHS-type
                    # table (same consolidation precedent as the MemberExpr
                    # branch just below): it knows the one-char*-arg opaque-
                    # constructor passthrough (`X = Path(some_str)` → the
                    # value IS its char* argument at runtime, see _lower_
                    # opaque_ctor) that would otherwise be mis-declared
                    # int64_t here, and returns int64_t for every shape the
                    # explicit rows above already handled identically.
                    _ivt = _phase17_value_type(value)
                    if _ivt == 'char *':
                        global_decls.append(f"char * {gname};")
                        self._global_var_types[gname] = 'char *'
                        self._global_c_decl_types[gname] = 'char *'
                    else:
                        global_decls.append(f"int64_t {gname};")
                        self._global_var_types[gname] = 'int64_t'
                        self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(value.func, MemberExpr):
                # Consolidated with Phase 1.7's own RHS-type table
                # (`_phase17_value_type`) instead of maintaining a third
                # drifting copy of the same method-call rows: that table
                # already maps read/readline -> char *, readlines ->
                # MojoList *, encode/decode/format -> char * (added when
                # Lib/mailbox.py:32's `linesep = os.linesep.encode(
                # 'ascii')` decl'd int64_t against a char*-producing RHS
                # — a hard whole-program "assignment to 'int64_t' from
                # 'char *'" plus a pointer-stored-as-int64 on every
                # later read), int64_t otherwise. Emission/cdecl side
                # effects here mirror the read/readline and readlines
                # rows verbatim.
                _mvt = _phase17_value_type(value)
                if _mvt in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    global_decls.append(f"int64_t {gname};  /* {_mvt} */")
                    self._global_var_types[gname] = _mvt
                    self._global_c_decl_types[gname] = 'int64_t'
                elif _mvt.endswith(' *') or _mvt == 'char *':
                    global_decls.append(f"{_mvt} {gname};")
                    self._global_var_types[gname] = _mvt
                    self._global_c_decl_types[gname] = _mvt
                else:
                    global_decls.append(f"int64_t {gname};")
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'
        elif (isinstance(value, MemberExpr) and isinstance(value.obj, IdentExpr)
                and value.obj.name in self.imported_symbols
                and self.imported_symbols[value.obj.name].get('module')
                and value.member in self._global_var_types
                and getattr(self, '_global_to_module', {}).get(value.member)
                    == self.imported_symbols[value.obj.name].get('module')):
            _mx_t = self._global_var_types[value.member]
            if _mx_t.endswith(' *'):
                global_decls.append(f"{_mx_t} {gname};")
                self._global_var_types[gname] = _mx_t
                self._global_c_decl_types[gname] = _mx_t
            elif _mx_t == '_Bool':
                global_decls.append(f"int {gname};")
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            else:
                global_decls.append(f"int64_t {gname};")
                self._global_var_types[gname] = 'int64_t'
                self._global_c_decl_types[gname] = 'int64_t'
        else:
            # A dispatch-table global assigned from a non-literal RHS
            # (`_BIN_OPS = _GD_BIN_OPS`, where `_GD_*` are `from
            # generated_dispatch import ... as ...` aliases) was answered at
            # the TOP of this function from the one table, so there is
            # nothing left to special-case here: what remains is the generic
            # `_quick_type` fallback, and it must not see a table name at all
            # (it would rewrite `_global_c_decl_types[gname]` to the boxed
            # `int64_t` that `module_loader`'s `int64_t _C_KEYWORDS` used to
            # disagree with every importer's `MojoSet *`).
            qt = self._quick_type(value) or 'int64_t'
            if qt.endswith(' *') or qt == 'char *':
                global_decls.append(f"{qt} {gname};")
                self._global_var_types[gname] = qt
                self._global_c_decl_types[gname] = (
                    'int64_t' if qt in ('MojoDict *', 'MojoList *', 'MojoSet *')
                    else qt)
            elif qt == '_Bool':
                global_decls.append(f"int {gname};")
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            else:
                global_decls.append(f"int64_t {gname};")
                self._global_var_types[gname] = 'int64_t'
                self._global_c_decl_types[gname] = 'int64_t'

    # `{gname: init_code}` captured at declaration time — the later
    # field-order loop's re-scan for the matching AssignStmt
    # (`_gmi_collect_global_stmts` + `stmt.target.name == gname`) proved
    # unreliable on the self-hosted compiled path, leaving `x = 42` globals
    # at `.x = 0`. Recorded here where `stmt.value` is already in hand.
    _declared_global_inits: dict = {}

    for stmt in _gmi_collect_global_stmts(all_global_scan):
        if isinstance(stmt, VarDecl):
            gname = _as_str(stmt.name)
            if gname in _declared_globals:
                continue
            _declared_globals[gname] = True
            if stmt.value is not None:
                _declared_global_inits[gname] = _gmi_global_init_code(stmt.value)
            # The second of the two declaration scans, and the same table
            # answers here — `funcs_shared.py`'s `_SELFHOST_EXTRA_FIELD_CACHE:
            # dict = {}` is a VarDecl, so a guard only in `_gscan_declare_global`
            # would box its home field `int64_t` while every importer declared
            # the same name `MojoDict *`.
            if _gmi_declare_table_global(self, gname, global_decls):
                continue
            if stmt.type_ann and stmt.value is None:
                _resolved = self._resolve_type(stmt.type_ann)
                self._global_var_types[gname] = _resolved
                if _resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    global_decls.append(f"int64_t {gname};  /* {_resolved} */")
                    self._global_c_decl_types[gname] = 'int64_t'
                else:
                    global_decls.append(f"{_resolved} {gname};")
                    self._global_c_decl_types[gname] = _resolved
                continue
            _gv = stmt.value
            if (isinstance(_gv, CallExpr) and isinstance(_gv.func, SubscriptExpr)
                    and isinstance(_gv.func.obj, IdentExpr)
                    and _gv.func.obj.name in ('list', 'List', 'dict', 'Dict', 'set', 'Set')):
                # `var g_seen: List[Int] = List[Int]()` — same subscripted-
                # generic-constructor gap as `_gscan_declare_global`'s
                # identical new branch above; see that comment for the full
                # root-cause (a 64-bit boxed pointer written through a
                # mis-declared 32-bit `int` struct field truncates to
                # garbage). This VarDecl path is a separate scan that
                # doesn't share code with `_gscan_declare_global`.
                _ctype = 'MojoDict *' if _gv.func.obj.name in ('dict', 'Dict') else (
                    'MojoSet *' if _gv.func.obj.name in ('set', 'Set') else 'MojoList *')
                global_decls.append(f"int64_t {gname};  /* {_ctype} */")
                self._global_var_types[gname] = _ctype
                self._global_c_decl_types[gname] = 'int64_t'
            elif (isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr)
                    and _gv.func.name in ('list', 'List', 'dict', 'Dict', 'set', 'Set')):
                _ctype = 'MojoDict *' if _gv.func.name in ('dict', 'Dict') else (
                    'MojoSet *' if _gv.func.name in ('set', 'Set') else 'MojoList *')
                global_decls.append(f"int64_t {gname};  /* {_ctype} */")
                self._global_var_types[gname] = _ctype
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr):
                if _gv.func.name in self.struct_field_types:
                    _struct_name = _gv.func.name
                    global_decls.append(f"{_struct_name} * {gname};")
                    self._global_var_types[gname] = f"{_struct_name} *"
                    self._global_c_decl_types[gname] = f"{_struct_name} *"
                else:
                    # Mirror _gscan_declare_global's IdentExpr-callee
                    # branch just above: a function whose return type is a
                    # real C pointer (e.g. `create_world() -> World`
                    # lowering to `World *`) must declare the global as
                    # that pointer type. Without this, `var g_world =
                    # create_world()` fell through to the int64_t default
                    # below and the toplevel assignment emitted
                    # `_root_globals.g_world = <World *>;` into a field
                    # declared `int64_t` — "assignment to 'int64_t' from
                    # 'World *'" (box.3d/game's engine_create_world()).
                    _ret = self.func_return_types.get(_gv.func.name, '')
                    if _ret.endswith(' *'):
                        if _ret in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                            # Boxed, for the same reason and with the same
                            # convention as _gscan_declare_global's identical
                            # IdentExpr-callee branch just above.
                            global_decls.append(f"int64_t {gname};  /* {_ret} */")
                            self._global_c_decl_types[gname] = 'int64_t'
                        else:
                            global_decls.append(f"{_ret} {gname};")
                            self._global_c_decl_types[gname] = _ret
                        self._global_var_types[gname] = _ret
                    else:
                        # Same shared-table fallback as _gscan_declare_global's
                        # IdentExpr-callee branch just above: the Phase 1.7
                        # table knows the one-char*-arg opaque-constructor
                        # passthrough (`X = Path(some_str)` → declare char *),
                        # and returns int64_t for every shape this branch's
                        # explicit rows already handled identically.
                        _ivt = _phase17_value_type(_gv)
                        if _ivt == 'char *':
                            global_decls.append(f"char * {gname};")
                            self._global_var_types[gname] = 'char *'
                            self._global_c_decl_types[gname] = 'char *'
                        else:
                            global_decls.append(f"int64_t {gname};")
                            self._global_var_types[gname] = 'int64_t'
                            self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, (IntLiteral, BoolLiteral)):
                global_decls.append(f"int {gname};")
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            elif isinstance(_gv, StringLiteral):
                global_decls.append(f"char * {gname};")
                self._global_var_types[gname] = 'char *'
                self._global_c_decl_types[gname] = 'char *'
            elif isinstance(_gv, (ListExpr, TupleExpr)):
                global_decls.append(f"int64_t {gname};  /* MojoList * */")
                self._global_var_types[gname] = 'MojoList *'
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, DictExpr):
                global_decls.append(f"int64_t {gname};  /* MojoDict * */")
                self._global_var_types[gname] = 'MojoDict *'
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, SetExpr):
                global_decls.append(f"int64_t {gname};  /* MojoSet * */")
                self._global_var_types[gname] = 'MojoSet *'
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, IdentExpr) and _gv.name in self._global_var_types:
                global_decls.append(f"{self._global_var_types[_gv.name]} {gname};")
                self._global_c_decl_types[gname] = self._global_c_decl_types.get(
                    _gv.name, self._global_var_types[_gv.name])
            else:
                global_decls.append(f"int {gname};")
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
        elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
            # `_as_str`: a boxed target name on the self-hosted path becomes a
            # boxed `_declared_globals` / `_global_var_types` key, so the
            # later field-order loop's `_as_str(gname)`-keyed lookups and the
            # init-code re-match (`x = 42` -> `.x = 42`) all miss -> the
            # global static-initialised to 0 (bootstrap_test_single_expr,
            # test_jit) under MOJO_NO_SHIM=1.
            gname = _as_str(stmt.target.name)
            if gname in _declared_globals:
                continue
            _declared_globals[gname] = True
            _gscan_declare_global(gname, stmt.value)
            # Fallback type inference so the two scans agree on which names
            # are real fields (this function's own docstring's requirement).
            # `_gscan_declare_global`'s own `isinstance(value, StringLiteral)`
            # chain can miss self-hosted for a NESTED assignment (one reached
            # through `_gmi_collect_global_stmts`' recursion): the name then
            # lands in `_declared_globals` but NOT in `_global_var_types`, and
            # the field-freeze loop below SKIPS any name missing from the
            # latter — so `y = "a"` inside a top-level `if` got no struct
            # field at all (`char * y` absent from `_root_toplev`), while the
            # shim emitted it.
            if gname not in self._global_var_types:
                _fb_t = _phase17_value_type(stmt.value)
                if _fb_t:
                    self._global_var_types[gname] = _fb_t
                    self._global_c_decl_types[gname] = _fb_t
                    # Own-overlay + owner, exactly like the ImportStmt branch
                    # below: without `_own_global_var_types` the top-level
                    # body still treated the name as a LOCAL (it declared
                    # `char * y;` inside `_toplevel` instead of using the
                    # `_root_globals.y` field the struct now exposes).
                    self._own_global_var_types[gname] = _fb_t
                    if gname not in self._global_to_module:
                        self._global_to_module[gname] = _phase17_mod
            _declared_global_inits[gname] = _gmi_global_init_code(stmt.value)
        elif (isinstance(stmt, ComptimeVarStmt)
                and isinstance(stmt.value, (ListExpr, TupleExpr))):
            gname = _as_str(stmt.target)
            if gname in _declared_globals:
                continue
            _declared_globals[gname] = True
            _gscan_declare_global(gname, stmt.value)
            _declared_global_inits[gname] = _gmi_global_init_code(stmt.value)
        elif isinstance(stmt, MultiAssignStmt):
            for _tgt in stmt.targets:
                if not isinstance(_tgt, IdentExpr):
                    continue
                gname = _as_str(_tgt.name)
                if gname in _declared_globals:
                    continue
                _declared_globals[gname] = True
                _gscan_declare_global(gname, stmt.value)
                _declared_global_inits[gname] = _gmi_global_init_code(stmt.value)
        elif isinstance(stmt, VarDecl) and _as_str(stmt.name) not in _declared_globals:
            _vd_gname = _as_str(stmt.name)
            _declared_globals[_vd_gname] = True
            ctype = self._resolve_type(stmt.type_ann) if stmt.type_ann else 'int64_t'
            global_decls.append(f"{ctype} {_vd_gname};")
            self._global_var_types[_vd_gname] = ctype
            self._global_c_decl_types[_vd_gname] = ctype
        elif isinstance(stmt, ImportStmt):
            for local_name in gimple_ctypes._import_local_names(stmt):
                if local_name not in _declared_globals:
                    _declared_globals[local_name] = True
                    global_decls.append(f"int64_t {local_name};")
                    self._global_var_types[local_name] = 'int64_t'
                    self._global_c_decl_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name

    # Belt-and-braces: a plain top-level `import X` must get an `int64_t X;`
    # backing field on `_<mod>_toplev` so a bare `X` identifier read (or the
    # dead `X.attr` receiver eval) resolves to `_<mod>_globals.X` — exactly
    # what the CPython codegen path emits. The `elif isinstance(stmt,
    # ImportStmt)` branches above were observed NOT to fire on the
    # self-hosted compiled path for some top-level imports (`import sys` in
    # t1.mojo/t_argv.mojo/mojo_main.mojo), so `sys` fell to an inline
    # `(int64_t)0` and the field/accessor went missing — a stage1-vs-stage2
    # parity break under MOJO_NO_SHIM=1. This standalone pass re-scans the
    # raw top-level statements with a single-type isinstance (no elif chain)
    # and fills any gap.
    for _imp_stmt in stmts:
        if not isinstance(_imp_stmt, ImportStmt):
            continue
        for _imp_local in gimple_ctypes._import_local_names(_imp_stmt):
            _imp_local = _as_str(_imp_local)
            if not _imp_local or _imp_local in _declared_globals:
                continue
            _declared_globals[_imp_local] = True
            global_decls.append(f"int64_t {_imp_local};")
            self._global_var_types[_imp_local] = 'int64_t'
            self._global_c_decl_types[_imp_local] = 'int64_t'
            # `_own_global_var_types` too: `_lower_IdentExpr`'s bare-name
            # global-read branch keys "it's our module's global" off this
            # (the shared `_global_to_module` superset can already hold a
            # stale foreign owner for a common name like `sys`), so without
            # it the read still fell to the `(int64_t)0` placeholder.
            self._own_global_var_types[_imp_local] = 'int64_t'
            self._global_to_module[_imp_local] = current_mod_name

    for gname in sorted(_declared_globals):   # dict keys -> content-sorted (deterministic field order); see decl above
        # Defensive: an erased global NAME (self-hosted backend handed back a
        # pointer where a `char *` name was expected) stringifies to a decimal
        # address — `int64_t 50789022240;` is invalid C anyway, and being a
        # live heap address it reshuffles every run. Never emit a struct field
        # whose name isn't a C identifier. (Real cause for `import os`/`ctypes`
        # here still unfound; the marker global is unused so dropping it is
        # harmless — matches the stubbed compiled `os`/`ctypes` behaviour.)
        _gn0 = _as_str(gname)
        if not _gn0 or not (_gn0[0] == '_' or _gn0[0].isalpha()):
            continue
        if gname in self._global_var_types:
            g_mtype = self._global_var_types[gname]
            # Own-overlay first: the field decl must use the SAME
            # resolution the assignment sites use (`_global_dst_ctype` →
            # `_own_overlay_global_ctype`), so a cross-module same-bare-
            # name homonym that polluted the SHARED `_global_c_decl_types`
            # between this module's field-freeze and its body-emission
            # (or vice versa) can never make the two sides disagree (the
            # observed c_analyzer/info.py failure: `UNKNOWN` frozen
            # int64_t here, then a foreign module's string `UNKNOWN`
            # cdecl'd 'char *' into the shared dict, then the assignment
            # coerced its RHS to `char *` against this int64_t field).
            _own_t = self._own_overlay_global_ctype(gname)
            if _own_t is not None:
                c_type = _own_t
            elif gname in self._global_c_decl_types:
                c_type = self._global_c_decl_types[gname]
            elif g_mtype and g_mtype.endswith(' *') \
                    and self._cpp_known_ptr_struct(g_mtype):
                c_type = g_mtype
            elif g_mtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                # Box as `int64_t` at the C struct-field level — the
                # whole-codebase module-global convention. This fallback
                # used to pass the bare container ctype straight through
                # when `_global_c_decl_types` had no entry (e.g. the
                # ListExpr branch above skipped on the compiled path):
                # array_ops_jit's `MojoList * arr` vs stage1's boxed
                # `int64_t arr` under MOJO_NO_SHIM=1.
                c_type = 'int64_t'
            else:
                c_type = 'void *' if (g_mtype and g_mtype.endswith(' *')) else (
                    g_mtype if g_mtype == 'char *' else 'int64_t')
            _gname_s = _as_str(gname)
            # Declaration-time capture wins (see `_declared_global_inits`);
            # the re-scan below is the pre-existing fallback for paths that
            # never populated it.
            init_code = _declared_global_inits.get(_gname_s, '0')
            if init_code == '0':
                for stmt in _gmi_collect_global_stmts(all_global_scan):
                    if (isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr)
                            and _as_str(stmt.target.name) == _gname_s):
                        init_code = _extract_init_expr(stmt.value)
                        break
                    elif (isinstance(stmt, MultiAssignStmt)
                            and any(isinstance(_t, IdentExpr) and _as_str(_t.name) == _gname_s
                                    for _t in stmt.targets)):
                        init_code = _extract_init_expr(stmt.value)
                        break
                    elif isinstance(stmt, ImportStmt) and gname in (
                            (_as_str(_ta) if _as_str(_ta) else _as_str(_tm))
                            for _tm, _ta in _import_targets(stmt)):
                        init_code = '0'
                        break
            # Faithful restoration of this line's ORIGINAL intent —
            # "append unless this exact (name, c_type, g_mtype) triple is
            # already registered" — which self-hosting silently broke: a
            # tuple lowers to a MojoList, so `<tuple> not in <list of
            # tuples>` compares HANDLES, not contents, and a freshly built
            # triple never matches an equal-valued one already in the list.
            #
            # The visible damage: fire_compiler.py has `import sys` at
            # module level AND inside a function, so `sys` registered twice
            # and its own translation unit failed to compile at all with
            # "duplicate member 'sys'" in `struct _root_toplev`.
            #
            # Compared elementwise through `_as_str` so the comparison works
            # on boxed values. Deliberately still keyed on the WHOLE triple,
            # not on the name alone: collapsing per-name looks tidier but
            # drops entries this loop legitimately registers more than once,
            # and that really does lose declarations (`LayoutSolver.STACK`
            # stopped being emitted as a class-attribute global, leaving
            # "'LayoutSolver_STACK' undeclared" behind). Same policy as
            # before, working comparison.
            _mg_seen = self._module_global_names[current_mod_name]
            _mg_key = (_gname_s + '\x00' + _as_str(c_type)
                       + '\x00' + _as_str(g_mtype))
            if _mg_key not in _mg_seen:
                _mg_seen.add(_mg_key)
                # `_gname_s` (the `_as_str`'d name), NOT the raw `gname` from
                # `sorted(_declared_globals)` — a boxed key here is read back
                # later via `inits.get(_as_str(_gt[0]))` in the struct-init
                # emit loop, so a boxed/clean mismatch silently dropped the
                # initializer (`x = 42` -> `.x = 0` under MOJO_NO_SHIM=1).
                self._module_globals[current_mod_name].append((_gname_s, c_type, g_mtype))
                # Flat local dict, NOT the nested
                # `self._module_global_inits[mod][name] = ...` chained
                # subscript-assign — on the self-hosted compiled path the
                # inner-dict handle from `outer[mod]` erased, so the write
                # silently no-op'd and every non-zero initializer was lost
                # (`x = 42` -> `.x = 0` under MOJO_NO_SHIM=1). Kept in sync
                # into the nested attr too (for any cross-invocation read).
                _this_mod_inits[_gname_s] = init_code
                self._module_global_inits[current_mod_name][_gname_s] = init_code
                self._global_to_module[_gname_s] = current_mod_name

    _mg_list = self._module_globals.get(current_mod_name) or []
    # `len(...) > 0`, NOT bare truthiness: the self-hosted compiler's
    # `if <empty MojoList>:` tests the pointer, not the length, so
    # `_module_globals[mod]` (pre-created as `[]`) was truthy and every
    # compiled program got an empty `typedef struct _<mod>_toplev {}` /
    # `_<mod>_globals = {}` block even with no module-level globals.
    if len(_mg_list) > 0:
        globals_list = _mg_list
        current_mod_str = str(current_mod_name) if current_mod_name else "root"
        safe_name = _c_field_name(current_mod_str) if current_mod_str else "root"
        typedef_name = f"_{safe_name}_toplev"

        globals_struct_lines = []
        _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_name}'
        globals_struct_lines.append(f'#ifndef {_toplev_guard}')
        globals_struct_lines.append(f'#define {_toplev_guard}')
        globals_struct_lines.append(f"typedef struct {typedef_name} {{")
        # Index the (gname, c_type, g_mtype) tuples — a `for a, b, _ in list`
        # 3-tuple unpack boxes every slot to int64_t on the self-hosted
        # backend, so `c_type` came out as a stringified pointer decimal
        # (`50764586080 ANY;`) and the whole `_<mod>_toplev` struct failed
        # GCC with "expected specifier-qualifier-list before numeric
        # constant" on the shimless `--dump-full`.
        for _gt in globals_list:
            _gn = _as_str(_gt[0]); _ct = _as_str(_gt[1])
            globals_struct_lines.append(f"  {_ct} {_c_field_name(_gn)};")
        globals_struct_lines.append(f"}} {typedef_name};")
        globals_struct_lines.append('#endif')
        globals_struct_lines.append("")

        instance_name = f"_{safe_name}_globals"
        globals_struct_lines.append(f"struct {typedef_name} {instance_name} = {{")
        inits = self._module_global_inits.get(current_mod_name, {})

        for _gt in globals_list:
            gname = _as_str(_gt[0]); c_type = _as_str(_gt[1])
            init_val = _this_mod_inits.get(gname)
            if init_val is None:
                init_val = inits.get(gname)
            if not init_val or init_val == '0' or 'mojo_' in str(init_val) or 'new' in str(init_val):
                if c_type.endswith(' *'):
                    init_val = f'({c_type})0'
                else:
                    init_val = '0'
            elif init_val.startswith('"') or init_val.startswith("'"):
                if c_type.endswith(' *'):
                    pass
                else:
                    # A POINTER literal initializing a NON-pointer field.
                    # Reachable only for a BOXED global, and the boxing
                    # convention is what makes it reachable at all: a
                    # container global's C field is `int64_t` (see
                    # `_own_overlay_global_ctype`'s container rule and the
                    # DictExpr/ListExpr/SetExpr rows of
                    # `_gscan_declare_global`), and so is a global whose
                    # binding carries values of more than one kind (see the
                    # `_phase17_scan_global_reassignments` driver above).
                    # A module-level string initializer for either is
                    # therefore a `char *` meeting an `int64_t` field:
                    # `initialization of 'long long int' from 'char *' makes
                    # integer from pointer without a cast [-Wint-conversion]`
                    # (Mac/BuildScript/build-installer.py's
                    # `FW_VERSION_PREFIX = "--undefined--"`, whose field
                    # became the box because `parseOptions` later assigns it
                    # a list). Box it the same way every runtime boxing site
                    # does — pointer, then `void *`, then the integer — so
                    # the static initializer is an explicit conversion
                    # rather than an implicit one.
                    init_val = f'(int64_t)(void *){init_val}'
            elif init_val.lstrip('-').isdigit():
                pass
            else:
                if c_type.endswith(' *'):
                    init_val = f'({c_type})0'
                else:
                    init_val = '0'
            globals_struct_lines.append(f"  .{_c_field_name(gname)} = {init_val},")
        globals_struct_lines.append("};")
        globals_struct_lines.append("")

        for _gt in globals_list:
            gname = _as_str(_gt[0]); c_type = _as_str(_gt[1])
            _acc_sym = f'{safe_name}__mojo_global_get_{_c_field_name(gname)}'
            globals_struct_lines.append(
                f'{c_type} {_acc_sym} (void) {{ return {instance_name}.{_c_field_name(gname)}; }}')
        globals_struct_lines.append("")

        insert_idx = _module_globals_insert_idx
        if insert_idx is not None and insert_idx <= len(parts):
            # Rebuild via slice + concat, NOT `parts[i:i] = lines` — the
            # self-hosted compiler has no lowering for a splice-assignment
            # to a list slice, so the module-globals struct/typedef/
            # accessor block was silently dropped from every compiled
            # program with a module-level `var`.
            parts = parts[:insert_idx] + globals_struct_lines + parts[insert_idx:]
        else:
            parts.extend(globals_struct_lines)

    class_attr_decls = []
    class_attr_inits = []
    # The synthetic `class GimpleGen` (self-host bootstrap) rides
    # `_imported_typedef_structs`, not `all_struct_defs` — but its class-body
    # constant tables (`_NO_OVERLOAD_MANGLE`, `BUILTIN_VALUE_MAP`, ...) still
    # need `_classattr_GimpleGen__X` globals + `_mojo_classattr_init` body
    # entries in whichever TU emits them, else `_alloc_GimpleGen`'s seed reads
    # a NULL global. `_class_attrs['GimpleGen']` was populated beside the
    # frozen-sig apply above; fold the synthetic StructDef in here too.
    _cai_structs = list(all_struct_defs)
    _gg_syn = self._selfhost_gimplegen_stmts
    if (_gg_syn is not None and 'GimpleGen' in self._class_attrs
            and not any(isinstance(s, StructDef) and s.name == 'GimpleGen'
                        for s in _cai_structs)):
        _cai_structs.append(_gg_syn)
    for s in _cai_structs:
        if isinstance(s, StructDef):
            class_attrs = self._class_attrs
            _ca_map = class_attrs.get(s.name, {})
            # Index, don't `for aname, mangled in ....items()`: unpacking the
            # 2-tuple re-boxes both str slots to int64_t on the self-hosted
            # path, so `mangled` (the `_classattr_<Struct>__<attr>` global
            # name) became a decimal heap address — `int64_t <addr>;` fields
            # in `_root_toplev` / `<addr> = mojo_set_new();` inits, different
            # every run. Same fix as the `for _aname in sorted(class_attrs)`
            # loop further down this function.
            for aname in _ca_map:
                mangled = _as_str(_ca_map[aname])
                aname = _as_str(aname)
                # Stop at the class's OWN declaration of `aname`, which is the
                # LAST one in the merged `.fields` (see
                # `_own_class_field_index`). Scanning to the first match took
                # the BASE's value for every override. The range is that one
                # index, not "up to it": a range ending at it still `break`s
                # on the inherited declaration earlier in the list.
                _own_idx = _own_class_field_index(s.fields, aname)
                for _pick in range(_own_idx, _own_idx + 1):
                    field = _as_list(s.fields)[_pick]
                    _cfd = _class_field_decl(field)
                    if _cfd is not None and _cfd[0] == aname:
                        v = _cfd[1]
                        ctype = _class_attr_ctype(v)
                        # `_X = frozenset({...})` / `set([...])` / `list((...))`:
                        # the container-constructor call wraps the literal whose
                        # elements we enumerate. Unwrap a single collection-literal
                        # argument so the class-attr set/list is actually populated
                        # (bare `{...}` / `[...]` literals fall through unchanged).
                        _lit_v = v
                        if (isinstance(v, CallExpr) and isinstance(v.func, IdentExpr)
                                and v.func.name in ('frozenset', 'set', 'list', 'tuple')
                                and len(getattr(v, 'args', []) or []) == 1
                                and isinstance(v.args[0], (SetExpr, ListExpr, TupleExpr))):
                            _lit_v = v.args[0]
                        if ctype == 'MojoSet *':
                            _lit_init_lines = [f"  {mangled} = mojo_set_new();"]
                            _set_elts = (_lit_v.elements
                                         if isinstance(_lit_v, (SetExpr, ListExpr, TupleExpr))
                                         else [])
                            for elt in _set_elts:
                                if isinstance(elt, StringLiteral):
                                    _lit_init_lines.append(f'  mojo_set_add_str ({mangled}, "{_c_escape(elt.value)}");')
                                elif isinstance(elt, IntLiteral):
                                    _lit_init_lines.append(f'  mojo_set_add_int ({mangled}, {_signed_int64_c_literal(elt.value)});')
                            class_attr_inits.extend(_lit_init_lines)
                        elif ctype == 'MojoDict *':
                            _di = [f"  {mangled} = mojo_dict_new();"]
                            _pairs = _lit_v.pairs if isinstance(_lit_v, DictExpr) else []
                            _all_str = bool(_pairs) and all(
                                isinstance(k, StringLiteral) and isinstance(vv, StringLiteral)
                                for k, vv in _pairs)
                            # `dict[str, tuple[str, list[str]]]` — the
                            # `_KNOWN_SIGS` / `_LIBC_SIGS` shape: value is
                            # `(ret_ctype, [param_ctype, ...])`. Store each
                            # as a 2-element MojoList `[ret, [params...]]`
                            # so `_KNOWN_SIGS[name][0]` / `[1]` (the exact
                            # tuple-indexing every consumer uses) still
                            # work. Without this the class-attr emitter
                            # left the dict EMPTY on the self-hosted path,
                            # so every `fname in gen._KNOWN_SIGS` missed
                            # and `py_tokenize(src)` / `int_join(...)` /
                            # `Interpreter_execute(...)` lowered arity-/
                            # type-wrong against the runtime header's real
                            # prototype (hard GCC errors on the shimless
                            # per-file `--dump`).
                            _sig_pairs = bool(_pairs) and all(
                                isinstance(k, StringLiteral)
                                and isinstance(vv, TupleExpr)
                                and len(vv.elements) == 2
                                and isinstance(vv.elements[0], StringLiteral)
                                and isinstance(vv.elements[1], (ListExpr, TupleExpr))
                                and all(isinstance(_pe, StringLiteral) for _pe in vv.elements[1].elements)
                                for k, vv in _pairs)
                            if _all_str:
                                for k, vv in _pairs:
                                    _di.append(
                                        f'  mojo_dict_set_str ({mangled}, "{_c_escape(k.value)}", '
                                        f'"{_c_escape(vv.value)}");')
                                self._global_dict_val_types[mangled] = 'char *'
                                class_attr_inits.extend(_di)
                            elif _sig_pairs:
                                _sig_tmp = 0
                                for k, vv in _pairs:
                                    _sig_tmp += 1
                                    _pl = f'{mangled}__pl{_sig_tmp}'
                                    _sl = f'{mangled}__sl{_sig_tmp}'
                                    _di.append(f'  MojoList *{_pl} = mojo_list_new();')
                                    for _pe in vv.elements[1].elements:
                                        _di.append(f'  mojo_list_append_str ({_pl}, "{_c_escape(_pe.value)}");')
                                    _di.append(f'  MojoList *{_sl} = mojo_list_new();')
                                    _di.append(f'  mojo_list_append_str ({_sl}, "{_c_escape(vv.elements[0].value)}");')
                                    _di.append(f'  mojo_list_append_int ({_sl}, (int64_t){_pl});')
                                    _di.append(f'  mojo_dict_set_int ({mangled}, "{_c_escape(k.value)}", (int64_t){_sl});')
                                class_attr_inits.extend(_di)
                            else:
                                class_attr_inits.append(f"  {mangled} = mojo_dict_new();")
                        elif ctype == 'MojoList *':
                            _lit_init_lines = [f"  {mangled} = mojo_list_new();"]
                            _lst_elts = (_lit_v.elements
                                         if isinstance(_lit_v, (ListExpr, TupleExpr, SetExpr))
                                         else [])
                            for elt in _lst_elts:
                                if isinstance(elt, StringLiteral):
                                    _lit_init_lines.append(f'  mojo_list_append_str ({mangled}, "{_c_escape(elt.value)}");')
                                elif isinstance(elt, IntLiteral):
                                    _lit_init_lines.append(f'  mojo_list_append_int ({mangled}, {_signed_int64_c_literal(elt.value)});')
                                else:
                                    _lit_init_lines = None
                                    break
                            if _lit_init_lines is None:
                                class_attr_inits.append(f"  {mangled} = mojo_list_new();")
                            else:
                                class_attr_inits.extend(_lit_init_lines)
                        elif ctype == 'MojoStructFmt *':
                            _sfmt = (v.args[0].value
                                     if (getattr(v, 'args', None)
                                         and isinstance(v.args[0], StringLiteral))
                                     else '')
                            class_attr_inits.append(
                                f'  {mangled} = mojo_struct_new("{_c_escape(_sfmt)}");')
                        elif isinstance(v, StringLiteral):
                            ctype = 'char *'
                            class_attr_inits.append(f'  {mangled} = "{_c_escape(v.value)}";')
                        elif isinstance(v, IntLiteral):
                            ctype = 'int64_t'
                            class_attr_inits.append(f'  {mangled} = {_signed_int64_c_literal(v.value)};')
                        else:
                            ctype = 'int64_t'
                        class_attr_decls.append(f"{ctype} {mangled};")
                        self._global_var_types[mangled] = ctype
                        break
    if class_attr_decls:
        parts.extend(class_attr_decls)
        parts.append('')
    self._class_attr_inits = class_attr_inits

    _funcattr_decls = []
    for _fn_name in sorted(self._func_attrs):
        for _attr in sorted(self._func_attrs[_fn_name]):
            _mangled = self._func_attrs[_fn_name][_attr]
            if _mangled in self._emitted_funcattr_decls:
                continue
            self._emitted_funcattr_decls.add(_mangled)
            _gtype = self._global_var_types.get(_mangled, 'int64_t')
            _funcattr_decls.append(f"static {_gtype} {_mangled};")
    if _funcattr_decls:
        parts.extend(_funcattr_decls)
        parts.append('')

    if self.emit_struct_defs:
        # Two parallel dicts (StructDef by name, field-count by name), NOT
        # one dict of `(StructDef, int)` tuples: the self-hosted compiler
        # does not carry a tuple's slot types through a dict value, so
        # `for sd, _ in track_best.values()` typed `sd` int64_t and every
        # `sd.name` boxed (`typedef struct <pointer-decimal>`). A dict
        # whose values are a plain struct pointer DOES flow the type via
        # `_dict_val_types`.
        track_best = {}
        track_best_fc = {}
        for s in (stmts + self._imported_typedef_structs
                  + (imported_stmts if (self.do_imports or self.link_imports) else [])):
            if isinstance(s, StructDef):
                field_count = len([f for f in s.fields if isinstance(f, VarDecl)])
                if s.name not in track_best or field_count > track_best_fc[s.name]:
                    track_best[s.name] = s
                    track_best_fc[s.name] = field_count

        for sd in track_best.values():
            if sd.name not in self._emitted_structs:
                _td_start = len(parts)
                if sd.name == 'Pointer':
                    parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    _td_start = len(parts)
                parts.append(f"typedef struct {sd.name} {{")
                parts.append(f"  int64_t __mojo_type_id;")
                emitted_fields = set()
                for field in sd.fields:
                    if isinstance(field, VarDecl):
                        if sd.name in self.struct_field_types and field.name in self.struct_field_types[sd.name]:
                            ft = self.struct_field_types[sd.name][field.name]
                        else:
                            ft = self._resolve_type(field.type_ann) if field.type_ann else 'int'
                        safe_fn = _safe_field(field.name)
                        _arr_dm = re.match(r'^(.+)\[(\d+)\]$', ft)
                        if _arr_dm:
                            parts.append(f"  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];")
                        else:
                            parts.append(f"  {ft} {safe_fn};")
                        emitted_fields.add(field.name)
                if sd.name in self.struct_field_types:
                    for field_name, field_type in self.struct_field_types[sd.name].items():
                        if field_name not in emitted_fields:
                            safe_fn = _safe_field(field_name)
                            _arr_dm2 = re.match(r'^(.+)\[(\d+)\]$', field_type)
                            if _arr_dm2:
                                parts.append(f"  {_arr_dm2.group(1)} {safe_fn}[{_arr_dm2.group(2)}];")
                            else:
                                parts.append(f"  {field_type} {safe_fn};")
                parts.append(f"}} {sd.name};")
                self._struct_typedef_texts[sd.name] = '\n'.join(parts[_td_start:])
                parts.append(f"#define {_stub_guard_name(sd.name)}")
                parts.append('')
                self._emitted_structs.add(sd.name)

        for inner_map in self._all_closures.values():
            for ci in inner_map.values():
                if ci.env_struct and ci.env_struct not in self._emitted_structs:
                    parts.append(f"typedef struct {ci.env_struct} {{")
                    for vname, vtype in ci.captures:
                        field_ctype = gimple_ctypes._env_field_ctype(
                            ci, _as_str(vname))
                        parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                    parts.append(f"}} {ci.env_struct};")
                    parts.append('')
                    self._emitted_structs.add(ci.env_struct)
                    # A closure's env is heap-allocated, and `sizeof` is not a
                    # valid GIMPLE operand, so its size accessor is defined
                    # HERE — right after the typedef it needs, and before every
                    # body that allocates one. Registering it at the typedef
                    # rather than at the allocation site matters because the
                    # allocation is emitted from inside a function body (the
                    # lifted closure's own `_alloc_`, or the outer function when
                    # the lambda is beta-reduced inline), where no top-level
                    # definition can be introduced. See
                    # GimpleGen._c_sizeof_helper / _c_helper_def.
                    _env_h = self._c_sizeof_helper(ci.env_struct)
                    _env_hd = self._c_helper_def(_env_h)
                    if _env_hd:
                        parts.append(_env_hd)
                        parts.append('')

        if self._dispatch_solver and len(self._dispatch_tables) > 0:
            for callee_set, dispatch_table in self._dispatch_tables.items():
                if dispatch_table.name not in self._emitted_dispatch_typedefs:
                    typedef = dispatch_table.emit_typedef()
                    if typedef:
                        parts.append(typedef)
                        parts.append('')
                        self._emitted_dispatch_typedefs.add(dispatch_table.name)

    # Filter + `_as_str` BEFORE `sorted()`, not inside the loop: the
    # compiled backend erased `_struct_allocs_needed`'s `set[str]` element
    # type to int64_t, and some entries are genuinely uninitialised heap
    # bytes / NULL (a `MojoSet` slot never stored with the right accessor;
    # see SESSION-19 `T\xf3\xcc0`). `sorted()` lowers to `mojo_list_sorted_
    # str`, whose `strcmp` hits a NULL entry and SEGFAULTs before any
    # per-element `_ptr_slot_in_range` guard in the loop body could skip it
    # — the `mojo_list_sorted_str + 112` crash on `MOJO_NO_SHIM=1 --dump-
    # full fire.py`. Mirror the same pre-sort clean-list pattern already
    # used for `_mojo_at_<T>` emission.
    _sa_names = []
    for _sx in self._struct_allocs_needed:
        if _ptr_slot_in_range(_sx):
            _sa_names.append(_as_str(_sx))
    for _sn_iter in sorted(_sa_names):
        # Fresh `sn` bound via `_as_str`, NOT the raw `for x in sorted(...)`
        # loop variable — that's int64_t on the self-hosted backend, so the
        # `f"static {sn} * __GIMPLE _alloc_{sn}"` f-string concatenated a
        # boxed pointer as a string → `strlen()` on garbage in
        # `mojo_str_cat` (crash-report bt: `mojo_str_cat` ←
        # `gen_module_impl` on a shimless `--dump-full`).
        sn = _as_str(_sn_iter)
        if sn in self._emitted_allocs:
            continue  # already emitted by an imported module
        self._emitted_allocs.add(sn)
        alloc_name = f'_alloc_{sn}'
        if alloc_name not in self.func_return_types:
            self.func_return_types[alloc_name] = f'{sn} *'
        class_attrs = self._class_attrs.get(sn, {})
        field_map = self.struct_field_types.get(sn, {})
        # Explicit loop, NOT `for aname, gname in sorted(class_attrs.items())`
        # in a genexpr: that 2-tuple unpack boxes `aname`/`gname` on the
        # self-hosted backend, so `_safe_field(aname)` / `{gname}` in the
        # f-string ran on garbage → `strlen()` on a bad pointer in
        # `mojo_str_cat` (crash-report bt: `mojo_str_cat` ← `gen_module_impl`
        # on a shimless `--dump-full`).
        _ai_parts = []
        for _aname in sorted(class_attrs):
            _aname = _as_str(_aname)
            _gname = _as_str(class_attrs[_aname])
            if (_aname in field_map
                    and field_map[_aname] == self._global_var_types.get(_gname, field_map[_aname])):
                _ai_parts.append(f"  _p->{_safe_field(_aname)} = {_gname};\n")
        attr_inits = ''.join(_ai_parts)
        # A builtin-`dict` subclass gets its hidden `_data` backing
        # MojoDict allocated here so inherited container ops have real
        # storage to route to (see gen_module_impl's dict-subclass block).
        _is_dict_sub = sn in getattr(self, '_dict_subclass_structs', ())
        _dsub_decls = "  void * _dd;\n" if _is_dict_sub else ""
        # DESIGN.html R3 exception, NOT routed through the chokepoint: raw
        # C source text for a struct allocator function (no `gen`, no
        # per-call-site codegen). Safe by construction, not a guess -
        # `_dd` is the value `mojo_dict_new()` on the line directly above
        # just returned, so its real kind is trivially proven, not
        # inferred.
        _dsub_init = ("  _dd = mojo_dict_new ();\n"
                      f"  _p->_data = (MojoDict *) _dd;\n") if _is_dict_sub else ""
        # `_init_S` puts a block of `sizeof(S)` bytes into the state a fresh
        # instance starts in (zeroed, type tag, class attributes); `_alloc_S`
        # is a heap block plus that; a stack-homed instance (an owned local
        # that never escapes, see emit_infra.maybe_stack_alloc_owned_ctor) is
        # frame storage plus that. One definition of "a new S", two homes.
        # Plain C, not `__GIMPLE`: `sizeof(S)` is not accepted inside a GIMPLE
        # body for a helper that only takes `S *`.
        parts.append(
            f"static void _init_{sn} ({sn} * _p)\n"
            f"{{\n"
            f"{_dsub_decls}"
            f"  memset (_p, 0, sizeof({sn}));\n"
            f"  _p->__mojo_type_id = (int64_t){_struct_type_id(sn)};\n"
            f"{_dsub_init}"
            f"{attr_inits}"
            f"}}"
        )
        parts.append('')
        # Plain-C definition of the size accessor, immediately before its only
        # caller — see GimpleGen._c_sizeof_helper / _c_helper_def.
        _sz_helper = self._c_sizeof_helper(sn)
        _sz_def = self._c_helper_def(_sz_helper)
        if _sz_def:
            parts.append(_sz_def)
        parts.append(
            f"static {sn} * __GIMPLE _alloc_{sn} (void)\n"
            f"{{\n"
            f"  {sn} * _p;\n"
            f"  void * _vp;\n"
            f"  int64_t _vs;\n"
            f"\nbb_2:\n"
            # `sizeof` is not a valid GIMPLE operand, so the size comes from
            # the non-GIMPLE accessor — see GimpleGen._c_sizeof_helper.
            f"  _vs = {self._c_sizeof_helper(sn)} ();\n"
            f"  _vp = malloc (_vs);\n"
            f"  _p = ({sn} *) _vp;\n"
            f"  _init_{sn} (_p);\n"
            f"  return _p;\n"
            f"}}"
        )
        parts.append('')

    if self.emit_struct_defs:
        _emit_reflection_dispatch(self, parts)

    if self.emit_struct_defs:
        parts.append("static void _mojo_classattr_init (void);")
        parts.append('')

    hardcoded = {
        'mojo_print', 'gimple_codegen_compile_to_gimple', 'compile_to_gimple',
        'int_write', 'int_parse_module', 'py_tokenize', 'Parser', 'Interpreter'
    }
    if self.do_imports or self.link_imports:
        inline_defined = set()
        for stmt in (imported_stmts or []):
            if isinstance(stmt, FunctionDef):
                inline_defined.add(stmt.name)
            elif isinstance(stmt, StructDef):
                for m in stmt.methods:
                    inline_defined.add(f"{stmt.name}_{m.name}")
                    inline_defined.add(m.name)
    else:
        inline_defined = set()

    _stub_only_modules = {'jit.arm64', 'jit'}
    _imp_syms = _as_dict(self.imported_symbols)

    def _sn_def_name(_si, _sn):
        """The name this TU's OWN inline definitions use for the symbol
        `imported_symbols` records under `_sn` — the `original_name` for a
        genuine `from M import f as g` alias, else `_sn` itself.

        `inline_defined` is built from the parsed FunctionDef NAMES, so a
        bare-name entry always hits it and an ALIAS entry never did. That
        miss is not cosmetic: the `inline_defined` skip exists precisely
        because a symbol this TU defines must not get a second,
        independently-typed declaration from the text-scan export table,
        and an alias skipped the skip and so emitted one. With an
        unannotated `def` the scan's signature has no parameters
        (`int64_t helper (void)`), so the single-TU output carried a
        forward declaration contradicting the definition compiled a few
        hundred lines below it:
        #
        #   conflicting types for 'helper_mod_helper_9f63a2';
        #     have 'int64_t(void)'
        #   main2.py:4:9: error: too many arguments to function
        #     'helper_mod_helper_9f63a2'; expected 0, have 1
        #
        # for `from helper_mod import helper as h; h(41)`. Same module, same
        # alias, no re-export involved.
        """
        _od = _si.get('original_name')
        if isinstance(_od, str) and _od:
            return _od
        return _sn

    for sym_name in sorted(_imp_syms):
        # `_sn` — a FRESH `_as_str` view (the sorted() loop var is int64_t;
        # reassigning `sym_name` would re-widen it via whole-function
        # unification). The `< 0x10000` skip drops the rare non-pointer
        # garbage key (a small int a mis-scoped writer stored) that would
        # otherwise segfault `_as_str(it)` + `it in <str set>`.
        if not isinstance(sym_name, str) and sym_name < 0x10000:
            continue
        _sn = _as_str(sym_name)
        if _sn in hardcoded:
            continue
        sym_info = _as_dict(_imp_syms[_sn])
        if sym_info.get('return_type') == 'unknown':
            continue
        # The `'signature' not in sym_info` escape hatch is LOAD-BEARING, not
        # an oversight: for a symbol this whole program defines but the module
        # being emitted only IMPORTS, the definition's own forward-declaration
        # pass does not run (it reads `func_defs`, which is `stmts` — the local
        # module — while `inline_defined` is built from `imported_stmts`), so
        # this block is the ONLY declaration of it. Widening the gate to an
        # unconditional skip on `_global_inline_defs` was measured: it removes
        # ~dozens of duplicate externs and then every importer of a
        # cross-module helper loses its declaration —
        #   ast_rewriter.py:61: error: implicit declaration of function
        #   'fire_compiler__as_str_9f63a2'
        #
        # It is also a type-mismatch hazard, because this extern is typed from
        # `module_loader`'s text scan while the definition is typed from the
        # body's own returns, and those are two independent inferences. When
        # they disagree, and this TU contains both, the hard gcc error is
        #   conflicting types for 'build_config_find_gcc'; have 'char *(void)'
        # (the scan defaults an UNANNOTATED `def` to int64_t; the body returns
        # a string). So the scanner must not be able to disagree: a compiler
        # module whose functions are reachable through this path needs real
        # return annotations. That is what build_config.find_gcc/find_gxx now
        # carry, and why
        # CODEGEN_optional_runtime_units_not_linked records the
        # unannotated case as a hazard rather than fixing it here.
        #
        # Separately, and NOT fixed here: the emitting line below guards with
        # `#ifndef {safe}` -- the bare symbol used as a macro name -- and never
        # `#define`s it, so the guard is inert and this block re-emits every
        # extern once per importing module (measured: three copies of
        # build_config's, for fire.py, driver.py and the module itself).
        # Adding the `#define` is not a safe standalone fix, because this block
        # runs first and would win the race to define `_MOJO_STUB_<sym>`,
        # suppressing the definition pass's own declaration.
        if (_sn in inline_defined
                or _sn_def_name(sym_info, _sn) in inline_defined
                or (_sn in self._global_inline_defs and 'signature' not in sym_info)):
            continue
        if _sn in self.struct_field_types:
            continue
        if _sn in self._LIBC_DECLARED and _sn not in _C_RESERVED_FUNCS:
            continue

        module = _as_str(sym_info.get('module', ''))
        if module in _stub_only_modules:
            cname = _safe_name(_as_str(sym_name))
            if cname in self._emitted_unresolved_stub_syms:
                continue
            self._emitted_unresolved_stub_syms.add(cname)
            ret_type = sym_info.get('return_type', 'int64_t')
            ret_type = self._resolve_type(ret_type) if ret_type and ret_type != 'unknown' else 'int'
            if ret_type == 'void':
                body = f'{{ mojo_print ((char *)"{_sn}: unavailable in compiled mode"); }}'
            else:
                body = f'{{ mojo_print ((char *)"{_sn}: unavailable in compiled mode"); return ({ret_type})0; }}'
            _stub_only_guard = _stub_guard_name(cname)
            parts.append(f"#ifndef {_stub_only_guard}\n#define {_stub_only_guard}\n"
                          f"{ret_type} {cname} () {body}  /* stub from {module} */\n#endif")
            continue

        safe = self._func_csym(_as_str(sym_name))
        if 'signature' in sym_info:
            if _sn in _C_RESERVED_FUNCS:
                ret_type = _as_str(sym_info.get('c_return_type')) or _as_str(sym_info.get('return_type', 'int64_t'))
                if ret_type and ret_type != 'unknown' and not any(
                        c in ret_type for c in ('*', ' ', 'int', 'char', 'void', 'float', 'double')):
                    ret_type = self._resolve_type(ret_type)
                elif not ret_type or ret_type == 'unknown':
                    ret_type = 'int64_t'
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")
            else:
                signature = _as_str(sym_info['signature'])
                orig_name = sym_info.get('original_name', _sn)
                if safe != orig_name:
                    signature = gimple_ctypes._replace_first_ident(
                        signature, _as_str(orig_name), safe)
                signature = re.sub(
                    r'\b(inout|borrowed|owned|borrow|out|mut|ref|read|copy|var)\s+(?=\w)',
                    '', signature)
                for _ckw in ('default', 'register', 'auto', 'static', 'extern',
                             'volatile', 'inline'):
                    signature = re.sub(r'\b' + _ckw + r'\b(?=\s*[,)])', f'_kw_{_ckw}', signature)
                parts.append(f"#ifndef {safe}\nextern {signature};  /* from {module} */\n#endif")
        else:
            ret_type = _as_str(sym_info.get('return_type', 'int64_t'))
            ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
            if self.do_imports or self.link_imports:
                if safe in self._emitted_unresolved_stub_syms:
                    continue
                self._emitted_unresolved_stub_syms.add(safe)
                if ret_type == 'void':
                    body = f'{{ mojo_print ((char *)"{_sn}: unavailable in compiled mode"); }}'
                else:
                    body = f'{{ mojo_print ((char *)"{_sn}: unavailable in compiled mode"); return ({ret_type})0; }}'
                _unresolved_guard = _stub_guard_name(safe)
                parts.append(f"#ifndef {_unresolved_guard}\n#define {_unresolved_guard}\n"
                              f"__attribute__((weak)) {ret_type} {safe} (...) {body}  /* stub from {module} */\n#endif")
            else:
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")

    if self.imported_symbols:
        parts.append('')

    # `_as_funcdef_node`, not a bare `s`: `stmts` is a heterogeneous
    # statement list, so its self-hosted element type is opaque int64_t
    # regardless of the isinstance filter — every `fdef.name`/`fdef.body`
    # read below then went through the dynamic getattr path instead of a
    # direct struct-field load. Concretely, `.get(fdef.name, ...)` treated
    # `fdef.name`'s (wrongly int64_t) result as a raw integer needing
    # `mojo_str_from_int()` conversion into a dict key — looking up
    # func_return_types by a stringified ADDRESS ("54073494352") instead
    # of the real name ("make_adder"), always missing and always falling
    # to the 'int64_t' default. A closure-returning function's forward
    # declaration was silently wrong on every compile as a result.
    func_defs = [_as_funcdef_node(s) for s in stmts if isinstance(s, FunctionDef)]
    # `self._generator_api` alone is not covered by `_supported_generators`/
    # `_generator_method_api`: a NESTED `async def` (create_task's
    # wrapper idiom, or the detached-async `var coro = wrapper()` idiom --
    # see CODEGEN_coro_detached_async_take_handle) is
    # deliberately keyed straight into `_generator_api` under its qualified
    # base name (register()'s own comment on why: there's no top-level def
    # with its bare name for `_supported_generators` to skip emitting), so
    # a module containing ONLY a nested async closure and no top-level
    # generator/method previously got no `MojoGenerator` typedef or extern
    # decls for its own trampolines at all — an implicit-declaration
    # compile failure the moment anything (e.g. `_take_handle()`) used the
    # handle outside the enclosing function's own `{base}_start` call.
    if self._supported_generators or self._generator_method_api or self._generator_api:
        parts.append('typedef struct MojoGenerator MojoGenerator;')
        # `self._generator_api: dict[str, dict] = {}` (and `_generator_
        # method_api`'s matching declaration) has a bare `dict` nested-value
        # annotation, not `dict[str, dict[str, str]]` — the same "no nested-
        # value-type hint" gap fixed for `_class_attrs` earlier this
        # session. Confirmed via a real --dump-full fire.py determinism
        # diff: `extern MojoGenerator *55158457152_start (void);` — an
        # erased dict VALUE ('base') printed as a decimal address and
        # spliced directly into a symbol name, invalid C, different every
        # run. `_as_str`-guard the extracted fields at the read site
        # (the dict's own VALUES are a genuinely mixed-type dict —
        # `base`/`value_ctype` are str, `params` is a list — so a single
        # `dict[str, str]` reparameterization wouldn't fit every field).
        for _api in list(self._generator_api.values()) + list(self._generator_method_api.values()):
            _base, _vct = _as_str(_api['base']), _as_str(_api['value_ctype'])
            # Plain unpack loop, NOT a genexpr — a list of string pieces
            # joined via a genexpr is the established self-hosted trap.
            _gp_parts = []
            for _gp in (_api.get('params') or []):
                _gp_parts.append(_as_str(_gp))
            _gptypes = ', '.join(_gp_parts) or 'void'
            parts.append(f"extern MojoGenerator *{_base}_start ({_gptypes});")
            parts.append(f"extern _Bool {_base}_resume (MojoGenerator *);")
            parts.append(f"extern {_vct} {_base}_value (MojoGenerator *);")
            parts.append(f"extern void {_base}_destroy (MojoGenerator *);")
            if _api.get('is_async_gen'):
                parts.append(f"extern _Bool {_base}_last_yield_was_wd (MojoGenerator *);")
        parts.append('')
    if '__mojo_gen_resume_once' in self._funcptr_builtins_needed:
        # "Detached async"'s resume_fn half (bugs/hard/CODEGEN_coro_
        # detached_async_take_handle.md) — a bare `(void *)` cast of this
        # runtime symbol (runtime/mojo_coro_gen.c) is referenced as a
        # function-pointer VALUE (`_coro_resume_fn`'s BUILTIN_VALUE_MAP
        # substitution under MOJO_CORO=stackswitch), which needs a real
        # declaration in scope at that reference — the per-generator
        # `_C_TRAMPOLINE_TMPL` blocks that also declare it live at the
        # BOTTOM of the file, after every ordinary function body (so after
        # this reference), and this symbol has no per-generator dependency
        # of its own. `__mojo_gen_destroy` (the paired destroy_fn half,
        # BUILTIN_VALUE_MAP's `_coro_destroy_fn` substitution) is declared
        # alongside it here too: it was ASSUMED to already be in scope via
        # the `_stackswitch_coro_c_units`-gated extern block above, which
        # is true whenever this TU's OWN top-level generator/async lowers
        # through gimple_gen_coro -- but a module whose ONLY coroutine
        # content is a NESTED async closure (hoisted, e.g. device_context.
        # mojo's enqueue_cpu_function wrapper) can reference `_coro_destroy_
        # fn` as a function-pointer value with `_stackswitch_coro_c_units`
        # still empty, leaving `__mojo_gen_destroy` genuinely undeclared
        # ("did you mean '__mojo_gen_resume_once'?").
        parts.append('extern void __mojo_gen_resume_once (int64_t);')
        if not any('__mojo_gen_destroy' in p for p in parts[:-1]):
            parts.append('extern void __mojo_gen_destroy (int64_t);')
    # AVOID `&` (set intersection) entirely here, rather than continuing to
    # chase its allocation/typing: two attempts (an inline literal, then a
    # named `set[str]`-annotated local) both still crashed identically —
    # SIGSEGV in mojo_set_intersection -> mojo_set_contains_str -> _str_hash
    # on a garbage small address (0x1, then 0x3 on retry) — real, reproduced
    # via lldb with ASLR re-enabled (lldb disables ASLR by default, which is
    # why the first several repro attempts came back clean). Whatever is
    # wrong is specific to a temporary MojoSet*'s lifetime/allocation inside
    # this ~8000-line function, not the element-type annotation. Only two
    # fixed, known string constants are ever checked for membership here —
    # there is no need for a real set or its intersection at all. Plain `in`
    # checks against `_funcptr_builtins_needed` (already a real, working
    # `set[str]`) sidestep the bug entirely.
    _needs_async_runtime_h = bool(
        len(self._supported_async) or len(self._supported_async_closures)
        or len(self._nested_async_api)
        or 'mojo_coro_resume_generic' in self._funcptr_builtins_needed
        or 'mojo_coro_destroy_generic' in self._funcptr_builtins_needed
        # A3 stack-switch "detached async" (bugs/hard/CODEGEN_coro_detached_
        # async_take_handle.md): `external_call["AsyncRT_DeviceContext_
        # enqueueHostFunction(Range)", ...]` is declared ONLY by this header
        # (see _LIBC_DECLARED's matching entries in gimple_codegen.py) — it
        # must be included even when the only coroutines in this TU are
        # stack-switch ones (so `_supported_async`/`_nested_async_api`, the
        # cpp-path's own bookkeeping, are both empty). Both names being
        # `_LIBC_DECLARED` means they're deliberately kept OUT of
        # `_external_protos` (see gimple_gen_exprs.py's `external_call`
        # lowering) — `func_param_types` is the one bookkeeping dict that
        # DOES get populated unconditionally for every external_call name,
        # LIBC-declared or not, so it's the right signal here.
        # Same set-intersection avoidance as the `_funcptr_builtins_needed`
        # checks above — `.keys() & {...}` is the identical crash pattern.
        or 'AsyncRT_DeviceContext_enqueueHostFunction' in self.func_param_types
        or 'AsyncRT_DeviceContext_enqueueHostFunctionRange' in self.func_param_types)
    if _needs_async_runtime_h and not (self._supported_async or self._supported_async_closures
                                        or self._nested_async_api):
        parts.append('typedef struct MojoAsync MojoAsync;')
        parts.append('#include <fire_async_runtime.h>')
        parts.append('')
    if self._supported_async or self._supported_async_closures or self._nested_async_api:
        parts.append('typedef struct MojoAsync MojoAsync;')
        parts.append('#include <fire_async_runtime.h>')
        for _api in list(self._async_api.values()) + list(self._nested_async_api.values()):
            _base, _vct = _api['base'], _api['value_ctype']
            _aptypes = ', '.join(_api.get('params') or []) or 'void'
            parts.append(f"extern MojoAsync *{_base}_start ({_aptypes});")
            parts.append(f"extern _Bool {_base}_is_done (MojoAsync *);")
            parts.append(f"extern {_vct} {_base}_value (MojoAsync *);")
            parts.append(f"extern void {_base}_destroy (MojoAsync *);")
            parts.append(f"extern void {_base}_translate_pending_exc (MojoAsync *);")
        for _api in self._async_closure_api.values():
            _base, _vct = _api['base'], _api['value_ctype']
            _aptypes = ', '.join(_api.get('params') or []) or 'void'
            parts.append(f"extern MojoAsync *{_base}_start ({_aptypes});")
            parts.append(f"extern _Bool {_base}_is_done (MojoAsync *);")
            parts.append(f"extern {_vct} {_base}_value (MojoAsync *);")
            parts.append(f"extern void {_base}_destroy (MojoAsync *);")
            parts.append(f"extern void {_base}_translate_pending_exc (MojoAsync *);")
        parts.append('')
    for fdef in func_defs:
        if fdef.name == 'main':
            continue
        if (fdef.name in self._supported_generators or fdef.name in self._supported_async
                or fdef.name in self._supported_async_gen):
            continue
        if fdef.name in self._unsupported_generator_names:
            continue
        # A DEVICE function has no C definition -- it is MSL in the tail
        # sidecar, entered through `_mg_launch_<name>`. This pass emits each
        # local function's C prototype, and for a device function that
        # prototype describes a symbol nothing ever defines: dead, and
        # actively misleading to a reader, who sees a declaration with real
        # parameter types and no matching body. Its host entry point gets a
        # REAL prototype in the preamble instead (see emit_launch_prototypes).
        if _as_str(fdef.name) in getattr(self, '_device_kernels', ()):
            continue
        ret    = self.func_return_types.get(fdef.name, 'int64_t')
        # This SECOND, later computation of `param_ctypes`/
        # `func_param_types` OVERWRITES the earlier forward-declaration
        # pass's result, so leaving it on a broken pattern silently
        # discards a fix made up there. `gimple_ctypes._params_have_
        # vararg` is safe (see its own docstring); the `pn, pt in
        # fdef.params` loop below is left as a PLAIN unpack, NOT indexed
        # (`fdef.params[_pi][0]`) — that double-subscript form was tried
        # here and is itself broken: confirmed via unescape_c.py's `s`
        # parameter, where `fdef.params[_pi][0]` had a working `==` but a
        # broken `len()` (reported 0 for a real 1-char string), so every
        # `in inferred_params` / `.get(_bare_pn)` dict lookup against it
        # missed even though the plain unpack's `pn` hashes correctly.
        if gimple_ctypes._params_have_vararg(fdef.params):
            param_ctypes = self._signature_ctypes(fdef.params, fdef, sentinel='MojoList *')
            self.func_param_types[fdef.name] = self._signature_ctypes(fdef.params, fdef)
            self._note_vararg_trailing_param_types(fdef)
        else:
            param_ctypes = []
            inferred_params = self._inferred_param_types.get(fdef.name, {}) if hasattr(self, '_inferred_param_types') else {}
            _fd_defaults = getattr(fdef, 'param_defaults', None) or {}
            for pn, pt in (fdef.params or []):
                _bare_pn = pn.lstrip('*')
                _dfl = _fd_defaults.get(_bare_pn)
                if (pt is None and getattr(_dfl, 'is_bytes', False)
                        and isinstance(_dfl, StringLiteral)):
                    # A `b'...'` default is unambiguous `bytes` evidence and
                    # must win over a weak usage-inferred `char *` here too,
                    # so this forward declaration agrees with the definition
                    # (which goes through _param_ctype's own bytes-default
                    # hook). Mismatch → "conflicting types for 'size'".
                    param_ctypes.append('MojoBytes *')
                elif pn in inferred_params:
                    param_ctypes.append(inferred_params[pn])
                else:
                    param_ctypes.append(self._param_ctype(pn, pt, fdef))
            self.func_param_types[fdef.name] = param_ctypes
        ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
        _c_fn_name = self._func_csym(fdef.name)
        _guard_name = _c_fn_name
        stub_guard = _stub_guard_name(_guard_name)
        parts.append(f'#ifndef {stub_guard}')
        parts.append(f"{ret} {_c_fn_name} ({ptypes});")
        parts.append('#endif')

    struct_defs = [s for s in stmts if isinstance(s, StructDef)]
    if not self.do_imports:
        struct_defs += [s for s in (imported_stmts or []) if isinstance(s, StructDef)]
    for sd in struct_defs:
        _moids = self._struct_method_overload_ids(sd)
        # Index loop, NOT `{id(m): oid for m, oid in zip(...)}`: neither
        # `zip()` nor a dict comprehension over it lowers in the self-hosted
        # backend, and `id()` is unreliable there — walk `sd.methods` by
        # position so `_moids` (same length) stays aligned.
        _z8_meths = sd.methods
        for _z8k in range(len(_z8_meths)):
            m = _z8_meths[_z8k]
            if (sd.name, m.name) in self._supported_generator_methods:
                continue
            overload_suffix = _moids[_z8k] if _z8k < len(_moids) else ''
            mangled_name = self._struct_method_csym(sd.name, m.name, overload_suffix)
            ret = (self.func_return_types.get(f"{sd.name}_{m.name}{overload_suffix}")
                   or self.func_return_types.get(f"{sd.name}_{m.name}")
                   or self._resolve_type(m.return_type))
            method_full_name = f"{sd.name}_{m.name}"
            per_overload_params = self.func_param_types.get(mangled_name)
            if per_overload_params is not None:
                param_ctypes = per_overload_params
            elif gimple_ctypes._params_have_vararg(m.params):
                param_ctypes = self._signature_ctypes(m.params, m, sd.name, sentinel='MojoList *')
                self.func_param_types[method_full_name] = self._signature_ctypes(m.params, m, sd.name)
            else:
                param_ctypes = []
                for i, (pname, ptype) in enumerate(m.params):
                    if pname.startswith('**'):
                        continue  # skip **kwargs
                    if pname == 'self':
                        ct = f"{sd.name} *"
                    elif ptype is None and hasattr(self, '_inferred_param_types'):
                        if method_full_name in self._inferred_param_types and pname in self._inferred_param_types[method_full_name]:
                            ct = self._inferred_param_types[method_full_name][pname]
                        else:
                            ct = 'int64_t'
                    else:
                        ct = self._resolve_type(ptype)
                    param_ctypes.append(ct)
            ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
            parts.append(f"{ret} {mangled_name} ({ptypes});")

        _emitted_base: set[str] = set()
        _z9_meths = sd.methods
        for _z9k in range(len(_z9_meths)):
            m = _z9_meths[_z9k]
            if (_moids[_z9k] if _z9k < len(_moids) else ''):  # has an overload suffix
                base_cname = self._struct_method_csym(sd.name, m.name, '')
                if base_cname not in _emitted_base:
                    base_ret = (self.func_return_types.get(f"{sd.name}_{m.name}")
                                or self._resolve_type(m.return_type))
                    parts.append(f"{base_ret} {base_cname} (...);")
                    _emitted_base.add(base_cname)

    if func_defs or struct_defs:
        parts.append('')

    if _is_selfhost_file:
        # Struct methods defined in self-host siblings are emitted via
        # _struct_method_csym, which qualifies the symbol with the DEFINING
        # module's name — fire_compiler_Parser___init__, fire_compiler_
        # Parser_parse_module (Parser defined in fire_compiler.py), and
        # myinterpreter_Interpreter___init__, myinterpreter_Interpreter_
        # execute (Interpreter defined in myinterpreter.py). The forward
        # declarations here must match the qualified definition symbol, not
        # a bare name that disagrees at link time. _struct_method_csym
        # depends on the CURRENT module knowing the struct (via
        # _local_struct_names or _imported_struct_home) — many self-host
        # files don't import Parser/Interpreter, so that lookup returns
        # '' (bare) here. `_selfhost_syms()` uses each entry's known
        # DEFINING module name instead, and is the SAME table the
        # func_return_types/func_param_types seeding above is derived from,
        # so a declaration and the call-site coercion it exists to satisfy
        # cannot disagree (they did once: `Parser__parse_expr` was `int64_t`
        # in the seeding and in gimple_codegen's return-type dict while the
        # definition is `UnaryOp *`, and the mismatch only surfaced as a
        # wall of GCC errors after a full self-host compile). Each entry's
        # own history and rationale lives on `_SELFHOST_SIGS` in
        # gimple_codegen.py.
        for _shn, _shr, _shp in gimple_codegen._selfhost_syms():
            _shparams = ', '.join(_shp)
            if _shn == 'jit_compile_and_execute':
                parts.append(f"{_shr} {_shn} ({_shparams});  /* from fire.py */")
            else:
                parts.append(f"{_shr} {_shn} ({_shparams});")
    parts.append("static int64_t _mojo_dispatch_getattr (void *, char *);")
    parts.append("static void _mojo_dispatch_setattr (void *, char *, int64_t);")
    parts.append("static MojoList * _mojo_dispatch_fields (void *);")
    if self._asdict_dispatch_needed:  # see that flag's own declaration
        parts.append("static MojoDict * _mojo_dispatch_asdict (void *);")
    parts.append("static int _mojo_dispatch_is_dataclass (void *);")
    parts.append("static char * _mojo_dispatch_repr (void *);")
    parts.append("static char * _mojo_repr_list (MojoList *);")
    parts.append("static char * _mojo_repr_dict (MojoDict *);")
    parts.append("static char * _mojo_generic_elem_repr (int64_t);")
    if 'type_name_table' in self._emitted_singletons:
        parts.append("static char * _mojo_type_name (int64_t);")
    parts.append('')

    if not self.emit_struct_defs:
        for inner_map in self._all_closures.values():
            for ci in inner_map.values():
                if ci.env_struct and ci.env_struct not in self._emitted_structs:
                    parts.append(f"typedef struct {ci.env_struct} {{")
                    for vname, vtype in ci.captures:
                        field_ctype = gimple_ctypes._env_field_ctype(
                            ci, _as_str(vname))
                        parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                    parts.append(f"}} {ci.env_struct};")
                    parts.append('')
                    self._emitted_structs.add(ci.env_struct)
                    # See the emit_struct_defs twin above: the size accessor is
                    # defined at the typedef, not at the allocation site.
                    _env_h = self._c_sizeof_helper(ci.env_struct)
                    _env_hd = self._c_helper_def(_env_h)
                    if _env_hd:
                        parts.append(_env_hd)
                        parts.append('')
    # Index-walk both dict levels, NOT `for outer_name, inner_map in
    # self._all_closures.items(): for inner_name, ci in inner_map.items():`
    # — a NESTED `.items()` 2-tuple unpack boxes `ci` itself on the
    # self-hosted path (it's the SECOND unpack target), so `ci.env_struct`
    # read a mis-typed attribute off a boxed handle and the forward-decl
    # `f"{ci.env_struct} * {alloc_fn} (void);"` emitted a few bytes of
    # raw heap garbage instead of the struct name — a hard GCC parse
    # failure on `MOJO_NO_SHIM=1 --dump myinterpreter.py`'s generated
    # .ci (real: `T\xf3\xcc0` in place of a struct name). The sibling
    # typedef-emission loop just above this one avoids the bug by using
    # a single-target `for ci in inner_map.values():` — mirror that here.
    for outer_name in self._all_closures:
        inner_map = self._all_closures[outer_name]
        for inner_name in inner_map:
            ci = inner_map[inner_name]
            if ci.env_struct:
                alloc_fn = f"_alloc_{ci.env_struct}"
                parts.append(f"{ci.env_struct} * {alloc_fn} (void);")
            ret  = ci.inferred_ret if ci.inferred_ret else self.func_return_types.get(ci.lifted_name, 'int64_t')
            if ci.is_re_sub_callback:
                ret = 'char *'
            node = ci.inner_def
            ptypes_list = []
            if ci.env_struct:
                ptypes_list.append(f"{ci.env_struct} *")
            for i, (pn, pt) in enumerate(node.params):
                if ci.is_re_sub_callback and i == 0:
                    ptypes_list.append('char *')
                elif pn in ci.inferred_params:
                    ptypes_list.append(ci.inferred_params[pn])
                else:
                    ptypes_list.append(self._param_ctype(pn, pt, node))
            ptypes = ', '.join(ptypes_list) if ptypes_list else 'void'
            parts.append(f"{ret} {ci.lifted_name} ({ptypes});")
            if ci.is_re_sub_callback:
                static_name = f"_mojo_cb_{ci.lifted_name}"
                parts.append(f"static void * {static_name} = (void *){ci.lifted_name};")
    if self._all_closures:
        parts.append('')

    if self._funcptr_builtins_needed:
        # `sorted(setA - setB)`, NOT `sorted([n for n in setA if n not in
        # setB])`: the plain `for n in <str set>` comprehension lowers to
        # `mojo_set_iter_val_int`, which reads slot.val_i (0 for a string
        # slot) — every name came back empty. `mojo_set_difference` +
        # `mojo_set_sorted` both handle string slots correctly; `_as_str`
        # in the loop below re-views the (still boxed) result elements.
        # `sorted(<plain set>)` then filter — NOT `sorted(<set> - <set>)`:
        # a set DIFFERENCE loses str-slot tracking, so `sorted()` on the
        # result orders by the boxed pointer VALUE (non-deterministic
        # emission order — a stage2-vs-stage3 idempotency failure).
        _new_names = []
        for _fpn in sorted(self._funcptr_builtins_needed):
            _fpn = _as_str(_fpn)
            if _fpn not in self._emitted_funcptr_builtins:
                _new_names.append(_fpn)
        # A SUPPORTED compiled generator has no ordinary C definition
        # under its bare csym (only its `<base>_start/_resume/_value/
        # _destroy` coroutine API), so a plain `(void *)<csym>`
        # initializer referenced an undefined symbol ("symbol(s) not
        # found" at link — test/seq_tests.py's `iterfunc`, itself a
        # generator, collected into a callable table alongside ordinary
        # functions). Point such slots at `<base>_start` instead: real
        # Python's "calling a generator FUNCTION constructs the
        # generator object without running its body", which is exactly
        # what `_start` does.
        def _funcptr_target(c_name):
            for _gfn, _gapi in self._generator_api.items():
                try:
                    if self._func_csym(_gfn) == c_name:
                        return f"{_gapi['base']}_start"
                except Exception:
                    continue
            return c_name
        if _new_names:
            # A target whose bare csym is the program ENTRY-POINT name
            # (`main`) references the generated `int main(int, const
            # char **)` — which is only DEFINED at the very end of this
            # translation unit and never forward-declared (the user's
            # own `def main` was renamed `_gimple_main`; see gimple_gen_
            # funcs.py). A file-scope `(void *)main` initializer there-
            # fore died with "'main' undeclared here (not in a
            # function)" — real: Tools/build/umarshal.py, whose own
            # `def main()` body does `sample2 = main.__code__`.
            # Declare the entrypoint up front so the initializer has a
            # declared identifier; every other funcptr target already
            # gets its ordinary forward declaration from the per-function
            # pass above.
            if 'main' in _new_names:
                parts.append("int main (int argc, const char **argv);")
                parts.append('')
            for c_name in _new_names:
                c_name = _as_str(c_name)   # `_new_names` erases to boxed
                # int64_t under self-compile (a set-of-str's element type
                # doesn't survive `- ` / `sorted`), so `c_name[0]` would
                # index a pointer and the funcptr global was never emitted.
                if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
                    parts.append(f"static void * _funcptr_{c_name} = (void *){_funcptr_target(c_name)};")
                self._emitted_funcptr_builtins.add(c_name)
            parts.append('')

    # `len(...) > 0`, not a bare `and self._dispatch_tables`: in the
    # self-hosted compiler the `and`-chain's TypeLattice.join collapses the
    # `MojoDict *` operand to a boxed int64_t, so the truthiness test became
    # "pointer non-null" and this section (a literal comment line) was
    # emitted for a module with no dispatch tables at all — a byte-parity
    # divergence vs `python3 fire.py --dump`. Same at the typedef site above.
    if self.emit_struct_defs and self._dispatch_solver and len(self._dispatch_tables) > 0:
        parts.append("/* Dispatch table initializations (virtual method tables) */")
        for callee_set, dispatch_table in self._dispatch_tables.items():
            if dispatch_table.name not in self._emitted_dispatch_tables:
                table_init = dispatch_table.emit_table_init()
                if table_init:
                    parts.append(table_init)
                    self._emitted_dispatch_tables.add(dispatch_table.name)
        parts.append('')

    if hasattr(self, '_str_pool') and self._str_pool:
        parts.append("/* String literal globals — array form so address is a compile-time r-value (required by GIMPLE strict mode) */")
        # Sort the FORMATTED lines, not `sorted(items, key=lambda x: x[1])`:
        # the compiled `mojo_dict_items_sorted` ignores a `key=` and orders
        # by the dict KEY (the escaped text), diverging from CPython's
        # sort-by-`_slit_N`. Every line's prefix up to the number is
        # constant and the numbers are the same width, so a plain lexical
        # sort of the whole line is byte-identical to CPython's
        # sort-by-sname and needs no MojoDict iteration-order guarantee.
        if self.emit_str_pool:
            _sp_lines = [f'static char * {sname} = "{escaped}";'
                         for escaped, sname in self._str_pool.items()]
        else:
            # Only the names this module's own emission put in the pool, and
            # only those no earlier module in this TU has already declared.
            # Both filters are needed and they are not the same filter: the
            # pool is SHARED (`temp_gen._str_pool = gen._str_pool`), so an
            # imported module sees every string interned before it — including
            # its importers' and its own — and without `_str_pool_declared`
            # each of them re-declared all of them. Legal C (a file-scope
            # declaration without an initializer is a tentative definition, and
            # any number of those precede the root's one real definition), so
            # this was never a compile error — it was N copies of a line per
            # name, quadratic in the imported-module count, in every .ci this
            # backend writes. See bugs/CODEGEN_inline_import_string_pool_
            # name_collision.md, whose reported `redefinition of '_slit_NNN'`
            # was measured on this tree and does not occur: the pool is shared
            # by construction and only the root emits definitions.
            _sp_lines = [f'static char * {sname};'
                         for escaped, sname in self._str_pool.items()
                         if sname not in self._str_pool_declared]
            for _escaped, _sname in self._str_pool.items():
                self._str_pool_declared.add(_sname)
        for _sp_line in sorted(_sp_lines):
            parts.append(_sp_line)
        parts.append('')
    _regex_new = {p: i for p, i in self._regex_progs.items() if p not in self._regex_progs_defined}
    if _regex_new:
        parts.append("/* Compile-time-compiled regex programs (finditer support) */")
        for pattern, info in _regex_new.items():
            parts.append(info['decls'])
            self._regex_progs_defined.add(pattern)
        parts.append('')
    parts.extend(func_parts)

    if self.emit_struct_defs:
        class_attr_inits = getattr(self, '_class_attr_inits', [])
        parts.append("static void _mojo_classattr_init (void)")
        parts.append("{")
        if class_attr_inits:
            parts.extend(class_attr_inits)
        parts.append("}")
        parts.append('')

    if self._generator_cpp_units:
        cpp_parts = [
            '/* Generated by gimple_codegen.py (Milestone B: C++20-coroutine',
            '   translation of this module\'s supported generator function(s);',
            '   Milestone C step 2 added `yield from`-delegation support;',
            '   Milestone C step 3 added generator METHODS on structs;',
            '   Milestone D added try/except/raise support;',
            '   Step B (async/await project) added compiled `async def`',
            '   functions -- a separate promise_type/extern "C" API from the',
            '   generator one above, deliberately not sharing a promise shape',
            '   -- see GimpleGen._gen_cpp_async_unit\'s docstring) */',
            '#include <coroutine>',
            '#include <cstdint>',
            '#include <cstdio>',
            '#include <cmath>',
            '#include <exception>',
            '#include <functional>',
            '#include <vector>',
            '#include <algorithm>',
            '#include <fire_runtime.h>',
            '',
            'extern "C" { typedef struct MojoGenerator MojoGenerator; }',
            'extern "C" { typedef struct MojoAsync MojoAsync; }',
            '',
            '/* Milestone D: RAII `finally:` translation (see',
            '   GimpleGen._cpp_try_stmt) -- runs an arbitrary capturing',
            '   lambda from its destructor, so it fires on every way its',
            '   enclosing scope can be exited (normal fallthrough, break/',
            '   continue, co_return, an exception unwinding through/past it,',
            '   or -- same C++20 coroutine-frame-destruction rule as',
            '   `_mojogen_sub_guard` below -- this coroutine being destroyed',
            '   early while suspended inside the guarded scope). A capturing',
            '   lambda (not a local class) specifically: a local class\'s own',
            '   member functions have NO implicit access to the enclosing',
            '   function\'s locals, so a finally body referencing an outer',
            '   variable wouldn\'t compile with that approach. */',
            'struct _MojoScopeExit {',
            '    std::function<void()> fn;',
            '    explicit _MojoScopeExit(std::function<void()> f) : fn(std::move(f)) {}',
            '    ~_MojoScopeExit() { fn(); }',
            '};',
            '',
            '/* Milestone D: a Mojo exception thrown as a real C++ exception,',
            '   confined to this coroutine\'s own .cpp translation unit (see',
            '   GimpleGen._cpp_raise_stmt/_cpp_try_stmt). Carries exactly the',
            '   same tri-part representation the ordinary (non-generator) GIMPLE',
            '   path already uses for its mojo_exc_type/msg/obj globals (see',
            '   fire_runtime.h) -- reused, not reinvented, so the extern "C"',
            '   `_resume` boundary below can translate one directly into the',
            '   other with no lossy conversion. */',
            'struct _MojoCppExc {',
            '    int64_t type_id;',
            '    char *msg;',
            '    void *obj;',
            '};',
            '',
            '/* RAII guard for a sub-generator a `yield from` delegates to (see',
            '   GimpleGen._cpp_yield_from) -- guarantees the sub-generator\'s own',
            '   `_destroy` runs exactly once, whether this scope exits because the',
            '   sub-generator was exhausted normally or because the OUTER coroutine',
            '   holding it is itself destroyed early (e.g. a consumer `break`s out',
            '   of the loop that\'s driving it): C++20 destroys every local object',
            '   in scope at a coroutine\'s suspension point when that coroutine\'s',
            '   frame is destroyed, exactly as if the enclosing block unwound',
            '   normally, so this destructor fires correctly in both cases with no',
            '   special-case code at either call site. Emitted unconditionally',
            '   whenever this module has ANY compiled generator -- harmless and',
            '   unused if none of them actually use `yield from`. */',
            'struct _mojogen_sub_guard {',
            '    MojoGenerator *g;',
            '    void (*destroy_fn)(MojoGenerator *);',
            '    ~_mojogen_sub_guard() { if (g) destroy_fn(g); }',
            '};',
            '',
        ]
        if (self._supported_async or self._supported_async_gen
                or self._supported_async_closures or self._nested_async_api):
            cpp_parts.append('#include <fire_async_runtime.h>')
            cpp_parts.append('#include <unistd.h>')
            cpp_parts.append('')
            cpp_parts.append('struct _mojoasync_SleepAwaiter {')
            cpp_parts.append('    uint64_t delay_ns;')
            cpp_parts.append('    bool await_ready() const { return false; }')
            cpp_parts.append('    void await_suspend(std::coroutine_handle<> h) const {')
            cpp_parts.append('        mojo_async_schedule_timer(h.address(), mojo_async_now_ns() + delay_ns);')
            cpp_parts.append('    }')
            cpp_parts.append('    void await_resume() const {}')
            cpp_parts.append('};')
            cpp_parts.append('')
            cpp_parts.append('struct _mojoasync_SockRecvAwaiter {')
            cpp_parts.append('    int fd;')
            cpp_parts.append('    bool await_ready() const { return false; }')
            cpp_parts.append('    void await_suspend(std::coroutine_handle<> h) const {')
            cpp_parts.append('        mojo_async_register_read(fd, h.address());')
            cpp_parts.append('    }')
            cpp_parts.append('    int64_t await_resume() const {')
            cpp_parts.append('        unsigned char c;')
            cpp_parts.append('        ssize_t n = ::read(fd, &c, 1);')
            cpp_parts.append('        if (n == 1) return (int64_t)c;')
            cpp_parts.append('        if (n == 0) return (int64_t)-1;')
            cpp_parts.append('        return (int64_t)-2;')
            cpp_parts.append('    }')
            cpp_parts.append('};')
            cpp_parts.append('')
        if (self._supported_generator_methods or self._cpp_param_struct_names
                or self._cpp_ctor_struct_names or self._cpp_value_struct_names):
            cpp_parts.append('/* Struct layout(s) needed by this module\'s')
            cpp_parts.append('   compiled generator method(s) -- verbatim copy of')
            cpp_parts.append('   the same typedef(s) emitted into the .c/.ci output. */')
            _gm_struct_names_seen: list = []
            for _gm_struct_method_key in self._supported_generator_methods:
                _gm_sname2 = _gm_struct_method_key[0]
                if _gm_sname2 not in _gm_struct_names_seen:
                    _gm_struct_names_seen.append(_gm_sname2)
            for _gm_sname3 in self._cpp_param_struct_names:
                if _gm_sname3 not in _gm_struct_names_seen:
                    _gm_struct_names_seen.append(_gm_sname3)
            for _gm_sname4 in self._cpp_ctor_struct_names:
                if _gm_sname4 not in _gm_struct_names_seen:
                    _gm_struct_names_seen.append(_gm_sname4)
            for _gm_sname5 in self._cpp_value_struct_names:
                if _gm_sname5 not in _gm_struct_names_seen:
                    _gm_struct_names_seen.append(_gm_sname5)
            _gm_frontier = list(_gm_struct_names_seen)
            while _gm_frontier:
                _gm_cur = _gm_frontier.pop()
                for _gm_fct in self.struct_field_types.get(_gm_cur, {}).values():
                    if isinstance(_gm_fct, str) and _gm_fct.endswith(' *'):
                        _gm_fld_sn = _gm_fct[:-2]
                        if (_gm_fld_sn in self.struct_field_types
                                and _gm_fld_sn not in _gm_struct_names_seen):
                            _gm_struct_names_seen.append(_gm_fld_sn)
                            _gm_frontier.append(_gm_fld_sn)
            # A struct referenced only from a module compiled with
            # emit_struct_defs=False (e.g. a transitively-imported
            # sibling's own top-level generator, compiled standalone via
            # _compile_imported_module -> _compile_link_inline_cpp_unit —
            # see “COMPILE_FAIL: Tools/cases_generator/parser.py”) never
            # populated THIS gen's own `_struct_typedef_texts` (that dict
            # is per-instance, only ever filled by the emit_struct_defs=
            # True pass above, which such a temp_gen never runs) even
            # though `struct_field_types` — shared by reference across
            # every nested temp_gen — already has its fully-resolved
            # field layout. Synthesize the typedef text on demand from
            # that shared, always-available source instead of silently
            # omitting the struct (leaving `Token * v` etc. referencing
            # an undeclared type — a real g++ hard-fail, not merely a
            # cosmetic gap) whenever the cached text isn't there yet.
            def _gm_typedef_text(_sn):
                _cached = self._struct_typedef_texts.get(_sn)
                if _cached:
                    return _cached
                _flds = self.struct_field_types.get(_sn)
                if _flds is None:
                    return None
                return '\n'.join(_render_struct_typedef_body(_sn, _flds))
            for _gm_fwd_sn in sorted(_gm_struct_names_seen):
                if _gm_typedef_text(_gm_fwd_sn) is not None:
                    cpp_parts.append(f'struct {_gm_fwd_sn};')
            if any(_gm_typedef_text(_fwd) is not None for _fwd in _gm_struct_names_seen):
                cpp_parts.append('')
            for _gm_method_struct_name in sorted(_gm_struct_names_seen):
                _td = _gm_typedef_text(_gm_method_struct_name)
                if _td:
                    cpp_parts.append(_td.replace('_Bool', 'bool'))
                    cpp_parts.append('')
            # Remember which struct typedefs this preamble now defines, so
            # the module-globals mirror block below can tell a nameable
            # type from one it must box.
            _cpp_preamble_typedef_structs = set(
                _sn2 for _sn2 in _gm_struct_names_seen
                if _gm_typedef_text(_sn2) is not None)
        else:
            _cpp_preamble_typedef_structs = set()
        if self._cpp_module_global_refs or self._cpp_module_func_refs:
            cpp_parts.append('/* Extern declarations for module-level symbols')
            cpp_parts.append('   referenced by this module\'s compiled generator')
            cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
            _mref_modules: list = []
            for _mref_pair in self._cpp_module_global_refs:
                _mref_mod = _mref_pair[0]
                if _mref_mod not in _mref_modules:
                    _mref_modules.append(_mref_mod)
            for _mref_mod in sorted(_mref_modules):
                # The refs carry the module's RAW `_module_globals` key,
                # because that is what the field rows below are looked up
                # by; the SYMBOL names need the sanitized spelling, because
                # a relative-import module name (`_.foreign`, from
                # `from . import foreign`) is not a legal C identifier.
                # Registering the sanitized spelling instead found no rows
                # for any dotted module and emitted an EMPTY mirror struct,
                # so every field read through it was a hard g++ error.
                _mref_safe_mod = _c_field_name(_mref_mod)
                _mt = f"_{_mref_safe_mod}_toplev"
                _mg = f"_{_mref_safe_mod}_globals"
                # A mirror field typed `SomeStruct *` is only emittable if
                # g++ can NAME SomeStruct in this translation unit. The
                # typedef BFS above only pulls structs generator bodies
                # actually reach (self/params/ctors/yields), so a global
                # whose inferred type is a struct pointer NO generator
                # touches (real: Lib/typing.py's `ByteString`/
                # `_lazy_annotationlib`/`_sentinel`, typed
                # `_DeprecatedGenericAlias *` etc. by the ordinary
                # constructor-call rule) used to be copied verbatim into
                # this mirror — "'_DeprecatedGenericAlias' does not name
                # a type", 5 hard g++ errors. Fix: (a) when SomeStruct's
                # fully-resolved layout is available in
                # struct_field_types, emit its forward decl + full
                # typedef here too (deduped against what the BFS block
                # already emitted); (b) when it is NOT available, box
                # THIS mirror's field to int64_t — layout-identical on
                # every supported ABI (both 8 bytes / 8-aligned), and
                # this TU never dereferences such a field anyway (the
                # .ci side owns the real typed accesses).
                _mirror_extra_structs: list = []
                for _gl in self._module_globals.get(
                        'root' if _mref_mod == 'root' else _mref_mod, []):
                    _mdm = re.match(r'^(\w+) \*$', _gl[1])
                    if not _mdm:
                        continue
                    _msn = _mdm.group(1)
                    if (_msn in _cpp_preamble_typedef_structs
                            or _msn not in self.struct_field_types
                            or _msn in _mirror_extra_structs):
                        continue
                    _mirror_extra_structs.append(_msn)
                # Transitive closure over field-typed struct pointers,
                # same as the generator-body BFS above: a typedef emitted
                # here may itself reference further struct-pointer fields,
                # each of which needs at least a forward declaration by
                # the time its referrer is parsed.
                _mirror_frontier = list(_mirror_extra_structs)
                while _mirror_frontier:
                    _mf_cur = _mirror_frontier.pop()
                    for _mf_fct in self.struct_field_types.get(_mf_cur, {}).values():
                        if isinstance(_mf_fct, str) and _mf_fct.endswith(' *'):
                            _mf_sn = _mf_fct[:-2]
                            if (_mf_sn in self.struct_field_types
                                    and _mf_sn not in _cpp_preamble_typedef_structs
                                    and _mf_sn not in _mirror_extra_structs):
                                _mirror_extra_structs.append(_mf_sn)
                                _mirror_frontier.append(_mf_sn)
                if _mirror_extra_structs:
                    cpp_parts.append('/* Struct layouts needed only by the')
                    cpp_parts.append('   module-globals mirror below. */')
                    for _me_sn in sorted(_mirror_extra_structs):
                        cpp_parts.append(f'struct {_me_sn};')
                    cpp_parts.append('')
                    for _me_sn in sorted(_mirror_extra_structs):
                        _me_flds = self.struct_field_types.get(_me_sn, {})
                        _me_td = '\n'.join(
                            _render_struct_typedef_body(_me_sn, _me_flds))
                        cpp_parts.append(_me_td.replace('_Bool', 'bool'))
                        cpp_parts.append('')
                    _cpp_preamble_typedef_structs.update(_mirror_extra_structs)
                cpp_parts.append(f'typedef struct {_mt} {{')
                for _gl in self._module_globals.get(
                        'root' if _mref_mod == 'root' else _mref_mod, []):
                    _gct = _as_str(_gl[1]).replace('_Bool', 'bool')
                    _gfname = _c_field_name(_as_str(_gl[0]))
                    if _gfname in _CPP_KEYWORD_FIELDS:
                        _gfname = f"_kw_{_gfname}"
                    cpp_parts.append(f'  {_gct} {_gfname};')
                cpp_parts.append(f'}} {_mt};')
                cpp_parts.append(f'extern struct {_mt} {_mg};')
            for _fname in sorted(self._cpp_module_func_refs):
                try:
                    _fsym = self._func_csym(_fname)
                    _fret = self.func_return_types.get(_fname, 'int64_t')
                    _fparams = self.func_param_types.get(_fname, [])
                    _fret_cpp = _fret.replace('_Bool', 'bool')
                    _fparam_str = ', '.join(
                        p if p not in ('_Bool',) else 'bool' for p in _fparams)
                    cpp_parts.append(
                        f'extern "C" {_fret_cpp} {_fsym} '
                        f'({_fparam_str});')
                except Exception:
                    continue
            for _vfn in sorted(self._cpp_module_variadic_func_refs):
                cpp_parts.append(f'extern "C" int64_t {_vfn} (...);')
            cpp_parts.append('')
        if self._cpp_libc_sig_refs:
            cpp_parts.append('/* Self-emitted extern "C" prototypes for C-stdlib /')
            cpp_parts.append('   POSIX functions called from this module\'s compiled')
            cpp_parts.append('   generator bodies (headers not in the prelude). */')
            for _lname in sorted(self._cpp_libc_sig_refs):
                _lret, _lparams = self._LIBC_SIGS[_lname]
                _lret_cpp = _lret.replace('_Bool', 'bool')
                _lparam_str = ', '.join(
                    p if p != '_Bool' else 'bool' for p in _lparams) or 'void'
                cpp_parts.append(
                    f'extern "C" {_lret_cpp} {_lname} ({_lparam_str});')
            cpp_parts.append('')
        if self._cpp_class_attr_refs:
            cpp_parts.append('/* Extern declarations for class-level')
            cpp_parts.append('   attribute globals (`cls.<attr>`) read by this')
            cpp_parts.append('   module\'s compiled generator bodies. */')
            for _cattr_gname in sorted(self._cpp_class_attr_refs):
                _cattr_ctype = self._global_var_types.get(_cattr_gname, 'int64_t')
                _cattr_ctype = _cattr_ctype.replace('_Bool', 'bool')
                cpp_parts.append(f'extern {_cattr_ctype} {_cattr_gname};')
            cpp_parts.append('')
        if self._cpp_struct_method_refs:
            cpp_parts.append('/* Extern declarations for struct methods')
            cpp_parts.append('   called from this module\'s compiled generator')
            cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
            for _sm_struct, _sm_method in sorted(self._cpp_struct_method_refs):
                try:
                    _smsym = self._struct_method_csym(_sm_struct, _sm_method, '')
                    _smkey = f"{_sm_struct}_{_safe_name(_sm_method)}"
                    _smret = self.func_return_types.get(
                        _smsym, self.func_return_types.get(_smkey, 'int64_t'))
                    # An INHERITED method — one never defined on this struct
                    # or anywhere else in this compile (its real home is a
                    # base class this codegen could not resolve to a
                    # StructDef at all, e.g. `unittest.TestCase`) — has no
                    # recorded signature under either key. The old
                    # `[f"{_sm_struct} *"]` fallback declared it
                    # `(self *)`-only, so any call passing the receiver
                    # PLUS arguments (test_random_things.py's generator
                    # body calling the inherited
                    # `self.assertEqual(a, b)`) failed g++ with "too many
                    # arguments" — a hard compile error for what is by
                    # construction an unresolvable-at-compile-time symbol.
                    # Mirror the two existing conventions for exactly this
                    # shape instead of guessing a fixed arity: (1) declare
                    # the extern C-VARIADIC with a named receiver —
                    # `extern "C" T Sym (Struct *, ...);` — matching
                    # `_cpp_module_variadic_func_refs`'s variadic-extern
                    # treatment of unresolved free functions; and (2)
                    # pair that declaration with a real, WEAKLY-defined,
                    # arity-agnostic stub body in THIS SAME translation
                    # unit (`__attribute__((weak)) ... { mojo_print(...);
                    # return 0; }`), so both sides of the link always
                    # agree even when no other TU defines the symbol —
                    # the identical mechanism `_lower_struct_method_call`'s
                    # own auto-stub path already uses for inherited-method
                    # calls from ORDINARY (non-generator) function bodies
                    # (gimple_gen_methods.py's `_structs_with_unresolved_
                    # base` branch). If a real definition DOES exist in
                    # another TU of a whole-program build (a sibling
                    # module / dylib exporting the same mangled symbol),
                    # that strong definition simply wins over this weak
                    # one and the real method runs — the weak stub is
                    # dead weight, never wrong behavior. See bugs/
                    # CODEGEN_generator_function_Lib_test_test_ctypes_
                    # test_random_things.md.
                    _known_params = (self.func_param_types.get(_smsym)
                                     or self.func_param_types.get(_smkey))
                    _smret_cpp = _smret.replace('_Bool', 'bool')
                    if not _known_params or (
                            len(_known_params) == 1 and _known_params[0] == '...'):
                        _stub_guard = _stub_guard_name(f"{_smkey}")
                        if _smret_cpp == 'void':
                            _stub_body = (f'{{ (void)_self; mojo_print ((char *)'
                                          f'"{_sm_struct}.{_sm_method}: unavailable in '
                                          f'compiled mode (inherited from an unmodeled '
                                          f'base class)"); }}')
                        else:
                            _stub_body = (f'{{ (void)_self; mojo_print ((char *)'
                                          f'"{_sm_struct}.{_sm_method}: unavailable in '
                                          f'compiled mode (inherited from an unmodeled '
                                          f'base class)"); return ({_smret_cpp})0; }}')
                        cpp_parts.append(
                            f'#ifndef {_stub_guard}\n#define {_stub_guard}\n'
                            f'extern "C" __attribute__((weak)) {_smret_cpp} {_smsym} '
                            f'({_sm_struct} *_self, ...) {_stub_body}\n#endif')
                        continue
                    _smparam_str = ', '.join(
                        p if p != '_Bool' else 'bool' for p in _known_params)
                    cpp_parts.append(
                        f'extern "C" {_smret_cpp} {_smsym} ({_smparam_str});')
                except Exception:
                    continue
            cpp_parts.append('')
        if getattr(self, '_cpp_xmod_generator_refs', None):
            # Extern "C" declarations of every compiled-generator drive API a
            # coroutine body of THIS module references via
            # {base}_start/_resume/_value/_destroy (see _cpp_resolve_generator_
            # call_api / _cpp_emit_generator_start_expr). Same-module bases are
            # defined later in this very TU (the units below) — a redundant
            # declaration ahead of the definition is ordinary C++; FOREIGN
            # bases (a transitively-imported sibling's own generators, e.g.
            # c_common/strutil.py's `_iter_significant_lines`) are defined in
            # that sibling's OWN object file (compiled + linked by
            # _compile_imported_module -> _compile_link_inline_cpp_unit), which
            # these declarations let the linker satisfy. Sorted for
            # deterministic (CAS-cache-stable) output.
            cpp_parts.append('/* Extern declarations for compiled-generator')
            cpp_parts.append('   drive APIs referenced by this module\'s')
            cpp_parts.append('   coroutine bodies (defined in this TU\'s own')
            cpp_parts.append('   units below, or in an imported sibling\'s')
            cpp_parts.append('   linked object). */')
            for _xg_base in sorted(self._cpp_xmod_generator_refs):
                _xg_info = self._cpp_xmod_generator_refs[_xg_base]
                _xg_vct = (_xg_info.get('value_ctype') or 'int64_t').replace('_Bool', 'bool')
                _xg_params = ', '.join(
                    p.replace('_Bool', 'bool') if isinstance(p, str) else p
                    for p in (_xg_info.get('params') or [])) or 'void'
                cpp_parts.append(f'extern "C" MojoGenerator *{_xg_base}_start ({_xg_params});')
                cpp_parts.append(f'extern "C" bool {_xg_base}_resume (MojoGenerator *);')
                cpp_parts.append(f'extern "C" {_xg_vct} {_xg_base}_value (MojoGenerator *);')
                cpp_parts.append(f'extern "C" void {_xg_base}_destroy (MojoGenerator *);')
            cpp_parts.append('')
        for unit in self._generator_cpp_units:
            cpp_parts.append(unit)
            cpp_parts.append('')
        self.generated_cpp = '\n'.join(cpp_parts)

    # A3 stack-switch coroutine trampolines (gimple_gen_coro.register): plain
    # C, emitted straight into this module's .c/.ci output — the generator
    # body itself was injected as an ordinary FunctionDef and is already
    # lowered among the function defs above; these 4 tiny <base>_* symbols
    # bridge it to the runtime shim (runtime/mojo_coro_gen.c).
    _ss_units = getattr(self, '_stackswitch_coro_c_units', None)
    if _ss_units:
        parts.append('')
        parts.extend(_ss_units)

    # ── GPU offload, Seam 3: the device sidecar ───────────────────────────
    # Emitted LAST, because the MSL text is only final once every device
    # function has been walked. It goes into the SAME .ci as a C string
    # literal, so one generated file is still the whole program — which is
    # what removes the offline `xcrun metal`/`metallib` step entirely: the
    # Metal runtime compiles the string at load time, for the GPU actually
    # present. The alternative (a second emitted artifact) would need build
    # wiring and a cache key for it, and buys nothing that
    # `newLibraryWithSource:` does not already do.
    if _device_parts:
        # The definitions -- MSL string, init, dispatch shim, per-kernel
        # launch wrappers, introspection. The `#include` and the wrapper
        # PROTOTYPES went into the preamble instead, because a host function
        # can call a kernel defined later in the file and an implicit
        # declaration of `float *` vs `int64_t` is a "conflicting types"
        # error reported against the wrong line.
        parts.append(_gmi_device_glue.emit_device_sidecar(
            _device_parts, sorted(self._device_kernels), _device_kernels_meta,
            module_name=_as_str(self.module_name),
            grids=getattr(self, '_device_launch_grids', None)))
        # The full sidecar defines the same four introspection entry points
        # as EMPTY_SIDECAR does, so mark them here too -- otherwise a
        # kernel-free module later in the closure emits EMPTY_SIDECAR and the
        # two collide. Measured: 2 definitions, `mojoc` and `selfhost` red.
        _mg_introspected.add('definitions')
    elif not _mg_introspected:
        # No device code in this module -- an ordinary module, or one compiled
        # with `--no-gpu` and no marked kernels. Emit the introspection entry
        # points anyway, reporting 0. Without them a program that ASKS whether
        # anything offloaded cannot be linked at all, which makes the question
        # unaskable exactly where it is most worth asking. No Metal include and
        # no device initialisation, so a kernel-free module still does not
        # depend on the GPU runtime and still runs on a machine without one.
        # ONCE PER TRANSLATION UNIT, not once per module -- see the flag's own
        # note at its initialisation above.
        _mg_introspected.add('definitions')
        parts.append(_gmi_device_glue.EMPTY_SIDECAR)

    return self._dedup_variadic_externs(parts)

def __getattr__(name):
    import gimple_codegen as _gc
    return getattr(_gc, name)
