# Moved from gimple_gen_funcs.py - gimple C/GIMPLE backend (mojo/backend_gimple).
# Shared analysis lives in mojo/middle/*; this file is emission.
"""Function/method generation for the GIMPLE backend.

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
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
    Parser, py_tokenize, _as_str, _as_dict, _pair_key, _as_structdef_node, _as_funcdef_node,
    _as_comptimevar_node, _as_intlit_node, _as_boollit_node,
)
import ast_rewriter
import regex_compile
import mlir
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes
import gimple_codegen
from gimple_codegen import _selfhost_impl_py_files
import mojo.backend_gimple.emit_methods as gmp
import mojo.backend_gimple.emit_calls as ggc
import mojo.backend_gimple.emit_infra as ginf

# Re-export shared helpers from mojo.middle.funcs_shared via explicit imports.
# (Was globals().update(dir(_shared)); self-hosted globals() is a
# weak stub returning NULL — see runtime/fire_runtime.c _globals.)
from mojo.middle.funcs_shared import *  # noqa: F401,F403
from mojo.middle.funcs_shared import (
    _SELFHOST_EXTRA_FIELD_CACHE, _as_dict, _as_funcdef_node, _as_str, _as_structdef_node, _find_generic_source,
    _find_imported_struct, _find_symbol_home_module, _from_import_name_is_submodule, _resolved_export_entry, _imported_field_ctype, _local_sibling_module_exports, _note_struct_import_alias, _note_vararg_trailing_param_types, _pair_key,
    _param_ctype, _parsed_import, _resolve_import_module_qualifier, _resolve_reexported_closure_func, _resolve_test_relative_module, _ris_base,
    _ris_collect, _scan_from_imports_flat, _selfhost_extracted_fn_index, _selfhost_gen_self_param_ctype, _sgfs_resolve_ann, _signature_ctypes,
    _struct_method_overload_ids, _struct_method_qualifier
)

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
            _own_mut_ptr = (getattr(gen, '_gimple_mut_ptr', None) or {}).get(vname)
            if vname in ci.mut_names and _own_mut_ptr:
                # DOUBLY-NESTED by-reference capture. This function is
                # ITSELF a lifted closure that captured `vname` by
                # reference (`_gen_lifted_closure` preloaded the box
                # pointer into `_mutptr_<name>`), and the closure it is
                # building right now ALSO captures it by reference. Hand
                # the grandchild the SAME box pointer, so the whole chain
                # of levels shares the one cell the owner allocated —
                # Python's cell model, and the only way a write three
                # levels down is visible back in the owner.
                #
                # Storing `gen._cname(vname)` here (the by-value seed
                # below, or the `&`-style address the `{mut}` draft
                # first used) is what this branch replaced. Both were
                # wrong in the same way: the intermediate holds a
                # POINTER, not the value, so seeding a value into a
                # pointer field is a hard `int64_t` -> `int64_t *`
                # `-Wint-conversion` error (hit for real by
                # `Tools/wasm/wasi/__main__.py`'s
                # `subdir` -> `decorator` -> `wrapper` chain, whose
                # `wrapper` declares `nonlocal working_dir`).
                gen._emit(
                    f"  {env_var}->{gimple_ctypes._c_field_name(vname)} = {_own_mut_ptr};")
            elif vname in ci.mut_names and not (vname in gen._captures and gen._env_param):
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
                # closure; it is handled by the branch immediately above
                # (which hands the grandchild the same box pointer), and
                # only a name the enclosing function captures by VALUE
                # despite this closure wanting it by reference -- which
                # `discover_closures`'s transitive fixup now rules out --
                # falls through to the by-value branch below rather than
                # emit something silently wrong.
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
        for _fip1 in (getattr(node, 'name_alias_strs', None) or []):
            name = gimple_ctypes._fi_name(_fip1)
            alias = gimple_ctypes._fi_alias(_fip1)
            # Qualify by the module that DEFINES the name, not the one this
            # statement names. A module that only RE-EXPORTS the name (a
            # package `__init__.py`) is not the module it was compiled
            # under, and this frame is the FIRST tier `_func_qualifier`
            # consults for the name — so writing the re-exporting module's
            # qualifier here wins over the correct value
            # `_note_own_func_home` records further down, and every call
            # site inside this body then emitted `p_tri_<suffix>` against a
            # definition emitted as `sub_tri_<suffix>` ("implicit
            # declaration of function 'p_tri_...'; did you mean
            # 'sub_tri_...'?") with no other diagnostic to explain it.
            # When the defining module cannot be resolved to a path, fall
            # back to the canonical dot-stripped spelling rather than to
            # the re-exporting module.
            _sc_home = gen._find_symbol_home_module(node.module, name, 'fn')
            if _sc_home and _sc_home != node.module:
                _scope_qual = (gen._resolve_import_module_qualifier(_sc_home)
                               or _sc_home.lstrip('.').replace('.', '_')
                               .replace('-', '_'))
            else:
                _scope_qual = gen._resolve_import_module_qualifier(node.module)
            if _scope_qual:
                gen._import_scope_stack[-1][alias if alias else name] = _scope_qual
    for _fip2 in (getattr(node, 'name_alias_strs', None) or []):
        name = gimple_ctypes._fi_name(_fip2)
        alias = gimple_ctypes._fi_alias(_fip2)
        # `_as_str` on the ternary result: without it the self-hosted
        # backend erased `symbol_name` to int64_t (whole-function
        # unification off the `(_fi_home, symbol_name)` tuple key that used
        # to live below), so `gen.imported_symbols[symbol_name] = {...}`
        # stringified the `char *` bits as a DECIMAL and stored the address
        # as the dict key — `sorted(imported_symbols.keys())` then ordered
        # the `/* from .<mod> */` re-export externs by ADDRESS, differently
        # every run.
        symbol_name = _as_str(alias if alias else name)
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
        # A function-body `from REEXPORTER import name` where REEXPORTER
        # only re-exports it (the package-`__init__.py` layout) hit the same
        # dead end the module-scope `_register_sym` did, and the same fix
        # applies: resolve the DEFINING module through the re-export hops
        # and take ITS export entry. `_fi_info` was empty here (the
        # re-exporting module's text scan finds no `def`), so the whole
        # `'signature'` branch below was skipped and the call site emitted a
        # reference to a symbol nothing declares:
        #
        #   implicit declaration of function 'p_tri_9f63a2';
        #     did you mean 'sub_tri_9f63a2'?
        #
        # Gate `not _fi_info` so the ordinary case does no extra work, and
        # `_find_symbol_home_module`'s own memo/cycle-guard so a re-export
        # loop cannot hang here.
        _fi_eff_mod = node.module
        if not _fi_info and not getattr(node, 'wildcard', False):
            _fi_home = gen._find_symbol_home_module(node.module, name, 'fn')
            if _fi_home and _fi_home != node.module:
                _fi_eff_mod = _fi_home
                try:
                    _fi_hexp, _fi_hqual = gen._local_sibling_module_exports(_fi_home)
                except Exception:
                    _fi_hexp = None
                    _fi_hqual = None
                if _fi_hexp:
                    # The DEFINING module's parsed signature, not the text
                    # scan's — same reason as the module-scope twin in
                    # `_register_sym`, and see `_resolved_export_entry`.
                    _fi_info = _resolved_export_entry(gen, _fi_home, name,
                                                     _fi_hexp.get(name))
                if _fi_hqual:
                    _fi_qual = _fi_hqual
        if isinstance(_fi_info, dict) and _fi_info.get('signature'):
            if not (isinstance(gen.imported_symbols.get(symbol_name), dict)
                    and 'signature' in gen.imported_symbols[symbol_name]):
                _fi_sig = _fi_info['signature']
                if symbol_name != name:
                    import re as _re_fi
                    _fi_sig = _re_fi.sub(r'\b' + _re_fi.escape(name) + r'\b',
                                         symbol_name, _fi_sig, count=1)
                gen.imported_symbols[symbol_name] = {
                    # `_fi_eff_mod`, not `node.module`: when the name only
                    # REACHES this module through a re-export, every reader
                    # of this entry ("which module defines this symbol") has
                    # to be told about the defining one, and the call site's
                    # own qualifier below is derived from the same value —
                    # the two halves of a mangled name must name one binding.
                    'module': _fi_eff_mod,
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
                # Process-imports loop (a module this compile INLINES is
                # keyed by the import string sanitized; a module satisfied
                # by a dylib uses the path-derived qualifier). `lstrip('.')`
                # is load-bearing and was missing here, the same way it was
                # missing in `_register_sym` (mojo/middle/module_shared.py)
                # — it made this the outlier among the call sites that mangle
                # a module string into a C symbol prefix (`_note_own_func_home`
                # and `_func_qualifier._sanitize_qualifier` both strip it
                # already, so a leading depth dot survived ONLY here):
                #
                #   def f():
                #       from .sub import tri     # `node.module` == '.sub'
                #       return tri(14)
                #     here        : '.sub' -> '_sub'  (dot + the module's own
                #                   name, with the module's real leading
                #                   underscore now doubled in)
                #     definition : 'sub'    (leading dot dropped)
                #   => call site emitted `_sub_tri_<suffix>(...)` against a
                #      definition emitted as `sub_tri_<suffix>(...)`:
                #      `implicit declaration of function '_sub_tri_...'`.
                #
                # The link-mode arm is gated the same way as the top-level
                # one: only a module link mode actually INLINES
                # (`_link_inline_modules`, the imports with no dylib behind
                # them) is compiled under the import-string spelling, so only
                # that one must spell the qualifier that way.
                if (getattr(gen, 'do_imports', False)
                        or node.module in getattr(gen, '_link_inline_modules', ())):
                    # `_fi_eff_mod` — the DEFINING module — for the reason
                    # its own docstring gives: a re-exporting `p/__init__.py`
                    # is not the module `tri` was compiled under, so
                    # qualifying by it emitted `p_tri_<suffix>` against a
                    # definition emitted as `sub_tri_<suffix>`. Identical to
                    # `node.module` when nothing was re-exported.
                    _fi_home = (_fi_eff_mod.lstrip('.').replace('.', '_')
                                .replace('-', '_'))
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
                    for _fs in (gen._parsed_import(_fi_eff_mod)[2] or []):
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
                    gen._imported_home_param_types[_pair_key(_fi_home, symbol_name)] = list(_fi_pts)
            # Param defaults too — same gap as the top-level loop had
            # before its own BUG-2026-020 fix.
            try:
                _fi_fn = None
                for _fs in (gen._parsed_import(_fi_eff_mod)[2] or []):
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
        # A function-scoped `from M import Class as Alias` is the same shape
        # the module-scope path records (see `_register_sym` in
        # mojo/middle/module_shared.py) and had the same hole: the export
        # table has no class exports, so the alias reached neither the
        # `'signature'` branch above nor anything the constructor dispatch
        # consults, and `Alias(...)` inside the function built the generic
        # opaque-constructor fallback. Same shared writer, so the two
        # scopes cannot disagree about what the alias names.
        if not getattr(node, 'wildcard', False):
            gen._note_struct_import_alias(node.module, symbol_name, name)
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
        # Lib/gettext.py (~5x) in a `fire.py build
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
    # `_as_str(node.target)`: the target name read off the (boxed, untyped)
    # ComptimeVarStmt node came back as its POINTER, so the dict was keyed by
    # that pointer and every later `name in gen._comptime_vals` / `.get(name)`
    # STRING lookup MISSED — a local `comptime idx = 0` then `t[idx]` fell to
    # the `/* ct param or undeclared: idx */` placeholder where the reference
    # folds it (repro: std/test/utils/test_static_tuple.mojo).
    _ct_target = _as_str(node.target)
    # `_as_comptimevar_node(node).value` for a DIRECT field read: reading
    # `.value` off the boxed, untyped ComptimeVarStmt node went through
    # reflective dispatch and came back as the miss sentinel, so `_eval_const`
    # did not recognise the IntLiteral and returned None — `val is not None`
    # was then False and the value was never recorded (a local
    # `comptime idx = 0` then `t[idx]` hit the placeholder).
    _ct_node = _as_comptimevar_node(node)
    val = gen._eval_const(_ct_node.value)
    if val is not None:
        gen._comptime_vals[_ct_target] = val
    if isinstance(_ct_node.value, gimple_ctypes.ListExpr):
        gen._comptime_list_asts[_ct_target] = _ct_node.value
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


def _gen_stmt_NonlocalStmt(gen, node):
    # A `nonlocal` DECLARATION. Like `global` it is a statement that changes no
    # value; unlike `global` it does not name a module-level binding, so the
    # work it asks for is in the closure pass: the declared names must be
    # treated as FREE variables of this function (so they are captured from the
    # enclosing frame) and, because the function rebinds them, as
    # by-REFERENCE captures (so the write reaches that frame). Recording the
    # names here is what lets `discover_closures` do that; see
    # `mojo/middle/closures.py`.
    for name in node.names:
        gen._func_declared_nonlocals.add(name)


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






def _selfhost_literal_ctype(_val):
    """ctype for a literal / builtin-container-call RHS, or None.

    Deliberately an isinstance chain, NOT a `type(_val)`-keyed dict
    lookup: confirmed by hand that `type()` yields an unreliable
    (non-uniquely-identifying) tag self-hosted — the exact same bug
    class already found and fixed for `_WALK_FIELD_NAMES_CACHE` in
    gimple_exprtypes.py. A `dict.get(type(_val))` lookup against real
    class-object keys silently returned None for almost every value
    self-hosted (confirmed: ctok dropped from 141 matches via the shim
    to 22 self-hosted with the dict-lookup form), even though the
    lookup worked perfectly via the shim (CPython's `type()` IS a
    real, uniquely-identifying class object)."""
    if isinstance(_val, DictExpr):
        return 'MojoDict *'
    if isinstance(_val, ListExpr):
        return 'MojoList *'
    if isinstance(_val, TupleExpr):
        return 'MojoList *'
    if isinstance(_val, SetExpr):
        return 'MojoSet *'
    if isinstance(_val, StringLiteral):
        return 'char *'
    if isinstance(_val, BoolLiteral):
        return '_Bool'
    if isinstance(_val, IntLiteral):
        return 'int64_t'
    if isinstance(_val, CallExpr) and isinstance(_val.func, IdentExpr):
        _fn = _as_str(_val.func.name)
        if _fn == 'set' or _fn == 'frozenset':
            return 'MojoSet *'
        if _fn == 'dict':
            return 'MojoDict *'
        if _fn == 'list':
            return 'MojoList *'
    if isinstance(_val, TernaryExpr):
        # `X if cond else Y` (e.g. `gen._cpp_pending_tuple_slots =
        # list(_pre_slots) if (_pre_ok and _pre_slots) else None`, real
        # extracted-helper code in gimple_cpp_async.py) -- neither
        # branch alone is the whole RHS, so the top-level isinstance
        # checks above never matched and this field silently defaulted
        # to `int64_t` on BOTH the shim and self-hosted before this
        # case existed (the shim independently resolved the correct
        # type some other way downstream; self-hosted did not, which
        # is what this fix closes). Recurse into whichever branch
        # resolves to a real ctype first (a bare `None` branch
        # correctly yields nothing to prefer over the other).
        _tc = _selfhost_literal_ctype(_val.then_val)
        if _tc is not None:
            return _tc
        return _selfhost_literal_ctype(_val.else_val)
    return None


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
    # NOT `isinstance(_ann, str)`: callers pass `AssignStmt.type_ann` /
    # `VarDecl.type_ann`, both hardcoded ambiguous `int64_t` in
    # gimple_module_gen.py's struct_field_types (the field is legitimately
    # `str | None`, but the table lumps it in with the polymorphic
    # target/value slots). `mojo_isinstance`/`mojo_isinstance_p`
    # (runtime/fire_runtime.c) never implement type_id 4 (str) for an
    # ambiguous boxed int64_t -- they unconditionally return 0 -- so
    # `isinstance(_ann, str)` is FALSE self-hosted for every real string
    # value here, not just malformed ones (confirmed: this is what made
    # `.type_ann` look "corrupted, neither str nor None" throughout the
    # Finding 5 investigation -- it wasn't corruption, isinstance(x, str)
    # simply cannot answer True for this field's representation). `is None`
    # is unaffected (a direct sentinel-value compare, not a type dispatch),
    # and `_as_str` is this codebase's established zero-cost cast for
    # exactly this "backend erased a real str to int64_t" shape -- same
    # fix pattern as every other `_as_str(...)` call in this file.
    if _ann is None:
        return None
    _s = _as_str(_ann).strip()
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


def _selfhost_merge_field(_fields: dict[str, str], _name: str, _ct: str):
    _cur = _fields.get(_name)
    # A generic default (`int`/`int64_t`) must yield to ANY more specific
    # ctype seen later for the same field, not just a pointer type -- the
    # earlier `_ct.endswith(' *')`-only check let a `_Bool` literal seen
    # after an `int64_t` default get silently dropped (a real, confirmed
    # shim-vs-noshim divergence: `_selfhost_gimplegen_registered` etc.
    # stuck at `int64_t` self-hosted while the shim correctly settled on
    # `_Bool`).
    if _cur is None or (_cur in ('int', 'int64_t', '_Bool')
                         and (_ct.endswith(' *') or _ct == '_Bool')):
        _fields[_name] = _ct


def _selfhost_walk_stmts_for_assign_targets(stmts, p0, fields):
    """Narrow, statement-only recursive walker used ONLY by
    `_selfhost_scan_gimplegen_extra_fields` — deliberately NOT the shared
    `gimple_exprtypes._walk_ast` (a full generic-dataclass-reflection
    walker used ~48 places across the compiler, and the documented
    subject of a well-known, actively-tracked O(N^2) whole-program
    rescan cost — see bugs/hard/PERF_nested_module_compile_walk_ast_
    quadratic_rescan.md). `self.x = <literal>` assignments are always
    direct statements, never nested inside an expression, so this only
    needs to recurse into STATEMENT-level body-bearing fields (if/while/
    for/try/with/match/comptime blocks) — far cheaper and, critically,
    self-hosted-safe: an attempt to instead fix `_walk_ast` itself
    (reordering its `dataclasses.is_dataclass` check ahead of its
    scalar-leaf isinstance checks, which were found to misclassify real
    AST dataclass instances as scalars self-hosted) made the shared
    walker recurse correctly for the FIRST time self-hosted — and that
    alone was enough to trigger the above O(N^2) rescan's real cost on
    literally any file's `--dump-full` self-compile (confirmed
    reproducing standalone on `gimple_gen_loops.py` alone, unrelated to
    this scan), causing multi-GB RSS growth and a SIGSEGV. Fixing the
    shared utility is out of scope for this investigation; this
    dedicated walker sidesteps it entirely for GimpleGen's own narrow
    need. Mutates `fields` via `_selfhost_merge_field`; no return value.

    NOTE: `isinstance(x, (A, B))` with a tuple of types is unreliable
    self-hosted (always evaluates False) — every check below is a
    separate `isinstance(x, A) or isinstance(x, B)` chain instead."""
    for _n in stmts:
        if isinstance(_n, MultiAssignStmt):
            _targets = _n.targets
        elif isinstance(_n, AssignStmt):
            _targets = [_n.target]
        else:
            _targets = None
        if _targets is not None:
            for _tgt in _targets:
                # `_as_str()` on `_tgt.obj.name` — a boxed self-hosted
                # AST-field read compared directly with `==` against
                # `p0` is the exact established bug class this codebase
                # has hit repeatedly; confirmed by hand this was the
                # single remaining self-hosted divergence at this layer.
                if (isinstance(_tgt, MemberExpr)
                        and isinstance(_tgt.obj, IdentExpr)
                        and _as_str(_tgt.obj.name) == _as_str(p0)):
                    _ct = _selfhost_literal_ctype(_n.value)
                    if _ct is not None:
                        # `_as_str()` on the field name — a boxed
                        # self-hosted AST-field read used directly as a
                        # dict key is a recurring corruption bug class
                        # in this codebase.
                        _selfhost_merge_field(fields, _as_str(_tgt.member), _ct)
        if isinstance(_n, IfStmt):
            _selfhost_walk_stmts_for_assign_targets(_n.then_body, p0, fields)
            for _ec, _eb in _n.elifs:
                _selfhost_walk_stmts_for_assign_targets(_eb, p0, fields)
            if _n.else_body:
                _selfhost_walk_stmts_for_assign_targets(_n.else_body, p0, fields)
        elif isinstance(_n, ComptimeIfStmt):
            _selfhost_walk_stmts_for_assign_targets(_n.then_body, p0, fields)
            for _ec, _eb in _n.elifs:
                _selfhost_walk_stmts_for_assign_targets(_eb, p0, fields)
            if _n.else_body:
                _selfhost_walk_stmts_for_assign_targets(_n.else_body, p0, fields)
        elif isinstance(_n, WhileStmt) or isinstance(_n, ForStmt) or isinstance(_n, ComptimeForStmt):
            _selfhost_walk_stmts_for_assign_targets(_n.body, p0, fields)
            _eb2 = getattr(_n, 'else_body', None)
            if _eb2:
                _selfhost_walk_stmts_for_assign_targets(_eb2, p0, fields)
        elif isinstance(_n, TryStmt):
            _selfhost_walk_stmts_for_assign_targets(_n.body, p0, fields)
            for _h in _n.handlers:
                _selfhost_walk_stmts_for_assign_targets(_h.body, p0, fields)
            if _n.else_body:
                _selfhost_walk_stmts_for_assign_targets(_n.else_body, p0, fields)
            if _n.finally_body:
                _selfhost_walk_stmts_for_assign_targets(_n.finally_body, p0, fields)
        elif isinstance(_n, WithStmt):
            _selfhost_walk_stmts_for_assign_targets(_n.body, p0, fields)
        elif isinstance(_n, MatchStmt):
            for _c in _n.cases:
                _selfhost_walk_stmts_for_assign_targets(_c.body, p0, fields)


def _selfhost_scan_gimplegen_extra_fields(_src_dir=None) -> dict[str, str]:
    """`{attr_name: ctype}` for every GimpleGen instance attribute first
    bound OUTSIDE `class GimpleGen`'s own body — i.e. `gen.<attr> = <literal>`
    / `self.<attr> = <literal>` inside the extracted backend helper functions
    (`gen.bb_counter = 2` in emit_infra.py, `gen._loop_depth = ...` in
    emit_calls.py, ...). The `class GimpleGen` scan can't see these, so they
    default to opaque `int` and a real pointer stored into that field
    truncates → segfault.

    Only literal RHS is trustworthy for a ctype; `gen.x = f()` gives nothing
    and is left to `_inferred_param_types` / the frozen table. Cached on the
    mtime set of implementation sources under the resolved source dir
    (root `gimple_*.py` + `mojo/middle` + `mojo/backend_gimple`).

    `_src_dir` (`gen._selfhost_src_dir`, threaded through from
    `_selfhost_register_gimplegen`) is tried FIRST, same fallback order as
    `_selfhost_load_gimplegen_class` in gimple_codegen.py: in the COMPILED
    binary `_SELFHOST_DIR` is `dirname(abspath(__file__))`, and `__file__`
    there is `<bootstrap>`, so it can resolve to a directory with no
    implementation siblings at all.

    File discovery goes through `gimple_codegen._selfhost_impl_py_files`
    (os.listdir-based): confirmed by hand that `glob.glob` silently returns
    0 matches self-hosted regardless of directory correctness."""
    _files: list = []
    for _cand_dir in (_src_dir, gimple_codegen._SELFHOST_DIR, '.', '..'):
        if _cand_dir is None:
            continue
        _cand_files = _selfhost_impl_py_files(_cand_dir)
        _cand_files = [f for f in _cand_files if gimple_ctypes.os.path.isfile(f)]
        if _cand_files:
            _files = _cand_files
            break
    _key = tuple((f, gimple_ctypes.os.path.getmtime(f)) for f in _files)
    _hit = _SELFHOST_EXTRA_FIELD_CACHE.get('k')
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _fields: dict[str, str] = {}
    for _f in _files:
        try:
            _mod: list = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _fn in _mod:
            if not (isinstance(_fn, FunctionDef) and _fn.params
                    and _fn.params[0][0].lstrip('*') in ('gen', 'self')):
                continue
            _p0 = _fn.params[0][0].lstrip('*')
            _selfhost_walk_stmts_for_assign_targets(_fn.body, _p0, _fields)
    _SELFHOST_EXTRA_FIELD_CACHE['k'] = (_key, _fields)
    return _fields


def _selfhost_gimplegen_field_types(gg_cls, _src_dir=None) -> dict:
    """`{field_name: ctype}` for `class GimpleGen` — its own `__init__` /
    method / class-body `self.X = <literal>` writes (compact literal-only
    inference, everything else → `int64_t`, refined later by
    `_inferred_param_types` / `_mojo_dispatch_getattr`), UNIONed with the
    extracted-helper writes (`_selfhost_scan_gimplegen_extra_fields`).

    This is what a nested temp_gen that never sees `class GimpleGen`'s
    StructDef in its own `stmts`/`imported_stmts` registers into the shared
    `struct_field_types['GimpleGen']` so `self`/`gen` params can be typed."""
    # Not `dict(_selfhost_scan_gimplegen_extra_fields())` — the self-hosted
    # backend's dict-copy-constructor is unreliable for this shape (same
    # class of bug as gimple_module_gen.py's matching fix, e8598e1):
    # rebuild via an indexed loop + _as_str instead of trusting dict() to
    # preserve key/value C types across the copy.
    _fields: dict = {}
    _sf_src = _selfhost_scan_gimplegen_extra_fields(_src_dir)
    for _sfk in _sf_src:
        _fields[_as_str(_sfk)] = _as_str(_sf_src[_sfk])
    if gg_cls is None:
        return _fields
    # class-body attrs (`_KNOWN_SIGS = {...}`, `_cpp_kwfwd_counter = 0`, ...)
    for _fld in getattr(gg_cls, 'fields', []):
        if isinstance(_fld, AssignStmt) and isinstance(_fld.target, IdentExpr):
            _ct = (_selfhost_ann_ctype(getattr(_fld, 'type_ann', None))
                   or _selfhost_literal_ctype(_fld.value))
            if _ct is not None:
                _selfhost_merge_field(_fields, _as_str(_fld.target.name), _ct)
        elif isinstance(_fld, VarDecl) and _fld.name:
            _ct = _selfhost_ann_ctype(getattr(_fld, 'type_ann', None))
            _selfhost_merge_field(_fields, _as_str(_fld.name), _ct or 'int64_t')
    # `__init__(self, ..., module_name="", ...)` param defaults: a bare
    # `self.module_name = module_name` in the body carries no literal RHS,
    # so infer the field ctype from the parameter's own default value /
    # annotation. Without this `module_name` stayed int64_t and every
    # `gen.module_name`-based module-name compare (`_global_to_module`
    # ownership, `_<mod>_globals` struct routing) read boxed garbage.
    _init_param_ct: dict = {}
    # NOT `_m.name != '__init__'` (even wrapped in `_as_str()`) -- confirmed
    # by hand that reading `.name` off a FunctionDef from THIS specific
    # object graph (the runtime meta-reparse of gimple_codegen.py done by
    # `_selfhost_load_gimplegen_class`, invoking the self-hosted-compiled
    # Parser as a library call rather than through the ordinary compile
    # flow) comes back as outright corrupted garbage self-hosted for EVERY
    # method (logged: every one of 363 methods printed the same nonsense
    # bytes, not merely a comparison failure) -- a different, deeper bug
    # than any `_as_str()` fix addresses. `__init__` is reliably the FIRST
    # method GimpleGen declares (confirmed via the shim's own method-name
    # log), so use position instead of a name read/compare that's known
    # broken on this object graph.
    _gg_methods_list = getattr(gg_cls, 'methods', [])
    if _gg_methods_list:
        _m = _gg_methods_list[0]
        for _pn, _pt in (getattr(_m, 'params', None) or []):
            _bare = _as_str(_pn).lstrip('*')
            _pc = _selfhost_ann_ctype(_pt)
            if _pc is not None:
                _init_param_ct[_bare] = _pc
        for _pn2, _dv in (getattr(_m, 'param_defaults', None) or {}).items():
            _bare2 = _as_str(_pn2).lstrip('*')
            if _bare2 not in _init_param_ct:
                _lc = _selfhost_literal_ctype(_dv)
                if _lc is not None:
                    _init_param_ct[_bare2] = _lc
    # `self.X = <literal>` in every method body (dominated by __init__).
    # Deliberately NOT `gimple_exprtypes._walk_ast(_m.body)` -- the same
    # shared-utility bug already worked around in
    # `_selfhost_scan_gimplegen_extra_fields` (isinstance(node, str/int/
    # float/bool) misclassifies real AST dataclass instances self-hosted,
    # so the walker barely recurses past the top level of a method body)
    # applies here too; any `self.X = <literal>` nested inside an if/for/
    # try/with/match block in `__init__` or another method went
    # undetected self-hosted, defaulting those fields to `int64_t`.
    # Confirmed by hand: after this class's whole GimpleGen struct
    # matched the shim in total field COUNT, ~19 fields (`do_imports`,
    # `_dispatch_solver`, `_cpp_gen_self_struct`, ...) still showed
    # `int64_t` self-hosted where the shim had the correct `_Bool`/
    # `char *`/`DispatchSolver *`/etc — this scan is where they're set.
    for _m in getattr(gg_cls, 'methods', []):
        _selfhost_walk_stmts_for_self_assigns(_m.body, _fields, _init_param_ct)
    return _fields


def _selfhost_walk_stmts_for_self_assigns(stmts, fields, init_param_ct):
    """Narrow, statement-only recursive walker for `self.X = <literal>`
    assignments inside a GimpleGen method body — the sibling of
    `_selfhost_walk_stmts_for_assign_targets` (same rationale: avoids
    the shared, self-hosted-broken `gimple_exprtypes._walk_ast`).
    Mutates `fields` via `_selfhost_merge_field`; no return value."""
    for _n in stmts:
        if (isinstance(_n, AssignStmt)
                and isinstance(_n.target, MemberExpr)
                and isinstance(_n.target.obj, IdentExpr)
                and _as_str(_n.target.obj.name) == 'self'):
            # NOTE: `getattr(_n, 'type_ann', None)` was confirmed by hand
            # to read as non-string garbage self-hosted for at least some
            # assignments in this method body (e.g. `self._dispatch_
            # solver: DispatchSolver | None = None`) -- the same class of
            # attribute-read corruption already found on `.name` for
            # FunctionDef objects from this same runtime-meta-reparsed
            # `class GimpleGen` object graph (see `_selfhost_gimplegen_
            # field_types`'s docstring/comments). `_selfhost_ann_ctype`
            # safely returns None for a non-string input, so this doesn't
            # crash -- it just silently loses the annotation-based type
            # for whichever fields hit it, leaving them at the generic
            # `int64_t` fallback. NOT fixed here; flagged as a deeper,
            # unresolved followup in bugs/CODEGEN_noshim_dumpfull_
            # preexisting_divergence.md — reading ANY attribute off an
            # object from this object graph may be unreliable, not just
            # `.name`/`.type_ann` specifically, so a real fix likely needs
            # to avoid re-parsing `class GimpleGen` via this runtime path
            # at all rather than patching individual field reads.
            _swfsa_member = _as_str(_n.target.member)
            if _swfsa_member == '_dispatch_solver':
                # `self._dispatch_solver: DispatchSolver | None = None` --
                # confirmed by hand (env-gated diagnostic) that `.type_ann`
                # reads back as neither a string NOR None self-hosted for
                # THIS one assignment (genuine value corruption on this
                # object graph, not a comparison/typing bug any `_as_str()`
                # cast can fix -- unlike every other `X | None`-annotated
                # GimpleGen field, all of which use a BUILTIN type name
                # (list/str/dict) resolved via `_SELFHOST_ANN_CTM` rather
                # than this function's separate bare-CapWord-struct-name
                # branch). `DispatchSolver` is a real, always-known struct
                # (gimple_solvers.py) for this one specific field, so
                # hardcode it directly -- same shape of narrow, name-based
                # exception `_struct_method_qualifier` already uses for
                # `Span`/`GimpleGen`.
                _selfhost_merge_field(fields, _swfsa_member, 'DispatchSolver *')
                continue
            _ct = (_selfhost_ann_ctype(getattr(_n, 'type_ann', None))
                   or _selfhost_literal_ctype(_n.value))
            if _ct is None and isinstance(_n.value, IdentExpr):
                _ct = init_param_ct.get(_as_str(_n.value.name))
            _selfhost_merge_field(fields, _swfsa_member, _ct or 'int64_t')
        if isinstance(_n, IfStmt):
            _selfhost_walk_stmts_for_self_assigns(_n.then_body, fields, init_param_ct)
            for _ec, _eb in _n.elifs:
                _selfhost_walk_stmts_for_self_assigns(_eb, fields, init_param_ct)
            if _n.else_body:
                _selfhost_walk_stmts_for_self_assigns(_n.else_body, fields, init_param_ct)
        elif isinstance(_n, ComptimeIfStmt):
            _selfhost_walk_stmts_for_self_assigns(_n.then_body, fields, init_param_ct)
            for _ec, _eb in _n.elifs:
                _selfhost_walk_stmts_for_self_assigns(_eb, fields, init_param_ct)
            if _n.else_body:
                _selfhost_walk_stmts_for_self_assigns(_n.else_body, fields, init_param_ct)
        elif isinstance(_n, WhileStmt) or isinstance(_n, ForStmt) or isinstance(_n, ComptimeForStmt):
            _selfhost_walk_stmts_for_self_assigns(_n.body, fields, init_param_ct)
            _eb2 = getattr(_n, 'else_body', None)
            if _eb2:
                _selfhost_walk_stmts_for_self_assigns(_eb2, fields, init_param_ct)
        elif isinstance(_n, TryStmt):
            _selfhost_walk_stmts_for_self_assigns(_n.body, fields, init_param_ct)
            for _h in _n.handlers:
                _selfhost_walk_stmts_for_self_assigns(_h.body, fields, init_param_ct)
            if _n.else_body:
                _selfhost_walk_stmts_for_self_assigns(_n.else_body, fields, init_param_ct)
            if _n.finally_body:
                _selfhost_walk_stmts_for_self_assigns(_n.finally_body, fields, init_param_ct)
        elif isinstance(_n, WithStmt):
            _selfhost_walk_stmts_for_self_assigns(_n.body, fields, init_param_ct)
        elif isinstance(_n, MatchStmt):
            for _c in _n.cases:
                _selfhost_walk_stmts_for_self_assigns(_c.body, fields, init_param_ct)


def _dvt_val_cts(_ann):
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
        _nv = _dvt_val_cts(_vann)
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



def _dvt_consider(_out, _tgt, _ann):
    _fname = None
    if (isinstance(_tgt, MemberExpr) and isinstance(_tgt.obj, IdentExpr)
            and _tgt.obj.name == 'self'):
        _fname = _tgt.member
    elif isinstance(_tgt, IdentExpr):
        _fname = _tgt.name
    if _fname is None or _fname in _out:
        return
    _r = _dvt_val_cts(_ann)
    if _r is not None:
        _out[_fname] = (_r[0], _r[1], str(_ann).strip())



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

    for _fld in getattr(gg_cls, 'fields', []):
        if isinstance(_fld, AssignStmt):
            _dvt_consider(_out, _fld.target, getattr(_fld, 'type_ann', None))
        elif isinstance(_fld, VarDecl) and _fld.name:
            _dvt_consider(_out, IdentExpr(_fld.name), getattr(_fld, 'type_ann', None))
    for _m in getattr(gg_cls, 'methods', []):
        for _n in gimple_exprtypes._walk_ast(_m.body):
            if isinstance(_n, AssignStmt) and getattr(_n, 'type_ann', None):
                _dvt_consider(_out, _n.target, str(_n.type_ann))
    return _out




def _sgfs_fn_delegate_target(_m, _idx: dict):
    """Hoisted out of `_selfhost_gimplegen_frozen_sigs` (module-level, not a
    nested closure) — see that function's docstring for why: a nested
    closure capturing `gen`/other locals from inside a function this big
    is exactly the "lifted closure" shape that has repeatedly erased or
    nondeterministically allocated its env struct elsewhere this session
    (see gimple_gen_exprs.py's `_lb_as_set`/`_lower_binary_set_op`, and
    this same bug class's own occurrence right here — confirmed via a real
    --dump-full fire.py determinism diff showing `_alloc_..._inferred_env
    ()` vs `(...*)0` for the SAME call site across two runs)."""
    _body = [s for s in _m.body
             if not (isinstance(s, ExprStmt)
                     and isinstance(s.value, StringLiteral))]
    if (len(_body) == 1 and isinstance(_body[0], ReturnStmt)
            and isinstance(_body[0].value, CallExpr)
            and isinstance(_body[0].value.func, MemberExpr)
            and isinstance(_body[0].value.func.obj, IdentExpr)):
        return _idx.get(_body[0].value.func.member)
    return None


def _sgfs_inferred(gen, _inf_cache: dict, _fn):
    """Hoisted out of `_selfhost_gimplegen_frozen_sigs` — see
    `_sgfs_fn_delegate_target`'s docstring."""
    _k = id(_fn)
    if _k not in _inf_cache:
        try:
            _inf_cache[_k] = gen._infer_param_types(_fn) or {}
        except Exception:
            _inf_cache[_k] = {}
    return _inf_cache[_k]




def _sgfs_param_ct(gen, _inf_cache: dict, _ann, _pn, _tgt_fn, _tgt_pn, _pos, _self_fn):
    """Hoisted out of `_selfhost_gimplegen_frozen_sigs` — see
    `_sgfs_fn_delegate_target`'s docstring."""
    if _ann is not None:
        return _sgfs_resolve_ann(gen, _ann)
    if _tgt_fn is not None and _pos < len(_tgt_fn.params):
        _ta = _tgt_fn.params[_pos][1]
        if _ta is not None:
            return _sgfs_resolve_ann(gen, _ta)
    _ct = _sgfs_inferred(gen, _inf_cache, _tgt_fn).get(_tgt_pn) if _tgt_fn is not None else None
    if _ct is None:
        _ct = _sgfs_inferred(gen, _inf_cache, _self_fn).get(_pn)
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


def _sgfs_ret_ct(gen, _m, _tgt_fn):
    """Hoisted out of `_selfhost_gimplegen_frozen_sigs` — see
    `_sgfs_fn_delegate_target`'s docstring."""
    if getattr(_m, 'return_type', None) is not None:
        return _sgfs_resolve_ann(gen, _m.return_type)
    if _tgt_fn is not None:
        if getattr(_tgt_fn, 'return_type', None) is not None:
            return _sgfs_resolve_ann(gen, _tgt_fn.return_type)
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


def _selfhost_gimplegen_frozen_sigs(gen, gg_cls) -> dict:
    """`{GimpleGen_<m>: (ret_ctype, [param_ctypes], [(pname, default_ast)])}` —
    a deterministic signature for every `class GimpleGen` method, computed
    ONCE against the root gen and shared/locked into every temp_gen so
    forward-decl and definition agree by construction (`_infer_param_types`
    is not pure — it reads the growing per-instance `struct_field_types`).

    Return/param types: the method's own annotation if it has one; else, for
    a one-line forwarding delegate `return <alias>.<fn>(self, ...)`, the
    extracted helper `<fn>`'s annotation at the same position; else
    `int64_t`. `self` → `GimpleGen *`.

    The four helper closures this used to nest directly (`_fn_delegate_
    target`, `_inferred`, `_param_ct`, `_ret_ct`) are now module-level
    functions (`_sgfs_*`, above) taking `gen`/`_inf_cache`/`_idx` explicitly
    — a real --dump-full fire.py determinism diff caught one of them
    (`_inferred`'s lifted-closure env) being allocated on one run and
    replaced with a null pointer on another, for the identical call site."""
    if gg_cls is None:
        return {}
    _idx = _selfhost_extracted_fn_index()
    # Signal-based param inference for the extracted helpers and for a
    # method's own body. Run against the (nearly-empty struct_field_types)
    # root gen so the impure struct-field-shape-matching branch of
    # `_infer_param_types` never engages — only the pure list/dict/string/
    # iteration/`len()` signals — keeping the result identical in every
    # temp_gen.
    _inf_cache: dict = {}

    _out: dict = {}
    _gg_methods = _as_structdef_node(gg_cls).methods
    for _mi in range(len(_gg_methods)):
        _m = _as_funcdef_node(_gg_methods[_mi])
        if _as_str(_m.name) == '__init__':
            continue
        _tgt = _sgfs_fn_delegate_target(_m, _idx)
        _rc = _sgfs_ret_ct(gen, _m, _tgt)
        _pcs = []
        _has_star = False
        _mparams = _m.params
        for _i in range(len(_mparams)):
            _pn = _as_str(_mparams[_i][0])
            _pt = _mparams[_i][1]
            if _pn.startswith('*'):
                _has_star = True
                break
            if _i == 0 and _pn == 'self':
                _pcs.append('GimpleGen *')
            else:
                # delegate forwards self as its own arg 0, so target pos == _i
                _tgt_pn = (_tgt.params[_i][0]
                           if _tgt is not None and _i < len(_tgt.params) else _pn)
                _pcs.append(_sgfs_param_ct(gen, _inf_cache, _pt, _pn, _tgt, _tgt_pn, _i, _m))
        if _has_star:
            continue   # variadic — leave to the normal passes
        # Index arg_pairs[i][0]/[1] directly rather than tuple-unpacking a
        # for-clause target (`for pn, dv in (...).items()`) — the
        # established boxing bug.
        _dflts = [(_pd_pair[0], _pd_pair[1])
                  for _pd_pair in (getattr(_m, 'param_defaults', None) or {}).items()]
        _out[f'GimpleGen_{_m.name}'] = (_rc, _pcs, _dflts)
    return _out






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
        _home_store[_pair_key(_q.replace('.', '_').replace('-', '_'), bare_name)] = list(pts)
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
            pts = _def_store.get(_pair_key(_sq, bare_name))
            if pts is not None:
                return pts
        if store:
            pts = store.get(_pair_key(_sq, bare_name))
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
    real repro found via `fire.py build`, not build_stdlib_dylib.py's
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
            for _fip3 in (getattr(stmt, 'name_alias_strs', None) or []):
                nm = gimple_ctypes._fi_name(_fip3)
                alias = gimple_ctypes._fi_alias(_fip3)
                # Same defining-module resolution as `_gen_stmt_FromImportStmt`'s
                # own scope write, and it has to be the SAME answer: this
                # pre-scan fills the frame BEFORE the body is lowered, and
                # the body pass writes the same frame again, so whichever
                # ran first with the wrong module string would leave every
                # call site in the body qualified by the re-exporting
                # module ("implicit declaration of function 'p_tri_...';
                # did you mean 'sub_tri_...'?") with no diagnostic pointing
                # at the import at all.
                _cb_mod = stmt.module
                _cb_home = gen._find_symbol_home_module(stmt.module, nm, 'fn')
                if _cb_home and _cb_home != stmt.module:
                    _cb_mod = _cb_home
                q = gen._resolve_import_module_qualifier(_cb_mod)
                if not q and _cb_mod != stmt.module:
                    # Unresolvable to a path: the canonical dot-stripped
                    # spelling of the DEFINING module, never the
                    # re-exporting one (which is what produced the
                    # mismatch).
                    q = _cb_mod.lstrip('.').replace('.', '_').replace('-', '_')
                if not q:
                    continue
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
    DIFFERENT real miscompiles surfaced via `fire.py build`'s actual
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
        key = q.lstrip('.').replace('.', '_').replace('-', '_') if q else q
        resolved = gen._inline_module_qualifiers.get(key, key)
        return resolved.lstrip('.').replace('.', '_').replace('-', '_') if resolved else resolved
    # NOT an early `if self-hosting file: return ''` short-circuit here
    # (removed — see git history / bugs doc): that unconditionally bare-ified
    # EVERY reference made from within any self-hosting-flagged file,
    # including one that genuinely imports a DIFFERENT, non-self-hosting
    # submodule (a downstream project's own nested package, e.g. a `jit/`
    # subdirectory that sits one level below the sibling `fire_compiler.py`
    # check) — those callees are correctly compiled WITH a real module
    # prefix (tier 3 below resolves it correctly), so a caller-side bare
    # override produced an undeclared-symbol reference instead. Removing
    # it is a no-op for genuine self-hosting-internal references (tiers
    # 1-3 below simply find nothing for those, same as before, falling
    # through to this function's own unconditional trailing `return ''`)
    # while letting a real cross-module resolution win when one exists.
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
    # `_as_dict` at BOTH levels: `gen.imported_symbols` is `dict[str, dict]`
    # but the self-hosted backend erases the OUTER field AND the nested
    # `.get()` value to int64_t, so `_imp_info.get('original_name')` and
    # `_safe_name(_orig)` stringified boxed pointers into decimal C
    # identifiers — the `#ifndef _Users_..._<addr>` re-export guards and
    # `extern <addr> <name>` decls, address-ordered / different every run.
    _imp_info = _as_dict(_as_dict(gen.imported_symbols).get(bare_name))
    _orig = _as_str(_as_dict(_imp_info).get('original_name')) if _imp_info else None
    # `_as_str` on the ternary: the phi'd `base` local came back typed
    # int64_t on the self-hosted path, so `f"{qualifier}_{base}"` below
    # emitted `mojo_str_from_int(base)` — the guard/decl name became a
    # decimal ADDRESS (`_Users_..._<addr>`, `extern <addr> <fn>`).
    if _orig and _orig != bare_name:
        base = _as_str(gimple_ctypes._safe_name(_orig))
    else:
        base = _as_str(gimple_ctypes._safe_name(bare_name))
    if not gen._func_mangleable(bare_name):
        return base
    qualifier = _as_str(gen._func_qualifier(bare_name))
    if qualifier:
        qualified_base = qualifier + '_' + base
    else:
        qualified_base = base
    mangled = qualified_base + _as_str(gen._overload_suffix(bare_name))
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
    # A COROUTINE BODY is lowered by a dedicated pass whose body model is
    # scalar-only, so the lambda beta-reduction must not inline a capturing
    # lambda's body into it — see `_reset_func`'s own comment for the exact
    # miscompile (a captured `char *` collapsed to int64_t) and coro.py's
    # `_mojo_coro_body` marker for why the two is_generator/is_async flags
    # cannot be used to detect this. Read off the node rather than inferred
    # from the name: `*_body` is a legal user function name.
    _is_coro_body = bool(getattr(node, '_mojo_coro_body', False))
    gen._reset_func(node.body, node.params,
                    allow_lambda_reduction=not _is_coro_body)
    # Per-FUNCTION record of which locals hold a beta-reducible
    # capturing lambda (see mojo/middle/lambdareduce). Cleared here,
    # at a real per-function entry point, rather than in `_reset_func`
    # — a lifted closure resets too, and clearing there would wipe the
    # enclosing function's entries mid-body.
    gen._inlined_lambdas = {}
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
    #
    # Plain `for pname, ptype in node.params:` — NOT indexed access
    # (`node.params[_pi][0]`). That double-subscript form was tried here
    # and is itself broken on the self-hosted path: it comes back with a
    # working `==`/`.startswith()` but a BROKEN `len()` (reported 0 for a
    # real 1-char string) and every `in`/`.get()` dict lookup against it
    # misses, even though a plain for-loop unpack over the exact same
    # `list[tuple[str, str]]` hashes correctly. Confirmed via
    # unescape_c.py's `s` parameter: with indexed access, `_infer_param_
    # types`'s correctly-computed `{'s': 'char *'}` entry existed in
    # `gen._inferred_param_types['unescape_c']` but `.get(pname)` here
    # still missed it and fell through to the int64_t default; switching
    # this loop back to a plain unpack fixed it. Do not "index-ify" this
    # loop, or any other `for name, type in <FunctionDef>.params:` loop —
    # only tuple-of-tuples built ad hoc at runtime (e.g.
    # analyze_param_usage's `==`/`+` operand scans) need the indexed fix.
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

    # Which parameters a nested closure captures BY REFERENCE has to be
    # known BEFORE `param_strs` is built: such a parameter is declared
    # under a second C name so the heap box can carry the source-level
    # one. See _plan_mut_captured_params.
    ginf._plan_mut_captured_params(gen, node, node.name)

    param_strs = []
    has_varargs = gimple_ctypes._params_have_vararg(node.params)
    seen_varargs = False
    # Plain `for pname, ptype in node.params:` — NOT indexed. Unlike a
    # tuple-of-tuples built ad hoc at runtime (see analyze_param_usage's
    # `==`/`+` operand scans), a for-loop unpack over `node.params`
    # itself (a real, statically-typed `list[tuple[str, str]]` dataclass
    # field) lowers correctly on the self-hosted path — CONFIRMED by
    # direct comparison: `node.params[_pi][0]` (double subscript) came
    # back with a working `==`/`.startswith()` but a BROKEN `len()`
    # (reported 0 for a real 1-char string) and dict-membership lookups
    # against it always missed, while the plain unpack's `pname` had a
    # correct `len()` and dict lookups worked. Do not "fix" this shape
    # to indexed access — that conversion is what's actually broken here.
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
        # A parameter some nested closure captures BY REFERENCE is declared
        # under a SECOND C name: the heap box (`_boxed_mut_locals`, seeded
        # from `_plan_mut_captured_params`) has to carry the source-level
        # name, because every read/write of it, and the env-field store
        # that hands it to the closure, resolve through `_cname(bare)`.
        param_strs.append(
            f"{ctype} {gen._mut_boxed_param_c[bare]}"
            if bare in gen._mut_boxed_param_c else f"{ctype} {safe_bare}")

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
    # doc/OWNERSHIP_MODEL.md Phase 3 codegen wiring (TODO item 1) — see
    # gimple_gen_infra.py's "Public entry points" section for the whole
    # feature; this file only ever calls in at these two points.
    ginf.begin_function(gen, node)
    for stmt in node.body:
        gen.gen_stmt(stmt)
    ginf.emit_fallthrough_frees(gen, node)

    # Add implicit return 0 for main if it returns int but has no explicit
    # return. Deliberately NOT `gen.body_lines[-1:]`/`gen.body_lines[-1]`
    # (negative slicing/indexing) — the established self-hosted trap for a
    # real accumulated MojoList (see this file's own `for pname, ptype in
    # node.params:` comment a few dozen lines up for the sibling
    # subscript-vs-plain-iteration version of the same trap): confirmed by
    # hand via lldb, `mojo_list_len(NULL)` crashed here for the minimal
    # repro `def main(): return 3` (this exact line's own `gen.body_lines
    # and gen.body_lines[-1]` truthiness/negative-index pair), reproduced
    # in isolation and bisected to this line specifically (a sibling
    # top-level function named anything other than `main`, or `main`
    # itself with no explicit `return`, both compiled fine — only a
    # `main` with a single explicit `return <value>` statement, so
    # `body_lines` has exactly one real entry, hit the crash). Length +
    # a plain, positive-index lookup is the established-safe replacement.
    if node.name == 'main' and ret_type in ('int', 'int64_t'):
        _n_body_lines = len(gen.body_lines)
        _last_body_line = gen.body_lines[_n_body_lines - 1] if _n_body_lines > 0 else ''
        if not _last_body_line.strip().startswith('return'):
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
    ginf.reset_no_candidates(gen)
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
    # Initialize this module's class-attribute defaults before ANY of its
    # top-level statements run. `_mojo_classattr_init` is emitted (and
    # forward-declared) exactly when this module emits struct definitions
    # (`emit_struct_defs`), so this is the one place guaranteed to both see
    # the definition and run before the first construction. Previously the
    # call lived only in `gen_func`'s `node.name == 'main' and
    # emit_struct_defs` branch — correct for a single-module program, but
    # `main` belongs to the ROOT module while the struct table (and hence
    # the init body) can live in an IMPORTED module whose TU has no `main`.
    # The binary's whole-program build lands in exactly that shape: one
    # `_mojo_classattr_init` is emitted, never called, so every class-attr
    # default stays NULL/0. Reproduced with `IntLiteral.raw: str = ''`
    # (the synthetic `s[byte=i]` index literal dumped `raw=None` instead
    # of `raw=''`); harmless for most defaults only because a NULL
    # list/dict renders as `[]`/`{}` anyway, but visible for `char *`.
    _cai_call = []
    if gen.emit_struct_defs:
        _cai_call.append("  _mojo_classattr_init ();")
    lines = [
        *_dep_init_lines,
        f"void {fn_name} (void)",
        "{",
        *gen.decls,
        "  static int _ran = 0;",
        "  if (_ran) return;",
        "  _ran = 1;",
        *_cai_call,
        *_dep_init_calls,
        *gen.body_lines,
        "}",
    ]

    return '\n'.join(lines)




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
        # NOT `isinstance(f.type_ann, str)`: VarDecl.type_ann is hardcoded
        # ambiguous `int64_t` in struct_field_types (struct_boxed_fields
        # includes it), and `mojo_isinstance`/`mojo_isinstance_p` never
        # answer True for type_id 4 (str) on an ambiguous boxed value --
        # see `_selfhost_ann_ctype`'s docstring for the full root-cause
        # writeup. `_as_str` is the zero-cost cast this codebase already
        # uses everywhere else for this exact "backend erased a real str
        # to int64_t" shape.
        _fann = _as_str(f.type_ann).strip() if f.type_ann is not None else ''
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
        # See `_selfhost_ann_ctype`'s docstring: VarDecl.type_ann is
        # ambiguous boxed int64_t, so `isinstance(f.type_ann, str)` is
        # unconditionally False self-hosted — use `is not None` + `_as_str`.
        if not isinstance(f, gimple_ctypes.VarDecl) or f.type_ann is None:
            continue
        _ann = _as_str(f.type_ann).strip()
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
        if not isinstance(f, gimple_ctypes.VarDecl) or f.type_ann is None:
            continue
        if fields.get(f.name) != 'MojoList *':
            continue
        _ann2 = _as_str(f.type_ann).strip()
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

    for st in stmts:
        if isinstance(st, gimple_ctypes.FunctionDef):
            _ris_collect(params_by_struct, st)
        elif isinstance(st, gimple_ctypes.StructDef):
            for m in st.methods:
                _ris_collect(params_by_struct, m)
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
            for _fip4 in (getattr(_ist, 'name_alias_strs', None) or []):
                _inm = gimple_ctypes._fi_name(_fip4)
                _ialias = gimple_ctypes._fi_alias(_fip4)
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
        for _fip5 in (getattr(st, 'name_alias_strs', None) or []):
            nm = gimple_ctypes._fi_name(_fip5)
            alias = gimple_ctypes._fi_alias(_fip5)
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
    never a guess). Memoized per (kind, module, name) in
    `gen._struct_home_cache`; the memo doubles as the cycle guard for
    re-export loops.

    The walk itself is `_find_symbol_home_module`
    (mojo/middle/funcs_shared.py), which the FREE-FUNCTION import
    qualifier needs too: "which module really defines this symbol" is one
    question, and the answer differs only in which kind of top-level
    definition counts. Two implementations of the same re-export walk
    would be two places for a cycle guard to be missing.
    """
    return _find_symbol_home_module(gen, module, name, 'struct', depth)







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






def _register_imported_generics(gen, stmts) -> None:
    """dylib mode: register `from M import gen` where gen is a generic free
    function (following re-export chains) so its call sites elaborate a
    concrete CAS-cached instantiation."""
    if gen.do_imports:
        return
    for st in stmts:
        if not (isinstance(st, gimple_ctypes.FromImportStmt) and not getattr(st, 'wildcard', False)):
            continue
        for _fip7 in (getattr(st, 'name_alias_strs', None) or []):
            nm = gimple_ctypes._fi_name(_fip7)
            alias = gimple_ctypes._fi_alias(_fip7)
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
        for _fip8 in (getattr(st, 'name_alias_strs', None) or []):
            nm = gimple_ctypes._fi_name(_fip8)
            alias = gimple_ctypes._fi_alias(_fip8)
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
    # Per-function, same reason and same placement as gen_func's.
    gen._inlined_lambdas = {}
    ginf.reset_no_candidates(gen)
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
    # `fire.py build .../Lib/glob.py` run (typing.py transitively
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
        # from a sliced self.<field> + `+=`, or the plain
        # `t = self.<field>; return t`) infers the real C return
        # type instead of int64_t — otherwise the definition's declared
        # return type disagrees with the body (which declares the local
        # correctly from _inferred_var_types) and every caller treats
        # the returned pointer as a scalar. COMPILE_FAIL_zipfile. The
        # rule is `gimple_ctypes._seedable_local_ctype`, shared by all three
        # call sites (not three private whitelists).
        _saved_lv = dict(gen.var_types)
        try:
            for _lvn, _lvt in gen._infer_local_var_types(node).items():
                if gimple_ctypes._seedable_local_ctype(_lvt):
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

    # See the free-function path's identical call: a by-reference capture
    # target among this method's parameters must be declared under a second
    # C name, and that has to be decided before `param_strs` is built.
    ginf._plan_mut_captured_params(gen, node, gen.current_func_name)

    method_full_name = f"{struct_name}_{node.name}"
    has_varargs = gimple_ctypes._params_have_vararg(node.params)
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
        # See the free-function path's identical branch: a by-reference
        # capture target is declared under a second C name so its heap box
        # can carry the source-level one.
        param_strs.append(
            f"{ctype} {gen._mut_boxed_param_c[bare]}"
            if bare in gen._mut_boxed_param_c else f"{ctype} {safe_bare}")

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
    # A method body is analyzed and freed exactly like a plain function's: its
    # locals are the same kind of local, `self` is a parameter (never a
    # candidate), and a store into `self.x` is an escape the analysis already
    # knows. The candidates computed here replace the empty set
    # `reset_no_candidates` left above.
    ginf.begin_function(gen, node)
    for stmt in node.body:
        gen.gen_stmt(stmt)
    ginf.emit_fallthrough_frees(gen, node)

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
