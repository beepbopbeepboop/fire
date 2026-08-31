"""gen_module implementation.

Entire original GimpleGen.gen_module body, hoisted verbatim.
Takes `self` (GimpleGen instance) and `stmts` (top-level AST
statements); returns the generated C source string.
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
    py_tokenize, Parser, _as_str, _as_funcdef_node,
)
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
from gimple_exprtypes import _walk_ast
import gimple_codegen
import gimple_gen_funcs as _ggf_dup
from gimple_codegen import ClosureInfo, DispatchSolver, TypeLattice, _CPP_KEYWORD_FIELDS, _C_KEYWORDS, _C_PARAM_EXTRA_KEYWORDS, _C_RESERVED_FUNCS, _EXPR_DISPATCH, _FIXED_ARRAY_ANN_RE, _LIST_RETURNING_METHODS, _PSEUDO_DUNDER_ATTRS, _RUNTIME_FUNCS, _SELFHOST_DIR, _STMT_DISPATCH, _STR_RETURNING_METHODS, _TYPE_MAP, _UnsupportedGeneratorShape, _async_gen_quick_eligible, _async_quick_eligible, _bracket_param_type_annotations, _c_escape, _c_field_name, _c_id, _class_attr_ctype, _compute_exc_descendants, _debug_note, _declared_vars_body, _emitted_unresolved_stub_syms, _extract_init_expr, _generator_quick_eligible, _import_targets, _merge_struct_inheritance, _module_init_name, _module_toplevel_name, _mojo_type, _safe_field, _safe_name, _struct_type_id, _stub_guard_name, _used_idents_deep, _used_idents_node

_SELFHOST_MODGLOBAL_CACHE: dict = {}


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


def _selfhost_modglobal_is_pathcall(_v) -> bool:
    """`os.path.<fn>(...)` (any nesting) — a char*-producing path expression."""
    if not isinstance(_v, CallExpr):
        return False
    _f = _v.func
    if (isinstance(_f, MemberExpr) and isinstance(_f.obj, MemberExpr)
            and isinstance(_f.obj.obj, IdentExpr)
            and _f.obj.obj.name == 'os' and _f.obj.member == 'path'):
        return True
    if isinstance(_f, MemberExpr) and isinstance(_f.obj, IdentExpr) and _f.obj.name == 'os':
        return True
    return False


def _selfhost_module_scalar_globals(sd: str) -> dict:
    """`{global_name: (module_name, semantic_ctype, c_decl_ctype)}` for every
    top-level `NAME = <int|str|bool literal>` / `NAME = frozenset(...)` /
    `NAME = {set literal}` assignment across this compiler's own sibling
    `.py` modules.

    Used as a pre-pass (see gen_module_impl's `_emit_imported_global_
    accessors` call site) to seed `_global_to_module` / `_global_var_types`
    BEFORE any function body is lowered. The gimple_codegen ↔ gimple_gen_*
    import cycle otherwise lowers a `gimple_codegen.STRING_POOL_BASE`-style
    qualified module-global read inside a dependency's body before
    gimple_codegen's own `_gscan_declare_global` has run — the read then
    falls to a NULL dynamic getattr (AttributeError / segfault) in the
    compiled compile_to_gimple. Only literal / frozenset RHS shapes are
    seeded: those are exactly what `_gscan_declare_global` itself would
    conclude for the same assignment, so the pre-seed can never disagree
    with the eventual per-module scan."""
    import glob as _glob
    _files = sorted(_glob.glob(os.path.join(sd, 'gimple_*.py'))
                    + [os.path.join(sd, n) for n in
                       ('mojo_compiler.py', 'module_loader.py', 'monomorphize.py',
                        'ast_rewriter.py', 'imports.py', 'generated_dispatch.py',
                        'reflect.py', 'mlir.py', 'regex_compile.py', 'cas.py',
                        'elaborate.py', 'myinterpreter.py')])
    _files = [f for f in _files if os.path.isfile(f)]
    _key = tuple((f, os.path.getmtime(f)) for f in _files)
    _hit = _SELFHOST_MODGLOBAL_CACHE.get('k')
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    # Home-side C-decl for a container module global is `int64_t` (boxed)
    # UNLESS it is one of gen_module_impl's hardcoded dispatch tables (which
    # get a bare `MojoDict *` / `MojoSet *` field). Skip those names so the
    # pre-seed can never disagree with the home's field/accessor type.
    _dispatch_only = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS', '_TYPE_MAP',
                      '_SIGNED', '_UNSIGNED', '_FLOAT', '_CMP_OPS'}
    _out: dict = {}
    for _f in _files:
        _mod = os.path.splitext(os.path.basename(_f))[0]
        try:
            _stmts = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _s in _stmts:
            if not (isinstance(_s, AssignStmt) and isinstance(_s.target, IdentExpr)):
                continue
            _n, _v = _s.target.name, _s.value
            if _n in _out or _n in _dispatch_only:
                continue
            if isinstance(_v, IntLiteral):
                _out[_n] = (_mod, 'int', 'int64_t')
            elif isinstance(_v, BoolLiteral):
                _out[_n] = (_mod, '_Bool', '_Bool')
            elif isinstance(_v, StringLiteral):
                _out[_n] = (_mod, 'char *', 'char *')
            elif isinstance(_v, (SetExpr,)) or (
                    isinstance(_v, CallExpr) and isinstance(_v.func, IdentExpr)
                    and _v.func.name in ('frozenset', 'set')):
                _out[_n] = (_mod, 'MojoSet *', 'int64_t')
            elif isinstance(_v, DictExpr) or (
                    isinstance(_v, CallExpr) and isinstance(_v.func, IdentExpr)
                    and _v.func.name in ('dict', 'Dict')):
                _out[_n] = (_mod, 'MojoDict *', 'int64_t')
            elif isinstance(_v, (ListExpr, TupleExpr)) or (
                    isinstance(_v, CallExpr) and isinstance(_v.func, IdentExpr)
                    and _v.func.name in ('list', 'List')):
                _out[_n] = (_mod, 'MojoList *', 'int64_t')
            elif _selfhost_modglobal_is_pathcall(_v):
                # `_SELFHOST_DIR = os.path.dirname(os.path.abspath(__file__))`
                # and similar — a char* path string. Home emits an int64_t
                # (boxed) accessor.
                _out[_n] = (_mod, 'char *', 'int64_t')
    _SELFHOST_MODGLOBAL_CACHE['k'] = (_key, _out)
    return _out


def _seed_selfhost_module_globals(self):
    """Populate the shared `_global_to_module` / `_global_var_types` /
    `_global_c_decl_types` from `_selfhost_module_scalar_globals` — see that
    helper's docstring."""
    for _n, (_mod, _sem, _cdecl) in _selfhost_module_scalar_globals(_SELFHOST_DIR).items():
        self._global_to_module.setdefault(_n, _mod)
        self._global_var_types.setdefault(_n, _sem)
        self._global_c_decl_types.setdefault(_n, _cdecl)


def _selfhost_struct_dict_field_val_types(sd: str) -> dict:
    """`{struct_name: {field_name: value_ctype}}` for every annotated
    `dict[K, V]` instance field across this compiler's own sibling `.py`
    modules — an `AssignStmt` (`self.X: dict[str, str] = {}` in `__init__`,
    or a class-body `X: dict[...] = {}`) carrying a `type_ann`.

    The ordinary field-value-type scan (`_collect_self_assigns`, the
    `_field_dict_val_types.setdefault(...)` there) only runs on structs whose
    full method BODIES are in `stmts`/`imported_stmts`. In a per-module
    `mojo.py build` compile a sibling class like `GimpleGen` arrives as a
    materialized imported struct with signature-only methods, so its
    `_str_pool: dict[str, str]` value type was lost — `for k, v in
    self._str_pool.items()` then unpacked `v` as int64 and `str()`'d the
    pointer (garbage decimal `_slit_N` names in the emitted string pool)."""
    import glob as _glob
    _files = sorted(_glob.glob(os.path.join(sd, 'gimple_*.py'))
                    + [os.path.join(sd, n) for n in
                       ('module_loader.py', 'mojo_compiler.py')])
    _files = [f for f in _files if os.path.isfile(f)]
    _key = tuple((f, os.path.getmtime(f)) for f in _files)
    _hit = _SELFHOST_MODGLOBAL_CACHE.get('sdfvt')
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _out: dict = {}
    for _f in _files:
        try:
            _stmts = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _s in _stmts:
            if not (isinstance(_s, StructDef) and _s.name):
                continue
            _bodies = list(getattr(_s, 'fields', []) or [])
            for _m in (getattr(_s, 'methods', []) or []):
                _bodies.extend(getattr(_m, 'body', []) or [])
            for _n in _bodies:
                if not (isinstance(_n, AssignStmt) and getattr(_n, 'type_ann', None)):
                    continue
                _ann = str(_n.type_ann).strip()
                if not (_ann.startswith('dict[') or _ann.startswith('Dict[')):
                    continue
                _tgt = _n.target
                _fname = (_tgt.member if isinstance(_tgt, MemberExpr)
                          and isinstance(_tgt.obj, IdentExpr) and _tgt.obj.name == 'self'
                          else _tgt.name if isinstance(_tgt, IdentExpr) else None)
                if _fname is None:
                    continue
                _inner = _ann[_ann.index('[') + 1:_ann.rindex(']')]
                _parts = [p.strip() for p in _inner.split(',')]
                if len(_parts) == 2:
                    _vt = _mojo_type(_parts[1]) if _parts[1] else 'int64_t'
                    # Only seed a `char *` value type: that is the case where
                    # a lost value type produces visibly-wrong output (int64
                    # boxed pointer -> `str()` -> decimal address). A
                    # container value slot (MojoDict*/MojoList*) is already
                    # boxed as int64_t by convention — leaving it is the
                    # pre-existing behavior, not a regression, and seeding it
                    # here would widen this pre-pass's blast radius.
                    if _vt == 'char *':
                        _out.setdefault(_s.name, {}).setdefault(_fname, _vt)
    _SELFHOST_MODGLOBAL_CACHE['sdfvt'] = (_key, _out)
    return _out


def _seed_selfhost_struct_dict_field_types(self):
    """Seed `_field_dict_val_types` from `_selfhost_struct_dict_field_val_types`
    so a sibling compiler struct's annotated `dict[str, str]` field keeps its
    value type through a per-module `mojo.py build` compile."""
    for _sn, _fields in _selfhost_struct_dict_field_val_types(_SELFHOST_DIR).items():
        _dst = self._field_dict_val_types.setdefault(_sn, {})
        for _fn, _vt in _fields.items():
            _dst.setdefault(_fn, _vt)


def _selfhost_homogeneous_tuple_ret_funcs(self, sd: str) -> dict:
    """`{func_key: elem_ctype}` for every sibling `.py` module-level function
    and struct method whose return annotation is a homogeneous non-`int64_t`
    `tuple[T, T[, ...]]`. `func_key` is the bare name for a free function and
    `Struct_method` for a method — the same keys `_return_elem_types` and
    `_lower_struct_method_call` / `_lower_named_call` look up.

    Pass-2c body inference (`_infer_return_elem_type`) can miss these when a
    slot is a reassigned local or a ternary, and in a per-module `mojo.py
    build` compile the defining function's body isn't even scanned from an
    importing module — so `GimpleGen._decode_str_literal_text`'s
    `(char*, char*)` return was unpacked via `mojo_list_get_int` and every
    user `StringLiteral`'s text read back as 0 (empty string-pool entries)."""
    import glob as _glob
    _files = sorted(_glob.glob(os.path.join(sd, 'gimple_*.py'))
                    + [os.path.join(sd, n) for n in ('module_loader.py', 'mojo_compiler.py')])
    _files = [f for f in _files if os.path.isfile(f)]
    _key = tuple((f, os.path.getmtime(f)) for f in _files)
    _hit = _SELFHOST_MODGLOBAL_CACHE.get('httrf')
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _out: dict = {}

    def _elem(_ann):
        if not isinstance(_ann, str):
            return None
        _s = _ann.strip()
        if not ((_s.startswith('tuple[') or _s.startswith('Tuple[')) and _s.endswith(']')):
            return None
        _inner = _s[_s.index('[') + 1:-1]
        _parts = [p.strip() for p in gimple_ctypes._split_top_level_commas(_inner) if p.strip()]
        if len(_parts) < 2:
            return None
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

    for _f in _files:
        try:
            _stmts = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _s in _stmts:
            if isinstance(_s, FunctionDef) and _s.name:
                _e = _elem(getattr(_s, 'return_type', None))
                if _e is not None:
                    _out.setdefault(_s.name, _e)
            elif isinstance(_s, StructDef) and _s.name:
                for _m in (getattr(_s, 'methods', []) or []):
                    _e = _elem(getattr(_m, 'return_type', None))
                    if _e is not None:
                        _out.setdefault(f"{_s.name}_{_m.name}", _e)
    _SELFHOST_MODGLOBAL_CACHE['httrf'] = (_key, _out)
    return _out


def _seed_selfhost_return_elem_types(self):
    """Seed `_return_elem_types` from `_selfhost_homogeneous_tuple_ret_funcs`."""
    for _k, _e in _selfhost_homogeneous_tuple_ret_funcs(self, _SELFHOST_DIR).items():
        if self._return_elem_types.get(_k) is None:
            self._return_elem_types[_k] = _e


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


def _selfhost_fn_reassigns_method(_fn, _pnames=('gen', 'self')) -> bool:
    """True if `_fn`'s body monkey-patches a METHOD on the `gen`/`self` param
    (`gen._emit = intercepted_emit` — the `_gen_stmt_TryStmt` emit-
    interception idiom). Those functions must keep the param OPAQUE in the
    closure pre-pass: typed as `GimpleGen *`, the nested closures capture a
    real void method as a value and the reassignment / later calls don't
    lower to valid C. try/except codegen already doesn't run natively, so
    leaving it stubbed (as before) is no regression.

    Only the METHOD-reassignment shape counts — the RHS is a nested `def`
    name or a lambda. An ORDINARY `self.<datafield> = value` assignment
    (which `gen_module_impl` and most GimpleGen methods do constantly) must
    NOT trip this: it would wrongly force `self`/`gen` to `int64_t` in the
    closure pre-pass, so `_scan_for_closures`'s capture of `self` typed
    `int64_t` -> `self._mutated_free_names(...)` stubbed -> `mojo_set_union
    (self, ...)` -> SEGV compiling any program with a nested `def`."""
    _local_defs = {_d.name for _d in _walk_ast(getattr(_fn, 'body', []) or [])
                   if isinstance(_d, FunctionDef)}
    for _n in _walk_ast(getattr(_fn, 'body', []) or []):
        if (isinstance(_n, AssignStmt) and isinstance(_n.target, MemberExpr)
                and isinstance(_n.target.obj, IdentExpr)
                and _n.target.obj.name in _pnames):
            _rhs = _n.value
            if isinstance(_rhs, LambdaExpr):
                return True
            if isinstance(_rhs, IdentExpr) and _rhs.name in _local_defs:
                return True
    return False


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
        for field_name, field_type in fields.items():
            ft = '' + field_type
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


def gen_module_impl(self, stmts):
    self._actual_types['stmts'] = 'MojoList *'
    self._toplevel_dep_init_modules: list[str] = []
    def _prefold_toplevel_comptime(_node_list):
        for _cn in _node_list:
            if isinstance(_cn, ComptimeVarStmt):
                _cv = self._eval_const(_cn.value)
                if _cv is not None:
                    self._comptime_vals.setdefault(_cn.target, _cv)
                if isinstance(_cn.value, ListExpr):
                    self._comptime_list_asts.setdefault(_cn.target, _cn.value)
            elif isinstance(_cn, IfStmt):
                _prefold_toplevel_comptime(_cn.then_body or [])
                if _cn.else_body:
                    _prefold_toplevel_comptime(_cn.else_body)
                for _, _eb in (_cn.elifs or []):
                    _prefold_toplevel_comptime(_eb or [])
            elif isinstance(_cn, (WhileStmt, ForStmt)):
                _prefold_toplevel_comptime(_cn.body or [])
            elif isinstance(_cn, TryStmt):
                _prefold_toplevel_comptime(_cn.body or [])
                for _h in (_cn.handlers or []):
                    _prefold_toplevel_comptime(getattr(_h, 'body', None) or [])
    _prefold_toplevel_comptime(stmts)
    for _fis in stmts:
        if not isinstance(_fis, FromImportStmt):
            continue
        try:
            _imp_path, _imp_src, _imp_stmts = self._parsed_import(_fis.module)
        except Exception:
            continue
        if not _imp_stmts:
            continue
        for _iname, _ialias in _fis.names:
            _isym = _ialias if _ialias else _iname
            if _isym in self._comptime_vals:
                continue   # a same-named local binding always wins
            _found = {}
            def _find_one(_node_list, _target=_iname, _out=_found):
                if _out:
                    return
                for _cn in _node_list:
                    if isinstance(_cn, ComptimeVarStmt) and _cn.target == _target:
                        _cv = self._eval_const(_cn.value)
                        if _cv is not None:
                            _out['v'] = _cv
                        return
                    elif isinstance(_cn, IfStmt):
                        _find_one(_cn.then_body or [], _target, _out)
                        if _cn.else_body:
                            _find_one(_cn.else_body, _target, _out)
                        for _, _eb in (_cn.elifs or []):
                            _find_one(_eb or [], _target, _out)
                    elif isinstance(_cn, (WhileStmt, ForStmt)):
                        _find_one(_cn.body or [], _target, _out)
                    elif isinstance(_cn, TryStmt):
                        _find_one(_cn.body or [], _target, _out)
                        for _h in (_cn.handlers or []):
                            _find_one(getattr(_h, 'body', None) or [], _target, _out)
            _find_one(_imp_stmts)
            if 'v' in _found:
                self._comptime_vals[_isym] = _found['v']
    self._import_scope_stack.append({})
    _generator_fns: dict[int, FunctionDef] = {}
    _async_fns: dict[int, FunctionDef] = {}
    for n in _walk_ast(stmts):
        if isinstance(n, FunctionDef):
            if n.is_generator: _generator_fns[id(n)] = n
            if n.is_async: _async_fns[id(n)] = n
    self._all_generator_names: set = {n.name for n in _generator_fns.values()}
    self._all_async_fn_names: set[str] = {n.name for n in _async_fns.values()}

    for _s in stmts:
        if isinstance(_s, StructDef) and _s.name in _C_KEYWORDS:
            _safe = f'_kw_{_s.name}'
            self._c_kw_struct_renames[_s.name] = _safe
            _s.name = _safe
    self._local_struct_names = {s.name for s in stmts if isinstance(s, StructDef)}
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

    def _toplev_bound_names(_tb_body):
        _names = set()
        for _tb_s in (_tb_body or []):
            if isinstance(_tb_s, FromImportStmt):
                for _tb_nm, _tb_alias in (_tb_s.names or []):
                    _names.add(_tb_alias if _tb_alias else _tb_nm)
            elif isinstance(_tb_s, ImportStmt):
                for _tb_mod, _tb_alias in _import_targets(_tb_s):
                    _names.add(_tb_alias if _tb_alias else _tb_mod.split('.')[0])
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
            for _m, _oid in zip(_s.methods, _moids_pre):
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

    for _s in stmts:
        if isinstance(_s, ComptimeVarStmt) and isinstance(_s.value, ListExpr):
            self._comptime_list_asts.setdefault(_s.target, _s.value)

    self._local_top_level_func_names = {
        s.name for s in stmts if isinstance(s, FunctionDef)}

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
        if _sg_cf:
            _sg_abs = os.path.abspath(os.path.dirname(_sg_cf))
            if _sg_abs == _SELFHOST_DIR or _sg_abs.startswith(_SELFHOST_DIR + os.sep):
                _seed_selfhost_module_globals(self)
                _seed_selfhost_struct_dict_field_types(self)
                _seed_selfhost_return_elem_types(self)

    imported_code = []
    imported_stmts = []
    if self.do_imports:
        modules_to_compile = set()
        def find_imports(node_list):
            for stmt in node_list:
                if isinstance(stmt, FromImportStmt):
                    modules_to_compile.add(stmt.module)
                    for _fn, _fa in (stmt.names or []):
                        # _join_import_member, not a blind f"{module}.{name}":
                        # for a bare-relative module (`from . import strutil`,
                        # module == '.') the separator dot would double-count
                        # the depth ('.' + '.' + 'strutil' spells '..strutil',
                        # a level-2 name that resolves one directory too high
                        # or nowhere at all). The joined string must be EXACTLY
                        # what _module_candidate_paths resolves and what the
                        # temp_gen's own module_name/qualifier derive from —
                        # see _join_import_member's docstring.
                        modules_to_compile.add(gimple_ctypes._join_import_member(stmt.module, _fn))
                elif isinstance(stmt, ImportStmt):
                    for _m, _a in _import_targets(stmt):
                        modules_to_compile.add(_m)
                elif isinstance(stmt, FunctionDef):
                    find_imports(stmt.body)
                elif isinstance(stmt, IfStmt):
                    find_imports(stmt.then_body)
                    for _, elif_body in stmt.elifs:
                        find_imports(elif_body)
                    if stmt.else_body:
                        find_imports(stmt.else_body)
                elif isinstance(stmt, (WhileStmt, ForStmt, TryStmt)):
                    find_imports(stmt.body)

        find_imports(stmts)

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
        if self.do_imports:
            _xg_alias_mod: dict = {}
            _xg_alias_orig: dict = {}
            # Bound-MODULE bindings for `<module>.<gen>(...)` attribute
            # calls: as-bound name -> the FromImportStmt module string it
            # came from (`from . import strutil` binds 'strutil' -> '.').
            _xg_module_binding: dict = {}
            for _xg_n in _walk_ast(stmts):
                if isinstance(_xg_n, FromImportStmt) and not getattr(_xg_n, 'wildcard', False):
                    for _xg_name, _xg_alias in (_xg_n.names or []):
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
                    _xg_cparams = [pn.lstrip('*') for pn, _pt in (_xg_callee.params or [])]
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
                if not isinstance(_xg_fd, FunctionDef):
                    continue
                for _xg_n3 in _walk_ast(_xg_fd.body):
                    if isinstance(_xg_n3, CallExpr):
                        _xg_calls.append((_xg_n3, _xg_fd))

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
                    _xg_pnames = [pn.lstrip('*') for pn, _pt in (_xg_fn.params or [])]
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
                _xg_pnames = [pn.lstrip('*') for pn, _pt in (_xg_fn.params or [])]
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

        for module_name in sorted(modules_to_compile):
            if module_name not in self._compiled_modules:
                self._compiled_modules.add(module_name)
                code, module_stmts = self._compile_imported_module(module_name)
                if code:
                    imported_code.append(f"/* ─── Imported module: {module_name} ───────────────────── */")
                    imported_code.append(code)
                    imported_code.append('')
                    imported_stmts.extend(module_stmts)
                    for _ms in module_stmts:
                        if isinstance(_ms, FunctionDef):
                            self._global_inline_defs.add(_ms.name)
                            self._imported_func_home.setdefault(_ms.name, module_name)
                            self._note_own_func_home(_ms.name, module_name, record_scope=False)
                        elif isinstance(_ms, StructDef):
                            for _m in _ms.methods:
                                self._global_inline_defs.add(_m.name)
                                self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                            self._imported_struct_home.setdefault(_ms.name, module_name)
                self._compiled_modules.add(module_name)

        already_in_stmts = set(id(s) for s in imported_stmts)
        for s in self._all_transitive_stmts_ordered:
            if id(s) not in already_in_stmts:
                imported_stmts.append(s)
                already_in_stmts.add(id(s))

    if self.link_imports:
        for module_name in sorted(self._link_inline_modules):
            if module_name not in self._compiled_modules:
                self._compiled_modules.add(module_name)
                code, module_stmts = self._compile_imported_module(module_name)
                if code:
                    imported_code.append(f"/* ─── Imported module (link-mode fallback): {module_name} ───────────────────── */")
                    imported_code.append(code)
                    imported_code.append('')
                    imported_stmts.extend(module_stmts)
                    for _ms in module_stmts:
                        if isinstance(_ms, FunctionDef):
                            self._global_inline_defs.add(_ms.name)
                            self._imported_func_home.setdefault(_ms.name, module_name)
                            self._note_own_func_home(_ms.name, module_name, record_scope=False)
                        elif isinstance(_ms, StructDef):
                            for _m in _ms.methods:
                                self._global_inline_defs.add(_m.name)
                                self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                            self._imported_struct_home.setdefault(_ms.name, module_name)

    self.struct_field_types['Span'] = {
        '_data': 'char *',
        '_len': 'int64_t',
    }

    _cur_file = getattr(self, '_current_filename', None)
    _cur_abs = os.path.abspath(_cur_file) if _cur_file else ''
    _is_selfhost_file = bool(_cur_file) and (
        _cur_abs == _SELFHOST_DIR or _cur_abs.startswith(_SELFHOST_DIR + '/'))
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
            '_INT_TYPE_NAMES': 'MojoSet *',
            '_FLOAT_TYPE_NAMES': 'MojoSet *',
            '_gen_tls': 'void *',
        }
        self.struct_field_types['Parser'] = {
            '_tok': 'MojoList *',
            '_pos': 'int64_t',
            '_filename': 'char *',
            '_pending_decs': 'MojoList *',
            '_known_traits': 'MojoSet *',
            '_CONV_KWS': 'MojoSet *',
        }
        self.struct_field_types['Scope'] = {
            'parent': 'Scope *',
            'vars': 'MojoDict *',
        }

        self.func_param_types['Scope_define'] = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope_get']    = ['Scope *', 'char *']
        self.func_param_types['Scope_set']    = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope___init__'] = ['Scope *', 'Scope *']
        # Runtime helpers whose real C signature (mojo_runtime.h) takes
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
        self._func_kwargs_slot['MojoFunction___call__'] = 3
        self._func_kwargs_has_vararg['MojoFunction___call__'] = True

        self.struct_field_types['CallExpr'] = {
            'func': 'int64_t',
            'args': 'MojoList *',
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
        self.struct_field_types['SubscriptExpr'] = {
            'obj': 'int64_t',
            'index': 'int64_t',
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
    self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}

    # ELEMENT types for the homogeneous list fields of the AST tables above.
    # `struct_field_types` records only that a field IS a `MojoList *`; with
    # no element type every `for m in struct_def.methods:` binds its loop
    # variable as an opaque int64_t, so `m.name` goes through the boxed
    # dynamic-getattr path and `m.params` cannot be typed at all. These
    # mirror the `list[FunctionDef]` / `list[tuple[str, str]]` annotations on
    # the corresponding dataclasses in mojo_compiler.py (the single source of
    # truth) — the same declarative seed the field-type tables above already
    # are, kept here because those tables are what a compile of an arbitrary
    # user file has available. Only genuinely HOMOGENEOUS fields are listed:
    # `StructDef.fields` (VarDecl | AssignStmt) and `FunctionDef.body` (any
    # statement) have no single element type and are deliberately absent.
    self._field_elem_types.setdefault('StructDef', {})['methods'] = 'FunctionDef *'
    self._field_elem_types.setdefault('TraitDef', {})['methods'] = 'FunctionDef *'
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
    _gg_stmts = getattr(self, '_selfhost_gimplegen_stmts', None)
    _gg_sigs = getattr(self, '_selfhost_gimplegen_sigs', None)
    if (_gg_stmts is not None and _is_selfhost_file
            and 'GimpleGen' not in self.struct_field_types
            and not any(isinstance(s, StructDef) and s.name == 'GimpleGen'
                        for s in (stmts + imported_stmts))):
        _gg_ft0 = dict(getattr(self, '_selfhost_gimplegen_extra_fields', {}) or {})
        self.struct_field_types['GimpleGen'] = _gg_ft0
        self._imported_struct_names.add('GimpleGen')
        self._struct_name_owner.setdefault('GimpleGen', id(_gg_stmts))
        self._imported_typedef_structs.append(_gg_stmts)
    # Apply + LOCK the frozen GimpleGen signature table BEFORE any of the
    # method-registration / Pass-2b-bis / forward-decl passes run, in EVERY
    # temp_gen (including the root, where `class GimpleGen` is in-file) — so
    # every `GimpleGen_*` symbol's params/return/defaults are identical
    # across the whole closure by construction (`_infer_param_types` is not
    # pure). Also union in the extracted-helper field writes.
    if _gg_sigs and 'GimpleGen' in self.struct_field_types:
        _gg_ft = self.struct_field_types['GimpleGen']
        for _f, _c in (getattr(self, '_selfhost_gimplegen_extra_fields', {}) or {}).items():
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
        _gg_dvts = getattr(self, '_selfhost_gimplegen_dict_vts', None) or {}
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
        self._class_attrs.setdefault('GimpleGen', {})
        for _caf in _gg_stmts.fields:
            if not (isinstance(_caf, AssignStmt) and isinstance(_caf.target, IdentExpr)):
                continue
            _ca_n = _caf.target.name
            _ca_m = f"_classattr_GimpleGen__{_ca_n}"
            self._class_attrs['GimpleGen'][_ca_n] = _ca_m
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
    _all_struct_names = {s.name for s in all_struct_defs if isinstance(s, StructDef)}
    _struct_bases_map = {s.name: (getattr(s, 'bases', None) or [])
                          for s in all_struct_defs if isinstance(s, StructDef)}
    _unresolved_base_memo: dict = {}
    def _has_unresolved_base(_name, _stack=frozenset()):
        if _name in _unresolved_base_memo:
            return _unresolved_base_memo[_name]
        if _name in _stack:
            return False  # inheritance-cycle guard; shouldn't normally happen
        result = False
        for _b in _struct_bases_map.get(_name, ()):
            if _b not in _all_struct_names or _has_unresolved_base(_b, _stack | {_name}):
                result = True
                break
        _unresolved_base_memo[_name] = result
        return result
    self._structs_with_unresolved_base = {
        _name for _name in _struct_bases_map if _has_unresolved_base(_name)
    }
    _merge_struct_inheritance(all_struct_defs)
    self._exc_descendants = _compute_exc_descendants(all_struct_defs)
    for _s in all_struct_defs:
        if isinstance(_s, StructDef) and _s.name not in self.struct_field_types:
            self.struct_field_types[_s.name] = {}
    self._ctor_lit_param_types: dict[str, dict[str, str]] = {}
    _ctor_init_params = {}
    _ctor_init_methods = {}
    for _s in all_struct_defs:
        if isinstance(_s, StructDef):
            _init = None
            for _m in _s.methods:
                if _m.name == '__init__':
                    _init = _m
                    break
            if _init:
                _ctor_init_params[_s.name] = [pn for pn, _ in (_init.params or [])
                                              if pn != 'self' and not pn.startswith('*')]
                _ctor_init_methods[_s.name] = _init
    if _ctor_init_params:
        _ctor_lit_obs: dict[str, dict[str, set]] = {}
        _ctor_calls: list = []
        self._calls_in_stmts(stmts, _ctor_calls)
        if self.do_imports or self.link_imports:
            self._calls_in_stmts(imported_stmts, _ctor_calls)
        for _call in _ctor_calls:
            if not isinstance(_call.func, IdentExpr):
                continue
            _pnames = _ctor_init_params.get(_call.func.name)
            if not _pnames:
                continue
            for _i, _a in enumerate(_call.args):
                if _i >= len(_pnames):
                    break
                if isinstance(_a, StringLiteral):
                    _ctor_lit_obs.setdefault(_call.func.name, {}).setdefault(
                        _pnames[_i], set()).add('char *')
                elif isinstance(_a, FloatLiteral):
                    _ctor_lit_obs.setdefault(_call.func.name, {}).setdefault(
                        _pnames[_i], set()).add('double')
        for _struct_name, _pmap in _ctor_lit_obs.items():
            _init = _ctor_init_methods.get(_struct_name)
            if not _init:
                continue
            _ann = {pn: pt for pn, pt in (_init.params or [])}
            for _pname, _types in _pmap.items():
                if _types not in ({'double'}, {'char *'}):
                    continue                    # not unanimous double / char *
                if _ann.get(_pname) is not None:
                    continue                    # respect explicit annotation
                self._ctor_lit_param_types.setdefault(_struct_name, {})[_pname] = (
                    'double' if _types == {'double'} else 'char *')

    # The synthetic `class GimpleGen` StructDef registered above (shared into
    # every nested temp_gen) must yield ownership to the REAL node whenever it
    # arrives naturally in this TU's closure (the root compile and
    # gimple_codegen.py's own compile). The shared `_struct_name_owner` would
    # otherwise keep the synthetic id set by some sibling temp_gen, and every
    # class-attr / method / field pass below (`!= id(s)`) would skip the struct
    # — dropping e.g. `_classattr_GimpleGen___NO_OVERLOAD_MANGLE` and its
    # `_alloc_GimpleGen` seed, leaving the field NULL at runtime.
    for s in all_struct_defs:
        if isinstance(s, StructDef) and s.name == 'GimpleGen':
            self._struct_name_owner['GimpleGen'] = id(s)
            break
    for s in all_struct_defs:
        if isinstance(s, StructDef) and s.name not in self._struct_name_owner:
            self._struct_name_owner[s.name] = id(s)
    for s in all_struct_defs:
        if isinstance(s, StructDef) and self._struct_name_owner.get(s.name) == id(s):
            if s.name not in self.struct_field_types:
                self.struct_field_types[s.name] = {}
    for s in all_struct_defs:
        if isinstance(s, StructDef):
            if self._struct_name_owner.get(s.name) != id(s):
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
                        self.struct_field_types[s.name][field.name] = (
                            _inherited_ft if _inherited_ft is not None else s.name + ' *')
            self._struct_generator_method_names.setdefault(s.name, set()).update(
                m.name for m in s.methods if getattr(m, 'is_generator', False))
            self._class_attrs[s.name] = {}
            for field in s.fields:
                if isinstance(field, AssignStmt):
                    if isinstance(field.target, IdentExpr):
                        aname = field.target.name
                        mangled = f"_classattr_{s.name}__{aname}"
                        self._class_attrs[s.name][aname] = mangled
                        v = field.value
                        ctype = _class_attr_ctype(v)
                        if ctype is not None:
                            self._global_var_types[mangled] = ctype
                            cur = self.struct_field_types[s.name].get(aname)
                            if cur is None or cur in ('int', 'int64_t'):
                                self.struct_field_types[s.name][aname] = ctype
                            if ctype == 'MojoList *' and isinstance(v, (ListExpr, TupleExpr)):
                                self._field_elem_types.setdefault(s.name, {})[aname] = (
                                    self._infer_list_elem_type(v.elements))
                        elif isinstance(v, StringLiteral):
                            self._global_var_types[mangled] = 'char *'
                        elif isinstance(v, (IntLiteral, BoolLiteral)):
                            self._global_var_types[mangled] = 'int64_t'
                        else:
                            self._global_var_types[mangled] = 'int64_t'
                        if field.type_ann is not None:
                            _dv_cls_early = self._annotation_dict_val_type(field.type_ann)
                            if _dv_cls_early is not None:
                                self._global_dict_val_types[mangled] = _dv_cls_early
                                # An annotated container class-attr
                                # (`_str_pool: dict[str, str] = {}`) is ALSO
                                # an instance field — the typed-assign loop
                                # below skips it (already registered here),
                                # so record its dict VALUE type for
                                # `_lower_MemberExpr` field reads too, or
                                # `for k, v in self._str_pool.items()`
                                # unpacks `v` as int64 and `str()`s the
                                # pointer (garbage `_slit_N` names).
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
                    if f_name not in self.struct_field_types[s.name]:
                        ft = _mojo_type(field.type_ann)
                        # BUG-2026-014 (box.3d/game): a bare capitalized
                        _fann_s = str(field.type_ann).strip() if field.type_ann else ''
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
                        if ft == 'int64_t' and _fann_s and _fann_s != str(field.type_ann).strip():
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
                                    for _inm, _ialias in _ist.names:
                                        if (_ialias or _inm) != _fann_s:
                                            continue
                                        if self._materialize_imported_struct(
                                                _ist.module, _inm, _fann_s):
                                            ft = f"{_fann_s} *"
                                        break
                                    else:
                                        continue
                                    break
                        _arr_m = (_FIXED_ARRAY_ANN_RE.match(str(field.type_ann).strip())
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
                        _ann_bare = str(field.type_ann).strip() if field.type_ann else ''
                        if _ann_bare in ('object', 'Any') or (
                                ' | ' in _ann_bare
                                and any(p.strip()[:1].isupper()
                                        for p in _ann_bare.split(' | ') if p.strip() != 'None')):
                            self.struct_boxed_fields.setdefault(s.name, set()).add(f_name)
                        if _ann_bare == 'bool':
                            self.struct_bool_fields.setdefault(s.name, set()).add(f_name)
                        if field.type_ann and not _arr_m:
                            _ann_str = str(field.type_ann)
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
                            self._field_annotations[s.name + '.' + f_name] = str(field.type_ann)
                        _dv_early = self._annotation_dict_val_type(field.type_ann)
                        if _dv_early is not None:
                            self._field_dict_val_types.setdefault(s.name, {})[f_name] = _dv_early
                        if _dv_early in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                            _nv_early = self._annotation_dict_nested_val_type(field.type_ann)
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
                                and '[' in str(field.type_ann)):
                            _li = gimple_ctypes._split_top_level_commas(
                                str(field.type_ann).split('[', 1)[1].rstrip(']').strip())
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

            def _self_member(expr):
                """MemberExpr's `.member` name iff its object is bare `self`."""
                if (isinstance(expr, MemberExpr) and isinstance(expr.obj, IdentExpr)
                        and expr.obj.name == 'self'):
                    return expr.member
                return None

            def _collect_self_assigns(body, param_types, found):
                for node in _walk_ast(body):
                    if isinstance(node, AssignStmt):
                        fn = _self_member(node.target)
                        _existing_fn_ft = found.get(fn)
                        if fn is not None and (
                                fn not in found
                                or (_existing_fn_ft in ('int', 'int64_t')
                                    and _existing_fn_ft is not None)):
                            v = node.value
                            if isinstance(v, IdentExpr):
                                ft = param_types.get(v.name, 'int64_t')
                            elif isinstance(v, IntLiteral):
                                ft = 'int64_t'
                            elif isinstance(v, StringLiteral):
                                ft = 'char *'
                            elif isinstance(v, BoolLiteral):
                                ft = '_Bool'
                            elif isinstance(v, DictExpr):
                                ft = 'MojoDict *'
                            elif isinstance(v, (ListExpr, TupleExpr)):
                                ft = 'MojoList *'
                            elif isinstance(v, SetExpr):
                                ft = 'MojoSet *'
                            elif isinstance(v, Comprehension):
                                ft = {'list': 'MojoList *', 'set': 'MojoSet *',
                                      'dict': 'MojoDict *'}.get(v.kind, 'MojoList *')
                            elif isinstance(v, CallExpr):
                                cfn = v.func
                                cn = cfn.name if isinstance(cfn, IdentExpr) else ''
                                if cn in ('list', 'DynamicVector', 'mojo_list_new'):
                                    ft = 'MojoList *'
                                elif cn in ('dict', 'Dict', 'mojo_dict_new'):
                                    ft = 'MojoDict *'
                                elif cn in ('set', 'Set', 'frozenset', 'mojo_set_new'):
                                    ft = 'MojoSet *'
                                elif cn.startswith('_alloc_'):
                                    sname = cn[len('_alloc_'):]
                                    ft = sname + ' *'
                                elif cn in self.struct_field_types:
                                    ft = cn + ' *'
                                elif (isinstance(cfn, MemberExpr)
                                      and cfn.member in _STR_RETURNING_METHODS):
                                    ft = 'char *'
                                elif (isinstance(cfn, MemberExpr)
                                      and cfn.member in _LIST_RETURNING_METHODS):
                                    ft = 'MojoList *'
                                else:
                                    ft = 'int'
                            else:
                                ft = 'int'
                            found[fn] = ft
                            # `self._str_pool: dict[str, str] = {}` in
                            # __init__: capture the dict VALUE type from the
                            # annotation so `for k, v in self._str_pool.
                            # items()` unpacks `v` as `char *`, not int64
                            # (int64 -> `str()` on the pointer -> garbage
                            # `_slit_N` names in the emitted string pool).
                            if ft == 'MojoDict *' and getattr(node, 'type_ann', None):
                                _dv_sa = self._annotation_dict_val_type(node.type_ann)
                                if _dv_sa is not None:
                                    self._field_dict_val_types.setdefault(
                                        s.name, {})[fn] = _dv_sa
                            # `self._struct_allocs_needed: set[str] = set()` /
                            # `self._x: list[Foo] = []` in __init__ — seed the
                            # element type from the annotation, mirroring the
                            # dict-value seed just above. Without it a later
                            # `for x in sorted(self._x):` / `for x in self._x:`
                            # left `x` boxed int64_t.
                            if (ft in ('MojoList *', 'MojoSet *')
                                    and getattr(node, 'type_ann', None)
                                    and '[' in str(node.type_ann)):
                                _li_sa = gimple_ctypes._split_top_level_commas(
                                    str(node.type_ann).split('[', 1)[1].rstrip(']').strip())
                                if _li_sa:
                                    _et_sa = self._resolve_type(_li_sa[0].strip())
                                    if _et_sa and _et_sa != 'int64_t':
                                        self._field_elem_types.setdefault(
                                            s.name, {})[fn] = _et_sa
                    elif isinstance(node, MultiAssignStmt):
                        for tgt in node.targets:
                            fn = _self_member(tgt)
                            if fn is not None and fn not in found:
                                found[fn] = 'int'
                    elif isinstance(node, AugAssignStmt):
                        fn = _self_member(node.target)
                        if fn is not None and fn not in found:
                            found[fn] = 'int64_t'

            _method_names = {m.name for m in s.methods}

            def _collect_self_reads(body, found):
                for node in _walk_ast(body):
                    fn = _self_member(node)
                    if (fn is not None and fn not in found and fn not in _method_names
                            and fn not in _PSEUDO_DUNDER_ATTRS):
                        found[fn] = 'int'

            already = set(self.struct_field_types[s.name].keys())
            for method in s.methods:
                pm = {}
                _defaults = getattr(method, 'param_defaults', {}) or {}
                for pname, ptype in method.params:
                    if pname != 'self':
                        if ptype:
                            pm[pname] = self._resolve_type(ptype)
                        elif pname in _defaults:
                            _dv = _defaults[pname]
                            if isinstance(_dv, StringLiteral):
                                pm[pname] = 'char *'
                            elif isinstance(_dv, BoolLiteral):
                                pm[pname] = '_Bool'
                            else:
                                pm[pname] = 'int64_t'
                        elif (method.name == '__init__'
                              and pname in self._ctor_lit_param_types.get(s.name, {})):
                            pm[pname] = self._ctor_lit_param_types[s.name][pname]
                        else:
                            pm[pname] = 'int64_t'
                new_fields = {}
                _collect_self_assigns(method.body, pm, new_fields)
                for fn, ft in new_fields.items():
                    existing_ft = self.struct_field_types[s.name].get(fn)
                    can_override = (existing_ft == 'int' and ft.endswith(' *'))
                    if fn not in self.struct_field_types[s.name] or can_override:
                        self.struct_field_types[s.name][fn] = ft
                        if fn not in already:
                            s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                            already.add(fn)
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
                _collect_self_reads(method.body, read_fields)
                for fn, ft in read_fields.items():
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
                        and self._struct_name_owner.get(st.name) == id(st)}

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

    def _scan_body_for_local_field_access(body, own_struct_name):
        # Collect EVERY struct type each local name is ever bound to, then
        # keep only unambiguous names. The candidate scan is flow-insensitive
        # (it unions assignments across the whole body), so a name rebound to
        # different node types in one function — `_parse_expr`'s `left` holds
        # UnaryOp/CompareChain/BinaryOp/WalrusExpr/TernaryExpr as the loop
        # refines the expression — must not mint fields on ANY of them: a
        # member access guarded by `isinstance(left, CompareChain)` at runtime
        # (`left.operands`, mojo_compiler.py:3292) otherwise registered
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
        for stmt in body:
            for obj_name, fn in _scan_stmt_member_candidates(stmt):
                target_struct = local_types.get(obj_name)
                if target_struct is None:
                    continue
                if fn in self.struct_field_types[target_struct]:
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
                self.struct_field_types[target_struct][fn] = 'int'
                if target_def is not None and not any(
                        isinstance(f, VarDecl) and f.name == fn for f in target_def.fields):
                    target_def.fields.append(VarDecl(name=fn, type_ann=None, value=None))

    _scan_body_for_local_field_access(stmts, None)
    if self.do_imports or self.link_imports:
        _scan_body_for_local_field_access(imported_stmts, None)

    _phase0_func_types = dict(self.func_return_types)   # save Phase 0 registrations
    _phase0_imported   = dict(getattr(self, 'imported_symbols', {}))  # save Phase 0 imported_symbols
    self.func_return_types = dict(_RUNTIME_FUNCS)
    self.func_return_types.update(_phase0_func_types)   # Phase 0 types win over defaults
    all_struct_defs_for_types = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    for s in all_struct_defs_for_types:
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
    # bugs/COMPILE_FAIL_Tools_cases_generator_parser.md. Must run BEFORE
    # `_gen_toplevel` (this scan does; a second, later, defensive-only
    # copy of this same registration also lives in this file's toplevel
    # global-declaration scan, which runs AFTER `_gen_toplevel` and so
    # cannot fix this by itself). Mirrors `_gen_stmt_ImportStmt`'s own
    # dict shape exactly; guarded so it never overwrites a richer entry
    # a `from X import Y` already set for the same local name.
    for s in stmts:
        if isinstance(s, ImportStmt):
            for _im_mod, _im_alias in _import_targets(s):
                _im_local = _im_alias if _im_alias else _im_mod.split('.')[0]
                if _im_local not in self.imported_symbols:
                    self.imported_symbols[_im_local] = {
                        'module': _im_mod,
                        'return_type': 'unknown',
                    }
                self._module_alias_names.add(_im_local)

    for s in stmts:
        if isinstance(s, FromImportStmt):
            _sib_qualifier = None
            try:
                exports = load_module(s.module)
            except Exception:
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
                def _register_sym(sym_name, orig_name, sym_info):
                    if sym_name in self.struct_field_types:
                        return
                    if not s.wildcard and self._from_import_name_is_submodule(s.module, orig_name):
                        self.imported_symbols[sym_name] = {
                            # _join_import_member: same canonical member-module
                            # string find_imports compiled the submodule under —
                            # consumers (including the coroutine emitter's
                            # bound-module generator resolution) key off THIS
                            # value, so it must match the temp_gen's own
                            # module_name byte for byte (a bare-relative
                            # `from . import strutil` means '.strutil', never
                            # '..strutil').
                            'module': gimple_ctypes._join_import_member(s.module, orig_name),
                            'return_type': 'unknown',
                        }
                        self._module_alias_names.add(sym_name)
                        return
                    if _sib_qualifier and not sym_info:
                        if not s.wildcard:
                            self._unresolved_import_aliases.add(sym_name)
                        return
                    if isinstance(sym_info, str):
                        self.imported_symbols[sym_name] = {
                            'module': s.module, 'original_name': orig_name,
                            'return_type': sym_info, 'parameters': [],
                            'signature': f"{sym_info} {sym_name} (void)"
                        }
                        self.func_return_types[sym_name] = sym_info
                    elif isinstance(sym_info, dict):
                        sym_info = dict(sym_info)
                        sym_info['module'] = s.module
                        sym_info['original_name'] = orig_name
                        self.imported_symbols[sym_name] = sym_info
                        _ret_changed = False
                        if orig_name.startswith('_'):
                            pass
                        elif _sib_is_local_project and sym_info.get('return_type'):
                            _resolved_ret = self._resolve_sibling_param_ctype(
                                s.module, sym_info['return_type'])
                            if _resolved_ret:
                                sym_info['c_return_type'] = _resolved_ret
                                _ret_changed = True
                        if 'c_return_type' in sym_info:
                            self.func_return_types[sym_name] = sym_info['c_return_type']
                        if sym_info.get('variadic'):
                            if _ret_changed:
                                sym_info['signature'] = (
                                    f"{sym_info.get('c_return_type', 'int64_t')} "
                                    f"{orig_name} (...)")
                        elif (_sib_is_local_project and not orig_name.startswith('_')
                                and sym_info.get('c_parameters') is not None
                                and len(sym_info.get('parameters') or []) == len(sym_info['c_parameters'])
                                and (sym_info.get('parameters') or _ret_changed)):
                            _new_c_params = []
                            _params_changed = False
                            for (_p_name, _p_raw_type), _c_param in zip(
                                    sym_info.get('parameters') or [],
                                    sym_info['c_parameters']):
                                _resolved_ctype = self._resolve_sibling_param_ctype(
                                    s.module, _p_raw_type)
                                if _resolved_ctype:
                                    _c_name = (_c_param.split()[-1]
                                               if _c_param.strip() else _p_name)
                                    _new_c_params.append(f"{_resolved_ctype} {_c_name}")
                                    _params_changed = True
                                else:
                                    _new_c_params.append(_c_param)
                            if _params_changed or _ret_changed:
                                sym_info['c_parameters'] = _new_c_params
                                _c_ret = sym_info.get('c_return_type', 'int64_t')
                                _param_str = ', '.join(_new_c_params) if _new_c_params else 'void'
                                sym_info['signature'] = f"{_c_ret} {orig_name} ({_param_str})"
                        if _sib_qualifier and 'c_parameters' in sym_info:
                            self.func_param_types[sym_name] = [
                                ' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                                for cp in (sym_info.get('c_parameters') or [])
                            ]
                    if _sib_qualifier and sym_info:
                        if self.do_imports:
                            _qual = (s.module.replace('.', '_')
                                     .replace('-', '_'))
                        else:
                            _qual = _sib_qualifier
                        # BUG-2026-024: snapshot THIS import's param ctypes
                        # under (home_qualifier, as_referenced_name) BEFORE
                        # anything else can overwrite the shared bare-name
                        # slot — a later sibling module's inline compile
                        # registers its own same-named function into
                        # func_param_types[bare] (mod.computer.network's
                        # get_energy(n: ComputerNetwork) clobbering
                        # mod.computer.computer_case's get_energy(c:
                        # ComputerCase) after this line wrote the Case
                        # shape), and _overload_suffix's shared-slot tier
                        # then hashes the WRONG sibling for every one of
                        # this module's call sites. The snapshot is keyed by
                        # home module, so same-named siblings land under
                        # different keys and nothing oscillates; lookup goes
                        # through _imported_def_pts, which walks the SAME
                        # tier order _func_qualifier uses, so the qualifier
                        # half and suffix half of one mangled symbol always
                        # mean the same binding. Preferred source is the
                        # defining module's own FunctionDef resolved via
                        # THIS gen's _signature_ctypes (the definition
                        # side's exact resolver — export-table c_parameters
                        # can carry int64_t placeholders for struct params,
                        # which hashed a DIFFERENT suffix than the
                        # definition); falls back to the already-populated
                        # slot.
                        try:
                            _pts_snap = None
                            for _fs in (self._parsed_import(s.module)[2] or []):
                                if isinstance(_fs, FunctionDef) and _fs.name == name:
                                    _pts_snap = self._signature_ctypes(_fs.params, _fs)
                                    break
                        except Exception:
                            _pts_snap = None
                        if not _pts_snap:
                            _pts_snap = self.func_param_types.get(sym_name)
                        if _pts_snap is not None:
                            self._imported_home_param_types[(_qual, sym_name)] = list(_pts_snap)
                        self._note_own_func_home(sym_name, _qual)
                try:
                    if not s.names:
                        for _wc_key, _wc_info in exports.items():
                            _register_sym(_wc_key, _wc_key, _wc_info)
                    else:
                        for name, alias in s.names:
                            sym_name = alias if alias else name
                            sym_info = exports.get(name, {})
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
                                _ov_path = self._parsed_import(s.module)[0]
                                if _ov_path:
                                    _ov_src = open(_ov_path).read()
                                    if len(re.findall(
                                            rf'\b(?:fn|def)\s+{re.escape(name)}\s*\(',
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
                                        s.module.replace('.', '_').replace('-', '_') + '::' + name)
                                    or self._generator_home_api.get(
                                        gimple_ctypes._join_import_member(s.module, name)
                                        .replace('.', '_').replace('-', '_') + '::' + name))
                                if _gmh_api is not None:
                                    self._imported_generator_bindings[sym_name] = _gmh_api
                                    continue
                            _register_sym(sym_name, name, sym_info)
                except Exception:
                    _debug_note('error registering sibling module imports', s.module)
            else:
                _debug_note('module load failed while registering imports')
                if not s.wildcard:
                    for _fb_name, _fb_alias in s.names:
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
        _s_pts = None
        if isinstance(s, FunctionDef) and s.params:
            if any(pn.startswith('*') for pn, _ in s.params):
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
        if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
            self._mangled_funcs.add(s.name)
        if isinstance(s, FunctionDef) and 'export' in (getattr(s, 'decorators', None) or []):
            self._extra_no_mangle.add(s.name)

    _own_top_level_func_names = {s.name for s in stmts if isinstance(s, FunctionDef)}

    def _scan_func_body_for_self_attr(fname, body):
        for _fstmt in body:
            if (isinstance(_fstmt, AssignStmt)
                    and isinstance(_fstmt.target, MemberExpr)
                    and isinstance(_fstmt.target.obj, IdentExpr)
                    and _fstmt.target.obj.name == fname):
                attr = _fstmt.target.member
                self._func_attrs.setdefault(fname, {})
                if attr not in self._func_attrs[fname]:
                    mangled = f"_funcattr_{fname}__{attr}"
                    self._func_attrs[fname][attr] = mangled
                    self._global_var_types.setdefault(mangled, 'int64_t')
                    self._global_c_decl_types.setdefault(mangled, 'int64_t')
            elif isinstance(_fstmt, FunctionDef):
                pass  # a nested def's own `f.attr` (if any) is scanned when THAT def is visited below
            elif isinstance(_fstmt, IfStmt):
                _scan_func_body_for_self_attr(fname, _fstmt.then_body)
                for _, _eb in _fstmt.elifs:
                    _scan_func_body_for_self_attr(fname, _eb)
                if _fstmt.else_body:
                    _scan_func_body_for_self_attr(fname, _fstmt.else_body)
            elif isinstance(_fstmt, (WhileStmt, ForStmt, TryStmt)):
                _scan_func_body_for_self_attr(fname, _fstmt.body)

    for s in stmts:
        if isinstance(s, FunctionDef) and s.name in _own_top_level_func_names:
            _scan_func_body_for_self_attr(s.name, s.body)

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
            for pname, ptype in s.params:
                if pname.startswith('**'):
                    self.var_types[pname[2:]] = 'MojoDict *'
                elif pname.startswith('*'):
                    self.var_types[pname[1:]] = 'MojoList *'
                else:
                    self.var_types[pname] = self._resolve_type(ptype)
            inferred = self._infer_return_type(s.body)
            if s.name == 'main' and inferred == 'void':
                inferred = 'int64_t'
            self.func_return_types[s.name] = inferred
            self.var_types.clear()

    for _pass2b_iter in range(4):
        _changed = False
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    self._struct_method_names.setdefault(s.name, set()).add(m.name)
                    if 'property' in (getattr(m, 'decorators', None) or []):
                        self._struct_property_names.setdefault(s.name, set()).add(m.name)
                    if m.name == '__init__':
                        self._struct_has_init.add(s.name)
                        self._struct_init_params[s.name] = [
                            pn for pn, _pt in m.params if pn != 'self']
                        _init_defaults = getattr(m, 'param_defaults', {}) or {}
                        self._struct_init_defaults[s.name] = {
                            pn: dv for pn, dv in _init_defaults.items() if pn != 'self'}
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
                        inferred = self._infer_return_type(m.body)
                        key = _mangled_key
                        if self.func_return_types.get(key) != inferred:
                            self.func_return_types[key] = inferred
                            _changed = True
                        self.var_types.clear()
        if not _changed:
            break

    _p2c_base_var_types = dict(self.func_return_types)
    for _pass2c_iter in range(8):
        _c_changed = False
        for s in all_functions:
            if _is_foreign_main(s) or not isinstance(s, FunctionDef):
                continue
            _ret_elem = self._infer_return_elem_type(
                s.body, func_def=s, _base_var_types=_p2c_base_var_types)
            if _ret_elem is None:
                _ret_elem = _homogeneous_tuple_ann_elem(self, s.return_type)
            if _ret_elem is not None and self._return_elem_types.get(s.name) != _ret_elem:
                self._return_elem_types[s.name] = _ret_elem
                _c_changed = True
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
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
            _moids = self._struct_method_overload_ids(s)
            for m, _oid in zip(s.methods, _moids):
                _has_self_first = bool(m.params) and m.params[0][0] == 'self'
                _params_no_self = m.params[1:] if _has_self_first else m.params
                # Sentinel is -1, NOT None: this compiler models None as 0,
                # so a `def m(self, *args)` whose star param IS at index 0
                # would be indistinguishable from "no star param" once
                # self-hosted (`_star_idx is not None` -> `0 != 0` -> False),
                # silently giving a varargs method max_arity 0. -1 is
                # unambiguous for an index under both evaluators.
                _star_idx = next((i for i, (pn, _pt) in enumerate(_params_no_self)
                                   if pn.startswith('*') and not pn.startswith('**')), -1)
                real_params = [(pn, pt) for pn, pt in _params_no_self
                               if not (pn.startswith('*') and not pn.startswith('**'))]
                _defaults = m.param_has_default or {}
                if _star_idx >= 0:
                    _pre_star = _params_no_self[:_star_idx]
                    min_arity = sum(1 for pn, _pt in _pre_star if pn not in _defaults)
                    max_arity = float('inf')
                else:
                    min_arity = sum(1 for pn, _pt in real_params
                                     if pn not in _defaults and not pn.startswith('**'))
                    max_arity = len(real_params)
                _all_ctypes = self._signature_ctypes(m.params, m, s.name)
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
                    _saved_var_types = dict(self.var_types)
                    self.var_types['self'] = f"{s.name} *"
                    for _pn, _pt in real_params:
                        self.var_types[_pn] = self._resolve_type(_pt)
                    _ret_type = self._infer_return_type(m.body)
                    self.var_types = _saved_var_types
                # Self-hosting bootstrap: the frozen GimpleGen signature
                # table is authoritative — override this pass's per-instance
                # inference so `_struct_method_signatures`, the method
                # externs, the forward decl and the definition all agree.
                _gg_sig = (getattr(self, '_selfhost_gimplegen_sigs', None) or {}).get(
                    f"GimpleGen_{m.name}") if s.name == 'GimpleGen' and not _oid else None
                if _gg_sig is not None:
                    _fz_ret, _fz_params, _ = _gg_sig
                    _ret_type = _fz_ret
                    _all_ctypes = list(_fz_params)
                    param_ctypes = _all_ctypes[1:] if _has_self_first else _all_ctypes
                    max_arity = len(param_ctypes)
                key = (s.name, m.name)
                self._struct_method_signatures.setdefault(key, []).append({
                    'overload_id': _oid,
                    'param_names': [pn for pn, _pt in real_params],
                    'param_ctypes': param_ctypes,
                    'min_arity': min_arity,
                    'max_arity': max_arity,
                    'ret_type': _ret_type,
                    'has_varargs': _star_idx >= 0,
                    'pre_star_count': _star_idx if _star_idx >= 0 else None,
                })
                self._mangled_signature_ctypes[f"{s.name}_{m.name}{_oid}"] = _all_ctypes

    for s in self._imported_typedef_structs:
        if not s.methods:
            continue
        for _oid, m in zip(self._struct_method_overload_ids(s), s.methods):
            bare_mangled = f"{s.name}_{m.name}{_oid}"
            mangled = self._struct_method_csym(s.name, m.name, _oid)
            param_ctypes = self._mangled_signature_ctypes.get(bare_mangled)
            if param_ctypes is None:
                continue
            ret_type = None
            for _cand in self._struct_method_signatures.get((s.name, m.name), []):
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
    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_param_types[s.name] = self._infer_param_types(s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{s.name}_{m.name}"
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

    self._inferred_var_types: dict[str, dict[str, str]] = {}  # func_name -> {var_name -> type}
    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_var_types[s.name] = self._infer_local_var_types(s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{s.name}_{m.name}"
                self._inferred_var_types[key] = self._infer_local_var_types(m)

    def _expr_provably_str(e):
        """Is `e` an expression whose Python runtime value is provably a
        str? Sound transitive closure over the two string-producing binary
        operators: `%`-format yields str whenever the FORMAT (LHS) is a
        str literal, and `+` yields str whenever EITHER operand is a str —
        str.__add__ rejects non-str operands with TypeError, so a literal
        str on either side proves BOTH sides are strs (which is what
        disambiguates this from list/tuple concatenation, the other
        inhabitant of `+`). Lets call sites like
        `self.sendcmd("OPTS MLST " + facts_joined + ";")` contribute real
        char* evidence instead of silence — without which a method whose
        ONLY call sites pass computed strings keeps its unannotated
        parameter at the int64_t default (ftplib.py gap #1's exact shape,
        reached once a module has no bare-literal call site to carry the
        vote alone)."""
        if isinstance(e, (StringLiteral, TstringLiteral)):
            return True
        if isinstance(e, BinaryOp):
            if e.op == '%':
                return _expr_provably_str(e.left)
            if e.op == '+':
                return (_expr_provably_str(e.left)
                        or _expr_provably_str(e.right))
        return False

    def _arg_scalar_type(caller_name, a, deep_str=False,
                         prefer_refined_param=False):
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
        if isinstance(a, FloatLiteral):
            return 'double'
        if isinstance(a, StringLiteral):
            return 'char *'
        if deep_str and _expr_provably_str(a):
            return 'char *'
        if isinstance(a, IdentExpr):
            t = self._inferred_var_types.get(caller_name, {}).get(a.name)
            if prefer_refined_param:
                _pt = self._inferred_param_types.get(caller_name, {}) \
                    .get(a.name)
                if _pt in ('char *', 'double'):
                    return _pt
                return t or _pt
            return t or self._inferred_param_types.get(caller_name, {}) \
                .get(a.name)
        return None

    _TOPLEVEL_CALLER = '<toplevel>'
    _caller_bodies = [(s.name, s.body) for s in all_functions if isinstance(s, FunctionDef)]
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
        for m in s.methods:
            _method_caller_bodies.append((f"{s.name}_{m.name}", s.name, m.body))
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
                pnames = [pn for pn, _ in (meth.params or [])
                          if pn != 'self' and not (_meth_is_cls and pn == 'cls')
                          and not pn.startswith('*')]
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
            ann = {pn: pt for pn, pt in (meth.params or [])}
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
        for m, _oid in zip(s.methods, self._struct_method_overload_ids(s)):
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
            if s.params and any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = _free_func_param_ctypes(self, s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                method_full_name = f"{s.name}_{m.name}"
                if method_full_name in self._selfhost_locked_param_types:
                    continue
                if m.params and any(pn.startswith('*') for pn, _ in m.params):
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
                if not (m.params and any(pn.startswith('*') for pn, _ in m.params)):
                    _m_dflts = getattr(m, 'param_defaults', None) or {}
                    if _m_dflts:
                        self._func_param_defaults.setdefault(method_full_name,
                                                             [(pn, dv) for pn, dv in _m_dflts.items()])

    for s in all_structs_for_methods:
        if not (isinstance(s, StructDef) and s.name == 'GimpleGen'):
            continue
        for m in s.methods:
            mangled = f"GimpleGen_{m.name}"
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
    _free_params = {s.name: [pn for pn, _ in (s.params or []) if not pn.startswith('*')]
                    for s in all_functions if isinstance(s, FunctionDef)}

    def _record_param_elem(callee, pname, e, ne):
        d = self._param_elem_types.setdefault(callee, {})
        if pname in d and d[pname] != (e, ne):
            d[pname] = (None, None)   # conflicting call sites → unknown
        else:
            d[pname] = (e, ne)

    _fn_by_name = {s.name: s for s in all_functions if isinstance(s, FunctionDef)}
    _scalar_obs: dict[str, dict[str, set]] = {}   # callee -> {pname -> {types}}

    for caller_name, body in _caller_bodies:
        elem, nested, _ = self._scan_container_elems(body)
        calls = []
        self._calls_in_stmts(body, calls)
        for call in calls:
            if not isinstance(call.func, IdentExpr):
                continue
            callee = call.func.name
            pnames = _free_params.get(callee)
            if not pnames:
                continue
            for i, a in enumerate(call.args):
                if i >= len(pnames):
                    break
                if isinstance(a, IdentExpr) and a.name in elem:
                    _record_param_elem(callee, pnames[i],
                                        elem[a.name], nested.get(a.name))
                st = _arg_scalar_type(caller_name, a)
                if st:
                    _scalar_obs.setdefault(callee, {}).setdefault(pnames[i], set()).add(st)

    # A container param whose ELEMENTS the callee `isinstance()`-checks
    # against struct types (`for s in stmts: if isinstance(s, FunctionDef)`)
    # holds boxed AST-node handles, never strings — retract any `char *`
    # element-type conclusion for it (a caller-side `_scan_container_elems`
    # mis-read, e.g. from `{s.name for s in stmts}` string comprehensions
    # elsewhere). Without this the callee's loop var is declared `char *`
    # and `s.name` lowers to `os.path.basename(s)` — the exact reason the
    # compiled `gen_module_impl` emitted no function bodies at all.
    _struct_names_here = ({s.name for s in all_struct_defs if isinstance(s, StructDef)}
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

    for callee, pmap in _scalar_obs.items():
        fn = _fn_by_name.get(callee)
        if not fn:
            continue
        ann = {pn: pt for pn, pt in (fn.params or [])}
        for pname, types in pmap.items():
            if types not in ({'double'}, {'char *'}):
                continue                         # not unanimous double / char *
            if ann.get(pname) is not None:
                continue                         # respect explicit annotation
            cur = self._inferred_param_types.get(callee, {}).get(pname)
            if cur in (None, 'int', 'int64_t'):
                resolved_type = 'double' if types == {'double'} else 'char *'
                self._inferred_param_types.setdefault(callee, {})[pname] = resolved_type

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
            if s.params and any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = _free_func_param_ctypes(self, s)

    _ctor_scalar_obs: dict[str, dict[str, set]] = {}   # struct -> {pname -> {types}}
    for caller_name, body in _caller_bodies:
        calls = []
        self._calls_in_stmts(body, calls)
        for call in calls:
            if not isinstance(call.func, IdentExpr):
                continue
            struct_name = call.func.name
            pnames = _ctor_init_params.get(struct_name)
            if not pnames:
                continue
            for i, a in enumerate(call.args):
                if i >= len(pnames):
                    break
                st = _arg_scalar_type(caller_name, a)
                if st:
                    _ctor_scalar_obs.setdefault(struct_name, {}).setdefault(
                        pnames[i], set()).add(st)

    for struct_name, pmap in _ctor_scalar_obs.items():
        _init = _ctor_init_methods.get(struct_name)
        if not _init:
            continue
        _ann = {pn: pt for pn, pt in (_init.params or [])}
        _init_defaults = getattr(_init, 'param_defaults', {}) or {}
        for pname, types in pmap.items():
            if types not in ({'double'}, {'char *'}):
                continue                        # not unanimous double / char *
            if _ann.get(pname) is not None:
                continue                        # respect explicit annotation
            if pname in _init_defaults:
                continue                        # respect default-value inference
            resolved_type = 'double' if types == {'double'} else 'char *'
            self._ctor_lit_param_types.setdefault(struct_name, {})[pname] = resolved_type
            for node in _walk_ast(_init.body):
                if not isinstance(node, AssignStmt):
                    continue
                tgt = node.target
                if not (isinstance(tgt, MemberExpr) and isinstance(tgt.obj, IdentExpr)
                        and tgt.obj.name == 'self'):
                    continue
                v = node.value
                if isinstance(v, IdentExpr) and v.name == pname:
                    _fld_types = self.struct_field_types.setdefault(struct_name, {})
                    if _fld_types.get(tgt.member) in (None, 'int', 'int64_t'):
                        _fld_types[tgt.member] = resolved_type

    for _gm_stmt in stmts:
        if isinstance(_gm_stmt, AssignStmt) and isinstance(_gm_stmt.target, IdentExpr):
            self._cpp_early_global_names.add(_gm_stmt.target.name)
        elif isinstance(_gm_stmt, ImportStmt):
            for _tm, _ta in _import_targets(_gm_stmt):
                self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
        elif isinstance(_gm_stmt, FromImportStmt):
            # `FromImportStmt.names` is `[(name, alias|None), ...]`
            # (mojo_compiler.py) -- NOT a flat list of bound-name
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

    def _scan_cpp_nested_imports(stmt_list):
        for _gi in stmt_list:
            if isinstance(_gi, (ImportStmt, FromImportStmt)):
                if isinstance(_gi, ImportStmt):
                    for _tm, _ta in _import_targets(_gi):
                        self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
                else:
                    # Same tuple-unpack fix as the top-level scan above
                    # (see that branch's comment) -- this is the nested
                    # (try/if-guarded import) sibling scan.
                    for _nm in getattr(_gi, 'names', []) or []:
                        _in, _ia = _nm if isinstance(_nm, tuple) else (_nm, None)
                        self._cpp_early_global_names.add(_ia if _ia else _in)
            elif isinstance(_gi, AssignStmt) and isinstance(_gi.target, IdentExpr):
                self._cpp_early_global_names.add(_gi.target.name)
            elif isinstance(_gi, TryStmt):
                _scan_cpp_nested_imports(_gi.body or [])
                for _h in (_gi.handlers or []):
                    _scan_cpp_nested_imports(getattr(_h, 'body', []) or [])
                if isinstance(getattr(_gi, 'finally_body', None), list):
                    _scan_cpp_nested_imports(_gi.finally_body)
            elif isinstance(_gi, IfStmt):
                _scan_cpp_nested_imports(_gi.then_body or [])
                if isinstance(_gi.else_body, list):
                    _scan_cpp_nested_imports(_gi.else_body)
    _scan_cpp_nested_imports(stmts)

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
            _dflt_list = [(pn, dv) for pn, dv in _gen_dflts.items()]
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
                _lens = {len(e.elements) for e in _els}
                if len(_lens) == 1:
                    _n = _lens.pop()
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
        if s.params and s.params[0][0] in ('self', 'cls'):
            continue
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
            if s.params and s.params[0][0] in ('self', 'cls'):
                continue
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

    for _sd in stmts:
        if not isinstance(_sd, StructDef):
            continue
        for m in _sd.methods:
            if not (isinstance(m, FunctionDef) and id(m) in _generator_fns
                    and id(m) not in _async_fns):
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
            key = (_sd.name, m.name)
            self._supported_generator_methods[key] = m
            self._generator_method_api[key] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            _gen_dflts = getattr(m, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f"{base}_start"] = [
                    (pn, dv) for pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _generator_fns.pop(id(m), None)

    for _sd in stmts:
        if not isinstance(_sd, StructDef):
            continue
        for m in _sd.methods:
            if not (isinstance(m, FunctionDef) and id(m) in _generator_fns
                    and id(m) not in _async_fns):
                continue
            if not _generator_quick_eligible(m):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = \
                    self._gen_cpp_generator_unit(m, struct_name=_sd.name)
            except _UnsupportedGeneratorShape as e:
                self._cpp_refusal_reasons.setdefault(m.name, str(e))
                _debug_note(f'generator method {_sd.name}.{m.name!r} not '
                            'eligible (pass 2)', e)
                continue
            key = (_sd.name, m.name)
            self._supported_generator_methods[key] = m
            self._generator_method_api[key] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            _gen_dflts = getattr(m, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f"{base}_start"] = [
                    (pn, dv) for pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _generator_fns.pop(id(m), None)

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
        for _m, _oid in zip(_sd.methods, _moids_ac):
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
            _saved_vt_23e = self.var_types
            self.var_types = dict(_saved_vt_23e)
            for pname, ptype in s.params:
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
            self.func_return_types[s.name] = inferred

    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_var_types[s.name] = self._infer_local_var_types(s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{s.name}_{m.name}"
                self._inferred_var_types[key] = self._infer_local_var_types(m)

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
        _found = [None]

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
                        if _found[0] is None:
                            _found[0] = prov
                        elif _found[0] != prov:
                            _found[0] = '<conflict>'
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
        return _found[0]

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

        def _collect_rt(stmts2):
            for _st in stmts2:
                if isinstance(_st, FunctionDef):
                    continue
                if isinstance(_st, ReturnStmt) and _st.value is not None:
                    acc_rt.append(_st.value)
                else:
                    for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                        sub = getattr(_st, attr, None)
                        if isinstance(sub, list):
                            _collect_rt(sub)
                    for _eb_cond, _eb_body in (getattr(_st, 'elifs', None) or []):
                        _collect_rt(_eb_body)
                    for _h in (getattr(_st, 'handlers', None) or []):
                        hb = getattr(_h, 'body', None)
                        if isinstance(hb, list):
                            _collect_rt(hb)

        _collect_rt(_rf.body)
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
            if s.params and any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = _free_func_param_ctypes(self, s)

    if self.emit_struct_defs:  # Only main module does dispatch solving
        self._dispatch_solver = DispatchSolver(
            self.struct_field_types, self.func_return_types,
            allow_assume_all_methods=_is_selfhost_file,
            generator_method_api=self._generator_method_api)
        all_stmts_for_dispatch = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        self._dispatch_solver.analyze(all_stmts_for_dispatch)
        self._dispatch_tables = self._dispatch_solver.get_dispatch_tables()
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

    self._all_closures: dict = {}  # outer_name → {inner_name → ClosureInfo}

    def _scan_for_closures(outer_name: str, outer_scope: dict, body: list):
        """Scan a function/method body for nested FunctionDefs and register them as closures."""
        def _all_stmts_nonfunc(stmts: list) -> list:
            """Return a list of statements recursively through control flow, not entering FunctionDef bodies."""
            result = []
            for s in stmts:
                result.append(s)
                if isinstance(s, FunctionDef):
                    continue
                for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                    sub = getattr(s, attr, None)
                    if isinstance(sub, list):
                        result.extend(_all_stmts_nonfunc(sub))
                for _cond, elif_body in getattr(s, 'elifs', []):
                    result.extend(_all_stmts_nonfunc(elif_body))
                for handler in getattr(s, 'handlers', []):
                    if hasattr(handler, 'body') and isinstance(handler.body, list):
                        result.extend(_all_stmts_nonfunc(handler.body))
            return result

        enriched_scope = dict(outer_scope)
        _saved_vt2 = dict(self.var_types)
        self.var_types.update(outer_scope)
        for bstmt in _all_stmts_nonfunc(body):
            if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                name = bstmt.target.name
                if name not in enriched_scope:
                    t = self._quick_type(bstmt.value)
                    # `original_emit = gen._emit` (a method taken as a value —
                    # the `_gen_stmt_TryStmt` emit-interception idiom): the
                    # body lowers this to a `MojoBoundMethod *` (see
                    # `_lower_bound_method_value`), but `_quick_type` reports
                    # the method's own return type (`void` / `int64_t`). A
                    # mismatched — or `void` — capture makes the env-struct
                    # field disagree with the body's local (hard C error).
                    if (isinstance(bstmt.value, MemberExpr)
                            and isinstance(bstmt.value.obj, IdentExpr)
                            and self.var_types.get(bstmt.value.obj.name, '').endswith(' *')):
                        _bmv_owner = gimple_exprtypes._struct_name_of(
                            self.var_types[bstmt.value.obj.name])
                        if (f"{_bmv_owner}_{bstmt.value.member}" in self.func_return_types
                                and bstmt.value.member not in self.struct_field_types.get(_bmv_owner, {})):
                            t = 'MojoBoundMethod *'
                    if t == 'void':
                        t = 'int64_t'
                    enriched_scope[name] = t
                    self.var_types[name] = t
            elif isinstance(bstmt, VarDecl):
                if bstmt.name not in enriched_scope:
                    t = self._quick_type(bstmt.value) if bstmt.value else 'int64_t'
                    if t == 'void':
                        t = 'int64_t'
                    enriched_scope[bstmt.name] = t
                    self.var_types[bstmt.name] = t
        self.var_types = _saved_vt2
        _sibling_cis: list = []   # (inner.name, ci, {names this ci calls})
        for stmt in _all_stmts_nonfunc(body):
            if not isinstance(stmt, FunctionDef):
                continue
            # `_as_funcdef_node`: identity in CPython, but its `-> FunctionDef`
            # annotation gives the self-hosted backend a real `FunctionDef *`
            # view of the otherwise-boxed loop element — without it `inner.name`
            # goes through dynamic getattr and the lifted symbol comes out
            # `outer_<garbage-bytes>`, the `_all_closures` key is garbage, and
            # every nested `def` degrades to a weak "unavailable" stub.
            inner     = _as_funcdef_node(stmt)
            if inner.is_async and not inner.is_generator:
                continue
            lifted    = f"{outer_name}_{inner.name}"
            used      = set()
            for body_node in inner.body:
                used |= _used_idents_node(body_node)
            inner_assign_targets = set()
            for bstmt in _all_stmts_nonfunc(inner.body):
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    inner_assign_targets.add(bstmt.target.name)
                elif isinstance(bstmt, ForStmt):
                    tgt = bstmt.target
                    if isinstance(tgt, str):
                        inner_assign_targets.add(tgt)
                    elif hasattr(tgt, 'name'):
                        inner_assign_targets.add(tgt.name)
            inner_declared = ({pn for pn, _ in inner.params}
                              | _declared_vars_body(inner.body)
                              | inner_assign_targets)
            outer_params = set(outer_scope.keys())
            free_globals = set(self.func_return_types.keys()) - outer_params
            free         = used - inner_declared - free_globals
            # `_as_str(v)`: elements of `sorted(free)` (a set-of-str) erase
            # to boxed int64_t under self-compile — without the static
            # `str` view `v in enriched_scope` would hash the pointer.
            captures     = []
            for v in sorted(free):
                v = _as_str(v)
                if v in enriched_scope:
                    captures.append((v, enriched_scope[v]))
            _cap_names_so_far = {_cn for _cn, _ in captures}
            _called_names = {nd.func.name for nd in _walk_ast(inner.body)
                              if isinstance(nd, CallExpr) and isinstance(nd.func, IdentExpr)}
            _transitive_mut: set = set()
            for _called in _called_names:
                _t_api = self._nested_async_api.get(f"{outer_name}::{_called}")
                if _t_api is None:
                    continue
                for _tn, _tt in (_t_api.get('captures') or []):
                    if _tn not in _cap_names_so_far and _tn in enriched_scope:
                        captures.append((_tn, enriched_scope[_tn]))
                        _cap_names_so_far.add(_tn)
                    if _tn in (_t_api.get('mut_capture_names') or frozenset()):
                        _transitive_mut.add(_tn)
            env_struct   = f"{lifted}_env" if len(captures) > 0 else ""
            ci           = ClosureInfo(lifted, env_struct, captures, inner)
            _inner_dflts = getattr(inner, 'param_defaults', None) or {}
            if _inner_dflts:
                self._func_param_defaults[lifted] = [
                    (_pn2, _dv2) for _pn2, _dv2 in _inner_dflts.items()]
            ci.mut_names = self._mutated_free_names(inner, _cap_names_so_far) | _transitive_mut
            if outer_name not in self._all_closures:
                self._all_closures[outer_name] = {}
            self._all_closures[outer_name][inner.name] = ci
            _sibling_cis.append((inner.name, ci, set(_called_names)))
            if inner.return_type is not None:
                self.func_return_types[lifted] = self._resolve_type(inner.return_type)
            else:
                for pname, ptype in inner.params:
                    self.var_types[pname] = self._resolve_type(ptype)
                self.func_return_types[lifted] = self._infer_return_type(inner.body)
                self.var_types.clear()
            inner_scope = dict(enriched_scope)
            for pn, pt in inner.params:
                inner_scope[pn] = self._resolve_type(pt)
            for bstmt in inner.body:
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    name = bstmt.target.name
                    if name not in inner_scope:
                        inner_scope[name] = self._quick_type(bstmt.value)
            _scan_for_closures(lifted, inner_scope, inner.body)

        # Mutually-recursive SIBLING closures (e.g. `_infer_param_types`'s
        # `scan_expr` <-> `scan_nodes`) each got their OWN env struct with
        # only their OWN captures. When one calls the other,
        # `_lower_sibling_closure_call` can forward only the fields whose
        # names match between the two envs — the callee's other captures
        # stay NULL and it SEGVs (`accessed_fields.add(...)` on NULL). Give
        # each connected call-group ONE shared env struct holding the UNION
        # of the group's captures, so any member can call any other by
        # passing its own (now identical-layout) env through.
        if len(_sibling_cis) > 1:
            _names_here = {n for n, _, _ in _sibling_cis}
            # Undirected sibling call graph (flat — no nested helper: this
            # runs inside gen_module_impl's own nested `_scan_for_closures`
            # and the self-host backend can't lift a 3-deep closure).
            _adj: dict = {}
            for _n in _names_here:
                _adj[_n] = []
            for _n, _ci_x, _cn in _sibling_cis:
                for _m in _cn:
                    if _m in _names_here and _m != _n:
                        if _m not in _adj[_n]:
                            _adj[_n].append(_m)
                        if _n not in _adj[_m]:
                            _adj[_m].append(_n)
            _seen_names: set = set()
            for _start in sorted(_names_here):
                if _start in _seen_names:
                    continue
                _stack = [_start]
                _members = []
                while _stack:
                    _cur = _stack.pop()
                    if _cur in _seen_names:
                        continue
                    _seen_names.add(_cur)
                    _members.append(_cur)
                    for _nb in _adj[_cur]:
                        if _nb not in _seen_names:
                            _stack.append(_nb)
                if len(_members) < 2:
                    continue
                _member_cis = [self._all_closures[outer_name][_m] for _m in _members]
                _merged_caps: dict = {}
                _merged_mut: list = []
                for _mci in _member_cis:
                    for _cv, _ct in _mci.captures:
                        if _cv not in _merged_caps:
                            _merged_caps[_cv] = _ct
                    for _mn in (getattr(_mci, 'mut_names', None) or []):
                        if _mn not in _merged_mut:
                            _merged_mut.append(_mn)
                if not _merged_caps:
                    continue
                _shared_env = outer_name + "_" + "_".join(sorted(_members)) + "_env"
                _merged_list = [(_cv, _merged_caps[_cv]) for _cv in sorted(_merged_caps)]
                _shared_mut = frozenset([_mn for _mn in _merged_mut if _mn in _merged_caps])
                for _mci in _member_cis:
                    _mci.captures = list(_merged_list)
                    _mci.env_struct = _shared_env
                    _mci.mut_names = _shared_mut

        def _find_re_sub_callbacks(search_body, context_outer):
            for stmt in search_body:
                stmts_to_check = []
                if isinstance(stmt, AssignStmt):
                    stmts_to_check.append(stmt.value)
                elif isinstance(stmt, ExprStmt):
                    stmts_to_check.append(stmt.value)  # ExprStmt uses .value
                elif hasattr(stmt, 'body'):
                    _find_re_sub_callbacks(getattr(stmt, 'body', []), context_outer)
                    for clause in ('orelse', 'handlers', 'finalbody'):
                        _find_re_sub_callbacks(getattr(stmt, clause, []), context_outer)
                for expr in stmts_to_check:
                    if not isinstance(expr, CallExpr):
                        continue
                    func = expr.func
                    if (isinstance(func, MemberExpr)
                            and isinstance(func.obj, IdentExpr)
                            and func.obj.name == 're'
                            and func.member == 'sub'
                            and len(expr.args) >= 2):
                        cb_arg = expr.args[1]
                        if isinstance(cb_arg, IdentExpr):
                            inner_map = self._all_closures.get(context_outer, {})
                            if cb_arg.name in inner_map:
                                inner_map[cb_arg.name].is_re_sub_callback = True
        _find_re_sub_callbacks(body, outer_name)

    for s in stmts:
        if isinstance(s, FunctionDef):
            s = _as_funcdef_node(s)   # real FunctionDef view: keeps `pname`/
            # `ptype` from `s.params` as `char *` so `outer_scope` is keyed
            # by the parameter NAME, not a boxed pointer — otherwise a
            # nested closure's `if v in enriched_scope` capture filter never
            # matches and every capture is silently dropped (`return add`
            # from a capturing closure came out a bare funcptr, no env).
            outer_scope: dict = {}
            for pname, ptype in s.params:
                _sh_ct = (None if _selfhost_fn_reassigns_method(s)
                          else _ggf_dup._selfhost_gen_self_param_ctype(self, pname, ptype, s))
                outer_scope[pname] = _sh_ct or self._resolve_type(ptype)
            _saved_vt = dict(self.var_types)
            self.var_types.update(outer_scope)
            for stmt in s.body:
                if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                    t = _mojo_type(stmt.type_ann)
                    outer_scope[stmt.name] = t
                    self.var_types[stmt.name] = t
                elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                    if stmt.target.name not in outer_scope:
                        t = self._quick_type(stmt.value)
                        outer_scope[stmt.target.name] = t
                        self.var_types[stmt.target.name] = t
            self.var_types = _saved_vt
            _scan_for_closures(s.name, outer_scope, s.body)
        elif isinstance(s, StructDef):
            _moids = self._struct_method_overload_ids(s)
            for method, _oid in zip(s.methods, _moids):
                outer_name = f"{s.name}_{method.name}{_oid}"
                outer_scope = {s.name.lower(): f"{s.name} *"}  # struct instance
                for pname, ptype in method.params:
                    if pname == 'self':
                        outer_scope['self'] = f"{s.name} *"
                    else:
                        outer_scope[pname] = self._resolve_type(ptype)
                for _cp_name in self._method_threaded_comptime_params.get((s.name, method.name), {}).get(_oid, []):
                    outer_scope[_cp_name] = 'int64_t'
                _saved_vt = dict(self.var_types)
                self.var_types.update(outer_scope)
                for stmt in method.body:
                    if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                        t = _mojo_type(stmt.type_ann)
                        outer_scope[stmt.name] = t
                        self.var_types[stmt.name] = t
                    elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                        if stmt.target.name not in outer_scope:
                            t = self._quick_type(stmt.value)
                            outer_scope[stmt.target.name] = t
                            self.var_types[stmt.target.name] = t
                self.var_types = _saved_vt
                _scan_for_closures(outer_name, outer_scope, method.body)

    _changed = True
    while _changed:
        _changed = False
        for _outer_name, _inner_map in list(self._all_closures.items()):
            for _inner_name, _ci in list(_inner_map.items()):
                _sub_closures = self._all_closures.get(_ci.lifted_name, {})
                if not _sub_closures:
                    continue
                _ci_param_names = {pn for pn, _ in _ci.inner_def.params}
                _ci_local_assigns = set()
                for _bstmt in _ci.inner_def.body:
                    if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                        _ci_local_assigns.add(_bstmt.target.name)
                _ci_own_vars = (_ci_param_names
                                | _declared_vars_body(_ci.inner_def.body)
                                | _ci_local_assigns)
                _ci_captures_dict = dict(_ci.captures)
                for _sub_ci in _sub_closures.values():
                    for _sv, _st in _sub_ci.captures:
                        if _sv not in _ci_own_vars and _sv not in _ci_captures_dict:
                            _ci.captures.append((_sv, _st))
                            _ci_captures_dict[_sv] = _st
                            if not _ci.env_struct:
                                _ci.env_struct = f"{_ci.lifted_name}_env"
                            _changed = True

    for _p3b_s in all_functions:
        if isinstance(_p3b_s, FunctionDef) and _p3b_s.return_type is None:
            _saved_vt_3b = self.var_types
            _saved_fcn_3b = self.current_func_name
            self.current_func_name = _p3b_s.name
            self.var_types = dict(_saved_vt_3b)
            for pname, ptype in _p3b_s.params:
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
            self.current_func_name = _saved_fcn_3b
            self.func_return_types[_p3b_s.name] = inferred

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
        elif isinstance(_value, (IntLiteral, BoolLiteral)):
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
                    # Everything else quick-types to int64_t here, matching
                    # this branch's old unconditional default.
                    qt2 = self._quick_type(_value)
                    return qt2 if qt2 == 'char *' else 'int64_t'
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
                return 'int64_t'
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

    def _phase17_set_gtype(_gname: str, _ctype: str):
        """Record a Phase 1.7 global-type conclusion into BOTH the
        whole-program-shared dict and THIS instance's own overlay (see
        `_own_global_var_types`/`_global_dst_ctype` for why the overlay
        must exist alongside the shared dict).

        `_gname: str` is load-bearing: without it the self-hosted compiler
        typed the param int64_t and `_own_global_var_types[_gname] = ...`
        keyed by the boxed pointer, so `_own_overlay_global_ctype` missed
        and a `var counter: Int = 0` module global was declared `int` (the
        IntLiteral default) instead of `int64_t` (the annotation)."""
        self._global_var_types[_gname] = _ctype
        self._own_global_var_types[_gname] = _ctype

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
        _phase17_set_gtype(_gname, _phase17_value_type(_value))
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
                    _pairs.append((_bstmt.target.name, _bstmt.value))
                elif isinstance(_bstmt, MultiAssignStmt):
                    for _tgt in _bstmt.targets:
                        if isinstance(_tgt, IdentExpr):
                            _pairs.append((_tgt.name, _bstmt.value))
                for _gname, _gvalue in _pairs:
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
        bugs/CODEGEN_generator_function_Lib_tarfile.md.

        Deliberately NOT self-recursive for the same reason
        `_phase17_scan_try_branches` isn't (a nested function calling
        itself here doesn't survive this file's own self-host build)
        — a nested if/elif/else inside one of THIS if's own branches
        is left unscanned (out of scope; no observed real-world
        instance needs it)."""
        _branch_lists = [_if_stmt.then_body or []]
        for _cond2, _elif_body2 in (getattr(_if_stmt, 'elifs', None) or []):
            _branch_lists.append(_elif_body2 or [])
        if isinstance(_if_stmt.else_body, list):
            _branch_lists.append(_if_stmt.else_body)
        _joined = {}
        for _blist in _branch_lists:
            for _bstmt in _flatten_resolved_conditionals(_blist):
                _pairs = []
                if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                    _pairs.append((_bstmt.target.name, _bstmt.value))
                elif isinstance(_bstmt, MultiAssignStmt):
                    for _tgt in _bstmt.targets:
                        if isinstance(_tgt, IdentExpr):
                            _pairs.append((_tgt.name, _bstmt.value))
                for _gname, _gvalue in _pairs:
                    _t = _phase17_value_type(_gvalue)
                    _joined[_gname] = (TypeLattice.join(_joined[_gname], _t)
                                       if _gname in _joined else _t)
        return _joined

    for _scan_stmt in _phase17_stmts:
        if isinstance(_scan_stmt, AssignStmt) and isinstance(_scan_stmt.target, IdentExpr):
            _gname = _scan_stmt.target.name
            if (isinstance(_scan_stmt.value, CallExpr)
                    and isinstance(_scan_stmt.value.func, MemberExpr)
                    and isinstance(_scan_stmt.value.func.obj, IdentExpr)
                    and _scan_stmt.value.func.obj.name == 're'
                    and _scan_stmt.value.func.member == 'compile'
                    and _scan_stmt.value.args
                    and isinstance(_scan_stmt.value.args[0], StringLiteral)):
                self._regex_patterns[_gname] = _scan_stmt.value.args[0].value
            if _gname in _pre_declared_globals:
                continue
            _pre_declared_globals.add(_gname)
            if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                self._global_to_module[_gname] = _phase17_mod
            _phase17_infer_global_type(_gname, _scan_stmt.value)
        elif isinstance(_scan_stmt, MultiAssignStmt):
            for _tgt in _scan_stmt.targets:
                if not isinstance(_tgt, IdentExpr):
                    continue
                _gname = _tgt.name
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
                _resolved = self._resolve_type(_scan_stmt.type_ann)
                _phase17_set_gtype(_scan_stmt.name, _resolved)
                if _resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
            else:
                if hasattr(_scan_stmt, 'value') and _scan_stmt.value:
                    if isinstance(_scan_stmt.value, DictExpr):
                        _phase17_set_gtype(_scan_stmt.name, 'MojoDict *')
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, (ListExpr, TupleExpr)):
                        _phase17_set_gtype(_scan_stmt.name, 'MojoList *')
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, SetExpr):
                        _phase17_set_gtype(_scan_stmt.name, 'MojoSet *')
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, StringLiteral):
                        _phase17_set_gtype(_scan_stmt.name, 'char *')
                    elif (isinstance(_scan_stmt.value, CallExpr)
                            and isinstance(_scan_stmt.value.func, IdentExpr)
                            and _scan_stmt.value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set', 'frozenset')):
                        _phase17_set_gtype(_scan_stmt.name, {
                            'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                            'list': 'MojoList *', 'List': 'MojoList *',
                            'set': 'MojoSet *', 'Set': 'MojoSet *',
                            'frozenset': 'MojoSet *',
                        }[_scan_stmt.value.func.name])
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, CallExpr):
                        if isinstance(_scan_stmt.value.func, IdentExpr):
                            ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                            if ret and ret.endswith(' *'):
                                _phase17_set_gtype(_scan_stmt.name, ret)
                            elif ret == 'char *':
                                _phase17_set_gtype(_scan_stmt.name, 'char *')
                            else:
                                _phase17_set_gtype(_scan_stmt.name, 'int64_t')
                        elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                and _scan_stmt.value.func.member in ('read', 'readline')
                                and not _scan_stmt.value.args):
                            _phase17_set_gtype(_scan_stmt.name, 'char *')
                        elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                and _scan_stmt.value.func.member == 'readlines'):
                            _phase17_set_gtype(_scan_stmt.name, 'MojoList *')
                        else:
                            _phase17_set_gtype(_scan_stmt.name, 'int64_t')
                    else:
                        qt = self._quick_type(_scan_stmt.value) or 'int64_t'
                        _phase17_set_gtype(_scan_stmt.name, qt if (qt.endswith(' *') or qt == '_Bool') else 'int64_t')
                else:
                    _phase17_set_gtype(_scan_stmt.name, 'int64_t')
        elif isinstance(_scan_stmt, TryStmt):
            for _gname, _gtype in _phase17_scan_try_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_set_gtype(_gname, _gtype)
        elif isinstance(_scan_stmt, IfStmt):
            for _gname, _gtype in _phase17_scan_if_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                _phase17_set_gtype(_gname, _gtype)
        elif (isinstance(_scan_stmt, ComptimeVarStmt)
                and isinstance(_scan_stmt.value, (ListExpr, TupleExpr))
                and _scan_stmt.target not in _pre_declared_globals):
            _pre_declared_globals.add(_scan_stmt.target)
            if _scan_stmt.target not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                self._global_to_module[_scan_stmt.target] = _phase17_mod
            _phase17_infer_global_type(_scan_stmt.target, _scan_stmt.value)

    def _phase17_collect_appends(_node_list, _append_hits):
        for _n in _node_list:
            if (isinstance(_n, ExprStmt)
                    and isinstance(_n.value, CallExpr)
                    and isinstance(_n.value.func, MemberExpr)
                    and _n.value.func.member == 'append'
                    and isinstance(_n.value.func.obj, IdentExpr)
                    and len(_n.value.args) == 1):
                _append_hits.setdefault(_n.value.func.obj.name, []).append(
                    self._quick_type(_n.value.args[0]))
            if isinstance(_n, FunctionDef):
                _saved = self.var_types
                self.var_types = dict(_saved)
                for _pname, _ptype in (_n.params or []):
                    if _ptype:
                        self.var_types[_pname] = _mojo_type(_ptype)
                for _lname, _ltype in self._infer_local_var_types(_n).items():
                    if _lname not in self.var_types:
                        self.var_types[_lname] = _ltype
                _phase17_collect_appends(_n.body or [], _append_hits)
                self.var_types = _saved
            elif isinstance(_n, IfStmt):
                _phase17_collect_appends(_n.then_body or [], _append_hits)
                if _n.else_body:
                    _phase17_collect_appends(_n.else_body, _append_hits)
                for _cond2, _ebody2 in (_n.elifs or []):
                    _phase17_collect_appends(_ebody2 or [], _append_hits)
            elif isinstance(_n, (WhileStmt, ForStmt)):
                _phase17_collect_appends(_n.body or [], _append_hits)
                if getattr(_n, 'else_body', None):
                    _phase17_collect_appends(_n.else_body, _append_hits)
            elif isinstance(_n, TryStmt):
                _phase17_collect_appends(_n.body or [], _append_hits)
                for _h in (_n.handlers or []):
                    _phase17_collect_appends(getattr(_h, 'body', None) or [], _append_hits)
                if isinstance(_n.else_body, list):
                    _phase17_collect_appends(_n.else_body, _append_hits)
                if isinstance(getattr(_n, 'finally_body', None), list):
                    _phase17_collect_appends(_n.finally_body, _append_hits)
            elif isinstance(_n, WithStmt):
                _phase17_collect_appends(_n.body or [], _append_hits)

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
        for _s in stmt_list:
            if isinstance(_s, ImportStmt):
                for _tm, _ta in _import_targets(_s):
                    _local = _ta if _ta else _tm
                    if _local not in self._global_var_types:
                        self._global_var_types[_local] = 'int64_t'
                        self._global_c_decl_types[_local] = 'int64_t'
                        if _local not in self._global_to_module:
                            self._global_to_module[_local] = _phase17_mod
            elif isinstance(_s, TryStmt):
                _scan_try_imports(_s.body or [])
                for _h in (_s.handlers or []):
                    _scan_try_imports(getattr(_h, 'body', []) or [])
            elif isinstance(_s, IfStmt):
                _scan_try_imports(_s.then_body or [])
                if isinstance(_s.else_body, list):
                    _scan_try_imports(_s.else_body)
    _scan_try_imports(stmts + (imported_stmts if (self.do_imports or self.link_imports) else []))

    _EARLY_DISPATCH_DICTS = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                             '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
    _EARLY_DISPATCH_SETS = {'_CMP_OPS'}
    for _gn, _gt in list(self._global_var_types.items()):
        if _gn in self._global_c_decl_types:
            continue
        if _gn in _EARLY_DISPATCH_DICTS:
            self._global_c_decl_types[_gn] = 'MojoDict *'
        elif _gn in _EARLY_DISPATCH_SETS:
            self._global_c_decl_types[_gn] = 'MojoSet *'
        elif _gt in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            self._global_c_decl_types[_gn] = 'int64_t'  # boxed by default
        else:
            self._global_c_decl_types[_gn] = _gt

    func_parts: list[str] = []

    _emitted_closures: set[str] = set()
    _emitted_env_allocs: set[str] = set()  # `_alloc_<env>` bodies — a merged
    # mutually-recursive sibling-closure GROUP shares one env struct, so its
    # allocator must be emitted exactly once (a second definition is a hard
    # C redefinition error).

    def _emit_closure_recursive(ci, outer_name: str = None) -> None:
        """Emit sub-closures first (depth-first), then this closure's allocator + body."""
        if ci.lifted_name in _emitted_closures:
            return
        _emitted_closures.add(ci.lifted_name)
        for sub_ci in self._all_closures.get(ci.lifted_name, {}).values():
            _emit_closure_recursive(sub_ci, ci.lifted_name)
        if ci.env_struct and ci.env_struct not in _emitted_env_allocs:
            _emitted_env_allocs.add(ci.env_struct)
            alloc_fn = f"_alloc_{ci.env_struct}"
            func_parts.append(
                f"{ci.env_struct} * __GIMPLE {alloc_fn} (void)\n"
                f"{{\n"
                f"  {ci.env_struct} * _e;\n"
                f"  void * _vp;\n"
                f"\nbb_2:\n"
                f"  _vp = malloc (sizeof({ci.env_struct}));\n"
                f"  _e = ({ci.env_struct} *) _vp;\n"
                f"  return _e;\n"
                f"}}"
            )
            func_parts.append('')
        func_parts.append(self._gen_lifted_closure(ci, outer_name))
        func_parts.append('')

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
    for _ts in stmts:
        if isinstance(_ts, (AssignStmt, AugAssignStmt, ExprStmt, IfStmt, WhileStmt, ForStmt, TryStmt, WithStmt, PassStmt, BreakStmt, ContinueStmt, ReturnStmt, RaiseStmt, AssertStmt, VarDecl)):
            for _n in _walk_ast(_ts):
                if isinstance(_n, CallExpr) and isinstance(_n.func, IdentExpr) and _n.func.name == 'main':
                    self._toplevel_calls_main = True
                    break
            if self._toplevel_calls_main:
                break

    for stmt in stmts:
        if isinstance(stmt, FunctionDef):
            if (stmt.name in self._supported_generators or stmt.name in self._supported_async
                    or stmt.name in self._supported_async_gen):
                continue
            if stmt.name in self._unsupported_generator_names:
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
                    _emit_closure_recursive(ci, stmt.name)
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
                method_outer_name = f"{stmt.name}_{m.name}{overload_id}"
                _method_outer_scope = self._push_import_scope()
                self._collect_body_import_bindings(m.body, _method_outer_scope)
                for ci in self._all_closures.get(method_outer_name, {}).values():
                    _emit_closure_recursive(ci, method_outer_name)
                self._lambda_parts = []
                func_parts.append(self._gen_struct_method(stmt.name, m, overload_id))
                func_parts.append('')
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
                if m.params and any(pn.startswith('*') for pn, _ in m.params):
                    ptypes = 'MojoList *'
                else:
                    ptypes = (', '.join(self._resolve_type(pt) for _, pt in m.params)
                              if m.params else 'void')
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

    func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
    for fdef in func_defs:
        if fdef.name == 'main':
            continue
        if fdef.params and any(pn.startswith('*') for pn, _ in fdef.params):
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
        toplevel_func = self._gen_toplevel(toplevel_stmts)
        func_parts.append(toplevel_func)
        func_parts.append('')
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
        '#include <mojo_runtime.h>',
        '#include <mojo_sqlite3.h>',
        '#include <mojo_zlib.h>',
        '#include <mojo_ssl.h>',
        '#include <mojo_ncurses.h>',
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
        '/* Undefine exception-name macros from mojo_runtime.h that clash with',
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
    parts.extend([
        '/* Mojo iterator and utility functions */',
        *_util_stubs,
        '',
        '/* Struct ___new stubs (for Self(...) call sites) */',
        *[f'int64_t {s}___new(...);' for s in sorted(self._self_ctor_stubs)],
        '',
        '/* Renamed C-reserved builtins called without import (e.g. abs→mojo_abs) */',
        *[f'{rt} {fn}(...);'
          for fn, rt in sorted(self._renamed_builtin_calls.items())
          if fn not in _skip_util and fn not in _imported_names
          and fn not in _local_funcs and fn not in _local_funcs_renamed
          and fn not in _imported_names_renamed],
        '',
        '',
        'char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename);',
        'char *compile_to_gimple(char *mojo_src, int do_imports, char *filename);',
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

    all_modules_to_declare = set()

    if our_mod != "root":
        all_modules_to_declare.add("root")

    all_modules_to_declare.update(self._module_globals.keys())

    all_scan_for_mods = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    for _ms in all_scan_for_mods:
        if isinstance(_ms, ImportStmt):
            for _mn, _ in _import_targets(_ms):
                if _mn and not _mn.startswith('_'):
                    all_modules_to_declare.add(_mn)
        elif isinstance(_ms, FromImportStmt):
            _mn = _ms.module
            if _mn and not _mn.startswith('_') and '.' not in _mn:
                all_modules_to_declare.add(_mn)

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
        _type_name_set = set(self.struct_field_types)
        for _dspk in _STMT_DISPATCH.keys():
            _type_name_set.add('' + _dspk)
        for _dspk in _EXPR_DISPATCH.keys():
            _type_name_set.add('' + _dspk)
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
        mod_str = mod_s if mod_s else "root"
        safe_mod = _c_field_name(mod_str) if mod_str else "root"
        struct_name = f"_{safe_mod}_toplev"
        global_var = f"_{safe_mod}_globals"
        _known_fields = self._module_globals.get(mod_str)
        if _known_fields:
            _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_mod}'
            parts.append(f'#ifndef {_toplev_guard}')
            parts.append(f'#define {_toplev_guard}')
            parts.append(f'typedef struct {struct_name} {{')
            for _kf_name, _kf_ctype, _ in _known_fields:
                parts.append(f'  {_kf_ctype} {_c_field_name(_kf_name)};')
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
        _argstr = ', '.join(_eargs) if _eargs else 'void'
        parts.append(f'extern {_eret} {_ecname} ({_argstr});')

    _module_globals_insert_idx = len(parts)
    if imported_code:
        parts.append('')
        parts.extend(imported_code)

    new_helpers = self._ptr_helpers_needed - self._emitted_ptr_helpers
    for et in sorted(new_helpers):
        cn = _c_id(et)
        parts.append(
            f"static {et} * _mojo_at_{cn} ({et} * p, int64_t n) {{ return p + n; }}"
        )
        self._emitted_ptr_helpers.add(et)
    if new_helpers:
        parts.append('')

    global_decls = []  # kept for compatibility, but won't be emitted
    current_mod_name = self.module_name if len(self.module_name) > 0 else "root"
    if current_mod_name not in self._module_globals:
        self._module_globals[current_mod_name] = []
        self._module_global_inits[current_mod_name] = {}
    _dispatch_dict_names = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                            '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
    _dispatch_set_names = {'_CMP_OPS'}
    _dispatch_names = _dispatch_dict_names | _dispatch_set_names
    _declared_globals = set()
    all_scan = stmts
    for stmt in all_scan:
        if isinstance(stmt, FromImportStmt):
            for alias in stmt.names:
                orig_name = alias[0]
                local_name = alias[1] if len(alias) > 1 and alias[1] else orig_name
                for check_name in (orig_name, local_name):
                    if check_name in _dispatch_dict_names and check_name not in _declared_globals:
                        global_decls.append(f"MojoDict * {check_name};")
                        _declared_globals.add(check_name)
                        self._global_c_decl_types[check_name] = 'MojoDict *'
                        self._global_var_types[check_name] = 'MojoDict *'
                    elif check_name in _dispatch_set_names and check_name not in _declared_globals:
                        global_decls.append(f"MojoSet * {check_name};")
                        _declared_globals.add(check_name)
                        self._global_c_decl_types[check_name] = 'MojoSet *'
                        self._global_var_types[check_name] = 'MojoSet *'
        elif isinstance(stmt, ImportStmt):
            for _tm, _ta in _import_targets(stmt):
                local_name = _ta if _ta else _tm
                if local_name not in _declared_globals:
                    global_decls.append(f"int64_t {local_name};")
                    _declared_globals.add(local_name)
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
                # See bugs/COMPILE_FAIL_Tools_cases_generator_parser.md.
                if local_name not in self.imported_symbols:
                    self.imported_symbols[local_name] = {
                        'module': _tm,
                        'return_type': 'unknown',
                    }
                self._module_alias_names.add(local_name)
    def _collect_global_stmts(stmt_list):
        result = []
        for _gs in stmt_list:
            result.append(_gs)
            if isinstance(_gs, TryStmt):
                result.extend(_collect_global_stmts(_gs.body or []))
                for _h in (_gs.handlers or []):
                    result.extend(_collect_global_stmts(getattr(_h, 'body', []) or []))
                result.extend(_collect_global_stmts(_gs.else_body or [] if isinstance(_gs.else_body, list) else []))
                result.extend(_collect_global_stmts(_gs.finally_body or [] if isinstance(_gs.finally_body, list) else []))
            elif isinstance(_gs, IfStmt):
                result.extend(_collect_global_stmts(_gs.then_body or []))
                result.extend(_collect_global_stmts(_gs.else_body or []))
        return result

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
        declared, i.e. 'struct _X_toplev has no member named NAME'."""
        if isinstance(value, DictExpr):
            if gname in _dispatch_names:
                global_decls.append(f"MojoDict * {gname};")
                self._global_c_decl_types[gname] = 'MojoDict *'
            else:
                global_decls.append(f"int64_t {gname};  /* MojoDict * */")
                self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoDict *'
        elif isinstance(value, (ListExpr, TupleExpr)):
            if gname in _dispatch_names:
                global_decls.append(f"MojoList * {gname};")
                self._global_c_decl_types[gname] = 'MojoList *'
            else:
                global_decls.append(f"int64_t {gname};  /* MojoList * */")
                self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoList *'
        elif isinstance(value, SetExpr):
            if gname in _dispatch_names:
                global_decls.append(f"MojoSet * {gname};")
                self._global_c_decl_types[gname] = 'MojoSet *'
            else:
                global_decls.append(f"int64_t {gname};  /* MojoSet * */")
                self._global_c_decl_types[gname] = 'int64_t'
            self._global_var_types[gname] = 'MojoSet *'
        elif isinstance(value, (IntLiteral, BoolLiteral)):
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
                    global_decls.append(f"{ret} {gname};")
                    self._global_var_types[gname] = ret
                    self._global_c_decl_types[gname] = ret
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

    for stmt in _collect_global_stmts(all_global_scan):
        if isinstance(stmt, VarDecl):
            gname = stmt.name
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
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
                        global_decls.append(f"{_ret} {gname};")
                        self._global_var_types[gname] = _ret
                        self._global_c_decl_types[gname] = _ret
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
            gname = stmt.target.name
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            _gscan_declare_global(gname, stmt.value)
        elif (isinstance(stmt, ComptimeVarStmt)
                and isinstance(stmt.value, (ListExpr, TupleExpr))):
            gname = stmt.target
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            _gscan_declare_global(gname, stmt.value)
        elif isinstance(stmt, MultiAssignStmt):
            for _tgt in stmt.targets:
                if not isinstance(_tgt, IdentExpr):
                    continue
                gname = _tgt.name
                if gname in _declared_globals:
                    continue
                _declared_globals.add(gname)
                _gscan_declare_global(gname, stmt.value)
        elif isinstance(stmt, VarDecl) and stmt.name not in _declared_globals:
            _declared_globals.add(stmt.name)
            ctype = self._resolve_type(stmt.type_ann) if stmt.type_ann else 'int64_t'
            global_decls.append(f"{ctype} {stmt.name};")
            self._global_var_types[stmt.name] = ctype
            self._global_c_decl_types[stmt.name] = ctype
        elif isinstance(stmt, ImportStmt):
            for _tm, _ta in _import_targets(stmt):
                local_name = _ta if _ta else _tm
                if local_name not in _declared_globals:
                    _declared_globals.add(local_name)
                    global_decls.append(f"int64_t {local_name};")
                    self._global_var_types[local_name] = 'int64_t'
                    self._global_c_decl_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name

    for gname in sorted(_declared_globals):   # sorted: deterministic field order for bootstrap
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
            else:
                c_type = 'void *' if (g_mtype and g_mtype.endswith(' *')) else (
                    g_mtype if g_mtype and g_mtype in ('MojoDict *', 'MojoList *', 'MojoSet *', 'char *') else 'int64_t')
            init_code = '0'
            for stmt in _collect_global_stmts(all_global_scan):
                if isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr) and stmt.target.name == gname:
                    init_code = _extract_init_expr(stmt.value)
                    break
                elif (isinstance(stmt, MultiAssignStmt)
                        and any(isinstance(_t, IdentExpr) and _t.name == gname for _t in stmt.targets)):
                    init_code = _extract_init_expr(stmt.value)
                    break
                elif isinstance(stmt, ImportStmt) and gname in (
                        (_ta if _ta else _tm) for _tm, _ta in _import_targets(stmt)):
                    init_code = '0'
                    break
            if (gname, c_type, g_mtype) not in self._module_globals[current_mod_name]:
                self._module_globals[current_mod_name].append((gname, c_type, g_mtype))
                self._module_global_inits[current_mod_name][gname] = init_code
                self._global_to_module[gname] = current_mod_name

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
        for gname, c_type, _ in globals_list:
            globals_struct_lines.append(f"  {c_type} {_c_field_name(gname)};")
        globals_struct_lines.append(f"}} {typedef_name};")
        globals_struct_lines.append('#endif')
        globals_struct_lines.append("")

        instance_name = f"_{safe_name}_globals"
        globals_struct_lines.append(f"struct {typedef_name} {instance_name} = {{")
        inits = self._module_global_inits.get(current_mod_name, {})

        for gname, c_type, _ in globals_list:
            init_val = inits.get(gname)
            if not init_val or init_val == '0' or 'mojo_' in str(init_val) or 'new' in str(init_val):
                if c_type.endswith(' *'):
                    init_val = f'({c_type})0'
                else:
                    init_val = '0'
            elif init_val.startswith('"') or init_val.startswith("'"):
                pass
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

        for gname, c_type, _ in globals_list:
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
    _gg_syn = getattr(self, '_selfhost_gimplegen_stmts', None)
    if (_gg_syn is not None and 'GimpleGen' in self._class_attrs
            and not any(isinstance(s, StructDef) and s.name == 'GimpleGen'
                        for s in _cai_structs)):
        _cai_structs.append(_gg_syn)
    for s in _cai_structs:
        if isinstance(s, StructDef):
            class_attrs = self._class_attrs
            for aname, mangled in class_attrs.get(s.name, {}).items():
                for field in s.fields:
                    if isinstance(field, AssignStmt) and isinstance(field.target, IdentExpr) and field.target.name == aname:
                        v = field.value
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
                            inits = [f"  {mangled} = mojo_set_new();"]
                            _set_elts = (_lit_v.elements
                                         if isinstance(_lit_v, (SetExpr, ListExpr, TupleExpr))
                                         else [])
                            for elt in _set_elts:
                                if isinstance(elt, StringLiteral):
                                    inits.append(f'  mojo_set_add_str ({mangled}, "{_c_escape(elt.value)}");')
                                elif isinstance(elt, IntLiteral):
                                    inits.append(f'  mojo_set_add_int ({mangled}, {elt.value});')
                            class_attr_inits.extend(inits)
                        elif ctype == 'MojoDict *':
                            _di = [f"  {mangled} = mojo_dict_new();"]
                            _pairs = _lit_v.pairs if isinstance(_lit_v, DictExpr) else []
                            _all_str = bool(_pairs) and all(
                                isinstance(k, StringLiteral) and isinstance(vv, StringLiteral)
                                for k, vv in _pairs)
                            if _all_str:
                                for k, vv in _pairs:
                                    _di.append(
                                        f'  mojo_dict_set_str ({mangled}, "{_c_escape(k.value)}", '
                                        f'"{_c_escape(vv.value)}");')
                                self._global_dict_val_types[mangled] = 'char *'
                                class_attr_inits.extend(_di)
                            else:
                                class_attr_inits.append(f"  {mangled} = mojo_dict_new();")
                        elif ctype == 'MojoList *':
                            inits = [f"  {mangled} = mojo_list_new();"]
                            _lst_elts = (_lit_v.elements
                                         if isinstance(_lit_v, (ListExpr, TupleExpr, SetExpr))
                                         else [])
                            for elt in _lst_elts:
                                if isinstance(elt, StringLiteral):
                                    inits.append(f'  mojo_list_append_str ({mangled}, "{_c_escape(elt.value)}");')
                                elif isinstance(elt, IntLiteral):
                                    inits.append(f'  mojo_list_append_int ({mangled}, {elt.value});')
                                else:
                                    inits = None
                                    break
                            if inits is None:
                                class_attr_inits.append(f"  {mangled} = mojo_list_new();")
                            else:
                                class_attr_inits.extend(inits)
                        elif isinstance(v, StringLiteral):
                            ctype = 'char *'
                            class_attr_inits.append(f'  {mangled} = "{_c_escape(v.value)}";')
                        elif isinstance(v, IntLiteral):
                            ctype = 'int64_t'
                            class_attr_inits.append(f'  {mangled} = {v.value};')
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
                        field_ctype = f"{vtype} *" if vname in ci.mut_names else vtype
                        parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                    parts.append(f"}} {ci.env_struct};")
                    parts.append('')
                    self._emitted_structs.add(ci.env_struct)

        if self._dispatch_solver and len(self._dispatch_tables) > 0:
            for callee_set, dispatch_table in self._dispatch_tables.items():
                if dispatch_table.name not in self._emitted_dispatch_typedefs:
                    typedef = dispatch_table.emit_typedef()
                    if typedef:
                        parts.append(typedef)
                        parts.append('')
                        self._emitted_dispatch_typedefs.add(dispatch_table.name)

    for sn in sorted(self._struct_allocs_needed):
        # `sn` is a struct-name string; the compiled backend erased it to
        # int64_t (the sorted-set element type never got seeded in time —
        # see `_struct_allocs_needed`'s `set[str]` annotation), so
        # `f'_alloc_{sn}'` emitted `_alloc_<pointer-decimal>`. Re-view it
        # as `str`.
        sn = _as_str(sn)
        if sn in self._emitted_allocs:
            continue  # already emitted by an imported module
        self._emitted_allocs.add(sn)
        alloc_name = f'_alloc_{sn}'
        if alloc_name not in self.func_return_types:
            self.func_return_types[alloc_name] = f'{sn} *'
        class_attrs = self._class_attrs.get(sn, {})
        field_map = self.struct_field_types.get(sn, {})
        attr_inits = ''.join(
            f"  _p->{_safe_field(aname)} = {gname};\n"
            for aname, gname in sorted(class_attrs.items())
            if aname in field_map
            and field_map[aname] == self._global_var_types.get(gname, field_map[aname])
        )
        parts.append(
            f"static {sn} * __GIMPLE _alloc_{sn} (void)\n"
            f"{{\n"
            f"  {sn} * _p;\n"
            f"  void * _vp;\n"
            f"  int64_t _tag;\n"
            f"\nbb_2:\n"
            f"  _vp = calloc (1, sizeof({sn}));\n"
            f"  _p = ({sn} *) _vp;\n"
            f"  _tag = (int64_t){_struct_type_id(sn)};\n"
            f"  _p->__mojo_type_id = _tag;\n"
            f"{attr_inits}"
            f"  return _p;\n"
            f"}}"
        )
        parts.append('')

    if self.emit_struct_defs:
        reflect_structs = sorted(set(self.struct_field_types.keys())
                                  & self._emitted_structs & self._struct_allocs_needed)
        refl_parts = []
        for sn in reflect_structs:
            fields = self.struct_field_types.get(sn, {})
            if not fields:
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
                + "".join(f'  mojo_list_append_str(_r, {nl});\n' for nl in name_lits) +
                f"  return _r;\n}}\n"
                + asdict_part
            )
        repr_fwd_decls = [f"static char * _mojo_repr_{sn} ({sn} *obj);" for sn in reflect_structs
                           if self.struct_field_types.get(sn)]
        for sn in reflect_structs:
            fields = self.struct_field_types.get(sn, {})
            if not fields:
                continue
            boxed = self.struct_boxed_fields.get(sn, set())
            bool_fields = self.struct_bool_fields.get(sn, set())
            nullable_containers = self.struct_nullable_container_fields.get(sn, set())
            part_exprs = []
            for fname, ftype in fields.items():
                if fname == '__mojo_type_id':
                    continue
                safe_f = _safe_field(fname)
                fref = f'obj->{safe_f}'
                if sn == 'IntLiteral' and fname == 'value' and 'raw' in fields:
                    raw_fref = f"obj->{_safe_field('raw')}"
                    val_expr = (f'(({raw_fref} && {raw_fref}[0]) '
                                f'? mojo_int_literal_decimal({raw_fref}) '
                                f': mojo_repr_int((int64_t){fref}))')
                elif fname in bool_fields:
                    val_expr = f'({fref} ? "True" : "False")'
                elif fname in boxed and ftype in (
                        'int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                        'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                    val_expr = f'_mojo_generic_elem_repr((int64_t){fref})'
                elif ftype == 'char *':
                    val_expr = f'({fref} ? mojo_repr_str({fref}) : "None")'
                elif ftype == '_Bool':
                    val_expr = f'({fref} ? "True" : "False")'
                elif ftype in ('double', 'float'):
                    val_expr = f'mojo_repr_float((double){fref})'
                elif ftype == 'MojoList *':
                    if self._field_elem_types.get(sn, {}).get(fname) == 'double':
                        list_repr = f'mojo_repr_list_doubles({fref})'
                    else:
                        list_repr = f'_mojo_repr_list({fref})'
                    if fname in nullable_containers:
                        val_expr = f'({fref} ? {list_repr} : "None")'
                    else:
                        val_expr = list_repr
                elif ftype == 'MojoDict *':
                    if fname in nullable_containers:
                        val_expr = f'({fref} ? _mojo_repr_dict({fref}) : "None")'
                    else:
                        val_expr = f'_mojo_repr_dict({fref})'
                elif ftype in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                               'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t'):
                    val_expr = f'mojo_repr_int((int64_t){fref})'
                elif ftype.endswith(' *'):
                    val_expr = f'({fref} ? _mojo_dispatch_repr((void *){fref}) : "None")'
                else:
                    val_expr = f'mojo_repr_int((int64_t){fref})'
                part_exprs.append(f'"{fname}=", {val_expr}')
            cat_chain = f'strdup("{sn}(")'
            for i, pe in enumerate(part_exprs):
                sep = ', ' if i > 0 else ''
                if sep:
                    cat_chain = f'mojo_str_cat({cat_chain}, ", ")'
                name_lit, val_e = pe.split(', ', 1)
                cat_chain = f'mojo_str_cat({cat_chain}, {name_lit})'
                cat_chain = f'mojo_str_cat({cat_chain}, {val_e})'
            cat_chain = f'mojo_str_cat({cat_chain}, ")")'
            refl_parts.append(
                f"static char * _mojo_repr_{sn} ({sn} *obj) {{\n"
                f"  if (!obj) return \"None\";\n"
                f"  return {cat_chain};\n"
                f"}}\n"
            )
        parts.append("static char * _mojo_dispatch_repr (void *);")
        parts.append("static char * _mojo_repr_list (MojoList *);")
        parts.append("static char * _mojo_repr_dict (MojoDict *);")
        parts.append("static char * _mojo_generic_elem_repr (int64_t);")
        if repr_fwd_decls:
            parts.append("/* Forward decls for generic repr() (mutual struct references) */")
            parts.append("\n".join(repr_fwd_decls))
            parts.append('')
        if True:
            parts.append("/* Generic reflection dispatch (getattr/setattr/dataclasses.fields/is_dataclass) */")
            parts.extend(refl_parts)
            tag_cases_get = "\n".join(
                f'  if (_tag == {_struct_type_id(sn)}) return _mojo_getattr_{sn}(({sn} *)obj, attr);'
                for sn in reflect_structs if self.struct_field_types.get(sn))
            tag_cases_set = "\n".join(
                f'  if (_tag == {_struct_type_id(sn)}) {{ _mojo_setattr_{sn}(({sn} *)obj, attr, val); return; }}'
                for sn in reflect_structs if self.struct_field_types.get(sn))
            tag_cases_fields = "\n".join(
                f'  if (_tag == {_struct_type_id(sn)}) return _mojo_fieldnames_{sn}();'
                for sn in reflect_structs if self.struct_field_types.get(sn))
            tag_cases_asdict = "\n".join(
                f'  if (_tag == {_struct_type_id(sn)}) return _mojo_asdict_{sn}(({sn} *)obj);'
                for sn in reflect_structs if self.struct_field_types.get(sn))
            tag_set_literal = ", ".join(
                str(_struct_type_id(sn)) for sn in reflect_structs if self.struct_field_types.get(sn))
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
                for sn in reflect_structs if self.struct_field_types.get(sn))
            tag_cases_repr_elem = "\n".join(
                f'    if (_tag == {_struct_type_id(sn)}) return _mojo_repr_{sn}(({sn} *)(intptr_t)val);'
                for sn in reflect_structs if self.struct_field_types.get(sn))
            parts.append(
                ("static char * _mojo_dispatch_repr (void *obj) {\n"
                 "  if (!obj) return \"None\";\n"
                 "  int64_t _tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);\n")
                + f"{tag_cases_repr}\n"
                + ("  return mojo_repr_obj((int64_t)(intptr_t)obj);\n"
                   "}\n"
                   "static char * _mojo_generic_elem_repr (int64_t val) {\n"
                   "  if (val == 0) return \"None\";\n"
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
                   "static char * _mojo_repr_list (MojoList *lst) {\n"
                   "  int _is_tup = lst && mojo_is_tuple(lst);\n"
                   "  if (!lst) return _is_tup ? \"()\" : \"[]\";\n"
                   "  int64_t _n = mojo_list_len(lst);\n"
                   "  char *_buf = strdup(_is_tup ? \"(\" : \"[\");\n"
                   "  for (int64_t _i = 0; _i < _n; _i++) {\n"
                   "    if (_i > 0) _buf = mojo_str_cat(_buf, \", \");\n"
                   "    _buf = mojo_str_cat(_buf, _mojo_generic_elem_repr(mojo_list_get_int(lst, _i)));\n"
                   "  }\n"
                   "  if (_is_tup && _n == 1) _buf = mojo_str_cat(_buf, \",\");\n"
                   "  return mojo_str_cat(_buf, _is_tup ? \")\" : \"]\");\n"
                   "}\n"
                   "static char * _mojo_repr_dict (MojoDict *d) {\n"
                   "  if (!d) return \"{}\";\n"
                   "  int _is_booldict = mojo_is_bool_dict(d);\n"
                   "  char *_buf = strdup(\"{\");\n"
                   "  int64_t *_order = mojo_dict_order_indices(d);\n"
                   "  for (int64_t _oi = 0; _oi < d->used; _oi++) {\n"
                   "    int64_t _i = _order[_oi];\n"
                   "    if (_oi > 0) _buf = mojo_str_cat(_buf, \", \");\n"
                   "    _buf = mojo_str_cat(_buf, mojo_repr_str(d->slots[_i].key));\n"
                   "    _buf = mojo_str_cat(_buf, \": \");\n"
                   "    if (_is_booldict)\n"
                   "      _buf = mojo_str_cat(_buf, d->slots[_i].val ? \"True\" : \"False\");\n"
                   "    else\n"
                   "      _buf = mojo_str_cat(_buf, _mojo_generic_elem_repr(d->slots[_i].val));\n"
                   "  }\n"
                   "  free(_order);\n"
                   "  return mojo_str_cat(_buf, \"}\");\n"
                   "}\n"
                )
            )
            parts.append('')

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
    for sym_name in sorted(self.imported_symbols.keys()):
        if sym_name in hardcoded:
            continue
        sym_info = self.imported_symbols[sym_name]
        if sym_info.get('return_type') == 'unknown':
            continue
        if sym_name in inline_defined or sym_name in self._global_inline_defs:
            continue
        if sym_name in self.struct_field_types:
            continue
        if sym_name in self._LIBC_DECLARED and sym_name not in _C_RESERVED_FUNCS:
            continue

        module = sym_info.get('module', '')
        if module in _stub_only_modules:
            cname = _safe_name(sym_name)
            if cname in _emitted_unresolved_stub_syms:
                continue
            _emitted_unresolved_stub_syms.add(cname)
            ret_type = sym_info.get('return_type', 'int64_t')
            ret_type = self._resolve_type(ret_type) if ret_type and ret_type != 'unknown' else 'int'
            if ret_type == 'void':
                body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); }}'
            else:
                body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); return ({ret_type})0; }}'
            _stub_only_guard = _stub_guard_name(cname)
            parts.append(f"#ifndef {_stub_only_guard}\n#define {_stub_only_guard}\n"
                          f"{ret_type} {cname} () {body}  /* stub from {module} */\n#endif")
            continue

        safe = self._func_csym(sym_name)
        if 'signature' in sym_info:
            if sym_name in _C_RESERVED_FUNCS:
                ret_type = sym_info.get('c_return_type') or sym_info.get('return_type', 'int64_t')
                if ret_type and ret_type != 'unknown' and not any(
                        c in ret_type for c in ('*', ' ', 'int', 'char', 'void', 'float', 'double')):
                    ret_type = self._resolve_type(ret_type)
                elif not ret_type or ret_type == 'unknown':
                    ret_type = 'int64_t'
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")
            else:
                signature = sym_info['signature']
                orig_name = sym_info.get('original_name', sym_name)
                if safe != orig_name:
                    signature = re.sub(r'\b' + re.escape(orig_name) + r'\b', safe, signature, count=1)
                signature = re.sub(
                    r'\b(inout|borrowed|owned|borrow|out|mut|ref|read|copy|var)\s+(?=\w)',
                    '', signature)
                for _ckw in ('default', 'register', 'auto', 'static', 'extern',
                             'volatile', 'inline'):
                    signature = re.sub(r'\b' + _ckw + r'\b(?=\s*[,)])', f'_kw_{_ckw}', signature)
                parts.append(f"#ifndef {safe}\nextern {signature};  /* from {module} */\n#endif")
        else:
            ret_type = sym_info.get('return_type', 'int64_t')
            ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
            if self.do_imports or self.link_imports:
                if safe in _emitted_unresolved_stub_syms:
                    continue
                _emitted_unresolved_stub_syms.add(safe)
                if ret_type == 'void':
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); }}'
                else:
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); return ({ret_type})0; }}'
                _unresolved_guard = _stub_guard_name(safe)
                parts.append(f"#ifndef {_unresolved_guard}\n#define {_unresolved_guard}\n"
                              f"__attribute__((weak)) {ret_type} {safe} (...) {body}  /* stub from {module} */\n#endif")
            else:
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")

    if self.imported_symbols:
        parts.append('')

    func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
    if self._supported_generators or self._generator_method_api:
        parts.append('typedef struct MojoGenerator MojoGenerator;')
        for _api in list(self._generator_api.values()) + list(self._generator_method_api.values()):
            _base, _vct = _api['base'], _api['value_ctype']
            _gptypes = ', '.join(_api.get('params') or []) or 'void'
            parts.append(f"extern MojoGenerator *{_base}_start ({_gptypes});")
            parts.append(f"extern _Bool {_base}_resume (MojoGenerator *);")
            parts.append(f"extern {_vct} {_base}_value (MojoGenerator *);")
            parts.append(f"extern void {_base}_destroy (MojoGenerator *);")
        parts.append('')
    _needs_async_runtime_h = bool(
        len(self._supported_async) or len(self._supported_async_closures)
        or len(self._nested_async_api)
        or len(self._funcptr_builtins_needed
              & {'mojo_coro_resume_generic', 'mojo_coro_destroy_generic'}))
    if _needs_async_runtime_h and not (self._supported_async or self._supported_async_closures
                                        or self._nested_async_api):
        parts.append('typedef struct MojoAsync MojoAsync;')
        parts.append('#include <mojo_async_runtime.h>')
        parts.append('')
    if self._supported_async or self._supported_async_closures or self._nested_async_api:
        parts.append('typedef struct MojoAsync MojoAsync;')
        parts.append('#include <mojo_async_runtime.h>')
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
        ret    = self.func_return_types.get(fdef.name, 'int64_t')
        has_varargs = any(pn.startswith('*') for pn, _ in (fdef.params or []))
        if has_varargs:
            param_ctypes = self._signature_ctypes(fdef.params, fdef, sentinel='MojoList *')
            self.func_param_types[fdef.name] = self._signature_ctypes(fdef.params, fdef)
            self._note_vararg_trailing_param_types(fdef)
        else:
            param_ctypes = []
            inferred_params = self._inferred_param_types.get(fdef.name, {}) if hasattr(self, '_inferred_param_types') else {}
            for pn, pt in (fdef.params or []):
                if pn in inferred_params:
                    param_ctypes.append(inferred_params[pn])
                else:
                    param_ctypes.append(self._param_ctype(pn, pt, fdef))
            self.func_param_types[fdef.name] = param_ctypes
        ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
        _c_fn_name = self._func_csym(fdef.name)
        _guard_name = _c_fn_name if fdef.name in _C_RESERVED_FUNCS else fdef.name
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
            elif any(pn.startswith('*') for pn, _ in (m.params or [])):
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
        parts.append("MojoList * Parser_parse_module (Parser *);")
        parts.append("void Parser___init__ (Parser *, MojoList *);")
        # gimple_module_gen.py's `from gimple_codegen import ...` of these two
        # unannotated single-def helpers (see _NO_OVERLOAD_MANGLE). Their sole
        # `all_struct_defs` param is a list — usage-inferred `MojoList *` on
        # the definition side, and the call passes a real list too.
        parts.append("void _merge_struct_inheritance (MojoList *);")
        parts.append("int64_t _compute_exc_descendants (MojoList *);")
        parts.append("void Interpreter___init__ (Interpreter *, char *, MojoList *);")
        parts.append("int64_t Interpreter_execute (Interpreter *, int64_t);")
        parts.append("_Bool jit_compile_and_execute (char *, char *, int64_t, int64_t, int64_t);  /* from mojo.py */")
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
                        field_ctype = f"{vtype} *" if vname in ci.mut_names else vtype
                        parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                    parts.append(f"}} {ci.env_struct};")
                    parts.append('')
                    self._emitted_structs.add(ci.env_struct)
    for outer_name, inner_map in self._all_closures.items():
        for inner_name, ci in inner_map.items():
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
        _new_names = sorted(self._funcptr_builtins_needed - self._emitted_funcptr_builtins)
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
    # divergence vs `python3 mojo.py --dump`. Same at the typedef site above.
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
            _sp_lines = [f'static char * {sname};'
                         for escaped, sname in self._str_pool.items()]
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
            '#include <mojo_runtime.h>',
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
            '   mojo_runtime.h) -- reused, not reinvented, so the extern "C"',
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
            # see bugs/COMPILE_FAIL_Tools_cases_generator_parser.md) never
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
            for _mref_safe_mod in sorted(_mref_modules):
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
                        'root' if _mref_safe_mod == 'root' else _mref_safe_mod, []):
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
                        'root' if _mref_safe_mod == 'root' else _mref_safe_mod, []):
                    _gct = _gl[1].replace('_Bool', 'bool')
                    _gfname = _c_field_name(_gl[0])
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

    return self._dedup_variadic_externs(parts)

def __getattr__(name):
    import gimple_codegen as _gc
    return getattr(_gc, name)
