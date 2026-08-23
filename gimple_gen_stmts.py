"""Statement lowering for the GIMPLE backend.

Function-extraction architecture: former GimpleGen methods as module-level
functions taking `gen` first; delegates remain on the class; cross-module
references are qualified (single-emission closure rule).
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

def gen_stmt(gen, node):
    # Emit #line directive to track source location. Critical for debugging:
    # optimizations intermix and reorder code from different lines and files.
    # Only emit if we haven't emitted this exact (filename, line) pair before.
    node_kind = type(node).__name__
    if hasattr(node, 'line') and node.line and node.line > 0:
        filename = '' + getattr(gen, '_current_filename', '')
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
        gen._gen_stmt_VarDecl(node)
    elif isinstance(node, gimple_ctypes.AssignStmt):
        gen._gen_stmt_AssignStmt(node)
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
        gen._gen_stmt_ForStmt(node)
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
    elif isinstance(node, gimple_ctypes.MatchStmt):
        gen._gen_stmt_MatchStmt(node)
    elif isinstance(node, gimple_ctypes.DelStmt):
        gen._gen_stmt_DelStmt(node)
    else:
        gimple_ctypes._debug_note('unknown statement dropped', node_kind)
        gen._emit(f"  /* TODO: {node_kind} */")

    if (body_start is not None and hasattr(node, 'line') and node.line and node.line > 0
            and len(gen.body_lines) - body_start > 1):
        filename = getattr(gen, '_current_filename', '')
        directive = f"#line {node.line} \"{filename}\"" if filename else f"#line {node.line}"
        # Skip the very first emitted line (already directly preceded by
        # the directive above); re-stamp every one after it, from the end
        # backwards so earlier insertions don't shift later indices.
        for i in range(len(gen.body_lines) - 1, body_start, -1):
            if gen.body_lines[i] != directive and not gen.body_lines[i].lstrip().startswith('#line '):
                gen.body_lines.insert(i, directive)


def _gen_stmt_PassStmt(gen, node):
    return


def _annotation_dict_val_type(gen, ann) -> str | None:
    """`dict[K, V]` / `Dict[K, V]` annotation → the dict's VALUE C type,
    else None. Seeds _dict_val_types so dict.items()/d[k] reads pick the
    right accessor for a string-valued dict (without it, `self._str_pool:
    dict[str, str]` in __init__ left the value type unknown, and the
    self-hosted string-pool loop read the boxed value slot via get_int,
    emitting `static char * <address> = "<address>"` instead of
    `_slit_N = "text"`)."""
    if isinstance(ann, str):
        s = ann.strip()
        if s.startswith('dict[') or s.startswith('Dict['):
            inner = s.split('[', 1)[1].rstrip(']').strip()
            parts = gimple_ctypes._split_top_level_commas(inner)
            if len(parts) >= 2:
                return gen._resolve_type(parts[1].strip())
    return None


def _gen_stmt_VarDecl(gen, node):
    # `var name = value` where `name` is heap-boxed (some nested
    # closure captures it BY REFERENCE -- see _seed_mut_captured_
    # local_types's docstring): `_declare_var` already emitted the
    # POINTER declaration (`{ctype} * name;`) before this statement
    # ever runs. Allocate the box, then store the (coerced) initial
    # value through it -- mirrors the env-struct allocator's own
    # `_vp = malloc (...); _e = (T *) _vp;` two-step pattern (`-fgimple`
    # requires the malloc/cast split; a direct `name = (T *) malloc
    # (...)` in one statement is invalid GIMPLE).
    if (isinstance(node.name, str) and node.name in gen._boxed_mut_locals
            and node.value is not None):
        ctype = gen._boxed_mut_locals[node.name]
        cname = gen._cname(node.name)
        # A literal byte count, not `sizeof({ctype})`: confirmed via a
        # hand-reduced repro that `-fgimple` rejects `sizeof(int64_t)`
        # as an inline expression ("expected expression before
        # 'sizeof'") even though `sizeof(SomeStructTypedef)` (the
        # env-struct allocator's own identical-looking pattern) is
        # accepted -- gimple's expression grammar apparently only
        # recognizes `sizeof` applied to an aggregate/struct type name,
        # not a scalar typedef. `_SCALAR_CTYPE_SIZE` covers every ctype
        # `ClosureInfo.captures`/`_quick_type` can actually produce for
        # a `{mut}`-captured local (see _seed_mut_captured_local_types).
        vp = gen._new_val('void *', f"malloc ({gimple_codegen._SCALAR_CTYPE_SIZE.get(ctype, 8)})")
        gen._emit(f"  {cname} = ({ctype} *) {vp};")
        vtype, v = gen.lower_expr(node.value)
        gen._safe_coerce_emit(vtype, ctype, v, f'*{cname}')
        return
    # Tuple VarDecl: parser sets name='a,b' for `a, b = expr`. Lower as individual
    # assignments to avoid GIMPLE's implicit multi-value decl which causes
    # "redeclaration with no linkage" when the names were already declared.
    if isinstance(node.name, str) and ',' in node.name and node.value is not None:
        names = [n.strip() for n in node.name.split(',')]
        vtype, v = gen.lower_expr(node.value)
        for i, n in enumerate(names):
            if n == '_':
                continue
            # _tuple_elem_value resolves the element accessor from the
            # (possibly int64_t-boxed) tuple's real element type, so a
            # char*-tuple VarDecl declares real char* locals instead of
            # storing pointer decimals in int64_t ones.
            et, ev = gen._tuple_elem_value(vtype, v, i)
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
        if ctype in ('MojoList *', 'MojoSet *') and v in gen._elem_types:
            gen._elem_types[node.name] = gen._elem_types[v]
        if ctype == 'MojoDict *':
            if v in gen._elem_types:
                gen._elem_types[node.name] = gen._elem_types[v]
            if v in gen._dict_val_types:
                gen._dict_val_types[node.name] = gen._dict_val_types[v]
        # If value has element type tracking (e.g. split result), propagate to inferred var
        if node.type_ann is None and v in gen._elem_types:
            gen._elem_types[node.name] = gen._elem_types[v]
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
        # `var f = <closure value>` (see _lower_IdentExpr's closure-value
        # materialization): carry the closure's real return type along
        # with the variable so a later `f()` (_lower_bound_method_call)
        # narrows the result correctly — mirrors the AssignStmt path's
        # identical propagation (see _track_pointer_actual_type's caller
        # a few lines below this method).
        if actual_dst == 'MojoBoundMethod *' and v in gen._bound_method_ret_types:
            gen._bound_method_ret_types[node.name] = gen._bound_method_ret_types[v]
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
        if actual_dst == 'MojoList *' and isinstance(node.type_ann, str) \
                and '[' in node.type_ann and not node.type_ann.startswith('['):
            _li = gimple_ctypes._split_top_level_commas(
                node.type_ann.split('[', 1)[1].rstrip(']').strip())
            if _li:
                try:
                    _et = gen._resolve_type(_li[0].strip())
                except Exception:
                    _et = None
                if _et and _et != 'int64_t' and node.name not in gen._elem_types:
                    gen._elem_types[node.name] = _et
        gen._safe_coerce_emit(vtype, actual_dst, v, gen._write_dest(node.name))
    else:
        ctype = gen._resolve_type(node.type_ann)
        gen._declare_var(node.name, ctype)
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
        # via box.3d/game/bugs/DYLIB_string_copy_append_return_segv.md
        # -- despite the bug report's title, this reproduces identically
        # in `mojo build`'s linked-executable path too, nothing to do
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
    mojo_compiler.py's own _strip_string_prefix_and_quotes, where
    `len(rest)`/`rest[0]` on the tuple-unpacked `rest` misread it as a
    MojoList* and segfaulted deep in mojo_list_get_int."""
    if dst != 'int64_t':
        if v in gen._struct_field_owners:
            gen._struct_field_owners[tname] = list(gen._struct_field_owners[v])
        if dst == 'MojoList *' and v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
        return
    if v in gen._actual_types:
        gen._actual_types[tname] = gen._actual_types[v]
    elif vtype.endswith(' *'):
        gen._actual_types[tname] = vtype
        if v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
        if v in gen._dict_val_types:
            gen._dict_val_types[tname] = gen._dict_val_types[v]
    elif vtype == 'char':
        gen._actual_types[tname] = 'char'
    if v in gen._struct_field_owners:
        gen._struct_field_owners[tname] = list(gen._struct_field_owners[v])
    if tname in gen._actual_types:
        actual_type = gen._actual_types[tname]
        if actual_type == 'MojoList *' and v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._nested_elem_types:
                gen._nested_elem_types[tname] = gen._nested_elem_types[v]
        elif actual_type == 'MojoDict *':
            if v in gen._elem_types:
                gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._dict_val_types:
                gen._dict_val_types[tname] = gen._dict_val_types[v]


def _assign_target(gen, tgt, et, ev):
    """Assign a lowered value (et, ev) to one unpack target, which may be a
    plain name or a nested tuple (e.g. (a, b), (c, d) = ...). Recurses for
    nested tuples by indexing the inner iterable."""
    if isinstance(tgt, gimple_ctypes.IdentExpr):
        if tgt.name not in gen.var_types:
            hint = gen._inferred_var_types.get(gen.current_func_name, {}).get(tgt.name) \
                if hasattr(gen, '_inferred_var_types') else None
            gen._declare_var(tgt.name, hint or et)
        gen._track_pointer_actual_type(tgt.name, gen.var_types[tgt.name], ev, et)
        gen._safe_coerce_emit(et, gen.var_types[tgt.name], ev, gen._write_dest(tgt.name))
    elif isinstance(tgt, gimple_ctypes.TupleExpr):
        # ev is itself an iterable; view it as a MojoList* and unpack by index.
        lp = ev if et == 'MojoList *' else gen._new_temp('MojoList *')
        if et != 'MojoList *':
            gen._emit(f"  {lp} = (MojoList *){ev};")
        for i, sub in enumerate(tgt.elements):
            idx64 = gen._new_val('int64_t', f"(int64_t){i}")
            elem_type = gen._elem_of(lp)
            suf = gimple_ctypes.TypeLattice.list_suffix(elem_type)
            set_et = elem_type if elem_type != 'unknown' else 'int64_t'
            sev = gen._new_val(set_et, f"mojo_list_get_{suf} ({lp}, {idx64})")
            gen._assign_target(sub, set_et, sev)


def _is_except_as_member_target(gen, obj_node) -> bool:
    """True when `obj_node` (a MemberExpr's `.obj`) is a bare identifier
    currently bound by an enclosing `except <ExcType> as <name>:` clause
    — see `self._except_as_names`'s own docstring. Deliberately keyed off
    this SYNTACTIC fact (which name was introduced by an except-as
    binding), not the receiver's C type (`char *`), so this can never
    accidentally match an ordinary string variable that merely happens
    to share a name — an ordinary string is never added to
    `_except_as_names` in the first place. See bugs/hard/
    CODEGEN_dynamic_attribute_on_generic_object.md's "Residual gap"
    section for why the type-keyed alternative was rejected."""
    return (isinstance(obj_node, gimple_ctypes.IdentExpr)
            and obj_node.name in gen._except_as_names)


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


def _gen_stmt_AssignStmt(gen, node):
    # Tuple unpacking: a, b, c = x, y, z  (targets may nest: (a,b),(c,d) = ...)
    if isinstance(node.target, gimple_ctypes.TupleExpr):
        targets = node.target.elements
        # Extended unpacking: one target may be starred (`*row, last =
        # data` / `first, *rest = data` — real Python syntax, parses as
        # UnaryOp(op='*', operand=<real target>) inside `elements`, see
        # mojo_compiler.py). The starred target collects whatever's
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
            lp = v if vtype == 'MojoList *' else gen._new_temp('MojoList *')
            if vtype != 'MojoList *':
                gen._emit(f"  {lp} = (MojoList *){v};")
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
            star_stop = gen._new_val('int64_t', f"{total} - {n_after}")
            star_v = gen._new_val('MojoList *', f"mojo_list_slice ({lp}, {star_start}, {star_stop})")
            gen._elem_types[star_v] = elem_type
            gen._assign_target(star_target, 'MojoList *', star_v)
            for j, tgt in enumerate(after):
                idx64 = gen._new_val('int64_t', f"{star_stop} + {j}")
                sev = gen._new_val(set_et, f"mojo_list_get_{suf} ({lp}, {idx64})")
                gen._assign_target(tgt, set_et, sev)
            return
        if isinstance(node.value, gimple_ctypes.TupleExpr) and len(node.value.elements) == len(targets):
            # RHS is a tuple literal — lower and assign each element individually
            for tgt, rhs_expr in zip(targets, node.value.elements):
                et, ev = gen.lower_expr(rhs_expr)
                gen._assign_target(tgt, et, ev)
        else:
            # RHS is a single iterable — lower it, then index each element
            vtype, v = gen.lower_expr(node.value)
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
        _dv = gen._annotation_dict_val_type(getattr(node, 'type_ann', None))
        if _dv is not None:
            gen._dict_val_types[tname] = _dv
        folded = gen._try_const_fold_str(node.value)
        if folded is not None:
            gen._const_str_locals[(gen.current_func_name, tname)] = folded
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
                        None, gen.module_name or "root"))))
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
            if vtype == 'MojoDict *':
                if v in gen._dict_val_types:
                    gen._dict_val_types[tname] = gen._dict_val_types[v]
            elif vtype == 'MojoList *':
                if v in gen._elem_types:
                    gen._elem_types[tname] = gen._elem_types[v]
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
            # Propagate dict/list/set value-type tracking for module-level
            # globals — the same fix as the _func_declared_globals branch above,
            # but for the toplevel-gen path that module-level assignments take.
            if vtype == 'MojoDict *':
                if v in gen._dict_val_types:
                    gen._dict_val_types[tname] = gen._dict_val_types[v]
            elif vtype == 'MojoList *':
                if v in gen._elem_types:
                    gen._elem_types[tname] = gen._elem_types[v]
            # Propagate _actual_types so the global load path (line 6481)
            # sets the correct actual type instead of gtype (which may be
            # int64_t).  Without this, a boxed MojoDict* or MojoList* stored
            # in a global variable is loaded back as plain int64_t and the
            # subscript dispatch falls through to the generic MojoList*
            # cast path — see BUG-2026-044.
            if vtype.endswith(' *') and v in gen._actual_types:
                gen._actual_types[tname] = gen._actual_types[v]
            elif v in gen._actual_types:
                gen._actual_types[tname] = gen._actual_types[v]
            return
        # Regular local variable assignment
        if tname not in gen.var_types:
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
            # 'int' (bare) is the hallucination marker — no real answer. If the
            # value is actually a container pointer (e.g. a dict read whose value
            # type is a dict/list/set), trust ground truth so a later
            # .get()/subscript dispatches on the right container.
            if ctype == 'int' and vtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
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
            # bugs/CODEGEN_untyped_param_string_passthrough_wrong.md.
            if ctype in ('int', 'int64_t') and vtype not in ('int', 'int64_t') and vtype.endswith('*'):
                ctype = vtype
            gen._declare_var(tname, ctype)
            # BUG-2026-023 residual (box.3d/game FileSystem.current_dir_path):
            # the rewriter turns `parts: List[String] = ...` into an
            # AssignStmt carrying type_ann (this file's VarDecl handler never
            # sees body declarations). Seed the list ELEMENT type from that
            # annotation so insert()/index-stores + later subscript reads
            # dispatch on the real element instead of int64_t handles.
            _ann_as = getattr(node, 'type_ann', None)
            if ctype == 'MojoList *' and isinstance(_ann_as, str) \
                    and '[' in _ann_as and not _ann_as.startswith('['):
                _li = gimple_ctypes._split_top_level_commas(
                    _ann_as.split('[', 1)[1].rstrip(']').strip())
                if _li:
                    try:
                        _et = gen._resolve_type(_li[0].strip())
                    except Exception:
                        _et = None
                    if _et and _et != 'int64_t':
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

        if dst in ('MojoList *', 'MojoSet *') and v in gen._elem_types:
            gen._elem_types[tname] = gen._elem_types[v]
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
            # bugs/COMPILE_FAIL_Tools_check-c-api-docs_main.md.
            if v in gen._tuple_slot_types:
                gen._tuple_slot_types[tname] = gen._tuple_slot_types[v]
        if dst == 'MojoDict *':
            if v in gen._elem_types:
                gen._elem_types[tname] = gen._elem_types[v]
            if v in gen._dict_val_types:
                gen._dict_val_types[tname] = gen._dict_val_types[v]
        # `f = self.b` (a bound-method value, see _lower_bound_method_value):
        # carry the method's real return type along with the variable so a
        # later `f()` (_lower_bound_method_call) narrows the result
        # correctly instead of assuming int64_t.
        if dst == 'MojoBoundMethod *' and v in gen._bound_method_ret_types:
            gen._bound_method_ret_types[tname] = gen._bound_method_ret_types[v]
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
        gen._track_pointer_actual_type(tname, dst, v, vtype)
        gen._safe_coerce_emit(vtype, dst, v, gen._write_dest(tname))
    elif isinstance(node.target, gimple_ctypes.MemberExpr):
        # `sys.argv = [...]` — a whole-list rebind. Reads lower to
        # mojo_get_argv() (see _lower_MemberExpr's sys/argv case), so the
        # write needs the matching runtime store or it is silently
        # dropped: mojo.py's own CLI strips its `--dump`/`--dump-full`
        # flags exactly this way before `input_file = sys.argv[1]`, and
        # without this the compiled binary kept the unstripped argv and
        # used the FLAG as the input filename (bootstrap stage 2/3 wrote
        # `--dump.ci` instead of `<basename>.ci` for every file).
        if (isinstance(node.target.obj, gimple_ctypes.IdentExpr)
                and node.target.obj.name == 'sys'
                and node.target.member == 'argv'):
            _av = v if vtype == 'MojoList *' else gen._new_val(
                'MojoList *', f"(MojoList *){v}")
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
            # _synthesize_fieldwise_inits (mojo_compiler.py) never taking
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
            # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
            # "Residual gap: caught exception objects" section.
            gen._emit_dynattr_setattr_dispatch(node.target.member, vtype, v, ot, ov)
        else:
            op = '->' if '*' in ot else '.'
            struct_name = gimple_exprtypes._struct_name_of(ot)
            field_type = gen.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
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
        if ot == 'MojoList *':
            elem = gen._elem_of(obj_v)
            suf  = gimple_ctypes.TypeLattice.list_suffix(elem)
            idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
            ev_cast = gen._cast_for_list(vtype, v, suf)
            gen._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
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
            # Found via mojo_compiler.py's own `_parse_postfix`'s
            # `keywords: dict = {}` (populated with parsed expression AST
            # nodes, then read back via `keywords.items()`) segfaulting
            # once self-hosted.
            if vtype in ('char *', 'double', 'MojoDict *', 'MojoList *', 'MojoSet *') or vtype.endswith(' *'):
                gen._dict_val_types[obj_v] = vtype
            # dict[key] = val → mojo_dict_set_str_* (key coerced via
            # _char_to_cstr, the single dict-key-to-string conversion
            # used by both read and write sides — see its docstring).
            _, key_tmp = gen._char_to_cstr(it, idx_v)
            if vtype == 'char *':
                gen._emit_call('void', '', 'mojo_dict_set_str',
                                [('MojoDict *', obj_v), ('char *', key_tmp), ('char *', v)])
            else:
                # Mark so generic repr() prints True/False instead of 1/0
                # for this dict's values — see mojo_mark_dict_bool_values's
                # doc comment in runtime/mojo_runtime.c.
                if isinstance(node.value, gimple_ctypes.BoolLiteral):
                    gen._emit(f"  mojo_mark_dict_bool_values ({obj_v});")
                # Pass actual vtype so _emit_call can coerce pointers to int64_t
                gen._emit_call('void', '', 'mojo_dict_set_int',
                                [('MojoDict *', obj_v), ('char *', key_tmp), (vtype, v)])
        else:
            # Opaque int-typed container: check if it's a list or dict
            if ot in ('int', 'int64_t'):
                # Check if this is actually a list (from nested access) or dict
                actual_type = gen._get_actual_type(ot, obj_v)
                if actual_type == 'MojoList *':
                    # It's a list - cast to MojoList* and set element
                    ip = gen._new_temp('int64_t')
                    lp = gen._new_temp('MojoList *')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    gen._emit(f"  {lp} = (MojoList *){ip};")
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
                    dp = gen._new_temp('MojoDict *')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    gen._emit(f"  {dp} = (MojoDict *){ip};")
                    _, key_tmp2 = gen._char_to_cstr(it, idx_v)
                    if isinstance(node.value, gimple_ctypes.BoolLiteral):
                        gen._emit(f"  mojo_mark_dict_bool_values ({dp});")
                    # Pass actual vtype so _emit_call can coerce pointers to int64_t
                    gen._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', dp), ('char *', key_tmp2), (vtype, v)])
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
                                gen._emit(f"  /* TODO: struct subscript write [{elem_t}] skipped */")
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
        gen._safe_coerce_emit(vtype, dst, v, gen._write_dest(tname))
    elif isinstance(node.target, gimple_ctypes.MemberExpr):
        # `sys.argv = [...]` — a whole-list rebind. Reads lower to
        # mojo_get_argv() (see _lower_MemberExpr's sys/argv case), so the
        # write needs the matching runtime store or it is silently
        # dropped: mojo.py's own CLI strips its `--dump`/`--dump-full`
        # flags exactly this way before `input_file = sys.argv[1]`, and
        # without this the compiled binary kept the unstripped argv and
        # used the FLAG as the input filename (bootstrap stage 2/3 wrote
        # `--dump.ci` instead of `<basename>.ci` for every file).
        if (isinstance(node.target.obj, gimple_ctypes.IdentExpr)
                and node.target.obj.name == 'sys'
                and node.target.member == 'argv'):
            _av = v if vtype == 'MojoList *' else gen._new_val(
                'MojoList *', f"(MojoList *){v}")
            gen._emit_call('void', '', 'mojo_replace_argv',
                            [('MojoList *', _av)])
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
            # bugs/COMPILE_FAIL_Tools_i18n_pygettext.md.
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
            _, key_tmp = gen._char_to_cstr(it, idx_v)
            if vtype == 'char *':
                gen._emit_call('void', '', 'mojo_dict_set_str',
                                [('MojoDict *', obj_v), ('char *', key_tmp), ('char *', v)])
            else:
                gen._emit_call('void', '', 'mojo_dict_set_int',
                                [('MojoDict *', obj_v), ('char *', key_tmp), (vtype, v)])
        elif ot in ('int', 'int64_t'):
            # Opaque int/int64_t used as subscript target — could be a
            # list OR a dict (e.g. a closure-captured env field, whose
            # static type isn't tracked); check like _gen_stmt_AssignStmt
            # does rather than always assuming MojoList.
            actual_type = gen._get_actual_type(ot, obj_v)
            if actual_type == 'MojoDict *':
                ip = gen._new_temp('int64_t')
                dp = gen._new_temp('MojoDict *')
                gen._emit(f"  {ip} = (int64_t){obj_v};")
                gen._emit(f"  {dp} = (MojoDict *){ip};")
                _, key_tmp2 = gen._char_to_cstr(it, idx_v)
                if vtype == 'char *':
                    gen._emit_call('void', '', 'mojo_dict_set_str',
                                    [('MojoDict *', dp), ('char *', key_tmp2), ('char *', v)])
                else:
                    gen._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', dp), ('char *', key_tmp2), (vtype, v)])
            else:
                ip = gen._new_val('int64_t', f"(int64_t){obj_v}")
                lp = gen._new_val('MojoList *', f"(MojoList *){ip}")
                elem = gen._elem_of(obj_v)
                suf = gimple_ctypes.TypeLattice.list_suffix(elem)
                idx64 = gen._new_val('int64_t', f"(int64_t) {idx_v}")
                gen._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {v});")
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
                gen._emit(f"  {obj_v}[{idx_v}] = {v};")
    else:
        pass  # complex aug-assign target: no-op


def _gen_stmt_ReturnStmt(gen, node):
    if node.value is None:
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
        if v in gen._elem_types:
            gen._return_elem_types[gen.current_func_name] = gen._elem_types[v]
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
    if ctype == '_Bool':
        return val
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


def _gen_stmt_IfStmt(gen, node):
    cond_type, cond_v = gen.lower_expr(node.condition)
    cond_v  = gen._ensure_bool_cond(cond_type, cond_v)
    bb_true     = gen._new_bb()
    bb_merge    = gen._new_bb()
    has_else    = bool(node.elifs or node.else_body)
    bb_false    = gen._new_bb() if has_else else bb_merge

    gen._emit(f"  if ({cond_v}) goto {bb_true}; else goto {bb_false};")
    gen._emit_label(bb_true)
    for s in node.then_body:
        gen.gen_stmt(s)
    gen._emit(f"  goto {bb_merge};")

    current_false = bb_false
    elifs = list(node.elifs)
    while elifs:
        ec, eb = elifs.pop(0)
        gen._emit_label(current_false)
        has_more   = bool(elifs or node.else_body)
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
        for s in eb:
            gen.gen_stmt(s)
        gen._emit(f"  goto {bb_merge};")
        current_false = next_false

    if node.else_body:
        gen._emit_label(current_false)
        for s in node.else_body:
            gen.gen_stmt(s)
        gen._emit(f"  goto {bb_merge};")

    gen._emit_label(bb_merge)


def _gen_stmt_DelStmt(gen, node):
    """`del a[b]`, `del a[b:c]`, `del a[b], c[d]` — one DelStmt per
    statement, node.targets holding each comma-separated target (see
    mojo_compiler.py's DelStmt docstring).

    Previously COMPLETELY unimplemented: gen_stmt's dispatch chain had
    no DelStmt case at all, so it silently fell through to the generic
    "unknown statement dropped" fallback (a bare `/* TODO */` comment,
    no-op). This was flat-out WRONG, not just incomplete, for
    mojo_compiler.py's own `_process_nested_tstrings`: its
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
    mojo_compiler.py/myinterpreter.py/mojo.py/mojo_main.py/
    module_loader.py/generated_dispatch.py) and would need much
    broader "this variable/attribute can become undefined" plumbing to
    support correctly in a compiled — not interpreted — target; left as
    an explicit, logged gap rather than silently doing nothing for them
    specifically.
    """
    for target in node.targets:
        # A bare single-slice subscript (`x[a:b]`) parses as a SliceExpr
        # with .obj attached directly, NOT wrapped in a SubscriptExpr —
        # see mojo_compiler.py's own `_parse_postfix`: "if len(items) ==
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
            lp = ov if ot == 'MojoList *' else gen._new_val(
                'MojoList *', f"(MojoList *){gen._to_int64(ot, ov)}")
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
            lp = ov if ot == 'MojoList *' else gen._new_val(
                'MojoList *', f"(MojoList *){gen._to_int64(ot, ov)}")
            gen._emit(f"  mojo_list_del_slice ({lp}, {start_v}, {stop_v});")
            continue
        if ot == 'MojoDict *':
            key_type, key_val = gen.lower_expr(target.index)
            key_type, key_val = gen._char_to_cstr(key_type, key_val)
            gen._emit_call('int64_t', '', 'mojo_dict_pop_int',
                             [('MojoDict *', ov), (key_type, key_val)])
        elif ot == 'MojoList *':
            idx_type, idx_val = gen.lower_expr(target.index)
            idx64 = gen._to_int64(idx_type, idx_val)
            gen._emit_call('int64_t', '', 'mojo_list_pop_at',
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
            dp = gen._new_val('MojoDict *', f"(MojoDict *){it64}")
            dkey_type, dkey_val = gen.lower_expr(target.index)
            dkey_type, dkey_val = gen._char_to_cstr(dkey_type, dkey_val)
            gen._emit_call('int64_t', '', 'mojo_dict_pop_int',
                             [('MojoDict *', dp), (dkey_type, dkey_val)])
            gen._emit(f"  goto {bb_after};")
            gen._emit_label(bb_list)
            lp = gen._new_val('MojoList *', f"(MojoList *){it64}")
            lidx_type, lidx_val = gen.lower_expr(target.index)
            lidx64 = gen._to_int64(lidx_type, lidx_val)
            gen._emit_call('int64_t', '', 'mojo_list_pop_at',
                             [('MojoList *', lp), ('int64_t', lidx64)])
            gen._emit(f"  goto {bb_after};")
            gen._emit_label(bb_after)
        else:
            gimple_ctypes._debug_note('DelStmt subscript on unsupported container type', ot)
            gen._emit(f"  /* TODO: del on {ot} not supported */")


def _gen_stmt_MatchStmt(gen, node):
    """`match subject: case p1: ... case p2, p3: ... case _: ...`

    Switch-style equality dispatch (see mojo_compiler.py's MatchStmt
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

        is_wildcard = any(
            isinstance(p, gimple_ctypes.IdentExpr) and p.name == '_' for p in match_case.patterns)
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
    for s in node.body:
        gen.gen_stmt(s)
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
                            None, gen.module_name or "root"))))
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
                elif vtype == 'MojoList *':
                    if v in gen._elem_types:
                        gen._elem_types[tname] = gen._elem_types[v]
                continue
            if gen._in_toplevel_gen and tname in gen._global_var_types:
                safe_module = gimple_ctypes._c_field_name(gen._current_module_ctx or "root")
                field_ref = f"_{safe_module}_globals.{gimple_ctypes._c_field_name(tname)}"
                gtype = gen._global_dst_ctype(tname)
                gen._safe_coerce_emit(vtype, gtype, v, field_ref)
                if vtype == 'MojoDict *':
                    if v in gen._dict_val_types:
                        gen._dict_val_types[tname] = gen._dict_val_types[v]
                elif vtype == 'MojoList *':
                    if v in gen._elem_types:
                        gen._elem_types[tname] = gen._elem_types[v]
                if vtype.endswith(' *') and v in gen._actual_types:
                    gen._actual_types[tname] = gen._actual_types[v]
                elif v in gen._actual_types:
                    gen._actual_types[tname] = gen._actual_types[v]
                continue
            if tname not in gen.var_types:
                gen._declare_var(tname, vtype)
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
                _, key_tmp = gen._char_to_cstr(it2, idx_v)
                if isinstance(node.value, gimple_ctypes.BoolLiteral):
                    gen._emit(f"  mojo_mark_dict_bool_values ({obj_v});")
                gen._emit_call('void', '', 'mojo_dict_set_int',
                                [('MojoDict *', obj_v), ('char *', key_tmp), (vtype, v)])
            elif ot in ('int', 'int64_t'):
                actual_type = gen._get_actual_type(ot, obj_v)
                if actual_type == 'MojoList *':
                    ip = gen._new_temp('int64_t')
                    lp = gen._new_temp('MojoList *')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    gen._emit(f"  {lp} = (MojoList *){ip};")
                    idx64 = gen._new_val('int64_t', f"(int64_t){idx_v}")
                    elem = gen._elem_of(obj_v) or 'int64_t'
                    suf = gimple_ctypes.TypeLattice.list_suffix(elem)
                    ev_cast = gen._cast_for_list(vtype, v, suf)
                    gen._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {ev_cast});")
                else:
                    ip = gen._new_temp('int64_t')
                    dp = gen._new_temp('MojoDict *')
                    gen._emit(f"  {ip} = (int64_t){obj_v};")
                    gen._emit(f"  {dp} = (MojoDict *){ip};")
                    _, key_tmp2 = gen._char_to_cstr(it2, idx_v)
                    if isinstance(node.value, gimple_ctypes.BoolLiteral):
                        gen._emit(f"  mojo_mark_dict_bool_values ({dp});")
                    gen._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', dp), ('char *', key_tmp2), (vtype, v)])
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
    if (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.IdentExpr) and
            node.iterable.func.name == 'range'):
        gen._gen_for_range(node)
    elif (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.IdentExpr) and
            node.iterable.func.name == 'enumerate'):
        gen._gen_for_enumerate(node)
    else:
        gen._gen_for_iter(node)


def _gen_stmt_BreakStmt(gen, node):
    if gen.loop_stack:
        gen._emit(f"  goto {gen.loop_stack[-1][1]};")
    else:
        # Skip emitting comment to avoid GIMPLE global-passing issues
        pass


def _gen_stmt_ContinueStmt(gen, node):
    if gen.loop_stack:
        gen._emit(f"  goto {gen.loop_stack[-1][0]};")
    else:
        # Skip emitting comment to avoid GIMPLE global-passing issues
        pass


def _gen_stmt_ExprStmt(gen, node):
    if isinstance(node.value, gimple_ctypes.CallExpr) and isinstance(node.value.func, gimple_ctypes.IdentExpr):
        raw_name = node.value.func.name
        if raw_name == 'print':
            gen._gen_print(node.value.args, node.value.kwargs)
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
            lifted   = _outer_ci.lifted_name
            arg_pairs = [gen.lower_expr(a) for a in node.value.args]
            fname_c  = gimple_ctypes._safe_name(lifted)
            if _outer_ci.env_struct:
                null_env = gen._new_val(f'{_outer_ci.env_struct} *', f'({_outer_ci.env_struct} *)0')
                full_arg_pairs = [(f'{_outer_ci.env_struct} *', null_env)] + arg_pairs
            else:
                full_arg_pairs = arg_pairs
            gen._emit_call('void', '', fname_c, full_arg_pairs)
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
        if gen._get_actual_type(_var_ctype, raw_name) == 'MojoBoundMethod *':
            # A closure/bound-method VALUE stored in a local and called
            # as a bare statement — mirrors _lower_call's identical
            # guard, so `add5(37)` (value discarded) re-supplies the
            # bundled env/receiver instead of being silently dropped.
            gen._lower_bound_method_call(raw_name, node.value, _var_ctype)
            return
        if _var_ctype in ('int', 'int64_t', 'void *', '_Bool'):
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
        expected_params = gen.func_param_types.get(raw_name, [])
        if not expected_params and fname in gen._KNOWN_SIGS:
            expected_params = gen._KNOWN_SIGS[fname][1]
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
                if _dv is not None:
                    arg_pairs.append(gen._default_expr_to_pair(_dv))
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
                                and fname not in gimple_codegen._SELFHOST_HARDCODED_FUNCS)
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


def _handler_exc_name(gen, h):
    if h.exc_type is None:
        return None
    # `except (A, B):` stores a list of type-name strings; use the first
    # as the representative name (typed/bare classification, binding
    # type). The full OR-match across all types is done via
    # _handler_exc_all_names in the dispatch loop.
    if isinstance(h.exc_type, list):
        if len(h.exc_type) > 0:
            return h.exc_type[0]
        return None
    if hasattr(h.exc_type, 'name'):
        return h.exc_type.name
    if isinstance(h.exc_type, str):
        # Step I (create_task/Task/TaskGroup/RaisingTask project):
        # real Mojo's `except e:` idiom — a BARE identifier with no
        # `as` — means "catch anything, bind it to e" (there is no
        # Python-style class named "e" being referenced; Mojo's
        # grammar reuses the same "type or name?" position Python's
        # `except <expr>:` uses, but a bare lowercase identifier that
        # ISN'T a real, known exception type is conventionally the
        # bind-all shorthand instead — confirmed via a hand repro
        # against this project's own interpreter: `except e: print(e)`
        # after `raise Error(...)` silently never caught anything
        # before this fix, exactly mirroring the bug this method's own
        # bare-string branch had). mojo_compiler.py's parser has no
        # symbol table at parse time, so it can't distinguish these
        # up front — it always stores a bare identifier in `exc_type`
        # (see _parse_try's "the common case is a single ... exception
        # type" comment) — so the distinction has to be made HERE,
        # where struct_field_types/_KNOWN_EXCEPTION_NAMES are actually
        # available: only a name _is_exc_class_name confidently
        # recognizes as a real exception type (a builtin like
        # ValueError, or a user-defined struct) is treated as a real
        # type at all; anything else (test_raising_asyncrt.mojo's own
        # `except e:`/`except caught_err:`-style handlers) is
        # reported as untyped (None) here, which _gen_stmt_TryStmt's
        # typed/bare classification then correctly treats as a
        # catch-all — see _emit_except_handler's own mirrored fix for
        # the BINDING half of this (the name still needs to reach the
        # handler body as a real local, which `handler.name` alone
        # doesn't carry for this shape).
        if not gen._is_exc_class_name(h.exc_type):
            return None
        return h.exc_type
    return None


def _handler_exc_all_names(gen, h):
    """Every exception type name a handler catches. A single-type handler
    yields one name; a parenthesized `except (A, B):` yields all of them."""
    if isinstance(h.exc_type, list):
        return h.exc_type
    one = gen._handler_exc_name(h)
    if one is None:
        return []
    return [one]


def _handler_bind_name(gen, h):
    """The real local variable name this handler's body should bind the
    caught exception to, or None if it doesn't bind one at all. Usually
    just `h.name` (an explicit `except ... as e:`) — but Mojo's `except
    e:` idiom (a bare identifier, no `as`) parses the name into
    `h.exc_type` instead (mojo_compiler.py has no symbol table at parse
    time to tell "real type" and "bind-all name" apart — see
    _handler_exc_name's own docstring for the full rationale), so when
    `h.name` is empty but `h.exc_type` is a string _handler_exc_name
    does NOT recognize as a real exception type, THAT string is the
    intended bind name instead."""
    if h.name:
        return h.name
    if isinstance(h.exc_type, str) and gen._handler_exc_name(h) is None:
        return h.exc_type
    return None


def _emit_except_handler(gen, handler, node, bb_after):
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
    bind_name = gen._handler_bind_name(handler)
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
        # bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md's
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
    sj_ret = gen._new_temp('int')
    cond_t = gen._new_temp('_Bool')
    bb_try   = gen._new_bb()
    bb_exc   = gen._new_bb()
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
            # break/continue lower to a bare `goto <loop label>;` (see
            # _gen_stmt_BreakStmt/_gen_stmt_ContinueStmt) — anywhere
            # inside the try body, even nested in an if/while, they jump
            # out of this try's protected region exactly like an early
            # return does, and leak the same way if unaccounted for.
            if gen.loop_stack and stripped in (
                f"goto {gen.loop_stack[-1][0]};",
                f"goto {gen.loop_stack[-1][1]};",
            ):
                original_emit("  mojo_exc_pop ();")
                original_emit(line)
                return
            original_emit(line)

        gen._emit = intercepted_emit
        gen.gen_stmt(s)
        gen._emit = original_emit  # Restore

        if gen._last_was_terminal:
            _had_terminal = True
            break

    # Emit finally body
    if bb_finally:
        gen._emit_label(bb_finally)
        for s in node.finally_body:
            gen.gen_stmt(s)
        gen._emit(f"  goto {bb_finally_done};")

    # After finally: do the actual return if needed. Only re-emit the
    # return here when a finally deferred it (see intercepted_emit above)
    # — without a finally_body, the interceptor already emitted the real
    # return statement directly, and doing it again here would duplicate
    # it (unreachable dead code, not a compile error, but still wrong).
    if bb_finally_done:
        gen._emit_label(bb_finally_done)
    if _had_terminal and _return_value is not None and node.finally_body:
        gen._emit(f"  return {_return_value};")
    elif not _had_terminal:
        gen._emit("  mojo_exc_pop ();")
        if bb_finally:
            for s in node.finally_body:
                gen.gen_stmt(s)
        gen._emit(f"  goto {bb_else if bb_else else bb_after};")

    # Reset terminal state for caller
    if not _had_terminal:
        gen._last_was_terminal = False

    gen._emit_label(bb_exc)
    gen._emit("  mojo_exc_pop ();")

    handlers = node.handlers
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

        handler_bbs = {id(h): gen._new_bb() for h in handlers}
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
                next_bb = handler_bbs[id(bare[0])] if bare else bb_no_match
            gen._emit(f"  if ({is_match}) goto {handler_bbs[id(h)]}; else goto {next_bb};")
            if i + 1 < n_typed:
                gen._emit_label(next_bb)

        for h in typed + bare[:1]:
            gen._emit_label(handler_bbs[id(h)])
            gen._emit_except_handler(h, node, bb_after)

        gen._emit_label(bb_no_match)
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


def _gen_stmt_WithStmt(gen, node):
    # `contexts` tracks the ORIGINAL context-manager value (`ctx_v`,
    # `ctx_t`) for each item, separately from the user-visible bound
    # name (`alias`, real Python's `with X() as v:` binds `v` to
    # `X().__enter__()`'s RETURN value, not to the `X()` instance
    # itself) — __exit__ must always be called on the context manager
    # object, never on whatever __enter__ happened to return.
    contexts = []
    for item in node.items:
        et, ev = gen.lower_expr(item.expr)
        ctx_t, ctx_v = et, ev
        struct_name = gimple_exprtypes._struct_name_of(et)
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
        if item.alias is not None:
            alias = item.alias if isinstance(item.alias, str) else item.alias.name
            if alias not in gen.var_types:
                gen._declare_var(alias, enter_ret_t)
            gen._safe_coerce_emit(enter_ret_t, gen.var_types[alias], enter_v, alias)
        contexts.append((ctx_t, ctx_v, struct_name))

    def _emit_exits():
        for ct, cv, sn in contexts:
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

    has_exit = any(
        gen._struct_method_csym(sn, '__exit__', '') in gen.func_return_types
        or f"{sn}___exit__" in gen.func_return_types
        for _, _, sn in contexts)

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
        # GIMPLE: pass array element directly to setjmp (decays to int*)
        gen._emit(f"  {sj_ret} = setjmp (_mojo_exc_stack[{temp_top2}]);")
        gen._emit(f"  {cond_t} = {sj_ret} != 0;")
        gen._emit(f"  if ({cond_t}) goto {bb_exc}; else goto {bb_try};")

        gen._emit_label(bb_try)
        for s in node.body:
            # break/continue lower to a bare `goto <loop label>;` and jump
            # out of this with's protected region same as an early return
            # — same leak as in _gen_stmt_TryStmt if unaccounted for.
            original_emit = gen._emit
            def intercepted_emit(line, rv=None, rt=None):
                stripped = line.strip()
                if gen.loop_stack and stripped in (
                    f"goto {gen.loop_stack[-1][0]};",
                    f"goto {gen.loop_stack[-1][1]};",
                ):
                    original_emit("  mojo_exc_pop ();")
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
        # codegen instead of `try`).
        if not gen._last_was_terminal:
            gen._emit("  mojo_exc_pop ();")
            _emit_exits()
            gen._emit(f"  goto {bb_after};")
        else:
            gen._emit("  mojo_exc_pop ();")
            _emit_exits()

        gen._emit_label(bb_exc)
        gen._emit("  mojo_exc_pop ();")
        _emit_exits()
        gen._emit("  mojo_raise ();")
        # Only emit goto if the exception handler didn't end with a return
        if not gen._last_was_terminal:
            gen._emit(f"  goto {bb_after};")

        gen._emit_label(bb_after)
    else:
        for s in node.body:
            gen.gen_stmt(s)
        _emit_exits()
