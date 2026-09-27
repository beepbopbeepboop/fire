"""Shared middle-end extracted from gimple_module_gen.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
import sys
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, py_tokenize, Parser, _as_str, _as_dict, _sms_key, _pair_key, _as_funcdef_node, _ptr_slot_in_range, _as_int, _as_intlit_node, _as_boollit_node, _as_structdef_node, _signed_int64, _signed_int64_c_literal, method_receiver_kind
from module_loader import load_module, get_symbol_type
import ast_rewriter
import mlir
import regex_compile
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
# Closure-scan leaf helpers live in mojo/middle.closures (formal + gimple
# share one copy; closures must not import this module — it pulls gimple_codegen).
from mojo.middle.closures import (
    _gmi_all_stmts_nonfunc, _selfhost_fn_reassigns_method,
)
import gimple_codegen  # constants used by some extracted helpers
from gimple_codegen import _selfhost_impl_py_files
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

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

def _selfhost_module_name_for_path(sd: str, path: str) -> str:
    """Compile-time module name for a compiler implementation source — the
    SAME string `_compile_imported_module` receives as `module_name` for the
    corresponding `import` (dotted package path under `mojo/`, bare basename
    for a root-level `.py`). The scalar-globals pre-seed must use this, not
    a naive basename: `_global_to_module` drives bare-name global reads to
    `_{mod}_globals` / `struct _{mod}_toplev`, and those struct names are
    built from `GimpleGen.module_name` / `current_mod_name`. Seeding
    `types.py`'s globals under `'types'` while the compile registers them
    under `'mojo.middle.types'` made every read reference the never-defined
    `struct _types_toplev` (a real test_selfhost regression after the
    package split when the pre-seed started covering `mojo/**`)."""
    try:
        rel = os.path.relpath(path, sd)
    except Exception:
        return os.path.splitext(os.path.basename(path))[0].replace('-', '_')
    if rel.startswith('..'):
        return os.path.splitext(os.path.basename(path))[0].replace('-', '_')
    # '/', not os.sep: see module_loader.module_name_for_path's identical
    # note — the self-hosted backend leaves os.sep opaque.
    rel = rel.replace(os.sep, '/').replace('-', '_')
    if rel.endswith('.py'):
        rel = rel[:-3]
    if rel.endswith('/__init__'):
        rel = rel[: -len('/__init__')]
    elif rel == '__init__':
        return os.path.splitext(os.path.basename(path))[0].replace('-', '_')
    return rel.replace('/', '.')

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
    _files = sorted(_selfhost_impl_py_files(sd)
                    + [os.path.join(sd, n) for n in
                       ('fire_compiler.py', 'module_loader.py', 'monomorphize.py',
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
        _mod = _selfhost_module_name_for_path(sd, _f)
        try:
            _stmts: list = ast_rewriter.rewrite(
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

def _selfhost_struct_dict_field_val_types(sd: str) -> dict:
    """`{struct_name: {field_name: value_ctype}}` for every annotated
    `dict[K, V]` instance field across this compiler's own sibling `.py`
    modules — an `AssignStmt` (`self.X: dict[str, str] = {}` in `__init__`,
    or a class-body `X: dict[...] = {}`) carrying a `type_ann`.

    The ordinary field-value-type scan (`_collect_self_assigns`, the
    `_field_dict_val_types.setdefault(...)` there) only runs on structs whose
    full method BODIES are in `stmts`/`imported_stmts`. In a per-module
    `fire.py build` compile a sibling class like `GimpleGen` arrives as a
    materialized imported struct with signature-only methods, so its
    `_str_pool: dict[str, str]` value type was lost — `for k, v in
    self._str_pool.items()` then unpacked `v` as int64 and `str()`'d the
    pointer (garbage decimal `_slit_N` names in the emitted string pool)."""
    _files = sorted(_selfhost_impl_py_files(sd)
                    + [os.path.join(sd, n) for n in
                       ('module_loader.py', 'fire_compiler.py')])
    _files = [f for f in _files if os.path.isfile(f)]
    _key = tuple((f, os.path.getmtime(f)) for f in _files)
    _hit = _SELFHOST_MODGLOBAL_CACHE.get('sdfvt')
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _out: dict = {}
    for _f in _files:
        try:
            _stmts: list = ast_rewriter.rewrite(
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

def _selfhost_homogeneous_tuple_ret_funcs(self, sd: str) -> dict:
    """`{func_key: elem_ctype}` for every sibling `.py` module-level function
    and struct method whose return annotation is a homogeneous non-`int64_t`
    `tuple[T, T[, ...]]`. `func_key` is the bare name for a free function and
    `Struct_method` for a method — the same keys `_return_elem_types` and
    `_lower_struct_method_call` / `_lower_named_call` look up.

    Pass-2c body inference (`_infer_return_elem_type`) can miss these when a
    slot is a reassigned local or a ternary, and in a per-module `fire.py
    build` compile the defining function's body isn't even scanned from an
    importing module — so `GimpleGen._decode_str_literal_text`'s
    `(char*, char*)` return was unpacked via `mojo_list_get_int` and every
    user `StringLiteral`'s text read back as 0 (empty string-pool entries)."""
    _files = sorted(_selfhost_impl_py_files(sd)
                    + [os.path.join(sd, n) for n in ('module_loader.py', 'fire_compiler.py')])
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
            _stmts: list = ast_rewriter.rewrite(
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

def _collect_import_modules(modules_to_compile: dict, node_list):
    """Populate `modules_to_compile` with every module named by an import
    anywhere in `node_list` — top level and nested inside function bodies,
    if/try/loop blocks. Deliberately a module-level function taking the
    accumulator explicitly rather than a nested closure over it: on the
    self-hosted (compiled) path a recursive nested function's capture of a
    mutable set/dict was unreliable, so `--dump-full` silently saw only the
    module's own top-level imports and emitted a truncated closure.

    `modules_to_compile: dict` is an EXPLICIT annotation, not decoration:
    this parameter used to be a `set` (`.add(...)` at every call site), and
    the caller changed it to a `dict` (`[...] = True`) for deterministic
    `sorted()` order — but the two-hop call chain
    (`gen_module_impl` -> `_collect_import_modules` ->
    `_collect_import_modules_rec`) left the self-hosted param-type inference
    for this bare, unannotated parameter still defaulting to its old
    container shape. `modules_to_compile[key] = True` inside
    `_collect_import_modules_rec` then lowered as a LIST subscript
    assignment (`mojo_list_set_int` with `key`'s pointer value used as the
    index) -> SIGBUS, wildly out of bounds. The annotation pins the ctype."""
    _collect_import_modules_rec(modules_to_compile, node_list, 0)

def _collect_import_modules_rec(modules_to_compile: dict, node_list, _depth: int):
    # Depth cap: on the self-hosted path a mis-lowered `isinstance(stmt,
    # (WhileStmt, ForStmt, TryStmt))` tuple-isinstance or an aliased `.body`
    # can make this recurse without bound (observed as a multi-GB memory
    # runaway on `MOJO_NO_SHIM=1 --dump-full` before any module is even
    # compiled). Real nesting never approaches 40.
    if _depth > 40:
        return
    for stmt in node_list:
        if isinstance(stmt, FromImportStmt):
            modules_to_compile[_as_str(stmt.module)] = True
            # `stmt.name_alias_strs` + `_fi_name`, NOT
            # `gimple_ctypes._fromimport_names(stmt)` + `_fip14[0]` — the
            # latter subscripts a freshly-built 2-tuple (each entry
            # `_fromimport_names` itself just constructed via
            # `.append((_as_str(...), _as_str(...)))`), and that exact
            # "subscript a freshly-built tuple" shape is the same one
            # confirmed broken self-hosted in gen_module_impl's own
            # FromImportStmt scan (see that fix's comment — `len()`/dict-
            # key hashing on the extracted value silently misbehaved even
            # though `==` still worked). `name_alias_strs` sidesteps
            # tuples entirely.
            for _fip14 in (getattr(stmt, 'name_alias_strs', None) or []):
                _fn = gimple_ctypes._fi_name(_fip14)
                # _join_import_member, not a blind f"{module}.{name}": for a
                # bare-relative module (`from . import strutil`, module == '.')
                # the separator dot would double-count the depth. The joined
                # string must be EXACTLY what _module_candidate_paths resolves
                # and what the temp_gen's module_name/qualifier derive from.
                modules_to_compile[_as_str(gimple_ctypes._join_import_member(stmt.module, _fn))] = True
        elif isinstance(stmt, ImportStmt):
            # Read `stmt.module` DIRECTLY (a char* field, exactly like the
            # FromImportStmt branch above), not via `_import_targets(stmt)`
            # with a `for _m, _a in ...` unpack: that 2-tuple unpack types
            # _m as int64_t on the self-hosted backend, so the module string
            # POINTER was stored via mojo_set_add_int and every later
            # `name in modules_to_compile` missed — the compiled --dump-full
            # then emitted a truncated transitive closure.
            modules_to_compile[_as_str(stmt.module)] = True
            _mtc_extra = stmt.extra
            if _mtc_extra and len(_mtc_extra) > 0:
                for _ex in _mtc_extra:
                    modules_to_compile[_as_str(_ex[0])] = True
        elif isinstance(stmt, FunctionDef):
            _collect_import_modules_rec(modules_to_compile, stmt.body, _depth + 1)
        elif isinstance(stmt, IfStmt):
            _collect_import_modules_rec(modules_to_compile, stmt.then_body, _depth + 1)
            for _elif_pair in stmt.elifs:
                _collect_import_modules_rec(modules_to_compile, _elif_pair[1], _depth + 1)
            if stmt.else_body:
                _collect_import_modules_rec(modules_to_compile, stmt.else_body, _depth + 1)
        elif isinstance(stmt, (WhileStmt, ForStmt, TryStmt)):
            _collect_import_modules_rec(modules_to_compile, stmt.body, _depth + 1)

def _register_sym(self, s, sym_name: str, orig_name: str, sym_info,
                  _sib_qualifier, _sib_is_local_project):
    """Hoisted out of gen_module_impl's `if exports is not None:` block —
    as a nested closure its params lifted to int64_t and `_sk`/`sym_name`
    erased into `imported_symbols` as decimal-address keys (address-ordered
    re-export externs). A real module function gets `str`-typed params and
    a single emission context, so `_lower_MemberExpr(self.imported_symbols)`
    keeps its `MojoDict *` ctype (via `_as_dict` too, belt-and-suspenders)."""
    # Fresh `_as_str` view — a lifted-closure param whose
    # `_infer_param_types` guess is int64_t would make every
    # `self.imported_symbols[sym_name] = ...` below store the
    # `char *` bits as a DECIMAL dict key (address-ordered
    # `sorted(keys())` in the re-export extern block).
    _sk = _as_str(sym_name)
    _reg_isym = _as_dict(self.imported_symbols)
    if _sk in self.struct_field_types:
        return
    if not s.wildcard and self._from_import_name_is_submodule(s.module, orig_name):
        _reg_isym[_sk] = {
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
        self._module_alias_names.add(_sk)
        return
    if _sib_qualifier and not sym_info:
        if not s.wildcard:
            self._unresolved_import_aliases.add(_sk)
        return
    if isinstance(sym_info, str):
        _reg_isym[_sk] = {
            'module': s.module, 'original_name': orig_name,
            'return_type': sym_info, 'parameters': [],
            'signature': f"{sym_info} {_sk} (void)"
        }
        self.func_return_types[_sk] = sym_info
    elif isinstance(sym_info, dict):
        sym_info = _as_dict(dict(sym_info))
        sym_info['module'] = s.module
        # Only record `original_name` for a genuine `import X as Y` alias.
        # For an unaliased import it equals `_sk`, and storing it makes
        # `_func_csym` read it back (MojoDict get -> int64_t, then a POINTER
        # `!=` against `bare_name` that is always true on the self-hosted
        # path) take its alias branch -> `_safe_name(<erased ptr>)` -> a
        # decimal-address guard name (`#ifndef _Users_..._<addr>`), different
        # every run. `orig_name`/`_sk` here are real str params (module-level
        # fn, not a lifted closure), so this compare is a true string compare.
        if orig_name != _sk:
            sym_info['original_name'] = orig_name
        _reg_isym[_sk] = sym_info
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
            self.func_return_types[_sk] = sym_info['c_return_type']
        if sym_info.get('variadic'):
            if _ret_changed:
                sym_info['signature'] = (
                    _as_str(sym_info.get('c_return_type', 'int64_t')) + ' '
                    + orig_name + ' (...)')
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
                _c_ret = _as_str(sym_info.get('c_return_type', 'int64_t'))
                _param_str = ', '.join(_new_c_params) if _new_c_params else 'void'
                sym_info['signature'] = f"{_c_ret} {orig_name} ({_param_str})"
        if _sib_qualifier and 'c_parameters' in sym_info:
            self.func_param_types[_sk] = [
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
                if isinstance(_fs, FunctionDef) and _fs.name == orig_name:
                    _pts_snap = self._signature_ctypes(_fs.params, _fs)
                    break
        except Exception:
            _pts_snap = None
        if not _pts_snap:
            _pts_snap = self.func_param_types.get(_sk)
        if _pts_snap is not None:
            self._imported_home_param_types[_pair_key(_qual, _sk)] = list(_pts_snap)
        self._note_own_func_home(_sk, _qual)

def _gmi_prefold_toplevel_comptime(self, _node_list):
    """Hoisted out of `gen_module_impl` (module-level, not a nested,
    RECURSIVE closure) — a real --dump-full fire.py determinism diff
    showed this closure (and several siblings in the same ~8000-line
    function) called with an inconsistent apparent arity across runs
    (`f(env, x)` vs `f(env, x, 0)`), the lifted-closure-env instability
    this session has fixed by hoisting everywhere else."""
    for _cn in _node_list:
        if isinstance(_cn, ComptimeVarStmt):
            _cv = self._eval_const(_cn.value)
            if _cv is not None:
                self._comptime_vals.setdefault(_cn.target, _cv)
            if isinstance(_cn.value, ListExpr):
                self._comptime_list_asts.setdefault(_cn.target, _cn.value)
        elif isinstance(_cn, IfStmt):
            _gmi_prefold_toplevel_comptime(self, _cn.then_body or [])
            if _cn.else_body:
                _gmi_prefold_toplevel_comptime(self, _cn.else_body)
            for _, _eb in (_cn.elifs or []):
                _gmi_prefold_toplevel_comptime(self, _eb or [])
        elif isinstance(_cn, (WhileStmt, ForStmt)):
            _gmi_prefold_toplevel_comptime(self, _cn.body or [])
        elif isinstance(_cn, TryStmt):
            _gmi_prefold_toplevel_comptime(self, _cn.body or [])
            for _h in (_cn.handlers or []):
                _gmi_prefold_toplevel_comptime(self, getattr(_h, 'body', None) or [])

def _gmi_find_comptime_one(self, _node_list, _target, _out: dict):
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. This one had DEFAULT PARAMETERS bound to
    captured values (`_target=_iname, _out=_found`) — exactly the shape
    that made the call-site arity flip between `f(env, x)` and
    `f(env, x, 0)` run to run. Explicit required params now."""
    if _out:
        return
    for _cn in _node_list:
        if isinstance(_cn, ComptimeVarStmt) and _cn.target == _target:
            _cv = self._eval_const(_cn.value)
            if _cv is not None:
                _out['v'] = _cv
            return
        elif isinstance(_cn, IfStmt):
            _gmi_find_comptime_one(self, _cn.then_body or [], _target, _out)
            if _cn.else_body:
                _gmi_find_comptime_one(self, _cn.else_body, _target, _out)
            for _, _eb in (_cn.elifs or []):
                _gmi_find_comptime_one(self, _eb or [], _target, _out)
        elif isinstance(_cn, (WhileStmt, ForStmt)):
            _gmi_find_comptime_one(self, _cn.body or [], _target, _out)
        elif isinstance(_cn, TryStmt):
            _gmi_find_comptime_one(self, _cn.body or [], _target, _out)
            for _h in (_cn.handlers or []):
                _gmi_find_comptime_one(self, getattr(_h, 'body', None) or [], _target, _out)

def _gmi_phase17_collect_appends(self, _node_list: list, _append_hits: dict) -> None:
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Recursive; `_append_hits` (dict) threaded and
    annotated per the hoist GOTCHA."""
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
            for _lname, _ltype in self._infer_local_var_types(_as_funcdef_node(_n)).items():
                if _lname not in self.var_types:
                    self.var_types[_lname] = _ltype
            _gmi_phase17_collect_appends(self, _n.body or [], _append_hits)
            self.var_types = _saved
        elif isinstance(_n, IfStmt):
            _gmi_phase17_collect_appends(self, _n.then_body or [], _append_hits)
            if _n.else_body:
                _gmi_phase17_collect_appends(self, _n.else_body, _append_hits)
            for _cond2, _ebody2 in (_n.elifs or []):
                _gmi_phase17_collect_appends(self, _ebody2 or [], _append_hits)
        elif isinstance(_n, (WhileStmt, ForStmt)):
            _gmi_phase17_collect_appends(self, _n.body or [], _append_hits)
            if getattr(_n, 'else_body', None):
                _gmi_phase17_collect_appends(self, _n.else_body, _append_hits)
        elif isinstance(_n, TryStmt):
            _gmi_phase17_collect_appends(self, _n.body or [], _append_hits)
            for _h in (_n.handlers or []):
                _gmi_phase17_collect_appends(self, getattr(_h, 'body', None) or [], _append_hits)
            if isinstance(_n.else_body, list):
                _gmi_phase17_collect_appends(self, _n.else_body, _append_hits)
            if isinstance(getattr(_n, 'finally_body', None), list):
                _gmi_phase17_collect_appends(self, _n.finally_body, _append_hits)
        elif isinstance(_n, WithStmt):
            _gmi_phase17_collect_appends(self, _n.body or [], _append_hits)

def _gmi_container_ctype(v):
    """Container C type a container LITERAL expression provably evaluates
    to, or None when `v` is not one. The single answer to "is this
    argument/expression a list, a dict or a set?", shared by
    `_gmi_collect_self_assigns`'s `self.<f> = <container>` chain below and
    the constructor-argument observers in `module_gen.py` (which need it
    for the `self.<f> = <param>` shape the pass cannot see through).

    Purely syntactic, so an answer here is a PROOF, never a guess -- which
    is what lets the constructor-argument observer act on it despite a
    struct field being pinned to exactly one C type
    (`struct_field_types[struct][field]`). A tuple display answers
    `MojoList *`: a tuple IS a MojoList carrying a tuple tag at runtime
    (`mojo_is_tuple` / `_mojo_repr_list`), the same representation the
    generator tuple-slot box uses.

    Returns None for a `Comprehension` whose `kind` is not one of the three
    display forms, leaving that caller's own fallback in charge -- the
    shape is unknowable, not list-typed."""
    if isinstance(v, (ListExpr, TupleExpr)):
        return 'MojoList *'
    if isinstance(v, DictExpr):
        return 'MojoDict *'
    if isinstance(v, SetExpr):
        return 'MojoSet *'
    if isinstance(v, Comprehension):
        return {'list': 'MojoList *', 'set': 'MojoSet *',
                'dict': 'MojoDict *'}.get(v.kind)
    return None


def _gmi_collect_self_assigns(self, _sname: str, body, param_types: dict, found: dict) -> None:
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Not recursive (walks via _walk_ast), but a
    lifted closure all the same; `param_types`/`found` (dicts) threaded
    and annotated per the hoist GOTCHA, and the captured struct name is
    passed as `_sname` instead of the whole StructDef."""
    for node in _walk_ast(body):
        if isinstance(node, AssignStmt):
            fn = _gmi_self_member(node.target)
            # `if not fn: continue` BEFORE `found.get(fn)`: a non-`self`
            # assignment target (`var x = 1` -> IdentExpr, `a.b = 1` ->
            # some other obj) makes `_gmi_self_member` return None, and
            # `found.get(None)` lowers to `mojo_dict_get_str(d, NULL)` ->
            # `strcmp(NULL)` -> SIGSEGV. Latent until nested/other bodies
            # were actually walked (`_walk_ast` doesn't recurse reliably
            # self-hosted).
            if not fn:
                continue
            _existing_fn_ft = found.get(fn)
            if (fn not in found
                    or (_existing_fn_ft in ('int', 'int64_t')
                        and _existing_fn_ft is not None)):
                v = node.value
                if isinstance(v, IdentExpr):
                    ft = param_types.get(v.name, 'int64_t')
                elif isinstance(v, IntLiteral):
                    ft = 'int64_t'
                elif isinstance(v, StringLiteral):
                    # `self._buf = b''` in __init__ (or any bytes
                    # literal) -> a real bytes value field, so a
                    # later `self._buf[a:]` slice routes through
                    # mojo_bytes_slice and `buf += <bytes>`
                    # concatenates instead of doing char*+ptr
                    # pointer arithmetic (COMPILE_FAIL_zipfile).
                    ft = 'MojoBytes *' if getattr(v, 'is_bytes', False) else 'char *'
                elif isinstance(v, BoolLiteral):
                    ft = '_Bool'
                elif isinstance(v, Comprehension) and _gmi_container_ctype(v) is None:
                    # An unrecognised comprehension `kind` still builds a
                    # LIST at runtime -- this pass's long-standing default,
                    # kept rather than dropped to int64_t, because
                    # `_gmi_container_ctype` returning None means "cannot
                    # tell", which is not the same answer as "not a
                    # container".
                    ft = 'MojoList *'
                elif _gmi_container_ctype(v) is not None:
                    ft = _gmi_container_ctype(v)
                elif isinstance(v, CallExpr):
                    cfn = v.func
                    # `deque()` / `deque[T]()` / `collections.deque(...)`
                    # -> a MojoList * field (bugs/COMPILE_FAIL_
                    # asyncio_queues.md gap 2). asyncio round-trips
                    # Future handles through it via append/popleft.
                    _cfn_base = cfn
                    if isinstance(_cfn_base, SubscriptExpr):
                        _cfn_base = _cfn_base.obj
                    _is_deque = (
                        (isinstance(_cfn_base, IdentExpr)
                         and _cfn_base.name == 'deque')
                        or (isinstance(_cfn_base, MemberExpr)
                            and _cfn_base.member == 'deque'))
                    cn = cfn.name if isinstance(cfn, IdentExpr) else ''
                    _is_evt_fut = (
                        (isinstance(_cfn_base, IdentExpr)
                         and _cfn_base.name in ('Event', 'Future'))
                        or (isinstance(_cfn_base, MemberExpr)
                            and _cfn_base.member in ('Event', 'Future',
                                                     'create_future')))
                    _is_struct_Struct = (
                        isinstance(_cfn_base, MemberExpr)
                        and isinstance(_cfn_base.obj, IdentExpr)
                        and _cfn_base.obj.name == 'struct'
                        and _cfn_base.member == 'Struct')
                    if _is_deque:
                        ft = 'MojoList *'
                    elif _is_struct_Struct:
                        ft = 'MojoStructFmt *'
                    elif _is_evt_fut:
                        # asyncio Event/Future field -> A3 runtime
                        # int64_t handle (gap 2). The .set()/.wait()/
                        # .done() lowering keys off the int64_t recv.
                        ft = 'int64_t'
                    elif cn in ('list', 'DynamicVector', 'mojo_list_new'):
                        ft = 'MojoList *'
                    elif cn in ('dict', 'Dict', 'mojo_dict_new'):
                        ft = 'MojoDict *'
                    elif cn in ('set', 'Set', 'frozenset', 'mojo_set_new'):
                        ft = 'MojoSet *'
                    elif cn in ('bytes', 'bytearray'):
                        ft = 'MojoBytes *'
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
                        ft = _UNKNOWN_FIELD_CTYPE
                else:
                    ft = _UNKNOWN_FIELD_CTYPE
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
                            _sname, {})[fn] = _dv_sa
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
                                _sname, {})[fn] = _et_sa
        elif isinstance(node, MultiAssignStmt):
            for tgt in node.targets:
                fn = _gmi_self_member(tgt)
                if fn is not None and fn not in found:
                    found[fn] = _UNKNOWN_FIELD_CTYPE
        elif isinstance(node, AugAssignStmt):
            fn = _gmi_self_member(node.target)
            if fn is not None and fn not in found:
                found[fn] = 'int64_t'
    # Nested classes/functions: the shared `_walk_ast` above does not
    # reliably RECURSE self-hosted (a nested `StructDef`/`FunctionDef` node
    # is misclassified as a scalar leaf — see `_walk_ast`'s own documented
    # history), so a nested `class _Suite: def __init__(self, fns):
    # self._fns = fns` was found by the shim (CPython) and folded onto the
    # ENCLOSING struct (the nested class gets no separate layout —
    # `TestSuite._fns`) but was missed self-hosted (`int _dummy`). Descend
    # explicitly here, matching the shim, without touching the shared walker.
    for _nn in body:
        if isinstance(_nn, StructDef):
            for _mm in _nn.methods:
                _gmi_collect_self_assigns(self, _sname, _mm.body, param_types, found)
        elif isinstance(_nn, FunctionDef):
            _gmi_collect_self_assigns(self, _sname, _nn.body, param_types, found)
        # Control-flow bodies, same reasoning: `_walk_ast` does not recurse
        # into them reliably self-hosted, so an assignment nested one level
        # down (`with self._cond: self._thread = threading.Thread(...)` in
        # myinterpreter.py's `_ThreadedGenerator.start`) was never seen and
        # its field stayed unregistered. Mirrors the explicit per-node-type
        # recursion `_selfhost_walk_stmts_for_assign_targets` already uses.
        elif isinstance(_nn, IfStmt):
            _gmi_collect_self_assigns(self, _sname, _nn.then_body, param_types, found)
            for _ei in range(len(_nn.elifs)):
                _gmi_collect_self_assigns(self, _sname, _nn.elifs[_ei][1], param_types, found)
            if _nn.else_body:
                _gmi_collect_self_assigns(self, _sname, _nn.else_body, param_types, found)
        elif isinstance(_nn, ComptimeIfStmt):
            _gmi_collect_self_assigns(self, _sname, _nn.then_body, param_types, found)
            for _ec2 in range(len(_nn.elifs)):
                _gmi_collect_self_assigns(self, _sname, _nn.elifs[_ec2][1], param_types, found)
            if _nn.else_body:
                _gmi_collect_self_assigns(self, _sname, _nn.else_body, param_types, found)
        elif (isinstance(_nn, WhileStmt) or isinstance(_nn, ForStmt)
                or isinstance(_nn, ComptimeForStmt)):
            _gmi_collect_self_assigns(self, _sname, _nn.body, param_types, found)
            _eb3 = getattr(_nn, 'else_body', None)
            if _eb3:
                _gmi_collect_self_assigns(self, _sname, _eb3, param_types, found)
        elif isinstance(_nn, TryStmt):
            _gmi_collect_self_assigns(self, _sname, _nn.body, param_types, found)
            for _hi in range(len(_nn.handlers)):
                _gmi_collect_self_assigns(self, _sname, _nn.handlers[_hi].body, param_types, found)
            if _nn.else_body:
                _gmi_collect_self_assigns(self, _sname, _nn.else_body, param_types, found)
            if _nn.finally_body:
                _gmi_collect_self_assigns(self, _sname, _nn.finally_body, param_types, found)
        elif isinstance(_nn, WithStmt):
            _gmi_collect_self_assigns(self, _sname, _nn.body, param_types, found)
        elif isinstance(_nn, MatchStmt):
            for _ci in range(len(_nn.cases)):
                _gmi_collect_self_assigns(self, _sname, _nn.cases[_ci].body, param_types, found)

def _gmi_scan_import_modules(mod_stmts, all_modules: dict) -> None:
    """Record every module named by `import m` / `import m as a, m2` /
    `from m import ...` in `mod_stmts` into `all_modules` (a str->bool
    dict). Hoisted out of `gen_module_impl` (see its call site) so the
    loop element binds as a generic int64_t and `isinstance` emits a real
    runtime tag check — an INLINE `for _ms in stmts + [...]:` bound `_ms`
    as `char *`, making both `isinstance` calls constant-false and
    dropping every imported module's `_<mod>_toplev` forward declaration.

    `mod_stmts` is deliberately unannotated: a bare list parameter's
    elements default to int64_t (the `_gmi_all_stmts_nonfunc` convention),
    which is what keeps `isinstance` dynamic here."""
    for _ms in mod_stmts:
        if isinstance(_ms, ImportStmt):
            _mn0 = _gmi_as_str(_ms.module)
            if _mn0 and not _mn0.startswith('_'):
                all_modules[_mn0] = True
            _ms_extra = _ms.extra
            if _ms_extra and len(_ms_extra) > 0:
                for _ex in _ms_extra:
                    _mnx = _gmi_as_str(_ex[0])
                    if _mnx and not _mnx.startswith('_'):
                        all_modules[_mnx] = True
        elif isinstance(_ms, FromImportStmt):
            _mn1 = _gmi_as_str(_ms.module)
            if _mn1 and not _mn1.startswith('_') and '.' not in _mn1:
                all_modules[_mn1] = True

def _gmi_self_member(expr):
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Pure. MemberExpr's `.member` name iff its
    object is bare `self`."""
    if (isinstance(expr, MemberExpr) and isinstance(expr.obj, IdentExpr)
            and _as_str(expr.obj.name) == 'self'):
        return _as_str(expr.member)
    return None

def _gmi_global_init_code(value) -> str:
    """Static C initializer for a module-global assignment RHS.

    Handles the scalar-literal cases inline, routing the isinstance-checked
    node through `_as_intlit_node` / `_as_boollit_node` FIRST — on the
    self-hosted compiled path a plain `isinstance` pass does NOT narrow the
    node, so `.value` / `.raw` still went through `_mojo_dispatch_getattr`
    and came back 0 (`x = 42` -> `.x = 0` instead of `.x = 42`, a
    stage1-vs-stage2 parity break under MOJO_NO_SHIM=1). The annotated
    identity view compiles a following field read to a direct struct load."""
    if isinstance(value, IntLiteral):
        _il = _as_intlit_node(value)
        _v64 = _signed_int64(_as_int(_il.value))
        if -0x80000000 <= _v64 <= 0x7FFFFFFF:
            _r = _as_str(_il.raw)
            return _r if _r else str(_v64)
        return _signed_int64_c_literal(_v64)
    if isinstance(value, BoolLiteral):
        return '1' if _as_boollit_node(value).value else '0'
    return _extract_init_expr(value)

def _method_receiver_kind(m) -> str:
    """Which receiver, if any, a struct METHOD `m` takes: 'self', 'cls', or
    '' (none). Delegates to fire_compiler.method_receiver_kind, which owns
    the rule (decorator first, first parameter's name second) and documents
    why the name alone was not enough — a `@staticmethod def gen(n)` has a
    REAL first parameter, so a name-only test read it as receiver-less and
    the method was emitted under the free-function symbol
    `_mojogen_<name>`, leaving `C.gen(...)` unrecognised as a generator
    call."""
    return method_receiver_kind(m)


def _cpp_method_receiver_name(m) -> str:
    """Which SOURCE parameter of a generator METHOD `m`, if any, is the
    receiver slot every caller must fill: 'self' for an instance method,
    'cls' for a @classmethod, '' for a @staticmethod (which has none).

    Read from the decorator first and the first parameter's name second —
    see `_method_receiver_kind`, which this now delegates to, and which
    documents why the name alone was not enough. Recorded into
    `_generator_method_api[key]['receiver']` at every registration site so a
    consumer can get a cross-method `cls.<gen>(...)` call's arity right; see
    GimpleGen._cpp_yield_from's `is_cls_gen_call` branch. An empty
    parameter list (a generator method with no parameters at all) yields
    '' -- there is no receiver, and passing one would be a wrong-arity
    call."""
    return _method_receiver_kind(m)


def _gmi_collect_global_stmts(stmt_list) -> list:
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Recursive; pure (no captured state)."""
    result = []
    for _gs in stmt_list:
        result.append(_gs)
        if isinstance(_gs, TryStmt):
            result.extend(_gmi_collect_global_stmts(_gs.body or []))
            for _h in (_gs.handlers or []):
                result.extend(_gmi_collect_global_stmts(getattr(_h, 'body', []) or []))
            result.extend(_gmi_collect_global_stmts(_gs.else_body or [] if isinstance(_gs.else_body, list) else []))
            result.extend(_gmi_collect_global_stmts(_gs.finally_body or [] if isinstance(_gs.finally_body, list) else []))
        elif isinstance(_gs, IfStmt):
            result.extend(_gmi_collect_global_stmts(_gs.then_body or []))
            result.extend(_gmi_collect_global_stmts(_gs.else_body or []))
    return result

def _gmi_scan_func_body_for_self_attr(self, fname, body):
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Recursive; only captures self."""
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
            _gmi_scan_func_body_for_self_attr(self, fname, _fstmt.then_body)
            for _, _eb in _fstmt.elifs:
                _gmi_scan_func_body_for_self_attr(self, fname, _eb)
            if _fstmt.else_body:
                _gmi_scan_func_body_for_self_attr(self, fname, _fstmt.else_body)
        elif isinstance(_fstmt, (WhileStmt, ForStmt, TryStmt)):
            _gmi_scan_func_body_for_self_attr(self, fname, _fstmt.body)

def _gmi_collect_return_values(acc_rt: list, stmts2) -> None:
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Recursive; the accumulator list is threaded."""
    for _st in stmts2:
        if isinstance(_st, FunctionDef):
            continue
        if isinstance(_st, ReturnStmt) and _st.value is not None:
            acc_rt.append(_st.value)
        else:
            for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                sub = getattr(_st, attr, None)
                if isinstance(sub, list):
                    _gmi_collect_return_values(acc_rt, sub)
            for _eb_cond, _eb_body in (getattr(_st, 'elifs', None) or []):
                _gmi_collect_return_values(acc_rt, _eb_body)
            for _h in (getattr(_st, 'handlers', None) or []):
                hb = getattr(_h, 'body', None)
                if isinstance(hb, list):
                    _gmi_collect_return_values(acc_rt, hb)

def _gmi_scan_try_imports(self, _phase17_mod, stmt_list):
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring."""
    for _s in stmt_list:
        if isinstance(_s, ImportStmt):
            # `_import_local_names`, NOT `for _tm0,_ta0 in _import_targets`:
            # unpacking the `(module, alias)` tuple re-boxes the `None`
            # alias slot to a stray truthy pointer, so `_ta if _ta else _tm`
            # picked it and `_global_var_types[<decimal addr>]` -> the
            # `import os`/`import ctypes` module-marker globals landed in
            # `_root_toplev` as address-named fields, different every run.
            for _local in gimple_ctypes._import_local_names(_s):
                _local = _as_str(_local)
                if _local and _local not in self._global_var_types:
                    self._global_var_types[_local] = 'int64_t'
                    self._global_c_decl_types[_local] = 'int64_t'
                    # `_own_global_var_types` too: this pre-pass runs BEFORE
                    # `_gen_toplevel`, and `_lower_IdentExpr`'s bare-name
                    # global-read branch keys "it's ours" off this — the
                    # shared `_global_to_module` superset's value erases to a
                    # boxed pointer on the compiled path, so
                    # `_global_owner_mod == _this_mod` spuriously fails and
                    # the read fell to `(int64_t)0` (`import sys` in
                    # t1.mojo/t_argv.mojo/mojo_main.py — a stage1-vs-stage2
                    # parity break under MOJO_NO_SHIM=1).
                    self._own_global_var_types[_local] = 'int64_t'
                    if _local not in self._global_to_module:
                        self._global_to_module[_local] = _phase17_mod
        elif isinstance(_s, TryStmt):
            _gmi_scan_try_imports(self, _phase17_mod, _s.body or [])
            for _h in (_s.handlers or []):
                _gmi_scan_try_imports(self, _phase17_mod, getattr(_h, 'body', []) or [])
        elif isinstance(_s, IfStmt):
            _gmi_scan_try_imports(self, _phase17_mod, _s.then_body or [])
            if isinstance(_s.else_body, list):
                _gmi_scan_try_imports(self, _phase17_mod, _s.else_body)

def _gmi_scan_cpp_nested_imports(self, stmt_list):
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring."""
    for _gi in stmt_list:
        if isinstance(_gi, (ImportStmt, FromImportStmt)):
            if isinstance(_gi, ImportStmt):
                # Plain unpack, NOT `for _it_pair in ...: _it_pair[0]` —
                # subscripting a freshly-iterated tuple is the same
                # self-hosted trap fixed throughout this file's
                # FromImportStmt.names handling.
                for _tm, _ta in _import_targets(_gi):
                    self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
            else:
                # `name_alias_strs` + `_fi_name`/`_fi_alias`, NOT the raw
                # `.names` tuple field — see this file's other
                # FromImportStmt.names fixes for why.
                for _nm in (getattr(_gi, 'name_alias_strs', None) or []):
                    _in = gimple_ctypes._fi_name(_nm)
                    _ia = gimple_ctypes._fi_alias(_nm)
                    self._cpp_early_global_names.add(_ia if _ia else _in)
        elif isinstance(_gi, AssignStmt) and isinstance(_gi.target, IdentExpr):
            self._cpp_early_global_names.add(_gi.target.name)
            # Module-level `X = Y` identifier alias to a plain module
            # function (`fspath = _fspath` in Lib/os.py, guarded by an
            # `if not _exists('fspath'):` — hence handled here in the
            # nested scan, which also covers the bare top-level case).
            # Recorded so a `X(...)` call in a compiled generator/
            # coroutine body resolves to Y's real symbol instead of the
            # honest "unresolved callee" refusal.
            if (isinstance(_gi.value, IdentExpr)
                    and _gi.value.name in self._cpp_module_fn_names
                    and _gi.target.name not in self._cpp_module_fn_names):
                self._cpp_module_fn_aliases[_gi.target.name] = _gi.value.name
        elif isinstance(_gi, TryStmt):
            _gmi_scan_cpp_nested_imports(self, _gi.body or [])
            for _h in (_gi.handlers or []):
                _gmi_scan_cpp_nested_imports(self, getattr(_h, 'body', []) or [])
            if isinstance(getattr(_gi, 'finally_body', None), list):
                _gmi_scan_cpp_nested_imports(self, _gi.finally_body)
        elif isinstance(_gi, IfStmt):
            _gmi_scan_cpp_nested_imports(self, _gi.then_body or [])
            if isinstance(_gi.else_body, list):
                _gmi_scan_cpp_nested_imports(self, _gi.else_body)

def _bytes_subclass_new_payload_name(new_fn):
    """Given a `class X(bytes)` `__new__` FunctionDef, return the name of
    the parameter it forwards as the bytes payload via
    `return super().__new__(cls, <name>)` / `return bytes.__new__(cls,
    <name>)`, or None if the shape isn't recognised."""
    for _st in (getattr(new_fn, 'body', None) or []):
        if not isinstance(_st, ReturnStmt):
            continue
        _v = _st.value
        if not (isinstance(_v, CallExpr) and isinstance(_v.func, MemberExpr)
                and _v.func.member == '__new__'):
            continue
        _base = _v.func.obj
        _is_super = (isinstance(_base, CallExpr) and isinstance(_base.func, IdentExpr)
                     and _base.func.name == 'super')
        _is_bytes = isinstance(_base, IdentExpr) and _base.name == 'bytes'
        if not (_is_super or _is_bytes):
            continue
        # args are (cls, <payload>) — payload is the 2nd positional
        if len(_v.args) >= 2 and isinstance(_v.args[1], IdentExpr):
            return _v.args[1].name
    return None


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_module_gen.py)
# ---------------------------------------------------------------------------

# --- dependency _SELFHOST_MODGLOBAL_CACHE (from gimple_module_gen.py) ---
_SELFHOST_MODGLOBAL_CACHE: dict = {}

# --- dependency _UNKNOWN_FIELD_CTYPE (from gimple_module_gen.py) ---
_UNKNOWN_FIELD_CTYPE = 'int64_t'

# --- dependency _gmi_as_str (from gimple_module_gen.py) ---
def _gmi_as_str(x) -> str:
    """Same-module `str`-view identity helper (see `_gmi_scan_import_modules`).
    An imported `fire_compiler._as_str`'s `-> str` return type is not
    resolved at a module-level call site here, so the result was inferred
    int64_t and the dict key was `mojo_str_from_int(<pointer>)` — a decimal
    address, not the module name. A SAME-MODULE `-> str` function resolves."""
    return x


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_module_gen.py)
# ---------------------------------------------------------------------------

# --- dependency _SELFHOST_MODGLOBAL_CACHE (from gimple_module_gen.py) ---
_SELFHOST_MODGLOBAL_CACHE: dict = {}

# --- dependency _UNKNOWN_FIELD_CTYPE (from gimple_module_gen.py) ---
_UNKNOWN_FIELD_CTYPE = 'int64_t'



# --- explicit underscore/shared imports (wave2c r1) ---
from mojo.middle.exprtypes import _walk_ast
from mojo.middle.types import _LIST_RETURNING_METHODS, _STR_RETURNING_METHODS, _extract_init_expr, _import_targets, _mojo_type
