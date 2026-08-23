"""GimpleGen resolution: generics elaboration, imports/linking, closures, reset.

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

def _locally_bound_names(gen, body: list, params: list = None) -> set:
    """Names bound as a LOCAL variable anywhere in this statement list,
    PLUS every parameter name — mirrors real Python's own scoping rule
    that any assignment target (or parameter) anywhere in a function
    makes that name local for the WHOLE function (even before its
    first lexical assignment), unless `global NAME` is declared. Used
    by _reset_func's global-container seeding (_global_elem_types/
    _global_dict_val_types) to avoid treating a LOCAL variable or
    PARAMETER that happens to share a global container's bare name as
    if it were still that global — see bugs/hard/CODEGEN_reset_func_
    wipes_global_container_type_inference.md's shadowing edge case
    (two real, confirmed segfaults without this guard: a local
    `path_separators = [42, 43]` and a parameter `def f(path_
    separators):`, both inheriting the global `path_separators`'s
    seeded char* element type instead of their own real types).

    Does NOT recurse into nested FunctionDef/LambdaExpr bodies (their
    own separate scope) or comprehension targets (scoped to the
    comprehension itself in real Python 3, never leaking to the
    enclosing function — this compiler's own comprehension lowering
    doesn't leak the loop variable into the enclosing scope either)."""
    bound: set = set()
    global_declared: set = set()
    for pname, _ in (params or []):
        bound.add(pname.lstrip('*'))

    def _target_names(t):
        if isinstance(t, gimple_ctypes.IdentExpr):
            return [t.name]
        if isinstance(t, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr)):
            names = []
            for e in t.elements:
                names.extend(_target_names(e))
            return names
        return []

    def walk(nodes):
        for node in nodes or []:
            if isinstance(node, gimple_ctypes.GlobalStmt):
                global_declared.update(node.names)
            elif isinstance(node, gimple_ctypes.AssignStmt):
                bound.update(_target_names(node.target))
            elif isinstance(node, gimple_ctypes.MultiAssignStmt):
                for t in node.targets:
                    bound.update(_target_names(t))
            elif isinstance(node, gimple_ctypes.AugAssignStmt):
                bound.update(_target_names(node.target))
            elif isinstance(node, gimple_ctypes.VarDecl):
                bound.add(node.name)
            elif isinstance(node, gimple_ctypes.ForStmt):
                bound.update(_target_names(node.target))
                walk(node.body)
                if node.else_body:
                    walk(node.else_body)
            elif isinstance(node, gimple_ctypes.WhileStmt):
                walk(node.body)
                if node.else_body:
                    walk(node.else_body)
            elif isinstance(node, gimple_ctypes.IfStmt):
                walk(node.then_body)
                if node.else_body:
                    walk(node.else_body)
                for _, elif_body in (node.elifs or []):
                    walk(elif_body)
            elif isinstance(node, gimple_ctypes.TryStmt):
                walk(node.body)
                for h in (node.handlers or []):
                    walk(h.body)
                if node.else_body:
                    walk(node.else_body)
                if node.finally_body:
                    walk(node.finally_body)
            elif isinstance(node, gimple_ctypes.WithStmt):
                for item in (node.items or []):
                    if item.alias is not None:
                        bound.add(item.alias if isinstance(item.alias, str) else item.alias.name)
                walk(node.body)

    walk(body)
    return bound - global_declared


def _module_candidate_paths(gen, module_name: str) -> list:
    """Ordered candidate source-file paths for `module_name` (dotted or
    bare) — exactly the search-path/extension/dotted-package resolution
    logic `_compile_imported_module` uses to locate a `.py`/`.mojo`
    file, factored out so a caller that only needs to know WHETHER a
    module resolves to a real file (not compile it) reuses the exact
    same rules instead of re-implementing its own path-probing (see
    `_submodule_source_path`, used by `_gen_stmt_FromImportStmt` to
    distinguish a `from PKG import NAME` submodule from an ordinary
    symbol defined inside PKG's own source). Returns candidates in
    priority order; does not check existence — callers do that.
    """
    # Get the directory where gimple_codegen.py is located
    script_dir = gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(__file__))

    # Look for module relative to the IMPORTING FILE's own directory and
    # the CWD first; only fall back to script_dir (this repo's own
    # top-level tool scripts — mojo_compiler.py, elaborate.py, lexer.py,
    # parser.py, ast_nodes.py, ...) once neither has a match. This repo
    # ships several very generically-named top-level modules — of all
    # things, `parser.py` and `lexer.py` — because it IS a Mojo compiler.
    # Any external project that is itself compiler-adjacent (e.g. a
    # hand-written C++ parser in Mojo) is highly likely to define its own
    # same-named sibling module. Checking script_dir FIRST meant that
    # user module silently lost to this repo's unrelated same-named file
    # with no error — the user's real struct/fn definitions were never
    # even parsed, only whatever this repo's own file happened to define
    # under that name (see BUG-2026-014: `from parser import Parser`
    # resolved to gimple_codegen's own parser.py — which defines
    # TokenStream, not Parser at all — instead of the sibling
    # parser.mojo, and cross-module field access on the real Parser
    # struct failed because its fields were never registered).
    # Self-hosting the compiler on ITS OWN sources still works exactly as
    # before: those entry files (mojo.py, gimple_codegen.py, ...) already
    # live IN script_dir, so their "importing file's own directory" IS
    # script_dir — it's just no longer checked ahead of a closer, more
    # specific match for everyone else.
    # Within one location, try .py first (the working Python reference
    # implementations), then .mojo (self-hosting versions) — but LOCATION
    # is the outer, primary priority: a real match in a closer/more
    # specific directory must win over an unrelated same-named file
    # merely because that one happens to be .py. Getting this backwards
    # (extension as the outer loop) meant ANY .py match anywhere — even
    # this repo's own unrelated script_dir/parser.py — was found before
    # EVERY .mojo location was even attempted, script_dir included
    # (BUG-2026-014).  Skip the mojo/ subdirectory (those .mojo files are
    # stale and use syntax the parser can't handle).
    extensions = ['.py', '.mojo']
    importer_dir = None
    _importer = getattr(gen, '_current_filename', None)
    if _importer:
        importer_dir = gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(_importer))
    # Explicit `sys.path.insert(...)` directories win outright — the user
    # said "look here first" (see _record_sys_path_inserts) — then the
    # importing file's own directory, then CWD and its parent, and only
    # then this repo's own installation directory as a last resort.
    search_dirs = list(gen._extra_search_paths)
    if importer_dir:
        search_dirs.append(importer_dir)
    search_dirs += ['.', '..', script_dir]
    mojo_paths = []
    for d in search_dirs:
        for ext in extensions:
            mojo_paths.append(gimple_ctypes.os.path.join(d, f"{module_name}{ext}"))
    # A DOTTED module_name (e.g. `import pkg.helper as m`, module_name ==
    # "pkg.helper") names a package-relative path, not a literal
    # filename with dots in it — the loop above only ever tried the
    # (non-existent) literal "pkg.helper.mojo"/"pkg.helper.py", so it
    # silently found nothing for every dotted, non-std import and
    # returned (None, []) below. That made `_imported_func_home` never
    # get populated for the module's functions (Phase 0's caller, around
    # gen_module's find_imports loop, only registers it when `code` is
    # truthy), so a later call site that had bound the function to a
    # plain variable (`x = m.helper_add`) recomputed an unqualified
    # symbol (`__helper_add`) that nothing defines — the module was
    # simply never compiled/inlined at all (BUG-2026-049). Mirror the
    # interpreter's own dotted-import resolution here (see
    # myinterpreter.py's `rel_path = module_name.replace('.', os.sep) +
    # '.mojo'` / `rel_pkg_path` two lines below it): try BOTH the flat
    # "pkg/helper.mojo" form and the package "pkg/helper/__init__.mojo"
    # form, for every extension, in every search dir. Only applies to
    # genuinely dotted names — a plain "helper" is unaffected (no '.' to
    # split on), and "std.*" is already handled by its own dedicated
    # ModuleLoader path just below.
    if '.' in module_name:
        _dotted_parts = module_name.split('.')
        _rel_flat = gimple_ctypes.os.sep.join(_dotted_parts)
        _rel_pkg = gimple_ctypes.os.path.join(gimple_ctypes.os.sep.join(_dotted_parts), '__init__')
        for d in search_dirs:
            for ext in extensions:
                mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_flat}{ext}"))
                mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_pkg}{ext}"))
        # `from tkinter import commondialog` inside tkinter/filedialog.py
        # itself: module_name is "tkinter.commondialog", but the
        # IMPORTING file's own directory (in search_dirs) already IS
        # ".../tkinter" — appending the full dotted path there doubles
        # the package segment (".../tkinter/tkinter/commondialog.py",
        # which doesn't exist), so the loop above never finds it. If a
        # search dir's own trailing path component matches the dotted
        # name's LEADING component, also try the dotted path's
        # remaining suffix directly under that dir (treating the dir
        # as already representing that first package level). See
        # bugs/COMPILE_FAIL_tkinter_filedialog.md.
        if len(_dotted_parts) > 1:
            _suffix_parts = _dotted_parts[1:]
            _rel_suffix_flat = gimple_ctypes.os.sep.join(_suffix_parts)
            _rel_suffix_pkg = gimple_ctypes.os.path.join(gimple_ctypes.os.sep.join(_suffix_parts), '__init__')
            for d in search_dirs:
                if gimple_ctypes.os.path.basename(gimple_ctypes.os.path.normpath(d)) == _dotted_parts[0]:
                    for ext in extensions:
                        mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_suffix_flat}{ext}"))
                        mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_suffix_pkg}{ext}"))

    # Cross the import/module boundary into the real stdlib: resolve std.* modules
    # to their .mojo source under STDLIB_PATH so we walk into (and compile) the
    # actual library implementation rather than relying on a runtime/*.c stub.
    if module_name.startswith('std.') or module_name == 'std':
        try:
            from module_loader import ModuleLoader
            stdlib_file = ModuleLoader().resolve_module_path(module_name)
            if stdlib_file and gimple_ctypes.os.path.exists(stdlib_file):
                mojo_paths.append(stdlib_file)
        except Exception as e:
            gimple_ctypes._debug_note(f'stdlib path resolution failed for {module_name!r}', e)

    return mojo_paths


def _submodule_source_path(gen, module_name: str) -> str | None:
    """First existing file for dotted `module_name` on the same search
    path `_compile_imported_module` uses (`_module_candidate_paths`,
    reused rather than re-implemented) — checks EXISTENCE only, does
    not compile/parse anything. Used by `_gen_stmt_FromImportStmt` to
    tell whether `from PKG import NAME` binds a real submodule FILE
    (`PKG/NAME.py` or `PKG/NAME/__init__.py`) as opposed to an ordinary
    symbol defined inside PKG's own source."""
    for p in gen._module_candidate_paths(module_name):
        if gimple_ctypes.os.path.exists(p):
            return p
    return None


def _compile_imported_module(gen, module_name: str) -> tuple:
    """Find and compile an imported .mojo/.py module, extracting type
    information.

    Returns (code: str, stmts: list) where stmts are parsed statements from the module.
    """
    mojo_paths = gen._module_candidate_paths(module_name)
    for path in mojo_paths:
        if gimple_ctypes.os.path.exists(path):
            _abspath = gimple_ctypes.os.path.abspath(path)
            if _abspath in gen._compiling_file_paths:
                # This candidate resolves (by real file identity, not by
                # the module NAME being looked up) to a file already
                # being compiled somewhere in the current whole-program
                # closure — most commonly the ROOT file itself, reached
                # via a same-basename bare import real Python would have
                # resolved to a DIFFERENT top-level module (see
                # `_compiling_file_paths`'s own declaration for the full
                # importlib/abc.py story). Treat it exactly like real
                # Python treats a re-entrant import of a module already
                # mid-initialization: do NOT compile it again — skip this
                # candidate and keep trying the remaining search
                # locations, so a genuinely different, correctly-
                # resolvable module of the same bare name elsewhere on
                # the search path is still found.
                continue
            modules_before = set(gen._compiled_modules)
            ptr_helpers_before = set(gen._emitted_ptr_helpers)
            emitted_structs_before = set(gen._emitted_structs)
            inline_defs_before = set(gen._global_inline_defs)
            emitted_allocs_before = set(gen._emitted_allocs)
            gen._compiling_file_paths.add(_abspath)
            try:
                with open(path, 'r') as f:
                    source = f.read()
                # Any sys.path.insert(...) in THIS module's own source
                # extends the search path for modules IT imports too.
                gen._record_sys_path_inserts(source, gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(path)))

                # Compile the module to get both code and type info
                tokens = gimple_ctypes.py_tokenize(source)
                stmts = gimple_ctypes.ast_rewriter.rewrite(gimple_ctypes.Parser(tokens).parse_module())

                # Create a temporary codegen to extract types
                # Use do_imports=True for transitive closure; share dedup sets and type information
                # emit_str_pool=False so only main module emits the shared string pool
                # emit_struct_defs=False so only main module emits struct typedefs
                # emit_entry_points=False so imported module doesn't emit main/_gimple_main
                temp_gen = gimple_codegen.GimpleGen(do_imports=True, emit_str_pool=False, emit_struct_defs=False,
                                     emit_entry_points=False, module_name=module_name,
                                     relaxed_imports=True)
                temp_gen._current_filename = path  # Set filename for #line directives
                temp_gen._compiled_modules = gen._compiled_modules
                temp_gen._compiling_file_paths = gen._compiling_file_paths  # share: path-identity self-import guard (see its own declaration)
                temp_gen._asdict_dispatch_needed = gen._asdict_dispatch_needed  # share: __dict__/vars() usage flag (see its own declaration)
                temp_gen._emitted_structs = gen._emitted_structs
                temp_gen._struct_allocs_needed = gen._struct_allocs_needed  # share: reflection dispatch scoping (see gen_module) needs every allocated struct visible, not just the root module's own
                temp_gen._str_pool = gen._str_pool
                temp_gen._regex_patterns = gen._regex_patterns  # share: finditer() lowering (see BACKLOG-CODEGEN.md §4f)
                temp_gen._regex_progs = gen._regex_progs        # share: bubble compiled regex data up to root preamble
                temp_gen._regex_progs_defined = gen._regex_progs_defined  # share: avoid duplicate emission across recursive paths
                temp_gen._const_str_locals = gen._const_str_locals  # share: re.sub() compile-time pattern folding (see _try_const_fold_str)
                temp_gen.struct_field_types = gen.struct_field_types
                # share: a struct's home-module qualifier (_struct_method_qualifier)
                # must be visible to every ancestor gen's call sites, not just the
                # one that happened to first compile the struct's defining module —
                # a 3-level-deep import chain (root -> A -> B, where B defines the
                # struct and A merely re-uses it) previously registered the
                # qualifier only into the A-compiling temp_gen's own (unshared)
                # dict, so the root's own call sites on that struct independently
                # recomputed an unqualified symbol the defining module never
                # exports under (BUG-2026-032's arena.mojo/ast_nodes.mojo chain,
                # discovered once the direct 2-level case above was fixed).
                temp_gen._imported_struct_home = gen._imported_struct_home
                # share: same reasoning as _imported_struct_home just above,
                # for free functions (SB-1 fix, _func_qualifier) — a 3-level
                # chain must see a function's home qualifier no matter which
                # ancestor temp_gen first registered it.
                temp_gen._imported_func_home = gen._imported_func_home
                temp_gen._c_kw_struct_renames = gen._c_kw_struct_renames  # share: C-keyword struct-name renames (auto/enum.auto) must agree across modules
                temp_gen.struct_boxed_fields = gen.struct_boxed_fields
                temp_gen.struct_bool_fields = gen.struct_bool_fields
                temp_gen._struct_name_owner = gen._struct_name_owner  # share: cross-module same-name collision guard
                temp_gen._global_var_types = gen._global_var_types
                temp_gen._global_c_decl_types = gen._global_c_decl_types
                temp_gen._emitted_ptr_helpers = gen._emitted_ptr_helpers
                # share: a builtin-as-bare-value static (`_funcptr_mojo_make_dict`
                # etc.) must be declared at most once across the WHOLE transitive
                # closure, not once per submodule's own throwaway GimpleGen — see
                # _emitted_funcptr_builtins's docstring at its declaration.
                temp_gen._funcptr_builtins_needed = gen._funcptr_builtins_needed
                temp_gen._emitted_funcptr_builtins = gen._emitted_funcptr_builtins
                temp_gen._external_protos = gen._external_protos  # share: bubble extern protos up to root preamble
                temp_gen._global_inline_defs = gen._global_inline_defs
                temp_gen._emitted_allocs = gen._emitted_allocs
                temp_gen._module_stmts = gen._module_stmts  # share: track all transitive stmts
                # share: incrementally-maintained flat mirror of
                # _module_stmts' union (see PERF_nested_module_compile_
                # walk_ast_quadratic_rescan.md Phase 1) — same sharing
                # pattern as _module_stmts itself, just above.
                temp_gen._all_transitive_stmts_ordered = gen._all_transitive_stmts_ordered
                temp_gen._all_transitive_stmts_ids = gen._all_transitive_stmts_ids
                # share: Phase 2 per-statement field-access-scan caches
                # (see their own declaration next to
                # _all_transitive_stmts_ordered in __init__).
                temp_gen._field_scan_var_cache = gen._field_scan_var_cache
                temp_gen._field_scan_member_cache = gen._field_scan_member_cache
                # share: Phase 3 per-function param-usage-scan cache
                # (see its own declaration next to _field_scan_var_cache).
                temp_gen._param_usage_scan_cache = gen._param_usage_scan_cache
                # share: Phase 4 per-statement call-collection cache
                # (see its own declaration next to _param_usage_scan_cache).
                temp_gen._calls_in_stmts_cache = gen._calls_in_stmts_cache
                temp_gen._extra_search_paths = gen._extra_search_paths  # share: sys.path.insert dirs seen anywhere in the closure
                temp_gen.func_return_types = gen.func_return_types  # share across gens
                # share: `self._compiled_modules`-based dedup (line above,
                # `_compiled_modules`) means a module can be Pass1b-scanned
                # exactly ONCE, in whichever temp_gen happens to compile it
                # first — a later sibling/ancestor module that also imports
                # the same (already-compiled, dedup-skipped) class and calls
                # one of its @staticmethod/@classmethod methods would find
                # the mangled name in the (correctly, globally-shared)
                # `func_return_types` above but NOT in a fresh, per-temp_gen
                # `_static_methods`/`_classmethod_names` — silently
                # mis-classifying a real static/classmethod call at the
                # call-site gate in `_lower_call` (~line 13020). Must be
                # shared the same way `func_return_types` is, not left to
                # each temp_gen's own disposable copy.
                temp_gen._static_methods = gen._static_methods
                temp_gen._classmethod_names = gen._classmethod_names
                temp_gen._sub_toplevels = gen._sub_toplevels  # share the ordered list of sub-toplevels
                temp_gen._module_globals = gen._module_globals  # share module globals tracking
                temp_gen._module_global_inits = gen._module_global_inits  # share global inits
                if hasattr(gen, '_global_to_module'):
                    temp_gen._global_to_module = gen._global_to_module  # share global -> module mapping
                # share: async/generator API tables across modules so
                # cross-module async composition (await on an async fn
                # defined in another module) can resolve the callee's
                # API without failing (Phase 5).
                temp_gen._async_api = gen._async_api
                temp_gen._generator_api = gen._generator_api
                temp_gen._generator_method_api = gen._generator_method_api
                # share: link mode's own link-line accumulators
                # (dylibs/objects the final `mojo.py build` link step
                # needs — see compile_linked's own docstring) must be
                # visible to and mutated by EVERY nested temp_gen this
                # do_imports=True recursion spins up, not just the one
                # `self` happens to be at this particular nesting level
                # — a `_link_inline_modules`-fallback-compiled sibling
                # module (parsing.py) can itself `import` a further
                # sibling (lexer.py) that only THIS deeper temp_gen ever
                # sees; without sharing, anything that deeper temp_gen
                # adds to its own (fresh, per-instance) `_link_objects`/
                # `_link_needs_cxx_box` is invisible to the link_imports
                # =True ROOT `compile_linked` ultimately reads from (see
                # `_link_needs_cxx_box`'s own declaration for the fuller
                # story, and this method's own cpp-unit-compile call
                # site below for the concrete case that surfaced this —
                # bugs/COMPILE_FAIL_Tools_cases_generator_parser.md).
                # `_link_dylibs` shared for the identical reason (a
                # nested import's own further imports recording a
                # dylib). Harmless, unread dead data for a do_imports=
                # True-only (non-link) root build — nothing outside
                # `compile_linked` (always `link_imports=True`) ever
                # reads these three.
                temp_gen._link_objects = gen._link_objects
                temp_gen._link_dylibs = gen._link_dylibs
                temp_gen._link_needs_cxx_box = gen._link_needs_cxx_box
                code = temp_gen.gen_module(stmts)

                # Link mode's 4th coroutine-code source: a PLAIN (non-
                # generic) top-level generator/async function defined in
                # a transitively-imported SIBLING module (possibly
                # several `_compile_imported_module` levels deep — e.g.
                # parser.py -> parsing.py -> lexer.py, where `lexer` is
                # only ever reached via parsing.py's own `import lexer`,
                # not directly by the link_imports=True ROOT). compile_
                # linked's own docstring only ever documented 3 sources
                # of coroutine code to link (the root module's own
                # gen.generated_cpp, an elaborated generic's monomorphize
                # .instantiate cpp_object, dylib-resident stdlib
                # generators); this module's own `temp_gen.gen_module
                # (stmts)` call just above ALREADY independently computed
                # the correct self-contained C++ coroutine translation
                # unit for e.g. lexer.py's `tokenize()`
                # (temp_gen.generated_cpp, populated by the identical
                # "if self._generator_cpp_units:" preamble-assembly step
                # the root gen's own gen_module uses) -- it was simply
                # discarded here, returning only (code, stmts). That is
                # why parser.py's `.c` side always correctly REFERENCED
                # `_mojogen_lexer_tokenize_start/_resume/_value/_destroy`
                # (`_generator_api` is shared by reference with `self`,
                # a few lines up, so the call site sees the right
                # module-qualified base name -- `_func_qualifier` derives
                # it from temp_gen's own `module_name`, the SAME value
                # used to build the base name inside temp_gen.
                # generated_cpp itself, so the two sides always agree)
                # but nothing ever compiled or LINKED IN the actual
                # definition -- an undefined-symbol link failure, not a
                # compile error (see bugs/COMPILE_FAIL_Tools_cases_
                # generator_parser.md).
                #
                # Compile it into its own self-contained CAS-cached
                # object here, exactly like an elaborated generic's own
                # cpp_object (monomorphize.instantiate) gets compiled
                # and added onto the link line (_ensure_generic_struct /
                # _emit_generic_instantiation, above) -- same idea, a 4th
                # call site for it. `temp_gen.generated_cpp` is fully
                # self-contained (its own boilerplate/typedefs/extern
                # decls, assembled from temp_gen's own state), so
                # compiling it as its own separate translation unit
                # needs no merging with the root's own generated_cpp or
                # any other inline module's -- avoids the double-
                # compile/duplicate-symbol hazard a shared-TU merge
                # would risk.
                #
                # NOT gated on self.link_imports: `self` here can be an
                # intermediate do_imports=True-only temp_gen (compiling
                # parsing.py) rather than the link_imports=True ROOT —
                # `_link_objects`/`_link_needs_cxx_box`, shared by
                # reference all the way down from the root (see the
                # sharing block just above), are what actually carry
                # this to `compile_linked`, not the LOCAL truth of
                # `self.link_imports`/`self.do_imports` at whichever
                # nesting level happens to do the work. Unconditional,
                # mirroring `_ensure_generic_struct`/`_emit_generic_
                # instantiation`'s identical no-gating convention for
                # the exact same `_link_objects`/`_link_needs_cxx`
                # pair — a do_imports=True-only (non-link) ROOT build
                # never reads any of these back (see their own
                # declarations), so this is a harmless no-op there,
                # same as the existing generic-instantiation sites
                # already are for that pipeline.
                if temp_gen.generated_cpp:
                    _link_mod_cpp_obj = gen._compile_link_inline_cpp_unit(
                        temp_gen.generated_cpp)
                    if (_link_mod_cpp_obj is not None
                            and _link_mod_cpp_obj not in gen._link_objects):
                        gen._link_objects.append(_link_mod_cpp_obj)
                        gen._link_needs_cxx = True
                        gen._link_needs_cxx_box[0] = True

                # Store parsed stmts for this module so parent gens can access them
                gen._module_stmts[module_name] = stmts
                # Incrementally extend the flat, pre-deduped mirror (see
                # PERF_nested_module_compile_walk_ast_quadratic_rescan.md
                # Phase 1) — O(this module's own stmt count), done once
                # per module ever, instead of leaving every ancestor
                # level to re-flatten the whole (growing) _module_stmts
                # dict from scratch on its own way through gen_module.
                for _ts in stmts:
                    _tsid = id(_ts)
                    if _tsid not in gen._all_transitive_stmts_ids:
                        gen._all_transitive_stmts_ids.add(_tsid)
                        gen._all_transitive_stmts_ordered.append(_ts)

                # Return both code and parsed statements
                return (code, stmts)
            except Exception as e:
                __import__('sys').stderr.write(f"# ERROR: compiling imported module {module_name!r} from {path}: {e}\n")
                # Rollback: remove any modules/helpers/structs added during this failed
                # compilation so the outer module can re-compile them and include their code.
                for _m in list(gen._compiled_modules - modules_before):
                    gen._compiled_modules.discard(_m)
                for _h in list(gen._emitted_ptr_helpers - ptr_helpers_before):
                    gen._emitted_ptr_helpers.discard(_h)
                for _s in list(gen._emitted_structs - emitted_structs_before):
                    gen._emitted_structs.discard(_s)
                for _d in list(gen._global_inline_defs - inline_defs_before):
                    gen._global_inline_defs.discard(_d)
                for _a in list(gen._emitted_allocs - emitted_allocs_before):
                    gen._emitted_allocs.discard(_a)
                # Note: _module_globals / _module_global_inits are intentionally NOT
                # rolled back. Partial data from a failed compilation (e.g. build_stdlib_dylib
                # failing but having populated its globals) is still needed so that the
                # module's globals struct typedef can be emitted for callers that reference it.
                continue

    # Module not found (e.g. stdlib module like sys, os)
    return (None, [])


def _register_link_imports(gen, stmts) -> list:
    """Link mode (MODULE_CACHE_DESIGN.md): `import` is the seam. For each
    imported symbol, resolve its signature from the module's dylib
    `__mojo_reflect` ABI (imports.import_exports → read_reflection), register
    its return/param C types (so call sites lower correctly), and emit the
    `extern` declaration. Bodies are NOT inlined — they live in the linked
    dylib. Falls back to module_loader's source-level extraction when no dylib
    is available. Scans top-level and nested imports.
    """
    decls: list[str] = []
    seen: set[str] = set()

    def _param_ctypes(c_parameters):
        # c_parameters are like ["int64_t a", "char * s"]; keep the type only.
        out = []
        for cp in c_parameters or []:
            toks = cp.split()
            out.append(' '.join(toks[:-1]) if len(toks) > 1 else cp)
        return out

    def _parse_c_sig(sig):
        # "int64_t name (int64_t, char *)" -> ('int64_t', ['int64_t', 'char *'])
        head, _, rest = sig.partition('(')
        params = rest.rstrip(') ').strip()
        toks = head.strip().rsplit(None, 1)        # split off the function name
        ret = toks[0] if len(toks) == 2 else 'int'
        if not params or params == 'void':
            ptypes = []
        else:
            ptypes = [p.strip() for p in params.split(',')]
        return ret, ptypes

    def _exports(module):
        # `import` resolves the module's dylib, records it on the program's
        # link line (so the program links every dylib its imports resolved
        # through — the loader binds the symbols), and returns the reflection
        # ABI. Falls back to source-level extraction if no dylib is available.
        try:
            import imports as _imp
            entry = _imp.resolve(module)   # the one authoritative module per name
            if entry.dylib:
                if entry.exports and entry.dylib not in gen._link_dylibs:
                    gen._link_dylibs.append(entry.dylib)
                return entry.exports, True, entry.source
        except Exception as e:
            gimple_ctypes._debug_note(f'imports.resolve({module!r}) failed; falling back to load_module', e)
        # `source` was previously hardcoded to None on both fallback returns
        # below, which starved the caller's source-text-based generic/
        # overload detection (and, before this fix, the plain-struct case
        # entirely) of any source to read for modules imports.py's
        # MOJO_PATH-based resolver can't find — e.g. an ordinary sibling
        # .mojo file in a project with no dylib-building setup of its own
        # (mojolib's cpp_parser/, BUG-2026-032). _parsed_import already
        # does this resolution correctly (walking up from the current
        # file, same as _find_imported_struct/_resolve_test_relative_module).
        _sib_path = gen._parsed_import(module)[0]
        try:
            return gimple_ctypes.load_module(module), False, _sib_path
        except Exception as e:
            gimple_ctypes._debug_note(f'load_module({module!r}) failed; treating module as empty', e)
            return {}, False, _sib_path

    def scan(stmt_list):
        for stmt in stmt_list:
            if isinstance(stmt, gimple_ctypes.FromImportStmt):
                exports, from_reflection, source = _exports(stmt.module)
                for name, alias in stmt.names:
                    info = exports.get(name)
                    sym = alias if alias else name
                    # Record the module source for any imported name, so a
                    # comptime call to it can be evaluated at compile time.
                    if source:
                        gen._imported_fn_sources.setdefault(name, source)
                    if not info:
                        # Not a concrete export — if the module source defines
                        # it as a generic (struct or fn), record it for
                        # on-demand elaboration at use sites.
                        if source:
                            try:
                                msrc = open(source).read()
                            except Exception as e:
                                gimple_ctypes._debug_note(f'cannot read module source {source!r}', e)
                                msrc = ''
                            _found = False
                            if gimple_ctypes.re.search(rf'\bstruct\s+{gimple_ctypes.re.escape(name)}\s*\[', msrc):
                                gen._imported_generic_structs.setdefault(sym, source)
                                _found = True
                            elif gimple_ctypes.re.search(rf'\b(?:fn|def)\s+{gimple_ctypes.re.escape(name)}\s*\[', msrc):
                                gen._imported_generics.setdefault(sym, source)
                                _found = True
                            elif len(gimple_ctypes.re.findall(rf'\b(?:fn|def)\s+{gimple_ctypes.re.escape(name)}\s*\(', msrc)) > 1:
                                gen._imported_overloads.setdefault(sym, source)
                                _found = True
                            elif gimple_ctypes.re.search(rf'\bstruct\s+{gimple_ctypes.re.escape(name)}\s*(\(|:)', msrc):
                                gen._link_inline_modules.add(stmt.module)
                                _found = True
                            elif gimple_ctypes.re.search(rf'\b(?:fn|def)\s+{gimple_ctypes.re.escape(name)}\s*\(', msrc):
                                gen._link_inline_modules.add(stmt.module)
                                _found = True
                            # Package fallback: when the primary source is
                            # __init__.mojo and the name wasn't found there,
                            # search sibling .mojo files in the same package
                            # directory (common Mojo package pattern:
                            # __init__.mojo re-exports from sibling files
                            # like os.mojo, dict.mojo, etc.).
                            if not _found and source.endswith('__init__.mojo'):
                                _pkg_dir = gimple_ctypes.os.path.dirname(source)
                                _name_re = gimple_ctypes.re.escape(name)
                                if gimple_ctypes.os.path.isdir(_pkg_dir):
                                    for _sf in sorted(gimple_ctypes.os.listdir(_pkg_dir)):
                                        if (not _sf.endswith('.mojo')
                                                or _sf == '__init__.mojo'):
                                            continue
                                        _sibling = gimple_ctypes.os.path.join(_pkg_dir, _sf)
                                        try:
                                            _smsrc = open(_sibling).read()
                                        except Exception:
                                            continue
                                        if gimple_ctypes.re.search(rf'\bstruct\s+{_name_re}\s*\[', _smsrc):
                                            gen._imported_generic_structs.setdefault(sym, _sibling)
                                            _found = True
                                            break
                                        elif gimple_ctypes.re.search(rf'\b(?:fn|def)\s+{_name_re}\s*\[', _smsrc):
                                            gen._imported_generics.setdefault(sym, _sibling)
                                            _found = True
                                            break
                                        elif len(gimple_ctypes.re.findall(rf'\b(?:fn|def)\s+{_name_re}\s*\(', _smsrc)) > 1:
                                            gen._imported_overloads.setdefault(sym, _sibling)
                                            _found = True
                                            break
                                        elif gimple_ctypes.re.search(rf'\bstruct\s+{_name_re}\s*(\(|:)', _smsrc):
                                            gen._link_inline_modules.add(stmt.module)
                                            _found = True
                                            break
                                        elif gimple_ctypes.re.search(rf'\b(?:fn|def)\s+{_name_re}\s*\(', _smsrc):
                                            gen._link_inline_modules.add(stmt.module)
                                            _found = True
                                            break
                        continue
                    if sym in seen:
                        continue
                    # A concrete struct TYPE import (kind 3, MOJO_SYM_TYPE):
                    # materialize its layout from the reflection table and
                    # register its methods (kind 1) as externs. This is the
                    # real-stdlib distribution path — the type + method bodies
                    # live in the compiled dylib; the client sees only the
                    # layout + extern method symbols (not inlined source).
                    if from_reflection and info.get('kind') == 3:
                        seen.add(sym)
                        gen._register_reflected_struct(
                            sym, info, exports, _parse_c_sig)
                        continue
                    sig = info.get('signature')
                    if not sig:
                        continue
                    seen.add(sym)
                    if from_reflection:
                        ret, ptypes = _parse_c_sig(sig)
                    else:
                        ret = info.get('c_return_type', 'int64_t')
                        ptypes = _param_ctypes(info.get('c_parameters'))
                    gen.func_return_types[sym] = ret
                    gen.func_param_types[sym] = ptypes
                    # Record this function's home module (SB-1 fix,
                    # _func_qualifier) so this call site's _func_csym
                    # computes the SAME module-qualified symbol the
                    # defining module's own compile actually emits —
                    # mirrors _register_reflected_struct's
                    # _imported_struct_home bookkeeping for structs.
                    # `source` is the resolved file path from _exports
                    # above (populated whether or not a dylib exists).
                    if source:
                        import module_loader as _mlmod
                        _qual = _mlmod.module_name_for_path(source)
                        if _qual:
                            # _own_imported_func_home (per-instance): see
                            # its own comment — this module's own import
                            # must win over any other module's claim on
                            # the same bare name.
                            # record_scope=False: scan() also recurses into
                            # function BODIES (its own scan handler below),
                            # and those nested imports must NOT land in the
                            # module scope — the correct lexical scope for
                            # them is the function's own, populated when
                            # the body is generated by _gen_stmt_FromImport
                            # Stmt / the body pre-scan. Top-level imports
                            # are also recorded into the module scope by
                            # _emit_stdlib_import_externs, which always
                            # runs, so nothing is lost here.
                            gen._note_own_func_home(sym, _qual, record_scope=False)
                    # Don't emit extern if: (a) locally defined in this module
                    # (would conflict), or (b) it's a C stdlib symbol GCC already
                    # declares (conflicting types when Mojo stub has different sig).
                    _locally_defined = sym in gen._global_inline_defs
                    _is_c_builtin = sym in gen._LIBC_DECLARED
                    if not _is_c_builtin:
                        # This imported Mojo function is overload-mangled by the
                        # defining module; the importer must mangle calls + its
                        # extern identically. Same param types (from the exported
                        # signature) ⇒ same suffix as the definition.
                        gen._mangled_funcs.add(sym)
                    if not _locally_defined and not _is_c_builtin:
                        _csym = gen._func_csym(sym)
                        decls.append(
                            f"extern {ret} {_csym} ({', '.join(ptypes) if ptypes else 'void'});")
            elif isinstance(stmt, gimple_ctypes.FunctionDef):
                scan(stmt.body)
            elif isinstance(stmt, gimple_ctypes.IfStmt):
                scan(stmt.then_body)
                for _, eb in stmt.elifs:
                    scan(eb)
                if stmt.else_body:
                    scan(stmt.else_body)
            elif isinstance(stmt, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt, gimple_ctypes.TryStmt)):
                scan(stmt.body)

    scan(stmts)
    return decls


def _register_reflected_struct(gen, name, type_info, exports, parse_c_sig):
    """Materialize a concrete struct imported from a dylib's reflection table.

    `type_info` is the MOJO_SYM_TYPE entry (signature = a layout descriptor
    `struct Name { ctype field; ... }`); `exports` is the full reflection
    dict, from which we pick the struct's MOJO_SYM_METHOD entries
    (`Name.method`). We register the layout (so the typedef is emitted),
    declare each method extern, and record their return/param C types so call
    sites lower to the dylib's symbols. This is the import path a real,
    already-compiled stdlib type takes: only layout + externs cross the
    boundary — the bodies are linked from the dylib (see ABI.md, ELABORATION.md
    which complements this with the from-source generic-struct path)."""
    # Parse the layout descriptor into {field: ctype}, preserving order.
    sig = type_info.get('signature', '')
    fields: dict[str, str] = {}
    inner = sig.split('{', 1)[1].rsplit('}', 1)[0] if '{' in sig else ''
    for decl in inner.split(';'):
        decl = decl.strip()
        if not decl:
            continue
        parts = decl.rsplit(' ', 1)
        if len(parts) == 2:
            ctype, fname = parts[0].strip(), parts[1].strip()
            fields[fname] = ctype
    if not gen.struct_field_types.get(name):
        gen.struct_field_types[name] = fields
    # Register each method (kind 1) belonging to this struct.
    for ename, einfo in exports.items():
        if einfo.get('kind') != 1 or not ename.startswith(name + '.'):
            continue
        msig = einfo.get('signature', '')
        if not msig:
            continue
        mret, mptypes = parse_c_sig(msig)
        # The C symbol is the function name inside the signature — this is
        # whatever the defining module's own compile actually emitted
        # (see GimpleGen._struct_method_csym_static / reflect.py's
        # collect_exports), i.e. already module-qualified if that module
        # had a real module_name. Record the qualifier (if any) into
        # _imported_struct_home so a CALL SITE on this struct
        # (_struct_method_qualifier / _struct_method_csym) derives the
        # exact same qualified symbol reflect.py already declared here —
        # otherwise the call site would independently recompute an
        # UNQUALIFIED name (Counter has no local source file to run
        # module_name_for_path on) and reference a symbol the dylib never
        # defines under that name.
        method_name = ename.split('.', 1)[1]
        _bare_prefix = f"{name}_{gimple_ctypes._safe_name(method_name)}"
        msym = msig.split('(', 1)[0].strip().split()[-1].lstrip('*')
        if msym.startswith(_bare_prefix):
            qualifier = ''
        else:
            qualifier, sep, _rest = msym.partition(f"_{_bare_prefix}")
            if not sep:
                qualifier = ''  # unrecognized shape; assume unqualified
        if qualifier:
            gen._imported_struct_home.setdefault(name, qualifier)
        gen.func_return_types[msym] = mret
        gen.func_param_types[msym] = mptypes
        bare_init = f"{name}___init__"
        if msym == bare_init or (qualifier and msym == f"{qualifier}_{bare_init}"):
            gen._struct_has_init.add(name)
            # The C signature gives no param names; record positional
            # placeholders so a kwarg ctor binds by source order (below).
            gen._struct_init_params.setdefault(name, [])
        decl = f'extern {msig};'
        if decl not in gen._elaborated_externs:
            gen._elaborated_externs.append(decl)


def _new_temp(gen, ctype: str) -> str:
    gen.temp_counter += 1
    name = f"_t{gen.temp_counter}"
    gen.decls.append(f"  {gimple_ctypes._c_var_decl(ctype, name)};")
    gen.var_types[name] = ctype
    return name


def _new_val(gen, ctype: str, rhs: str) -> str:
    """Alloc a GIMPLE temp, emit `t = rhs`, return t."""
    t = gen._new_temp(ctype)
    # GIMPLE strict mode: a bare integer literal (e.g. `0`) is typed
    # plain 'int' by the C frontend; assigning it to a temp declared
    # with any OTHER scalar type without an explicit cast is a
    # 'non-trivial conversion in integer_cst' error. 'int64_t' was the
    # only case handled here historically; '_Bool' has the identical
    # gap — confirmed via a real repro (`_new_val('_Bool', '0')`, used
    # by `_isinstance_one_type`'s `isinstance(x, type)`-always-False
    # stub and the `isinstance(x, (A, B, ...))` OR-accumulator seed)
    # producing "_Bool / int / _tN = 0;" on Lib/typing.py's
    # `_BaseGenericAlias.__mro_entries__`/`_GenericAlias._make_
    # substitution` (~22 occurrences in a `mojo.py build
    # Lib/subprocess.py` run) — GCC's C frontend does NOT apply the
    # usual implicit int->_Bool conversion under `-fgimple`'s stricter
    # verifier, same as it doesn't for int->int64_t. Both need the
    # explicit cast.
    if ctype in ('int64_t', '_Bool') and rhs.lstrip('-').isdigit():
        if rhs.startswith('-'):
            # A cast applied directly to a NEGATIVE literal
            # (`(int64_t)-1`, or even parenthesized: `(int64_t)(-1)`)
            # is rejected by a `__GIMPLE`-tagged function's STRICT
            # raw-GIMPLE parser ("expected expression before '-'/'('
            # token") — unlike an ordinary (non-`__GIMPLE`) C function,
            # which GCC itself lowers to GIMPLE and so tolerates normal
            # C expression syntax, a `__GIMPLE` function's body must
            # already BE valid GIMPLE: one operation per statement, no
            # literal directly following a cast when that literal is
            # negative. Real Mojo source `-1` (parsed as UnaryOp('-',
            # IntLiteral(1)), see _lower_UnaryOp) already produces
            # exactly this safe two-step shape — cast the POSITIVE
            # magnitude into its own temp first (valid: a cast of a
            # non-negative literal is fine), then negate that TEMP
            # (NEGATE_EXPR on an SSA name, not a literal, is always
            # valid GIMPLE) — mirror it here so a negative literal
            # reaching `_new_val` some other way (e.g. a folded
            # comptime int constant) gets the same safe lowering.
            # Found via a negative top-level `comptime` constant (e.g.
            # `comptime _InvalidTypeIndex: Int = -1`) read inside a
            # `__GIMPLE`-tagged struct method — see test_gimple.py's
            # "toplevel_comptime_const_visible_everywhere".
            mag = gen._new_temp(ctype)
            gen._emit(f'  {mag} = ({ctype}){rhs[1:]};')
            gen._emit(f'  {t} = -{mag};')
        else:
            gen._emit(f'  {t} = ({ctype}){rhs};')
    else:
        gen._emit(f'  {t} = {rhs};')
    return t


def _call_expr(gen, ret_type: str, fname: str, arg_pairs: list) -> str:
    """Emit a call and return the result temp."""
    t = gen._new_temp(ret_type)
    gen._emit_call(ret_type, t, fname, arg_pairs)
    return t


def _void_call(gen, fname: str, arg_pairs: list) -> tuple:
    """Emit a void call, return ('int', zero_temp)."""
    gen._emit_call('void', '', fname, arg_pairs)
    return 'int', gen._new_val('int', '0')


def _emit_label(gen, label: str, freq_hint: str = ''):
    ann = f'  /* {freq_hint} */' if freq_hint else ''
    gen.body_lines.append(f"\n{label}:{ann}")
    gen._last_was_terminal = False


def _strided_data_ptr(gen, pt: str, pv: str) -> str:
    """An `int64_t *` to the scalar data for a strided op's pointer operand —
    `self->address` for an UnsafePointer struct, else the raw pointer itself.
    (int→ptr goes through void* in two single casts; GIMPLE rejects a double
    cast in one statement.)"""
    sn = gimple_exprtypes._struct_name_of(pt)
    if sn and 'address' in (gen.struct_field_types.get(sn) or {}):
        addr = gen._new_val('int64_t', f"{pv}->address")
        vp = gen._new_val('void *', f"(void *){addr}")
        return gen._new_val('int64_t *', f"(int64_t *){vp}")
    if pt == 'int64_t *':
        return gen._ensure_local(pt, pv)
    if pt.endswith(' *'):
        return gen._new_val('int64_t *', f"(int64_t *){gen._ensure_local(pt, pv)}")
    loc = gen._ensure_local('int64_t', pv)
    vp = gen._new_val('void *', f"(void *){loc}")
    return gen._new_val('int64_t *', f"(int64_t *){vp}")


def _safe_coerce_emit(gen, src: str, dst: str, val: str, lhs: str) -> None:
    """Emit `lhs = val` coercing src→dst; routes struct-field LHS and literal RHS
    through register temps as required by GIMPLE."""

    # A dot-accessed struct member (e.g. a non-pointer module-globals
    # instance's own field, `_typing_globals.some_field`) needs the exact
    # same "coerce into a register temp first" treatment as an arrow-
    # accessed one: `-fgimple` rejects a cast expression's result being
    # stored directly through EITHER a COMPONENT_REF shape (`.` or `->`
    # are both COMPONENT_REF at the GIMPLE level, just through a value
    # vs. pointer base) — only checking for `->` here left every plain
    # dot-accessed struct-field LHS requiring a cast (e.g. a module
    # global whose declared C type is a struct pointer, assigned an
    # int64_t-boxed source value) emitting an invalid single combined
    # cast+store statement ("non-register as LHS of unary operation").
    # A bare C identifier (local var/temp name) never itself contains a
    # `.`, so this is unambiguous. Found via typing.py's `_lazy_
    # annotationlib` global (`global _lazy_annotationlib; ...;
    # _lazy_annotationlib = annotationlib` inside `_LazyAnnotationLib.
    # __getattr__`) once its write target was fixed to correctly resolve
    # to `_typing_globals._lazy_annotationlib` (see the module-context
    # fix in _gen_struct_method/_gen_lifted_closure) — this dot-access
    # gap was previously unreachable for that write because it hard-
    # failed even earlier (an entirely undeclared struct member) before
    # ever reaching -fgimple verification.
    is_field = '->' in lhs or '.' in lhs
    # A dereferenced pointer lvalue (`*name`, e.g. a `{mut}`-capture-
    # spec's heap-boxed local -- see _seed_mut_captured_local_types)
    # needs the exact same "coerce into a register temp first, then a
    # plain (no embedded cast) store" treatment as a struct-field LHS:
    # `-fgimple` rejects a cast expression's result being stored
    # directly through an INDIRECT_REF just as it rejects one through
    # a COMPONENT_REF (confirmed via a hand-reduced repro: `*count =
    # (int64_t)0;` is invalid GIMPLE, `t = (int64_t)0; *count = t;`
    # is not).
    is_deref = lhs.startswith('*')
    val_is_literal = val.startswith('"') or val.startswith("'") or (
        val.lstrip('-').replace('.','',1).isdigit())  # All numeric strings including single digits
    needs_temp = is_field or is_deref

    def _simple_emit(dest: str, v: str, s: str, d: str):
        # GIMPLE: integer constant assigned to int64_t/_Bool needs explicit cast
        if s == d:
            if d == 'int64_t' and v.lstrip('-').isdigit():
                gen._emit(f'  {dest} = (int64_t){v};')
            elif d == '_Bool' and v.lstrip('-').isdigit():
                gen._emit(f'  {dest} = (_Bool){v};')
            else:
                # Same C type, but the value's *declared* type may still be
                # wider than this same-typed slot (an int64_t ABI param
                # assigned into a uint8_t local) — GIMPLE rejects the
                # implicit conversion, so cast explicitly.
                declared = gen._declared_int_ctype(v)
                if declared is not None and declared != s and s in gimple_ctypes._SCALAR_INT_TYPES:
                    gen._emit(f'  {dest} = ({s}){v};')
                else:
                    gen._emit(f'  {dest} = {v};')
        elif s.endswith(' *') and d in ('int', 'int64_t'):
            # Load global into local before casting (GIMPLE restriction)
            v = gen._ensure_local(s, v)
            # GIMPLE: non-void pointer → int64_t requires void * intermediate
            if s != 'void *':
                vp = gen._new_val('void *', f'(void *){v}')
                v = vp
            ip = gen._new_val('int64_t', f'(int64_t){v}')
            if d == 'int64_t':
                gen._emit(f'  {dest} = {ip};')
            else:
                gen._emit(f'  {dest} = (int){ip};')
        elif d == 'char *' and s == 'char':
            # A Python str of length 1 (a bare `char` in this codegen)
            # coerced into a `char *` STRING slot — e.g. the `char`
            # branch of a mixed-type ternary like `s[k-1] if k>0 else ''`
            # (one branch a single char, the other a real string), or a
            # char stored into a char*-typed field/variable. Build a real
            # 1-char heap string via mojo_char_to_str. The `(char *){v}`
            # cast the generic narrow-scalar branch below would apply
            # instead reinterprets the char's BYTE VALUE as a pointer
            # address (e.g. '_' → (char *)0x5f), which then segfaults the
            # instant anything dereferences it (strcmp/mojo_cstr_cmp/...).
            # Found via mojo_compiler.py's own
            # `prev = src[k-1] if k>0 else ''` followed by `prev == '_'`
            # crashing the self-hosted `--dump` — the last 2/152
            # mojo.tok/.ast divergence in `make bootstrap` (a real
            # SIGSEGV, not just a mistokenization, once the surrounding
            # prefix-scan loop actually advanced far enough to reach a
            # non-empty `prev`).
            v = gen._ensure_local(s, v)
            sv = gen._call_expr('char *', 'mojo_char_to_str', [('char', v)])
            gen._emit(f'  {dest} = {sv};')
        elif d.endswith(' *') and s in ('int', 'int64_t', 'char'):
            # 'char' here too: a narrower-than-pointer scalar (e.g. a
            # single dereferenced byte from an unresolved generic
            # element access) cast directly to a pointer type is the
            # same -Wint-to-pointer-cast size mismatch as 'int' — widen
            # through int64_t first, same as the other narrow sources.
            v = gen._ensure_local(s, v)
            ip = gen._new_val('int64_t', f'(int64_t){v}')
            gen._emit(f'  {dest} = ({d}){ip};')
        else:
            # GIMPLE: a cast operand must be a local, never a global decl
            # (e.g. a _slit_ string literal). Load it first.
            v = gen._ensure_local(s, v)
            gen._emit(f'  {dest} = ({d}){v};')

    if needs_temp:
        t = gen._new_temp(dst)
        _simple_emit(t, val, src, dst)
        gen._emit(f'  {lhs} = {t};')
    else:
        _simple_emit(lhs, val, src, dst)


def _cname(gen, name: str) -> str:
    """Translate a Python variable name to its C name (handles C keyword renaming)."""
    return gen._c_names.get(name, name)


def _closure_value_locals(gen, body: list) -> dict:
    """Map local name → 'MojoBoundMethod *'/'void *' for the locals of a
    function body that are assigned a nested-function (closure) VALUE
    (`var f = inner`, `f = inner`), resolved from the closure's capture
    shape (a capturing closure is a MojoBoundMethod*, a non-capturing
    one a bare function pointer — see _lower_IdentExpr's closure-value
    materialization). Used to seed return-type inference so it can see
    through a local alias (`def make_both(): var f = inner; return f`),
    which `_infer_local_var_types` can't (that pass never scans VarDecl
    and runs before `_all_closures` is populated)."""
    result: dict = {}

    def _walk(stmts: list):
        for st in stmts:
            tgt = None
            val = None
            if isinstance(st, gimple_ctypes.AssignStmt) and isinstance(st.target, gimple_ctypes.IdentExpr):
                tgt = st.target.name
                val = st.value
            elif (isinstance(st, gimple_ctypes.VarDecl) and isinstance(st.name, str)
                    and ',' not in st.name and st.value is not None):
                tgt = st.name
                val = st.value
            if tgt is not None and tgt not in result and isinstance(val, gimple_ctypes.IdentExpr):
                _ci = gen._closure_info_for_ident(val.name)
                if _ci is not None:
                    result[tgt] = 'MojoBoundMethod *' if _ci.env_struct else 'void *'
            if isinstance(st, gimple_ctypes.FunctionDef):
                continue
            for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                sub = getattr(st, attr, None)
                if isinstance(sub, list):
                    _walk(sub)
            for _eb_cond, _eb_body in (getattr(st, 'elifs', None) or []):
                _walk(_eb_body)
            for _h in (getattr(st, 'handlers', None) or []):
                hb = getattr(_h, 'body', None)
                if isinstance(hb, list):
                    _walk(hb)

    _walk(body)
    return result


def _quick_type(gen, node) -> str:
    """Estimate C type of an expression without emitting code."""
    if isinstance(node, gimple_ctypes.IntLiteral):    return 'int64_t'
    if isinstance(node, gimple_ctypes.FloatLiteral):  return 'double'
    if isinstance(node, gimple_ctypes.BoolLiteral):   return '_Bool'
    if isinstance(node, gimple_ctypes.StringLiteral): return 'char *'
    if isinstance(node, gimple_ctypes.IdentExpr):
        if node.name in gen.var_types:
            return gen.var_types[node.name]
        # A nested-function (closure) name referenced as a VALUE
        # (`return add`, `var f = add`, `foo(add)`) — a capturing
        # closure bundles its env with the lifted function pointer as a
        # `MojoBoundMethod *` (see _lower_IdentExpr's closure-value
        # materialization); a non-capturing one is a bare function
        # pointer. Recognized here so return-type inference
        # (`def make_adder(...): return add`) and call-site var typing
        # (`var add5 = make_adder(5)`) see the real value shape instead
        # of the int64_t default (which made `return add` return NULL).
        _ci = gen._closure_info_for_ident(node.name)
        if _ci is not None:
            return 'MojoBoundMethod *' if _ci.env_struct else 'void *'
        return 'int64_t'
    if isinstance(node, gimple_ctypes.BinaryOp):
        # 'in'/'not in' are missing from _CMP_OPS (generated_dispatch.py) —
        # real, pre-existing gap: falling through to
        # TypeLattice.join(type(left), type(right)) for e.g.
        # `dump = '--dump' in sys.argv` joins 'char *' (the string
        # literal) with whatever sys.argv itself quick-types to, giving
        # 'char *' instead of '_Bool'. The variable then gets declared
        # char* while every value stored in it is really a 0/1 _Bool bit
        # pattern; `if dump:`'s char*-truthiness coercion
        # (_ensure_bool_cond -> mojo_truthy_cstr) dereferences that
        # bit pattern as a pointer — a real crash for `dump = True`
        # (address 0x1). Found chasing self-hosted mojo.py evaluating
        # its own `dump = '--dump' in sys.argv`.
        # _CMP_OPS (generated_dispatch.py) also contains 'and'/'or' —
        # correct for the STATEMENT-condition dispatch table it's really
        # meant for, wrong here: real Python `and`/`or` return whichever
        # OPERAND was selected (see the _lower_BinaryOp fix), never a bare
        # bool. Treating them as _Bool here mis-typed cas.py's own
        # `GMOJO_HOME = os.environ.get(...) or os.path.expanduser(...)`
        # global as `_Bool`: the real string value computed at runtime then
        # got cast down to a 0/1 bit pattern when stored into that
        # (wrongly-typed) global, and the next read (os.path.join(GMOJO_HOME,
        # 'cas')) dereferenced it as a pointer — a real crash at address 0x1.
        if node.op in ('and', 'or'):
            lt = gen._quick_type(node.left)
            rt = gen._quick_type(node.right)
            return gimple_ctypes.TypeLattice.join(lt, rt)
        if node.op in gimple_ctypes._CMP_OPS or node.op in ('in', 'not in'): return '_Bool'
        lt = gen._quick_type(node.left)
        rt = gen._quick_type(node.right)
        return gimple_ctypes.TypeLattice.join(lt, rt)
    if isinstance(node, gimple_ctypes.CompareChain):
        # Same as any single comparison above: a chained comparison
        # (`a < b < c`) always yields a bool, regardless of the operand
        # types being compared.
        return '_Bool'
    if isinstance(node, gimple_ctypes.UnaryOp):
        if node.op == 'not': return '_Bool'
        return gen._quick_type(node.operand)
    if isinstance(node, gimple_ctypes.TernaryExpr):
        return gimple_ctypes.TypeLattice.join(gen._quick_type(node.then_val),
                                gen._quick_type(node.else_val))
    if isinstance(node, gimple_ctypes.CallExpr) and isinstance(node.func, gimple_ctypes.IdentExpr):
        fname: str
        fname = node.func.name
        _BUILTIN_CTORS = {'set': 'MojoSet *', 'dict': 'MojoDict *', 'list': 'MojoList *'}
        # Same `_locally_binds_name` gate as `_BUILTIN_SCALARS` just
        # below — `set`/`dict`/`list` are ordinary identifiers a module
        # could shadow with its own top-level def/import.
        if fname in _BUILTIN_CTORS and not gen._locally_binds_name(fname):
            return _BUILTIN_CTORS[fname]
        # Scalar builtins, matching the lowering (float()->double, etc.). Without
        # these, [float(i), ...] infers an int element type and nested float
        # lists silently read/return as int.
        _BUILTIN_SCALARS = {'float': 'double', 'int': 'int64_t', 'str': 'char *',
                            'len': 'int64_t', 'ord': 'int64_t', 'chr': 'char *',
                            'bool': '_Bool', 'repr': 'char *',
                            # isinstance()/all()/any() always return a plain
                            # Python bool regardless of their arguments' types
                            # (same "no argument-type inspection needed"
                            # reasoning as len/ord above) — without this,
                            # `return isinstance(...)`/`return all(...)`/
                            # `return any(...)` fell through to the int64_t
                            # default below. Real emission (_lower_builtin_
                            # isinstance/_lower_builtin_all_any) actually
                            # produces a C `int`, but declaring the more
                            # precise `_Bool` here still matches every other
                            # boolean-producing case above (BinaryOp compare/
                            # 'in', CompareChain, UnaryOp 'not', BoolLiteral)
                            # and avoids joining as an opaque int64_t/pointer
                            # against a sibling return path of a real pointer
                            # type (see bugs/hard/CODEGEN_comprehension_
                            # return_type_defaults_int64.md's follow-up note).
                            'isinstance': '_Bool', 'all': '_Bool', 'any': '_Bool'}
        # `all`/`any`/`isinstance` (and in principle any other name in
        # this table) are ordinary identifiers a module can legally
        # shadow with its own top-level def — e.g. tokenize.py's own
        # `def any(*choices): return group(*choices) + '*'`, called as
        # `any(pattern)` inside `Ignore = Whitespace + any(...) +
        # maybe(...)`. Without this gate, a call to the LOCAL `any`
        # quick-typed to `_Bool` (the builtin's return type) instead of
        # the real `char *`, so the surrounding `+` joined 'char *' with
        # '_Bool' and produced a bogus type ("invalid use of void
        # expression" downstream) instead of the correct 'char *'.
        # Mirrors the `open` builtin-shadowing gate at this class's
        # `_lower_builtin_all_any` call site — same `_locally_binds_name`
        # mechanism, see its docstring.
        if fname in _BUILTIN_SCALARS and not gen._locally_binds_name(fname):
            return _BUILTIN_SCALARS[fname]
        if fname in gen.struct_field_types:
            return f'{fname} *'
        # A bare call to a KNOWN COMPILED GENERATOR function (Milestone
        # B/C, self._generator_api) returns an opaque MojoGenerator* —
        # calling the generator function only CONSTRUCTS the coroutine,
        # it doesn't run the body (real Python/Mojo "calling a generator
        # function returns a generator object" semantics), so this must
        # be checked before the generic func_return_types fallback below
        # (a generator function was never given an ordinary return type
        # entry there — see bugs/CODEGEN_compiled_generator_not_first_
        # class_value.md). This dict is only fully populated after
        # gen_module's Pass 1.3d-gen eligibility loop runs (deliberately
        # AFTER Pass 1.3b/1.3d, per that loop's own ordering note) —
        # Pass 1.3b's FIRST call into this method (for a generator call
        # site) still sees it empty and falls through to the int64_t
        # default below, same as any other call to a not-yet-registered
        # callee; Pass 1.3f's unconditional full rerun of local-variable-
        # type inference (after the eligibility loop has populated
        # _generator_api) is what actually corrects `g = counter(3)`'s
        # inferred type, mirroring the exact same "corrective rerun"
        # pattern Pass 1.3e/1.3f already use for a plain unannotated-
        # callee return-type correction.
        if fname in gen._generator_api:
            return 'MojoGenerator *'
        return gen.func_return_types.get(fname, 'int64_t')
    if isinstance(node, gimple_ctypes.CallExpr) and isinstance(node.func, gimple_ctypes.MemberExpr):
        # .read()/.readline()/.readlines() on ANY receiver shape (not just
        # a plain IdentExpr file handle) — e.g. `sys.stdin.read()` (obj is
        # itself a MemberExpr) or `open(path).read()` (obj is a CallExpr).
        # The IdentExpr-only checks below never match these chained
        # shapes, so this must come first and be receiver-shape-agnostic.
        if node.func.member in ('read', 'readline') and not node.args:
            return 'char *'
        if node.func.member == 'readlines':
            return 'MojoList *'
        # Module method calls: re.sub → char *, str.join → char *, etc.
        if isinstance(node.func.obj, gimple_ctypes.IdentExpr):
            mod: str
            mod = node.func.obj.name
            meth: str
            meth = node.func.member
            # file_handle.read()/.readline(): this pre-pass runs before
            # any real var_types are populated (it's the upfront scan
            # that *produces* them), so `ot = self.var_types.get(mod, '')`
            # below is always empty for a `with open(...) as f:` handle
            # at this point — falls through to the int64_t default,
            # regardless of what `mod` actually is. Real bug found via
            # `with open(input_file) as f: src = f.read()` in mojo.py's
            # own main(): `src` got declared int64_t while every value
            # written to it was really a char* pointer to the file
            # content, so len(src) and print(src) both read it as a
            # raw integer instead of the string.
            if meth in ('read', 'readline') and not node.args:
                return 'char *'
            if meth == 'readlines':
                return 'MojoList *'
            # Unambiguous string-only methods: in this codebase's Python
            # subset, these are only ever called on real strings — return
            # char* regardless of whether the receiver's own type is known
            # yet (this pre-pass runs before var_types is populated, so
            # `ot` below is empty here for a not-yet-declared local, same
            # blind spot as the .read()/.readline() case above). Missing
            # this made e.g. `expanded = line.expandtabs(N)` infer
            # `expanded` as int64_t; a later `len(expanded)` then treated
            # the real char* as a boxed MojoList* pointer, reading garbage
            # struct fields as the string's "length" — the real source of
            # `_strip_inline_comment`-style tokenizer stack corruption
            # (a huge garbage `indent` value). Found via py_tokenize's own
            # `expanded = line.expandtabs(_INDENT_SIZE)`.
            if meth in ('expandtabs', 'lstrip', 'rstrip', 'strip', 'lower',
                        'upper', 'title', 'capitalize', 'swapcase',
                        'replace', 'format', 'zfill', 'center', 'ljust', 'rjust',
                        'encode', 'decode', 'join', 'group'):
                return 'char *'
            if mod == 're' and meth == 'sub':    return 'char *'
            if mod == 're' and meth == 'match':  return 'int'
            if mod == 're' and meth == 'search': return 'int'
            if mod == 'os' and meth in ('getcwd', 'path'): return 'char *'
            if mod == 'sysconfig' and meth == 'get_config_var': return 'char *'
            if mod == 'sys': return 'int'
            # dict.keys()/.values()/.items(): _lower_dict_method (below)
            # lowers all three to a real `MojoList *` (mojo_dict_keys/
            # _values/_items) — but this pre-pass had no case for them at
            # all. Unlike the string-only methods just above, gating this
            # on `self.var_types.get(mod)` doesn't work: this pre-pass
            # (_collect_return_types/_infer_return_type, Pass 2b) runs
            # BEFORE a function's own LOCAL variable types are known —
            # `modules = {}` earlier in the SAME function body being
            # scanned hasn't been recorded into var_types yet at this
            # point (same blind spot the .read()/.readline() note above
            # already documents for `with open(...) as f:`). Treated the
            # same way as the "Unambiguous string-only methods" block
            # just above instead: `.keys`/`.values`/`.items` are
            # dict-view-only method NAMES in this codebase's supported
            # subset (no other builtin container type has them), so
            # unconditionally returning MojoList* here is safe by the
            # same reasoning that block already uses. Real:
            # Lib/modulefinder.py's `find_all_submodules` has an early
            # bare `return` (None) followed by `return modules.keys()`;
            # the wrong int64_t forward-declaration against a body that
            # actually returns a MojoList* pointer produced GCC's honest
            # `-fgimple` refusal ("invalid conversion in return
            # statement"). See CODEGEN_generator_function_Lib_
            # modulefinder.md.
            if meth in ('keys', 'values', 'items') and not node.args:
                return 'MojoList *'
            # Try as struct instance method call: resolve receiver type then look up mangled name
            ot = gen.var_types.get(mod, '')
            if ot and ot.endswith(' *'):
                sn = gimple_exprtypes._struct_name_of(ot)
                # obj.method(...) where `method` is a supported compiled
                # GENERATOR method (Milestone C step 3,
                # self._generator_method_api) — same "returns
                # MojoGenerator*, doesn't run the body" reasoning as the
                # free-function generator case above, checked before the
                # ordinary mangled-name func_return_types lookup below (a
                # generator method has no such ordinary entry either).
                if (sn, meth) in gen._generator_method_api:
                    return 'MojoGenerator *'
                mangled = f"{sn}_{meth}"
                rt = gen.func_return_types.get(mangled)
                if rt:
                    return rt
        # os.path.basename(...)/.splitext(...)/etc.: node.func.obj here is
        # itself a MemberExpr (os.path), not a plain IdentExpr, so the
        # `mod == 'os'` branch above never matches this chained shape at
        # all — this pre-pass had no case for it whatsoever. Mirrors the
        # real lowering (the os.path.* block in lower_expr): basename/
        # expanduser return char*, splitext returns a 2-element char*
        # list. Real bug found via
        # `os.path.splitext(os.path.basename(input_file))[0]` in mojo.py's
        # build_executable: the parameter fix above still left this local
        # variable declared int64_t (a real char* pointer value shown as
        # a raw address by print()).
        elif (isinstance(node.func.obj, gimple_ctypes.MemberExpr)
                and isinstance(node.func.obj.obj, gimple_ctypes.IdentExpr)
                and node.func.obj.obj.name == 'os' and node.func.obj.member == 'path'):
            if node.func.member in ('basename', 'expanduser'):
                return 'char *'
            if node.func.member == 'splitext':
                return 'MojoList *'
        # Chained string methods, e.g. `s.replace(a, b).replace(c, d)` —
        # the receiver here is itself a CallExpr (the inner .replace()),
        # not a plain IdentExpr, so the `isinstance(node.func.obj,
        # IdentExpr)` branch above never matches this shape at all. Same
        # class of gap as the os.path.* chained case just above: without
        # this, format_token()'s `tok.value.replace(...).replace(...)`
        # (mojo_compiler.py's own tokenizer dump helper) declared its
        # result int64_t, corrupting the pointer on every read.
        if (node.func.member in ('expandtabs', 'lstrip', 'rstrip', 'strip', 'lower',
                    'upper', 'title', 'capitalize', 'swapcase',
                    'replace', 'format', 'zfill', 'center', 'ljust', 'rjust',
                    'encode', 'decode', 'join')
                and gen._quick_type(node.func.obj) == 'char *'):
            return 'char *'
    if isinstance(node, gimple_ctypes.MemberExpr):
        ot: str
        ot = gen._quick_type(node.obj)
        sn: str
        sn = gimple_exprtypes._struct_name_of(ot)
        _fields = gen.struct_field_types.get(sn, {})
        if node.member in _fields:
            return _fields[node.member]
        # `node.member` isn't a real FIELD on this struct — it may be a
        # bound METHOD/`@property` read without call syntax (`self.
        # filename.parent`, `filename` a 0-arg method/property). Real
        # codegen (_lower_MemberExpr's object-lowering path) auto-
        # invokes such a value before doing the outer member lookup —
        # this static type-guessing pre-pass (used by _infer_return_
        # type/_collect_return_types to pick a function's own C return
        # type from its `return` statements) must mirror that or a
        # `return self.prop.attr`-shaped return silently defaulted to
        # int64_t against a body that actually returns a real pointer:
        # the compiled function's OWN declared C return type disagreed
        # with what its body computed (the `.attr` field read itself
        # was already correct — only the enclosing function's
        # signature was wrong). Same struct-method detection
        # `_lower_MemberExpr` itself already uses to recognize "this
        # member is a bound-method value, not a field" (see that
        # method's `_lower_bound_method_value` call site). See bugs/
        # COMPILE_FAIL_zipfile__path___init__.md.
        if sn and (f"{sn}_{node.member}" in gen.func_return_types
                   or (sn, node.member) in gen._struct_method_signatures):
            candidates = gen._struct_method_signatures.get((sn, node.member))
            overload_id = ''
            if candidates and len(candidates) == 1:
                overload_id = candidates[0].get('overload_id', '') or ''
            mangled = gen._struct_method_csym(sn, node.member, overload_id)
            return gen.func_return_types.get(
                mangled, gen.func_return_types.get(f"{sn}_{node.member}", 'int64_t'))
        return 'int64_t'
    if isinstance(node, gimple_ctypes.ListExpr):  return 'MojoList *'
    if isinstance(node, gimple_ctypes.DictExpr):  return 'MojoDict *'
    if isinstance(node, gimple_ctypes.SetExpr):   return 'MojoSet *'
    if isinstance(node, gimple_ctypes.TupleExpr): return 'MojoList *'
    if isinstance(node, gimple_ctypes.Comprehension):
        # `[x for x in y]`/`{k: v for ...}`/`{x for x in y}`/a
        # generator-expression — a distinct AST node from the literal
        # ListExpr/DictExpr/SetExpr cases just above (mojo_compiler.py),
        # which this method had NO case for at all: falling through to
        # the int64_t default at the bottom of this method while the
        # REAL emission (_lower_comprehension, below) constructs and
        # returns a real MojoList*/MojoDict*/MojoSet* pointer. For a
        # function whose SOLE `return` is a bare comprehension (real:
        # Lib/calendar.py's Calendar.monthdatescalendar and 5 sibling
        # methods), this method is what populates the function's
        # forward-declared return type (_collect_return_types) — a
        # wrong int64_t declaration there, against a body that actually
        # constructs/returns a pointer, produces GCC's honest
        # `-fgimple` refusal ("non-trivial conversion in
        # 'integer_cst'"/"type mismatch in binary expression"). Mirrors
        # _lower_comprehension's own kind->type mapping exactly (a
        # generator-expression is converted to a MojoList* there too,
        # per that method's own "convert to list for simplicity"
        # comment) rather than inventing a second, possibly-diverging
        # mapping — an unrecognized kind falls to the SAME int64_t
        # default this method already used for every other
        # unmatched/unsupported node shape (matching
        # _lower_comprehension's own TODO-kind fallback, which emits a
        # plain scalar 0, not a pointer). See
        # CODEGEN_comprehension_return_type_defaults_int64.md.
        if node.kind == 'dict':
            return 'MojoDict *'
        if node.kind == 'set':
            return 'MojoSet *'
        if node.kind in ('list', 'generator'):
            return 'MojoList *'
        return 'int64_t'
    # A slice's type is the type of the object being sliced (mirrors _lower_slice:
    # list slice -> list, str slice -> str, plain pointer -> same pointer).
    if isinstance(node, gimple_ctypes.SliceExpr): return gen._quick_type(node.obj)
    if isinstance(node, gimple_ctypes.SubscriptExpr):
        # container[idx]: result is the container's element type, read from the
        # same side-tables the subscript lowering uses. Covers nested reads
        # (outer[i][j]) via the container's nested element type.
        obj = node.obj
        # sys.argv[i]: a real MojoList * of strings (mojo_get_argv(), see
        # the `sys`/`argv` MemberExpr lowering), but `obj` here is a
        # MemberExpr, not a tracked IdentExpr — this pre-pass had no case
        # for it at all, so it fell through to the int64_t default below.
        # Real bug found via `input_file = sys.argv[1]` in mojo.py's own
        # build command handling: the variable got declared int64_t while
        # every value stored in it was actually a char* pointer (same
        # bit pattern, so no crash — just wrong for any later use, e.g.
        # print() showing a raw address instead of the string).
        if (isinstance(obj, gimple_ctypes.MemberExpr) and isinstance(obj.obj, gimple_ctypes.IdentExpr)
                and obj.obj.name == 'sys' and obj.member == 'argv'):
            return 'char *'
        # os.path.splitext(...)[0]: the CallExpr case above returns
        # 'MojoList *' for splitext's own type, but this needs the
        # *element* type for the subscript — always char* (root, ext),
        # for any index. Same os.path.* blind spot as above.
        if (isinstance(obj, gimple_ctypes.CallExpr) and isinstance(obj.func, gimple_ctypes.MemberExpr)
                and isinstance(obj.func.obj, gimple_ctypes.MemberExpr)
                and isinstance(obj.func.obj.obj, gimple_ctypes.IdentExpr)
                and obj.func.obj.obj.name == 'os' and obj.func.obj.member == 'path'
                and obj.func.member == 'splitext'):
            return 'char *'
        if isinstance(obj, gimple_ctypes.IdentExpr):
            e = gen._elem_types.get(obj.name)
            if e:
                return e
        elif isinstance(obj, gimple_ctypes.SubscriptExpr) and isinstance(obj.obj, gimple_ctypes.IdentExpr):
            ne = gen._nested_elem_types.get(obj.obj.name)
            if ne:
                return ne
    return 'int64_t'


def _infer_list_elem_type(gen, elements: list) -> str:
    """Determine element C type for a list/set/tuple literal."""
    if not elements:
        return 'int64_t'
    # Explicit loop (NOT a comprehension): the self-hosted compiler has no
    # lowering for `[f(x) for x in lst]` over a runtime MojoList (the
    # comprehension emits a no-op, leaving `types` NULL -> join_all(NULL)
    # segfault). List comprehension lowering only works for a small
    # hardcoded set of shapes.
    types = []
    for _e in elements:
        types.append(gen._quick_type(_e))
    return gimple_ctypes.TypeLattice.join_all(types) if types else 'int64_t'


def _prepass_callee_key(gen, node) -> str | None:
    """Symbol key of a CallExpr's callee for the pre-pass's
    _return_elem_types lookup — mirrors the bare {struct}_{method}
    mangling the call sites and _gen_struct_method's current_func_name
    both use ('self' resolves to the struct being pre-passed)."""
    f = node.func
    if isinstance(f, gimple_ctypes.IdentExpr):
        return f.name
    if isinstance(f, gimple_ctypes.MemberExpr) and isinstance(f.obj, gimple_ctypes.IdentExpr) and f.obj.name == 'self':
        if gen._prepass_struct:
            return f"{gen._prepass_struct}_{f.member}"
    return None


def _collect_local_container_elems(gen, stmts) -> None:
    """Populate self._prepass_local_elems from a function's assignments:
    a named local holding a container literal / container-returning call,
    or both halves of a `xt, xv = <container-returning call>` unpack."""
    for node in stmts:
        if isinstance(node, gimple_ctypes.AssignStmt):
            t, v = node.target, node.value
            if isinstance(t, gimple_ctypes.IdentExpr):
                e = gen._quick_container_elem(v)
                if e is not None:
                    gen._prepass_local_elems[t.name] = e
            elif isinstance(t, gimple_ctypes.TupleExpr):
                # `xt, xv = <container-returning call>` — a tuple is
                # homogeneous at the C level, so both targets get the
                # container's element type. A literal RHS assigns each
                # element with its own type (skip).
                if not isinstance(v, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr)):
                    e = gen._quick_container_elem(v)
                    if e is not None:
                        for sub in t.elements:
                            if isinstance(sub, gimple_ctypes.IdentExpr):
                                gen._prepass_local_elems[sub.name] = e
        elif isinstance(node, gimple_ctypes.VarDecl):
            if (isinstance(node.name, str) and ',' not in node.name
                    and node.value is not None):
                e = gen._quick_container_elem(node.value)
                if e is not None:
                    gen._prepass_local_elems[node.name] = e
        elif isinstance(node, gimple_ctypes.IfStmt):
            gen._collect_local_container_elems(node.then_body)
            for _, eb in node.elifs:
                gen._collect_local_container_elems(eb)
            if node.else_body:
                gen._collect_local_container_elems(node.else_body)
        elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            gen._collect_local_container_elems(node.body)
        elif isinstance(node, gimple_ctypes.TryStmt):
            gen._collect_local_container_elems(node.body)
            for h in node.handlers:
                gen._collect_local_container_elems(h.body)
            if node.else_body:
                gen._collect_local_container_elems(node.else_body)
            if node.finally_body:
                gen._collect_local_container_elems(node.finally_body)
        elif isinstance(node, gimple_ctypes.WithStmt):
            gen._collect_local_container_elems(node.body)


def _collect_return_elems(gen, stmts, acc) -> None:
    """Collect container element types of return values (structural walk
    mirroring _collect_return_types)."""
    for node in stmts:
        if isinstance(node, gimple_ctypes.ReturnStmt):
            if node.value is not None:
                e = gen._quick_container_elem(node.value)
                if e is not None:
                    acc.append(e)
        elif isinstance(node, gimple_ctypes.IfStmt):
            gen._collect_return_elems(node.then_body, acc)
            for _, eb in node.elifs:
                gen._collect_return_elems(eb, acc)
            if node.else_body:
                gen._collect_return_elems(node.else_body, acc)
        elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            gen._collect_return_elems(node.body, acc)
        elif isinstance(node, gimple_ctypes.TryStmt):
            gen._collect_return_elems(node.body, acc)
            for h in node.handlers:
                gen._collect_return_elems(h.body, acc)
            if node.else_body:
                gen._collect_return_elems(node.else_body, acc)
            if node.finally_body:
                gen._collect_return_elems(node.finally_body, acc)
        elif isinstance(node, gimple_ctypes.WithStmt):
            gen._collect_return_elems(node.body, acc)


KNOWN_LEAF_RETS = {'_mojo_type': 'char *'}


def _infer_return_elem_type(gen, body, func_def=None,
                            _base_var_types=None) -> str | None:
    """Infer the container ELEMENT type a function returns, or None when it
    returns no statically-identifiable container. See _quick_container_elem.

    HERMETIC: runs against a snapshot of the shared type-scratch maps
    (var_types/_elem_types/_dict_val_types/_actual_types) so scanning one
    function's body can neither poison nor be poisoned by the scratch left
    behind by the previously-scanned function in Pass 2c's whole-program
    loop. Before this was hermetic, whatever function happened to be
    scanned just before (module processing order varies with the closure
    import graph) leaked its var_types into this scan and mis-typed unrelated
    callees' tuple returns as int64_t (comptime.py's `ret, params =
    _signature(...)` unpacked params as int64_t -> mojo_strlen(int))."""
    # CLEAN-SLATE scan: derive every fact from THIS body alone. Ambient
    # var_types/_elem_types carry other functions' locals (often common
    # names like 'params'/'ret' typed int64_t), which poisoned tuple-return
    # element inference depending on module processing order.
    _saved = (gen.var_types, gen._elem_types, gen._dict_val_types,
              gen._actual_types, getattr(gen, '_prepass_struct', None))
    # Phase 4 (bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
    # rescan.md): the per-call seed used to be built by iterating the
    # ENTIRE tree-shared `func_return_types` dict one setdefault at a
    # time — O(|func_return_types|) interpreted work on EVERY call, and
    # Pass 2c calls this once per function per fixpoint iteration per
    # nesting level (275k calls × ~1800 entries ≈ 500M setdefaults for
    # Lib/contextlib.py). `func_return_types` is provably frozen for the
    # duration of one Pass 2c run (its loop touches only bodies via this
    # scan and writes only `self._return_elem_types`; nothing reachable
    # from here registers return types), so the caller may hoist ONE
    # snapshot of it per run and hand it in as `_base_var_types` — each
    # call then copies that snapshot at C speed instead of re-seeding
    # entry-by-entry. Content is identical either way; when no snapshot
    # is supplied the legacy path below still seeds from
    # gen.func_return_types directly.
    gen.var_types = dict(_base_var_types) if _base_var_types is not None else {}
    # Seed with facts that are TRUE regardless of processing order: this
    # function's own annotated params, every registered cross-function
    # return type (imported externs + Pass-2a inferred), and the fixed
    # return types of leaf helpers exported by gimple_ctypes.
    if func_def is not None:
        for pname, ptype in (func_def.params or []):
            gen.var_types[pname] = (gimple_ctypes._mojo_type(ptype)
                                    if ptype else 'int64_t')
    if _base_var_types is None:
        for k, v in gen.func_return_types.items():
            gen.var_types.setdefault(k, v)
    for k, v in KNOWN_LEAF_RETS.items():
        gen.var_types.setdefault(k, v)
    gen._elem_types = dict(_saved[1])   # container elem types stay visible
    gen._dict_val_types = {}
    gen._actual_types = dict(_saved[3])
    gen._prepass_local_elems = {}
    # Scalar assignment seeding: `ret = _mojo_type(...)` — record the
    # callee's registered return type for simple Ident targets so the
    # ReturnStmt element walk can type non-container locals. Container
    # locals are handled by _collect_local_container_elems above.
    def _seed_scalar_assigns(nodes):
        for nd in nodes:
            if isinstance(nd, gimple_ctypes.AssignStmt) \
                    and isinstance(nd.target, gimple_ctypes.IdentExpr) \
                    and isinstance(nd.value, gimple_ctypes.CallExpr):
                callee = getattr(nd.value.func, 'name', None)
                if callee and nd.target.name not in gen.var_types:
                    rt = gen.func_return_types.get(callee)
                    if rt is None and callee in ('_mojo_type', '_c_escape', '_safe_name'):
                        rt = 'char *'
                    if rt:
                        gen.var_types[nd.target.name] = rt
            elif isinstance(nd, gimple_ctypes.IfStmt):
                _seed_scalar_assigns(nd.then_body)
                for _, eb in (getattr(nd, 'elifs', None) or []):
                    _seed_scalar_assigns(eb)
                if nd.else_body:
                    _seed_scalar_assigns(nd.else_body)
            elif isinstance(nd, (gimple_ctypes.ForStmt, gimple_ctypes.WhileStmt)):
                _seed_scalar_assigns(nd.body)
            elif isinstance(nd, gimple_ctypes.TryStmt):
                _seed_scalar_assigns(nd.body)
                for h in nd.handlers:
                    _seed_scalar_assigns(h.body)
            elif isinstance(nd, gimple_ctypes.WithStmt):
                _seed_scalar_assigns(nd.body)

    try:
        _seed_scalar_assigns(body)
        gen._collect_local_container_elems(body)
        acc = []
        gen._collect_return_elems(body, acc)
        if not acc:
            return None
        return gimple_ctypes.TypeLattice.join_all(acc)
    finally:
        gen.var_types, gen._elem_types, gen._dict_val_types, \
            gen._actual_types, _ps = _saved
        gen._prepass_struct = _ps


def _infer_local_var_types(gen, func: gimple_ctypes.FunctionDef) -> dict[str, str]:
    """Infer local variable types from all assignments in function body.

    Scans all assignments to determine the variable's actual type needs.
    Returns dict mapping var_name → inferred_ctype.
    """
    inferred = {}

    # This pre-pass runs before self.var_types is populated for this
    # function, so _quick_type(IdentExpr(param_name)) falls through to its
    # int64_t default for every parameter reference — e.g. `prefix, rest =
    # raw[:prefix_len], raw[prefix_len:]` (Parser._strip_string_prefix_and_
    # quotes) inferred `rest` as int64_t instead of `char *` even though
    # `raw: str` is explicitly annotated, because `_quick_type(SliceExpr)`
    # resolves through `_quick_type(node.obj)` = `_quick_type(IdentExpr
    # ('raw'))`, which found no var_types entry. `rest` then got compiled
    # as a plain int64_t, so `rest[1:-1]` fell into _lower_slice's
    # generic "raw pointer, no bounds check" fallback instead of calling
    # mojo_cstr_slice — silently keeping every extra byte past the
    # (ignored) stop bound. Seed the annotated parameter types into
    # var_types just for this scan (saved/restored below) so identifier
    # lookups inside it resolve correctly.
    _saved_var_types = gen.var_types
    gen.var_types = dict(_saved_var_types)
    for pname, ptype in (func.params or []):
        if pname not in gen.var_types and ptype:
            gen.var_types[pname] = gimple_ctypes._mojo_type(ptype)

    def collect_assigned_types(nodes: list):
        """Recursively scan statements and collect types assigned to variables."""
        for node in nodes:
            if isinstance(node, gimple_ctypes.AssignStmt):
                # Use _quick_type instead of lower_expr to avoid incomplete var_types
                if isinstance(node.target, gimple_ctypes.TupleExpr):
                    targets = node.target.elements
                    # Type each unpack target by its own value, never by the
                    # whole RHS: _quick_type(a_tuple) is 'MojoList *', which would
                    # wrongly poison scalar unpack targets (e.g. start, stop, step
                    # = ivals[0], ivals[1], ivals[2]).
                    if (isinstance(node.value, gimple_ctypes.TupleExpr)
                            and len(node.value.elements) == len(targets)):
                        elem_types = [gen._quick_type(e) for e in node.value.elements]
                    else:
                        # Unpacking a single iterable: per-element type is unknown
                        # here; use the int64_t storage default, not the container.
                        elem_types = ['int64_t'] * len(targets)
                else:
                    targets = [node.target]
                    elem_types = [gen._quick_type(node.value)]
                for target, vtype in zip(targets, elem_types):
                    if isinstance(target, gimple_ctypes.IdentExpr):
                        vname = target.name
                        if vname not in inferred:
                            inferred[vname] = []
                        inferred[vname].append(vtype)
            elif isinstance(node, gimple_ctypes.MultiAssignStmt):
                # `a = b = ... = expr` (chained assignment): every target
                # receives the SAME value/type (real Python chained-
                # assignment semantics), unlike AssignStmt's TupleExpr
                # unpack case above. Was entirely unhandled here — every
                # target of a chained assignment fell through to this
                # scan's int64_t default regardless of the RHS's real
                # type. See bugs/hard/CODEGEN_multi_assign_local_var_
                # type_not_inferred.md.
                vtype = gen._quick_type(node.value)
                for target in node.targets:
                    if isinstance(target, gimple_ctypes.IdentExpr):
                        vname = target.name
                        if vname not in inferred:
                            inferred[vname] = []
                        inferred[vname].append(vtype)
            elif isinstance(node, gimple_ctypes.IfStmt):
                collect_assigned_types(node.then_body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
                for _, elif_body in node.elifs:
                    collect_assigned_types(elif_body)
            elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
                collect_assigned_types(node.body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
            elif isinstance(node, gimple_ctypes.TryStmt):
                collect_assigned_types(node.body)
                for h in node.handlers:
                    collect_assigned_types(h.body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
                if node.finally_body:
                    collect_assigned_types(node.finally_body)
            elif isinstance(node, gimple_ctypes.WithStmt):
                collect_assigned_types(node.body)
            elif isinstance(node, gimple_ctypes.ExprStmt) and isinstance(node.value, gimple_ctypes.WalrusExpr):
                # `name := expr` used as a bare statement (e.g. `r :=
                # ShapedRecipe()`) parses as an ExprStmt wrapping a
                # WalrusExpr, NOT an AssignStmt -- unlike a walrus used
                # inside a larger expression, this shape was invisible
                # to this scan entirely, so a local first bound only via
                # a statement-level `:=` (never a plain `=`) never got an
                # inferred type here. See box.3d/game/bugs/DYLIB_struct_
                # list_index_reads_first_field_only_wrong_craft_results.md.
                vname = node.value.name
                if vname not in inferred:
                    inferred[vname] = []
                inferred[vname].append(gen._quick_type(node.value.value))

    try:
        collect_assigned_types(func.body)
    finally:
        gen.var_types = _saved_var_types

    # Join all types for each variable using TypeLattice
    result = {}
    for vname, types in inferred.items():
        if types:
            result[vname] = gimple_ctypes.TypeLattice.join_all(types)

    return result


def _collect_calls(gen, expr, out):
    """Append every CallExpr in an expression tree to out. A method (not a
    nested function) so it never goes through the closure-lift machinery."""
    if expr is None:
        return
    if isinstance(expr, gimple_ctypes.StringLiteral):
        for sub in gen._fstring_sub_exprs(expr):
            gen._collect_calls(sub, out)
    elif isinstance(expr, gimple_ctypes.CallExpr):
        out.append(expr)
        gen._collect_calls(expr.func, out)
        for a in expr.args:
            gen._collect_calls(a, out)
        for _k, kv in (getattr(expr, 'kwargs', None) or []):
            gen._collect_calls(kv, out)
    elif isinstance(expr, gimple_ctypes.BinaryOp):
        gen._collect_calls(expr.left, out); gen._collect_calls(expr.right, out)
    elif isinstance(expr, gimple_ctypes.CompareChain):
        for o in expr.operands:
            gen._collect_calls(o, out)
    elif isinstance(expr, gimple_ctypes.UnaryOp):
        gen._collect_calls(expr.operand, out)
    elif isinstance(expr, gimple_ctypes.SubscriptExpr):
        gen._collect_calls(expr.obj, out); gen._collect_calls(expr.index, out)
    elif isinstance(expr, gimple_ctypes.SliceExpr):
        gen._collect_calls(expr.obj, out); gen._collect_calls(expr.start, out); gen._collect_calls(expr.stop, out)
    elif isinstance(expr, gimple_ctypes.MemberExpr):
        gen._collect_calls(expr.obj, out)
    elif isinstance(expr, gimple_ctypes.TernaryExpr):
        gen._collect_calls(expr.condition, out); gen._collect_calls(expr.then_val, out); gen._collect_calls(expr.else_val, out)
    elif isinstance(expr, (gimple_ctypes.ListExpr, gimple_ctypes.SetExpr, gimple_ctypes.TupleExpr)):
        for x in expr.elements:
            gen._collect_calls(x, out)
    elif isinstance(expr, gimple_ctypes.DictExpr):
        for dk, dv in expr.pairs:
            gen._collect_calls(dk, out); gen._collect_calls(dv, out)


def _calls_in_stmts(gen, stmts, out):
    """Collect every CallExpr reachable from a statement list.

    Phase 4 (bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
    rescan.md): the traversal is a pure function of each top-level
    statement's subtree (`_collect_calls` reads no mutable gen state —
    its only gen call, `_fstring_sub_exprs`, re-parses the literal's own
    text from scratch), and every consumer of the collected list only
    READS the yielded CallExpr nodes (isinstance/`.func.name`/`.args`
    inspection; none mutates them or compares identity). So each top-
    level statement's contribution is memoized by id(stmt) in the
    tree-wide shared `gen._calls_in_stmts_cache`, exactly like Phase 2's
    field-scan caches: a statement already walked by any earlier level /
    fixpoint round contributes its cached calls verbatim instead of
    being re-walked O(levels × rounds) times as `imported_stmts` and the
    Pass 1.3d/2c caller-body lists grow."""
    cache = gen._calls_in_stmts_cache
    for n in stmts:
        cached = cache.get(id(n))
        if cached is None:
            sub = []
            _collect_calls_in_stmt(gen, n, sub)
            cached = tuple(sub)
            cache[id(n)] = cached
        out.extend(cached)


def _collect_calls_in_stmt(gen, n, out):
    """Walk ONE statement, appending every reachable CallExpr to out —
    the exact per-statement body of the pre-memoization `_calls_in_stmts`
    loop (same attribute order, same recursion through the memoized
    `gen._calls_in_stmts` entry point so nested statement lists are
    cached too)."""
    for attr in ('value', 'condition', 'iterable'):
        if hasattr(n, attr):
            gen._collect_calls(getattr(n, attr), out)
    for attr in ('body', 'then_body', 'else_body', 'finally_body'):
        sub = getattr(n, attr, None)
        if isinstance(sub, list):
            gen._calls_in_stmts(sub, out)
    for _cond, eb in (getattr(n, 'elifs', None) or []):
        gen._calls_in_stmts(eb, out)
    for h in (getattr(n, 'handlers', None) or []):
        hb = getattr(h, 'body', None)
        if isinstance(hb, list):
            gen._calls_in_stmts(hb, out)

def _split_expr_format(src: str) -> str:
    """Split off format spec and conversion from an f-string expression.

    Only ':' and '!' at the top level (not inside brackets/parens/braces)
    separate the expression from the format spec or conversion."""
    depth = 0
    for i, ch in enumerate(src):
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch in ':!' and depth == 0:
            return src[:i].strip()
    return src.strip()


def _parse_fstring_parts(gen, inner):
    """Parse f-string body into [('lit',text) | ('expr',code)] parts."""
    parts = []
    i = 0
    buf = []
    while i < len(inner):
        c = inner[i]
        if c == '{':
            if i + 1 < len(inner) and inner[i+1] == '{':
                buf.append('{'); i += 2; continue
            if buf:
                parts.append(('lit', ''.join(buf), '', '')); buf = []
            i += 1
            depth = 1
            expr_chars = []
            while i < len(inner) and depth > 0:
                ch = inner[i]
                if ch == '{': depth += 1
                elif ch == '}': depth -= 1
                if depth > 0:
                    expr_chars.append(ch)
                i += 1
            expr_src = ''.join(expr_chars)
            # Split the expression from its optional format spec /
            # conversion (`{x:04d}` -> expr "x", spec "04d").
            _spec = ''
            _conv = ''
            _depth = 0
            for _k, _ch in enumerate(expr_src):
                if _ch in '([{':
                    _depth += 1
                elif _ch in ')]}':
                    _depth -= 1
                elif _ch == ':' and _depth == 0:
                    _spec = expr_src[_k + 1:]
                    expr_src = expr_src[:_k]
                    break
                elif _ch == '!' and _depth == 0:
                    _conv = expr_src[_k + 1:]
                    expr_src = expr_src[:_k]
                    break
            parts.append(('expr', expr_src.strip(), _spec, _conv))
        elif c == '}' and i + 1 < len(inner) and inner[i+1] == '}':
            buf.append('}'); i += 2
        else:
            buf.append(c); i += 1
    if buf:
        parts.append(('lit', ''.join(buf), '', ''))
    return parts


def _repr_value(gen, rat: str, rav: str) -> str:
    """Convert an already-lowered (type, value) pair into a `char *` per
    Python `repr()` semantics. Shared by the `repr()` builtin and `%r`
    string-formatting."""
    if rat == 'char *':
        return gen._call_expr('char *', 'mojo_repr_str', [('char *', rav)])
    if rat == 'MojoList *':
        return gen._call_expr('char *', gen._list_repr_fn(rav), [('MojoList *', rav)])
    if rat == 'MojoDict *':
        return gen._call_expr('char *', '_mojo_repr_dict', [('MojoDict *', rav)])
    if rat.endswith(' *') or rat == 'void *':
        # Dispatch through the per-struct field-by-field reprs generated
        # in gen_module (see reflect_structs) when the runtime type tag
        # is one this program actually allocates — falls back to the
        # address placeholder (mojo_repr_obj) for anything else, same
        # as before. Real bug found via mojo.py's own `--dump`'s
        # `repr(ast)` on a parsed AST list: every node printed as a
        # meaningless `<object at 0x...>` instead of its real fields,
        # since only mojo_repr_obj (no field-metadata table) existed.
        rav_local = gen._ensure_local(rat, rav)
        vp = gen._new_val('void *', f'(void *){rav_local}')
        return gen._call_expr('char *', '_mojo_dispatch_repr', [('void *', vp)])
    if rat in ('double', 'float'):
        rav_d = rav if rat == 'double' else gen._new_val('double', f'(double){rav}')
        return gen._call_expr('char *', 'mojo_repr_float', [('double', rav_d)])
    rav64 = rav if rat == 'int64_t' else gen._new_val('int64_t', f'(int64_t){rav}')
    return gen._call_expr('char *', 'mojo_repr_int', [('int64_t', rav64)])


def _decode_str_literal_text(gen, val: str) -> tuple[str, bool]:
    """Strip a raw StringLiteral.value's f/r/b/u/t prefix and outer quotes,
    returning (text, is_fstring). Shared by plain-string lowering, f-string
    interpolation, and `%`-style string-formatting (which needs the format
    string's literal text at codegen time, before any quoting/escaping)."""
    # Detect and strip f/r/b/u/t prefix — only if followed by a quote character
    # Regular strings have their quotes already stripped by the parser; f-strings
    # and t-strings (template strings — same `{expr}` interpolation syntax,
    # treated identically here) keep prefix+quotes.
    is_fstring = False
    prefix = ''
    while val and val[0] in 'fFrRbBuUtT':
        prefix += val[0]
        val = val[1:]
    # If the remaining value starts with a quote, it still has quotes (f-string case)
    # If not, the prefix-like characters were part of the string content — restore them
    if not val or val[0] not in ('"', "'"):
        val = prefix + val  # restore — these weren't string prefixes
    else:
        # These were actual prefixes — check for f-string/t-string marker
        is_fstring = any(c in 'fFtT' for c in prefix)
    # Strip outer triple or single quotes. mojo_compiler.py's Parser
    # already strips quotes from a plain (non-triple, non-f/t-string)
    # StringLiteral's value at tokenize time — this defensive re-strip
    # exists for values that DIDN'T go through that (f/t-strings keep
    # their prefix+quotes per the comment above; triple-quoted strings
    # come back from the placeholder cache still fully quoted). The
    # `len(val) >= 2` guard matters: a bare single-character value that
    # happens to BE a quote character (e.g. this file's own `'"'` /
    # `"'"` literals — a StringLiteral literally containing just a
    # double- or single-quote) both start AND end with that same
    # character, indistinguishable from "an already-quoted empty
    # string" to the naive check below without a length floor — an
    # actually-quoted value needs at least the two delimiter
    # characters. Without the guard, `'"'` silently became the empty
    # string, and worse, collided in the string-interning pool with
    # `"'"` (also emptied out) — found via mojo_compiler.py's own
    # `_strip_inline_comment`'s `c in ('"', "'", '\`')` never matching
    # a real `"` once self-hosted, letting a `#` inside an f-string
    # call argument get misread as a real comment start.
    if val.startswith('"""') and val.endswith('"""'):
        val = val[3:-3]
    elif val.startswith("'''") and val.endswith("'''"):
        val = val[3:-3]
    elif len(val) >= 2 and ((val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'"))):
        val = val[1:-1]
    # Return the is_fstring flag as an EMPTY/non-empty STRING ("", "1")
    # rather than a bool, so the (text, is_fstring) tuple is homogeneous
    # [char*, char*] — the caller unpacks both slots via get_str (the
    # tuple elem type), and a heterogeneous (str, bool) tuple would make
    # Pass 2c infer elem 'int64_t' (it can't type the local `val` as
    # char* with var_types empty), so the caller read val's pointer as an
    # int and the string pool stored its address. All consumers treat
    # is_fstring as truthiness, which "" vs "1" preserves exactly.
    return val, ('1' if is_fstring else '')


def _stub_result(gen, ctype: str, value: str, note: str) -> tuple[str, str]:
    """Emit a placeholder result for an operation codegen cannot lower.

    The generated program receives `value` (typically 0 or an empty
    string) instead of a real implementation, annotated with a
    `/* note */` comment.  Every use is reported through _debug_note so
    stubbed-out behavior is diagnosable with MOJO_DEBUG instead of
    silently returning wrong answers.
    """
    gimple_ctypes._debug_note('stubbed operation', note)
    t = gen._new_temp(ctype)
    gen._emit(f"  {t} = {value};  /* {note} */")
    return ctype, t


def _intern_string(gen, escaped: str) -> str:
    """Return the pool name (_slit_N) for an already-escaped C string.

    Adds the string to the module-level pool on first use.  All string
    literals must go through the pool: inline char[] literals are not
    valid in __GIMPLE assignments or call arguments.
    """
    if escaped not in gen._str_pool:
        gen._str_pool[escaped] = f'_slit_{gimple_codegen.STRING_POOL_BASE + len(gen._str_pool)}'
    return gen._str_pool[escaped]


def _str_literal_to_slit(gen, str_literal: str) -> str:
    """Convert a raw C string literal to a _slit_ name from the string pool.
    
    Args:
        str_literal: A raw C string literal like '"hello world"' or "'test'"
        
    Returns:
        The corresponding _slit_ name like '_slit_10000'
    """
    # Strip the outer quotes
    if (str_literal.startswith('"') and str_literal.endswith('"')) or \
       (str_literal.startswith("'") and str_literal.endswith("'")):
        val = str_literal[1:-1]
    else:
        val = str_literal
    
    # Escape the string content
    escaped = gimple_ctypes._c_escape(val)

    return gen._intern_string(escaped)


def _subst_idents(gen, expr, mapping: dict):
    """Return a copy of an AST expression with any IdentExpr whose name is in
    `mapping` replaced by the mapped node. Used to rebind `Self`/struct-name
    to a concrete object expression when expanding a struct comptime alias."""
    if isinstance(expr, gimple_ctypes.IdentExpr) and expr.name in mapping:
        return mapping[expr.name]
    if gimple_ctypes.dataclasses.is_dataclass(expr) and not isinstance(expr, type):
        changes = {}
        for f in gimple_ctypes.dataclasses.fields(expr):
            v = getattr(expr, f.name)
            nv = gen._subst_in_value(v, mapping)
            if nv is not v:
                changes[f.name] = nv
        return gimple_ctypes.dataclasses.replace(expr, **changes) if changes else expr
    return expr


def _format_percent_spec(gen, full_spec: str, conv: str, et: str, ev: str) -> str:
    """Render one %-spec's operand to `char *`, applying any width or
    precision in `full_spec` via a real C sprintf (see _sprintf_one)
    rather than reimplementing printf-style padding by hand."""
    if conv == 's':
        sval = gen._stringify_value(et, ev)
        if full_spec == '%s':
            return sval
        return gen._sprintf_one(full_spec[:-1] + 's', sval)
    if conv == 'r':
        rval = gen._repr_value(et, ev)
        if full_spec == '%r':
            return rval
        return gen._sprintf_one(full_spec[:-1] + 's', rval)
    if conv == 'c':
        nv = gen._to_int64(et, ev)
        cv = gen._new_val('char', f'(char){nv}')
        return gen._call_expr('char *', 'mojo_char_to_str', [('char', cv)])
    if conv in 'diouxX':
        nv = gen._to_int64(et, ev)
        # Insert a 64-bit length modifier: Python %-specs never carry one
        # (Python ints have no fixed width), but this codebase's Int is a
        # 64-bit int64_t -- sprintf-ing that through a bare "%d" is
        # undefined behavior (only 32 bits of the varargs int64_t are
        # consumed on most ABIs). "%5d" -> "%5lld", etc.
        c_spec = full_spec[:-1] + 'll' + conv
        return gen._sprintf_one(c_spec, nv)
    if conv in 'fFeEgG':
        dv = ev if et == 'double' else gen._new_val('double', f'(double){ev}')
        return gen._sprintf_one(full_spec, dv)
    # Unknown/unsupported conversion (e.g. '%a') -- degrade to str().
    return gen._stringify_value(et, ev)


def _cast_for_list(gen, elem_type: str, val: str, suf: str) -> str:
    """Coerce a value to the API's expected type; always returns an lvalue (temp if cast needed)."""
    if suf == 'int':
        return gen._to_int64(elem_type, val)
    if suf == 'double':
        if elem_type == 'double':
            return val
        t = gen._new_val('double', f"(double){val}")
        return t
    # str: a genuine single character (real C `char`/`int`/`int64_t` holding
    # a small ASCII code, e.g. from string indexing via mojo_str_char_at)
    # is a distinct representation from a char*-boxed-as-int64_t pointer —
    # reinterpreting its raw byte value as a pointer produces a garbage
    # address (e.g. 0x22 for '"'). `elem_type == 'char'` always means a raw
    # byte (only mojo_str_char_at produces that C type); a declared
    # 'int'/'int64_t' local is ambiguous — it's a real boxed pointer only
    # when _actual_types records one (set wherever a pointer got stored
    # into an int64_t elsewhere, see _gen_stmt_AssignStmt). Build a real
    # 1-char string in the unambiguous/small-value cases instead of
    # numeric-casting. Found via mojo_compiler.py's own
    # `c in ('"', "'", '`')`, where `c`'s declared type ended up `int64_t`
    # (joined across other assignment sites in the same function) even
    # though every value actually stored in it here is a raw char byte.
    actual = gen._actual_types.get(val)
    # A genuine single char is 'char'-typed or tracked as 'char' in
    # _actual_types (e.g. `c = s[i]` reassigned into an int64_t local).
    # An int64_t with NO record is a BOXED char* pointer (the codegen's
    # storage convention) — the old "no pointer record → char byte" check
    # truncated it, appending the low byte of the pointer as a 1-char
    # string instead of the boxed string it points to.
    if suf == 'str' and (elem_type == 'char' or actual == 'char'):
        cval = val if elem_type == 'char' else gen._new_val('char', f"(char){val}")
        return gen._call_expr('char *', 'mojo_char_to_str', [('char', cval)])
    # str: cast int-cast strings (boxed pointers stored as int64_t) to char*
    if suf == 'str' and elem_type in ('int', 'int64_t'):
        cp = gen._new_temp('char *')
        ip = gen._new_val('int64_t', f"(int64_t){val}")
        gen._emit(f"  {cp} = (char *){ip};")
        return cp
    return val  # already char*


def _type_expr_to_ann(gen, node) -> str:
    """Reconstruct a type-annotation string from a type expression node, so
    parametric types in external_call/MLIR positions resolve via _mojo_type.
    e.g. UnsafePointer[Int8] -> 'UnsafePointer[Int8]', c_ssize_t -> 'c_ssize_t'.

    Also doubles as the textual rendering of a COMPTIME VALUE bracket
    argument (`f[1]`, `f[True]`, `f[-1]`) for a comptime-bracket-
    parametrized call (`f[N: Int](...)`, not a type-parametrized generic)
    — see bugs/CODEGEN_comptime_bracket_parametrized_function_calls_
    silently_wrong.md. monomorphize.py's substitution is purely textual
    (`re.sub(r'\\bTP\\b', str(concrete), src)`), so a literal's Python
    repr substitutes into the callee body exactly like a type name does;
    no separate value-vs-type code path is needed downstream, only this
    node-to-string step, which previously returned '' for every literal
    (IntLiteral/BoolLiteral/negative-int UnaryOp), making
    _is_concrete_type_arg reject it and silently falling back to the
    placeholder-0 codegen instead of ever binding/invoking the callee."""
    if isinstance(node, gimple_ctypes.IdentExpr):
        return node.name
    if isinstance(node, gimple_ctypes.SubscriptExpr):
        base = gen._type_expr_to_ann(node.obj)
        idx = node.index
        parts = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
        inner = ', '.join(gen._type_expr_to_ann(p) for p in parts)
        return f"{base}[{inner}]"
    if isinstance(node, gimple_ctypes.MemberExpr):
        return f"{gen._type_expr_to_ann(node.obj)}.{node.member}"
    if isinstance(node, gimple_ctypes.IntLiteral):
        return str(node.value)
    if isinstance(node, gimple_ctypes.BoolLiteral):
        return 'True' if node.value else 'False'
    if isinstance(node, gimple_ctypes.UnaryOp) and node.op == '-' and isinstance(node.operand, gimple_ctypes.IntLiteral):
        return str(-node.operand.value)
    return ''


def _static_generic_return_ctype(gen, func_name: str) -> str | None:
    """Best-effort static return type for a generic free function this
    codegen could not fully elaborate (see the call site's docstring for
    why: implicit/inferred bracket params like `mut`/`origin` this
    elaborator has no lifetime model for). Reads ONLY the function's own
    `-> ReturnType:` annotation text from its defining module's source —
    no monomorphization, no method extraction, just enough to tell an
    opaque stub apart from a real container so a later `for x in
    <this call>:` doesn't take the boxed dict/list runtime-dispatch path
    (see _gen_for_iter) and declare the loop variable `char *` no matter
    what the loop body actually does with it."""
    src_path = gen._imported_generics.get(func_name)
    if not src_path:
        return None
    try:
        text = open(src_path).read()
    except OSError:
        return None
    m = gimple_ctypes.re.search(rf'\b(?:fn|def)\s+{gimple_ctypes.re.escape(func_name)}\s*\[', text)
    if not m:
        return None
    # Scan forward tracking bracket/paren depth from the opening `[` of
    # the comptime param list, through the `(...)` value param list, to
    # find the return annotation right after the value params' closing
    # `)` — bracket-aware because a real signature nests brackets inside
    # brackets (`origin: Origin[mut=mut]`).
    i = m.end() - 1
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in '[(':
            depth += 1
        elif c in '])':
            depth -= 1
            if depth == 0 and c == ')':
                break
        i += 1
    else:
        return None
    rm = gimple_ctypes.re.match(r'\s*(?:raises\s*)?->\s*([^:\n]+):', text[i + 1:i + 300])
    if not rm:
        return None
    ctype = gimple_ctypes._mojo_type(rm.group(1).strip())
    return ctype if ctype in ('MojoList *', 'MojoDict *', 'MojoSet *', 'Span *') else None


def _elaborate_generic_call(gen, node: gimple_ctypes.CallExpr):
    """Elaborate a call to an imported generic into a concrete CAS-cached
    instantiation. Handles both the explicit form `Generic[TypeArgs](args)`
    and the inferred form `Generic(args)` (type args inferred from argument
    types — slice 2). Returns (ctype, val) if elaborated, else None."""
    explicit = isinstance(node.func, gimple_ctypes.SubscriptExpr)
    g = node.func.obj.name if explicit else node.func.name
    source = gen._imported_generics.get(g)
    if not source:
        return None
    # Lower args once; their C types drive inference (and the emitted call).
    # Append keyword-argument values after the positionals (they fill the
    # trailing params in order — e.g. `_async_execute[T](h, desired_worker_id=-1)`).
    arg_pairs = [gen.lower_expr(a) for a in node.args]
    for _kn, _kexpr in (getattr(node, 'kwargs', None) or []):
        arg_pairs.append(gen.lower_expr(_kexpr))
    try:
        module_src = open(source).read()
        import elaborate
        el = elaborate.Elaborator()
        # A generic being elaborated here MAY contain a nested async/
        # generator def (test_tracing.mojo's own real shape: `def
        # test_tracing[level, enabled](): async def test_tracing_add
        # [enabled, lhs](...): ...`). This used to be an unconditional
        # honest refusal — monomorphize.py's substitution is purely
        # TEXTUAL over the whole extracted template block, which has no
        # notion of nested-scope shadowing (a nested nested nested
        # bracket-param re-declaring an OUTER template's own bracket-
        # param name), and `instantiate()`'s `build()` only ever
        # compiled the .c side, silently discarding the required
        # coroutine translation unit. Both are now handled: `monomorphize
        # _source`'s `_shadowed_spans`/`_sub_outside_spans` exclude any
        # nested function's own re-declared bracket-parameter scope from
        # the outer substitution, and `instantiate()` compiles+CAS-
        # caches a SECOND (.cpp-compiled) object whenever `GimpleGen.
        # generated_cpp` is non-empty (see that method's own docstring),
        # threaded through elaborate.py's returned dict as `cpp_object`
        # and collected onto `self._link_objects`/`self._link_needs_cxx`
        # by `_emit_generic_instantiation`/`_ensure_generic_struct`
        # below — no refusal needed here anymore.
        if explicit:
            idx = node.func.index
            elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
            type_args = [gen._type_expr_to_ann(e) for e in elems]
            # Only instantiate for CONCRETE type args. Inside a still-generic
            # body the args are unbound type parameters (U, Self.T, *Ts,
            # Self.Types[i]); "instantiating" those just substitutes symbol for
            # symbol and recurses without converging — the call must stay
            # generic and resolve when the OUTER generic is instantiated.
            if not all(gimple_exprtypes._is_concrete_type_arg(t) for t in type_args):
                return None
            # A type arg can itself be a generic-struct instantiation
            # (e.g. `alloc[MoveOnly[Int]]`). elaborate.py's monomorphizer
            # only does textual substitution — it has no notion that
            # "MoveOnly[Int]" mangles to a real struct "MoveOnly_Int" — so
            # pre-elaborate+register any such nested struct HERE (where
            # self._imported_generic_structs / struct_field_types are
            # available) and substitute its mangled name in place of the
            # raw generic text before handing type_args to the elaborator.
            # (The isolated monomorphized alloc_MoveOnly_Int_ body still
            # can't resolve the bare name "MoveOnly_Int" either — it falls
            # back to int64_t/int64_t* internally — but that's ABI-harmless
            # for a pointer return: see the return-type override below,
            # which corrects the CALLER-side declared type using this
            # instance's own struct-aware _resolve_type.)
            orig_type_args = type_args
            new_type_args = []
            for ta in type_args:
                base = ta.split('[', 1)[0].strip()
                if '[' in ta and base in gen._imported_generic_structs:
                    inner = ta.split('[', 1)[1].rstrip(']')
                    sub_args = [a.strip() for a in gimple_ctypes._split_top_level_commas(inner)]
                    # _is_concrete_type_arg only inspects the OUTER base
                    # name — "DictEntry[Self.K, Self.V, Self.H]" (inside
                    # Dict's own still-generic methods) has a concrete
                    # outer base ("DictEntry") but unbound nested args, so
                    # check those recursively before attempting to
                    # elaborate; otherwise this would try (and fail, or
                    # worse, wrongly succeed) to monomorphize a struct
                    # against unbound Self.X placeholders.
                    if not all(gimple_exprtypes._is_concrete_type_arg(sa) for sa in sub_args):
                        new_type_args.append(ta)
                        continue
                    mangled = gen._ensure_generic_struct(base, sub_args)
                    new_type_args.append(mangled if mangled else ta)
                else:
                    new_type_args.append(ta)
            type_args = new_type_args
            info = el.elaborate_generic_call(module_src, g, type_args, arg_count=len(arg_pairs))
            if info:
                gen._refine_generic_return_type(info, module_src, g, type_args, len(node.args))
        else:
            info = el.elaborate_generic_call_inferred(
                module_src, g, [ct for ct, _ in arg_pairs])
    except RuntimeError:
        # The nested-async-in-a-generic guard above raises RuntimeError
        # deliberately — an honest refusal, not a "try something else"
        # signal — so it must propagate, not be swallowed into the
        # silent `info = None` fallback the broad `except Exception`
        # below exists for (genuinely transient/inapplicable
        # elaboration failures elsewhere, e.g. a generic this
        # elaborator just can't handle yet).
        raise
    except Exception:
        gimple_ctypes._debug_note('generic call elaboration failed')
        info = None
    if not info:
        return None
    return gen._emit_generic_instantiation(info, arg_pairs)


def _refine_generic_return_type(gen, info: dict, module_src: str, g: str,
                                 mangled_type_args: list, arg_count: int) -> None:
    """elaborate.py's _signature() resolves a generic's return type via the
    bare, stateless _mojo_type(), which has no notion of a struct newly
    monomorphized by _ensure_generic_struct just above (e.g. "MoveOnly_Int")
    — it only matches _TYPE_MAP's builtin names, so it silently falls back
    to int64_t/int64_t* whenever a type argument is such a struct. Recompute
    the return type here using this instance's own struct-aware
    _resolve_type (which DOES know about struct_field_types) over the
    template's own return annotation, substituted with the mangled type
    args — and only override info['ret'] when that yields something more
    specific than the generic int64_t default, so ordinary (non-struct)
    generics are unaffected."""
    import elaborate
    tmpl = elaborate.extract_fn_source(module_src, g, arg_count=arg_count)
    if not tmpl:
        return
    params = elaborate.type_param_names(tmpl)
    if not params:
        return
    for s in gimple_ctypes.Parser(gimple_ctypes.py_tokenize(tmpl)).parse_module():
        if isinstance(s, gimple_ctypes.FunctionDef) and s.name == g and s.return_type:
            ret_ann = s.return_type
            for tp, concrete in zip(params, mangled_type_args):
                ret_ann = gimple_ctypes.re.sub(rf'\b{gimple_ctypes.re.escape(tp)}\b', concrete, ret_ann)
            better_ret = gen._resolve_type(ret_ann)
            if better_ret != 'int64_t':
                info['ret'] = better_ret
            break


def _ensure_generic_struct(gen, base_name: str, type_args: list) -> str | None:
    """Elaborate+register `base_name[type_args]` (idempotent) via
    elaborate.Elaborator.elaborate_generic_struct: materialize the concrete
    monomorphized struct (register its layout + typedef, declare its
    methods, record its object on the link line). Returns the mangled
    struct name, or None if base_name isn't a known imported generic
    struct or elaboration fails.

    Factored out of _elaborate_generic_struct_call so a nested generic
    struct used as a TYPE ARGUMENT to another generic (e.g. `alloc[
    MoveOnly[Int]]`) can also be resolved to a real struct, not just one
    used at a direct `Struct[Args](...)` construction call site."""
    source = gen._imported_generic_structs.get(base_name)
    if not source:
        return None
    # Only instantiate for CONCRETE type args (mirrors the same guard
    # _elaborate_generic_call already has). Inside a still-generic body
    # a type arg can be an unbound placeholder (`Self.size`, `Self.K`,
    # a lone type param) — e.g. `StaticTuple[Self.size](...)` called from
    # StaticTuple's OWN generic methods, or `alloc[DictEntry[Self.K,
    # Self.V, Self.H]]` from Dict's own methods. Monomorphizing against
    # an unbound placeholder textually "succeeds" but produces a bogus,
    # inconsistently-mangled struct/symbol that collides with the real
    # compiled definition ("conflicting types") — confirmed regression
    # once _imported_generic_structs started actually being populated.
    if not all(gimple_exprtypes._is_concrete_type_arg(ta) for ta in type_args):
        return None
    try:
        module_src = open(source).read()
        import elaborate
        info = elaborate.Elaborator().elaborate_generic_struct(module_src, base_name, type_args)
    except Exception:
        gimple_ctypes._debug_note('generic struct elaboration failed')
        info = None
    if not info or not info['fields']:
        return None

    name = info['name']
    if name not in gen.struct_field_types:
        # elaborate_generic_struct's method extraction doesn't mangle
        # overloaded methods by signature — two `__init__`s (or e.g.
        # LinkedList's `pop()` / `pop(index)`, a common pattern) both come
        # back named "{name}_{method}", which would need two DIFFERENT
        # extern declarations for the same C symbol ("conflicting
        # types"). Rather than register a subset (silently making the
        # OTHER overload uncallable — confirmed to actively break
        # LinkedList, which has real callers of both `pop` forms), bail
        # out of elaborating this struct entirely: the caller
        # (_lower_call's `if res is not None: return res` pattern) then
        # falls through to whatever path already handled this struct
        # correctly before _imported_generic_structs started actually
        # being populated (this whole mechanism was previously dead code
        # — see _register_imported_generic_structs).
        seen_sigs: dict = {}
        for mname, ret, ps in info['methods']:
            sig = (ret, tuple(ps))
            if mname in seen_sigs and seen_sigs[mname] != sig:
                return None
            seen_sigs[mname] = sig
        # Register the layout; the struct-typedef section emits the typedef.
        gen.struct_field_types[name] = {f: ct for f, ct in info['fields']}
        for mname, ret, ps in info['methods']:
            msym = f"{name}_{mname}"
            gen.func_return_types[msym] = ret
            gen.func_param_types[msym] = [f"{name} *"] + ps
            decl = (f"extern {ret} {msym} "
                    f"({', '.join([name + ' *'] + ps) or 'void'});")
            if decl not in gen._elaborated_externs:
                gen._elaborated_externs.append(decl)
    if info['object'] not in gen._link_objects:
        gen._link_objects.append(info['object'])
    _cpp_obj = info.get('cpp_object')
    if _cpp_obj is not None and _cpp_obj not in gen._link_objects:
        gen._link_objects.append(_cpp_obj)
        gen._link_needs_cxx = True
    return name


def _elaborate_generic_struct_call(gen, node: gimple_ctypes.CallExpr):
    """Elaborate Struct[TypeArgs](args): materialize the concrete monomorphized
    struct (register its layout + typedef, declare its methods, record its
    object on the link line), then lower the call as a constructor."""
    g = node.func.obj.name
    idx = node.func.index
    elems = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
    type_args = [gen._type_expr_to_ann(e) for e in elems]
    name = gen._ensure_generic_struct(g, type_args)
    if not name:
        return None
    return gen._lower_struct_constructor(name, node.args, getattr(node, 'kwargs', None))


def _emit_generic_instantiation(gen, info, arg_pairs):
    """Record an elaborated instantiation (object on the link line, extern in
    the preamble, signature for calls) and emit the concrete call."""
    sym = info['symbol']
    # A re-entrant (recursive-cycle) instantiation returns object=None — the
    # real .o is contributed by the outer frame; don't add a null link entry.
    if info['object'] is not None and info['object'] not in gen._link_objects:
        gen._link_objects.append(info['object'])
    _cpp_obj = info.get('cpp_object')
    if _cpp_obj is not None and _cpp_obj not in gen._link_objects:
        gen._link_objects.append(_cpp_obj)
        gen._link_needs_cxx = True
    gen.func_return_types[sym] = info['ret']
    gen.func_param_types[sym] = info['params']
    # The template may have trailing params with a default value (e.g.
    # `alloc[type](count: Int, *, alignment: Int = align_of[type]())`);
    # the parser deliberately discards default-value expressions (no
    # comptime evaluator), so a call site that relies on the default
    # (`alloc[Int](5)`) legitimately has fewer args than `info['params']`.
    # Pad with the same best-effort placeholder used for every other
    # missing-argument case in this file (e.g. _lower_call's general kwarg
    # padding) — semantically a stand-in, but keeps the call C-typesafe.
    while len(arg_pairs) < len(info['params']):
        arg_pairs.append(('int', '0'))
    # A variadic pack param (`*args: *Ts`) collapses to a single generic
    # slot in the elaborated signature (elaborate.py's _signature has no
    # notion of packing N call-site args into one MojoList*), so a call
    # site passing more values than the template's own params can supply
    # more arg_pairs than info['params'] has slots. Truncate the excess —
    # a stand-in like the padding above, just in the other direction —
    # so the call stays argument-count-safe against the extern decl.
    if len(arg_pairs) > len(info['params']):
        arg_pairs = arg_pairs[:len(info['params'])]
    _decl = f"extern {info['ret']} {sym} ({', '.join(info['params']) or 'void'});"
    if _decl not in gen._elaborated_externs:
        gen._elaborated_externs.append(_decl)
    if info['ret'] == 'void':
        gen._emit_call('', '', sym, arg_pairs)
        t = gen._new_temp('int')
        gen._emit(f"  {t} = 0;  /* void generic call */")
        return 'int', t
    t = gen._call_expr(info['ret'], sym, arg_pairs)
    return info['ret'], t


def _as_ptr(gen, ctype: str, val: str) -> tuple[str, str]:
    """Ensure (ctype, val) is a C pointer; if type inference lost it, cast to
    a generic pointer.  Returns (pointer_ctype, pointer_val)."""
    if ctype.endswith(' *'):
        return ctype, val
    pv = gen._new_temp('int64_t *')
    v64 = gen._ensure_local(ctype, val)
    gen._emit(f"  {pv} = (int64_t *) {v64};")
    return 'int64_t *', pv

def _is_none_literal(el) -> bool:
    """`None` is parsed as a bare `IdentExpr(name='None')`, not a
    dedicated literal node (see `_lower_IdentExpr`'s/`_quick_type`'s own
    `name == 'None'` checks — this file has no case that ever
    constructs `NoneLiteral`, despite mojo_compiler.py defining the
    class). Centralized here so every None-in-a-literal check in this
    file recognizes the same shape."""
    return isinstance(el, gimple_ctypes.IdentExpr) and el.name == 'None'


def _literal_elements_include_none(gen, elements: list) -> bool:
    """True when a list/tuple literal's own source elements contain a
    literal `None` (directly, or as either branch of a top-level
    ternary — the common `x if cond else None` shape). MojoList stores
    every element as a raw int64_t slot with no per-element type tag,
    and `None` lowers to the same all-zero bit pattern a genuine int
    value of 0 does — `_list_repr_fn`'s int64_t-elem-type fast path
    (mojo_repr_list_ints, no None-sentinel check) is only safe for a
    list PROVABLY free of any real `None` element; a literal that
    spells one out explicitly is the one case this codegen can check
    cheaply and confidently. Not a full type-flow analysis (a `None`
    arriving via a function call or a variable already holding it is
    still missed, same accepted-risk shape `mojo_repr_list_doubles`
    already carries for an Optional[Float] list — see _list_repr_fn's
    docstring), just enough to stop this specific fix from regressing
    the single most common explicit-`None`-in-a-literal shape."""
    for el in elements:
        if gen._is_none_literal(el):
            return True
        if isinstance(el, gimple_ctypes.TernaryExpr) and (
                gen._is_none_literal(el.then_val)
                or gen._is_none_literal(el.else_val)):
            return True
    return False


def _compr_enumerate_loop(gen, node, gen0, res, res_type, it_val, start_val):
    """`[... for i, x in enumerate(seq[, start]):]` (and dict/set
    equivalents) — walks `it_val` (the already-lowered underlying
    list) by index, assigning the (optionally `start`-offset) 0-based
    counter to the target's first slot and each element to the
    second. See `_lower_comprehension`'s call site for why this needs
    its own path rather than falling through to `_compr_list_loop`."""
    target_str = gen0.target.strip()
    inner_str = (target_str[1:-1].strip()
                 if (target_str.startswith('(') and target_str.endswith(')'))
                 else target_str)
    parts = [p.strip() for p in inner_str.split(',')]
    idx_var = parts[0] if len(parts) >= 1 and parts[0] else '_enum_i'
    val_var = parts[1] if len(parts) >= 2 and parts[1] else '_enum_val'

    elem = gen._elem_of(it_val)
    gen._declare_var(idx_var, 'int64_t')
    gen._declare_var(val_var, elem if elem else 'int64_t')

    len64 = gen._new_val('int64_t', f'mojo_list_len ({it_val})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    if start_val is not None:
        disp_idx = gen._new_val('int64_t', f"{idx64} + {start_val}")
        gen._emit(f"  {idx_var} = {disp_idx};")
    else:
        gen._emit(f"  {idx_var} = {idx64};")
    suf = gimple_ctypes.TypeLattice.list_suffix(elem) if elem else 'int'
    if suf == 'double':
        gen._emit(f"  {val_var} = mojo_list_get_double ({it_val}, {idx64});")
    elif suf == 'str':
        temp_str = gen._new_val('char *', f"mojo_list_get_str ({it_val}, {idx64})")
        target_type = gen._type_of(val_var)
        if target_type == 'char *':
            gen._emit(f"  {val_var} = {temp_str};")
        else:
            int_ptr = gen._new_val('int64_t', f"(int64_t){temp_str}")
            gen._emit(f"  {val_var} = {int_ptr};")
    else:
        raw64 = gen._new_val('int64_t', f"mojo_list_get_int ({it_val}, {idx64})")
        target_type = gen._type_of(val_var)
        if target_type and target_type != 'int64_t':
            gen._safe_coerce_emit('int64_t', target_type, raw64, val_var)
        else:
            gen._emit(f"  {val_var} = (int64_t) {raw64};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one64 = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx64} + {one64}")
    gen._emit(f"  {idx64} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_str_loop(gen, node, gen0, res, res_type, it_val):
    gen._declare_var(gen0.target, 'char')
    len64 = gen._new_val('int64_t', f'mojo_str_len ({it_val})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._emit(f"  {gen0.target} = mojo_str_char_at ({it_val}, {idx64});")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one64 = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx64} + {one64}")
    gen._emit(f"  {idx64} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_cstr_loop(gen, node, gen0, res, res_type, it_val):
    """`[... for c in s]`/`(... for c in s)` where `s` is a plain
    `char *` (this codegen's usual representation for an ordinary
    Python str local — MojoStr* is a separate, less common wrapped-
    string type _compr_str_loop already handles). Was completely
    unsupported here (no 'char *' case in _lower_comprehension's
    dispatch), matching _gen_for_iter's identical gap for a plain
    `for c in s:` statement loop — see _gen_for_cstr's own docstring
    for the real-world impact this had (mojo_compiler.py's own
    `any(c in (...) for c in prefix)` silently evaluating empty/False
    for every self-hosted-compiled program). Mirrors _compr_str_loop's
    identical index-loop shape, just over mojo_strlen/_mojo_at_char
    instead of mojo_str_len/mojo_str_char_at."""
    gen._declare_var(gen0.target, 'char')
    len64 = gen._new_val('int64_t', f'mojo_strlen ({it_val})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._ptr_helpers_needed.add('char')
    addr = gen._new_val('char *', f"_mojo_at_char ({it_val}, {idx64})")
    gen._emit(f"  {gen0.target} = *{addr};")
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one64 = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx64} + {one64}")
    gen._emit(f"  {idx64} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _gen_compr_append(gen, node: gimple_ctypes.Comprehension, gen0, res: str,
                      res_type: str, bb_skip: str):
    """`bb_skip` must be the loop's bb_post (advance-index-and-continue
    label), NOT bb_after (the loop-exit label) — every caller here used
    to pass bb_after, so a filter condition failing on ANY element
    jumped straight past the rest of the loop entirely instead of just
    skipping that one element, silently truncating the whole
    comprehension after its first non-matching item. E.g.
    `[s for s in body if isinstance(s, FunctionDef)]` returned [] as
    soon as body's FIRST entry wasn't a FunctionDef (a leading
    docstring ExprStmt, in the reproducing case), even though later
    entries would have matched."""
    if gen0.conditions:
        bb_append = gen._new_bb()
        for cond_expr in gen0.conditions:
            _, cv = gen.lower_expr(cond_expr)
            bb_next = gen._new_bb()
            gen._emit(f"  if ({cv}) goto {bb_next}; else goto {bb_skip};")
            gen._emit_label(bb_next)
        gen._emit_label(bb_append)

    if node.kind == 'list' or node.kind == 'generator':
        # `_lower_comprehension` initializes a 'generator' comprehension
        # identically to 'list' ("convert to list for simplicity" — see
        # its own comment), but this method never got the matching
        # 'generator' case added alongside 'list'/'set'/'dict' — so a
        # bare generator expression's body silently appended NOTHING,
        # leaving the backing list permanently empty regardless of the
        # source iterable. Any consumer expecting to see per-element
        # results (any()/all()/sum()/list(genexpr), or a `for` loop over
        # a saved generator expression) saw an empty result instead —
        # e.g. `any(c in (...) for c in prefix)` always evaluated
        # False/0. Found chasing make bootstrap's verify byte-identity
        # failures back through _gen_for_cstr's own motivating bug
        # (mojo_compiler.py's `_process_nested_tstrings` uses exactly
        # this any(genexpr) shape).
        et, ev = gen.lower_expr(node.element)
        suf = gimple_ctypes.TypeLattice.list_suffix(et)
        ev_cast = gen._cast_for_list(et, ev, suf)
        # GIMPLE: load global string literals into temp before function call
        if suf == 'str' and ev_cast.startswith('_slit_'):
            temp = gen._new_val('char *', f'{ev_cast}')
            ev_cast = temp
        gen._emit(f"  mojo_list_append_{suf} ({res}, {ev_cast});")
        # Track element type so downstream for-loops use the right accessor
        gen._elem_types[res] = et
        # A comprehension of TUPLES (`[(n, f) for n, f in funcs]`) — carry
        # the heterogeneous tuple's per-slot types so a later
        # `for n, f in test_funcs:` reads each slot with the right accessor.
        if et == 'MojoList *' and ev in gen._tuple_slot_types:
            gen._tuple_slot_types[res] = gen._tuple_slot_types[ev]
    elif node.kind == 'set':
        et, ev = gen.lower_expr(node.element)
        if et == 'char *':
            gen._emit_call('void', '', 'mojo_set_add_str', [('MojoSet *', res), ('char *', ev)])
        else:
            ev64 = gen._to_int64(et, ev)
            gen._emit_call('void', '', 'mojo_set_add_int', [('MojoSet *', res), ('int64_t', ev64)])
    elif node.kind == 'dict':
        kt, kv = gen.lower_expr(node.element)   # element = key expression in dict compr
        vt, vv = gen.lower_expr(node.key)        # key field holds the value expression
        # parser stores dict comprehension as: element=key_expr, key=val_expr
        # Dict keys are char* in the runtime: coerce the key to a char* local
        # via _char_to_cstr (handles a non-char* key — e.g. a genuine Int
        # key, stringified via mojo_str_from_int, or one actually boxed as
        # int64_t — and loads global string literals into locals first).
        if kt != 'char *':
            kt, kv = gen._char_to_cstr(kt, kv)
        elif kv.startswith('_slit_'):
            kv_tmp = gen._new_val('char *', f"{kv}")
            kv = kv_tmp
        if vt in gimple_ctypes._FLOAT_TYPES:
            gen._emit(f"  mojo_dict_set_double ({res}, {kv}, {vv});")
        elif vt == 'char *':
            if vv.startswith('_slit_'):
                vv_tmp = gen._new_val('char *', f"{vv}")
                vv = vv_tmp
            gen._emit(f"  mojo_dict_set_str ({res}, {kv}, {vv});")
        else:
            # See the dict-literal case's identical comment: vt alone
            # can't distinguish a real bool literal from a genuine int.
            if isinstance(node.key, gimple_ctypes.BoolLiteral):
                gen._emit(f"  mojo_mark_dict_bool_values ({res});")
            vv64 = gen._to_int64(vt, vv)
            gen._emit(f"  mojo_dict_set_int ({res}, {kv}, {vv64});")

def _is_sys_stderr(expr) -> bool:
    """Structural check for `sys.stderr` — deliberately not lowered as a
    runtime value at all (see mojo_print_stderr's doc comment: a bare
    FILE* isn't safely passable through -fgimple's restricted subset)."""
    return (isinstance(expr, gimple_ctypes.MemberExpr) and isinstance(expr.obj, gimple_ctypes.IdentExpr)
            and expr.obj.name == 'sys' and expr.member == 'stderr')


def _module_const_int(gen, name: str, stmts: list, imported_stmts: list | None) -> int | None:
    """Resolve a bare NAME to a compile-time int, by looking for a
    module-level `comptime NAME: T = <expr>` (or plain `NAME = <expr>`)
    binding in `stmts`/`imported_stmts` whose value folds to an int via
    `_eval_const_int`. Used by the fixed-size-array struct-field
    annotation (`[ElemType; N]`) to resolve a named size like box.3d/
    game's `comptime MAX_BLOCKS: Int = 4096`, since that array shape's
    size is very commonly a named constant rather than a bare literal.
    Cached (per-name) since struct field registration can look up the
    same name repeatedly across many fields/structs in one compile."""
    cache = getattr(gen, '_module_int_consts_cache', None)
    if cache is None:
        cache = gen._module_int_consts_cache = {}
    if name in cache:
        return cache[name]
    val = None
    for src in (stmts, imported_stmts or []):
        for st in src:
            if isinstance(st, gimple_ctypes.ComptimeVarStmt) and st.target == name:
                val = gen._eval_const_int(st.value)
            elif isinstance(st, gimple_ctypes.VarDecl) and st.name == name and st.value is not None:
                val = gen._eval_const_int(st.value)
            elif (isinstance(st, gimple_ctypes.AssignStmt) and isinstance(st.target, gimple_ctypes.IdentExpr)
                  and st.target.name == name):
                val = gen._eval_const_int(st.value)
            if val is not None:
                break
        if val is not None:
            break
    cache[name] = val
    return val


def _eval_const_compare_op(gen, op: str, left, right):
    """Apply one comparison-chain link's operator to two already
    compile-time-folded operands (used by _eval_const_int/_eval_const's
    CompareChain cases). A plain if/elif chain, not a dict of lambdas —
    self-hosting gimple_codegen.py couldn't link a dict-of-lambdas here
    (undefined `_GimpleGen__eval_const_lambda_N` symbols at self-host
    link time; this codegen's own closure-lowering doesn't support
    several small same-scope lambdas bound into one dict literal).
    Returns None for an unrecognized op, distinct from a real False."""
    if op == '==': return left == right
    if op == '!=': return left != right
    if op == '<':  return left < right
    if op == '<=': return left <= right
    if op == '>':  return left > right
    if op == '>=': return left >= right
    return None


def _eval_const(gen, node):
    """Evaluate an expression as any compile-time constant (int, bool,
    str, or a `comptime NAME: T = value` alias previously recorded by
    _gen_stmt_ComptimeVarStmt into self._comptime_vals) — or None if it
    isn't foldable. A superset of _eval_const_int/_eval_const_bool used
    where the comptime value's own type (not just int/bool) matters,
    e.g. a comptime `if` testing a comptime string alias."""
    if isinstance(node, gimple_ctypes.BoolLiteral): return node.value
    if isinstance(node, gimple_ctypes.IntLiteral):  return node.value
    if isinstance(node, gimple_ctypes.StringLiteral): return node.value
    if isinstance(node, gimple_ctypes.IdentExpr):
        return gen._comptime_vals.get(node.name)
    if isinstance(node, gimple_ctypes.UnaryOp) and node.op == '-':
        v = gen._eval_const(node.operand)
        return -v if isinstance(v, (int, bool)) else None
    if isinstance(node, gimple_ctypes.UnaryOp) and node.op == 'not':
        v = gen._eval_const(node.operand)
        return not v if isinstance(v, (bool, int)) else None
    if isinstance(node, gimple_ctypes.BinaryOp):
        l = gen._eval_const(node.left)
        r = gen._eval_const(node.right)
        if l is None or r is None: return None
        op = node.op
        if op == '+':   return l + r
        if op == '-':   return l - r
        if op == '*':   return l * r
        if op == '/':   return l // r
        if op == '==':  return l == r
        if op == '!=':  return l != r
        if op == '<':   return l < r
        if op == '<=':  return l <= r
        if op == '>':   return l > r
        if op == '>=':  return l >= r
        if op == 'and': return l and r
        if op == 'or':  return l or r
    if isinstance(node, gimple_ctypes.CompareChain):
        left = gen._eval_const(node.operands[0])
        if left is None: return None
        for op, operand in zip(node.ops, node.operands[1:]):
            right = gen._eval_const(operand)
            if right is None: return None
            link = gen._eval_const_compare_op(op, left, right)
            if link is None: return None
            if not link: return False
            left = right
        return True
    # `sys.platform` — a genuinely compile-time-constant value for THIS
    # host (matching this compiler's own CPython `sys.platform`, since
    # that's the platform any `if sys.platform == 'X': def f(): ...`
    # conditional-toplevel-def idiom is really being resolved for — see
    # gen_module's "conditional toplevel def" promotion, whose own TODO
    # comment names this exact gap: "if the guarding condition is one
    # this compiler can already resolve statically... pick the matching
    # branch... instead of" always picking the syntactically-first
    # branch regardless of whether its condition is actually true. Without
    # this, `_MS_WINDOWS = (sys.platform == 'win32')` folds to `None`
    # (unresolvable) on every host, and the promotion logic's "first-
    # branch-wins" fallback silently picks the WINDOWS-only branch's
    # body even when compiling on macOS/Linux — found via Lib/
    # importlib/_bootstrap_external.py's `if _MS_WINDOWS: def
    # _path_join(...): ... else: def _path_join(...): ...`.
    if (isinstance(node, gimple_ctypes.MemberExpr) and isinstance(node.obj, gimple_ctypes.IdentExpr)
            and node.obj.name == 'sys' and node.member == 'platform'):
        return gimple_ctypes.sys.platform
    return None
