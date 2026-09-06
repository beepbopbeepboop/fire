"""Function/method generation for the GIMPLE backend.

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
    Parser, py_tokenize, _as_str,
)
import ast_rewriter
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc

def _gen_stmt_FunctionDef(gen, node: FunctionDef):
    # A nested `async def` (not an async generator) — whether nested
    # inside a struct method (device_context.mojo's `async def
    # wrapper(...) capturing -> None:` shape, discovered by gen_module's
    # dedicated struct-method-nested pass and registered in
    # _async_closure_api — see that dict's docstring) or nested inside
    # an ordinary top-level function's own body (Step I's
    # `@parameter async def wrapper(): ...` shape, discovered by
    # _compile_nested_async_functions and registered in
    # _nested_async_api) — was already fully compiled to its own C++20
    # coroutine unit by one of those two (disjoint-parent-shape)
    # discovery passes. It gets NO ordinary GIMPLE body/env-struct-alloc
    # here at all, exactly mirroring how a top-level supported async
    # function's FunctionDef is skipped entirely in gen_module's own
    # Phase 2a loop. Any call site referencing it resolves through
    # _async_closure_api (keyed by (current_func_name, name)) or
    # self._async_api's scoped push (for the top-level-function-nested
    # case — see gen_module's per-statement loop), not through anything
    # this statement itself would emit. A nested async def that turned
    # out NOT eligible for either discovery pass is also skipped here
    # (never falls through to ordinary closure-lifting, which has no
    # `await` support at all) — any call site referencing it then hits
    # its own honest, already-existing refusal instead.
    if node.is_async and not node.is_generator:
        return
    outer_closures = getattr(gen, '_all_closures', {}).get(
        gen.current_func_name, {})
    ci = outer_closures.get(node.name)
    if ci is None:
        gen._emit(f"  /* TODO: closure '{node.name}' (no pre-pass info) */")
        return
    # `len(...) > 0`, not a bare `if ci.captures`: a non-capturing nested
    # `def` has `ci.captures == []`, and an empty MojoList is a non-null
    # pointer -> truthy in the self-hosted backend, so a bare check made
    # every non-capturing closure allocate a bogus env and its call sites
    # prepend an empty env arg (`outer_inner (, x)`).
    if len(ci.captures) > 0:
        env_var  = f"_env_{node.name}"
        alloc_fn = f"_alloc_{ci.env_struct}"
        gen._declare_var(env_var, f"{ci.env_struct} *")
        gen._emit(f"  {env_var} = {alloc_fn} ();")
        for vname, vtype in ci.captures:
            if vname in ci.mut_names and not (vname in gen._captures and gen._env_param):
                # `{mut}`-capture-spec closure (ClosureInfo.mut_names):
                # store the local's own POINTER (not its dereferenced
                # value) so a write inside the nested closure's body is
                # visible here after it returns. `vname` is already a
                # heap-boxed pointer local at this point (`_seed_mut_
                # captured_local_types` declared it as `{vtype} *
                # vname` and _gen_stmt_VarDecl allocated it) -- NOT the
                # address of an ordinary stack scalar (`&vname`), which
                # this mechanism's first draft used and which `-fgimple`
                # rejects once that same local is also cast-assigned or
                # `return`ed elsewhere in this function (see _seed_mut_
                # captured_local_types's docstring for the hand-reduced
                # repro that surfaced this, via std/memory/span.mojo's
                # real `Span.count`).
                #
                # A capture that's ALSO already captured (by reference)
                # in the CURRENT function's own env is a doubly-nested
                # closure -- not yet supported transitively (see
                # bugs/CODEGEN_comptime_bracket_parametrized_function_
                # calls_silently_wrong.md's gap 3); falls through to
                # the by-value branch below rather than emit something
                # silently wrong.
                ptr_val = gen._new_val(f"{vtype} *", gen._cname(vname))
                gen._emit(f"  {env_var}->{gimple_ctypes._c_field_name(vname)} = {ptr_val};")
            # If vname is captured in the current function's own env, read from _env->vname.
            elif vname in gen._captures and gen._env_param:
                # GIMPLE: cannot use component_ref directly as RHS of struct store;
                # load into a temp first.
                tmp = gen._new_val(vtype, f"{gen._env_param}->{gimple_ctypes._c_field_name(vname)}")
                gen._emit(f"  {env_var}->{gimple_ctypes._c_field_name(vname)} = {tmp};")
            else:
                # Use _safe_coerce_emit to handle int→int64_t and other conversions.
                local_type = gen.var_types.get(vname, vtype)
                cname = gen._write_dest(vname)  # resolve capture path if nested
                gen._safe_coerce_emit(local_type, vtype, cname, f"{env_var}->{gimple_ctypes._c_field_name(vname)}")
        gen._closure_envs[node.name] = env_var
    else:
        gen._closure_envs[node.name] = ''


def _gen_stmt_ImportStmt(gen, node):
    # import module [as alias][, module2 [as alias2], ...] — handle every
    # target in a comma-separated list (node.extra), not just the first.
    for module, alias in gimple_ctypes._import_targets(node):
        # `_as_str` into FRESH names (`_mod`/`_al`, never reassigning the
        # loop vars): `ImportStmt.alias` is typed `object` so the self-hosted
        # backend erases it to int64_t, and reassigning `module`/`alias`
        # in place would unify those locals to int64_t too — then
        # `imported_symbols[local_name]` stringifies the char* pointer as a
        # decimal dict key. A name only ever assigned an `_as_str(...)`
        # (`-> str`) stays `char *`.
        _mod = _as_str(module)
        _al = _as_str(alias)
        # `import a.b.c` (no alias) binds the top-level package name `a` in
        # scope (Python semantics) — not the invalid C identifier "a.b.c".
        if _al:
            local_name = _al
        elif '.' in _mod:
            local_name = _mod[:_mod.index('.')]
        else:
            local_name = _mod
        gen.imported_symbols[local_name] = {
            'module': _mod,
            'return_type': 'unknown',
        }
        gen._module_alias_names.add(local_name)
        # Declare the module as an int marker for attribute access
        # This allows code like os.path.basename() to work
        if local_name not in gen.var_types:
            gen._declare_var(local_name, 'int64_t')
            # `_declare_var` renames a C-keyword module name to a safe
            # C identifier (e.g. `import struct` -> declares `_struct`,
            # since `struct` is a reserved C keyword) but the marker
            # assignment right below used the RAW `local_name` — a
            # mismatch between what got declared and what got assigned
            # to, producing literally invalid C ("struct = ...", parsed
            # as an anonymous-struct declaration missing its `{`) —
            # "expected '{' before '=' token". Route through _cname so
            # the assignment targets the SAME (possibly renamed) C
            # identifier the declaration used. Found via ctypes/util.py's
            # own `import struct`.
            # GIMPLE: an int64_t lvalue needs an int64_t-typed constant, not a
            # bare `0` (which is `int`) — that is a non-trivial integer_cst.
            gen._emit(f"  {gen._cname(local_name)} = (int64_t)0;  /* module marker */")



def _from_import_name_is_submodule(gen, module: str, name: str) -> bool:
    """True when `from module import name` binds a real SUBMODULE FILE
    (`module/name.py` or `module/name/__init__.py`), as opposed to an
    ordinary symbol (function/class/global) defined inside `module`'s
    own source — e.g. `from test.support import os_helper`, where
    `os_helper` names the file `test/support/os_helper.py`, not a name
    looked up inside `test/support/__init__.py` (see bugs/CODEGEN_
    generator_function_Lib_test_test_support.md's 2026-08-09 root-
    cause). A real top-level def/class/global-assignment for `name`
    inside `module`'s own parsed body always wins FIRST — mirrors
    CPython, where an attribute `__init__.py` actually sets on the
    package object (a function, class, or plain assignment) shadows
    the submodule-autoimport binding of the same name — so this only
    probes the filesystem once no such symbol is found. Uses
    `_parsed_import` (the same cached parse `_find_imported_struct`/
    `_find_generic_source` already use) and `_submodule_source_path`
    (the same search-path resolution `_compile_imported_module` uses)
    rather than inventing new resolution logic."""
    _path, _src, _stmts = gen._parsed_import(module)
    if _stmts:
        for s in _stmts:
            if isinstance(s, (gimple_ctypes.FunctionDef, gimple_ctypes.StructDef)) and s.name == name:
                return False
            if isinstance(s, gimple_ctypes.VarDecl) and s.name == name:
                return False
            if isinstance(s, gimple_ctypes.AssignStmt) and isinstance(s.target, gimple_ctypes.IdentExpr) \
                    and s.target.name == name:
                return False
            if isinstance(s, gimple_ctypes.MultiAssignStmt):
                for _t in s.targets:
                    if isinstance(_t, gimple_ctypes.IdentExpr) and _t.name == name:
                        return False
            # Real, common idiom: `module`'s own `__init__` RE-EXPORTS
            # `name` by importing it from one of ITS OWN submodules —
            # e.g. `std/memory/__init__.mojo` has `from .alloc import
            # alloc` (the free FUNCTION `alloc`, re-exported under the
            # same bare name as the submodule FILE `std/memory/
            # alloc.mojo` that defines it). Without this check, `from
            # std.memory import alloc` misclassified `alloc` as THE
            # SUBMODULE (the bare filesystem probe below finds `std/
            # memory/alloc.mojo` and, having no other evidence,
            # concludes "submodule") instead of the re-exported
            # function — confirmed via a real regression this exact
            # case caused (`dict.mojo`'s `_ensure_capacity` calling
            # `alloc(...)` as a bare function lost its extern
            # declaration entirely, "implicit declaration of function
            # 'alloc'"). Mirrors real Python: `__init__.py` executing
            # `from .alloc import alloc` REBINDS the package's `alloc`
            # attribute to the function, overwriting whatever the
            # submodule auto-import step bound it to first — an
            # explicit later rebinding always wins, exactly like the
            # def/class/assignment cases above.
            if (isinstance(s, gimple_ctypes.FromImportStmt) and not getattr(s, 'wildcard', False)):
                for _fip0 in gimple_ctypes._fromimport_names(s):
                    _rn = _as_str(_fip0[0])
                    _ra = _as_str(_fip0[1])
                    if (_ra if _ra else _rn) == name:
                        return False
    return gen._submodule_source_path(
        gimple_ctypes._join_import_member(module, name)) is not None


def _resolve_reexported_closure_func(gen, module: str, name: str, _depth: int = 0):
    """Follow a closure module's own `from SIBLING import (...)` re-exports
    to the top-level FunctionDef that actually defines `name`. Returns
    (FunctionDef, defining_module_name) or (None, None). Bounded recursion;
    parses are `_parsed_import`-cached so this is cheap."""
    if _depth > 4:
        return None, None
    _stmts = None
    try:
        _pi = gen._parsed_import(module)
        _stmts = _pi[2] if _pi else None
    except Exception:
        _stmts = None
    if not _stmts:
        # _parsed_import (imports.resolve_source) can't see a bare repo-local
        # `.py` sibling; resolve it the way _compile_imported_module does and
        # seed the shared cache so this parse is done at most once.
        try:
            _mp = None
            for _c in gen._module_candidate_paths(module):
                if os.path.exists(_c):
                    _mp = _c
                    break
            if _mp:
                with open(_mp) as _mf:
                    _msrc = _mf.read()
                _stmts = gimple_ctypes.ast_rewriter.rewrite(
                    gimple_ctypes.Parser(gimple_ctypes.py_tokenize(_msrc)).parse_module())
                gen._imported_src_cache[module] = (_mp, _msrc, _stmts)
        except Exception:
            _stmts = None
    if not _stmts:
        return None, None
    for _s in _stmts:
        if isinstance(_s, FunctionDef) and _s.name == name:
            return _s, module
    for _s in _stmts:
        if not isinstance(_s, gimple_ctypes.FromImportStmt) or getattr(_s, 'wildcard', False):
            continue
        for _fp in gimple_ctypes._fromimport_names(_s):
            _rn = _as_str(_fp[0]); _ra = _as_str(_fp[1])
            if (_ra if _ra else _rn) == name:
                _fn, _home = _resolve_reexported_closure_func(
                    gen, _s.module, _rn, _depth + 1)
                if _fn is not None:
                    return _fn, _home
    return None, None


def _gen_stmt_FromImportStmt(gen, node):
    # from module import name1, name2, ...
    # Per-lexical-scope import tracking: this statement executes in the
    # current lexical scope (a function/method body — top-level
    # FromImportStmts never reach here; gen_module's Phase 2a skips them),
    # so bind each imported name to its module in the CURRENT innermost
    # import scope. A later same-name import in the same body shadows the
    # earlier one, and a call site after this statement resolves to the
    # right module (the pre-scan in gen_func/_gen_struct_method/
    # _gen_lifted_closure already did the same, so even pre-passes agree).
    if not getattr(node, 'wildcard', False) and gen._import_scope_stack:
        _scope_qual = gen._resolve_import_module_qualifier(node.module)
        if _scope_qual:
            _scope = gen._import_scope_stack[-1]
            for _fip1 in gimple_ctypes._fromimport_names(node):
                name = _as_str(_fip1[0])
                alias = _as_str(_fip1[1])
                _scope[alias if alias else name] = _scope_qual
    for _fip2 in gimple_ctypes._fromimport_names(node):
        name = _as_str(_fip2[0])
        alias = _as_str(_fip2[1])
        symbol_name = alias if alias else name
        # A compiled free-function generator reached through a
        # function-body-scoped cross-module import: bind it exactly like
        # the top-level registration loop does (shared _generator_home_api,
        # keyed by "<DEFINING module's qualifier>::<ORIGINAL name>") and
        # skip the ordinary-symbol resolution below —
        # the defining module never emitted an ordinary C function for a
        # compiled generator (Phase 2a skip), so an ordinary extern/call
        # would reference a symbol nothing defines. do_imports-only, same
        # reason as the top-level site.
        if (getattr(gen, 'do_imports', False)
                and not getattr(node, 'wildcard', False)):
            _fi_gmh = getattr(gen, '_generator_home_api', {}).get(
                node.module.replace('.', '_').replace('-', '_') + '::' + name)
            if _fi_gmh is not None:
                gen._imported_generator_bindings[symbol_name] = _fi_gmh
                continue
        # `from PKG import SUBMOD` where SUBMOD names a real submodule
        # FILE (PKG/SUBMOD.py or PKG/SUBMOD/__init__.py), not a symbol
        # defined inside PKG's own source — register it exactly like
        # a plain `import PKG.SUBMOD as SUBMOD` would (_gen_stmt_
        # ImportStmt, just below): a genuine module marker (an int64_t
        # local declared and assigned 0), not a func/class symbol
        # entry. Without this, `_lower_MemberExpr` never recognizes
        # SUBMOD as a module at all — `SUBMOD.some_global` silently
        # fell through to the fully-dynamic runtime getattr dispatch on
        # an unresolved-identifier NULL placeholder instead of reading
        # the real cross-module global (see bugs/CODEGEN_generator_
        # function_Lib_test_test_support.md's 2026-08-09 root-cause:
        # `TESTFN = os_helper.TESTFN` via `from test.support import
        # os_helper`). A CALL through the member (`os_helper.foo(...)`)
        # is unaffected either way — that already goes through the
        # separate, already-working `_lower_call` member-call path.
        if not getattr(node, 'wildcard', False) \
                and gen._from_import_name_is_submodule(node.module, name):
            _sub_mod = f"{node.module}.{name}"
            if not (isinstance(gen.imported_symbols.get(symbol_name), dict)
                    and 'signature' in gen.imported_symbols[symbol_name]):
                gen.imported_symbols[symbol_name] = {
                    'module': _sub_mod,
                    'return_type': 'unknown',
                }
            gen._module_alias_names.add(symbol_name)
            if symbol_name not in gen.var_types:
                gen._declare_var(symbol_name, 'int64_t')
                # See _gen_stmt_ImportStmt's identical marker-assignment
                # comment: route through _cname so the assignment
                # targets the same (possibly C-keyword-renamed) local
                # _declare_var just declared.
                gen._emit(f"  {gen._cname(symbol_name)} = (int64_t)0;  "
                           f"/* module marker (from-import submodule) */")
            continue
        # A module-level VALUE imported from a module that is inline-compiled
        # into this same whole-program unit (`def test(): from ctypes import
        # cdll` where ctypes/__init__.py's `cdll = LibraryLoader(CDLL)` ran in
        # this closure): bind the alias to the OWNING module's globals-struct
        # field — the exact same `_{module}_globals.<field>` read the
        # `submod.GLOBAL` MemberExpr branch in _lower_MemberExpr emits for
        # qualified reads, including the pointer-boxing dance for globals
        # whose declared C type is a pointer but which are boxed int64_t at
        # the statement level. Without this, the alias fell through to the
        # bare no-signature registration below, every use compiled against a
        # weak variadic stub ("unavailable in compiled mode") or an
        # undeclared-identifier placeholder, and `cdll` never reached the
        # real LibraryLoader instance its defining module constructs.
        # `_global_to_module`/`_global_var_types` are whole-transitive-tree
        # tables populated when Phase 0 inline-compiles the owner module,
        # which strictly precedes any function-body walk that could contain
        # this statement. Owner must match EXACTLY (`_global_to_module` is
        # first-writer-wins across the tree — mirrors the identical caveat on
        # the MemberExpr branch). Aliases rename only the LOCAL symbol; the
        # field name stays the DEFINING module's own. A same-named genuine
        # local shadows nothing here: `symbol_name not in gen.var_types`
        # defers to it exactly like the submodule branch above.
        _gv_owner = getattr(gen, '_global_to_module', {}).get(name)
        if (not getattr(node, 'wildcard', False)
                and _gv_owner is not None
                and _gv_owner == node.module
                and name in gen._global_var_types
                and symbol_name not in gen.var_types):
            _gv_type = gen._global_var_types[name]
            _gv_ctype = ('int64_t'
                         if _gv_type in ('MojoDict *', 'MojoList *', 'MojoSet *')
                         else _gv_type)
            gen._declare_var(symbol_name, _gv_ctype)
            safe_owner = gimple_ctypes._c_field_name(_gv_owner) if _gv_owner else "root"
            _gv_field = f"_{safe_owner}_globals.{gimple_ctypes._c_field_name(name)}"
            _gv_decl = gen._global_c_decl_types.get(name, _gv_ctype)
            if _gv_ctype == 'int64_t' and _gv_decl.endswith(' *'):
                # Declared pointer C type boxed as int64_t: load through the
                # matching pointer type first, then cast via void * (the same
                # two-step GIMPLE-safe sequence _lower_IdentExpr's global-read
                # branch and the submod.GLOBAL branch both emit).
                raw_ptr = gen._new_val(_gv_decl, f'{_gv_field}')
                vp = gen._new_val('void *', f'(void *){raw_ptr}')
                gen._emit(f"  {gen._cname(symbol_name)} = (int64_t){vp};")
            else:
                gen._emit(f"  {gen._cname(symbol_name)} = {_gv_field};")
            continue
        # BUG-2026-021: resolve the name for real when the module is
        # resolvable — a function-scoped `from sibling import f` used to fall
        # straight to the bare no-signature registration below, so the
        # extern-preamble pass read it as "never resolved to any real
        # implementation" and emitted a WEAK STUB (`int64_t f (...)`
        # "unavailable in compiled mode") alongside the REAL `extern void
        # f (void);` another pass had already declared from the same import —
        # conflicting C types, hard GCC failure. Mirrors the top-level
        # Process-imports loop's own resolution chain: load_module() first
        # (stdlib/test modules), then the local-sibling source fallback.
        _fi_exports = None
        _fi_qual = None
        import module_loader as _mlmod_fi
        # Guard BEFORE calling load_module/resolve_module_path, not just
        # try/except around the call: this codegen's compiled try/except
        # does not reliably catch a raised exception, so a genuine
        # non-mojo-stdlib Python import (`from dataclasses import ...`,
        # real stdlib source myinterpreter.py itself uses) reached
        # module_loader's `raise` UNCAUGHT and crashed the whole
        # `MOJO_NO_SHIM=1 --dump` compile. See ModuleLoader.
        # can_resolve_module_path's docstring.
        if _mlmod_fi.can_resolve_module_path(node.module):
            try:
                _fi_exports = _mlmod_fi.load_module(node.module)
                _fi_path = _mlmod_fi._module_loader.resolve_module_path(node.module)
                if _fi_path and os.path.exists(_fi_path):
                    _fi_qual = _mlmod_fi.module_name_for_path(_fi_path)
            except Exception:
                _fi_exports = None
        if _fi_exports is None:
            try:
                _fi_exports, _fi_qual = gen._local_sibling_module_exports(node.module)
            except Exception:
                _fi_exports = None
        _fi_info = (_fi_exports or {}).get(name)
        if isinstance(_fi_info, dict) and _fi_info.get('signature'):
            if not (isinstance(gen.imported_symbols.get(symbol_name), dict)
                    and 'signature' in gen.imported_symbols[symbol_name]):
                _fi_sig = _fi_info['signature']
                if symbol_name != name:
                    import re as _re_fi
                    _fi_sig = _re_fi.sub(r'\b' + _re_fi.escape(name) + r'\b',
                                         symbol_name, _fi_sig, count=1)
                gen.imported_symbols[symbol_name] = {
                    'module': node.module,
                    'original_name': name,
                    'c_return_type': _fi_info.get('c_return_type', 'int64_t'),
                    'return_type': _fi_info.get('return_type'),
                    'parameters': _fi_info.get('parameters'),
                    'c_parameters': _fi_info.get('c_parameters'),
                    'signature': _fi_sig,
                }
            ret = _fi_info.get('c_return_type', 'int64_t')
            if symbol_name not in gen.func_return_types:
                gen.func_return_types[symbol_name] = ret
            if _fi_qual:
                # Same mode-dependent qualifier rule as the top-level
                # Process-imports loop (do_imports inlines siblings under
                # the dotted-import string sanitized; per-file dylib
                # pipelines use the path-derived qualifier).
                if getattr(gen, 'do_imports', False):
                    _fi_home = node.module.replace('.', '_').replace('-', '_')
                else:
                    _fi_home = _fi_qual
                gen._note_own_func_home(symbol_name, _fi_home)
                # BUG-2026-024: record the home module's own parameter
                # ctypes for THIS binding, exactly like the top-level
                # Process-imports loop's snapshot beside its
                # _note_own_func_home call. Function-body-scoped aliased
                # imports (`from mod.thaumic_tinkerer.eldritch_table import
                # add_essentia as et_add_ess` inside a test function) used
                # to leave _imported_home_param_types empty for the name,
                # so the call site's suffix fell through to the shared
                # bare-name slot and came up EMPTY (suffix-less symbol vs
                # the definition's suffixed one — implicit declaration).
                # Same "TYPE NAME" -> ctype transform as the top-level
                # site's c_parameters mirroring. Preferred source is the
                # DEFINING module's own FunctionDef resolved through THIS
                # gen's _signature_ctypes — the exact resolver the
                # definition side uses — because export-table c_parameters
                # can carry placeholder ctypes for struct params the
                # export pass didn't have registered (add_essentia's
                # EldritchTable * exported as int64_t hashed a different
                # suffix than the same function's own definition). Falls
                # back to c_parameters when the AST isn't resolvable.
                _fi_pts = None
                try:
                    for _fs in (gen._parsed_import(node.module)[2] or []):
                        if isinstance(_fs, gimple_ctypes.FunctionDef) and _fs.name == name:
                            _fi_pts = gen._signature_ctypes(_fs.params, _fs)
                            break
                except Exception:
                    _fi_pts = None
                if not _fi_pts:
                    _fi_cps = _fi_info.get('c_parameters')
                    if _fi_cps:
                        _fi_pts = [
                            ' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                            for cp in _fi_cps
                        ]
                if _fi_pts:
                    gen._imported_home_param_types[(_fi_home, symbol_name)] = list(_fi_pts)
            # Param defaults too — same gap as the top-level loop had
            # before its own BUG-2026-020 fix.
            try:
                _fi_fn = None
                for _fs in (gen._parsed_import(node.module)[2] or []):
                    if isinstance(_fs, gimple_ctypes.FunctionDef) and _fs.name == name:
                        _fi_fn = _fs
                        break
                _pd = getattr(_fi_fn, 'param_defaults', None) or {} if _fi_fn else {}
                if _pd:
                    _dl = list(_pd.items())
                    gen._func_param_defaults.setdefault(symbol_name, _dl)
                    try:
                        gen._func_param_defaults.setdefault(
                            gen._func_csym(symbol_name), _dl)
                    except Exception:
                        pass
            except Exception:
                pass
            continue
        # do_imports closure: a function-local `from M import name` where M
        # RE-EXPORTS `name` from a sibling (`from gimple_codegen import
        # _mojo_type`, gimple_codegen re-exporting it from gimple_ctypes).
        # Neither load_module (M isn't a stdlib/test module) nor _local_
        # sibling_module_exports (no .py path) resolves it, so it fell to
        # the bare no-signature registration → the extern pass emitted a
        # weak `int64_t name (...)` "unavailable in compiled mode" NULL
        # stub, and the call site bound to that (bare, unmangled) instead
        # of the real `name_<suffix>` the sibling's own compile emitted →
        # strcmp(NULL)/segfault on the shimless closure path. Follow M's
        # own `from SIBLING import (...)` re-exports to the real def and
        # register a properly-typed mangleable imported symbol.
        if (getattr(gen, 'do_imports', False)
                and not getattr(node, 'wildcard', False)
                and symbol_name == name
                and not (isinstance(gen.imported_symbols.get(symbol_name), dict)
                         and 'signature' in gen.imported_symbols[symbol_name])):
            _rx_fn, _rx_home = _resolve_reexported_closure_func(gen, node.module, name)
            if _rx_fn is not None and _rx_fn.return_type is not None:
                _rx_ret = gen._resolve_type(_rx_fn.return_type)
                _rx_pts = []
                for _rxi, (_rxpn, _rxpt) in enumerate(_rx_fn.params):
                    if _rxi == 0 and _rxpn == 'self':
                        continue
                    _rx_pts.append(gen._param_ctype(_rxpn, _rxpt, _rx_fn))
                _rx_sig = f"{_rx_ret} {name} ({', '.join(_rx_pts) if _rx_pts else 'void'})"
                gen.imported_symbols[symbol_name] = {
                    'module': _rx_home,
                    'original_name': name,
                    'c_return_type': _rx_ret,
                    'return_type': _rx_ret,
                    'c_parameters': list(_rx_pts),
                    'signature': _rx_sig,
                }
                gen._mangled_funcs.add(name)
                gen.func_return_types.setdefault(name, _rx_ret)
                gen.func_param_types.setdefault(name, list(_rx_pts))
                if _rx_home:
                    gen._note_own_func_home(
                        name, _rx_home.replace('.', '_').replace('-', '_'))
                continue
        # Use known signature if available. Default to 'int64_t' (NOT
        # 'int') for unknown symbols — this must match the fallback
        # return type every other unknown-callee path in this file
        # uses (e.g. func_return_types.get(fname, 'int64_t') at many
        # call sites, and the unavailable-stub generator's own
        # `int64_t <name> (...)` fallback signature below). A function-
        # scoped `from mod import Name` (e.g. `from inspect import
        # Parameter, Signature` inside enum.py's __signature__, `from
        # _colorize import can_colorize` inside argparse.py's
        # _set_color, `from struct import unpack` inside gettext.py's
        # gettext) for a symbol with no _KNOWN_SIGS entry used to
        # register 'int' here — but the call site's own SSA temp gets
        # pre-declared 'int64_t' by the (separate, generic) prescan
        # that seeds var/temp types, and the "unavailable in compiled
        # mode" stub emitted for any never-linked symbol is ALSO
        # declared to return 'int64_t'. The stale 'int' registration
        # here was the only thing disagreeing with both, producing a
        # real 'int'/'int64_t' GIMPLE type mismatch ("invalid
        # conversion in gimple call") at the call site — confirmed via
        # a minimal repro (`from _colorize import can_colorize` inside
        # a method, then `if can_colorize(): ...`) and seen at scale
        # across Lib/argparse.py (~15x), Lib/enum.py (~10x),
        # Lib/gettext.py (~5x) in a `mojo.py build
        # Lib/subprocess.py` run.
        sig = gen._KNOWN_SIGS.get(symbol_name)
        ret = sig[0] if sig else 'int64_t'
        # Don't clobber an entry link-mode's Phase 0 pre-pass
        # (_register_link_imports, gen_module, self.link_imports=True
        # only) already resolved to the real defining module's C
        # signature — this statement-lowering path runs AFTER that
        # pre-pass (it fires while walking the function BODY that
        # contains this FromImportStmt, whereas Phase 0 runs before any
        # body is walked at all), so an unconditional overwrite here
        # DOWNGRADES an already-correctly-resolved entry (with a real
        # 'signature'/'c_return_type', enough for the extern-decl
        # preamble to link against the real symbol) back down to this
        # bare 'module'+'return_type'-only shape, which the preamble's
        # imported_symbols loop (~gimple_codegen.py:32472's "no
        # 'signature' was ever attached" branch) reads as "never
        # resolved to any real implementation" and emits a
        # do_imports=False-mode bare `extern` with no real definition
        # ever linked in — an undefined symbol at LINK time (confirmed
        # via `Lib/runpy.py`'s function-scoped `from pkgutil import
        # read_code`/`get_importer`, see bugs/hard/CODEGEN_function_
        # scoped_import_call_unresolved_at_link.md). Only fall through
        # to the bare-stub registration below when Phase 0 didn't
        # already resolve this exact name to a real signature.
        if not (isinstance(gen.imported_symbols.get(symbol_name), dict)
                and 'signature' in gen.imported_symbols[symbol_name]):
            gen.imported_symbols[symbol_name] = {
                'module': node.module,
                'return_type': ret,
            }
        # Track in func_return_types so calls know the return type
        if symbol_name not in gen.func_return_types:
            gen.func_return_types[symbol_name] = ret


def _gen_stmt_ComptimeIfStmt(gen, node):
    val = gen._eval_const_bool(node.condition)
    if val is True:
        for s in node.then_body:
            gen.gen_stmt(s)
        return
    if val is False:
        # Try each elif branch before falling to else
        for elif_cond, elif_body in (getattr(node, 'elifs', None) or []):
            elif_val = gen._eval_const_bool(elif_cond)
            if elif_val is True:
                for s in elif_body:
                    gen.gen_stmt(s)
                return
            if elif_val is False:
                continue
            # Unknown at compile time: emit as runtime branch
            _, cv = gen.lower_expr(elif_cond)
            bb_t = gen._new_bb(); bb_m = gen._new_bb()
            gen._emit(f"  if ({cv}) goto {bb_t}; else goto {bb_m};")
            gen._emit_label(bb_t)
            for s in elif_body:
                gen.gen_stmt(s)
            gen._emit(f"  goto {bb_m};")
            gen._emit_label(bb_m)
            return
        if node.else_body:
            for s in node.else_body:
                gen.gen_stmt(s)
        return
    # Condition unknown at compile time: emit full runtime if-elif-else chain
    _, cond_v = gen.lower_expr(node.condition)
    bb_merge = gen._new_bb()
    elifs = getattr(node, 'elifs', None) or []
    has_else = bool(node.else_body)
    # First branch
    if elifs or has_else:
        bb_false = gen._new_bb()
    else:
        bb_false = bb_merge
    bb_true = gen._new_bb()
    gen._emit(f"  if ({cond_v}) goto {bb_true}; else goto {bb_false};")
    gen._emit_label(bb_true)
    for s in node.then_body:
        gen.gen_stmt(s)
    gen._emit(f"  goto {bb_merge};")
    # elif chains
    for _elif_idx, (elif_cond, elif_body) in enumerate(elifs):
        gen._emit_label(bb_false)
        elif_tt, elif_cv = gen.lower_expr(elif_cond)
        elif_cv = gen._ensure_bool_cond(elif_tt, elif_cv)
        bb_elif_true = gen._new_bb()
        if _elif_idx < len(elifs) - 1 or has_else:
            bb_false = gen._new_bb()
        else:
            bb_false = bb_merge
        gen._emit(f"  if ({elif_cv}) goto {bb_elif_true}; else goto {bb_false};")
        gen._emit_label(bb_elif_true)
        for _elif_stmt in elif_body:
            gen.gen_stmt(_elif_stmt)
        gen._emit(f"  goto {bb_merge};")
    if has_else:
        gen._emit_label(bb_false)
        for s in node.else_body:
            gen.gen_stmt(s)
        gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)


def _gen_stmt_ComptimeVarStmt(gen, node):
    # Comptime variables are compile-time only and don't generate runtime
    # code, but a later comptime `if`/expression may reference this name
    # (e.g. `comptime FOO = 1` then `if FOO == 1:`) — record the folded
    # value so _eval_const's IdentExpr case can resolve it.
    val = gen._eval_const(node.value)
    if val is not None:
        gen._comptime_vals[node.target] = val
    if isinstance(node.value, gimple_ctypes.ListExpr):
        gen._comptime_list_asts[node.target] = node.value
    return


def _gen_stmt_GlobalStmt(gen, node):
    # Mark each listed name as a module-level global so reads/writes in this
    # function route to the module struct (_modname_globals.x) rather than a local.
    for name in node.names:
        gen._func_declared_globals.add(name)
        # Also seed var_types with the global's type for type-inference purposes,
        # but do NOT let it shadow the global-access path: _func_declared_globals
        # is checked before var_types in the IdentExpr read/write paths.
        if name in gen._global_var_types and name not in gen.var_types:
            gen.var_types[name] = gen._global_var_types[name]


def _gen_stmt_ComptimeForStmt(gen, node):
    unrolled = False
    if (isinstance(node.iterable, gimple_ctypes.CallExpr) and
            isinstance(node.iterable.func, gimple_ctypes.IdentExpr) and
            node.iterable.func.name == 'range'):
        args = node.iterable.args
        ivals = [gen._eval_const_int(a) for a in args]
        if len(ivals) == 1 and ivals[0] is not None:
            start, stop, step = 0, ivals[0], 1
            unrolled = True
        elif len(ivals) == 2 and all(v is not None for v in ivals):
            start, stop, step = ivals[0], ivals[1], 1
            unrolled = True
        elif len(ivals) == 3 and all(v is not None for v in ivals):
            start, stop, step = ivals[0], ivals[1], ivals[2]
            unrolled = True
        if unrolled and step != 0:
            if node.target not in gen.var_types:
                gen._declare_var(node.target, 'int64_t')
            i = start
            while (step > 0 and i < stop) or (step < 0 and i > stop):
                gen._emit(f"  {node.target} = {i};")
                for s in node.body:
                    gen.gen_stmt(s)
                i += step
            return
    if not unrolled:
        pass


def _selfhost_gen_self_param_ctype(gen, pname, ptype, node) -> str | None:
    """Self-hosting bootstrap only: in this compiler's OWN extracted GIMPLE
    backend modules (`gimple_*.py`), the former `GimpleGen` methods now live
    as module-level functions whose first parameter is the `GimpleGen`
    instance, conventionally named `gen` (`gimple_gen_*.py` / `gimple_cpp_*.py`)
    or `self` (`gimple_module_gen.py`'s `gen_module_impl`). Those params carry
    no annotation, so the generic resolver boxes them to opaque `int64_t` —
    and then EVERY `gen.<field>` / `gen.<method>(...)` inside the function
    lowers to a stubbed no-op or a runtime `_mojo_dispatch_getattr`, gutting
    the function body in the self-hosted binary (the compiled `compile_to_gimple`
    silently produced an empty `.ci` for every input; see doc/architecture.html
    §6 "roadmap to remove the shim"). Typing that first param as the real
    `GimpleGen *` struct pointer restores static field/method resolution.

    Narrow by construction: only an UNANNOTATED FIRST parameter named exactly
    `gen`/`self`, only while compiling a `.py` file named `gimple*` under this
    repo (the self-hosting bootstrap is always this compiler's own Python
    source — no `.mojo` file is ever part of it), and only when `GimpleGen`
    is actually a registered struct in this compile."""
    if ptype is not None:
        return None
    bare = pname.lstrip('*')
    if bare not in ('gen', 'self'):
        return None
    ps = getattr(node, 'params', None) or []
    if not ps or ps[0][0].lstrip('*') != bare:
        return None
    cf = getattr(gen, '_current_filename', None)
    if not cf or not cf.endswith('.py'):
        return None
    base = gimple_ctypes.os.path.basename(cf)
    if not base.startswith('gimple'):
        return None
    cur_abs = gimple_ctypes.os.path.abspath(cf)
    sd = gimple_codegen._SELFHOST_DIR
    if not (cur_abs == sd or cur_abs.startswith(sd + '/')):
        return None
    # Fires only once the GimpleGen registry pre-pass has run for this
    # (shared) compile — see _selfhost_register_gimplegen in gimple_codegen
    # .py, which parses `class GimpleGen`, unions in the fields the extracted
    # backend helpers bind (`_selfhost_scan_gimplegen_extra_fields`), routes
    # the synthetic StructDef through `_imported_typedef_structs`, and locks
    # a frozen `GimpleGen_*` signature table via `_selfhost_locked_param_
    # types`. Without that, typing `self` as a struct pointer just trades
    # "silently stubbed" for hard arity / pointer-vs-int errors at every
    # `self.<method>()` call site.
    if not getattr(gen, '_selfhost_gimplegen_registered', False):
        return None
    return 'GimpleGen *'


_SELFHOST_EXTRA_FIELD_CACHE: dict = {}


_SELFHOST_LITERAL_CTM = {DictExpr: 'MojoDict *', ListExpr: 'MojoList *',
                         TupleExpr: 'MojoList *', SetExpr: 'MojoSet *',
                         StringLiteral: 'char *', BoolLiteral: '_Bool',
                         IntLiteral: 'int64_t'}
_SELFHOST_CALL_CTM = {'set': 'MojoSet *', 'frozenset': 'MojoSet *',
                      'dict': 'MojoDict *', 'list': 'MojoList *'}


def _selfhost_literal_ctype(_val):
    """ctype for a literal / builtin-container-call RHS, or None."""
    _ct = _SELFHOST_LITERAL_CTM.get(type(_val))
    if _ct is None and isinstance(_val, CallExpr) and isinstance(_val.func, IdentExpr):
        _ct = _SELFHOST_CALL_CTM.get(_val.func.name)
    return _ct


_SELFHOST_ANN_CTM = {'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                     'list': 'MojoList *', 'List': 'MojoList *',
                     'set': 'MojoSet *', 'Set': 'MojoSet *',
                     'frozenset': 'MojoSet *',
                     'str': 'char *', 'String': 'char *',
                     'bool': '_Bool', 'Bool': '_Bool',
                     'int': 'int64_t', 'Int': 'int64_t',
                     'float': 'double', 'Float64': 'double'}


def _selfhost_ann_ctype(_ann):
    """ctype for a class-body / param type annotation string, or None.
    `X | None` / `Optional[X]` → `X *` for a struct name X; builtins mapped
    via _SELFHOST_ANN_CTM. Conservative: unknown → None (caller keeps its
    own default)."""
    if not isinstance(_ann, str):
        return None
    _s = _ann.strip()
    for _drop in (' | None', 'None | ', 'Optional[', ']'):
        _s = _s.replace(_drop, '')
    _s = _s.strip()
    if not _s:
        return None
    _base = _s.split('[', 1)[0].split('.')[-1].strip()
    if _base in _SELFHOST_ANN_CTM:
        return _SELFHOST_ANN_CTM[_base]
    # A bare CapWord names a struct type → pointer.
    if _base and _base[0].isupper() and _base.isidentifier():
        return f'{_base} *'
    return None


def _selfhost_merge_field(_fields: dict, _name: str, _ct: str):
    _cur = _fields.get(_name)
    if _cur is None or (_cur in ('int', 'int64_t', '_Bool') and _ct.endswith(' *')):
        _fields[_name] = _ct


def _selfhost_scan_gimplegen_extra_fields() -> dict:
    """`{attr_name: ctype}` for every GimpleGen instance attribute first
    bound OUTSIDE `class GimpleGen`'s own body — i.e. `gen.<attr> = <literal>`
    / `self.<attr> = <literal>` inside the ~344 extracted backend helper
    functions (`gen.bb_counter = 2` in gimple_gen_infra.py, `gen._loop_depth
    = ...` in gimple_gen_calls.py, ...). The `class GimpleGen` scan can't see
    these, so they default to opaque `int` and a real pointer stored into
    that field truncates → segfault.

    Only literal RHS is trustworthy for a ctype; `gen.x = f()` gives nothing
    and is left to `_inferred_param_types` / the frozen table. Cached on the
    mtime set of all `gimple_*.py` under _SELFHOST_DIR."""
    import glob as _glob
    _sd = gimple_codegen._SELFHOST_DIR
    _files = sorted(_glob.glob(gimple_ctypes.os.path.join(_sd, 'gimple_*.py')))
    _key = tuple((f, gimple_ctypes.os.path.getmtime(f)) for f in _files)
    _hit = _SELFHOST_EXTRA_FIELD_CACHE.get('k')
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _fields: dict = {}
    for _f in _files:
        try:
            _mod = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _fn in _mod:
            if not (isinstance(_fn, FunctionDef) and _fn.params
                    and _fn.params[0][0].lstrip('*') in ('gen', 'self')):
                continue
            _p0 = _fn.params[0][0].lstrip('*')
            for _n in gimple_exprtypes._walk_ast(_fn.body):
                # A chained assignment (`units = gen._stackswitch_coro_c_
                # units = []`, gimple_gen_coro.py's own lazy-init idiom)
                # parses as MultiAssignStmt (multiple `targets`), not
                # AssignStmt (one `target`) -- missing this case here left
                # `_stackswitch_coro_c_units` (and any other field first
                # bound this way) undetected, so `gen`/`self` stayed typed
                # as an opaque struct with no such member, and a real
                # self-hosted compile of the module doing the chained
                # assignment failed to resolve it ("'GimpleGen' has no
                # member named ...").
                if isinstance(_n, MultiAssignStmt):
                    _targets = _n.targets
                elif isinstance(_n, AssignStmt):
                    _targets = [_n.target]
                else:
                    continue
                for _tgt in _targets:
                    if not (isinstance(_tgt, MemberExpr)
                            and isinstance(_tgt.obj, IdentExpr)
                            and _tgt.obj.name == _p0):
                        continue
                    _ct = _selfhost_literal_ctype(_n.value)
                    if _ct is not None:
                        _selfhost_merge_field(_fields, _tgt.member, _ct)
    _SELFHOST_EXTRA_FIELD_CACHE['k'] = (_key, _fields)
    return _fields


def _selfhost_gimplegen_field_types(gg_cls) -> dict:
    """`{field_name: ctype}` for `class GimpleGen` — its own `__init__` /
    method / class-body `self.X = <literal>` writes (compact literal-only
    inference, everything else → `int64_t`, refined later by
    `_inferred_param_types` / `_mojo_dispatch_getattr`), UNIONed with the
    extracted-helper writes (`_selfhost_scan_gimplegen_extra_fields`).

    This is what a nested temp_gen that never sees `class GimpleGen`'s
    StructDef in its own `stmts`/`imported_stmts` registers into the shared
    `struct_field_types['GimpleGen']` so `self`/`gen` params can be typed."""
    _fields: dict = dict(_selfhost_scan_gimplegen_extra_fields())
    if gg_cls is None:
        return _fields
    # class-body attrs (`_KNOWN_SIGS = {...}`, `_cpp_kwfwd_counter = 0`, ...)
    for _fld in getattr(gg_cls, 'fields', []):
        if isinstance(_fld, AssignStmt) and isinstance(_fld.target, IdentExpr):
            _ct = (_selfhost_ann_ctype(getattr(_fld, 'type_ann', None))
                   or _selfhost_literal_ctype(_fld.value))
            if _ct is not None:
                _selfhost_merge_field(_fields, _fld.target.name, _ct)
        elif isinstance(_fld, VarDecl) and _fld.name:
            _ct = _selfhost_ann_ctype(getattr(_fld, 'type_ann', None))
            _selfhost_merge_field(_fields, _fld.name, _ct or 'int64_t')
    # `__init__(self, ..., module_name="", ...)` param defaults: a bare
    # `self.module_name = module_name` in the body carries no literal RHS,
    # so infer the field ctype from the parameter's own default value /
    # annotation. Without this `module_name` stayed int64_t and every
    # `gen.module_name`-based module-name compare (`_global_to_module`
    # ownership, `_<mod>_globals` struct routing) read boxed garbage.
    _init_param_ct: dict = {}
    for _m in getattr(gg_cls, 'methods', []):
        if _m.name != '__init__':
            continue
        for _pn, _pt in (getattr(_m, 'params', None) or []):
            _bare = _pn.lstrip('*')
            _pc = _selfhost_ann_ctype(_pt)
            if _pc is not None:
                _init_param_ct[_bare] = _pc
        for _pn2, _dv in (getattr(_m, 'param_defaults', None) or {}).items():
            _bare2 = _pn2.lstrip('*')
            if _bare2 not in _init_param_ct:
                _lc = _selfhost_literal_ctype(_dv)
                if _lc is not None:
                    _init_param_ct[_bare2] = _lc
    # `self.X = <literal>` in every method body (dominated by __init__)
    for _m in getattr(gg_cls, 'methods', []):
        for _n in gimple_exprtypes._walk_ast(_m.body):
            if (isinstance(_n, AssignStmt)
                    and isinstance(_n.target, MemberExpr)
                    and isinstance(_n.target.obj, IdentExpr)
                    and _n.target.obj.name == 'self'):
                _ct = (_selfhost_ann_ctype(getattr(_n, 'type_ann', None))
                       or _selfhost_literal_ctype(_n.value))
                if _ct is None and isinstance(_n.value, IdentExpr):
                    _ct = _init_param_ct.get(_n.value.name)
                _selfhost_merge_field(_fields, _n.target.member, _ct or 'int64_t')
    return _fields


def _selfhost_gimplegen_dict_val_types(gg_cls) -> dict:
    """`{field_name: (outer_val_ctype, nested_val_ctype_or_None, raw_ann)}` for every
    `class GimpleGen` instance/class field annotated `dict[K, V]` (or
    `dict[K, dict[K2, V2]]`) — parsed straight from the real declared
    annotation, bracket-aware (so `dict[str, dict[str, str]]` yields
    `('MojoDict *', 'char *')`, not a mangled 3-way naive split).

    A nested temp_gen compiling a backend `gimple_*.py` module never sees
    `class GimpleGen`'s StructDef, so `_seed_struct_field_types`'
    `_annotation_dict_val_type` seeding of `_field_dict_val_types` /
    `_field_dict_nested_val_types` never runs for it — `gen.struct_field_types
    [k]` / `.get(k, {})` then loses its `MojoDict *` value type and every
    `member in field_map` / `_known_field_type` lookup silently no-ops on an
    int64_t. This recovers exactly that seeding for GimpleGen."""
    _out: dict = {}
    if gg_cls is None:
        return _out

    def _val_cts(_ann):
        if not isinstance(_ann, str):
            return None
        _s = _ann.strip()
        if not ((_s.startswith('dict[') or _s.startswith('Dict['))
                and _s.endswith(']')):
            return None
        _inner = _s[_s.index('[') + 1:-1]
        _parts = gimple_ctypes._split_top_level_commas(_inner)
        if len(_parts) != 2:
            return None
        _vann = _parts[1].strip()
        _outer = _selfhost_ann_ctype(_vann)
        if _outer is None:
            _outer = 'int64_t'
        _nested = None
        if _outer == 'MojoDict *':
            _nv = _val_cts(_vann)
            if _nv is not None:
                _nested = _nv[0]
        elif _outer in ('MojoList *', 'MojoSet *'):
            # `dict[K, list[E]]` / `dict[K, set[E]]` — E, so `d.get(k)[i]`
            # / `for x in d.get(k)` reads with the right accessor instead
            # of boxing (e.g. `func_param_types: dict[str, list[str]]` ->
            # `func_param_types.get(fn)[0]` must be a real `char *`, not a
            # pointer-decimal cast target).
            _vbase = _vann.split('[', 1)[0].strip()
            if _vbase in ('list', 'List', 'set', 'Set', 'frozenset') and '[' in _vann:
                _einner = _vann[_vann.index('[') + 1:_vann.rindex(']')].strip()
                _eparts = gimple_ctypes._split_top_level_commas(_einner)
                if len(_eparts) == 1 and _eparts[0].strip():
                    _ec = _selfhost_ann_ctype(_eparts[0].strip())
                    if _ec is not None and _ec != 'int64_t':
                        _nested = _ec
        return (_outer, _nested)

    def _consider(_tgt, _ann):
        _fname = None
        if (isinstance(_tgt, MemberExpr) and isinstance(_tgt.obj, IdentExpr)
                and _tgt.obj.name == 'self'):
            _fname = _tgt.member
        elif isinstance(_tgt, IdentExpr):
            _fname = _tgt.name
        if _fname is None or _fname in _out:
            return
        _r = _val_cts(_ann)
        if _r is not None:
            _out[_fname] = (_r[0], _r[1], str(_ann).strip())

    for _fld in getattr(gg_cls, 'fields', []):
        if isinstance(_fld, AssignStmt):
            _consider(_fld.target, getattr(_fld, 'type_ann', None))
        elif isinstance(_fld, VarDecl) and _fld.name:
            _consider(IdentExpr(_fld.name), getattr(_fld, 'type_ann', None))
    for _m in getattr(gg_cls, 'methods', []):
        for _n in gimple_exprtypes._walk_ast(_m.body):
            if isinstance(_n, AssignStmt) and getattr(_n, 'type_ann', None):
                _consider(_n.target, str(_n.type_ann))
    return _out


def _selfhost_extracted_fn_index() -> dict:
    """`{fn_name: FunctionDef}` for every top-level `def fn(gen|self, ...)`
    across the backend `gimple_*.py` modules — the extracted helper that a
    `class GimpleGen` delegate method `return <alias>.<fn>(self, ...)`
    forwards to. Cached with the field scanner's cache key."""
    _hit = _SELFHOST_EXTRA_FIELD_CACHE.get('fnidx')
    import glob as _glob
    _sd = gimple_codegen._SELFHOST_DIR
    _files = sorted(_glob.glob(gimple_ctypes.os.path.join(_sd, 'gimple_*.py')))
    _key = tuple((f, gimple_ctypes.os.path.getmtime(f)) for f in _files)
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _idx: dict = {}
    for _f in _files:
        try:
            _mod = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _fn in _mod:
            if (isinstance(_fn, FunctionDef) and _fn.params
                    and _fn.params[0][0].lstrip('*') in ('gen', 'self')
                    and _fn.name not in _idx):
                _idx[_fn.name] = _fn
    _SELFHOST_EXTRA_FIELD_CACHE['fnidx'] = (_key, _idx)
    return _idx


def _selfhost_gimplegen_frozen_sigs(gen, gg_cls) -> dict:
    """`{GimpleGen_<m>: (ret_ctype, [param_ctypes], [(pname, default_ast)])}` —
    a deterministic signature for every `class GimpleGen` method, computed
    ONCE against the root gen and shared/locked into every temp_gen so
    forward-decl and definition agree by construction (`_infer_param_types`
    is not pure — it reads the growing per-instance `struct_field_types`).

    Return/param types: the method's own annotation if it has one; else, for
    a one-line forwarding delegate `return <alias>.<fn>(self, ...)`, the
    extracted helper `<fn>`'s annotation at the same position; else
    `int64_t`. `self` → `GimpleGen *`."""
    if gg_cls is None:
        return {}
    _idx = _selfhost_extracted_fn_index()

    def _fn_delegate_target(_m):
        _body = [s for s in _m.body
                 if not (isinstance(s, ExprStmt)
                         and isinstance(s.value, StringLiteral))]
        if (len(_body) == 1 and isinstance(_body[0], ReturnStmt)
                and isinstance(_body[0].value, CallExpr)
                and isinstance(_body[0].value.func, MemberExpr)
                and isinstance(_body[0].value.func.obj, IdentExpr)):
            return _idx.get(_body[0].value.func.member)
        return None

    # Signal-based param inference for the extracted helpers and for a
    # method's own body. Run against the (nearly-empty struct_field_types)
    # root gen so the impure struct-field-shape-matching branch of
    # `_infer_param_types` never engages — only the pure list/dict/string/
    # iteration/`len()` signals — keeping the result identical in every
    # temp_gen.
    _inf_cache: dict = {}

    def _inferred(_fn):
        _k = id(_fn)
        if _k not in _inf_cache:
            try:
                _inf_cache[_k] = gen._infer_param_types(_fn) or {}
            except Exception:
                _inf_cache[_k] = {}
        return _inf_cache[_k]

    def _param_ct(_ann, _pn, _tgt_fn, _tgt_pn, _pos, _self_fn):
        if _ann is not None:
            return gen._resolve_type(_ann)
        if _tgt_fn is not None and _pos < len(_tgt_fn.params):
            _ta = _tgt_fn.params[_pos][1]
            if _ta is not None:
                return gen._resolve_type(_ta)
        _ct = _inferred(_tgt_fn).get(_tgt_pn) if _tgt_fn is not None else None
        if _ct is None:
            _ct = _inferred(_self_fn).get(_pn)
        if _ct is not None:
            return _ct
        # A parameter's own default VALUE is type evidence (mirrors
        # gimple_module_gen.py's method-param pass): `sentinel='...'` is
        # `char *`, `is_self=False` is `_Bool`.
        for _dsrc in (_self_fn, _tgt_fn):
            if _dsrc is None:
                continue
            _dv = (getattr(_dsrc, 'param_defaults', None) or {}).get(
                _self_fn is _dsrc and _pn or _tgt_pn)
            if isinstance(_dv, StringLiteral):
                return 'char *'
            if isinstance(_dv, BoolLiteral):
                return '_Bool'
        return 'int64_t'

    def _ret_ct(_m, _tgt_fn):
        if getattr(_m, 'return_type', None) is not None:
            return gen._resolve_type(_m.return_type)
        if _tgt_fn is not None:
            if getattr(_tgt_fn, 'return_type', None) is not None:
                return gen._resolve_type(_tgt_fn.return_type)
            try:
                _r = gen._infer_return_type(_tgt_fn.body)
                if _r:
                    return _r
            except Exception:
                pass
        try:
            _r = gen._infer_return_type(_m.body)
            if _r:
                return _r
        except Exception:
            pass
        return 'int64_t'

    _out: dict = {}
    for _m in gg_cls.methods:
        if _m.name == '__init__':
            continue
        _tgt = _fn_delegate_target(_m)
        _rc = _ret_ct(_m, _tgt)
        _pcs = []
        _has_star = False
        for _i, (_pn, _pt) in enumerate(_m.params):
            if _pn.startswith('*'):
                _has_star = True
                break
            if _i == 0 and _pn == 'self':
                _pcs.append('GimpleGen *')
            else:
                # delegate forwards self as its own arg 0, so target pos == _i
                _tgt_pn = (_tgt.params[_i][0]
                           if _tgt is not None and _i < len(_tgt.params) else _pn)
                _pcs.append(_param_ct(_pt, _pn, _tgt, _tgt_pn, _i, _m))
        if _has_star:
            continue   # variadic — leave to the normal passes
        _dflts = [(pn, dv) for pn, dv in (getattr(_m, 'param_defaults', None) or {}).items()]
        _out[f'GimpleGen_{_m.name}'] = (_rc, _pcs, _dflts)
    return _out


def _signature_ctypes(gen, params, node, self_struct=None, sentinel='...') -> list:
    """C param-type list for a function/method.
    - **kwargs -> 'MojoDict *' (a real trailing parameter).
    - *args     -> 'MojoList *' when the function ALSO has **kwargs (the
      forwarding pattern f(self, *args, **kwargs): the parser flattens the
      call's spreads, so the caller passes the list/dict directly -> concrete
      params, no packing). Otherwise the packing `sentinel` ('...' for
      func_param_types, 'MojoList *' for emitted declarations), and the rest
      collapse into it.
    """
    has_kw = any(pn.startswith('**') for pn, _ in (params or []))
    out = []
    seen_vararg = False
    for i, (pn, pt) in enumerate(params or []):
        if pn.startswith('**'):
            out.append('MojoDict *')
        elif pn.startswith('*'):
            if has_kw:
                out.append('MojoList *')      # pass-through: concrete list param
            elif not seen_vararg:
                out.append(sentinel)          # packing convention
                seen_vararg = True
            # After *args, continue to catch any trailing `out` params that also
            # appear in the definition and must match the forward declaration.
        elif i == 0 and pn == 'self' and self_struct:
            # `_as_str`: `self_struct` arrives through a parameter that
            # defaults to None, so the self-hosted backend types it int64_t.
            # `f"{self_struct} *"` then formats the struct name's `char *`
            # bits as a DECIMAL and stores `"45740546496 *"` into
            # `func_param_types[method]` — every later `({that}){self}`
            # receiver cast in the generated C is then a raw heap address
            # (`_t34 = (45740546496 *)self;`), invalid and ASLR-unstable.
            out.append(f"{_as_str(self_struct)} *")
        elif i == 0 and _selfhost_gen_self_param_ctype(gen, pn, pt, node):
            out.append('GimpleGen *')
        elif (self_struct and isinstance(pt, str) and pt.split('[', 1)[0].strip() == self_struct
                and self_struct in gen.struct_field_types):
            # A non-self param whose annotation is a bracketed generic
            # instantiation of THIS SAME struct (e.g. List.extend(mut
            # self, var other: List[Self.T, ...])) means "another
            # instance of the struct I'm compiling," not the builtin
            # generic — but _mojo_type's List/Dict/Set/Span bracket
            # handling can't distinguish those and always erases to the
            # runtime's boxed representation (MojoList*/MojoDict*/...).
            # That's correct for every OTHER file merely using List[T]/
            # Dict[K,V]/etc, but wrong here, in the one file that IS
            # List/Dict/Set/Span's own real implementation — `other`
            # needs the real struct pointer so `other->_len` etc. resolve
            # against the actual fields, not the runtime's builtin ones.
            out.append(f"{_as_str(self_struct)} *")
        else:
            # Method context: consult the method's QUALIFIED
            # "Struct_method" inferred-param entry (usage-based inference
            # and the cross-call scalar contract both store there) before
            # falling back to _param_ctype, which can only see BARE
            # function-name keys and so silently missed every method's
            # resolved types — leaving unannotated varargs-method params
            # at the int64_t default in _mangled_signature_ctypes /
            # func_param_types even after the qualified registry held the
            # real type, so pre-definition call sites converted arguments
            # against the stale boxed type ("makes pointer from integer
            # without a cast", self-hosted myinterpreter.py's
            # Interpreter__call_dunder). Mirrors the precedence the
            # gen_module forward-declaration loop applies.
            _msig_ct = None
            if pt is None and self_struct and hasattr(gen, '_inferred_param_types'):
                _msig_ct = gen._inferred_param_types.get(
                    f"{self_struct}_{node.name}", {}).get(pn)
            out.append(_msig_ct if _msig_ct is not None
                       else gen._param_ctype(pn, pt, node))
    return out


def _note_vararg_trailing_param_types(gen, s) -> None:
    """Called immediately after `self.func_param_types[s.name] =
    self._signature_ctypes(...)` sets a free function's CORRECT,
    fully-inferred signature — copies it into `self._vararg_
    trailing_param_types` when the packing sentinel isn't in the
    LAST position (a `(fixed, *args, trailing_kwonly=default, ...)`
    shape with no `**kwargs`). `func_param_types[name]` itself later
    gets its sentinel overwritten with the concrete signature once
    the function's forward declaration is finalized (see
    `_vararg_trailing_param_types`'s own docstring) — this side
    table is where `_lower_named_call`'s trailing-keyword-only-param
    packing fix reads from instead, so it stays correct regardless
    of how much LATER a given call site is compiled. Deliberately
    NOT computed once at registration time (a first, reverted
    attempt did that — `_param_ctype`'s own type inference for an
    unannotated param isn't fully settled that early, confirmed via
    a real repro where it wrongly produced `int64_t` for a `char *`
    message param). Piggybacking on the SAME already-correct value
    this line just computed avoids re-deriving anything."""
    if not isinstance(s, gimple_ctypes.FunctionDef) or not s.params:
        return
    if not any(pn.startswith('**') for pn, _ in s.params):
        _last_pn = s.params[-1][0]
        if not _last_pn.startswith('*'):
            _sig = gen.func_param_types.get(s.name)
            if _sig and '...' in _sig and _sig[-1] != '...':
                gen._vararg_trailing_param_types[s.name] = _sig
                try:
                    gen._vararg_trailing_param_types[gen._func_csym(s.name)] = _sig
                except Exception:
                    pass


def _fixed_param_ctypes(gen, params, node, self_struct=None) -> list:
    """C types of the parameters that precede the first *-param, for a
    function with *args. The varargs are packed into a single trailing
    MojoList* by the caller; **kwargs is not a positional parameter. Callers
    append the '...' sentinel (func_param_types) or 'MojoList *' (signatures).
    Including these fixed params is essential: e.g. __call__(self, interpreter,
    *args) must keep `interpreter`, or the forward decl and definition disagree
    on arity."""
    out = []
    for i, (pn, pt) in enumerate(params or []):
        if pn.startswith('*'):
            break
        if i == 0 and pn == 'self' and self_struct:
            out.append(f"{_as_str(self_struct)} *")  # see _signature_ctypes
        else:
            out.append(gen._param_ctype(pn, pt, node))
    return out


def _param_struct_name(gen, ptype) -> str | None:
    """If a parameter annotation names a known struct (a bare struct
    name, or a bracketed generic whose base is a registered struct,
    e.g. `ArcPointer[Self.T]` → 'ArcPointer'), return the bare struct
    name — used to recover the real semantic type of a param the ABI
    boxed to a generic scalar (`downgrade: ArcPointer[Self.T]` is
    declared `int64_t` in the C signature). Returns None for scalar
    annotations and struct names not registered in struct_field_types.

    ptype is a raw annotation (string or AST node)."""
    if ptype is None:
        return None
    if not isinstance(ptype, str):
        ptype = gimple_ctypes._walk_type_expr(ptype)
    base = ptype.split('[', 1)[0].split('.')[0].strip()
    if base in gen.struct_field_types:
        return base
    return None


def _param_ctype(gen, pname: str, ptype, node: gimple_ctypes.FunctionDef,
                 is_self: bool = False) -> str:
    """Resolve parameter C type, applying argument convention qualifiers."""
    if is_self:
        return f"{node.name} *"
    _sh = _selfhost_gen_self_param_ctype(gen, pname, ptype, node)
    if _sh is not None:
        return _sh
    # Check inferred parameter types first (for unannotated parameters).
    # `.get` into a local (typed MojoDict* via the field's declared
    # `dict[str, dict[str, str]]` shape), NOT a double `[fn][pname]`
    # subscript — the latter left the inner dict typed int64_t in the
    # self-hosted backend, so `pname in it` lowered to the `/* TODO: 'in'
    # for int64_t */` no-op and no usage-inferred type was ever found.
    ctype = None
    if ptype is None and hasattr(gen, '_inferred_param_types'):
        func_key: str
        func_key = node.name
        _ipt_fn = gen._inferred_param_types.get(func_key)
        if _ipt_fn is not None and pname in _ipt_fn:
            ctype = _ipt_fn[pname]
    if ctype is None:
        ctype = gen._resolve_type(ptype)
    # An UNANNOTATED parameter whose declared default value is a string
    # literal IS a string parameter. The default expression is type
    # evidence exactly as strong as an annotation for the omitted-
    # argument case: every call site that omits this param gets the
    # literal padded in via _default_expr_to_pair, which lowers a
    # StringLiteral default to a real ('char *', '"..."') C string —
    # previously coerced INTO the int64_t box this resolver produced,
    # so the callee then did int-arithmetic/str-from-int on a genuine
    # char* pointer (`convertdir(dir, dirprefix='', nameprefix='')` in
    # Tools/unicode/gencodec.py printing the pointer's decimal digits
    # instead of the prefix text for `dirprefix + name`). Only fires on
    # the unresolved generic int64_t box: explicit annotations, usage-
    # based inference results, and the cross-call scalar contract all
    # keep their existing precedence. param_defaults is keyed by the
    # bare declared name (the parser stores no star prefixes there),
    # matching how dup_def_signature_key looks the same table up.
    _pdflt = (getattr(node, 'param_defaults', None) or {}).get(pname.lstrip('*'))
    if (ptype is None and ctype == 'int64_t'
            and isinstance(_pdflt, StringLiteral)):
        # A `b'...'` default makes the param a `bytes` param; a plain string
        # default makes it a `str` (char *) param. bytes must NOT be
        # conflated with str — b[i] is an int, not a 1-char string.
        ctype = 'MojoBytes *' if getattr(_pdflt, 'is_bytes', False) else 'char *'
    elif (ptype is None and ctype == 'char *'
          and isinstance(_pdflt, StringLiteral) and getattr(_pdflt, 'is_bytes', False)):
        # A `b'...'` default is unambiguous `bytes` evidence and must win
        # over a weak usage-inferred `char *` — `len(b)` alone (the only
        # body signal for many bytes params) resolves to str, which would
        # then pass a real `MojoBytes *` argument into a `char *` slot and
        # `strlen()` the struct (non-deterministic length). An explicit
        # annotation still takes precedence (ptype is not None there).
        ctype = 'MojoBytes *'
    # Compile-time string types (StaticString, StringLiteral, StringRef,
    # StringSlice) are REAL strings in this codegen — a NUL-terminated
    # `char *`. The general resolver boxes them as opaque int64_t handles
    # (the libc-stub `int64_t StaticString(...)`), which breaks a param
    # used as a string: `file_name[byte=0:i]` on a `file_name: StaticString`
    # param then slices an int64_t and lowers to int64_t, and passing it to
    # a String-taking ctor is a `makes pointer from integer` error. Mirror
    # _imported_field_ctype's handling (std/pathlib/path.mojo:90).
    if ptype in ('StaticString', 'StringLiteral', 'StringRef', 'StringSlice'):
        ctype = 'char *'
    if ctype == 'void':
        # _mojo_type('None') correctly maps NoneType -> void for RETURN
        # types, but a named PARAMETER can never be typed void in a
        # multi-argument C signature (only the sole, unnamed `(void)` no-
        # args marker is legal) — e.g. Bool.__init__(out self, value:
        # None). Box it the same generic way every other
        # no-runtime-representation type already is throughout this file.
        ctype = 'int64_t'
    conv  = (getattr(node, 'param_convs', {}) or {}).get(pname)
    if conv in ('read', 'ref') and gimple_ctypes.TypeLattice.is_pointer(ctype):
        # Immutable borrow of a pointer arg → const T *
        # Only add const if not already present
        if not ctype.startswith('const '):
            ctype = 'const ' + ctype
    # Span/StringSlice's `mut` comptime Bool bracket-parameter is erased by
    # _mojo_type/_resolve_type down to the fat-pointer `Span *` above, with
    # no record of what it was bound to — but the literal is still visible
    # in the raw annotation text here (e.g. "StringSlice[mut=True,...]").
    # Recorded so _lower_MemberExpr can answer `b.mut` instead of emitting
    # an invalid field access on the erased struct.
    if isinstance(ptype, str):
        m = gimple_ctypes.re.search(r'\b(?:Span|StringSlice)\[.*\bmut\s*=\s*(True|False)\b', ptype)
        if m:
            gen._span_mut_params[pname] = (m.group(1) == 'True')
    return ctype

def overload_suffix_for(c_param_types) -> str:
    """A short stable suffix from a function's C parameter-type list. Shared by
    the codegen and reflect (reflect.func_overload_suffix) so both agree.

    Uses zlib.crc32 (available in the self-hosted runtime as mojo_zlib_crc32,
    already used by `_exc_type_id`), NOT hashlib.md5 — the compiled compiler
    has no md5, so `md5(...).hexdigest()` was stubbed to 0 and EVERY function
    mangled to the same `_0` suffix (`fib_0`, `add_0`) once mojoc ran its own
    codegen. The 6 hex digits are built with `chr()` (a per-digit 1-char
    string) rather than indexing a hex-alphabet string — compiled char*
    subscription yields the byte's integer value, not a 1-char string."""
    if not c_param_types or any('...' in p for p in c_param_types):
        return ''
    # Hand-rolled polynomial hash over the joined string's bytes — same
    # `while i < n` + `if isinstance(c, str): c = ord(c)` shape as
    # `_struct_type_id`. Neither hashlib.md5 NOR zlib.crc32 is available in
    # the self-hosted runtime (both stub to 0), so the previous md5 form
    # mangled every function to the same `_0` suffix once mojoc ran its
    # own codegen. 6 hex digits emitted via `chr()` (compiled char*
    # subscription yields the byte value, not a 1-char string, so a
    # hex-alphabet index would not work).
    _s = ','.join(c_param_types)
    _h = 0
    _i = 0
    _sn = len(_s)
    while _i < _sn:
        _c = _s[_i]
        if isinstance(_c, str):
            _c = ord(_c)
        _h = (_h * 31 + _c) & 0x7FFFFFFF
        _i = _i + 1
    _h = _h & 0xFFFFFF
    _out = ''
    _k = 0
    while _k < 6:
        _d = _h % 16
        _h = _h // 16
        if _d < 10:
            _out = chr(48 + _d) + _out
        else:
            _out = chr(87 + _d) + _out
        _k = _k + 1
    return '_' + _out


def dup_def_signature_key(fn) -> tuple:
    """Signature-identity key for deciding whether two same-named top-level
    FunctionDefs are genuine OVERLOADS of each other or a REDEFINITION
    (BUG-2026-021). Shared by gen_module's duplicate-def pre-pass and
    reflect.collect_exports_src so both sides classify a duplicated name
    identically — codegen decides which single definition survives, and the
    reflection table must advertise exactly that survivor, never zero entries
    (which stranded the entry point behind an empty `_gimple_main`) and never
    two competing ones.

    Key = per-parameter (star-prefix, annotation text, has-default) plus the
    comptime bracket-param list. Deliberately EXCLUDED, matching
    myinterpreter.py's last-def-wins binding semantics: the parameter NAME
    (a rename doesn't change the interpreter's binding, and call sites never
    saw two live choices), the return type (Mojo overloads can't be selected
    by return type alone, so differing returns still mean "same call shape,
    last def wins"), decorators, and body."""
    key = []
    for pname, ptype in (getattr(fn, 'params', None) or []):
        star = '**' if pname.startswith('**') else ('*' if pname.startswith('*') else '')
        has_dflt = bool((getattr(fn, 'param_has_default', None) or {}).get(pname.lstrip('*')))
        key.append((star, ptype, has_dflt))
    return (tuple(key), tuple(getattr(fn, 'comptime_params', None) or ()))


def _local_def_pts(gen, bare_name: str):
    """BUG-2026-019 helper: THIS compile unit's own ctypes for `bare_name`,
    resolved lazily from the module's own FunctionDef node (see gen_module's
    seeding comment for why lazily — struct-typed params need the struct
    registration passes to have run first). Memoized in
    `_local_def_param_types`; None when this unit doesn't define the name or
    its signature can't be resolved.

    Every successful resolution here is ALSO the DEFINITION-side truth for
    this (home module, name) pair — the same resolution gen_func uses for
    the emitted definition's own mangled symbol — so it is recorded into
    the WHOLE-PROGRAM-SHARED `_home_def_param_types` store. Importers'
    `_imported_def_pts` consults that store FIRST: an importer's own eager
    `_signature_ctypes` snapshot of the callee can legitimately disagree
    with the definer's (each gen's `_inferred_param_types` is per-instance,
    so call-site literal evidence an importer sees — e.g. every _global.py
    call passing a string literal as log_match's `group` — is invisible to
    the definer, which has no call sites of its own and freezes int64_t).
    Without this store the two halves of one mangled free-function symbol
    hashed different suffixes (`__common_log_match_c52cbf` call sites vs
    the `..._7a6366` definition — "implicit declaration of function" at
    g++). Only the defining unit ever writes here (only it has the node),
    and a miss falls through to the prior tiers unchanged."""
    m = getattr(gen, '_local_def_param_types', None)
    if m is None:
        return None
    if bare_name in m:
        return m[bare_name]
    node = getattr(gen, '_local_def_nodes', {}).get(bare_name)
    if node is None:
        return None
    try:
        pts = gen._signature_ctypes(node.params, node)
    except Exception:
        return None
    if not pts:
        return None
    m[bare_name] = pts
    # Record the DEFINITION-side truth for this (home, name) pair into the
    # whole-program-shared store so every importer's `_imported_def_pts`
    # hashes the SAME suffix the emitted definition uses (see this
    # function's docstring for the log_match failure this closes).
    _home_store = getattr(gen, '_home_def_param_types', None)
    if _home_store is not None:
        _q = getattr(gen, 'module_name', None) or ''
        _home_store[(_q.replace('.', '_').replace('-', '_'), bare_name)] = list(pts)
    return pts


def _imported_def_pts(gen, bare_name: str):
    """BUG-2026-024 helper: the parameter ctypes recorded for `bare_name` by
    its HOME module at FromImportStmt registration time
    (_imported_home_param_types, keyed (sanitized_home_qualifier, name)),
    or None when nothing was recorded.

    This is the suffix-half twin of _func_qualifier: that function decides
    WHICH module's `bare_name` a reference means (walking the same tiers in
    the same order — lexical scope stack innermost-first, then this unit's
    own flat import registrations, then the shared first-claim fallback);
    THIS function then supplies THAT module's signature for the mangled
    symbol's overload hash. Reading the shared func_param_types[bare] slot
    instead is exactly what drifted: sibling modules' inline compiles keep
    re-registering their own same-named defs into that one bare-name key,
    so an importer whose two homonyms come from different modules hashed
    whichever module compiled last (mod.computer.computer_case.get_energy
    vs mod.computer.network.get_energy -> call sites emitted
    computer_case_get_energy_77b31a against definition ..._0ed997).

    Never raises: an _AMBIGUOUS_FUNC_HOME entry resolves to None here so
    the caller falls through to the shared-slot tier; the authoritative
    refusal for genuinely ambiguous references stays in _func_qualifier,
    which every _func_csym call runs anyway.

    Tier 0, ahead of this instance's own eager snapshot: the SHARED
    `_home_def_param_types` store the DEFINING unit populated when its own
    `_local_def_pts` resolved (only a unit that actually defines the name
    can write there). The definer's committed signature is authoritative —
    exactly one definition symbol gets emitted — while an importer's own
    `_signature_ctypes` snapshot of the same FunctionDef can legitimately
    disagree: each gen's `_inferred_param_types` is per-instance, so an
    importer's call-site literal evidence (`log_match('literal', ...)`
    freezing `group` to char * in _global.py) is invisible to the definer,
    which has no call sites and freezes int64_t. Preferring the definer's
    truth keeps both halves of one mangled symbol on one suffix regardless
    of which module's inference saw what."""
    _def_store = getattr(gen, '_home_def_param_types', None)
    store = getattr(gen, '_imported_home_param_types', None)
    if not store and not _def_store:
        return None

    def _sanitize(q):
        return q.replace('.', '_').replace('-', '_') if q else q

    # Tier order deliberately mirrors _func_qualifier (scope stack, then
    # _own_imported_func_home, then shared _imported_func_home) so both
    # halves of one mangled symbol resolve the same binding.
    candidate_quals = []
    scopes = getattr(gen, '_import_scope_stack', None)
    if scopes:
        # reverse-index walk (innermost scope wins), NOT `reversed(scopes)`
        # — no self-hosted `reversed(<list>)` lowering (mojo_unsupported_iter,
        # zero iterations).
        for _si in range(len(scopes) - 1, -1, -1):
            frame = scopes[_si]
            if bare_name in frame:
                candidate_quals.append(frame[bare_name])
                break
    if not candidate_quals:
        own_home = getattr(gen, '_own_imported_func_home', None)
        if own_home and bare_name in own_home:
            q = own_home[bare_name]
            if q != gimple_codegen._AMBIGUOUS_FUNC_HOME:
                candidate_quals.append(q)
    if not candidate_quals:
        shared_home = getattr(gen, '_imported_func_home', None)
        if shared_home and bare_name in shared_home:
            candidate_quals.append(shared_home[bare_name])
    for q in candidate_quals:
        _sq = _sanitize(q)
        if _def_store:
            pts = _def_store.get((_sq, bare_name))
            if pts is not None:
                return pts
        if store:
            pts = store.get((_sq, bare_name))
            if pts is not None:
                return pts
    return None


def _effective_param_types(gen, bare_name: str):
    """The parameter ctypes a reference to `bare_name` in THIS compile unit
    must honor — the single source of truth for BOTH halves of a mangled
    free-function symbol: `_overload_suffix` hashes this list, and
    _func_csym's mangled-key mirror feeds it to _emit_call's argument
    coercion. Tier order:
    1. _local_def_pts — this unit defines the name (BUG-2026-019).
    2. _imported_def_pts — an imported name's home-module signature,
       recorded at FromImportStmt registration (BUG-2026-024).
    3. shared func_param_types[bare] — legacy fallback; permanently
       oscillates when same-named siblings exist, so tiers 1/2 exist."""
    pts = _local_def_pts(gen, bare_name)
    if pts is None:
        pts = _imported_def_pts(gen, bare_name)
    if pts is None:
        pts = gen.func_param_types.get(bare_name)
    return pts


def _overload_suffix(gen, bare_name: str) -> str:
    # BUG-2026-019 (box.3d/game mod families): prefer THIS compile unit's own
    # definition of `bare_name` over the shared whole-program registry. In a
    # flattened do_imports/link-fallback compile every nested module's
    # registration passes re-write the SHARED bare-name slot
    # (func_param_types['can_craft']) once per sibling that defines a
    # same-named function — tuff.mojo's `can_craft(t: Tuff)` and
    # tuff_bricks.mojo's `can_craft(t: TuffBricks)` fight over one key, so
    # whichever wrote last/first at any given moment decided BOTH modules'
    # overload suffixes. That mismatched tuff_bricks's own definition/call
    # symbols against its correctly-typed forward decl and dylib-reflection
    # extern ("expected 'TuffBricks *' but argument is of type 'Tuff *'").
    # The qualifier tier already disambiguates the NAME; this gives the
    # SUFFIX the same per-module truth.
    return gen.overload_suffix_for(_effective_param_types(gen, bare_name))


def _note_own_func_home(gen, bare_name: str, module_name: str,
                        record_scope: bool = True) -> None:
    """Register bare_name's home module into THIS instance's own
    _own_imported_func_home (see its own comment) — or, if bare_name is
    already registered to a DIFFERENT module within this SAME compile
    unit, mark it _AMBIGUOUS_FUNC_HOME instead of silently keeping
    whichever module happened to be processed first.

    When record_scope is True (default), ALSO bind bare_name in the
    CURRENT lexical scope of _import_scope_stack (a later same-name
    import in the same scope shadows the earlier one, Python/Mojo
    semantics) — the per-lexical-scope half of the fix that lets
    _func_qualifier resolve an _AMBIGUOUS_FUNC_HOME entry by which
    `from X import bare_name` statement lexically encloses the reference.
    Callers that register names which are NOT this module's own lexical
    imports (gen_module's do_imports/`_register_link_imports` transitive
    fallback registrations, whose function-body scopes are properly
    populated by _gen_stmt_FromImportStmt when the body is generated)
    pass record_scope=False so they never pollute a module scope they
    don't lexically belong to.

    This genuine same-instance conflict is narrower than it looks: it
    can only fire when ONE gen_module call's own transitive import
    discovery (find_imports) pulls in two DIFFERENT sibling modules that
    both define a function with the SAME bare name — e.g. one file with
    two different nested scopes each locally importing a same-named
    function from two different sibling modules (do_imports=True; a
    real repro found via `mojo.py build`, not build_stdlib_dylib.py's
    per-module-standalone-compile path, which never shares/nests
    GimpleGen instances this way). It does NOT fire across DIFFERENT
    compile instances (e.g. two sibling WRAPPER modules each importing
    their own same-named dependency) — those each get their OWN private
    _own_imported_func_home dict, so there's nothing to conflict with;
    that shape is the one this whole tier exists to get right, and is
    covered by test_sb1_wrapper_modules_distinct_symbols.

    _func_qualifier only raises for _AMBIGUOUS_FUNC_HOME if the
    ambiguous name is actually looked up — an unrelated, coincidentally
    same-named private helper in two sibling modules that this compile
    unit never actually CALLS by that bare name never triggers an
    error, only a genuinely ambiguous reference does (never silently
    miscompile, but also never spuriously refuse an innocuous
    same-named-but-unused coincidence).

    `module_name` is normalized by stripping LEADING dots before storage/
    comparison: two call sites can legitimately register the SAME
    relative import under different spellings — `_register_link_imports`'
    link-mode fallback (and `_compile_imported_module`'s temp_gen
    `module_name=` param) pass `stmt.module` through completely raw
    (`.base`, dots preserved), while `_emit_stdlib_import_externs`
    resolves the identical statement via `_resolve_relative` first
    (`base`, dots already stripped). Comparing the raw strings marked
    every such import falsely `_AMBIGUOUS_FUNC_HOME` even though both
    sides name the exact same module — see `_func_qualifier`'s
    `_sanitize_qualifier` (which now strips the same leading dots for
    the same reason) and bugs/CODEGEN_link_mode_from_submodule_import_
    symbol_value_call_segfault.md."""
    if module_name:
        module_name = module_name.lstrip('.')
    scopes = gen._import_scope_stack
    if record_scope and scopes:
        # Per-lexical-scope: within the CURRENT scope, a later import of
        # the same bare name shadows the earlier one (myinterpreter.py's
        # Scope.define does exactly this), so overwrite, don't mark
        # ambiguous — two top-level `from X import alloc` /
        # `from Y import alloc` in std/memory/__init__.mojo bind `alloc`
        # to the SECOND module for every reference after it.
        scopes[-1][bare_name] = module_name
    home = gen._own_imported_func_home
    cur = home.get(bare_name)
    if cur is None:
        home[bare_name] = module_name
    elif cur != gimple_codegen._AMBIGUOUS_FUNC_HOME and cur != module_name:
        home[bare_name] = gimple_codegen._AMBIGUOUS_FUNC_HOME


def _push_import_scope(gen) -> dict:
    """Push a fresh lexical-scope import-binding map onto
    _import_scope_stack (see its docstring) and return it — used at the
    start of every function/method body compile. Popped (not strictly
    required on the exception path: a raise abandons the whole
    gen_module call and its GimpleGen instance) when the body is done."""
    frame: dict = {}
    gen._import_scope_stack.append(frame)
    return frame


def _pop_import_scope(gen) -> None:
    if gen._import_scope_stack:
        gen._import_scope_stack.pop()


def _resolve_import_module_qualifier(gen, mod: str) -> str:
    """Canonical module qualifier for a `from <mod> import ...` statement
    — the string _func_qualifier must use for a name that statement binds,
    so a call site and the defining module's own compile derive the
    identical qualified C symbol. Mirrors _emit_stdlib_import_externs:
    resolve a relative module ref against this file's own package, then
    module_loader.resolve_module_path + module_name_for_path. Returns ''
    when the module can't be resolved (callers then skip scope tracking
    for that import, falling back to the flat dict / existing tiers)."""
    import module_loader as _mlmod
    path = None
    if mod.startswith('.'):
        fn = getattr(gen, '_current_filename', '') or ''
        if not fn:
            return ''
        d = gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(fn))
        dots = len(mod) - len(mod.lstrip('.'))
        rest = mod.lstrip('.')
        for _ in range(dots - 1):
            p = gimple_ctypes.os.path.dirname(d)
            if p == d:
                break
            d = p
        if rest:
            cand = gimple_ctypes.os.path.join(d, *rest.split('.'), '__init__.mojo')
            if not gimple_ctypes.os.path.exists(cand):
                cand = gimple_ctypes.os.path.join(d, *rest.split('.')) + '.mojo'
        else:
            cand = gimple_ctypes.os.path.join(d, '__init__.mojo')
        if gimple_ctypes.os.path.exists(cand):
            path = cand
        if path is None:
            return ''
    else:
        # Guard first (compiled try/except is not reliable — see
        # ModuleLoader.can_resolve_module_path's docstring).
        path = None
        if _mlmod.can_resolve_module_path(mod):
            try:
                path = _mlmod._module_loader.resolve_module_path(mod)
            except Exception:
                path = None
        if not path or not gimple_ctypes.os.path.exists(path):
            # Not a stdlib/test module (e.g. a sibling project module,
            # `alpha_module` in a mojo.py build test dir) — fall back to
            # the module string itself, matching the do_imports
            # inline-compile loop, which keys its registrations by the
            # module string.
            return mod
    try:
        q = _mlmod.module_name_for_path(path)
    except Exception:
        return mod
    return q or mod


def _collect_body_import_bindings(gen, node_list: list, scope: dict) -> None:
    """Record every `from X import ...` in a function body into `scope`
    (the lexical scope of that body), so a bare-name reference anywhere in
    the body resolves to the module its lexically-closest import statement
    bound it to. Descends into compound-statement bodies (Python/Mojo have
    no block scoping) but does NOT cross FunctionDef/LambdaExpr boundaries
    — a nested def's imports belong to that nested def's OWN scope, which
    is compiled by its own gen entry point (_gen_lifted_closure /
    _gen_struct_method) and populated by its own call to this method."""
    for stmt in node_list:
        if isinstance(stmt, gimple_ctypes.FromImportStmt) and not getattr(stmt, 'wildcard', False):
            q = gen._resolve_import_module_qualifier(stmt.module)
            if not q:
                continue
            for _fip3 in gimple_ctypes._fromimport_names(stmt):
                nm = _as_str(_fip3[0])
                alias = _as_str(_fip3[1])
                scope[alias if alias else nm] = q
        elif isinstance(stmt, gimple_ctypes.IfStmt):
            gen._collect_body_import_bindings(stmt.then_body, scope)
            for _, eb in stmt.elifs:
                gen._collect_body_import_bindings(eb, scope)
            if stmt.else_body:
                gen._collect_body_import_bindings(stmt.else_body, scope)
        elif isinstance(stmt, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt, gimple_ctypes.WithStmt)):
            gen._collect_body_import_bindings(stmt.body, scope)
            if getattr(stmt, 'else_body', None):
                gen._collect_body_import_bindings(stmt.else_body, scope)
        elif isinstance(stmt, gimple_ctypes.TryStmt):
            gen._collect_body_import_bindings(stmt.body, scope)
            for h in stmt.handlers:
                gen._collect_body_import_bindings(
                    getattr(h, 'body', None) or [], scope)
            if getattr(stmt, 'else_body', None):
                gen._collect_body_import_bindings(stmt.else_body, scope)
            if getattr(stmt, 'finally_body', None):
                gen._collect_body_import_bindings(stmt.finally_body, scope)


def _func_qualifier(gen, bare_name: str) -> str:
    """Module-qualifier prefix for a free function's mangled C symbol — the
    free-function analog of _struct_method_qualifier (same exemptions,
    same "only when this compile genuinely knows a home module" rule),
    added to fix SB-1 (doc/STDLIB-BUGS.md): two modules' same-named free
    function overloads that box down to the same C parameter shape (e.g.
    math.abs(SIMD) vs complex.abs(Complex), both boxing to a lone
    int64_t) hash to the identical overload_suffix_for(...) suffix and
    collide at link, since the C types have already collapsed by the
    time that hash runs — no amount of re-hashing the SAME collapsed
    input fixes it. Prefixing the symbol with the function's owning
    module's name distinguishes them without touching the hash at all.

    Three-tier priority, most-specific first — this ordering is
    load-bearing, not cosmetic, and was tightened twice after two
    DIFFERENT real miscompiles surfaced via `mojo.py build`'s actual
    multi-file driver path (do_imports=True inline compilation), neither
    of which build_stdlib_dylib.py's per-module-standalone-compile tests
    could ever exercise (its GimpleGen instances are never shared or
    nested the way do_imports=True's are):

    1. _local_top_level_func_names (THIS exact gen_module call's own
       top-level FunctionDefs) — a bare_name declared directly in the
       module THIS instance is compiling is always authoritative for
       itself, full stop. Needed because _imported_func_home (tier 3) is
       a single dict SHARED (by object identity,
       _compile_imported_module's `temp_gen._imported_func_home = self.
       _imported_func_home`) across every nested temp_gen a
       do_imports=True build spins up, keyed by bare function NAME
       ALONE via setdefault — so when two sibling modules being inlined
       together each define a same-named function, whichever is
       processed first "claims" that bare name, and the second module's
       OWN nested temp_gen would otherwise silently inherit the FIRST
       module's qualifier for its OWN local definition (repro: beta_
       module's own `sb1_probe_x` got emitted under
       `alpha_module_sb1_probe_x_...`, colliding with alpha_module's own
       definition at link).
    2. _own_imported_func_home (THIS exact gen_module call's own
       FromImportStmt scan — _emit_stdlib_import_externs /
       _register_link_imports, operating only on `stmts`, never shared
       across temp_gens) — for a bare_name NOT locally defined here but
       imported here. Needed because tier 3 alone is insufficient even
       for a name that ISN'T a collision at its own definition site: two
       sibling WRAPPER modules (e.g. alpha_wrapper.mojo doing `from
       alpha_module import f`, beta_wrapper.mojo doing `from beta_module
       import f`, both transitively pulled into one program) each
       correctly compute their own `f`'s true home via their own
       FromImportStmt — but if that result were written into the SAME
       shared dict tier-3 uses, beta_wrapper's correct `f -> beta_module`
       registration would be a setdefault no-op (alpha_module's do_imports
       Phase-0 registration already claimed the bare key `f` first), so
       beta_wrapper's call site would silently CALL alpha_module's `f`
       instead of beta_module's — a real, silent, wrong-result
       miscompile with no build error at all, not just a naming
       collision. Every module that references an imported name
       necessarily has that name's own FromImportStmt in ITS OWN
       top-level stmts (Mojo/Python scoping requires it), so this
       per-instance (never shared) dict is always authoritative for any
       name referenced while compiling THIS module's own body.
    3. _imported_func_home (see its own comment — populated only by
       gen_module's do_imports inline-compile loop, shared across nested
       temp_gens) — the last-resort fallback, kept for whatever a
       bare_name that is neither locally defined nor locally imported in
       THIS exact compile still needs it for (its own known limitation:
       first-registered-module-wins on a same-bare-name collision — the
       same class of accepted, documented limitation
       _imported_struct_home already has for structs, see
       test_module_cache.py's test_module_qualified_struct_symbols
       "aliasing an imported struct" comment).
    """
    # Every tier below can hand back a raw module_name — which, for a
    # DOTTED package import (`import pkg.helper as m`, module_name ==
    # "pkg.helper"), contains '.' characters that are not valid in a C
    # identifier. Every OTHER qualifier-prefix computation in this file
    # sanitizes the same way (`self.module_name.replace('.', '_')
    # .replace('-', '_')` — see the several `_mod_id = ...` sites), so
    # do the same here before returning: previously this tier-1 return
    # handed back "pkg.helper" verbatim, producing an invalid C
    # identifier like `pkg.helper_helper_add_...` for the imported
    # module's OWN definition (BUG-2026-049 — caught once
    # _compile_imported_module was fixed to actually find and inline a
    # dotted submodule's file at all; before that fix this tier was
    # never reached for a dotted import in the first place).
    def _sanitize_qualifier(q):
        # Strip LEADING dots before the '.'->'_' substitution: a raw
        # relative-import spelling (`.base`, from `_link_inline_modules`'
        # link-mode fallback — see `_compile_imported_module`'s temp_gen
        # `module_name=module_name`, which passes `stmt.module` through
        # completely unresolved) would otherwise sanitize to `_base`
        # (leading underscore) here, while `_emit_stdlib_import_externs`'
        # OWN relative-import resolution (`_resolve_relative`, run
        # against the SAME statement) already strips the dots before
        # this function ever sees the name and produces plain `base` —
        # two internally-consistent but MUTUALLY DISAGREEING spellings
        # of the identical module for the identical bare name. A call
        # site resolving one way and the definition resolving the other
        # way emits a reference to an undeclared identifier that (being
        # a bare, non-function name in a `(void *)` cast) silently
        # compiles to a null pointer instead of erroring — see
        # bugs/CODEGEN_link_mode_from_submodule_import_symbol_value_
        # call_segfault.md. Stripping leading dots here makes every
        # qualifier path converge on the same plain-name spelling
        # regardless of which one happened to run first.
        return q.lstrip('.').replace('.', '_').replace('-', '_') if q else q
    _cur_file = getattr(gen, '_current_filename', None)
    _cur_abs = gimple_ctypes.os.path.abspath(_cur_file) if _cur_file else ''
    if (_cur_file and _cur_file.endswith('.py')
            and (_cur_abs == gimple_codegen._SELFHOST_DIR or _cur_abs.startswith(gimple_codegen._SELFHOST_DIR + '/'))):
        return ''
    if bare_name in getattr(gen, '_local_top_level_func_names', ()):
        return _sanitize_qualifier(gen.module_name) or ''
    # Per-lexical-scope import tracking: a bare-name reference is bound by
    # whichever `from X import bare_name` statement lexically encloses it
    # — the innermost enclosing scope that binds the name decides which
    # module's function the reference means (a function-body import
    # shadows a module-level one; a later same-scope import shadows an
    # earlier one). The scope stack is populated only from this module's
    # OWN lexical imports (_emit_stdlib_import_externs /
    # _gen_stmt_FromImportStmt / per-function body pre-scans), so it is
    # always authoritative for a name referenced while compiling THIS
    # instance's own body — consulted here ahead of the flat
    # _own_imported_func_home so a name whose flat entry is
    # _AMBIGUOUS_FUNC_HOME (two same-bare-name imports from different
    # sibling modules — std/memory/__init__.mojo's two `alloc` imports,
    # or the SB-1 nested-scope residual in doc/STDLIB-BUGS.md) still
    # resolves correctly instead of refusing.
    scopes = getattr(gen, '_import_scope_stack', None)
    if scopes:
        # reverse-index walk (innermost scope wins), NOT `reversed(scopes)`
        # — no self-hosted `reversed(<list>)` lowering.
        for _si in range(len(scopes) - 1, -1, -1):
            frame = scopes[_si]
            if bare_name in frame:
                return _sanitize_qualifier(frame[bare_name])
    own_home = getattr(gen, '_own_imported_func_home', None)
    if own_home and bare_name in own_home:
        qualifier = own_home[bare_name]
        if qualifier == gimple_codegen._AMBIGUOUS_FUNC_HOME:
            # Never silently miscompile (doc/STDLIB-BUGS.md SB-1's
            # per-scope-import residual): this compile unit transitively
            # imports TWO different sibling modules that both define a
            # function named `bare_name`, each from a different lexical
            # scope, and no enclosing lexical scope binds the name for
            # THIS particular reference (the scope-chain walk above found
            # nothing). Picking either one silently would risk calling
            # the wrong module's implementation with no error at all.
            # Honest refusal instead (see _note_own_func_home's docstring
            # for the exact repro shape and why this can't be resolved by
            # the module-qualifier mechanism alone).
            raise RuntimeError(
                f"cannot compile module: {bare_name!r} is ambiguous — this "
                "program transitively imports two different sibling "
                "modules that both define a free function named "
                f"{bare_name!r}, each from a different lexical scope "
                "(e.g. two different nested `from X import ...` "
                "statements), and no enclosing `from X import ...` "
                "statement in the current lexical scope binds the name "
                "for this specific reference. Rename one of the two "
                "functions, or import qualified (`import X` + "
                "`X.func(...)`), to work around this.")
        return _sanitize_qualifier(qualifier)
    home = getattr(gen, '_imported_func_home', None)
    if home and bare_name in home:
        return _sanitize_qualifier(home[bare_name])
    return ''


def _locally_binds_name(gen, bare_name: str) -> bool:
    """Whether the module CURRENTLY being compiled itself defines or
    imports a free function named `bare_name` — i.e. tiers 1/2 of
    `_func_qualifier`'s three-tier lookup (this exact gen_module call's
    own top-level defs, its own lexical import-scope stack, and its own
    FromImportStmt scan), deliberately EXCLUDING tier 3
    (`_imported_func_home`, populated by scanning every sibling module
    in the whole-program transitive closure and shared by object
    identity across nested temp_gens).

    Needed for builtins whose bare name collides with an unrelated
    stdlib module's own same-named free function elsewhere in the
    transitive closure (e.g. `tokenize.py`'s own `def open(filename):`,
    `wave.py`'s `def open(f, mode=None):`) — a global `bare_name in
    self.func_return_types` check (populated by scanning ALL modules,
    not just this one) can't distinguish "some OTHER module defines
    this name" from "THIS module shadows the builtin", so a bare
    `open(path, mode)` call in a module that never touches `tokenize`
    at all was routed through the wrong arm (BUILTIN_VALUE_MAP's
    1-argument `mojo_open_file`, not `_lower_builtin_open`'s real
    2-argument handling) purely because some unrelated module
    elsewhere in the same whole-program build happens to define a
    function with the same bare name. See
    bugs/CODEGEN_generator_function_Lib_symtable.md's `with open(path,
    'rb') as f:` repro (symtable.py imports tokenize transitively but
    never binds its `open`)."""
    if bare_name in getattr(gen, '_local_top_level_func_names', ()):
        return True
    scopes = getattr(gen, '_import_scope_stack', None)
    if scopes:
        # forward iteration (not `reversed(scopes)` — the self-hosted
        # backend has no `reversed(<list>)` lowering, emitting
        # mojo_unsupported_iter so the loop ran zero times): this is a
        # pure "is `bare_name` in ANY frame" membership test, order-
        # independent.
        for frame in scopes:
            if bare_name in frame:
                return True
    own_home = getattr(gen, '_own_imported_func_home', None)
    if own_home and bare_name in own_home:
        return True
    return False


def _func_mangleable(gen, name: str) -> bool:
    """Whether a free function's C symbol is overload-mangled. True for a local
    user def (in _mangled_funcs) or an imported Mojo function (a concrete
    function export with a signature). False for entry points, struct types,
    and C stdlib symbols, whose names are fixed."""
    if (name in gen._NO_OVERLOAD_MANGLE
            or name in gen._extra_no_mangle
            or name in gen.struct_field_types):
        return False
    # A local user def is authoritative — mangle it even if it shares a name
    # with a libc symbol (e.g. `abs` overloaded in math vs complex: both rename
    # to mojo_abs and would otherwise collide at link).
    if name in gen._mangled_funcs:
        return True
    if name in gen._LIBC_DECLARED:
        return False
    info = gen.imported_symbols.get(name)
    return bool(info and 'signature' in info and info.get('kind') != 3)


def _func_csym(gen, bare_name: str) -> str:
    """The C symbol for a free function: _safe_name + overload suffix when the
    function is a user/imported Mojo function eligible for mangling. Used at the
    definition, every forward declaration, and every call site so they agree."""
    # `from X import real_name as bare_name`: the DEFINING module compiled
    # `real_name` under ITS OWN bare (unaliased) name — an alias is purely a
    # local binding in the IMPORTING module, so this call site's mangled
    # symbol must be built from `real_name`, not the local alias, or it
    # disagrees with what the defining module's own compile actually
    # exports (e.g. `from b import add as plus` mangling to `b_plus_<hash>`
    # here while b.mojo's own standalone compile emits `b_add_<hash>` —
    # "implicit declaration"/undefined-symbol, not just a naming quirk).
    _imp_info = gen.imported_symbols.get(bare_name)
    # `_as_str`: a dict VALUE slot erases to int64_t on the self-hosted
    # path, so `_safe_name(_orig)` stringified the boxed pointer as a
    # decimal — the source of the non-deterministic
    # `extern int64_t <ptr> (...); /* from ... */` externs.
    _orig = _as_str(_imp_info.get('original_name')) if _imp_info else None
    base = gimple_ctypes._safe_name(_orig) if (_orig and _orig != bare_name) else gimple_ctypes._safe_name(bare_name)
    if not gen._func_mangleable(bare_name):
        return base
    qualifier = gen._func_qualifier(bare_name)
    qualified_base = f"{qualifier}_{base}" if qualifier else base
    mangled = qualified_base + gen._overload_suffix(bare_name)
    # Mirror the param/return types under the mangled key so _emit_call's
    # argument coercion and return typing (keyed by the emitted name) still
    # work — func_param_types/func_return_types are keyed by the bare name.
    # Plain assignment, NOT setdefault: `_func_csym` is called repeatedly
    # for the same function throughout compilation (every call site's
    # symbol resolution, every forward declaration), and the bare-name
    # entry it mirrors from is deliberately CORRECTED in place over time
    # by later passes (e.g. Pass 1.3e's "refresh return types now that
    # param inference is final", which re-infers an unannotated
    # function's return type once its real parameter shape is known and
    # overwrites func_return_types[bare_name] with the corrected value).
    # `setdefault` here meant whichever call happened to run FIRST froze
    # the mangled key at whatever the bare-name value was AT THAT MOMENT
    # — if that first call landed before Pass 1.3e's correction (e.g.
    # from a same-module caller compiled earlier in source order, which
    # resolves its own call site's symbol via this same method before
    # the callee itself has been fully return-type-inferred), the
    # mangled key stayed wrong FOREVER even after the bare key was
    # later fixed, since nothing ever re-mirrored it. `_emit_call`
    # looks up func_return_types BY THE MANGLED KEY (see its "Also
    # check func_return_types" mismatch-correction block) — a stale
    # mangled entry there overrides an otherwise-correct `ret_type`
    # with the wrong one, then emits the call's result straight into a
    # temp declared with that wrong type, with NO cast (an invalid,
    # uncaught type mismatch, since the whole point of that block is to
    # apply a cast when the two types differ — but it never even
    # considers that ITS OWN "authoritative" value might itself be
    # stale). Real: glob.py's `_join` (return type correctly inferred
    # 'char *' via Pass 1.3e) called from `_glob0` (compiled earlier in
    # source order) — `_func_csym('_join')` ran during `_glob0`'s OWN
    # compile before Pass 1.3e had corrected the bare key, freezing
    # `func_return_types['_join_abb124'] = 'int64_t'` permanently;
    # `_t8 = _join_abb124(_t5, _t7);` (a real char*-returning call
    # assigned into an int64_t temp with no cast) then failed
    # -Wint-conversion. Always re-mirroring the CURRENT bare-name value
    # is strictly more correct than freezing at first use — the whole
    # reason `func_return_types`/`func_param_types` get corrected after
    # the fact is that later passes have STRICTLY MORE information than
    # earlier ones, never less.
    if mangled != base:
        # Mirror from the SAME effective param types _overload_suffix just
        # used (this unit's own definition when it has one, the home
        # module's registration-time signature for an imported name —
        # BUG-2026-024 — shared registry otherwise — BUG-2026-019). All
        # three tiers MUST match _overload_suffix's exactly: this mirror is
        # what _emit_call keys its argument coercion by, so any disagreement
        # between the two halves emits call symbols whose suffix says one
        # module while the casts say another (the `(ComputerNetwork *)c`
        # argument at test_computer_mod.mojo's get_energy(c) call sites).
        _eff_pts = _effective_param_types(gen, bare_name)
        if _eff_pts is not None:
            gen.func_param_types[mangled] = _eff_pts
        if bare_name in gen.func_return_types:
            gen.func_return_types[mangled] = gen.func_return_types[bare_name]
    return mangled


def gen_func(gen, node: gimple_ctypes.FunctionDef) -> str:
    gen._reset_func(node.body, node.params)
    # BUG-2026-016's allow-list: locals whose DECLARATION carries an
    # explicit NUMERIC/boolean annotation (`hin_id: UInt64 = 0`). Such a
    # variable can never legitimately hold a pointer, so when one is
    # passed to a pointer-to-scalar parameter it must mean out-param
    # aliasing -- take its address. The complement is exactly why this
    # allow-list exists: UNANNOTATED locals initialized from
    # pointer-returning calls (`var ptr = data.unsafe_ptr()`,
    # std/hashlib/_ahash.mojo; `var mbar = stack_allocation[...]`,
    # gpu/elementwise.mojo) routinely hold REAL addresses in int64_t
    # storage, and auto-addressing those corrupts the call (confirmed:
    # both stdlib modules regressed to GCC errors without this gate).
    gen._scalar_annotated_locals = set()
    for _dn in gimple_exprtypes._walk_ast(node.body):
        if isinstance(_dn, gimple_ctypes.VarDecl) and getattr(_dn, 'type_ann', None):
            if gimple_ctypes._TYPE_MAP.get(str(_dn.type_ann).strip()) in (
                    gimple_ctypes._PTR_OUT_PARAM_SCALAR_ELEMS | {'char'}):
                gen._scalar_annotated_locals.add(_dn.name)
        elif (isinstance(_dn, gimple_ctypes.AssignStmt) and isinstance(_dn.target, gimple_ctypes.IdentExpr)
                and getattr(_dn, 'type_ann', None)):
            if gimple_ctypes._TYPE_MAP.get(str(_dn.type_ann).strip()) in (
                    gimple_ctypes._PTR_OUT_PARAM_SCALAR_ELEMS | {'char'}):
                gen._scalar_annotated_locals.add(_dn.target.name)
    # Per-lexical-scope import tracking: this function body is its own
    # scope — push a fresh frame and pre-record every `from X import ...`
    # directly in the body so a bare-name call site resolves to the module
    # its lexically-closest import bound it to, even during the pre-passes
    # below (return-type inference etc.) that run before the body's
    # statements are generated one-by-one. Popped right before the return;
    # a raise abandons the whole compile and this GimpleGen instance, so
    # there is nothing to leak on the exception path.
    _func_scope = gen._push_import_scope()
    gen._collect_body_import_bindings(node.body, _func_scope)
    # Set module context for global field access
    gen._current_module_ctx = gen.module_name if len(gen.module_name) > 0 else "root"
    gen.current_func_name = node.name

    # Seed param types into var_types BEFORE return-type inference so
    # _quick_type can resolve param names during the pre-pass. Unannotated
    # params use the inferred type (incl. cross-call scalar contract, e.g. a
    # double param), not the int64_t default, so return inference is right.
    for pname, ptype in node.params:
        bare = pname.lstrip('*')
        if pname.startswith('*'):
            ctype = 'MojoList *'
        elif ptype is None:
            ctype = (gen._inferred_param_types.get(node.name, {}).get(pname)
                     or gen._resolve_type(ptype))
        else:
            ctype = gen._resolve_type(ptype)
        gen.var_types[bare] = ctype
        # Register in _actual_types so _get_actual_type resolves the real
        # type for for-loop iterables and other dispatch paths.
        if ctype != 'int64_t':
            gen._actual_types[bare] = ctype
        # Record the semantic struct identity of a known-struct param so
        # member access can cast through the right struct pointer even
        # when the ABI boxed the param to a generic scalar (see
        # _param_struct_name / _lower_MemberExpr).
        pst = gen._param_struct_name(ptype)
        if pst:
            gen._param_struct_types[bare] = pst

    # Seed container element types straight from a param's own declared
    # annotation — the same static-truth seed struct fields already get
    # (see gimple_module_gen.py's `list[tuple[T, T]]` field block). A param
    # annotated `list[tuple[str, str]]` / `list[str]` / `dict[str, list[str]]`
    # otherwise binds its loop/unpack vars as boxed int64_t inside the body
    # even though the caller's shape is fully known here (concretely:
    # `_emit_call(arg_pairs: list[tuple[str, str]])` unpacked `(atype, aval)`
    # as int64_t, so once a callee's `func_param_types` entry became readable
    # the `ptype != atype` compare fired a bogus `(char *)` reinterpret cast).
    for pname, ptype in node.params:
        if ptype is None or pname.startswith('*') or not isinstance(ptype, str):
            continue
        bare = pname.lstrip('*')
        _pa = ptype.strip()
        _pbase = _pa.split('[', 1)[0].strip()
        if _pbase not in ('list', 'List', 'set', 'Set', 'frozenset', 'dict', 'Dict') or '[' not in _pa:
            continue
        _pin = gimple_ctypes._split_top_level_commas(
            _pa[_pa.index('[') + 1:_pa.rindex(']')].strip())
        if _pbase in ('dict', 'Dict'):
            if len(_pin) != 2:
                continue
            _vann = _pin[1].strip()
            _vc = gen._resolve_type(_vann)
            if _vc and _vc != 'int64_t':
                gen._dict_val_types.setdefault(bare, _vc)
            _vbase = _vann.split('[', 1)[0].strip()
            if _vbase in ('list', 'List', 'set', 'Set', 'frozenset') and '[' in _vann:
                _ei = gimple_ctypes._split_top_level_commas(
                    _vann[_vann.index('[') + 1:_vann.rindex(']')].strip())
                if len(_ei) == 1 and _ei[0].strip():
                    _ec = gen._resolve_type(_ei[0].strip())
                    if _ec and _ec != 'int64_t':
                        gen._dict_nested_val_types.setdefault(bare, _ec)
            continue
        if len(_pin) != 1 or not _pin[0].strip():
            continue
        _eann = _pin[0].strip()
        _ebase = _eann.split('[', 1)[0].strip()
        if _ebase in ('tuple', 'Tuple') and '[' in _eann:
            _slots = gimple_ctypes._split_top_level_commas(
                _eann[_eann.index('[') + 1:_eann.rindex(']')].strip())
            _sc = None
            _same = True
            for _sl in _slots:
                _sl = _sl.strip()
                if not _sl:
                    continue
                _t = gen._resolve_type(_sl)
                if _sc is None:
                    _sc = _t
                elif _t != _sc:
                    _same = False
                    break
            if _same and _sc and _sc != 'int64_t':
                gen._elem_types.setdefault(bare, 'MojoList *')
                gen._nested_elem_types.setdefault(bare, _sc)
        else:
            _ec = gen._resolve_type(_eann)
            if _ec and _ec != 'int64_t':
                gen._elem_types.setdefault(bare, _ec)

    # Seed the cross-call element-type contract for container params, so
    # param[i][j] reads the inner element with the right getter and return
    # inference sees the real scalar (must precede return-type inference).
    # (Iterate keys + index, not `for k, (e, ne) in .items()`: a nested tuple
    # for-target over .items() isn't lowered correctly when self-compiled.)
    _pe = getattr(gen, '_param_elem_types', {}).get(node.name, {})
    for bare in _pe:
        # `_pe[bare]` is a 2-tuple; `e, ne = _pe[bare]` boxes both slots
        # on the self-hosted path, so `_elem_types[bare]` got a garbage
        # ctype string and `_declare_var`'s `mojo_str_cat` ran `strlen()`
        # on it — a hard segfault on the single-TU `--dump myinterpreter.py`.
        _pe_v = _pe[bare]
        e = _as_str(_pe_v[0])
        ne = _as_str(_pe_v[1])
        if e:
            gen._elem_types[bare] = e
            if ne:
                gen._nested_elem_types[bare] = ne
    # Seed local container element types too, so return inference can see
    # through nested subscripts on locals (e.g. `return bodies[0][0]` where
    # bodies is a local list-of-double-lists). Lowering re-derives the same.
    _loc_elem, _loc_nested, _loc_dict_val = gen._scan_container_elems(node.body)
    for v in _loc_elem:
        gen._elem_types.setdefault(_as_str(v), _as_str(_loc_elem[v]))
    for v in _loc_nested:
        gen._nested_elem_types.setdefault(_as_str(v), _as_str(_loc_nested[v]))
    for v in _loc_dict_val:
        gen._dict_val_types.setdefault(_as_str(v), _as_str(_loc_dict_val[v]))

    # Determine return type: annotation takes priority; infer if absent.
    if node.return_type is not None:
        ret_type = gen._resolve_type(node.return_type)
    else:
        # Seed any local holding a closure VALUE (`var f = inner`) so
        # `return f` infers the closure's real MojoBoundMethod*/void*
        # shape instead of the int64_t default (which would make a
        # capturing-closure return box the env+fnptr bundle as a bare
        # scalar, corrupting the later call). Seeded temporarily: the
        # body's own VarDecl statements re-declare their locals.
        _closure_locals = gen._closure_value_locals(node.body)
        if _closure_locals:
            _saved_vt_rt = gen.var_types
            gen.var_types = dict(_saved_vt_rt)
            for _cln, _clt in _closure_locals.items():
                if _cln not in gen.var_types:
                    gen.var_types[_cln] = _clt
            ret_type = gen._infer_return_type(node.body)
            gen.var_types = _saved_vt_rt
        else:
            ret_type = gen._infer_return_type(node.body)
        # Special case: main() should return int, not void
        if node.name == 'main' and ret_type == 'void':
            ret_type = 'int64_t'

    gen.func_ret_type = ret_type
    # Sync so forward declarations (Phase 2b) match Phase 2a inference
    gen.func_return_types[node.name] = ret_type

    # Run layout solver for struct locals
    solver = gimple_solvers.LayoutSolver(gen.struct_field_types)
    gen._struct_layout = solver.solve(node.params, node.body)

    param_strs = []
    has_varargs = any(pname.startswith('*') for pname, _ in (node.params or []))
    seen_varargs = False
    for pname, ptype in node.params:
        bare = pname.lstrip('*')
        if pname.startswith('**'):
            # **kwargs: a real MojoDict* parameter (the forwarding pattern; the
            # caller passes the dict directly since the parser flattens **spreads)
            gen.var_types[bare] = 'MojoDict *'
            param_strs.append(f"MojoDict * {bare}")
            continue
        if pname.startswith('*'):
            if seen_varargs:
                continue  # only one MojoList* for all *args
            seen_varargs = True
            ctype = 'MojoList *'
        else:
            ctype = gen._param_ctype(pname, ptype, node)
        safe_bare = gen._param_safe_name(bare)
        gen.var_types[bare] = ctype
        if safe_bare != bare:
            gen.var_types[safe_bare] = ctype
            gen._c_names[bare] = safe_bare
        param_strs.append(f"{ctype} {safe_bare}")

    # A param typed `MojoGenerator *` by the cross-call generator-value
    # contract (Pass 1.3f-gen) needs its generator's base/value_ctype
    # extern "C" api recoverable inside the body (`for x in g:` /
    # `next(g)`), but `_generator_var_api` is only populated at
    # construction/assignment sites (see its docstring) and a param
    # crossing a call boundary has no entry of its own. Seed it from the
    # provenance recorded at the call site — the value flows
    # `counter(3)` → `g` (in the caller) → `consume(g)` → this param.
    # Keyed by the param's C name, which is what `_lower_IdentExpr`
    # yields as the lowered value (so `_gen_for_iter`/`next` lookups
    # find it). See bugs/CODEGEN_compiled_generator_not_first_class_
    # value.md.
    _pg_apis = gen._param_generator_api.get(node.name, {})
    for _pp, _pt in node.params:
        _pb = _pp.lstrip('*')
        if _pp.startswith('*'):
            continue
        _gf = _pg_apis.get(_pb)
        if _gf is not None and gen.var_types.get(_pb) == 'MojoGenerator *':
            _api24 = gen._generator_api.get(_gf)
            if _api24 is not None:
                gen._generator_var_api[gen._cname(_pb)] = _api24

    params_str = ', '.join(param_strs) if param_strs else 'void'
    # Record that this function takes varargs so call sites can pack args
    if has_varargs:
        gen.func_param_types[node.name] = gen._signature_ctypes(node.params, node)
        gen._note_vararg_trailing_param_types(node)
    safe = gen._func_csym(node.name)

    # For main (in main module only), call class-attr initializer first
    if node.name == 'main' and gen.emit_struct_defs:
        gen._emit('  _mojo_classattr_init ();')

    gen._seed_mut_captured_local_types(node.name)
    gen._seed_addressed_locals(node.body)
    # Allocate each heap-boxed ({mut}-captured) local's box once, here in
    # the prologue -- NOT lazily at its first-binding statement (the old
    # VarDecl-time scheme): real Python source's first binding is a plain
    # AssignStmt that never reaches _gen_stmt_VarDecl, leaving the box
    # unallocated while every access dereferenced the pointer (a
    # mid-function segfault on Tools/cases_generator/analyzer.py's
    # `nonlocal next_opcode` closure). See _emit_mut_local_box_allocs.
    gen._emit_mut_local_box_allocs()

    # Don't emit bb_2 label at function start - let statements flow directly
    gen._genexp_narrow_names = set()
    gen._genexp_list_locals = {}
    gen._seed_genexp_list_narrowing(node)
    for stmt in node.body:
        gen.gen_stmt(stmt)

    # Add implicit return 0 for main if it returns int but has no explicit return
    if node.name == 'main' and ret_type == 'int' and not gen.body_lines[-1:] == ['  return 0;']:
        # Check if last statement is a return
        if not (gen.body_lines and gen.body_lines[-1].strip().startswith('return')):
            gen._emit('  return 0;')

    # For main function in root module, rename to _gimple_main and create wrapper
    # For main function in library module, rename to _{module}_main to avoid collision
    if node.name == 'main':
        if gen.emit_entry_points:
            safe = '_gimple_main'
        else:
            # Sub-module's main: rename to avoid collision with root main()
            # Module name may contain dots (e.g. "test.builtin.foo") — replace with underscores
            _mod_id = gen.module_name.replace('.', '_').replace('-', '_') if gen.module_name else ''
            safe = f"_{_mod_id}_main" if _mod_id else '_lib_main'

    lines = [
        f"{ret_type} {safe} ({params_str})",
        "{",
        *gen.decls,
        *gen.body_lines,
        "}",
    ]

    # Generate C wrapper for main that optionally initializes Python (root module only)
    if node.name == 'main' and gen.emit_entry_points:
        lines.append("")
        lines.append(f"int main (int argc, const char **argv) {{")
        lines.append(f"  mojo_set_argv(argc, argv);")
        lines.append(f"#if USE_PYTHON")
        lines.append(f"  Py_Initialize ();")
        lines.append(f"#endif")
        # Call sub-module toplevels first, then root's own _toplevel (if present)
        for sub_fn in gen._sub_toplevels:
            lines.append(f"  {sub_fn} ();")
        # Only call root's _toplevel if root actually has top-level statements;
        # pre-scanned into _has_toplevel_code so we trim the call when empty.
        # If it does AND that top-level code itself genuinely calls
        # `main(...)` somewhere (self._toplevel_calls_main — see
        # gen_module's own docstring on this flag for the real, pre-
        # existing bug this distinction fixes), _toplevel() already runs
        # the root module's own `if __name__ == '__main__': main()` (now
        # that __name__ correctly resolves per-module — see the
        # __name__ lowering above) — calling {safe}() again here
        # unconditionally was a real double-invocation bug, previously
        # masked because that guard never used to fire correctly
        # (__name__ was hardcoded to "__main__" everywhere). But if the
        # top-level code does NOT call main() itself (e.g. it's just an
        # ordinary module docstring — ubiquitous in real Mojo source,
        # which has no __name__/__main__ convention at all: `main()` is
        # simply the direct, unconditional entry point), the compiled
        # main function must still be called directly here, exactly
        # like the "no top-level code at all" branch below — otherwise
        # it silently never runs at all.
        if getattr(gen, '_has_toplevel_code', False) and getattr(gen, '_toplevel_calls_main', False):
            lines.append(f"  _toplevel ();")
            lines.append(f"  int result = 0;")
        elif getattr(gen, '_has_toplevel_code', False):
            lines.append(f"  _toplevel ();")
            call_args = ', '.join(['0'] * len(param_strs))
            # `def main() -> None:` (real, common — e.g. Tools/build/
            # generate_sbom.py) makes `ret_type` here 'void'. `void
            # result = ...;` is invalid C ("variable or field 'result'
            # declared void") -- a void function's call has no value to
            # capture in the first place. Call it as a bare statement
            # and keep `result` as a real `int` process exit code (this
            # wrapper's own C `main()` always returns `int`, regardless
            # of what the compiled Python `main()` itself returns).
            if ret_type == 'void':
                lines.append(f"  {safe} ({call_args});")
                lines.append(f"  int result = 0;")
            else:
                lines.append(f"  {ret_type} result = {safe} ({call_args});")
        else:
            # `def main(args=None):` (a legitimate, common pattern — the
            # file's own `if __name__ == '__main__': sys.exit(main())`
            # calls it with no args, relying on the default) declares
            # {safe} with real C params (params_str, above), but this
            # process-level C `main()` always called `{safe} ()` with
            # zero arguments regardless — "too few arguments to function
            # '_gimple_main'; expected 1, have 0". Every one of main's
            # own params is necessarily defaulted for a bare `main()`
            # call to even be valid Mojo/Python, so pass each default's
            # boxed-zero equivalent (`0`/NULL for every C type this
            # compiler uses — int64_t, char*, MojoList*, ... are all
            # represented as 0) rather than omitting the argument.
            # Found via mojolib BUG-2026-032: transpiler.mojo's
            # `def main(args=None):`.
            call_args = ', '.join(['0'] * len(param_strs))
            # See the identical `ret_type == 'void'` guard above (`def
            # main() -> None:`) -- same fix, same reason.
            if ret_type == 'void':
                lines.append(f"  {safe} ({call_args});")
                lines.append(f"  int result = 0;")
            else:
                lines.append(f"  {ret_type} result = {safe} ({call_args});")
        lines.append(f"#if USE_PYTHON")
        lines.append(f"  Py_Finalize ();")
        lines.append(f"#endif")
        lines.append(f"  return result;")
        lines.append(f"}}")

    gen._pop_import_scope()
    return '\n'.join(lines)


def _gen_toplevel(gen, toplevel_stmts: list) -> str:
    """Generate _toplevel() or _{module}_toplevel() function for top-level statements."""
    gen._reset_func(toplevel_stmts)
    # Set module context for global field access
    gen._current_module_ctx = gen.module_name if len(gen.module_name) > 0 else "root"
    # Choose function name based on whether this is the root module or a library module
    if gen.emit_entry_points:
        fn_name = '_toplevel'
    else:
        fn_name = gimple_ctypes._module_toplevel_name(gen.module_name)
    gen.current_func_name = fn_name
    gen.func_ret_type = 'void'
    gen.func_return_types[fn_name] = 'void'

    # Generate code for each top-level statement
    gen._in_toplevel_gen = True
    try:
        for stmt in toplevel_stmts:
            gen.gen_stmt(stmt)
    finally:
        gen._in_toplevel_gen = False

    # Dependency-init prelude: a `mojo dylib` build compiles every
    # module SEPARATELY (see gen_module's population of
    # `_toplevel_dep_init_modules`) and links them together, each with
    # its own unprioritized `__attribute__((constructor))`. Constructor
    # firing order across translation units follows link/discovery
    # order (driver._expand_dylib_modules' BFS over `from X import`
    # statements), NOT the real import dependency graph — so a module
    # whose top-level code (or a ctor-invoked function it calls) reads
    # another module's globals has no guarantee that module's own ctor
    # has already run. Real Python/Mojo import semantics require an
    # imported module's top-level code to run before the importer's own
    # — restore that here explicitly by calling each directly-imported
    # local sibling's one-shot-guarded `<module>_init()` before this
    # module's own body executes. This composes transitively: if A
    # imports B and B imports C, A's prelude calls B_init() first,
    # whose OWN prelude (compiled the identical way) calls C_init()
    # first — so by the time A's own top-level statements run, both B
    # and C are fully initialized, regardless of ctor link order.
    # Reproduced via box.3d/game: `game_ffi.mojo`'s ctor called
    # `engine_create_world()` -> `init_default_conversions()` ->
    # `base/resource.mojo`'s `g_conversions.append(...)` while
    # `resource`'s own ctor (transitively imported via `engine_world`,
    # never directly by game_ffi) hadn't fired yet — `g_conversions`
    # was still unallocated, `mojo_list_append_int` on it segfaulted at
    # dlopen time. Only applies to standalone library-module compiles
    # (matches gen_module's own ctor/`_init()`-emission condition) —
    # a `do_imports=True` inline build has no separate per-module
    # `_init()` to call (everything is already inlined in true
    # execution order), and the root/emit_entry_points module has no
    # exported `_init()` name of its own to match against.
    _dep_init_lines = []
    if not gen.emit_entry_points and not gen.do_imports:
        for _dep_mod in gen._toplevel_dep_init_modules:
            _dep_init_fn = gimple_ctypes._module_init_name(_dep_mod)
            _dep_init_lines.append(f"extern void {_dep_init_fn} (void);")
    _dep_init_calls = [f"  {gimple_ctypes._module_init_name(_dep_mod)} ();"
                        for _dep_mod in gen._toplevel_dep_init_modules] \
        if (not gen.emit_entry_points and not gen.do_imports) else []

    # One-shot guard: this function may now be reached from more than one
    # caller — the executable path's own explicit call in `main()`'s
    # wrapper (unchanged, pre-existing), PLUS (library/dylib modules
    # only, see gen_module) an automatic `__attribute__((constructor))`
    # AND a publicly-exported `<module>_init()` a C host may call
    # directly (bugs/DYLIB_module_scope_never_executes.md). Whichever
    # combination of those actually fires at runtime, module-scope code
    # must run exactly once — the guard lives HERE, inside the single
    # underlying function every caller funnels through, rather than in
    # each caller, so it can't be bypassed by adding a new call site.
    # Plain C (this function is never `__GIMPLE`-tagged — see gen_module's
    # identically-shaped `main()` wrapper, which already freely uses
    # `if`/function calls/etc.), so a local `static` flag is safe here.
    lines = [
        *_dep_init_lines,
        f"void {fn_name} (void)",
        "{",
        *gen.decls,
        "  static int _ran = 0;",
        "  if (_ran) return;",
        "  _ran = 1;",
        *_dep_init_calls,
        *gen.body_lines,
        "}",
    ]

    return '\n'.join(lines)


def _imported_field_ctype(gen, type_ann: str) -> str:
    """Resolve an imported struct field's type to C. Compile-time string types
    are char* here (they back string fields like emission_kind) even though the
    general resolver keeps them as opaque int64_t handles elsewhere."""
    if type_ann in ('StaticString', 'StringLiteral', 'StringSlice', 'StringRef', 'String'):
        return 'char *'
    return gen._resolve_type(type_ann) if type_ann else 'int64_t'


def _materialize_imported_struct(gen, module: str, nm: str, local: str) -> bool:
    """Register `nm` (a struct defined directly in `module`'s real source,
    looked up via the real parser through `_find_imported_struct`) into
    this file's own `struct_field_types`/typedef bookkeeping under the
    local name `local`, exactly as if it were a struct this file defines
    itself: real field layout (`_imported_field_ctype`, the same
    resolver used for every other imported-struct field), a queued
    typedef (`_imported_typedef_structs`, emitted into THIS file's own
    translation unit — see gen_module's "Struct typedefs" section,
    which walks stmts + _imported_typedef_structs uniformly), and its
    home module (`_imported_struct_home`, for correct call-site/extern
    symbol qualification). Returns True iff `nm` is a genuine struct in
    `module`'s own source and registration succeeded (already-registered
    counts as success); False means `nm` isn't a struct there (caller
    keeps its own generic/opaque fallback — an honest "can't help" case,
    not a guess).

    Shared by two call sites that both need "give the CALLER real,
    parser-verified field-layout knowledge of a cross-module struct"
    rather than the opaque-int64_t-handle fallback: (1)
    _register_imported_structs below, for a struct named directly in a
    `from B import S` and actually constructed/field-accessed/method-
    called in this file; (2) _resolve_sibling_param_ctype, for a struct
    that only appears as a PARAMETER TYPE of some other imported
    function `f` (e.g. `from base.chest import chest_total_count` where
    chest_total_count's own signature takes a `Chest`, but this file
    never imports `Chest` itself) — see
    bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md's "struct-
    typed function parameter" gap and
    bugs/hard/... crash-repro writeup for why a bare int64_t placeholder
    there is unsafe (a caller-side `S()`/field-write on that placeholder
    corrupts memory) and why symbol-hash-only patching without this real
    materialization was reverted."""
    if local in gen.struct_field_types:
        return True  # already registered (this call, or a prior one)
    if local in getattr(gen, '_imported_generic_structs', ()):
        return False  # generic imported struct: out of scope here
    if any(w in nm for w in gen._IMPORTED_STRUCT_SKIP_BASENAMES):
        return False
    sdef = gen._find_imported_struct(module, nm)
    if sdef is None:
        # Not defined directly in `module` itself -- chase `module`'s own
        # import statements transitively for the struct's REAL defining
        # module (BUG-2026-014/015: an importing module's reference to a
        # struct routinely crosses TWO hops -- `game_ffi.mojo` imports
        # `engine_view_slot` from `engine_world.mojo`, whose return type
        # `ItemSlot` is defined in `base/items.mojo` -- and every step
        # scoped to the immediate module gave up to the opaque int64_t
        # default, leaving caller-side field access on the dynamic
        # `_mojo_dispatch_getattr` path -> AttributeError/segfault).
        # Rebind `module` so EVERY downstream consumer below -- the
        # per-field ctype resolution (whose bare-name recursion passes
        # `module` on), the comptime-constant lookups against the home
        # module's AST, the List[X]/[X; N] element-struct transitive
        # pass, and the `_imported_struct_home` symbol qualification --
        # resolves against the struct's true home by construction.
        _home = gen._find_struct_home_module(module, nm)
        if _home is None or _home == module:
            return False
        sdef = gen._find_imported_struct(_home, nm)
        if sdef is None:
            return False
        module = _home
    # `_imported_generic_structs` (checked above) is only reliable once
    # `_register_imported_generic_structs` has actually run — which
    # happens AFTER `_register_imported_structs` in gen_module's own
    # pass ordering, so it's empty on this call the first time a generic
    # struct (e.g. std/collections/interval.mojo's `struct Interval[T:
    # IntervalElement]`) reaches here. Don't rely on ordering: check the
    # struct's OWN home-module source text directly for the same
    # `struct Name[...]` shape `_find_generic_source` looks for. A
    # generic struct's un-elaborated field/method types reference its
    # own type parameters abstractly (e.g. `other: Self` resolving
    # differently per instantiation) — registering the raw template as
    # if it were a concrete struct produced a real regression
    # (confirmed: test/collections/test_interval.mojo's `Interval.union`
    # method extern ended up with a mismatched `int64_t` parameter type
    # against the call site's real `Interval *` argument — "makes
    # integer from pointer without a cast"). Elaboration/monomorphization
    # of generics is a separate, already-existing mechanism
    # (Elaborator.elaborate_generic_struct) this narrow, non-generic-only
    # materialization deliberately doesn't attempt to replace.
    _imp_path0, _imp_src0, _imp_mod0 = gen._parsed_import(module)
    if _imp_src0 and gimple_ctypes.re.search(rf'\bstruct\s+{gimple_ctypes.re.escape(nm)}\s*\[', _imp_src0):
        return False
    # Fixed-size-array fields (`var x: [ElemType; N]`, BUG-2026-008's own
    # shape) need the SAME "ElemCtype[N]" marker string the own-module
    # struct-field-registration path produces (see gen_module's
    # `_FIXED_ARRAY_ANN_RE.match` handling below) — `_imported_field_ctype`
    # (-> `_resolve_type`) has no idea about this annotation shape and
    # falls back to a bare scalar (`int64_t`), which the typedef-emission
    # pass's "don't overwrite an already-registered field" guard then
    # locks in permanently, silently downgrading the field from a real
    # embedded struct array to an opaque int64_t (BUG-2026-010,
    # box.3d/game: `World.blocks: [Block; MAX_BLOCKS]` imported only via
    # `g_world = engine_create_world()`, never a direct `World(...)`
    # construction — see _register_imported_structs' own companion fix
    # for how `World` gets materialized in the first place). Resolved
    # against the STRUCT'S OWN home module's constants (`_imp_mod0`,
    # already parsed above), matching `_module_const_int`'s normal
    # same-module `comptime` scoping.
    fields = {}
    # Register the (still-empty) fields dict under `local` BEFORE
    # resolving any field's own ctype below, and mutate this same dict
    # object in place as fields are resolved (instead of building a
    # temporary dict and assigning it to struct_field_types only at the
    # end, as this function used to). This is what makes the recursive
    # bare-struct-field materialization a few lines down cycle-safe: two
    # structs whose fields reference each other (`struct A: b: B` /
    # `struct B: a: A`), or a struct referencing itself indirectly,
    # terminate because the SECOND recursive call's own
    # "if local in self.struct_field_types: return True" guard at the
    # top of this function now fires immediately (finding this same,
    # still-filling-in dict already present) instead of recursing
    # forever — `_resolve_type`'s callers only need the KEY's presence
    # to emit a pointer type (`f"{ann} *"`), not a fully-populated dict,
    # so an in-progress registration is already good enough for them.
    gen.struct_field_types[local] = fields
    for f in sdef.fields:
        if not isinstance(f, gimple_ctypes.VarDecl):
            continue
        _fann = f.type_ann.strip() if isinstance(f.type_ann, str) else ''
        _farr_m = gimple_ctypes._FIXED_ARRAY_ANN_RE.match(_fann) if _fann else None
        if _farr_m:
            _felem_nm, _fsize_txt = _farr_m.group(1), _farr_m.group(2)
            _fn_size = (int(_fsize_txt) if _fsize_txt.isdigit()
                        else gen._module_const_int(_fsize_txt, _imp_mod0 or [], None))
            if _fn_size is not None and _fn_size > 0:
                # Materialize the element struct FIRST (if it's one) so
                # struct_field_types already has it by the time this
                # marker is read back — mirrors the transitive-
                # materialization pass below, but must also run here
                # since this dict is consulted directly by callers that
                # never reach that loop (e.g. the array-index element
                # ctype lookup at typedef-emission time).
                if (_felem_nm not in gen._IMPORTED_STRUCT_SKIP_BASENAMES
                        and gen._materialize_imported_struct(module, _felem_nm, _felem_nm)):
                    _felem_ct = _felem_nm
                else:
                    _felem_ct = gimple_ctypes._mojo_type(_felem_nm)
                fields[f.name] = f"{_felem_ct}[{_fn_size}]"
                gen._array_field_sizes.setdefault(local, {})[f.name] = (_felem_ct, _fn_size)
                continue
        # A field whose annotation is a BARE capitalized name (no `[`,
        # no leading `*`, e.g. `inner: Inner` — as opposed to the
        # List[X]/[X; N] shapes already handled above/below) that names
        # a real struct defined in the SAME home `module` needs that
        # struct materialized too, BEFORE resolving this field's own
        # ctype — otherwise `_imported_field_ctype`
        # (-> `_resolve_type`) finds it absent from struct_field_types
        # and silently falls back to the generic `int64_t` default
        # (root cause of the cross-module nested-struct-field crash:
        # `Outer.inner: Inner` got typed `int64_t` in an IMPORTING
        # module whenever nothing else had separately materialized
        # `Inner` first, producing a DIFFERENT C layout for `Outer`
        # than the struct's own DEFINING module compiles — any code
        # that then did `.inner.val` fell through to the fully-dynamic
        # `_mojo_dispatch_getattr` runtime path on what it treated as
        # an opaque pointer, i.e. a real `AttributeError`/segfault, not
        # just a missed optimization). Mirrors the List[X]/[X; N]
        # transitive-materialization pass below, but must ALSO run
        # here (not only there) because THIS field's own ctype string
        # — resolved right below via `_imported_field_ctype` — is what
        # actually goes into `fields[f.name]`; running the equivalent
        # logic only in the later pass would be too late to affect it.
        if (_fann and _fann[0].isupper() and '[' not in _fann
                and '.' not in _fann and _fann not in gen.struct_field_types
                and _fann not in gen._IMPORTED_STRUCT_SKIP_BASENAMES
                and gimple_ctypes._TYPE_MAP.get(_fann) is None):
            gen._materialize_imported_struct(module, _fann, _fann)
        fields[f.name] = gen._imported_field_ctype(f.type_ann)
    # Carry the struct's real methods along so the signature-registration
    # pass (all_structs_for_methods) resolves their return/param C types
    # and mangled names exactly as it would for an in-file struct (see
    # _register_imported_structs' original, longer comment on this same
    # pattern for the full rationale) — smoke-test the overload-id
    # computation first, falling back to a typedef-only (methods=[])
    # registration if it raises, rather than risk a broken signature.
    _methods_for_reg: list = []
    try:
        gen._struct_method_overload_ids(sdef)
        _methods_for_reg = sdef.methods
    except Exception as e:
        gimple_ctypes._debug_note(f'cannot resolve method signatures for imported struct {nm}', e)
    # `fields` was already registered under `local` (same dict object,
    # mutated in place as each field was resolved above) before this
    # function started resolving individual field ctypes, specifically
    # so bare-struct-typed-field recursion could see itself mid-
    # registration and terminate cycles — see the comment at this
    # function's `fields = {}` site. Left assigned again here is
    # redundant (same object, same key) but documents that `fields` is
    # now considered complete.
    gen.struct_field_types[local] = fields
    gen._imported_struct_names.add(local)
    _imp_path, _imp_src, _imp_mod = gen._parsed_import(module)
    if _imp_path:
        import module_loader as _mlmod
        gen._imported_struct_home[local] = _mlmod.module_name_for_path(_imp_path)
    # Transitively materialize element structs of TWO field shapes whose
    # element type is itself a struct defined in the SAME home `module`:
    #   (1) `List[X]` (e.g. `World.blocks: List[Block]`,
    #   (2) fixed-size-array `[X; N]` (e.g. `World.blocks: [Block; MAX_BLOCKS]`,
    #       the BUG-2026-008 shape — see _FIXED_ARRAY_ANN_RE), both defined
    #       in engine_world.mojo).
    # `_imported_field_ctype`/`_resolve_type` erase `List[Block]` down to
    # the generic `MojoList *` (the runtime has no per-instantiation
    # list type), which loses the element type — without this, a caller
    # in a DIFFERENT module that only imports `World` (not `Block`
    # itself, since it never names `Block` directly — it only reaches
    # it transitively through `World.blocks`) has no registered
    # `struct_field_types['Block']` and no `_field_elem_types['World']
    # ['blocks']`, so `w.blocks[i].block_type` can't be resolved to a
    # direct `->block_type` C field access and falls back to the
    # runtime's fully-dynamic `_mojo_dispatch_getattr` (which returns 0 /
    # raises `AttributeError: block_type` for a struct that isn't
    # reflect-registered on this path) instead of a real, correct read.
    # Reproduced via box.3d/game's DYLIB_dlopen_extern_fn_attributeerror.md
    # (dlopen of a dylib whose module-scope var, in a DIFFERENT module
    # from World/Block's own definitions, reads `g_world.blocks[hash].
    # block_type`). Scoped to same-module element structs only (the
    # common real-world shape); an element struct defined in yet another,
    # third module would need the field's own annotation to carry that
    # module's name, which the plain `List[Block]`/`[Block; N]` spelling
    # doesn't.
    #
    # This transitive pass MUST run — and any recursive
    # `_imported_typedef_structs` append it triggers for the ELEMENT
    # struct MUST land — before `local`'s (the CONTAINING struct's) own
    # typedef is appended below. A fixed-size-array field embeds its
    # element type BY VALUE (`Block blocks[4096];`, not a pointer), so
    # the generated C typedef for World needs Block's typedef already
    # emitted earlier in the file — same-module compiles get this for
    # free from source declaration order (Block is textually declared
    # before World), but the cross-module materialization path has no
    # such natural order and must construct it explicitly here.
    for f in sdef.fields:
        if not isinstance(f, gimple_ctypes.VarDecl) or not isinstance(f.type_ann, str):
            continue
        _ann = f.type_ann.strip()
        _elem_name = None
        _is_list_field = _ann.startswith('List[') and _ann.endswith(']')
        if _is_list_field:
            _elem_name = _ann[len('List['):-1].strip()
        else:
            _arr_m = gimple_ctypes._FIXED_ARRAY_ANN_RE.match(_ann)
            if _arr_m:
                _elem_name = _arr_m.group(1).strip()
        if not _elem_name or not _elem_name[0].isupper():
            continue
        if _elem_name in gen._IMPORTED_STRUCT_SKIP_BASENAMES:
            continue
        if gen._materialize_imported_struct(module, _elem_name, _elem_name):
            if _is_list_field:
                gen._field_elem_types.setdefault(local, {})[f.name] = f"{_elem_name} *"
            # Fixed-size-array fields need no _field_elem_types entry: the
            # element type is embedded by value and picked up directly
            # from struct_field_types at typedef-emission time (gen_module's
            # `_elem_ct = _elem_nm if _elem_nm in self.struct_field_types
            # else _mojo_type(_elem_nm)`) — which now finds Block there
            # because of the ordering guarantee above.
    # Scalar/container element types for imported-struct LIST fields
    # (`variables: List[String]`, `variable_values: List[Int]` — box.3d/
    # game's ComputerCase). The transitive pass above only covers
    # UPPERCASE struct-element lists; a scalar-element list's importer-
    # side _field_elem_types entry was never seeded at all (the nested
    # temp_gen that compiled the defining module seeded ITS OWN instance
    # via gen_module's StructDef pass, but this map is per-instance and
    # not shared), so an importer read like `c.variables[i]` fell back to
    # int64_t and returned raw boxed handles instead of strings.
    # Annotation-derived static truth — mirrors the seeding just added to
    # gen_module's local StructDef pass (see its BUG-2026-023 comment).
    for f in sdef.fields:
        if not isinstance(f, gimple_ctypes.VarDecl) or not isinstance(f.type_ann, str):
            continue
        if fields.get(f.name) != 'MojoList *':
            continue
        _ann2 = f.type_ann.strip()
        if not (_ann2.startswith('List[') and _ann2.endswith(']')):
            continue
        _inner2 = gimple_ctypes._split_top_level_commas(
            _ann2[len('List['):-1].strip())
        if not _inner2:
            continue
        try:
            _et2 = gen._resolve_type(_inner2[0].strip())
        except Exception:
            _et2 = None
        if _et2 and _et2 != 'int64_t':
            gen._field_elem_types.setdefault(local, {})[f.name] = _et2
    gen._imported_typedef_structs.append(
        gimple_ctypes.StructDef(name=local, fields=sdef.fields, methods=_methods_for_reg))
    return True


def _resolve_sibling_param_ctype(gen, module: str, raw_ptype) -> str | None:
    """For a sibling-imported FUNCTION's parameter whose raw Mojo type
    annotation (from module_loader's text scan, still the original Mojo
    source spelling — e.g. "Chest", not yet C-typed) names a struct
    defined directly in that function's own home `module`, materialize
    it (via _materialize_imported_struct, same field-layout resolution
    as any other imported struct) and return its real C pointer type
    (`"Chest *"`) for the caller to splice into that parameter's C
    signature text. Returns None — the honest "not a struct I can give
    you real layout for" case — for scalars, collection/pointer-like
    types (Dict/List/UnsafePointer/…), and any name that genuinely isn't
    a struct in `module`'s own source (a real external/unmodeled type,
    or a struct defined somewhere OTHER than the function's own home
    module — out of scope for this narrow, function-parameter-only
    resolution; such cases keep today's honest link-failure behavior
    rather than a guess)."""
    if not isinstance(raw_ptype, str):
        return None
    base = raw_ptype.split('[', 1)[0].split('.')[0].strip()
    if not base or not base[0].isupper():
        return None  # Mojo/Python convention: only structs are capitalized
    if base in gen._IMPORTED_STRUCT_SKIP_BASENAMES:
        return None
    if base in gen.struct_field_types:
        return f"{base} *"
    if gimple_ctypes._TYPE_MAP.get(base) is not None:
        return None  # a real scalar/builtin Mojo type, not a struct
    if gen._materialize_imported_struct(module, base, base):
        return f"{base} *"
    return None


def _register_imported_structs(gen, stmts) -> None:
    """dylib mode: register a concrete imported struct's field layout + queue
    its typedef, for a struct used as a parameter type whose field is
    actually accessed here (so e.g. `info: CompiledFunctionInfo` +
    `info.emission_kind` works), OR a struct actually CONSTRUCTED locally
    (`s := S(...)` / `s = S(...)`) — the latter needs real field layout
    just as much as a param-typed field access does: without it, `S()`
    collapses to an opaque `int64_t` placeholder (see
    _lower_imported_struct_ctor) and a subsequent `s.x = 1` becomes a
    dynamic `_mojo_dispatch_setattr` on that placeholder — a crash, not
    merely a missed optimization (the exact shape a reverted symbol-hash-
    only fix for a related gap was found to reintroduce; see
    bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md's "follow-on
    attempt #2" section). Tightly scoped beyond that to avoid disturbing
    the many imported structs a module merely passes through untouched."""
    if gen.do_imports or not getattr(gen, '_current_filename', None):
        return
    try:
        src = open(gen._current_filename).read()
    except Exception:
        gimple_ctypes._debug_note('cannot read source for self-assign scan', gen._current_filename)
        return
    # struct base name -> set of parameter names with that type (so the field /
    # method checks below are specific to values actually of this struct, not a
    # coincidental `.field`/`.method(` on some other object).
    params_by_struct: dict = {}

    def _base(ann):
        return ann.split('[', 1)[0].split('.')[0].strip() if isinstance(ann, str) else ''

    def _collect(fn):
        for _pn, _pt in (getattr(fn, 'params', None) or []):
            b = _base(_pt)
            if b:
                params_by_struct.setdefault(b, set()).add(
                    gimple_ctypes._strip_mojo_param_modifiers(_pn.lstrip('*')))
        # Nested `def`s (e.g. a raises-helper closure declared inside a
        # test function, typed on an imported struct) live inside the
        # enclosing statement's body/orelse/handler blocks, not at
        # top-level — walk those too (iteratively: a nested generator
        # calling itself doesn't survive self-host closure-lifting) so
        # their typed params count too.
        _worklist = [getattr(fn, 'body', None)]
        while _worklist:
            _blk = _worklist.pop()
            for _st in (_blk or []):
                if isinstance(_st, gimple_ctypes.FunctionDef):
                    _collect(_st)
                for _attr in ('body', 'orelse', 'finally_body'):
                    _sub = getattr(_st, _attr, None)
                    if isinstance(_sub, list):
                        _worklist.append(_sub)
                _handlers = getattr(_st, 'handlers', None)
                if isinstance(_handlers, list):
                    for _h in _handlers:
                        _hb = getattr(_h, 'body', None)
                        if isinstance(_hb, list):
                            _worklist.append(_hb)
    for st in stmts:
        if isinstance(st, gimple_ctypes.FunctionDef):
            _collect(st)
        elif isinstance(st, gimple_ctypes.StructDef):
            for m in st.methods:
                _collect(m)
    param_type_names = set(params_by_struct)

    # Local variable names directly assigned from a constructor call to
    # an imported struct name (`s := S(...)` / `s = S(...)`, including as
    # a VarDecl initializer), keyed by struct base name — the ASSIGNMENT
    # shape specifically, not any bare in-place use (`for x in S(...):`,
    # `f(S(...))`). A bare in-place use never gets a name to write a
    # field through, so the existing opaque-int64_t-handle convention
    # already handles it safely (confirmed: std/collections/string/
    # _utf8.mojo's UTF8Chunks is constructed inline as a for-loop
    # iterable, `for chunk in UTF8Chunks(x):`, with no assigned name —
    # registering it as a real struct anyway, tried first, broke this:
    # UTF8Chunks' own __iter__ overload signature couldn't be resolved
    # by _struct_method_overload_ids, so no extern got emitted for it,
    # regressing a previously-working dynamic dispatch call into an
    # "implicit declaration of function" compile error). An ASSIGNED
    # name, by contrast, is exactly the shape that needs real field
    # layout to be safe at all: `s := S()` with no registration lowers
    # to a bare `s = (int64_t)0` placeholder (_lower_imported_struct_ctor),
    # and a later `s.x = 1` becomes a dynamic `_mojo_dispatch_setattr`
    # call on that null placeholder — a crash, not merely imprecise
    # codegen (the exact shape a reverted symbol-hash-only fix for a
    # related gap was found to reintroduce; see
    # bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md's "follow-on
    # attempt #2"). Combined with the existing _field_accessed check
    # below (which already requires an actual `name.field` textual
    # access, not just an assignment), this only pulls in structs that
    # are BOTH constructed AND field-accessed locally — the same
    # "genuinely needs real layout" bar the parameter-typed case already
    # applies, just widened to also recognize local-variable typing, not
    # only function-parameter typing.
    # Name -> home module for every `from X import name [as alias]` in
    # this file (functions as well as structs) — used just below to
    # recognize `g_world = engine_create_world()` (BUG-2026-010,
    # box.3d/game) as needing the SAME real-struct-layout treatment as a
    # direct `g_world = World()` constructor call: the assignment target
    # gets a struct via calling an IMPORTED FUNCTION, not the struct's
    # own constructor.
    _imported_name_to_module: dict = {}
    for _ist in stmts:
        if isinstance(_ist, gimple_ctypes.FromImportStmt) and not getattr(_ist, 'wildcard', False):
            for _fip4 in gimple_ctypes._fromimport_names(_ist):
                _inm = _as_str(_fip4[0])
                _ialias = _as_str(_fip4[1])
                _imported_name_to_module.setdefault(_ialias or _inm, _ist.module)

    def _imported_func_return_struct(fname):
        """If `fname` is an imported free function whose OWN return-type
        annotation names a struct defined in that SAME home module,
        return that struct's bare name (e.g. 'World'). None otherwise.
        Scoped to same-module only — matches _materialize_imported_
        struct's existing List[X]/[X; N]-element scoping rationale: a
        function's return struct living in a THIRD module would need
        more than this narrow, function-call-site-only resolution."""
        _fmod = _imported_name_to_module.get(fname)
        if not _fmod:
            return None
        _fpath, _fsrc, _fstmts = gen._parsed_import(_fmod)
        if not _fstmts:
            return None
        for _fs in _fstmts:
            if isinstance(_fs, gimple_ctypes.FunctionDef) and _fs.name == fname and _fs.return_type:
                _rt = str(_fs.return_type).strip()
                _rbase = _rt.split('[', 1)[0].strip()
                if (_rbase and _rbase[0].isupper()
                        and _rbase not in gen._IMPORTED_STRUCT_SKIP_BASENAMES):
                    return _rbase
        return None

    _locally_constructed: dict = {}
    for _node in gimple_exprtypes._walk_ast(stmts):
        _ctor_name = None
        _target_name = None
        if isinstance(_node, gimple_ctypes.AssignStmt) and isinstance(_node.target, gimple_ctypes.IdentExpr):
            _target_name = _node.target.name
            _val = _node.value
        elif isinstance(_node, gimple_ctypes.VarDecl):
            _target_name = _node.name
            _val = _node.value
        else:
            continue
        if isinstance(_val, gimple_ctypes.CallExpr) and isinstance(_val.func, gimple_ctypes.IdentExpr):
            _ctor_name = _val.func.name
        if _ctor_name and _target_name:
            _locally_constructed.setdefault(_ctor_name, set()).add(_target_name)
            # `_ctor_name` may not be the struct's own constructor at
            # all, but an imported FUNCTION that returns one (see
            # _imported_func_return_struct above) — register the target
            # under the RETURN struct's own name too, so the lookup
            # below (keyed by the struct's name as imported) finds it.
            _ret_struct = _imported_func_return_struct(_ctor_name)
            if _ret_struct:
                _locally_constructed.setdefault(_ret_struct, set()).add(_target_name)

    for st in stmts:
        if not (isinstance(st, gimple_ctypes.FromImportStmt) and not getattr(st, 'wildcard', False)):
            continue
        for _fip5 in gimple_ctypes._fromimport_names(st):
            nm = _as_str(_fip5[0])
            alias = _as_str(_fip5[1])
            local = alias or nm
            if (nm.startswith('_') or local in gen.struct_field_types
                    or local in gen._imported_generic_structs
                    or any(w in nm for w in gen._IMPORTED_STRUCT_SKIP_BASENAMES)):
                continue
            if local not in param_type_names and nm not in _locally_constructed:
                continue
            sdef = gen._find_imported_struct(st.module, nm)
            if sdef is None:
                continue
            fields = {f.name: gen._imported_field_ctype(f.type_ann)
                      for f in sdef.fields if isinstance(f, gimple_ctypes.VarDecl)}
            pnames = set(params_by_struct.get(nm, set())) | _locally_constructed.get(nm, set())
            _field_accessed = fields and any(
                f"{pn}.{fn}" in src for pn in pnames for fn in fields)
            # A (non-trivial) method CALLED on this struct anywhere: common
            # trait/dunder methods are excluded (their names collide with
            # calls on unrelated objects, and they have generic handling
            # rather than a hard symbol).
            _uncommon = [m.name for m in sdef.methods
                         if m.name not in gimple_ctypes._COMMON_METHOD_NAMES]
            _called_uncommon = any(f".{mn}(" in src for mn in _uncommon)
            if not fields and not _called_uncommon:
                continue
            if not _field_accessed and not _called_uncommon:
                continue  # struct is merely passed through, untouched
            gen._materialize_imported_struct(st.module, nm, local)


def _find_imported_struct(gen, module: str, name: str):
    """The StructDef for `name` defined directly in `module`'s source, or None."""
    _path, _src, mod = gen._parsed_import(module)
    if mod is None:
        return None
    for s in mod:
        if isinstance(s, gimple_ctypes.StructDef) and s.name == name:
            return s
    return None


def _find_struct_home_module(gen, module: str, name: str, depth: int = 0) -> str | None:
    """The module ref whose own source DIRECTLY defines `struct {name}`,
    starting from `module` and following its `from X import ...`
    statements transitively (re-export chains -- BUG-2026-014/015,
    box.3d/game: `game_ffi.mojo` imports `engine_view_slot` from
    `engine_world`, whose return annotation names `ItemSlot`, but
    ItemSlot is DEFINED in `base.items`; every prior resolution step
    looked only in the immediate module and gave up with the opaque
    int64_t default).

    Returns a module-ref string usable with `_parsed_import`/
    `_materialize_imported_struct` (each hop's own `from X import`
    target -- relative spellings are absolutized against the importing
    module via `_abs_module`, mirroring `_find_generic_source`). None
    if no reachable module defines the struct (an honest "not found",
    never a guess). Memoized per (module, name); the memo doubles as
    the cycle guard for re-export loops."""
    if depth > 5 or not module:
        return None
    key = (module, name)
    if key in gen._struct_home_cache:
        return gen._struct_home_cache[key]
    # Mark in-progress BEFORE recursing so an import cycle terminates
    # (a re-export loop A->B->A must not recurse forever).
    gen._struct_home_cache[key] = None
    if gen._find_imported_struct(module, name) is not None:
        gen._struct_home_cache[key] = module
        return module
    _path, _src, stmts = gen._parsed_import(module)
    if not stmts:
        return None
    for st in stmts:
        if not (isinstance(st, gimple_ctypes.FromImportStmt) and not getattr(st, 'wildcard', False)):
            continue
        for _fip6 in gimple_ctypes._fromimport_names(st):
            nm = _as_str(_fip6[0])
            alias = _as_str(_fip6[1])
            if (alias or nm) != name:
                continue
            sub = gen._abs_module(st.module, module) if st.module.startswith('.') else st.module
            r = gen._find_struct_home_module(sub, name, depth + 1)
            if r:
                gen._struct_home_cache[key] = r
                return r
    return None


def _resolve_test_relative_module(gen, module: str) -> str | None:
    """Fallback for local test-only packages (e.g. `test_utils`) that
    `imports.py`'s resolver can't find: it only searches MOJO_PATH/
    PYTHONPATH/the stdlib root, none of which include a plain `test/`
    subtree, so a bare `test_utils` (living at `test/test_utils/`,
    imported test-relatively by sibling files like
    `test/memory/test_span.mojo`) is unresolvable there at any level —
    not a re-export-chain issue, the module itself has no path. Walk
    upward from the currently-compiled file's directory (bounded to
    avoid escaping the stdlib checkout) looking for `<dir>/<module path>/
    __init__.mojo` or `<dir>/<module path>.mojo`. `module` may itself be
    dotted (e.g. `test_utils.types`, produced when following a re-export
    chain via _find_generic_source — not just the bare top-level name)."""
    if not gen._current_filename:
        return None
    rel_parts = module.split('.')
    d = gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(gen._current_filename))
    for _ in range(6):
        cand_pkg = gimple_ctypes.os.path.join(d, *rel_parts, '__init__.mojo')
        if gimple_ctypes.os.path.isfile(cand_pkg):
            return cand_pkg
        cand_mod = gimple_ctypes.os.path.join(d, *rel_parts[:-1], rel_parts[-1] + '.mojo')
        if gimple_ctypes.os.path.isfile(cand_mod):
            return cand_mod
        parent = gimple_ctypes.os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _parsed_import(gen, module: str):
    """(path, source_text, stmts) for an imported module, parsed once and
    cached. (None, '', None) on failure."""
    cache = gen._imported_src_cache
    if module not in cache:
        try:
            import imports as _imp
            path = _imp.resolve_source(module) or gen._resolve_test_relative_module(module)
            # A LEADING-DOT relative ref (`from .base import triple`) can
            # never be resolved by either helper above: `imports.py`'s
            # resolver only understands MOJO_PATH-relative dotted names
            # (`_find`'s `name.replace('.', os.sep)` turns a leading dot
            # into a leading path separator, which `os.path.join` then
            # treats as absolute and silently DISCARDS the search
            # directory it was joined onto — `os.path.join('/foo',
            # '/base.mojo') == '/base.mojo'`), and
            # `_resolve_test_relative_module` only tries the `.mojo`
            # extension and mis-splits a leading dot into an empty path
            # component. Both gaps are real but harmless everywhere else
            # `_parsed_import` is called from (struct/generic lookups
            # degrade to "not found" the same as any other unresolvable
            # module) — the one place they turned into a genuine crash is
            # `_register_link_imports` (link mode's `mojo build`): failing
            # to resolve `.base` meant `triple` never got registered at
            # all, `f = triple` fell through to the generic "undeclared
            # identifier" placeholder (a literal `0`), and calling through
            # that placeholder (`f(14)`) called a NULL function pointer —
            # `Segmentation fault: 11` (see bugs/CODEGEN_link_mode_from_
            # submodule_import_symbol_value_call_segfault.md). Reuse
            # `_module_candidate_paths`, the do_imports=True inline path's
            # OWN relative-import resolver (anchors at the IMPORTING
            # file's directory, handles the dot-count-as-level Python
            # semantics, and tries `.py` before `.mojo`) — it was already
            # correct, just never wired into this cache-filling helper.
            # Gated to `module.startswith('.')` (a genuine relative ref)
            # ONLY — widening this fallback to every otherwise-
            # unresolvable ABSOLUTE bare name too (the first attempt at
            # this fix did) regressed `make check-selfhost`:
            # `_module_candidate_paths`' broad search (CWD, ancestor
            # dirs, this repo's own script_dir) can spuriously MATCH an
            # unrelated same-named file for a bare name that was always
            # intentionally left unresolved (a real external/unmodeled
            # package), changing struct/generic type-resolution behavior
            # across the whole self-hosted build in ways this fix has
            # nothing to do with.
            if not path and module.startswith('.'):
                for _cand in gen._module_candidate_paths(module):
                    if gimple_ctypes.os.path.exists(_cand):
                        path = _cand
                        break
            src = open(path).read() if path else ''
            cache[module] = (path, src,
                             ast_rewriter.rewrite(Parser(py_tokenize(src)).parse_module()) if src else None)
        except Exception:
            gimple_ctypes._debug_note('cannot resolve/parse module', module)
            cache[module] = (None, '', None)
    return cache[module]


def _local_sibling_module_exports(gen, module: str):
    """(exports_dict, qualifier) for a `from module import ...` that
    module_loader.load_module() can't resolve because it isn't a
    tracked stdlib/test module — i.e. a LOCAL project sibling file (see
    bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md, box.3d/game
    repo). (None, None) when `module` genuinely can't be found anywhere
    (a real external/unmodeled package, or a bare relative import), in
    which case the caller falls back to the existing weak-stub/
    unresolved-alias behavior.

    `mojo dylib` (driver.compile_dylib -> build_stdlib_dylib.build)
    compiles each module SEPARATELY — one private GimpleGen instance per
    file, do_imports=False, link_imports=False — so neither
    _register_link_imports (link_imports-only) nor the do_imports
    inline-compile loop's _imported_func_home bookkeeping ever runs for
    this shape; the only registration pass that always runs
    (_emit_stdlib_import_externs, and this gen_module's own "Process
    imports" loop) previously just gave up on any non-stdlib module
    name, degrading a same-dylib sibling to the SAME "genuinely
    external, unmodeled package" weak-stub path real third-party C
    packages use — even though the real definition compiles into the
    very same output dylib (driver._expand_dylib_modules already walks
    the same sibling-import closure to include it). The call sites just
    never learned the sibling's module qualifier, so they emitted an
    UNQUALIFIED call that bound to the weak stub instead of the real
    module-qualified symbol sitting right there in the dylib.

    Resolves via `_parsed_import` — the SAME sibling-resolution
    machinery (imports.resolve_source, falling back to
    _resolve_test_relative_module's walk-up-from-this-file directory
    search) `_find_imported_struct`/`_find_generic_source` already use
    for cross-module struct/generic lookups — then extracts real
    fn/def signatures via module_loader.load_module_from_path (the same
    text-scan logic load_module() itself uses for stdlib/test modules,
    just entry-pointed by file path instead of by stdlib-relative
    module name, since resolve_module_path is deliberately restricted
    to STDLIB_PATH/TEST_PATH and cannot see a project's own local
    files)."""
    path, _src, _stmts = gen._parsed_import(module)
    if not path:
        return None, None
    import module_loader as _mlmod
    exports = _mlmod.load_module_from_path(path)
    qualifier = _mlmod.module_name_for_path(path)
    return exports, (qualifier or None)

def _abs_module(ref: str, base: str) -> str:
    """Resolve a possibly-relative import ref against the base package:
    `.os` from `std.os` -> `std.os.os`; `..fstat` from `std.os.path` ->
    `std.os.fstat`. Absolute refs unchanged."""
    if not ref.startswith('.'):
        return ref
    dots = len(ref) - len(ref.lstrip('.'))
    leaf = ref[dots:]
    parts = base.split('.')
    keep = parts[:len(parts) - (dots - 1)] if dots > 1 else parts
    return '.'.join(keep + ([leaf] if leaf else []))


def _find_generic_source(gen, module: str, name: str, kind: str = 'fn', depth: int = 0):
    """Source path of the module that DEFINES generic `name` (a free
    function when kind='fn', a struct when kind='struct'), reachable from
    `module` by following `from X import (...)` re-export hops (e.g.
    std.os re-exports listdir from .os = os.mojo). None if not generic."""
    # String key, NOT a `(module, name, kind)` tuple — a tuple set-key is
    # coerced to a boxed int64_t on the self-hosted path so `key in
    # visited` never hits, forcing a full re-scan on every repeat call.
    key = module + '\x1f' + name + '\x1f' + kind
    if key in gen._find_generic_visited:
        return None
    gen._find_generic_visited.add(key)
    if depth > 3 or not module:
        return None
    path, src, mod = gen._parsed_import(module)
    if not src:
        return None
    head = r'\bstruct\s+' if kind == 'struct' else r'\b(?:fn|def)\s+'
    if gimple_ctypes.re.search(head + rf'{gimple_ctypes.re.escape(name)}\s*\[', src):
        return path
    nm = gimple_ctypes.re.escape(name)
    # Flat [mod0, names0, mod1, names1, ...] scan instead of two
    # `re.finditer(...)` loops with `mm.group(1)/.group(2)` — the
    # self-hosted backend has no lowering for `re.finditer` (emits
    # `mojo_unsupported_iter`, loop body runs zero times) nor for
    # `.group(n)` with an argument, so on the compiled path re-export
    # hop resolution here was silently dead.
    _fi = _scan_from_imports_flat(src)
    _j = 0
    while _j < len(_fi):
        _fmod = _fi[_j]
        _fnames = _fi[_j + 1]
        _j += 2
        if gimple_ctypes.re.search(rf'(?:^|[\s,(]){nm}(?:[\s,)]|$)', _fnames):
            r = gen._find_generic_source(gen._abs_module(_fmod, module), name, kind, depth + 1)
            if r:
                return r
    return None


def _scan_from_imports_flat(src: str) -> list:
    """Every `from X import ...` in `src` as a flat list
    [mod0, names0, mod1, names1, ...] — a flat list (not a list of
    2-tuples, not a tuple return) so the self-hosted backend can iterate
    it by index without boxing. A parenthesised, multi-line import list
    (`from X import (\n a,\n b,\n)`) is joined into one names string."""
    out: list = []
    lines = src.split('\n')
    _i = 0
    _n = len(lines)
    while _i < _n:
        _ln = lines[_i].strip()
        _i += 1
        if not _ln.startswith('from '):
            continue
        _rest = _ln[5:]
        _p = _rest.find(' import')
        if _p < 0:
            continue
        _mod = _rest[:_p].strip()
        _names = _rest[_p + 7:].lstrip()
        if _names.startswith('('):
            _names = _names[1:]
            while (')' not in _names) and (_i < _n):
                _names = _names + ' ' + lines[_i].strip()
                _i += 1
            _cut = _names.find(')')
            if _cut >= 0:
                _names = _names[:_cut]
        out.append(_mod)
        out.append(_names)
    return out


def _register_imported_generics(gen, stmts) -> None:
    """dylib mode: register `from M import gen` where gen is a generic free
    function (following re-export chains) so its call sites elaborate a
    concrete CAS-cached instantiation."""
    if gen.do_imports:
        return
    for st in stmts:
        if not (isinstance(st, gimple_ctypes.FromImportStmt) and not getattr(st, 'wildcard', False)):
            continue
        for _fip7 in gimple_ctypes._fromimport_names(st):
            nm = _as_str(_fip7[0])
            alias = _as_str(_fip7[1])
            local = alias or nm
            if (local in gen._imported_generics or local in gen.struct_field_types
                    or nm != local):   # aliased: elaborator looks up the source name
                continue
            src = gen._find_generic_source(st.module, nm)
            if src:
                gen._imported_generics.setdefault(local, src)
    for name, module in gen._PRELUDE_GENERICS.items():
        if name in gen._imported_generics or name in gen.struct_field_types:
            continue
        src = gen._find_generic_source(module, name)
        if src:
            gen._imported_generics.setdefault(name, src)


def _register_imported_generic_structs(gen, stmts) -> None:
    """Register `from M import GenericStruct` (following re-export chains,
    same as _register_imported_generics does for free functions) so both
    `Struct[Args](...)` constructor call sites and a nested generic-struct
    TYPE ARGUMENT to another generic (_elaborate_generic_call's use of
    _ensure_generic_struct, e.g. `alloc[MoveOnly[Int]]`) can resolve it.

    `MoveOnly` (test_utils.types) is only re-exported through
    `test_utils/__init__.mojo`, and `test_utils` itself isn't resolvable
    via imports.py's MOJO_PATH-based search at all (it's a local
    test-only package, sibling to the test files that import it, not on
    any search path) — _find_generic_source's _parsed_import call falls
    back to _resolve_test_relative_module for that case."""
    if gen.do_imports:
        return
    for st in stmts:
        if not (isinstance(st, gimple_ctypes.FromImportStmt) and not getattr(st, 'wildcard', False)):
            continue
        for _fip8 in gimple_ctypes._fromimport_names(st):
            nm = _as_str(_fip8[0])
            alias = _as_str(_fip8[1])
            local = alias or nm
            if (local in gen._imported_generic_structs or local in gen.struct_field_types
                    or nm != local):
                continue
            src = gen._find_generic_source(st.module, nm, kind='struct')
            if src:
                gen._imported_generic_structs.setdefault(local, src)
    # A generic struct DEFINED IN THIS SAME FILE (`struct MoveOnlyList[T:
    # ...]:` with no import at all — real, in stdlib's own
    # test_ref_iteration.mojo) was never registered here: the loop above
    # only ever looks at FromImportStmt. Elaborator.elaborate_generic_struct
    # only needs the struct's own source TEXT (extract_struct_source does
    # its own regex-based extraction), so the current file's own path
    # works exactly like an imported module's — same lookup, same
    # monomorphize-and-cache path, just skipping the "which file re-exports
    # this" search entirely. Without this, `MoveOnlyList[MoveOnlyInt]()`'s
    # `__next__`/`__iter__` stayed the UN-elaborated generic (T unresolved,
    # boxed int64_t), so a `for ref x in list: x.value += 1` loop var's
    # `.value` read hit a hard "not a structure or union" — the generic
    # struct was never actually monomorphized for this type argument.
    if gen._current_filename and any(isinstance(st, gimple_ctypes.StructDef) for st in stmts):
        try:
            _own_src = open(gen._current_filename).read()
        except OSError:
            _own_src = ''
        for st in stmts:
            if not isinstance(st, gimple_ctypes.StructDef):
                continue
            if st.name in gen._imported_generic_structs or st.name in gen.struct_field_types:
                continue
            if not gimple_ctypes.re.search(rf'\bstruct\s+{gimple_ctypes.re.escape(st.name)}\s*\[', _own_src):
                continue
            gen._imported_generic_structs.setdefault(st.name, gen._current_filename)

def _struct_method_overload_ids(stmt: StructDef) -> list:
    """Overload-id per method, aligned with stmt.methods. Must match the
    emission loop in gen_module so the method's C symbol, its closure-lookup
    key (current_func_name), and the pre-pass closure registration all agree.
    Empty string for a non-overloaded method. A @staticmethod (no `self` use)
    so reflect.py's collect_exports can call the exact same logic when
    building each method's exported C symbol — reflect.py previously used a
    bare `Struct_method` name unconditionally, which silently diverged from
    this hash-suffix scheme for any overloaded method and produced a
    reflection-table entry (and forward-declared `extern` in the dylib's
    merged reflect table) pointing at a symbol nothing ever defines.

    `stmt: StructDef` is load-bearing for the self-hosted build, not
    decoration: unannotated, `stmt` compiles to an opaque int64_t, so
    `stmt.methods` resolves through `_known_field_type('methods')` — which
    is AMBIGUOUS (`MojoList *` on StructDef/TraitDef, `MojoDict *` on the
    interpreter's runtime MojoClass) and therefore answers None. The loop
    then fell to the runtime dict-or-list dispatch whose dict branch binds
    the loop variable as `char *`, so `m.name` hit `_lower_MemberExpr`'s
    pathlib `.name`->basename special case and every method collapsed onto
    ONE `counts` key. Compiled mojoc consequently believed every method of
    every struct was overloaded and emitted `Counter___init___0` /
    `Counter_inc_0_2` / `Counter_get_0_3` where the reference emits plain
    `Counter___init__` / `Counter_inc` / `Counter_get`."""
    counts = {}
    for m in stmt.methods:
        counts[m.name] = counts.get(m.name, 0) + 1
    used: dict = {}
    ids = []
    for m in stmt.methods:
        oid = ''
        if counts[m.name] > 1:
            oid = gimple_ctypes._method_overload_id(tuple(m.params or []), stmt.name, m.name)
            seen = used.setdefault(m.name, {})
            c = seen.get(oid, 0)
            seen[oid] = c + 1
            if c > 0:
                oid = f"{oid}_{c + 1}"
        ids.append(oid)
    return ids


def _struct_method_qualifier(gen, struct_name: str) -> str:
    """Home-module prefix for struct_name's method C symbols, or '' when
    no real module identity should apply.

    struct_name may be either a struct DEFINED in the module currently
    being compiled (self.module_name — already correct and unique per
    stdlib source file, see build_stdlib_dylib.py's use of
    module_loader.module_name_for_path) or one reached via `from X
    import Struct` and registered into _imported_struct_home (see the
    import-registration block that populates _imported_typedef_structs,
    and _register_reflected_struct for the dylib-reflection-only case).
    The imported case is checked first since an imported name is by
    definition not locally defined.

    Self-hosting exemption: gated on the file CURRENTLY being compiled
    being one of this repo's own .py sources, NOT on `self.module_name`
    being empty — module_name is NOT reliably empty for a self-hosted
    file: do_imports=True's _compile_imported_module recursion passes a
    real dotted-module-name-derived module_name for EVERY imported
    module, including when mojo.py's own self-hosting bootstrap pulls in
    gimple_codegen.py/monomorphize.py/etc. as sibling imports of ITSELF
    (confirmed regression: those nested compiles got
    module_name='gimple_codegen'/'monomorphize', producing calls like
    `gimple_codegen_Parser___init__` that the hardcoded self-host tables
    — which assume bare names — don't recognize, breaking
    `make check-selfhost`).

    Deliberately narrower than the `_is_selfhost_file` path-only check
    used elsewhere (~13130) for the hardcoded field/method tables: that
    check alone (just "is this file under the repo directory") ALSO
    matches ordinary .mojo test fixtures written into runtime/ by the
    test suite (e.g. test_module_cache.py's rs_cnt.mojo, itself under
    this same repo tree) — confirmed regression: it wrongly suppressed
    qualification for a real user struct (Counter) with no connection to
    the self-hosting bootstrap at all. The self-hosting bootstrap is
    always this compiler's own Python implementation, always .py — no
    .mojo source is ever part of it — so requiring a .py extension here
    (in addition to the directory check) distinguishes the two exactly.

    Synthetic cross-module ABI types exemption: `Span` is unconditionally
    seeded into struct_field_types (gen_module, NOT gated on
    _is_selfhost_file, unlike every other hardcoded entry there — see
    that seed's own comment) as a compiler-synthesized fat-pointer
    convenience type, not a real struct owned by any one module's
    source. Its `.unsafe_ptr()`/`.__len__()` calls fall through to a
    SEPARATE, older "utility stub" fallback-declaration mechanism (the
    `_util_pairs` table, unrelated to this composer) that always
    forward-declares a single, permanently bare `Span_unsafe_ptr(...)`
    shared across every compile — confirmed regression: qualifying the
    CALL SITE only (there's nothing to qualify on the definition side;
    Span has no real source module) produced a call to
    `<qualifier>_Span_unsafe_ptr` with no matching declaration anywhere,
    since the stub table still (correctly, for this shared synthetic
    type) emits the bare name. Exempt it the same way MojoList/MojoDict
    (the other synthetic runtime-representation types) are naturally
    exempt by never going through struct-method mangling at all."""
    if struct_name == 'Span':
        return ''
    # Every source below can hand back a raw module_name — which, for a
    # DOTTED package import (`import pkg.helper as m`, module_name ==
    # "pkg.helper"), contains '.' characters that are not valid in a C
    # identifier. _func_qualifier (the free-function analog of this
    # method) already sanitizes for exactly this reason (BUG-2026-049);
    # this struct-method sibling was missed at the time, so a struct
    # DEFINED in a dotted-package module (e.g. `transpiler.ast_rewrite`)
    # got an unsanitized qualifier like "transpiler.ast_rewrite" here,
    # producing an invalid C function name
    # (`transpiler.ast_rewrite_Rewriter__rewrite_param_list_ids`) that
    # GCC's parser chokes on at the literal '.' — and, once desynced,
    # goes on to misparse unrelated later lines in the same function
    # (BUG-2026-052: the "'transpiler' undeclared" errors reported deep
    # inside a docstring are that parser desync, not a real reference to
    # an undefined symbol). See _func_qualifier's own comment for the
    # same fix applied to the free-function case.
    def _sanitize_qualifier(q):
        # Strip LEADING dots before the '.'->'_' substitution: a raw
        # relative-import spelling (`.base`, from `_link_inline_modules`'
        # link-mode fallback — see `_compile_imported_module`'s temp_gen
        # `module_name=module_name`, which passes `stmt.module` through
        # completely unresolved) would otherwise sanitize to `_base`
        # (leading underscore) here, while `_emit_stdlib_import_externs`'
        # OWN relative-import resolution (`_resolve_relative`, run
        # against the SAME statement) already strips the dots before
        # this function ever sees the name and produces plain `base` —
        # two internally-consistent but MUTUALLY DISAGREEING spellings
        # of the identical module for the identical bare name. A call
        # site resolving one way and the definition resolving the other
        # way emits a reference to an undeclared identifier that (being
        # a bare, non-function name in a `(void *)` cast) silently
        # compiles to a null pointer instead of erroring — see
        # bugs/CODEGEN_link_mode_from_submodule_import_symbol_value_
        # call_segfault.md. Stripping leading dots here makes every
        # qualifier path converge on the same plain-name spelling
        # regardless of which one happened to run first.
        return q.lstrip('.').replace('.', '_').replace('-', '_') if q else q
    _cur_file = getattr(gen, '_current_filename', None)
    _cur_abs = gimple_ctypes.os.path.abspath(_cur_file) if _cur_file else ''
    if (_cur_file and _cur_file.endswith('.py')
            and (_cur_abs == gimple_codegen._SELFHOST_DIR or _cur_abs.startswith(gimple_codegen._SELFHOST_DIR + '/'))):
        return ''
    # A struct genuinely DECLARED in the file currently being compiled
    # (gen_module's _local_struct_names, set once per GimpleGen instance
    # from that instance's own top-level stmts) always wins THIS
    # instance's own qualifier, checked BEFORE the shared, whole-
    # program `_imported_struct_home` registry below. `_imported_struct_
    # home` is keyed purely on bare struct name and shared across every
    # nested temp_gen in the whole transitive closure — when a locally-
    # defined class happens to share a bare name with an unrelated (or,
    # as here, a genuine base-class) struct some OTHER module in the
    # closure legitimately registered there, checking it first
    # mislabels THIS module's own struct as belonging to that OTHER
    # module, qualifying its methods with the WRONG (foreign) prefix.
    # Concrete real-world repro: `Lib/mailbox.py` defines its own
    # `class Message(email.message.Message):` — both classes are
    # legitimately named "Message" (a genuine subclass relationship,
    # not a coincidence), and `_merge_struct_inheritance` correctly
    # splices the base's own (shared, by-reference) FunctionDef method
    # objects into mailbox.py's derived struct's own `.methods` list so
    # each concrete struct gets its own callable copies (no C++ vtable
    # here). But with the OLD priority order, mailbox.py's own "Message"
    # struct-method-emission loop looked up `_imported_struct_home
    # ['Message'] == 'email.message'` (registered when Phase 0 compiled
    # the REAL imported email.message.Message) and reused THAT
    # qualifier for its own struct too — emitting EVERY one of
    # mailbox.py's own Message methods (both genuinely inherited ones
    # and its own locally-overridden ones like `__init__`) under the
    # exact same C symbols
    # (`email_message_Message___str__`/`___init__`/...) the real
    # email.message.Message module already emits once for itself,
    # producing ~45 GCC "redefinition of ..." errors in the SAME
    # translation unit (see bugs/CODEGEN_generator_function_Lib_
    # mailbox.md / bugs/hard/CODEGEN_same_bare_name_struct_collision_
    # across_modules.md). Reordering only changes behavior for this
    # exact ambiguous case (name present in BOTH _local_struct_names
    # AND _imported_struct_home simultaneously) — the overwhelmingly
    # common case where only one of the two is true is completely
    # unaffected, since a struct's OWN compiling temp_gen registers
    # ITS OWN `module_name` into `_imported_struct_home` under the same
    # value `_local_struct_names`-based qualification would produce
    # anyway (see `_compile_imported_module`'s Phase 0 registration),
    # so the two branches agree whenever there's no real collision.
    if struct_name in getattr(gen, '_local_struct_names', ()):
        return _sanitize_qualifier(gen.module_name) or ''
    # Only apply an IMPORTED module's qualifier to a struct genuinely
    # reached via `from X import Struct` and registered into
    # _imported_struct_home (or the dylib-reflection-only case) — never
    # as a guess for a name this compile doesn't recognize as either
    # local or (registered-)imported. An imported struct _register_
    # imported_structs' narrow registration gate missed must stay
    # unqualified (the historical, safe behavior) rather than get
    # mislabeled as belonging to this module.
    home = getattr(gen, '_imported_struct_home', None)
    if home and struct_name in home:
        return _sanitize_qualifier(home[struct_name])
    return ''


def _struct_method_csym(gen, struct_name: str, method_name: str, overload_id: str) -> str:
    """The one composer every struct-method symbol site should call:
    {qualifier_}StructName_method{overload_id}, qualifier omitted when
    the struct has no real module identity (see
    _struct_method_qualifier). Mirrors _func_csym's existing shape/trick
    for free functions (see gimple_codegen.py's _func_csym): mirrors
    func_return_types/func_param_types from the bare (unqualified)
    mangled key onto the newly-qualified key via setdefault, so any
    lookup still keyed by the historical bare mangled string keeps
    resolving — no call site needs a simultaneous flag-day rename."""
    qualifier = gen._struct_method_qualifier(struct_name)
    bare = f"{struct_name}_{gimple_ctypes._safe_name(method_name)}{overload_id}"
    if not qualifier:
        return bare
    qualified = f"{qualifier}_{bare}"
    if bare in gen.func_return_types:
        gen.func_return_types.setdefault(qualified, gen.func_return_types[bare])
    if bare in gen.func_param_types:
        gen.func_param_types.setdefault(qualified, gen.func_param_types[bare])
    if hasattr(gen, '_mangled_signature_ctypes') and bare in gen._mangled_signature_ctypes:
        gen._mangled_signature_ctypes.setdefault(qualified, gen._mangled_signature_ctypes[bare])
    return qualified

def _struct_method_csym_static(qualifier: str, struct_name: str, method_name: str, overload_id: str) -> str:
    """Pure version of _struct_method_csym reflect.py can call with no
    GimpleGen instance in hand — mirrors overload_suffix_for's existing
    @staticmethod pattern (see gimple_codegen.py's overload_suffix_for),
    used the same way _func_export_csym mirrors _func_csym for free
    functions. No setdefault mirroring here: reflect.py only needs the
    symbol STRING to embed in the reflection table, not a live lookup
    table to maintain."""
    bare = f"{struct_name}_{gimple_ctypes._safe_name(method_name)}{overload_id}"
    return f"{qualifier}_{bare}" if qualifier else bare


def _gen_struct_method(gen, struct_name: str, node: gimple_ctypes.FunctionDef, overload_id: str = '') -> str:
    gen._reset_func(node.body, node.params)
    # Set module context for global field access -- mirrors the identical
    # line in gen_func/_gen_toplevel (this method was missing it entirely).
    # Without this, `self._current_module_ctx` keeps whatever value the
    # PREVIOUS gen_func/_gen_toplevel call in this same GimpleGen instance
    # happened to leave it at (or its "" __init__ default, read as "root"
    # via the `self._current_module_ctx or "root"` fallback used at every
    # write-target resolution site) -- stale, order-dependent state that
    # is correct only by coincidence. Concretely: a class whose methods
    # are the FIRST thing processed in a module's own recursive compile
    # (e.g. typing.py's `_LazyAnnotationLib`, defined right after the
    # module's `__all__` list, before any ordinary function or executed
    # module-level statement) generated its `global` write-target (see
    # _gen_stmt_AssignStmt's `_func_declared_globals` branch) against
    # `_root_globals` instead of `_typing_globals` -- "struct
    # '_root_toplev' has no member named '_lazy_annotationlib'" at gcc
    # -fsyntax-only stage. Confirmed via direct `.ci` inspection on a
    # `mojo.py build .../Lib/glob.py` run (typing.py transitively
    # imported): `typing__LazyAnnotationLib___getattr__`'s body wrote
    # `_root_globals._lazy_annotationlib = ...` even though the function
    # itself is correctly module-qualified "typing__"-prefixed and
    # `_typing_toplev`'s struct definition genuinely has that field. Same
    # class of bug (and identical fix shape: target
    # `self._current_module_ctx` directly) as the write-side misrouting
    # fixed for AssignStmt/MultiAssignStmt/_write_dest -- see
    # bugs/hard/CODEGEN_module_globals_cross_contamination_via_imported_
    # stmts.md's history -- just a 4th call site (struct/class methods)
    # that fix's audit didn't cover because it never SET the context in
    # the first place, rather than consulting the wrong (shared,
    # first-writer-wins) map.
    gen._current_module_ctx = gen.module_name if len(gen.module_name) > 0 else "root"
    # Per-lexical-scope import tracking: a method body is its own lexical
    # scope (its own local `from X import ...` statements shadow the
    # module-level same-named bindings).
    _method_scope = gen._push_import_scope()
    gen._collect_body_import_bindings(node.body, _method_scope)
    # Key by overload so overloaded methods don't share closure state (each
    # overload's lifted closures + capture env are distinct).
    gen.current_func_name = f"{struct_name}_{node.name}{overload_id}"
    gen._current_struct_name = struct_name  # for Self() constructor call lowering

    # Seed param types for pre-pass inference
    for i, (pname, ptype) in enumerate(node.params):
        # Strip Mojo parameter modifiers (inout, borrowed, etc.)
        bare = gimple_ctypes._strip_mojo_param_modifiers(pname.lstrip('*'))
        if pname == 'self':
            gen.var_types['self'] = f"{struct_name} *"
            gen._actual_types['self'] = f"{struct_name} *"
        elif pname.startswith('*'):
            gen.var_types[bare] = 'MojoList *'
            gen._actual_types[bare] = 'MojoList *'
        else:
            ctype = gen._resolve_type(ptype)
            gen.var_types[bare] = ctype
            if ctype != 'int64_t':
                gen._actual_types[bare] = ctype
            pst = gen._param_struct_name(ptype)
            if pst:
                gen._param_struct_types[bare] = pst

    _locked_key = f"{struct_name}_{node.name}"
    if (_locked_key in getattr(gen, '_selfhost_locked_param_types', ())
            and _locked_key in gen.func_return_types):
        # Self-hosting bootstrap: the frozen GimpleGen signature table
        # (gimple_gen_funcs._selfhost_gimplegen_frozen_sigs, applied in
        # gen_module_impl) is authoritative for every `GimpleGen_*` symbol.
        # Emit the definition against it so it matches the forward decl
        # every temp_gen derived from the same table.
        ret_type = gen.func_return_types[_locked_key]
    elif node.return_type is not None:
        # A method returning a bracketed generic instantiation of its OWN
        # enclosing struct (e.g. UnsafePointer.as_any_origin() -> UnsafePointer[
        # Self.type, AnyOrigin[mut=Self.mut], address_space=Self.address_space])
        # hits _mojo_type's hardcoded builtin-pointer-name shortcut (meant for
        # ordinary *uses* of these generic types elsewhere, e.g. a field
        # annotated UnsafePointer[Int]) and silently defaults to int64_t,
        # since the complex bracket contents aren't a simple type. Recognize
        # this specific case narrowly — only when the return annotation's
        # base name is literally this struct's own name AND the struct is
        # one of the pointer-family types actually represented as a real
        # struct pointer — rather than in _resolve_type generally (shared
        # by all parameter resolution; a broader fix there previously
        # mistyped sibling parameters like `other: UnsafePointer[...]`
        # that rely on the existing boxed-pointer representation), and
        # rather than for ANY self-referencing struct (tried that too:
        # broke SIMD, which returns bracketed Self-generics like
        # `SIMD[target, Self.size]` but is represented as a boxed scalar,
        # not a struct pointer — forcing `SIMD *` there broke every
        # SIMD-returning method).
        _ret_base = node.return_type.split('[', 1)[0].strip()
        if (_ret_base == struct_name
                and struct_name in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer')):
            ret_type = f"{struct_name} *"
        else:
            ret_type = gen._resolve_type(node.return_type)
    else:
        # Seed inferred LOCAL var types so `return <local>` where the
        # local holds a pointer value (e.g. a bytes accumulator built
        # from a sliced self.<field> + `+=`) infers the real C return
        # type instead of int64_t — otherwise the definition's declared
        # return type disagrees with the body (which declares the local
        # correctly from _inferred_var_types) and every caller treats
        # the returned pointer as a scalar. COMPILE_FAIL_zipfile.
        _saved_lv = dict(gen.var_types)
        try:
            for _lvn, _lvt in gen._infer_local_var_types(node).items():
                if _lvt == 'MojoBytes *':
                    gen.var_types.setdefault(_lvn, _lvt)
        except Exception:
            pass
        ret_type = gen._infer_return_type(node.body)
        gen.var_types = _saved_lv
        if ret_type == 'void':
            ret_type = 'void'

    gen.func_ret_type = ret_type
    # Sync so forward declarations (Phase 2b) match Phase 2a inference.
    # Store BOTH the base name (for single-overload lookups) and the
    # per-overload keyed name (so multi-overload methods don't clobber each other).
    bare_key = f"{struct_name}_{node.name}"
    gen.func_return_types[bare_key] = ret_type
    if overload_id:
        gen.func_return_types[f"{bare_key}{overload_id}"] = ret_type
    # Also update the (possibly module-qualified) key so _emit_call's
    # func_return_types lookup (which uses the qualified symbol name)
    # sees the correct return type — Pass 1b set the bare key to the
    # _resolve_type fallback (int64_t for unresolved generics), and
    # _struct_method_csym's setdefault already copied that stale value
    # into the qualified key; without this overwrite, _emit_call would
    # create a result temp with the wrong type.
    qualifier = gen._struct_method_qualifier(struct_name)
    if qualifier:
        qualified_key = f"{qualifier}_{bare_key}"
        gen.func_return_types[qualified_key] = ret_type
        if overload_id:
            gen.func_return_types[f"{qualifier}_{bare_key}{overload_id}"] = ret_type

    solver = gimple_solvers.LayoutSolver(gen.struct_field_types)
    gen._struct_layout = solver.solve(node.params, node.body)

    method_full_name = f"{struct_name}_{node.name}"
    has_varargs = any(pn.startswith('*') for pn, _ in (node.params or []))
    param_strs = []
    if has_varargs:
        # Keep self + any fixed params before *args, then pack the rest; e.g.
        # __call__(self, interpreter, *args) must keep `interpreter`.
        gen.func_param_types[method_full_name] = gen._signature_ctypes(node.params, node, struct_name)
    # Prefer THIS overload's own suffixed entry (registered in Pass 2b-bis,
    # gimple_codegen.py's per-struct-method overload-candidate pass) over
    # the bare/unsuffixed key. A later pre-pass (~line 10907, "CRITICAL:
    # must happen before Phase 2a") writes the bare key unconditionally for
    # every method sharing a name — last overload processed wins — so for
    # an overloaded method the bare key can hold a DIFFERENT overload's
    # param types entirely (confirmed: Logger.log(x: Int) vs
    # Logger.log(x: String) both ended up compiled with `x` as char*,
    # corrupting the Int overload's own body). The suffixed key is always
    # this specific overload's real signature.
    _suffixed_params = gen.func_param_types.get(f"{method_full_name}{overload_id}")
    hardcoded_params = (_suffixed_params if _suffixed_params is not None
                         else gen.func_param_types.get(method_full_name, []))
    seen_varargs = False
    for i, (pname, ptype) in enumerate(node.params):
        # Strip Mojo parameter modifiers (inout, borrowed, etc.)
        bare = gimple_ctypes._strip_mojo_param_modifiers(pname.lstrip('*'))
        if pname == 'self':
            ctype = f"{struct_name} *"
        elif pname.startswith('**'):
            # **kwargs: a real MojoDict* parameter (forwarding pattern)
            gen.var_types[bare] = 'MojoDict *'
            param_strs.append(f"MojoDict * {bare}")
            continue
        elif pname.startswith('*'):
            if seen_varargs:
                continue
            seen_varargs = True
            ctype = 'MojoList *'
        elif ptype == 'Self':
            # A non-self parameter typed `Self` (e.g. the keyword copy ctor
            # `__init__(out self, *, copy: Self)`) is a pointer to this struct.
            ctype = f"{struct_name} *"
        elif ptype and ptype.split('[', 1)[0].split('.')[0].strip() in gen._imported_struct_names:
            # An explicit imported-struct parameter (info: CompiledFunctionInfo)
            # is authoritative — use the struct pointer, not a type a sibling
            # overload clobbered onto the shared base key.
            ctype = f"{ptype.split('[', 1)[0].split('.')[0].strip()} *"
        elif (hardcoded_params and '...' not in hardcoded_params and i < len(hardcoded_params)
              and not (i == 0 and pname != 'self'
                       and hardcoded_params[i] == f"{struct_name} *")):
            # The guard skips a self-pointer leaked onto a non-self first param
            # from a sibling instance overload sharing this method's base key
            # (e.g. static fetch_add(ptr) vs instance fetch_add(self) on Atomic).
            hc_ctype = hardcoded_params[i]
            ctype = hc_ctype
        else:
            if ptype is None and hasattr(gen, '_inferred_param_types'):
                if method_full_name in gen._inferred_param_types and bare in gen._inferred_param_types[method_full_name]:
                    ctype = gen._inferred_param_types[method_full_name][bare]
                else:
                    ctype = gen._resolve_type(ptype)
            else:
                ctype = gen._param_ctype(pname, ptype, node)
        gen.var_types[bare] = ctype
        # Register in _actual_types so _get_actual_type resolves the real
        # type for for-loop iterables and other dispatch paths. Must happen
        # for ALL params, not just the else branch, because GimpleGen
        # methods hit hardcoded_params first and never reach the else branch.
        if ctype != 'int64_t':
            gen._actual_types[bare] = ctype
        # Record the semantic struct identity of a known-struct param so
        # member access can cast through the right struct pointer even
        # when the ABI boxed the param to a generic scalar (see
        # _param_struct_name / _lower_MemberExpr).
        pst = gen._param_struct_name(ptype)
        if pst:
            gen._param_struct_types[bare] = pst
        safe_bare = gen._param_safe_name(bare)
        if safe_bare != bare:
            gen._c_names[bare] = safe_bare
            gen.var_types[safe_bare] = ctype
        param_strs.append(f"{ctype} {safe_bare}")

    # Thread any function-typed, actually-used comptime bracket
    # parameter(s) through as ordinary trailing C parameters (opaque
    # callable pointers) — see _method_threaded_comptime_params'
    # docstring / bugs/CODEGEN_device_context_captured_function_
    # parameter_closures_broken.md's Repro 1. Call sites append the
    # matching bracket argument as an extra positional arg (see
    # _lower_call's "obj.method[...]" branch), so this signature and
    # that call-site lowering must stay in lockstep.
    for _cp_name in gen._method_threaded_comptime_params.get((struct_name, node.name), {}).get(overload_id, []):
        gen.var_types[_cp_name] = 'int64_t'
        param_strs.append(f"int64_t {_cp_name}")

    params_str = ', '.join(param_strs) if param_strs else 'void'
    mangled    = gen._struct_method_csym(struct_name, node.name, overload_id)

    gen._seed_mut_captured_local_types(gen.current_func_name)
    gen._seed_addressed_locals(node.body)
    # Same prologue box-allocation contract as the plain-function path
    # above (see _emit_mut_local_box_allocs's docstring).
    gen._emit_mut_local_box_allocs()

    gen._emit_label("bb_2")
    gen._genexp_narrow_names = set()
    gen._genexp_list_locals = {}
    gen._seed_genexp_list_narrowing(node)
    for stmt in node.body:
        gen.gen_stmt(stmt)

    # Store per-overload param types so forward declarations can match definitions exactly
    param_ctypes_only = [s.rsplit(' ', 1)[0].strip() for s in param_strs]
    gen.func_param_types[mangled] = param_ctypes_only

    # See _reset_func's own comment on `_func_used_setjmp`: a method
    # whose body emitted a real `setjmp` (try/except, or a `with`
    # using `__exit__`) must NOT be tagged `__GIMPLE` -- gcc -fgimple
    # never gives such a body's setjmp the "returns-twice" CFG
    # treatment a later `longjmp` needs, causing an unconditional
    # runtime segfault. Fall back to gen_func's existing LENIENT
    # (non-`__GIMPLE`) path for exactly those bodies; every other
    # method keeps `__GIMPLE` unchanged.
    _sig_kw = '' if gen._func_used_setjmp else '__GIMPLE '
    lines = [
        f"{ret_type} {_sig_kw}{mangled} ({params_str})",
        "{",
        *gen.decls,
        *gen.body_lines,
        "}",
    ]
    gen._pop_import_scope()
    return '\n'.join(lines)
