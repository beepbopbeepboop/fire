"""C++ fallback lowering: expressions, statements, control flow.

Function-extraction architecture: former GimpleGen methods as
module-level functions taking `gen` first; delegates remain on
the class; cross-module references are qualified.
"""
from __future__ import annotations

import os
import re

from mojo_compiler import (
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
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc
import gimple_gen_exprs as gex

def _cpp_short_circuit_bool(gen, node) -> bool | None:
    """Like `_eval_const_bool`, but implements REAL Python short-circuit
    semantics for `and`/`or` at the top level, instead of requiring both
    operands to be independently foldable.

    Used only by `_cpp_stmt`'s `IfStmt` dead-branch elimination (the
    generator/coroutine `.cpp` body path) to resolve guard idioms like
    `if sys.platform == 'win32' and self.file_type ==
    SomeEnum.WINDOWS_ONLY_MEMBER:` — `sys.platform` is a genuine
    compile-time constant for this host (see `_eval_const`'s own
    `sys.platform` case and its "conditional toplevel def" precedent),
    and on a non-Windows host the left operand alone already proves the
    whole `and` False. Python's `and`/`or` never evaluate their right
    operand once the left side already decides the result, so the right
    operand's own resolvability (here, a top-level enum class name this
    codegen doesn't thread into a generator's coroutine scope — see
    bugs/CODEGEN_generator_function_Lib_test_libregrtest_runtests.md)
    is irrelevant to the branch's real, correct-for-this-host truth
    value. Returns True/False only when the ENTIRE condition is decided
    this way; None otherwise (ordinary runtime-dependent condition, or
    an `and`/`or` whose outcome genuinely depends on an unresolvable
    operand) — callers must fall back to normal codegen unchanged.
    """
    if isinstance(node, gimple_ctypes.BinaryOp) and node.op == 'and':
        l = gen._cpp_short_circuit_bool(node.left)
        if l is False:
            return False  # short-circuit: right operand never evaluated
        if l is True:
            return gen._cpp_short_circuit_bool(node.right)
        return None
    if isinstance(node, gimple_ctypes.BinaryOp) and node.op == 'or':
        l = gen._cpp_short_circuit_bool(node.left)
        if l is True:
            return True  # short-circuit: right operand never evaluated
        if l is False:
            return gen._cpp_short_circuit_bool(node.right)
        return None
    return gen._eval_const_bool(node)


def _cpp_in_link(gen, a: str, a_node, b: str, b_node, negate: bool) -> str:
    """Lower `a in b` / `a not in b` for the C++20-coroutine generator body,
    mirroring the GIMPLE path's _lower_in_dispatch (mojo_runtime.h
    membership helpers) rather than emitting Python's `in`/`not in`
    keyword text, which is invalid C++ (`not` is a keyword and `in` is not
    an operator). `a` is the element/needle, `b` is the container/haystack
    — exactly the operand order the runtime helpers take."""
    bt = gen._cpp_declared_type(b_node)
    at = gen._cpp_declared_type(a_node)
    if bt == 'char *':
        # substring/char membership: mojo_str_contains(haystack, needle)
        # The needle must be a char * — a bare indexed char (mojo_str_char_at
        # result, typed 'char') is widened to a 1-char string first, the
        # same coercion the GIMPLE path applies (mojo_char_to_str).
        if at == 'char':
            needle = f"mojo_char_to_str((char)({a}))"
        else:
            needle = f"(char *)({a})"
        res = f"mojo_str_contains((char *)({b}), {needle})"
    elif bt == 'MojoStr *':
        res = f"mojo_str_contains((char *)({b}), (char *)({a}))"
    elif bt == 'MojoList *':
        # mojo_list_contains_{int,double,str}; pick the suffix from the
        # list's recorded element type when known, else fall back to a
        # generic int probe (honest: wrong-typed elements compare unequal
        # at runtime rather than miscompiling). Mirrors _lower_in_dispatch's
        # list-element-type resolution.
        elem = None
        if gen._cpp_declared is not None and isinstance(b_node, gimple_ctypes.IdentExpr):
            elem = gen._elem_types.get(b_node.name)
        if elem in ('double',):
            res = f"mojo_list_contains_double((MojoList *)({b}), (double)({a}))"
        elif elem == 'char *' or at == 'char *':
            res = f"mojo_list_contains_str((MojoList *)({b}), (char *)({a}))"
        else:
            res = f"mojo_list_contains_int((MojoList *)({b}), (int64_t)({a}))"
    elif bt == 'MojoSet *':
        if at == 'char *' or (at and at.endswith('char')):
            res = f"mojo_set_contains_str((MojoSet *)({b}), (char *)({a}))"
        else:
            res = f"mojo_set_contains_int((MojoSet *)({b}), (int64_t)({a}))"
    elif bt == 'MojoDict *':
        # dict membership is keyed by string (all dict keys are char * in
        # the runtime) — `a in d` tests key presence.
        res = f"mojo_dict_contains((MojoDict *)({b}), (char *)({a}))"
    else:
        # Honest stub: we can't statically resolve the container's C++ type
        # here, so emit a conservative 0 (matches the GIMPLE path's
        # `/* TODO: 'in' for {rt} */` fallback — the module still COMPILES,
        # behavior is simply "not present", same as the documented stopgap).
        gimple_ctypes._debug_note("stubbed 'in'", f"unknown container type {bt!r} for `in`")
        res = "0"
    if negate:
        res = f"(!({res}))"
    return f"({res})"


def _cpp_container_literal_init(gen, name: str, value_node, indent: str) -> list[str]:
    """Emit a REAL runtime construction for a container-LITERAL assignment
    target (`lines = []`, `entry = {}`) into an already-container-typed
    local `name` — the statement-level counterpart of `_infer_simple_expr_
    ctype`'s ListExpr/DictExpr/SetExpr cases (which type the local). The
    expression emitter's literal cases produce raw C++ brace-init text
    (`{}`), which is only valid for scalar/aggregate C++ types, never for
    a MojoList*/MojoDict*/MojoSet* local. Python semantics create a FRESH
    object per evaluation, so each call re-constructs rather than clearing.

    Element/value ctypes come from the same `_infer_simple_expr_ctype`
    (default int64_t, this model's boxed-value convention); the list's
    unified element type is recorded into `gen._cpp_list_local_elem_types`
    for the later `.append`/for-loop/subscript-read sites to reuse.
    Non-literal-typed elements (a nested literal, a call of unknown type)
    still append via the int64_t box — matching every other "unknown ->
    int64_t box" convention in this emitter — EXCEPT genuinely nested
    containers, which have no flat representation here and refuse honestly.
    """
    elem_reg = getattr(gen, '_cpp_list_local_elem_types', None)
    if isinstance(value_node, gimple_ctypes.ListExpr):
        etype = None
        for el in value_node.elements:
            if isinstance(el, (gimple_ctypes.ListExpr, gimple_ctypes.DictExpr,
                               gimple_ctypes.SetExpr, gimple_ctypes.TupleExpr)):
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    "a nested container literal has no representation as a "
                    "list element in this coroutine-body model")
            ect = gimple_exprtypes._infer_simple_expr_ctype(
                el, gen._cpp_declared, getattr(gen, '_cpp_gen_self_fields', None),
                gen._async_api) or 'int64_t'
            etype = ect if etype is None else (gimple_ctypes.TypeLattice.join(etype, ect) or 'int64_t')
        lines = [f"{indent}{name} = mojo_list_new();"]
        for el in value_node.elements:
            ev = gen._cpp_expr(el)
            ect = gimple_exprtypes._infer_simple_expr_ctype(
                el, gen._cpp_declared, getattr(gen, '_cpp_gen_self_fields', None),
                gen._async_api) or 'int64_t'
            if etype == 'char *':
                lines.append(f"{indent}mojo_list_append_str({name}, "
                             f"(char *)({ev}));")
            elif etype == 'double':
                lines.append(f"{indent}mojo_list_append_double({name}, "
                             f"(double)({ev}));")
            else:
                lines.append(f"{indent}mojo_list_append_int({name}, "
                             f"(int64_t)({ev}));")
        if elem_reg is not None:
            elem_reg[name] = etype or 'int64_t'
        return lines
    if isinstance(value_node, gimple_ctypes.DictExpr):
        lines = [f"{indent}{name} = mojo_dict_new();"]
        vtype = None
        for k_node, v_node in value_node.pairs:
            if not isinstance(k_node, gimple_ctypes.StringLiteral):
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    "only string-literal keys are supported in a dict "
                    "literal inside a coroutine body")
            vct = gimple_exprtypes._infer_simple_expr_ctype(
                v_node, gen._cpp_declared, getattr(gen, '_cpp_gen_self_fields', None),
                gen._async_api) or 'int64_t'
            vtype = vct if vtype is None else (gimple_ctypes.TypeLattice.join(vtype, vct) or 'int64_t')
        for k_node, v_node in value_node.pairs:
            vv = gen._cpp_expr(v_node)
            key = f'"{gimple_ctypes._c_escape(k_node.value)}"'
            if vtype == 'char *':
                lines.append(f"{indent}mojo_dict_set_str({name}, {key}, "
                             f"(char *)({vv}));")
            elif vtype == 'double':
                lines.append(f"{indent}mojo_dict_set_double({name}, {key}, "
                             f"(double)({vv}));")
            else:
                lines.append(f"{indent}mojo_dict_set_int({name}, {key}, "
                             f"(int64_t)({vv}));")
        return lines
    if isinstance(value_node, gimple_ctypes.SetExpr):
        lines = [f"{indent}{name} = mojo_set_new();"]
        for el in value_node.elements:
            ev = gen._cpp_expr(el)
            ect = gimple_exprtypes._infer_simple_expr_ctype(
                el, gen._cpp_declared, getattr(gen, '_cpp_gen_self_fields', None),
                gen._async_api) or 'int64_t'
            if ect == 'char *':
                lines.append(f"{indent}mojo_set_add_str({name}, (char *)({ev}));")
            else:
                lines.append(f"{indent}mojo_set_add_int({name}, (int64_t)({ev}));")
        return lines
    return None


def _cpp_pad_struct_method_call_args(gen, sym: str, bare: str,
                                     args: list) -> list:
    """Pad a coroutine-body struct-method call's argument list out to the
    callee method's real arity (`args` EXCLUDES the receiver — the caller
    re-prepends it when composing the final call text). The ordinary
    (non-coroutine) GIMPLE path's `_lower_struct_method_call` already pads
    a short call to `expected_non_self`; this emitter's three struct-method
    call branches (`self.<method>(...)`, `cls.<method>(...)`,
    `<struct-ptr-local>.<method>(...)`) previously emitted the given
    arguments verbatim, so an omitted defaulted trailing argument
    (mailbox.py's `_singlefileMailbox.iterkeys` calling `self._lookup()` on
    `def _lookup(self, key=None)`) produced a C call with fewer arguments
    than the callee's real signature — g++'s "too few arguments to
    function '<mangled>'".

    Arity comes from `func_param_types` under the qualified-or-bare mangled
    key — the SAME registry the ordinary path reads (its entries include
    the receiver as slot 0, hence the +1 below). Trailing gaps are filled
    with each param's real declared default via the existing
    `_default_expr_to_pair` helper (registered per bare mangled key by
    gen_module's method pre-pass), falling back to a literal 0 — this
    runtime's None/absent box — exactly like the ordinary path's own
    padding loop. A vararg ('...' sentinel) signature is left unpadded
    (unknown arity); kwargs are not modeled here (the coroutine emitter's
    CallExpr handling never produced them for these branches).
    """
    expected = gen.func_param_types.get(sym) or gen.func_param_types.get(bare)
    if not expected or len(expected) == 0 or '...' in expected:
        return args
    expected_non_self = len(expected) - 1
    if len(args) >= expected_non_self:
        return args
    dflts = gen._func_param_defaults.get(sym) or gen._func_param_defaults.get(bare) or []
    first_dflt = expected_non_self - len(dflts)
    out = list(args)
    while len(out) < expected_non_self:
        pos = len(out)
        dv = dflts[pos - first_dflt][1] if (dflts and 0 <= pos - first_dflt < len(dflts)) else None
        if dv is None:
            out.append('0')
        else:
            _dt, dval = gen._default_expr_to_pair(dv)
            out.append(dval)
    return out


def _cpp_try_kwargs_forward_call(gen, e):
    """Real runtime-lookup-based `**kwargs` forwarding for a compiled
    generator/coroutine body call `f(pos..., **kwargs_var)`, where `f`
    is a statically-known local free function that itself declares
    `**kwargs`. See the call site's own comment (bugs/COMPILE_FAIL_
    Tools_c-analyzer_c_analyzer___init__.md) for why a naive "pad the
    gap with f's static defaults" fix is a WORKING WRONG ANSWER: it
    ignores whatever the caller's kwargs dict actually contains at
    runtime. This instead resolves each "gap" parameter (between the
    given positional args and f's own `**kwargs` slot) with a genuine
    `mojo_dict_contains`/`mojo_dict_pop_int` runtime lookup against a
    COPY of the caller's dict — falling back to the static default only
    when the key is genuinely absent — and forwards the copy's
    unconsumed remainder into f's own `**kwargs` parameter. The dict is
    copied (never mutated in place) because the spread variable may be
    reused across further calls (e.g. this exact bug's `while i < n:
    yield target(i, **kwargs)` loop — popping straight from the
    caller's own dict on iteration 1 would silently lose the override
    for iterations 2/3).

    Only handles the narrow shape it can PROVE is exactly this:
    `f`'s non-kwargs parameters are all either supplied positionally or
    covered by a int64_t-typed static default, in that exact order,
    with no `*args` in between (a real `*args` slot shifts positions in
    a way this derivation doesn't attempt to untangle). Returns the
    lowered C++ expression string, or None — never a guess — for
    anything else, so the caller falls through to the existing honest
    refusal.
    """
    fname_raw = e.func.name
    spread = e.args[-1].operand
    given = e.args[:-1]
    # Only a statically-known LOCAL free function — never a dynamically
    # obtained callee (a parameter/local holding a function value, e.g.
    # codecs.py's `getincrementalencoder(encoding)(errors, **kwargs)`,
    # or c_analyzer/__init__.py's own `parse_files=_parse_files`
    # default-valued callable parameter), whose real parameter names/
    # defaults can't be known at compile time.
    if fname_raw not in gen.func_param_types:
        return None
    # `fname_raw` must be an ORDINARY function with a real, directly-
    # callable C symbol — never a generator/async function (compiled
    # ones have no such symbol at all, only the `_start`/`_resume`/
    # `_value` coroutine API; calling their mangled name directly is
    # either a link error or, worse, an accidental collision), and
    # never a struct method (no `self`, wrong call shape). Real
    # instance: Tools/c-analyzer/c_analyzer/__init__.py's
    # `iter_analysis_results` doing `iter_decls(filenames, **kwargs)`
    # — `iter_decls` is itself a generator.
    if fname_raw in gen._generator_api or fname_raw in gen._async_api:
        return None
    try:
        fsym = gen._func_csym(fname_raw)
    except Exception:
        fsym = fname_raw
    kwslot = gen._func_kwargs_slot.get(fsym, gen._func_kwargs_slot.get(fname_raw, -1))
    if kwslot < 0:
        return None  # callee doesn't itself declare **kwargs
    ctypes = gen.func_param_types.get(fsym) or gen.func_param_types.get(fname_raw) or []
    if len(ctypes) <= kwslot:
        return None
    defaults = gen._func_param_defaults.get(fsym) or gen._func_param_defaults.get(fname_raw) or []
    n_given = len(given)
    if n_given > kwslot:
        return None  # more positional args than f has non-kwargs params
    n_required = kwslot - len(defaults)
    if n_given < n_required:
        return None  # a genuinely-required param wasn't supplied — can't safely guess
    gap_defaults = defaults[max(0, n_given - n_required):]
    if len(gap_defaults) != (kwslot - n_given):
        return None  # shape doesn't line up cleanly (e.g. a real *args
                      # in between) — don't guess, fall through to refusal
    # Every gap param must be a plain int64_t slot — this narrow fix
    # only has a real dict-pop primitive for int (mojo_dict_pop_int);
    # a double/_Bool/pointer-typed gap param falls through to the
    # honest refusal rather than mis-typing it.
    gap_ctypes = ctypes[n_given:kwslot]
    if any(ct != 'int64_t' for ct in gap_ctypes):
        return None
    given_vals = [gen._cpp_expr(a) for a in given]
    kwargs_val = gen._cpp_expr(spread)
    ret_ctype = gen.func_return_types.get(fname_raw, 'int64_t')
    # Register fname_raw so the .cpp preamble emits a real `extern "C"`
    # forward declaration for it (see _cpp_module_func_refs' consumer
    # a few thousand lines down) — without this, `target_5c8044` (the
    # mangled C symbol) is referenced but never declared in this
    # separately-compiled .cpp translation unit: "was not declared in
    # this scope".
    gen._cpp_module_func_refs.add(fname_raw)
    gimple_codegen.GimpleGen._cpp_kwfwd_counter += 1
    uid = gimple_codegen.GimpleGen._cpp_kwfwd_counter
    dict_var = f"_kwfwd{uid}"
    lines = [f"MojoDict *{dict_var} = mojo_dict_copy((MojoDict *)({kwargs_val}));"]
    call_args = list(given_vals)
    for i in range(len(gap_defaults)):
        pname, dflt_ast = gap_defaults[i]
        _dt, dval = gen._default_expr_to_pair(dflt_ast)
        gap_var = f"_kwgap{uid}_{i}"
        lines.append(
            f'int64_t {gap_var} = mojo_dict_contains({dict_var}, "{pname}") '
            f'? mojo_dict_pop_int({dict_var}, "{pname}") : (int64_t)({dval});')
        call_args.append(gap_var)
    call_args.append(dict_var)
    lines.append(f"return {fsym}({', '.join(call_args)});")
    body = ' '.join(lines)
    return f"[&]() -> {ret_ctype} {{ {body} }}()"


def _cpp_receiver_ctype(gen, e):
    """Best-effort static C type of a method-call RECEIVER expression inside
    a compiled generator/coroutine body, for the receiver-typed dispatch the
    `.replace(...)`/`.get(...)`/`.items()`-family lowering below (and
    `_cpp_for_stmt`'s dict-iteration cases) need. Covers exactly the four
    receiver shapes this body model can actually type — a declared local/param,
    a `self.<field>` struct field, a `cls.<class-attr>` class-level global,
    and a zero-argument `.copy()` chain over either collection type (the one
    chained call whose result type is statically knowable: mojo_dict_copy/
    mojo_list_copy preserve the receiver's pointer type) — returning None for
    everything else, which every caller treats as "unknown, fall through to
    the generic lowering". Consolidates what used to be three separate inline
    lookups inside `_cpp_expr`'s MemberExpr-call handling so `_cpp_for_stmt`
    can share them instead of growing its own divergent copy."""
    declared = getattr(gen, '_cpp_declared', None)
    if isinstance(e, gimple_ctypes.IdentExpr):
        return declared.get(e.name) if declared is not None else None
    if isinstance(e, gimple_ctypes.MemberExpr):
        _self_struct = getattr(gen, '_cpp_gen_self_struct', None)
        if (_self_struct and isinstance(e.obj, gimple_ctypes.IdentExpr)
                and e.obj.name == 'self'):
            return gen.struct_field_types.get(_self_struct, {}).get(e.member)
        if (_self_struct and isinstance(e.obj, gimple_ctypes.IdentExpr)
                and e.obj.name == 'cls'):
            _cls_gname = gen._class_attrs.get(_self_struct, {}).get(e.member)
            if _cls_gname is not None:
                return gen._global_var_types.get(_cls_gname)
        # `<struct-pointer local>.<field>` — the non-self sibling of the
        # `self.<field>` case (e.g. a generator taking a struct-typed
        # parameter: `for k, v in b.data.copy().items():`), resolved
        # through the same declared-struct-pointer-local lookup
        # `_cpp_expr`'s MemberExpr case already uses for the read itself.
        if isinstance(e.obj, gimple_ctypes.IdentExpr):
            _obj_struct = gen._cpp_struct_ptr_local(e.obj.name)
            if _obj_struct:
                return gen.struct_field_types.get(_obj_struct, {}).get(e.member)
        return None
    if (isinstance(e, gimple_ctypes.CallExpr)
            and isinstance(e.func, gimple_ctypes.MemberExpr)
            and not e.args and e.func.member == 'copy'):
        rc = _cpp_receiver_ctype(gen, e.func.obj)
        return rc if rc in ('MojoDict *', 'MojoList *') else None
    return None


def _cpp_trusted_fn_return_types(gen) -> dict:
    """The subset of `gen.func_return_types` a coroutine body may trust for
    local-variable typing: only pointer-shaped ctypes ('char *' and the
    container pointers, plus known-struct pointers). An int64_t entry carries
    no information beyond this emitter's own untyped-local default, so it is
    excluded — trusting it could never change anything, but scanning less
    keeps the map honest about what it asserts. Built once per module compile
    into `gen._cpp_trusted_fn_returns`; func_return_types entries are
    corrected in place by later passes (see _func_csym's Pass 1.3e note), so
    the cache is cleared in gen_module's generator/async pre-passes' unit
    builder `finally` blocks via `_cpp_reset_unit_state`."""
    cached = getattr(gen, '_cpp_trusted_fn_returns', None)
    if cached is not None:
        return cached
    trusted: dict = {}
    _known_structs = frozenset(gen.struct_field_types.keys())
    for _k, _v in gen.func_return_types.items():
        if not isinstance(_v, str):
            continue
        if _v in ('char *', 'MojoList *', 'MojoDict *', 'MojoSet *') or (
                _v.endswith(' *') and _v[:-2] in _known_structs):
            trusted[_k] = _v
    gen._cpp_trusted_fn_returns = trusted
    return trusted


def _cpp_percent_format(gen, node) -> str | None:
    """Coroutine-body counterpart of the ordinary GIMPLE path's
    `_lower_percent_format` (gimple_gen_exprs.py) — Python `%`-style
    string formatting (`"%s and %s are not of the same version" %
    (self, other)`, ipaddress.py's `BaseNetwork.address_exclude`;
    `"%r is not a positive integer"`, enum.py's `_iter_bits_lsb`;
    `"MLSD %s" % path`, ftplib.py's `mlsd`) when the LHS is a literal
    format string, inside a compiled generator/async body.

    That statement-based helper can't be reused directly: it emits
    GIMPLE temp-declaration statements via `gen._new_val` and reads
    typed (et, ev) pairs off `gen.lower_expr`'s own SSA-like value
    system, neither of which this emitter has — `_cpp_expr` always
    returns one inline C++ EXPRESSION string, no side-channel statement
    list. So this rebuilds the same left-to-right literal/spec split,
    but composes the result as a nested `mojo_str_cat(...)` expression
    tree instead of a sequence of statements, and dispatches each
    operand's stringification off `_infer_simple_expr_ctype` (this
    body model's own best-effort static ctype) rather than the ordinary
    path's exact GIMPLE-inferred (et, ev).

    Deliberately narrow: only bare `%s`/`%r`/`%d`/`%i` specs (no
    width/precision/flags — dynamic padding is rare for the
    error-message shape this targets, and `mojo_str`'s int/pointer
    heuristic — the same one `str(x)` already uses inside this emitter,
    see the `fname == 'str'` branch above — has no notion of field
    width to apply anyway). Returns None (the same "give up, let the
    caller fall through" sentinel `_lower_percent` uses) for: a
    non-literal or f-string LHS, a mismatched spec/operand count, an
    unsupported conversion character, or no specs at all (a literal
    `%` that wasn't really meant as a template) — the caller then emits
    the plain numeric `%` operator, unchanged from before this function
    existed.
    """
    if not isinstance(node.left, gimple_ctypes.StringLiteral):
        return None
    fmt_text, is_fstring = gen._decode_str_literal_text(node.left.value)
    if is_fstring:
        return None
    rhs_exprs = (list(node.right.elements)
                 if isinstance(node.right, gimple_ctypes.TupleExpr)
                 else [node.right])
    parts = []
    buf = []
    i, n = 0, len(fmt_text)
    while i < n:
        c = fmt_text[i]
        if c != '%':
            buf.append(c); i += 1
            continue
        if i + 1 < n and fmt_text[i + 1] == '%':
            buf.append('%'); i += 2
            continue
        if buf:
            parts.append(('lit', ''.join(buf))); buf = []
        spec_start = i
        i += 1
        while i < n and fmt_text[i] in '-+0 #.123456789':
            i += 1
        conv = fmt_text[i] if i < n else 's'
        if i < n:
            i += 1
        parts.append(('spec', fmt_text[spec_start:i], conv))
    if buf:
        parts.append(('lit', ''.join(buf)))
    n_specs = sum(1 for p in parts if p[0] == 'spec')
    if n_specs == 0 or n_specs != len(rhs_exprs):
        return None
    if any(p[0] == 'spec' and p[1] not in ('%s', '%r', '%d', '%i') for p in parts):
        return None

    self_fields = getattr(gen, '_cpp_gen_self_fields', None)
    fn_ret = _cpp_trusted_fn_return_types(gen)

    def _operand_ctype(operand):
        try:
            return gimple_exprtypes._infer_simple_expr_ctype(
                operand, gen._cpp_declared, self_fields, gen._async_api,
                fn_return_types=fn_ret) or 'int64_t'
        except Exception:
            return 'int64_t'

    def _stringify(operand, conv):
        v = gen._cpp_expr(operand)
        ct = _operand_ctype(operand)
        if conv == 'r':
            if ct == 'char *':
                return f"mojo_repr_str((char *)({v}))"
            if ct == 'double':
                return f"mojo_repr_float(({v}))"
            return f"mojo_str((void *)({v}))"
        # 's' / 'd' / 'i'
        if ct == 'char *':
            return v
        if ct == 'double':
            return f"mojo_repr_float(({v}))"
        return f"mojo_str((void *)({v}))"

    acc = None
    arg_i = 0
    for p in parts:
        if p[0] == 'lit':
            text = p[1]
            if not text:
                continue
            piece = f'"{gimple_ctypes._c_escape(text)}"'
        else:
            _, _full_spec, conv = p
            operand = rhs_exprs[arg_i]
            arg_i += 1
            piece = _stringify(operand, conv)
        acc = piece if acc is None else (
            f"mojo_str_cat((char *)({acc}), (char *)({piece}))")
    return acc if acc is not None else '""'


def _cpp_fn_container_shape(gen, fname: str, depth: int = 0) -> str | None:
    """'dict' / 'list' when EVERY value-returning exit of module-level
    function `fname` provably produces that container kind (never both), by
    scanning its FunctionDef AST — the coroutine-body emitter's substitute
    for the ordinary path's per-temp `_actual_types` propagation, which a
    separately-compiled C++ unit cannot read. Recognized shapes: DictExpr /
    `<regex match>.groupdict()` / a local bound to either; ListExpr /
    `<str>.split(...)` / sorted(...) / a local bound to those; plus
    pass-through returns of another module function with an already-known
    shape (depth-limited). Mixed dict/list returns, unknown shapes, and
    functions returning None alongside nothing else resolve to None ("no
    proof"), which every consumer must treat as "keep the previous
    lowering". Real driver: dyld.py's generators subscripting
    `framework_info(name)['name']` — framework_info's int64_t-boxed dict
    result previously lowered as a STRING slice (mojo_cstr_slice on a dict
    pointer)."""
    if depth > 4:
        return None
    cache = getattr(gen, '_cpp_fn_shape_cache', None)
    if cache is None:
        cache = {}
        gen._cpp_fn_shape_cache = cache
    if fname in cache:
        return cache[fname]
    fn_ast = getattr(gen, '_cpp_module_fn_asts', {}).get(fname)
    if fn_ast is None:
        return None
    shapes: set = set()

    def _shape_of(expr, locals_shape: dict):
        if expr is None:
            return None
        if isinstance(expr, gimple_ctypes.DictExpr):
            return 'dict'
        if isinstance(expr, (gimple_ctypes.ListExpr, gimple_ctypes.SetExpr,
                             gimple_ctypes.Comprehension)):
            return 'list'
        if isinstance(expr, gimple_ctypes.TupleExpr):
            return 'list'
        if isinstance(expr, gimple_ctypes.TernaryExpr):
            a = _shape_of(getattr(expr, 'then_val', None), locals_shape)
            b = _shape_of(getattr(expr, 'else_val', None), locals_shape)
            return a if a == b else None
        if isinstance(expr, gimple_ctypes.IdentExpr):
            if expr.name == 'None':
                return None
            return locals_shape.get(expr.name)
        if isinstance(expr, gimple_ctypes.CallExpr):
            f = expr.func
            if isinstance(f, gimple_ctypes.MemberExpr):
                if f.member in ('groupdict', 'items', 'copy') and not expr.args:
                    return 'dict' if f.member in ('groupdict', 'items') else None
                if f.member == 'split':
                    return 'list'
                return None
            if isinstance(f, gimple_ctypes.IdentExpr):
                if f.name == 'sorted' or f.name == 'dict':
                    return 'list' if f.name == 'sorted' else 'dict'
                sub = _cpp_fn_container_shape(gen, f.name, depth + 1)
                if sub:
                    shapes.add(sub)
                return None
        return None

    def _scan(stmts, locals_shape: dict):
        for st in stmts:
            if isinstance(st, gimple_ctypes.AssignStmt) and isinstance(st.target, gimple_ctypes.IdentExpr):
                sh = _shape_of(st.value, locals_shape)
                if sh:
                    locals_shape[st.target.name] = sh
            elif isinstance(st, gimple_ctypes.ReturnStmt):
                sh = _shape_of(st.value, locals_shape)
                if sh:
                    shapes.add(sh)
            elif isinstance(st, gimple_ctypes.IfStmt):
                _scan(st.then_body or [], dict(locals_shape))
                for _, elif_body in (st.elifs or []):
                    _scan(elif_body or [], dict(locals_shape))
                if st.else_body:
                    _scan(st.else_body, dict(locals_shape))
            elif isinstance(st, gimple_ctypes.TryStmt):
                _scan(st.body or [], dict(locals_shape))
                for h in (st.handlers or []):
                    _scan(h.body or [], dict(locals_shape))
                if st.else_body:
                    _scan(st.else_body, dict(locals_shape))
    _scan(fn_ast.body, {})
    # `next(iter(shapes))` avoided deliberately: this module is itself
    # compiled by the self-hosting `make check-selfhost` pass, whose
    # plain-C `next()` lowering only understands a MojoGenerator* operand
    # (see gimple_gen_calls.py's `next` handling) — `next()` on a `set`
    # falls through to an undefined-at-link-time generic stub. A plain
    # loop over the one-element set reaches the same value through a
    # shape this codegen path already supports.
    if len(shapes) == 1:
        for _shape in shapes:
            cache[fname] = _shape
            return _shape
    cache[fname] = None
    return None


def _cpp_reset_unit_state(gen):
    """Reset the per-coroutine-unit emitter state: the lazy caches
    `_cpp_trusted_fn_return_types` / `_cpp_fn_container_shape` populate
    (rebuilt per unit so func_return_types corrections earlier passes made
    meanwhile are re-read — see _func_csym's stale-freeze warning), plus the
    per-unit map of locals statically known to hold a dict/list (from a
    container-shaped callee), consumed by SubscriptExpr lowering."""
    gen._cpp_trusted_fn_returns = None
    gen._cpp_fn_shape_cache = {}
    gen._cpp_local_container_shapes = {}


def _cpp_expr(gen, e) -> str:
    if isinstance(e, gimple_ctypes.IntLiteral):
        return str(e.value)
    if isinstance(e, gimple_ctypes.FloatLiteral):
        s = repr(e.value)
        if '.' not in s and 'e' not in s.lower():
            s += '.0'
        return s
    if isinstance(e, gimple_ctypes.BoolLiteral):
        return 'true' if e.value else 'false'
    if isinstance(e, gimple_ctypes.StringLiteral):
        val = e.value
        if val.startswith('`') and val.endswith('`') and len(val) > 2:
            return val  # backtick-quoted identifier (mojo keyword escape)
        # C++ string literal
        escaped = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
        return f'"{escaped}"'
    if isinstance(e, gimple_ctypes.IdentExpr):
        if e.name == 'None':
            return '0'  # None → null pointer / zero (matches _lower_IdentExpr)
        if e.name == 'True':
            return 'true'
        if e.name == 'False':
            return 'false'
        if e.name == 'self' and getattr(gen, '_cpp_gen_self_struct', None):
            return "self"  # self is a struct pointer in generator methods
        # A mutated-by-reference capture (see `_gen_cpp_async_unit`'s
        # `mut_capture_names` docstring) is threaded through as a
        # pointer parameter -- every ordinary READ of its name must
        # dereference that pointer, not read the pointer's own address
        # as if it were the value.
        if e.name in gen._cpp_mut_capture_names:
            return f"(*{e.name})"
        # Module-global reference: a name that isn't a declared local/
        # param/capture but IS a known module-level global (in
        # `_global_var_types`) resolves to the module globals struct
        # field `_{module}_globals.<name>` — the exact field reference
        # the ordinary GIMPLE path's _lower_IdentExpr emits. The .cpp
        # preamble declares that struct + `extern` instance (see
        # gen_module's generated_cpp assembly), so a generator body can
        # read a module global like any ordinary compiled function.
        if (gen._cpp_declared is not None
                and e.name not in gen._cpp_declared
                and (e.name in gen._global_var_types
                     or e.name in gen._cpp_early_global_names)):
            global_module = getattr(gen, '_global_to_module', {}).get(
                e.name, gen._current_module_ctx or "root")
            safe_mod = gimple_ctypes._c_field_name(str(global_module)) if global_module else "root"
            field = gimple_ctypes._c_field_name(e.name)
            # Same C++-keyword escaping the .cpp globals-struct typedef
            # uses (`operator`/`new`/... are fine in C, not in C++).
            if field in gimple_ctypes._CPP_KEYWORD_FIELDS:
                field = f"_kw_{field}"
            gen._cpp_module_global_refs.add((safe_mod, e.name))
            return f"_{safe_mod}_globals.{field}"
        # A bare module-level function name referenced as a value (e.g.
        # tokenize.py's `encode = detect_encoding`) — the generator body
        # holds it as an opaque int64_t; the call site resolves the real
        # mangled symbol separately (see the CallExpr IdentExpr case).
        if (gen._cpp_declared is not None
                and e.name not in gen._cpp_declared
                and e.name in gen.func_param_types
                and e.name not in gen._global_var_types):
            gen._cpp_module_func_refs.add(e.name)
            return f"(int64_t)&{gen._func_csym(e.name)}"
        # A coroutine parameter whose Python name is a reserved C/C++
        # keyword (e.g. `default`) was renamed in the emitted
        # signature — see self._cpp_kw_param_renames's docstring.
        # Every read of it must agree with that renamed identifier.
        if e.name in gen._cpp_kw_param_renames:
            return gen._cpp_kw_param_renames[e.name]
        return e.name
    if isinstance(e, gimple_ctypes.MemberExpr):
        # Generator-METHOD `self.<field>` read — the only attribute
        # access this narrow step supports. self._cpp_gen_self_struct
        # (set/cleared by _gen_cpp_generator_unit around this whole
        # method's compile attempt, never set for a free-function
        # generator) names the enclosing struct so struct_field_types
        # can be consulted for the field's real scalar type; anything
        # else (self.other_method(), a nested chain like self.x.y, an
        # attribute read on a non-self object) falls through to the
        # raise below, unchanged.
        struct_name = getattr(gen, '_cpp_gen_self_struct', None)
        if struct_name and isinstance(e.obj, gimple_ctypes.IdentExpr) and e.obj.name == 'self':
            # `self.<method>` read WITHOUT an immediate call -- a
            # bound-method-as-VALUE reference (pickletools.py's
            # `getpos = data.tell` idiom, `self.<method>` variant --
            # see bugs/hard/CODEGEN_generator_lambda_expr_unsupported.
            # md). Checked FIRST, ahead of the field lookup just below:
            # `struct_field_types[struct_name]` can't be trusted to
            # prove "not a method" on its own —
            # `_scan_body_for_local_field_access` (this file's dynamic-
            # attribute pre-pass) synthesizes a phantom `'int'`-typed
            # FIELD entry for any `<struct local>.<unrecognized member>`
            # read found ANYWHERE in the module (a real method read as
            # a value, like this one, is exactly such an "unrecognized
            # member" read), so a real method's name can end up in
            # struct_field_types too. `_struct_method_names` (real
            # method names straight from the struct's own AST) is the
            # actual authoritative signal, so it's asked first — a
            # struct field can't legitimately share a name with one of
            # its own methods anyway. When `e.member` IS a real method
            # -- mirroring this same file's OWN `self.method(...)`
            # CALL-site convention just below (`_cpp_self_struct`
            # branch of the CallExpr/MemberExpr case: trust the source,
            # dispatch through the method's real mangled C symbol) --
            # wrap that SAME statically-known symbol in a capturing C++
            # lambda convertible to this coroutine model's one
            # callable-value category (`_CPP_CALLABLE_CTYPE`). A real
            # call through the resulting value is an ordinary `name()`
            # — the existing bare-name CallExpr fallback already emits
            # exactly that, and `std::function` supports `operator()`
            # natively, so no separate call-site case is needed.
            if e.member in gen._struct_method_names.get(struct_name, ()):
                _sym = gen._struct_method_csym(struct_name, e.member, '')
                gen._cpp_struct_method_refs.add((struct_name, e.member))
                return (f"(({gimple_ctypes._CPP_CALLABLE_CTYPE})"
                        f"([&]() -> int64_t {{ return {_sym}(self); }}))")
            _self_fields = gen.struct_field_types.get(struct_name, {})
            if e.member in _self_fields:
                ft = _self_fields[e.member]
                if ft in ('int64_t', 'double', '_Bool', 'char *'):
                    return f"self->{gimple_ctypes._safe_field(e.member)}"
                # Unknown-shaped field: emit as self->member (C++ struct pointer access)
                return f"self->{gimple_ctypes._safe_field(e.member)}"
            # Anything else (neither a field nor a real method — a
            # genuine not-yet-synthesized dynamic attribute) falls
            # through unchanged to the original best-effort raw access.
            return f"self->{gimple_ctypes._safe_field(e.member)}"
        # `cls.<attr>` — the class-level (not instance) analogue of
        # `self.<field>` just above, for a @classmethod generator (see
        # the classmethod-generator eligibility check, ~line 30536,
        # which conventionally names this parameter `cls`). `cls`
        # itself is only ever an opaque, never-dereferenced int64_t
        # placeholder in this codegen — there is no real object behind
        # it (see that same eligibility check's own comment), so
        # (unlike `self`) there is no `cls->member` struct-field-
        # pointer form to fall back to. Only the SAME class-attribute-
        # global redirect the ordinary (non-coroutine) GIMPLE path's
        # own `_lower_MemberExpr` already uses for `self.<class-level-
        # attr>`/`ClassName.attr` reads (`self._class_attrs[struct_
        # name][attr] -> mangled global variable`, see that method's
        # "Class-level attribute (not an instance field)" branch) is
        # supported here — anything else (a genuine instance field,
        # which `cls` structurally cannot have; an unrecognized name)
        # must refuse rather than silently emit `cls->member` (invalid
        # C++ on a scalar int64_t) or `cls.member` (equally invalid).
        # See bugs/CODEGEN_generator_function_Lib_enum.md's 2026-08-21
        # update for the motivating `cls._flag_mask_`/`cls.
        # _value2member_map_` shapes (Flag._iter_member_by_value_).
        if struct_name and isinstance(e.obj, gimple_ctypes.IdentExpr) and e.obj.name == 'cls':
            _cls_gname = gen._class_attrs.get(struct_name, {}).get(e.member)
            if _cls_gname is not None:
                gen._cpp_class_attr_refs.add(_cls_gname)
                return _cls_gname
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"cls.{e.member}: only a class-level attribute assigned "
                "in the enclosing class's own body is supported for "
                "`cls.<attr>` reads in a compiled generator/coroutine "
                "body (no class-level attribute/method access exists "
                "for any other shape)")
        # Two-level `self.<field1>.<field2>` chain (imaplib.py's
        # `Idler.burst`: `self._imap.sock`, where `_imap` is itself a
        # struct-pointer-typed field). This narrow model's own struct-
        # field boxing convention (the same one module globals and
        # `_safe_coerce_emit` already box through) stores ANY non-
        # scalar field — including a struct pointer like `_imap:
        # IMAP4` — as a raw `int64_t` in the emitted C++ typedef (see
        # gen_module's struct-typedef emission), so a bare `self-
        # >field1` is genuinely `int64_t` at the C++ level, not a real
        # pointer: `self->field1.field2`/`self->field1->field2` are
        # BOTH invalid C++ on that raw int64_t (g++: "member reference
        # base type 'int64_t' is not a structure or union"). An
        # explicit cast through `field1`'s own REGISTERED struct-
        # pointer type (already known via struct_field_types, exactly
        # like the single-level case just above already looks up)
        # makes the chain valid: `((Inner *)(self->field1))->field2`.
        # Only recurses one extra level (matches the one confirmed
        # real-world shape) — a THIRD level (`self.a.b.c`) still falls
        # through to the generic fallback below and is not attempted.
        if (struct_name and isinstance(e.obj, gimple_ctypes.MemberExpr)
                and isinstance(e.obj.obj, gimple_ctypes.IdentExpr) and e.obj.obj.name == 'self'):
            outer_ft = gen.struct_field_types.get(struct_name, {}).get(e.obj.member)
            if (outer_ft and outer_ft.endswith(' *')
                    and outer_ft[:-2] in gen.struct_field_types):
                # The inner struct's own C typedef must actually be
                # emitted into the .cpp preamble too — gen_module's
                # existing "struct layout(s) needed by this module's
                # compiled generator method(s)" collection only knew
                # about a generator METHOD's own `self`-struct and a
                # generator's declared PARAMETER structs, neither of
                # which covers a struct reached only indirectly through
                # a field's pointer type, like `IMAP4` here (reached
                # via `Idler`'s own `_imap` field). Reuses the SAME
                # `_cpp_param_struct_names` set that collection already
                # reads from, rather than inventing a second one.
                gen._cpp_param_struct_names.add(outer_ft[:-2])
                return f"(({outer_ft})(self->{gimple_ctypes._safe_field(e.obj.member)}))->{gimple_ctypes._safe_field(e.member)}"
        # Non-self member access: entry.name, os.path, etc. A struct-
        # POINTER-typed local/parameter (see bugs/hard/CODEGEN_
        # generator_struct_typed_param_refused.md — e.g. dis.py's
        # `arg_resolver: ArgResolver` generator parameter) needs `->`,
        # not `.`, same as `self` above; every other non-self case
        # (a module-object field like os.path, a scalar local with no
        # real struct type) keeps the existing `.` form unchanged.
        obj_expr = gen._cpp_expr(e.obj) if not isinstance(e.obj, gimple_ctypes.IdentExpr) else e.obj.name
        if isinstance(e.obj, gimple_ctypes.IdentExpr):
            _ptr_struct = gen._cpp_struct_ptr_local(e.obj.name)
            if _ptr_struct:
                # Bound-method-as-VALUE off a struct-pointer local/
                # param, not immediately called — same rationale
                # (`_struct_method_names` checked FIRST, ahead of the
                # field lookup — see the `self.<method>` case above's
                # comment for why "absent from struct_field_types"
                # alone isn't proof) and mechanism as the
                # `self.<method>` case above (this is its non-self
                # twin).
                if e.member in gen._struct_method_names.get(_ptr_struct, ()):
                    _sym = gen._struct_method_csym(_ptr_struct, e.member, '')
                    gen._cpp_struct_method_refs.add((_ptr_struct, e.member))
                    return (f"(({gimple_ctypes._CPP_CALLABLE_CTYPE})"
                            f"([&]() -> int64_t {{ return {_sym}({obj_expr}); }}))")
                return f"{obj_expr}->{gimple_ctypes._safe_field(e.member)}"
        # A member READ rooted at a DECLARED local typed as a plain
        # scalar — including multi-level chains like
        # `cm.unraisable.exc_value` (test_ctypes/test_random_things.py),
        # where EVERY intermediate link lowers recursively: the
        # innermost `cm.unraisable` becomes `0`, and the outer level
        # would then emit `0.object` — which C++ tokenizes as the float
        # literal `0.` followed by an identifier ("exponent has no
        # digits"). Walk to the chain's root identifier and check ITS
        # declared ctype BEFORE any recursion-shaped emission. Mirror the
        # module-member stub convention: emit 0, diagnosed via
        # _debug_note, so the body still COMPILES. Must sit OUTSIDE the
        # `isinstance(e.obj, IdentExpr)` block above precisely so it
        # also covers chains whose obj is itself a MemberExpr.
        _chain_root = e
        while isinstance(_chain_root, gimple_ctypes.MemberExpr):
            _chain_root = _chain_root.obj
        if isinstance(_chain_root, gimple_ctypes.IdentExpr) \
                and gen._cpp_declared is not None \
                and gen._cpp_declared.get(_chain_root.name) in (
                    'int', 'int64_t', 'double', '_Bool'):
            gimple_ctypes._debug_note('stubbed operation',
                        f'generator-body attribute read on opaque '
                        f'scalar local {_chain_root.name}.{e.member}')
            return '0'
        return f"{obj_expr}.{gimple_ctypes._safe_field(e.member)}"
    if isinstance(e, gimple_ctypes.LambdaExpr):
        # A `lambda` used as a VALUE inside a generator body (e.g.
        # pickletools.py's `_genops`: `getpos = lambda: None`, the
        # sibling branch of `getpos = data.tell` above) — see
        # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.
        # Lowered as a genuine, capturing native C++ lambda (this
        # coroutine codegen targets real C++20, unlike the plain
        # GIMPLE path's `_lower_LambdaExpr`, whose much heavier
        # "lift to a top-level C function + explicit env struct"
        # machinery exists only because -fgimple can't take the
        # address of a stack local at all — a constraint that simply
        # doesn't apply here) — implicitly convertible to this
        # model's one callable-value declared type
        # (`_CPP_CALLABLE_CTYPE`, see its own docstring).
        #
        # `[&]` (capture everything by reference): every local this
        # coroutine body can see lives in the coroutine's own
        # heap-allocated frame (not an ordinary stack frame that could
        # go out of scope while the callable value is still held), so
        # a reference capture stays valid for as long as the
        # coroutine itself does — exactly the lifetime the callable
        # value needs (it may be invoked after further `co_await`/
        # `co_yield` suspension points, e.g. `_genops`' own
        # `pos = getpos()` on the very next loop iteration).
        #
        # The zero-Python-argument shape (`_CPP_CALLABLE_CTYPE`) and a
        # SINGLE plain parameter, no `*`/`**`/default (`_CPP_CALLABLE_
        # CTYPE_1ARG` — added for enum.py's `key=lambda m: m._sort_
        # order_`, a `sorted(..., key=...)` comparator) are the only
        # shapes supported — anything wider (2+ params, or a `*a`/`**k`
        # forwarding param like fsutil.py's `lambda *a, **k: _walk(*a,
        # walk=_files, **k)`) is refused honestly rather than guessing a
        # signature; the fsutil.py occurrence is additionally blocked by
        # the separate, deliberately unfixed bugs/hard/CODEGEN_args_
        # kwargs_signature_assumed_forwarding_only.md gap regardless.
        if len(e.params) > 1 or (e.params and (
                e.params[0][0].startswith('*') or e.params[0][1] is not None)):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "a `lambda` with more than one parameter, a `*`/`**`"
                "-forwarding parameter, or a parameter default is not "
                "supported as a value inside a compiled generator/"
                "coroutine body (only a zero-argument lambda or a "
                "single plain-parameter lambda, e.g. `lambda: None` / "
                "`lambda x: x`, is supported)")
        if e.params:
            _pname = e.params[0][0]
            _hint = gen._cpp_pending_lambda_param_ctype
            gen._cpp_pending_lambda_param_ctype = None
            _pctype = _hint if _hint is not None else 'int64_t'
            _declared_here = gen._cpp_declared
            _had_prev = _declared_here is not None and _pname in _declared_here
            _prev = _declared_here.get(_pname) if _had_prev else None
            if _declared_here is not None:
                _declared_here[_pname] = _pctype
            try:
                _body = gen._cpp_expr(e.body)
            finally:
                if _declared_here is not None:
                    if _had_prev:
                        _declared_here[_pname] = _prev
                    else:
                        del _declared_here[_pname]
            # The C++ lambda's own parameter is always `int64_t` (the
            # boxed value `std::function<int64_t(int64_t)>` actually
            # passes) -- a real struct-pointer ctype `_pctype` (from the
            # `sorted(..., key=...)` call site below, when the
            # iterable's element type is statically known) is recovered
            # by an immediate cast into a same-named local shadowing the
            # boxed parameter, so `_cpp_expr(e.body)` above's ordinary
            # `<name>.<field>` struct-field lowering (which resolved
            # `_pname`'s ctype via `self._cpp_declared` set above) sees
            # a real, correctly-typed local.
            _boxed = f"{_pname}__boxed"
            _cast = f"{_pctype} {_pname} = ({_pctype})({_boxed});"
            return (f"(({gimple_ctypes._CPP_CALLABLE_CTYPE_1ARG})"
                    f"([&](int64_t {_boxed}) -> int64_t "
                    f"{{ {_cast} return (int64_t)({_body}); }}))")
        _body = gen._cpp_expr(e.body)
        return (f"(({gimple_ctypes._CPP_CALLABLE_CTYPE})"
                f"([&]() -> int64_t {{ return (int64_t)({_body}); }}))")
    if isinstance(e, gimple_ctypes.UnaryOp):
        op = {'not': '!'}.get(e.op, e.op)
        return f"({op}{gen._cpp_expr(e.operand)})"
    if isinstance(e, gimple_ctypes.TernaryExpr):
        return f"({gen._cpp_expr(e.condition)} ? {gen._cpp_expr(e.then_val)} : {gen._cpp_expr(e.else_val)})"
    if isinstance(e, gimple_ctypes.BinaryOp):
        if e.op == '//':
            # Python floor division — uses the same __mojo_floordiv
            # runtime helper the GIMPLE path's _lower_floordiv emits (a
            # plain C `/` truncates toward zero, which differs for
            # negative operands; this helper floors like Python).
            return f"__mojo_floordiv({gen._cpp_expr(e.left)}, {gen._cpp_expr(e.right)})"
        if e.op == '**':
            return f"pow({gen._cpp_expr(e.left)}, {gen._cpp_expr(e.right)})"
        if e.op == '+':
            # String concatenation (`current + part`, pprint.py's shape;
            # `path[:-len('.dylib')] + suffix`, dyld.py's `_inject`) →
            # mojo_str_cat, mirroring the GIMPLE path's char* + char*
            # lowering. Fires ONLY when BOTH operands are string-typed
            # (see _is_str_operand just below). A genuinely numeric
            # `a + b` (both declared int64_t) and a HETEROGENEOUS
            # `total + x` (int64_t += char*, the async runner's
            # `total = total + x` shape) both fall through to the plain
            # `+` below — never mis-cat.
            def _is_str_operand(node):
                if isinstance(node, gimple_ctypes.StringLiteral):
                    return True
                if isinstance(node, gimple_ctypes.IdentExpr) and gen._cpp_declared is not None:
                    return gen._cpp_declared.get(node.name) == 'char *'
                # A slice/subscript of a string (`path[:-len('.dylib')]`,
                # dyld.py's `_inject`) or a call whose trusted module
                # return type is char* (`int64_t_basename(p)`) also
                # produces a genuine char* in this body model — the
                # narrow IdentExpr/literal check above left those to the
                # raw `+` fallthrough, an invalid char* + char* C++
                # operand combination.
                try:
                    return gimple_exprtypes._infer_simple_expr_ctype(
                        node, gen._cpp_declared,
                        getattr(gen, '_cpp_gen_self_fields', None),
                        gen._async_api,
                        fn_return_types=_cpp_trusted_fn_return_types(gen),
                    ) == 'char *'
                except Exception:
                    return False
            if _is_str_operand(e.left) and _is_str_operand(e.right):
                return (f"mojo_str_cat((char *)({gen._cpp_expr(e.left)}), "
                        f"(char *)({gen._cpp_expr(e.right)}))")
        if e.op == '%':
            _pf = _cpp_percent_format(gen, e)
            if _pf is not None:
                return _pf
        if e.op in ('in', 'not in'):
            # `'x' not in s` is parsed as a BinaryOp (mojo_compiler.py),
            # not a CompareChain — so the CompareChain 'in'/'not in' branch
            # above never fires for the overwhelmingly common single-membership
            # test. Reuse the same runtime-helper dispatch
            # (_cpp_in_link: mojo_str_contains / mojo_list_contains_* /
            # mojo_dict_contains / mojo_set_contains_*), keyed on the right
            # operand's declared C++ type. `not in` is the negation.
            # Without this the raw `in`/`not in` text was emitted into C++
            # (`not` is a C++ keyword, `in` is not an operator) — mimetypes.py's
            # `if '\\0' not in ctype:` is the exact failure.
            a = gen._cpp_expr(e.left)
            b = gen._cpp_expr(e.right)
            return gen._cpp_in_link(a, e.left, b, e.right, negate=(e.op == 'not in'))
        op = gimple_ctypes._GD_BIN_OPS.get(e.op, e.op)
        return f"({gen._cpp_expr(e.left)} {op} {gen._cpp_expr(e.right)})"
    if isinstance(e, gimple_ctypes.CompareChain):
        links = []
        for i, op in enumerate(e.ops):
            a_node = e.operands[i]
            b_node = e.operands[i + 1]
            a = gen._cpp_expr(a_node)
            b = gen._cpp_expr(b_node)
            if op in ('in', 'not in'):
                links.append(gen._cpp_in_link(a, a_node, b, b_node,
                                               negate=(op == 'not in')))
            else:
                links.append(f"({a} {gimple_ctypes._GD_BIN_OPS.get(op, op)} {b})")
        return '(' + ' && '.join(links) + ')'
    if isinstance(e, gimple_ctypes.DictExpr):
        pairs = [f"{{{gen._cpp_expr(k)}, {gen._cpp_expr(v)}}}" for k, v in e.pairs]
        return '{' + ', '.join(pairs) + '}'
    if isinstance(e, gimple_ctypes.Comprehension):
        # Comprehension as a value: build an empty MojoList. The generator
        # body's statements still compile; the comprehension result is an
        # honest empty-collection stub (real comprehension lowering needs
        # a loop, which an expression slot can't hold).
        return "mojo_list_new ()"
    if isinstance(e, gimple_ctypes.SetExpr):
        return '{' + ', '.join(gen._cpp_expr(el) for el in e.elements) + '}'
    if isinstance(e, gimple_ctypes.ListExpr):
        return '{' + ', '.join(gen._cpp_expr(el) for el in e.elements) + '}'
    if isinstance(e, gimple_ctypes.TupleExpr):
        if not e.elements: return '{}'
        inner = ', '.join(gen._cpp_expr(el) for el in e.elements)
        return '{' + inner + '}' if len(e.elements) != 1 else '{' + inner + ',}'
    if isinstance(e, gimple_ctypes.WalrusExpr):
        # `x := expr` assigns x and yields the value
        name = e.name
        val = gen._cpp_expr(e.value)
        return f"({name} = {val})"
    if isinstance(e, gimple_ctypes.CallExpr):
        # A `*`/`**`-unpack call ARGUMENT (this project's parser wraps
        # a spread argument in UnaryOp(op='*'/'**', operand=...) — see
        # this repo's own CLAUDE.md) has no case anywhere in this
        # coroutine-body expression emitter's call-argument lowering
        # (every call shape below just does a flat `', '.join(self.
        # _cpp_expr(a) for a in e.args)` or an equivalent). Left
        # unchecked, such an argument falls through to the generic
        # UnaryOp case further down (`op == '**'` -> literally `(**x)`),
        # which g++ parses as a double pointer-dereference of a
        # MojoDict*/MojoList* local, not an argument-unpack — a silent
        # MISCOMPILE (invalid/nonsensical C++), not just a missed
        # feature. Real: codecs.py's `iterencode`/`iterdecode` doing
        # `getincrementalencoder(encoding)(errors, **kwargs)` — the
        # callee is itself a dynamically-obtained class, so even a
        # correct implementation would need to know that class's real
        # parameter names at compile time, which this scalar body model
        # has no way to discover. Refuse the whole generator honestly
        # here (falls the module back to interpreting it from source)
        # instead of ever reaching one of those broken emission sites —
        # same family as bugs/hard/CODEGEN_generator_lambda_expr_
        # unsupported.md's existing LambdaExpr-argument refusal.
        #
        # One narrow, provably-safe exception: `f(pos..., **kwargs_var)`
        # where `f` is a STATICALLY-KNOWN local free function (its real
        # parameter names/defaults are known at compile time, unlike the
        # codecs.py case above). See bugs/COMPILE_FAIL_Tools_c-analyzer_
        # c_analyzer___init__.md — an earlier attempt at this special
        # case (reverted, never merged) filled the "gap" between the
        # given positional args and the callee's `**kwargs` slot with
        # the callee's STATIC DEFAULT VALUES, ignoring what the caller's
        # kwargs dict actually contains at runtime — `target(i,
        # **kwargs)` with `kwargs={'b': 5}` silently computed `b=100`
        # (the hardcoded default) instead of the real override `b=5`:
        # a WORKING WRONG ANSWER, worse than an honest refusal.
        # `_cpp_try_kwargs_forward_call` instead resolves each gap slot
        # with a REAL runtime dict lookup (falling back to the static
        # default only when the key is genuinely absent at runtime),
        # and only ever fires when it can prove that's exactly right
        # (see its own docstring for the full shape it requires) —
        # returning None (never guessing) for anything else, which
        # falls straight through to the honest refusal below.
        if (isinstance(e.func, gimple_ctypes.IdentExpr) and e.args
                and isinstance(e.args[-1], gimple_ctypes.UnaryOp) and e.args[-1].op == '**'
                and not any(isinstance(a, gimple_ctypes.UnaryOp) and a.op in ('*', '**')
                            for a in e.args[:-1])):
            _kwfwd = gen._cpp_try_kwargs_forward_call(e)
            if _kwfwd is not None:
                return _kwfwd
        if any(isinstance(a, gimple_ctypes.UnaryOp) and a.op in ('*', '**') for a in e.args):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "a `*`/`**`-unpack call argument is not supported in a "
                "compiled generator/coroutine body")
        # Simple function call in generator body (e.g. os.path.join(a, b))
        if isinstance(e.func, gimple_ctypes.MemberExpr):
            # `.format(...)` on a string literal — mirrors the GIMPLE
            # path's _lower_string_method_call stub (returns the format
            # string itself, diagnosed via _debug_note; the interpolation
            # isn't performed). compileall.py's `print('Listing
            # {!r}...'.format(dir))` shape.
            if e.func.member == 'format' and isinstance(e.func.obj, gimple_ctypes.StringLiteral):
                gimple_ctypes._debug_note('stubbed operation', 'generator-body str.format()')
                return gen._cpp_expr(e.func.obj)
            # Known module-attribute calls — a module global object
            # (os.path / math / sys, each an int64_t MojoDict* in this
            # body model) followed by a STATICALLY-KNOWN member function.
            # Mirrors the GIMPLE path's own os.path.* / math.* lowering:
            # the module object itself is never dereferenced, the member
            # call maps straight onto a runtime helper / math.h function.
            # Without this, `os.path.join(a, b)` / `math.isnan(x)` emit
            # as `_root_globals.os.path.join(...)` — invalid C++.
            if isinstance(e.func.obj, gimple_ctypes.MemberExpr) \
                    and isinstance(e.func.obj.obj, gimple_ctypes.IdentExpr) \
                    and e.func.obj.obj.name == 'os' and e.func.obj.member == 'path':
                a = [gen._cpp_expr(x) for x in e.args]
                if e.func.member == 'join' and len(a) >= 1:
                    # os.path.join(a, b, ...) → nested mojo_path_join
                    acc = a[0]
                    for nxt in a[1:]:
                        acc = f"mojo_path_join((char *)({acc}), (char *)({nxt}))"
                    return acc
                # os.path.isdir/exists(p) — the GIMPLE path's own
                # os.path.* dispatch (_lower_call) already has these
                # wired to real runtime helpers (`marker` is an unused
                # leading int64_t param, an existing overload-
                # disambiguation convention, not this call's concern).
                # Before this, only `.join` was handled here; every
                # OTHER os.path.* member call (isdir/exists/isabs/...)
                # fell through to the generic MemberExpr fallback below,
                # which emitted the raw, invalid C++ `os.path.isdir(p)`
                # (`os` was never a real declared variable/namespace in
                # this scalar body model) — "'os' was not declared in
                # this scope". Found via Tools/build/update_file.py's
                # own `os.path.isdir(tmpfile)`.
                if e.func.member == 'isdir' and len(a) == 1:
                    return f"int_isdir(0, (int64_t)(char *)({a[0]}))"
                if e.func.member == 'exists' and len(a) == 1:
                    return f"int_exists(0, (int64_t)(char *)({a[0]}))"
                # isfile/normpath/relpath: mirror the GIMPLE path's own
                # honest stubs for these exactly (isfile -> always
                # false; normpath/relpath -> identity), rather than
                # inventing different behavior for this narrower body
                # model.
                if e.func.member == 'isfile' and len(a) == 1:
                    return '0'
                if e.func.member in ('normpath', 'relpath') and len(a) >= 1:
                    return a[0]
                # basename/dirname/splitext/expanduser/abspath — the
                # remaining real-runtime os.path helpers, mirroring the
                # GIMPLE path's own dispatch (mojo_runtime.h's
                # int64_t_basename/int64_t_splitext/int64_t_expanduser/
                # int_abspath/int_dirname). Without these, dyld.py's
                # generator bodies emitted raw `os.path.basename(name)`
                # C++ ("'os' was not declared in this scope; did you mean
                # 'cos'").
                if e.func.member == 'basename' and len(a) == 1:
                    return f"int64_t_basename((char *)({a[0]}))"
                if e.func.member == 'dirname' and len(a) == 1:
                    return f"(char *)int_dirname(0, (int64_t)(char *)({a[0]}))"
                if e.func.member == 'splitext' and len(a) == 1:
                    return f"int64_t_splitext((char *)({a[0]}))"
                if e.func.member == 'expanduser' and len(a) == 1:
                    return f"int64_t_expanduser((char *)({a[0]}))"
                if e.func.member == 'abspath' and len(a) == 1:
                    return f"(char *)int_abspath(0, (int64_t)(char *)({a[0]}))"
            if isinstance(e.func.obj, gimple_ctypes.IdentExpr) and e.func.obj.name == 'math':
                a = [gen._cpp_expr(x) for x in e.args]
                if e.func.member in ('isnan', 'isinf', 'floor', 'ceil', 'fabs',
                                     'sqrt', 'log', 'log10', 'exp', 'sin',
                                     'cos', 'tan', 'fsum', 'isfinite') and a:
                    return f"std::{e.func.member}((double)({a[0]}))"
                if e.func.member == 'isclose' and len(a) >= 2:
                    return (f"std::abs((double)({a[0]}) - (double)({a[1]})) "
                            f"< 1e-9")
            # self.method(...) / <struct-ptr local>.method(...) — this
            # codegen's structs are plain C structs with no real C++
            # member functions (only field layout is re-emitted into
            # the .cpp preamble — see gen_module's own "Struct layout(s)
            # needed by this module's compiled generator method(s)"
            # comment), so a call must go through the method's own
            # mangled C symbol (obj_ptr, args...) — `obj->method(args)`/
            # `obj.method(args)` C++ member-call syntax doesn't compile
            # against a plain struct at all (confirmed via a direct
            # repro: `struct Counter has no member named 'bump'`).
            # `_cpp_struct_method_refs` records which (struct, method)
            # pairs actually get called so gen_module's final .cpp
            # assembly can declare each one's real signature `extern
            # "C"`, mirroring the existing _cpp_module_func_refs
            # pattern for free functions. See bugs/hard/CODEGEN_
            # generator_struct_typed_param_refused.md.
            _cpp_self_struct = getattr(gen, '_cpp_gen_self_struct', None)
            # `<container-local>.append(v)` / `<set-local>.add(v)` — a
            # mutating container-method call on a local whose declared
            # type is a real container pointer (`lines.append("alpha")`
            # after `lines = []`, ftplib.py's `FTP.mlsd`). The generic
            # `{obj}.{member}(...)` fallback below emits C++ member-call
            # syntax, which is invalid on a plain struct pointer with no
            # member functions ("request for member 'append' in 'lines',
            # which is of non-class type 'int64_t'" when untyped — the
            # pre-container-typing symptom; "no member named 'append'"
            # once typed). Lowers through the same runtime primitives the
            # subscript-write branch already uses, wrapped in a comma
            # expression so it works in both statement and expression
            # slots (the runtime append/add helpers return void). The
            # appended value's own inferred ctype updates the local's
            # unified element-type registry (same join rule the literal-
            # init helper uses), so later iteration/subscript reads pick
            # the right accessor.
            if (isinstance(e.func.obj, gimple_ctypes.IdentExpr)
                    and gen._cpp_declared is not None
                    and e.func.obj.name in gen._cpp_declared):
                _cont_name = e.func.obj.name
                _cont_ct = gen._cpp_declared.get(_cont_name)
                if (_cont_ct == 'MojoList *' and e.func.member == 'append'
                        and len(e.args) == 1):
                    _avct = gimple_exprtypes._infer_simple_expr_ctype(
                        e.args[0], gen._cpp_declared,
                        getattr(gen, '_cpp_gen_self_fields', None),
                        gen._async_api) or 'int64_t'
                    _reg = getattr(gen, '_cpp_list_local_elem_types', None)
                    if _reg is not None:
                        _prev = _reg.get(_cont_name)
                        _reg[_cont_name] = _avct if _prev is None else (
                            gimple_ctypes.TypeLattice.join(_prev, _avct) or 'int64_t')
                    _a = gen._cpp_expr(e.args[0])
                    _eff = (_reg or {}).get(_cont_name, _avct)
                    if _eff == 'char *':
                        return f"(mojo_list_append_str({_cont_name}, (char *)({_a})), 0)"
                    if _eff == 'double':
                        return f"(mojo_list_append_double({_cont_name}, (double)({_a})), 0)"
                    return f"(mojo_list_append_int({_cont_name}, (int64_t)({_a})), 0)"
                if (_cont_ct == 'MojoSet *' and e.func.member == 'add'
                        and len(e.args) == 1):
                    _avct = gimple_exprtypes._infer_simple_expr_ctype(
                        e.args[0], gen._cpp_declared,
                        getattr(gen, '_cpp_gen_self_fields', None),
                        gen._async_api) or 'int64_t'
                    _a = gen._cpp_expr(e.args[0])
                    if _avct == 'char *':
                        return f"(mojo_set_add_str({_cont_name}, (char *)({_a})), 0)"
                    return f"(mojo_set_add_int({_cont_name}, (int64_t)({_a})), 0)"
            if isinstance(e.func.obj, gimple_ctypes.IdentExpr) and e.func.obj.name == 'self' \
                    and _cpp_self_struct:
                args = [gen._cpp_expr(a) for a in e.args]
                _sym = gen._struct_method_csym(_cpp_self_struct, e.func.member, '')
                gen._cpp_struct_method_refs.add((_cpp_self_struct, e.func.member))
                args = _cpp_pad_struct_method_call_args(
                    gen, _sym,
                    f"{_cpp_self_struct}_{gimple_ctypes._safe_name(e.func.member)}",
                    args)
                return f"{_sym}(self{', ' + ', '.join(args) if args else ''})"
            # `cls.method(...)` inside a @classmethod generator — the
            # SAME name-only resolution mechanism the ordinary
            # (non-coroutine) GIMPLE path's own CallExpr/MemberExpr
            # lowering already uses for `cls.method(...)` (see that
            # method's own "cls.method(...) inside a @classmethod"
            # comment): resolved purely by NAME via `_cpp_gen_self_
            # struct` (the enclosing struct, known statically the same
            # way the classmethod eligibility check derives it) plus
            # `self._classmethod_names`/`func_return_types` — no real
            # runtime `cls` VALUE is ever needed, mirroring the `self.
            # method(...)` case immediately above. Only a genuine
            # compiled classmethod/static/ordinary method of the
            # enclosing struct is accepted; a call to another compiled
            # GENERATOR method via `cls` (e.g. Lib/enum.py's Flag.
            # _iter_member_by_def_: `cls._iter_member_by_value_(value)`)
            # is deliberately NOT handled here — that needs its own
            # coroutine-construction call convention (mirroring the
            # ordinary path's `_generator_method_api`/`_gm_api`
            # handling), which this fix does not add — refuse honestly
            # instead of emitting a call to a symbol that was never
            # compiled as an ordinary C function. See bugs/CODEGEN_
            # generator_function_Lib_enum.md's 2026-08-21 update.
            if isinstance(e.func.obj, gimple_ctypes.IdentExpr) and e.func.obj.name == 'cls' \
                    and _cpp_self_struct:
                _cls_method = e.func.member
                _cls_mangled = f"{_cpp_self_struct}_{_cls_method}"
                # Exclude another compiled GENERATOR method (a real
                # `@classmethod` generator is ALSO in `_classmethod_
                # names`, which alone would wrongly accept this shape
                # and then call a symbol that was never compiled as an
                # ordinary C function — see this branch's own comment
                # above and `_cls_refs_supported`'s identical guard).
                if (_cls_method not in gen._struct_generator_method_names.get(
                        _cpp_self_struct, ())
                        and (_cls_mangled in gen._classmethod_names
                             or _cls_mangled in gen.func_return_types)):
                    args = [gen._cpp_expr(a) for a in e.args]
                    _sym = gen._struct_method_csym(_cpp_self_struct, _cls_method, '')
                    gen._cpp_struct_method_refs.add((_cpp_self_struct, _cls_method))
                    args = _cpp_pad_struct_method_call_args(
                        gen, _sym,
                        f"{_cpp_self_struct}_{gimple_ctypes._safe_name(_cls_method)}",
                        args)
                    return f"{_sym}(cls{', ' + ', '.join(args) if args else ''})"
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    f"cls.{_cls_method}(...): only a call to a real "
                    "compiled classmethod/static method of the "
                    "enclosing class is supported for `cls.<method>"
                    "(...)` calls in a compiled generator/coroutine "
                    "body (not e.g. a call to another compiled "
                    "generator method, which needs separate "
                    "coroutine-construction handling this fix does "
                    "not add)")
            if isinstance(e.func.obj, gimple_ctypes.IdentExpr):
                _obj_struct = gen._cpp_struct_ptr_local(e.func.obj.name)
                if _obj_struct:
                    args = [gen._cpp_expr(a) for a in e.args]
                    _sym = gen._struct_method_csym(_obj_struct, e.func.member, '')
                    gen._cpp_struct_method_refs.add((_obj_struct, e.func.member))
                    args = _cpp_pad_struct_method_call_args(
                        gen, _sym,
                        f"{_obj_struct}_{gimple_ctypes._safe_name(e.func.member)}",
                        args)
                    return f"{_sym}({e.func.obj.name}{', ' + ', '.join(args) if args else ''})"
            # A member call on a MODULE-GLOBAL object whose member isn't a
            # statically-known function (os.py's `sys.audit(...)`,
            # compileall.py's `os.fspath(...)`, mimetypes.py's
            # `_winreg.EnumKey(...)`, modulefinder.py's
            # `dis._find_store_names(...)`): the module object is an
            # opaque int64_t MojoDict* and its members are runtime-lookup
            # methods this scalar body model can't dispatch. Mirror the
            # GIMPLE path's _stub_result convention for an unknown
            # module-member call: emit 0 (diagnosed via _debug_note) so
            # the body still COMPILES, matching how the .ci side stubs
            # the same shape (e.g. `int64_t.isnan() stubbed`) rather than
            # emitting invalid `_root_globals.sys.audit(...)` C++.
            if isinstance(e.func.obj, gimple_ctypes.IdentExpr) \
                    and gen._cpp_declared is not None \
                    and e.func.obj.name not in gen._cpp_declared \
                    and e.func.obj.name in gen._cpp_early_global_names:
                gimple_ctypes._debug_note('stubbed operation',
                            f'generator-body module-member call '
                            f'{e.func.obj.name}.{e.func.member}()')
                return '0'
            # `<char*-typed obj>.replace(old, new)` — a real string
            # method call on a local/self-field this narrow body model
            # already knows is `char *` (not a struct-pointer/module
            # object), which the generic `{obj}.{member}(...)` fallback
            # just below can't handle at all (C++ has no member
            # functions on a raw `char *`). Routes through the SAME
            # `_char_replace_impl` runtime helper the ordinary GIMPLE
            # path's own `str.replace(...)` lowering already uses
            # (already declared via the wholesale `#include
            # <mojo_runtime.h>` every generated .cpp file has — no new
            # extern declaration needed). Real: save_env.py's
            # `resource_info`: `name.replace('.', '_')`.
            _str_obj_ctype = _cpp_receiver_ctype(gen, e.func.obj)
            if (_str_obj_ctype == 'char *' and e.func.member == 'replace'
                    and len(e.args) == 2):
                _obj_expr = gen._cpp_expr(e.func.obj)
                _a0 = gen._cpp_expr(e.args[0])
                _a1 = gen._cpp_expr(e.args[1])
                return (f"(char *)_char_replace_impl((int64_t)(char *)({_obj_expr}), "
                        f"(int64_t)(char *)({_a0}), (int64_t)(char *)({_a1}))")
            # `<char*-typed obj>.strip()`/`.lstrip()`/`.rstrip()` (0 or 1
            # `chars` arg) / `.lower()`/`.upper()` (0 args) —
            # same rationale/mechanism as `.replace` just above, routed
            # through the SAME `mojo_str_lstrip`/`mojo_str_rstrip`/
            # `mojo_str_rstrip_chars`/`mojo_str_lstrip_chars`/
            # `string_strip`/`string_lower`/`string_upper` runtime
            # helpers the ordinary GIMPLE path's own char* method-call
            # dispatch already uses (`gimple_gen_methods.py`'s
            # `_CSTR_METHODS` table) — reused, not reinvented. `.strip
            # (chars)` with an argument mirrors that same table's own
            # behavior (the `chars` arg is accepted syntactically but
            # ignored — only `.lstrip`/`.rstrip` have a real chars-aware
            # helper; matching, not a new limitation). Real:
            # zipfile/_path/__init__.py's `_ancestry`: `path = path.
            # rstrip(posixpath.sep)`.
            if _str_obj_ctype == 'char *' and e.func.member in ('strip', 'lstrip', 'rstrip') \
                    and len(e.args) in (0, 1):
                _obj_expr = gen._cpp_expr(e.func.obj)
                if e.func.member == 'strip' or not e.args:
                    _fn = {'strip': 'string_strip', 'lstrip': 'mojo_str_lstrip',
                           'rstrip': 'mojo_str_rstrip'}[e.func.member]
                    return f"(char *){_fn}((char *)({_obj_expr}))"
                _fn = 'mojo_str_lstrip_chars' if e.func.member == 'lstrip' else 'mojo_str_rstrip_chars'
                _a0 = gen._cpp_expr(e.args[0])
                return f"(char *){_fn}((char *)({_obj_expr}), (char *)({_a0}))"
            if _str_obj_ctype == 'char *' and e.func.member in ('lower', 'upper') and not e.args:
                _obj_expr = gen._cpp_expr(e.func.obj)
                _fn = 'string_lower' if e.func.member == 'lower' else 'string_upper'
                return f"(char *){_fn}((char *)({_obj_expr}))"
            # `<char*-typed obj>.startswith(prefix)` / `.endswith(suffix)`
            # — real `int`-returning runtime helpers (`mojo_str_
            # startswith`/`mojo_str_endswith`), same receiver-ctype gate
            # as the string methods just above.
            if _str_obj_ctype == 'char *' and e.func.member in ('startswith', 'endswith') \
                    and len(e.args) == 1:
                _obj_expr = gen._cpp_expr(e.func.obj)
                _fn = 'mojo_str_startswith' if e.func.member == 'startswith' else 'mojo_str_endswith'
                _a0 = gen._cpp_expr(e.args[0])
                return f"({_fn}((char *)({_obj_expr}), (char *)({_a0})) != 0)"
            # `<char*-typed-or-literal obj>.join(iterable)` — a real
            # `str.join(...)` call on either a declared/self-field `char *`
            # separator OR (unlike the string methods just above, which
            # only recognize a receiver `_cpp_receiver_ctype` can resolve
            # to a known local/field) a bare STRING LITERAL separator —
            # `";".join(facts)`, ftplib.py's `mlsd`. `_cpp_receiver_ctype`
            # has no StringLiteral case (nothing else needs one), so this
            # is checked directly here rather than widening that shared
            # helper. Routes through the SAME `mojo_str_join(sep, parts)`
            # runtime helper the ordinary GIMPLE path's own `str.join`
            # lowering already uses (gimple_gen_methods.py); the argument
            # is cast straight to `MojoList *` (this emitter's other
            # container-typed-call sites, e.g. the `sorted()` case above,
            # do the same unconditional cast rather than the ordinary
            # path's int64_t-widening dance, since a coroutine-body
            # argument that isn't already list-shaped has no narrower
            # static type to widen from here).
            if e.func.member == 'join' and len(e.args) == 1 and (
                    _str_obj_ctype == 'char *'
                    or isinstance(e.func.obj, gimple_ctypes.StringLiteral)):
                _obj_expr = gen._cpp_expr(e.func.obj)
                _a0 = gen._cpp_expr(e.args[0])
                return (f"(char *)mojo_str_join((char *)({_obj_expr}), "
                        f"(MojoList *)({_a0}))")
            # `<dict-typed obj>.get(key)` / `.get(key, default)` — a real
            # dict method call on a local/self-field this narrow body
            # model already knows is `MojoDict *`, which (like `.replace`
            # just above) the generic `{obj}.{member}(...)` fallback
            # can't handle (MojoDict is an opaque C struct pointer with
            # no real C++ member functions — g++ rejected the raw
            # `self->map.get(k)` this fallback used to emit outright).
            # Routes through the SAME mojo_dict_get_int/_double/_str
            # runtime helpers the ordinary (non-generator) GIMPLE path's
            # own dict `.get()`/`d[k]` lowering already uses (see
            # _lower_call's/_lower_subscript's identical three-way
            # dispatch) — reused, not a fresh mechanism. The dict's
            # VALUE ctype comes from the SAME `self._field_dict_val_
            # types` registry `_infer_simple_expr_ctype`'s struct-
            # pointer-yield support (below) already resolves it from —
            # a struct-pointer value type is read back via
            # mojo_dict_get_int (pointers are stored as int64_t in this
            # dict representation, same convention _pack_kwargs_dict's
            # own docstring documents for "ints, doubles, pointers") and
            # cast back to the real pointer type. Real: Lib/enum.py's
            # `Flag._iter_member_by_value_`: `cls._value2member_map_.
            # get(val)` returns a `Flag *`. See
            # CODEGEN_generator_function_Lib_enum.md's 2026-08-20
            # update.
            if (_str_obj_ctype == 'MojoDict *' and e.func.member == 'get'
                    and len(e.args) in (1, 2)):
                _dict_val_ct = None
                if (isinstance(e.func.obj, gimple_ctypes.MemberExpr)
                        and isinstance(e.func.obj.obj, gimple_ctypes.IdentExpr)
                        and e.func.obj.obj.name == 'self' and _cpp_self_struct):
                    _dict_val_ct = gen._field_dict_val_types.get(
                        _cpp_self_struct, {}).get(e.func.obj.member)
                elif (isinstance(e.func.obj, gimple_ctypes.MemberExpr)
                        and isinstance(e.func.obj.obj, gimple_ctypes.IdentExpr)
                        and e.func.obj.obj.name == 'cls' and _cpp_self_struct):
                    # `cls.<class-attr dict>.get(...)`'s VALUE ctype —
                    # the class-level-global sibling of
                    # `_field_dict_val_types` above, keyed by the
                    # mangled global name (see `_class_attrs`'s own
                    # docstring for that naming).
                    _cls_gname = gen._class_attrs.get(
                        _cpp_self_struct, {}).get(e.func.obj.member)
                    if _cls_gname is not None:
                        _dict_val_ct = gen._global_dict_val_types.get(_cls_gname)
                _obj_expr = gen._cpp_expr(e.func.obj)
                _key_expr = gen._cpp_dict_key_expr(e.args[0], gen._cpp_expr(e.args[0]))
                if _dict_val_ct == 'char *':
                    return f"mojo_dict_get_str((MojoDict *)({_obj_expr}), {_key_expr})"
                if _dict_val_ct == 'double':
                    return f"mojo_dict_get_double((MojoDict *)({_obj_expr}), {_key_expr})"
                if (isinstance(_dict_val_ct, str) and _dict_val_ct.endswith(' *')
                        and _dict_val_ct[:-2] in gen.struct_field_types):
                    return (f"({_dict_val_ct})mojo_dict_get_int("
                            f"(MojoDict *)({_obj_expr}), {_key_expr})")
                return f"mojo_dict_get_int((MojoDict *)({_obj_expr}), {_key_expr})"
            # `<dict-typed obj>.copy()/.items()/.keys()/.values()` — the
            # zero-argument collection-accessor siblings of the `.get(...)`
            # case just above, same receiver-typing mechanism
            # (`_cpp_receiver_ctype`) and same runtime helpers the ordinary
            # GIMPLE path's own dict-method lowering already routes through
            # (gimple_gen_methods.py's identical `mojo_dict_*` mapping).
            # Without this, a coroutine body's `self.data.copy().items()`
            # fell to the generic `{obj}.{member}(...)` fallback and emitted
            # invalid C++ member-call syntax on an opaque struct pointer.
            # Real: Lib/weakref.py's WeakValueDictionary.items/keys:
            # `for k, wr in self.data.copy().items():`.
            if (_str_obj_ctype == 'MojoDict *' and not e.args
                    and e.func.member in ('copy', 'items', 'keys', 'values')):
                _dict_fn = {'copy': 'mojo_dict_copy', 'items': 'mojo_dict_items',
                            'keys': 'mojo_dict_keys',
                            'values': 'mojo_dict_values'}[e.func.member]
                return f"{_dict_fn}((MojoDict *)({gen._cpp_expr(e.func.obj)}))"
            # A member call on a DECLARED local whose ctype is a plain
            # scalar (`root_logger = logging.getLogger()` — the module-
            # call elision already typed `root_logger` int64_t and
            # initialized it to 0, so the value semantics are already
            # gone before this call). The generic `{obj}.{member}(...)`
            # fallback just below would emit invalid C++
            # (`root_logger.addHandler(handler)` against a raw int64_t).
            # Mirror the module-member stub convention immediately above:
            # emit 0 (diagnosed via _debug_note) so the body still
            # COMPILES. Deliberately placed AFTER the `.replace`/`.get`
            # real-method cases above (and the `.copy`/`.items()` family
            # just above) so genuinely-typed char*/MojoDict* receivers
            # keep their real lowerings.
            if isinstance(e.func.obj, gimple_ctypes.IdentExpr) \
                    and gen._cpp_declared is not None \
                    and gen._cpp_declared.get(e.func.obj.name) in (
                        'int', 'int64_t', 'double', '_Bool'):
                gimple_ctypes._debug_note('stubbed operation',
                            f'generator-body method call on opaque scalar '
                            f'local {e.func.obj.name}.{e.func.member}()')
                return '0'
            obj = gen._cpp_expr(e.func.obj)
            args = ', '.join(gen._cpp_expr(a) for a in e.args)
            return f"{obj}.{e.func.member}({args})"
        if isinstance(e.func, gimple_ctypes.IdentExpr):
            fname = e.func.name
            args = [gen._cpp_expr(a) for a in e.args]
            # Python builtins that map directly onto runtime helpers —
            # mirrors the GIMPLE path's own builtin lowering (len/range/
            # str/repr/hasattr), since the generator-body emitter shares
            # the same <mojo_runtime.h> helpers. Without this, `len(x)`,
            # `range(...)`, etc. inside a generator body would emit as
            # bare undeclared C++ calls (a real failure: pprint.py's
            # `len(object)`, argparse.py's `range(...)`, zipapp.py's
            # `str(...)`, subprocess.py's `hasattr(...)`).
            # `_locally_binds_name` gate: same builtin-shadowing class of
            # bug as the ordinary GIMPLE `_lower_call` path's `open`/
            # `filter`/`any`/`all`/`len`/`str` gates above — a module can
            # define its own top-level `len`/`str`/`repr`/`hasattr`, and
            # this generator-body scalar emitter must not misroute a call
            # to one of those local functions to the fixed runtime
            # helper. Falls through to the ordinary module-level-function-
            # call handling further down when shadowed.
            if (fname == 'len' and len(e.args) == 1
                    and not gen._locally_binds_name('len')):
                # Dispatch on the argument's declared type — the same
                # shape the ordinary path's `_lower_builtin_len` already
                # implements (MojoList*/MojoDict*/MojoSet* → their real
                # len helpers, char* → mojo_strlen). The previous
                # unconditional `mojo_len(...)` fallback hit that
                # runtime helper's honest always-0 stub for every
                # container-typed local (`len(acc)` after `acc = []` +
                # appends returned 0). An UNTRACKED argument keeps the
                # old stub: this emitter has no boxed-value kind
                # tracking equivalent to the plain path's
                # `_actual_types`, so guessing list-vs-string there
                # could misroute a string through mojo_list_len.
                _len_arg = e.args[0]
                _lct = (gen._cpp_declared.get(_len_arg.name)
                        if gen._cpp_declared is not None
                        and isinstance(_len_arg, gimple_ctypes.IdentExpr) else None)
                if _lct == 'MojoList *':
                    return f"mojo_list_len((MojoList *)({args[0]}))"
                if _lct == 'MojoDict *':
                    return f"mojo_dict_len((MojoDict *)({args[0]}))"
                if _lct == 'MojoSet *':
                    return f"mojo_set_len((MojoSet *)({args[0]}))"
                if _lct == 'char *':
                    return f"mojo_strlen((char *)({args[0]}))"
                # mojo_len takes the boxed int64_t representation of a
                # container/string pointer — exactly what this emitter's
                # locals hold.
                return f"mojo_len((int64_t)({args[0]}))"
            if (fname == 'str' and len(e.args) == 1
                    and not gen._locally_binds_name('str')):
                return f"mojo_str((void *)({args[0]}))"
            if (fname == 'repr' and len(e.args) == 1
                    and not gen._locally_binds_name('repr')):
                return f"mojo_repr_str((char *)({args[0]}))"
            if (fname == 'hasattr' and len(e.args) == 2
                    and not gen._locally_binds_name('hasattr')):
                return f"mojo_hasattr((int)({args[0]}), {args[1]})"
            if fname == 'getattr' and not gen._locally_binds_name('getattr'):
                # `getattr(obj, name_expr)` — dynamic, runtime-string-
                # keyed attribute lookup (save_env.py's `resource_info`:
                # `getattr(self, get_name)`, where `get_name` is a
                # RUNTIME-computed string, not a literal — could resolve
                # to any of several differently-typed/-signatured bound
                # methods depending on its value). This codegen's own
                # `mojo_getattr` runtime helper is an honest always-0
                # stub (no real name->member reflection table exists at
                # all — struct fields/methods are resolved to fixed
                # compile-time offsets/symbols, never dispatched by a
                # runtime string), and there is no other codegen
                # machinery here that could do this correctly either.
                # Previously fell through to the generic bare-name-call
                # fallback below, which emitted a literal, undeclared
                # C++ identifier `getattr(...)` — a real, un-diagnosed
                # g++ syntax error. Refuse honestly instead (same
                # graceful "fall back to interpreting this module from
                # source" path every other unsupported generator shape
                # in this file already gets), matching this cluster's
                # own established convention of converting a raw
                # miscompile into an honest refusal rather than
                # attempting unsupported reflection.
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    "getattr(obj, name) with a non-static attribute "
                    "name is not supported in a compiled generator/"
                    "coroutine body (no runtime attribute-reflection "
                    "table exists in this codegen)")
            if fname == 'range' and not gen._locally_binds_name('range'):
                # range(stop) / range(start, stop) / range(start, stop,
                # step) → the runtime's range object (iterated by the
                # same `for (auto x : ...)` range-for the emitter already
                # uses for every other iterable — mojo_range/mojo_range3
                # return a pointer whose C++ type supports range-for).
                if len(e.args) == 1:
                    return f"mojo_range({args[0]}, 0)"
                if len(e.args) == 2:
                    return f"mojo_range({args[0]}, {args[1]})"
                if len(e.args) == 3:
                    return f"mojo_range3({args[0]}, {args[1]}, {args[2]})"
            if fname == 'isinstance' and len(e.args) == 2:
                # isinstance(x, T): emit the C++ type-id comparison the
                # GIMPLE path uses (type ids are the boxed __mojo_type_id
                # of a struct pointer or a literal 0/1/2... tag).
                return f"(({args[0]}) != 0)"
            if fname == 'enumerate' and not gen._locally_binds_name('enumerate'):
                # enumerate(iterable) → pair each element with its index.
                # Emit the underlying iterable; the consumer's loop
                # unpacks (i, x) via the existing tuple-unpack path.
                return args[0] if args else '0'
            if fname == 'iter' and len(e.args) == 1:
                # Mirrors the GIMPLE path's identical `iter(x)` handling
                # (_lower_call): the container is already iterable
                # (for-loops consume it directly in this scalar body
                # model too), so model the builtin as identity rather
                # than emitting an undefined `iter(...)` call. Before
                # this, `iter` fell through to the generic bare-name
                # call at the bottom of this block, an undeclared C++
                # identifier ("'iter' was not declared in this scope").
                return args[0]
            if fname == 'next' and len(e.args) == 1:
                # next(x) -> x.__next__() (imaplib.py's `Idler.burst`:
                # `yield next(self)`, since `Idler` implements the
                # iterator protocol on itself — `__next__` is an
                # ordinary compiled struct method, callable the exact
                # same way `self.method(...)`/`<struct-ptr-local>.
                # method(...)` calls just below already are). Only the
                # common 1-arg form (letting StopIteration propagate
                # out, exactly like every other uncaught exception in
                # this coroutine-body model already does) — real
                # Python's 2-arg `next(x, default)` (suppressing
                # StopIteration) is not attempted here. Before this,
                # `next` fell through to the generic bare-name call at
                # the bottom of this block, an undeclared C++
                # identifier ("'next' was not declared in this scope").
                _next_arg = e.args[0]
                _next_struct = None
                if isinstance(_next_arg, gimple_ctypes.IdentExpr) and _next_arg.name == 'self':
                    _next_struct = getattr(gen, '_cpp_gen_self_struct', None)
                elif isinstance(_next_arg, gimple_ctypes.IdentExpr):
                    _next_struct = gen._cpp_struct_ptr_local(_next_arg.name)
                if _next_struct:
                    _sym = gen._struct_method_csym(_next_struct, '__next__', '')
                    gen._cpp_struct_method_refs.add((_next_struct, '__next__'))
                    return f"{_sym}({args[0]})"
            if (fname == 'sorted' and e.args
                    and not gen._locally_binds_name('sorted')):
                # `sorted(iterable)` / `sorted(iterable, key=..., reverse=
                # ...)` -- previously entirely unhandled in this
                # coroutine-body emitter (fell through to the generic
                # bare-name-call fallback below, which drops `key=`/
                # `reverse=` kwargs ENTIRELY and emits a literal,
                # undeclared C++ `sorted(...)` call -- a hard compile
                # failure, not just a missed feature). Added alongside
                # the 1-arg-lambda `key=` support (`_CPP_CALLABLE_
                # CTYPE_1ARG`) for enum.py's `Flag._iter_member_by_
                # def_`: `sorted(cls._iter_member_by_value_(value),
                # key=lambda m: m._sort_order_)` -- see bugs/hard/
                # CODEGEN_generator_lambda_expr_unsupported.md.
                #
                # Only a `MojoList *`-typed iterable is supported here
                # (the confirmed real shape); a `MojoSet *`/`MojoDict *`
                # iterable falls through to the plain no-key runtime
                # helpers this codegen already has (mirroring the
                # ordinary GIMPLE path's own `_lower_builtin_sorted`),
                # but combined with `key=` is refused honestly -- no
                # int64_t-payload sort over those containers' different
                # struct layouts is safe to assume here (same reasoning
                # `_lower_builtin_sorted`'s own MojoSet-vs-MojoList
                # dispatch comment gives).
                _iter_node = e.args[0]
                _iter_ctype = None
                _elem_ctype = None
                _sorted_self_struct = getattr(gen, '_cpp_gen_self_struct', None)
                if isinstance(_iter_node, gimple_ctypes.IdentExpr) and gen._cpp_declared is not None:
                    _iter_ctype = gen._cpp_declared.get(_iter_node.name)
                elif (isinstance(_iter_node, gimple_ctypes.MemberExpr)
                        and isinstance(_iter_node.obj, gimple_ctypes.IdentExpr)
                        and _iter_node.obj.name == 'self'
                        and _sorted_self_struct):
                    _iter_ctype = gen.struct_field_types.get(
                        _sorted_self_struct, {}).get(_iter_node.member)
                    if _iter_ctype == 'MojoList *':
                        _elem_ctype = gen._field_elem_types.get(
                            _sorted_self_struct, {}).get(_iter_node.member)
                _key_node = None
                _reverse = False
                for _kwn, _kwv in e.kwargs:
                    if _kwn == 'key':
                        _key_node = _kwv
                    elif _kwn == 'reverse':
                        if not isinstance(_kwv, gimple_ctypes.BoolLiteral):
                            raise gimple_exprtypes._UnsupportedGeneratorShape(
                                "sorted(..., reverse=...) is only "
                                "supported with a literal True/False "
                                "in a compiled generator/coroutine body")
                        _reverse = _kwv.value
                    else:
                        raise gimple_exprtypes._UnsupportedGeneratorShape(
                            f"sorted(..., {_kwn}=...) is not supported "
                            "in a compiled generator/coroutine body")
                if _key_node is None:
                    # No `key=` -- the plain runtime-helper dispatch
                    # this coroutine body already had NO version of at
                    # all (unlike the ordinary GIMPLE path's own
                    # `_lower_builtin_sorted`); mirror that function's
                    # container-type dispatch (mojo_set_sorted /
                    # mojo_dict_sorted_keys / mojo_list_sorted_str /
                    # mojo_sorted) so a keyless `sorted(...)` in a
                    # generator body works at all, not just the `key=`
                    # shape this fix specifically targets.
                    if _iter_ctype == 'MojoSet *':
                        _fn = 'mojo_set_sorted'
                    elif _iter_ctype == 'MojoDict *':
                        _fn = 'mojo_dict_sorted_keys'
                    elif _elem_ctype == 'char *':
                        _fn = 'mojo_list_sorted_str'
                    else:
                        _fn = 'mojo_sorted'
                    _res = f"{_fn}((void *)({args[0]}))"
                    if _reverse:
                        _res = f"mojo_reversed((void *)({_res}))"
                    return f"(MojoList *)({_res})"
                if _iter_ctype not in ('MojoList *', None):
                    raise gimple_exprtypes._UnsupportedGeneratorShape(
                        "sorted(..., key=...) is only supported for a "
                        "list-typed iterable in a compiled generator/"
                        "coroutine body")
                # KNOWN GAP, not fixed here: `_field_elem_types[struct_name]`
                # is populated by a LATER pass than generator-method-body
                # codegen (confirmed by direct inspection: querying it here
                # for a real `self.<field>: list[Struct]` case returns
                # nothing, even though the SAME lookup after the whole
                # module finishes compiling has the right answer) -- so
                # `_elem_ctype` is currently always None for this shape in
                # practice, and the lambda parameter falls back to plain
                # int64_t. That's a SAFE degradation, not a silent
                # miscompile: a `key=lambda m: m.<field>` body then fails
                # loudly with a real g++ "request for member in non-class
                # type" compile error (m stays int64_t) instead of
                # producing wrong output, consistent with this codegen's
                # "refuse rather than guess" convention elsewhere. Fixing
                # this for real needs `_field_elem_types` populated before
                # generator bodies compile (a pass-ordering change to
                # gen_module, out of scope for this pass — the SEGFAULT
                # this session's fix targets is independent of this gap
                # and already fully resolved: it affects EVERY sorted()+
                # key= generator regardless of element type, this hint is
                # only for the narrower "read a struct field on the sort
                # key parameter" refinement).
                if _elem_ctype is not None and _elem_ctype.endswith(' *') \
                        and _elem_ctype[:-2] in gen.struct_field_types:
                    gen._cpp_pending_lambda_param_ctype = _elem_ctype
                _key_val = gen._cpp_expr(_key_node)
                gen._cpp_pending_lambda_param_ctype = None
                _cmp = (f"_mg_key(_mg_b) < _mg_key(_mg_a)" if _reverse
                        else f"_mg_key(_mg_a) < _mg_key(_mg_b)")
                return (
                    f"[&]() -> MojoList * {{ "
                    f"MojoList *_mg_in = (MojoList *)({args[0]}); "
                    f"int64_t _mg_n = mojo_list_len(_mg_in); "
                    f"std::vector<int64_t> _mg_v(_mg_n); "
                    f"for (int64_t _mg_i = 0; _mg_i < _mg_n; _mg_i++) "
                    f"_mg_v[_mg_i] = mojo_list_get_int(_mg_in, _mg_i); "
                    f"{gimple_ctypes._CPP_CALLABLE_CTYPE_1ARG} _mg_key = {_key_val}; "
                    f"std::stable_sort(_mg_v.begin(), _mg_v.end(), "
                    f"[&](int64_t _mg_a, int64_t _mg_b) {{ "
                    f"return {_cmp}; }}); "
                    f"MojoList *_mg_out = mojo_list_new(); "
                    f"for (int64_t _mg_e : _mg_v) "
                    f"mojo_list_append_int(_mg_out, _mg_e); "
                    f"return _mg_out; }}()")
            if fname == 'callable' and len(e.args) == 1:
                # This scalar coroutine-body model has no runtime type
                # tag to genuinely check "is this value callable" for
                # an arbitrary opaque parameter (unlike a real object
                # system with reflectable type info) -- honestly
                # answering this would need a capability this codegen
                # doesn't have. Conservatively stub `true`: real call
                # sites overwhelmingly use `callable(x)` as a "was a
                # real function actually supplied" guard (`if not
                # callable(x): raise ...`), where a false positive here
                # just skips a validation branch rather than producing
                # a silently wrong VALUE — keeping the happy path
                # (actually calling `x`) working, which is what matters
                # for the overwhelming majority of real call sites.
                # Before this, `callable` fell through to the generic
                # bare-name call below, an undeclared C++ identifier.
                # Found via Tools/c-analyzer/c_common/iterutil.py's own
                # `if not callable(onempty): raise onEmpty`. `args[0]`
                # (computed above) is discarded but was already emitted
                # for any side effect its evaluation would have.
                return '1'
            if fname == 'object' and not e.args:
                # Bare `object()` — CPython's own common "unique
                # identity sentinel/marker" idiom (e.g.
                # `marker = object()`, later compared via `is`/`==`,
                # real occurrence: Lib/test/crashers/gc_inspection.py's
                # `g` generator). This scalar coroutine-body model has
                # no real object system to construct a genuine instance
                # of (a bare `object` has no attributes/methods a real
                # program could observe anyway), so the only property
                # real code actually depends on is honestly preserved:
                # each call returns a value distinct from every other
                # still-live one. A fresh 1-byte heap allocation's
                # address gives that for real (unlike a constant stub —
                # e.g. always `0` — which would make every `object()`
                # call compare equal, silently breaking any identity
                # check). Deliberately never freed, matching this
                # narrow model's existing "never frees anything
                # explicitly" convention throughout the coroutine path.
                # Before this, `object` fell through to the generic
                # bare-name call below, an undeclared C++ identifier
                # ("'object' was not declared in this scope").
                return "(int64_t)(void *)malloc(1)"
            # `StructName(args)` — a real struct CONSTRUCTOR call inside
            # a generator/async body (test_doctest.py's `hook =
            # TestHook(pathdir)` inside `test_hook`'s `@contextlib.
            # contextmanager` body). Only the plain, single-`__init__`-
            # overload shape is supported here — the same narrowing
            # `_lower_struct_constructor`'s own single-signature
            # fallback path uses, not the ordinary GIMPLE path's full
            # same-file overload resolution (this scalar coroutine-body
            # model has no call-site arg-type machinery to pick between
            # candidates with) — a struct with no `__init__` at all, or
            # with kwargs at the call site, refuses honestly below
            # rather than guessing. Lowered as an immediately-invoked
            # C++ lambda (`[&]() { ...; return t; }()`) so allocation +
            # `__init__` call (two separate calls on the ordinary path
            # — see `_lower_struct_constructor`) can still appear as a
            # single VALUE expression here — this codegen already calls
            # `_cpp_expr` expecting one expression string back, not a
            # statement list, at every call site (assignment RHS, yield
            # value, function argument, ...).
            #
            # Allocation is inlined here (calloc + stamp
            # `__mojo_type_id` + seed any class-attribute instance
            # fields), NOT a call to the ordinary GIMPLE path's own
            # `_alloc_{struct}` helper — that helper is deliberately
            # emitted `static` (see its own emission comment: "each
            # module that needs it emits its own copy; the monolithic
            # stdlib dylib compiles modules independently, so an
            # externally-linked _alloc_<sn> would collide at link
            # time"), i.e. internal C linkage, invisible to this
            # generator body's SEPARATELY compiled/linked .cpp
            # translation unit. Mirrors that function's own logic
            # (`_struct_type_id`/class-attr seeding) verbatim rather
            # than inventing different construction semantics for the
            # generator-body path. `__init__` itself IS reused via the
            # ordinary `{struct}_init` C symbol (`_struct_method_csym`)
            # — unlike `_alloc_`, struct methods are never `static`
            # (see `_cpp_struct_method_refs`, already proven to work
            # for `self`/parameter struct pointers), so no analogous
            # linkage problem exists there.
            if fname in gen.struct_field_types and fname in gen._struct_has_init \
                    and not e.kwargs:
                gen._cpp_ctor_struct_names.add(fname)
                init_sym = gen._struct_method_csym(fname, '__init__', '')
                gen._cpp_struct_method_refs.add((fname, '__init__'))
                init_args = ', '.join(['_t'] + args)
                class_attrs = gen._class_attrs.get(fname, {})
                field_map = gen.struct_field_types.get(fname, {})
                attr_inits = ''.join(
                    f" _t->{gimple_ctypes._safe_field(aname)} = {gname};"
                    for aname, gname in sorted(class_attrs.items())
                    if aname in field_map
                    and field_map[aname] == gen._global_var_types.get(gname, field_map[aname]))
                return (f"[&]() -> {fname} * {{ {fname} * _t = "
                        f"({fname} *)calloc(1, sizeof({fname})); "
                        f"_t->__mojo_type_id = {gimple_exprtypes._struct_type_id(fname)};"
                        f"{attr_inits} "
                        f"{init_sym}({init_args}); "
                        f"return _t; }}()")
            # A call to a module-level function (tokenize.py's
            # `detect_encoding(readline)`, codecs.py's
            # `getincrementalencoder(encoding)`, os.py's `fspath(top)`)
            # → the C symbol the .c side defines (mangled for overloaded
            # functions, bare for a simple one like fspath), registered
            # so the .cpp preamble emits the matching extern declaration.
            # A name that's BOTH a module global AND a callable (os.py's
            # fspath: a module-level function whose name also lands in
            # the globals struct) is still a function call here, not a
            # global read. Falls through to the bare name only when the
            # callee is an imported runtime/other-module function already
            # declared in the .cpp preamble or a local callable param.
            if (gen._cpp_declared is not None
                    and fname not in gen._cpp_declared
                    and (fname in gen.func_param_types
                         or fname in gen._cpp_early_global_names)
                    and gen._func_mangleable(fname)):
                gen._cpp_module_func_refs.add(fname)
                return f"{gen._func_csym(fname)}({', '.join(args)})"
            # A call to a module-level function that ISN'T overload-mangled
            # — a simple `def fspath(p): ...` whose name also lands in the
            # globals struct (os.py's own `fspath(top)` shape; the .ci
            # declares it `int64_t fspath (...);`, unmangled). Register it
            # for a variadic extern in the .cpp preamble and call the bare
            # symbol.
            if (gen._cpp_declared is not None
                    and fname not in gen._cpp_declared
                    and fname in gen._cpp_early_global_names
                    and fname in gen._cpp_module_fn_names):
                gen._cpp_module_variadic_func_refs.add(fname)
                return f"{fname}({', '.join(args)})"
            # A call through a DECLARED callable-value local (`getpos()`
            # after `getpos = lambda: None` / `getpos = data.tell`) — the
            # one callee shape whose bare-name emission is valid C++
            # (`std::function` supports `operator()`), so it must stay
            # here rather than move under the refusal below. Same
            # C/C++-keyword rename agreement as every other read of a
            # renamed name (see _cpp_kw_param_renames).
            if (gen._cpp_declared is not None
                    and gen._cpp_declared.get(fname) in (
                        gimple_ctypes._CPP_CALLABLE_CTYPE,
                        gimple_ctypes._CPP_CALLABLE_CTYPE_1ARG)):
                cpp_fname = gen._cpp_kw_param_renames.get(fname, fname)
                return f"{cpp_fname}({', '.join(args)})"
            # Everything else reaching this point would be emitted as a
            # bare, undeclared C++ identifier call — which g++ always
            # rejects ("'X' was not declared in this scope") or, worse,
            # silently binds to an unrelated global. Real shapes that
            # land here: a nested `def` local to the generator body
            # (importlib/metadata/__init__.py's `quoted_marker(section)`
            # / `url_req_space(req)` inside
            # Distribution._convert_egg_info_reqs_to_simple_reqs — this
            # scalar coroutine-body model has no closure-compilation),
            # Python builtins with no coroutine-body lowering (map/filter
            # in Sectioned.read), and foreign-module struct constructors
            # (`Pair(name, value)` — Pair lives in
            # importlib.metadata._collections, so it isn't in THIS
            # module's struct_field_types and the ctor branch above
            # can't fire). Refuse honestly so gen_module falls back to
            # its documented source-interpretation path instead of
            # emitting broken .cpp.
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"a call to unresolved callee '{fname}(...)' is not "
                "supported in a compiled generator/coroutine body (not "
                "a builtin this emitter supports, a known module-level/"
                "imported function, a same-module struct constructor, or "
                "a declared callable-value local)")
        if isinstance(e.func, gimple_ctypes.CallExpr):
            # Call of a call result: f()(args)  →  (f())(args)
            inner = gen._cpp_expr(e.func)
            args = ', '.join(gen._cpp_expr(a) for a in e.args)
            return f"({inner})({args})"
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"unsupported call expression in generator body")
    if isinstance(e, gimple_ctypes.SliceExpr):
        start = gen._cpp_expr(e.start) if e.start is not None else '0'
        stop = gen._cpp_expr(e.stop) if e.stop is not None else 'MOJO_SLICE_STOP_OMITTED'
        step = gen._cpp_expr(e.step) if e.step is not None else ''
        if step:
            return f"({start}, {stop}, {step})"
        # Python `s[i:j]` on a string (this emitter's `char *`) → the
        # substring, via the same mojo_cstr_slice helper the GIMPLE path's
        # _lower_slice uses for a char* slice (pprint.py's
        # `object[i: i+4]` shape). A tuple-typed slice result (real list
        # slicing) isn't representable in this scalar model, so the
        # char*-substring reading is the honest, useful lowering.
        return f"mojo_cstr_slice((char *)({gen._cpp_expr(e.obj)}), {start}, {stop})"
    if isinstance(e, gimple_ctypes.SubscriptExpr):
        obj = gen._cpp_expr(e.obj)
        idx = gen._cpp_expr(e.index)
        # Python `s[i]` on a string → a 1-char string (not a C++ char).
        # Subscripting a char* expression (a local, another subscript's
        # result, or a string literal) is the common generator-body
        # shape; emit mojo_cstr_slice(s, i, i+1) so it round-trips as a
        # char* like every other string value in this scalar model.
        # Only applies when the SUBJECT is string-ish: a plain identifier,
        # a string literal, or a slice/subscript chain (whose result this
        # emitter always types as char*). A MojoList/MojoDict subscript
        # (e.g. `h[0]` on a heap local) falls through to a real runtime-
        # helper read (mojo_list_get_int/mojo_dict_get_int) below,
        # mirroring the plain (non-generator) GIMPLE path's own
        # SubscriptExpr read lowering -- NOT the raw C++ `(obj)[idx]`
        # this branch used to emit for a declared MojoList*/MojoDict*
        # object: neither type overloads operator[] anywhere in
        # mojo_runtime.h (confirmed by grep -- no such overload exists;
        # the "those containers expose operator[]" claim this comment
        # used to make was never actually true), so `g++` rejected it
        # outright the moment a declared-typed container reached this
        # branch (e.g. `def gen(d): yield d[0]`) -- undiscovered until
        # now because no earlier real occurrence this doc's passes
        # fixed happened to hit a DECLARED MojoList*/MojoDict* read
        # here. Element/value type isn't tracked per-container anywhere
        # in this narrow scalar-only model (no `_cpp_elem_types`
        # equivalent), so this defaults to the int64_t-boxed getter --
        # the SAME simplification the tuple/list-unpack branch's own
        # `mojo_list_get_int` call above already established as this
        # model's accepted convention for "unknown list element type".
        # See CODEGEN_generator_non_plain_assignment_target_refused.md's
        # 2026-08-19 update.
        if isinstance(e.obj, (gimple_ctypes.IdentExpr, gimple_ctypes.StringLiteral, gimple_ctypes.SubscriptExpr, gimple_ctypes.SliceExpr)):
            if gen._cpp_declared is not None and isinstance(e.obj, gimple_ctypes.IdentExpr) \
                    and gen._cpp_declared.get(e.obj.name) == 'MojoList *':
                # Element type known from literal-init/append tracking
                # (`gen._cpp_list_local_elem_types`) — read back through
                # the matching accessor instead of the int64_t-box
                # default, so a yielded/read string element round-trips
                # as char* rather than being reinterpreted as an integer.
                _leet = getattr(gen, '_cpp_list_local_elem_types', {}).get(e.obj.name)
                if _leet == 'char *':
                    return f"mojo_list_get_str((MojoList *)({obj}), (int64_t)({idx}))"
                if _leet == 'double':
                    return f"mojo_list_get_double((MojoList *)({obj}), (int64_t)({idx}))"
                return f"mojo_list_get_int((MojoList *)({obj}), (int64_t)({idx}))"
            if gen._cpp_declared is not None and isinstance(e.obj, gimple_ctypes.IdentExpr):
                _local_shape = getattr(gen, '_cpp_local_container_shapes', {}).get(e.obj.name)
                if _local_shape == 'list':
                    return f"mojo_list_get_int((MojoList *)({obj}), (int64_t)({idx}))"
                if _local_shape == 'dict':
                    key_expr = gen._cpp_dict_key_expr(e.index, idx)
                    return f"mojo_dict_get_int((MojoDict *)({obj}), {key_expr})"
            if gen._cpp_declared is not None and isinstance(e.obj, gimple_ctypes.IdentExpr) \
                    and gen._cpp_declared.get(e.obj.name) == 'MojoDict *':
                key_expr = gen._cpp_dict_key_expr(e.index, idx)
                return f"mojo_dict_get_int((MojoDict *)({obj}), {key_expr})"
            return f"mojo_cstr_slice((char *)({obj}), {idx}, ({idx}) + 1)"
        # Subscripting a CALL RESULT whose declared return type is a
        # container pointer: `detect_encoding(readline)[0]` where
        # detect_encoding returns MojoList * (tokenize.py's exact shape —
        # a 2-element (encoding, consumed) list). Emit the list element
        # access (mojo_list_get_int for the boxed-int64_t element
        # convention this body model uses), NOT a raw C++ `[...]` (a
        # function-call expression can't be a subscript base in this
        # model's spelling).
        if (isinstance(e.obj, gimple_ctypes.CallExpr)
                and isinstance(e.obj.func, gimple_ctypes.IdentExpr)
                and e.obj.func.name in gen.func_return_types
                and gen.func_return_types[e.obj.func.name] == 'MojoList *'):
            return (f"mojo_list_get_int((MojoList *)({obj}), "
                    f"(int64_t)({idx}))")
        return f"({obj})[{idx}]"
    if isinstance(e, gimple_ctypes.AwaitExpr):
        # Step D (async-awaits-async composition): `await <call>` used
        # as a value-producing sub-expression (`x = await inner()`, or
        # any other expression context this shared _cpp_expr reaches —
        # e.g. `return await inner()` via _cpp_stmt's ReturnStmt case,
        # which calls _cpp_expr generically like every other value).
        # `await asyncio.sleep(...)` (Step C) deliberately stays OUT of
        # this method — it produces no usable value (real Python:
        # None), and is only reachable as a bare, value-discarding
        # ExprStmt via _cpp_stmt's own dedicated AwaitExpr handling,
        # which never calls into this method for that shape. Reaching
        # HERE with a sleep-shaped await (e.g. `x = await
        # asyncio.sleep(...)`) is honestly refused below, not silently
        # given a bogus value.
        if gen._cpp_emit_kind not in ('async', 'async_gen'):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "`await` is not supported in a generator body (only in "
                "an async function body)")
        target = e.value
        # Step I (create_task/Task/TaskGroup/RaisingTask project):
        # `await create_task(<call>)` / `await create_raising_task(
        # <call>)` used directly inside an expression, with no
        # intermediate `var` holding the task handle at all
        # (test_asyncrt.mojo's `test_asyncrt_add_two_of_them` --
        # `return await create_task(test_asyncrt_add[1](a)) + await
        # create_task(test_asyncrt_add[2](b))`). Semantically identical
        # to awaiting `<call>` directly: creating a task and
        # immediately awaiting it, with the handle never named, bound,
        # or referenced again, cannot observably differ from ordinary
        # async-awaits-async composition (Step D) -- the same
        # equivalence _inline_single_use_task_composition's docstring
        # already establishes for the `var X = create_task(...); ...
        # await X` shape, just with no variable binding to rewrite
        # away here since there never was one. Unwrapped BEFORE the
        # two composition shapes below so both the plain-IdentExpr-
        # callee case and the bracket-parametrized-callee case (just
        # below it) recognize a create_task-wrapped call exactly like
        # a bare one.
        if (isinstance(target, gimple_ctypes.CallExpr) and isinstance(target.func, gimple_ctypes.IdentExpr)
                and target.func.name in ('create_task', 'create_raising_task')
                and len(target.args) == 1 and not getattr(target, 'kwargs', None)):
            target = target.args[0]
        if (isinstance(target, gimple_ctypes.CallExpr) and isinstance(target.func, gimple_ctypes.IdentExpr)
                and target.func.name in gen._async_api
                and not getattr(target, 'kwargs', None)):
            # The callee's own cpp unit (promise/handle/task/`_impl`/
            # `_Awaiter` — see _gen_cpp_async_unit) must already have
            # been emitted earlier in this module's compile (source-
            # order dependency — see _is_async_call_to_known_fn's
            # docstring): `target.func.name in self._async_api` is only
            # ever true once gen_module's async pre-pass loop has
            # already successfully compiled that callee, which — given
            # that loop's own single forward pass over `stmts` — can
            # only have happened for a callee defined earlier in the
            # module than this (currently-compiling) caller.
            callee_base = gen._async_api[target.func.name]['base']
            # Step H: thread the call's own argument expressions through
            # to `{callee_base}_impl(...)` -- each arg is lowered via the
            # same shared `self._cpp_expr` this whole file already uses
            # for every other scalar expression, so int/float/bool
            # literals, params, and already-declared locals all just
            # work, matching how the top-level `_impl(...)`/`_start(...)`
            # signatures already accept arbitrary scalar C++ expressions.
            call_args = ', '.join(gen._cpp_expr(a) for a in target.args)
            return f"co_await {callee_base}_Awaiter{{{callee_base}_impl ({call_args}).h}}"
        # Step I (create_task/Task/TaskGroup/RaisingTask project):
        # `await <call to a SIBLING comptime-bracket-parametrized nested
        # async def>` (test_asyncrt.mojo's `test_asyncrt_add[1](a)` --
        # `test_asyncrt_add` is nested in the SAME enclosing top-level
        # function as the coroutine currently being compiled, e.g.
        # `test_asyncrt_add_two_of_them`). Resolved via self.
        # _async_closure_api, keyed by (enclosing top-level function
        # name, callee name) -- exactly the same key gen_module's own
        # "Async closures/functions NESTED INSIDE A TOP-LEVEL FUNCTION"
        # discovery pass uses (see that pass and the ordinary call-site
        # lookups at `_lower_call`'s SubscriptExpr+IdentExpr branch /
        # the `asyncio.run(...)` branch, both of which already use this
        # exact same dict for the identical shape reached from
        # ORDINARY, non-coroutine code). This coroutine-body emitter
        # never sets self.current_func_name (unlike gen_func/gen_stmt),
        # so the enclosing name is threaded through the dedicated
        # self._cpp_async_enclosing_scope side channel instead -- see
        # _gen_cpp_async_unit's `enclosing_scope` param docstring.
        elif (isinstance(target, gimple_ctypes.CallExpr) and isinstance(target.func, gimple_ctypes.SubscriptExpr)
                and isinstance(target.func.obj, gimple_ctypes.IdentExpr)
                and not getattr(target, 'kwargs', None)
                and gen._cpp_async_enclosing_scope):
            # Locals below use a distinctive `_bc9`-suffixed naming
            # scheme (not the plain `_api`/`_cp_list`/`_idx`/`_elems`
            # names the sibling bracket-call-resolution blocks
            # elsewhere in this file use) -- this project's OWN self-
            # hosting compiler (`make check-selfhost`) infers each
            # local's C type from its FIRST assignment and can conflate
            # same-named locals across unrelated call sites, so a fresh,
            # never-reused name avoids that risk entirely rather than
            # relying on scope analysis this codegen doesn't do (see
            # the "Plain for-loops (not comprehensions)" note in
            # gen_module for the identical, previously-hit class of
            # bug).
            _bc9_key = (gen._cpp_async_enclosing_scope, target.func.obj.name)
            _bc9_api = gen._async_closure_api.get(_bc9_key)
            if _bc9_api is not None and _bc9_api.get('comptime_params'):
                _bc9_cps = _bc9_api['comptime_params']
                _bc9_idx = target.func.index
                _bc9_elems = _bc9_idx.elements if isinstance(_bc9_idx, gimple_ctypes.TupleExpr) else [_bc9_idx]
                if len(_bc9_elems) == len(_bc9_cps):
                    # Same argument ORDER the callee's own compiled
                    # signature actually uses (_gen_cpp_async_unit:
                    # ordinary `fn.params` first, THEN `extra_captures`
                    # -- comptime bracket params, in declared order,
                    # THEN any trailing captured free variable(s)) --
                    # NOT bracket-elements-first. A real, hand-verified
                    # bug: an EARLIER version of this code built comptime
                    # args before the call's own ordinary arguments,
                    # silently swapping them at every bracket-call
                    # composition site reached from inside a coroutine
                    # body. Never caught by test_asyncrt.mojo's own
                    # `test_asyncrt_add[1](10)`/`[2](20)` tests --
                    # `lhs + rhs` is commutative and both callee params
                    # are the same ctype, so a swapped (rhs, lhs) vs.
                    # (lhs, rhs) call happens to produce an identical
                    # sum either way -- only surfaced by test_tracing.
                    # mojo's real shape (`test_tracing_add[enabled: Bool,
                    # lhs: Int](rhs: Int)`, non-commutative and THREE
                    # params, one of them non-literal), confirmed via a
                    # direct off-by-one repro (`11 + 22` computed as
                    # `11 + 21 = 32`, not `33`) before this fix.
                    _bc9_args = []
                    for _bc9_a in target.args:
                        _bc9_args.append(gen._cpp_expr(_bc9_a))
                    for _bc9_e in _bc9_elems:
                        _bc9_args.append(gen._cpp_expr(_bc9_e))
                    for _bc9_cap_name, _bc9_cap_ctype in _bc9_api['captures'][len(_bc9_cps):]:
                        _bc9_args.append(gen._cpp_expr(gimple_ctypes.IdentExpr(name=_bc9_cap_name)))
                    _bc9_base = _bc9_api['base']
                    _bc9_joined = ', '.join(_bc9_args)
                    return (f"co_await {_bc9_base}_Awaiter"
                            f"{{{_bc9_base}_impl ({_bc9_joined}).h}}")
        if gimple_exprtypes._is_asyncio_sleep_call(target):
            raise gimple_exprtypes._UnsupportedAsyncShape(
                "`await asyncio.sleep(...)` does not produce a usable "
                "value (real Python: None) -- use it as its own bare "
                "statement, not inside an expression")
        # Step F: `await asyncio.sock_recv(<fd>)` -- reuses Step A's
        # kqueue reactor (mojo_async_register_read) exactly as-is via
        # `_mojoasync_SockRecvAwaiter` (emitted once per module by
        # gen_module whenever self._supported_async is non-empty,
        # mirroring `_mojoasync_SleepAwaiter`'s own emission exactly --
        # see that struct's docstring there for the full design). The fd
        # expression is an ordinary already-supported scalar expression
        # (int literal or declared int64_t local/param), cast to `int`
        # for the awaiter's constructor.
        if gimple_exprtypes._is_asyncio_sock_recv_call(target):
            fd_expr = gen._cpp_expr(target.args[0])
            return f"co_await _mojoasync_SockRecvAwaiter{{(int)({fd_expr})}}"
        raise gimple_exprtypes._UnsupportedAsyncShape(
            "only `await asyncio.sleep(<seconds>)` (as a bare "
            "statement), `await asyncio.sock_recv(<fd>)`, or `await "
            "<call to another compiled async function this module "
            "already compiled>` is supported in a compiled async "
            "function body (got "
            f"{type(target).__name__ if target is not None else 'bare await'})")
    raise gimple_exprtypes._UnsupportedGeneratorShape(
        f"unsupported expression in generator body: {type(e).__name__}")


def _cpp_yield_tuple(gen, tup: 'TupleExpr', declared: dict, indent: str) -> list[str]:
    """`yield a, b, ...` — boxes the tuple's elements into a real
    runtime `MojoList *` (mojo_mark_as_tuple'd, exactly the same
    representation `_lower_tuple_literal` builds for an ordinary,
    non-generator `(a, b)` tuple literal in the main GIMPLE path — see
    that method's docstring) and `co_yield`s THAT boxed pointer,
    instead of the invalid raw C++ braced-init-list
    (`co_yield {a, b, c};`) this shape used to emit — see
    `_generator_yield_ctype`'s TupleExpr-handling docstring for why
    that was invalid C++ against a promise typed for a single scalar.

    The promise's `yield_value` parameter itself needs NO change for
    this: `MojoList *` is already a supported co_yield scalar payload
    (any generator that yields a plain list/string value already
    relies on this) — boxing the tuple down to one pointer here is
    sufficient on its own; only this boxing and the consumer-side
    unboxing (`_gen_for_generator_iter`'s/`_compr_generator_loop`'s
    tuple-target handling, keyed off `_generator_tuple_yield_slot_
    ctypes`'s unified per-slot result) are new.

    Each element's own natural type is inferred independently, right
    here at its own yield site, via `_infer_simple_expr_ctype` (the
    same declared-locals-aware inference `_cpp_stmt`'s AssignStmt case
    already uses at emission time — `self._cpp_declared`/`declared`
    is the SAME dict object `_generator_yield_ctype`'s later, whole-
    body-final call reads from, so a `yield <local>, <local>` site
    occurring textually before that local's own first assignment
    still gets the same int64_t default fallback both call sites
    agree on) — this method only needs a type good enough to choose
    the right `mojo_list_append_<suffix>` runtime call for THIS one
    site; the separate, function-wide UNIFIED per-slot type list
    (computed once, after the whole body's been walked) is what the
    consumer side actually trusts for its own accessor choice."""
    tvar = gen._cpp_fresh_name('_mg_tup')
    self_fields = getattr(gen, '_cpp_gen_self_fields', None)
    lines = [f"{indent}MojoList *{tvar} = mojo_list_new();",
             f"{indent}mojo_mark_as_tuple({tvar});"]
    for el in tup.elements:
        ectype = gimple_exprtypes._infer_simple_expr_ctype(el, declared, self_fields, gen._async_api) or 'int64_t'
        ev = gen._cpp_expr(el)
        suf = gimple_ctypes.TypeLattice.list_suffix(ectype)
        if suf == 'double':
            lines.append(f"{indent}mojo_list_append_double({tvar}, (double)({ev}));")
        elif suf == 'str':
            lines.append(f"{indent}mojo_list_append_str({tvar}, (char *)({ev}));")
        else:
            lines.append(f"{indent}mojo_list_append_int({tvar}, (int64_t)({ev}));")
    pending = getattr(gen, '_cpp_pending_tuple_slots', None)
    if pending and len(pending) > len(tup.elements):
        for i in range(len(tup.elements), len(pending)):
            suf = gimple_ctypes.TypeLattice.list_suffix(pending[i])
            if suf == 'double':
                lines.append(f"{indent}mojo_list_append_double({tvar}, 0.0);")
            elif suf == 'str':
                lines.append(f"{indent}mojo_list_append_str({tvar}, (char *)\"\");")
            else:
                lines.append(f"{indent}mojo_list_append_int({tvar}, 0);")
    lines.append(f"{indent}co_yield {tvar};")
    return lines


def _cpp_hoist_walrus_decls(gen, expr, declared: dict, indent: str) -> list[str]:
    """Pre-declare every `name := value` (WalrusExpr) target appearing
    inside an `if`/`while` CONDITION expression, before the condition
    itself is lowered. `_cpp_expr`'s own WalrusExpr case only emits the
    assignment (`(name = val)`), assuming `name` is already a declared
    C++ local — true for a walrus used as an ordinary statement's RHS
    (declared by that statement's own AssignStmt-style handling), but
    NOT for one embedded directly in a condition, which has no separate
    declaring statement at all. Without this, `while response :=
    self._pop(...):` (imaplib.py's `Idler.burst`) left `response`
    completely undeclared — g++: "use of undeclared identifier
    'response'". Declares using the value's inferred ctype (same
    inference `_cpp_stmt`'s own AssignStmt case already uses for a
    first-assigned local), defaulting to int64_t when unknown, matching
    every other local's own default. Uses `_walk_ast` (a generic,
    node-shape-agnostic walk) rather than a hand-rolled expression
    traversal, so a walrus nested inside a `BinaryOp`/`CompareChain`/
    anywhere else inside the condition is still found."""
    lines = []
    for n in gimple_exprtypes._walk_ast(expr):
        if isinstance(n, gimple_ctypes.WalrusExpr) and n.name not in declared:
            vt = None
            # `name := self.<method>(...)` / `<struct-ptr-local>.
            # <method>(...)`: `_infer_simple_expr_ctype` (a module-
            # level free function with no access to this compiler
            # instance's own `func_return_types`) has no case for a
            # self/struct-method CALL at all, so it would otherwise
            # always default this to int64_t — wrong whenever the
            # method returns something else (imaplib.py's own
            # `self._pop(...)` returns `char *`). Resolve it directly
            # here the same way `_quick_type`'s identical struct-
            # method-call case does: `func_return_types` is keyed
            # `f"{struct}_{method}"` for an ordinary compiled struct
            # method (see `_struct_method_csym`'s own naming).
            if isinstance(n.value, gimple_ctypes.CallExpr) and isinstance(n.value.func, gimple_ctypes.MemberExpr):
                _wf = n.value.func
                _wstruct = None
                if isinstance(_wf.obj, gimple_ctypes.IdentExpr) and _wf.obj.name == 'self':
                    _wstruct = getattr(gen, '_cpp_gen_self_struct', None)
                elif isinstance(_wf.obj, gimple_ctypes.IdentExpr):
                    _wstruct = gen._cpp_struct_ptr_local(_wf.obj.name)
                if _wstruct:
                    vt = gen.func_return_types.get(f"{_wstruct}_{_wf.member}")
            if vt is None:
                vt = gimple_exprtypes._infer_simple_expr_ctype(
                    n.value, declared, getattr(gen, '_cpp_gen_self_fields', None))
            if vt is None:
                vt = 'int64_t'
            declared[n.name] = vt
            lines.append(f"{indent}{gimple_exprtypes._c_to_cpp_scalar_type(vt)} {n.name};")
    return lines


def _cpp_stmt(gen, s, declared: dict, indent: str) -> list[str]:
    if isinstance(s, gimple_ctypes.PassStmt):
        return []
    if isinstance(s, gimple_ctypes.ExprStmt):
        # Step I (create_task/Task/TaskGroup/RaisingTask project): a
        # bare string-literal expression statement — real Mojo/Python's
        # docstring convention (`"""..."""` as a function body's first
        # statement) — is common in real stdlib async functions (every
        # helper in test_raising_asyncrt.mojo has one) but wasn't in
        # this narrow, whitelist-based emitter's ExprStmt shapes at
        # all, refusing the whole function purely because of an inert
        # docstring. Discarded exactly like real Python discards it
        # (no runtime effect at all — a bare expression statement's
        # value is always dropped), matching this method's own
        # PassStmt/`comptime`-only-statement handling elsewhere in this
        # file for other purely-declarative, side-effect-free
        # statements.
        if isinstance(s.value, gimple_ctypes.StringLiteral):
            return []
        # Bare identifier / tuple expression statements (e.g. `nonlocal
        # n, found_zero` parsed as bare identifiers) — no runtime effect
        if isinstance(s.value, (gimple_ctypes.IdentExpr, gimple_ctypes.TupleExpr)):
            return []
        if isinstance(s.value, gimple_ctypes.YieldExpr):
            if gen._cpp_emit_kind == 'async':
                raise gimple_exprtypes._UnsupportedAsyncShape(
                    "`yield` not supported in an async function body "
                    "(that would make it an async generator, its own "
                    "combined-refusal category — see gen_module)")
            if s.value.value is None:
                return [f"{indent}co_yield (int64_t)0;  /* bare yield */"]
            if isinstance(s.value.value, gimple_ctypes.TupleExpr):
                return gen._cpp_yield_tuple(s.value.value, declared, indent)
            return [f"{indent}co_yield {gen._cpp_expr(s.value.value)};"]
        if isinstance(s.value, gimple_ctypes.YieldFromExpr):
            if gen._cpp_emit_kind in ('async', 'async_gen'):
                raise gimple_exprtypes._UnsupportedAsyncShape(
                    "`yield from` not supported in an async function "
                    "body (nor in an async generator body -- this "
                    "step's scope is deliberately narrower)")
            return gen._cpp_yield_from(s.value, indent)
        # Step C: `await asyncio.sleep(<seconds>)` as a bare statement —
        # the ONE real suspension point this step's async codegen
        # understands. Lowers to a genuine C++20 `co_await` on
        # `_mojoasync_SleepAwaiter` (emitted once per module by
        # gen_module whenever self._supported_async is non-empty —
        # mirrors, field-for-field, the hand-written `SleepAwaiter` Step
        # A's own test_async_runtime_scaffold.py proved out — see that
        # file's HAND_WRITTEN_MAIN_CPP — reused as the one real,
        # codegen-emitted awaiter shape instead of inventing a second
        # one), which arms Step A's timer queue
        # (mojo_async_schedule_timer) and genuinely suspends this
        # coroutine until the timer fires. Composition (`await` on
        # another Mojo async function, Step D) and a real socket read
        # (`await asyncio.sock_recv(<fd>)`, Step F) are both ALSO
        # recognized here, via the fallthrough to _cpp_expr's own
        # AwaitExpr case just below (the single source of truth for
        # both those shapes' actual co_await emission — not duplicated
        # in this bare-statement branch). Anything else awaited
        # is an honest whole-module refusal: _async_quick_eligible
        # already filtered out any *other* unrecognized AwaitExpr
        # shape before this method is ever reached for THIS function,
        # but the check is repeated here too (single source of truth
        # for what this step actually emits, not just what the cheap
        # pre-filter allowed through) since `_async_quick_eligible`'s
        # role is "worth attempting", not "guaranteed compilable".
        if isinstance(s.value, gimple_ctypes.AwaitExpr):
            if gen._cpp_emit_kind not in ('async', 'async_gen'):
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    "`await` is not supported in a generator body "
                    "(only in an async function body)")
            target = s.value.value
            if gimple_exprtypes._is_asyncio_sleep_call(target):
                self_fields = getattr(gen, '_cpp_gen_self_fields', None)
                arg_ctype = gimple_exprtypes._infer_simple_expr_ctype(target.args[0], declared, self_fields)
                if arg_ctype not in ('int64_t', 'double'):
                    raise gimple_exprtypes._UnsupportedAsyncShape(
                        "asyncio.sleep()'s argument must be a scalar "
                        "int64_t/double seconds expression")
                arg_expr = gen._cpp_expr(target.args[0])
                return [f"{indent}co_await _mojoasync_SleepAwaiter{{"
                        f"(uint64_t)((double)({arg_expr}) * 1e9)}};"]
            # Step D: a bare, value-DISCARDING `await <call to another
            # compiled async function>` statement — same real co_await/
            # composition machinery as the value-producing shape
            # (`x = await inner()`), just with the resulting value
            # thrown away rather than assigned. Delegates to the shared
            # _cpp_expr AwaitExpr case (single source of truth for the
            # actual `co_await <base>_Awaiter{...}` emission) instead of
            # duplicating it here; that method also owns the "anything
            # else is an honest refusal" fallback (unrecognized await
            # target, socket ops, ...), so no separate check is needed
            # in this branch.
            return [f"{indent}{gen._cpp_expr(s.value)};"]
        # `print(<one scalar arg>)` — a small, deliberate addition (not
        # part of the original Milestone B generator whitelist, which
        # has never needed a body-internal side effect since a
        # generator's own values are consumed from OUTSIDE it) added
        # specifically so Step B's async codegen has an observable way
        # to prove "constructing a coroutine does not run its body" —
        # see test_gimple_async_runner.py's laziness test, which relies
        # on a `print(...)` inside the async body only firing once the
        # coroutine is actually scheduled/run, never at bare
        # construction time. Available to generator bodies too (no
        # reason to special-case it out), just not yet exercised there.
        if (isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.IdentExpr)
                and s.value.func.name == 'print' and len(s.value.args) == 1
                and not getattr(s.value, 'kwargs', None)):
            self_fields = getattr(gen, '_cpp_gen_self_fields', None)
            arg_ctype = gimple_exprtypes._infer_simple_expr_ctype(s.value.args[0], declared, self_fields)
            if arg_ctype not in ('int64_t', 'double', '_Bool', 'char *'):
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    "print() argument must be a scalar int64_t/double/"
                    "_Bool/char* expression")
            arg_expr = gen._cpp_expr(s.value.args[0])
            fmt = {'int64_t': '"%lld\\n"', 'double': '"%g\\n"',
                   '_Bool': '"%s\\n"', 'char *': '"%s\\n"'}[arg_ctype]
            if arg_ctype == 'int64_t':
                return [f"{indent}printf({fmt}, (long long){arg_expr});"]
            if arg_ctype == '_Bool':
                return [f'{indent}printf({fmt}, ({arg_expr}) ? "True" : "False");']
            return [f"{indent}printf({fmt}, {arg_expr});"]
        # A bare call to a captured (or scalar-parameter) function-type
        # value — device_context.mojo's `async def wrapper(...)
        # capturing -> None: func()`/`func(idx)`, the ENTIRE body of
        # each of its four `wrapper` closures. `declared[name] ==
        # 'int64_t'` is this coroutine sub-compiler's own convention for
        # an opaque callable pointer (mirrors the ordinary, non-async
        # GIMPLE path's identical `_fname_var_ctype in ('int', 'int64_t',
        # 'void *', '_Bool')` guard in _lower_call/_gen_stmt_ExprStmt —
        # see _lower_fnptr_call). Uses the SAME mojo_fnptr_call_N()
        # runtime helper (declared `static inline` in mojo_runtime.h,
        # which this .cpp translation unit already #includes) rather
        # than inventing a second indirect-call convention — only 0-4
        # scalar arguments are supported, matching that helper's own
        # fixed arity family.
        if (isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.IdentExpr)
                and s.value.func.name in declared
                and declared[s.value.func.name] == 'int64_t'
                and not getattr(s.value, 'kwargs', None)
                and len(s.value.args) <= 4):
            fname = s.value.func.name
            self_fields = getattr(gen, '_cpp_gen_self_fields', None)
            arg_exprs = []
            for a in s.value.args:
                actype = gimple_exprtypes._infer_simple_expr_ctype(a, declared, self_fields, gen._async_api)
                if actype not in ('int64_t', 'double', '_Bool', 'char *'):
                    raise gimple_exprtypes._UnsupportedAsyncShape(
                        f"calling captured function '{fname}': argument "
                        "must be a scalar int64_t/double/_Bool/char* expression")
                ae = gen._cpp_expr(a)
                if actype != 'int64_t':
                    ae = f"(int64_t)({ae})"
                arg_exprs.append(ae)
            helper = f"mojo_fnptr_call_{len(arg_exprs)}"
            call_args = ', '.join([f"(void *){fname}"] + arg_exprs)
            return [f"{indent}{helper}({call_args});"]
        # A bare `abort(...)` call (real Mojo's `std.os.abort`,
        # test_tracing.mojo's own `except e: abort(String(e))` shape) --
        # `abort`'s ENTIRE observable contract is "never returns,
        # terminates the process", regardless of its message argument,
        # which this narrow scalar-only coroutine-body model has no way
        # to represent faithfully anyway (a `String`/exception-object
        # value). Compiles to a real `abort()` (with a diagnostic on
        # stderr first) -- mirrors this file's own established "loud,
        # honest runtime failure, not silently wrong" pattern used
        # elsewhere for a provably-unreachable-in-practice call (see
        # `_lower_call`'s create_task/create_raising_task stub-branch
        # comment) -- correctness here doesn't depend on ever actually
        # reaching this statement at runtime (test_tracing.mojo's own
        # `with Trace[level](...): return lhs + rhs` guarded body,
        # elided per `_cpp_with_stmt`, never raises), only on it
        # COMPILING, since every statement in a function body must.
        if (isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.IdentExpr)
                and s.value.func.name == 'abort'):
            return [f'{indent}fprintf(stderr, "mojo: abort() called\\n");',
                    f"{indent}abort();"]
        # Bare CallExpr as statement: func(args)
        if isinstance(s.value, gimple_ctypes.CallExpr):
            return [f"{indent}{gen._cpp_expr(s.value)};"]
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            "unsupported expression statement in generator body "
            f"({type(s.value).__name__})")
    if isinstance(s, gimple_ctypes.AssignStmt):
        if isinstance(s.target, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr)):
            # Tuple unpacking: a, b = expr  →  a = expr[0]; b = expr[1]
            # A LIST-PATTERN target (`[tup] = [...]`, `[a, b] = [...]`)
            # is Python's other, less common but real, unpacking-target
            # spelling — semantically identical to the tuple-target
            # case (both just bind N names from N elements; the target
            # brackets vs. parens are a syntax choice, not a semantic
            # one), and `ListExpr`/`TupleExpr` share the exact same
            # `.elements` field shape (see mojo_compiler.py), so no
            # separate branch is needed — just widen the isinstance
            # check to accept both. Before this, `[tup] = [...]` (real:
            # Lib/test/crashers/gc_inspection.py's own generator `g`)
            # fell all the way through to the generic "only a plain
            # identifier assignment target is supported" refusal below,
            # even though the exact same decomposition this TupleExpr
            # branch already does applies unchanged. See
            # CODEGEN_generator_non_plain_assignment_target_refused.md.
            # When `expr` is a call to a module function returning a
            # MojoList* (tokenize.py's `encoding, consumed =
            # detect_encoding(readline)` — detect_encoding returns a
            # 2-element list), the element access must be the runtime
            # list getter, not a raw C++ `[...]` on a call expression.
            _tup_val = gen._cpp_expr(s.value)
            _tup_is_list_call = (isinstance(s.value, gimple_ctypes.CallExpr)
                and isinstance(s.value.func, gimple_ctypes.IdentExpr)
                and s.value.func.name in gen.func_return_types
                and gen.func_return_types[s.value.func.name] == 'MojoList *')
            # A bare Comprehension as the RHS (`[tup] = [x for x in ...]`,
            # Lib/test/crashers/gc_inspection.py's own `g` generator) also
            # lowers, via _cpp_expr's own Comprehension case just above,
            # to a genuine `MojoList *` value (`mojo_list_new ()` — an
            # honest always-empty stub, same simplification as every
            # other comprehension-as-value site in this codegen) — NOT a
            # C aggregate/array that supports `operator[]`. Without this,
            # the final `else` branch below emitted `(mojo_list_new
            # ())[0]`, which g++ rejects outright ("invalid types
            # 'MojoList*[int]' for array subscript"); route it through
            # the same runtime getter the MojoList*-returning-call case
            # above already uses instead.
            # A plain identifier RHS that's already a known MojoList*
            # local (e.g. `items = [x for x in ...]` two lines above,
            # now typed 'MojoList *' by _infer_simple_expr_ctype's own
            # Comprehension case — see that case's comment for the full
            # chain) — same underlying value shape as the direct-
            # Comprehension case just above, just reached through a
            # variable instead of inline. Mirrors the identical
            # `self._cpp_declared.get(name) == 'MojoList *'` check the
            # SliceExpr/full-slice-assignment branch elsewhere in this
            # method already uses for the same purpose.
            _tup_is_list_ident = (isinstance(s.value, gimple_ctypes.IdentExpr)
                and gen._cpp_declared is not None
                and gen._cpp_declared.get(s.value.name) == 'MojoList *')
            _tup_is_list_val = (_tup_is_list_call
                or isinstance(s.value, gimple_ctypes.Comprehension)
                or _tup_is_list_ident)
            # A call to a name this codegen has no real signature for
            # (e.g. `tempfile.mkstemp(...)` -- real Python's own
            # tempfile module, unresolved by this compiler's tracked
            # stdlib) lowers to a bare opaque scalar stub (`0`), not a
            # real tuple/MojoList*. Subscripting that stub (`(0)[i]`)
            # is invalid C++ ("invalid types 'int[int]' for array
            # subscript") -- found via importlib/resources/_common.py's
            # `fd, raw_path = tempfile.mkstemp(suffix=suffix)` inside a
            # generator body. `_tup_val` is still emitted above (for
            # any side effects a real call would have), just never
            # subscripted; every target gets the same safe-stub 0
            # every other unresolved-call site in this codegen already
            # falls back to.
            # Module-qualified calls (`tempfile.mkstemp(...)`) have a
            # MemberExpr func, not a bare IdentExpr -- must be caught
            # here too, not just the bare-name case _tup_is_list_call
            # already checks.
            if isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.IdentExpr):
                _tup_callee = s.value.func.name
            elif isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.MemberExpr):
                _tup_callee = s.value.func.member
            else:
                _tup_callee = None
            _tup_is_unresolved_call = (_tup_callee is not None
                and not _tup_is_list_val
                and _tup_callee not in gen.func_return_types
                and _tup_callee not in gen._KNOWN_SIGS)
            lines = []
            if _tup_is_unresolved_call:
                # Still emit the call itself (discarding its bogus
                # scalar result) so any real side effect the actual
                # external function would have isn't silently dropped.
                lines.append(f"{indent}(void)({_tup_val});")
            for i, el in enumerate(s.target.elements):
                if isinstance(el, gimple_ctypes.IdentExpr):
                    if el.name not in declared:
                        declared[el.name] = 'int64_t'
                        lines.append(f"{indent}int64_t {el.name};")
                    if _tup_is_list_val:
                        lines.append(f"{indent}{el.name} = "
                                     f"mojo_list_get_int((MojoList *)({_tup_val}), {i});")
                    elif _tup_is_unresolved_call:
                        lines.append(f"{indent}{el.name} = 0;")
                    else:
                        lines.append(f"{indent}{el.name} = ({_tup_val})[{i}];")
            return lines
        if not isinstance(s.target, gimple_ctypes.IdentExpr):
            # self.field = val  →  self->field = val
            if isinstance(s.target, gimple_ctypes.MemberExpr) and isinstance(s.target.obj, gimple_ctypes.IdentExpr) \
                    and s.target.obj.name == 'self' and getattr(gen, '_cpp_gen_self_struct', None):
                val = gen._cpp_expr(s.value)
                return [f"{indent}self->{gimple_ctypes._safe_field(s.target.member)} = {val};"]
            # arr[i] = val / d[k] = val  →  a real runtime-helper write
            # (mojo_list_set_*/mojo_dict_set_*), mirroring the plain
            # (non-generator) GIMPLE path's own SubscriptExpr-target
            # lowering (see _gen_stmt_AssignStmt's isinstance(node.
            # target, SubscriptExpr) branch above in this file) --
            # NOT a raw C++ `obj[idx] = val`, which was this branch's
            # ORIGINAL lowering and is actually invalid C++ for a real
            # MojoList*/MojoDict* target: neither exposes operator[]
            # anywhere in mojo_runtime.h (confirmed by grep -- no such
            # overload exists), so `g++` rejected it outright ("no
            # viable overloaded '='") the moment a declared MojoList*/
            # MojoDict* identifier actually reached this branch, e.g.
            # `def gen(d): d[0] = 99`. This was undiscovered because no
            # real corpus occurrence this doc's earlier passes fixed
            # happened to hit a DECLARED-typed container here (the
            # confirmed real occurrences were self-field/tuple-unpack/
            # sys.attr/slice-assign shapes) -- see CODEGEN_generator_
            # non_plain_assignment_target_refused.md's 2026-08-19
            # update. Only handles the two KNOWN declared-type cases
            # (positive proof, same "no ambiguous default" bar the
            # full-slice-assign branch below already uses); any other
            # object type (untracked/int64_t/char*/a real C array
            # param) falls through to the original raw-subscript
            # lowering unchanged -- that shape genuinely does compile
            # (e.g. a fixed-size C array parameter), so it must stay.
            if isinstance(s.target, gimple_ctypes.SubscriptExpr):
                obj = gen._cpp_expr(s.target.obj)
                idx = gen._cpp_expr(s.target.index)
                val = gen._cpp_expr(s.value)
                obj_ct = (gen._cpp_declared.get(s.target.obj.name)
                          if gen._cpp_declared is not None
                          and isinstance(s.target.obj, gimple_ctypes.IdentExpr) else None)
                self_fields = getattr(gen, '_cpp_gen_self_fields', None)
                if obj_ct == 'MojoList *':
                    vctype = gimple_exprtypes._infer_simple_expr_ctype(
                        s.value, gen._cpp_declared, self_fields, gen._async_api)
                    idx64 = f"(int64_t)({idx})"
                    if vctype == 'char *':
                        return [f"{indent}mojo_list_set_str(({obj}), {idx64}, {val});"]
                    if vctype == 'double':
                        return [f"{indent}mojo_list_set_double(({obj}), {idx64}, {val});"]
                    return [f"{indent}mojo_list_set_int(({obj}), {idx64}, (int64_t)({val}));"]
                if obj_ct == 'MojoDict *':
                    key_expr = gen._cpp_dict_key_expr(s.target.index, idx)
                    vctype = gimple_exprtypes._infer_simple_expr_ctype(
                        s.value, gen._cpp_declared, self_fields, gen._async_api)
                    if vctype == 'char *':
                        return [f"{indent}mojo_dict_set_str(({obj}), {key_expr}, {val});"]
                    if vctype == 'double':
                        return [f"{indent}mojo_dict_set_double(({obj}), {key_expr}, {val});"]
                    return [f"{indent}mojo_dict_set_int(({obj}), {key_expr}, (int64_t)({val}));"]
                return [f"{indent}{obj}[{idx}] = {val};"]
            # sys.stderr/stdout/stdin = val (task #150's remaining
            # non-self-MemberExpr gap, e.g. test_faulthandler.py's
            # `sys.stderr = None`): `sys` has no real backing value
            # ANYWHERE in this narrow generator-body model -- _cpp_
            # expr's IdentExpr case has no case at all for a bare
            # module name, and _is_sys_stderr (this codegen's ONLY
            # existing recognition of `sys.stderr`, used by _gen_
            # print's `file=sys.stderr` kwarg match) treats it as a
            # compile-time STRUCTURAL marker, never a real runtime
            # value -- reading `sys.stderr` outside that one
            # structural position is already unsupported (would
            # lower to a bare, undefined `sys` C++ identifier via
            # _cpp_expr's IdentExpr fallthrough). So there is no real
            # "current stderr/stdout/stdin" value anywhere in this
            # model for an assignment to actually change, and eliding
            # the assignment can't discard any behavior this codegen
            # could otherwise observe -- it just lets the surrounding
            # function's OTHER statements be reached (and accepted or
            # refused on their own separate merits) instead of the
            # whole function being refused solely because of this one
            # line. Still evaluates the RHS (mirrors the tuple-unpack
            # branch's identical unresolved-call side-effect-discard
            # pattern above). See CODEGEN_generator_non_plain_
            # assignment_target_refused.md. Every OTHER non-self
            # MemberExpr target (a real object's attribute) remains
            # refused below -- unlike `sys`, a real object might have
            # an observable backing value elsewhere, so silently
            # eliding those would risk actually-wrong behavior, not
            # just a no-op on an already-fictional value.
            # `dont_write_bytecode` widened alongside stderr/stdout/
            # stdin (same rationale: confirmed via grep to have no
            # backing value anywhere else in this file either) — found
            # via Tools/importbench/importbench.py's `sys.dont_write_
            # bytecode = True`/`= False` (see COMPILE_FAIL_Tools_
            # importbench_importbench.md's "gap 3").
            if isinstance(s.target, gimple_ctypes.MemberExpr) and isinstance(s.target.obj, gimple_ctypes.IdentExpr) \
                    and s.target.obj.name == 'sys' \
                    and s.target.member in ('stderr', 'stdout', 'stdin', 'dont_write_bytecode'):
                val = gen._cpp_expr(s.value)
                return [f"{indent}(void)({val});"]
            # x[:] = value  (full-slice replace-in-place; real
            # occurrences: Lib/test/support/__init__.py's patch_list
            # (`orig[:] = saved`) and iter_builtin_types (`subs[:] =
            # []`), both exactly this shape -- start=stop=step=None.
            # `x[a:b] = y` parses to a bare SliceExpr TARGET (not
            # wrapped in SubscriptExpr -- see mojo_compiler.py's
            # `_parse_postfix`), so it falls into this MemberExpr/
            # SubscriptExpr-shaped branch, not the arr[i]=val one
            # above. Unlike the sys.stderr elision above, this is
            # REAL correct behavior, not a no-op: a slice-assignment
            # target must mutate the SAME MojoList* object in place
            # (other references/aliases need to observe the change),
            # so this lowers to genuine, pre-existing runtime helpers
            # (mojo_list_clear + mojo_list_extend) rather than
            # discarding the statement. Only the FULL-slice case
            # (`x[:] = y`) is handled -- both real occurrences are
            # exactly this shape; a bounded/stepped slice-assign
            # (`x[a:b] = y`, `x[::2] = y`) needs real element-
            # shifting splice support (mirroring what mojo_list_
            # del_slice already does for deletion) and is a
            # meaningfully bigger step, not attempted here since no
            # real occurrence needs it -- falls through to the
            # generic refusal below unchanged.
            #
            # Type guard, found by hand-verifying patch_list's own
            # real body end-to-end (not just the eligibility gate):
            # `saved = orig[:]` two lines above types `saved` as
            # `char *` (`_infer_simple_expr_ctype`'s `if isinstance(e,
            # SliceExpr): return 'char *'` -- this narrow model reads
            # EVERY slice as a string, a separate pre-existing gap,
            # see this doc's own notes on list-slice READS). Blindly
            # reinterpret-casting a real char*/double/_Bool value to
            # MojoList* and calling mojo_list_clear/extend on it would
            # SYNTAX-compile (an explicit C-style pointer cast is
            # always legal) but corrupt memory or crash at runtime --
            # exactly the "silently wrong or broken code" this whole
            # codegen otherwise refuses to emit.
            #
            # The TARGET (container being written into) stays
            # permissive of an untracked/int64_t-default type -- same
            # "ambiguous/untracked boxed value is assumed to be a
            # list" heuristic the plain codegen path's DelStmt
            # SliceExpr branch already uses, and in practice it's
            # almost always a parameter (reliably typed from function
            # entry, see param_ctypes seeding `declared` before any
            # statement is processed).
            #
            # The RHS is held to a STRICTER bar -- exactly 'MojoList
            # *', no ambiguous-default fallback -- because of a
            # separate, confirmed hazard specific to a value:
            # `_cpp_try_stmt` translates a `finally:` block's
            # statements BEFORE the preceding `try:` block's (see its
            # own body -- `finally_lines` is computed first), so a
            # name first assigned inside the `try:` (like `saved`
            # here) is NOT YET in `declared` at the point THIS
            # statement (inside `finally:`) is translated -- it reads
            # back as untracked (None), not as its eventual real type,
            # even though that real type will end up being the
            # definitively-wrong 'char *' once the try block is
            # actually processed. Treating that untracked None as
            # "assume list" here would be silently wrong for exactly
            # patch_list's own real shape; requiring positive proof
            # (declared[name] == 'MojoList *') instead means this
            # exact case is refused (as it must be, since the RHS
            # really is a string here) while a genuinely list-typed
            # RHS identifier (resolved at a point in program order
            # where its type IS already known) still gets the real
            # fix.
            if (isinstance(s.target, gimple_ctypes.SliceExpr) and s.target.start is None
                    and s.target.stop is None and s.target.step is None
                    and isinstance(s.target.obj, gimple_ctypes.IdentExpr)):
                obj_ct = (gen._cpp_declared.get(s.target.obj.name)
                          if gen._cpp_declared is not None else None)
                if obj_ct not in (None, 'MojoList *', 'int64_t'):
                    raise gimple_exprtypes._UnsupportedGeneratorShape(
                        "full-slice assignment target's declared type "
                        f"({obj_ct!r}) is not a list")
                obj = gen._cpp_expr(s.target.obj)
                obj_lp = obj if obj_ct == 'MojoList *' else f"((MojoList *)({obj}))"
                if isinstance(s.value, gimple_ctypes.ListExpr) and not s.value.elements:
                    # x[:] = []  -- an empty-list RHS lowers (via the
                    # ListExpr case above) to a C++ brace-init-list
                    # ('{}'), not a real MojoList*, so it can't be
                    # passed to mojo_list_extend -- but "replace with
                    # nothing" is just a clear, so this exact, real,
                    # confirmed shape (iter_builtin_types) needs no
                    # extend call at all.
                    return [f"{indent}mojo_list_clear({obj_lp});"]
                if (isinstance(s.value, gimple_ctypes.IdentExpr) and gen._cpp_declared is not None
                        and gen._cpp_declared.get(s.value.name) == 'MojoList *'):
                    val = gen._cpp_expr(s.value)
                    return [f"{indent}mojo_list_clear({obj_lp});",
                            f"{indent}mojo_list_extend({obj_lp}, {val});"]
                # Any other RHS shape (a non-empty list/tuple literal,
                # a call result not statically known to be a
                # MojoList*, ...) has no safe representation to
                # extend from in this narrow model -- refuse honestly
                # rather than emit ill-typed/silently-wrong C++.
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "only a plain identifier assignment target is supported")
        name = s.target.name
        # A list/dict/set LITERAL RHS (`lines = []`, ftplib.py's mlsd) is
        # NOT representable as the raw C++ brace-init text `_cpp_expr`'s
        # literal cases emit — for a container-typed local that text must
        # become a real runtime construction instead (`mojo_list_new()` +
        # element appends). Handled for BOTH the first assignment (which
        # also declares the local with its real container type via
        # `_infer_simple_expr_ctype`'s matching cases) and any later
        # re-assignment of an already-container-typed local.
        _container_literal = isinstance(s.value, (gimple_ctypes.ListExpr,
                                                  gimple_ctypes.DictExpr,
                                                  gimple_ctypes.SetExpr))
        val = gen._cpp_expr(s.value)
        # See self._cpp_kw_param_renames's docstring — an assignment
        # TARGET is emitted directly (`name = val`, bypassing
        # _cpp_expr's own IdentExpr branch entirely), so a keyword-
        # named coroutine parameter being REASSIGNED needs the exact
        # same rename applied here too, or its write and every read
        # of it would disagree. A brand-new local (first assignment,
        # `name not in declared` below) that itself happens to be
        # named a C/C++ keyword is a separate, rarer shape this fix
        # also covers by the same rename-and-remember mechanism, so
        # it doesn't regress the moment a local variable (not just a
        # parameter) collides with a keyword.
        if name in gen._cpp_kw_param_renames:
            cpp_name = gen._cpp_kw_param_renames[name]
        elif name in gimple_ctypes._C_KEYWORDS or name in gimple_ctypes._CPP_KEYWORD_FIELDS or name in gimple_ctypes._C_PARAM_EXTRA_KEYWORDS:
            cpp_name = f"_kw_{name}"
            gen._cpp_kw_param_renames[name] = cpp_name
        else:
            cpp_name = name
        if name not in declared:
            # `x = StructName(args)` — see `_cpp_expr`'s CallExpr
            # struct-constructor branch just above, which already
            # lowered `val` to a real `[&]() -> {Struct} * {...}()`
            # construction expression for exactly this shape; give the
            # LOCAL the matching real pointer type here instead of
            # letting it fall through `_infer_simple_expr_ctype` (which
            # has no notion of struct constructors at all) to the
            # int64_t default below — that mismatch is what produced
            # "assignment to 'int64_t' from 'TestHook *'" originally.
            if (isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.IdentExpr)
                    and s.value.func.name in gen._cpp_ctor_struct_names):
                ctype = f"{s.value.func.name} *"
            elif gen._cpp_is_callable_value_expr(s.value):
                # A zero-arg `lambda` / bound-method-as-value RHS (see
                # `_cpp_is_callable_value_expr`'s docstring) — give the
                # local this coroutine model's one callable-value
                # declared type instead of letting it fall through
                # `_infer_simple_expr_ctype` (which has no notion of
                # either shape) to the int64_t default below, which
                # would mismatch the real `std::function<...>`-
                # convertible value `_cpp_expr` actually emits for it.
                ctype = gimple_ctypes._CPP_CALLABLE_CTYPE
            else:
                ctype = gimple_exprtypes._infer_simple_expr_ctype(
                    s.value, declared, getattr(gen, '_cpp_gen_self_fields', None),
                    gen._async_api,
                    fn_return_types=_cpp_trusted_fn_return_types(gen))
            if ctype is None:
                ctype = 'int64_t'  # default for unknown-type locals
            declared[name] = ctype
            # A call to a module-level function whose every value-return is
            # provably a dict/list (`_cpp_fn_container_shape`) — record the
            # local's container kind so a later `local['key']` /
            # `local[i]` subscript lowers through the real runtime dict/list
            # getter instead of the string-substring fallback. The local's
            # STORAGE type stays the boxed int64_t (the .c side stores
            # cross-function container values exactly that way), so this
            # side map — not `declared` — carries the extra knowledge.
            if (ctype == 'int64_t' and isinstance(s.value, gimple_ctypes.CallExpr)
                    and isinstance(s.value.func, gimple_ctypes.IdentExpr)):
                _shp = _cpp_fn_container_shape(gen, s.value.func.name)
                if _shp:
                    gen._cpp_local_container_shapes[name] = _shp
            if (ctype == 'MojoList *' and isinstance(s.value, gimple_ctypes.CallExpr)
                    and isinstance(s.value.func, gimple_ctypes.IdentExpr)):
                _ret_elem = gen._return_elem_types.get(s.value.func.name)
                if _ret_elem:
                    reg = getattr(gen, '_cpp_list_local_elem_types', None)
                    if reg is not None:
                        reg[name] = _ret_elem
            # Hoist the declaration to the coroutine's top (function)
            # scope so a local first-assigned inside a `try:`/`for:` body
            # is still visible to a sibling `else:`/post-loop block (the
            # exact mimetypes `ctype` / shelve-analogue failure mode).
            # C++ coroutine frames outlive every block, so a function-
            # scope local is sound and matches Python's function (not
            # block) scoping. The inline text emitted here is now just the
            # block-scoped ASSIGNMENT; the DECLARATION was deferred into
            # `_cpp_func_scope_decls` (init/cleared per coroutine unit)
            # and is emitted at the top of the impl body.
            if gen._cpp_func_scope_decls is not None:
                gen._cpp_func_scope_decls.append(
                    f"{gimple_exprtypes._c_to_cpp_scalar_type(ctype)} {cpp_name};")
            if _container_literal and ctype in ('MojoList *', 'MojoDict *', 'MojoSet *'):
                init = _cpp_container_literal_init(gen, cpp_name, s.value, indent)
                if init is not None:
                    return init
            return [f"{indent}{cpp_name} = {val};"]
        if _container_literal and declared.get(name) in ('MojoList *', 'MojoDict *', 'MojoSet *'):
            init = _cpp_container_literal_init(gen, cpp_name, s.value, indent)
            if init is not None:
                return init
        # A mutated-by-reference capture (see `_gen_cpp_async_unit`'s
        # `mut_capture_names` docstring) is a pointer parameter -- the
        # WRITE must go through it (`*name = ...`), not overwrite the
        # pointer itself.
        if name in gen._cpp_mut_capture_names:
            return [f"{indent}*{cpp_name} = {val};"]
        return [f"{indent}{cpp_name} = {val};"]
    if isinstance(s, gimple_ctypes.AugAssignStmt):
        if not isinstance(s.target, gimple_ctypes.IdentExpr) or s.target.name not in declared:
            # self.field += val  →  self->field = self->field op val
            if isinstance(s.target, gimple_ctypes.MemberExpr) and isinstance(s.target.obj, gimple_ctypes.IdentExpr) \
                    and s.target.obj.name == 'self' and getattr(gen, '_cpp_gen_self_struct', None):
                op = gimple_ctypes._GD_BIN_OPS.get(s.op, s.op)
                val = gen._cpp_expr(s.value)
                return [f"{indent}self->{gimple_ctypes._safe_field(s.target.member)} = self->{gimple_ctypes._safe_field(s.target.member)} {op} {val};"]
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "augmented assignment to an undeclared/non-simple target")
        op = gimple_ctypes._GD_BIN_OPS.get(s.op, s.op)
        val = gen._cpp_expr(s.value)
        name = s.target.name
        # Same by-reference dereference as AssignStmt just above --
        # test_locks.mojo's own `rawCounter += 1` shape.
        if name in gen._cpp_mut_capture_names:
            return [f"{indent}*{name} = *{name} {op} {val};"]
        return [f"{indent}{name} = {name} {op} {val};"]
    if isinstance(s, gimple_ctypes.WhileStmt):
        lines = gen._cpp_hoist_walrus_decls(s.condition, declared, indent)
        cond = gen._cpp_expr(s.condition)
        if s.else_body:
            brk_var = gen._cpp_fresh_name("_mg_brk")
            lines.append(f"{indent}bool {brk_var} = false;")
            lines.append(f"{indent}while ({cond}) {{")
            for inner in s.body:
                lines.extend(gen._cpp_stmt_with_break_flag(inner, declared, indent + '    ', brk_var))
            lines.append(f"{indent}}}")
            lines.append(f"{indent}if (!{brk_var}) {{")
            for inner in s.else_body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
        else:
            lines.append(f"{indent}while ({cond}) {{")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
        return lines
    if isinstance(s, gimple_ctypes.IfStmt):
        # Dead-branch elimination for a fully compile-time-decidable
        # if/elif/.../else chain (see `_cpp_short_circuit_bool`'s
        # docstring): if EVERY branch's condition, evaluated in order
        # with real Python short-circuit `and`/`or` semantics, resolves
        # to a definite True/False, pick the first True branch (or
        # `else`) and emit ONLY its body, unconditionally — never
        # emitting the untaken branches' condition/body text at all.
        # This lets a host-platform guard like `if sys.platform ==
        # 'win32' and self.file_type == SomeEnum.WINDOWS_ONLY:` compile
        # even though `SomeEnum` (a top-level class) isn't threaded into
        # this generator's coroutine scope — on a non-Windows host the
        # left operand alone already proves the branch dead, so the
        # right operand's own unresolvability is moot, exactly like
        # CPython itself never evaluating it. Falls back to the
        # original verbatim-condition emission the moment any branch in
        # the chain isn't fully decidable this way (the overwhelmingly
        # common case — an ordinary runtime-dependent `if`).
        _branches = [(s.condition, s.then_body)] + list(s.elifs)
        _resolved = []
        _fully_determined = True
        for _cond, _body in _branches:
            _v = gen._cpp_short_circuit_bool(_cond)
            _resolved.append((_v, _body))
            if _v is None:
                _fully_determined = False
                break
        if _fully_determined:
            for _v, _body in _resolved:
                if _v:
                    lines = []
                    for inner in _body:
                        lines.extend(gen._cpp_stmt(inner, declared, indent))
                    return lines
            lines = []
            if s.else_body:
                for inner in s.else_body:
                    lines.extend(gen._cpp_stmt(inner, declared, indent))
            return lines
        lines = gen._cpp_hoist_walrus_decls(s.condition, declared, indent)
        cond = gen._cpp_expr(s.condition)
        lines.append(f"{indent}if ({cond}) {{")
        for inner in s.then_body:
            lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
        lines.append(f"{indent}}}")
        for econd, ebody in s.elifs:
            lines.append(f"{indent}else if ({gen._cpp_expr(econd)}) {{")
            for inner in ebody:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
        if s.else_body:
            lines.append(f"{indent}else {{")
            for inner in s.else_body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
        return lines
    if isinstance(s, gimple_ctypes.BreakStmt):
        return [f"{indent}break;"]
    if isinstance(s, gimple_ctypes.ContinueStmt):
        return [f"{indent}continue;"]
    if isinstance(s, gimple_ctypes.ReturnStmt):
        if gen._cpp_emit_kind == 'async':
            # Step B's whole target shape: `return <scalar-expr>` is how
            # this narrow async function's one result gets produced —
            # the exact opposite of the generator case just below (a
            # generator's `return` ends iteration with NO value; an
            # async function's `return` IS its one value). A bare
            # `return` with no value isn't in this step's scope (the
            # eligibility scan requires a genuine scalar result).
            if s.value is None:
                raise gimple_exprtypes._UnsupportedAsyncShape(
                    "bare `return` (no value) not supported in an async "
                    "function this step — a scalar return value is "
                    "required")
            return [f"{indent}co_return {gen._cpp_expr(s.value)};"]
        if s.value is not None:
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "`return <value>` inside a generator is not supported "
                "(a generator's `return` ends iteration with no value, "
                "unlike an ordinary function's `return`)")
        return [f"{indent}co_return;"]
    if isinstance(s, gimple_ctypes.TryStmt):
        return gen._cpp_try_stmt(s, declared, indent)
    if isinstance(s, gimple_ctypes.RaiseStmt):
        return gen._cpp_raise_stmt(s, indent)
    if isinstance(s, gimple_ctypes.ForStmt):
        if not s.is_async:
            return gen._cpp_for_stmt(s, declared, indent)
        return gen._cpp_async_for_stmt(s, declared, indent)
    if isinstance(s, gimple_ctypes.WithStmt):
        return gen._cpp_with_stmt(s, declared, indent)
    if isinstance(s, gimple_ctypes.AssertStmt):
        return []  # assert is a no-op in compiled generators
    if isinstance(s, gimple_ctypes.MultiAssignStmt):
        # a = b = expr → declare ALL targets, assign value to each.
        # Unlike the ordinary AssignStmt case just above, this never
        # actually DECLARED a first-seen target as a real C++ local —
        # it recorded the (always-int64_t-guessed) type into `declared`
        # (the PYTHON-side bookkeeping dict) and emitted the assignment
        # line, but no `{ctype} {name};` ever reached the emitted text
        # at all — g++: "use of undeclared identifier". Real:
        # ipaddress.py's `_find_address_range`: `first = last =
        # next(it)`. Fixed by mirroring AssignStmt's own two-part
        # fix exactly: infer each NEW target's real ctype from the
        # value (same `_infer_simple_expr_ctype` call, same self/
        # struct-method-call special case `_cpp_hoist_walrus_decls`
        # already added, for consistency — a `first = last = self.
        # method()` shape would hit the identical gap otherwise), and
        # hoist the declaration into `_cpp_func_scope_decls` (function
        # scope, not this block) — needed for the exact same reason
        # AssignStmt's own comment documents: a name first assigned
        # inside a `try:`/`for:` body must stay visible to a sibling
        # `else:`/post-loop block, and this project's C++ coroutine
        # frames outlive every block, so function scope is sound and
        # matches Python's own function-level (not block-level)
        # scoping.
        if s.targets:
            val = gen._cpp_expr(s.value)
            lines = []
            for t in s.targets:
                tname = t if isinstance(t, str) else (t.name if isinstance(t, gimple_ctypes.IdentExpr) else None)
                if tname is None:
                    continue
                if tname not in declared:
                    vt = None
                    if isinstance(s.value, gimple_ctypes.CallExpr) and isinstance(s.value.func, gimple_ctypes.MemberExpr):
                        _mf = s.value.func
                        _mstruct = None
                        if isinstance(_mf.obj, gimple_ctypes.IdentExpr) and _mf.obj.name == 'self':
                            _mstruct = getattr(gen, '_cpp_gen_self_struct', None)
                        elif isinstance(_mf.obj, gimple_ctypes.IdentExpr):
                            _mstruct = gen._cpp_struct_ptr_local(_mf.obj.name)
                        if _mstruct:
                            vt = gen.func_return_types.get(f"{_mstruct}_{_mf.member}")
                    if vt is None:
                        vt = gimple_exprtypes._infer_simple_expr_ctype(
                            s.value, declared, getattr(gen, '_cpp_gen_self_fields', None),
                            fn_return_types=_cpp_trusted_fn_return_types(gen))
                    if vt is None:
                        vt = 'int64_t'
                    declared[tname] = vt
                    if gen._cpp_func_scope_decls is not None:
                        gen._cpp_func_scope_decls.append(f"{gimple_exprtypes._c_to_cpp_scalar_type(vt)} {tname};")
                lines.append(f"{indent}{tname} = {val};")
            return lines
        return []
    if isinstance(s, gimple_ctypes.ComptimeVarStmt):
        # `comptime NAME = <value>` inside an async/generator coroutine
        # body -- test_tracing.mojo's own real shape (`comptime s1 =
        # "ENABLED: ..." if enabled else "DISABLED: ..."`, feeding a
        # `with Trace[level](s1, s2):` guard `_cpp_with_stmt` already
        # elides ENTIRELY as a no-op intrinsic -- see that method's own
        # docstring -- so `s1`/`s2` are never actually evaluated at
        # all here). Comptime values are compile-time-only by
        # definition (no runtime code either way -- mirrors the
        # ordinary GIMPLE path's identical `_gen_stmt_ComptimeVarStmt`
        # treatment), but THIS narrow scalar-only (int64_t/double/
        # _Bool) coroutine-body model has no representation for a
        # STRING comptime value at all (this repro's own shape) and no
        # comptime-folding evaluator of its own (unlike the ordinary
        # path's `self._comptime_vals`/`_eval_const`) -- so this is a
        # deliberate, narrow no-op skip, not a real fold: if `s.target`
        # were ever actually REFERENCED later as a plain identifier
        # (impossible in the with-elision shape above, since the whole
        # guard expression that would read it is never evaluated),
        # `_cpp_expr`'s own name resolution would raise its own honest
        # "unsupported identifier" refusal there -- never a silent
        # wrong value.
        return []
    if isinstance(s, gimple_ctypes.GlobalStmt):
        return []  # global declarations are compile-time-only in generators
    if isinstance(s, (gimple_ctypes.ImportStmt, gimple_ctypes.FromImportStmt)):
        return []  # imports are resolved at module scope; no-op in generators
    if isinstance(s, gimple_ctypes.FunctionDef):
        return []  # nested function definitions are compiled separately
    if isinstance(s, gimple_ctypes.DelStmt):
        return []  # del on a generator local is a no-op (compile-time)
    if isinstance(s, gimple_ctypes.MatchStmt):
        return gen._cpp_match_stmt(s, declared, indent)
    raise gimple_exprtypes._UnsupportedGeneratorShape(
        f"unsupported statement in generator body: {type(s).__name__}")


def _cpp_with_stmt(gen, s, declared: dict, indent: str) -> list[str]:
    """`with BlockingScopedLock(lock): <body>` / `with Trace[level](s1,
    s2): <body>` inside an async coroutine body (test_locks.mojo's/
    test_tracing.mojo's own real shapes, formerly gap (2): `_cpp_stmt`
    had no `WithStmt` case at all).

    This project's async runtime (runtime/mojo_async_runtime.cpp) is
    genuinely single-threaded and cooperative -- confirmed via a
    direct grep: no `pthread`/`std::thread`/worker-pool anywhere in
    that file. A coroutine's body therefore only ever yields control
    to another coroutine at an explicit `co_await`; nothing can
    interleave between two statements that contain no suspension
    point. A SCOPED LOCK GUARD whose only job is mutual exclusion is
    consequently a real, provable NO-OP for correctness in this
    specific runtime model -- not a shortcut or an approximation:
    there is no other coroutine that could ever actually contend for
    the lock mid-body. This reinterprets each type in `_ASYNC_NOOP_
    LOCK_GUARD_TYPES` (see that set's own docstring for why EACH one,
    individually, is safe to elide -- not all for the same reason) as
    a compiler-recognized intrinsic, exactly like `TaskGroup`/
    `create_task` already are, rather than genuinely compiling the
    real struct's body (in both cases, deep machinery -- `external_
    call`/`Atomic`-backed for `BlockingSpinLock`, GPU/DeviceContext-
    importing for `Trace` -- entirely outside this narrow scalar-only
    async codegen's model). The guarded expression itself (`lock` in
    `BlockingScopedLock(lock)`, `level`/`s1`/`s2` in `Trace[level](s1,
    s2)`) is never evaluated at all: eliding the whole guard means none
    of it is ever referenced, so it doesn't even need to be threaded
    through as a capture.

    Safety is enforced, not just asserted: an `await` anywhere in the
    protected body makes this an honest refusal instead of silently
    eliding a guard that would have been load-bearing across a real
    suspension point (where a DIFFERENT coroutine genuinely could run
    while this one is suspended) -- true for BOTH guard types (a real
    lock's mutual exclusion AND a real trace span's start/end timing
    would both be observably wrong if silently elided across one)."""
    _alias_decl_lines: list[str] = []
    for item in s.items:
        expr = item.expr
        gname = gen._cpp_with_guard_type_name(expr)
        if gname not in gen._ASYNC_NOOP_LOCK_GUARD_TYPES:
            if gen._cpp_emit_kind in ('async', 'async_gen'):
                raise gimple_exprtypes._UnsupportedAsyncShape(
                    "`with` inside an async function body is only "
                    "supported for a recognized no-op guard type "
                    f"({sorted(gen._ASYNC_NOOP_LOCK_GUARD_TYPES)}), not "
                    f"{type(expr).__name__}"
                    + (f" ({gname!r})" if gname else ""))
            else:
                # Plain (non-async) generator: elide the `with` and
                # just emit the body. The enter/exit aren't compiled
                # but the body's statements still execute. An `as name:`
                # alias IS still declared (as an opaque int64_t handle
                # — zipapp.py's `with open(archive, mode) as f:` yields
                # `f` later), so the body's references resolve; only the
                # enter/exit calls themselves are dropped.
                gname = None
                _al = item.alias
                if _al is not None and isinstance(_al, str) and _al not in declared:
                    declared[_al] = 'int64_t'
                    _alias_decl_lines.append(f"{indent}int64_t {_al};")
                elif _al is not None and isinstance(_al, gimple_ctypes.IdentExpr) and _al.name not in declared:
                    declared[_al.name] = 'int64_t'
                    _alias_decl_lines.append(f"{indent}int64_t {_al.name};")
                break
        if item.alias is not None and gen._cpp_emit_kind in ('async', 'async_gen'):
            raise gimple_exprtypes._UnsupportedAsyncShape(
                "`with ... as name:` is not supported for an async "
                f"no-op guard `with` ({gname} has no usable return "
                "value to bind)")
        elif item.alias is not None and isinstance(item.alias, str):
            declared[item.alias] = 'int64_t'
        elif item.alias is not None and isinstance(item.alias, gimple_ctypes.IdentExpr):
            declared[item.alias.name] = 'int64_t'
    if any(isinstance(n, gimple_ctypes.AwaitExpr) for st in s.body for n in gimple_exprtypes._walk_ast(st)):
        raise gimple_exprtypes._UnsupportedAsyncShape(
            "`await` inside a `with`-guarded body is not supported "
            "-- eliding the guard (this codegen's own no-op "
            "optimization, safe only because nothing else can "
            "interleave BETWEEN statements in this runtime's "
            "single-threaded cooperative scheduler) would be UNSAFE "
            "across a real suspension point, where another coroutine "
            "genuinely could run")
    lines: list[str] = list(_alias_decl_lines)
    for st in s.body:
        lines.extend(gen._cpp_stmt(st, declared, indent))
    return lines


def _cpp_for_generator_delegate(gen, target, call: 'CallExpr', body: list,
                                 declared: dict, indent: str,
                                 index_var: str = None,
                                 index_start_expr: str = '0') -> list[str]:
    """`for <target> in <call to another already-compiled generator>():`
    inside a coroutine body — an ordinary (non-`yield from`) consuming
    loop over a sibling generator (e.g. dis.py's
    `_get_instructions_bytes` doing `for offset, start_offset, op, arg
    in _unpack_opargs(original_code):`). `target` is either a plain str
    (single loop variable) or a list of names (a tuple target — see
    `_cpp_for_stmt`'s own "(a, b, ...)" string convention, already
    unwrapped by the caller).

    `index_var`/`index_start_expr`: optional support for `_cpp_for_stmt`'s
    NESTED-tuple-target `enumerate()` case (`for i, (y, m, d) in
    enumerate(self.itermonthdays3(...)):` — calendar.py's `itermonthdays4`)
    composing an `enumerate()` index with this same sub-generator drive
    loop, rather than duplicating it. When given, `index_var` is declared
    as an `int64_t` OUTSIDE the drive `while` loop (so it survives across
    iterations, unlike the per-iteration tuple-slot locals below),
    initialized to `index_start_expr` (supporting `enumerate(x, start)`'s
    optional 2nd argument the same way the flat-target case already
    does), and incremented once at the end of each iteration — an
    ordinary indexed-loop counter composed around the unchanged
    tuple-unpack/single-value logic below.

    Mirrors `_cpp_yield_from`'s existing sub-generator delegation drive
    loop almost exactly: same `<base>_start/_resume/_value/_destroy`
    calling convention over `self._generator_api`, same "callee must be
    a generator this compile has ALREADY translated" ordering
    constraint (this naturally means "defined earlier in the module",
    exactly like `yield from` — gen_module's multi-pass retry loop for
    generators that depend on a not-yet-compiled sibling applies here
    unchanged, since raising `_UnsupportedGeneratorShape` when `call.
    func.name` isn't in `self._generator_api` yet is exactly what makes
    a caller like `_get_instructions_bytes` retried in a later pass) —
    but DRIVES the sub-generator instead of re-`co_yield`ing: each
    produced value is assigned into the loop target(s) and the loop
    body runs, rather than delegating it onward. A tuple target is
    unboxed via the same `MojoList *`-of-boxed-elements convention
    `_cpp_yield_tuple` produces on the producer side and
    `_emit_generator_tuple_unpack` reads back on the plain-GIMPLE
    consumer side (`TypeLattice.list_suffix` picks the right
    `mojo_list_get_*` accessor per slot, from the callee's own
    registered `tuple_slot_ctypes`) — this is that same protocol's
    coroutine-body counterpart, which had no consumer at all before
    (only the GIMPLE side's `for`/comprehension consumers did).

    Raises `_UnsupportedGeneratorShape` (never emits invalid C++) for:
    the callee not being a genuinely-compiled generator yet (source-
    order/never-eligible), an argument-count mismatch, or (implicitly,
    via the caller's own pre-check) a tuple target paired with a
    non-tuple-yielding callee — all handled exactly like every other
    out-of-scope shape in this emitter, so an unsupported instance
    falls back to interpreting the whole module from source instead of
    miscompiling."""
    if call.kwargs:
        for kname, kexpr in call.kwargs:
            call.args.append(kexpr)
        call.kwargs = []
    # Set True only by the free-function self-recursion branch below —
    # read further down (the non-tuple value-consumption branch) to
    # decide between an explicit `vct` declaration and `auto` type
    # deduction. A `self.<method>()` generator-METHOD self-recursion
    # (the MemberExpr branch just below) is a separate, more complex
    # case not attempted here — stays False for that branch, matching
    # its existing (unchanged) refusal behavior.
    is_self_recursive = False
    # `self.method(...)` — a generator METHOD call (e.g. calendar.py's
    # `Calendar.itermonthdates` doing `for y, m, d in self.
    # itermonthdays3(year, month):`), resolved via
    # `self._generator_method_api` (keyed by (struct_name, method_name)
    # — see that dict's own population sites) instead of the
    # free-function `self._generator_api`. `<base>_start`'s first
    # parameter is the receiver itself (`_gen_cpp_generator_unit`
    # prepends `('self', f"{struct_name} *")` to a method's own
    # `param_ctypes`, mirroring `_gen_struct_method`'s identical
    # convention for an ordinary compiled method) — passed here as the
    # literal `self` (this delegating generator's OWN receiver; a
    # generator method can only ever be consumed via `self.<method>()`
    # in this scalar body model, never through an arbitrary struct-typed
    # local — see the `isinstance(call.func.obj, IdentExpr) and ...
    # 'self'` guard below), never a separately-evaluated expression.
    if isinstance(call.func, gimple_ctypes.MemberExpr):
        _self_struct = getattr(gen, '_cpp_gen_self_struct', None)
        if not (isinstance(call.func.obj, gimple_ctypes.IdentExpr)
                and call.func.obj.name == 'self' and _self_struct):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "`for ... in <expr>.<method>(...)` is only supported "
                "when <expr> is literally `self` inside a generator "
                "method on the same struct")
        sub_name = f"{_self_struct}.{call.func.member}"
        api = gen._generator_method_api.get((_self_struct, call.func.member))
        if (api is None or (_self_struct, call.func.member)
                not in gen._supported_generator_methods):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"`for ... in self.{call.func.member}(...)` does not "
                "consume a generator method this compile has itself "
                "already translated via the C++20-coroutine path "
                "(either it's not a generator this codegen supports, or "
                "it's defined LATER among this struct's methods — the "
                "consumed generator method must be defined earlier)")
        receiver_exprs = ['self']
    else:
        sub_name = call.func.name
        # Self-recursion: `for <target> in <this-same-function>(...):`
        # (real: glob.py's `_rlistdir`, which recurses into itself via
        # an ordinary consuming for-loop, not `yield from` — os.walk's
        # well-known recursive-directory-listing shape). Mirrors
        # `_cpp_yield_from`'s own `is_self_recursive` handling exactly,
        # for the identical chicken-and-egg reason documented there:
        # this function can never find ITSELF in `self._generator_api`
        # yet, since registration only happens after the whole compile
        # succeeds. Without this, every self-recursive generator that
        # consumes itself via a plain `for` (as opposed to `yield
        # from`) hard-refused on EVERY multi-pass retry (never just
        # "defined later" — a self-reference can never resolve via
        # reordering), taking the whole module down with it.
        _self_name = getattr(gen, '_cpp_gen_self_name', None)
        is_self_recursive = (_self_name is not None and sub_name == _self_name)
        if is_self_recursive:
            # Same locally-tracked self-context `_cpp_yield_from` uses
            # — no premature/partial registration into the real
            # (still-being-built) `self._generator_api` dict needed.
            # `value_ctype`/`tuple_slot_ctypes` are genuinely NOT known
            # yet (computed only after this whole generator's body
            # finishes, in `_gen_cpp_generator_unit`) — left as None;
            # the non-tuple value-consumption branch below uses C++
            # `auto` type deduction instead of a literal ctype for
            # exactly this reason (see its own comment), and the
            # tuple-target branch's existing `tuple_slot_ctypes is
            # None` check (just below) already refuses a tuple loop
            # target here honestly, rather than guessing.
            api = {'base': gen._cpp_gen_self_base,
                   'params': gen._cpp_gen_self_params,
                   'value_ctype': None, 'tuple_slot_ctypes': None}
            # Tell _gen_cpp_generator_unit (after this body-emission
            # pass completes) that `{base}_start`/`_resume`/`_value`/
            # `_destroy` need forward declarations ahead of `{impl}`'s
            # own definition — same flag `_cpp_yield_from` sets for the
            # identical reason (this body references its own
            # not-yet-textually-defined extern "C" wrappers).
            gen._cpp_gen_self_recursed = True
        else:
            api = gen._generator_api.get(sub_name)
            if api is None or sub_name not in gen._supported_generators:
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    f"`for ... in {sub_name}(...)` does not consume a generator "
                    "this compile has itself already translated via the "
                    "C++20-coroutine path (either it's not a generator this "
                    "codegen supports, or it's defined LATER in this module — "
                    "the consumed generator must be defined earlier)")
        receiver_exprs = []
    sub_params = api.get('params') or []
    if len(call.args) + len(receiver_exprs) != len(sub_params):
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"`for ... in {sub_name}(...)`: expected "
            f"{len(sub_params) - len(receiver_exprs)} argument(s), "
            f"got {len(call.args)}")
    arg_exprs = receiver_exprs + [gen._cpp_expr(a) for a in call.args]
    base = api['base']
    vct = api['value_ctype']
    tuple_slot_ctypes = api.get('tuple_slot_ctypes')
    is_tuple = isinstance(target, list)
    if is_tuple and tuple_slot_ctypes is None:
        # A tuple loop target (`for a, b in ...:`) but the callee isn't
        # actually a tuple-valued yielder (`_generator_tuple_yield_
        # slot_ctypes` found nothing to unify) — e.g. it yields a plain
        # scalar/string, or a real Python `for` over its results
        # wouldn't even type-check. Refuse honestly rather than
        # silently defaulting every slot to int64_t (which would read
        # back garbage from a single-scalar `MojoList` value on the
        # producer side, since `_cpp_yield_tuple`'s boxing convention
        # was never applied there at all).
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"`for {', '.join(target)} in {sub_name}(...)`: tuple loop "
            f"target but {sub_name!r} is not a tuple-valued generator")
    gen._yield_from_seq = getattr(gen, '_yield_from_seq', 0) + 1
    guard = f"__mojogen_forgen{gen._yield_from_seq}"
    args_text = ', '.join(arg_exprs)
    lines = [f"{indent}{{"]
    if index_var is not None:
        if index_var not in declared:
            declared[index_var] = 'int64_t'
        lines.append(f"{indent}    int64_t {index_var} = ({index_start_expr});")
    lines.append(f"{indent}    _mojogen_sub_guard {guard}"
        f"{{ {base}_start({args_text}), &{base}_destroy }};")
    lines.append(f"{indent}    while ({base}_resume({guard}.g)) {{")
    body_indent = indent + '        '
    if is_tuple:
        val_var = gen._cpp_fresh_name("_mg_forgen_val")
        lines.append(f"{body_indent}MojoList * {val_var} = {base}_value({guard}.g);")
        for i, nm in enumerate(target):
            slot_ct = tuple_slot_ctypes[i] if tuple_slot_ctypes and i < len(tuple_slot_ctypes) else 'int64_t'
            if nm not in declared:
                declared[nm] = slot_ct
                lines.append(f"{body_indent}{gimple_exprtypes._c_to_cpp_scalar_type(slot_ct)} {nm};")
            suf = gimple_ctypes.TypeLattice.list_suffix(slot_ct)
            if suf == 'double':
                lines.append(f"{body_indent}{nm} = mojo_list_get_double({val_var}, {i});")
            elif suf == 'str':
                lines.append(f"{body_indent}{nm} = mojo_list_get_str({val_var}, {i});")
            elif slot_ct == '_Bool':
                lines.append(f"{body_indent}{nm} = (bool)mojo_list_get_int({val_var}, {i});")
            else:
                lines.append(f"{body_indent}{nm} = mojo_list_get_int({val_var}, {i});")
    elif is_self_recursive:
        # `vct` is None here (this generator's own value_ctype is only
        # known AFTER its whole body finishes generating — see
        # _gen_cpp_generator_unit) — declare via C++ `auto` type
        # deduction instead of a literal ctype. This is provably
        # correct, not a guess: `_gen_cpp_generator_unit` always emits
        # a forward `extern "C"` declaration for `{base}_value`
        # (returning the eventual real `cpp_value_ctype`) whenever
        # `self._cpp_gen_self_recursed` was set (true here — set just
        # above), and that declaration is textually emitted before
        # `impl`'s own body (which is what `lines`, built here, becomes
        # part of) — see that method's own "Self-recursion" comment.
        # `target` is deliberately NOT added to `declared`: its real
        # ctype genuinely isn't known yet at this point, and declaring
        # it now with a wrong guess (e.g. always int64_t) would be
        # worse than leaving it absent — an absent name already falls
        # back to this codegen's existing "unknown identifier" handling
        # everywhere else (_cpp_expr's IdentExpr case emits the bare
        # C++ name, which is correct here since `target` genuinely IS
        # a real, `auto`-typed local by this point in the emitted
        # text). Residual known gap: a direct `yield <target>` later in
        # THIS SAME function's body (a "flatten" pattern with no other
        # concrete yield site to establish the real type from) would
        # still default to int64_t in `_generator_yield_ctype`'s
        # unify-across-every-yield-site walk — not the shape confirmed
        # here (glob.py's `_rlistdir` yields `x`/`_join(x, y)`, both
        # independently char*-typed, so the merge's "prefer char* if
        # either is a string" rule already gives the right answer
        # regardless).
        if target not in declared:
            lines.append(f"{body_indent}auto {target} = {base}_value({guard}.g);")
        else:
            lines.append(f"{body_indent}{target} = {base}_value({guard}.g);")
    else:
        if target not in declared:
            declared[target] = vct
            lines.append(f"{body_indent}{gimple_exprtypes._c_to_cpp_scalar_type(vct)} {target};")
        lines.append(f"{body_indent}{target} = {base}_value({guard}.g);")
    for inner in body:
        lines.extend(gen._cpp_stmt(inner, declared, body_indent))
    if index_var is not None:
        lines.append(f"{body_indent}{index_var}++;")
    lines.append(f"{indent}    }}")
    # Same Milestone-D pending-exception disambiguation _cpp_yield_from
    # already does at its own `_resume`-driven while-loop boundary (see
    # that method's docstring for the full reasoning) — `_resume`
    # reporting "no more values" is ambiguous between genuine
    # exhaustion and an uncaught exception that unwound the whole
    # sub-generator body; re-throw a real C++ exception here (never
    # mojo_raise()/longjmp from inside a coroutine frame) so `{guard}`'s
    # destructor still runs correctly during the throw's normal stack
    # unwind.
    lines.append(f"{indent}    if (mojo_exc_pending_get()) {{")
    lines.append(f"{indent}        mojo_exc_pending_set(0);")
    lines.append(f"{indent}        throw _MojoCppExc{{ mojo_exc_type_get(), "
                 f"mojo_exc_msg_get(), mojo_exc_obj_get() }};")
    lines.append(f"{indent}    }}")
    lines.append(f"{indent}}}")
    return lines


def _cpp_for_stmt(gen, s: 'ForStmt', declared: dict, indent: str) -> list[str]:
    """Plain `for <var> in <iterable>:` inside a generator body.
    Lowers to a C++ range-for or indexed loop over the iterable.
    Only supports iterable as a simple identifier or call expression."""
    target = s.target
    if isinstance(target, str) and target.startswith('(') and target.endswith(')'):
        # `for (a, b) in enumerate(iterable):` — tuple-unpack loop target
        # (statistics.py's `for n, x in enumerate(iterable, start=1):`,
        # the one shape this scalar body model supports: enumerate's
        # (index, value) pairs, each unpacked into a plain int64_t local).
        # Lowered as an indexed loop over the underlying list, assigning
        # the counter to the first target and each element to the second.
        # Any OTHER tuple-target shape falls through to the string-target
        # path below (which range-fors over the whole tuple-as-identifier,
        # or refuses honestly) — unchanged from the pre-enumerate behavior.
        # Depth-aware split — a naive `.split(',')` here breaks a
        # NESTED tuple target's own inner commas (`(i, (y, m, d))`
        # would wrongly split into 4 pieces: 'i', '(y', 'm', 'd)').
        _names = [t.strip() for t in gimple_ctypes._split_top_level_commas(target[1:-1]) if t.strip()]
        # `for i, (a, b, ...) in enumerate(...):` — a NESTED tuple
        # target whose second element is ITSELF a (flat, depth-1)
        # tuple of plain names (calendar.py's `itermonthdays4`: `for
        # i, (y, m, d) in enumerate(self.itermonthdays3(...)):`;
        # dis.py's `_find_imports`: `for i, (op, oparg) in
        # enumerate(opargs):`). Only recognized when the second
        # element is a flat parenthesized, comma-joined list of plain
        # identifiers — arbitrary further nesting isn't needed by
        # either real-world case and isn't attempted here.
        _nested_inner = None
        if len(_names) == 2 and _names[1].startswith('(') and _names[1].endswith(')'):
            _cand = [t.strip() for t in gimple_ctypes._split_top_level_commas(_names[1][1:-1]) if t.strip()]
            if _cand and all(gimple_ctypes.re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', n) for n in _cand):
                _nested_inner = _cand
        if (_nested_inner is not None
                and isinstance(s.iterable, gimple_ctypes.CallExpr)
                and isinstance(s.iterable.func, gimple_ctypes.IdentExpr)
                and s.iterable.func.name == 'enumerate'
                and s.iterable.args):
            # `enumerate`'s own iterable argument — may be a plain
            # collection expression OR a call to another compiled
            # generator (delegated to `_cpp_for_generator_delegate`,
            # composing its index-tracking `index_var` support with
            # that method's existing sub-generator drive loop).
            _idx_name = _names[0]
            _enum_src_node = s.iterable.args[0]
            _idx_start_expr = '0'
            if len(s.iterable.args) >= 2:
                _idx_start_expr = gen._cpp_expr(s.iterable.args[1])
            if not s.else_body and gen._cpp_iterable_is_delegatable_generator_call(_enum_src_node):
                return gen._cpp_for_generator_delegate(
                    _nested_inner, _enum_src_node, s.body, declared, indent,
                    index_var=_idx_name, index_start_expr=_idx_start_expr)
            # Plain collection: a `MojoList *` of boxed tuples — same
            # element-boxing convention the plain-GIMPLE `_gen_for_list`
            # tuple-target case already uses (each element is itself a
            # `MojoList *`, boxed as an int64_t pointer value, read back
            # via `mojo_list_get_int` per inner slot; narrow int64_t-only
            # default, matching the existing flat-target enumerate case's
            # own scalar-only assumption just above).
            _src = gen._cpp_expr(_enum_src_node)
            _ctr = gen._cpp_fresh_name("_mg_i")
            _tup = gen._cpp_fresh_name("_mg_tup")
            lines = []
            if _idx_name not in declared:
                declared[_idx_name] = 'int64_t'
                lines.append(f"{indent}int64_t {_idx_name};")
            for _nm in _nested_inner:
                if _nm not in declared:
                    declared[_nm] = 'int64_t'
                    lines.append(f"{indent}int64_t {_nm};")
            lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                         f"{_ctr} < mojo_list_len((MojoList *)({_src})); {_ctr}++) {{")
            lines.append(f"{indent}    {_idx_name} = ({_ctr} + ({_idx_start_expr}));")
            lines.append(f"{indent}    MojoList * {_tup} = "
                         f"(MojoList *)mojo_list_get_int((MojoList *)({_src}), {_ctr});")
            for _si, _nm in enumerate(_nested_inner):
                lines.append(f"{indent}    {_nm} = mojo_list_get_int({_tup}, {_si});")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        if len(_names) == 2 and _nested_inner is None and (isinstance(s.iterable, gimple_ctypes.CallExpr)
                and isinstance(s.iterable.func, gimple_ctypes.IdentExpr)
                and s.iterable.func.name == 'enumerate'
                and s.iterable.args):
            # `enumerate`'s own iterable argument may itself be a call to
            # another compiled generator (calendar.py's `itermonthdays2`:
            # `for i, d in enumerate(self.itermonthdays(year, month),
            # self.firstweekday):`) — delegate to
            # `_cpp_for_generator_delegate`, composing its sub-generator
            # drive loop with the same `index_var`/`index_start_expr`
            # index-tracking support the NESTED-tuple-target case just
            # above uses (this is that composition's flat-target twin:
            # the value slot is the generator's own yielded scalar,
            # assigned through its registered `value_ctype`, never a
            # boxed-tuple read-back). Without this, `_cpp_expr` lowered
            # the generator call through the ordinary (non-coroutine)
            # extern "C" stub — void-returning — producing "void value
            # not ignored as it ought to be" at g++ time.
            _enum_src_node = s.iterable.args[0]
            if not s.else_body and gen._cpp_iterable_is_delegatable_generator_call(_enum_src_node):
                _idx_start_expr = '0'
                if len(s.iterable.args) >= 2:
                    _idx_start_expr = gen._cpp_expr(s.iterable.args[1])
                return gen._cpp_for_generator_delegate(
                    _names[1], _enum_src_node, s.body, declared, indent,
                    index_var=_names[0], index_start_expr=_idx_start_expr)
            _src = gen._cpp_expr(s.iterable.args[0])
            _ctr = gen._cpp_fresh_name("_mg_i")
            # Optional 2-arg `enumerate(iterable, start)` form
            # (statistics.py's own motivating example in this
            # function's docstring above — `start=1` — was never
            # actually implemented until now: the loop counter always
            # started at 0 regardless of a `start` argument being
            # present). `_ctr` itself stays the 0-based list-access
            # index; only the value assigned to the user-visible
            # first target gets the offset added.
            _idx_expr = _ctr
            if len(s.iterable.args) >= 2:
                _start_e = gen._cpp_expr(s.iterable.args[1])
                _idx_expr = f"({_ctr} + ({_start_e}))"
            lines = []
            for _nm in _names:
                if _nm not in declared:
                    declared[_nm] = 'int64_t'
                    lines.append(f"{indent}int64_t {_nm};")
            lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                         f"{_ctr} < mojo_list_len((MojoList *)({_src})); {_ctr}++) {{")
            lines.append(f"{indent}    {_names[0]} = {_idx_expr};")
            lines.append(f"{indent}    {_names[1]} = "
                         f"mojo_list_get_int((MojoList *)({_src}), {_ctr});")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        # `for a, b, ... in <call to another already-compiled generator>
        # ():` — a PLAIN (non-`yield from`) consuming loop, inside a
        # coroutine body, over a sibling generator this same module has
        # already translated via the C++20-coroutine path, with a
        # non-`enumerate()` tuple target. Real: dis.py's
        # `_get_instructions_bytes` doing `for offset, start_offset, op,
        # arg in _unpack_opargs(original_code):`. Only intercepted when
        # the callee is BOTH a known compiled generator AND (since the
        # target is a tuple) itself a genuine tuple-valued yielder —
        # anything else (a dict/list `.items()`-shaped call, a struct
        # __iter__, ...) falls through to the pre-existing
        # single-bogus-identifier path below unchanged (see
        # bugs/CODEGEN_generator_function_Lib_weakref.md for that
        # separate, still-open gap).
        if not s.else_body and gen._cpp_iterable_is_delegatable_generator_call(s.iterable):
            return gen._cpp_for_generator_delegate(_names, s.iterable, s.body,
                                                      declared, indent)
        # `for k, v in <dict-typed expr>.items():` — a plain (non-generator)
        # dict iteration with a 2-name tuple target, inside a coroutine body.
        # Lowered through the SAME runtime protocol the ordinary GIMPLE
        # path's `for k, v in d.items():` tuple branch already uses:
        # mojo_dict_items builds a MojoList of boxed 2-element sub-lists
        # (keys always char*, values read as the int64_t convention), and
        # this unpacks each pair per-slot. Before this, any tuple target
        # over a non-enumerate/non-generator call fell through to the
        # string-target path below and emitted the whole comma-joined
        # target as ONE bogus C++ identifier (`for (auto k, wr : ...)`,
        # g++: "declaration of 'auto k' has no initializer"). Real: Lib/
        # weakref.py's WeakValueDictionary.items/keys and
        # WeakKeyDictionary.items/values. The `.items()` CALL itself is
        # lowered by _cpp_expr's own `<dict>.items()` case; here only the
        # loop shape is built, so the receiver expression is evaluated
        # exactly once into a cached list local (a `.copy()` receiver
        # must not re-run per iteration).
        if (len(_names) == 2
                and isinstance(s.iterable, gimple_ctypes.CallExpr)
                and isinstance(s.iterable.func, gimple_ctypes.MemberExpr)
                and s.iterable.func.member == 'items'
                and not s.iterable.args
                and not s.else_body
                and _cpp_receiver_ctype(gen, s.iterable.func.obj) == 'MojoDict *'):
            _dsrc = gen._cpp_expr(s.iterable.func.obj)
            _items = gen._cpp_fresh_name("_mg_items")
            _ctr = gen._cpp_fresh_name("_mg_i")
            _pair = gen._cpp_fresh_name("_mg_pair")
            lines = []
            for _nm, _ct in ((_names[0], 'char *'), (_names[1], 'int64_t')):
                if _nm not in declared:
                    declared[_nm] = _ct
                    lines.append(f"{indent}{gimple_exprtypes._c_to_cpp_scalar_type(_ct)} {_nm};")
            lines.append(f"{indent}MojoList *{_items} = "
                         f"mojo_dict_items((MojoDict *)({_dsrc}));")
            lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                         f"{_ctr} < mojo_list_len({_items}); {_ctr}++) {{")
            lines.append(f"{indent}    MojoList *{_pair} = "
                         f"(MojoList *)mojo_list_get_int({_items}, {_ctr});")
            lines.append(f"{indent}    {_names[0]} = mojo_list_get_str({_pair}, 0);")
            lines.append(f"{indent}    {_names[1]} = mojo_list_get_int({_pair}, 1);")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        target = target[1:-1]
    if isinstance(target, str):
        # `for x in <call to another already-compiled generator>():` —
        # the single-loop-variable sibling of the tuple-target case just
        # above (same delegation machinery, no per-slot unpack needed).
        # Checked before the generic `_cpp_expr`/range-for fallback
        # below: that fallback has no notion of `self._generator_api` at
        # all, so it previously emitted a call through the WRONG
        # (non-coroutine, arity/return-type-mismatched) extern "C"
        # declaration gen_module's "module-level symbols referenced by
        # generator bodies" preamble falls back to for any unrecognized
        # callee — invalid C++, not just a missed optimization.
        if not s.else_body and gen._cpp_iterable_is_delegatable_generator_call(s.iterable):
            return gen._cpp_for_generator_delegate(target, s.iterable, s.body,
                                                      declared, indent)
        target_was_declared = target in declared
        declared[target] = 'int64_t'
        # `for i in range(...)` → a plain indexed loop, mirroring the
        # GIMPLE path's _gen_for_range. The C++20-coroutine body can't
        # range-for over mojo_range()'s opaque void* — an explicit
        # int64_t counter loop is the same semantics with no runtime
        # range object at all. Handles range(stop), range(start, stop),
        # and range(start, stop, step) with a constant step (positive or
        # negative).
        if (isinstance(s.iterable, gimple_ctypes.CallExpr)
                and isinstance(s.iterable.func, gimple_ctypes.IdentExpr)
                and s.iterable.func.name == 'range'
                and len(s.iterable.args) in (1, 2, 3)):
            rargs = [gen._cpp_expr(a) for a in s.iterable.args]
            if len(rargs) == 1:
                start_e, stop_e, step_e = '0', rargs[0], '1'
            elif len(rargs) == 2:
                start_e, stop_e, step_e = rargs[0], rargs[1], '1'
            else:
                start_e, stop_e, step_e = rargs[0], rargs[1], rargs[2]
            ctr = gen._cpp_fresh_name("_mg_i")
            # The loop variable must be a real C++ declaration (unlike
            # the range-for path, where `for (auto i : ...)` declares it
            # itself): emit `int64_t i;` up front — the first time, only
            # — so both the in-loop assignment and any use AFTER the loop
            # (Python loop variables escape the loop) reference a valid
            # identifier. `declared` doubles as the "already declared in
            # C++" tracker, so a target that was already a declared local
            # (e.g. assigned before the loop) is NOT redeclared.
            lines = []
            if not target_was_declared:
                lines.append(f"{indent}int64_t {target};")
            lines.append(f"{indent}for (int64_t {ctr} = {start_e}; "
                         f"({ctr} < {stop_e}) == ({step_e} > 0); {ctr} += {step_e}) {{")
            lines.append(f"{indent}    {target} = {ctr};")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        # `for x in itertools.repeat(value, times):` (finite 2-arg
        # form — see `_is_itertools_repeat2_call`'s docstring): the
        # analogous plain-`for`-loop sibling of `_cpp_yield_from`'s own
        # `yield from repeat(...)` special case just above in this
        # file. Not hit by any real corpus source this doc's bug is
        # about (Lib/calendar.py only uses the `yield from` form), but
        # `repeat` is equally undeclared-in-scope if a plain
        # consuming `for` loop over it were ever compiled, so handled
        # here too for the same reason `range(...)` gets its own
        # indexed-loop special case just above rather than falling to
        # the generic `_cpp_expr` fallback.
        if isinstance(s.iterable, gimple_ctypes.CallExpr) and gimple_exprtypes._is_itertools_repeat2_call(s.iterable):
            val_expr = gen._cpp_expr(s.iterable.args[0])
            times_expr = gen._cpp_expr(s.iterable.args[1])
            ctr = gen._cpp_fresh_name("_mg_i")
            lines = []
            if not target_was_declared:
                lines.append(f"{indent}int64_t {target};")
            lines.append(f"{indent}auto _rep_val = {val_expr};")
            lines.append(f"{indent}int64_t _rep_n = {times_expr};")
            lines.append(f"{indent}for (int64_t {ctr} = 0; {ctr} < _rep_n; {ctr}++) {{")
            lines.append(f"{indent}    {target} = _rep_val;")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        # `for x in <dict-typed expr>.keys()/.values()/.items():` and the
        # bare-dict sibling `for k in <dict-typed expr>:` — plain dict
        # iteration with a single-name target inside a coroutine body.
        # Lowered through the same mojo_dict_keys/mojo_dict_values/
        # mojo_dict_items runtime helpers the ordinary GIMPLE path already
        # uses (evaluated ONCE into a cached list local, then an indexed
        # loop): keys are always char* in this dict representation, values
        # use the boxed-int64_t convention, so `.items()`'s pairs read as
        # int64_t sub-list pointers here (a TUPLE-target `.items()` loop is
        # handled by its own per-slot case in the tuple-target branch
        # above). Without this, a single-name loop over a dict-shaped call
        # fell to the generic `for (auto x : ...)` range-for, which cannot
        # compile against any of these opaque pointer types (no ADL
        # begin/end). Real: Lib/weakref.py's WeakValueDictionary.values
        # (`for wr in self.data.copy().values():`) and WeakKeyDictionary's
        # own keys (`for wr in self.data.copy():`).
        _dict_iter_fn = None
        _dict_iter_elem = None
        _dict_iter_src = None
        if not s.else_body:
            if (isinstance(s.iterable, gimple_ctypes.CallExpr)
                    and isinstance(s.iterable.func, gimple_ctypes.MemberExpr)
                    and not s.iterable.args
                    and s.iterable.func.member in ('keys', 'values', 'items')
                    and _cpp_receiver_ctype(gen, s.iterable.func.obj) == 'MojoDict *'):
                _dict_iter_fn = f"mojo_dict_{s.iterable.func.member}"
                _dict_iter_elem = ('char *' if s.iterable.func.member == 'keys'
                                   else 'int64_t')
                _dict_iter_src = gen._cpp_expr(s.iterable.func.obj)
            elif _cpp_receiver_ctype(gen, s.iterable) == 'MojoDict *':
                _dict_iter_fn = 'mojo_dict_keys'
                _dict_iter_elem = 'char *'
                _dict_iter_src = gen._cpp_expr(s.iterable)
        if _dict_iter_fn is not None:
            _dlist = gen._cpp_fresh_name("_mg_dlist")
            _ctr = gen._cpp_fresh_name("_mg_i")
            lines = []
            if not target_was_declared:
                declared[target] = _dict_iter_elem
                lines.append(f"{indent}{gimple_exprtypes._c_to_cpp_scalar_type(_dict_iter_elem)} {target};")
            lines.append(f"{indent}MojoList *{_dlist} = "
                         f"{_dict_iter_fn}((MojoDict *)({_dict_iter_src}));")
            lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                         f"{_ctr} < mojo_list_len({_dlist}); {_ctr}++) {{")
            if _dict_iter_elem == 'char *':
                lines.append(f"{indent}    {target} = "
                             f"mojo_list_get_str({_dlist}, {_ctr});")
            else:
                lines.append(f"{indent}    {target} = "
                             f"mojo_list_get_int({_dlist}, {_ctr});")
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        try:
            iter_expr = gen._cpp_expr(s.iterable)
        except gimple_exprtypes._UnsupportedGeneratorShape:
            iter_expr = None
        if iter_expr is not None:
            # `for x in <identifier>` where the identifier is a
            # CONTAINER-typed local/param (declared int64_t — this
            # scalar body model boxes MojoList* as int64_t) but the body
            # iterates it (locale.py's `_grouping_intervals(grouping)`
            # `for interval in grouping:`, statistics.py's
            # `_fail_neg(values)` `for x in values:`): range-for over an
            # int64_t doesn't compile. Emit an indexed loop over the
            # list's elements (mojo_list_len / mojo_list_get_int), the
            # same element protocol a `yield from`-over-list already
            # uses. Only fires when the iterable is a bare identifier
            # (so `for x in <call>()`'s generator delegation is
            # untouched) whose declared type is the boxed-int64_t
            # container convention -- OR a real `MojoList *`-typed
            # local/parameter (a generator function whose param is
            # annotated/inferred as MojoList*, not boxed int64_t: e.g.
            # `def _fix_read_default(row): for value in row: ...` where
            # `row`'s C++ param type is the real pointer). Without this
            # second case, the generic range-for fallback below emitted
            # `for (auto value : row)` on a bare `MojoList *` pointer --
            # C++ range-for needs ADL `begin`/`end` for the iterated
            # expression's type, which don't exist for a raw pointer --
            # "'begin' was not declared in this scope" / "'end' was not
            # declared in this scope". Found via Tools/c-analyzer/
            # c_common/tables.py's `_fix_read_default`.
            # A third shape reaches the same "raw pointer, no ADL
            # begin/end" failure: `for x in self.<field>:` where
            # `<field>` is a struct FIELD (not a local/param) typed
            # `MojoList *` in the generated C++ struct typedef --
            # save_env.py's `resource_info`: `for name in self.
            # resources:`. struct_field_types (the same lookup
            # `_cpp_expr`'s MemberExpr case already uses for
            # `self.<field>` reads) tells us the field's real C type;
            # anything that ISN'T one of the four known scalars is,
            # per this codegen's own struct-field-boxing convention,
            # pointer-shaped (a real `MojoList *` in the emitted
            # typedef, same as this branch already assumes for a bare
            # identifier) -- so the identical indexed-loop lowering
            # applies, reading through `self->field` instead of a bare
            # local name.
            _self_field_itname = None
            _self_field_elem_ctype = None
            _pre_lines: list[str] = []
            # `for x in sorted(<self.field-or-declared-list>, key=...):`
            # -- `_cpp_expr` above already lowered the WHOLE `sorted(...)`
            # call into `iter_expr` (a self-invoking C++ lambda building
            # a fresh `MojoList *`, see the CallExpr/'sorted' case), but
            # using that expression text directly as `_itname` below
            # (referenced from BOTH `mojo_list_len` and
            # `mojo_list_get_int`, each re-evaluated every loop
            # iteration) would re-run the ENTIRE sort -- reallocating a
            # new list and re-invoking the `key=` callable O(n log n)
            # times -- on every single element read, an O(n^2 log n)
            # blowup and a fresh MojoList leak per iteration. Evaluate
            # it exactly ONCE into a cached local before the loop
            # instead, then treat that cached local exactly like the
            # existing bare-identifier/self-field cases below. The
            # element type is the WRAPPED iterable's own (sorting
            # reorders, never changes, element type) -- resolved via the
            # same `self.<field>` + `_field_elem_types` lookup the plain
            # `for x in self.<field>:` case just above already uses,
            # since a `self.<field>` iterable is the one real corpus
            # shape (`Lib/enum.py`-style `key=lambda m: m.<field>`, see
            # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md).
            if (isinstance(s.iterable, gimple_ctypes.CallExpr)
                    and isinstance(s.iterable.func, gimple_ctypes.IdentExpr)
                    and s.iterable.func.name == 'sorted' and s.iterable.args
                    and not gen._locally_binds_name('sorted')):
                _sorted_inner = s.iterable.args[0]
                if (isinstance(_sorted_inner, gimple_ctypes.MemberExpr)
                        and isinstance(_sorted_inner.obj, gimple_ctypes.IdentExpr)
                        and _sorted_inner.obj.name == 'self'
                        and getattr(gen, '_cpp_gen_self_struct', None)):
                    _sw_ft = gen.struct_field_types.get(
                        gen._cpp_gen_self_struct, {}).get(_sorted_inner.member)
                    if _sw_ft not in ('int64_t', 'double', '_Bool', 'char *'):
                        _self_field_elem_ctype = gen._field_elem_types.get(
                            gen._cpp_gen_self_struct, {}).get(_sorted_inner.member)
                _cached = gen._cpp_fresh_name("_mg_sorted")
                _pre_lines.append(
                    f"{indent}MojoList *{_cached} = (MojoList *)({iter_expr});")
                _self_field_itname = _cached
            if (isinstance(s.iterable, gimple_ctypes.MemberExpr)
                    and isinstance(s.iterable.obj, gimple_ctypes.IdentExpr)
                    and s.iterable.obj.name == 'self'
                    and getattr(gen, '_cpp_gen_self_struct', None)):
                _self_ft = gen.struct_field_types.get(
                    gen._cpp_gen_self_struct, {}).get(s.iterable.member)
                if _self_ft not in ('int64_t', 'double', '_Bool', 'char *'):
                    _self_field_itname = f"self->{gimple_ctypes._safe_field(s.iterable.member)}"
                    # The field's ELEMENT type (as opposed to the field's
                    # own MojoList*-pointer type just checked above) —
                    # `_field_elem_types` is the same struct-field
                    # element-type map the ordinary GIMPLE path already
                    # populates for a `self.x: list[str]`-shaped field
                    # (e.g. from a class-body tuple/list literal
                    # initializer of string constants, save_env.py's
                    # `resources = ('sys.argv', 'cwd', ...)`). Drives
                    # which `mojo_list_get_*` accessor/target C type is
                    # correct below; unknown defaults to the same
                    # int64_t/mojo_list_get_int convention the sibling
                    # bare-identifier branch above already uses.
                    _self_field_elem_ctype = gen._field_elem_types.get(
                        gen._cpp_gen_self_struct, {}).get(s.iterable.member)
            if ((isinstance(s.iterable, gimple_ctypes.IdentExpr)
                    and gen._cpp_declared is not None
                    and s.iterable.name in gen._cpp_declared
                    and gen._cpp_declared[s.iterable.name] in ('int64_t', 'MojoList *'))
                    or _self_field_itname is not None):
                _itname = _self_field_itname if _self_field_itname is not None else s.iterable.name
                # A LOCAL list's element type (literal-init/append
                # tracking) — same role `_self_field_elem_ctype` plays
                # for the self-field case below.
                _local_elem_ctype = None
                if _self_field_itname is None:
                    _local_elem_ctype = getattr(gen, '_cpp_list_local_elem_types', {}).get(_itname)
                _ctr = gen._cpp_fresh_name("_mg_i")
                lines = list(_pre_lines)
                # A known struct-pointer element type (e.g. `Thing *`,
                # from `_field_elem_types` -- the `self.<field>: list
                # [Struct]` case, and now also its `sorted(self.<field>,
                # key=...)` wrapper just above) needs the loop variable
                # declared with that REAL pointer type, cast out of the
                # boxed-int64_t element read, so a later `target.<field>`
                # read inside the loop body resolves through the
                # ordinary struct-field lowering (`_cpp_struct_ptr_local`
                # only recognizes a declared type ending in ' *') instead
                # of emitting `target->member` on a plain int64_t (an
                # invalid-C++ "not a structure or union" error) --
                # previously EVERY struct-pointer-list element loop
                # variable was declared int64_t regardless, so this also
                # closes that same gap for a plain (non-sorted)
                # `for x in self.<field>:` over a `list[Struct]` field.
                _elem_struct_ctype = None
                _eff_elem = (_self_field_elem_ctype if _self_field_elem_ctype is not None
                             else _local_elem_ctype)
                if (isinstance(_eff_elem, str)
                        and _eff_elem.endswith(' *')
                        and _eff_elem[:-2] in gen.struct_field_types):
                    _elem_struct_ctype = _eff_elem
                if _eff_elem == 'char *':
                    if not target_was_declared:
                        lines.append(f"{indent}char *{target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len((MojoList *)({_itname})); "
                                 f"{_ctr}++) {{")
                    lines.append(f"{indent}    {target} = "
                                 f"mojo_list_get_str((MojoList *)({_itname}), {_ctr});")
                elif _eff_elem == 'double':
                    if not target_was_declared:
                        lines.append(f"{indent}double {target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len((MojoList *)({_itname})); "
                                 f"{_ctr}++) {{")
                    lines.append(f"{indent}    {target} = "
                                 f"mojo_list_get_double((MojoList *)({_itname}), {_ctr});")
                elif _elem_struct_ctype is not None:
                    if not target_was_declared:
                        lines.append(f"{indent}{_elem_struct_ctype}{target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len((MojoList *)({_itname})); "
                                 f"{_ctr}++) {{")
                    lines.append(f"{indent}    {target} = ({_elem_struct_ctype})"
                                 f"mojo_list_get_int((MojoList *)({_itname}), {_ctr});")
                else:
                    if not target_was_declared:
                        lines.append(f"{indent}int64_t {target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len((MojoList *)({_itname})); "
                                 f"{_ctr}++) {{")
                    lines.append(f"{indent}    {target} = "
                                 f"mojo_list_get_int((MojoList *)({_itname}), {_ctr});")
                if _eff_elem == 'char *':
                    declared[target] = 'char *'
                elif _eff_elem == 'double':
                    declared[target] = 'double'
                elif _elem_struct_ctype is not None:
                    declared[target] = _elem_struct_ctype
                else:
                    declared[target] = 'int64_t'
                for inner in s.body:
                    lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
                lines.append(f"{indent}}}")
                return lines
            if iter_expr == '0':
                # The iterable lowered to the scalar stub '0' (e.g.
                # test_exception_group.py's leaf_generator:
                # `for e in exc.exceptions:` where `exc` is an untyped
                # param boxed to int64_t and `.exceptions` is the
                # diagnosed attribute-read stub). A range-for over `0`
                # is invalid C++, and the iterable's real value is
                # already unrepresentable here — so run ZERO
                # iterations: bind the target to 0 and skip the body,
                # mirroring how every other stubbed operation in this
                # body model behaves.
                lines = []
                if not target_was_declared:
                    lines.append(f"{indent}int64_t {target} = 0;")
                else:
                    lines.append(f"{indent}{target} = 0;")
                return lines
            # `for x in <MojoList *-typed expression>:` where the list
            # provenance is statically known but the iterable is NOT one of
            # the shapes the branches above already handle: a call to a
            # module-level function whose inferred return ctype is
            # MojoList* (dyld.py's `for path in dyld_framework_path(env):`),
            # or a module-level list global (`for path in
            # DEFAULT_FRAMEWORK_FALLBACK:`). The generic range-for below
            # cannot iterate a raw MojoList* pointer ("no viable 'begin'
            # function available"), so lower through the same cached-local
            # + indexed loop every other list-iteration branch here uses.
            # Element type comes from Pass 2c's `_return_elem_types`
            # fixpoint for the callee ('char *' for a split()-of-strings
            # producer like dyld_env), defaulting to the boxed int64_t
            # convention when unknown.
            _iter_list_expr = None
            _iter_elem = None
            if isinstance(s.iterable, gimple_ctypes.CallExpr) and isinstance(s.iterable.func, gimple_ctypes.IdentExpr):
                _callee = s.iterable.func.name
                if gen.func_return_types.get(_callee) == 'MojoList *':
                    _iter_list_expr = f"(MojoList *)({gen._cpp_expr(s.iterable)})"
                    _iter_elem = gen._return_elem_types.get(_callee)
            elif isinstance(s.iterable, gimple_ctypes.IdentExpr) \
                    and gen._cpp_declared is not None \
                    and s.iterable.name not in gen._cpp_declared \
                    and gen._global_var_types.get(s.iterable.name) == 'MojoList *':
                _iter_list_expr = f"(MojoList *)({gen._cpp_expr(s.iterable)})"
            if _iter_list_expr is not None and not isinstance(target, str):
                raise gimple_exprtypes._UnsupportedGeneratorShape(
                    "unsupported for-loop target over a list-typed iterable")
            if _iter_list_expr is not None:
                _cached = gen._cpp_fresh_name("_mg_iter")
                _ctr = gen._cpp_fresh_name("_mg_i")
                lines = [f"{indent}MojoList *{_cached} = {_iter_list_expr};"]
                if _iter_elem == 'char *':
                    if not target_was_declared:
                        declared[target] = 'char *'
                        lines.append(f"{indent}char *{target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len({_cached}); {_ctr}++) {{")
                    lines.append(f"{indent}    {target} = mojo_list_get_str({_cached}, {_ctr});")
                elif _iter_elem == 'double':
                    if not target_was_declared:
                        declared[target] = 'double'
                        lines.append(f"{indent}double {target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len({_cached}); {_ctr}++) {{")
                    lines.append(f"{indent}    {target} = mojo_list_get_double({_cached}, {_ctr});")
                else:
                    if not target_was_declared:
                        declared[target] = 'int64_t'
                        lines.append(f"{indent}int64_t {target};")
                    lines.append(f"{indent}for (int64_t {_ctr} = 0; "
                                 f"{_ctr} < mojo_list_len({_cached}); {_ctr}++) {{")
                    lines.append(f"{indent}    {target} = mojo_list_get_int({_cached}, {_ctr});")
                for inner in s.body:
                    lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
                lines.append(f"{indent}}}")
                return lines
            if s.else_body:
                # for/else: the else body runs only when the loop
                # completes WITHOUT a `break` — mirror _cpp_stmt's
                # WhileStmt else handling with a shared break flag.
                brk_var = gen._cpp_fresh_name("_mg_brk")
                lines = [f"{indent}bool {brk_var} = false;"]
                if (isinstance(s.iterable, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr))
                        and s.iterable.elements
                        and all(isinstance(el, gimple_ctypes.StringLiteral)
                                for el in s.iterable.elements)):
                    declared[target] = 'char *'
                lines.append(f"{indent}for (auto {target} : {iter_expr}) {{")
                for inner in s.body:
                    lines.extend(gen._cpp_stmt_with_break_flag(inner, declared, indent + '    ', brk_var))
                lines.append(f"{indent}}}")
                lines.append(f"{indent}if (!{brk_var}) {{")
                for inner in s.else_body:
                    lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
                lines.append(f"{indent}}}")
                return lines
            if (isinstance(s.iterable, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr))
                    and s.iterable.elements
                    and all(isinstance(el, gimple_ctypes.StringLiteral)
                            for el in s.iterable.elements)):
                # `for k in ("a", "b"):` — the generic range-for declares
                # the target via C++ `auto`, but this emitter's OWN type
                # tracking must still learn the target's real ctype
                # (char *), or later uses — most importantly a dict
                # subscript keyed by the loop variable (`d[k]`) — fall
                # back to the int64_t default and stringify the pointer
                # through mojo_str_from_int (garbage key).
                declared[target] = 'char *'
            lines = [f"{indent}for (auto {target} : {iter_expr}) {{"]
            for inner in s.body:
                lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
            lines.append(f"{indent}}}")
            return lines
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"unsupported for-loop iterable type: {type(s.iterable).__name__}")
    raise gimple_exprtypes._UnsupportedGeneratorShape(
        f"unsupported for-loop target type: {type(target).__name__}")


def _cpp_async_for_stmt(gen, s: 'ForStmt', declared: dict, indent: str) -> list[str]:
    """`async for <var> in <call>():` -- the final step of the async/
    await codegen project's own consumption protocol for a compiled
    async generator (see `_gen_cpp_async_generator_unit`'s docstring).
    Real Python: `async for` is the ONLY legal way to consume an async
    generator (it's not directly awaitable itself -- only its
    `__anext__()` is), and `async for` is itself only legal lexically
    inside another `async def`'s own body -- both confirmed by this
    step's own research. This project's parser already carries
    `ForStmt.is_async` (parked, parser-only, since the async-parsing
    milestone) with NO prior codegen support anywhere, compiled or
    interpreted -- this is the first codegen (of either kind) to
    consume it.

    This step supports a plain identifier loop target, over a call to
    another `async def f(): ... yield ...` this same module compile has
    ALREADY successfully lowered via `_gen_cpp_async_generator_unit`
    (`self._async_gen_api` -- same source-order-dependent "callee
    already compiled" constraint `_is_async_call_to_known_fn` documents
    for plain async-awaits-async composition). As of the follow-up fix
    to bugs/hard/CODEGEN_async_gen_params_silent_regression.md, the
    call MAY carry real positional arguments -- threaded through to
    `{base}_impl(...)` exactly like the sibling async-awaits-async
    composition call site (`_cpp_expr`'s `AwaitExpr` case, `call_args
    = ', '.join(self._cpp_expr(a) for a in target.args)`), with the
    supplied argument COUNT validated against `api['params']` first
    (honest `_UnsupportedAsyncShape` refusal on a mismatch, never
    invalid C++) -- point (b) from that doc's own "Fix" section, which
    the sibling AwaitExpr call site does NOT itself do (it only joins
    whatever args are given); this call site is stricter than its
    sibling on purpose, matching the doc's "ideally safer" framing.
    Keyword arguments are still refused (the sibling AwaitExpr shape
    never supported them either -- `not getattr(target, 'kwargs',
    None)` there, matched here by the same check). Lowers to a
    `co_await` loop on that generator's own `<base>_AnextAwaiter`
    (constructed directly from `{impl}(<args>).h`, same-translation-
    unit composition, no `extern "C"` boundary -- see that method's
    docstring), destroying the generator's coroutine frame exactly once
    after the loop exits (natural exhaustion OR an early `break` -- both
    fall through to the same statement after the loop) -- an exception
    exit destroys the frame itself, inside `<base>_AnextAwaiter::
    await_resume`, before throwing, so this never double-destroys."""
    if not (s.is_async and gen._cpp_emit_kind in ('async', 'async_gen')):
        raise gimple_exprtypes._UnsupportedAsyncShape(
            "a plain (non-`async`) `for` loop is not supported in a "
            "generator/async function body; `async for` is only "
            "supported inside an async function/async generator body")
    if s.else_body:
        raise gimple_exprtypes._UnsupportedAsyncShape("`async for`/`else` is not supported")
    # `ForStmt.target` is a plain Python str (the loop variable's bare
    # name), not an IdentExpr -- unlike most other expression slots in
    # this AST (confirmed against mojo_compiler.py's actual parse
    # output; ForStmt predates the rest of this narrow-scope codegen
    # entirely, and multi-target/tuple-unpacking `for` isn't supported
    # here so it's always a single str, never a tuple).
    if not isinstance(s.target, str):
        raise gimple_exprtypes._UnsupportedAsyncShape(
            "only a plain identifier `async for` loop target is supported")
    it = s.iterable
    if not (isinstance(it, gimple_ctypes.CallExpr) and isinstance(it.func, gimple_ctypes.IdentExpr)
            and not getattr(it, 'kwargs', None)
            and it.func.name in gen._async_gen_api):
        raise gimple_exprtypes._UnsupportedAsyncShape(
            "`async for` is only supported over a call (with plain "
            "positional arguments, if any -- no keyword arguments) to "
            "another compiled async-generator function this module has "
            "already compiled (defined earlier in the module than this "
            "loop)")
    api = gen._async_gen_api[it.func.name]
    base = api['base']
    value_ctype = api['value_ctype']
    # See this method's own docstring point (b): validate the call
    # site's real argument COUNT against the generator's own compiled
    # parameter list before emitting anything -- an honest refusal here
    # (never invalid C++ deferred to a downstream g++ failure). Stricter
    # than the sibling AwaitExpr composition call site on purpose (that
    # one never checks arg count at all).
    gen_params = api['params']
    if len(it.args) != len(gen_params):
        raise gimple_exprtypes._UnsupportedAsyncShape(
            f"async generator {it.func.name!r} called with "
            f"{len(it.args)} argument(s), expected {len(gen_params)}")
    call_args = ', '.join(gen._cpp_expr(a) for a in it.args)
    var = s.target
    handle_var = f"__agen_h_{var}"
    has_var = f"__agen_has_{var}"
    lines = [
        f"{indent}{base}_handle {handle_var} = {base}_impl ({call_args}).h;",
        f"{indent}for (;;) {{",
        f"{indent}    bool {has_var} = co_await {base}_AnextAwaiter{{{handle_var}}};",
        f"{indent}    if (!{has_var}) break;",
        f"{indent}    {gimple_exprtypes._c_to_cpp_scalar_type(value_ctype)} {var} = {handle_var}.promise().current_value;",
    ]
    declared[var] = value_ctype
    for inner in s.body:
        lines.extend(gen._cpp_stmt(inner, declared, indent + '    '))
    lines.append(f"{indent}}}")
    lines.append(f"{indent}{handle_var}.destroy();")
    return lines


def _cpp_raise_stmt(gen, s, indent: str) -> list[str]:
    """`raise`/`raise ExcName(...)` inside a generator body — Milestone D.
    Translates to a real C++ `throw` of `_MojoCppExc` (type tag + string
    message + object slot — see the shared preamble's struct def and
    _exc_type_id/mojo_exc_*_set, the EXACT SAME representation the
    ordinary (non-generator) GIMPLE path's _gen_stmt_RaiseStmt already
    uses, not a second one), confined to this coroutine's own .cpp
    translation unit. Mirrors _gen_stmt_RaiseStmt's own restrictions
    (single-string-argument constructor call, or a bare class reference)
    rather than inventing a richer payload shape this narrow scalar-only
    generator-body model has no way to represent anyway (a compiled
    generator's locals/params are int64_t/double/_Bool only — see
    _infer_simple_expr_ctype — so a raise message can only ever be a
    literal string, never a variable, unlike the GIMPLE path)."""
    if s.value is None:
        # Bare `raise` (re-raise): only meaningful inside a translated
        # except-handler's own body (`self._cpp_reraise_stack` — see
        # _cpp_except_handler_body — names the LOCAL VARIABLE holding a
        # copy of the exception this handler is running for; handler
        # bodies execute OUTSIDE the actual `catch` clause — see
        # _cpp_try_stmt's docstring for why — so this can't be a plain
        # `throw;`, which is only legal lexically inside a real
        # `catch`). Outside any handler a bare `raise` isn't well-
        # defined in this narrow model (real Python itself raises a
        # RuntimeError for a bare raise with no active exception) —
        # refuse honestly rather than guess.
        stack = gen._cpp_reraise_stack
        if stack:
            return [f"{indent}throw {stack[-1]};"]
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            "bare `raise` (re-raise) outside an except handler is not "
            "supported in a generator body")
    val = s.value
    exc_name = None
    msg_arg = None
    if isinstance(val, gimple_ctypes.CallExpr) and isinstance(val.func, gimple_ctypes.IdentExpr):
        exc_name = val.func.name
        if len(val.args) == 1:
            msg_arg = val.args[0]
    elif isinstance(val, gimple_ctypes.IdentExpr) and gen._is_exc_class_name(val.name):
        exc_name = val.name
    if exc_name is None:
        # `raise e` where e is a handler-bound exception variable
        # (bound as char* message in the handler body): throw a fresh
        # _MojoCppExc carrying that message, so `except X: ... raise e
        # from None` re-raises the specific caught exception rather than
        # refusing the whole generator.
        if isinstance(val, gimple_ctypes.IdentExpr):
            msg_cpp = gen._cpp_expr(val)
            return [f"{indent}throw _MojoCppExc{{ (int64_t)0, {msg_cpp}, "
                    f"(void *){msg_cpp} }};"]
        # `raise <MemberExpr>(...)` / bare `raise <MemberExpr>` — a
        # DYNAMICALLY resolved exception class (real, recurring idiom:
        # `raise self._imap.error(...)` in imaplib.py's Idler.burst,
        # plus test.support's run_with_locale/subst_drive — see
        # CODEGEN_generator_raise_non_static_exception_class.md's three
        # confirmed occurrences) has no statically-known class NAME to
        # look up in _exc_type_id, so it can't get a real per-class tag
        # the way `raise ExcName(...)` does. Rather than refuse the
        # whole generator outright, fall back to the SAME untyped(0)/
        # lenient-match representation `raise e` (a handler-bound
        # IdentExpr, just above) already uses for the identical "don't
        # statically know the exact class" situation — tag 0 is an
        # existing, documented convention (see _cpp_try_stmt's own
        # docstring: "untagged(0) lenient match on the first typed
        # handler", and the ordinary GIMPLE path's identical handling
        # around _gen_stmt_TryStmt), not a new one invented here. This
        # necessarily loses precise except-type matching for a
        # dynamically-resolved raise (an `except SpecificError:` may
        # over-eagerly catch it) — an accepted, pre-existing tradeoff
        # of this narrow scalar-only generator-body model, identical in
        # kind to the one `raise e` already makes.
        if isinstance(val, gimple_ctypes.MemberExpr) or (
                isinstance(val, gimple_ctypes.CallExpr) and isinstance(val.func, gimple_ctypes.MemberExpr)):
            msg_arg = val.args[0] if isinstance(val, gimple_ctypes.CallExpr) and val.args else None
            if msg_arg is not None:
                if isinstance(msg_arg, gimple_ctypes.StringLiteral):
                    text, is_fstr = gen._decode_str_literal_text(msg_arg.value)
                    if is_fstr:
                        msg_cpp = gen._cpp_expr(msg_arg)
                    else:
                        msg_cpp = f'const_cast<char *>("{gimple_ctypes._c_escape(text)}")'
                else:
                    msg_cpp = gen._cpp_expr(msg_arg)
            else:
                msg_cpp = 'const_cast<char *>("")'
            return [f"{indent}throw _MojoCppExc{{ (int64_t)0, {msg_cpp}, "
                    f"(void *){msg_cpp} }};"]
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            "unsupported `raise` value expression in generator body "
            "(only `raise ExcName(...)`/`raise ExcName` with a "
            "statically known exception class name is supported)")
    tag = gen._exc_type_id(exc_name)
    msg_cpp = 'nullptr'
    if msg_arg is not None:
        if isinstance(msg_arg, gimple_ctypes.StringLiteral):
            text, is_fstr = gen._decode_str_literal_text(msg_arg.value)
            if is_fstr:
                # F-string message: emit the interpolated expression as
                # the message (best-effort — a static string or a simple
                # member access on a param).
                msg_cpp = gen._cpp_expr(msg_arg)
            else:
                msg_cpp = f'const_cast<char *>("{gimple_ctypes._c_escape(text)}")'
        else:
            # Variable/expression message: evaluate as char* expression
            msg_cpp = gen._cpp_expr(msg_arg)
    return [f"{indent}throw _MojoCppExc{{ (int64_t){tag}, {msg_cpp}, "
            f"(void *){msg_cpp} }};"]


def _cpp_try_stmt(gen, node, declared: dict, indent: str) -> list[str]:
    """`try`/`except`/`finally` inside a generator body — Milestone D.
    Real C++ `try`/`catch (_MojoCppExc &...)`, with the SAME per-
    exception-type-tag dispatch semantics (inheritance-aware descendant
    matching, untagged(0) lenient match on the first typed handler, bare
    handler tried last, no match propagates) that _gen_stmt_TryStmt
    already implements for the ordinary GIMPLE path — reusing
    _handler_exc_name/_handler_exc_all_names/_exc_descendants/
    _exc_type_id directly rather than a second hand-rolled copy of that
    logic.

    The except-handler BODIES are deliberately NOT emitted inside the
    `catch` clause itself, even though that's the obvious first-draft
    translation — found the hard way, via this milestone's own
    independent hand-verification: g++ rejects `co_yield` lexically
    inside a `catch` block outright ("await expressions are not
    permitted in handlers", [expr.await] in the C++20 standard — a
    suspension point mid-exception-handling has no well-defined
    resume/unwind semantics, so the language simply forbids it), and a
    `yield` inside an `except:` body is an entirely ordinary, expected
    shape (see e.g. test_gimple_generator_runner.py's internally-caught
    test). Worked around by hoisting: the `catch` clause itself does
    nothing but record "yes, something was caught" (a bool flag) and
    take a plain-data COPY of the `_MojoCppExc` into an ordinary local
    declared before the `try` — copying a 3-field struct-of-scalars is
    cheap and, crucially, doesn't itself need any C++ exception
    machinery. The actual dispatch if/else-if chain and every handler's
    real body then run in a plain `if (caught) { ... }` AFTER the
    try/catch has already been fully exited — an ordinary block, not a
    handler, so `co_yield` there is unrestricted, exactly like anywhere
    else in this coroutine's body. A re-raise (bare `raise`) inside a
    handler body correspondingly can't be a bare `throw;` either (only
    legal lexically inside a real `catch`) — see _cpp_raise_stmt /
    self._cpp_reraise_stack, which throws the captured copy by value
    instead.

    `finally` has no native C++ counterpart, but C++'s own RAII already
    gives exactly Python's finally semantics for free: a locally-scoped
    guard object whose destructor runs the (translated) finally body is
    destroyed on EVERY way this block's scope can be exited — normal
    fallthrough, break/continue, `co_return`, or an exception unwinding
    through/past it — including when this coroutine's frame is
    destroyed early while SUSPENDED inside this very block (verified
    precedent: Milestone C step 2's `_mojogen_sub_guard` for `yield
    from` relies on the exact same C++20 coroutine-frame-destruction
    rule). `yield`/`yield from` inside the finally body itself is
    refused: a destructor is an ordinary (non-coroutine) member
    function and can't contain `co_yield` either (a DIFFERENT
    restriction from the catch-handler one above — a destructor isn't
    the coroutine function at all, so this one isn't specific to
    exception handling)."""
    # try/else: the else body runs when the try block completes without
    # an exception. Tracked via the caught_flag set by any handler that
    # fired — after the catch chain, emit else_body when !caught_flag.

    body_indent = indent
    closing = []
    lines: list[str] = []
    if node.finally_body:
        gen._cpp_finally_seq = getattr(gen, '_cpp_finally_seq', 0) + 1
        fin_var = f"__mojofin{gen._cpp_finally_seq}"
        finally_lines = []
        for fs in node.finally_body:
            finally_lines.extend(
                gen._cpp_stmt(fs, declared, indent + '        '))
        if any('co_yield' in ln or 'co_await' in ln
               for ln in finally_lines):
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                "`yield`/`yield from` inside a `finally:` block is not "
                "supported in a generator body")
        lines.append(f"{indent}{{")
        # `_MojoScopeExit` (shared preamble, alongside `_MojoCppExc`/
        # `_mojogen_sub_guard`) wraps an arbitrary `std::function<void
        # ()>`, run from its destructor on every way this scope can be
        # exited — see this method's docstring. A LOCAL CLASS (the
        # first thing tried here) doesn't work: its member functions
        # have no implicit access to the enclosing function's own
        # locals (unlike a lambda), so a finally body referencing any
        # variable from outside itself failed to compile ("use of
        # local variable with automatic storage from containing
        # function") — found via this milestone's own independent
        # hand-verification (a finally body that merely reads/writes an
        # outer local, an extremely ordinary shape, not an edge case).
        # A capturing lambda (`[&]`) fixes this outright.
        lines.append(f"{indent}    _MojoScopeExit {fin_var}([&]() {{")
        lines.extend(finally_lines)
        lines.append(f"{indent}    }});")
        body_indent = indent + '    '
        closing.append(f"{indent}}}")

    inner_indent = body_indent + '    '

    gen._cpp_try_seq = getattr(gen, '_cpp_try_seq', 0) + 1
    seq = gen._cpp_try_seq
    exc_var = f"__mojoexc{seq}"
    caught_flag = f"__mojocaught{seq}"
    caught_var = f"__mojocaughtexc{seq}"

    handlers = node.handlers
    if handlers:
        lines.append(f"{body_indent}bool {caught_flag} = false;")
        lines.append(f"{body_indent}_MojoCppExc {caught_var}{{}};")

    lines.append(f"{body_indent}try {{")
    for st in node.body:
        lines.extend(gen._cpp_stmt(st, declared, inner_indent))
    lines.append(f"{body_indent}}}")

    if not handlers:
        # A pure try/finally with no except clauses at all: a bare C++
        # `try { ... }` with no `catch` at all isn't legal syntax (found
        # via this exact shape failing to even PARSE, not just behave
        # wrong — g++: "expected 'catch' before '}' token") — so a
        # catch-and-immediately-rethrow is still required here, even
        # though there's nothing to actually dispatch on. The
        # finally-guard's destructor still runs correctly either way
        # (RAII, above) as the exception unwinds through this rethrow,
        # exactly like an ordinary uncaught throw anywhere else in this
        # translation unit.
        lines.append(f"{body_indent}catch (...) {{ throw; }}")
        lines.extend(closing)
        return lines

    lines.append(f"{body_indent}catch (_MojoCppExc &{exc_var}) {{")
    lines.append(f"{inner_indent}{caught_flag} = true;")
    lines.append(f"{inner_indent}{caught_var} = {exc_var};")
    lines.append(f"{body_indent}}}")

    lines.append(f"{body_indent}if ({caught_flag}) {{")
    _UNIVERSAL_CATCH_NAMES = ('Exception', 'BaseException')
    typed = [h for h in handlers
             if gen._handler_exc_name(h) is not None
             and gen._handler_exc_name(h) not in _UNIVERSAL_CATCH_NAMES]
    bare = [h for h in handlers
            if gen._handler_exc_name(h) is None
            or gen._handler_exc_name(h) in _UNIVERSAL_CATCH_NAMES]
    handler_indent = inner_indent

    if not typed:
        if bare:
            lines.extend(gen._cpp_except_handler_body(
                bare[0], caught_var, declared, handler_indent))
        else:
            lines.append(f"{handler_indent}throw {caught_var};")
    else:
        first = True
        for h in typed:
            names = set()
            for dn in gen._handler_exc_all_names(h):
                names |= gen._exc_descendants.get(dn, {dn})
            if not names:
                names = {gen._handler_exc_name(h)}
            cond = ' || '.join(
                f"{caught_var}.type_id == (int64_t){gen._exc_type_id(n)}"
                for n in sorted(names))
            if first:
                # Untagged (0) is treated leniently and falls to the
                # first typed handler — mirrors _gen_stmt_TryStmt's own
                # rationale for this exactly.
                cond = f"{caught_var}.type_id == (int64_t)0 || {cond}"
            kw = 'if' if first else 'else if'
            lines.append(f"{handler_indent}{kw} ({cond}) {{")
            lines.extend(gen._cpp_except_handler_body(
                h, caught_var, declared, handler_indent + '    '))
            lines.append(f"{handler_indent}}}")
            first = False
        lines.append(f"{handler_indent}else {{")
        if bare:
            lines.extend(gen._cpp_except_handler_body(
                bare[0], caught_var, declared, handler_indent + '    '))
        else:
            # No handler matched: this try wasn't meant to catch it —
            # propagate to whatever encloses it (another try in this
            # same coroutine body, or out to the coroutine's own
            # unhandled_exception()), exactly like _gen_stmt_TryStmt's
            # own bb_no_match falling through to mojo_raise(). Throws
            # the captured COPY (not the original catch-clause
            # reference, long out of scope by now) — same value either
            # way, just needs to still be alive here.
            lines.append(f"{handler_indent}    throw {caught_var};")
        lines.append(f"{handler_indent}}}")
    lines.append(f"{body_indent}}}")  # closes `if ({caught_flag})`

    # try/else: runs when no exception occurred (caught_flag is false)
    if node.else_body:
        lines.append(f"{body_indent}if (!{caught_flag}) {{")
        for es in node.else_body:
            lines.extend(gen._cpp_stmt(es, declared, body_indent + '    '))
        lines.append(f"{body_indent}}}")

    lines.extend(closing)
    return lines


def _cpp_yield_from(gen, yf: 'YieldFromExpr', indent: str) -> list[str]:
    """`yield from <call>` — delegates to ANOTHER generator this same
    compile has already itself translated via the C++20-coroutine path
    (self._supported_generators/self._generator_api; populated by
    gen_module's Pass-1.3d-gen loop strictly in source order, so the
    delegated-to generator must be DEFINED EARLIER in the same module —
    the one scope restriction this step adds beyond "known compiled
    generator", chosen because it falls out for free from the existing
    single-pass compile-attempt loop instead of requiring a second,
    dependency-ordered pass). Anything else — `yield from` over a list/
    other plain iterable, over a call through an attribute/module
    access, over a generator that itself failed to compile (unsupported
    shape) or hasn't been compiled YET (defined later in the module) —
    raises _UnsupportedGeneratorShape, exactly like every other
    out-of-scope shape in this emitter.

    C++20's co_yield-based coroutines have no built-in "delegate to a
    sub-generator" primitive (unlike Python's `yield from`, which is
    itself sugar for a resume/yield/exhaust loop plus StopIteration
    value propagation — the value-propagation half is out of scope here
    since this codegen's compiled generators don't support `return
    <value>` at all yet). So delegation is hand-rolled as a local loop
    inside the delegating coroutine's own body: call the sub-
    generator's own <base>_start/_resume/_value/_destroy extern "C"
    functions (already fully DEFINED earlier in this same .cpp
    translation unit — gen_module concatenates every supported
    generator's cpp unit in the same source order used here, so no
    separate forward declaration is needed), co_yield-ing each value
    until the sub-generator reports done.

    Lifetime/early-cleanup: the sub-generator handle is held in a
    `_mojogen_sub_guard` RAII wrapper (emitted once in the .cpp
    preamble) whose destructor calls the sub-generator's `_destroy`.
    This covers BOTH exit paths uniformly: normal exhaustion (the guard
    goes out of scope at the end of the `{ ... }` block below, right
    after the while-loop's condition first reports done), and the
    delegating (outer) coroutine itself being destroyed early — e.g. a
    consumer `break`s out of a `for x in outer(): ...` loop, which calls
    `_start`'s own `_destroy`, i.e. std::coroutine_handle<>::destroy()
    on a coroutine suspended mid-`co_yield` inside this very block. Per
    the C++20 coroutine-frame-destruction rules, destroying a suspended
    coroutine's frame runs the destructors of every local object in
    scope at that suspension point, exactly as if the enclosing block
    were unwound normally — so `_mojogen_sub_guard`'s destructor (and
    hence the sub-generator's own `_destroy`) fires correctly even in
    that case, without any special-case code here. Verified end-to-end
    by test_gimple_generator_runner.py's
    yield_from_delegation_early_break_cleans_up_both_generators test."""
    call = yf.value
    # `yield from <ListExpr/TupleExpr>` — delegate to a plain collection:
    # emit `for (auto _yf_item : <collection>) { co_yield _yf_item; }`
    if isinstance(call, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr)):
        coll = gen._cpp_expr(call)
        return [f"{indent}for (auto _yf_item : {coll}) {{",
                f"{indent}    co_yield _yf_item;",
                f"{indent}}}"]
    # `yield from itertools.repeat(value, times)` (finite 2-arg form —
    # see `_is_itertools_repeat2_call`'s docstring): `repeat` has no C
    # symbol anywhere in this codegen (it isn't a list/tuple literal
    # and isn't a generator this compile has translated), so without
    # this case it fell into the generic "plain collection expression"
    # fallback below, which evaluates `repeat(value, times)` as an
    # ordinary call via `_cpp_expr` — 'repeat' was not declared in this
    # scope. Emit a native counted loop instead: evaluate `value` and
    # `times` ONCE up front (matching Python's own one-time-evaluation
    # semantics), then co_yield `value` exactly `times` times. Real:
    # Lib/calendar.py's `Calendar.itermonthdays`: `yield from
    # repeat(0, days_before)` / `yield from repeat(0, days_after)`.
    if isinstance(call, gimple_ctypes.CallExpr) and gimple_exprtypes._is_itertools_repeat2_call(call):
        val_expr = gen._cpp_expr(call.args[0])
        times_expr = gen._cpp_expr(call.args[1])
        rep_val = gen._cpp_fresh_name("_rep_val")
        rep_n = gen._cpp_fresh_name("_rep_n")
        rep_i = gen._cpp_fresh_name("_rep_i")
        return [
            f"{indent}{{",
            f"{indent}    auto {rep_val} = {val_expr};",
            f"{indent}    int64_t {rep_n} = {times_expr};",
            f"{indent}    for (int64_t {rep_i} = 0; {rep_i} < {rep_n}; {rep_i}++) {{",
            f"{indent}        co_yield {rep_val};",
            f"{indent}    }}",
            f"{indent}}}",
        ]
    # `yield from range(...)`: a native indexed counted loop, mirroring
    # `_cpp_for_stmt`'s own (non-`yield from`) `for i in range(...):`
    # special case, instead of falling into the generic "plain
    # collection" fallback below — that fallback goes through
    # `mojo_range()`'s opaque MojoList*-of-boxed-ints via
    # `mojo_list_get_str`, co_yield-ing char* even though `range()`'s
    # elements are always integers, which mismatches the int64_t
    # promise type `_yield_from_delegate_ctype`'s own `range(...)` case
    # (just above, in this file) now correctly infers. Handles
    # range(stop), range(start, stop), and range(start, stop, step)
    # with a constant step (positive or negative), same 3 shapes
    # `_cpp_for_stmt` supports. Real: Lib/calendar.py's
    # `Calendar.itermonthdays`: `yield from range(1, ndays + 1)`,
    # alongside its sibling `yield from repeat(...)` sites, all of
    # which must agree on one int64_t promise type.
    if (isinstance(call, gimple_ctypes.CallExpr) and isinstance(call.func, gimple_ctypes.IdentExpr)
            and call.func.name == 'range' and not call.kwargs
            and len(call.args) in (1, 2, 3)):
        rargs = [gen._cpp_expr(a) for a in call.args]
        if len(rargs) == 1:
            start_e, stop_e, step_e = '0', rargs[0], '1'
        elif len(rargs) == 2:
            start_e, stop_e, step_e = rargs[0], rargs[1], '1'
        else:
            start_e, stop_e, step_e = rargs[0], rargs[1], rargs[2]
        ctr = gen._cpp_fresh_name("_yf_range_i")
        return [
            f"{indent}for (int64_t {ctr} = {start_e}; "
            f"({ctr} < {stop_e}) == ({step_e} > 0); {ctr} += {step_e}) {{",
            f"{indent}    co_yield {ctr};",
            f"{indent}}}",
        ]
    # `yield from sorted(<inner>, key=..., reverse=...)`: `_cpp_expr`'s
    # CallExpr/'sorted' case already lowers the WHOLE `sorted(...)`
    # expression to a self-invoking C++ lambda returning a real
    # `MojoList *` — but that list's elements are ALWAYS stored via
    # `mojo_list_append_int` (this codegen's own "store a struct
    # pointer as a boxed int64_t, cast on read" convention, same as
    # every other MojoList of struct-pointer/scalar elements
    # elsewhere in this file), never as strings — so this needs the
    # same `mojo_list_get_int`-based drive loop the `range()` case
    # just above uses, not the generic "plain collection, assume
    # char*" fallback below. Mirrors `_yield_from_delegate_ctype`'s
    # matching `sorted(...)` type-inference case (this file, ~line
    # 3108) so both sides agree: that function's int64_t default for
    # this shape only stays correct if the elements are actually read
    # back as int64_t here too. Without this case, `mojo_list_get_str`
    # dereferenced the int64_t payload bits as a `char *` — a real,
    # confirmed segfault, not just a wrong-value bug. See
    # bugs/hard/CODEGEN_generator_lambda_expr_unsupported.md.
    if (isinstance(call, gimple_ctypes.CallExpr) and isinstance(call.func, gimple_ctypes.IdentExpr)
            and call.func.name == 'sorted' and call.args
            and not gen._locally_binds_name('sorted')):
        result_var = gen._cpp_fresh_name("_yf_sorted")
        coll_expr = gen._cpp_expr(call)
        return [f"{indent}auto {result_var} = (MojoList *)({coll_expr});",
                f"{indent}for (int64_t _i = 0; _i < mojo_list_len({result_var}); _i++) {{",
                f"{indent}    co_yield mojo_list_get_int({result_var}, _i);",
                f"{indent}}}"]
    # `yield from <expr>` where the value is a plain collection (any
    # non-generator-call expression — a method chain, a bare name, etc.):
    # iterate the MojoList* result with an indexed loop, co_yield-ing
    # each element as char*.
    # Self-recursion: `yield from <this-same-function>(...)` — see the
    # self-tracking context _gen_cpp_generator_unit sets up (`self.
    # _cpp_gen_self_name`/`_base`/`_params`) right before compiling this
    # function's own body, precisely because this function can never
    # find ITSELF in `self._generator_api` yet (registration only
    # happens after the whole compile succeeds) — matches the identical
    # reasoning in `_generator_yield_ctype`'s own YieldFromExpr case,
    # just on the body-EMISSION side instead of the type-INFERENCE
    # side. Without this, a self-recursive `yield from` silently fell
    # through to the "plain collection" fallback below (WRONG: drops
    # keyword arguments entirely — no `_emit_call`-style padding exists
    # on that path — and doesn't even attempt the real delegation
    # loop), which is exactly what produced this hard bug's two
    # observed C++ errors (too-few-arguments, and a yield-type
    # mismatch from the type-inference side's matching char* default).
    _self_name = getattr(gen, '_cpp_gen_self_name', None)
    is_self_recursive = (isinstance(call, gimple_ctypes.CallExpr) and isinstance(call.func, gimple_ctypes.IdentExpr)
                          and _self_name is not None and call.func.name == _self_name)
    is_gen_call = is_self_recursive or (
        isinstance(call, gimple_ctypes.CallExpr) and isinstance(call.func, gimple_ctypes.IdentExpr)
        and call.func.name in gen._generator_api)
    if not is_gen_call:
        result_var = gen._cpp_fresh_name("_yf_result")
        coll_expr = gen._cpp_expr(call)
        # mojo_list_len/mojo_list_get_str both take a real `MojoList *`,
        # but `coll_expr` isn't guaranteed to already BE one at the C++
        # level: a `self.<field>` MemberExpr whose field type isn't one
        # of the 4 known scalars (int64_t/double/_Bool/char *) falls to
        # _cpp_expr's "Unknown field: emit as self->member" case, which
        # returns the field access UNCAST — for a MojoList*-typed field,
        # this codegen's own struct-field boxing convention (same one
        # module globals use — see gen_module's preamble) stores it as
        # a raw `int64_t`, so `auto {result_var} = self->field;` used to
        # infer `result_var` as `long long int`, not `MojoList *`,
        # producing g++ "invalid conversion from 'long long int' to
        # 'MojoList*'" at both calls below. An explicit cast here is
        # correct for every shape this branch reaches (the comment two
        # lines up documents the whole branch's contract as "the value
        # IS a plain collection" — i.e. always semantically a MojoList*
        # already, whether or not its C++-level TYPE currently reflects
        # that), and a cast from an already-correctly-typed `MojoList *`
        # expression to itself is a no-op, so this can't regress any
        # currently-working `yield from <expr>` shape. Real:
        # Lib/test/libregrtest/runtests.py's `RunTests.iter_tests`:
        # `yield from self.tests` (a MojoList* field). See
        # CODEGEN_generator_function_Lib_test_libregrtest_runtests.md.
        result_init = f"(MojoList *)({coll_expr})"
        return [f"{indent}auto {result_var} = {result_init};",
                f"{indent}for (int64_t _i = 0; _i < mojo_list_len({result_var}); _i++) {{",
                f"{indent}    co_yield mojo_list_get_str({result_var}, _i);",
                f"{indent}}}"]
    if call.kwargs:
        # Append keyword arguments as positional args at the end.
        # This is a simplification (correct only when kwargs match the
        # LAST parameters in source order, which is the common case).
        for kname, kexpr in call.kwargs:
            call.args.append(kexpr)
        call.kwargs = []
    sub_name = call.func.name
    if is_self_recursive:
        # Build the SAME {'base', 'params', ...} shape self.
        # _generator_api's entry would eventually hold, straight from
        # the locally-tracked self-context — no premature/partial
        # registration into the real (still-being-built) dict needed.
        api = {'base': gen._cpp_gen_self_base,
               'params': gen._cpp_gen_self_params}
        # Tell _gen_cpp_generator_unit (after this body-emission pass
        # completes) that `{base}_start`/`_resume`/`_value`/`_destroy`
        # need forward declarations ahead of `{impl}`'s own definition
        # — see that flag's own declaration comment for why.
        gen._cpp_gen_self_recursed = True
    else:
        api = gen._generator_api.get(sub_name)
        if api is None or sub_name not in gen._supported_generators:
            raise gimple_exprtypes._UnsupportedGeneratorShape(
                f"`yield from {sub_name}(...)` does not delegate to a "
                "generator this compile has itself already translated via "
                "the C++20-coroutine path (either it's not a generator this "
                "codegen supports, or it's defined LATER in this module — "
                "the delegated-to generator must be defined earlier)")
    sub_params: list = api.get('params') or []
    if len(call.args) != len(sub_params):
        raise gimple_exprtypes._UnsupportedGeneratorShape(
            f"`yield from {sub_name}(...)`: expected {len(sub_params)} "
            f"argument(s), got {len(call.args)}")
    arg_exprs = [gen._cpp_expr(a) for a in call.args]
    sub_base = api['base']
    gen._yield_from_seq = getattr(gen, '_yield_from_seq', 0) + 1
    guard = f"__mojogen_sub{gen._yield_from_seq}"
    args_text = ', '.join(arg_exprs)
    return [
        f"{indent}{{",
        f"{indent}    _mojogen_sub_guard {guard}"
        f"{{ {sub_base}_start({args_text}), &{sub_base}_destroy }};",
        f"{indent}    while ({sub_base}_resume({guard}.g)) {{",
        f"{indent}        co_yield {sub_base}_value({guard}.g);",
        f"{indent}    }}",
        # Milestone D: the sub-generator's own `_resume` (same wrapper
        # every compiled generator gets — see _gen_cpp_generator_unit)
        # already translated any exception that escaped ITS body,
        # uncaught, into the shared mojo_exc_* globals + the pending
        # flag, and reported "done" the same as ordinary exhaustion so
        # this loop above exits either way (see mojo_runtime.h's long
        # comment). Disambiguate here: if it was really a pending
        # exception, re-throw a FRESH _MojoCppExc built from those same
        # globals, right here inside the delegating (outer) generator's
        # OWN body -- NOT via mojo_raise()/longjmp, which must never
        # originate from inside a coroutine frame (this while loop, and
        # the `{guard}` RAII object still in scope one line below,
        # prove exactly why: a longjmp here would skip past `{guard}`'s
        # destructor without running it). Throwing instead keeps this
        # propagating as an ordinary C++ exception: `{guard}`'s
        # destructor runs correctly during the throw's normal stack
        # unwind (a no-op `_destroy` on the sub-generator, which is
        # already done()), and the exception keeps flowing outward
        # through this SAME translation unit -- caught by an enclosing
        # `try` in this generator's own body if there is one, or
        # reaching this (outer) generator's own unhandled_exception(),
        # which repeats the exact same translation for ITS OWN
        # `_resume` boundary. Composes to any depth of nested `yield`
        # `from` with no special-casing beyond this one check.
        f"{indent}    if (mojo_exc_pending_get()) {{",
        f"{indent}        mojo_exc_pending_set(0);",
        f"{indent}        throw _MojoCppExc{{ mojo_exc_type_get(), "
        f"mojo_exc_msg_get(), mojo_exc_obj_get() }};",
        f"{indent}    }}",
        f"{indent}}}",
    ]


def _cls_refs_supported(gen, body, struct_name: str) -> bool:
    """True iff EVERY `cls` reference found anywhere in a @classmethod
    generator's body is one of the two shapes `_cpp_expr`'s MemberExpr/
    CallExpr `cls.<...>` handling actually supports:
      - `cls.<attr>` where `<attr>` is a real class-level attribute
        assigned in the enclosing class's own body (`self._class_attrs`
        — the same class-attribute-global redirect the ordinary,
        non-coroutine GIMPLE path already uses for `self.<class-attr>`/
        `ClassName.attr` reads).
      - `cls.<method>(...)` where `<method>` is a real compiled
        classmethod/static/ordinary method of the enclosing struct
        (`self._classmethod_names`/`self.func_return_types`) — NOT a
        call to another compiled GENERATOR method, which needs its own
        coroutine-construction call convention this fix does not add.
    False for ANYTHING else — a bare `cls` used as a plain value (`x =
    cls`, `f(cls)`), an unrecognized `cls.<attr>` name, or a `cls.
    <method>(...)` call that doesn't resolve to a real compiled
    function — keeping this pre-check exactly as conservative as the
    ORIGINAL blanket "any cls reference in the body -> refuse" check
    for every shape this fix doesn't add real support for, so nothing
    new ever reaches `_cpp_expr`'s MemberExpr "non-self member access"
    fallback (which would emit invalid C++ on `cls`'s opaque int64_t
    placeholder) or silently reads that placeholder as if it were a
    real value.

    Walked in two passes rather than one, since a single `IdentExpr`
    node can only be recognized as "supported" from its PARENT
    (MemberExpr/CallExpr) context — the first pass collects the
    `id()` of every `cls` IdentExpr that appears as the receiver of a
    supported access shape; the second pass then requires EVERY `cls`
    IdentExpr anywhere in the body to be one of those, by identity
    (not by name/position), so a `cls` reference that happens to look
    like a supported receiver's `.obj` but is a DIFFERENT AST node
    (impossible in practice, since each occurrence in source is its
    own node, but kept identity-based rather than shape-based to
    avoid ever under-counting) is never missed.

    See gimple_codegen.py's classmethod-generator eligibility check
    (this method's only caller) and bugs/CODEGEN_generator_function_
    Lib_enum.md's 2026-08-21 update for the motivating Lib/enum.py
    `Flag._iter_member_by_value_`/`_iter_member_by_def_` shapes.
    """
    class_attrs = gen._class_attrs.get(struct_name, {})
    supported_ids: set = set()
    for n in gimple_exprtypes._walk_ast(body):
        if (isinstance(n, gimple_ctypes.MemberExpr) and isinstance(n.obj, gimple_ctypes.IdentExpr)
                and n.obj.name == 'cls' and n.member in class_attrs):
            supported_ids.add(id(n.obj))
        elif (isinstance(n, gimple_ctypes.CallExpr) and isinstance(n.func, gimple_ctypes.MemberExpr)
                and isinstance(n.func.obj, gimple_ctypes.IdentExpr) and n.func.obj.name == 'cls'):
            mangled = f"{struct_name}_{n.func.member}"
            # Exclude a call to another compiled GENERATOR method
            # (`self._struct_generator_method_names` — a real
            # `@classmethod` generator, like Lib/enum.py's `Flag.
            # _iter_member_by_value_`, is ALSO in `_classmethod_names`,
            # which alone would wrongly mark this shape "supported"):
            # that needs its own coroutine-construction call
            # convention this fix does not add (see this method's own
            # docstring).
            if (n.func.member not in gen._struct_generator_method_names.get(struct_name, ())
                    and (mangled in gen._classmethod_names
                         or mangled in gen.func_return_types)):
                supported_ids.add(id(n.func.obj))
    for n in gimple_exprtypes._walk_ast(body):
        if isinstance(n, gimple_ctypes.IdentExpr) and n.name == 'cls' and id(n) not in supported_ids:
            return False
    return True
