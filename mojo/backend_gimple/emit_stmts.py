# Moved from gimple_gen_stmts.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""Statement lowering for the GIMPLE backend.

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
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator,
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
    _as_str, _pair_key,
)
import regex_compile
import mlir
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import mojo.middle.itcursor as itc
import gimple_codegen
import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.emit_calls as ggc
import mojo.backend_gimple.emit_infra as ginf

# Re-export shared helpers from mojo.middle.stmts_shared via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.stmts_shared import *  # noqa: F401,F403
from mojo.middle.stmts_shared import (
    _annotation_container_elem_type, _annotation_dict_nested_val_type, _annotation_dict_val_type, _as_str, _assign_target, _collect_isinstance_narrowings, _handler_bind_name,
    _handler_exc_name, _is_except_as_member_target, _is_genexp, _isinstance_narrow_struct, _iter_ast, _narrow_key_for_expr,
    _pair_key, _seed_genexp_list_narrowing, _with_item_alias_name
)
from mojo.middle.types import _is_empty_container_literal
from mojo.middle.calls_shared import _is_pointer_ctype


def gen_stmt(gen, node):
    # Emit #line directive to track source location. Critical for debugging:
    # optimizations intermix and reorder code from different lines and files.
    # Only emit if we haven't emitted this exact (filename, line) pair before.
    node_kind = type(node).__name__
    if hasattr(node, 'line') and node.line and node.line > 0:
        # `_line_src_file` overrides `_current_filename` for the duration of
        # one enclosing unit (a base class's method body re-emitted as a
        # SUBCLASS method by the inheritance merge, whose nodes physically
        # belong to the base's module). Without it every such statement was
        # tagged with the subclass's filename and the base's line NUMBER —
        # e.g. Lib/weakref.py's inherited `Mapping.__eq__` reported as
        # "weakref.py:962" when weakref.py is only 574 lines long and the
        # real source is _collections_abc.py:819. A pure diagnostics defect
        # (the emitted C itself was correct). FIXED; regression test
        # `inherited_method_line_directive_names_its_own_module` in
        # test_gimple.py. (The bug report that recorded it,
        # bugs/hard/CODEGEN_function_scoped_import_rettype_and_literal_cast_
        # mismatches.md, was removed 2026-09-26 once verified; its remaining
        # live residue is bugs/hard/CODEGEN_function_scoped_import_module_not_
        # inlined.md, which is a different mechanism and does not own this.)
        filename = '' + (getattr(gen, '_line_src_file', '')
                         or getattr(gen, '_current_filename', ''))
        emitted_pairs = getattr(gen, '_emitted_line_pairs', set())

        # Create unique key for this (filename, line) combination
        pair_key = (filename, node.line)

        # Emit #line only if we haven't emitted this exact pair before
        if pair_key not in emitted_pairs:
            if filename:
                gen._emit(f"#line {node.line} \"{filename}\"")
            else:
                gen._emit(f"#line {node.line}")
            emitted_pairs.add(pair_key)
            gen._emitted_line_pairs = emitted_pairs

    # A single Mojo statement (e.g. an assignment whose RHS is a call)
    # commonly lowers to SEVERAL physical C lines (one per temp var), but
    # the #line directive above is only emitted once, before the first of
    # them. GCC's own line-counting for a -fgimple diagnostic increments
    # per PHYSICAL line since the last #line directive, not per logical
    # Mojo statement — so an error on e.g. the 3rd physical line of a
    # one-statement expansion gets reported 2 lines past the statement's
    # real source line (see BUG-2026-016: a bad field assignment reported
    # 2 lines below the assignment itself). Re-stamping every physical
    # line of a LEAF statement's own expansion with the same #line
    # directive eliminates that drift, since GCC resets its count at
    # every directive. Restricted to leaf statement kinds — a compound
    # statement (if/while/for/try/with/...) recurses into gen_stmt for
    # its own nested body, which already got its own correct #line calls;
    # blindly re-stamping its ENTIRE emitted range here would instead
    # overwrite those nested statements' correct line numbers with the
    # outer compound statement's line.
    body_start = len(gen.body_lines) if node_kind not in gen._COMPOUND_STMT_KINDS else None

    # Static dispatch: an explicit isinstance chain (one branch per
    # statement kind), NOT getattr(self, name)(node) on _STMT_DISPATCH.
    # getattr's dynamic indirect call compiles to a no-op when this file
    # is itself compiled into the mojoc binary, silently dropping every
    # statement body; the isinstance chain compiles to plain branch
    # checks (the same pattern _cpp_stmt uses successfully).
    if isinstance(node, gimple_ctypes.PassStmt):
        gen._gen_stmt_PassStmt(node)
    elif isinstance(node, gimple_ctypes.VarDecl):
        if isinstance(node.name, str) and ginf.maybe_stack_alloc_owned_ctor(
                gen, node.name, node.value, getattr(node, 'type_ann', None)):
            pass  # fully handled — see gimple_gen_infra.py's Phase 6 section
        else:
            gen._decl_value_node = node.value
            gen._decl_rhs_val = ''
            gen._gen_stmt_VarDecl(node)
            ginf.maybe_push_owned_local(gen, node.name, node.value)
            gen._decl_value_node = None
    elif isinstance(node, gimple_ctypes.AssignStmt):
        if (isinstance(node.target, IdentExpr)
                and ginf.maybe_stack_alloc_owned_ctor(
                    gen, node.target.name, node.value,
                    getattr(node, 'type_ann', None))):
            pass  # fully handled — see gimple_gen_infra.py's Phase 6 section
        else:
            gen._decl_value_node = node.value
            gen._decl_rhs_val = ''
            gen._gen_stmt_AssignStmt(node)
            if isinstance(node.target, IdentExpr):
                ginf.maybe_push_owned_local(gen, node.target.name, node.value)
            gen._decl_value_node = None
    elif isinstance(node, gimple_ctypes.AugAssignStmt):
        gen._gen_stmt_AugAssignStmt(node)
    elif isinstance(node, gimple_ctypes.MultiAssignStmt):
        gen._gen_stmt_MultiAssignStmt(node)
    elif isinstance(node, gimple_ctypes.ReturnStmt):
        gen._gen_stmt_ReturnStmt(node)
    elif isinstance(node, gimple_ctypes.IfStmt):
        gen._gen_stmt_IfStmt(node)
    elif isinstance(node, gimple_ctypes.WhileStmt):
        gen._gen_stmt_WhileStmt(node)
    elif isinstance(node, gimple_ctypes.ForStmt):
        _for_mark = len(gen._scope_live)
        gen._gen_stmt_ForStmt(node)
        ginf.emit_statement_temp_frees(gen, _for_mark)
    elif isinstance(node, gimple_ctypes.BreakStmt):
        gen._gen_stmt_BreakStmt(node)
    elif isinstance(node, gimple_ctypes.ContinueStmt):
        gen._gen_stmt_ContinueStmt(node)
    elif isinstance(node, gimple_ctypes.ExprStmt):
        gen._gen_stmt_ExprStmt(node)
    elif isinstance(node, gimple_ctypes.AssertStmt):
        gen._gen_stmt_AssertStmt(node)
    elif isinstance(node, gimple_ctypes.RaiseStmt):
        gen._gen_stmt_RaiseStmt(node)
    elif isinstance(node, gimple_ctypes.TryStmt):
        gen._gen_stmt_TryStmt(node)
    elif isinstance(node, gimple_ctypes.WithStmt):
        gen._gen_stmt_WithStmt(node)
    elif isinstance(node, gimple_ctypes.FunctionDef):
        gen._gen_stmt_FunctionDef(node)
    elif isinstance(node, gimple_ctypes.ImportStmt):
        gen._gen_stmt_ImportStmt(node)
    elif isinstance(node, gimple_ctypes.FromImportStmt):
        gen._gen_stmt_FromImportStmt(node)
    elif isinstance(node, gimple_ctypes.ComptimeIfStmt):
        gen._gen_stmt_ComptimeIfStmt(node)
    elif isinstance(node, gimple_ctypes.ComptimeForStmt):
        gen._gen_stmt_ComptimeForStmt(node)
    elif isinstance(node, gimple_ctypes.ComptimeVarStmt):
        gen._gen_stmt_ComptimeVarStmt(node)
    elif isinstance(node, gimple_ctypes.GlobalStmt):
        gen._gen_stmt_GlobalStmt(node)
    elif isinstance(node, NonlocalStmt):
        gen._gen_stmt_NonlocalStmt(node)
    elif isinstance(node, gimple_ctypes.MatchStmt):
        gen._gen_stmt_MatchStmt(node)
    elif isinstance(node, gimple_ctypes.DelStmt):
        gen._gen_stmt_DelStmt(node)
    else:
        gimple_ctypes._debug_note('unknown statement dropped', node_kind)
        gen._emit(f"  /* TODO: {node_kind} */")

    if (body_start is not None and hasattr(node, 'line') and node.line and node.line > 0
            and len(gen.body_lines) - body_start > 1):
        filename = (getattr(gen, '_line_src_file', '')
                    or getattr(gen, '_current_filename', ''))
        directive = f"#line {node.line} \"{filename}\"" if filename else f"#line {node.line}"
        # Skip the very first emitted line (already directly preceded by
        # the directive above); re-stamp every one after it, from the end
        # backwards so earlier insertions don't shift later indices.
        for i in range(len(gen.body_lines) - 1, body_start, -1):
            if gen.body_lines[i] != directive and not gen.body_lines[i].lstrip().startswith('#line '):
                gen.body_lines.insert(i, directive)




def _gen_stmt_PassStmt(gen, node):
    return






def _try_bind_iter_cursor(gen, name, value):
    """`it = iter(<container-expr>)` — bind `it` to the container plus a
    companion int64_t cursor temp so `next(it)` advances a genuine position
    and a following `for x in it:` resumes from it (single-pass Python
    iterator semantics), rather than modelling `iter()` as a bare identity
    (which restarts every scan from element 0 and leaves `next()` with no
    real lowering at all). Mirrors gimple_cpp_core.py's `_cpp_list_iter_
    cursor` for the old cpp coroutine path; here it also covers an A3
    stack-switch generator body, whose statements go through this ordinary
    codegen. Returns True iff it claimed the assignment.

    Two container kinds, and the admission test for the second is the tree's
    own `_struct_data_field` rather than a hardcoded `Span`:
    `emit_calls._lower_subscript`'s struct-pointer arm already treats "a
    struct pointer with a `_data`/`data` field AND a `_len`" as an indexable
    buffer and reads it through `_mojo_at_<T>`. `iter()` on such a value is the
    same container viewed as a sequence, so admitting it here makes
    `next(iter(span))` agree with `span[i]` by construction instead of by a
    second list of type names. That is what `test/collections/test_span.mojo`'s
    `var it = iter(span); next(it)` needs, and it was refused for exactly the
    reason ROUND 4 (a) of
    bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md
    records: the cursor mechanism gated on `MojoList *`, so a `Span *` — which
    IS a real sequence with a real length — got no cursor, and `next()` then
    had no receiver to dispatch on.

    The element type comes from `_elem_types`, the side-table the Span
    constructor already populates; an untracked element (a raw byte buffer) is
    int64_t, which is what every consumer assumed before.
    """
    if not (isinstance(name, str) and name and ',' not in name
            and isinstance(value, CallExpr)
            and isinstance(value.func, IdentExpr)
            and value.func.name == 'iter'
            and len(value.args) == 1 and not getattr(value, 'kwargs', None)
            and not gen._locally_binds_name('iter')
            and name not in gen.var_types
            and name not in gen._global_var_types):
        return False
    at, av = gen.lower_expr(value.args[0])
    at = gen._get_actual_type(at, av)
    data = None
    if at == 'MojoList *':
        kind = 'list'
    elif at in ('int', 'int64_t', 'void *'):
        kind = 'list'
        av = gen._coerce_to_type('int64_t', 'MojoList *', gen._to_int64(at, av))
        at = 'MojoList *'
    else:
        fname, ftype = gen._struct_data_field(at)
        sname = gimple_exprtypes._struct_name_of(at) if fname else ''
        if not fname or '_len' not in gen.struct_field_types.get(sname, {}):
            return False
        kind = 'span'
        data = (fname, ftype)
    elem = gen._elem_of(av)
    gen._declare_var(name, at)
    gen._emit(f"  {gen._write_dest(name)} = {av};")
    cname = gen._cname(name)
    cur = gen._new_temp('int64_t')
    gen._emit(f"  {cur} = (int64_t)0;")
    # The TOTAL length, read once here rather than at each use: see
    # mojo/middle/itcursor.py's `remaining` for why re-reading it per
    # condition is a different program.
    if kind == 'span':
        full = gen._new_val('int64_t', f"{av}->_len")
    else:
        full = gen._call_expr('int64_t', 'mojo_list_len', [(at, av)])
    rec = {'kind': kind, 'src': cname, 'cursor': cur, 'full': full,
           'elem': elem, 'vct': itc.slot_ctype(elem)}
    if data is not None:
        rec['data'] = data
    gen._list_iter_cursor[cname] = rec
    if elem and elem != 'int64_t':
        gen._elem_types[cname] = elem
    return True









def _maybe_narrow_genexp_local(gen, name, value) -> bool:
    """If `name = (<genexp>)` was marked by `_seed_genexp_list_narrowing`
    and `name` already has a non-list C storage type (a parameter, or a
    local previously typed otherwise — the fresh-local case already works
    via ordinary inference), materialise the genexp as a list, store it
    into the existing slot as an opaque pointer, and register `name` in
    `_genexp_list_locals` so later reads lower as `MojoList *`. Returns
    True iff it claimed the assignment."""
    if not (isinstance(name, str) and name in gen._genexp_narrow_names
            and _is_genexp(value)):
        return False
    if gen.var_types.get(name) in (None, 'MojoList *'):
        return False
    # Lower the genexp AS a list comprehension.
    _saved_kind = value.kind
    value.kind = 'list'
    try:
        vtype, v = gen.lower_expr(value)
    finally:
        value.kind = _saved_kind
    dst = gen.var_types[name]
    gen._safe_coerce_emit(vtype, dst, v, gen._write_dest(name))
    elem = gen._elem_of(v)
    gen._genexp_list_locals[name] = elem if elem else 'int64_t'
    gen._genexp_narrow_names.discard(name)
    return True


def _record_bool_valued(gen, name: str, value) -> None:
    """Remember that `name` holds a bool, so `print` can format it as
    True/False.

    A bool's C type is a plain `int` here (BoolLiteral lowers to int, and
    any/all/isinstance return a C int on purpose), so the print dispatch's
    static-type check cannot see it and `print(True)`, `print(b)` for
    `b = True`, `print(any(xs))` all printed `1`/`0`. Keyed by NAME and
    consulted only by the print dispatch, so this adds no claim to the type
    lattice itself."""
    try:
        if isinstance(value, gimple_ctypes.BoolLiteral):
            gen._bool_valued.add(name)
        elif gen._quick_type(value) == '_Bool':
            gen._bool_valued.add(name)
        else:
            gen._bool_valued.discard(name)
    except Exception:
        # _quick_type is best-effort by contract; a node it cannot type
        # simply leaves the name unmarked (the old behaviour).
        pass


def _gen_stmt_VarDecl(gen, node):
    if node.value is not None and _try_bind_iter_cursor(gen, node.name, node.value):
        return
    # `var name = value` where `name` is heap-boxed (some nested
    # closure captures it BY REFERENCE -- see _seed_mut_captured_
    # local_types's docstring): `_declare_var` already emitted the
    # POINTER declaration (`{ctype} * name;`) before this statement
    # ever runs, and the box ITSELF is allocated once in the function
    # prologue (see _emit_mut_local_box_allocs -- allocating here made
    # the box per-statement-execution instead of per-call, which both
    # missed plain-AssignStmt first bindings entirely (real Python
    # source: analyzer.py's `nonlocal next_opcode`) and re-malloc'd a
    # fresh cell on every loop iteration, silently splitting the
    # nonlocal binding). Just store the (coerced) initial value through
    # the already-allocated box's dereference.
    if (isinstance(node.name, str) and node.name in gen._boxed_mut_locals
            and node.value is not None):
        ctype = gen._boxed_mut_locals[node.name]
        cname = gen._cname(node.name)
        vtype, v = gen.lower_expr(node.value)
        gen._safe_coerce_emit(vtype, ctype, v, f'*{cname}')
        return
    # Tuple VarDecl: parser sets name='a,b' for `a, b = expr`. Lower as individual
    # assignments to avoid GIMPLE's implicit multi-value decl which causes
    # "redeclaration with no linkage" when the names were already declared.
    if isinstance(node.name, str) and ',' in node.name and node.value is not None:
        # Bracket-aware split: a naive `.split(',')` tore a nested slot
        # `(b, c)` into the bogus fragments `(b` / `c)` (declared verbatim
        # as C identifiers). One name per TOP-LEVEL slot keeps the
        # position-to-_tuple_elem_value mapping intact.
        names = [n.strip() for n in gimple_ctypes._split_top_level_commas(node.name)
                 if n.strip()]
        vtype, v = gen.lower_expr(node.value)
        for i, n in enumerate(names):
            if n == '_':
                continue
            # _tuple_elem_value resolves the element accessor from the
            # (possibly int64_t-boxed) tuple's real element type, so a
            # char*-tuple VarDecl declares real char* locals instead of
            # storing pointer decimals in int64_t ones.
            et, ev = gen._tuple_elem_value(vtype, v, i)
            # A target already registered as the int64_t DEFAULT is not a
            # decision — it is the absence of one, and this slot read is
            # real evidence about what the name holds. Re-declaring it is
            # safe precisely because the old type carries no information:
            # `_declare_var` is first-decl-wins, so without this the real
            # slot type was thrown away and the value was immediately
            # coerced BACK to int64_t on the store (a `Config *` slot read
            # through `(Config *)` then `(void *)` then `(int64_t)`).
            if gen.var_types.get(n) in ('int64_t', 'int') and et not in ('int64_t', 'int'):
                _redecl_upgrade_default(gen, n, et)
            gen._declare_var(n, et)
            gen._safe_coerce_emit(et, gen.var_types[n], ev, gen._write_dest(n))
            gen._track_pointer_actual_type(n, gen.var_types[n], ev, et)
        return
    if node.type_ann in gen.struct_field_types and node.value is not None:
        layout = gen._struct_layout.get(node.name, gimple_solvers.LayoutSolver.HEAP)
        gen._layout_hint = layout
    if node.value is not None:
        vtype, v = gen.lower_expr(node.value)
        # Type inference: if no annotation, use the value's type instead of 'int'
        if node.type_ann is None:
            ctype = vtype
            # An unannotated integer local is Int (64-bit), not the C
            # `int` an int32-range literal lowers to: the pre-pass
            # (`_infer_local_var_types`) already widened it, so honour
            # that hint exactly as the plain-assignment path does.
            if (ctype == 'int' and isinstance(node.name, str)
                    and node.name not in gen.var_types):
                _hint = gen._inferred_var_types.get(
                    gen.current_func_name, {}).get(node.name)
                if _hint == 'int64_t':
                    ctype = 'int64_t'
        else:
            ctype = gen._resolve_type(node.type_ann)
        gen._declare_var(node.name, ctype)
        # Use the actual declared type (may differ if variable was already declared
        # in an earlier branch with a different inferred type)
        actual_dst = gen.var_types.get(node.name, ctype)
        # A module-level `var name = value`/`var name: T = value` (this
        # module's OWN top-level statement, or a nested `global name`
        # declaration) writes to the module-globals STRUCT FIELD, whose
        # real declared C type can differ from the semantic `ctype`
        # (a MojoDict*/MojoList*/MojoSet* global is boxed as int64_t at
        # the struct-field level — see gen_module's global-scan DictExpr/
        # ListExpr/SetExpr cases) — mirrors _gen_stmt_AssignStmt's
        # identical `_global_c_decl_types.get(...)` coercion a few
        # hundred lines below in this file. Missing this meant `var
        # g_cooking_recipes = list()` at module scope emitted a raw,
        # uncoerced `_mod_globals.g_cooking_recipes = <MojoList *>;` into
        # a field GCC now (correctly) declares `int64_t` — "assignment to
        # 'int64_t' from 'MojoList *' makes integer from pointer without
        # a cast" — found via box.3d/game/lib/recipes.mojo.
        if ((gen._in_toplevel_gen or node.name in getattr(gen, '_func_declared_globals', ()))
                and node.name in gen._global_var_types):
            actual_dst = gen._global_dst_ctype(node.name)
        _record_bool_valued(gen, node.name, node.value)
        if ctype in ('MojoList *', 'MojoSet *') and v in gen._elem_types:
            gen._elem_types[node.name] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[node.name] = gen._nested_elem_types[v]
        if ctype == 'MojoDict *':
            if v in gen._elem_types:
                gen._elem_types[node.name] = gen._elem_types[v]
                if v in gen._nested_elem_types:
                    gen._nested_elem_types[node.name] = gen._nested_elem_types[v]
            if v in gen._dict_val_types:
                gen._dict_val_types[node.name] = gen._dict_val_types[v]
                if v in gen._dict_nested_val_types:
                    gen._dict_nested_val_types[node.name] = gen._dict_nested_val_types[v]
        # If value has element type tracking (e.g. split result), propagate to inferred var
        if node.type_ann is None and v in gen._elem_types:
            gen._elem_types[node.name] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[node.name] = gen._nested_elem_types[v]
        # Same propagation for a `struct.unpack(...)` result's PER-SLOT
        # kinds: `var m = struct.unpack('<if', buf)` records them on the
        # unpack temp, and the subscript on `m` needs them under `m`'s own
        # name. Without this the mixed-format fix silently does nothing for
        # the local-variable spelling (only a bare
        # `struct.unpack(...)[1]` would see it). Mirrors _elem_types
        # exactly, including the `type_ann is None` guard.
        if node.type_ann is None and v in gen._struct_slot_kinds:
            gen._struct_slot_kinds[node.name] = gen._struct_slot_kinds[v]
        # And the companion marker for the reads the per-slot kinds cannot
        # answer — iteration and a computed subscript — which need the
        # runtime's own record on the value. Same guard, same reason: it is
        # the local name the read is keyed on, not the unpack temp.
        if node.type_ann is None and v in gen._maybe_kinds_vals:
            gen._maybe_kinds_vals.add(node.name)
        # Same propagation for a `struct.Struct(...)` handle's format string,
        # which is what lets `var s = struct.Struct('<if')` then
        # `s.unpack(buf)` recover the per-slot kinds. Same shape, same
        # `type_ann is None` guard, same reason: without it only the inline
        # `struct.Struct('<if').unpack(buf)` spelling would know its format.
        if node.type_ann is None and v in gen._struct_formats:
            gen._struct_formats[node.name] = gen._struct_formats[v]
        # `var g = counter(3)` / `var task = create_task(f())` — the
        # `var`-keyword spelling of a declaration lowers through THIS
        # method (VarDecl), not the plain AssignStmt path a few lines
        # below in this file, which already carries the generator/async
        # "value -> api" side-table entries across a `g = counter(3)`-
        # style (no `var`) assignment (see that method's own comment on
        # self._generator_var_api/self._async_var_api). Mirrored here
        # for the exact same reason — without it, `var task =
        # create_task(f())` followed by `task.wait()` found no entry
        # for `task` and fell through to a bogus generic method-
        # dispatch fallback instead of the real _lower_method_call
        # `.wait()` handling.
        if actual_dst == 'MojoGenerator *' and v in gen._generator_var_api:
            gen._generator_var_api[node.name] = gen._generator_var_api[v]
        if actual_dst == 'MojoAsync *' and v in gen._async_var_api:
            gen._async_var_api[node.name] = gen._async_var_api[v]
        # `var f = <closure value>` / `var f = lambda: False` (see
        # _lower_IdentExpr's closure-value materialization and
        # _lower_LambdaExpr): carry what the callable REALLY returns onto the
        # variable, so a later `f()` (_lower_bound_method_call /
        # _lower_fnptr_call_value) narrows the result correctly instead of
        # assuming the homogenized `int64_t` — without it `print(f())` printed
        # `0` for a `lambda: False`. One shared carry for all three callable
        # tables (`var f = <bound method>`, `var f = <lambda>`, and the dict's
        # own single agreed record), because the AssignStmt path below had the
        # same three tables hand-copied and the two module-global store
        # branches had none of them — a copy that is silently forgotten is a
        # wrong value with exit 0, not a build error.
        ginf.carry_callable_ret_types(gen, v, node.name)
        ginf.carry_callable_ret_from_call(gen, getattr(node, 'value', None), node.name)
        # `append = l.append` (a builtin-container method bound as a
        # value, see _lower_builtin_method_value): carry the recorded
        # (receiver, method) binding from the RHS temp onto the variable,
        # mirroring the _bound_method_ret_types propagation just above —
        # a later `append(...)` call dispatches on the VARIABLE's name.
        if v in gen._builtin_method_values:
            gen._builtin_method_values[node.name] = gen._builtin_method_values[v]
        # `var tg = TaskGroup()` -- mirrors the `MojoAsync *` case just
        # above exactly (see `_lower_call`'s `TaskGroup()` construction
        # docstring / `self._taskgroup_var_api`'s own docstring).
        if actual_dst == 'MojoList *' and v in gen._taskgroup_var_api:
            gen._taskgroup_var_api[node.name] = gen._taskgroup_var_api[v]
        # BUG-2026-023 residual: annotated `parts: List[String] = ...` with
        # an INITIALIZER takes this branch (not the else-branch below), so
        # seed the element type from the annotation here too — otherwise a
        # list filled via insert()/index-stores reads back as raw int64_t
        # handles (same gap as the no-initializer path's seeding below).
        if actual_dst == 'MojoList *' or actual_dst == 'MojoSet *':
            _et = _annotation_container_elem_type(gen, node.type_ann, actual_dst)
            if _et and node.name not in gen._elem_types:
                gen._elem_types[node.name] = _et
        # `var s: Set[Int] = {}` — an empty `{}` display carries no evidence
        # for ANY container kind (an empty dict, list and set are equally
        # "nothing"), and its default lowering is a DICT, so coercing it to
        # the declared `MojoSet *` either reinterprets the header (the
        # silent-wrong-value shape: `s.add(i)` became a no-op and the set
        # printed `{}` forever) or, once anything in the body needs the set's
        # real kind, hard-refuses with "cannot coerce MojoDict * to MojoSet *".
        # Build the kind the destination declares instead. Same
        # `reify_empty_container_literal` call, same reason, as the
        # plain-assignment path below — which is the shape the
        # `parts: List[String] = ...` rewriter produces, so the `var` spelling
        # was the only one still missing it.
        _reified = gimple_ctypes.reify_empty_container_literal(
            gen, vtype, actual_dst, node.value)
        if _reified is not None:
            vtype, v = actual_dst, _reified
        # `var k = 3000000000` IS a store, so it goes through the SAME
        # chokepoint the plain AssignStmt path and the tuple-declaration path
        # already use. This method carried `_elem_types` / `_dict_val_types`
        # / `_struct_slot_kinds` / the callable tables by hand across the
        # statements above and was missing the one table that decides whether
        # a value is a plain INTEGER — so `var k = 3000000000` (at any scope,
        # local or module-level) left `k` unrecorded and `d[k] = 1` was
        # handed to `mojo_dict_set_int_kw`, where the runtime's range-only
        # discriminator calls address 3000000000 a `char *` and the program
        # SIGSEGVs. The chokepoint's `discard` branch keeps it sound: a
        # `var` whose initializer the codegen cannot vouch for clears the
        # record instead of leaving a stale one. See
        # bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md.
        gen._track_pointer_actual_type(node.name, actual_dst, v, vtype)
        gen._safe_coerce_emit(vtype, actual_dst, v, gen._write_dest(node.name))
    else:
        ctype = gen._resolve_type(node.type_ann)
        gen._declare_var(node.name, ctype)
        # BUG-2026-030: a default-constructed struct local (`var w: W`, no
        # initializer) used to leave `w` a bare, never-allocated `W *` --
        # reading/writing through it is undefined behavior (usually a
        # segfault, sometimes silent heap corruption when the garbage bit
        # pattern happens to land in mapped memory). This is the exact same
        # shape of gap the "()"-suffix List[T]/Dict/Set auto-alloc a few
        # lines below in this function already fixes for those container
        # types (see its own long comment, box.3d/game's
        # DYLIB_string_copy_append_return_segv.md) -- give a struct local
        # real storage the same way an explicit `W()` constructor call does
        # (`_lower_struct_constructor`): call the `_alloc_W()` helper so the
        # struct's `__mojo_type_id` tag and any class-attribute-seeded
        # fields are initialized too, not just a raw `malloc` with no field
        # initialization. Struct-by-value RETURNS ride on the same local
        # (`return w`), so this also fixes that shape.
        _sann = gen._c_kw_struct_renames.get(node.type_ann, node.type_ann) \
            if isinstance(node.type_ann, str) else node.type_ann
        if isinstance(_sann, str) and _sann in gen.struct_field_types:
            gen._struct_allocs_needed.add(_sann)
            gen._emit(f"  {gen._write_dest(node.name)} = _alloc_{_sann} ();")
        _dv = gen._annotation_dict_val_type(node.type_ann)
        if _dv is not None:
            gen._dict_val_types[node.name] = _dv
        # BUG-2026-023 residual (box.3d/game's FileSystem.current_dir_path):
        # seed the ELEMENT type of an explicitly-annotated List[T] local from
        # its own annotation, mirroring `_dv` above for dicts. Without this,
        # a `parts: List[String]` that is only ever filled via
        # insert()/index-stores (no .append for _scan_container_elems to
        # learn from) read back through mojo_list_get_int — every element
        # came back as a raw pointer handle printed as a decimal blob.
        if ctype == 'MojoList *' and isinstance(node.type_ann, str) \
                and '[' in node.type_ann and not node.type_ann.startswith('['):
            _li = gimple_ctypes._split_top_level_commas(
                node.type_ann.split('[', 1)[1].rstrip(']').strip())
            if _li:
                try:
                    _et = gen._resolve_type(_li[0].strip())
                except Exception:
                    _et = None
                if _et and _et != 'int64_t':
                    gen._elem_types[node.name] = _et
        # `var x: list()` / `var x: dict()` / `var x: set()` -- a bare
        # call-shaped annotation with NO initializer (see _mojo_type's
        # matching "()"-suffix branch for the full story: this project's
        # own "declare + implicitly construct an empty dynamic
        # container" idiom, e.g. `var g_item_ids: list()` in box.3d/
        # game/lib/recipes.mojo). `_declare_var` above only emits the
        # bare C POINTER DECLARATION -- `_mojo_type` now resolves the
        # annotation to the right pointer type, but the pointer itself
        # is never actually allocated, so the first `.append()`/
        # subscript/read dereferences whatever garbage bits happen to
        # be sitting in that slot: a deterministic SIGSEGV (bisected
        # via box.3d/game/DYLIB_string_copy_append_return_segv
        # -- despite the bug report's title, this reproduces identically
        # in `fire build`'s linked-executable path too, nothing to do
        # with dylib mode; the report's own p2/global-`list()` repro
        # was simply never re-tested in build mode). Auto-allocate here,
        # mirroring exactly what `var x = list()` (a real initializer)
        # already does via `_lower_call`'s `list()`/`dict()`/`set()`
        # handling.
        #
        # Deliberately scoped to ONLY this "()"-suffix annotation shape
        # -- a bracketed `var x: List[T]` (no initializer) is real
        # Mojo's own explicit "must assign before use" form, not this
        # project's implicit-construct idiom, and auto-allocating THAT
        # too would silently paper over genuine definite-assignment
        # bugs instead of fixing this one, narrowly-reported gap.
        if isinstance(node.type_ann, str) and node.type_ann.endswith('()') and '[' not in node.type_ann:
            _alloc = {'MojoList *': 'mojo_list_new ()',
                      'MojoDict *': 'mojo_dict_new ()',
                      'MojoSet *': 'mojo_set_new ()'}.get(ctype)
            if _alloc is not None:
                v = gen._new_val(ctype, _alloc)
                actual_dst = gen.var_types.get(node.name, ctype)
                if ((gen._in_toplevel_gen or node.name in getattr(gen, '_func_declared_globals', ()))
                        and node.name in gen._global_var_types):
                    actual_dst = gen._global_dst_ctype(node.name)
                gen._safe_coerce_emit(ctype, actual_dst, v, gen._write_dest(node.name))
    gen._layout_hint = gimple_solvers.LayoutSolver.HEAP


def _track_pointer_actual_type(gen, tname: str, dst: str, v: str, vtype: str) -> None:
    """When storing a pointer value into an int64_t-declared local (either
    because the local's own type was widened joining another assignment
    site in the same function, or it's simply this codegen's
    boxed-pointer storage convention), remember its real pointer type in
    _actual_types so a later read (len(), x[i], x.attr, etc.) recovers
    the right runtime dispatch instead of guessing MojoList*. Shared by
    both the plain scalar AssignStmt path and the tuple-unpack path
    (_assign_target) — the latter used to skip this tracking entirely,
    which is why `prefix, rest = raw[:n], raw[n:]`-style tuple
    assignments (unlike an equivalent plain `rest = raw[n:]`) left
    `rest` with no actual-type record at all: found via
    fire_compiler.py's own _strip_string_prefix_and_quotes, where
    `len(rest)`/`rest[0]` on the tuple-unpacked `rest` misread it as a
    MojoList* and segfaulted deep in mojo_list_get_int.

    `_as_str(tname)` — a CHOKEPOINT guard (the same pattern `_new_temp`
    uses for `ctype`). `tname` here is an IdentExpr's `.name` FIELD read
    (`tgt.name` at the call site), not a local variable — and a struct
    field of static type `str` apparently still round-trips through this
    self-hosted backend's generic int64_t erasure in a way plain string
    locals/params don't: `==`/`.startswith()` against it worked (byte
    contents intact) but `len()` on it returned 0 and every dict lookup
    keyed by it missed, even immediately after inserting a `char` entry
    UNDER that exact key in this exact call (confirmed with
    `/tmp/mojo_repro/t1.py`'s `c = s[0]; if c == 'x': ...` — the minimal
    repro: `gen._actual_types['c'] = 'char'` here, followed one
    statement later by `gen._actual_types.get('c')` at the comparison
    site, returned None on self-host despite an identical-content key).
    This is very likely the SAME root cause behind the ~696/779-file
    CI-DIFF the aside/bside sweep found across the whole stdlib, since
    `_actual_types`-by-identifier-name tracking is used pervasively for
    char/string dispatch. See bugs/CODEGEN_selfhost_actual_types_
    identifier_field_key.md for the still-open general form of this."""
    tname = _as_str(tname)
    # The complement of everything below: carry the POSITIVE integer record
    # across the assignment, so `k = 3000000000` then `d[k]` is still known
    # to be an integer at the dict site rather than handed to the runtime's
    # range-only discriminator (see `gen._int_word_vals`). `discard` on the
    # other branch is what keeps this sound rather than optimistic — `k = "s"`
    # later must NOT leave `k` marked, and every RHS this codegen cannot
    # vouch for takes that branch.
    if v in gen._int_word_vals:
        gen._int_word_vals.add(tname)
    else:
        gen._int_word_vals.discard(tname)
    if dst != 'int64_t':
        if v in gen._struct_field_owners:
            gen._struct_field_owners[tname] = list(gen._struct_field_owners[v])
        if dst == 'MojoList *' and v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
        # The dict-value twin of the arm above. Without it this function's
        # `dst != 'int64_t'` block had exactly ONE container arm, so the one
        # alias shape whose type lives in `_dict_val_types` rather than
        # `_elem_types` fell off the end of it: `e = d` inside a function
        # read `e[k]` through `mojo_dict_get_int` even with `d`'s value type
        # known (`f(d)` where every call site passes `{'x': '1'}` printed an
        # address, while the same call reading `d[k]` directly printed `1`).
        if dst == 'MojoDict *' and v in gen._dict_val_types:
            gen._dict_val_types[tname] = gen._dict_val_types[v]
            if v in gen._dict_nested_val_types:
                gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
        return
    if v in gen._actual_types:
        gen._actual_types[tname] = gen._actual_types[v]
    elif vtype.endswith(' *'):
        gen._actual_types[tname] = vtype
        if v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
        if v in gen._dict_val_types:
            gen._dict_val_types[tname] = gen._dict_val_types[v]
            if v in gen._dict_nested_val_types:
                gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
    elif vtype == 'char':
        gen._actual_types[tname] = 'char'
    # `e = d` where `d` is a BOXED dict parameter: `vtype` is `int64_t`
    # because the parameter is declared `int64_t`, so the
    # `vtype.endswith(' *')` arm above cannot fire — yet `_dict_val_types`
    # holding an entry for `v` is itself proof that `v` is a dict, which is
    # all this carry needs. Measured: with `f(d)`'s value type known from its
    # call sites, reading `d[k]` in `f` printed the string while the alias's
    # `e[k]` one line earlier printed the pointer's digits.
    if v in gen._dict_val_types:
        gen._dict_val_types[tname] = gen._dict_val_types[v]
        if v in gen._dict_nested_val_types:
            gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
    if v in gen._struct_field_owners:
        gen._struct_field_owners[tname] = list(gen._struct_field_owners[v])
    if tname in gen._actual_types:
        actual_type = gen._actual_types[tname]
        if actual_type == 'MojoList *' and v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
        elif actual_type == 'MojoDict *':
            if v in gen._elem_types:
                gen._elem_types[tname] = gen._elem_types[v]
                if v in gen._nested_elem_types:
                    gen._nested_elem_types[tname] = gen._nested_elem_types[v]
            if v in gen._dict_val_types:
                gen._dict_val_types[tname] = gen._dict_val_types[v]
                if v in gen._dict_nested_val_types:
                    gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]






def _emit_dynattr_setattr_dispatch(gen, member: str, vtype: str, v: str,
                                    ot: str, ov: str) -> None:
    """Emit a `_mojo_dispatch_setattr(obj, "member", val)` call — the
    same emission Sub-cases A/B/C already duplicate at each of their own
    write-side call sites (AssignStmt/AugAssignStmt/MultiAssignStmt), now
    shared here so the new except-as-bound-exception-object case (see
    `_is_except_as_member_target`) doesn't add a FOURTH copy of it."""
    if vtype == 'char *':
        # Record so a later read of this same attribute name (see
        # `self._except_attr_str_fields`'s own docstring) can cast the
        # generic boxed-int64_t dispatch result back to `char *`.
        gen._except_attr_str_fields.add(member)
    key_slit = gen._intern_string(gimple_ctypes._c_escape(member))
    key_tmp = gen._new_val('char *', f"{key_slit}")
    v64 = gen._new_temp('int64_t')
    gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
    obj64 = gen._to_int64(ot, ov)
    vp_tmp = gen._new_val('void *', f"(void *){obj64}")
    gen._emit_call('void', '', '_mojo_dispatch_setattr',
                    [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])


def _note_global_store_types(gen, tname: str, vtype: str, v: str,
                             value_node=None) -> None:
    """Carry a value stored into a module global's type knowledge forward to
    the global's NAME, so the read path can dispatch on the container it
    really holds.

    Both arms of "this assignment writes a globals-struct field" — the
    `global x` store inside a function body and the module-level store in
    `_toplevel()` — call this. They were two hand-maintained copies of the
    same three facts, and they had already drifted: the `_in_toplevel_gen`
    arm carried the `_actual_types` propagation and the `_func_declared_
    globals` arm did not, so a `global N = <list>` followed by a read of `N`
    in the same function read the boxed `int64_t` back with no kind at all.

    `_actual_types` is the whole point. Without it a boxed `MojoDict *` /
    `MojoList *` stored in a global loads back as a plain `int64_t` and the
    subscript dispatch falls through to the generic `MojoList *` cast path
    (BUG-2026-044). With it, `_lower_IdentExpr`'s global-read arm copies the
    name's entry onto the read-back temp, which is what lets the next line
    slice a list that the previous line made a list.

    The CALLABLE return-type tables are the fourth fact, and both arms need
    it for the same reason both arms need `_actual_types`: this function
    RETURNS right here, so without the carry every store to a
    `global`-declared name returns with all three tables still keyed on the
    RHS TEMP rather than on the global's name. A module-level
    `f = lambda: False` reached through either arm then printed `0` — the
    `_func_declared_globals` arm's copy of this was the one that existed
    first, and the `_in_toplevel_gen` arm is where an ordinary module-level
    `f = lambda: False` goes, so it is the one a real program hits. See
    `ginf.carry_callable_ret_types`.
    """
    if vtype == 'MojoDict *':
        if v in gen._dict_val_types:
            gen._dict_val_types[tname] = gen._dict_val_types[v]
            if v in gen._dict_nested_val_types:
                gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
    elif vtype == 'MojoList *':
        if v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
    if v in gen._actual_types:
        gen._actual_types[tname] = gen._actual_types[v]
    # …and the container KIND itself, which the two arms above do not cover
    # because they are about the value's ELEMENT / VALUE type and a `|` result
    # may have neither: `_dict_union_val_type` propagates only an AGREEMENT
    # between the two operands' dict-value types, so `e = {}; d = {'PATH':
    # '/a'}; m = e | d` merges a dict of strings with a dict of NOTHING and
    # records no value type at all. The kind needs no such agreement — the
    # RHS's own lowered type IS the answer — and without it the global reads
    # back with no kind whatsoever, so `print(m)` formatted the boxed
    # `MojoDict *` with `%s` and printed its address.
    #
    # `setdefault`, because an earlier pass's own conclusion for this name (a
    # parameter usage guess, say) is not something a store site may overturn.
    if vtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
        gen._actual_types.setdefault(tname, vtype)
    # The same carry, for the same reason, one table over: "this value is a
    # plain integer" (`gen._int_word_vals`) has to survive the store or a
    # module-level key is asked of the runtime's range-only discriminator,
    # which calls every positive int64 in [2^31, 2^47) a `char *` — so
    # `K = 3000000000` at module scope followed by `d[K] = 1` on the next
    # line was a `strcmp` of address 3000000000. Same `discard`-on-unknown
    # discipline as `_track_pointer_actual_type`, which is why `K = "s"` on
    # the next line still clears it rather than leaving a stale record.
    # See bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md.
    if v in gen._int_word_vals:
        gen._int_word_vals.add(tname)
    else:
        gen._int_word_vals.discard(tname)
    ginf.carry_callable_ret_types(gen, v, tname)
    ginf.carry_callable_ret_from_call(gen, value_node, tname)
    # A bound METHOD stored into a module global. The globals-struct FIELD is
    # `int64_t` (`_global_dst_ctype`), whatever the value's own type is, so the
    # call site's `_get_actual_type` has nothing to dispatch on, routes the
    # call to `mojo_fnptr_call_N`, and that helper calls the RAW method symbol
    # with no `self` — a call with the wrong arity, which happened to print
    # `1` for `f = m.truthy; print(f())` rather than crash. The identical
    # spelling bound to a LOCAL is right, because there the destination keeps
    # its `MojoBoundMethod *` type.
    #
    # The kind is known here and nowhere else: `_bound_method_ret_types` holds
    # a `MojoBoundMethod *` and nothing else, and the carry just above put
    # `tname` in it precisely when this value is one. So the presence of that
    # entry IS the answer, and it goes in the same `_actual_types` overlay the
    # local path already consults (see `_lower_call`'s
    # `_get_actual_type(_fname_var_ctype, fname_raw) ==
    # 'MojoBoundMethod *'` guard). Keyed on `tname`, not on `v`: the RHS temp
    # is a per-function name that recycles, and a stale entry on it is
    # exactly the bug class this table's own comment warns about. Harmless
    # when the field really is a `MojoBoundMethod *`, because `_get_actual_type`
    # only consults `_actual_types` for an `int64_t`-declared slot.
    if vtype == 'MojoBoundMethod *' and tname in gen._bound_method_ret_types:
        gen._actual_types[tname] = 'MojoBoundMethod *'
    # …and the WHOLE-PROGRAM half of the same fact. `carry_callable_ret_types`
    # writes the per-function tables, which are keyed by the lowered VALUE, and
    # this function RETURNS right here — so a store into a globals-struct field
    # loses them the same way. A call through `_root_globals.<name>` still
    # knows the NAME, which is what `_note_global_callable_store` is keyed on.
    ginf._note_global_callable_store(gen, tname, v)


def _gen_stmt_AssignStmt(gen, node):
    if isinstance(node.target, gimple_ctypes.IdentExpr) \
            and getattr(node, 'value', None) is not None:
        _record_bool_valued(gen, node.target.name, node.value)
    if (isinstance(node.target, gimple_ctypes.IdentExpr)
            and getattr(node, 'value', None) is not None
            and _try_bind_iter_cursor(gen, node.target.name, node.value)):
        return
    if (isinstance(node.target, gimple_ctypes.IdentExpr)
            and getattr(node, 'value', None) is not None
            and _maybe_narrow_genexp_local(gen, node.target.name, node.value)):
        return
    # Tuple unpacking: a, b, c = x, y, z  (targets may nest: (a,b),(c,d) = ...)
    # A list-pattern target (`[a] = ...`, `[a, b] = ...`) is the same
    # construct with the other Python spelling — identical `.elements`
    # shape — and is decomposed by the identical logic below.
    if isinstance(node.target, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr)):
        targets = node.target.elements
        # Extended unpacking: one target may be starred (`*row, last =
        # data` / `first, *rest = data` — real Python syntax, parses as
        # UnaryOp(op='*', operand=<real target>) inside `elements`, see
        # fire_compiler.py). The starred target collects whatever's
        # left over after the non-starred targets on either side have
        # each claimed one element — mirrors the interpreter's
        # identical before/star/after split in myinterpreter.py's
        # _assign_target. Scoped to a MojoList*-typed RHS (the
        # realistic real-world shape, e.g. Tools/c-analyzer's
        # `*row, declaration = _render_known_row(decl)`); a starred
        # target against a literal tuple RHS is rare enough in real
        # source to leave unhandled here (falls through unchanged,
        # same honest-if-unsupported posture as before this fix for
        # that narrower shape).
        _star_idx = None
        for _si, _t in enumerate(targets):
            if isinstance(_t, gimple_ctypes.UnaryOp) and _t.op == '*':
                _star_idx = _si
                break
        if _star_idx is not None:
            vtype, v = gen.lower_expr(node.value)
            # DESIGN.html R1/R5: shares _materialize_as_list with all()/
            # any()/enumerate()/*.join() - `*a, b = some_dict` is real
            # Python (unpacks the dict's keys).
            lp = gen._materialize_as_list(vtype, v)
            before, after = targets[:_star_idx], targets[_star_idx + 1:]
            star_target = targets[_star_idx].operand
            n_before, n_after = len(before), len(after)
            elem_type = gen._elem_of(lp)
            suf = gimple_ctypes.TypeLattice.list_suffix(elem_type)
            set_et = elem_type if elem_type != 'unknown' else 'int64_t'
            for i, tgt in enumerate(before):
                idx64 = gen._new_val('int64_t', f"(int64_t){i}")
                sev = gen._new_val(set_et, f"mojo_list_get_{suf} ({lp}, {idx64})")
                gen._assign_target(tgt, set_et, sev)
            total = gen._new_val('int64_t', f"mojo_list_len ({lp})")
            star_start = gen._new_val('int64_t', f"(int64_t){n_before}")
            # GIMPLE (-fgimple) requires both operands of a binary expr to
            # have the identical type, so each literal operand must go
            # through its own int64_t temp — a bare C `int` literal next to
            # an int64_t SSA name is a hard gcc verifier error ("type
            # mismatch in binary expression"), not a warning.
            n_after64 = gen._new_val('int64_t', f"(int64_t){n_after}")
            star_stop = gen._new_val('int64_t', f"{total} - {n_after64}")
            star_v = gen._new_val('MojoList *', f"mojo_list_slice ({lp}, {star_start}, {star_stop})")
            gen._elem_types[star_v] = elem_type
            gen._assign_target(star_target, 'MojoList *', star_v)
            for j, tgt in enumerate(after):
                j64 = gen._new_val('int64_t', f"(int64_t){j}")
                idx64 = gen._new_val('int64_t', f"{star_stop} + {j64}")
                sev = gen._new_val(set_et, f"mojo_list_get_{suf} ({lp}, {idx64})")
                gen._assign_target(tgt, set_et, sev)
            return
        if isinstance(node.value, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr)) \
                and len(node.value.elements) == len(targets):
            # RHS is a tuple/list literal — lower and assign each element individually
            for tgt, rhs_expr in zip(targets, node.value.elements):
                et, ev = gen.lower_expr(rhs_expr)
                gen._assign_target(tgt, et, ev)
        else:
            # RHS is a single iterable — lower it, then index each element
            vtype, v = gen.lower_expr(node.value)
            # A TAGGED nested generator tuple (`args` from
            # `for what, args in scan_opcodes(co):`, see
            # `_emit_generator_tuple_unpack`'s nested-slot path): destructure
            # each element as a DYNAMIC local reading the tagged box (the
            # layout is [tag0,word0,tag1,word1,...]), never a raw
            # `mojo_list_get_int` at the slot position.
            if v in getattr(gen, '_tagged_gen_tuple_locals', ()):
                for i, tgt in enumerate(targets):
                    # For a plain NAME target, the runtime TAG is the only
                    # reliable source of its type: static inference is wrong
                    # for Lib/modulefinder's slot 0 (`name`/`fromlist`/`level`
                    # are str/list/int across sites), and even `--dump` and
                    # the linked build disagree on what `_infer_local_var_types`
                    # guesses (int64_t vs MojoList *). Bind every name target
                    # as a DYNAMIC local whose reads dispatch on the tag; a
                    # real int/str/list target all work through the same path.
                    if isinstance(tgt, gimple_ctypes.IdentExpr):
                        gen._tagged_dyn_src[tgt.name] = (v, i)
                        # `force=True` when a prior inference already declared
                        # the name with a pointer type (the linked build seeds
                        # `nm` as `MojoList *` from _infer_local_var_types):
                        # a dynamic local MUST be int64_t storage, and
                        # _declare_var's default first-decl-wins guard would
                        # otherwise keep the stale pointer decl and the
                        # tagged read assignment fails to compile.
                        if tgt.name not in gen.var_types:
                            gen._declare_var(tgt.name, 'int64_t')
                        elif gen.var_types.get(tgt.name) != 'int64_t':
                            gen._declare_var(tgt.name, 'int64_t', force=True)
                        continue
                    # A nested-tuple / subscript target: best-effort int read
                    # (no static type channel); real consumers of these bind
                    # a further dynamic local on the next unpack.
                    gen._assign_target(
                        tgt, 'int64_t',
                        gen._new_val('int64_t', f'mojo_tagged_int ((int64_t){v}, {i})'))
                return
            for i, tgt in enumerate(targets):
                # _tuple_elem_value resolves an int64_t-boxed tuple handle
                # (a call result — the codegen's own `-> tuple[str, str]`
                # annotated methods return these) to its real MojoList*
                # element type, so char* tuples unpack via get_str instead
                # of reading pointers as int64_t decimals.
                et, ev = gen._tuple_elem_value(vtype, v, i)
                gen._assign_target(tgt, et, ev)
        return
    vtype, v = gen.lower_expr(node.value)
    if isinstance(node.target, gimple_ctypes.IdentExpr):
        tname = node.target.name
        # Rebinding a genexp-materialised local to a non-genexp value (the
        # RHS was just lowered above, still seeing the list-typed window)
        # ends that window — later reads use the slot's own declared type.
        if tname in gen._genexp_list_locals and not _is_genexp(node.value):
            gen._genexp_list_locals.pop(tname, None)
        _dv = gen._annotation_dict_val_type(getattr(node, 'type_ann', None))
        if _dv is not None:
            gen._dict_val_types[tname] = _dv
        folded = gen._try_const_fold_str(node.value)
        if folded is not None:
            gen._const_str_locals[_pair_key(gen.current_func_name, tname)] = folded
        # Write to module struct when `global x` was declared in this function.
        # Always target THIS module's own struct (self._current_module_ctx),
        # never `_global_to_module.get(tname)` — that map is a SHARED,
        # whole-tree, "first module to claim this bare name wins" map, so
        # it can misdirect the write to a DIFFERENT module that happens to
        # declare its own same-named global (see the `_in_toplevel_gen`
        # branch right below, already fixed this exact way, and
        # _write_dest's identical fix — bugs/hard/CODEGEN_module_globals_
        # cross_contamination_via_imported_stmts.md's write-side addendum).
        # A `global tname` statement unambiguously means THIS function's
        # own enclosing module's global under real Python scoping.
        # A bare-name write whose name is THIS module's own global and that
        # no local/param shadows routes to the globals struct too — same
        # interpreter-parity fix as _write_dest's (BUG-2026-018): the read
        # half of `_passed + 1` already resolved to the module global while
        # this write used to create a dead local, so check()/assert_* in
        # test_framework.mojo silently lost every increment under --jit.
        # Ownership guard mirrors the IdentExpr read path exactly
        # (_global_to_module is None or ours), so this can never redirect a
        # genuine local into some OTHER inlined module's same-named global.
        if (((tname in gen._func_declared_globals
                or (tname not in gen.var_types
                    and getattr(gen, '_global_to_module', {}).get(tname) in (
                        None, (gen.module_name if len(gen.module_name) > 0 else "root")))))
                and tname in gen._global_var_types):
            safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
            field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(tname)}"
            # The struct field's REAL declared C type can differ from the
            # semantic _global_var_types entry (e.g. a MojoDict* global not
            # in _dispatch_names is boxed as `int64_t` at the C level, see
            # the global-scan's DictExpr/ListExpr/SetExpr cases) — coerce to
            # that actual declared type, not the semantic one, or GIMPLE
            # rejects the direct pointer/int64_t mismatch. `_global_dst_
            # ctype` additionally trusts THIS module's own Phase 1.7 scalar
            # conclusion over the whole-program-shared dicts, which a
            # later-scanned same-bare-name global may have overwritten.
            gtype = gen._global_dst_ctype(tname)
            gen._safe_coerce_emit(vtype, gtype, v, field_ref)
            # Propagate dict/list/set value-type tracking for global variables.
            # Without this, _dict_val_types[name] is never set for globals,
            # and d["key"] on a global dict falls back to mojo_dict_get_int
            # instead of mojo_dict_get_str — see BUG-2026-043.
            _note_global_store_types(gen, tname, vtype, v, node.value)
            return
        # Genuine module-scope statement (we're generating THIS module's own
        # _toplevel()/_{module}_toplevel() body — see _in_toplevel_gen) whose
        # target is a tracked global: actually execute the initializer and
        # store it into this module's globals struct field, rather than the
        # previous behavior of silently skipping the assignment altogether
        # ("module globals are initialized in struct definition, not in
        # _toplevel" — true only for simple literals; a computed initializer
        # like `CAS_DIR = os.path.join(GMOJO_HOME, 'cas')` in cas.py was never
        # actually run, leaving the field permanently zero). Always target
        # self._current_module_ctx (this module), not
        # _global_to_module.get(tname) — that map is name-keyed only and
        # "first module wins" when two different inlined files declare a
        # same-named global (e.g. every file's own `HERE = os.path.dirname(...)`),
        # so trusting it here could redirect this module's own write into a
        # different module's struct.
        #
        # current_func_name is NOT a usable signal for "are we at module
        # scope" here — _gen_toplevel sets it to '_toplevel'/'_{module}_toplevel'
        # so it's non-empty even for genuine top-level statements. Use the
        # dedicated _in_toplevel_gen flag instead. Inside a *real* Python
        # function body (_in_toplevel_gen is False there), Python scoping
        # makes an assignment without `global` a fresh local no matter what
        # name it uses — even if do_imports=True's flat, unnamespaced
        # _global_var_types happens to contain the same name from a
        # completely different inlined file's module scope (e.g. this
        # function's local `src` vs. another inlined file's module-level
        # `src`) — so that case still falls through to the regular local
        # path below, and must not be redirected to any global struct.
        if gen._in_toplevel_gen and tname in gen._global_var_types:
            safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
            field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(tname)}"
            # See the _func_declared_globals branch above: coerce to the
            # struct field's real declared C type, not the semantic one.
            gtype = gen._global_dst_ctype(tname)
            gen._safe_coerce_emit(vtype, gtype, v, field_ref)
            # Same tracking as the `_func_declared_globals` branch above —
            # one helper for both, because they are two arms of the same
            # decision (a store into this module's globals struct) and the
            # `_func_declared_globals` arm was missing the `_actual_types`
            # half that this one had. The callable return-type tables are in
            # there too, for the reason the helper's own docstring gives.
            _note_global_store_types(gen, tname, vtype, v, node.value)
            return
        # Regular local variable assignment
        if tname not in gen.var_types:
            # A name bound to more than one distinct container kind has no
            # container pointer type at all, so it is declared as the box and
            # every store coerces into it — BEFORE any of the ground-truth
            # rules below, which would otherwise pick the first value's kind
            # and leave the second store to hit `_sce_simple_emit`'s
            # container-kind chokepoint as a hard "cannot coerce" build
            # failure. This is the container half of the rule
            # `_prebound_local_ctypes` states for structs (a name is recorded
            # only while every pointer-shaped binding of it agrees; a
            # disagreement disqualifies it and the box is the answer), and it
            # has to come first because every rule below is a "trust this one
            # value" rule, which is exactly what a mixed name must not be
            # trusted for. Real: `gen_module_impl`'s `_lens` is a dict at
            # line 1257 and a set at line 6114, and the self-host closure
            # could not be generated until this existed.
            _mixed = tname in ginf.mixed_container_locals(gen)
            if _mixed:
                ctype = 'int64_t'
            else:
                # Check for inferred variable type (from analysis of all assignments)
                func_key = gen.current_func_name
                if func_key and hasattr(gen, '_inferred_var_types'):
                    if func_key in gen._inferred_var_types and tname in gen._inferred_var_types[func_key]:
                        ctype = gen._inferred_var_types[func_key][tname]
                    else:
                        ctype = vtype
                else:
                    ctype = vtype
            # The pre-pass cannot always see a nested subscript's element type
            # (it runs before the cross-call element contract), so it can hint
            # an integer for what is really a double read. A local assigned a
            # double value is a double — don't silently truncate it.
            if ctype in ('int', 'int64_t') and vtype == 'double':
                ctype = 'double'
            # Every "trust ground truth" rule below reads the pre-pass's
            # `int`/`int64_t` hint as a STALE SCALAR that the freshly-lowered
            # value refines, and pins the slot to this value's kind. That
            # reading is wrong for a name the pre-pass found bound to
            # containers/structs of MORE THAN ONE kind: there its `int64_t`
            # is not a stale scalar but the honest join of conflicting
            # containers, this assignment site is only the FIRST of several,
            # and pinning to its kind makes every later branch's store a
            # container-kind coercion `_sce_simple_emit` refuses.
            # `gen._multi_kind_locals` (filled by `_infer_local_var_types`) is
            # the one place that distinguishes the two meanings of that
            # `int64_t`. Real: `Tools/build/umarshal.py`'s `r_object`, whose
            # `retval` is a list, a dict, a set, a frozenset and a `Code` on
            # five different branches.
            #
            # One gate for all of them rather than a check per rule: they are
            # three steps of one decision, and an earlier attempt guarded only
            # the container one and was immediately undone by the
            # generalized-pointer one right below it.
            #
            # It gates on BOTH halves of the box name, and the `_mixed` half
            # is the one that was MISSING — so the box installed four lines
            # above was installed and then immediately undid by this group,
            # and the second store of a rebound name reached
            # `_sce_simple_emit`'s container-kind chokepoint exactly as if
            # neither rule existed. `multi_kind_locals` alone is not enough
            # because it is a DIFFERENT predicate that does not always name
            # the same names: it is the PRE-PASS's `_multi_kind_locals`
            # verdict (`_infer_local_var_types` is handed bare `FunctionDef`s
            # and records its answer under every spelling it can derive),
            # while `_mixed` is THIS function's own walk of `_cur_func_body`.
            # A name bound to two container kinds inside a LIFTED CLOSURE is
            # found by the latter and missed by the former — measured, both
            # consulted for one closure in the same run, `_mixed` naming the
            # local and `multi_kind_locals` answering empty.
            #
            # The two are still not merged as PREDICATES, and this is not
            # widening the box: a `_mixed` name is already boxed above, so
            # adding it here changes nothing about WHICH names are boxed and
            # only stops this group from taking one back out. (Widening
            # `multi_kind_locals` into `_mixed` is the thing that would box
            # names on evidence `_mixed` never had; that remains undone, and
            # it is why `multi_kind_locals` — not `_mixed` — is what decides
            # the box for a name only the pre-pass found.)
            #
            # Real, and the shape of `argparse`'s
            # `_parse_known_args.consume_optional`: `args` is a dict literal in
            # one arm and a list in two others, so the whole module is
            # dropped from an ordinary stdlib closure with `cannot coerce
            # MojoList * to MojoDict * (incompatible container kinds) ...
            # value='_tN' dest='args'`. See
            # bugs/INTERFACE_REQUEST_1_to_middle_infra_infer.md.
            _pin_to_ground_truth = (tname not in ginf.multi_kind_locals(gen)
                                    and not _mixed)
            # 'int' (bare) is the hallucination marker — no real answer. If the
            # value is actually a container pointer (e.g. a dict read whose value
            # type is a dict/list/set), trust ground truth so a later
            # .get()/subscript dispatches on the right container.
            if _pin_to_ground_truth and ctype == 'int' and vtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                ctype = vtype
            # Same rule, one step further: the pre-pass hint is a POINTER
            # that disagrees with a container value. `int` is the
            # hallucination marker, but `char *` becomes one by the same
            # route whenever a subscript-of-a-slice makes the pre-pass read
            # the name as string-shaped, so the "int only" form of the rule
            # above let it win. A `MojoList *` / `MojoDict *` / `MojoSet *`
            # VALUE is ground truth about which container this is, and a
            # string hint cannot express that; the disagreement is the
            # pre-pass being wrong, not a refinement. Real: `ids =
            # VOCAB.encode(CORPUS)[:5]` declared `char * ids` for a list of
            # ints, so `ids[1:]` lowered to `mojo_cstr_slice` and `ids[1]`
            # to `_mojo_at_char` dereferenced as a `char` — the
            # int+list concat on the next line became `char * + MojoList *`
            # and gimple died with "internal compiler error: in build2".
            #
            # A multi-kind name is excluded from it deliberately, by the ONE
            # gate declared above rather than by `_mixed`: every rule in this
            # group is "trust THIS value", which is the one thing a name
            # holding two container kinds cannot be trusted for, and letting it
            # through here would undo the box.
            #
            # The two predicates are NOT the same predicate and are not merged
            # here, because they answer from different evidence and each has
            # its own real repro: `_mixed` is this function's own walk of
            # `_cur_func_body` (a container kind disagreement, and it is what
            # decides the box), while `_pin_to_ground_truth` is the PRE-PASS's
            # `_infer_local_var_types` verdict, which also covers known struct
            # pointers and which `resolve_shared` records under every spelling
            # of the function's name. Widening one into the other would box
            # names on evidence the other never had; the gate above is the one
            # that must win, because it is the one whose false positives the
            # `len(set(...))` fix in `_infer_local_var_types` removed.
            if _pin_to_ground_truth and vtype in ('MojoDict *', 'MojoList *', 'MojoSet *') \
                    and ctype != vtype:
                ctype = vtype
            # Same "trust ground truth" principle, generalized to ANY pointer
            # type (not just Mojo containers) — this pre-pass hint
            # (_inferred_var_types, Pass 1.3b) runs BEFORE Pass 1.3d's
            # cross-call parameter-type propagation corrects an unannotated
            # callee's real return type, so a local assigned straight from
            # such a call (`y = g("a", "b")` where g's inferred return type
            # only became char* once Pass 1.3d saw g's string call sites) can
            # still carry a stale int64_t/int hint here even though the
            # actual value just lowered is a real pointer. Declaring `y` as
            # int64_t against that pointer value would truncate/reinterpret
            # it as an integer at the coercion below. See
            # CODEGEN_untyped_param_string_passthrough_wrong.
            if _pin_to_ground_truth and ctype in ('int', 'int64_t') \
                    and vtype not in ('int', 'int64_t') and vtype.endswith('*'):
                ctype = vtype
            # `s: Set[Int] = {}` — an ANNOTATED assignment declares a
            # container kind, and an empty `{}` is a dict DISPLAY: evidence
            # for the dict and nothing else. Without this the annotation is
            # honoured for the element/value type (the `_dv` / `List[T]`
            # blocks below) but not for the container KIND itself, so `s`
            # was declared and stack-allocated as a `MojoDict`, `s.add(i)`
            # became a no-op against a dict header, `i in s` was False and
            # `len(s)` was 0 — silently, exit 0. Same premise as the
            # VarDecl path (which resolves `node.type_ann` outright) and as
            # `reify_empty_container_literal` just below: the declared kind
            # wins, because the literal is empty.
            _ann_ctype = ginf.ann_container_ctype(gen,
                                                  getattr(node, 'type_ann', None))
            if _ann_ctype is not None:
                ctype = _ann_ctype
            gen._declare_var(tname, ctype)
            # BUG-2026-023 residual (box.3d/game FileSystem.current_dir_path):
            # the rewriter turns `parts: List[String] = ...` into an
            # AssignStmt carrying type_ann (this file's VarDecl handler never
            # sees body declarations). Seed the list ELEMENT type from that
            # annotation so insert()/index-stores + later subscript reads
            # dispatch on the real element instead of int64_t handles.
            _ann_as = getattr(node, 'type_ann', None)
            _et = _annotation_container_elem_type(gen, _ann_as, ctype)
            if _et:
                gen._elem_types[tname] = _et
        # A heap-boxed mutable capture: _write_dest returns `*name` (the
        # deref, pointee-typed lvalue), so the coercion target must be
        # the POINTEE ctype, not the box pointer ctype — otherwise the
        # value gets pointer-cast and assigned into a non-pointer lvalue
        # (test_locks.mojo's `_ = time_function(...)`).
        if tname in gen._boxed_mut_locals:
            dst = gen._boxed_mut_locals[tname]
        else:
            dst = gen.var_types[tname]

        # `var x: Set[String] = {}` (or List/Dict-declared-elsewhere):
        # `{}`'s syntax can't express "empty set", so it always lowers to
        # mojo_dict_new() — construct the variable's real declared kind
        # instead of coercing/casting the wrong one. See
        # gimple_ctypes.reify_empty_container_literal's own docstring
        # (DESIGN.html R1: shared with the MemberExpr field-write branch
        # below and _lower_dict_method's `.get(k, default)`).
        _reified = gimple_ctypes.reify_empty_container_literal(gen, vtype, dst, node.value)
        if _reified is not None:
            vtype, v = dst, _reified

        if dst in ('MojoList *', 'MojoSet *') and v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
            # Also propagate nested element types (for lists of lists)
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
            # And per-slot tuple element types (for lists of heterogeneous
            # tuples, e.g. `to_check = [(all_missing, "missing", msg), ...]`
            # — _lower_list_literal already computes and records this on
            # the RHS temp `v` (see its own `_tuple_slot_types[t] =
            # _tuple_slot_types[ev]` propagation from each tuple element
            # into the list literal temp), but that record was never
            # carried from the temp onto the assigned variable name here,
            # so a later `for name_list, what, message in to_check:`
            # (_gen_for_list) found no entry for `to_check` and fell back
            # to the joined `_nested_elem_types` pair type (int64_t),
            # declaring the list[str] slot `name_list` as a plain
            # int64_t. The inner `for name in name_list:` then dispatched
            # on that stale int64_t type as a STRING iteration
            # (mojo_strlen/_mojo_at_char on an int64_t list pointer) —
            # "makes pointer from integer without a cast". See
            # COMPILE_FAIL_Tools_check-c-api-docs_main.
            if v in gen._tuple_slot_types:
                gen._tuple_slot_types[tname] = gen._tuple_slot_types[v]
        if dst == 'MojoDict *':
            if v in gen._elem_types:
                gen._elem_types[tname] = gen._elem_types[v]
                if v in gen._nested_elem_types:
                    gen._nested_elem_types[tname] = gen._nested_elem_types[v]
            if v in gen._dict_val_types:
                gen._dict_val_types[tname] = gen._dict_val_types[v]
                if v in gen._dict_nested_val_types:
                    gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
        # `f = self.b` (a bound-method value, see _lower_bound_method_value):
        # carry the method's real return type along with the variable so a
        # later `f()` (_lower_bound_method_call) narrows the result
        # correctly instead of assuming int64_t. The same carry for every
        # OTHER callable kind is the shared one just below — one definition,
        # because three hand-written copies of it is how the two module-global
        # store branches came to omit all of it.
        ginf.carry_callable_ret_types(gen, v, tname)
        ginf.carry_callable_ret_from_call(gen, getattr(node, 'value', None), tname)
        # A `MojoBoundMethod *` value stored into a local whose declared C
        # type is NOT `MojoBoundMethod *` — the var-type-inference join
        # with another branch's plain fn-pointer / lambda value collapsed
        # the slot to `void *`/`int64_t` (`if c: f = lambda: 42 else: f =
        # self.tell; f()`). The call site can't tell statically which kind
        # of callable is live, so record the name for dynamic dispatch
        # (mojo_maybe_bound_call_N) — see _lower_maybe_bound_call. Its return
        # type rides along on the shared carry immediately above, which covers
        # the `_Bool` a `lambda: 42`-vs-`self.tell` join would otherwise
        # narrow to `int64_t`.
        if vtype == 'MojoBoundMethod *' and dst != 'MojoBoundMethod *':
            gen._bm_tainted_locals.add(tname)
        # `append = l.append` (a builtin-container method bound as a
        # value, see _lower_builtin_method_value): carry the recorded
        # (receiver, method) binding from the RHS temp onto the variable,
        # mirroring the _bound_method_ret_types propagation just above —
        # a later `append(...)` call dispatches on the VARIABLE's name.
        if v in gen._builtin_method_values:
            gen._builtin_method_values[tname] = gen._builtin_method_values[v]
        # `g = counter(3)` / `g = obj.countdown(n)`: the generator-call
        # lowering above recorded which extern "C" resume/value/destroy
        # API this coroutine uses, keyed by the CALL SITE's own SSA temp
        # (see self._generator_var_api's docstring) — that key goes out
        # of scope the moment the value is assigned to a real local, so
        # propagate it onto the assigned variable's own name too,
        # mirroring the exact same "carry the side-table entry across an
        # assignment" pattern used above for MojoList*/MojoDict*/
        # MojoBoundMethod* (_elem_types/_dict_val_types/_bound_method_
        # ret_types). Without this, `for x in g:` / `next(g)` anywhere
        # after this assignment finds no entry for `g` and falls back to
        # the honest "no known API" refusal — see bugs/CODEGEN_compiled_
        # generator_not_first_class_value.md.
        if dst == 'MojoGenerator *' and v in gen._generator_var_api:
            gen._generator_var_api[tname] = gen._generator_var_api[v]
        # Step I: `var task = create_task(f())` -- mirrors the
        # MojoGenerator* carry-through immediately above exactly (see
        # self._async_var_api's own docstring for the identical "value
        # -> api" side-table rationale, just for `MojoAsync *` instead
        # of `MojoGenerator *`).
        if dst == 'MojoAsync *' and v in gen._async_var_api:
            gen._async_var_api[tname] = gen._async_var_api[v]
        # The per-slot-KIND side tables, carried from the RHS temp onto the
        # assigned name — the exact mirror of the three same-shaped blocks in
        # this file's VarDecl path (see the `var m = struct.unpack('<if', b)`
        # / `var s = struct.Struct('<if')` comments there), and for the same
        # reason. All three are keyed by the NAME a value is read under, and
        # that name is the RHS temp only until this assignment replaces it:
        #
        #   b = [1, 2.5]     ->  b[0] read 5e-324 (the int slot's bits as a
        #   for x in b          denormal double) and `for x in b` printed
        #                         5e-324 / 2.5, exit 0 — while the `var b =
        #                         [1, 2.5]` spelling of the very same value was
        #                         exactly right, because the VarDecl path
        #                         already carried the marker across.
        #   t = struct.unpack('<if', buf)  ->  same, for the same reason.
        #   s = struct.Struct('<if')       ->  `s.unpack(buf)` found no format
        #                         on `s`, so the per-slot kinds the format
        #                         names were never recovered for the unpack.
        #
        # `_maybe_kinds_vals` is the load-bearing one: a heterogeneous
        # container's tracked element type is its PROMOTED one ('double' for
        # `[1, 2.5]`), which is exactly the answer that is wrong for its int
        # slot, and this marker is what routes the read to the runtime's own
        # per-slot record instead (see the `_maybe_kinds_vals` check in
        # `_lower_Subscript`'s list branch and in `_gen_for_list`).
        #
        # Same `type_ann is None` guard as the VarDecl path: an ANNOTATED
        # local is declared as some other container on purpose, so the
        # initializer's own side tables describe a value it is not.
        if getattr(node, 'type_ann', None) is None:
            if v in gen._struct_slot_kinds:
                gen._struct_slot_kinds[tname] = gen._struct_slot_kinds[v]
            if v in gen._maybe_kinds_vals:
                gen._maybe_kinds_vals.add(tname)
            if v in gen._struct_formats:
                gen._struct_formats[tname] = gen._struct_formats[v]
        gen._track_pointer_actual_type(tname, dst, v, vtype)
        gen._safe_coerce_emit(vtype, dst, v, gen._write_dest(tname))
    elif isinstance(node.target, gimple_ctypes.MemberExpr):
        # `sys.argv = [...]` — a whole-list rebind. Reads lower to
        # mojo_get_argv() (see _lower_MemberExpr's sys/argv case), so the
        # write needs the matching runtime store or it is silently
        # dropped: fire.py's own CLI strips its `--dump`/`--dump-full`
        # flags exactly this way before `input_file = sys.argv[1]`, and
        # without this the compiled binary kept the unstripped argv and
        # used the FLAG as the input filename (bootstrap stage 2/3 wrote
        # `--dump.ci` instead of `<basename>.ci` for every file).
        if (isinstance(node.target.obj, gimple_ctypes.IdentExpr)
                and node.target.obj.name == 'sys'
                and node.target.member == 'argv'):
            _av = v if vtype == 'MojoList *' else gen._coerce_to_type(
                vtype, 'MojoList *', v)
            gen._emit_call('void', '', 'mojo_replace_argv',
                            [('MojoList *', _av)])
            return
        # `f.attr = value` where `f` is a free function memoizing a
        # value on itself -- see the `_func_attrs` pre-scan's docstring
        # (gen_module, Phase 1) and `_lower_MemberExpr`'s matching read-
        # side branch. Checked BEFORE `self.lower_expr(node.target.obj)`
        # below: lowering a bare function-name identifier boxes it as a
        # `void *` (a function can't be a bare rvalue under -fgimple),
        # and this branch's normal struct-field-write path would then
        # try to write through that `void *` as if it pointed at a real
        # struct instance -- invalid, since a function has no fields
        # (confirmed regression: jit/arm64.py's `_toolchain_id._cached =
        # cached` / `_compiler_id._cached = cached`, GCC "request for
        # member '_cached' in something not a structure or union").
        _fattrs_w = gen._func_attrs
        if (_fattrs_w and isinstance(node.target.obj, gimple_ctypes.IdentExpr)
                and node.target.obj.name in _fattrs_w
                and node.target.member in _fattrs_w[node.target.obj.name]):
            mangled = _fattrs_w[node.target.obj.name][node.target.member]
            gtype = gen._global_var_types.get(mangled, 'int64_t')
            gen._safe_coerce_emit(vtype, gtype, v, mangled)
            return
        _cattr_w = gmp._resolve_class_attr_write_target(gen, node.target)
        if _cattr_w is not None:
            gtype, gname = _cattr_w
            gen._safe_coerce_emit(vtype, gtype, v, gname)
            return
        _dv = gen._annotation_dict_val_type(getattr(node, 'type_ann', None))
        if _dv is not None:
            gen._dict_val_types[node.target.member] = _dv
        ot, ov = gen.lower_expr(node.target.obj)
        if _dv is not None:
            # _dict_val_types is reset per function (_reset_func), so the
            # annotation-seeded value type must ALSO live in the shared
            # per-struct-field table for reads in OTHER functions to see
            # it (the _lower_MemberExpr field-read propagates it onto the
            # read temp). Keyed by the struct owning the field.
            _dsn = gimple_exprtypes._struct_name_of(ot)
            gen._field_dict_val_types.setdefault(_dsn, {})[node.target.member] = _dv
        elif v in gen._dict_val_types:
            # `self.d = d` where the RIGHT-HAND SIDE's dict value type is
            # already known — a dictionary literal passed straight to the
            # constructor, or a parameter the cross-call contract resolved.
            # Same carry as the annotation arm above, same table, same reader:
            # without it the field is left untyped, so `self.d[k]` in every
            # OTHER method reads the slot through `mojo_dict_get_int` and
            # hands back the stored `char *`'s own bits. Gated on `v` already
            # being a recorded dict, which is itself proof the value is one.
            _dsn2 = gimple_exprtypes._struct_name_of(ot)
            if _dsn2:
                gen._field_dict_val_types.setdefault(_dsn2, {})[node.target.member] = gen._dict_val_types[v]
        if ot in ('int', 'int64_t', 'void *'):
            # Opaque Python object (e.g. `s.field = val` where `s`'s
            # static type isn't narrowed past a runtime isinstance()
            # check — this compiler doesn't track that): dispatch via
            # _mojo_dispatch_setattr, which reads the runtime type tag
            # and routes to the right struct's real setter. Calling the
            # bare mojo_setattr() runtime stub directly (the previous
            # behavior) silently did nothing at all — it's an
            # intentional no-op fallback for values with NO type tag,
            # not a real implementation; found via
            # `s._fieldwise_ctor_synthesized = True` in
            # _synthesize_fieldwise_inits (fire_compiler.py) never taking
            # effect once compiled.
            member_str = node.target.member
            key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
            key_tmp = gen._new_val('char *', f"{key_slit}")
            v64 = gen._new_temp('int64_t')
            gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
            obj64 = gen._to_int64(ot, ov)
            vp_tmp = gen._new_val('void *', f"(void *){obj64}")
            gen._emit_call('void', '', '_mojo_dispatch_setattr',
                            [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
        elif (gimple_exprtypes._struct_name_of(ot) in gimple_ctypes._FIXED_RUNTIME_STRUCT_NAMES
              and node.target.member not in gen.struct_field_types.get(gimple_exprtypes._struct_name_of(ot), {})):
            # Step 4 (bugs/hard/CODEGEN_dynamic_attribute_on_generic_
            # object.md): `ot` is one of this codegen's own fixed-layout
            # runtime structs (MojoBoundMethod, ...) and `node.target.
            # member` isn't one of its real, hardcoded C fields — the
            # direct-field-write path just below would blindly emit
            # `ov->member = val`, which GCC rejects for a struct with no
            # such member. Route through the same dynamic-attribute
            # dispatch the fully-opaque branch above uses (real
            # per-object storage via mojo_setattr), mirroring that
            # branch's own emission exactly. Confirmed real instance:
            # `inner.__name__ = 'read_nonlocal'` / `__del__._slotted =
            # True` on a `MojoBoundMethod` value.
            member_str = node.target.member
            key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
            key_tmp = gen._new_val('char *', f"{key_slit}")
            v64 = gen._new_temp('int64_t')
            gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
            obj64 = gen._to_int64(ot, ov)
            vp_tmp = gen._new_val('void *', f"(void *){obj64}")
            gen._emit_call('void', '', '_mojo_dispatch_setattr',
                            [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
        elif gen._is_except_as_member_target(node.target.obj):
            # A caught exception object (`except OSError as err: ...
            # err.filename = ...`) — `ot` is a bare `char *` (this
            # runtime models an exception's payload as a plain message
            # string, not a real struct/object), so it's neither Sub-case
            # A/B above nor Sub-case C's fixed-runtime-struct set. Routed
            # here SYNTACTICALLY (`node.target.obj` is a name introduced
            # by an `except ... as name:` clause — see
            # `_is_except_as_member_target`/`self._except_as_names`), not
            # by broadening the `ot in (...)` check above to include
            # `char *` in general, which would also match every ordinary
            # string variable in this codegen. Confirmed real instance:
            # Lib/pathlib/_os.py's `err.filename = source_f.name`. See
            # “setting/getting an arbitrary attribute on a generically-typed object”'s
            # "Residual gap: caught exception objects" section.
            gen._emit_dynattr_setattr_dispatch(node.target.member, vtype, v, ot, ov)
        else:
            op = '->' if '*' in ot else '.'
            struct_name = gimple_exprtypes._struct_name_of(ot)
            known_fields = gen.struct_field_types.get(struct_name, {})
            _is_user_struct = struct_name in gen.struct_field_types
            if (( _is_user_struct and node.target.member not in known_fields)
                    or (not _is_user_struct and '*' in ot)):
                # A member write on a receiver whose DECLARED type has no
                # such field — either a KNOWN user struct genuinely
                # lacking the member, or a container/opaque pointer type
                # (MojoList *, MojoDict *, ...) that is not a user struct
                # at all. The old unconditional `ov->member = val`
                # emission was a hard GCC error ("'X' has no member named
                # 'Y'") whenever the declaration lost a cross-branch type
                # unification — real: Tools/build/umarshal.py's
                # `_r_object`, whose single `retval` local is declared
                # from the FIRST branch's list shape (`MojoList *`) but
                # is written with 16 `co_*` Code fields in the Type.CODE
                # branch (where it really does hold a tagged `Code`
                # instance at runtime). Route through the same
                # dynamic-attribute dispatch the fully-opaque branch
                # above uses: `_mojo_dispatch_setattr` reads the object's
                # RUNTIME type tag, so when this path executes with a
                # receiver whose actual type does have the field (Code
                # here), the write lands correctly; on any other runtime
                # type it degrades to per-object dynamic storage / no-op
                # exactly like Python-level attribute assignment on an
                # arbitrary object would.
                member_str = node.target.member
                key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
                key_tmp = gen._new_val('char *', f"{key_slit}")
                v64 = gen._new_temp('int64_t')
                gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
                obj64 = gen._to_int64(ot, ov)
                vp_tmp = gen._new_val('void *', f"(void *){obj64}")
                gen._emit_call('void', '', '_mojo_dispatch_setattr',
                                [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
                return
            field_type = known_fields.get(node.target.member, vtype)
            # `self.x = {}` where `x`'s declared type is a container kind
            # other than dict (e.g. `Set[String]`) — see
            # gimple_ctypes.reify_empty_container_literal (confirmed via
            # TestSuite.skip_list: Set[String] = {}).
            _reified = gimple_ctypes.reify_empty_container_literal(gen, vtype, field_type, node.value)
            if _reified is not None:
                vtype, v = field_type, _reified
            gen._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{gimple_ctypes._safe_field(node.target.member)}")
            # Propagate elem/dict-val types from value to field name so
            # later field loads (in _lower_MemberExpr) can recover the
            # element type for subscript/list-iter dispatch — without this,
            # f.scopes[0] on a list-of-dicts field always returns int64_t
            # (see BUG-2026-044).  Keyed by field name (not variable name)
            # since that's what _lower_MemberExpr looks up.
            if field_type == 'MojoList *' and v in gen._elem_types:
                gen._field_elem_types.setdefault(struct_name, {})[node.target.member] = gen._elem_types[v]
                # Also store the dict value type for list-of-dicts fields
                # so f.scopes[0]["key"] dispatches to mojo_dict_get_str
                # instead of mojo_dict_get_int.
                if gen._elem_types[v] == 'MojoDict *' and v in gen._dict_val_types:
                    gen._field_dict_val_types.setdefault(struct_name, {})[node.target.member] = gen._dict_val_types[v]
    elif isinstance(node.target, gimple_ctypes.SubscriptExpr):
        # Fixed-size-array struct field write: `obj.field[idx] = ...` /
        # `obj.field[idx] += ...` (whole-element assignment, e.g. a
        # constructor-call RHS). See _array_field_elem_ptr's docstring —
        # must run before the generic `self.lower_expr(node.target.obj)`
        # below, which has no notion of the fixed-array field shape.
        _arr_tgt = (gen._array_field_elem_ptr(node.target.obj)
                    if isinstance(node.target.obj, gimple_ctypes.MemberExpr) else None)
        if _arr_tgt is not None:
            ot, obj_v = _arr_tgt
        else:
            ot, obj_v = gen.lower_expr(node.target.obj)
        it, idx_v  = gen.lower_expr(node.target.index)
        _dsw_sn = gen._dict_subclass_of(ot)
        # A USER-STRUCT instance whose class defines `__setitem__`: the
        # write is protocol dispatch to that method, not a container
        # store (see _lower_struct_subscript_dunder). vtype/v and the
        # index are already lowered above, so this keeps the statement's
        # single-evaluation guarantee.
        _setitem_r = gmp._lower_struct_subscript_dunder(
            gen, ot, obj_v, '__setitem__', [(it, idx_v), (vtype, v)])
        if _setitem_r is not None:
            return
        if ot == 'MojoList *':
            elem = gen._elem_of(obj_v)
            suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
            idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
            ev_cast = gen._cast_for_list(vtype, v, suf)
            gen._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
        elif ot == 'MojoBytes *':
            # `ba[i] = v` — bytearray element store (bytes is immutable in
            # Python, but the C type is shared; a store to a genuine
            # `bytes` value is a TypeError real code never reaches).
            idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
            v64 = gen._to_int64(vtype, v)
            gen._emit(f"  mojo_bytearray_setitem ({obj_v}, {idx64}, {v64});")
        elif ot == 'MojoDict *':
            # Record the dict's value type so later reads recover it (esp.
            # pointer values: dict-of-dicts/lists/sets, or a plain struct
            # instance). Homogeneous assumption, matching list element-type
            # tracking. Originally only recognized the hardcoded container
            # types, silently dropping any OTHER struct pointer (e.g.
            # `d[k] = SomeStruct(...)`) — later reads then had no
            # _dict_val_types entry and fell back to the char*-values
            # default, misreading the boxed struct pointer as a raw C
            # string and corrupting memory on the first `.attr` access.
            # Found via fire_compiler.py's own `_parse_postfix`'s
            # `keywords: dict = {}` (populated with parsed expression AST
            # nodes, then read back via `keywords.items()`) segfaulting
            # once self-hosted.
            if vtype in ('char *', 'double', 'MojoDict *', 'MojoList *', 'MojoSet *') or vtype.endswith(' *'):
                gen._dict_val_types[obj_v] = vtype
            # dict[key] = val → mojo_dict_set_str_* (key coerced via
            # _char_to_cstr, the single dict-key-to-string conversion
            # used by both read and write sides — see its docstring).
            if it == 'MojoBytes *':
                # A bytes KEY is its own key domain in the runtime (see
                # _DictSlot.keykind), not a char* one: routing it through
                # _char_to_cstr cast the MojoBytes POINTER to char*, so the
                # stored key was an address — a later `d[b'x']` read built a
                # different address and always missed, and two entries could
                # never collide or compare equal.
                if vtype == 'char *':
                    gen._emit_call('void', '', 'mojo_dict_set_bytes_str',
                                    [('MojoDict *', obj_v), ('MojoBytes *', idx_v), ('char *', v)])
                else:
                    gen._emit_dict_int_value_store(obj_v, 'MojoBytes *', idx_v,
                                                    vtype, v, node.value)
                key_tmp = None
            else:
                _, key_tmp = gen._char_to_cstr(it, idx_v, True, True)
            if key_tmp is None:
                pass
            elif vtype == 'char *':
                gen._emit_call('void', '', 'mojo_dict_set_str',
                                [('MojoDict *', obj_v), ('char *', key_tmp), ('char *', v)])
            else:
                # The ONE shared non-str dict store, `emit_dict_int_value_store`
                # (whose docstring is this arm's spec: a float through the
                # double setter, a `None` through `mojo_dict_set_none`, a bool
                # through `mojo_dict_set_bool` so THAT slot's repr says
                # True/False, the stored callable's return type noted, the
                # store through `_emit_call` so `_char_to_cstr`'s placeholder
                # key resolves). It used to be re-spelled here against the
                # whole-dict marker `mojo_mark_dict_bool_values`, which the
                # runtime DELETED when the per-slot kind replaced it — so
                # `d['a'] = True` compiled to a call to a function that does
                # not exist ("implicit declaration" in the generated C, a hard
                # build failure), and the bytes-keyed sibling two lines up
                # called a `gen.` name that was never a delegate and raised
                # AttributeError instead. Both were this arm's bug, and both
                # are gone now that there is one spelling of the store.
                gen._emit_dict_int_value_store(obj_v, 'char *', key_tmp,
                                              vtype, v, node.value)
        else:
            # Opaque int-typed container: check if it's a list or dict
            if ot in ('int', 'int64_t'):
                # Check if this is actually a list (from nested access) or dict
                actual_type = gen._get_actual_type(ot, obj_v)
                # Mirror the READ side's rule EXACTLY (`_lower_subscript` in
                # gimple_gen_calls.py): an opaque container is a dict only
                # when its resolved type says so, or when the KEY is
                # string-shaped; otherwise it is a list. This used to
                # default to dict while the read defaulted to list, so
                # `val[i]` and `val[i] = ...` on the same opaque local
                # disagreed: the read emitted `mojo_list_get_int(val, i)`
                # and the write `mojo_dict_set_int((MojoDict *)val,
                # mojo_str_from_int(i), ...)`. Writing through a MojoList
                # reinterpreted as a MojoDict scribbles over the list
                # header, and the next _dict_grow free()s a `slots`
                # pointer the allocator never handed out — a
                # POINTER_BEING_FREED_WAS_NOT_ALLOCATED abort. Real repro:
                # ast_rewriter._rewrite_node's `val[i] = _rewrite_node(...)`
                # inside its `isinstance(val, list)` branch, which only
                # became reachable once isinstance stopped truncating
                # pointers (see mojo_isinstance).
                _idx_is_str = (it in ('char *', 'MojoStr *')
                               or gen._get_actual_type(it, idx_v) == 'char *')
                _is_dict = (actual_type == 'MojoDict *'
                            or (_idx_is_str and actual_type not in ('MojoList *', 'MojoSet *')))
                if not _is_dict:
                    # It's a list - cast to MojoList* and set element
                    ip = gen._new_temp('int64_t')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    lp = gen._coerce_to_type('int64_t', 'MojoList *', ip)
                    idx64 = gen._new_val('int64_t', f"(int64_t){idx_v}")
                    # Get element type from the nested list
                    # First try _elem_of, then check _nested_elem_types, then default to int64_t
                    elem = gen._elem_of(obj_v)
                    if not elem or elem == 'int64_t':
                        if obj_v in gen._elem_types:
                            elem = gen._elem_types[obj_v]
                        elif obj_v in gen._nested_elem_types:
                            elem = gen._nested_elem_types[obj_v]
                    elem = elem or 'int64_t'
                    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
                    ev_cast = gen._cast_for_list(vtype, v, suf)
                    gen._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {ev_cast});")
                else:
                    # Default to dict (original behavior)
                    ip = gen._new_temp('int64_t')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    dp = gen._coerce_to_type('int64_t', 'MojoDict *', ip)
                    _, key_tmp2 = gen._char_to_cstr(it, idx_v, True, True)
                    # The same one store the statically-typed arm above uses;
                    # only the dict handle is a coerced int here.
                    gen._emit_dict_int_value_store(dp, 'char *', key_tmp2,
                                                  vtype, v, node.value)
            elif _dsw_sn and not gen._struct_defines_method(_dsw_sn, '__setitem__'):
                # `d[k] = v` on a builtin-`dict` subclass with no
                # `__setitem__` override: store into the backing MojoDict.
                _dsw_dp = gen._new_val('MojoDict *', f"{obj_v}->_data")
                _dsw_kt, _dsw_kv = gen._char_to_cstr(it, idx_v, True, True)
                if vtype == 'char *':
                    gen._emit_call('void', '', 'mojo_dict_set_str',
                                    [('MojoDict *', _dsw_dp), ('char *', _dsw_kv),
                                     ('char *', v)])
                else:
                    gen._note_container_callable_ret(_dsw_dp, v, vtype)
                    gen._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', _dsw_dp), ('char *', _dsw_kv),
                                     (vtype, v)])
            else:
                if not gen._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                    # GIMPLE strict: raw pointer subscript write needs address in a register.
                    # e.g. int64_t *ptr; ptr[i] = 0  must use _mojo_at_int64_t helper.
                    if ot.endswith(' *'):
                        elem_t = ot[:-2].rstrip()  # e.g. 'int64_t' from 'int64_t *'
                        if elem_t in gen.struct_field_types:
                            # Struct values can't sit in GIMPLE registers, so an
                            # aggregate `*addr = v` is not emittable; copy the
                            # struct into the slot field by field instead.
                            fields = gen.struct_field_types[elem_t]
                            if fields and vtype == f'{elem_t} *':
                                gen._ptr_helpers_needed.add(elem_t)
                                idx64 = gen._new_val('int64_t', f"(int64_t){idx_v}")
                                ptr_typed = gen._new_val(ot, f"({ot}){obj_v}")
                                addr = gen._new_val(ot, f"_mojo_at_{gimple_ctypes._c_id(elem_t)} ({ptr_typed}, {idx64})")
                                for fname, ftype in fields.items():
                                    safe_fn = gimple_ctypes._safe_field(fname)
                                    if gimple_ctypes.re.match(r'^.+\[\d+\]$', ftype):
                                        # Fixed-size-array field (marker
                                        # "ElemCtype[N]", see
                                        # _FIXED_ARRAY_ANN_RE): the field
                                        # is a real embedded C array, not
                                        # a scalar/pointer value — it
                                        # can't be read into a GIMPLE
                                        # register via `_new_val` (that
                                        # emitted an illegal
                                        # `int64_t[6] _tN;` local
                                        # declaration) nor assigned with
                                        # plain `=` (C arrays aren't
                                        # assignable). A whole-array
                                        # `memcpy` is the correct C
                                        # equivalent of Mojo's by-value
                                        # array-field copy semantics.
                                        # The byte count must be a
                                        # SIMPLE operand (a literal or a
                                        # plain variable) — `-fgimple`
                                        # rejects `sizeof(addr->field)`
                                        # ("expected expression before
                                        # 'sizeof'": its sizeof grammar
                                        # only accepts a bare TYPE NAME,
                                        # never an arbitrary expression;
                                        # see _gen_stmt_VarDecl's boxed-
                                        # mut-local allocator comment for
                                        # the same finding). Resolve the
                                        # element ctype + count from
                                        # self._array_field_sizes (the
                                        # authoritative source populated
                                        # at struct registration) rather
                                        # than re-parsing `ftype`.
                                        _ainfo = gen._array_field_sizes.get(elem_t, {}).get(fname)
                                        if _ainfo:
                                            _ect, _acnt = _ainfo
                                        else:
                                            _am = gimple_ctypes.re.match(r'^(.+)\[(\d+)\]$', ftype)
                                            _ect, _acnt = (_am.group(1), int(_am.group(2))) if _am else ('int64_t', 1)
                                        if _ect in gimple_codegen._SCALAR_CTYPE_SIZE:
                                            # Scalar element type: `sizeof(int64_t)` itself
                                            # is rejected by GIMPLE's sizeof grammar (see
                                            # above), so use a literal byte count computed
                                            # in Python instead.
                                            _nbytes = gimple_codegen._SCALAR_CTYPE_SIZE[_ect] * _acnt
                                        else:
                                            # Struct element type: unlike a scalar typedef,
                                            # `sizeof(StructName)` (a bare aggregate type
                                            # name) IS accepted by GIMPLE — this is the same
                                            # pattern already used for `calloc(1, sizeof(...))`
                                            # struct allocation elsewhere in this codegen.
                                            _esz = gen._new_val('int64_t', f"(int64_t) sizeof({_ect})")
                                            _nbytes = gen._new_val('int64_t', f"{_esz} * {_acnt}")
                                        gen._emit(f"  memcpy({addr}->{safe_fn}, {v}->{safe_fn}, {_nbytes});")
                                        continue
                                    fv = gen._new_val(ftype, f"{v}->{safe_fn}")
                                    gen._emit(f"  {addr}->{safe_fn} = {fv};")
                            else:
                                gimple_ctypes._debug_note('struct subscript write dropped',
                                            f'{elem_t}[...] = {vtype}')
                                raise RuntimeError(
                                    f"cannot compile module: `{elem_t}[...] = ...` "
                                    f"subscript store on user-defined struct "
                                    f"{elem_t!r} (no `__setitem__` method and "
                                    "no backing container field) — this codegen "
                                    "can't represent it as compiled C without "
                                    "silently dropping the store; falling back "
                                    "to interpreting this module from source instead")
                        else:
                            gen._ptr_helpers_needed.add(elem_t)
                            idx64 = gen._new_val('int64_t', f"(int64_t){idx_v}")
                            # Cast obj_v to the pointer type (it may be stored as integer)
                            ptr_typed = gen._new_val(ot, f"({ot}){obj_v}")
                            addr = gen._new_val(ot, f"_mojo_at_{gimple_ctypes._c_id(elem_t)} ({ptr_typed}, {idx64})")
                            v_cast = gen._new_temp(elem_t)
                            gen._safe_coerce_emit(vtype, elem_t, v, v_cast)
                            gen._emit(f"  *{addr} = {v_cast};")
                    else:
                        gen._emit(f"  {obj_v}[{idx_v}] = {v};")
    elif isinstance(node.target, gimple_ctypes.SliceExpr):
        # `x[a:b] = y` / `x[:] = y` / `x[::k] = y` — a real in-place splice
        # of a list, matching Python semantics (remove the slice's slots,
        # insert `y`'s elements at `start`, growing/shrinking the list).
        # Before this branch existed the trailing `else: pass` below
        # silently dropped the whole store — no error, no mutation
        # (“CODEGEN: bounded/full slice-assignment (`x[a:b] = y`”). The bounded
        # case shares the exact bound-normalization (`_lower_slice_bounds`)
        # of slice READS and `del x[a:b]`, and the same MojoList*-or-assume
        # ambiguity handling as `del x[a:b]`.
        stgt = node.target
        ot, obj_v = gen.lower_expr(stgt.obj)
        if ot == 'MojoStr *' or ot == 'char *':
            # `s[a:b] = ...` is not valid Python (str is immutable).
            raise RuntimeError(
                "cannot compile module: slice-assignment to a string "
                "target is not valid (strings are immutable) — falling "
                "back to interpreting this module from source instead")
        if ot == 'MojoBytes *':
            # `ba[a:b] = <bytes>` — bytearray slice-assign (splice). Only
            # the unstepped form is valid Python for a size-changing RHS;
            # a stepped bytearray slice-assign requires matching lengths
            # and is rare — handle the common case, fall through otherwise.
            if vtype == 'MojoBytes *':
                _rhs_b = v
            elif vtype == 'MojoList *':
                _rhs_b = gen._new_val('MojoBytes *', f"mojo_bytes_from_list ({v})")
            else:
                _rhs_b = gen._coerce_to_type('int64_t', 'MojoBytes *', gen._to_int64(vtype, v))
            if stgt.step is None:
                start_v, stop_v = gen._lower_slice_bounds(stgt)
                gen._emit(f"  mojo_bytearray_splice ({obj_v}, {start_v}, {stop_v}, {_rhs_b});")
                return
        lp = obj_v if ot == 'MojoList *' else gen._coerce_to_type(
            'int64_t', 'MojoList *', gen._to_int64(ot, obj_v))
        # RHS (`vtype`, `v`) is already lowered above. Both splice paths
        # read it as a MojoList* (raw int64_t element slots) — a list/tuple
        # literal or any list-typed expression. `x[:] = some_dict` is real
        # Python too (splices in the dict's keys) — DESIGN.html R1/R5,
        # shares _materialize_as_list with the tuple/list-unpack targets.
        rhs = gen._materialize_as_list(vtype, v)
        if stgt.step is None:
            # `x[:] = y` / `x[a:b] = y` — a real element-shifting splice
            # (delete [start:stop), insert y's elements at start, grow or
            # shrink). Shares `_lower_slice_bounds` (and thus the exact
            # negative-index / omitted-stop normalization) with slice READS
            # and `del x[a:b]`.
            start_v, stop_v = gen._lower_slice_bounds(stgt)
            gen._emit(f"  mojo_list_splice ({lp}, {start_v}, {stop_v}, {rhs});")
        else:
            # `x[a:b:k] = y` — an "extended slice" assignment: no size
            # change, each selected slot overwritten in order, and Python
            # requires len(y) to equal the slot count (the runtime helper
            # reports + exits on a mismatch). `has_start`/`has_stop` let
            # the runtime tell an omitted bound from an explicit 0, which
            # matters for the sign of `k` (Python's slice.indices rules).
            step_t, step_v = gen.lower_expr(stgt.step)
            step64 = gen._to_int64(step_t, step_v)
            if stgt.start is not None:
                st_t, st_v = gen.lower_expr(stgt.start)
                start64 = gen._to_int64(st_t, st_v)
                has_start = '1'
            else:
                start64, has_start = '0', '0'
            if stgt.stop is not None:
                sp_t, sp_v = gen.lower_expr(stgt.stop)
                stop64 = gen._to_int64(sp_t, sp_v)
                has_stop = '1'
            else:
                stop64, has_stop = '0', '0'
            gen._emit(f"  mojo_list_assign_step ({lp}, {has_start}, {start64}, "
                      f"{has_stop}, {stop64}, {step64}, {rhs});")
    elif isinstance(node.target, gimple_ctypes.CallExpr) and isinstance(node.target.func, gimple_ctypes.IdentExpr) \
            and node.target.func.name == '__get_address_as_uninit_lvalue' \
            and node.target.args:
        # __get_address_as_uninit_lvalue(addr) = val  →  *(T *)addr = val
        # addr is an int64_t holding raw pointer bits; val is the value to store.
        addr_t, addr_v = gen.lower_expr(node.target.args[0])
        ptr_tmp = gen._new_temp('int64_t *')
        gen._safe_coerce_emit(addr_t, 'int64_t *', addr_v, ptr_tmp)
        val_tmp = gen._new_temp(vtype)
        gen._safe_coerce_emit(vtype, vtype, v, val_tmp)
        gen._emit(f"  *{ptr_tmp} = {val_tmp};")
    else:
        pass


def _gen_stmt_AugAssignStmt(gen, node):
    base_op = node.op[:-1]
    # For augmented assignments, use lower_expr with a fake BinaryOp to get proper type handling
    # This includes string concatenation, list concatenation, etc.
    # '@' (matrix-multiply, `a @= b`) must go through this path too — it
    # has no native C operator, so falling into the `else` branch below
    # (which builds a raw `{lv} {c_op} {rv}` C expression via _BIN_OPS,
    # whose .get(base_op, base_op) fallback returns the literal '@' verbatim
    # since _BIN_OPS has no '@' entry) emitted a bare `@` token straight
    # into the GIMPLE C output — invalid syntax ("stray '@' in program" /
    # "expected ';' before 'b'", real repro: Lib/operator.py's
    # `def imatmul(a, b): a @= b; return a`). Routing through lower_expr's
    # BinaryOp path instead reaches _lower_binary's own `if node.op == '@':
    # return self._lower_matmul(node)` case, the same dunder-dispatch
    # `a.__matmul__(b)` lowering plain `a @ b` already uses.
    if base_op in ('//', '**', '+', '-', '*', '/', '%', '|', '&', '^', '<<', '>>', '@'):
        fake  = gimple_ctypes.BinaryOp(op=base_op, left=node.target, right=node.value)
        vtype, v = gen.lower_expr(fake)
    else:
        c_op = gimple_ctypes._BIN_OPS.get(base_op, base_op)
        rtype, rv = gen.lower_expr(node.value)
        if isinstance(node.target, gimple_ctypes.IdentExpr):
            tname  = node.target.name
            ttype  = gen._type_of(tname)
            arith  = gimple_ctypes.TypeLattice.join(ttype, rtype)
            lv_a   = gen._cname(tname)
            rv_a   = rv
            if ttype != arith:
                ct = gen._new_val(arith, f"({arith}){gen._cname(tname)}")
                lv_a = ct
            if rtype != arith:
                ct = gen._new_val(arith, f"({arith}){rv}")
                rv_a = ct
            tmp = gen._new_val(arith, f"{lv_a} {c_op} {rv_a}")
            vtype, v = arith, tmp
        else:
            # Skip emitting comment to avoid GIMPLE global-passing issues
            return
    if isinstance(node.target, gimple_ctypes.IdentExpr):
        tname = node.target.name
        # If the target is a heap-boxed mutable capture, _write_dest
        # returns the DEREFERENCED box (`*name`, an lvalue of the
        # pointee type) — the coercion target must be the POINTEE
        # ctype, not the box pointer ctype, or the value gets
        # pointer-cast and assigned into a non-pointer lvalue
        # (GCC: "assignment to 'int64_t' from 'int64_t *'" — real bug
        # found via test_locks.mojo's `_ = time_function(test_atomic)`
        # where `_` is boxed because a nested async closure reassigns
        # it). _type_of normally returns the pointee, but its
        # `name not in self._captures` guard skips the boxed branch
        # when the name is ALSO a regular env capture, so resolve the
        # pointee explicitly here.
        if tname in getattr(gen, '_boxed_mut_locals', {}):
            dst = gen._boxed_mut_locals[tname]
        elif (tname in gen._global_var_types
                and (gen._in_toplevel_gen
                     or tname in getattr(gen, '_func_declared_globals', ()))):
            # Mirror _write_dest's own "is this write actually landing
            # on the module globals struct?" check: _type_of only ever
            # consults var_types (LOCAL variable types), never
            # _global_var_types/_global_c_decl_types, so for a genuine
            # module-level global (no enclosing function needed for a
            # plain top-level statement — see _write_dest's identical
            # `_in_toplevel_gen` check) it silently fell back to its
            # generic 'int64_t' default. _write_dest's OWN lvalue is
            # correctly typed (the real struct field, e.g. `char *`),
            # so coercing the computed value as if the destination
            # were int64_t produced a genuine, real type mismatch —
            # "assignment to 'char *' from 'int64_t'" — for something
            # as ordinary as a top-level `X += " world"` on a string
            # global (found via Tools/build/generate_token.py's own
            # `token_h_template += """..."""`).
            dst = gen._global_dst_ctype(tname)
        else:
            dst = gen._type_of(tname)
        # `k += 1` IS an assignment, so it goes through the SAME chokepoint
        # the plain AssignStmt path uses (`_track_pointer_actual_type` is
        # what carries `_actual_types`, `_elem_types`, `_dict_val_types`
        # and `_int_word_vals` from the value being stored onto the name
        # being stored into). This path was the one write-side site that
        # skipped it, which is silent rather than loud: `k = 3000000000`
        # then `k += 1` loses the "this value is a plain integer" record
        # that `_lower_IntLiteral` seeded, so `d[k] = 1` goes to
        # `mojo_dict_set_int_kw` and the runtime's range-only
        # discriminator calls address 3000000001 a `char *`
        # (bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md) —
        # a SIGSEGV in the middle of a perfectly ordinary increment loop.
        # The chokepoint's own `discard` branch is what keeps it sound:
        # `k += "x"` clears the record rather than leaving it.
        gen._track_pointer_actual_type(tname, dst, v, vtype)
        gen._safe_coerce_emit(vtype, dst, v, gen._write_dest(tname))
    elif isinstance(node.target, gimple_ctypes.MemberExpr):
        # `sys.argv = [...]` — a whole-list rebind. Reads lower to
        # mojo_get_argv() (see _lower_MemberExpr's sys/argv case), so the
        # write needs the matching runtime store or it is silently
        # dropped: fire.py's own CLI strips its `--dump`/`--dump-full`
        # flags exactly this way before `input_file = sys.argv[1]`, and
        # without this the compiled binary kept the unstripped argv and
        # used the FLAG as the input filename (bootstrap stage 2/3 wrote
        # `--dump.ci` instead of `<basename>.ci` for every file).
        if (isinstance(node.target.obj, gimple_ctypes.IdentExpr)
                and node.target.obj.name == 'sys'
                and node.target.member == 'argv'):
            _av = v if vtype == 'MojoList *' else gen._coerce_to_type(
                vtype, 'MojoList *', v)
            gen._emit_call('void', '', 'mojo_replace_argv',
                            [('MojoList *', _av)])
            return
        _cattr_w = gmp._resolve_class_attr_write_target(gen, node.target)
        if _cattr_w is not None:
            gtype, gname = _cattr_w
            gen._safe_coerce_emit(vtype, gtype, v, gname)
            return
        _dv = gen._annotation_dict_val_type(getattr(node, 'type_ann', None))
        if _dv is not None:
            gen._dict_val_types[node.target.member] = _dv
        ot, ov = gen.lower_expr(node.target.obj)
        if ot in ('int', 'int64_t'):
            # See the AssignStmt MemberExpr branch above for why this
            # calls _mojo_dispatch_setattr, not the bare mojo_setattr
            # runtime stub (a no-op fallback, not a real implementation).
            member_str = node.target.member
            key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
            key_tmp = gen._new_val('char *', f"{key_slit}")
            v64 = gen._new_temp('int64_t')
            gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
            vp_tmp = gen._new_val('void *', f"(void *){ov}")
            gen._emit_call('void', '', '_mojo_dispatch_setattr',
                            [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
        elif (gimple_exprtypes._struct_name_of(ot) in gimple_ctypes._FIXED_RUNTIME_STRUCT_NAMES
              and node.target.member not in gen.struct_field_types.get(gimple_exprtypes._struct_name_of(ot), {})):
            # Step 4 (bugs/hard/CODEGEN_dynamic_attribute_on_generic_
            # object.md), augmented-assignment analogue of the plain
            # AssignStmt MemberExpr branch above — same fixed-layout
            # runtime struct (e.g. MojoBoundMethod), unknown field:
            # route through dynamic-attribute dispatch instead of a
            # direct `->member = v` GCC would reject.
            member_str = node.target.member
            key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
            key_tmp = gen._new_val('char *', f"{key_slit}")
            v64 = gen._new_temp('int64_t')
            gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
            vp_tmp = gen._new_val('void *', f"(void *){ov}")
            gen._emit_call('void', '', '_mojo_dispatch_setattr',
                            [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
        elif gen._is_except_as_member_target(node.target.obj):
            # Augmented-assignment analogue of the AssignStmt MemberExpr
            # branch above (`err.filename += ...` on a caught exception
            # object) — see `_is_except_as_member_target`/
            # `self._except_as_names` and bugs/hard/
            # CODEGEN_dynamic_attribute_on_generic_object.md's "Residual
            # gap: caught exception objects" section.
            gen._emit_dynattr_setattr_dispatch(node.target.member, vtype, v, ot, ov)
        else:
            # Mirrors _gen_stmt_AssignStmt's identical MemberExpr
            # struct-field branch: look up the field's REAL declared C
            # type and coerce the computed value to it instead of a raw
            # `->member = v` emit. Without this, `self.is_docstring |=
            # is_docstring` (a bool dataclass field, declared plain
            # `int` per this codegen's bool representation) — where the
            # RHS is computed via the BinaryOp `|` path a few lines up
            # and widened to `int64_t` (an unannotated `is_docstring=
            # False` keyword param defaults to int64_t) — assigned that
            # int64_t straight into the `int` field with no cast, a
            # hard GIMPLE verifier rejection ("non-trivial conversion
            # in 'var_decl'"), since -fgimple requires an explicit
            # narrowing cast, unlike ordinary C. Real repro: Tools/
            # i18n/pygettext.py's `Message.add_location`. See
            # COMPILE_FAIL_Tools_i18n_pygettext.
            op = '->' if '*' in ot else '.'
            struct_name = gimple_exprtypes._struct_name_of(ot)
            field_type = gen.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
            gen._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{gimple_ctypes._safe_field(node.target.member)}")
    elif isinstance(node.target, gimple_ctypes.SubscriptExpr):
        # Fixed-size-array struct field write: `obj.field[idx] = ...` /
        # `obj.field[idx] += ...` (whole-element assignment, e.g. a
        # constructor-call RHS). See _array_field_elem_ptr's docstring —
        # must run before the generic `self.lower_expr(node.target.obj)`
        # below, which has no notion of the fixed-array field shape.
        _arr_tgt = (gen._array_field_elem_ptr(node.target.obj)
                    if isinstance(node.target.obj, gimple_ctypes.MemberExpr) else None)
        if _arr_tgt is not None:
            ot, obj_v = _arr_tgt
        else:
            ot, obj_v = gen.lower_expr(node.target.obj)
        it, idx_v  = gen.lower_expr(node.target.index)
        _dsa_sn = gen._dict_subclass_of(ot)
        # Augmented-assignment analogue of the AssignStmt branch above:
        # `obj[key] += v` on a user struct defining `__setitem__` stores
        # through that method; the read half already dispatched to
        # `__getitem__` via the fake-BinaryOp subscript lowering.
        _setitem_r = gmp._lower_struct_subscript_dunder(
            gen, ot, obj_v, '__setitem__', [(it, idx_v), (vtype, v)])
        if _setitem_r is not None:
            return
        if ot == 'MojoList *':
            elem = gen._elem_of(obj_v)
            suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
            idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
            gen._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {v});")
        elif ot == 'MojoDict *':
            # `d[k] += val` etc. — mirrors _gen_stmt_AssignStmt's MojoDict*
            # branch (this one had no dict case at all: any dict-subscript
            # augmented assignment fell through to the raw-pointer/MojoList
            # branches below, e.g. `_mojo_at_MojoDict` array-offset codegen
            # on a dict pointer — invalid GIMPLE, "non-register as LHS of
            # unary operation". Found via mojolib BUG-2026-031: a closure
            # capturing an outer dict and doing `counts[key] += 1` inside it.
            _, key_tmp = gen._char_to_cstr(it, idx_v, True, True)
            if vtype == 'char *':
                gen._emit_call('void', '', 'mojo_dict_set_str',
                                [('MojoDict *', obj_v), ('char *', key_tmp), ('char *', v)])
            else:
                gen._emit_call('void', '', 'mojo_dict_set_int',
                                [('MojoDict *', obj_v), ('char *', key_tmp), (vtype, v)])
        elif ot in ('int', 'int64_t'):
            # Opaque int/int64_t used as subscript target — could be a
            # list OR a dict (e.g. a closure-captured env field, or a
            # stubbed constructor like `collections.Counter[str]()`,
            # whose static type isn't tracked). Dispatch EXACTLY like
            # the subscript READ path (_lower_subscript's opaque-int
            # case), because an augmented subscript assignment is a
            # read-modify-write: the read half already picks dict when
            # the index is string-typed ("no list is indexable by a
            # string"), and this write half used to dispatch on the
            # actual-type check ALONE — falling into its MojoList
            # fallback for any not-statically-dict container. A
            # str-keyed `stats[k] += v` on such a container then READ
            # mojo_dict_get_int (dict) but STORED via
            # mojo_list_set_int(list) — a GCC int-conversion hard error
            # at best (v a char*), silent header-as-list memory
            # corruption at worst (v an int; real repro:
            # Tools/scripts/summarize_stats.py's load_raw_data, whose
            # `stats` is a stubbed Counter and which segfaulted as a
            # minimal 6-line repro before erroring there).
            actual_type = gen._get_actual_type(ot, obj_v)
            idx_is_str = (it in ('char *', 'MojoStr *')
                          or gen._get_actual_type(it, idx_v) == 'char *')
            if actual_type == 'MojoDict *' or (idx_is_str and actual_type not in ('MojoList *', 'MojoSet *')):
                ip = gen._new_temp('int64_t')
                gen._emit(f"  {ip} = (int64_t){obj_v};")
                dp = gen._coerce_to_type('int64_t', 'MojoDict *', ip)
                _, key_tmp2 = gen._char_to_cstr(it, idx_v, True, True)
                if vtype == 'char *':
                    gen._emit_call('void', '', 'mojo_dict_set_str',
                                    [('MojoDict *', dp), ('char *', key_tmp2), ('char *', v)])
                else:
                    gen._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', dp), ('char *', key_tmp2), (vtype, v)])
            else:
                ip = gen._new_val('int64_t', f"(int64_t){obj_v}")
                lp = gen._coerce_to_type('int64_t', 'MojoList *', ip)
                elem = gen._elem_of(obj_v)
                suf = gimple_ctypes.TypeLattice.list_suffix(elem)
                idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
                gen._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {v});")
        elif _dsa_sn and not gen._struct_defines_method(_dsa_sn, '__setitem__'):
            # `d[k] += v` on a builtin-`dict` subclass: read-modify-write
            # through the backing MojoDict (the read half already went
            # through _lower_subscript's dict-subclass branch).
            _dsa_dp = gen._new_val('MojoDict *', f"{obj_v}->_data")
            _dsa_kt, _dsa_kv = gen._char_to_cstr(it, idx_v, True, True)
            if vtype == 'char *':
                gen._emit_call('void', '', 'mojo_dict_set_str',
                                [('MojoDict *', _dsa_dp), ('char *', _dsa_kv),
                                 ('char *', v)])
            else:
                gen._emit_call('void', '', 'mojo_dict_set_int',
                                [('MojoDict *', _dsa_dp), ('char *', _dsa_kv),
                                 (vtype, v)])
        elif ot.endswith(' *') and gimple_exprtypes._struct_name_of(ot) not in gen.struct_field_types:
            # Raw C pointer: use _mojo_at_ helper (GIMPLE doesn't allow ptr arithmetic)
            if not gen._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                elem_t = gimple_ctypes._elem_type(ot)
                cn = gimple_ctypes._c_id(elem_t)
                gen._ptr_helpers_needed.add(elem_t)
                idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
                ptr_t = gen._new_val(ot, f"({ot}){obj_v}")
                addr = gen._new_val(ot, f"_mojo_at_{cn} ({ptr_t}, {idx64})")
                v_cast = gen._new_temp(elem_t)
                gen._safe_coerce_emit(vtype, elem_t, v, v_cast)
                gen._emit(f"  *{addr} = {v_cast};")
        else:
            if not gen._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                # A KNOWN USER struct with no `__setitem__` and no _data
                # container field has no correct lowering for a subscript
                # store — the instance is not an array. The raw C emit
                # below is only valid for a genuine raw-pointer/array
                # lvalue; on a struct pointer it silently wrote garbage
                # (or, once loop slots stopped being blanket-int64_t,
                # became GCC's "array subscript is not an integer" —
                # real: Counter.__iadd__'s `self[elem] += count`, whose
                # class subclasses builtin dict but registers neither
                # dunder here). Refuse honestly so gen_module falls back
                # to interpreting this module from source.
                _w_sn = gimple_exprtypes._struct_name_of(ot)
                if ot.endswith(' *') and _w_sn in gen.struct_field_types:
                    raise RuntimeError(
                        f"cannot compile module: `{_w_sn}[...] = ...` "
                        f"subscript store on user-defined struct {_w_sn!r} "
                        "(no `__setitem__` method and no backing container "
                        "field) — this codegen can't represent it as "
                        "compiled C without emitting silently wrong code; "
                        "falling back to interpreting this module from "
                        "source instead")
                gen._emit(f"  {obj_v}[{idx_v}] = {v};")
    else:
        pass  # complex aug-assign target: no-op


def _redecl_upgrade_default(gen, name: str, ctype: str) -> None:
    """Re-type a local already declared as the int64_t DEFAULT, when a
    later read proves what it really holds.

    `_declare_var` is deliberately first-decl-wins (see its docstring) and
    that guard is load-bearing for the case it was written for — two sibling
    `for` loops reusing a target name with different element types, where
    the FIRST declaration is the intended one. This is the other case: the
    first declaration was not a decision at all but the "no evidence" box,
    and the multi-value-destructuring slot read that follows is exactly the
    evidence that was missing.

    So the upgrade is gated on the old type being the default box, which no
    inference path ever chooses deliberately, and the already-emitted C
    declaration is rewritten in place rather than appended (the decls list
    is C text, and a second declaration of the same name would not compile).
    The C identifier is reused — `_declare_var` will see the name present
    and no-op, so `var_types` is what actually carries the new type.
    """
    c_name = gen._c_names.get(name, name)
    gen.var_types[name] = ctype
    gen._elem_types.pop(name, None)
    for _di in range(len(gen.decls)):
        _d = gen.decls[_di]
        if _d.strip() == f"int64_t {c_name};" or _d.strip() == f"int {c_name};":
            _ind = _d[:len(_d) - len(_d.lstrip())]
            gen.decls[_di] = f"{_ind}{ctype} {c_name};"
            return


def _gen_stmt_ReturnStmt(gen, node):
    # doc/OWNERSHIP_MODEL.md Phase 3 codegen wiring (TODO item 1) — see
    # gimple_gen_infra.py's "Public entry points" section for the whole
    # feature.
    #
    # IMPORTANT: for a `return <value>`, this call must run AFTER
    # `gen.lower_expr(node.value)` below, not before it — see the second
    # call site further down. A candidate can never be the returned VALUE
    # ITSELF (rule 3 disqualifies `return d`/`return d, x`), but rule 3
    # does NOT — and was never meant to — disqualify a candidate merely
    # READ from in the return expression (`return d["x"]`, `return
    # d.get(k)`, `return len(d)`, ...): `_scan_expr`'s subscript/member
    # safe-receiver carve-outs correctly say this doesn't make `d`
    # ESCAPE, but escaping and "still needed to compute the value on
    # THIS statement" are different questions. Freeing `d` before
    # evaluating `d["x"]` was a real, confirmed use-after-free (found
    # 2026-09-15 investigating Phase 6, reproduced as a `MallocScribble`
    # segfault via `d = {}; d["x"] = 1; return d["x"]`, which used to
    # free `d` in the generated C, THEN read `mojo_dict_get_int(d, ...)`
    # from it, on the same line) — worked "by accident" in every case
    # exercised before that, because a freed small allocation isn't
    # necessarily corrupted before it's read back on this allocator.
    # A bare `return` (no value) has no such expression to protect, so
    # its call site (below, in the `if node.value is None` branch) is
    # unaffected and unchanged.
    if node.value is None:
        ginf.emit_return_frees(gen)
        # If function returns non-void, return default value
        if gen.func_ret_type and gen.func_ret_type != 'void':
            ret = gen.func_ret_type
            # A bare `return` (Python's implicit `return None`) inside a
            # function whose OTHER paths return a real value must still
            # emit a same-typed placeholder for THIS path — but a bare,
            # uncast integer literal `return 0;` only actually type-
            # checks under `-fgimple` when `ret` is plain `int` (the
            # literal's own default C type) or a pointer type (`0` is
            # also a valid null-pointer constant there). Any OTHER
            # declared return type — most commonly `int64_t`, this
            # codegen's default "boxed scalar" representation used far
            # more often than plain `int` (see _quick_type's own int64_t
            # defaults throughout), also `_Bool`/`double`/etc. — left a
            # bare `int`-typed `0` returned from a differently-typed
            # function, which GIMPLE (unlike ordinary C) does NOT
            # implicitly convert: GCC's honest "invalid conversion in
            # return statement". Real: turtle.py's `TPen.pencolor`/
            # `.fillcolor`, each with an early bare `return` (`if color
            # == self._pencolor: return`) alongside another branch
            # returning `self._color(...)`'s real int64_t-typed value —
            # the function's own inferred return type is int64_t, so the
            # bare-return path's naked `return 0;` mismatched.
            if ret == 'int' or ret.endswith(' *'):
                gen._emit(f"  return 0;")
            else:
                tmp = gen._new_temp(ret)
                zero_lit = '0.0' if ret == 'double' else '0'
                gen._emit(f"  {tmp} = ({ret}){zero_lit};")
                gen._emit(f"  return {tmp};")
        else:
            gen._emit(gimple_codegen._RETURN)
    else:
        vtype, v = gen.lower_expr(node.value)
        # See this function's own top comment: must run AFTER the value is
        # computed, not before — a candidate can still be legitimately
        # READ from (subscript/member/method) while computing `v` above.
        ginf.emit_return_frees(gen)
        # Record the returned container's element type so CALL SITES can
        # unpack/iterate it with the right accessor. The old condition
        # required vtype == 'MojoList *' (only fired for `return <list
        # variable>`); a TUPLE return (`return ctype, cval`, the codegen's
        # own ubiquitous pattern — lower_expr/_lower_* all return
        # (ctype, cval) string pairs) lowers with vtype = the tuple's
        # ELEMENT type ('char *'), so it was never recorded and callers
        # unpacked the tuple via mojo_list_get_int, reading char* pointers
        # as int64_t and f-string-interpolating them as decimal addresses
        # (every basic statement's variable/value names printed as garbage
        # heap addresses in the native .ci). Just checking `v` is a tracked
        # container is enough — the returned value's element type is what
        # matters, regardless of how the value's own C type reads.
        #
        # NOT for an EMPTY container literal. `_lower_list_literal` /
        # `_lower_tuple_literal` / `_lower_dict_literal` record their temp's
        # element type from `_infer_list_elem_type`, whose answer for an empty
        # literal is `'int64_t'` — a STORAGE default (the list variable needs a
        # declaration), not evidence about what it holds. Publishing it as the
        # FUNCTION's return element type is a false claim with real
        # consequences: this write is last-write-wins, so
        #
        #     def f(i):
        #         if i: return [t for t in ["a", "b"]]
        #         return []
        #
        # published `int64_t` from the trailing `[]` (the comprehension
        # contributes nothing of its own — its loop target is not in
        # `_prepass_local_elems`, so `_quick_container_elem` answers None for
        # it), and `print(f(1))` routed to `mojo_repr_list_ints`, which reads
        # each slot with the integer accessor, and printed both `char *` slots
        # as pointer decimals. The same program WITHOUT the trailing
        # `return []` was already right, which is what made the `if` look like
        # the trigger instead of the empty literal. See bugs/
        # CODEGEN_comprehension_in_a_branch_loses_its_result_elem_type.md.
        #
        # The element-type table itself still gets its `'int64_t'`: `l = []`
        # followed by `l.append(x)` — including through a module-level global,
        # where nothing else seeds the table — reads it there, and removing it
        # regressed `test_gimple_runner.py`'s
        # `gimple_genexp_struct_receiver_still_correct`.
        if v in gen._elem_types and not _is_empty_container_literal(node.value):
            gen._return_elem_types[gen.current_func_name] = gen._elem_types[v]
        # A `return` whose value is a container of a DIFFERENT kind than an
        # earlier `return` in this same function: the function has no single
        # container type, so its return slot is the box and a call site cannot
        # know which container it holds. Recorded so the call site asks the
        # runtime registries instead of guessing one kind and reading another
        # one's memory — see `gen._multi_kind_return_funcs`.
        _fk = gen.current_func_name
        if (_fk and vtype in ('MojoList *', 'MojoDict *', 'MojoSet *')
                and gen.func_ret_type == 'int64_t'):
            _seen = gen._multi_kind_return_kinds.setdefault(_fk, [])
            if vtype not in _seen:
                _seen.append(vtype)
                if len(_seen) > 1:
                    gen._multi_kind_return_funcs[_fk] = True
        elif (_fk and gen.func_ret_type == 'int64_t'
                and (v in ginf.multi_kind_locals(gen)
                     or v in ginf.mixed_container_locals(gen)
                     or v in getattr(gen, '_boxed_container_vals', ()))):
            # The returned value is a LOCAL BOUND TO CONTAINERS OF MORE THAN
            # ONE KIND, so it lowers to the box and the `vtype in (...)` arm
            # above never sees a second kind: `def probe(box, kind): if kind
            # == 1: box = [1, 2] else: box = {"a": 1}; return box` returned
            # `box` on BOTH paths, so the disagreement lives in the local,
            # not in the returns.
            #
            # The call site then took the `int64_t`-returning branch's
            # DEFAULT — `_actual_types[t] = 'MojoList *'` — and read the dict
            # through `mojo_repr_list_ints`: another container's memory, out
            # of bounds, printing `[0]` where CPython prints `{'a': 1}`. The
            # registry dispatch is the answer the caller has to be told
            # about, and this is the same fact from the callee's side.
            #
            # All THREE predicates name the value, and each is needed because
            # each is the only one that sees a different way the disagreement
            # arrives (the first two for the same reason the declaration
            # site's gate consults both — see the comment on
            # `_pin_to_ground_truth`: `mixed_container_locals` is this
            # function's own `_cur_func_body` walk and is the only one of the
            # two that finds a rebound local inside a LIFTED CLOSURE, whose
            # name `resolve_shared._infer_local_var_types` never recorded
            # under any spelling).
            #
            # `_boxed_container_vals` is the third and closes the remaining
            # hole: a function that FORWARDS a box rather than owning one
            # (`def outer(flag): return consume(flag)`) has no multi-kind
            # local of its own for the first two to name — but its result is
            # a container of unknown kind all the same, and it was relabelled
            # `MojoList *` at the caller for exactly that reason. Without this
            # the box is reported by the function that made it and dropped by
            # every function it passes through, so a one-line forwarding hop
            # is enough to lose it. A box the callee installs but does not
            # report is worse than no box: it reads as a wrong answer at the
            # call site instead of refusing at the store.
            gen._multi_kind_return_funcs[_fk] = True
        # Same for a multi-value return's PER-SLOT types: `return cfg, Model(cfg)`
        # is a heterogeneous tuple (two different struct pointers) whose
        # single joined element type is the useless int64_t, so a caller's
        # `cfg, m = build(...)` read both slots as int64_t and assigned
        # them into `Config *` / `Model *` locals — which GIMPLE rejects
        # outright ("internal compiler error: in build2, at tree.cc:5208"),
        # since unlike plain C it does not implicitly convert.
        if gen.current_func_name and v in gen._tuple_slot_types:
            gen._return_slot_types[gen.current_func_name] = gen._tuple_slot_types[v]
        # Same idea for a returned CALLABLE: `def mk(): return lambda: False`
        # hands back a `void *`, and the `mk()(...)` call site would then read
        # the homogenized int64_t box. The lowered value is what
        # `_lower_LambdaExpr` recorded the real type against, so this is the
        # one site that can see it.
        if gen.current_func_name and v in gen._callable_ret_types:
            gen._return_callable_ret_types[gen.current_func_name] = \
                gen._callable_ret_types[v]
        ret = gen.func_ret_type
        if ret == 'void':
            gen._emit(gimple_codegen._RETURN)
        elif ret and ret != 'void' and vtype != ret:
            tmp = gen._new_temp(ret)
            gen._safe_coerce_emit(vtype, ret, v, tmp)
            gen._emit(f"  return {tmp};")
        else:
            gen._emit(f"  return {v};")


def _ensure_bool_cond(gen, ctype: str, val: str) -> str:
    """Convert val to a GIMPLE-safe _Bool for use in if/while conditions."""
    # A condition whose `lower_expr` returned an UNKNOWN type leaves
    # `ctype` as the real Python `None` — which reaches the string-keyed
    # `ctype in gen._CONTAINER_LEN_FN` membership test just below and, on
    # the self-hosted path, SIGSEGVs in strcmp inside mojo_dict_contains
    # with a NULL key (the identical failure mode the `_real_ctype is not
    # None` guard further down already documents). Normalize to the empty
    # string so every `in`/`==`/`.endswith` below is a safe string
    # operation and the unknown type falls through to the generic
    # nonzero-int truthiness path (CPython never sees None here — it would
    # have raised on `None.endswith` — so this is compiled-path-only).
    if ctype is None:
        ctype = ''
    if ctype == '_Bool':
        return val
    # A module-level container global (`x: set = set()`) is deliberately
    # reported here as `ctype == 'int64_t'` — its C struct field is boxed
    # int64_t by design (see _lower_IdentExpr's global-read branch: "Globals
    # are stored at C level as int64_t (boxed pointers)"), with the REAL
    # Mojo type tracked separately in `gen._actual_types[val]` for callers
    # that need it. Without consulting that overlay here, `if <container
    # -global>:` compiled to a raw `!= 0` pointer-nullness check instead of
    # an emptiness check — always true once the global's `set()`/`{}`/`[]`
    # initializer allocated it, regardless of whether it had any elements.
    # Concrete failure: gimple_gen_coro.py's module-level `_NATIVE_FUTURE_
    # CLASSES: set = set()` — `if _NATIVE_FUTURE_CLASSES:` (gated on
    # non-empty) was always truthy on the compiled backend, so `register()`
    # unconditionally set `gen._native_future_bridge = True` for every
    # program (even one with zero coroutines/futures), spuriously pulling
    # in ~40 unrelated `extern __mojo_*` coroutine-shim declarations into
    # gen_module_impl's boilerplate assembly on EVERY `MOJO_NO_SHIM=1`
    # compile and crashing downstream.
    if ctype == 'int64_t':
        _real_ctype = gen._actual_types.get(val)
        # `_real_ctype is not None and ...`, not a bare `in` check: `val`
        # is usually NOT a key in `_actual_types` (that dict only tracks
        # globals/specially-typed temps), so `.get(val)` returning the
        # real Python `None` is the COMMON case here — and checking
        # `None in gen._CONTAINER_LEN_FN` (a dict of string keys) on the
        # compiled backend doesn't safely evaluate to False the way real
        # Python does: it reached the same string-keyed dict membership
        # machinery with a NULL "key" and SIGSEGV'd in strcmp inside
        # mojo_dict_contains, on virtually any `if <cond>:`/`while <cond>:`
        # whose scalar int64_t condition simply isn't a tracked container
        # value — i.e. almost every ordinary boolean condition in a real
        # program (surfaced only once compiling fire.py's own full source
        # actually reached a deeply-nested closure this small test corpus
        # never exercised).
        if _real_ctype is not None and _real_ctype in gen._CONTAINER_LEN_FN:
            # `val` is still C-level `int64_t` (the boxed-pointer storage
            # type) — GIMPLE needs the pointer cast to go through `void *`
            # first (the same two-step sequence every other int64_t<->
            # pointer boxing site in this file uses), or gcc rejects the
            # direct `int64_t` -> `MojoSet *` argument as "makes pointer
            # from integer without a cast".
            _vp = gen._new_val('void *', f'(void *){val}')
            val = gen._new_val(_real_ctype, f'({_real_ctype}){_vp}')
            ctype = _real_ctype
    if ctype in gen._CONTAINER_LEN_FN:
        n = gen._call_expr('int64_t', gen._CONTAINER_LEN_FN[ctype], [(ctype, val)])
        b = gen._new_temp('_Bool')
        zero = gen._new_temp('int64_t')
        gen._emit(f"  {zero} = (int64_t)0;")
        gen._emit(f"  {b} = {n} != {zero};")
        return b
    if ctype == 'char *':
        n = gen._call_expr('int', 'mojo_truthy_cstr', [('char *', val)])
        b = gen._new_temp('_Bool')
        gen._emit(f"  {b} = {n} != 0;")
        return b
    if ctype in ('void *',) or (ctype.endswith(' *') and ctype != '_Bool'):
        ip   = gen._new_temp('int64_t')
        zero = gen._new_temp('int64_t')
        b    = gen._new_temp('_Bool')
        gen._emit(f"  {ip} = (int64_t){val};")
        gen._emit(f"  {zero} = (int64_t)0;")
        gen._emit(f"  {b} = {ip} != {zero};")
        return b
    if ctype == 'int64_t':
        zero = gen._new_temp('int64_t')
        b    = gen._new_temp('_Bool')
        gen._emit(f"  {zero} = (int64_t)0;")
        gen._emit(f"  {b} = {val} != {zero};")
        return b
    # int and other integer types: avoid GIMPLE type-mismatch by going through int64_t
    if ctype not in ('_Bool',):
        b = gen._new_temp('_Bool')
        v64 = gen._new_temp('int64_t')
        z64 = gen._new_temp('int64_t')
        gen._emit(f"  {v64} = (int64_t){val};")
        gen._emit(f"  {z64} = (int64_t)0;")
        gen._emit(f"  {b} = {v64} != {z64};")
        return b
    return val








def _apply_isinstance_narrowings(gen, cond) -> dict:
    """Lower each `isinstance`-guarded expression once, cast it to the
    guarded struct-pointer type, and register it in `_narrowed_exprs` for
    the guarded body. Returns {key: prior_value_or_None} for _restore."""
    narrowings: list = []
    gen._collect_isinstance_narrowings(cond, narrowings)
    saved: dict = {}
    # Index the 3-tuple, NOT `for key, ptr_ct, expr in narrowings`: the
    # unpack boxes `ptr_ct` (a C type string like 'ExprStmt *') on the
    # self-hosted path, so `f'({ptr_ct}){vp}'` emitted a raw pointer
    # decimal AS THE CAST TYPE (`_t16 = (47828682656)_t15;`) — invalid C
    # on the shimless `--dump`.
    for _nw in narrowings:
        key = _as_str(_nw[0])
        ptr_ct = _as_str(_nw[1])
        expr = _nw[2]
        if key in saved:
            continue
        ot, ov = gen.lower_expr(expr)
        # Narrow unless the value ALREADY has exactly the guarded type.
        # `isinstance(x, T)` is positive RUNTIME evidence that x is a T for
        # the whole guarded body, so it outranks whatever static type the
        # value happens to carry — including a wrong one. This used to skip
        # any value already typed as some concrete pointer, on the theory
        # that such a type is "either right already or narrowed by an outer
        # guard"; but a loop variable mis-typed by first-decl-wins element
        # inference (`for _ms in module_stmts:` binding `FunctionDef *`
        # because an earlier loop in the same function used that name) is
        # neither. There, `elif isinstance(_ms, StructDef): for _m in
        # _ms.methods:` silently kept the WRONG struct type, so `.methods`
        # missed StructDef's field map, fell to the boxed dynamic-getattr
        # path, and the loop degraded to a runtime dict-or-list dispatch.
        # Casting to the guarded type is safe even when the prior type was
        # genuinely unrelated: the body only executes when the runtime tag
        # actually matches.
        if ot == ptr_ct:
            continue
        vp = gen._new_val('void *', f'(void *){ov}')
        cast = gen._new_val(ptr_ct, f'({ptr_ct}){vp}')
        saved[key] = gen._narrowed_exprs.get(key)
        gen._narrowed_exprs[key] = (ptr_ct, cast)
    return saved


def _restore_isinstance_narrowings(gen, saved: dict) -> None:
    for key, prior in saved.items():
        if prior is None:
            gen._narrowed_exprs.pop(key, None)
        else:
            gen._narrowed_exprs[key] = prior


def _gen_stmt_IfStmt(gen, node):
    cond_type, cond_v = gen.lower_expr(node.condition)
    cond_v  = gen._ensure_bool_cond(cond_type, cond_v)
    bb_true     = gen._new_bb()
    bb_merge    = gen._new_bb()
    # Explicit length tests, NOT `bool(node.elifs or node.else_body)` — an
    # `or` of two list attributes folds to a falsy int64_t on the
    # self-hosted compiled path even when a list is non-empty, so an
    # `if: ... elif: ...` with no `else:` mis-computed `has_else = False`,
    # aimed the main condition's false-edge straight at bb_merge and
    # never tested the elif at all.
    _n_elifs = len(node.elifs) if node.elifs else 0
    _n_else  = len(node.else_body) if node.else_body else 0
    has_else    = _n_elifs > 0 or _n_else > 0
    bb_false    = gen._new_bb() if has_else else bb_merge

    # `bb_merge` is reachable via a condition's false-edge unless a real
    # `else:` block consumes the last one; otherwise only a
    # non-terminating branch body keeps it live.
    _merge_reachable = _n_else == 0

    gen._emit(f"  if ({cond_v}) goto {bb_true}; else goto {bb_false};")
    gen._emit_label(bb_true)
    _narrowed = gen._apply_isinstance_narrowings(node.condition)
    for s in node.then_body:
        gen.gen_stmt(s)
    gen._restore_isinstance_narrowings(_narrowed)
    # No `goto {bb_merge}` when the body already ended in `return`/`goto`:
    # a dead `goto` after `return` is not just noise — when GCC INLINES
    # this function it can follow that trailing `goto` (to the next
    # isinstance check) instead of the return, so a branch that computed
    # the right answer falls through to a later `return set()`. This is
    # exactly why the self-hosted `_used_idents_node` returned an empty
    # set for a closure body once it got inlined into `_scan_for_closures`.
    if not gen._last_was_terminal:
        gen._emit(f"  goto {bb_merge};")
        _merge_reachable = True

    current_false = bb_false
    elifs = list(node.elifs)
    _ei = 0
    while _ei < len(elifs):
        ec, eb = elifs[_ei]
        _ei += 1
        gen._emit_label(current_false)
        has_more   = (len(elifs) - _ei) > 0 or _n_else > 0
        next_false = gen._new_bb() if has_more else bb_merge
        next_true  = gen._new_bb()
        ec_t, ev = gen.lower_expr(ec)
        # Apply the same truthiness conversion as the main condition — the
        # elif branch used to skip _ensure_bool_cond, so a char* elif
        # (`elif result_var:` in _emit_call) compiled to a RAW POINTER
        # truthiness test (`if (result_var)`), treating the empty string ""
        # as truthy and emitting `  = call (...)` with an empty LHS (the
        # list_ops/list_append corruption).
        ev = gen._ensure_bool_cond(ec_t, ev)
        gen._emit(f"  if ({ev}) goto {next_true}; else goto {next_false};")
        gen._emit_label(next_true)
        _elif_narrowed = gen._apply_isinstance_narrowings(ec)
        for s in eb:
            gen.gen_stmt(s)
        gen._restore_isinstance_narrowings(_elif_narrowed)
        if not gen._last_was_terminal:
            gen._emit(f"  goto {bb_merge};")
            _merge_reachable = True
        current_false = next_false

    if _n_else > 0:
        gen._emit_label(current_false)
        for s in node.else_body:
            gen.gen_stmt(s)
        if not gen._last_was_terminal:
            gen._emit(f"  goto {bb_merge};")
            _merge_reachable = True

    if _merge_reachable:
        gen._emit_label(bb_merge)
        gen._last_was_terminal = False
    else:
        # Every branch returned/jumped — anything the caller emits after
        # this `if` is unreachable. Drop the orphan `bb_merge` label
        # (GIMPLE rejects a label with no predecessors) and let the
        # caller's own `_last_was_terminal` handling suppress dead code.
        gen._last_was_terminal = True


def _gen_stmt_DelStmt(gen, node):
    """`del a[b]`, `del a[b:c]`, `del a[b], c[d]` — one DelStmt per
    statement, node.targets holding each comma-separated target (see
    fire_compiler.py's DelStmt docstring).

    Previously COMPLETELY unimplemented: gen_stmt's dispatch chain had
    no DelStmt case at all, so it silently fell through to the generic
    "unknown statement dropped" fallback (a bare `/* TODO */` comment,
    no-op). This was flat-out WRONG, not just incomplete, for
    fire_compiler.py's own `_process_nested_tstrings`: its
    `del result[-len(prefix):]` (removing a stray prefix character
    already appended to `result` char-by-char before the scanner
    realized it was actually part of a string literal's prefix) never
    ran once self-hosted, so that prefix character stayed in `result`
    AND the string-with-its-own-prefix got appended right after it —
    e.g. an f-string literal came out as `ff"..."` (the leading `f`
    duplicated) in every self-hosted-compiled program, not just this
    compiler's own source. Root-caused chasing `make bootstrap`'s
    `verify` byte-identity failures back to actual token-level
    corruption (confirmed via a minimal 3-line repro dumped through a
    freshly-built stage2/mojo).

    Only `del container[key-or-slice]` is implemented (list index/slice,
    dict key, or — when the container's real type isn't known until
    runtime, e.g. myinterpreter.py's own generic `del obj[idx]` in
    execute_DelStmt — a runtime dispatch on the actual object, mirroring
    _gen_for_iter's identical boxed-int64_t dict-vs-list dispatch). Bare
    `del name` / `del obj.attr` are NOT reachable anywhere in this
    codebase's own self-hosted closure (grep-confirmed across
    fire_compiler.py/myinterpreter.py/fire.py/mojo_main.py/
    module_loader.py/generated_dispatch.py) and would need much
    broader "this variable/attribute can become undefined" plumbing to
    support correctly in a compiled — not interpreted — target; left as
    an explicit, logged gap rather than silently doing nothing for them
    specifically.
    """
    for target in node.targets:
        # A bare single-slice subscript (`x[a:b]`) parses as a SliceExpr
        # with .obj attached directly, NOT wrapped in a SubscriptExpr —
        # see fire_compiler.py's own `_parse_postfix`: "if len(items) ==
        # 1: if isinstance(only, SliceExpr): only.obj = expr; expr =
        # only" (a single non-slice index DOES still wrap in
        # SubscriptExpr — that path is unaffected). `del result[-len(
        # prefix):]` (this method's own motivating bug) takes exactly
        # this bare-SliceExpr shape, so it must be checked before (not
        # inside) the SubscriptExpr branch below.
        if isinstance(target, gimple_ctypes.SliceExpr):
            ot, ov = gen.lower_expr(target.obj)
            start_v, stop_v = gen._lower_slice_bounds(target)
            # Only lists support slice deletion (a dict has no notion of
            # a slice) — an ambiguous/untracked boxed value is assumed to
            # be a list here, mirroring _lower_slice's own MojoList*
            # branch reasoning for the same ambiguity.
            lp = ov if ot == 'MojoList *' else gen._coerce_to_type(
                'int64_t', 'MojoList *', gen._to_int64(ot, ov))
            gen._emit(f"  mojo_list_del_slice ({lp}, {start_v}, {stop_v});")
            continue
        if not isinstance(target, gimple_ctypes.SubscriptExpr):
            gimple_ctypes._debug_note('DelStmt target not supported (only container[key]/[slice])',
                        type(target).__name__)
            gen._emit(f"  /* TODO: del {type(target).__name__} not supported */")
            continue
        ot, ov = gen.lower_expr(target.obj)
        if isinstance(target.index, gimple_ctypes.SliceExpr):
            start_v, stop_v = gen._lower_slice_bounds(target.index)
            lp = ov if ot == 'MojoList *' else gen._coerce_to_type(
                'int64_t', 'MojoList *', gen._to_int64(ot, ov))
            gen._emit(f"  mojo_list_del_slice ({lp}, {start_v}, {stop_v});")
            continue
        if ot == 'MojoBytes *':
            # `del ba[i]` — bytearray element removal.
            idx_type, idx_val = gen.lower_expr(target.index)
            idx64 = gen._to_int64(idx_type, idx_val)
            gen._emit(f"  mojo_bytearray_delitem ({ov}, {idx64});")
            continue
        if ot == 'MojoDict *':
            key_type, key_val = gen.lower_expr(target.index)
            key_type, key_val = gen._char_to_cstr(key_type, key_val, True, True)
            # `del d[k]` — a removal whose VALUE is discarded, so the
            # absent-box default (0) is the whole answer it needs from the
            # new `dflt` parameter `d.pop(k, default)` requires.
            gen._emit_call('int64_t', '', 'mojo_dict_pop_int',
                             [('MojoDict *', ov), (key_type, key_val),
                              ('int64_t', '0')])
        elif ot == 'MojoList *':
            idx_type, idx_val = gen.lower_expr(target.index)
            idx64 = gen._to_int64(idx_type, idx_val)
            # mojo_list_delitem, not mojo_list_pop_at: `del t[0]` and
            # `t.pop(0)` remove the same slot but are different Python
            # operations, and CPython refuses them differently on a tuple
            # (TypeError "doesn't support item deletion" vs AttributeError
            # "has no attribute 'pop'"). See mojo_list_delitem's definition.
            gen._emit_call('int64_t', '', 'mojo_list_delitem',
                             [('MojoList *', ov), ('int64_t', idx64)])
        elif ot in ('int', 'int64_t', 'void *'):
            # Fully dynamic: the container's real type isn't known until
            # runtime (e.g. myinterpreter.py's `del obj[idx]`, where
            # `obj` is whatever value the INTERPRETED program's own
            # runtime object happens to be) — dispatch on the actual
            # object, mirroring _gen_for_iter's identical boxed-int64_t
            # "for x in <unknown container>:" dict-vs-list branch.
            it64 = gen._to_int64(ot, ov)
            bb_dict = gen._new_bb(); bb_not_dict = gen._new_bb()
            bb_list = gen._new_bb(); bb_after = gen._new_bb()
            isd = gen._call_expr('int', 'mojo_is_registered_dict', [('int64_t', it64)])
            gen._emit(f"  if ({isd}) goto {bb_dict}; else goto {bb_not_dict};")
            gen._emit_label(bb_not_dict)
            isl = gen._call_expr('int', 'mojo_is_registered_list', [('int64_t', it64)])
            gen._emit(f"  if ({isl}) goto {bb_list}; else goto {bb_after};")
            gen._emit_label(bb_dict)
            dp = gen._coerce_to_type('int64_t', 'MojoDict *', it64)
            dkey_type, dkey_val = gen.lower_expr(target.index)
            dkey_type, dkey_val = gen._char_to_cstr(dkey_type, dkey_val, True, True)
            gen._emit_call('int64_t', '', 'mojo_dict_pop_int',
                             [('MojoDict *', dp), (dkey_type, dkey_val),
                              ('int64_t', '0')])
            gen._emit(f"  goto {bb_after};")
            gen._emit_label(bb_list)
            lp = gen._coerce_to_type('int64_t', 'MojoList *', it64)
            lidx_type, lidx_val = gen.lower_expr(target.index)
            lidx64 = gen._to_int64(lidx_type, lidx_val)
            # mojo_list_delitem, matching the statically-typed branch above
            # — this is still `del x[i]`, not `x.pop(i)`.
            gen._emit_call('int64_t', '', 'mojo_list_delitem',
                             [('MojoList *', lp), ('int64_t', lidx64)])
            gen._emit(f"  goto {bb_after};")
            gen._emit_label(bb_after)
        else:
            gimple_ctypes._debug_note('DelStmt subscript on unsupported container type', ot)
            gen._emit(f"  /* TODO: del on {ot} not supported */")


def _gen_stmt_MatchStmt(gen, node):
    """`match subject: case p1: ... case p2, p3: ... case _: ...`

    Switch-style equality dispatch (see fire_compiler.py's MatchStmt
    docstring for why this isn't full structural pattern matching):
    lowered as a chain of `if (subject == p1 | subject == p2 | ...)`
    checks, reusing the existing `==` lowering (_lower_BinaryOp already
    knows how to compare strings via mojo_str_eq/strcmp vs. plain value
    equality for everything else) rather than duplicating that type
    dispatch here. The subject is lowered exactly once, up front, into a
    temp — each pattern comparison references that temp via a synthetic
    IdentExpr rather than re-lowering `node.subject`, since re-lowering
    would re-evaluate it (with side effects) once per pattern."""
    subj_type, subj_v = gen.lower_expr(node.subject)
    subj_ref = gimple_ctypes.IdentExpr(name=subj_v)

    bb_merge = gen._new_bb()
    case_bbs = [gen._new_bb() for _ in node.cases]
    next_check_bb = gen._new_bb() if node.cases else bb_merge
    gen._emit(f"  goto {next_check_bb};")
    for i, match_case in enumerate(node.cases):
        gen._emit_label(next_check_bb)
        has_more = i + 1 < len(node.cases)
        next_check_bb = gen._new_bb() if has_more else bb_merge

        # An explicit loop, NOT `any(isinstance(p, IdentExpr) and
        # p.name == '_' for p in match_case.patterns)`: `pattern` elements
        # are heterogeneous Expr nodes with no tracked element type, so the
        # element binds as a bare int64_t — for which `isinstance` emits a
        # REAL `mojo_read_type_tag` check (unlike the constant-false
        # `isinstance(<char *>, ...)` static guard). The generator-
        # comprehension form instead materialized an empty list plus
        # `mojo_list_any` (`/* TODO: comprehension over int64_t */`), i.e.
        # always False, which emitted `case _:` as `case 0:` on the
        # self-hosted path (native vs python3 `--dump match_stmt.mojo`).
        is_wildcard = False
        for _wp in match_case.patterns:
            if isinstance(_wp, gimple_ctypes.IdentExpr) and _wp.name == '_':
                is_wildcard = True
                break
        if is_wildcard:
            # A bare `_Bool x; x = 1;` is a "non-trivial conversion" under
            # -fgimple's strict mode (an int constant assigned straight
            # into a _Bool isn't automatically allowed, unlike normal C).
            # `_lower_BoolLiteral` sidesteps this the same way: type the
            # temp as plain `int` (a same-type, always-trivial `int = 1`
            # assignment) rather than `_Bool` — used below only as an
            # `if (...)` condition or combined via `_ensure_bool_cond`,
            # both of which accept a plain int fine (see BUG-2026-017,
            # found via cpp_parser's `match name: ... case _:` wildcard).
            match_bool = gen._new_temp('int')
            gen._emit(f"  {match_bool} = 1;")
        else:
            match_bool = None
            for p in match_case.patterns:
                ct, cv = gen.lower_expr(gimple_ctypes.BinaryOp(op='==', left=subj_ref, right=p))
                cv = gen._ensure_bool_cond(ct, cv)
                if match_bool is None:
                    match_bool = cv
                else:
                    combined = gen._new_temp('_Bool')
                    gen._emit(f"  {combined} = {match_bool} | {cv};")
                    match_bool = combined
        if match_case.guard is not None:
            gt, gv = gen.lower_expr(match_case.guard)
            gv = gen._ensure_bool_cond(gt, gv)
            # match_bool is plain `int` for the wildcard branch above,
            # `_Bool` otherwise — coerce before combining so `combined`
            # (declared `_Bool`) is only ever assigned a real `_Bool`
            # value, not a mixed int/_Bool bitwise-AND result (the same
            # "non-trivial conversion" trap the wildcard fix addresses).
            match_bool = gen._ensure_bool_cond('int' if is_wildcard else '_Bool', match_bool)
            combined = gen._new_temp('_Bool')
            gen._emit(f"  {combined} = {match_bool} & {gv};")
            match_bool = combined
        gen._emit(f"  if ({match_bool}) goto {case_bbs[i]}; else goto {next_check_bb};")

    for i, match_case in enumerate(node.cases):
        gen._emit_label(case_bbs[i])
        for s in match_case.body:
            gen.gen_stmt(s)
        gen._emit(f"  goto {bb_merge};")

    gen._emit_label(bb_merge)


def _gen_stmt_WhileStmt(gen, node):
    bb_cond  = gen._new_bb()
    bb_body  = gen._new_bb()
    bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_type, cond_v = gen.lower_expr(node.condition)
    cond_v = gen._ensure_bool_cond(cond_type, cond_v)
    gen._emit(f"  if ({cond_v}) goto {bb_body}; else goto {bb_after};")
    gen._loop_depth += 1
    gen._emit_label(bb_body, f'count(guessed_local({10 ** gen._loop_depth}))')
    gen.loop_stack.append((bb_cond, bb_after))
    gen._gen_loop_body(node.body)
    gen.loop_stack.pop()
    gen._loop_depth -= 1
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_stmt_MultiAssignStmt(gen, node):
    vtype, v = gen.lower_expr(node.value)
    for target in node.targets:
        if isinstance(target, gimple_ctypes.IdentExpr):
            tname = target.name
            # A chained assignment's IdentExpr target(s) can be a real
            # GLOBAL exactly like _gen_stmt_AssignStmt's single-target
            # case (either via an explicit `global x` inside a real
            # function, or as a genuine module-level/script statement
            # during _gen_toplevel) — this loop used to treat EVERY
            # IdentExpr target as a plain local unconditionally,
            # regardless of whether Phase 1.7/the global-declaration
            # scan already knows it's a real module global. That was
            # silently "safe" only by accident, back when a chained-
            # assignment-only global was invisible to those scans too
            # (so nothing else expected it to be a global either) —
            # now that both scans recognize such globals (see
            # bugs/hard/CODEGEN_multi_assign_local_var_type_not_
            # inferred.md), skipping this check meant a global boxed
            # as int64_t at the C level (e.g. a MojoDict*/MojoList*
            # global not in _dispatch_names) got its real pointer
            # value written into a plain LOCAL variable declared
            # straight as the semantic pointer type instead of the
            # struct field's actual boxed-int64_t C type — "assignment
            # to 'int64_t' from 'MojoDict *' makes integer from
            # pointer without a cast" at the field's OTHER (correctly-
            # routed) write/read sites, or a value invisible to any
            # other function reading the same name as a global.
            # Mirrors _gen_stmt_AssignStmt's own two global-write
            # branches exactly (same field-ref construction, same
            # _global_c_decl_types coercion, same dict/list/actual-type
            # propagation), falling back to the ordinary local-variable
            # path below only when neither applies. Always targets THIS
            # module's own struct directly (self._current_module_ctx),
            # not `_global_to_module.get(tname)` — see
            # _gen_stmt_AssignStmt's identical branch for why.
            if (((tname in gen._func_declared_globals
                    or (tname not in gen.var_types
                        and getattr(gen, '_global_to_module', {}).get(tname) in (
                            None, (gen.module_name if len(gen.module_name) > 0 else "root")))))
                    and tname in gen._global_var_types):
                # Same BUG-2026-018 interpreter-parity extension as
                # _gen_stmt_AssignStmt's branch above (un-shadowed bare-name
                # writes to this module's own globals land on the globals
                # struct, matching both the IdentExpr read path and the
                # interpreter's dynamic scope chain).
                safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
                field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(tname)}"
                gtype = gen._global_dst_ctype(tname)
                gen._safe_coerce_emit(vtype, gtype, v, field_ref)
                if vtype == 'MojoDict *':
                    if v in gen._dict_val_types:
                        gen._dict_val_types[tname] = gen._dict_val_types[v]
                        if v in gen._dict_nested_val_types:
                            gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
                elif vtype == 'MojoList *':
                    if v in gen._elem_types:
                        gen._elem_types[tname] = gen._elem_types[v]
                        if v in gen._nested_elem_types:
                            gen._nested_elem_types[tname] = gen._nested_elem_types[v]
                continue
            if gen._in_toplevel_gen and tname in gen._global_var_types:
                safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
                field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(tname)}"
                gtype = gen._global_dst_ctype(tname)
                gen._safe_coerce_emit(vtype, gtype, v, field_ref)
                if vtype == 'MojoDict *':
                    if v in gen._dict_val_types:
                        gen._dict_val_types[tname] = gen._dict_val_types[v]
                        if v in gen._dict_nested_val_types:
                            gen._dict_nested_val_types[tname] = gen._dict_nested_val_types[v]
                elif vtype == 'MojoList *':
                    if v in gen._elem_types:
                        gen._elem_types[tname] = gen._elem_types[v]
                        if v in gen._nested_elem_types:
                            gen._nested_elem_types[tname] = gen._nested_elem_types[v]
                if vtype.endswith(' *') and v in gen._actual_types:
                    gen._actual_types[tname] = gen._actual_types[v]
                elif v in gen._actual_types:
                    gen._actual_types[tname] = gen._actual_types[v]
                continue
            if tname not in gen.var_types:
                # Same whole-body-type hint _assign_target already consults
                # for a single-target assignment's first declaration: this
                # function-wide pre-pass joins the types of EVERY assignment
                # to this name, so a chained `CRC = compress_size =
                # file_size = 0` whose later statements reassign a wider
                # value (`file_size = 0xffffffff`, ZipInfo.FileHeader)
                # declares the locals int64_t instead of the bare RHS
                # literal's C `int` -- which -fgimple then rejects outright
                # ("non-trivial conversion in 'integer_cst'") at the wider
                # reassignment rather than silently truncating. Declaring
                # from the raw RHS type here (ignoring the hint) was exactly
                # the drift bugs/hard/CODEGEN_multi_assign_local_var_type_
                # not_inferred.md's single-target fix predated.
                hint = gen._inferred_var_types.get(gen.current_func_name, {}).get(tname) \
                    if hasattr(gen, '_inferred_var_types') else None
                gen._declare_var(tname, hint or vtype)
            dst = gen.var_types[tname]
            gen._safe_coerce_emit(vtype, dst, v, gen._write_dest(tname))
        elif isinstance(target, gimple_ctypes.MemberExpr):
            ot, ov = gen.lower_expr(target.obj)
            # `cls.__slot_names__ = value` etc. as ONE of a chained
            # assignment's targets (`slotnames = cls.__slot_names__ =
            # []`) — mirrors _gen_stmt_AssignStmt's single-target
            # MemberExpr branch's own opaque-object/fixed-runtime-
            # struct dispatch (bugs/hard/CODEGEN_dynamic_attribute_on_
            # generic_object.md): this loop previously had NEITHER
            # check at all, so a chained assignment onto an opaque
            # `cls`/`self` value (Sub-case A/B) or a fixed-layout
            # runtime struct like MojoBoundMethod (Sub-case C) always
            # fell straight to the raw `->field = v` write below,
            # regardless of `ot` — confirmed via this doc's own minimal
            # repro (`slotnames = cls.__slot_names__ = []`, a chained
            # assignment), which reached exactly this path.
            if ot in ('int', 'int64_t', 'void *'):
                member_str = target.member
                key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
                key_tmp = gen._new_val('char *', f"{key_slit}")
                v64 = gen._new_temp('int64_t')
                gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
                obj64 = gen._to_int64(ot, ov)
                vp_tmp = gen._new_val('void *', f"(void *){obj64}")
                gen._emit_call('void', '', '_mojo_dispatch_setattr',
                                [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
                continue
            sn = gimple_exprtypes._struct_name_of(ot)
            if (sn in gimple_ctypes._FIXED_RUNTIME_STRUCT_NAMES
                    and target.member not in gen.struct_field_types.get(sn, {})):
                member_str = target.member
                key_slit = gen._intern_string(gimple_ctypes._c_escape(member_str))
                key_tmp = gen._new_val('char *', f"{key_slit}")
                v64 = gen._new_temp('int64_t')
                gen._safe_coerce_emit(vtype, 'int64_t', v, v64)
                obj64 = gen._to_int64(ot, ov)
                vp_tmp = gen._new_val('void *', f"(void *){obj64}")
                gen._emit_call('void', '', '_mojo_dispatch_setattr',
                                [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
                continue
            if gen._is_except_as_member_target(target.obj):
                # Chained-assignment analogue (`slotnames = err.filename
                # = value`) of the caught-exception-object case in
                # _gen_stmt_AssignStmt — see
                # `_is_except_as_member_target`/`self._except_as_names`.
                gen._emit_dynattr_setattr_dispatch(target.member, vtype, v, ot, ov)
                continue
            op = '->' if '*' in ot else '.'
            # Coerce to the field's real declared C type (mirrors
            # _gen_stmt_AssignStmt's single-target MemberExpr branch just
            # above) instead of emitting a raw, uncoerced `->field = v`.
            # A chained assign to a struct field whose declared type
            # differs from the RHS's type (e.g. `self.k = self.ck =
            # compile_keymap(...)` where the field is boxed as a
            # generic 'int' but the call result is int64_t/a pointer)
            # otherwise produces a direct type-mismatched store that
            # gcc's -fgimple frontend rejects outright ("invalid
            # conversion in gimple call"/assignment) — not merely a
            # warning, a hard compile failure.
            field_type = gen.struct_field_types.get(sn, {}).get(target.member, vtype)
            gen._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{gimple_ctypes._safe_field(target.member)}")
        elif isinstance(target, gimple_ctypes.SubscriptExpr):
            ot, obj_v = gen.lower_expr(target.obj)
            it2, idx_v = gen.lower_expr(target.index)
            if ot == 'MojoList *':
                elem = gen._elem_of(obj_v)
                suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
                idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
                ev_cast = gen._cast_for_list(vtype, v, suf)
                gen._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
            elif ot == 'MojoDict *':
                _, key_tmp = gen._char_to_cstr(it2, idx_v, True, True)
                gen._emit_dict_int_value_store(obj_v, 'char *', key_tmp,
                                              vtype, v, node.value)
            elif ot in ('int', 'int64_t'):
                actual_type = gen._get_actual_type(ot, obj_v)
                # Same read/write-symmetry rule as the other two subscript
                # stores in this file (see the AssignStmt branch's comment):
                # an opaque container is a dict only when its resolved type
                # says so or the KEY is string-shaped, never merely because
                # the container's type is unknown.
                _idx_is_str2 = (it2 in ('char *', 'MojoStr *')
                                or gen._get_actual_type(it2, idx_v) == 'char *')
                if not (actual_type == 'MojoDict *'
                        or (_idx_is_str2 and actual_type not in ('MojoList *', 'MojoSet *'))):
                    ip = gen._new_temp('int64_t')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    lp = gen._coerce_to_type('int64_t', 'MojoList *', ip)
                    idx64 = gen._new_val('int64_t', f"(int64_t){idx_v}")
                    elem = gen._elem_of(obj_v) or 'int64_t'
                    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
                    ev_cast = gen._cast_for_list(vtype, v, suf)
                    gen._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {ev_cast});")
                else:
                    ip = gen._new_temp('int64_t')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    dp = gen._coerce_to_type('int64_t', 'MojoDict *', ip)
                    _, key_tmp2 = gen._char_to_cstr(it2, idx_v, True, True)
                    gen._emit_dict_int_value_store(dp, 'char *', key_tmp2,
                                                  vtype, v, node.value)
            elif ot.endswith(' *') and gimple_exprtypes._struct_name_of(ot) not in gen.struct_field_types:
                # Raw C pointer: use _mojo_at_ helper (GIMPLE doesn't allow
                # ptr arithmetic) — mirrors _gen_stmt_AugAssignStmt's
                # equivalent branch, which this one was missing entirely,
                # falling through to plain (invalid in strict GIMPLE)
                # subscript syntax for a genuine buffer pointer (e.g.
                # `buf[i] = src[i] = 2` once alloc[UInt8] correctly
                # returns uint8_t * instead of a boxed int64_t).
                if not gen._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                    elem_t = gimple_ctypes._elem_type(ot)
                    cn = gimple_ctypes._c_id(elem_t)
                    gen._ptr_helpers_needed.add(elem_t)
                    idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
                    ptr_t = gen._new_val(ot, f"({ot}){obj_v}")
                    addr = gen._new_val(ot, f"_mojo_at_{cn} ({ptr_t}, {idx64})")
                    v_cast = gen._new_temp(elem_t)
                    gen._safe_coerce_emit(vtype, elem_t, v, v_cast)
                    gen._emit(f"  *{addr} = {v_cast};")
            elif not gen._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                gen._emit(f"  {obj_v}[{idx_v}] = {v};")
        else:
            pass  # complex multi-assign target: no-op


def _gen_stmt_ForStmt(gen, node):
    # A PARENTHESISED SINGLE NAME — `for (a) in b:` — is one binding, spelled
    # `'(a)'` by the parser, while the 1-tuple `for (a,) in b:` is `'(a,)'` and
    # DOES unpack (fire_compiler.py's "Unpacking-target representation"; see
    # CODEGEN_for_loop_target_one_tuple_vs_paren_single_name). Peel the
    # redundant parens HERE, once, so every `_gen_for_*` below — and every
    # `_declare_var` they call — sees a bare C identifier for a one-name
    # target.
    #
    # Normalizing at the entry rather than in each lowering is the point: each
    # of them used to answer "is this target a group?" with its own
    # `startswith('(')` test, and that test cannot see the trailing comma, so
    # it read `for (a,) in ...` as a one-name target too. With the parens gone
    # by the time they run, `for_target_is_tuple` is the only thing any of them
    # has to know, and it is the one that knows about the comma.
    #
    # Idempotent, so a module compiled twice (as an import and again inline)
    # lands on the same target both times.
    if isinstance(node.target, str) and not gimple_ctypes.for_target_is_tuple(node.target):
        node.target = gimple_ctypes.for_target_single_name(node.target)
    # `for i in reversed(range(...))` — rewrite to an equivalent descending
    # `range(...)` ForStmt and take the fast integer-loop path, instead of
    # `_lower_builtin_reversed` (which only materializes list/str/bytes and
    # otherwise refuses — `range` isn't a first-class value here). Covers
    # `reversed(range(n))` / `reversed(range(a, b))` and the step==1
    # 3-arg form; any other step falls through to the generic path.
    _riter = node.iterable
    if (isinstance(_riter, gimple_ctypes.CallExpr)
            and isinstance(_riter.func, gimple_ctypes.IdentExpr)
            and _riter.func.name == 'reversed'
            and not gen._locally_binds_name('reversed')
            and len(_riter.args) == 1
            and isinstance(_riter.args[0], gimple_ctypes.CallExpr)
            and isinstance(_riter.args[0].func, gimple_ctypes.IdentExpr)
            and _riter.args[0].func.name == 'range'):
        _rng = _riter.args[0]
        _IL = gimple_ctypes.IntLiteral
        _BO = gimple_ctypes.BinaryOp
        # `-1` as UnaryOp('-', IntLiteral(1)), NOT IntLiteral(-1): _gen_for_range
        # explicitly special-cases the UnaryOp form for a negative step, and a
        # bare negative IntLiteral lowers to invalid `-fgimple` C ("expected
        # expression before '-' token" / "non-trivial conversion in integer_cst").
        _neg1 = lambda: gimple_ctypes.UnaryOp('-', _IL(1))
        _minus1 = lambda e: _BO('-', e, _IL(1))
        _ra = _rng.args
        _new_args = None
        if len(_ra) == 1:
            _new_args = [_minus1(_ra[0]), _neg1(), _neg1()]
        elif len(_ra) == 2:
            _new_args = [_minus1(_ra[1]), _minus1(_ra[0]), _neg1()]
        elif len(_ra) == 3 and isinstance(_ra[2], gimple_ctypes.IntLiteral) and _ra[2].value == 1:
            _new_args = [_minus1(_ra[1]), _minus1(_ra[0]), _neg1()]
        if _new_args is not None:
            _desc = gimple_ctypes.ForStmt(
                node.target,
                gimple_ctypes.CallExpr(gimple_ctypes.IdentExpr('range'), _new_args),
                node.body,
                getattr(node, 'else_body', None))
            gen._gen_for_range(_desc)
            return
    if (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.IdentExpr) and
            node.iterable.func.name == 'range'):
        gen._gen_for_range(node)
    elif (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.IdentExpr) and
            node.iterable.func.name == 'enumerate'):
        gen._gen_for_enumerate(node)
    elif (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.IdentExpr) and
            node.iterable.func.name == 'zip' and
            not gen._locally_binds_name('zip')):
        # Transactional, same pattern as the zip_longest attempt below: any
        # shape `_gen_for_zip` can't prove supported raises, we roll back
        # whatever it emitted, and fall through to the generic path.
        body_mark, decls_mark = len(gen.body_lines), len(gen.decls)
        try:
            gen._gen_for_zip(node)
            return
        except Exception as e:
            del gen.body_lines[body_mark:]
            del gen.decls[decls_mark:]
            gimple_ctypes._debug_note('zip lowering failed, falling back', e)
        gen._gen_for_iter(node)
    elif (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.MemberExpr) and
            node.iterable.func.member == 'zip_longest' and
            isinstance(node.iterable.func.obj, gimple_ctypes.IdentExpr) and
            node.iterable.func.obj.name == 'itertools' and
            not gen._locally_binds_name('itertools')):
        # Transactional: roll back any partially-emitted lines/decls if the
        # shape turns out unsupported partway, then fall through to the
        # pre-existing generic path unchanged (same pattern as
        # _gen_for_iter's regex-finditer attempt above).
        body_mark, decls_mark = len(gen.body_lines), len(gen.decls)
        try:
            gen._gen_for_zip_longest(node)
            return
        except Exception as e:
            del gen.body_lines[body_mark:]
            del gen.decls[decls_mark:]
            gimple_ctypes._debug_note('zip_longest lowering failed, falling back', e)
        gen._gen_for_iter(node)
    else:
        gen._gen_for_iter(node)


def _loop_continue_bb(gen) -> str:
    """The innermost loop's continue target (basic-block label). The `->
    str` return annotation is load-bearing for the self-hosted compiler:
    `loop_stack`'s `(str, str)` tuple element type does not survive the
    struct-field `.append`, so a bare `loop_stack[-1][0]` read is typed
    int64_t and an f-string interpolation of it emits the label pointer's
    integer value (`goto 37359235440;`). Coercing on return through this
    declared `char *` restores it — the label really is a char* string."""
    return gen.loop_stack[-1][0]


def _loop_break_bb(gen) -> str:
    """The innermost loop's break target — see `_loop_continue_bb`."""
    return gen.loop_stack[-1][1]


def _emit_try_loop_exit_exc_pops(gen) -> None:
    """Everything a `break`/`continue` owes the `try` regions it jumps out
    of: one `mojo_exc_pop()` per exited protected region, plus that region's
    `finally` body when it has one.

    A `try` counts when its entry `len(loop_stack)` is >= the current depth
    (the loop it jumps out of was already open at try-entry; a loop opened
    INSIDE the try stays put and needs no pop). Replaces the
    `gen._emit = intercepted_emit` nested closure in `_gen_stmt_TryStmt`,
    which the self-hosted backend did not run — `mojo.mojo`'s REPL loop
    silently lost the `mojo_exc_pop()` before a `break`/`continue` inside a
    `try`.

    The `finally` hop is the other half of real Python's rule that a
    `finally` runs on EVERY way out of the `try` — including `break` and
    `continue`. It was missing: `for i in ...: try: ... break ...
    finally: release()` skipped the release entirely, and the pop-only
    behavior is why `g.close()`-style cleanup vanished on that path too.
    Emitted AFTER all the pops (so an exception raised by a `finally` body
    propagates outward rather than being caught by the `try` it is leaving,
    matching CPython) and innermost-region-first (nested `try`/`finally`
    blocks unwind inside-out)."""
    if not gen.loop_stack:
        return
    _npops = 0
    _exited: list = []
    _depth = len(gen.loop_stack)
    for _i, _d in enumerate(gen._try_loop_protect):
        if _depth <= _d:
            _npops += 1
            _exited.append(_i)
    for _i in range(_npops):
        gen._emit("  mojo_exc_pop ();")
    # Innermost first: the regions are recorded outermost-first.
    _bodies = getattr(gen, '_try_finally_bodies', None) or []
    for _i in reversed(_exited):
        if _i < len(_bodies) and _bodies[_i]:
            for _s in _bodies[_i]:
                gen.gen_stmt(_s)


def _gen_stmt_BreakStmt(gen, node):
    if gen.loop_stack:
        ginf.emit_loop_exit_frees(gen)
        _emit_try_loop_exit_exc_pops(gen)
        gen._emit(f"  goto {gen._loop_break_bb()};")
    else:
        # Skip emitting comment to avoid GIMPLE global-passing issues
        pass


def _gen_stmt_ContinueStmt(gen, node):
    if gen.loop_stack:
        ginf.emit_loop_exit_frees(gen)
        _emit_try_loop_exit_exc_pops(gen)
        gen._emit(f"  goto {gen._loop_continue_bb()};")
    else:
        # Skip emitting comment to avoid GIMPLE global-passing issues
        pass


def _gen_stmt_ExprStmt(gen, node):
    if isinstance(node.value, gimple_ctypes.CallExpr) and isinstance(node.value.func, gimple_ctypes.IdentExpr):
        raw_name = gen._ident_call_name(node.value.func)
        # A bare, value-discarding call to an offloaded DEVICE function.
        # This handler has its own fast path for statement-position calls and
        # never reaches _lower_call, so without this the launch hook only
        # fired for calls in value position and the ordinary
        # `kernel(a, b, out, n)` line silently became a weak stub call.
        if raw_name in getattr(gen, '_device_kernels', ()):
            ggc._lower_device_launch(gen, node.value)
            return
        if raw_name == 'print':
            gen._gen_print(node.value.args, node.value.kwargs)
            return
        # `fut.add_done_callback(cb)` / `.remove_done_callback(cb)` as a
        # bare statement (the async-body hook in gimple_gen_coro lowers
        # the method call to this 2-arg `__mojo_future_*` shim call). The
        # generic call-building path below would pad the missing 3rd
        # argument (the callable-kind tag) with a literal 0, mis-invoking
        # a bound-method / closure callback as a bare function pointer.
        # Route to the shared handler that derives the tag from the
        # lowered C type of the callback value -- the statement-level twin
        # of _lower_call's identical interception.
        if (raw_name in ('__mojo_future_add_done_callback',
                         '__mojo_future_remove_done_callback')
                and len(node.value.args) == 2):
            ggc._lower_future_done_callback(gen, node.value)
            return
        # Step B: a bare, value-DISCARDING call to a supported compiled
        # async function (`f()` with no assignment/use of the result) —
        # construct (`<base>_start`) and immediately destroy, WITHOUT
        # ever calling mojo_async_schedule_ready/_run_until_complete, so
        # the coroutine is never actually scheduled and its body never
        # runs — see _lower_call's async branch (the value-CONSUMING
        # counterpart) for the full rationale; this is the one place
        # this narrow step's "calling f() must not run the body
        # immediately" correctness bar is genuinely observable from
        # Mojo source (see test_gimple_async_runner.py's laziness test).
        # A nested async closure (see the identical, value-CONSUMING
        # case in _lower_call) called as a bare, value-discarding
        # statement — same construct-then-immediately-destroy-without-
        # scheduling convention as the plain top-level async case just
        # below.
        _acl_key = (gen.current_func_name, raw_name)
        if _acl_key in gen._async_closure_api:
            handle, _vct = gen._lower_async_closure_construct(_acl_key, node.value)
            gen._emit(f"  {gen._async_closure_api[_acl_key]['base']}_destroy ({handle});")
            return
        if raw_name in gen._async_api:
            api = gen._async_api[raw_name]
            arg_pairs = [gen.lower_expr(a) for a in node.value.args]
            base = api['base']
            handle = gen._call_expr('MojoAsync *', f"{base}_start", arg_pairs)
            gen._emit(f"  {base}_destroy ({handle});")
            return
        if raw_name in ('strided_load', 'strided_store') and node.value.args:
            gen._lower_strided(node.value, store=(raw_name == 'strided_store'))
            return
        # A bare, value-discarding STRUCT-CONSTRUCTOR call
        # (`SubclassWithKwargs(newarg=1)` standing alone — test_deque.py's
        # TestSubclassWithKwargs). The generic call-building path below
        # has no constructor knowledge: it emitted the raw struct NAME as
        # if it were an ordinary function (`SubclassWithKwargs ();`), a
        # hard GIMPLE parse error ("expected expression before
        # 'SubclassWithKwargs'") since the name resolves to the struct
        # TYPE, not any function. Route through lower_expr so the value-
        # CONSUMING constructor path (_lower_struct_constructor, which
        # already handles kwargs) lowers it, discarding the instance.
        if raw_name in gen.struct_field_types:
            gen.lower_expr(node.value)
            return
        # A bare, value-discarding `len(x)` statement (e.g. the
        # `try: len(t) except TypeError: ...` type-probe idiom —
        # see Tools/unicode/gencodec.py's hexrepr()). Without this,
        # `len` fell all the way to the generic call-building path
        # below, which has no type-aware dispatch at all and just
        # calls the runtime `mojo_len` directly with the argument's
        # raw (possibly non-pointer, e.g. int64_t) type/value — "passing
        # argument 1 of 'mojo_len' makes integer from pointer without a
        # cast". `_lower_builtin_len` (the value-CONSUMING twin every
        # other `len()` call site already routes through, in
        # `_lower_call`) has the real per-type dispatch
        # (MojoStr*/MojoList*/MojoDict*/MojoSet*/char*/int64_t-widened);
        # reuse it here and simply discard its result.
        if raw_name == 'len' and len(node.value.args) == 1:
            gen._lower_builtin_len(node.value)
            return
        # A bare, value-discarding `next(g)` statement — the generator
        # protocol's "advance one step, ignore the value" spelling (e.g.
        # draining a generator toward exhaustion, or a `try: next(g)
        # except StopIteration:` probe). Same shape as the `len` case
        # above: the value-CONSUMING dispatch lives in `_lower_call`, and
        # the generic call-building path further down has no notion of the
        # generator `next` at all — it emitted a call to a `next` function
        # that exists nowhere, failing at LINK time with "Undefined
        # symbols: _next" (found via `next(g)` as a statement inside a
        # try/except StopIteration, where the enclosing `print(next(g))`
        # form worked and hid the gap).
        if (raw_name == 'next' and 1 <= len(node.value.args) <= 2
                and not gen._locally_binds_name('next')):
            gen._lower_call(node.value)
            return
        # A bare, value-discarding `list(x)` / `tuple(x)` statement
        # (e.g. `tuple(g())` used to force/drain a generator for its
        # side effects — Lib/test/crashers/gc_inspection.py). Without
        # this, `list`/`tuple` fell all the way to the generic
        # call-building path below, which maps the builtin name straight
        # to `mojo_make_list`/`mojo_make_tuple` (the 0-ARG empty-
        # container constructors, per BUILTIN_VALUE_MAP) with no regard
        # for the actual argument — "too many arguments to function
        # 'mojo_make_tuple'; expected 0, have 1". `_lower_builtin_list`
        # (the value-CONSUMING twin every other `list()`/`tuple(<=1 arg)`
        # call site already routes through at `_lower_call`'s own
        # `fname_raw in ('list', 'tuple')` check) has the real
        # iterable-conversion lowering; reuse it here and simply discard
        # its result, mirroring the identical `len` fix just above.
        if raw_name in ('list', 'tuple') and len(node.value.args) <= 1:
            gen._lower_builtin_list(node.value)
            return
        # Recursive call from inner function to itself. Bare-statement
        # twin of _lower_recursive_self_call — routed through
        # _emit_call (like the sibling-closure-call branch just below)
        # so arguments get coerced to the callee's declared param
        # types instead of passed raw. See _lower_recursive_self_call's
        # own comment for why this was a real, previously-invisible gap.
        if raw_name == gen._inner_func_name and gen._env_param:
            lifted   = gen.current_func_name
            env_var  = gen._env_param
            arg_pairs = [gen.lower_expr(a) for a in node.value.args]
            env_type = gen.func_param_types.get(lifted, ['void *'])[0]
            full_arg_pairs = [(env_type, env_var)] + arg_pairs
            fname_c  = gimple_ctypes._safe_name(lifted)
            gen._emit_call('void', '', fname_c, full_arg_pairs)
            return
        # Check closure call (nested function defined in this scope)
        if raw_name in gen._closure_envs:
            lifted   = f"{gen.current_func_name}_{raw_name}"
            env_var  = gen._closure_envs[raw_name]
            arg_pairs = [gen.lower_expr(a) for a in node.value.args]
            # Handle kwargs for closure calls
            kwargs = getattr(node.value, 'kwargs', []) or []
            kwarg_dict = {kname: gen.lower_expr(kexpr) for kname, kexpr in kwargs}
            # Pad kwargs to expected arity
            # Note: expected_params[0] is the env pointer, which gets prepended separately
            expected_params = gen.func_param_types.get(lifted, [])
            # Subtract 1 for the env pointer that will be prepended
            user_param_count = len(expected_params) - (1 if env_var and expected_params else 0)
            if expected_params and len(arg_pairs) < user_param_count:
                # Pad with the closure's own declared defaults before
                # falling back to a bare 0 -- see the registration in
                # the closure-scan pass (Pass 3) and _lower_closure_
                # call's identical padding for the expression-context
                # twin of this same call shape.
                _dflts = gen._func_param_defaults.get(lifted) or []
                while len(arg_pairs) < user_param_count:
                    _pos = len(arg_pairs)
                    _pname = _dflts[_pos][0] if _pos < len(_dflts) else None
                    if _pname is not None and _pname in kwarg_dict:
                        arg_pairs.append(kwarg_dict[_pname])
                    elif _pos < len(_dflts):
                        # See _lower_closure_call's identical choice of
                        # self.lower_expr over _default_expr_to_pair:
                        # closure defaults commonly reference the
                        # OUTER function's own live variables
                        # (`iterator=iterator`), which needs real
                        # expression lowering in the current (outer)
                        # scope, not literal-only handling.
                        arg_pairs.append(gen.lower_expr(_dflts[_pos][1]))
                    else:
                        arg_pairs.append(('int', '0'))
            fname_c  = gimple_ctypes._safe_name(lifted)
            if env_var:
                env_type = gen.func_param_types.get(lifted, ['void *'])[0]
                full_arg_pairs = [(env_type, env_var)] + arg_pairs
            else:
                full_arg_pairs = arg_pairs
            gen._emit_call('void', '', fname_c, full_arg_pairs)
            return
        # Sibling-closure call, bare-statement twin of _lower_call's
        # identical `_lambda_outer_closures` fallback a few hundred
        # lines up. `self._closure_envs` just above only covers
        # closures nested directly in THIS closure's own body -- a
        # closure calling one of its SIBLINGS (another nested `def` in
        # the same enclosing function, e.g. Lib/tokenize.py's `_main()`
        # defining both `perror()` and `error()`, with `error()` then
        # calling `perror(...)` as a bare, value-discarding statement)
        # was never checked here at all, so it fell all the way through
        # to the generic-name handling below and was emitted as a bare,
        # unqualified `perror (...)` call -- colliding with libc's own
        # `perror` (a real "conflicting types for 'perror'" GCC error;
        # for a non-colliding name it would instead silently call
        # whatever unrelated same-named symbol happens to exist, or
        # fail to link). The value-CONSUMING call path (`_lower_call`)
        # already had this fallback; this bare-statement path just
        # never got the same fix.
        _outer_ci = getattr(gen, '_lambda_outer_closures', {}).get(raw_name)
        if _outer_ci:
            # Reuse the value-CONSUMING path (`_lower_outer_closure_call`),
            # discarding the result. It forwards the callee's env — copying
            # each captured field from THIS closure's own `_env` where the
            # name matches — instead of the always-NULL env this branch used
            # to pass. Critical for mutually-recursive sibling closures that
            # share an env struct (`_infer_param_types`'s `scan_nodes`
            # calling its sibling `scan_expr` as a bare statement): a NULL
            # env there SEGV'd on the first `accessed_fields.add(...)`.
            gen._lower_outer_closure_call(raw_name, _outer_ci, node.value)
            return
        # Redirect calls to user's main() to its renamed symbol (root ->
        # _gimple_main; sub-module -> _{module}_main), matching gen_func.
        # If raw_name is a local (or captured) variable holding a function
        # value (e.g., a Mojo function-type parameter stored as int64_t),
        # calling it directly in GIMPLE is invalid — needs the same
        # mojo_fnptr_call_N() indirection _lower_call's identical guard
        # already uses via _lower_fnptr_call. This statement-level twin
        # previously only evaluated the call's ARGUMENTS (for side
        # effects) and then silently dropped the call itself — a real,
        # standalone bug (not merely "unsupported"): a bare, value-
        # discarding statement calling a captured function-type parameter
        # (e.g. `func()` as a nested closure's entire body — see
        # bugs/CODEGEN_device_context_captured_function_parameter_
        # closures_broken.md's Repro 2) silently compiled to a no-op,
        # never actually invoking the captured function at all. See
        # _lower_call's own identical guard a few hundred lines up for
        # the same fix already proven correct there.
        _var_ctype = gen.var_types.get(raw_name, '')
        # Statement-level twin of _lower_named_call's builtin-container
        # bound-method guard (`append = l.append; append(x)` with the
        # value discarded) — must precede the fnptr guard below for the
        # same reason: the boxed handle var is int64_t-declared, and the
        # fnptr path would call through an opaque getattr box. See
        # _lower_builtin_method_value / _lower_builtin_bound_method_call.
        if raw_name in gen._builtin_method_values:
            gen._lower_builtin_bound_method_call(raw_name, node.value)
            return
        if gen._get_actual_type(_var_ctype, raw_name) == 'MojoBoundMethod *':
            # A closure/bound-method VALUE stored in a local and called
            # as a bare statement — mirrors _lower_call's identical
            # guard, so `add5(37)` (value discarded) re-supplies the
            # bundled env/receiver instead of being silently dropped.
            gen._lower_bound_method_call(raw_name, node.value, _var_ctype)
            return
        # Statement-level twin of _lower_call's own membership half of
        # the fnptr guard (`fname_raw in gen.var_types`): ANY name that
        # is a local VARIABLE here — not just one whose declared type is
        # already one of the four scalar boxes — must be called through
        # mojo_fnptr_call_N, never as a bare C function named after the
        # variable. Real: Tools/wasm/wasi/__main__.py's build_steps —
        # `for step in steps: step(context)` where the generic for-iter
        # arm declared the loop var `char *` (its dict-key convention),
        # so only the ctype-list check was consulted, missed, and the
        # call fell through to a literal `step (context);` C call on a
        # char* ("invalid call to non-function before ';' token"). In
        # any VALID Python a locally-bound name called as a function IS
        # a callable value, so the indirection is semantics-preserving;
        # see _lower_call's own comment for why a misleading
        # first-decl-wins `char *` decl can't disqualify it.
        if _var_ctype in ('int', 'int64_t', 'void *', '_Bool') or raw_name in gen.var_types:
            gen._lower_fnptr_call(raw_name, _var_ctype, node.value)
            return
        # Same guard as _lower_CallExpr: don't redirect an *imported*
        # 'main' (e.g. `from foo import main; main()`) to the
        # synthesized entry point — only this module's own main.
        if (raw_name == 'main' and gen.current_func_name != 'main'
                and raw_name not in gen.imported_symbols
                and raw_name not in gen._unresolved_import_aliases):
            if gen.emit_entry_points:
                fname = gimple_ctypes._safe_name('_gimple_main')
            else:
                _mod_id = gen.module_name.replace('.', '_').replace('-', '_') if gen.module_name else ''
                fname = gimple_ctypes._safe_name(f"_{_mod_id}_main" if _mod_id else '_lib_main')
            # Mirror the identical fix in _lower_call's own copy of this
            # exact redirect guard: _emit_call below looks up expected
            # param/return types under the RENAMED key (`fname`), but
            # they were only ever registered under 'main' itself — so
            # without this, `func_param_types.get(fname)` returned None,
            # _emit_call had nothing to coerce arguments against, and a
            # pointer argument (e.g. a MojoList* from `main(sys.argv[
            # 1:])`) was passed straight into main's own int64_t
            # parameter with NO cast at all — "passing argument 1 of
            # '_gimple_main' makes integer from pointer without a cast"
            # (a hard GIMPLE error, not just a warning). Found via
            # Doc/includes/ndiff.py's/Tools/build/generate_token.py's/
            # generate_re_casefix.py's own top-level `main(...)` calls
            # (this bare-statement path, `_gen_stmt_ExprStmt`, not
            # _lower_call — `main(...)` as its own statement, result
            # discarded, never reaches _lower_call at all).
            if 'main' in gen.func_param_types and fname not in gen.func_param_types:
                gen.func_param_types[fname] = gen.func_param_types['main']
            if 'main' in gen.func_return_types and fname not in gen.func_return_types:
                gen.func_return_types[fname] = gen.func_return_types['main']
        else:
            # Mirror the rename logic in _lower_call: only rename _C_RESERVED_FUNCS
            # names when they are locally defined OR imported — otherwise keep the
            # C stdlib name (e.g. abort() from a monomorphized template that has no
            # import statement should stay as abort(), not become mojo_abort()).
            if (raw_name in gimple_ctypes._C_RESERVED_FUNCS
                    and raw_name not in gen.func_return_types
                    and raw_name not in gimple_ctypes._FORCE_RENAME_RESERVED
                    and (raw_name not in gen.imported_symbols
                         or raw_name in gen._unresolved_import_aliases)):
                if raw_name in gen._unresolved_import_aliases:
                    # Statement-level twin of _lower_named_call's identical
                    # unresolved-alias branch: a relative/external import this
                    # compile could never resolve (`from .os_helper import
                    # unlink`) must bind its call site to the SAME weak-stub
                    # symbol (`_func_csym` → `mojo_unlink`) the preamble's
                    # stub pass emitted — not the raw reserved name, which
                    # silently retargeted libc's undeclared same-named
                    # function ("implicit declaration of function 'unlink'",
                    # a hard error).
                    fname = gen._func_csym(raw_name)
                else:
                    fname = gen.BUILTIN_VALUE_MAP.get(raw_name, raw_name)
            else:
                # _func_csym applies the overload suffix to match the definition.
                fname = gen.BUILTIN_VALUE_MAP.get(raw_name, gen._func_csym(raw_name))
            if fname == 'main' and raw_name in gen._unresolved_import_aliases:
                # See _lower_named_call's identical branch and
                # bugs/hard/CODEGEN_aliased_external_import_no_backing_
                # symbol.md.
                fname = '_unresolved_import_main'
        # Statement-level twin of _lower_named_call's identical libc
        # self-extern registration: a bare `mkdir(name, mode)` /
        # `rmdir(name)` / `execv(file, args)` statement (os.py's own
        # wrappers are exactly that) never reaches _lower_named_call at
        # all, so without this its prototype was never recorded and the
        # call stayed an implicit declaration.
        ggc._ensure_libc_self_extern(gen, raw_name)
        arg_pairs = [gen.lower_expr(a) for a in node.value.args]

        # exit(msg)/quit(msg) as a bare statement — see _lower_named_
        # call's identical check (this is that fix's statement-level
        # twin: a bare `exit("...")` line never reaches _lower_call at
        # all, exactly like the kwarg-padding duplication noted above).
        if raw_name in ('exit', 'quit') and len(arg_pairs) == 1:
            _ex_t, _ex_v = arg_pairs[0]
            if _ex_t not in ('int', 'int64_t', '_Bool'):
                _msg = gen._stringify_value(_ex_t, _ex_v)
                gen._emit_call('void', '', 'mojo_print_stderr', [('char *', _msg)])
                gen._emit("  exit (1);")
                return

        # Handle keyword arguments for regular function calls
        kwargs = getattr(node.value, 'kwargs', []) or []
        kwarg_dict = {kname: gen.lower_expr(kexpr) for kname, kexpr in kwargs}

        # `def f(fixed, *args, trailing_kwonly=default, ...)` called as
        # a bare, value-discarding statement (e.g. importlib/_bootstrap.
        # py's `_verbose_message('import {!r} # {!r}', spec.name,
        # spec.loader)`, whose None return is discarded) — this is the
        # statement-level twin of `_lower_named_call`'s identical
        # packing; see `_pack_vararg_trailing_params`'s docstring for
        # the full rationale. Without this, this function's own
        # general-call-building path below coerces the extra positional
        # args 1:1 against the trailing params' concrete C types
        # instead of packing them, e.g. "passing argument 2 of
        # '_verbose_message' makes pointer from integer without a cast".
        _call_has_spread = any(isinstance(_a, gimple_ctypes.UnaryOp) and _a.op in ('*', '**')
                               for _a in node.value.args)
        arg_pairs, kwarg_dict = gen._pack_vararg_trailing_params(
            fname, raw_name, arg_pairs, kwarg_dict, _call_has_spread)

        # For compile_to_gimple: pad with do_imports and filename kwargs
        if raw_name == 'compile_to_gimple':
            if 'do_imports' in kwarg_dict:
                arg_pairs.append(kwarg_dict['do_imports'])
            elif len(arg_pairs) < 2:
                arg_pairs.append(('int', '0'))
            if 'filename' in kwarg_dict:
                arg_pairs.append(kwarg_dict['filename'])
            elif len(arg_pairs) < 3:
                arg_pairs.append(('char *', '0'))

        # For interpret_and_execute: pad with filename kwarg
        if raw_name == 'interpret_and_execute':
            if 'filename' in kwarg_dict:
                arg_pairs.append(kwarg_dict['filename'])
            elif len(arg_pairs) < 2:
                arg_pairs.append(('int', '0'))

        # General: pad missing args with kwargs when expected param count is
        # known — see _lower_call's identical logic (this is the
        # statement-level twin: a call whose return value is discarded,
        # e.g. `memcpy(dest=.., src=.., count=..)` standing alone as its
        # own statement, never reaches _lower_call at all). Falling back
        # to `_KNOWN_SIGS`'s real arity when func_param_types has no entry
        # is what fixed the memcpy-in-isolated-compile bug investigated
        # 2026-07-15 without over-firing for a struct constructor called
        # with stale/vestigial kwargs (not in _KNOWN_SIGS, so untouched).
        # BUG-2026-024 tiered truth, statement-level twin of the identical
        # `_ggf_eff._effective_param_types` lookup in _lower_named_call:
        # the raw bare-name `func_param_types` slot permanently oscillates
        # between sibling homonyms in a whole-program closure (whichever
        # module's registration pass ran last owns it), so padding arity
        # against it silently retargeted THIS unit's own same-named def's
        # call sites at ANOTHER module's signature. Real instance:
        # re/_compiler.py's `_compile(code, pattern, flags)` — three bare
        # ExprStmt-level recursive calls — padded out to FIVE arguments
        # with codeop.py's unrelated homonym's trailing defaults
        # (`incomplete_input=True, *, flags=0`), i.e. GCC "too many
        # arguments to function '__compiler__compile_132aaf'; expected 3,
        # have 5" at all 20 recursive call sites, whenever codeop was in
        # the same program's transitive closure. Tier order here must
        # mirror _func_csym's (which picked this very call site's mangled
        # symbol) so arity and symbol can't disagree.
        import mojo.backend_gimple.emit_funcs as _ggf_stmt_eff
        expected_params = _ggf_stmt_eff._effective_param_types(gen, raw_name)
        if not expected_params:
            expected_params = gen.func_param_types.get(raw_name, [])
        if not expected_params and fname in gen._KNOWN_SIGS:
            expected_params = gen._KNOWN_SIGS[fname][1]
        # `f(*iterable)` unpacking against a fixed-arity callee — shared
        # with _lower_named_call's identical expansion (see there).
        arg_pairs = gen._expand_sole_spread_into_fixed_slots(
            node.value, fname, raw_name, arg_pairs, expected_params)
        if expected_params and len(arg_pairs) < len(expected_params):
            # BUG-2026-020: pad with the callee's DECLARED DEFAULTS first —
            # this statement-level twin previously only knew kwargs-then-0,
            # so every bare, value-discarding call that omitted a defaulted
            # argument (`check("one-arg")`, `greet()`) passed literal 0 and
            # phantom-failed under --jit (43/170 in test_furnace.mojo).
            # Mirrors _lower_named_call's identical padding, including the
            # trailing-run offset (`param_defaults` only holds entries for
            # params THAT HAVE one, starting at the first defaulted
            # position).
            _dflts = (gen._func_param_defaults.get(fname)
                      or gen._func_param_defaults.get(raw_name) or [])
            _n_req = len(expected_params) - len(_dflts)
            kwarg_values = list(kwarg_dict.values()) if kwarg_dict else []
            while len(arg_pairs) < len(expected_params):
                if kwarg_values:
                    arg_pairs.append(kwarg_values.pop(0))
                    continue
                _pos = len(arg_pairs)
                _dv = None
                if _dflts and 0 <= _pos - _n_req < len(_dflts):
                    _dv = _dflts[_pos - _n_req][1]
                # The declared parameter type decides the shape of "no
                # value": a POINTER slot has to be padded with a typed NULL,
                # because an integer 0 handed to a `char *` is coerced
                # through `mojo_cstr_or_int_str` into the one-character
                # string "0" — a true, non-null pointer. Same fix and same
                # reason as `_lower_named_call`'s identical loop (see
                # `_default_expr_to_pair`'s `param_ctype`); this is the
                # statement-level twin, so a bare `f()` that discards its
                # result needs it too.
                _pct = (expected_params[_pos]
                        if 0 <= _pos < len(expected_params) else None)
                if _dv is not None:
                    arg_pairs.append(gen._default_expr_to_pair(_dv, param_ctype=_pct))
                elif _is_pointer_ctype(_pct):
                    arg_pairs.append((_pct, '0'))
                else:
                    arg_pairs.append(('int', '0'))

        if fname in gen._KNOWN_SIGS:
            ret_type = gen._KNOWN_SIGS[fname][0]
            gen._emit_call(ret_type, '', fname, arg_pairs)
        else:
            # Auto-stub completely unknown names (bracket params, implicit fnptrs)
            # Skip the self-host hardcoded forward-declared symbols — the
            # `_is_selfhost_file` block declares those concretely; a variadic
            # stub here would conflict ("conflicting types").
            _is_unknown_stmt = (raw_name not in gen.func_return_types
                                and raw_name not in gen.imported_symbols
                                and fname not in gen._KNOWN_SIGS
                                and raw_name not in gen.BUILTIN_VALUE_MAP
                                and raw_name not in gimple_ctypes._C_RESERVED_FUNCS
                                and fname not in gimple_codegen._SELFHOST_HARDCODED_FUNCS
                                and raw_name not in gimple_codegen._SELFHOST_HARDCODED_FUNCS)
            if _is_unknown_stmt and fname not in gen._auto_stubbed:
                _stub_guard = gimple_ctypes._stub_guard_name(fname)
                if raw_name in gen._unresolved_import_aliases:
                    # See _lower_named_call's identical branch (and
                    # bugs/hard/CODEGEN_aliased_external_import_no_
                    # backing_symbol.md) — a name imported from a
                    # module load_module() couldn't resolve never gets
                    # a real definition anywhere in this compile, so a
                    # bare forward decl here just moves the failure to
                    # an undefined-symbol link error instead.
                    _stub = (f'#ifndef {_stub_guard}\n#define {_stub_guard}\n'
                             f'__attribute__((weak)) int64_t {fname} (...) '
                             f'{{ mojo_print ((char *)"{raw_name}: unavailable in compiled mode '
                             f'(imported from an unresolved external/relative module)"); '
                             f'return (int64_t)0; }}\n#endif')
                else:
                    # See _lower_named_call's identical branch for the
                    # full reasoning: anything reaching _is_unknown_stmt
                    # is, by construction, never going to get a real
                    # definition anywhere in this compile (a genuine
                    # same-TU forward reference can't reach here — every
                    # top-level function's return type is pre-registered
                    # well before any body is lowered), so a bare decl
                    # only postpones today's failure from compile-time to
                    # an equally inevitable link-time "undefined symbols"
                    # error for any such name actually called at runtime.
                    _stub = (f'#ifndef {_stub_guard}\n#define {_stub_guard}\n'
                             f'__attribute__((weak)) int64_t {fname} (...) '
                             f'{{ mojo_print ((char *)"{raw_name}: unavailable in compiled mode"); '
                             f'return (int64_t)0; }}\n#endif')
                if _stub not in gen._elaborated_externs:
                    gen._elaborated_externs.append(_stub)
                gen._auto_stubbed.add(fname)
            # For user-defined functions, still use _emit_call to handle type coercion
            ret_type = gen.func_return_types.get(raw_name, 'void')
            gen._emit_call(ret_type, '', fname, arg_pairs)
    else:
        gen.lower_expr(node.value)


def _gen_stmt_AssertStmt(gen, node):
    _, v = gen.lower_expr(node.value)
    bb_trap = gen._new_bb()
    bb_ok   = gen._new_bb()
    gen._emit(f"  if ({v}) goto {bb_ok}; else goto {bb_trap};")
    gen._emit_label(bb_trap)
    if node.msg is not None:
        mt, mv = gen.lower_expr(node.msg)
        if mt == 'char *':
            gen._emit(f'  puts ({mv});')
        elif mt in ('double', 'float', '__fp16'):
            dv = mv if mt == 'double' else gen._new_val('double', f'(double){mv}')
            rv = gen._call_expr('char *', 'mojo_repr_float', [('double', dv)])
            gen._emit(f'  printf ("%s\\n", {rv});')
        else:
            gen._emit(f'  printf ("{gimple_ctypes.TypeLattice.printf_fmt(mt)}\\n", {mv});')
    gen._emit("  __builtin_trap ();")
    gen._emit(f"  goto {bb_ok};")
    gen._emit_label(bb_ok)


def _gen_stmt_RaiseStmt(gen, node):
    # Bare `raise` (re-raise): the currently-live exception's type tag,
    # message, and object were already set when it was first raised (or
    # by the handler binding below), so just propagate.
    if node.value is None:
        gen._emit("  mojo_raise ();")
        return

    # `raise ExcName(...)` / `raise ExcName` (constructor call or bare
    # class reference): tag the runtime's exception slot with a stable
    # per-class id (see _exc_type_id) so a multi-handler try/except can
    # dispatch on which exception this actually is, instead of always
    # running the first handler. Exception *constructors* still can't be
    # generally lowered to GIMPLE, but a single string argument is a
    # common enough case (str(e) / the message) to special-case.
    val = node.value
    exc_name = None
    msg_arg = None
    if isinstance(val, gimple_ctypes.CallExpr) and isinstance(val.func, gimple_ctypes.IdentExpr):
        exc_name = val.func.name
        if len(val.args) == 1:
            msg_arg = val.args[0]
    elif isinstance(val, gimple_ctypes.IdentExpr) and gen._is_exc_class_name(val.name):
        # `raise SomeExceptionClass` with no call — legal Python,
        # equivalent to `raise SomeExceptionClass()`.
        exc_name = val.name
    # else: `raise e` re-raising a bound variable — the type tag set
    # when `e` was originally raised (and copied onto it in the handler
    # below) is still live in the runtime slot; leave it alone.

    if exc_name:
        gen._emit(f"  mojo_exc_type_set ({gen._exc_type_id(exc_name)});")
    if isinstance(msg_arg, (gimple_ctypes.StringLiteral, gimple_ctypes.IdentExpr)):
        mt, mv = gen.lower_expr(msg_arg)
        if mt == 'char *':
            gen._emit(f"  mojo_exc_msg_set ({mv});")
            # The object slot is what `except X as e:` actually binds
            # (see _emit_handler_body) — without this, `e` reads back
            # whatever was last there (frequently NULL), regardless of
            # the message just set above. A bare string is the only
            # payload shape raise-lowering supports right now (an
            # arbitrary Int/Dict/struct payload would need real value
            # construction here plus a way for the handler to know
            # which of several possible C types to cast back to —
            # tracked as a follow-up, not done here).
            gen._emit(f"  mojo_exc_obj_set ({mv});")

    gen._emit("  mojo_raise ();")




def _handler_exc_all_names(gen, h):
    """Every exception type name a handler catches. A single-type handler
    yields one name; a parenthesized `except (A, B):` yields all of them."""
    if isinstance(h.exc_type, list):
        return h.exc_type
    one = gen._handler_exc_name(h)
    if one is None:
        return []
    return [one]




def _emit_except_handler(gen, handler, node, bb_after: str):
    """Emit one except-handler's binding + body + finally + exit goto.
    A plain method (not a closure nested in _gen_stmt_TryStmt): this file
    self-hosts, and a large method with several nested `def`s pushed
    _gen_stmt_TryStmt's own compiled form into a code path that mishandled
    it — kept flat here instead."""
    had_c_name = False
    restore_c_name = None
    was_except_as_char = False
    added_except_as = False
    had_var_type = False
    restore_var_type = None
    # `_as_str`, not the bare call result: `_handler_bind_name` has
    # multiple return paths (`h.name`, `h.exc_type`, `None`), and the
    # self-hosted backend's whole-function type-unification erased its
    # return type to int64_t instead of `str | None`. Every dict write
    # below keyed off the erased `bind_name` (`gen.var_types[bind_name]
    # = exc_ctype`, `gen._c_names[bind_name] = bound`) then stored under
    # a garbage/stringified-pointer key instead of the real name (e.g.
    # "e") — so a later `note(e)` call-argument lookup for the literal
    # string "e" always missed both dicts and fell back to a plain
    # `(int64_t)0` default instead of reading the correctly-bound
    # `char *` temp holding the caught exception's value. Confirmed via
    # a --dump-full fire.py sibling-import diff (mojo_exc_obj_get()'s
    # result silently discarded at every `except Exception as e:` call
    # site referencing `e`) and reproduced standalone with a 2-line
    # `except Exception as e: note(e)`.
    bind_name = _as_str(gen._handler_bind_name(handler))
    if bind_name:
        # Exception handlers are typed as pointers to exception objects.
        exc_type_name = gen._handler_exc_name(handler)
        if exc_type_name and exc_type_name in gen.struct_field_types:
            exc_ctype = f"{exc_type_name} *"
        else:
            # Builtin exceptions (ValueError, KeyError, ...) and bare
            # `except as e` have no struct: the object slot is populated
            # as a bare message string (see _gen_stmt_RaiseStmt), so bind
            # as char * — matches what is actually stored instead of an
            # opaque void * that would print as a raw address.
            exc_ctype = 'char *'
            # Track that `bind_name` is, for the extent of this handler's
            # body, an except-as-bound `char *` exception object — see
            # `self._except_as_names`'s own docstring for why this is
            # needed (a caught exception has no struct type for ordinary
            # MemberExpr dispatch to key off). Save/restore exactly like
            # `had_c_name`/`restore_c_name` just below, so a second,
            # sequential `except ... as e:` in the same function (or a
            # nested one shadowing an outer binding) can't leave a stale
            # entry once this handler's body is done.
            was_except_as_char = bind_name in gen._except_as_names
            if not was_except_as_char:
                gen._except_as_names.add(bind_name)
                added_except_as = True

        # Bind through a fresh, guaranteed-unique C temp rather than
        # declaring `handler.name` itself as a plain local: GCC's raw
        # -GIMPLE parser trips when the same plain local is assigned from
        # two different, non-dominating basic blocks — which is exactly
        # what happens when two separate try/except statements in the
        # same function both bind the same name (commonly `e`). It
        # re-interprets the second assignment as an implicit-int
        # redeclaration instead of a plain store (found self-hosting
        # gimple_codegen.py's own _compile_imported_module, which has two
        # sequential `except Exception as e:` blocks). _c_names — the
        # same rename table _declare_var uses for keyword/shadow
        # collisions — redirects every reference to `handler.name` inside
        # this handler's body to the fresh temp, and is restored after so
        # an unrelated same-named binding elsewhere in the function is
        # unaffected.
        # FORCE (not setdefault) bind_name's var_types entry to
        # exc_ctype for the extent of this handler's body, saving/
        # restoring exactly like `_c_names`/`had_c_name`/
        # `restore_c_name` just below. `setdefault` was wrong: if
        # `bind_name` (commonly `e`) was already used earlier in this
        # SAME function for an unrelated, differently-typed local (e.g.
        # a plain assignment `e, self._inject_exc = self._inject_exc,
        # None` above this try/except -- see
        # _ThreadedGenerator._resume, myinterpreter.py), `var_types
        # [bind_name]` already existed (typically `int64_t`, the
        # generic boxed default) and setdefault left it untouched.
        # `_c_names` already correctly redirects every REFERENCE inside
        # this handler's body to the fresh, correctly-typed `bound`
        # temp below, but `lower_expr(IdentExpr(bind_name))` reports
        # its TYPE from `var_types`, not from the C variable it
        # resolves to -- so a caller like `_emit_call` computing
        # argument-coercion casts saw the STALE `int64_t` type tag
        # paired with the correctly-cast `char *`-typed C value, read
        # `ptype == atype` (both nominally `int64_t`) as "no coercion
        # needed", and silently passed the raw pointer bits where the
        # callee's own declared `int64_t` parameter expected a real
        # int64_t -- invisible under a `__GIMPLE`-tagged caller (raw
        # GIMPLE bypasses gcc's normal call-argument type checking),
        # exposed as a hard "-Wint-conversion" error only once the
        # calling method genuinely lost `__GIMPLE` for an unrelated,
        # correct reason (containing its own real `setjmp`). See
        # “setting/getting an arbitrary attribute on a generically-typed object”'s
        # "Segfault root-caused" section for the full mechanism.
        had_var_type = bind_name in gen.var_types
        restore_var_type = gen.var_types.get(bind_name)
        gen.var_types[bind_name] = exc_ctype
        had_c_name = bind_name in gen._c_names
        restore_c_name = gen._c_names.get(bind_name)

        # Retrieve the exception object from the runtime.
        # Use a temp to avoid casting function call results in GIMPLE.
        temp_var = gen._new_temp('void *')
        gen._emit(f"  {temp_var} = mojo_exc_obj_get ();")
        bound = gen._new_temp(exc_ctype)
        gen._emit(f"  {bound} = ({exc_ctype}) {temp_var};")
        gen._c_names[bind_name] = bound
    gen._last_was_terminal = False
    for s in handler.body:
        gen.gen_stmt(s)
    if node.finally_body:
        for s in node.finally_body:
            gen.gen_stmt(s)
    # Only emit goto if the exception handler didn't end with a return
    if not gen._last_was_terminal:
        gen._emit(f"  goto {bb_after};")
    if bind_name:
        if had_c_name:
            gen._c_names[bind_name] = restore_c_name
        else:
            del gen._c_names[bind_name]
        if had_var_type:
            gen.var_types[bind_name] = restore_var_type
        else:
            del gen.var_types[bind_name]
        if added_except_as:
            gen._except_as_names.discard(bind_name)


def _gen_stmt_TryStmt(gen, node):
    # See _reset_func's own comment on `_func_used_setjmp` -- this
    # function's body is about to emit a real `setjmp`, so whichever
    # enclosing `__GIMPLE`-tagged emitter (_gen_struct_method /
    # _gen_lifted_closure) is generating this statement must drop
    # `__GIMPLE` from its signature.
    gen._func_used_setjmp = True
    # Loop nesting at try-entry: a `break`/`continue` inside the try body
    # only leaves this try's setjmp region if it targets a loop that was
    # ALREADY open here (a loop OUTSIDE the try). A loop opened inside the
    # try body keeps its `continue` within the protected region — popping
    # there is a spurious `mojo_exc_pop()` every iteration, which is
    # exactly what walked `_mojo_exc_top` negative across a full self-host
    # run (`ModuleLoader.load_module_from_path`'s `try: ... for _l in
    # src.split(): ... continue`).
    _entry_loop_depth = len(getattr(gen, 'loop_stack', []))
    sj_ret = gen._new_temp('int')
    cond_t = gen._new_temp('_Bool')
    bb_try   = gen._new_bb()
    bb_exc   = gen._new_bb()
    # The "this exception is not handled here" path: run the `finally`, then
    # let the exception keep propagating. Needed for BOTH shapes that reach
    # it — a `try/except/finally` whose handlers all declined to match, and a
    # `try/finally` with no `except` at all.
    bb_exc_reraise = gen._new_bb()
    bb_else  = gen._new_bb() if node.else_body else None
    bb_after = gen._new_bb()

    # Emit setjmp directly in the generated function (not via mojo_try_push
    # wrapper) so the setjmp frame stays live for longjmp from mojo_raise.
    # Use proper GIMPLE pattern with temporaries for increment and address.
    temp_top1 = gen._new_temp('int')
    temp_inc = gen._new_temp('int')
    temp_top2 = gen._new_temp('int')
    temp_addr = gen._new_temp('void *')  # jmp_buf is int[48], use void* to avoid type mismatch
    gen._emit(f"  {temp_top1} = _mojo_exc_top;")
    gen._emit(f"  {temp_inc} = {temp_top1} + 1;")
    gen._emit(f"  _mojo_exc_top = {temp_inc};")
    gen._emit(f"  {temp_top2} = _mojo_exc_top;")
    # Snapshot the cleanup-thunk stack depth this level unwinds back down to
    # on an exception (doc/OWNERSHIP_MODEL.md's exception-handling option 2)
    # — must happen after the _mojo_exc_top bump above (it indexes the
    # checkpoint table by that level) and before setjmp.
    gen._emit("  mojo_cleanup_checkpoint_save ();")
    # GIMPLE: pass array element directly to setjmp (decays to int*)
    gen._emit(f"  {sj_ret} = setjmp (_mojo_exc_stack[{temp_top2}]);")
    gen._emit(f"  {cond_t} = {sj_ret} != 0;")
    gen._emit(f"  if ({cond_t}) goto {bb_exc}; else goto {bb_try};")

    bb_finally = gen._new_bb() if node.finally_body else None
    bb_finally_done = gen._new_bb() if node.finally_body else None
    bb_do_return = gen._new_bb()  # Label to do the actual return after finally

    gen._emit_label(bb_try)
    _had_terminal = False
    _return_value = None
    _return_type = None
    _saw_return = [False]   # list so the nested intercepted_emit can set it
    # Save/restore the protected-region list around this body rather than a
    # bare append/pop: a nested function or nested try compiled from this
    # body can leave the list in a different state (a stray pop) before
    # this try returns, which made the bare `pop()` raise
    # `IndexError: pop from empty list` and abort the whole module compile.
    _saved_tlp = list(gen._try_loop_protect)
    _saved_tfb = list(gen._try_finally_bodies)
    gen._try_loop_protect.append(_entry_loop_depth)
    gen._try_finally_bodies.append(node.finally_body if node.finally_body else None)
    for s in node.body:
        # Temporarily override _emit to intercept return statements
        original_emit = gen._emit
        def intercepted_emit(line, rv=None, rt=None):
            nonlocal _return_value, _return_type
            stripped = line.strip()
            if stripped.startswith('return ') or stripped == 'return;':
                # Extract return value if any
                if stripped.startswith('return ') and stripped != 'return;':
                    _return_value = stripped[7:].rstrip(';').strip()
                    _return_type = 'int64_t'  # Simplified
                else:
                    _return_value = None
                _saw_return[0] = True
                # An early return leaves the try block's protected region
                # just as much as falling off the end of it does — it
                # must pop the exception stack (_mojo_exc_top) the same
                # way the normal-exit path below does. Omitting this
                # leaked one _mojo_exc_top level per early return with no
                # matching pop: harmless for a single try, but a whole
                # self-hosted compiler run has many `try: ... return ...`
                # sites, so _mojo_exc_top crept up across the run and
                # eventually walked off the end of the fixed-size
                # _mojo_exc_stack[MOJO_EXC_STACK_MAX] array — silent OOB
                # writes that corrupted nearby memory, surfacing much
                # later as a longjmp into a garbage jmp_buf.
                original_emit("  mojo_exc_pop ();")
                # Emit goto to finally instead of return
                if node.finally_body:
                    original_emit(f"  goto {bb_finally};")
                else:
                    original_emit(line)
                gen._last_was_terminal = True
                return
            # break/continue jumping out of this try's protected region is
            # handled in _gen_stmt_BreakStmt/_gen_stmt_ContinueStmt via
            # `_emit_try_loop_exit_exc_pops` (which reads
            # `gen._try_loop_protect`), NOT here — the former interception
            # of the `goto <loop label>;` line was a nested-closure
            # `gen._emit` override the self-hosted backend did not run.
            original_emit(line)

        gen._emit = intercepted_emit
        gen.gen_stmt(s)
        gen._emit = original_emit  # Restore

        if gen._last_was_terminal:
            _had_terminal = True
            break

    gen._try_loop_protect = _saved_tlp
    gen._try_finally_bodies = _saved_tfb

    # Normal fall-through out of the try body: no exception, no early
    # return. `finally` must run EXACTLY ONCE here, then control continues
    # to the `else` clause (which runs its own `finally` afterwards) or
    # straight to `bb_after`. Crucially this path must NOT fall into the
    # early-return `finally` block emitted just below — jump over it.
    # (The previous structure let control fall through the `bb_finally`
    # label AND then re-run the finally body inline, so every plain
    # `try: ... finally: ...` that fell off the end of its try body ran
    # its finally twice — over-counting any counter the finally mutated,
    # and, in a `while` loop around the try, skipping loop iterations.)
    if not _had_terminal:
        gen._emit("  mojo_exc_pop ();")
        if bb_else:
            gen._emit(f"  goto {bb_else};")
        elif node.finally_body:
            gen._emit(f"  goto {bb_finally_done};")
        else:
            gen._emit(f"  goto {bb_after};")

    # Early-`return`-inside-try path: intercepted_emit rewrote each
    # `return X` in the body to `mojo_exc_pop (); goto {bb_finally};`.
    # Run `finally`, then perform the deferred return.
    if bb_finally:
        gen._emit_label(bb_finally)
        for s in node.finally_body:
            gen.gen_stmt(s)
        if _return_value is not None:
            gen._emit(f"  return {_return_value};")
        elif _saw_return[0]:
            # A valueless `return;` was intercepted in the try body. Only
            # a void-returning body (a generator body is one) lowers a
            # bare `return` to a literal `return;` — _gen_stmt_ReturnStmt
            # already rewrites the non-void case to `return 0;`/a typed
            # temp, which takes the branch above. So emitting `return;`
            # here is correct and needed: it ends the (generator) body.
            gen._emit("  return;")
        else:
            # Dead code: no `return` at all in the try body, so nothing
            # jumps to bb_finally. Fall through to bb_after rather than
            # emitting a bare `return;` that would fail -Wreturn-mismatch
            # in a non-void function (real: device_graph.mojo's `region`).
            gen._emit(f"  goto {bb_after};")

    # Normal-path `finally` landing pad (only when there is no `else`
    # clause — with an `else`, bb_else runs the finally itself).
    if not _had_terminal and node.finally_body and not bb_else:
        gen._emit_label(bb_finally_done)
        for s in node.finally_body:
            gen.gen_stmt(s)
        gen._emit(f"  goto {bb_after};")

    # Reset terminal state for caller
    if not _had_terminal:
        gen._last_was_terminal = False

    gen._emit_label(bb_exc)
    gen._emit("  mojo_exc_pop ();")

    handlers = node.handlers
    if not handlers:
        # `try: ... finally: ...` (no `except`): the exception was never
        # going to be handled here, so it must keep propagating — but only
        # AFTER the finally has run. Falling through instead (which is what
        # this used to do, since the handler-dispatch code below emits
        # nothing when there are no handlers) dropped the exception on the
        # floor entirely: `try: raise ValueError("x") finally: print("c")`
        # printed neither the cleanup nor anything else, and exited 0.
        gen._emit(f"  goto {bb_exc_reraise};")
    # `except Exception`/`except BaseException` must catch *anything* —
    # in real Python every raised type is an Exception subclass, but the
    # tag-equality dispatch below has no notion of inheritance, so
    # without this special case `except Exception as e:` only matched a
    # literal Exception tag and let every other exception type (e.g. the
    # very common `except Exception: <log and continue>` guarding a
    # SyntaxError from a speculative/lookahead parse) propagate straight
    # past it — a regression from the old "run whatever handler is here
    # unconditionally" behavior, where this happened to work by
    # accident. Treated as a catch-all (`bare`) the same as a
    # type-less `except:`.
    _UNIVERSAL_CATCH_NAMES = ('Exception', 'BaseException')
    typed = [h for h in handlers
             if gen._handler_exc_name(h) is not None
             and gen._handler_exc_name(h) not in _UNIVERSAL_CATCH_NAMES]
    bare = [h for h in handlers
            if gen._handler_exc_name(h) is None
            or gen._handler_exc_name(h) in _UNIVERSAL_CATCH_NAMES]

    if not typed:
        # Only bare handler(s) (or none) — nothing to dispatch on.
        for handler in bare[:1]:
            gen._emit_except_handler(handler, node, bb_after)
    else:
        # Real per-exception-type dispatch (see mojo_exc_type_set /
        # _exc_type_id): each typed handler matches only its own tag —
        # including when it's the sole handler, so e.g. `except KeyError`
        # correctly lets an unrelated ValueError propagate instead of
        # swallowing it (the old behavior ran whatever single handler was
        # there unconditionally). Tag 0 (untagged: a raise site that
        # couldn't be statically identified, or a bare re-raise of
        # something never tagged) is treated leniently and matches the
        # first typed handler, so pre-existing untyped raises don't
        # regress from "always caught" to "always propagates". A bare
        # handler (no exc_type) matches anything and — mirroring
        # Python's own rule that a bare except must be last — is tried
        # only after every typed handler, regardless of source position.
        # If nothing matches, this try wasn't meant to catch it:
        # propagate to the enclosing frame instead of guessing.
        exc_type_t = gen._new_temp('int64_t')
        gen._declare_var(exc_type_t, 'int64_t')
        gen._emit(f"  {exc_type_t} = mojo_exc_type_get ();")

        # Plain loop, not `{id(h): gen._new_bb() for h in handlers}` — a
        # dict comprehension with int keys (`id(h)`) and str VALUES: the
        # self-hosted backend didn't track the value type, so a later
        # `handler_bbs[id(h)]` read came back an erased int64_t (the bb-
        # name string's address) and emitted `goto <decimal address>;` —
        # invalid C, different every run (confirmed via a real --dump-full
        # fire.py determinism diff at myinterpreter.py:634's `except
        # (GeneratorExit, StopIteration):`). Build it explicitly and
        # `_as_str`-guard every read.
        handler_bbs: dict = {}
        for _hbb in handlers:
            handler_bbs[id(_hbb)] = gen._new_bb()
        bb_no_match = gen._new_bb()

        # A bare int literal (e.g. `== 12345`) defaults to plain `int`
        # in C, mismatching the int64_t exc_type_t in this dialect's
        # stricter comparison check — and the cast has to land in its
        # own temp first, since raw GIMPLE also rejects an inline cast
        # *inside* a comparison (same two-step pattern _new_val uses).
        n_typed = len(typed)
        for i, h in enumerate(typed):
            # `except BaseError:` must also match a raised *subclass* of
            # BaseError (struct/class inheritance — see
            # _compute_exc_descendants), not just an exact tag match:
            # OR the equality check across every known descendant's tag,
            # not just the handler's own type.
            handler_name = gen._handler_exc_name(h)
            descendant_names = set()
            for _hn in gen._handler_exc_all_names(h):
                descendant_names |= gen._exc_descendants.get(_hn, {_hn})
            if len(descendant_names) == 0:
                descendant_names = {handler_name}
            is_match = None
            for dname in sorted(descendant_names):
                tid = gen._exc_type_id(dname)
                tid_t = gen._new_temp('int64_t')
                gen._emit(f"  {tid_t} = (int64_t){tid};")
                one_match = gen._new_temp('_Bool')
                gen._emit(f"  {one_match} = {exc_type_t} == {tid_t};")
                if is_match is None:
                    is_match = one_match
                else:
                    combined = gen._new_temp('_Bool')
                    gen._emit(f"  {combined} = {is_match} | {one_match};")
                    is_match = combined
            if i == 0:
                # Untagged (0) is treated leniently and falls to the
                # first typed handler — see the rationale above. Two
                # separate comparisons combined via a temp bool rather
                # than an inline `||`: this file's raw-GIMPLE dialect
                # wants one comparison per statement.
                zero_t = gen._new_temp('int64_t')
                gen._emit(f"  {zero_t} = (int64_t)0;")
                is_untagged = gen._new_temp('_Bool')
                gen._emit(f"  {is_untagged} = {exc_type_t} == {zero_t};")
                combined = gen._new_temp('_Bool')
                # Bitwise, not `||`: both operands are already plain 0/1
                # _Bool values, and this file's raw-GIMPLE dialect wants
                # one simple binary op per statement, not a short-circuit
                # operator (see the and/or eager-evaluation note in
                # PLAN.md for the same underlying constraint).
                gen._emit(f"  {combined} = {is_untagged} | {is_match};")
                is_match = combined
            # Raw-GIMPLE wants both branches of every conditional
            # explicit — no implicit fallthrough — so each check needs
            # its own "else keep checking" label.
            if i + 1 < n_typed:
                next_bb = gen._new_bb()
            else:
                next_bb = _as_str(handler_bbs[id(bare[0])]) if bare else bb_no_match
            gen._emit(f"  if ({is_match}) goto {_as_str(handler_bbs[id(h)])}; else goto {next_bb};")
            if i + 1 < n_typed:
                gen._emit_label(next_bb)

        for h in typed + bare[:1]:
            gen._emit_label(_as_str(handler_bbs[id(h)]))
            gen._emit_except_handler(h, node, bb_after)

        gen._emit_label(bb_no_match)
        # No handler claimed it: run the finally (a caught exception runs
        # it inline in _emit_except_handler, so without this hop an
        # unhandled-by-any-handler exception skipped the cleanup entirely),
        # then keep propagating.
        gen._emit(f"  goto {bb_exc_reraise};")

    # Finally-then-propagate block (see bb_exc_reraise's declaration).
    gen._emit_label(bb_exc_reraise)
    if node.finally_body:
        for s in node.finally_body:
            gen.gen_stmt(s)
    gen._emit("  mojo_raise ();")

    if bb_else:
        gen._emit_label(bb_else)
        for s in node.else_body:
            gen.gen_stmt(s)
        if node.finally_body:
            for s in node.finally_body:
                gen.gen_stmt(s)
        # Only emit goto if the else block didn't end with a return
        if not gen._last_was_terminal:
            gen._emit(f"  goto {bb_after};")

    gen._emit_label(bb_after)


def _with_emit_exits(gen, _ex_ts, _ex_vs, _ex_sns, _ex_gbases, _ex_gvs):
    """Emit every `with`-item's teardown (`__exit__` call, generator
    resume/destroy, or a placeholder comment), in REVERSE index order —
    last acquired, first released.

    HOISTED out of `_gen_stmt_WithStmt` (was a nested closure reading the
    enclosing function's `_ctx_ts`/`_ctx_vs`/`_ctx_sns`/`_gctx_bases`/
    `_gctx_vs` locals directly). As a nested closure it emitted NOTHING
    after the self-hosted binary compiled the compiler: a real
    stage1-vs-stage2 `make bootstrap` divergence (fire_main.py/mojo.mojo
    emitted `/* with: __exit__ (int64_t) */` and the python3 reference
    emitted it, the native side omitted it entirely), while the same
    function's `__enter__`/alias-binding path — which runs in the
    ENCLOSING scope, not a closure — emitted correctly. Threading the
    lists as explicit parameters while leaving it nested did NOT fix it,
    so the failure is the nested-closure lifting itself, not the capture
    values; hoisting to module level (this project's standard remedy —
    see `_gmi_scan_import_modules`, `_register_imported_structs`'s
    `collect`) removes it.

    Index walk over parallel lists, NOT
    `for (ct, cv, sn), gctx in zip(contexts, gen_ctxs)` — the
    nested-tuple `for` target has no self-hosted lowering (emits
    mojo_unsupported_iter, the loop ran zero times so `with` blocks
    never emitted their __exit__ / generator teardown in the compiled
    compiler's own output).

    The walk runs BACKWARDS because that is the order the items were
    ACQUIRED in: `with A() as a, B():` calls `A.__enter__` then
    `B.__enter__`, and Python releases them in the mirror of that —
    `B.__exit__` then `A.__exit__` — which is the whole point of nesting,
    since an inner context manager's teardown may depend on the outer
    one's state still being live. This emitted forward, so a multi-item
    `with` released the outer manager first (exit 6 / exit 7 where CPython
    prints exit 7 / exit 6; see
    so the OUTER one was released first). One walk,
    five call sites — the normal tail, the `return`/loop-exit interceptor,
    and the exception arm — so every exit route unwinds in the same order.

    A generator item's teardown is its final `resume()` + `_destroy()`,
    which IS its `__exit__`, so reversing moves that pair after the outer
    items' `__exit__`s only when the generator was acquired first — the
    same relative order the acquisition order gives, which is what CPython
    does for `@contextlib.contextmanager` items too.
    """
    # `_as_str` on every element read out of a plain (element-type-
    # untracked) list parameter — otherwise the str slot erases to
    # int64_t and `f"({sn})"` emitted the pointer's DECIMAL address
    # (`/* with: __exit__ (4376542048) */`) instead of `int64_t`.
    for _xi in range(len(_ex_ts) - 1, -1, -1):
        ct = _as_str(_ex_ts[_xi])
        cv = _as_str(_ex_vs[_xi])
        sn = _as_str(_ex_sns[_xi])
        _gbase = _ex_gbases[_xi]
        _gval = _ex_gvs[_xi]
        if _gbase is not None:
            _gbase = _as_str(_gbase)
            _gval = _as_str(_gval)
            # Generator context manager: the final resume() runs the
            # body from its bare yield to co_return (= __exit__), then
            # the coroutine frame is destroyed. resume()'s _Bool
            # result (False == already done) is intentionally
            # discarded — real Python's __exit__ return value only
            # suppresses exceptions, and this normal-path emission
            # runs after an unexceptional body.
            done_t = gen._new_temp('_Bool')
            gen._emit(f"  {done_t} = {_gbase}_resume ({_gval});")
            gen._emit_call('void', '', f"{_gbase}_destroy",
                           [('MojoGenerator *', _gval)])
            continue
        exit_fn = gen._struct_method_csym(sn, '__exit__', '')
        if exit_fn in gen.func_return_types or f"{sn}___exit__" in gen.func_return_types:
            # __exit__(self, exc_type, exc_val, exc_tb) — real
            # Python's protocol always passes 3 exception-info
            # args (None/None/None on the normal-exit path). This
            # codegen doesn't thread real per-with-statement
            # exception objects through to here on the exceptional
            # path either (both paths pass 0/0/0) — always calling
            # with the correct ARITY, matching whatever exception
            # info happens to be available, was previously simply
            # missing altogether ("too few arguments to function
            # ...__exit__; expected 4, have 1", a hard compile
            # failure, not just imprecise semantics).
            #
            # Real Mojo (unlike Python) does NOT require __exit__
            # to accept the 3 exception-info params — plain
            # resource-cleanup-only `def __exit__(self):` is a
            # legitimate, common shape too (e.g. std/io/io.mojo's
            # `_fdopen`). Padding unconditionally to 4 args broke
            # that shape ("too many arguments... expected 1, have
            # 4") — pad only up to however many params THIS
            # exit_fn's own real signature actually declares.
            _exit_params = gen.func_param_types.get(exit_fn)
            if _exit_params is None:
                _exit_params = gen.func_param_types.get(f"{sn}___exit__")
            _n_extra = max(len(_exit_params) - 1, 0) if _exit_params is not None else 3
            _extra_args = [('int64_t', '0')] * min(_n_extra, 3)
            ret_t = gen.func_return_types.get(exit_fn, '_Bool')
            gen._emit_call(ret_t, '', exit_fn, [(ct, cv)] + _extra_args)
        else:
            gen._emit(f"  /* with: __exit__ ({sn}) */")


def _gen_stmt_WithStmt(gen, node):
    # `contexts` tracks the ORIGINAL context-manager value (`ctx_v`,
    # `ctx_t`) for each item, separately from the user-visible bound
    # name (`alias`, real Python's `with X() as v:` binds `v` to
    # `X().__enter__()`'s RETURN value, not to the `X()` instance
    # itself) — __exit__ must always be called on the context manager
    # object, never on whatever __enter__ happened to return.
    # 3 index-parallel lists rather than a list of 3-tuples — the
    # self-hosted backend boxes `contexts[i][k]` tuple-element access.
    _ctx_ts = []
    _ctx_vs = []
    _ctx_sns = []
    # parallel per-item generator-context info: base name (or None) + the
    # coroutine handle value. Two lists, not a list of (v, base) tuples.
    _gctx_bases = []
    _gctx_vs = []
    for item in node.items:
        et, ev = gen.lower_expr(item.expr)
        ctx_t, ctx_v = et, ev
        struct_name = gimple_exprtypes._struct_name_of(et)
        # A @contextlib.contextmanager-decorated generator method/function
        # call lowers to a compiled-coroutine handle ('MojoGenerator *',
        # registered in _generator_var_api by its start-call emission).
        # Drive it directly: first resume() runs the body to the first
        # yield (= __enter__), the second (after the body) runs it to
        # completion (= __exit__); <base>_value(g) is what `as` binds.
        # Before this, both protocol steps were placeholder comments and
        # the coroutine body NEVER RAN — cwriter.py's header_guard
        # (the motivating real shape) compiled clean but silently wrote
        # nothing. The exceptional path (body raises → skip the final
        # resume + destroy) is deliberately not threaded through the
        # setjmp machinery here: the status quo this replaces ran NO body
        # code at all, so normal-path correctness is strictly better and
        # no previously-working behavior changes.
        gen_api = (gen._generator_var_api.get(ctx_v)
                   if ctx_t == 'MojoGenerator *' else None)
        if gen_api is not None:
            base = gen_api['base']
            resume_t = gen._new_temp('_Bool')
            gen._emit(f"  {resume_t} = {base}_resume ({ctx_v});")
            if item.alias is not None:
                alias = _with_item_alias_name(item.alias)
                val_t = gen._call_expr('int64_t', f"{base}_value",
                                       [('MojoGenerator *', ctx_v)])
                if alias not in gen.var_types:
                    gen._declare_var(alias, 'int64_t')
                gen._safe_coerce_emit('int64_t', gen.var_types[alias], val_t, alias)
            _gctx_bases.append(base)
            _gctx_vs.append(ctx_v)
            _ctx_ts.append(ctx_t)
            _ctx_vs.append(ctx_v)
            _ctx_sns.append(None)
            continue
        enter_fn    = gen._struct_method_csym(struct_name, '__enter__', '')
        has_enter = (enter_fn in gen.func_return_types
                     or f"{struct_name}___enter__" in gen.func_return_types)
        # __enter__'s return value, not the context manager itself, is
        # what gets bound to the `as` target — previously this called
        # __enter__ purely for its side effects and discarded the
        # result, binding the alias to the raw ctx-manager object
        # instead (the compiled-path analogue of the interpreter bug
        # fixed in myinterpreter.py's execute_WithStmt — see bugs/
        # INTERP_with_as_binding_for_loop_keyerror.md). Found via
        # Tools/ftscalingbench/ftscalingbench.py's MyContextManager.
        enter_ret_t = gen.func_return_types.get(enter_fn, et) if has_enter else et
        if has_enter and enter_ret_t == 'void':
            # A void-returning __enter__ (a legitimate, common Mojo
            # shape — no explicit return, side-effects only, e.g.
            # test/tempfile/test_tempfile.mojo's TempEnvWithCleanup)
            # has no value to capture; `void _t = f();` is invalid C.
            # Call it as a statement instead. There is nothing
            # meaningful to bind an `as` target to in this shape
            # either — real code with a void __enter__ never uses one
            # (this real-world file's own `with TempEnvWithCleanup
            # (...):` has none) — fall back to the ctx manager value
            # itself rather than crash if it somehow does.
            gen._emit_call('void', '', enter_fn, [(et, ctx_v)])
            enter_v = ctx_v
            enter_ret_t = et
        elif has_enter:
            enter_v = gen._call_expr(enter_ret_t, enter_fn, [(et, ctx_v)])
        else:
            gen._emit(f"  /* with: __enter__ ({struct_name}) */")
            enter_v = ctx_v
            enter_ret_t = et
        # Register the item for its TEARDOWN before deciding anything about
        # the `as` target, which is what the generator arm just above does.
        # These five appends used to sit INSIDE `if item.alias is not None:`,
        # so `with ctx():` — no `as` — appended nothing at all: `has_exit`
        # below stayed False, no `setjmp`-protected region was emitted, and
        # `_with_emit_exits` walked an empty list. `__enter__` was called, the
        # body ran, and the teardown was never emitted. Not a wrong `__exit__`
        # argument and not a missing `mojo_exc_pop` — no teardown at all, with
        # exit 0, on every `with` whose context manager has one.
        #
        # Real Python calls `__exit__` for `with C():` too, so this is a
        # compiled-path-only divergence, and `test_runtime_diff.py`'s A/B engine
        # comparison cannot see it either: the two engines differ on the
        # OUTPUT, and here the output can be identical (the body worked) while
        # the teardown never ran.
        #
        # It was found on a LOCK: `build_stdlib_dylib`'s publish lock, where
        # `with _OutputLock(out):` silently never released it and wedged every
        # other process wanting the same lock for the life of the tree —
        # exactly the cross-process situation the lock exists for. Any
        # resource with an `__exit__` (a temp file, a transaction, a
        # subprocess) leaks per iteration.
        #
        # `has_exit` and `_with_emit_exits` need no change: they already
        # consume exactly these lists, and index-parallelism is the
        # convention the generator arm established (which is why it is three
        # lists and not a list of tuples).
        _ctx_ts.append(ctx_t)
        _ctx_vs.append(ctx_v)
        _ctx_sns.append(struct_name)
        _gctx_bases.append(None)   # keep index-parallel
        _gctx_vs.append(None)
        if item.alias is not None:
            alias = _with_item_alias_name(item.alias)
            if alias not in gen.var_types:
                gen._declare_var(alias, enter_ret_t)
            gen._safe_coerce_emit(enter_ret_t, gen.var_types[alias], enter_v, alias)

    has_exit = False
    for _hxi in range(len(_ctx_sns)):
        _hsn = _ctx_sns[_hxi]
        if _hsn is not None and (
                gen._struct_method_csym(_hsn, '__exit__', '') in gen.func_return_types
                or f"{_hsn}___exit__" in gen.func_return_types):
            has_exit = True
            break
    # A GENERATOR context manager has no `__exit__` to find that way — its
    # teardown is the final `resume()` + `destroy()` in `_with_emit_exits`,
    # which the normal-exit emission below already calls. So this pre-scan
    # used to read the generator arm as "no teardown", leave `has_exit`
    # False, skip the whole setjmp region, and the teardown then existed ONLY
    # on the fallthrough path: a body that raised propagated straight out with
    # the generator still parked at its `yield`, so everything after the
    # `yield` — which for `@contextlib.contextmanager` is the `finally` that
    # releases the resource — never ran. Silent, and invisible from the
    # program's own output (the body's work all happened).
    #
    # Measured on this tree, a `@contextmanager` whose `finally` prints:
    #
    #     with tracked("a"): print("body a"); raise ValueError
    #
    # compiled to `enter a / body a / caught / done` — Python's answer has
    # `exit a` between `body a` and `caught`. The `bb_exc` block below
    # already calls `_with_emit_exits` before `mojo_raise()`; it was simply
    # never generated for this arm.
    #
    # The arm's own comment when it was added said the exceptional path was
    # "deliberately not threaded through the setjmp machinery here", which was
    # true when the alternative was emitting NO body code at all. It is not a
    # reason to leave a resource unreleased now that the arm is what ordinary
    # `@contextlib.contextmanager` code lowers to.
    if not has_exit:
        for _hgi in range(len(_gctx_bases)):
            if _gctx_bases[_hgi] is not None:
                has_exit = True
                break

    if has_exit:
        # See _reset_func's own comment on `_func_used_setjmp` -- same
        # setjmp/__GIMPLE hazard as _gen_stmt_TryStmt, here for a
        # `with`-block whose context manager has a real `__exit__`.
        gen._func_used_setjmp = True
        sj_ret = gen._new_temp('int')
        cond_t = gen._new_temp('_Bool')
        bb_try   = gen._new_bb()
        bb_exc   = gen._new_bb()
        bb_after = gen._new_bb()
        # Emit setjmp directly in the generated function (not via mojo_try_push
        # wrapper) so the setjmp frame stays live for longjmp from mojo_raise.
        # Use proper GIMPLE pattern with temporaries for increment and address.
        temp_top1 = gen._new_temp('int')
        temp_inc = gen._new_temp('int')
        temp_top2 = gen._new_temp('int')
        temp_addr = gen._new_temp('void *')  # jmp_buf is int[48], use void* to avoid type mismatch
        gen._emit(f"  {temp_top1} = _mojo_exc_top;")
        gen._emit(f"  {temp_inc} = {temp_top1} + 1;")
        gen._emit(f"  _mojo_exc_top = {temp_inc};")
        gen._emit(f"  {temp_top2} = _mojo_exc_top;")
        # See _gen_stmt_TryStmt's identical checkpoint-save call for why.
        gen._emit("  mojo_cleanup_checkpoint_save ();")
        # GIMPLE: pass array element directly to setjmp (decays to int*)
        gen._emit(f"  {sj_ret} = setjmp (_mojo_exc_stack[{temp_top2}]);")
        gen._emit(f"  {cond_t} = {sj_ret} != 0;")
        gen._emit(f"  if ({cond_t}) goto {bb_exc}; else goto {bb_try};")

        gen._emit_label(bb_try)
        # Set when the interceptor below has ALREADY emitted this region's
        # teardown on an early-exit path, so the tail block below does not emit
        # it a second time as unreachable code. A one-element list rather than
        # a `nonlocal`, for the self-hosted compiled path.
        _teardown_done = [False]
        for s in node.body:
            # break/continue lower to a bare `goto <loop label>;` and jump
            # out of this with's protected region same as an early return
            # — same leak as in _gen_stmt_TryStmt if unaccounted for.
            #
            # Both of those paths popped the exception stack and emitted
            # NOTHING else, so the teardown never ran on them either: a
            # `return` out of a `with` body, or a `continue`/`break` out of
            # one, left the context manager's `__exit__` uncalled. That is
            # pre-existing and hit the `as` spelling too — but the tail block
            # below emits its teardown AFTER the body, i.e. after the `return`,
            # so the very lines meant to clean up were themselves dead. The
            # teardown has to be emitted BEFORE the statement that leaves.
            #
            # The `return` is caught at the STATEMENT level rather than in the
            # emitter interceptor, because `_with_emit_exits`'s own docstring
            # records that a nested closure in this function emitted NOTHING
            # once the self-hosted binary compiled the compiler (a real
            # stage1-vs-stage2 divergence). Anything that must be reliable here
            # belongs outside the closure. `type(x).__name__` is the
            # established spelling in this file family (see `_lower_LambdaExpr`'s
            # `_bound` scan).
            if type(s).__name__ == 'ReturnStmt':
                _with_emit_exits(gen, _ctx_ts, _ctx_vs, _ctx_sns,
                                 _gctx_bases, _gctx_vs)
                _teardown_done[0] = True
            original_emit = gen._emit
            def intercepted_emit(line, rv=None, rt=None):
                stripped = line.strip()
                if gen.loop_stack and stripped in (
                    f"goto {gen._loop_continue_bb()};",
                    f"goto {gen._loop_break_bb()};",
                ):
                    original_emit("  mojo_exc_pop ();")
                    _with_emit_exits(gen, _ctx_ts, _ctx_vs, _ctx_sns,
                                     _gctx_bases, _gctx_vs)
                    _teardown_done[0] = True
                    original_emit(line)
                    return
                original_emit(line)
            gen._emit = intercepted_emit
            gen.gen_stmt(s)
            gen._emit = original_emit
        # Only emit cleanup and goto if the with body didn't end with a
        # return — but an early return still leaves the protected region
        # and must pop the exception stack (_mojo_exc_top) exactly like
        # the normal-exit path does (see the matching fix and comment in
        # _gen_stmt_TryStmt — this is the same leak, in the `with`
        # codegen instead of `try`). It does NOT re-emit the teardown when the
        # interceptor already did it above (`_teardown_done`).
        if not gen._last_was_terminal:
            gen._emit("  mojo_exc_pop ();")
            _with_emit_exits(gen, _ctx_ts, _ctx_vs, _ctx_sns, _gctx_bases, _gctx_vs)
            gen._emit(f"  goto {bb_after};")
        elif not _teardown_done[0]:
            gen._emit("  mojo_exc_pop ();")
            _with_emit_exits(gen, _ctx_ts, _ctx_vs, _ctx_sns, _gctx_bases, _gctx_vs)

        gen._emit_label(bb_exc)
        gen._emit("  mojo_exc_pop ();")
        _with_emit_exits(gen, _ctx_ts, _ctx_vs, _ctx_sns, _gctx_bases, _gctx_vs)
        gen._emit("  mojo_raise ();")
        # Only emit goto if the exception handler didn't end with a return
        if not gen._last_was_terminal:
            gen._emit(f"  goto {bb_after};")

        gen._emit_label(bb_after)
    else:
        for s in node.body:
            gen.gen_stmt(s)
        _with_emit_exits(gen, _ctx_ts, _ctx_vs, _ctx_sns, _gctx_bases, _gctx_vs)
