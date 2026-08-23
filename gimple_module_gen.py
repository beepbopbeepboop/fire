"""gen_module phase functions.

Hoisted verbatim by tools/slice_gen_module.py; shared state rides on _ctx.
"""
from __future__ import annotations

import os
import re
import sys

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
    py_tokenize, Parser,
)
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
from gimple_exprtypes import _walk_ast


def __getattr__(name):
    # Remaining gen_module-era module globals resolve against the
    # host module lazily (avoids import-order cycles).
    import gimple_codegen as _gc
    return getattr(_gc, name)
def _gm_head(self, _ctx):
    from gimple_codegen import _C_KEYWORDS, _bracket_param_type_annotations, _debug_note, _import_targets, _used_idents_deep
    self._actual_types['stmts'] = 'MojoList *'
    self._toplevel_dep_init_modules: list[str] = []

    def _prefold_toplevel_comptime(_node_list):
        for _cn in _node_list:
            if isinstance(_cn, ComptimeVarStmt):
                _ctx._cv = self._eval_const(_cn.value)
                if _ctx._cv is not None:
                    self._comptime_vals.setdefault(_cn.target, _ctx._cv)
                if isinstance(_cn.value, ListExpr):
                    self._comptime_list_asts.setdefault(_cn.target, _cn.value)
            elif isinstance(_cn, IfStmt):
                _prefold_toplevel_comptime(_cn.then_body or [])
                if _cn.else_body:
                    _prefold_toplevel_comptime(_cn.else_body)
                for _ctx._, _ctx._eb in _cn.elifs or []:
                    _prefold_toplevel_comptime(_ctx._eb or [])
            elif isinstance(_cn, (WhileStmt, ForStmt)):
                _prefold_toplevel_comptime(_cn.body or [])
            elif isinstance(_cn, TryStmt):
                _prefold_toplevel_comptime(_cn.body or [])
                for _ctx._h in _cn.handlers or []:
                    _prefold_toplevel_comptime(getattr(_ctx._h, 'body', None) or [])
    _prefold_toplevel_comptime(_ctx.stmts)
    for _fis in _ctx.stmts:
        if not isinstance(_fis, FromImportStmt):
            continue
        try:
            _imp_path, _imp_src, _imp_stmts = self._parsed_import(_fis.module)
        except Exception:
            continue
        if not _imp_stmts:
            continue
        for _iname, _ctx._ialias in _fis.names:
            _isym = _ctx._ialias if _ctx._ialias else _iname
            if _isym in self._comptime_vals:
                continue
            _found = {}

            def _find_one(_node_list, _target=_iname, _out=_found):
                if _out:
                    return
                for _cn in _node_list:
                    if isinstance(_cn, ComptimeVarStmt) and _cn.target == _target:
                        _ctx._cv = self._eval_const(_cn.value)
                        if _ctx._cv is not None:
                            _out['v'] = _ctx._cv
                        return
                    elif isinstance(_cn, IfStmt):
                        _find_one(_cn.then_body or [], _target, _out)
                        if _cn.else_body:
                            _find_one(_cn.else_body, _target, _out)
                        for _ctx._, _ctx._eb in _cn.elifs or []:
                            _find_one(_ctx._eb or [], _target, _out)
                    elif isinstance(_cn, (WhileStmt, ForStmt)):
                        _find_one(_cn.body or [], _target, _out)
                    elif isinstance(_cn, TryStmt):
                        _find_one(_cn.body or [], _target, _out)
                        for _ctx._h in _cn.handlers or []:
                            _find_one(getattr(_ctx._h, 'body', None) or [], _target, _out)
            _find_one(_imp_stmts)
            if 'v' in _found:
                self._comptime_vals[_isym] = _found['v']
    self._import_scope_stack.append({})
    _ctx._generator_fns: dict[int, FunctionDef] = {}
    _ctx._async_fns: dict[int, FunctionDef] = {}
    for n in _walk_ast(_ctx.stmts):
        if isinstance(n, FunctionDef):
            if n.is_generator:
                _ctx._generator_fns[id(n)] = n
            if n.is_async:
                _ctx._async_fns[id(n)] = n
    self._all_generator_names: set = {n.name for n in _ctx._generator_fns.values()}
    self._all_async_fn_names: set[str] = {n.name for n in _ctx._async_fns.values()}
    for _ctx._s in _ctx.stmts:
        if isinstance(_ctx._s, StructDef) and _ctx._s.name in _C_KEYWORDS:
            _safe = f'_kw_{_ctx._s.name}'
            self._c_kw_struct_renames[_ctx._s.name] = _safe
            _ctx._s.name = _safe
    self._local_struct_names = {s.name for s in _ctx.stmts if isinstance(s, StructDef)}
    _fn_counts = {}
    for _ctx._s in _ctx.stmts:
        if isinstance(_ctx._s, FunctionDef):
            _fn_counts[_ctx._s.name] = _fn_counts.get(_ctx._s.name, 0) + 1
    _overloaded = {n for n, c in _fn_counts.items() if c > 1}
    if _overloaded:
        _ctx.stmts = [s for s in _ctx.stmts if not (isinstance(s, FunctionDef) and s.name in _overloaded)]

    def _toplev_bound_names(_tb_body):
        _names = set()
        for _tb_s in _tb_body or []:
            if isinstance(_tb_s, FromImportStmt):
                for _tb_nm, _tb_alias in _tb_s.names or []:
                    _names.add(_tb_alias if _tb_alias else _tb_nm)
            elif isinstance(_tb_s, ImportStmt):
                for _tb_mod, _tb_alias in _import_targets(_tb_s):
                    _names.add(_tb_alias if _tb_alias else _tb_mod.split('.')[0])
            elif isinstance(_tb_s, FunctionDef):
                _names.add(_tb_s.name)
        return _names
    _try_replaced: list = []
    for _ctx._s in _ctx.stmts:
        if isinstance(_ctx._s, TryStmt):
            _try_names = _toplev_bound_names(_ctx._s.body)
            _handler_names: set = set()
            for _ctx._h in _ctx._s.handlers or []:
                _handler_names |= _toplev_bound_names(_ctx._h.body)
            if _try_names and _try_names & _handler_names:
                _try_replaced.extend(_ctx._s.body or [])
            else:
                _try_replaced.append(_ctx._s)
        else:
            _try_replaced.append(_ctx._s)
    _ctx.stmts = _try_replaced
    for _tls in _ctx.stmts:
        if isinstance(_tls, AssignStmt) and isinstance(_tls.target, IdentExpr):
            _tlv = self._eval_const(_tls.value)
            if _tlv is not None:
                self._comptime_vals.setdefault(_tls.target.name, _tlv)
    _cond_fn_counts: dict = {}
    _cond_worklist = [s for s in _ctx.stmts if isinstance(s, IfStmt)]
    while _cond_worklist:
        _wi = _cond_worklist.pop()
        for _ctx._s in _wi.then_body or []:
            if isinstance(_ctx._s, FunctionDef):
                _cond_fn_counts[_ctx._s.name] = _cond_fn_counts.get(_ctx._s.name, 0) + 1
            elif isinstance(_ctx._s, IfStmt):
                _cond_worklist.append(_ctx._s)
        for _ctx._cond, _elif_body in getattr(_wi, 'elifs', None) or []:
            for _ctx._s in _elif_body or []:
                if isinstance(_ctx._s, FunctionDef):
                    _cond_fn_counts[_ctx._s.name] = _cond_fn_counts.get(_ctx._s.name, 0) + 1
                elif isinstance(_ctx._s, IfStmt):
                    _cond_worklist.append(_ctx._s)
        if _wi.else_body:
            for _ctx._s in _wi.else_body:
                if isinstance(_ctx._s, FunctionDef):
                    _cond_fn_counts[_ctx._s.name] = _cond_fn_counts.get(_ctx._s.name, 0) + 1
                elif isinstance(_ctx._s, IfStmt):
                    _cond_worklist.append(_ctx._s)
    _cond_collisions = {n for n, c in _cond_fn_counts.items() if c > 1}
    _direct_toplevel_names = {s.name for s in _ctx.stmts if isinstance(s, FunctionDef)}
    _cond_unique = {n for n, c in _cond_fn_counts.items() if c == 1 and n not in _direct_toplevel_names}
    _promote_names = _cond_collisions | _cond_unique
    if _promote_names:
        _already_promoted_names: set = set()
        _replaced: list = []
        for _ctx._s in _ctx.stmts:
            if not isinstance(_ctx._s, IfStmt):
                _replaced.append(_ctx._s)
                continue
            _promoted: list = []
            _seen_names: set = set()
            _ctx._stack: list = [([_ctx._s], 0)]
            while _ctx._stack:
                _ctx._frame_body, _ctx._frame_idx = _ctx._stack[-1]
                if _ctx._frame_idx >= len(_ctx._frame_body):
                    _ctx._stack.pop()
                    continue
                _ctx._frame_stmt = _ctx._frame_body[_ctx._frame_idx]
                _ctx._stack[-1] = (_ctx._frame_body, _ctx._frame_idx + 1)
                if isinstance(_ctx._frame_stmt, FunctionDef):
                    if _ctx._frame_stmt.name in _promote_names and _ctx._frame_stmt.name not in _seen_names and (_ctx._frame_stmt.name not in _already_promoted_names):
                        _promoted.append(_ctx._frame_stmt)
                        _seen_names.add(_ctx._frame_stmt.name)
                        _already_promoted_names.add(_ctx._frame_stmt.name)
                elif isinstance(_ctx._frame_stmt, IfStmt):
                    _ctx._resolved = False
                    _ctx._resolved_body = []
                    _ctx._cond_val = self._eval_const_bool(_ctx._frame_stmt.condition)
                    if _ctx._cond_val is True:
                        _ctx._resolved = True
                        _ctx._resolved_body = _ctx._frame_stmt.then_body or []
                    elif _ctx._cond_val is False:
                        _ctx._resolved = True
                        for _ctx._cond2, _ctx._elif_body2 in getattr(_ctx._frame_stmt, 'elifs', None) or []:
                            _ctx._elif_val = self._eval_const_bool(_ctx._cond2)
                            if _ctx._elif_val is True:
                                _ctx._resolved_body = _ctx._elif_body2 or []
                                break
                            if _ctx._elif_val is None:
                                _ctx._resolved = False
                                break
                        else:
                            _ctx._resolved_body = _ctx._frame_stmt.else_body or []
                    if _ctx._resolved:
                        _nested_body = _ctx._resolved_body
                    else:
                        _nested_body = _ctx._frame_stmt.then_body or []
                        for _ctx._cond2, _ctx._elif_body2 in getattr(_ctx._frame_stmt, 'elifs', None) or []:
                            _nested_body = _nested_body + _ctx._elif_body2
                        if _ctx._frame_stmt.else_body:
                            _nested_body = _nested_body + _ctx._frame_stmt.else_body
                    _ctx._stack.append((_nested_body, 0))
            if _promoted:
                _replaced.extend(_promoted)
            else:
                _replaced.append(_ctx._s)
        _ctx.stmts = _replaced
    _ctx._gsrc = ''
    if getattr(self, '_current_filename', None):
        try:
            _ctx._gsrc = open(self._current_filename).read()
        except Exception:
            _debug_note('cannot read source for generics scan', self._current_filename)
            _ctx._gsrc = ''
    if _ctx._gsrc:
        _local_generics = {s.name for s in _ctx.stmts if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE and re.search(f'\\b(?:fn|def)\\s+{re.escape(s.name)}\\s*\\[', _ctx._gsrc)}
        for _ctx._gn in _local_generics:
            self._imported_generics.setdefault(_ctx._gn, self._current_filename)
        if _local_generics:
            _stripped_generic_fns = [s for s in _ctx.stmts if isinstance(s, FunctionDef) and s.name in _local_generics]
            _ctx.stmts = [s for s in _ctx.stmts if not (isinstance(s, FunctionDef) and s.name in _local_generics)]
            for _sgf in _stripped_generic_fns:
                for _ctx._n in _walk_ast(_sgf.body):
                    if isinstance(_ctx._n, FunctionDef):
                        _ctx._async_fns.pop(id(_ctx._n), None)
                        _ctx._generator_fns.pop(id(_ctx._n), None)
    if _ctx._gsrc:
        for _ctx._s in _ctx.stmts:
            if not isinstance(_ctx._s, StructDef):
                continue
            try:
                import elaborate as _elaborate_mod
                _struct_src = _elaborate_mod.extract_struct_source(_ctx._gsrc, _ctx._s.name) or _ctx._gsrc
            except Exception:
                _struct_src = _ctx._gsrc
            _moids_pre = self._struct_method_overload_ids(_ctx._s)
            _name_occurrence: dict = {}
            for _ctx._m, _ctx._oid in zip(_ctx._s.methods, _moids_pre):
                _occ = _name_occurrence.get(_ctx._m.name, 0)
                _name_occurrence[_ctx._m.name] = _occ + 1
                if not _ctx._m.comptime_params:
                    continue
                _bp_types = _bracket_param_type_annotations(_struct_src, _ctx._m.name, occurrence=_occ)
                _func_typed = {p for p in _ctx._m.comptime_params if _bp_types.get(p, '').startswith('def')}
                if not _func_typed:
                    continue
                _used = set()
                for _ctx._b in _ctx._m.body:
                    _used |= _used_idents_deep(_ctx._b)
                _threaded = [p for p in _ctx._m.comptime_params if p in _func_typed and p in _used]
                if _threaded:
                    _ctx._key = (_ctx._s.name, _ctx._m.name)
                    self._method_threaded_comptime_params.setdefault(_ctx._key, {})[_ctx._oid] = _threaded
                    self._method_comptime_param_order.setdefault(_ctx._key, {})[_ctx._oid] = list(_ctx._m.comptime_params)
    self._callable_structs = {s.name for s in _ctx.stmts if isinstance(s, StructDef) and any((m.name == '__call__' for m in s.methods))}
    self._register_imported_structs(_ctx.stmts)
    self._register_imported_generics(_ctx.stmts)
    self._register_imported_generic_structs(_ctx.stmts)
    for _ctx._s in _ctx.stmts:
        if isinstance(_ctx._s, ComptimeVarStmt) and isinstance(_ctx._s.value, ListExpr):
            self._comptime_list_asts.setdefault(_ctx._s.target, _ctx._s.value)
    self._local_top_level_func_names = {s.name for s in _ctx.stmts if isinstance(s, FunctionDef)}

def _gm_phase0_imports(self, _ctx):
    from gimple_codegen import _FIXED_ARRAY_ANN_RE, _LIST_RETURNING_METHODS, _PSEUDO_DUNDER_ATTRS, _RUNTIME_FUNCS, _SELFHOST_DIR, _STR_RETURNING_METHODS, _TYPE_MAP, _class_attr_ctype, _compute_exc_descendants, _debug_note, _import_targets, _merge_struct_inheritance, _mojo_type
    for _ctx._s in _ctx.stmts:
        if isinstance(_ctx._s, FunctionDef):
            self._global_inline_defs.add(_ctx._s.name)
        elif isinstance(_ctx._s, StructDef):
            for _ctx._m in _ctx._s.methods:
                self._global_inline_defs.add(_ctx._m.name)
                self._global_inline_defs.add(f'{_ctx._s.name}_{_ctx._m.name}')
            _al = getattr(_ctx._s, 'comptime_aliases', None)
            if _al:
                self._struct_comptime_aliases[_ctx._s.name] = _al
    self._link_import_decl_list = []
    if self.link_imports:
        self._link_import_decl_list = self._register_link_imports(_ctx.stmts)
    self._link_import_decl_list = list(self._link_import_decl_list)
    self._emit_stdlib_import_externs(_ctx.stmts)
    self._emit_imported_global_accessors(_ctx.stmts)
    _ctx.imported_code = []
    _ctx.imported_stmts = []
    if self.do_imports:
        modules_to_compile = set()

        def find_imports(node_list):
            for _ctx.stmt in node_list:
                if isinstance(_ctx.stmt, FromImportStmt):
                    modules_to_compile.add(_ctx.stmt.module)
                    for _ctx._fn, _fa in _ctx.stmt.names or []:
                        modules_to_compile.add(f'{_ctx.stmt.module}.{_ctx._fn}')
                elif isinstance(_ctx.stmt, ImportStmt):
                    for _ctx._m, _ctx._a in _import_targets(_ctx.stmt):
                        modules_to_compile.add(_ctx._m)
                elif isinstance(_ctx.stmt, FunctionDef):
                    find_imports(_ctx.stmt.body)
                elif isinstance(_ctx.stmt, IfStmt):
                    find_imports(_ctx.stmt.then_body)
                    for _ctx._, _ctx.elif_body in _ctx.stmt.elifs:
                        find_imports(_ctx.elif_body)
                    if _ctx.stmt.else_body:
                        find_imports(_ctx.stmt.else_body)
                elif isinstance(_ctx.stmt, (WhileStmt, ForStmt, TryStmt)):
                    find_imports(_ctx.stmt.body)
        find_imports(_ctx.stmts)
        for _ctx.module_name in sorted(modules_to_compile):
            if _ctx.module_name not in self._compiled_modules:
                self._compiled_modules.add(_ctx.module_name)
                _ctx.code, module_stmts = self._compile_imported_module(_ctx.module_name)
                if _ctx.code:
                    _ctx.imported_code.append(f'/* ─── Imported module: {_ctx.module_name} ───────────────────── */')
                    _ctx.imported_code.append(_ctx.code)
                    _ctx.imported_code.append('')
                    _ctx.imported_stmts.extend(module_stmts)
                    for _ctx._ms in module_stmts:
                        if isinstance(_ctx._ms, FunctionDef):
                            self._global_inline_defs.add(_ctx._ms.name)
                            self._imported_func_home.setdefault(_ctx._ms.name, _ctx.module_name)
                            self._note_own_func_home(_ctx._ms.name, _ctx.module_name, record_scope=False)
                        elif isinstance(_ctx._ms, StructDef):
                            for _ctx._m in _ctx._ms.methods:
                                self._global_inline_defs.add(_ctx._m.name)
                                self._global_inline_defs.add(f'{_ctx._ms.name}_{_ctx._m.name}')
                            self._imported_struct_home.setdefault(_ctx._ms.name, _ctx.module_name)
                self._compiled_modules.add(_ctx.module_name)
        already_in_stmts = set((id(_ctx.s) for _ctx.s in _ctx.imported_stmts))
        for _ctx.s in self._all_transitive_stmts_ordered:
            if id(_ctx.s) not in already_in_stmts:
                _ctx.imported_stmts.append(_ctx.s)
                already_in_stmts.add(id(_ctx.s))
    if self.link_imports:
        for _ctx.module_name in sorted(self._link_inline_modules):
            if _ctx.module_name not in self._compiled_modules:
                self._compiled_modules.add(_ctx.module_name)
                _ctx.code, module_stmts = self._compile_imported_module(_ctx.module_name)
                if _ctx.code:
                    _ctx.imported_code.append(f'/* ─── Imported module (link-mode fallback): {_ctx.module_name} ───────────────────── */')
                    _ctx.imported_code.append(_ctx.code)
                    _ctx.imported_code.append('')
                    _ctx.imported_stmts.extend(module_stmts)
                    for _ctx._ms in module_stmts:
                        if isinstance(_ctx._ms, FunctionDef):
                            self._global_inline_defs.add(_ctx._ms.name)
                            self._imported_func_home.setdefault(_ctx._ms.name, _ctx.module_name)
                            self._note_own_func_home(_ctx._ms.name, _ctx.module_name, record_scope=False)
                        elif isinstance(_ctx._ms, StructDef):
                            for _ctx._m in _ctx._ms.methods:
                                self._global_inline_defs.add(_ctx._m.name)
                                self._global_inline_defs.add(f'{_ctx._ms.name}_{_ctx._m.name}')
                            self._imported_struct_home.setdefault(_ctx._ms.name, _ctx.module_name)
    self.struct_field_types['Span'] = {'_data': 'char *', '_len': 'int64_t'}
    _cur_file = getattr(self, '_current_filename', None)
    _cur_abs = os.path.abspath(_cur_file) if _cur_file else ''
    _ctx._is_selfhost_file = bool(_cur_file) and (_cur_abs == _SELFHOST_DIR or _cur_abs.startswith(_SELFHOST_DIR + '/'))
    if _ctx._is_selfhost_file:
        self.struct_field_types['Scope'] = {'parent': 'Scope *', 'vars': 'MojoDict *'}
        self.struct_field_types['Token'] = {'kind': 'char *', 'value': 'char *', 'line': 'int64_t', 'col': 'int64_t'}
        self.struct_field_types['ReturnValue'] = {'value': 'int64_t'}
        self.struct_field_types['BreakException'] = {}
        self.struct_field_types['ContinueException'] = {}
        self.struct_field_types['MojoFunction'] = {'name': 'char *', 'params': 'MojoList *', 'body': 'MojoList *', 'closure_scope': 'Scope *', 'comptime_params': 'MojoList *', '_pd': 'MojoList *', 'is_generator': '_Bool', 'is_async': '_Bool'}
        self.struct_field_types['_MojoSortFn'] = {'_impl': 'int64_t', '_interpreter': 'Interpreter *'}
        self.struct_field_types['_MojoSortPartial'] = {'_impl': 'int64_t', '_cmp_fn': 'int64_t'}
        self.struct_field_types['_ComplexFloat'] = {'bits': 'int64_t'}
        self.struct_field_types['_MojoComplex'] = {'_r': 'double', '_i': 'double'}
        self.struct_field_types['_AutoStubValue'] = {}
        self.struct_field_types['_AutoStubNamespace'] = {}
        self.struct_field_types['_AutoStubCheckNamespace'] = {}
        self.struct_field_types['_MojoBoundComptimeFunction'] = {'func': 'MojoFunction *', 'comptime_bindings': 'MojoDict *'}
        self.struct_field_types['MojoClass'] = {'name': 'char *', 'fields': 'MojoList *', 'methods': 'MojoDict *', 'interpreter': 'Interpreter *', 'bases': 'MojoList *', 'comptime_aliases': 'MojoDict *', 'static_methods': 'MojoSet *', 'def_scope': 'Scope *'}
        self.struct_field_types['MojoInstance'] = {'_mojo_class': 'MojoClass *'}
        self.struct_field_types['BoundMethod'] = {'bound_func': 'MojoFunction *', 'instance': 'MojoInstance *', 'interpreter': 'Interpreter *'}
        self.struct_field_types['MojoOverloadSet'] = {'name': 'char *', 'candidates': 'MojoList *'}
        self.struct_field_types['Interpreter'] = {'scope': 'Scope *', 'filename': 'char *', 'argv': 'MojoList *', '_mojo_module_cache': 'MojoDict *', '_func_specs': 'MojoDict *', '_raised_mojo_value': 'int64_t', '_INT_TYPE_NAMES': 'MojoSet *', '_FLOAT_TYPE_NAMES': 'MojoSet *', '_gen_tls': 'void *'}
        self.struct_field_types['Parser'] = {'_tok': 'MojoList *', '_pos': 'int64_t', '_filename': 'char *', '_pending_decs': 'MojoList *', '_known_traits': 'MojoSet *', '_CONV_KWS': 'MojoSet *'}
        self.struct_field_types['Scope'] = {'parent': 'Scope *', 'vars': 'MojoDict *'}
        self.func_param_types['Scope_define'] = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope_get'] = ['Scope *', 'char *']
        self.func_param_types['Scope_set'] = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope___init__'] = ['Scope *', 'Scope *']
        self._selfhost_locked_param_types.update(('Scope_define', 'Scope_get', 'Scope_set', 'Scope___init__'))
        self._func_kwargs_slot['MojoFunction___call__'] = 3
        self._func_kwargs_has_vararg['MojoFunction___call__'] = True
        self.struct_field_types['CallExpr'] = {'func': 'int64_t', 'args': 'MojoList *'}
        self.struct_field_types['BinaryOp'] = {'op': 'char *', 'left': 'int64_t', 'right': 'int64_t'}
        self.struct_field_types['CompareChain'] = {'operands': 'MojoList *', 'ops': 'MojoList *'}
        self.struct_field_types['UnaryOp'] = {'op': 'char *', 'operand': 'int64_t'}
        self.struct_field_types['TernaryExpr'] = {'condition': 'int64_t', 'then_val': 'int64_t', 'else_val': 'int64_t'}
        self.struct_field_types['MemberExpr'] = {'obj': 'int64_t', 'member': 'char *'}
        self.struct_field_types['SubscriptExpr'] = {'obj': 'int64_t', 'index': 'int64_t'}
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
    self.struct_field_types['IfStmt'] = {'condition': 'int64_t', 'then_body': 'MojoList *', 'elifs': 'MojoList *', 'else_body': 'MojoList *'}
    self.struct_field_types['WhileStmt'] = {'condition': 'int64_t', 'body': 'MojoList *', 'else_body': 'MojoList *'}
    self.struct_field_types['ForStmt'] = {'target': 'int64_t', 'iterable': 'int64_t', 'body': 'MojoList *', 'else_body': 'MojoList *', 'is_async': '_Bool'}
    self.struct_field_types['FunctionDef'] = {'name': 'char *', 'params': 'MojoList *', 'return_type': 'int64_t', 'body': 'MojoList *', 'decorators': 'MojoList *', 'param_convs': 'MojoDict *', 'param_has_default': 'MojoDict *', 'param_defaults': 'MojoDict *', 'kwonly': 'MojoList *', 'comptime_params': 'MojoList *', 'is_generator': '_Bool', 'yield_bearing_node_ids': 'int64_t', 'is_async': '_Bool'}
    self.struct_field_types['ExprStmt'] = {'value': 'int64_t'}
    self.struct_field_types['AssignStmt'] = {'target': 'int64_t', 'value': 'int64_t', 'line': 'int64_t', 'col': 'int64_t', 'type_ann': 'int64_t'}
    self.struct_field_types['AugAssignStmt'] = {'target': 'int64_t', 'op': 'char *', 'value': 'int64_t'}
    self.struct_field_types['ReturnStmt'] = {'value': 'int64_t'}
    self.struct_field_types['VarDecl'] = {'name': 'char *', 'type_ann': 'int64_t', 'value': 'int64_t'}
    self.struct_field_types['MultiAssignStmt'] = {'targets': 'MojoList *', 'value': 'int64_t'}
    self.struct_field_types['BreakStmt'] = {}
    self.struct_field_types['ContinueStmt'] = {}
    self.struct_field_types['PassStmt'] = {}
    self.struct_field_types['AssertStmt'] = {'value': 'int64_t', 'msg': 'int64_t', 'is_comptime': '_Bool'}
    self.struct_field_types['RaiseStmt'] = {'value': 'int64_t'}
    self.struct_field_types['TryStmt'] = {'body': 'MojoList *', 'handlers': 'MojoList *', 'else_body': 'MojoList *', 'finally_body': 'MojoList *'}
    self.struct_field_types['WithStmt'] = {'items': 'MojoList *', 'body': 'MojoList *', 'is_async': '_Bool'}
    self.struct_field_types['ImportStmt'] = {'module': 'char *', 'alias': 'char *', 'extra': 'MojoList *'}
    self.struct_field_types['FromImportStmt'] = {'module': 'char *', 'names': 'MojoList *', 'wildcard': '_Bool'}
    self.struct_field_types['ComptimeIfStmt'] = {'condition': 'int64_t', 'then_body': 'MojoList *', 'elifs': 'MojoList *', 'else_body': 'MojoList *'}
    self.struct_field_types['ComptimeForStmt'] = {'target': 'char *', 'iterable': 'int64_t', 'body': 'MojoList *'}
    self.struct_field_types['ComptimeVarStmt'] = {'target': 'char *', 'value': 'int64_t'}
    self.struct_field_types['GlobalStmt'] = {'names': 'MojoList *'}
    self.struct_field_types['DelStmt'] = {'targets': 'MojoList *'}
    self.struct_field_types['MatchStmt'] = {'subject': 'int64_t', 'cases': 'MojoList *'}
    self.struct_field_types['LambdaExpr'] = {'params': 'MojoList *', 'body': 'int64_t'}
    self.struct_field_types['SubscriptExpr'] = {'obj': 'int64_t', 'index': 'int64_t', 'attrs': 'MojoList *'}
    self.struct_field_types['SliceExpr'] = {'obj': 'int64_t', 'start': 'int64_t', 'stop': 'int64_t', 'step': 'int64_t'}
    self.struct_field_types['Comprehension'] = {'kind': 'char *', 'element': 'int64_t', 'key': 'int64_t', 'generators': 'MojoList *'}
    self.struct_field_types['IdentExpr'] = {'name': 'char *'}
    self.struct_field_types['IntLiteral'] = {'value': 'int64_t', 'line': 'int64_t', 'col': 'int64_t', 'raw': 'char *'}
    self.struct_field_types['FloatLiteral'] = {'value': 'double'}
    self.struct_field_types['BoolLiteral'] = {'value': '_Bool'}
    self.struct_field_types['EllipsisLiteral'] = {}
    self.struct_field_types['NoneLiteral'] = {}
    self.struct_field_types['StringLiteral'] = {'value': 'char *'}
    self.struct_field_types['TstringLiteral'] = {'value': 'char *'}
    self.struct_field_types['ImagLiteral'] = {'value': 'double'}
    self.struct_field_types['TupleLiteral'] = {'elements': 'MojoList *'}
    self.struct_field_types['TupleExpr'] = {'elements': 'MojoList *'}
    self.struct_field_types['ListLiteral'] = {'elements': 'MojoList *'}
    self.struct_field_types['ListExpr'] = {'elements': 'MojoList *'}
    self.struct_field_types['SetLiteral'] = {'elements': 'MojoList *'}
    self.struct_field_types['SetExpr'] = {'elements': 'MojoList *'}
    self.struct_field_types['DictLiteral'] = {'pairs': 'MojoList *'}
    self.struct_field_types['DictExpr'] = {'pairs': 'MojoList *'}
    self.struct_field_types['WalrusExpr'] = {'name': 'char *', 'value': 'int64_t'}
    self.struct_field_types['YieldExpr'] = {'value': 'int64_t'}
    self.struct_field_types['YieldFromExpr'] = {'value': 'int64_t'}
    self.struct_field_types['AwaitExpr'] = {'value': 'int64_t'}
    self.struct_field_types['StructDef'] = {'name': 'char *', 'fields': 'MojoList *', 'methods': 'MojoList *', 'decorators': 'MojoList *', 'comptime_aliases': 'MojoDict *', 'bases': 'MojoList *', 'line': 'int64_t', 'col': 'int64_t', '_fieldwise_ctor_synthesized': '_Bool'}
    self.struct_field_types['TraitDef'] = {'name': 'char *', 'methods': 'MojoList *', 'decorators': 'MojoList *'}
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
    self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}
    self.struct_nullable_container_fields['SubscriptExpr'] = {'attrs'}
    self.struct_nullable_container_fields['IfStmt'] = {'else_body'}
    self.struct_nullable_container_fields['WhileStmt'] = {'else_body'}
    self.struct_nullable_container_fields['ForStmt'] = {'else_body'}
    self.struct_nullable_container_fields['TryStmt'] = {'else_body', 'finally_body'}
    self.struct_nullable_container_fields['ComptimeIfStmt'] = {'else_body'}
    self.struct_nullable_container_fields['ImportStmt'] = {'extra'}
    self._selfhost_hardcoded_struct_names = frozenset(self.struct_field_types.keys())
    _ctx.all_struct_defs = _ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else [])
    self._struct_bases = {_ctx.s.name: list(getattr(_ctx.s, 'bases', None) or []) for _ctx.s in _ctx.all_struct_defs if isinstance(_ctx.s, StructDef)}
    _all_struct_names = {_ctx.s.name for _ctx.s in _ctx.all_struct_defs if isinstance(_ctx.s, StructDef)}
    _struct_bases_map = {_ctx.s.name: getattr(_ctx.s, 'bases', None) or [] for _ctx.s in _ctx.all_struct_defs if isinstance(_ctx.s, StructDef)}
    _unresolved_base_memo: dict = {}

    def _has_unresolved_base(_name, _stack=frozenset()):
        if _name in _unresolved_base_memo:
            return _unresolved_base_memo[_name]
        if _name in _stack:
            return False
        _ctx.result = False
        for _ctx._b in _struct_bases_map.get(_name, ()):
            if _ctx._b not in _all_struct_names or _has_unresolved_base(_ctx._b, _stack | {_name}):
                _ctx.result = True
                break
        _unresolved_base_memo[_name] = _ctx.result
        return _ctx.result
    self._structs_with_unresolved_base = {_name for _name in _struct_bases_map if _has_unresolved_base(_name)}
    _merge_struct_inheritance(_ctx.all_struct_defs)
    self._exc_descendants = _compute_exc_descendants(_ctx.all_struct_defs)
    for _ctx._s in _ctx.all_struct_defs:
        if isinstance(_ctx._s, StructDef) and _ctx._s.name not in self.struct_field_types:
            self.struct_field_types[_ctx._s.name] = {}
    self._ctor_lit_param_types: dict[str, dict[str, str]] = {}
    _ctx._ctor_init_params = {}
    _ctx._ctor_init_methods = {}
    for _ctx._s in _ctx.all_struct_defs:
        if isinstance(_ctx._s, StructDef):
            _ctx._init = None
            for _ctx._m in _ctx._s.methods:
                if _ctx._m.name == '__init__':
                    _ctx._init = _ctx._m
                    break
            if _ctx._init:
                _ctx._ctor_init_params[_ctx._s.name] = [pn for pn, _ctx._ in _ctx._init.params or [] if pn != 'self' and (not pn.startswith('*'))]
                _ctx._ctor_init_methods[_ctx._s.name] = _ctx._init
    if _ctx._ctor_init_params:
        _ctor_lit_obs: dict[str, dict[str, set]] = {}
        _ctor_calls: list = []
        self._calls_in_stmts(_ctx.stmts, _ctor_calls)
        if self.do_imports or self.link_imports:
            self._calls_in_stmts(_ctx.imported_stmts, _ctor_calls)
        for _ctx._call in _ctor_calls:
            if not isinstance(_ctx._call.func, IdentExpr):
                continue
            _ctx._pnames = _ctx._ctor_init_params.get(_ctx._call.func.name)
            if not _ctx._pnames:
                continue
            for _ctx._i, _ctx._a in enumerate(_ctx._call.args):
                if _ctx._i >= len(_ctx._pnames):
                    break
                if isinstance(_ctx._a, StringLiteral):
                    _ctor_lit_obs.setdefault(_ctx._call.func.name, {}).setdefault(_ctx._pnames[_ctx._i], set()).add('char *')
                elif isinstance(_ctx._a, FloatLiteral):
                    _ctor_lit_obs.setdefault(_ctx._call.func.name, {}).setdefault(_ctx._pnames[_ctx._i], set()).add('double')
        for _ctx._struct_name, _ctx._pmap in _ctor_lit_obs.items():
            _ctx._init = _ctx._ctor_init_methods.get(_ctx._struct_name)
            if not _ctx._init:
                continue
            _ctx._ann = {pn: pt for pn, pt in _ctx._init.params or []}
            for _ctx._pname, _types in _ctx._pmap.items():
                if _types not in ({'double'}, {'char *'}):
                    continue
                if _ctx._ann.get(_ctx._pname) is not None:
                    continue
                self._ctor_lit_param_types.setdefault(_ctx._struct_name, {})[_ctx._pname] = 'double' if _types == {'double'} else 'char *'
    for _ctx.s in _ctx.all_struct_defs:
        if isinstance(_ctx.s, StructDef) and _ctx.s.name not in self._struct_name_owner:
            self._struct_name_owner[_ctx.s.name] = id(_ctx.s)
    for _ctx.s in _ctx.all_struct_defs:
        if isinstance(_ctx.s, StructDef) and self._struct_name_owner.get(_ctx.s.name) == id(_ctx.s):
            if _ctx.s.name not in self.struct_field_types:
                self.struct_field_types[_ctx.s.name] = {}
    for _ctx.s in _ctx.all_struct_defs:
        if isinstance(_ctx.s, StructDef):
            if self._struct_name_owner.get(_ctx.s.name) != id(_ctx.s):
                continue
            if _ctx.s.name not in self.struct_field_types:
                self.struct_field_types[_ctx.s.name] = {}
            for _ctx.field in _ctx.s.fields if hasattr(_ctx.s, 'fields') else []:
                if isinstance(_ctx.field, VarDecl) and _ctx.field.name and (_ctx.field.name != 'self'):
                    if not _ctx.field.type_ann and _ctx.field.name not in self.struct_field_types[_ctx.s.name]:
                        _inherited_ft = None
                        for _base_name in getattr(_ctx.s, 'bases', None) or []:
                            _base_ft = self.struct_field_types.get(_base_name, {})
                            if _ctx.field.name in _base_ft:
                                _inherited_ft = _base_ft[_ctx.field.name]
                                break
                        self.struct_field_types[_ctx.s.name][_ctx.field.name] = _inherited_ft if _inherited_ft is not None else _ctx.s.name + ' *'
            self._struct_generator_method_names.setdefault(_ctx.s.name, set()).update((m.name for m in _ctx.s.methods if getattr(m, 'is_generator', False)))
            self._class_attrs[_ctx.s.name] = {}
            for _ctx.field in _ctx.s.fields:
                if isinstance(_ctx.field, AssignStmt):
                    if isinstance(_ctx.field.target, IdentExpr):
                        _ctx.aname = _ctx.field.target.name
                        _ctx.mangled = f'_classattr_{_ctx.s.name}__{_ctx.aname}'
                        self._class_attrs[_ctx.s.name][_ctx.aname] = _ctx.mangled
                        _ctx.v = _ctx.field.value
                        _ctx.ctype = _class_attr_ctype(_ctx.v)
                        if _ctx.ctype is not None:
                            self._global_var_types[_ctx.mangled] = _ctx.ctype
                            _ctx.cur = self.struct_field_types[_ctx.s.name].get(_ctx.aname)
                            if _ctx.cur is None or _ctx.cur in ('int', 'int64_t'):
                                self.struct_field_types[_ctx.s.name][_ctx.aname] = _ctx.ctype
                            if _ctx.ctype == 'MojoList *' and isinstance(_ctx.v, (ListExpr, TupleExpr)):
                                self._field_elem_types.setdefault(_ctx.s.name, {})[_ctx.aname] = self._infer_list_elem_type(_ctx.v.elements)
                        elif isinstance(_ctx.v, StringLiteral):
                            self._global_var_types[_ctx.mangled] = 'char *'
                        elif isinstance(_ctx.v, (IntLiteral, BoolLiteral)):
                            self._global_var_types[_ctx.mangled] = 'int64_t'
                        else:
                            self._global_var_types[_ctx.mangled] = 'int64_t'
                        if _ctx.field.type_ann is not None:
                            _dv_cls_early = self._annotation_dict_val_type(_ctx.field.type_ann)
                            if _dv_cls_early is not None:
                                self._global_dict_val_types[_ctx.mangled] = _dv_cls_early
            for _ctx.field in _ctx.s.fields:
                _is_typed_assign = isinstance(_ctx.field, AssignStmt) and isinstance(_ctx.field.target, IdentExpr) and (_ctx.field.type_ann is not None)
                if isinstance(_ctx.field, VarDecl) or _is_typed_assign:
                    f_name = _ctx.field.name if isinstance(_ctx.field, VarDecl) else _ctx.field.target.name
                    if f_name not in self.struct_field_types[_ctx.s.name]:
                        _ctx.ft = _mojo_type(_ctx.field.type_ann)
                        _fann_s = str(_ctx.field.type_ann).strip() if _ctx.field.type_ann else ''
                        if _fann_s and _fann_s[0].isupper() and ('[' not in _fann_s) and ('.' not in _fann_s) and ('*' not in _fann_s) and (_fann_s not in self._IMPORTED_STRUCT_SKIP_BASENAMES) and (_TYPE_MAP.get(_fann_s) is None):
                            if _fann_s in self.struct_field_types:
                                _ctx.ft = f'{_fann_s} *'
                            else:
                                for _ist in _ctx.stmts:
                                    if not (isinstance(_ist, FromImportStmt) and (not getattr(_ist, 'wildcard', False))):
                                        continue
                                    for _inm, _ctx._ialias in _ist.names:
                                        if (_ctx._ialias or _inm) != _fann_s:
                                            continue
                                        if self._materialize_imported_struct(_ist.module, _inm, _fann_s):
                                            _ctx.ft = f'{_fann_s} *'
                                        break
                                    else:
                                        continue
                                    break
                        _arr_m = _FIXED_ARRAY_ANN_RE.match(str(_ctx.field.type_ann).strip()) if _ctx.field.type_ann else None
                        if _arr_m:
                            _elem_nm, _size_txt = (_arr_m.group(1), _arr_m.group(2))
                            _ctx._n = int(_size_txt) if _size_txt.isdigit() else self._module_const_int(_size_txt, _ctx.stmts, _ctx.imported_stmts)
                            if _ctx._n is not None and _ctx._n > 0:
                                _elem_ct = _elem_nm if _elem_nm in self.struct_field_types else _mojo_type(_elem_nm)
                                _ctx.ft = f'{_elem_ct}[{_ctx._n}]'
                                self._array_field_sizes.setdefault(_ctx.s.name, {})[f_name] = (_elem_ct, _ctx._n)
                        if f_name == 'value' and _ctx.s.name == 'Generator':
                            _ctx.ft = 'int'
                        _ann_bare = str(_ctx.field.type_ann).strip() if _ctx.field.type_ann else ''
                        if _ann_bare in ('object', 'Any') or (' | ' in _ann_bare and any((p.strip()[:1].isupper() for p in _ann_bare.split(' | ') if p.strip() != 'None'))):
                            self.struct_boxed_fields.setdefault(_ctx.s.name, set()).add(f_name)
                        if _ann_bare == 'bool':
                            self.struct_bool_fields.setdefault(_ctx.s.name, set()).add(f_name)
                        if _ctx.field.type_ann and (not _arr_m):
                            _ann_str = str(_ctx.field.type_ann)
                            _outer_base = _ann_str.split('[')[0].strip()
                            _ptr_wrappers = ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer', 'Reference')
                            if _outer_base in _ptr_wrappers and '[' in _ann_str:
                                _ctx._inner = _ann_str.split('[', 1)[1]
                                _inner_base = _ctx._inner.split('[')[0].strip()
                                if _inner_base in self.struct_field_types:
                                    _ctx.ft = f'{_inner_base} *'
                            elif _ctx.ft.endswith(' *') and _outer_base in self.struct_field_types:
                                _ctx.ft = f'{_outer_base} *'
                        self.struct_field_types[_ctx.s.name][f_name] = _ctx.ft
                        _dv_early = self._annotation_dict_val_type(_ctx.field.type_ann)
                        if _dv_early is not None:
                            self._field_dict_val_types.setdefault(_ctx.s.name, {})[f_name] = _dv_early

            def _self_member(expr):
                """MemberExpr's `.member` name iff its object is bare `self`."""
                if isinstance(expr, MemberExpr) and isinstance(expr.obj, IdentExpr) and (expr.obj.name == 'self'):
                    return expr.member
                return None

            def _collect_self_assigns(body, param_types, found):
                for _ctx.node in _walk_ast(body):
                    if isinstance(_ctx.node, AssignStmt):
                        _ctx.fn = _self_member(_ctx.node.target)
                        _existing_fn_ft = found.get(_ctx.fn)
                        if _ctx.fn is not None and (_ctx.fn not in found or (_existing_fn_ft in ('int', 'int64_t') and _existing_fn_ft is not None)):
                            _ctx.v = _ctx.node.value
                            if isinstance(_ctx.v, IdentExpr):
                                _ctx.ft = param_types.get(_ctx.v.name, 'int64_t')
                            elif isinstance(_ctx.v, IntLiteral):
                                _ctx.ft = 'int64_t'
                            elif isinstance(_ctx.v, StringLiteral):
                                _ctx.ft = 'char *'
                            elif isinstance(_ctx.v, BoolLiteral):
                                _ctx.ft = '_Bool'
                            elif isinstance(_ctx.v, DictExpr):
                                _ctx.ft = 'MojoDict *'
                            elif isinstance(_ctx.v, (ListExpr, TupleExpr)):
                                _ctx.ft = 'MojoList *'
                            elif isinstance(_ctx.v, SetExpr):
                                _ctx.ft = 'MojoSet *'
                            elif isinstance(_ctx.v, Comprehension):
                                _ctx.ft = {'list': 'MojoList *', 'set': 'MojoSet *', 'dict': 'MojoDict *'}.get(_ctx.v.kind, 'MojoList *')
                            elif isinstance(_ctx.v, CallExpr):
                                cfn = _ctx.v.func
                                _ctx.cn = cfn.name if isinstance(cfn, IdentExpr) else ''
                                if _ctx.cn in ('list', 'DynamicVector', 'mojo_list_new'):
                                    _ctx.ft = 'MojoList *'
                                elif _ctx.cn in ('dict', 'Dict', 'mojo_dict_new'):
                                    _ctx.ft = 'MojoDict *'
                                elif _ctx.cn in ('set', 'Set', 'frozenset', 'mojo_set_new'):
                                    _ctx.ft = 'MojoSet *'
                                elif _ctx.cn.startswith('_alloc_'):
                                    _ctx.sname = _ctx.cn[len('_alloc_'):]
                                    _ctx.ft = _ctx.sname + ' *'
                                elif _ctx.cn in self.struct_field_types:
                                    _ctx.ft = _ctx.cn + ' *'
                                elif isinstance(cfn, MemberExpr) and cfn.member in _STR_RETURNING_METHODS:
                                    _ctx.ft = 'char *'
                                elif isinstance(cfn, MemberExpr) and cfn.member in _LIST_RETURNING_METHODS:
                                    _ctx.ft = 'MojoList *'
                                else:
                                    _ctx.ft = 'int'
                            else:
                                _ctx.ft = 'int'
                            found[_ctx.fn] = _ctx.ft
                    elif isinstance(_ctx.node, MultiAssignStmt):
                        for _ctx.tgt in _ctx.node.targets:
                            _ctx.fn = _self_member(_ctx.tgt)
                            if _ctx.fn is not None and _ctx.fn not in found:
                                found[_ctx.fn] = 'int'
                    elif isinstance(_ctx.node, AugAssignStmt):
                        _ctx.fn = _self_member(_ctx.node.target)
                        if _ctx.fn is not None and _ctx.fn not in found:
                            found[_ctx.fn] = 'int64_t'
            _method_names = {m.name for m in _ctx.s.methods}

            def _collect_self_reads(body, found):
                for _ctx.node in _walk_ast(body):
                    _ctx.fn = _self_member(_ctx.node)
                    if _ctx.fn is not None and _ctx.fn not in found and (_ctx.fn not in _method_names) and (_ctx.fn not in _PSEUDO_DUNDER_ATTRS):
                        found[_ctx.fn] = 'int'
            already = set(self.struct_field_types[_ctx.s.name].keys())
            for _ctx.method in _ctx.s.methods:
                pm = {}
                _ctx._defaults = getattr(_ctx.method, 'param_defaults', {}) or {}
                for _ctx.pname, _ctx.ptype in _ctx.method.params:
                    if _ctx.pname != 'self':
                        if _ctx.ptype:
                            pm[_ctx.pname] = self._resolve_type(_ctx.ptype)
                        elif _ctx.pname in _ctx._defaults:
                            _dv = _ctx._defaults[_ctx.pname]
                            if isinstance(_dv, StringLiteral):
                                pm[_ctx.pname] = 'char *'
                            elif isinstance(_dv, BoolLiteral):
                                pm[_ctx.pname] = '_Bool'
                            else:
                                pm[_ctx.pname] = 'int64_t'
                        elif _ctx.method.name == '__init__' and _ctx.pname in self._ctor_lit_param_types.get(_ctx.s.name, {}):
                            pm[_ctx.pname] = self._ctor_lit_param_types[_ctx.s.name][_ctx.pname]
                        else:
                            pm[_ctx.pname] = 'int64_t'
                new_fields = {}
                _collect_self_assigns(_ctx.method.body, pm, new_fields)
                for _ctx.fn, _ctx.ft in new_fields.items():
                    existing_ft = self.struct_field_types[_ctx.s.name].get(_ctx.fn)
                    can_override = existing_ft == 'int' and _ctx.ft.endswith(' *')
                    if _ctx.fn not in self.struct_field_types[_ctx.s.name] or can_override:
                        self.struct_field_types[_ctx.s.name][_ctx.fn] = _ctx.ft
                        if _ctx.fn not in already:
                            _ctx.s.fields.append(VarDecl(name=_ctx.fn, type_ann=None, value=None))
                            already.add(_ctx.fn)
            if _ctx.s.name in self._selfhost_hardcoded_struct_names:
                continue
            for _ctx.method in _ctx.s.methods:
                read_fields = {}
                _collect_self_reads(_ctx.method.body, read_fields)
                for _ctx.fn, _ctx.ft in read_fields.items():
                    if _ctx.fn not in self.struct_field_types[_ctx.s.name]:
                        _base_ft = None
                        for _base_name in getattr(_ctx.s, 'bases', None) or []:
                            _ctx._cand = self.struct_field_types.get(_base_name, {}).get(_ctx.fn)
                            if _ctx._cand is not None:
                                _base_ft = _ctx._cand
                                break
                        self.struct_field_types[_ctx.s.name][_ctx.fn] = _base_ft if _base_ft is not None else _ctx.ft
                        if _ctx.fn not in already:
                            _ctx.s.fields.append(VarDecl(name=_ctx.fn, type_ann=None, value=None))
                            already.add(_ctx.fn)
    _struct_by_name = {st.name: st for st in _ctx.all_struct_defs if isinstance(st, StructDef) and self._struct_name_owner.get(st.name) == id(st)}

    def _scan_stmt_var_candidates(stmt):
        sid = id(_ctx.stmt)
        cached = self._field_scan_var_cache.get(sid)
        if cached is not None:
            return cached
        cands = []
        for _ctx.node in _walk_ast(_ctx.stmt):
            if isinstance(_ctx.node, VarDecl) and _ctx.node.type_ann:
                cands.append((_ctx.node.name, str(_ctx.node.type_ann).strip()))
            elif isinstance(_ctx.node, AssignStmt) and isinstance(_ctx.node.target, IdentExpr) and isinstance(_ctx.node.value, CallExpr) and isinstance(_ctx.node.value.func, IdentExpr):
                cands.append((_ctx.node.target.name, _ctx.node.value.func.name))
        self._field_scan_var_cache[sid] = cands
        return cands

    def _scan_stmt_member_candidates(stmt):
        sid = id(_ctx.stmt)
        cached = self._field_scan_member_cache.get(sid)
        if cached is not None:
            return cached
        cands = []
        for _ctx.node in _walk_ast(_ctx.stmt):
            if not (isinstance(_ctx.node, MemberExpr) and isinstance(_ctx.node.obj, IdentExpr)):
                continue
            _ctx.fn = _ctx.node.member
            if _ctx.fn.startswith('__') and _ctx.fn.endswith('__'):
                continue
            cands.append((_ctx.node.obj.name, _ctx.fn))
        self._field_scan_member_cache[sid] = cands
        return cands

    def _scan_body_for_local_field_access(body, own_struct_name):
        local_types = {}
        for _ctx.stmt in body:
            for _ctx.name, _ctx.ann in _scan_stmt_var_candidates(_ctx.stmt):
                if _ctx.ann in self.struct_field_types and _ctx.ann != own_struct_name and (_ctx.ann not in self._selfhost_hardcoded_struct_names):
                    local_types[_ctx.name] = _ctx.ann
        if not local_types:
            return
        for _ctx.stmt in body:
            for obj_name, _ctx.fn in _scan_stmt_member_candidates(_ctx.stmt):
                target_struct = local_types.get(obj_name)
                if target_struct is None:
                    continue
                if _ctx.fn in self.struct_field_types[target_struct]:
                    continue
                self.struct_field_types[target_struct][_ctx.fn] = 'int'
                target_def = _struct_by_name.get(target_struct)
                if target_def is not None and (not any((isinstance(f, VarDecl) and f.name == _ctx.fn for f in target_def.fields))):
                    target_def.fields.append(VarDecl(name=_ctx.fn, type_ann=None, value=None))
    _scan_body_for_local_field_access(_ctx.stmts, None)
    if self.do_imports or self.link_imports:
        _scan_body_for_local_field_access(_ctx.imported_stmts, None)
    _phase0_func_types = dict(self.func_return_types)
    _phase0_imported = dict(getattr(self, 'imported_symbols', {}))
    self.func_return_types = dict(_RUNTIME_FUNCS)
    self.func_return_types.update(_phase0_func_types)
    all_struct_defs_for_types = _ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else [])
    for _ctx.s in all_struct_defs_for_types:
        if isinstance(_ctx.s, StructDef):
            self.func_return_types[_ctx.s.name] = f'{_ctx.s.name} *'
    self.imported_symbols = dict(_phase0_imported)
    for _ctx.s in _ctx.stmts:
        if isinstance(_ctx.s, FromImportStmt):
            _sib_qualifier = None
            try:
                _ctx.exports = load_module(_ctx.s.module)
            except Exception:
                _ctx.exports, _sib_qualifier = self._local_sibling_module_exports(_ctx.s.module)
            _sib_is_local_project = False
            if _sib_qualifier:
                try:
                    import module_loader as _mlmod_chk
                    _sib_path0 = self._parsed_import(_ctx.s.module)[0]
                    _sib_is_local_project = bool(_sib_path0) and (not (_sib_path0.startswith(_mlmod_chk.STDLIB_PATH) or _sib_path0.startswith(_mlmod_chk.TEST_PATH)))
                except Exception:
                    _sib_is_local_project = False
            if _sib_is_local_project and _sib_qualifier not in self._toplevel_dep_init_modules:
                self._toplevel_dep_init_modules.append(_sib_qualifier)
            if _ctx.exports is not None:

                def _register_sym(sym_name, orig_name, sym_info):
                    if _ctx.sym_name in self.struct_field_types:
                        return
                    if not _ctx.s.wildcard and self._from_import_name_is_submodule(_ctx.s.module, orig_name):
                        self.imported_symbols[_ctx.sym_name] = {'module': f'{_ctx.s.module}.{orig_name}', 'return_type': 'unknown'}
                        return
                    if _sib_qualifier and (not _ctx.sym_info):
                        if not _ctx.s.wildcard:
                            self._unresolved_import_aliases.add(_ctx.sym_name)
                        return
                    if isinstance(_ctx.sym_info, str):
                        self.imported_symbols[_ctx.sym_name] = {'module': _ctx.s.module, 'original_name': orig_name, 'return_type': _ctx.sym_info, 'parameters': [], 'signature': f'{_ctx.sym_info} {_ctx.sym_name} (void)'}
                        self.func_return_types[_ctx.sym_name] = _ctx.sym_info
                    elif isinstance(_ctx.sym_info, dict):
                        _ctx.sym_info = dict(_ctx.sym_info)
                        _ctx.sym_info['module'] = _ctx.s.module
                        _ctx.sym_info['original_name'] = orig_name
                        self.imported_symbols[_ctx.sym_name] = _ctx.sym_info
                        _ret_changed = False
                        if orig_name.startswith('_'):
                            pass
                        elif _sib_is_local_project and _ctx.sym_info.get('return_type'):
                            _resolved_ret = self._resolve_sibling_param_ctype(_ctx.s.module, _ctx.sym_info['return_type'])
                            if _resolved_ret:
                                _ctx.sym_info['c_return_type'] = _resolved_ret
                                _ret_changed = True
                        if 'c_return_type' in _ctx.sym_info:
                            self.func_return_types[_ctx.sym_name] = _ctx.sym_info['c_return_type']
                        if _ctx.sym_info.get('variadic'):
                            if _ret_changed:
                                _ctx.sym_info['signature'] = f"{_ctx.sym_info.get('c_return_type', 'int64_t')} {orig_name} (...)"
                        elif _sib_is_local_project and (not orig_name.startswith('_')) and (_ctx.sym_info.get('c_parameters') is not None) and (len(_ctx.sym_info.get('parameters') or []) == len(_ctx.sym_info['c_parameters'])) and (_ctx.sym_info.get('parameters') or _ret_changed):
                            _new_c_params = []
                            _params_changed = False
                            for (_p_name, _p_raw_type), _c_param in zip(_ctx.sym_info.get('parameters') or [], _ctx.sym_info['c_parameters']):
                                _resolved_ctype = self._resolve_sibling_param_ctype(_ctx.s.module, _p_raw_type)
                                if _resolved_ctype:
                                    _c_name = _c_param.split()[-1] if _c_param.strip() else _p_name
                                    _new_c_params.append(f'{_resolved_ctype} {_c_name}')
                                    _params_changed = True
                                else:
                                    _new_c_params.append(_c_param)
                            if _params_changed or _ret_changed:
                                _ctx.sym_info['c_parameters'] = _new_c_params
                                _c_ret = _ctx.sym_info.get('c_return_type', 'int64_t')
                                _param_str = ', '.join(_new_c_params) if _new_c_params else 'void'
                                _ctx.sym_info['signature'] = f'{_c_ret} {orig_name} ({_param_str})'
                        if _sib_qualifier and 'c_parameters' in _ctx.sym_info:
                            self.func_param_types[_ctx.sym_name] = [' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp for cp in _ctx.sym_info.get('c_parameters') or []]
                    if _sib_qualifier and _ctx.sym_info:
                        if self.do_imports:
                            _qual = _ctx.s.module.replace('.', '_').replace('-', '_')
                        else:
                            _qual = _sib_qualifier
                        self._note_own_func_home(_ctx.sym_name, _qual)
                try:
                    if not _ctx.s.names:
                        for _wc_key, _wc_info in _ctx.exports.items():
                            _register_sym(_wc_key, _wc_key, _wc_info)
                    else:
                        for _ctx.name, _ctx.alias in _ctx.s.names:
                            _ctx.sym_name = _ctx.alias if _ctx.alias else _ctx.name
                            _ctx.sym_info = _ctx.exports.get(_ctx.name, {})
                            _register_sym(_ctx.sym_name, _ctx.name, _ctx.sym_info)
                except Exception:
                    _debug_note('error registering sibling module imports', _ctx.s.module)
            else:
                _debug_note('module load failed while registering imports')
                if not _ctx.s.wildcard:
                    for _fb_name, _fb_alias in _ctx.s.names:
                        _fb_sym = _fb_alias if _fb_alias else _fb_name
                        if self._from_import_name_is_submodule(_ctx.s.module, _fb_name):
                            self.imported_symbols[_fb_sym] = {'module': f'{_ctx.s.module}.{_fb_name}', 'return_type': 'unknown'}
                            continue
                        self._unresolved_import_aliases.add(_fb_sym)
    _ctx.all_functions = _ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else [])

    def _is_foreign_main(s):
        return isinstance(_ctx.s, FunctionDef) and _ctx.s.name == 'main' and (_ctx.s not in _ctx.stmts)
    _ctx._is_foreign_main = _is_foreign_main
    for _ctx.s in _ctx.all_functions:
        if _ctx._is_foreign_main(_ctx.s):
            continue
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.return_type is not None:
            self.func_return_types[_ctx.s.name] = self._resolve_type(_ctx.s.return_type)
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.params:
            if any((pn.startswith('*') for pn, _ctx._ in _ctx.s.params)):
                self.func_param_types[_ctx.s.name] = self._signature_ctypes(_ctx.s.params, _ctx.s)
                self._note_vararg_trailing_param_types(_ctx.s)
            else:
                self.func_param_types[_ctx.s.name] = [self._param_ctype(pn, pt, _ctx.s) for pn, pt in _ctx.s.params]
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.name not in self._NO_OVERLOAD_MANGLE:
            _dflts = getattr(_ctx.s, 'param_defaults', None) or {}
            if _dflts:
                try:
                    _ctx._mangled = self._func_csym(_ctx.s.name)
                except Exception:
                    _ctx._mangled = None
                if _ctx._mangled:
                    self._func_param_defaults[_ctx._mangled] = [(pn, _dv) for pn, _dv in _dflts.items()]
        if isinstance(_ctx.s, FunctionDef):
            _kw_i = -1
            _ctx._ci = 0
            _seen_star = False
            for _ctx._pn, _ctx._pt in _ctx.s.params or []:
                if _ctx._pn.startswith('**'):
                    _kw_i = _ctx._ci
                    break
                if _ctx._pn.startswith('*'):
                    if _seen_star:
                        continue
                    _seen_star = True
                _ctx._ci += 1
            if _kw_i >= 0:
                self._func_kwargs_slot[_ctx.s.name] = _kw_i
                self._func_kwargs_has_vararg[_ctx.s.name] = _seen_star
                try:
                    _mangled_kw_name = self._func_csym(_ctx.s.name)
                    self._func_kwargs_slot[_mangled_kw_name] = _kw_i
                    self._func_kwargs_has_vararg[_mangled_kw_name] = _seen_star
                except Exception:
                    pass
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.name not in self._NO_OVERLOAD_MANGLE:
            self._mangled_funcs.add(_ctx.s.name)
        if isinstance(_ctx.s, FunctionDef) and 'export' in (getattr(_ctx.s, 'decorators', None) or []):
            self._extra_no_mangle.add(_ctx.s.name)
    _own_top_level_func_names = {_ctx.s.name for _ctx.s in _ctx.stmts if isinstance(_ctx.s, FunctionDef)}

    def _scan_func_body_for_self_attr(fname, body):
        for _fstmt in body:
            if isinstance(_fstmt, AssignStmt) and isinstance(_fstmt.target, MemberExpr) and isinstance(_fstmt.target.obj, IdentExpr) and (_fstmt.target.obj.name == fname):
                _ctx.attr = _fstmt.target.member
                self._func_attrs.setdefault(fname, {})
                if _ctx.attr not in self._func_attrs[fname]:
                    _ctx.mangled = f'_funcattr_{fname}__{_ctx.attr}'
                    self._func_attrs[fname][_ctx.attr] = _ctx.mangled
                    self._global_var_types.setdefault(_ctx.mangled, 'int64_t')
                    self._global_c_decl_types.setdefault(_ctx.mangled, 'int64_t')
            elif isinstance(_fstmt, FunctionDef):
                pass
            elif isinstance(_fstmt, IfStmt):
                _scan_func_body_for_self_attr(fname, _fstmt.then_body)
                for _ctx._, _ctx._eb in _fstmt.elifs:
                    _scan_func_body_for_self_attr(fname, _ctx._eb)
                if _fstmt.else_body:
                    _scan_func_body_for_self_attr(fname, _fstmt.else_body)
            elif isinstance(_fstmt, (WhileStmt, ForStmt, TryStmt)):
                _scan_func_body_for_self_attr(fname, _fstmt.body)
    for _ctx.s in _ctx.stmts:
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.name in _own_top_level_func_names:
            _scan_func_body_for_self_attr(_ctx.s.name, _ctx.s.body)

def _gm_pass1b_2_fixpoints(self, _ctx):
    from gimple_codegen import _stub_guard_name
    _ctx.all_structs_for_methods = _ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else []) + self._imported_typedef_structs
    for _ctx.s in _ctx.all_structs_for_methods:
        if isinstance(_ctx.s, StructDef):
            for _ctx.m in _ctx.s.methods:
                _ctx.mangled = f'{_ctx.s.name}_{_ctx.m.name}'
                if _ctx.m.return_type is not None:
                    self.func_return_types[_ctx.mangled] = self._resolve_type(_ctx.m.return_type)
                if hasattr(_ctx.m, 'decorators') and 'staticmethod' in (_ctx.m.decorators or []):
                    self._static_methods.add(_ctx.mangled)
                if hasattr(_ctx.m, 'decorators') and 'classmethod' in (_ctx.m.decorators or []) or _ctx.m.name in ('__init_subclass__', '__class_getitem__'):
                    self._classmethod_names.add(_ctx.mangled)
                if _ctx.m.params:
                    ctypes = []
                    for _ctx.i, (_ctx.pn, _ctx.pt) in enumerate(_ctx.m.params):
                        if _ctx.i == 0 and _ctx.pn == 'self':
                            ctypes.append(f'{_ctx.s.name} *')
                        else:
                            ctypes.append(self._param_ctype(_ctx.pn, _ctx.pt, _ctx.m))
                    if _ctx.mangled not in self.func_param_types:
                        self.func_param_types[_ctx.mangled] = ctypes
    for _ctx.s in _ctx.all_functions:
        if _ctx._is_foreign_main(_ctx.s):
            continue
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.return_type is None:
            for _ctx.pname, _ctx.ptype in _ctx.s.params:
                if _ctx.pname.startswith('**'):
                    self.var_types[_ctx.pname[2:]] = 'MojoDict *'
                elif _ctx.pname.startswith('*'):
                    self.var_types[_ctx.pname[1:]] = 'MojoList *'
                else:
                    self.var_types[_ctx.pname] = self._resolve_type(_ctx.ptype)
            _ctx.inferred = self._infer_return_type(_ctx.s.body)
            if _ctx.s.name == 'main' and _ctx.inferred == 'void':
                _ctx.inferred = 'int64_t'
            self.func_return_types[_ctx.s.name] = _ctx.inferred
            self.var_types.clear()
    for _pass2b_iter in range(4):
        _ctx._changed = False
        for _ctx.s in _ctx.all_structs_for_methods:
            if isinstance(_ctx.s, StructDef):
                for _ctx.m in _ctx.s.methods:
                    self._struct_method_names.setdefault(_ctx.s.name, set()).add(_ctx.m.name)
                    if _ctx.m.name == '__init__':
                        self._struct_has_init.add(_ctx.s.name)
                        self._struct_init_params[_ctx.s.name] = [_ctx.pn for _ctx.pn, _ctx._pt in _ctx.m.params if _ctx.pn != 'self']
                        _ctx._init_defaults = getattr(_ctx.m, 'param_defaults', {}) or {}
                        self._struct_init_defaults[_ctx.s.name] = {_ctx.pn: dv for _ctx.pn, dv in _ctx._init_defaults.items() if _ctx.pn != 'self'}
                    if _ctx.m.return_type is None:
                        for _ctx.i, (_ctx.pname, _ctx.ptype) in enumerate(_ctx.m.params):
                            if _ctx.pname == 'self':
                                self.var_types[_ctx.pname] = f'{_ctx.s.name} *'
                            else:
                                self.var_types[_ctx.pname] = self._resolve_type(_ctx.ptype)
                        _ctx.inferred = self._infer_return_type(_ctx.m.body)
                        _ctx.key = f'{_ctx.s.name}_{_ctx.m.name}'
                        if self.func_return_types.get(_ctx.key) != _ctx.inferred:
                            self.func_return_types[_ctx.key] = _ctx.inferred
                            _ctx._changed = True
                        self.var_types.clear()
        if not _ctx._changed:
            break
    for _pass2c_iter in range(8):
        _c_changed = False
        for _ctx.s in _ctx.all_functions:
            if _ctx._is_foreign_main(_ctx.s) or not isinstance(_ctx.s, FunctionDef):
                continue
            _ret_elem = self._infer_return_elem_type(_ctx.s.body, func_def=_ctx.s)
            if _ret_elem is not None and self._return_elem_types.get(_ctx.s.name) != _ret_elem:
                self._return_elem_types[_ctx.s.name] = _ret_elem
                _c_changed = True
        for _ctx.s in _ctx.all_structs_for_methods:
            if isinstance(_ctx.s, StructDef):
                self._prepass_struct = _ctx.s.name
                for _ctx.m in _ctx.s.methods:
                    if _ctx.m.name == '__init__':
                        continue
                    _ret_elem = self._infer_return_elem_type(_ctx.m.body)
                    _ctx._key = f'{_ctx.s.name}_{_ctx.m.name}'
                    if _ret_elem is not None and self._return_elem_types.get(_ctx._key) != _ret_elem:
                        self._return_elem_types[_ctx._key] = _ret_elem
                        _c_changed = True
        self._prepass_struct = None
        if not _c_changed:
            break
    for _ctx.s in _ctx.all_structs_for_methods:
        if isinstance(_ctx.s, StructDef):
            _ctx._moids = self._struct_method_overload_ids(_ctx.s)
            for _ctx.m, _ctx._oid in zip(_ctx.s.methods, _ctx._moids):
                _has_self_first = bool(_ctx.m.params) and _ctx.m.params[0][0] == 'self'
                _params_no_self = _ctx.m.params[1:] if _has_self_first else _ctx.m.params
                _star_idx = next((_ctx.i for _ctx.i, (_ctx.pn, _ctx._pt) in enumerate(_params_no_self) if _ctx.pn.startswith('*') and (not _ctx.pn.startswith('**'))), None)
                real_params = [(_ctx.pn, _ctx.pt) for _ctx.pn, _ctx.pt in _params_no_self if not (_ctx.pn.startswith('*') and (not _ctx.pn.startswith('**')))]
                _ctx._defaults = _ctx.m.param_has_default or {}
                if _star_idx is not None:
                    _pre_star = _params_no_self[:_star_idx]
                    min_arity = sum((1 for _ctx.pn, _ctx._pt in _pre_star if _ctx.pn not in _ctx._defaults))
                    max_arity = float('inf')
                else:
                    min_arity = sum((1 for _ctx.pn, _ctx._pt in real_params if _ctx.pn not in _ctx._defaults and (not _ctx.pn.startswith('**'))))
                    max_arity = len(real_params)
                _all_ctypes = self._signature_ctypes(_ctx.m.params, _ctx.m, _ctx.s.name)
                _ctx.param_ctypes = _all_ctypes[1:] if _has_self_first else _all_ctypes
                if _star_idx is not None:
                    _ctx.param_ctypes = [c for c in _ctx.param_ctypes if c != '...']
                if _ctx.m.return_type is not None:
                    _ret_base = _ctx.m.return_type.split('[', 1)[0].strip() if isinstance(_ctx.m.return_type, str) else ''
                    if _ret_base == _ctx.s.name and _ctx.s.name in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
                        _ret_type = f'{_ctx.s.name} *'
                    else:
                        _ret_type = self._resolve_type(_ctx.m.return_type)
                else:
                    _saved_var_types = dict(self.var_types)
                    self.var_types['self'] = f'{_ctx.s.name} *'
                    for _ctx._pn, _ctx._pt in real_params:
                        self.var_types[_ctx._pn] = self._resolve_type(_ctx._pt)
                    _ret_type = self._infer_return_type(_ctx.m.body)
                    self.var_types = _saved_var_types
                _ctx.key = (_ctx.s.name, _ctx.m.name)
                self._struct_method_signatures.setdefault(_ctx.key, []).append({'overload_id': _ctx._oid, 'param_names': [_ctx.pn for _ctx.pn, _ctx._pt in real_params], 'param_ctypes': _ctx.param_ctypes, 'min_arity': min_arity, 'max_arity': max_arity, 'ret_type': _ret_type, 'has_varargs': _star_idx is not None, 'pre_star_count': _star_idx if _star_idx is not None else None})
                self._mangled_signature_ctypes[f'{_ctx.s.name}_{_ctx.m.name}{_ctx._oid}'] = _all_ctypes
    for _ctx.s in self._imported_typedef_structs:
        if not _ctx.s.methods:
            continue
        for _ctx._oid, _ctx.m in zip(self._struct_method_overload_ids(_ctx.s), _ctx.s.methods):
            bare_mangled = f'{_ctx.s.name}_{_ctx.m.name}{_ctx._oid}'
            _ctx.mangled = self._struct_method_csym(_ctx.s.name, _ctx.m.name, _ctx._oid)
            _ctx.param_ctypes = self._mangled_signature_ctypes.get(bare_mangled)
            if _ctx.param_ctypes is None:
                continue
            _ctx.ret_type = None
            for _ctx._cand in self._struct_method_signatures.get((_ctx.s.name, _ctx.m.name), []):
                if _ctx._cand.get('overload_id') == _ctx._oid:
                    _ctx.ret_type = _ctx._cand.get('ret_type')
                    break
            if _ctx.ret_type is None:
                _ctx.ret_type = self.func_return_types.get(f'{_ctx.s.name}_{_ctx.m.name}', 'void' if _ctx.m.name == '__init__' else 'int64_t')
            if any(('...' in p for p in _ctx.param_ctypes)):
                params_str = '...'
            else:
                params_str = ', '.join(_ctx.param_ctypes) or 'void'
            sig = f'{_ctx.ret_type} {_ctx.mangled} ({params_str})'
            _ctx.guard = _stub_guard_name(_ctx.mangled)
            decl = f'#ifndef {_ctx.guard}\n#define {_ctx.guard}\nextern {sig};\n#endif'
            if decl not in self._elaborated_externs:
                self._elaborated_externs.append(decl)
            if _ctx._oid:
                no_oid = self._struct_method_csym(_ctx.s.name, _ctx.m.name, '')
                bare_guard = _stub_guard_name(no_oid)
                bare_decl = f'#ifndef {bare_guard}\n#define {bare_guard}\nextern {_ctx.ret_type} {no_oid} (...);\n#endif'
                if bare_decl not in self._elaborated_externs:
                    self._elaborated_externs.append(bare_decl)
    self._inferred_param_types: dict[str, dict[str, str]] = {}
    for _ctx.s in _ctx.all_functions:
        if isinstance(_ctx.s, FunctionDef):
            self._inferred_param_types[_ctx.s.name] = self._infer_param_types(_ctx.s)
    for _ctx.s in _ctx.all_structs_for_methods:
        if isinstance(_ctx.s, StructDef):
            for _ctx.m in _ctx.s.methods:
                _ctx.key = f'{_ctx.s.name}_{_ctx.m.name}'
                self._inferred_param_types[_ctx.key] = self._infer_param_types(_ctx.m)
    self._inferred_var_types: dict[str, dict[str, str]] = {}
    for _ctx.s in _ctx.all_functions:
        if isinstance(_ctx.s, FunctionDef):
            self._inferred_var_types[_ctx.s.name] = self._infer_local_var_types(_ctx.s)
    for _ctx.s in _ctx.all_structs_for_methods:
        if isinstance(_ctx.s, StructDef):
            for _ctx.m in _ctx.s.methods:
                _ctx.key = f'{_ctx.s.name}_{_ctx.m.name}'
                self._inferred_var_types[_ctx.key] = self._infer_local_var_types(_ctx.m)
    for _ctx.s in _ctx.all_functions:
        if _ctx._is_foreign_main(_ctx.s):
            continue
        if isinstance(_ctx.s, FunctionDef):
            if _ctx.s.params and any((_ctx.pn.startswith('*') for _ctx.pn, _ctx._ in _ctx.s.params)):
                self.func_param_types[_ctx.s.name] = self._signature_ctypes(_ctx.s.params, _ctx.s)
                self._note_vararg_trailing_param_types(_ctx.s)
            else:
                self.func_param_types[_ctx.s.name] = [self._param_ctype(_ctx.pn, _ctx.pt, _ctx.s) for _ctx.pn, _ctx.pt in _ctx.s.params] if _ctx.s.params else []
    for _ctx.s in _ctx.all_structs_for_methods:
        if isinstance(_ctx.s, StructDef):
            for _ctx.m in _ctx.s.methods:
                _ctx.method_full_name = f'{_ctx.s.name}_{_ctx.m.name}'
                if _ctx.method_full_name in self._selfhost_locked_param_types:
                    continue
                if _ctx.m.params and any((_ctx.pn.startswith('*') for _ctx.pn, _ctx._ in _ctx.m.params)):
                    self.func_param_types[_ctx.method_full_name] = self._signature_ctypes(_ctx.m.params, _ctx.m, _ctx.s.name)
                else:
                    _ctx.param_ctypes = []
                    for _ctx.i, (_ctx.pname, _ctx.ptype) in enumerate(_ctx.m.params):
                        if _ctx.pname.startswith('**'):
                            continue
                        if _ctx.pname == 'self':
                            _ctx.param_ctypes.append(f'{_ctx.s.name} *')
                        else:
                            _ctx.param_ctypes.append(self._param_ctype(_ctx.pname, _ctx.ptype, _ctx.m))
                    self.func_param_types[_ctx.method_full_name] = _ctx.param_ctypes
    for _ctx.s in _ctx.all_structs_for_methods:
        if not (isinstance(_ctx.s, StructDef) and _ctx.s.name == 'GimpleGen'):
            continue
        for _ctx.m in _ctx.s.methods:
            _ctx.mangled = f'GimpleGen_{_ctx.m.name}'
            fpt = self.func_param_types.get(_ctx.mangled)
            _ctx.inferred = self._inferred_param_types.get(_ctx.mangled)
            if not fpt or not _ctx.inferred:
                continue
            _ctx.idx = 0
            for _ctx.pname, _ctx.ptype in _ctx.m.params or []:
                if _ctx.pname.startswith('**') or (_ctx.pname.startswith('*') and _ctx.pname != 'self'):
                    continue
                if _ctx.pname == 'self':
                    _ctx.idx += 1
                    continue
                if _ctx.idx < len(fpt) and _ctx.pname in _ctx.inferred and (fpt[_ctx.idx] == 'int64_t'):
                    fpt[_ctx.idx] = _ctx.inferred[_ctx.pname]
                _ctx.idx += 1
    self._param_elem_types: dict[str, dict[str, tuple]] = {}
    _ctx._free_params = {_ctx.s.name: [_ctx.pn for _ctx.pn, _ctx._ in _ctx.s.params or [] if not _ctx.pn.startswith('*')] for _ctx.s in _ctx.all_functions if isinstance(_ctx.s, FunctionDef)}

    def _record_param_elem(callee, pname, e, ne):
        _ctx.d = self._param_elem_types.setdefault(callee, {})
        if _ctx.pname in _ctx.d and _ctx.d[_ctx.pname] != (e, ne):
            _ctx.d[_ctx.pname] = (None, None)
        else:
            _ctx.d[_ctx.pname] = (e, ne)
    _ctx._fn_by_name = {_ctx.s.name: _ctx.s for _ctx.s in _ctx.all_functions if isinstance(_ctx.s, FunctionDef)}
    _scalar_obs: dict[str, dict[str, set]] = {}

    def _arg_scalar_type(caller_name, a):
        if isinstance(_ctx.a, FloatLiteral):
            return 'double'
        if isinstance(_ctx.a, StringLiteral):
            return 'char *'
        if isinstance(_ctx.a, IdentExpr):
            _ctx.t = self._inferred_var_types.get(_ctx.caller_name, {}).get(_ctx.a.name) or self._inferred_param_types.get(_ctx.caller_name, {}).get(_ctx.a.name)
            return _ctx.t
        return None
    _ctx._arg_scalar_type = _arg_scalar_type
    _TOPLEVEL_CALLER = '<toplevel>'
    _ctx._caller_bodies = [(_ctx.s.name, _ctx.s.body) for _ctx.s in _ctx.all_functions if isinstance(_ctx.s, FunctionDef)]
    _ctx._caller_bodies.append((_TOPLEVEL_CALLER, _ctx.stmts))
    for _ctx.caller_name, _ctx.body in _ctx._caller_bodies:
        _ctx.elem, nested, _ctx._ = self._scan_container_elems(_ctx.body)
        _ctx.calls = []
        self._calls_in_stmts(_ctx.body, _ctx.calls)
        for _ctx.call in _ctx.calls:
            if not isinstance(_ctx.call.func, IdentExpr):
                continue
            callee = _ctx.call.func.name
            _ctx.pnames = _ctx._free_params.get(callee)
            if not _ctx.pnames:
                continue
            for _ctx.i, _ctx.a in enumerate(_ctx.call.args):
                if _ctx.i >= len(_ctx.pnames):
                    break
                if isinstance(_ctx.a, IdentExpr) and _ctx.a.name in _ctx.elem:
                    _record_param_elem(callee, _ctx.pnames[_ctx.i], _ctx.elem[_ctx.a.name], nested.get(_ctx.a.name))
                _ctx.st = _ctx._arg_scalar_type(_ctx.caller_name, _ctx.a)
                if _ctx.st:
                    _scalar_obs.setdefault(callee, {}).setdefault(_ctx.pnames[_ctx.i], set()).add(_ctx.st)
    for callee, _ctx.pmap in _scalar_obs.items():
        _ctx.fn = _ctx._fn_by_name.get(callee)
        if not _ctx.fn:
            continue
        _ctx.ann = {_ctx.pn: _ctx.pt for _ctx.pn, _ctx.pt in _ctx.fn.params or []}
        for _ctx.pname, _ctx.types in _ctx.pmap.items():
            if _ctx.types not in ({'double'}, {'char *'}):
                continue
            if _ctx.ann.get(_ctx.pname) is not None:
                continue
            _ctx.cur = self._inferred_param_types.get(callee, {}).get(_ctx.pname)
            if _ctx.cur in (None, 'int', 'int64_t'):
                _ctx.resolved_type = 'double' if _ctx.types == {'double'} else 'char *'
                self._inferred_param_types.setdefault(callee, {})[_ctx.pname] = _ctx.resolved_type
    for _ctx.s in _ctx.all_functions:
        if _ctx._is_foreign_main(_ctx.s):
            continue
        if isinstance(_ctx.s, FunctionDef):
            if _ctx.s.params and any((_ctx.pn.startswith('*') for _ctx.pn, _ctx._ in _ctx.s.params)):
                self.func_param_types[_ctx.s.name] = self._signature_ctypes(_ctx.s.params, _ctx.s)
                self._note_vararg_trailing_param_types(_ctx.s)
            else:
                self.func_param_types[_ctx.s.name] = [self._param_ctype(_ctx.pn, _ctx.pt, _ctx.s) for _ctx.pn, _ctx.pt in _ctx.s.params] if _ctx.s.params else []

def _gm_phase2_pre(self, _ctx):
    from gimple_codegen import ClosureInfo, DispatchSolver, _UnsupportedGeneratorShape, _async_gen_quick_eligible, _async_quick_eligible, _bracket_param_type_annotations, _debug_note, _declared_vars_body, _generator_quick_eligible, _import_targets, _mojo_type, _stub_guard_name, _used_idents_node
    _ctor_scalar_obs: dict[str, dict[str, set]] = {}
    for _ctx.caller_name, _ctx.body in _ctx._caller_bodies:
        _ctx.calls = []
        self._calls_in_stmts(_ctx.body, _ctx.calls)
        for _ctx.call in _ctx.calls:
            if not isinstance(_ctx.call.func, IdentExpr):
                continue
            _ctx.struct_name = _ctx.call.func.name
            _ctx.pnames = _ctx._ctor_init_params.get(_ctx.struct_name)
            if not _ctx.pnames:
                continue
            for _ctx.i, _ctx.a in enumerate(_ctx.call.args):
                if _ctx.i >= len(_ctx.pnames):
                    break
                _ctx.st = _ctx._arg_scalar_type(_ctx.caller_name, _ctx.a)
                if _ctx.st:
                    _ctor_scalar_obs.setdefault(_ctx.struct_name, {}).setdefault(_ctx.pnames[_ctx.i], set()).add(_ctx.st)
    for _ctx.struct_name, _ctx.pmap in _ctor_scalar_obs.items():
        _ctx._init = _ctx._ctor_init_methods.get(_ctx.struct_name)
        if not _ctx._init:
            continue
        _ctx._ann = {_ctx.pn: _ctx.pt for _ctx.pn, _ctx.pt in _ctx._init.params or []}
        _ctx._init_defaults = getattr(_ctx._init, 'param_defaults', {}) or {}
        for _ctx.pname, _ctx.types in _ctx.pmap.items():
            if _ctx.types not in ({'double'}, {'char *'}):
                continue
            if _ctx._ann.get(_ctx.pname) is not None:
                continue
            if _ctx.pname in _ctx._init_defaults:
                continue
            _ctx.resolved_type = 'double' if _ctx.types == {'double'} else 'char *'
            self._ctor_lit_param_types.setdefault(_ctx.struct_name, {})[_ctx.pname] = _ctx.resolved_type
            for _ctx.node in _walk_ast(_ctx._init.body):
                if not isinstance(_ctx.node, AssignStmt):
                    continue
                _ctx.tgt = _ctx.node.target
                if not (isinstance(_ctx.tgt, MemberExpr) and isinstance(_ctx.tgt.obj, IdentExpr) and (_ctx.tgt.obj.name == 'self')):
                    continue
                _ctx.v = _ctx.node.value
                if isinstance(_ctx.v, IdentExpr) and _ctx.v.name == _ctx.pname:
                    _fld_types = self.struct_field_types.setdefault(_ctx.struct_name, {})
                    if _fld_types.get(_ctx.tgt.member) in (None, 'int', 'int64_t'):
                        _fld_types[_ctx.tgt.member] = _ctx.resolved_type
    for _gm_stmt in _ctx.stmts:
        if isinstance(_gm_stmt, AssignStmt) and isinstance(_gm_stmt.target, IdentExpr):
            self._cpp_early_global_names.add(_gm_stmt.target.name)
        elif isinstance(_gm_stmt, ImportStmt):
            for _ctx._tm, _ctx._ta in _import_targets(_gm_stmt):
                self._cpp_early_global_names.add(_ctx._ta if _ctx._ta else _ctx._tm.split('.', 1)[0])
        elif isinstance(_gm_stmt, FromImportStmt):
            for _ctx._nm in getattr(_gm_stmt, 'names', []) or []:
                self._cpp_early_global_names.add(_ctx._nm)
        elif isinstance(_gm_stmt, FunctionDef):
            self._cpp_early_global_names.add(_gm_stmt.name)
            self._cpp_module_fn_names.add(_gm_stmt.name)

    def _scan_cpp_nested_imports(stmt_list):
        for _gi in stmt_list:
            if isinstance(_gi, (ImportStmt, FromImportStmt)):
                if isinstance(_gi, ImportStmt):
                    for _ctx._tm, _ctx._ta in _import_targets(_gi):
                        self._cpp_early_global_names.add(_ctx._ta if _ctx._ta else _ctx._tm.split('.', 1)[0])
                else:
                    for _ctx._nm in getattr(_gi, 'names', []) or []:
                        self._cpp_early_global_names.add(_ctx._nm)
            elif isinstance(_gi, AssignStmt) and isinstance(_gi.target, IdentExpr):
                self._cpp_early_global_names.add(_gi.target.name)
            elif isinstance(_gi, TryStmt):
                _scan_cpp_nested_imports(_gi.body or [])
                for _ctx._h in _gi.handlers or []:
                    _scan_cpp_nested_imports(getattr(_ctx._h, 'body', []) or [])
                if isinstance(getattr(_gi, 'finally_body', None), list):
                    _scan_cpp_nested_imports(_gi.finally_body)
            elif isinstance(_gi, IfStmt):
                _scan_cpp_nested_imports(_gi.then_body or [])
                if isinstance(_gi.else_body, list):
                    _scan_cpp_nested_imports(_gi.else_body)
    _scan_cpp_nested_imports(_ctx.stmts)
    for _ctx.s in _ctx.stmts:
        if not (isinstance(_ctx.s, FunctionDef) and id(_ctx.s) in _ctx._generator_fns and (id(_ctx.s) not in _ctx._async_fns)):
            continue
        if _ctx.s.params and _ctx.s.params[0][0] in ('self', 'cls'):
            continue
        if not _generator_quick_eligible(_ctx.s):
            continue
        try:
            cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_generator_unit(_ctx.s)
        except _UnsupportedGeneratorShape as e:
            _debug_note(f'generator {_ctx.s.name!r} not eligible for C++ coroutine path, falling back to honest refusal', e)
            continue
        self._supported_generators[_ctx.s.name] = _ctx.s
        self._generator_api[_ctx.s.name] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes}
        self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
        _gen_dflts = getattr(_ctx.s, 'param_defaults', None) or {}
        if _gen_dflts:
            self._func_param_defaults[f'{_ctx.base}_start'] = [(_ctx.pn, dv) for _ctx.pn, dv in _gen_dflts.items()]
        self._generator_cpp_units.append(cpp_text)
        _ctx._generator_fns.pop(id(_ctx.s), None)
    for _pass in range(3):
        if not _ctx._generator_fns:
            break
        for _gm_id, _ctx.s in list(_ctx._generator_fns.items()):
            if _gm_id in _ctx._async_fns:
                continue
            if _ctx.s.params and _ctx.s.params[0][0] in ('self', 'cls'):
                continue
            if not _generator_quick_eligible(_ctx.s):
                continue
            try:
                cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_generator_unit(_ctx.s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'generator {_ctx.s.name!r} not eligible for C++ coroutine path (pass {_pass + 2}), falling back', e)
                continue
            self._supported_generators[_ctx.s.name] = _ctx.s
            self._generator_api[_ctx.s.name] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes}
            self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
            _gen_dflts = getattr(_ctx.s, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f'{_ctx.base}_start'] = [(_ctx.pn, dv) for _ctx.pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _ctx._generator_fns.pop(_gm_id, None)
    for _ctx.s in _ctx.stmts:
        if not (isinstance(_ctx.s, FunctionDef) and id(_ctx.s) in _ctx._async_fns and (id(_ctx.s) in _ctx._generator_fns)):
            continue
        if not _async_gen_quick_eligible(_ctx.s, frozenset(self._async_api.keys())):
            continue
        try:
            cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_async_generator_unit(_ctx.s)
        except _UnsupportedGeneratorShape as e:
            _debug_note(f'async generator {_ctx.s.name!r} not eligible for C++ coroutine path, falling back to honest refusal', e)
            continue
        self._supported_async_gen[_ctx.s.name] = _ctx.s
        self._async_gen_api[_ctx.s.name] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes}
        self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
        self._generator_cpp_units.append(cpp_text)
        _ctx._async_fns.pop(id(_ctx.s), None)
        _ctx._generator_fns.pop(id(_ctx.s), None)
    if _ctx._async_fns:
        for _gm_id, _ctx.s in list(_ctx._async_fns.items()):
            if _gm_id not in _ctx._generator_fns:
                continue
            if not _async_gen_quick_eligible(_ctx.s, frozenset(self._async_api.keys())):
                continue
            try:
                cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_async_generator_unit(_ctx.s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'async generator {_ctx.s.name!r} not eligible (pass 2)', e)
                continue
            self._supported_async_gen[_ctx.s.name] = _ctx.s
            self._async_gen_api[_ctx.s.name] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes}
            self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
            self._generator_cpp_units.append(cpp_text)
            _ctx._async_fns.pop(_gm_id, None)
            _ctx._generator_fns.pop(_gm_id, None)
    for _ctx.s in _ctx.stmts:
        if not (isinstance(_ctx.s, FunctionDef) and id(_ctx.s) in _ctx._async_fns and (id(_ctx.s) not in _ctx._generator_fns)):
            continue
        _ctx.s.body = self._inline_single_use_task_composition(_ctx.s.body)
        self._normalize_await_kwargs(_ctx.s.body)
        if not _async_quick_eligible(_ctx.s, frozenset(self._async_api.keys())):
            continue
        try:
            cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_async_unit(_ctx.s)
        except _UnsupportedGeneratorShape as e:
            _debug_note(f'async function {_ctx.s.name!r} not eligible for C++ coroutine path, falling back to honest refusal', e)
            continue
        self._supported_async[_ctx.s.name] = _ctx.s
        self._async_api[_ctx.s.name] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes}
        self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
        self._generator_cpp_units.append(cpp_text)
        _ctx._async_fns.pop(id(_ctx.s), None)
    _nested_in_fn_ids: set = set()
    for _st in _ctx.stmts:
        if not (isinstance(_st, FunctionDef) and id(_st) not in _ctx._async_fns and (id(_st) not in _ctx._generator_fns)):
            continue
        for _nf in _walk_ast(_st):
            if isinstance(_nf, FunctionDef):
                _nested_in_fn_ids.add(id(_nf))
    for _st in _ctx.stmts:
        if not isinstance(_st, StructDef):
            continue
        for _sm in _st.methods:
            if not isinstance(_sm, FunctionDef):
                continue
            for _nf in _walk_ast(_sm.body):
                if isinstance(_nf, FunctionDef):
                    _nested_in_fn_ids.add(id(_nf))
    if _ctx._async_fns:
        for _gm_id, _ctx.s in list(_ctx._async_fns.items()):
            if _gm_id in _ctx._generator_fns:
                continue
            if _gm_id in _nested_in_fn_ids:
                continue
            _ctx.s.body = self._inline_single_use_task_composition(_ctx.s.body)
            self._normalize_await_kwargs(_ctx.s.body)
            if not _async_quick_eligible(_ctx.s, frozenset(self._async_api.keys())):
                continue
            try:
                cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_async_unit(_ctx.s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'async function {_ctx.s.name!r} not eligible (pass 2)', e)
                continue
            self._supported_async[_ctx.s.name] = _ctx.s
            self._async_api[_ctx.s.name] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes}
            self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
            self._generator_cpp_units.append(cpp_text)
            _ctx._async_fns.pop(_gm_id, None)
    for _ctx.s in _ctx.stmts:
        if not (isinstance(_ctx.s, FunctionDef) and id(_ctx.s) not in _ctx._async_fns and (id(_ctx.s) not in _ctx._generator_fns)):
            continue
        self._compile_nested_async_functions(_ctx.s, _ctx._async_fns)
    for _sd in _ctx.stmts:
        if not isinstance(_sd, StructDef):
            continue
        for _ctx.m in _sd.methods:
            if not (isinstance(_ctx.m, FunctionDef) and id(_ctx.m) in _ctx._generator_fns and (id(_ctx.m) not in _ctx._async_fns)):
                continue
            if not _generator_quick_eligible(_ctx.m):
                continue
            try:
                cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_generator_unit(_ctx.m, struct_name=_sd.name)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'generator method {_sd.name}.{_ctx.m.name!r} not eligible for C++ coroutine path, falling back to honest refusal', e)
                continue
            _ctx.key = (_sd.name, _ctx.m.name)
            self._supported_generator_methods[_ctx.key] = _ctx.m
            self._generator_method_api[_ctx.key] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes}
            self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
            _gen_dflts = getattr(_ctx.m, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f'{_ctx.base}_start'] = [(_ctx.pn, dv) for _ctx.pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _ctx._generator_fns.pop(id(_ctx.m), None)
    for _sd in _ctx.stmts:
        if not isinstance(_sd, StructDef):
            continue
        for _ctx.m in _sd.methods:
            if not (isinstance(_ctx.m, FunctionDef) and id(_ctx.m) in _ctx._generator_fns and (id(_ctx.m) not in _ctx._async_fns)):
                continue
            if not _generator_quick_eligible(_ctx.m):
                continue
            try:
                cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_generator_unit(_ctx.m, struct_name=_sd.name)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'generator method {_sd.name}.{_ctx.m.name!r} not eligible (pass 2)', e)
                continue
            _ctx.key = (_sd.name, _ctx.m.name)
            self._supported_generator_methods[_ctx.key] = _ctx.m
            self._generator_method_api[_ctx.key] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes}
            self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
            _gen_dflts = getattr(_ctx.m, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f'{_ctx.base}_start'] = [(_ctx.pn, dv) for _ctx.pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _ctx._generator_fns.pop(id(_ctx.m), None)
    if _ctx._gsrc:
        for _od in _ctx.stmts:
            if not isinstance(_od, FunctionDef):
                continue
            _outer_scope2 = {}
            for _ctx._pname, _ctx._ptype in _od.params or []:
                _outer_scope2[_ctx._pname] = self._resolve_type(_ctx._ptype)
            for _ctx._inner in _od.body:
                if not (isinstance(_ctx._inner, FunctionDef) and id(_ctx._inner) in _ctx._async_fns):
                    continue
                _cp_ctypes = {}
                if _ctx._inner.comptime_params:
                    _bp_types2 = _bracket_param_type_annotations(_ctx._gsrc, _ctx._inner.name)
                    for _cp in _ctx._inner.comptime_params:
                        _ctx._ann = _bp_types2.get(_cp, '')
                        _cp_ctypes[_cp] = 'int64_t' if _ctx._ann.startswith('def') else self._resolve_type(_ctx._ann)
                if not _async_quick_eligible(_ctx._inner, frozenset(self._async_api.keys())):
                    continue
                _captures2 = self._compute_nested_closure_captures(_ctx._inner, _outer_scope2)
                _extra2 = [(cp, _cp_ctypes.get(cp, 'int64_t')) for cp in _ctx._inner.comptime_params] + _captures2
                _base_override2 = f'{_od.name}_{_ctx._inner.name}'
                try:
                    cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_async_unit(_ctx._inner, extra_captures=_extra2, base_name_override=_base_override2, enclosing_scope=_od.name)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'nested async function {_od.name}.{_ctx._inner.name!r} not eligible for C++ coroutine path, falling back to honest refusal', e)
                    continue
                _ctx.key = (_od.name, _ctx._inner.name)
                self._supported_async_closures[_ctx.key] = _ctx._inner
                self._async_closure_api[_ctx.key] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'captures': _extra2, 'comptime_params': list(_ctx._inner.comptime_params)}
                self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
                self._generator_cpp_units.append(cpp_text)
                _ctx._async_fns.pop(id(_ctx._inner), None)
    for _sd in _ctx.stmts:
        if not isinstance(_sd, StructDef):
            continue
        _moids_ac = self._struct_method_overload_ids(_sd)
        for _ctx._m, _ctx._oid in zip(_sd.methods, _moids_ac):
            _outer_scope = {_sd.name.lower(): f'{_sd.name} *', 'self': f'{_sd.name} *'}
            for _ctx._pname, _ctx._ptype in _ctx._m.params:
                if _ctx._pname != 'self':
                    _outer_scope[_ctx._pname] = self._resolve_type(_ctx._ptype)
            for _cp_name in self._method_threaded_comptime_params.get((_sd.name, _ctx._m.name), {}).get(_ctx._oid, []):
                _outer_scope[_cp_name] = 'int64_t'
            for _ctx._inner in _ctx._m.body:
                if not (isinstance(_ctx._inner, FunctionDef) and id(_ctx._inner) in _ctx._async_fns):
                    continue
                if not _async_quick_eligible(_ctx._inner, frozenset(self._async_api.keys())):
                    continue
                _captures = self._compute_nested_closure_captures(_ctx._inner, _outer_scope)
                _base_override = f'{_sd.name}_{_ctx._m.name}{_ctx._oid}_{_ctx._inner.name}'
                try:
                    cpp_text, value_ctype, _ctx.base, _ctx.param_ctypes = self._gen_cpp_async_unit(_ctx._inner, extra_captures=_captures, base_name_override=_base_override)
                except _UnsupportedGeneratorShape as e:
                    _debug_note(f'nested async closure {_sd.name}.{_ctx._m.name}.{_ctx._inner.name!r} not eligible for C++ coroutine path, falling back to honest refusal', e)
                    continue
                outer_ctx = f'{_sd.name}_{_ctx._m.name}{_ctx._oid}'
                _ctx.key = (outer_ctx, _ctx._inner.name)
                self._supported_async_closures[_ctx.key] = _ctx._inner
                self._async_closure_api[_ctx.key] = {'base': _ctx.base, 'value_ctype': value_ctype, 'params': _ctx.param_ctypes, 'captures': _captures}
                self.func_param_types[f'{_ctx.base}_start'] = _ctx.param_ctypes
                self._generator_cpp_units.append(cpp_text)
                _ctx._async_fns.pop(id(_ctx._inner), None)
    _gen_only_names: list = []
    for _gm_id, _gm_fn in _ctx._generator_fns.items():
        if _gm_id not in _ctx._async_fns:
            _gen_only_names.append(_gm_fn.name)
    _async_only_names: list = []
    for _gm_id, _gm_fn in _ctx._async_fns.items():
        if _gm_id not in _ctx._generator_fns:
            _async_only_names.append(_gm_fn.name)
    _async_gen_names: list = []
    for _gm_id, _gm_fn in _ctx._generator_fns.items():
        if _gm_id in _ctx._async_fns:
            _async_gen_names.append(_gm_fn.name)
    _gen_only = sorted(_gen_only_names)
    _async_only = sorted(_async_only_names)
    _async_gen = sorted(_async_gen_names)
    if _gen_only or _async_only or _async_gen:
        _categories = []
        if _gen_only:
            _categories.append(f"{', '.join(_gen_only)} (generator function(s), contain a `yield`/`yield from`)")
        if _async_only:
            _categories.append(f"{', '.join(_async_only)} (async function(s), declared `async def`)")
        if _async_gen:
            _categories.append(f"{', '.join(_async_gen)} (async generator function(s), declared `async def` AND contain a `yield`/`yield from`)")
        if self.relaxed_imports:
            _debug_note('relaxed_imports: skipping unsupported functions', '; '.join(_categories))
            for _ctx._fn_name in _gen_only + _async_only + _async_gen:
                _csym = self._func_csym(_ctx._fn_name)
                _g = _stub_guard_name(_csym)
                _stub = f'#ifndef {_g}\n#define {_g}\nint64_t {_csym} (...);\n#endif'
                if _stub not in self._elaborated_externs:
                    self._elaborated_externs.append(_stub)
                self._unsupported_generator_names.add(_ctx._fn_name)
        else:
            raise RuntimeError('cannot compile module: function(s) ' + '; '.join(_categories) + ' — this codegen compiles every function into a single straight-line C function and has no suspend/resume state-machine transform for generators, nor an event loop / suspend-resume codegen for async functions, yet, so these cannot be represented as compiled C without emitting silently wrong or broken code; falling back to interpreting this module from source instead')
    for _ctx.s in _ctx.all_functions:
        if isinstance(_ctx.s, FunctionDef) and _ctx.s.return_type is None:
            _saved_vt_23e = self.var_types
            self.var_types = dict(_saved_vt_23e)
            for _ctx.pname, _ctx.ptype in _ctx.s.params:
                _ctx.bare = _ctx.pname.lstrip('*')
                if _ctx.pname.startswith('*'):
                    self.var_types[_ctx.bare] = 'MojoList *'
                elif _ctx.ptype is None:
                    self.var_types[_ctx.bare] = self._inferred_param_types.get(_ctx.s.name, {}).get(_ctx.bare) or self._resolve_type(_ctx.ptype)
                else:
                    self.var_types[_ctx.bare] = self._resolve_type(_ctx.ptype)
            _ctx.inferred = self._infer_return_type(_ctx.s.body)
            if _ctx.s.name == 'main' and _ctx.inferred == 'void':
                _ctx.inferred = 'int64_t'
            self.var_types = _saved_vt_23e
            self.func_return_types[_ctx.s.name] = _ctx.inferred
    for _ctx.s in _ctx.all_functions:
        if isinstance(_ctx.s, FunctionDef):
            self._inferred_var_types[_ctx.s.name] = self._infer_local_var_types(_ctx.s)
    for _ctx.s in _ctx.all_structs_for_methods:
        if isinstance(_ctx.s, StructDef):
            for _ctx.m in _ctx.s.methods:
                _ctx.key = f'{_ctx.s.name}_{_ctx.m.name}'
                self._inferred_var_types[_ctx.key] = self._infer_local_var_types(_ctx.m)
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
        found = None

        def _scan(stmts):
            for _ctx.st in _ctx.stmts:
                _ctx.val = None
                if isinstance(_ctx.st, AssignStmt) and isinstance(_ctx.st.target, IdentExpr):
                    if _ctx.st.target.name == target_name:
                        _ctx.val = _ctx.st.value
                elif isinstance(_ctx.st, VarDecl) and _ctx.st.name == target_name:
                    _ctx.val = _ctx.st.value
                if _ctx.val is not None:
                    prov = None
                    if isinstance(_ctx.val, CallExpr) and isinstance(_ctx.val.func, IdentExpr):
                        if _ctx.val.func.name in self._generator_api:
                            prov = _ctx.val.func.name
                        else:
                            prov = self._fn_returns_generator.get(_ctx.val.func.name)
                    elif isinstance(_ctx.val, IdentExpr):
                        prov = known_params.get(_ctx.val.name)
                    if prov is not None:
                        if found is None:
                            found = prov
                        elif found != prov:
                            found = '<conflict>'
                    continue
                if isinstance(_ctx.st, FunctionDef):
                    continue
                for _ctx.attr in ('then_body', 'else_body', 'body', 'finally_body'):
                    sub = getattr(_ctx.st, _ctx.attr, None)
                    if isinstance(sub, list):
                        _ctx._scan(sub)
                for _eb_cond, _eb_body in getattr(_ctx.st, 'elifs', None) or []:
                    _ctx._scan(_eb_body)
                for _ctx._h in getattr(_ctx.st, 'handlers', None) or []:
                    hb = getattr(_ctx._h, 'body', None)
                    if isinstance(hb, list):
                        _ctx._scan(hb)
        _ctx._scan(_ctx.body)
        return found

    def _arg_generator_prov(caller_name, arg):
        """The generator function name behind call-site argument `arg`
        (typed `MojoGenerator *` in the caller), or None."""
        if isinstance(arg, IdentExpr):
            _ctx.t = self._inferred_var_types.get(_ctx.caller_name, {}).get(arg.name) or self._inferred_param_types.get(_ctx.caller_name, {}).get(arg.name)
            if _ctx.t != 'MojoGenerator *':
                return None
            _ctx.fn = _ctx._fn_by_name.get(_ctx.caller_name)
            if _ctx.fn is not None:
                _ctx.p = _walk_gen_prov(_ctx.fn.body, arg.name, self._param_generator_api.get(_ctx.caller_name, {}))
                if _ctx.p is not None:
                    return _ctx.p
            return self._param_generator_api.get(_ctx.caller_name, {}).get(arg.name)
        if isinstance(arg, CallExpr) and isinstance(arg.func, IdentExpr):
            if arg.func.name in self._generator_api:
                return arg.func.name
            return self._fn_returns_generator.get(arg.func.name)
        return None
    for _rf in _ctx.all_functions:
        if not isinstance(_rf, FunctionDef):
            continue
        acc_rt = []

        def _collect_rt(stmts2):
            for _st in stmts2:
                if isinstance(_st, FunctionDef):
                    continue
                if isinstance(_st, ReturnStmt) and _st.value is not None:
                    acc_rt.append(_st.value)
                else:
                    for _ctx.attr in ('then_body', 'else_body', 'body', 'finally_body'):
                        sub = getattr(_st, _ctx.attr, None)
                        if isinstance(sub, list):
                            _collect_rt(sub)
                    for _eb_cond, _eb_body in getattr(_st, 'elifs', None) or []:
                        _collect_rt(_eb_body)
                    for _ctx._h in getattr(_st, 'handlers', None) or []:
                        hb = getattr(_ctx._h, 'body', None)
                        if isinstance(hb, list):
                            _collect_rt(hb)
        _collect_rt(_rf.body)
        rt_prov = None
        for _rv in acc_rt:
            if isinstance(_rv, CallExpr) and isinstance(_rv.func, IdentExpr) and (_rv.func.name in self._generator_api):
                if rt_prov is None:
                    rt_prov = _rv.func.name
                elif rt_prov != _rv.func.name:
                    rt_prov = '<conflict>'
            else:
                rt_prov = '<conflict>'
        if rt_prov not in (None, '<conflict>'):
            self._fn_returns_generator[_rf.name] = rt_prov
    _param_gen_obs: dict[str, dict[str, dict]] = {}
    for _round in range(4):
        _ctx._changed = False
        for _cl_name, _cl_body in _ctx._caller_bodies:
            _calls = []
            self._calls_in_stmts(_cl_body, _calls)
            for _ctx._call in _calls:
                if not isinstance(_ctx._call.func, IdentExpr):
                    continue
                _callee = _ctx._call.func.name
                _ctx._pnames = _ctx._free_params.get(_callee)
                if not _ctx._pnames:
                    continue
                for _ctx._i, _ctx._a in enumerate(_ctx._call.args):
                    if _ctx._i >= len(_ctx._pnames):
                        break
                    prov = _arg_generator_prov(_cl_name, _ctx._a)
                    if prov is None:
                        continue
                    _pobs = _param_gen_obs.setdefault(_callee, {})
                    _fmap = _pobs.setdefault(_ctx._pnames[_ctx._i], {})
                    _fmap[prov] = _fmap.get(prov, 0) + 1
        for _callee, _ctx._pmap in _param_gen_obs.items():
            _ctx._fn = _ctx._fn_by_name.get(_callee)
            if _ctx._fn is None:
                continue
            for _ctx._pname, _fmap in _ctx._pmap.items():
                _keys = []
                for _ctx._k in _fmap:
                    _keys.append(_ctx._k)
                _annot = None
                for _p, _ctx._pt in _ctx._fn.params or []:
                    if _p == _ctx._pname:
                        _annot = _ctx._pt
                        break
                if _annot is not None:
                    continue
                _cur = self._inferred_param_types.get(_callee, {}).get(_ctx._pname)
                if _cur not in (None, 'int', 'int64_t', 'MojoList *'):
                    continue
                self._inferred_param_types.setdefault(_callee, {})[_ctx._pname] = 'MojoGenerator *'
                if len(_keys) == 1 and _keys[0] != '<conflict>':
                    self._param_generator_api.setdefault(_callee, {})[_ctx._pname] = _keys[0]
                _ctx._changed = True
        if not _ctx._changed:
            break
    for _ctx.s in _ctx.all_functions:
        if _ctx._is_foreign_main(_ctx.s):
            continue
        if isinstance(_ctx.s, FunctionDef):
            if _ctx.s.params and any((_ctx.pn.startswith('*') for _ctx.pn, _ in _ctx.s.params)):
                self.func_param_types[_ctx.s.name] = self._signature_ctypes(_ctx.s.params, _ctx.s)
                self._note_vararg_trailing_param_types(_ctx.s)
            else:
                self.func_param_types[_ctx.s.name] = [self._param_ctype(_ctx.pn, _ctx.pt, _ctx.s) for _ctx.pn, _ctx.pt in _ctx.s.params] if _ctx.s.params else []
    if self.emit_struct_defs:
        self._dispatch_solver = DispatchSolver(self.struct_field_types, self.func_return_types, allow_assume_all_methods=_ctx._is_selfhost_file, generator_method_api=self._generator_method_api)
        all_stmts_for_dispatch = _ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else [])
        self._dispatch_solver.analyze(all_stmts_for_dispatch)
        self._dispatch_tables = self._dispatch_solver.get_dispatch_tables()
    self._all_closures: dict = {}

    def _scan_for_closures(outer_name: str, outer_scope: dict, body: list):
        """Scan a function/method body for nested FunctionDefs and register them as closures."""

        def _all_stmts_nonfunc(stmts):
            """Return a list of statements recursively through control flow, not entering FunctionDef bodies."""
            _ctx.result = []
            for _ctx.s in _ctx.stmts:
                _ctx.result.append(_ctx.s)
                if isinstance(_ctx.s, FunctionDef):
                    continue
                for _ctx.attr in ('then_body', 'else_body', 'body', 'finally_body'):
                    sub = getattr(_ctx.s, _ctx.attr, None)
                    if isinstance(sub, list):
                        _ctx.result.extend(_all_stmts_nonfunc(sub))
                for _ctx._cond, _ctx.elif_body in getattr(_ctx.s, 'elifs', []):
                    _ctx.result.extend(_all_stmts_nonfunc(_ctx.elif_body))
                for _ctx.handler in getattr(_ctx.s, 'handlers', []):
                    if hasattr(_ctx.handler, 'body') and isinstance(_ctx.handler.body, list):
                        _ctx.result.extend(_all_stmts_nonfunc(_ctx.handler.body))
            return _ctx.result
        enriched_scope = dict(_ctx.outer_scope)
        _saved_vt2 = dict(self.var_types)
        self.var_types.update(_ctx.outer_scope)
        for bstmt in _all_stmts_nonfunc(_ctx.body):
            if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                _ctx.name = bstmt.target.name
                if _ctx.name not in enriched_scope:
                    _ctx.t = self._quick_type(bstmt.value)
                    enriched_scope[_ctx.name] = _ctx.t
                    self.var_types[_ctx.name] = _ctx.t
            elif isinstance(bstmt, VarDecl):
                if bstmt.name not in enriched_scope:
                    _ctx.t = self._quick_type(bstmt.value) if bstmt.value else 'int64_t'
                    enriched_scope[bstmt.name] = _ctx.t
                    self.var_types[bstmt.name] = _ctx.t
        self.var_types = _saved_vt2
        for _ctx.stmt in _all_stmts_nonfunc(_ctx.body):
            if not isinstance(_ctx.stmt, FunctionDef):
                continue
            if _ctx.stmt.is_async and (not _ctx.stmt.is_generator):
                continue
            _ctx.inner = _ctx.stmt
            lifted = f'{_ctx.outer_name}_{_ctx.inner.name}'
            used = set()
            for body_node in _ctx.inner.body:
                used |= _used_idents_node(body_node)
            inner_assign_targets = set()
            for bstmt in _all_stmts_nonfunc(_ctx.inner.body):
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    inner_assign_targets.add(bstmt.target.name)
                elif isinstance(bstmt, ForStmt):
                    _ctx.tgt = bstmt.target
                    if isinstance(_ctx.tgt, str):
                        inner_assign_targets.add(_ctx.tgt)
                    elif hasattr(_ctx.tgt, 'name'):
                        inner_assign_targets.add(_ctx.tgt.name)
            inner_declared = {_ctx.pn for _ctx.pn, _ in _ctx.inner.params} | _declared_vars_body(_ctx.inner.body) | inner_assign_targets
            outer_params = set(_ctx.outer_scope.keys())
            free_globals = set(self.func_return_types.keys()) - outer_params
            free = used - inner_declared - free_globals
            captures = [(_ctx.v, enriched_scope[_ctx.v]) for _ctx.v in sorted(free) if _ctx.v in enriched_scope]
            _cap_names_so_far = {_cn for _cn, _ in captures}
            _called_names = {nd.func.name for nd in _walk_ast(_ctx.inner.body) if isinstance(nd, CallExpr) and isinstance(nd.func, IdentExpr)}
            _transitive_mut: set = set()
            for _called in _called_names:
                _t_api = self._nested_async_api.get(f'{_ctx.outer_name}::{_called}')
                if _t_api is None:
                    continue
                for _ctx._tn, _tt in _t_api.get('captures') or []:
                    if _ctx._tn not in _cap_names_so_far and _ctx._tn in enriched_scope:
                        captures.append((_ctx._tn, enriched_scope[_ctx._tn]))
                        _cap_names_so_far.add(_ctx._tn)
                    if _ctx._tn in (_t_api.get('mut_capture_names') or frozenset()):
                        _transitive_mut.add(_ctx._tn)
            env_struct = f'{lifted}_env' if captures else ''
            _ctx.ci = ClosureInfo(lifted, env_struct, captures, _ctx.inner)
            _inner_dflts = getattr(_ctx.inner, 'param_defaults', None) or {}
            if _inner_dflts:
                self._func_param_defaults[lifted] = [(_pn2, _dv2) for _pn2, _dv2 in _inner_dflts.items()]
            _ctx.ci.mut_names = self._mutated_free_names(_ctx.inner, _cap_names_so_far) | _transitive_mut
            if _ctx.outer_name not in self._all_closures:
                self._all_closures[_ctx.outer_name] = {}
            self._all_closures[_ctx.outer_name][_ctx.inner.name] = _ctx.ci
            if _ctx.inner.return_type is not None:
                self.func_return_types[lifted] = self._resolve_type(_ctx.inner.return_type)
            else:
                for _ctx.pname, _ctx.ptype in _ctx.inner.params:
                    self.var_types[_ctx.pname] = self._resolve_type(_ctx.ptype)
                self.func_return_types[lifted] = self._infer_return_type(_ctx.inner.body)
                self.var_types.clear()
            inner_scope = dict(enriched_scope)
            for _ctx.pn, _ctx.pt in _ctx.inner.params:
                inner_scope[_ctx.pn] = self._resolve_type(_ctx.pt)
            for bstmt in _ctx.inner.body:
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    _ctx.name = bstmt.target.name
                    if _ctx.name not in inner_scope:
                        inner_scope[_ctx.name] = self._quick_type(bstmt.value)
            _scan_for_closures(lifted, inner_scope, _ctx.inner.body)

        def _find_re_sub_callbacks(search_body, context_outer):
            for _ctx.stmt in search_body:
                stmts_to_check = []
                if isinstance(_ctx.stmt, AssignStmt):
                    stmts_to_check.append(_ctx.stmt.value)
                elif isinstance(_ctx.stmt, ExprStmt):
                    stmts_to_check.append(_ctx.stmt.value)
                elif hasattr(_ctx.stmt, 'body'):
                    _find_re_sub_callbacks(getattr(_ctx.stmt, 'body', []), context_outer)
                    for clause in ('orelse', 'handlers', 'finalbody'):
                        _find_re_sub_callbacks(getattr(_ctx.stmt, clause, []), context_outer)
                for _ctx.expr in stmts_to_check:
                    if not isinstance(_ctx.expr, CallExpr):
                        continue
                    _ctx.func = _ctx.expr.func
                    if isinstance(_ctx.func, MemberExpr) and isinstance(_ctx.func.obj, IdentExpr) and (_ctx.func.obj.name == 're') and (_ctx.func.member == 'sub') and (len(_ctx.expr.args) >= 2):
                        _ctx.cb_arg = _ctx.expr.args[1]
                        if isinstance(_ctx.cb_arg, IdentExpr):
                            _ctx.inner_map = self._all_closures.get(context_outer, {})
                            if _ctx.cb_arg.name in _ctx.inner_map:
                                _ctx.inner_map[_ctx.cb_arg.name].is_re_sub_callback = True
        _find_re_sub_callbacks(_ctx.body, _ctx.outer_name)
    for _ctx.s in _ctx.stmts:
        if isinstance(_ctx.s, FunctionDef):
            _ctx.outer_scope: dict = {}
            for _ctx.pname, _ctx.ptype in _ctx.s.params:
                _ctx.outer_scope[_ctx.pname] = self._resolve_type(_ctx.ptype)
            _saved_vt = dict(self.var_types)
            self.var_types.update(_ctx.outer_scope)
            for _ctx.stmt in _ctx.s.body:
                if isinstance(_ctx.stmt, VarDecl) and _ctx.stmt.type_ann is not None:
                    _ctx.t = _mojo_type(_ctx.stmt.type_ann)
                    _ctx.outer_scope[_ctx.stmt.name] = _ctx.t
                    self.var_types[_ctx.stmt.name] = _ctx.t
                elif isinstance(_ctx.stmt, AssignStmt) and isinstance(_ctx.stmt.target, IdentExpr):
                    if _ctx.stmt.target.name not in _ctx.outer_scope:
                        _ctx.t = self._quick_type(_ctx.stmt.value)
                        _ctx.outer_scope[_ctx.stmt.target.name] = _ctx.t
                        self.var_types[_ctx.stmt.target.name] = _ctx.t
            self.var_types = _saved_vt
            _scan_for_closures(_ctx.s.name, _ctx.outer_scope, _ctx.s.body)
        elif isinstance(_ctx.s, StructDef):
            _ctx._moids = self._struct_method_overload_ids(_ctx.s)
            for _ctx.method, _ctx._oid in zip(_ctx.s.methods, _ctx._moids):
                _ctx.outer_name = f'{_ctx.s.name}_{_ctx.method.name}{_ctx._oid}'
                _ctx.outer_scope = {_ctx.s.name.lower(): f'{_ctx.s.name} *'}
                for _ctx.pname, _ctx.ptype in _ctx.method.params:
                    if _ctx.pname == 'self':
                        _ctx.outer_scope['self'] = f'{_ctx.s.name} *'
                    else:
                        _ctx.outer_scope[_ctx.pname] = self._resolve_type(_ctx.ptype)
                for _cp_name in self._method_threaded_comptime_params.get((_ctx.s.name, _ctx.method.name), {}).get(_ctx._oid, []):
                    _ctx.outer_scope[_cp_name] = 'int64_t'
                _saved_vt = dict(self.var_types)
                self.var_types.update(_ctx.outer_scope)
                for _ctx.stmt in _ctx.method.body:
                    if isinstance(_ctx.stmt, VarDecl) and _ctx.stmt.type_ann is not None:
                        _ctx.t = _mojo_type(_ctx.stmt.type_ann)
                        _ctx.outer_scope[_ctx.stmt.name] = _ctx.t
                        self.var_types[_ctx.stmt.name] = _ctx.t
                    elif isinstance(_ctx.stmt, AssignStmt) and isinstance(_ctx.stmt.target, IdentExpr):
                        if _ctx.stmt.target.name not in _ctx.outer_scope:
                            _ctx.t = self._quick_type(_ctx.stmt.value)
                            _ctx.outer_scope[_ctx.stmt.target.name] = _ctx.t
                            self.var_types[_ctx.stmt.target.name] = _ctx.t
                self.var_types = _saved_vt
                _scan_for_closures(_ctx.outer_name, _ctx.outer_scope, _ctx.method.body)
    _ctx._changed = True
    while _ctx._changed:
        _ctx._changed = False
        for _outer_name, _inner_map in list(self._all_closures.items()):
            for _inner_name, _ctx._ci in list(_inner_map.items()):
                _sub_closures = self._all_closures.get(_ctx._ci.lifted_name, {})
                if not _sub_closures:
                    continue
                _ci_param_names = {_ctx.pn for _ctx.pn, _ in _ctx._ci.inner_def.params}
                _ci_local_assigns = set()
                for _ctx._bstmt in _ctx._ci.inner_def.body:
                    if isinstance(_ctx._bstmt, AssignStmt) and isinstance(_ctx._bstmt.target, IdentExpr):
                        _ci_local_assigns.add(_ctx._bstmt.target.name)
                _ci_own_vars = _ci_param_names | _declared_vars_body(_ctx._ci.inner_def.body) | _ci_local_assigns
                _ci_captures_dict = dict(_ctx._ci.captures)
                for _sub_ci in _sub_closures.values():
                    for _sv, _st in _sub_ci.captures:
                        if _sv not in _ci_own_vars and _sv not in _ci_captures_dict:
                            _ctx._ci.captures.append((_sv, _st))
                            _ci_captures_dict[_sv] = _st
                            if not _ctx._ci.env_struct:
                                _ctx._ci.env_struct = f'{_ctx._ci.lifted_name}_env'
                            _ctx._changed = True

def _gm_phase2a(self, _ctx):
    from gimple_codegen import TypeLattice, _debug_note, _import_targets, _module_init_name, _module_toplevel_name, _mojo_type, _safe_name
    for _p3b_s in _ctx.all_functions:
        if isinstance(_p3b_s, FunctionDef) and _p3b_s.return_type is None:
            _saved_vt_3b = self.var_types
            _saved_fcn_3b = self.current_func_name
            self.current_func_name = _p3b_s.name
            self.var_types = dict(_saved_vt_3b)
            for _ctx.pname, _ctx.ptype in _p3b_s.params:
                _ctx.bare = _ctx.pname.lstrip('*')
                if _ctx.pname.startswith('*'):
                    self.var_types[_ctx.bare] = 'MojoList *'
                elif _ctx.ptype is None:
                    self.var_types[_ctx.bare] = self._inferred_param_types.get(_p3b_s.name, {}).get(_ctx.bare) or self._resolve_type(_ctx.ptype)
                else:
                    self.var_types[_ctx.bare] = self._resolve_type(_ctx.ptype)
            for _cln, _clt in self._closure_value_locals(_p3b_s.body).items():
                if _cln not in self.var_types:
                    self.var_types[_cln] = _clt
            _ctx.inferred = self._infer_return_type(_p3b_s.body)
            if _p3b_s.name == 'main' and _ctx.inferred == 'void':
                _ctx.inferred = 'int64_t'
            self.var_types = _saved_vt_3b
            self.current_func_name = _saved_fcn_3b
            self.func_return_types[_p3b_s.name] = _ctx.inferred

    def _flatten_resolved_conditionals(_root_list):
        _out = []
        _ctx._stack = [(_root_list, 0)]
        while _ctx._stack:
            _ctx._frame_body, _ctx._frame_idx = _ctx._stack[-1]
            if _ctx._frame_idx >= len(_ctx._frame_body):
                _ctx._stack.pop()
                continue
            _ctx._frame_stmt = _ctx._frame_body[_ctx._frame_idx]
            _ctx._stack[-1] = (_ctx._frame_body, _ctx._frame_idx + 1)
            if isinstance(_ctx._frame_stmt, IfStmt):
                _ctx._resolved = False
                _ctx._resolved_body = []
                _ctx._cond_val = self._eval_const_bool(_ctx._frame_stmt.condition)
                if _ctx._cond_val is True:
                    _ctx._resolved = True
                    _ctx._resolved_body = _ctx._frame_stmt.then_body or []
                elif _ctx._cond_val is False:
                    _ctx._resolved = True
                    for _ctx._cond2, _ctx._elif_body2 in getattr(_ctx._frame_stmt, 'elifs', None) or []:
                        _ctx._elif_val = self._eval_const_bool(_ctx._cond2)
                        if _ctx._elif_val is True:
                            _ctx._resolved_body = _ctx._elif_body2 or []
                            break
                        if _ctx._elif_val is None:
                            _ctx._resolved = False
                            break
                    else:
                        _ctx._resolved_body = _ctx._frame_stmt.else_body or []
                if _ctx._resolved:
                    _ctx._stack.append((_ctx._resolved_body, 0))
                else:
                    _out.append(_ctx._frame_stmt)
            else:
                _out.append(_ctx._frame_stmt)
        return _out
    _pre_declared_globals = set()
    _phase17_mod = self.module_name or 'root'
    _phase17_own_stmts = _flatten_resolved_conditionals(_ctx.stmts)
    _phase17_stmts = _phase17_own_stmts + (_flatten_resolved_conditionals(_ctx.imported_stmts) if self.do_imports or self.link_imports else [])
    _phase17_own_ids = set((id(s) for s in _phase17_own_stmts))

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
        elif isinstance(_value, (IntLiteral, BoolLiteral)):
            return 'int'
        elif isinstance(_value, StringLiteral):
            return 'char *'
        elif isinstance(_value, CallExpr):
            if isinstance(_value.func, IdentExpr) and _value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set'):
                return {'dict': 'MojoDict *', 'Dict': 'MojoDict *', 'list': 'MojoList *', 'List': 'MojoList *', 'set': 'MojoSet *', 'Set': 'MojoSet *'}[_value.func.name]
            if isinstance(_value.func, IdentExpr) and _value.func.name in self.struct_field_types:
                return f'{_value.func.name} *'
            elif isinstance(_value.func, IdentExpr):
                _ctx.ret = self.func_return_types.get(_value.func.name, '')
                if _ctx.ret.endswith(' *'):
                    return _ctx.ret
                elif _ctx.ret == 'char *':
                    return 'char *'
                else:
                    return 'int64_t'
            elif isinstance(_value.func, MemberExpr) and _value.func.member in ('read', 'readline') and (not _value.args):
                return 'char *'
            elif isinstance(_value.func, MemberExpr) and _value.func.member == 'readlines':
                return 'MojoList *'
            else:
                return 'int64_t'
        elif isinstance(_value, MemberExpr) and isinstance(_value.obj, IdentExpr) and (_value.obj.name in self.imported_symbols):
            _mx_mod = self.imported_symbols[_value.obj.name].get('module')
            if _mx_mod and _value.member in self._global_var_types and (getattr(self, '_global_to_module', {}).get(_value.member) == _mx_mod):
                _ctx._mx_t = self._global_var_types[_value.member]
                if _ctx._mx_t.endswith(' *'):
                    return _ctx._mx_t
                elif _ctx._mx_t == '_Bool':
                    return 'int'
                else:
                    return 'int64_t'
            return 'int64_t'
        else:
            _ctx.qt = self._quick_type(_value) or 'int64_t'
            if _ctx.qt.endswith(' *'):
                return _ctx.qt
            elif _ctx.qt == '_Bool':
                return 'int'
            else:
                return 'int64_t'

    def _phase17_infer_global_type(_gname, _value):
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
        bugs/hard/CODEGEN_multi_assign_local_var_type_not_inferred.md
        (that doc covers the LOCAL-variable analogue of this same
        gap; this is the GLOBAL/module-scope sibling)."""
        self._global_var_types[_gname] = _phase17_value_type(_value)
        if isinstance(_value, (ListExpr, TupleExpr)) and _value.elements:
            _elt = self._quick_type(_value.elements[0])
            for _e in _value.elements[1:]:
                _elt = TypeLattice.join(_elt, self._quick_type(_e))
            self._elem_types[_gname] = _elt
            self._global_elem_types[_gname] = _elt
        elif isinstance(_value, DictExpr) and _value.pairs:
            _vt = self._quick_type(_value.pairs[0][1])
            for _ctx._k, _v in _value.pairs[1:]:
                _vt = TypeLattice.join(_vt, self._quick_type(_v))
            self._global_dict_val_types[_gname] = _vt

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
        for _ctx._h in _try_stmt.handlers or []:
            _branch_lists.append(getattr(_ctx._h, 'body', None) or [])
        if isinstance(_try_stmt.else_body, list):
            _branch_lists.append(_try_stmt.else_body)
        if isinstance(getattr(_try_stmt, 'finally_body', None), list):
            _branch_lists.append(_try_stmt.finally_body)
        _joined = {}
        for _blist in _branch_lists:
            for _ctx._bstmt in _flatten_resolved_conditionals(_blist):
                _pairs = []
                if isinstance(_ctx._bstmt, AssignStmt) and isinstance(_ctx._bstmt.target, IdentExpr):
                    _pairs.append((_ctx._bstmt.target.name, _ctx._bstmt.value))
                elif isinstance(_ctx._bstmt, MultiAssignStmt):
                    for _ctx._tgt in _ctx._bstmt.targets:
                        if isinstance(_ctx._tgt, IdentExpr):
                            _pairs.append((_ctx._tgt.name, _ctx._bstmt.value))
                for _gname, _gvalue in _pairs:
                    _t = _phase17_value_type(_gvalue)
                    _joined[_gname] = TypeLattice.join(_joined[_gname], _t) if _gname in _joined else _t
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
        bugs/CODEGEN_generator_function_Lib_tarfile.md.

        Deliberately NOT self-recursive for the same reason
        `_phase17_scan_try_branches` isn't (a nested function calling
        itself here doesn't survive this file's own self-host build)
        — a nested if/elif/else inside one of THIS if's own branches
        is left unscanned (out of scope; no observed real-world
        instance needs it)."""
        _branch_lists = [_if_stmt.then_body or []]
        for _ctx._cond2, _ctx._elif_body2 in getattr(_if_stmt, 'elifs', None) or []:
            _branch_lists.append(_ctx._elif_body2 or [])
        if isinstance(_if_stmt.else_body, list):
            _branch_lists.append(_if_stmt.else_body)
        _joined = {}
        for _blist in _branch_lists:
            for _ctx._bstmt in _flatten_resolved_conditionals(_blist):
                _pairs = []
                if isinstance(_ctx._bstmt, AssignStmt) and isinstance(_ctx._bstmt.target, IdentExpr):
                    _pairs.append((_ctx._bstmt.target.name, _ctx._bstmt.value))
                elif isinstance(_ctx._bstmt, MultiAssignStmt):
                    for _ctx._tgt in _ctx._bstmt.targets:
                        if isinstance(_ctx._tgt, IdentExpr):
                            _pairs.append((_ctx._tgt.name, _ctx._bstmt.value))
                for _gname, _gvalue in _pairs:
                    _t = _phase17_value_type(_gvalue)
                    _joined[_gname] = TypeLattice.join(_joined[_gname], _t) if _gname in _joined else _t
        return _joined
    for _scan_stmt in _phase17_stmts:
        if isinstance(_scan_stmt, AssignStmt) and isinstance(_scan_stmt.target, IdentExpr):
            _gname = _scan_stmt.target.name
            if isinstance(_scan_stmt.value, CallExpr) and isinstance(_scan_stmt.value.func, MemberExpr) and isinstance(_scan_stmt.value.func.obj, IdentExpr) and (_scan_stmt.value.func.obj.name == 're') and (_scan_stmt.value.func.member == 'compile') and _scan_stmt.value.args and isinstance(_scan_stmt.value.args[0], StringLiteral):
                self._regex_patterns[_gname] = _scan_stmt.value.args[0].value
            if _gname in _pre_declared_globals:
                continue
            _pre_declared_globals.add(_gname)
            if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                self._global_to_module[_gname] = _phase17_mod
            _phase17_infer_global_type(_gname, _scan_stmt.value)
        elif isinstance(_scan_stmt, MultiAssignStmt):
            for _ctx._tgt in _scan_stmt.targets:
                if not isinstance(_ctx._tgt, IdentExpr):
                    continue
                _gname = _ctx._tgt.name
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_infer_global_type(_gname, _scan_stmt.value)
        elif isinstance(_scan_stmt, VarDecl) and _scan_stmt.name not in _pre_declared_globals:
            _pre_declared_globals.add(_scan_stmt.name)
            if _scan_stmt.name not in self._global_to_module:
                self._global_to_module[_scan_stmt.name] = _phase17_mod
            if _scan_stmt.type_ann:
                _ctx._resolved = self._resolve_type(_scan_stmt.type_ann)
                self._global_var_types[_scan_stmt.name] = _ctx._resolved
                if _ctx._resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
            elif hasattr(_scan_stmt, 'value') and _scan_stmt.value:
                if isinstance(_scan_stmt.value, DictExpr):
                    self._global_var_types[_scan_stmt.name] = 'MojoDict *'
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                elif isinstance(_scan_stmt.value, (ListExpr, TupleExpr)):
                    self._global_var_types[_scan_stmt.name] = 'MojoList *'
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                elif isinstance(_scan_stmt.value, SetExpr):
                    self._global_var_types[_scan_stmt.name] = 'MojoSet *'
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                elif isinstance(_scan_stmt.value, StringLiteral):
                    self._global_var_types[_scan_stmt.name] = 'char *'
                elif isinstance(_scan_stmt.value, CallExpr) and isinstance(_scan_stmt.value.func, IdentExpr) and (_scan_stmt.value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set')):
                    self._global_var_types[_scan_stmt.name] = {'dict': 'MojoDict *', 'Dict': 'MojoDict *', 'list': 'MojoList *', 'List': 'MojoList *', 'set': 'MojoSet *', 'Set': 'MojoSet *'}[_scan_stmt.value.func.name]
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                elif isinstance(_scan_stmt.value, CallExpr):
                    if isinstance(_scan_stmt.value.func, IdentExpr):
                        _ctx.ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                        if _ctx.ret and _ctx.ret.endswith(' *'):
                            self._global_var_types[_scan_stmt.name] = _ctx.ret
                        elif _ctx.ret == 'char *':
                            self._global_var_types[_scan_stmt.name] = 'char *'
                        else:
                            self._global_var_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value.func, MemberExpr) and _scan_stmt.value.func.member in ('read', 'readline') and (not _scan_stmt.value.args):
                        self._global_var_types[_scan_stmt.name] = 'char *'
                    elif isinstance(_scan_stmt.value.func, MemberExpr) and _scan_stmt.value.func.member == 'readlines':
                        self._global_var_types[_scan_stmt.name] = 'MojoList *'
                    else:
                        self._global_var_types[_scan_stmt.name] = 'int64_t'
                else:
                    _ctx.qt = self._quick_type(_scan_stmt.value) or 'int64_t'
                    self._global_var_types[_scan_stmt.name] = _ctx.qt if _ctx.qt.endswith(' *') or _ctx.qt == '_Bool' else 'int64_t'
            else:
                self._global_var_types[_scan_stmt.name] = 'int64_t'
        elif isinstance(_scan_stmt, TryStmt):
            for _gname, _ctx._gtype in _phase17_scan_try_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                self._global_var_types[_gname] = _ctx._gtype
        elif isinstance(_scan_stmt, IfStmt):
            for _gname, _ctx._gtype in _phase17_scan_if_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                self._global_var_types[_gname] = _ctx._gtype
        elif isinstance(_scan_stmt, ComptimeVarStmt) and isinstance(_scan_stmt.value, (ListExpr, TupleExpr)) and (_scan_stmt.target not in _pre_declared_globals):
            _pre_declared_globals.add(_scan_stmt.target)
            if _scan_stmt.target not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                self._global_to_module[_scan_stmt.target] = _phase17_mod
            _phase17_infer_global_type(_scan_stmt.target, _scan_stmt.value)

    def _phase17_collect_appends(_node_list, _append_hits):
        for _ctx._n in _node_list:
            if isinstance(_ctx._n, ExprStmt) and isinstance(_ctx._n.value, CallExpr) and isinstance(_ctx._n.value.func, MemberExpr) and (_ctx._n.value.func.member == 'append') and isinstance(_ctx._n.value.func.obj, IdentExpr) and (len(_ctx._n.value.args) == 1):
                _append_hits.setdefault(_ctx._n.value.func.obj.name, []).append(self._quick_type(_ctx._n.value.args[0]))
            if isinstance(_ctx._n, FunctionDef):
                _saved = self.var_types
                self.var_types = dict(_saved)
                for _ctx._pname, _ctx._ptype in _ctx._n.params or []:
                    if _ctx._ptype:
                        self.var_types[_ctx._pname] = _mojo_type(_ctx._ptype)
                for _lname, _ltype in self._infer_local_var_types(_ctx._n).items():
                    if _lname not in self.var_types:
                        self.var_types[_lname] = _ltype
                _phase17_collect_appends(_ctx._n.body or [], _append_hits)
                self.var_types = _saved
            elif isinstance(_ctx._n, IfStmt):
                _phase17_collect_appends(_ctx._n.then_body or [], _append_hits)
                if _ctx._n.else_body:
                    _phase17_collect_appends(_ctx._n.else_body, _append_hits)
                for _ctx._cond2, _ebody2 in _ctx._n.elifs or []:
                    _phase17_collect_appends(_ebody2 or [], _append_hits)
            elif isinstance(_ctx._n, (WhileStmt, ForStmt)):
                _phase17_collect_appends(_ctx._n.body or [], _append_hits)
                if getattr(_ctx._n, 'else_body', None):
                    _phase17_collect_appends(_ctx._n.else_body, _append_hits)
            elif isinstance(_ctx._n, TryStmt):
                _phase17_collect_appends(_ctx._n.body or [], _append_hits)
                for _ctx._h in _ctx._n.handlers or []:
                    _phase17_collect_appends(getattr(_ctx._h, 'body', None) or [], _append_hits)
                if isinstance(_ctx._n.else_body, list):
                    _phase17_collect_appends(_ctx._n.else_body, _append_hits)
                if isinstance(getattr(_ctx._n, 'finally_body', None), list):
                    _phase17_collect_appends(_ctx._n.finally_body, _append_hits)
            elif isinstance(_ctx._n, WithStmt):
                _phase17_collect_appends(_ctx._n.body or [], _append_hits)
    _phase17_append_hits: dict = {}
    _phase17_collect_appends(_phase17_stmts, _phase17_append_hits)
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

    def _scan_try_imports(stmt_list):
        for _ctx._s in stmt_list:
            if isinstance(_ctx._s, ImportStmt):
                for _ctx._tm, _ctx._ta in _import_targets(_ctx._s):
                    _local = _ctx._ta if _ctx._ta else _ctx._tm
                    if _local not in self._global_var_types:
                        self._global_var_types[_local] = 'int64_t'
                        self._global_c_decl_types[_local] = 'int64_t'
                        if _local not in self._global_to_module:
                            self._global_to_module[_local] = _phase17_mod
            elif isinstance(_ctx._s, TryStmt):
                _scan_try_imports(_ctx._s.body or [])
                for _ctx._h in _ctx._s.handlers or []:
                    _scan_try_imports(getattr(_ctx._h, 'body', []) or [])
            elif isinstance(_ctx._s, IfStmt):
                _scan_try_imports(_ctx._s.then_body or [])
                if isinstance(_ctx._s.else_body, list):
                    _scan_try_imports(_ctx._s.else_body)
    _scan_try_imports(_ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else []))
    _EARLY_DISPATCH_DICTS = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS', '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
    _EARLY_DISPATCH_SETS = {'_CMP_OPS'}
    for _ctx._gn, _gt in list(self._global_var_types.items()):
        if _ctx._gn in self._global_c_decl_types:
            continue
        if _ctx._gn in _EARLY_DISPATCH_DICTS:
            self._global_c_decl_types[_ctx._gn] = 'MojoDict *'
        elif _ctx._gn in _EARLY_DISPATCH_SETS:
            self._global_c_decl_types[_ctx._gn] = 'MojoSet *'
        elif _gt in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            self._global_c_decl_types[_ctx._gn] = 'int64_t'
        else:
            self._global_c_decl_types[_ctx._gn] = _gt
    _ctx.func_parts: list[str] = []
    _emitted_closures: set[str] = set()

    def _emit_closure_recursive(ci, outer_name: str=None) -> None:
        """Emit sub-closures first (depth-first), then this closure's allocator + body."""
        if _ctx.ci.lifted_name in _emitted_closures:
            return
        _emitted_closures.add(_ctx.ci.lifted_name)
        for sub_ci in self._all_closures.get(_ctx.ci.lifted_name, {}).values():
            _emit_closure_recursive(sub_ci, _ctx.ci.lifted_name)
        if _ctx.ci.env_struct:
            _ctx.alloc_fn = f'_alloc_{_ctx.ci.env_struct}'
            _ctx.func_parts.append(f'{_ctx.ci.env_struct} * __GIMPLE {_ctx.alloc_fn} (void)\n{{\n  {_ctx.ci.env_struct} * _e;\n  void * _vp;\n\nbb_2:\n  _vp = malloc (sizeof({_ctx.ci.env_struct}));\n  _e = ({_ctx.ci.env_struct} *) _vp;\n  return _e;\n}}')
            _ctx.func_parts.append('')
        _ctx.func_parts.append(self._gen_lifted_closure(_ctx.ci, outer_name))
        _ctx.func_parts.append('')
    _ctx.toplevel_stmts = []
    _toplevel_types = (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)
    self._has_toplevel_code = False
    for _ts in _ctx.stmts:
        if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
            self._has_toplevel_code = True
            break
        if isinstance(_ts, ComptimeVarStmt) and isinstance(_ts.value, (ListExpr, TupleExpr)):
            self._has_toplevel_code = True
            break
    self._toplevel_calls_main = False
    for _ts in _ctx.stmts:
        if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
            for _ctx._n in _walk_ast(_ts):
                if isinstance(_ctx._n, CallExpr) and isinstance(_ctx._n.func, IdentExpr) and (_ctx._n.func.name == 'main'):
                    self._toplevel_calls_main = True
                    break
            if self._toplevel_calls_main:
                break
    for _ctx.stmt in _ctx.stmts:
        if isinstance(_ctx.stmt, FunctionDef):
            if _ctx.stmt.name in self._supported_generators or _ctx.stmt.name in self._supported_async or _ctx.stmt.name in self._supported_async_gen:
                continue
            if _ctx.stmt.name in self._unsupported_generator_names:
                continue
            _nested_pushed = []
            _prefix = f'{_ctx.stmt.name}::'
            for _qn, _info in self._nested_async_api.items():
                if _qn.startswith(_prefix):
                    _ctx._nm = _info['nested_name']
                    self._async_api[_ctx._nm] = _info
                    _nested_pushed.append(_ctx._nm)
            for _cvs in _ctx.stmt.body:
                if isinstance(_cvs, ComptimeVarStmt):
                    _ctx._cv = self._eval_const(_cvs.value)
                    if _ctx._cv is not None:
                        self._comptime_vals.setdefault(_cvs.target, _ctx._cv)
            _func_outer_scope = self._push_import_scope()
            self._collect_body_import_bindings(_ctx.stmt.body, _func_outer_scope)
            try:
                for _ctx.ci in self._all_closures.get(_ctx.stmt.name, {}).values():
                    _emit_closure_recursive(_ctx.ci, _ctx.stmt.name)
                self._lambda_parts = []
                _ctx.func_parts.append(self.gen_func(_ctx.stmt))
            finally:
                self._pop_import_scope()
                for _ctx._nm in _nested_pushed:
                    self._async_api.pop(_ctx._nm, None)
            if self._lambda_parts:
                _ctx.func_parts.extend(self._lambda_parts)
                self._lambda_parts = []
            _ctx.func_parts.append('')
        elif isinstance(_ctx.stmt, StructDef):
            _ctx._moids = self._struct_method_overload_ids(_ctx.stmt)
            for _ctx.m, _ctx.overload_id in zip(_ctx.stmt.methods, _ctx._moids):
                if (_ctx.stmt.name, _ctx.m.name) in self._supported_generator_methods:
                    continue
                method_outer_name = f'{_ctx.stmt.name}_{_ctx.m.name}{_ctx.overload_id}'
                _method_outer_scope = self._push_import_scope()
                self._collect_body_import_bindings(_ctx.m.body, _method_outer_scope)
                for _ctx.ci in self._all_closures.get(method_outer_name, {}).values():
                    _emit_closure_recursive(_ctx.ci, method_outer_name)
                self._lambda_parts = []
                _ctx.func_parts.append(self._gen_struct_method(_ctx.stmt.name, _ctx.m, _ctx.overload_id))
                _ctx.func_parts.append('')
                self._pop_import_scope()
                if self._lambda_parts:
                    _ctx.func_parts.extend(self._lambda_parts)
                    self._lambda_parts = []
        elif isinstance(_ctx.stmt, TraitDef):
            lines = [f'typedef struct {_ctx.stmt.name}_vtable {{']
            _seen_vtable_members: set = set()
            for _ctx.m in _ctx.stmt.methods:
                safe_mname = _safe_name(_ctx.m.name)
                if safe_mname in _seen_vtable_members:
                    continue
                _seen_vtable_members.add(safe_mname)
                _ctx.ret = self._resolve_type(_ctx.m.return_type)
                if _ctx.m.params and any((_ctx.pn.startswith('*') for _ctx.pn, _ in _ctx.m.params)):
                    _ctx.ptypes = 'MojoList *'
                else:
                    _ctx.ptypes = ', '.join((self._resolve_type(_ctx.pt) for _, _ctx.pt in _ctx.m.params)) if _ctx.m.params else 'void'
                lines.append(f'  {_ctx.ret} (*{safe_mname}) ({_ctx.ptypes});')
            lines.append(f'}} {_ctx.stmt.name}_vtable;')
            _ctx.func_parts.extend(lines)
            _ctx.func_parts.append('')
        elif isinstance(_ctx.stmt, (ImportStmt, FromImportStmt)):
            pass
        elif isinstance(_ctx.stmt, ComptimeVarStmt) and isinstance(_ctx.stmt.value, (ListExpr, TupleExpr)):
            _ctx.toplevel_stmts.append(AssignStmt(target=IdentExpr(_ctx.stmt.target, line=_ctx.stmt.line, col=_ctx.stmt.col), value=_ctx.stmt.value, line=_ctx.stmt.line, col=_ctx.stmt.col))
        elif isinstance(_ctx.stmt, (AssignStmt, AugAssignStmt, MultiAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
            _ctx.toplevel_stmts.append(_ctx.stmt)
        else:
            _debug_note('top-level statement dropped', type(_ctx.stmt).__name__)
            _ctx.func_parts.append(f'/* TODO: top-level {type(_ctx.stmt).__name__} */')
    _ctx.func_defs = [s for s in _ctx.stmts if isinstance(s, FunctionDef)]
    for _ctx.fn in _ctx.func_defs:
        if _ctx.fn.name == 'main':
            continue
        if _ctx.fn.params and any((_ctx.pn.startswith('*') for _ctx.pn, _ in _ctx.fn.params)):
            self.func_param_types[_ctx.fn.name] = self._signature_ctypes(_ctx.fn.params, _ctx.fn)
            self._note_vararg_trailing_param_types(_ctx.fn)
        else:
            _ctx.inferred_params = self._inferred_param_types.get(_ctx.fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
            _ctx.param_ctypes = []
            for _ctx.pn, _ctx.pt in _ctx.fn.params or []:
                if _ctx.pn in _ctx.inferred_params:
                    _ctx.param_ctypes.append(_ctx.inferred_params[_ctx.pn])
                else:
                    _ctx.param_ctypes.append(self._param_ctype(_ctx.pn, _ctx.pt, _ctx.fn))
            self.func_param_types[_ctx.fn.name] = _ctx.param_ctypes
    _ctx.has_toplevel_code = len(_ctx.toplevel_stmts) > 0
    if _ctx.has_toplevel_code:
        toplevel_func = self._gen_toplevel(_ctx.toplevel_stmts)
        _ctx.func_parts.append(toplevel_func)
        _ctx.func_parts.append('')
        if not self.emit_entry_points:
            _ctx.sub_fn = _module_toplevel_name(self.module_name)
            if _ctx.sub_fn not in self._sub_toplevels:
                self._sub_toplevels.append(_ctx.sub_fn)
            if not self.do_imports:
                init_fn = _module_init_name(self.module_name)
                _ctx.func_parts.append(f'__attribute__((constructor)) static void {_ctx.sub_fn}_ctor (void)')
                _ctx.func_parts.append('{')
                _ctx.func_parts.append(f'  {_ctx.sub_fn} ();')
                _ctx.func_parts.append('}')
                _ctx.func_parts.append('')
                _ctx.func_parts.append(f'void {init_fn} (void)')
                _ctx.func_parts.append('{')
                _ctx.func_parts.append(f'  {_ctx.sub_fn} ();')
                _ctx.func_parts.append('}')
                _ctx.func_parts.append('')
    if self.emit_entry_points:
        has_main = False
        for _hs in _ctx.stmts:
            if isinstance(_hs, FunctionDef) and _hs.name == 'main':
                has_main = True
                break
        if not has_main:
            _ctx.func_parts.append('int _gimple_main (void)')
            _ctx.func_parts.append('{')
            _ctx.func_parts.append('  return 0;')
            _ctx.func_parts.append('}')
            _ctx.func_parts.append('')
            _ctx.func_parts.append('int main (int argc, const char **argv) {')
            _ctx.func_parts.append('  mojo_set_argv(argc, argv);')
            _ctx.func_parts.append('#if USE_PYTHON')
            _ctx.func_parts.append('  Py_Initialize ();')
            _ctx.func_parts.append('#endif')
            for _ctx.sub_fn in self._sub_toplevels:
                _ctx.func_parts.append(f'  {_ctx.sub_fn} ();')
            if _ctx.has_toplevel_code:
                _ctx.func_parts.append('  _toplevel ();')
            _ctx.func_parts.append('#if USE_PYTHON')
            _ctx.func_parts.append('  Py_Finalize ();')
            _ctx.func_parts.append('#endif')
            _ctx.func_parts.append('  return 0;')
            _ctx.func_parts.append('}')

def _gm_phase2b(self, _ctx):
    from gimple_codegen import _C_KEYWORDS, _C_PARAM_EXTRA_KEYWORDS, _C_RESERVED_FUNCS, _EXPR_DISPATCH, _STMT_DISPATCH, _c_escape, _c_field_name, _c_id, _class_attr_ctype, _emitted_unresolved_stub_syms, _extract_init_expr, _import_targets, _module_toplevel_name, _safe_field, _safe_name, _struct_type_id, _stub_guard_name
    _ctx.parts = ['/* Generated by gimple_codegen.py */', '/* Compile with: gcc -fgimple -fsyntax-only file.c (uses gcc-15 if available) */', '#define USE_PYTHON 1' if self._python_api_needed else '#define USE_PYTHON 0', '#include <stdint.h>', '#include <stdlib.h>', '#include <string.h>', '#include <math.h>', '#include <stdio.h>', '#include <setjmp.h>', '#include <dlfcn.h>', '#if USE_PYTHON', '#include <Python.h>', '#endif', '#include <mojo_runtime.h>', '#include <mojo_sqlite3.h>', '#include <mojo_zlib.h>', '#include <mojo_ssl.h>', '#include <mojo_ncurses.h>', '/* Disable security wrappers: sprintf/snprintf/memcpy/memmove/memset/', '   strcpy/strncpy/strcat/strncat macros expand to nested', '   __builtin___*_chk calls which GIMPLE rejects (confirmed for memcpy:', '   a bare memcpy(dst, src, n) call expanded to', '   __builtin___memcpy_chk(dst, src, n, __builtin_object_size(dst, 0))', '   and broke every cold-CAS-cache stdlib build via List[T].extend,', '   investigated 2026-07-15 — the other _FORTIFY_SOURCE-wrapped libc', '   functions below are the same class of bug, pre-empted before they', '   bite the same way). */', '#ifdef sprintf', '#undef sprintf', '#endif', '#ifdef snprintf', '#undef snprintf', '#endif', '#ifdef memcpy', '#undef memcpy', '#endif', '#ifdef memmove', '#undef memmove', '#endif', '#ifdef memset', '#undef memset', '#endif', '#ifdef strcpy', '#undef strcpy', '#endif', '#ifdef strncpy', '#undef strncpy', '#endif', '#ifdef strcat', '#undef strcat', '#endif', '#ifdef strncat', '#undef strncat', '#endif', '/* Undefine exception-name macros from mojo_runtime.h that clash with', '   Mojo struct/class names in generated code. */', '#ifdef StopIteration', '#undef StopIteration', '#endif', '#ifdef ValueError', '#undef ValueError', '#endif', '#ifdef TypeError', '#undef TypeError', '#endif', '#ifdef IndexError', '#undef IndexError', '#endif', '#ifdef KeyError', '#undef KeyError', '#endif', '#ifdef NotImplementedError', '#undef NotImplementedError', '#endif', 'void mojo_print(char *str);']
    if self.emit_entry_points:
        for _ctx.sub_fn in self._sub_toplevels:
            _ctx.parts.append(f'void {_ctx.sub_fn}(void);')
        if _ctx.has_toplevel_code:
            _ctx.parts.append('void _toplevel(void);')
    elif _ctx.has_toplevel_code:
        fn_name = _module_toplevel_name(self.module_name)
        _ctx.parts.append(f'void {fn_name}(void);')
    _local_structs = set(self.struct_field_types.keys())
    _imported_names = set(self.imported_symbols.keys())
    _skip_ctors = _local_structs | _imported_names
    _builtin_ctors = [('String', 'int64_t String(...);'), ('Int', 'int64_t Int(...);'), ('UInt', 'int64_t UInt(...);'), ('Bool', 'int64_t Bool(...);'), ('Int8', 'int64_t Int8(...);'), ('Int16', 'int64_t Int16(...);'), ('Int32', 'int64_t Int32(...);'), ('Int64', 'int64_t Int64(...);'), ('UInt8', 'int64_t UInt8(...);'), ('UInt16', 'int64_t UInt16(...);'), ('UInt32', 'int64_t UInt32(...);'), ('UInt64', 'int64_t UInt64(...);'), ('Float16', 'int64_t Float16(...);'), ('BFloat16', 'int64_t BFloat16(...);'), ('Float32', 'int64_t Float32(...);'), ('Float64', 'int64_t Float64(...);'), ('Error', 'int64_t Error(...);')]

    def _guarded_ctor(name, decl):
        _ctx.guard = f'_MOJO_CTOR_{name.upper()}'
        stub_guard = _stub_guard_name(name)
        return f'#ifndef {stub_guard}\n#ifndef {_ctx.guard}\n#define {_ctx.guard}\n' + (decl + '\n#endif\n#endif')
    _ctor_lines = [_guarded_ctor(name, decl) for name, decl in _builtin_ctors if name not in _skip_ctors]
    if _ctor_lines:
        _ctx.parts.append('/* Mojo built-in type constructors */')
        _ctx.parts.extend(_ctor_lines)
        _ctx.parts.append('')
    _local_funcs = {_ctx.s.name for _ctx.s in _ctx.stmts if isinstance(_ctx.s, FunctionDef) and _ctx.s.name not in _C_RESERVED_FUNCS}
    for _ctx._s in _ctx.stmts:
        if isinstance(_ctx._s, StructDef):
            for _ctx._m in _ctx._s.methods or []:
                if isinstance(_ctx._m, FunctionDef):
                    _local_funcs.add(f'{_ctx._s.name}_{_ctx._m.name}')
    _local_funcs_renamed = {_safe_name(_ctx.s.name) for _ctx.s in _ctx.stmts if isinstance(_ctx.s, FunctionDef)}
    _imported_names_renamed = {_safe_name(n) for n in _imported_names}
    _all_defined_funcs = (set(self.func_return_types.keys()) | self._global_inline_defs) - _C_RESERVED_FUNCS
    _skip_util = _local_structs | _imported_names | _local_funcs | _all_defined_funcs | _local_funcs_renamed | _imported_names_renamed
    _util_pairs = [('iter', 'int64_t iter(...);'), ('next', 'int64_t next(...);'), ('swap', 'void swap(...);'), ('op', 'int64_t op(...);'), ('U128', 'int64_t U128(...);'), ('Pointer', '#ifndef _MOJO_POINTER_STRUCT_DEF\nint64_t Pointer(...);\n#endif'), ('UnsafePointer', 'int64_t UnsafePointer(...);'), ('StringSlice', 'int64_t StringSlice(...);'), ('StaticString', 'int64_t StaticString(...);'), ('debug_assert', 'void debug_assert(...);'), ('__get_mvalue_as_litref', 'int64_t __get_mvalue_as_litref(...);'), ('__get_litref_as_mvalue', 'int64_t __get_litref_as_mvalue(...);'), ('MojoList_unsafe_ptr', 'int64_t MojoList_unsafe_ptr(...);'), ('MojoList_unsafe_get', 'int64_t MojoList_unsafe_get(...);'), ('Span_unsafe_ptr', 'int64_t Span_unsafe_ptr(...);'), ('Optional', 'int64_t Optional(...);'), ('int64_t_init_pointee_move', 'void int64_t_init_pointee_move(...);'), ('conforms_to', '_Bool conforms_to(int64_t a, int64_t b);'), ('Codepoint', 'int64_t Codepoint(...);'), ('stat_result', 'int64_t stat_result(...);'), ('UInt128', 'int64_t UInt128(...);'), ('SIMDSize', 'int64_t SIMDSize(...);'), ('List', 'int64_t List(...);'), ('MojoDict__reserved', 'int64_t MojoDict__reserved(...);'), ('ord', 'int64_t ord(...);'), ('chr', 'int64_t chr(...);'), ('sort', 'void sort(...);'), ('Span_byte_length', 'int64_t Span_byte_length(...);'), ('_stat_macos', 'int64_t _stat_macos(...);'), ('_getpw_macos', 'int64_t _getpw_macos(...);'), ('Passwd', 'int64_t Passwd(...);'), ('create_test_device_context', 'int64_t create_test_device_context(...);'), ('check_write_to', 'void check_write_to(...);'), ('_unsupported_mma_op', 'void _unsupported_mma_op(...);'), ('IntType', 'int64_t IntType(...);'), ('Byte', 'int64_t Byte(...);'), ('hash', 'int64_t hash(...);'), ('MojoList___contains__', 'int64_t MojoList___contains__(...);'), ('MojoList_get_loaded_kgen_pack', 'int64_t MojoList_get_loaded_kgen_pack(...);'), ('_stat_linux_x86', 'int64_t _stat_linux_x86(...);'), ('func', 'int64_t func(...);'), ('mojo_getenv', 'int64_t mojo_getenv(...);'), ('mojo_atol', 'int64_t mojo_atol(...);'), ('mojo_frexp', 'int64_t mojo_frexp(...);'), ('mojo_abort', 'void mojo_abort(...);'), ('Span_as_bytes', 'int64_t Span_as_bytes(...);'), ('Span_get_immutable', 'int64_t Span_get_immutable(...);'), ('_Bool___mlir_i1__', 'int64_t _Bool___mlir_i1__(...);'), ('sync_parallelize', 'void sync_parallelize(...);'), ('main_func', 'void main_func(void);'), ('scalar', 'int64_t scalar(...);'), ('Scalar', 'int64_t Scalar(...);'), ('type_of', 'int64_t type_of(...);'), ('align_up', 'int64_t align_up(...);'), ('align_down', 'int64_t align_down(...);'), ('clamp', 'int64_t clamp(...);'), ('serialize', 'void serialize(...);'), ('slice', 'int64_t slice(...);'), ('_getpw_linux', 'int64_t _getpw_linux(...);'), ('_lstat_macos', 'int64_t _lstat_macos(...);'), ('getuid', 'unsigned int getuid (void);'), ('getgid', 'unsigned int getgid (void);'), ('getpid', 'int getpid (void);'), ('getppid', 'int getppid (void);'), ('isatty', 'int isatty (int fd);'), ('sysconf', 'long sysconf (int name);'), ('_log2_ceil', 'int64_t _log2_ceil(...);'), ('int64_t_unsafe_value', 'int64_t int64_t_unsafe_value(...);'), ('MojoDict_unsafe_ptr', 'int64_t MojoDict_unsafe_ptr(...);'), ('_Empty_copy', 'void _Empty_copy(...);'), ('_get_global_or_null', 'int64_t _get_global_or_null(...);')]

    def _guarded_stub(name, decl):
        _ctx.guard = _stub_guard_name(name)
        return f'#ifndef {_ctx.guard}\n#define {_ctx.guard}\n' + (decl + '\n#endif')
    _util_stubs = [_guarded_stub(name, decl) for name, decl in _util_pairs if name not in _skip_util]
    _ctx.parts.extend(['/* Mojo iterator and utility functions */', *_util_stubs, '', '/* Struct ___new stubs (for Self(...) call sites) */', *[f'int64_t {_ctx.s}___new(...);' for _ctx.s in sorted(self._self_ctor_stubs)], '', '/* Renamed C-reserved builtins called without import (e.g. abs→mojo_abs) */', *[f'{rt} {_ctx.fn}(...);' for _ctx.fn, rt in sorted(self._renamed_builtin_calls.items()) if _ctx.fn not in _skip_util and _ctx.fn not in _imported_names and (_ctx.fn not in _local_funcs) and (_ctx.fn not in _local_funcs_renamed) and (_ctx.fn not in _imported_names_renamed)], '', '', 'char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename);', 'char *compile_to_gimple(char *mojo_src, int do_imports, char *filename);', 'int64_t mojo_open_file(char *path);', *([] if 'open' in self.func_return_types or 'open' in self.imported_symbols else ['void *mojo_open(char *filename, char *mode);']), 'int64_t int_write (int64_t, char *);', 'int64_t int_parse_module (int);', '#ifndef _MOJO_UNIMPL_STUBS', '#define _MOJO_UNIMPL_STUBS', 'static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }', 'static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }', 'static int64_t id (int64_t x) { return x; }', '#endif'])
    for _decl in self._link_import_decl_list:
        _ctx.parts.append(_decl)
    our_mod = self.module_name or 'root'
    if not self.module_name and self._current_filename:
        our_mod = os.path.splitext(os.path.basename(self._current_filename))[0]
    all_modules_to_declare = set()
    if our_mod != 'root':
        all_modules_to_declare.add('root')
    all_modules_to_declare.update(self._module_globals.keys())
    all_scan_for_mods = _ctx.stmts + (_ctx.imported_stmts if self.do_imports or self.link_imports else [])
    for _ctx._ms in all_scan_for_mods:
        if isinstance(_ctx._ms, ImportStmt):
            for _mn, _ctx._ in _import_targets(_ctx._ms):
                if _mn and (not _mn.startswith('_')):
                    all_modules_to_declare.add(_mn)
        elif isinstance(_ctx._ms, FromImportStmt):
            _mn = _ctx._ms.module
            if _mn and (not _mn.startswith('_')) and ('.' not in _mn):
                all_modules_to_declare.add(_mn)
    if self._current_filename:
        _ctx.parts.append(f'#line 1 "{self._current_filename}"')
    if self.emit_struct_defs and hasattr(self, 'struct_field_types') and self.struct_field_types:
        _ctx.parts.append('')
        emitted = set()
        max_iterations = len(self.struct_field_types) + 1
        iteration = 0
        while emitted != set(self.struct_field_types.keys()) and iteration < max_iterations:
            iteration += 1
            for _ctx.struct_name in sorted(self.struct_field_types.keys()):
                if _ctx.struct_name in emitted:
                    continue
                fields = self.struct_field_types[_ctx.struct_name]
                dependencies_met = True
                for field_type in fields.values():
                    base_type = re.sub('\\[\\d+\\]$', '', ('' + field_type).rstrip(' *'))
                    if base_type == _ctx.struct_name:
                        continue
                    if base_type in self.struct_field_types and base_type not in emitted:
                        dependencies_met = False
                        break
                if not dependencies_met:
                    continue
                _td_start = len(_ctx.parts)
                if _ctx.struct_name == 'Pointer':
                    _ctx.parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    _td_start = len(_ctx.parts)
                _ctx.parts.append(f'typedef struct {_ctx.struct_name} {{')
                _ctx.parts.append(f'  int64_t __mojo_type_id;')
                if fields:
                    for field_name, field_type in fields.items():
                        _ctx.ft = '' + field_type
                        if _ctx.ft == f'{_ctx.struct_name} *':
                            _ctx.ft = f'struct {_ctx.struct_name} *'
                        safe_fn = f'_kw_{field_name}' if field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS else field_name
                        _arr_dm = re.match('^(.+)\\[(\\d+)\\]$', _ctx.ft)
                        if _arr_dm:
                            _ctx.parts.append(f'  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];')
                        else:
                            _ctx.parts.append(f'  {_ctx.ft} {safe_fn};')
                else:
                    _ctx.parts.append(f'  int _dummy;')
                _ctx.parts.append(f'}} {_ctx.struct_name};')
                self._struct_typedef_texts[_ctx.struct_name] = '\n'.join(_ctx.parts[_td_start:])
                _ctx.parts.append(f'#define {_stub_guard_name(_ctx.struct_name)}')
                emitted.add(_ctx.struct_name)
                self._emitted_structs.add(_ctx.struct_name)
        _ctx.parts.append('')
    global _emitted_type_name_emitted
    if self._needs_type_name_table and (not _emitted_type_name_emitted):
        _emitted_type_name_emitted = True
        _ctx.parts.append('static char * _mojo_type_name (int64_t tag)')
        _ctx.parts.append('{')
        _type_name_set = set(self.struct_field_types)
        for _dspk in _STMT_DISPATCH.keys():
            _type_name_set.add('' + _dspk)
        for _dspk in _EXPR_DISPATCH.keys():
            _type_name_set.add('' + _dspk)
        for _ctx._tn in sorted(_type_name_set):
            _tn_s = '' + _ctx._tn
            _ctx.parts.append(f'  if (tag == {_struct_type_id(_tn_s)}) return "{_tn_s}";')
        _ctx.parts.append('  return "<type>";')
        _ctx.parts.append('}')
        _ctx.parts.append('')
    for mod_name in sorted(all_modules_to_declare):
        mod_s = '' + mod_name
        if mod_s == our_mod:
            continue
        mod_str = mod_s if mod_s else 'root'
        safe_mod = _c_field_name(mod_str) if mod_str else 'root'
        _ctx.struct_name = f'_{safe_mod}_toplev'
        global_var = f'_{safe_mod}_globals'
        _known_fields = self._module_globals.get(mod_str)
        if _known_fields:
            _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_mod}'
            _ctx.parts.append(f'#ifndef {_toplev_guard}')
            _ctx.parts.append(f'#define {_toplev_guard}')
            _ctx.parts.append(f'typedef struct {_ctx.struct_name} {{')
            for _kf_name, _kf_ctype, _ctx._ in _known_fields:
                _ctx.parts.append(f'  {_kf_ctype} {_c_field_name(_kf_name)};')
            _ctx.parts.append(f'}} {_ctx.struct_name};')
            _ctx.parts.append('#endif')
            _ctx.parts.append(f'extern struct {_ctx.struct_name} {global_var};')
        else:
            _ctx.parts.append(f'struct {_ctx.struct_name} __attribute__((incomplete));  /* extern module globals struct */')
            _ctx.parts.append(f'extern struct {_ctx.struct_name} {global_var};')
    for _decl in self._elaborated_externs:
        _ctx.parts.append(_decl)
    for _ecname in sorted(self._external_protos):
        if _ecname in self._LIBC_DECLARED and _ecname not in self._NEEDS_SELF_EXTERN:
            continue
        _eret, _eargs = self._external_protos[_ecname]
        _argstr = ', '.join(_eargs) if _eargs else 'void'
        _ctx.parts.append(f'extern {_eret} {_ecname} ({_argstr});')
    _module_globals_insert_idx = len(_ctx.parts)
    if _ctx.imported_code:
        _ctx.parts.append('')
        _ctx.parts.extend(_ctx.imported_code)
    new_helpers = self._ptr_helpers_needed - self._emitted_ptr_helpers
    for _ctx.et in sorted(new_helpers):
        _ctx.cn = _c_id(_ctx.et)
        _ctx.parts.append(f'static {_ctx.et} * _mojo_at_{_ctx.cn} ({_ctx.et} * p, int64_t n) {{ return p + n; }}')
        self._emitted_ptr_helpers.add(_ctx.et)
    if new_helpers:
        _ctx.parts.append('')
    global_decls = []
    current_mod_name = self.module_name or 'root'
    if current_mod_name not in self._module_globals:
        self._module_globals[current_mod_name] = []
        self._module_global_inits[current_mod_name] = {}
    _dispatch_dict_names = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS', '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
    _dispatch_set_names = {'_CMP_OPS'}
    _dispatch_names = _dispatch_dict_names | _dispatch_set_names
    _declared_globals = set()
    all_scan = _ctx.stmts
    for _ctx.stmt in all_scan:
        if isinstance(_ctx.stmt, FromImportStmt):
            for _ctx.alias in _ctx.stmt.names:
                orig_name = _ctx.alias[0]
                local_name = _ctx.alias[1] if len(_ctx.alias) > 1 and _ctx.alias[1] else orig_name
                for check_name in (orig_name, local_name):
                    if check_name in _dispatch_dict_names and check_name not in _declared_globals:
                        global_decls.append(f'MojoDict * {check_name};')
                        _declared_globals.add(check_name)
                        self._global_c_decl_types[check_name] = 'MojoDict *'
                        self._global_var_types[check_name] = 'MojoDict *'
                    elif check_name in _dispatch_set_names and check_name not in _declared_globals:
                        global_decls.append(f'MojoSet * {check_name};')
                        _declared_globals.add(check_name)
                        self._global_c_decl_types[check_name] = 'MojoSet *'
                        self._global_var_types[check_name] = 'MojoSet *'
        elif isinstance(_ctx.stmt, ImportStmt):
            for _ctx._tm, _ctx._ta in _import_targets(_ctx.stmt):
                local_name = _ctx._ta if _ctx._ta else _ctx._tm
                if local_name not in _declared_globals:
                    global_decls.append(f'int64_t {local_name};')
                    _declared_globals.add(local_name)
                    self._global_var_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name

    def _collect_global_stmts(stmt_list):
        _ctx.result = []
        for _gs in stmt_list:
            _ctx.result.append(_gs)
            if isinstance(_gs, TryStmt):
                _ctx.result.extend(_collect_global_stmts(_gs.body or []))
                for _ctx._h in _gs.handlers or []:
                    _ctx.result.extend(_collect_global_stmts(getattr(_ctx._h, 'body', []) or []))
                _ctx.result.extend(_collect_global_stmts(_gs.else_body or [] if isinstance(_gs.else_body, list) else []))
                _ctx.result.extend(_collect_global_stmts(_gs.finally_body or [] if isinstance(_gs.finally_body, list) else []))
            elif isinstance(_gs, IfStmt):
                _ctx.result.extend(_collect_global_stmts(_gs.then_body or []))
                _ctx.result.extend(_collect_global_stmts(_gs.else_body or []))
        return _ctx.result
    all_global_scan = _ctx.stmts

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
        declared, i.e. 'struct _X_toplev has no member named NAME'."""
        if isinstance(value, DictExpr):
            if gname in _dispatch_names:
                global_decls.append(f'MojoDict * {gname};')
                self._global_c_decl_types[gname] = 'MojoDict *'
            else:
                global_decls.append(f'int64_t {gname};  /* MojoDict * */')
                self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoDict *'
        elif isinstance(value, (ListExpr, TupleExpr)):
            if gname in _dispatch_names:
                global_decls.append(f'MojoList * {gname};')
                self._global_c_decl_types[gname] = 'MojoList *'
            else:
                global_decls.append(f'int64_t {gname};  /* MojoList * */')
                self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoList *'
        elif isinstance(value, SetExpr):
            if gname in _dispatch_names:
                global_decls.append(f'MojoSet * {gname};')
                self._global_c_decl_types[gname] = 'MojoSet *'
            else:
                global_decls.append(f'int64_t {gname};  /* MojoSet * */')
                self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoSet *'
        elif isinstance(value, (IntLiteral, BoolLiteral)):
            global_decls.append(f'int {gname};')
            self._global_var_types[gname] = 'int'
            self._global_c_decl_types[gname] = 'int'
        elif isinstance(value, StringLiteral):
            global_decls.append(f'char * {gname};')
            self._global_var_types[gname] = 'char *'
            self._global_c_decl_types[gname] = 'char *'
        elif isinstance(value, CallExpr):
            if isinstance(value.func, IdentExpr) and value.func.name in self.struct_field_types:
                _ctx.struct_name = value.func.name
                global_decls.append(f'{_ctx.struct_name} * {gname};')
                self._global_var_types[gname] = f'{_ctx.struct_name} *'
                self._global_c_decl_types[gname] = f'{_ctx.struct_name} *'
            elif isinstance(value.func, IdentExpr):
                _ctx.ret = self.func_return_types.get(value.func.name, '')
                if _ctx.ret.endswith(' *'):
                    global_decls.append(f'{_ctx.ret} {gname};')
                    self._global_var_types[gname] = _ctx.ret
                    self._global_c_decl_types[gname] = _ctx.ret
                elif _ctx.ret == 'char *':
                    global_decls.append(f'char * {gname};')
                    self._global_var_types[gname] = 'char *'
                    self._global_c_decl_types[gname] = 'char *'
                else:
                    global_decls.append(f'int64_t {gname};')
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(value.func, MemberExpr) and value.func.member in ('read', 'readline') and (not value.args):
                global_decls.append(f'char * {gname};')
                self._global_var_types[gname] = 'char *'
                self._global_c_decl_types[gname] = 'char *'
            elif isinstance(value.func, MemberExpr) and value.func.member == 'readlines':
                global_decls.append(f'int64_t {gname};  /* MojoList * */')
                self._global_var_types[gname] = 'MojoList *'
                self._global_c_decl_types[gname] = 'int64_t'
            else:
                global_decls.append(f'int64_t {gname};')
                self._global_var_types[gname] = 'int64_t'
                self._global_c_decl_types[gname] = 'int64_t'
        elif isinstance(value, MemberExpr) and isinstance(value.obj, IdentExpr) and (value.obj.name in self.imported_symbols) and self.imported_symbols[value.obj.name].get('module') and (value.member in self._global_var_types) and (getattr(self, '_global_to_module', {}).get(value.member) == self.imported_symbols[value.obj.name].get('module')):
            _ctx._mx_t = self._global_var_types[value.member]
            if _ctx._mx_t.endswith(' *'):
                global_decls.append(f'{_ctx._mx_t} {gname};')
                self._global_var_types[gname] = _ctx._mx_t
                self._global_c_decl_types[gname] = _ctx._mx_t
            elif _ctx._mx_t == '_Bool':
                global_decls.append(f'int {gname};')
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            else:
                global_decls.append(f'int64_t {gname};')
                self._global_var_types[gname] = 'int64_t'
                self._global_c_decl_types[gname] = 'int64_t'
        else:
            _ctx.qt = self._quick_type(value) or 'int64_t'
            if _ctx.qt.endswith(' *') or _ctx.qt == 'char *':
                global_decls.append(f'{_ctx.qt} {gname};')
                self._global_var_types[gname] = _ctx.qt
                self._global_c_decl_types[gname] = 'int64_t' if _ctx.qt in ('MojoDict *', 'MojoList *', 'MojoSet *') else _ctx.qt
            elif _ctx.qt == '_Bool':
                global_decls.append(f'int {gname};')
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            else:
                global_decls.append(f'int64_t {gname};')
                self._global_var_types[gname] = 'int64_t'
                self._global_c_decl_types[gname] = 'int64_t'
    for _ctx.stmt in _collect_global_stmts(all_global_scan):
        if isinstance(_ctx.stmt, VarDecl):
            gname = _ctx.stmt.name
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            if _ctx.stmt.type_ann and _ctx.stmt.value is None:
                _ctx._resolved = self._resolve_type(_ctx.stmt.type_ann)
                self._global_var_types[gname] = _ctx._resolved
                if _ctx._resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    global_decls.append(f'int64_t {gname};  /* {_ctx._resolved} */')
                    self._global_c_decl_types[gname] = 'int64_t'
                else:
                    global_decls.append(f'{_ctx._resolved} {gname};')
                    self._global_c_decl_types[gname] = _ctx._resolved
                continue
            _gv = _ctx.stmt.value
            if isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr) and (_gv.func.name in ('list', 'List', 'dict', 'Dict', 'set', 'Set')):
                _ctype = 'MojoDict *' if _gv.func.name in ('dict', 'Dict') else 'MojoSet *' if _gv.func.name in ('set', 'Set') else 'MojoList *'
                global_decls.append(f'int64_t {gname};  /* {_ctype} */')
                self._global_var_types[gname] = _ctype
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr):
                if _gv.func.name in self.struct_field_types:
                    _ctx._struct_name = _gv.func.name
                    global_decls.append(f'{_ctx._struct_name} * {gname};')
                    self._global_var_types[gname] = f'{_ctx._struct_name} *'
                    self._global_c_decl_types[gname] = f'{_ctx._struct_name} *'
                else:
                    _ret = self.func_return_types.get(_gv.func.name, '')
                    if _ret.endswith(' *'):
                        global_decls.append(f'{_ret} {gname};')
                        self._global_var_types[gname] = _ret
                        self._global_c_decl_types[gname] = _ret
                    elif _ret == 'char *':
                        global_decls.append(f'char * {gname};')
                        self._global_var_types[gname] = 'char *'
                        self._global_c_decl_types[gname] = 'char *'
                    else:
                        global_decls.append(f'int64_t {gname};')
                        self._global_var_types[gname] = 'int64_t'
                        self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, (IntLiteral, BoolLiteral)):
                global_decls.append(f'int {gname};')
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
            elif isinstance(_gv, StringLiteral):
                global_decls.append(f'char * {gname};')
                self._global_var_types[gname] = 'char *'
                self._global_c_decl_types[gname] = 'char *'
            elif isinstance(_gv, (ListExpr, TupleExpr)):
                global_decls.append(f'int64_t {gname};  /* MojoList * */')
                self._global_var_types[gname] = 'MojoList *'
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, DictExpr):
                global_decls.append(f'int64_t {gname};  /* MojoDict * */')
                self._global_var_types[gname] = 'MojoDict *'
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, SetExpr):
                global_decls.append(f'int64_t {gname};  /* MojoSet * */')
                self._global_var_types[gname] = 'MojoSet *'
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, IdentExpr) and _gv.name in self._global_var_types:
                global_decls.append(f'{self._global_var_types[_gv.name]} {gname};')
                self._global_c_decl_types[gname] = self._global_c_decl_types.get(_gv.name, self._global_var_types[_gv.name])
            else:
                global_decls.append(f'int {gname};')
                self._global_var_types[gname] = 'int'
                self._global_c_decl_types[gname] = 'int'
        elif isinstance(_ctx.stmt, AssignStmt) and isinstance(_ctx.stmt.target, IdentExpr):
            gname = _ctx.stmt.target.name
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            _gscan_declare_global(gname, _ctx.stmt.value)
        elif isinstance(_ctx.stmt, ComptimeVarStmt) and isinstance(_ctx.stmt.value, (ListExpr, TupleExpr)):
            gname = _ctx.stmt.target
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            _gscan_declare_global(gname, _ctx.stmt.value)
        elif isinstance(_ctx.stmt, MultiAssignStmt):
            for _ctx._tgt in _ctx.stmt.targets:
                if not isinstance(_ctx._tgt, IdentExpr):
                    continue
                gname = _ctx._tgt.name
                if gname in _declared_globals:
                    continue
                _declared_globals.add(gname)
                _gscan_declare_global(gname, _ctx.stmt.value)
        elif isinstance(_ctx.stmt, VarDecl) and _ctx.stmt.name not in _declared_globals:
            _declared_globals.add(_ctx.stmt.name)
            _ctx.ctype = self._resolve_type(_ctx.stmt.type_ann) if _ctx.stmt.type_ann else 'int64_t'
            global_decls.append(f'{_ctx.ctype} {_ctx.stmt.name};')
            self._global_var_types[_ctx.stmt.name] = _ctx.ctype
            self._global_c_decl_types[_ctx.stmt.name] = _ctx.ctype
        elif isinstance(_ctx.stmt, ImportStmt):
            for _ctx._tm, _ctx._ta in _import_targets(_ctx.stmt):
                local_name = _ctx._ta if _ctx._ta else _ctx._tm
                if local_name not in _declared_globals:
                    _declared_globals.add(local_name)
                    global_decls.append(f'int64_t {local_name};')
                    self._global_var_types[local_name] = 'int64_t'
                    self._global_c_decl_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name
    for gname in sorted(_declared_globals):
        if gname in self._global_var_types:
            _ctx.g_mtype = self._global_var_types[gname]
            if gname in self._global_c_decl_types:
                c_type = self._global_c_decl_types[gname]
            elif _ctx.g_mtype and _ctx.g_mtype.endswith(' *') and self._cpp_known_ptr_struct(_ctx.g_mtype):
                c_type = _ctx.g_mtype
            else:
                c_type = 'void *' if _ctx.g_mtype and _ctx.g_mtype.endswith(' *') else _ctx.g_mtype if _ctx.g_mtype and _ctx.g_mtype in ('MojoDict *', 'MojoList *', 'MojoSet *', 'char *') else 'int64_t'
            init_code = '0'
            for _ctx.stmt in _collect_global_stmts(all_global_scan):
                if isinstance(_ctx.stmt, AssignStmt) and isinstance(_ctx.stmt.target, IdentExpr) and (_ctx.stmt.target.name == gname):
                    init_code = _extract_init_expr(_ctx.stmt.value)
                    break
                elif isinstance(_ctx.stmt, MultiAssignStmt) and any((isinstance(_t, IdentExpr) and _t.name == gname for _t in _ctx.stmt.targets)):
                    init_code = _extract_init_expr(_ctx.stmt.value)
                    break
                elif isinstance(_ctx.stmt, ImportStmt) and gname in (_ctx._ta if _ctx._ta else _ctx._tm for _ctx._tm, _ctx._ta in _import_targets(_ctx.stmt)):
                    init_code = '0'
                    break
            if (gname, c_type, _ctx.g_mtype) not in self._module_globals[current_mod_name]:
                self._module_globals[current_mod_name].append((gname, c_type, _ctx.g_mtype))
                self._module_global_inits[current_mod_name][gname] = init_code
                self._global_to_module[gname] = current_mod_name
    if self._module_globals.get(current_mod_name):
        globals_list = self._module_globals[current_mod_name]
        current_mod_str = str(current_mod_name) if current_mod_name else 'root'
        safe_name = _c_field_name(current_mod_str) if current_mod_str else 'root'
        typedef_name = f'_{safe_name}_toplev'
        globals_struct_lines = []
        _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_name}'
        globals_struct_lines.append(f'#ifndef {_toplev_guard}')
        globals_struct_lines.append(f'#define {_toplev_guard}')
        globals_struct_lines.append(f'typedef struct {typedef_name} {{')
        for gname, c_type, _ctx._ in globals_list:
            globals_struct_lines.append(f'  {c_type} {_c_field_name(gname)};')
        globals_struct_lines.append(f'}} {typedef_name};')
        globals_struct_lines.append('#endif')
        globals_struct_lines.append('')
        instance_name = f'_{safe_name}_globals'
        globals_struct_lines.append(f'struct {typedef_name} {instance_name} = {{')
        inits = self._module_global_inits.get(current_mod_name, {})
        for gname, c_type, _ctx._ in globals_list:
            init_val = inits.get(gname)
            if not init_val or init_val == '0' or 'mojo_' in str(init_val) or ('new' in str(init_val)):
                if c_type.endswith(' *'):
                    init_val = f'({c_type})0'
                else:
                    init_val = '0'
            elif init_val.startswith('"') or init_val.startswith("'"):
                pass
            elif init_val.lstrip('-').isdigit():
                pass
            elif c_type.endswith(' *'):
                init_val = f'({c_type})0'
            else:
                init_val = '0'
            globals_struct_lines.append(f'  .{_c_field_name(gname)} = {init_val},')
        globals_struct_lines.append('};')
        globals_struct_lines.append('')
        for gname, c_type, _ctx._ in globals_list:
            _acc_sym = f'{safe_name}__mojo_global_get_{_c_field_name(gname)}'
            globals_struct_lines.append(f'{c_type} {_acc_sym} (void) {{ return {instance_name}.{_c_field_name(gname)}; }}')
        globals_struct_lines.append('')
        insert_idx = _module_globals_insert_idx
        if insert_idx is not None and insert_idx <= len(_ctx.parts):
            _ctx.parts[insert_idx:insert_idx] = globals_struct_lines
        else:
            _ctx.parts.extend(globals_struct_lines)
    class_attr_decls = []
    _ctx.class_attr_inits = []
    for _ctx.s in _ctx.all_struct_defs:
        if isinstance(_ctx.s, StructDef):
            class_attrs = self._class_attrs
            for _ctx.aname, _ctx.mangled in class_attrs.get(_ctx.s.name, {}).items():
                for _ctx.field in _ctx.s.fields:
                    if isinstance(_ctx.field, AssignStmt) and isinstance(_ctx.field.target, IdentExpr) and (_ctx.field.target.name == _ctx.aname):
                        _ctx.v = _ctx.field.value
                        _ctx.ctype = _class_attr_ctype(_ctx.v)
                        if _ctx.ctype == 'MojoSet *':
                            inits = [f'  {_ctx.mangled} = mojo_set_new();']
                            _set_elts = _ctx.v.elements if isinstance(_ctx.v, SetExpr) else []
                            for elt in _set_elts:
                                if isinstance(elt, StringLiteral):
                                    inits.append(f'  mojo_set_add_str ({_ctx.mangled}, "{_c_escape(elt.value)}");')
                                elif isinstance(elt, IntLiteral):
                                    inits.append(f'  mojo_set_add_int ({_ctx.mangled}, {elt.value});')
                            _ctx.class_attr_inits.extend(inits)
                        elif _ctx.ctype == 'MojoDict *':
                            _ctx.class_attr_inits.append(f'  {_ctx.mangled} = mojo_dict_new();')
                        elif _ctx.ctype == 'MojoList *':
                            _ctx.class_attr_inits.append(f'  {_ctx.mangled} = mojo_list_new();')
                        elif isinstance(_ctx.v, StringLiteral):
                            _ctx.ctype = 'char *'
                            _ctx.class_attr_inits.append(f'  {_ctx.mangled} = "{_c_escape(_ctx.v.value)}";')
                        elif isinstance(_ctx.v, IntLiteral):
                            _ctx.ctype = 'int64_t'
                            _ctx.class_attr_inits.append(f'  {_ctx.mangled} = {_ctx.v.value};')
                        else:
                            _ctx.ctype = 'int64_t'
                        class_attr_decls.append(f'{_ctx.ctype} {_ctx.mangled};')
                        self._global_var_types[_ctx.mangled] = _ctx.ctype
                        break
    if class_attr_decls:
        _ctx.parts.extend(class_attr_decls)
        _ctx.parts.append('')
    self._class_attr_inits = _ctx.class_attr_inits
    _funcattr_decls = []
    for _ctx._fn_name in sorted(self._func_attrs):
        for _attr in sorted(self._func_attrs[_ctx._fn_name]):
            _ctx._mangled = self._func_attrs[_ctx._fn_name][_attr]
            if _ctx._mangled in self._emitted_funcattr_decls:
                continue
            self._emitted_funcattr_decls.add(_ctx._mangled)
            _ctx._gtype = self._global_var_types.get(_ctx._mangled, 'int64_t')
            _funcattr_decls.append(f'static {_ctx._gtype} {_ctx._mangled};')
    if _funcattr_decls:
        _ctx.parts.extend(_funcattr_decls)
        _ctx.parts.append('')
    if self.emit_struct_defs:
        track_best = {}
        for _ctx.s in _ctx.stmts + self._imported_typedef_structs + (_ctx.imported_stmts if self.do_imports or self.link_imports else []):
            if isinstance(_ctx.s, StructDef):
                field_count = len([f for f in _ctx.s.fields if isinstance(f, VarDecl)])
                if _ctx.s.name not in track_best or field_count > track_best[_ctx.s.name][1]:
                    track_best[_ctx.s.name] = (_ctx.s, field_count)
        for sd, _ctx._ in track_best.values():
            if sd.name not in self._emitted_structs:
                _td_start = len(_ctx.parts)
                if sd.name == 'Pointer':
                    _ctx.parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    _td_start = len(_ctx.parts)
                _ctx.parts.append(f'typedef struct {sd.name} {{')
                _ctx.parts.append(f'  int64_t __mojo_type_id;')
                emitted_fields = set()
                for _ctx.field in sd.fields:
                    if isinstance(_ctx.field, VarDecl):
                        if sd.name in self.struct_field_types and _ctx.field.name in self.struct_field_types[sd.name]:
                            _ctx.ft = self.struct_field_types[sd.name][_ctx.field.name]
                        else:
                            _ctx.ft = self._resolve_type(_ctx.field.type_ann) if _ctx.field.type_ann else 'int'
                        safe_fn = f'_kw_{_ctx.field.name}' if _ctx.field.name in _C_KEYWORDS or _ctx.field.name in _C_PARAM_EXTRA_KEYWORDS else _ctx.field.name
                        _arr_dm = re.match('^(.+)\\[(\\d+)\\]$', _ctx.ft)
                        if _arr_dm:
                            _ctx.parts.append(f'  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];')
                        else:
                            _ctx.parts.append(f'  {_ctx.ft} {safe_fn};')
                        emitted_fields.add(_ctx.field.name)
                if sd.name in self.struct_field_types:
                    for field_name, field_type in self.struct_field_types[sd.name].items():
                        if field_name not in emitted_fields:
                            safe_fn = f'_kw_{field_name}' if field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS else field_name
                            _arr_dm2 = re.match('^(.+)\\[(\\d+)\\]$', field_type)
                            if _arr_dm2:
                                _ctx.parts.append(f'  {_arr_dm2.group(1)} {safe_fn}[{_arr_dm2.group(2)}];')
                            else:
                                _ctx.parts.append(f'  {field_type} {safe_fn};')
                _ctx.parts.append(f'}} {sd.name};')
                self._struct_typedef_texts[sd.name] = '\n'.join(_ctx.parts[_td_start:])
                _ctx.parts.append(f'#define {_stub_guard_name(sd.name)}')
                _ctx.parts.append('')
                self._emitted_structs.add(sd.name)
        for _ctx.inner_map in self._all_closures.values():
            for _ctx.ci in _ctx.inner_map.values():
                if _ctx.ci.env_struct and _ctx.ci.env_struct not in self._emitted_structs:
                    _ctx.parts.append(f'typedef struct {_ctx.ci.env_struct} {{')
                    for vname, _ctx.vtype in _ctx.ci.captures:
                        field_ctype = f'{_ctx.vtype} *' if vname in _ctx.ci.mut_names else _ctx.vtype
                        _ctx.parts.append(f'  {field_ctype} {_c_field_name(vname)};')
                    _ctx.parts.append(f'}} {_ctx.ci.env_struct};')
                    _ctx.parts.append('')
                    self._emitted_structs.add(_ctx.ci.env_struct)
        if self._dispatch_solver and self._dispatch_tables:
            for _ctx.callee_set, _ctx.dispatch_table in self._dispatch_tables.items():
                if _ctx.dispatch_table.name not in self._emitted_dispatch_typedefs:
                    typedef = _ctx.dispatch_table.emit_typedef()
                    if typedef:
                        _ctx.parts.append(typedef)
                        _ctx.parts.append('')
                        self._emitted_dispatch_typedefs.add(_ctx.dispatch_table.name)
    for sn in sorted(self._struct_allocs_needed):
        if sn in self._emitted_allocs:
            continue
        self._emitted_allocs.add(sn)
        alloc_name = f'_alloc_{sn}'
        if alloc_name not in self.func_return_types:
            self.func_return_types[alloc_name] = f'{sn} *'
        class_attrs = self._class_attrs.get(sn, {})
        field_map = self.struct_field_types.get(sn, {})
        attr_inits = ''.join((f'  _p->{_safe_field(_ctx.aname)} = {gname};\n' for _ctx.aname, gname in sorted(class_attrs.items()) if _ctx.aname in field_map and field_map[_ctx.aname] == self._global_var_types.get(gname, field_map[_ctx.aname])))
        _ctx.parts.append(f'static {sn} * __GIMPLE _alloc_{sn} (void)\n{{\n  {sn} * _p;\n  void * _vp;\n  int64_t _tag;\n\nbb_2:\n  _vp = calloc (1, sizeof({sn}));\n  _p = ({sn} *) _vp;\n  _tag = (int64_t){_struct_type_id(sn)};\n  _p->__mojo_type_id = _tag;\n{attr_inits}  return _p;\n}}')
        _ctx.parts.append('')
    if self.emit_struct_defs:
        reflect_structs = sorted(set(self.struct_field_types.keys()) & self._emitted_structs & self._struct_allocs_needed)
        refl_parts = []
        for sn in reflect_structs:
            fields = self.struct_field_types.get(sn, {})
            if not fields:
                continue
            get_lines = []
            set_lines = []
            name_lits = []
            asdict_lines = []
            for _ctx.fname, ftype in fields.items():
                if _ctx.fname == '__mojo_type_id':
                    continue
                safe_f = _safe_field(_ctx.fname)
                if re.match('^.+\\[\\d+\\]$', ftype):
                    name_lits.append(f'"{_ctx.fname}"')
                    continue
                if ftype.endswith(' *'):
                    get_lines.append(f'  if (strcmp(attr, "{_ctx.fname}") == 0) return (int64_t)(intptr_t)obj->{safe_f};')
                    set_lines.append(f'  if (strcmp(attr, "{_ctx.fname}") == 0) {{ obj->{safe_f} = ({ftype})(intptr_t)val; return; }}')
                    asdict_lines.append(f'  mojo_dict_set_int(_r, "{_ctx.fname}", (int64_t)(intptr_t)obj->{safe_f});')
                else:
                    get_lines.append(f'  if (strcmp(attr, "{_ctx.fname}") == 0) return (int64_t)obj->{safe_f};')
                    set_lines.append(f'  if (strcmp(attr, "{_ctx.fname}") == 0) {{ obj->{safe_f} = ({ftype})val; return; }}')
                    asdict_lines.append(f'  mojo_dict_set_int(_r, "{_ctx.fname}", (int64_t)obj->{safe_f});')
                name_lits.append(f'"{_ctx.fname}"')
            asdict_part = f'static MojoDict * _mojo_asdict_{sn} ({sn} *obj) {{\n  MojoDict *_r = mojo_dict_new();\n' + ''.join(asdict_lines) + f'\n  return _r;\n}}\n' if self._asdict_dispatch_needed else ''
            refl_parts.append(f'static int64_t _mojo_getattr_{sn} ({sn} *obj, char *attr) {{\n' + '\n'.join(get_lines) + f'\n  return mojo_obj_getattr((void *)obj, attr);\n}}\nstatic void _mojo_setattr_{sn} ({sn} *obj, char *attr, int64_t val) {{\n' + '\n'.join(set_lines) + f'\n  mojo_setattr((void *)obj, attr, val);\n}}\nstatic MojoList * _mojo_fieldnames_{sn} (void) {{\n  MojoList *_r = mojo_list_new();\n' + ''.join((f'  mojo_list_append_str(_r, {nl});\n' for nl in name_lits)) + f'  return _r;\n}}\n' + asdict_part)
        repr_fwd_decls = [f'static char * _mojo_repr_{sn} ({sn} *obj);' for sn in reflect_structs if self.struct_field_types.get(sn)]
        for sn in reflect_structs:
            fields = self.struct_field_types.get(sn, {})
            if not fields:
                continue
            boxed = self.struct_boxed_fields.get(sn, set())
            bool_fields = self.struct_bool_fields.get(sn, set())
            nullable_containers = self.struct_nullable_container_fields.get(sn, set())
            part_exprs = []
            for _ctx.fname, ftype in fields.items():
                if _ctx.fname == '__mojo_type_id':
                    continue
                safe_f = _safe_field(_ctx.fname)
                fref = f'obj->{safe_f}'
                if sn == 'IntLiteral' and _ctx.fname == 'value' and ('raw' in fields):
                    raw_fref = f"obj->{_safe_field('raw')}"
                    val_expr = f'(({raw_fref} && {raw_fref}[0]) ? mojo_int_literal_decimal({raw_fref}) : mojo_repr_int((int64_t){fref}))'
                elif _ctx.fname in bool_fields:
                    val_expr = f'({fref} ? "True" : "False")'
                elif _ctx.fname in boxed and ftype in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                    val_expr = f'_mojo_generic_elem_repr((int64_t){fref})'
                elif ftype == 'char *':
                    val_expr = f'({fref} ? mojo_repr_str({fref}) : "None")'
                elif ftype == '_Bool':
                    val_expr = f'({fref} ? "True" : "False")'
                elif ftype in ('double', 'float'):
                    val_expr = f'mojo_repr_float((double){fref})'
                elif ftype == 'MojoList *':
                    if self._field_elem_types.get(sn, {}).get(_ctx.fname) == 'double':
                        list_repr = f'mojo_repr_list_doubles({fref})'
                    else:
                        list_repr = f'_mojo_repr_list({fref})'
                    if _ctx.fname in nullable_containers:
                        val_expr = f'({fref} ? {list_repr} : "None")'
                    else:
                        val_expr = list_repr
                elif ftype == 'MojoDict *':
                    if _ctx.fname in nullable_containers:
                        val_expr = f'({fref} ? _mojo_repr_dict({fref}) : "None")'
                    else:
                        val_expr = f'_mojo_repr_dict({fref})'
                elif ftype in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t', 'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                    val_expr = f'mojo_repr_int((int64_t){fref})'
                elif ftype.endswith(' *'):
                    val_expr = f'({fref} ? _mojo_dispatch_repr((void *){fref}) : "None")'
                else:
                    val_expr = f'mojo_repr_int((int64_t){fref})'
                part_exprs.append(f'"{_ctx.fname}=", {val_expr}')
            cat_chain = f'strdup("{sn}(")'
            for _ctx.i, pe in enumerate(part_exprs):
                sep = ', ' if _ctx.i > 0 else ''
                if sep:
                    cat_chain = f'mojo_str_cat({cat_chain}, ", ")'
                name_lit, val_e = pe.split(', ', 1)
                cat_chain = f'mojo_str_cat({cat_chain}, {name_lit})'
                cat_chain = f'mojo_str_cat({cat_chain}, {val_e})'
            cat_chain = f'mojo_str_cat({cat_chain}, ")")'
            refl_parts.append(f'static char * _mojo_repr_{sn} ({sn} *obj) {{\n  if (!obj) return "None";\n  return {cat_chain};\n}}\n')
        _ctx.parts.append('static char * _mojo_dispatch_repr (void *);')
        _ctx.parts.append('static char * _mojo_repr_list (MojoList *);')
        _ctx.parts.append('static char * _mojo_repr_dict (MojoDict *);')
        _ctx.parts.append('static char * _mojo_generic_elem_repr (int64_t);')
        if repr_fwd_decls:
            _ctx.parts.append('/* Forward decls for generic repr() (mutual struct references) */')
            _ctx.parts.append('\n'.join(repr_fwd_decls))
            _ctx.parts.append('')
        if True:
            _ctx.parts.append('/* Generic reflection dispatch (getattr/setattr/dataclasses.fields/is_dataclass) */')
            _ctx.parts.extend(refl_parts)
            tag_cases_get = '\n'.join((f'  if (_tag == {_struct_type_id(sn)}) return _mojo_getattr_{sn}(({sn} *)obj, attr);' for sn in reflect_structs if self.struct_field_types.get(sn)))
            tag_cases_set = '\n'.join((f'  if (_tag == {_struct_type_id(sn)}) {{ _mojo_setattr_{sn}(({sn} *)obj, attr, val); return; }}' for sn in reflect_structs if self.struct_field_types.get(sn)))
            tag_cases_fields = '\n'.join((f'  if (_tag == {_struct_type_id(sn)}) return _mojo_fieldnames_{sn}();' for sn in reflect_structs if self.struct_field_types.get(sn)))
            tag_cases_asdict = '\n'.join((f'  if (_tag == {_struct_type_id(sn)}) return _mojo_asdict_{sn}(({sn} *)obj);' for sn in reflect_structs if self.struct_field_types.get(sn)))
            tag_set_literal = ', '.join((str(_struct_type_id(sn)) for sn in reflect_structs if self.struct_field_types.get(sn)))
            if len(tag_set_literal) == 0:
                tag_set_literal = '0'
            asdict_dispatch_part = 'static MojoDict * _mojo_dispatch_asdict (void *obj) {\n  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n' + f'{tag_cases_asdict}\n' + '  return mojo_dict_new();\n}\n' if self._asdict_dispatch_needed else ''
            _ctx.parts.append('static int64_t _mojo_dispatch_getattr (void *obj, char *attr) {\n  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n' + f'{tag_cases_get}\n' + '  return mojo_obj_getattr(obj, attr);\n}\nstatic void _mojo_dispatch_setattr (void *obj, char *attr, int64_t val) {\n  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n' + f'{tag_cases_set}\n' + '  mojo_setattr(obj, attr, val);\n}\nstatic MojoList * _mojo_dispatch_fields (void *obj) {\n  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n' + f'{tag_cases_fields}\n' + '  return mojo_list_new();\n}\n' + asdict_dispatch_part + 'static int _mojo_dispatch_is_dataclass (void *obj) {\n  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n' + f'  static const int64_t _known[] = {{{tag_set_literal}}};\n' + '  if (_tag == 0) return 0;\n  for (size_t _i = 0; _i < sizeof(_known)/sizeof(_known[0]); _i++)\n    if (_known[_i] == _tag) return 1;\n  return 0;\n}\n')
            tag_cases_repr = '\n'.join((f'  if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)obj);' for sn in reflect_structs if self.struct_field_types.get(sn)))
            tag_cases_repr_elem = '\n'.join((f'    if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)(intptr_t)val);' for sn in reflect_structs if self.struct_field_types.get(sn)))
            _ctx.parts.append('static char * _mojo_dispatch_repr (void *obj) {\n  if (!obj) return "None";\n  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n' + f'{tag_cases_repr}\n' + '  return mojo_repr_obj((int64_t)(intptr_t)obj);\n}\nstatic char * _mojo_generic_elem_repr (int64_t val) {\n  if (val == 0) return "None";\n  if (val > 65536) {\n    if (mojo_is_registered_list(val))\n      return _mojo_repr_list((MojoList *)(intptr_t)val);\n    if (mojo_is_registered_dict(val))\n      return _mojo_repr_dict((MojoDict *)(intptr_t)val);\n    int64_t _tag = mojo_read_type_tag_safe(val);\n' + f'{tag_cases_repr_elem}\n' + '    return mojo_repr_str((char *)(intptr_t)val);\n  }\n  return mojo_repr_int(val);\n}\nstatic char * _mojo_repr_list (MojoList *lst) {\n  int _is_tup = lst && mojo_is_tuple(lst);\n  if (!lst) return _is_tup ? "()" : "[]";\n  int64_t _n = mojo_list_len(lst);\n  char *_buf = strdup(_is_tup ? "(" : "[");\n  for (int64_t _i = 0; _i < _n; _i++) {\n    if (_i > 0) _buf = mojo_str_cat(_buf, ", ");\n    _buf = mojo_str_cat(_buf, _mojo_generic_elem_repr(mojo_list_get_int(lst, _i)));\n  }\n  if (_is_tup && _n == 1) _buf = mojo_str_cat(_buf, ",");\n  return mojo_str_cat(_buf, _is_tup ? ")" : "]");\n}\nstatic char * _mojo_repr_dict (MojoDict *d) {\n  if (!d) return "{}";\n  int _is_booldict = mojo_is_bool_dict(d);\n  char *_buf = strdup("{");\n  int64_t *_order = mojo_dict_order_indices(d);\n  for (int64_t _oi = 0; _oi < d->used; _oi++) {\n    int64_t _i = _order[_oi];\n    if (_oi > 0) _buf = mojo_str_cat(_buf, ", ");\n    _buf = mojo_str_cat(_buf, mojo_repr_str(d->slots[_i].key));\n    _buf = mojo_str_cat(_buf, ": ");\n    if (_is_booldict)\n      _buf = mojo_str_cat(_buf, d->slots[_i].val ? "True" : "False");\n    else\n      _buf = mojo_str_cat(_buf, _mojo_generic_elem_repr(d->slots[_i].val));\n  }\n  free(_order);\n  return mojo_str_cat(_buf, "}");\n}\n')
            _ctx.parts.append('')
    if self.emit_struct_defs:
        _ctx.parts.append('static void _mojo_classattr_init (void);')
        _ctx.parts.append('')
    hardcoded = {'mojo_print', 'gimple_codegen_compile_to_gimple', 'compile_to_gimple', 'int_write', 'int_parse_module', 'py_tokenize', 'Parser', 'Interpreter'}
    if self.do_imports or self.link_imports:
        inline_defined = set()
        for _ctx.stmt in _ctx.imported_stmts or []:
            if isinstance(_ctx.stmt, FunctionDef):
                inline_defined.add(_ctx.stmt.name)
            elif isinstance(_ctx.stmt, StructDef):
                for _ctx.m in _ctx.stmt.methods:
                    inline_defined.add(f'{_ctx.stmt.name}_{_ctx.m.name}')
                    inline_defined.add(_ctx.m.name)
    else:
        inline_defined = set()
    _stub_only_modules = {'jit.arm64', 'jit'}
    for _ctx.sym_name in sorted(self.imported_symbols.keys()):
        if _ctx.sym_name in hardcoded:
            continue
        _ctx.sym_info = self.imported_symbols[_ctx.sym_name]
        if _ctx.sym_info.get('return_type') == 'unknown':
            continue
        if _ctx.sym_name in inline_defined or _ctx.sym_name in self._global_inline_defs:
            continue
        if _ctx.sym_name in self.struct_field_types:
            continue
        if _ctx.sym_name in self._LIBC_DECLARED and _ctx.sym_name not in _C_RESERVED_FUNCS:
            continue
        _ctx.module = _ctx.sym_info.get('module', '')
        if _ctx.module in _stub_only_modules:
            cname = _safe_name(_ctx.sym_name)
            if cname in _emitted_unresolved_stub_syms:
                continue
            _emitted_unresolved_stub_syms.add(cname)
            _ctx.ret_type = _ctx.sym_info.get('return_type', 'int64_t')
            _ctx.ret_type = self._resolve_type(_ctx.ret_type) if _ctx.ret_type and _ctx.ret_type != 'unknown' else 'int'
            if _ctx.ret_type == 'void':
                _ctx.body = f'{{ mojo_print ((char *)"{_ctx.sym_name}: unavailable in compiled mode"); }}'
            else:
                _ctx.body = f'{{ mojo_print ((char *)"{_ctx.sym_name}: unavailable in compiled mode"); return ({_ctx.ret_type})0; }}'
            _stub_only_guard = _stub_guard_name(cname)
            _ctx.parts.append(f'#ifndef {_stub_only_guard}\n#define {_stub_only_guard}\n{_ctx.ret_type} {cname} () {_ctx.body}  /* stub from {_ctx.module} */\n#endif')
            continue
        safe = self._func_csym(_ctx.sym_name)
        if 'signature' in _ctx.sym_info:
            if _ctx.sym_name in _C_RESERVED_FUNCS:
                _ctx.ret_type = _ctx.sym_info.get('c_return_type') or _ctx.sym_info.get('return_type', 'int64_t')
                if _ctx.ret_type and _ctx.ret_type != 'unknown' and (not any((c in _ctx.ret_type for c in ('*', ' ', 'int', 'char', 'void', 'float', 'double')))):
                    _ctx.ret_type = self._resolve_type(_ctx.ret_type)
                elif not _ctx.ret_type or _ctx.ret_type == 'unknown':
                    _ctx.ret_type = 'int64_t'
                _ctx.parts.append(f'#ifndef {safe}\nextern {_ctx.ret_type} {safe} (...);  /* from {_ctx.module} */\n#endif')
            else:
                signature = _ctx.sym_info['signature']
                orig_name = _ctx.sym_info.get('original_name', _ctx.sym_name)
                if safe != orig_name:
                    signature = re.sub('\\b' + re.escape(orig_name) + '\\b', safe, signature, count=1)
                signature = re.sub('\\b(inout|borrowed|owned|borrow|out|mut|ref|read|copy|var)\\s+(?=\\w)', '', signature)
                for _ckw in ('default', 'register', 'auto', 'static', 'extern', 'volatile', 'inline'):
                    signature = re.sub('\\b' + _ckw + '\\b(?=\\s*[,)])', f'_kw_{_ckw}', signature)
                _ctx.parts.append(f'#ifndef {safe}\nextern {signature};  /* from {_ctx.module} */\n#endif')
        else:
            _ctx.ret_type = _ctx.sym_info.get('return_type', 'int64_t')
            _ctx.ret_type = self._resolve_type(_ctx.ret_type) if _ctx.ret_type != 'unknown' else 'int'
            if self.do_imports or self.link_imports:
                if safe in _emitted_unresolved_stub_syms:
                    continue
                _emitted_unresolved_stub_syms.add(safe)
                if _ctx.ret_type == 'void':
                    _ctx.body = f'{{ mojo_print ((char *)"{_ctx.sym_name}: unavailable in compiled mode"); }}'
                else:
                    _ctx.body = f'{{ mojo_print ((char *)"{_ctx.sym_name}: unavailable in compiled mode"); return ({_ctx.ret_type})0; }}'
                _unresolved_guard = _stub_guard_name(safe)
                _ctx.parts.append(f'#ifndef {_unresolved_guard}\n#define {_unresolved_guard}\n__attribute__((weak)) {_ctx.ret_type} {safe} (...) {_ctx.body}  /* stub from {_ctx.module} */\n#endif')
            else:
                _ctx.parts.append(f'#ifndef {safe}\nextern {_ctx.ret_type} {safe} (...);  /* from {_ctx.module} */\n#endif')
    if self.imported_symbols:
        _ctx.parts.append('')
    _ctx.func_defs = [_ctx.s for _ctx.s in _ctx.stmts if isinstance(_ctx.s, FunctionDef)]
    if self._supported_generators or self._generator_method_api:
        _ctx.parts.append('typedef struct MojoGenerator MojoGenerator;')
        for _api in list(self._generator_api.values()) + list(self._generator_method_api.values()):
            _base, _vct = (_api['base'], _api['value_ctype'])
            _gptypes = ', '.join(_api.get('params') or []) or 'void'
            _ctx.parts.append(f'extern MojoGenerator *{_base}_start ({_gptypes});')
            _ctx.parts.append(f'extern _Bool {_base}_resume (MojoGenerator *);')
            _ctx.parts.append(f'extern {_vct} {_base}_value (MojoGenerator *);')
            _ctx.parts.append(f'extern void {_base}_destroy (MojoGenerator *);')
        _ctx.parts.append('')
    _needs_async_runtime_h = bool(len(self._supported_async) or len(self._supported_async_closures) or len(self._nested_async_api) or len(self._funcptr_builtins_needed & {'mojo_coro_resume_generic', 'mojo_coro_destroy_generic'}))
    if _needs_async_runtime_h and (not (self._supported_async or self._supported_async_closures or self._nested_async_api)):
        _ctx.parts.append('typedef struct MojoAsync MojoAsync;')
        _ctx.parts.append('#include <mojo_async_runtime.h>')
        _ctx.parts.append('')
    if self._supported_async or self._supported_async_closures or self._nested_async_api:
        _ctx.parts.append('typedef struct MojoAsync MojoAsync;')
        _ctx.parts.append('#include <mojo_async_runtime.h>')
        for _api in list(self._async_api.values()) + list(self._nested_async_api.values()):
            _base, _vct = (_api['base'], _api['value_ctype'])
            _aptypes = ', '.join(_api.get('params') or []) or 'void'
            _ctx.parts.append(f'extern MojoAsync *{_base}_start ({_aptypes});')
            _ctx.parts.append(f'extern _Bool {_base}_is_done (MojoAsync *);')
            _ctx.parts.append(f'extern {_vct} {_base}_value (MojoAsync *);')
            _ctx.parts.append(f'extern void {_base}_destroy (MojoAsync *);')
            _ctx.parts.append(f'extern void {_base}_translate_pending_exc (MojoAsync *);')
        for _api in self._async_closure_api.values():
            _base, _vct = (_api['base'], _api['value_ctype'])
            _aptypes = ', '.join(_api.get('params') or []) or 'void'
            _ctx.parts.append(f'extern MojoAsync *{_base}_start ({_aptypes});')
            _ctx.parts.append(f'extern _Bool {_base}_is_done (MojoAsync *);')
            _ctx.parts.append(f'extern {_vct} {_base}_value (MojoAsync *);')
            _ctx.parts.append(f'extern void {_base}_destroy (MojoAsync *);')
            _ctx.parts.append(f'extern void {_base}_translate_pending_exc (MojoAsync *);')
        _ctx.parts.append('')
    for _ctx.fn in _ctx.func_defs:
        if _ctx.fn.name == 'main':
            continue
        if _ctx.fn.name in self._supported_generators or _ctx.fn.name in self._supported_async or _ctx.fn.name in self._supported_async_gen:
            continue
        if _ctx.fn.name in self._unsupported_generator_names:
            continue
        _ctx.ret = self.func_return_types.get(_ctx.fn.name, 'int64_t')
        has_varargs = any((_ctx.pn.startswith('*') for _ctx.pn, _ctx._ in _ctx.fn.params or []))
        if has_varargs:
            _ctx.param_ctypes = self._signature_ctypes(_ctx.fn.params, _ctx.fn, sentinel='MojoList *')
            self.func_param_types[_ctx.fn.name] = self._signature_ctypes(_ctx.fn.params, _ctx.fn)
            self._note_vararg_trailing_param_types(_ctx.fn)
        else:
            _ctx.param_ctypes = []
            _ctx.inferred_params = self._inferred_param_types.get(_ctx.fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
            for _ctx.pn, _ctx.pt in _ctx.fn.params or []:
                if _ctx.pn in _ctx.inferred_params:
                    _ctx.param_ctypes.append(_ctx.inferred_params[_ctx.pn])
                else:
                    _ctx.param_ctypes.append(self._param_ctype(_ctx.pn, _ctx.pt, _ctx.fn))
            self.func_param_types[_ctx.fn.name] = _ctx.param_ctypes
        _ctx.ptypes = ', '.join(_ctx.param_ctypes) if _ctx.param_ctypes else 'void'
        _c_fn_name = self._func_csym(_ctx.fn.name)
        _guard_name = _c_fn_name if _ctx.fn.name in _C_RESERVED_FUNCS else _ctx.fn.name
        stub_guard = _stub_guard_name(_guard_name)
        _ctx.parts.append(f'#ifndef {stub_guard}')
        _ctx.parts.append(f'{_ctx.ret} {_c_fn_name} ({_ctx.ptypes});')
        _ctx.parts.append('#endif')
    struct_defs = [_ctx.s for _ctx.s in _ctx.stmts if isinstance(_ctx.s, StructDef)]
    if not self.do_imports:
        struct_defs += [_ctx.s for _ctx.s in _ctx.imported_stmts or [] if isinstance(_ctx.s, StructDef)]
    for sd in struct_defs:
        _ctx._moids = self._struct_method_overload_ids(sd)
        method_ids = {id(_ctx.m): oid for _ctx.m, oid in zip(sd.methods, _ctx._moids)}
        for _ctx.m in sd.methods:
            if (sd.name, _ctx.m.name) in self._supported_generator_methods:
                continue
            overload_suffix = method_ids.get(id(_ctx.m), '')
            mangled_name = self._struct_method_csym(sd.name, _ctx.m.name, overload_suffix)
            _ctx.ret = self.func_return_types.get(f'{sd.name}_{_ctx.m.name}{overload_suffix}') or self.func_return_types.get(f'{sd.name}_{_ctx.m.name}') or self._resolve_type(_ctx.m.return_type)
            _ctx.method_full_name = f'{sd.name}_{_ctx.m.name}'
            per_overload_params = self.func_param_types.get(mangled_name)
            if per_overload_params is not None:
                _ctx.param_ctypes = per_overload_params
            elif any((_ctx.pn.startswith('*') for _ctx.pn, _ctx._ in _ctx.m.params or [])):
                _ctx.param_ctypes = self._signature_ctypes(_ctx.m.params, _ctx.m, sd.name, sentinel='MojoList *')
                self.func_param_types[_ctx.method_full_name] = self._signature_ctypes(_ctx.m.params, _ctx.m, sd.name)
            else:
                _ctx.param_ctypes = []
                for _ctx.i, (_ctx.pname, _ctx.ptype) in enumerate(_ctx.m.params):
                    if _ctx.pname.startswith('**'):
                        continue
                    if _ctx.pname == 'self':
                        ct = f'{sd.name} *'
                    elif _ctx.ptype is None and hasattr(self, '_inferred_param_types'):
                        if _ctx.method_full_name in self._inferred_param_types and _ctx.pname in self._inferred_param_types[_ctx.method_full_name]:
                            ct = self._inferred_param_types[_ctx.method_full_name][_ctx.pname]
                        else:
                            ct = 'int64_t'
                    else:
                        ct = self._resolve_type(_ctx.ptype)
                    _ctx.param_ctypes.append(ct)
            _ctx.ptypes = ', '.join(_ctx.param_ctypes) if _ctx.param_ctypes else 'void'
            _ctx.parts.append(f'{_ctx.ret} {mangled_name} ({_ctx.ptypes});')
        _emitted_base: set[str] = set()
        for _ctx.m in sd.methods:
            if method_ids.get(id(_ctx.m), ''):
                base_cname = self._struct_method_csym(sd.name, _ctx.m.name, '')
                if base_cname not in _emitted_base:
                    base_ret = self.func_return_types.get(f'{sd.name}_{_ctx.m.name}') or self._resolve_type(_ctx.m.return_type)
                    _ctx.parts.append(f'{base_ret} {base_cname} (...);')
                    _emitted_base.add(base_cname)
    if _ctx.func_defs or struct_defs:
        _ctx.parts.append('')
    if _ctx._is_selfhost_file:
        _ctx.parts.append('MojoList * Parser_parse_module (Parser *);')
        _ctx.parts.append('void Parser___init__ (Parser *, MojoList *);')
        _ctx.parts.append('void Interpreter___init__ (Interpreter *, char *, MojoList *);')
        _ctx.parts.append('int64_t Interpreter_execute (Interpreter *, int64_t);')
        _ctx.parts.append('_Bool jit_compile_and_execute (char *, char *, int64_t, int64_t, int64_t);  /* from mojo.py */')
    _ctx.parts.append('static int64_t _mojo_dispatch_getattr (void *, char *);')
    _ctx.parts.append('static void _mojo_dispatch_setattr (void *, char *, int64_t);')
    _ctx.parts.append('static MojoList * _mojo_dispatch_fields (void *);')
    if self._asdict_dispatch_needed:
        _ctx.parts.append('static MojoDict * _mojo_dispatch_asdict (void *);')
    _ctx.parts.append('static int _mojo_dispatch_is_dataclass (void *);')
    _ctx.parts.append('static char * _mojo_dispatch_repr (void *);')
    _ctx.parts.append('static char * _mojo_repr_list (MojoList *);')
    _ctx.parts.append('static char * _mojo_repr_dict (MojoDict *);')
    _ctx.parts.append('static char * _mojo_generic_elem_repr (int64_t);')
    if _emitted_type_name_emitted:
        _ctx.parts.append('static char * _mojo_type_name (int64_t);')
    _ctx.parts.append('')
    if not self.emit_struct_defs:
        for _ctx.inner_map in self._all_closures.values():
            for _ctx.ci in _ctx.inner_map.values():
                if _ctx.ci.env_struct and _ctx.ci.env_struct not in self._emitted_structs:
                    _ctx.parts.append(f'typedef struct {_ctx.ci.env_struct} {{')
                    for vname, _ctx.vtype in _ctx.ci.captures:
                        field_ctype = f'{_ctx.vtype} *' if vname in _ctx.ci.mut_names else _ctx.vtype
                        _ctx.parts.append(f'  {field_ctype} {_c_field_name(vname)};')
                    _ctx.parts.append(f'}} {_ctx.ci.env_struct};')
                    _ctx.parts.append('')
                    self._emitted_structs.add(_ctx.ci.env_struct)

def _gm_tail_emit(self, _ctx):
    from gimple_codegen import _CPP_KEYWORD_FIELDS, _c_field_name, _safe_name
    for _ctx.outer_name, _ctx.inner_map in self._all_closures.items():
        for inner_name, _ctx.ci in _ctx.inner_map.items():
            if _ctx.ci.env_struct:
                _ctx.alloc_fn = f'_alloc_{_ctx.ci.env_struct}'
                _ctx.parts.append(f'{_ctx.ci.env_struct} * {_ctx.alloc_fn} (void);')
            _ctx.ret = _ctx.ci.inferred_ret if _ctx.ci.inferred_ret else self.func_return_types.get(_ctx.ci.lifted_name, 'int64_t')
            if _ctx.ci.is_re_sub_callback:
                _ctx.ret = 'char *'
            _ctx.node = _ctx.ci.inner_def
            ptypes_list = []
            if _ctx.ci.env_struct:
                ptypes_list.append(f'{_ctx.ci.env_struct} *')
            for _ctx.i, (_ctx.pn, _ctx.pt) in enumerate(_ctx.node.params):
                if _ctx.ci.is_re_sub_callback and _ctx.i == 0:
                    ptypes_list.append('char *')
                elif _ctx.pn in _ctx.ci.inferred_params:
                    ptypes_list.append(_ctx.ci.inferred_params[_ctx.pn])
                else:
                    ptypes_list.append(self._param_ctype(_ctx.pn, _ctx.pt, _ctx.node))
            _ctx.ptypes = ', '.join(ptypes_list) if ptypes_list else 'void'
            _ctx.parts.append(f'{_ctx.ret} {_ctx.ci.lifted_name} ({_ctx.ptypes});')
            if _ctx.ci.is_re_sub_callback:
                static_name = f'_mojo_cb_{_ctx.ci.lifted_name}'
                _ctx.parts.append(f'static void * {static_name} = (void *){_ctx.ci.lifted_name};')
    if self._all_closures:
        _ctx.parts.append('')
    if self._funcptr_builtins_needed:
        _new_names = sorted(self._funcptr_builtins_needed - self._emitted_funcptr_builtins)
        if _new_names:
            for c_name in _new_names:
                if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
                    _ctx.parts.append(f'static void * _funcptr_{c_name} = (void *){c_name};')
                self._emitted_funcptr_builtins.add(c_name)
            _ctx.parts.append('')
    if self.emit_struct_defs and self._dispatch_solver and self._dispatch_tables:
        _ctx.parts.append('/* Dispatch table initializations (virtual method tables) */')
        for _ctx.callee_set, _ctx.dispatch_table in self._dispatch_tables.items():
            if _ctx.dispatch_table.name not in self._emitted_dispatch_tables:
                table_init = _ctx.dispatch_table.emit_table_init()
                if table_init:
                    _ctx.parts.append(table_init)
                    self._emitted_dispatch_tables.add(_ctx.dispatch_table.name)
        _ctx.parts.append('')
    str_pool: dict = {}
    for _ctx.attr in dir(self):
        pass
    if hasattr(self, '_str_pool') and self._str_pool:
        _ctx.parts.append('/* String literal globals — array form so address is a compile-time r-value (required by GIMPLE strict mode) */')
        if self.emit_str_pool:
            for _ctx.escaped, _ctx.sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                _ctx.parts.append(f'static char * {_ctx.sname} = "{_ctx.escaped}";')
        else:
            for _ctx.escaped, _ctx.sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                _ctx.parts.append(f'static char * {_ctx.sname};')
        _ctx.parts.append('')
    _regex_new = {p: _ctx.i for p, _ctx.i in self._regex_progs.items() if p not in self._regex_progs_defined}
    if _regex_new:
        _ctx.parts.append('/* Compile-time-compiled regex programs (finditer support) */')
        for _ctx.pattern, _ctx.info in _regex_new.items():
            _ctx.parts.append(_ctx.info['decls'])
            self._regex_progs_defined.add(_ctx.pattern)
        _ctx.parts.append('')
    _ctx.parts.extend(_ctx.func_parts)
    if self.emit_struct_defs:
        _ctx.class_attr_inits = getattr(self, '_class_attr_inits', [])
        _ctx.parts.append('static void _mojo_classattr_init (void)')
        _ctx.parts.append('{')
        if _ctx.class_attr_inits:
            _ctx.parts.extend(_ctx.class_attr_inits)
        _ctx.parts.append('}')
        _ctx.parts.append('')
    if self._generator_cpp_units:
        cpp_parts = ['/* Generated by gimple_codegen.py (Milestone B: C++20-coroutine', "   translation of this module's supported generator function(s);", '   Milestone C step 2 added `yield from`-delegation support;', '   Milestone C step 3 added generator METHODS on structs;', '   Milestone D added try/except/raise support;', '   Step B (async/await project) added compiled `async def`', '   functions -- a separate promise_type/extern "C" API from the', '   generator one above, deliberately not sharing a promise shape', "   -- see GimpleGen._gen_cpp_async_unit's docstring) */", '#include <coroutine>', '#include <cstdint>', '#include <cstdio>', '#include <cmath>', '#include <exception>', '#include <functional>', '#include <vector>', '#include <algorithm>', '#include <mojo_runtime.h>', '', 'extern "C" { typedef struct MojoGenerator MojoGenerator; }', 'extern "C" { typedef struct MojoAsync MojoAsync; }', '', '/* Milestone D: RAII `finally:` translation (see', '   GimpleGen._cpp_try_stmt) -- runs an arbitrary capturing', '   lambda from its destructor, so it fires on every way its', '   enclosing scope can be exited (normal fallthrough, break/', '   continue, co_return, an exception unwinding through/past it,', '   or -- same C++20 coroutine-frame-destruction rule as', '   `_mojogen_sub_guard` below -- this coroutine being destroyed', '   early while suspended inside the guarded scope). A capturing', "   lambda (not a local class) specifically: a local class's own", '   member functions have NO implicit access to the enclosing', "   function's locals, so a finally body referencing an outer", "   variable wouldn't compile with that approach. */", 'struct _MojoScopeExit {', '    std::function<void()> fn;', '    explicit _MojoScopeExit(std::function<void()> f) : fn(std::move(f)) {}', '    ~_MojoScopeExit() { fn(); }', '};', '', '/* Milestone D: a Mojo exception thrown as a real C++ exception,', "   confined to this coroutine's own .cpp translation unit (see", '   GimpleGen._cpp_raise_stmt/_cpp_try_stmt). Carries exactly the', '   same tri-part representation the ordinary (non-generator) GIMPLE', '   path already uses for its mojo_exc_type/msg/obj globals (see', '   mojo_runtime.h) -- reused, not reinvented, so the extern "C"', '   `_resume` boundary below can translate one directly into the', '   other with no lossy conversion. */', 'struct _MojoCppExc {', '    int64_t type_id;', '    char *msg;', '    void *obj;', '};', '', '/* RAII guard for a sub-generator a `yield from` delegates to (see', "   GimpleGen._cpp_yield_from) -- guarantees the sub-generator's own", '   `_destroy` runs exactly once, whether this scope exits because the', '   sub-generator was exhausted normally or because the OUTER coroutine', '   holding it is itself destroyed early (e.g. a consumer `break`s out', "   of the loop that's driving it): C++20 destroys every local object", "   in scope at a coroutine's suspension point when that coroutine's", '   frame is destroyed, exactly as if the enclosing block unwound', '   normally, so this destructor fires correctly in both cases with no', '   special-case code at either call site. Emitted unconditionally', '   whenever this module has ANY compiled generator -- harmless and', '   unused if none of them actually use `yield from`. */', 'struct _mojogen_sub_guard {', '    MojoGenerator *g;', '    void (*destroy_fn)(MojoGenerator *);', '    ~_mojogen_sub_guard() { if (g) destroy_fn(g); }', '};', '']
        if self._supported_async or self._supported_async_gen or self._supported_async_closures or self._nested_async_api:
            cpp_parts.append('#include <mojo_async_runtime.h>')
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
        if self._supported_generator_methods or self._cpp_param_struct_names or self._cpp_ctor_struct_names or self._cpp_value_struct_names:
            cpp_parts.append("/* Struct layout(s) needed by this module's")
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
                        if _gm_fld_sn in self.struct_field_types and _gm_fld_sn not in _gm_struct_names_seen:
                            _gm_struct_names_seen.append(_gm_fld_sn)
                            _gm_frontier.append(_gm_fld_sn)
            for _gm_fwd_sn in sorted(_gm_struct_names_seen):
                if _gm_fwd_sn in self._struct_typedef_texts:
                    cpp_parts.append(f'struct {_gm_fwd_sn};')
            if any((_fwd in self._struct_typedef_texts for _fwd in _gm_struct_names_seen)):
                cpp_parts.append('')
            for _gm_method_struct_name in sorted(_gm_struct_names_seen):
                _td = self._struct_typedef_texts.get(_gm_method_struct_name)
                if _td:
                    cpp_parts.append(_td.replace('_Bool', 'bool'))
                    cpp_parts.append('')
        if self._cpp_module_global_refs or self._cpp_module_func_refs:
            cpp_parts.append('/* Extern declarations for module-level symbols')
            cpp_parts.append("   referenced by this module's compiled generator")
            cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
            _mref_modules: list = []
            for _mref_pair in self._cpp_module_global_refs:
                _mref_mod = _mref_pair[0]
                if _mref_mod not in _mref_modules:
                    _mref_modules.append(_mref_mod)
            for _mref_safe_mod in sorted(_mref_modules):
                _mt = f'_{_mref_safe_mod}_toplev'
                _mg = f'_{_mref_safe_mod}_globals'
                cpp_parts.append(f'typedef struct {_mt} {{')
                for _gl in self._module_globals.get('root' if _mref_safe_mod == 'root' else _mref_safe_mod, []):
                    _gct = _gl[1].replace('_Bool', 'bool')
                    _gfname = _c_field_name(_gl[0])
                    if _gfname in _CPP_KEYWORD_FIELDS:
                        _gfname = f'_kw_{_gfname}'
                    cpp_parts.append(f'  {_gct} {_gfname};')
                cpp_parts.append(f'}} {_mt};')
                cpp_parts.append(f'extern struct {_mt} {_mg};')
            for _fname in sorted(self._cpp_module_func_refs):
                try:
                    _fsym = self._func_csym(_fname)
                    _fret = self.func_return_types.get(_fname, 'int64_t')
                    _fparams = self.func_param_types.get(_fname, [])
                    _fret_cpp = _fret.replace('_Bool', 'bool')
                    _fparam_str = ', '.join((p if p not in ('_Bool',) else 'bool' for p in _fparams))
                    cpp_parts.append(f'extern "C" {_fret_cpp} {_fsym} ({_fparam_str});')
                except Exception:
                    continue
            for _vfn in sorted(self._cpp_module_variadic_func_refs):
                cpp_parts.append(f'extern "C" int64_t {_vfn} (...);')
            cpp_parts.append('')
        if self._cpp_class_attr_refs:
            cpp_parts.append('/* Extern declarations for class-level')
            cpp_parts.append('   attribute globals (`cls.<attr>`) read by this')
            cpp_parts.append("   module's compiled generator bodies. */")
            for _cattr_gname in sorted(self._cpp_class_attr_refs):
                _cattr_ctype = self._global_var_types.get(_cattr_gname, 'int64_t')
                _cattr_ctype = _cattr_ctype.replace('_Bool', 'bool')
                cpp_parts.append(f'extern {_cattr_ctype} {_cattr_gname};')
            cpp_parts.append('')
        if self._cpp_struct_method_refs:
            cpp_parts.append('/* Extern declarations for struct methods')
            cpp_parts.append("   called from this module's compiled generator")
            cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
            for _sm_struct, _sm_method in sorted(self._cpp_struct_method_refs):
                try:
                    _smsym = self._struct_method_csym(_sm_struct, _sm_method, '')
                    _smkey = f'{_sm_struct}_{_safe_name(_sm_method)}'
                    _smret = self.func_return_types.get(_smsym, self.func_return_types.get(_smkey, 'int64_t'))
                    _smparams = self.func_param_types.get(_smsym, self.func_param_types.get(_smkey, [f'{_sm_struct} *']))
                    _smret_cpp = _smret.replace('_Bool', 'bool')
                    _smparam_str = ', '.join((p if p != '_Bool' else 'bool' for p in _smparams))
                    cpp_parts.append(f'extern "C" {_smret_cpp} {_smsym} ({_smparam_str});')
                except Exception:
                    continue
            cpp_parts.append('')
        for unit in self._generator_cpp_units:
            cpp_parts.append(unit)
            cpp_parts.append('')
        self.generated_cpp = '\n'.join(cpp_parts)
