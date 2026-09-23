"""GimpleGen resolution: generics elaboration, imports/linking, closures, reset.

Function-extraction architecture: former GimpleGen methods as
module-level functions taking `gen` first; delegates remain on
the class; cross-module references are qualified.
"""
from __future__ import annotations

import os
import re

# Gated determinism tracing hook (see determinism_trace.py's module docstring
# and HOW-TO-DEBUG.html section 8b). `_DTRACE_ON` is read ONCE, here, so the
# per-call check in `_new_val` (the temp-allocation chokepoint every emitted
# statement flows through) is a single dead bool branch when tracing is off —
# no I/O, no allocation, and no perturbation of the heap layout being
# measured. Set `MOJO_TRACE=1` (and optionally `MOJO_TRACE_FILE=<path>`) to
# switch the iota+xorshift64 stream on for a directed divergence hunt.
import determinism_trace as _dtrace

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
    _as_str, _sms_key,
    _as_assignstmt_node, _as_vardecl_node, _as_multiassignstmt_node,
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc
# gimple_gen_coro is reached via `gimple_codegen.gimple_gen_coro` below,
# not a separate import of its own here -- see gimple_codegen.py's own
# module-level `import gimple_gen_coro` and its comment on why a
# function-local import (the pattern this used to follow) caused a real
# self-hosted whole-program redefinition collision.

def _lbn_target_names(t) -> list:
    """Hoisted out of `_locally_bound_names` (module-level, not a nested
    closure) — see `_lbn_walk`'s docstring for why."""
    if isinstance(t, gimple_ctypes.IdentExpr):
        return [t.name]
    if isinstance(t, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr)):
        names = []
        for e in t.elements:
            names.extend(_lbn_target_names(e))
        return names
    return []


def _lbn_walk(bound: set, global_declared: set, nodes) -> None:
    """Hoisted out of `_locally_bound_names` (module-level, not a nested,
    RECURSIVE closure mutating two captured sets) — a real --dump-full
    fire.py crash (SIGSEGV in mojo_set_update -> mojo_set_add_str ->
    _set_slot_str -> _str_hash, address 0x1) traced here via lldb: the
    lifted-closure env carrying `bound`/`global_declared` across this
    closure's OWN recursive self-calls wasn't reliably allocated/valid at
    every recursion depth. Threading both sets as explicit parameters
    (mutated in place, same as any ordinary Python call) sidesteps the
    lifted-closure machinery entirely."""
    for node in nodes or []:
        if isinstance(node, gimple_ctypes.GlobalStmt):
            global_declared.update(node.names)
        elif isinstance(node, gimple_ctypes.AssignStmt):
            bound.update(_lbn_target_names(node.target))
        elif isinstance(node, gimple_ctypes.MultiAssignStmt):
            for t in node.targets:
                bound.update(_lbn_target_names(t))
        elif isinstance(node, gimple_ctypes.AugAssignStmt):
            bound.update(_lbn_target_names(node.target))
        elif isinstance(node, gimple_ctypes.VarDecl):
            bound.add(node.name)
        elif isinstance(node, gimple_ctypes.ForStmt):
            bound.update(_lbn_target_names(node.target))
            _lbn_walk(bound, global_declared, node.body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
        elif isinstance(node, gimple_ctypes.WhileStmt):
            _lbn_walk(bound, global_declared, node.body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
        elif isinstance(node, gimple_ctypes.IfStmt):
            _lbn_walk(bound, global_declared, node.then_body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
            for _, elif_body in (node.elifs or []):
                _lbn_walk(bound, global_declared, elif_body)
        elif isinstance(node, gimple_ctypes.TryStmt):
            _lbn_walk(bound, global_declared, node.body)
            for h in (node.handlers or []):
                _lbn_walk(bound, global_declared, h.body)
            if node.else_body:
                _lbn_walk(bound, global_declared, node.else_body)
            if node.finally_body:
                _lbn_walk(bound, global_declared, node.finally_body)
        elif isinstance(node, gimple_ctypes.WithStmt):
            for item in (node.items or []):
                _al = item.alias
                if _al is not None:
                    # `isinstance(_al, str)` is unreliable in the
                    # self-hosted backend (WithItem.alias is typed
                    # `object` -> int64_t -> the isinstance stub says
                    # False for a real `char *`, then `_al.name` on the
                    # bare string "f" raises AttributeError). Check for
                    # the node case explicitly; everything else is the
                    # string alias.
                    if isinstance(_al, gimple_ctypes.IdentExpr):
                        bound.add(_al.name)
                    else:
                        bound.add(_as_str(_al))
            _lbn_walk(bound, global_declared, node.body)


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

    _lbn_walk(bound, global_declared, body)
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
    # top-level tool scripts — fire_compiler.py, elaborate.py, lexer.py,
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
    # before: those entry files (fire.py, gimple_codegen.py, ...) already
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
    # RELATIVE imports (`from . import sibling` / `from ..pkg import mod`):
    # the parser keeps the leading dots in `module_name` (find_imports'
    # synthesized per-name candidates too: `from . import strutil` yields
    # both '.' and '.strutil'), and every candidate path below is built
    # by joining `module_name` into a search dir VERBATIM — so a
    # leading-dot name produced literal `<dir>/..strutil.py` filenames
    # that never exist. Relative imports therefore never resolved on the
    # compiled path at all (the INTERPRETER side has always handled them
    # — myinterpreter.py's execute_FromImportStmt level-based walk — so
    # any real-world Python package using intra-package imports silently
    # fell back from compilation to interpretation). Mirror the
    # interpreter's exact rule here: strip the dots to get the remaining
    # dotted suffix, count them as the level, anchor at the IMPORTING
    # FILE's own directory (the package directory containing it), and
    # walk up (level - 1) more parents; then resolve the remaining
    # suffix under that base exactly like an absolute name (flat file,
    # package __init__, and — for a genuinely dotted suffix — the
    # dotted-path forms below). A bare '.' (level 1, no suffix) names
    # the current package itself, i.e. its own __init__ source.
    # Names NOT starting with '.' are untouched — this only ever fires
    # for names that previously resolved to nothing, so no existing
    # resolution can change.
    _rel_level = 0
    if module_name.startswith('.'):
        _rel_suffix = module_name.lstrip('.')
        _rel_level = len(module_name) - len(_rel_suffix)
        if not _rel_suffix:
            # Bare package self-reference (`from . import X`): the names
            # live in the current package's own __init__ source.
            _rel_candidates = [('__init__', True)]
        else:
            _rel_candidates = [(_rel_suffix, False)]
        if importer_dir is None:
            return []
        _base_dir = importer_dir
        for _ in range(max(0, _rel_level - 1)):
            _base_dir = gimple_ctypes.os.path.dirname(_base_dir)
        rel_mojo_paths = []
        for _suffix, _is_pkg_self in _rel_candidates:
            _parts = _suffix.split('.')
            _flat = '/'.join(_parts)
            for ext in extensions:
                rel_mojo_paths.append(gimple_ctypes.os.path.join(_base_dir, f"{_flat}{ext}"))
            rel_mojo_paths.append(gimple_ctypes.os.path.join(
                _base_dir, _flat, f"__init__.py"))
            rel_mojo_paths.append(gimple_ctypes.os.path.join(
                _base_dir, _flat, f"__init__.mojo"))
        return rel_mojo_paths
    # Explicit `sys.path.insert(...)` directories win outright — the user
    # said "look here first" (see _record_sys_path_inserts) — then the
    # importing file's own directory, then ITS ANCESTOR directories
    # (nearest first, bounded — same bounded upward walk the INTERPRETER
    # side has always done for exactly the same reason: a nested package
    # member's imports are anchored at the package ROOT several levels up,
    # e.g. Lib/ctypes/macholib/dyld.py's `from ctypes.macholib.framework
    # import framework_info`, whose package root is .../Lib, two levels up
    # from the importing file's own directory — see myinterpreter.py's
    # matching search_dirs walk), then CWD and its parent, and only
    # then this repo's own installation directory as a last resort.
    search_dirs = list(gen._extra_search_paths)
    if importer_dir:
        search_dirs.append(importer_dir)
        _anc = gimple_ctypes.os.path.dirname(importer_dir)
        for _ in range(6):
            if not _anc or _anc == '/':   # os.path.sep — opaque on the compiled path
                break
            search_dirs.append(_anc)
            _parent = gimple_ctypes.os.path.dirname(_anc)
            if _parent == _anc:
                break
            _anc = _parent
    search_dirs += ['.', '..', script_dir]
    mojo_paths = []
    _seen_dirs: list = []
    for d in search_dirs:
        if d in _seen_dirs:
            continue
        _seen_dirs.append(d)
        for ext in extensions:
            mojo_paths.append(gimple_ctypes.os.path.join(d, f"{module_name}{ext}"))
            if '.' not in module_name:
                # BARE-package form: `from ctypes import cdll` names the PACKAGE
                # directory's own __init__ source when no sibling `ctypes.py`
                # exists — mirror the interpreter, which tries the
                # `<name>/__init__.<ext>` form for EVERY module name (see its
                # rel_pkg_path above), not just dotted ones. Without this, any
                # bare import of a real package (ctypes/, json/, ...) resolved
                # to nothing on the compiled path even though the identical
                # import worked interpreted.
                mojo_paths.append(gimple_ctypes.os.path.join(
                    d, module_name, f"__init__{ext}"))
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
        # `'/'`, not `os.sep`: `gimple_ctypes.os` is an opaque module
        # marker in the compiled backend, so `.sep` raised
        # `AttributeError: sep`. Every supported target uses `/`.
        _rel_flat = '/'.join(_dotted_parts)
        _rel_pkg = gimple_ctypes.os.path.join(_rel_flat, '__init__')
        for d in _seen_dirs:
            mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_flat}.py"))
            mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_flat}.mojo"))
            mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_pkg}.py"))
            mojo_paths.append(gimple_ctypes.os.path.join(d, f"{_rel_pkg}.mojo"))
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
            _rel_suffix_flat = '/'.join(_suffix_parts)
            _rel_suffix_pkg = gimple_ctypes.os.path.join(_rel_suffix_flat, '__init__')
            for d in _seen_dirs:
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


def _register_closure_struct_inits(gen, stmts) -> None:
    """Populate `gen._struct_has_init` / `_struct_init_params` /
    `_struct_init_defaults` / `_struct_method_names` for every top-level
    StructDef in `stmts` that defines an `__init__`. Called for each module
    of a do_imports=True closure BEFORE its bodies are lowered, so a
    cross-module `Class(kw=...)` constructor resolves to the real
    `Class___init__` call instead of falling to the field-assignment
    fallback. Mirrors gen_module_impl's Pass 2b registration."""
    for s in stmts:
        if not isinstance(s, StructDef):
            continue
        for m in s.methods:
            gen._struct_method_names.setdefault(s.name, set()).add(m.name)
            if m.name == '__init__':
                gen._struct_has_init.add(s.name)
                gen._struct_init_params[s.name] = [
                    pn for pn, _pt in m.params if pn != 'self']
                _init_defaults = getattr(m, 'param_defaults', {}) or {}
                gen._struct_init_defaults[s.name] = {
                    pn: dv for pn, dv in _init_defaults.items() if pn != 'self'}
                # Full C signature too, so _lower_struct_constructor's
                # __init__-call path coerces every arg to its declared param
                # type (a cross-module `Class(kw=..., aset={..})` otherwise
                # passes a MojoSet* into an int64_t slot uncast → GCC
                # -Wint-conversion). Mirrors gen_module_impl Pass 2b.
                _mangled = s.name + "___init__"
                if _mangled not in gen.func_param_types:
                    _ctypes = [s.name + " *"]
                    for _i, (_pn, _pt) in enumerate(m.params):
                        if _i == 0 and _pn == 'self':
                            continue
                        _ctypes.append(gen._param_ctype(_pn, _pt, m))
                    gen.func_param_types[_mangled] = _ctypes


def _compile_imported_module(gen, module_name: str) -> tuple:
    """Find and compile an imported .mojo/.py module, extracting type
    information.

    Returns (code: str, stmts: list) where stmts are parsed statements from the module.
    """
    mojo_paths = gen._module_candidate_paths(module_name)
    for path in mojo_paths:
        if gimple_ctypes.os.path.exists(path):
            _abspath = gimple_ctypes.os.path.abspath(path)
            # `_ap_key`: a fresh `_as_str`-typed local for the two
            # `_compiling_file_paths` set ops. `_abspath` derives from the
            # `for path in mojo_paths` loop var (int64_t on the self-hosted
            # backend), so `.add(_abspath)` lowered to `mojo_set_add_int`
            # and `_abspath in ...` to `mojo_set_contains_int` — a set keyed
            # by POINTER VALUE. `os.path.abspath` returns a fresh string
            # each call, so the cycle guard NEVER matched a re-entrant
            # import → infinite `_compile_imported_module` recursion through
            # the gimple_codegen ↔ gimple_gen_resolve import cycle → RSS
            # runaway on `MOJO_NO_SHIM=1 --dump-full`.
            _ap_key = _as_str(_abspath)
            if _ap_key in gen._inline_module_qualifiers:
                _module_key = module_name.lstrip('.').replace('.', '_').replace('-', '_')
                gen._inline_module_qualifiers[_module_key] = gen._inline_module_qualifiers[_ap_key]
            if _ap_key in gen._compiling_file_paths:
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
            # Same rollback rationale for the builtin-as-value funcptr pair:
            # a module whose gen_module raises mid-compile (e.g. the
            # "cannot compile module: `Counter[...] = ...` subscript store"
            # fallback for collections/inspect) has usually ALREADY run its
            # preamble-assembly pass, which marks every funcptr name it
            # discovered into the SHARED `_emitted_funcptr_builtins` — but
            # its generated text (containing those `static void *
            # _funcptr_X` declarations) is discarded by this very except
            # handler. Without rolling the marks back, every LATER module
            # that references the same name computes
            # `needed - emitted == {}`, emits no declaration of its own,
            # and the whole translation unit dies with "'_funcptr_mojo_len'
            # undeclared (first use in this function)" at the surviving
            # reference sites (real: re/_compiler.py's `_len = len`,
            # re/_parser.py:520, textwrap.py's `sum(map(len, ...))` in any
            # whole-program build whose closure contains collections or
            # inspect). Rolling `needed` back too keeps the pair symmetric:
            # names discovered ONLY by the failed subtree have no surviving
            # reference (their referencing text was discarded with it).
            funcptr_needed_before = set(gen._funcptr_builtins_needed)
            funcptr_emitted_before = set(gen._emitted_funcptr_builtins)
            gen._compiling_file_paths.add(_ap_key)
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
                # `_as_str(path)`: `path` is the raw `for path in
                # mojo_paths:` loop variable — but more fundamentally,
                # NOT the raw `path` at all, even `_as_str`-guarded:
                # `mojo_paths` (`_module_candidate_paths`) can list BOTH a
                # CWD-relative candidate (`search_dirs` includes a bare
                # `'.'`) and an absolute one for the SAME real file, and
                # WHICH ONE actually matches first (hence which literal
                # string `path` holds) depends on the enclosing gen's own
                # `_current_filename`/`importer_dir` state at resolution
                # time — itself dependent on which of several importers'
                # recursive compiles reaches this module first in the
                # whole-program closure, an order this session found is
                # not guaranteed identical between the shim and self-host
                # (see bugs/CODEGEN_selfhost_actual_types_identifier_
                # field_key.md). `_abspath` (already computed just above
                # for `_ap_key`) is canonical regardless of which
                # candidate matched, so `#line 1 "{...}"`
                # (gimple_module_gen.py) is stable either way. Observed
                # before this fix: `#line 1 "./module_loader.py"` on one
                # self-hosted `mojoc fire.py --dump-full` run vs the real
                # absolute path on the next, for the identical invocation.
                temp_gen._current_filename = _abspath  # Set filename for #line directives
                temp_gen._compiled_modules = gen._compiled_modules
                temp_gen._inline_module_qualifiers = gen._inline_module_qualifiers
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
                # share: definition-side free-function signature truth —
                # only the DEFINING unit writes it (its `_local_def_pts`
                # resolution), every importer reads it FIRST when hashing a
                # mangled call-site suffix, so both halves of one mangled
                # symbol always agree (log_match c52cbf-vs-7a6366 family).
                temp_gen._home_def_param_types = gen._home_def_param_types
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
                temp_gen._emitted_singletons = gen._emitted_singletons
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
                temp_gen.func_param_types = gen.func_param_types  # share across gens (mirrors func_return_types) — cross-module __init__ arg coercion
                # share: the self-host GimpleGen registry seed (parsed
                # `class GimpleGen` StructDef + the extracted-helper field
                # union + the frozen-signature flag). Read-only; every nested
                # temp_gen routes the same StructDef through its own
                # `_imported_typedef_structs` so `self`/`gen` params type
                # consistently. See gimple_codegen._selfhost_register_gimplegen.
                # EXPLICIT per-attribute copies, NOT the former
                # `for _sh_attr in ('_selfhost_gimplegen_stmts', ...):
                # hasattr(gen, _sh_attr) / setattr(temp_gen, _sh_attr, ...)`
                # loop: iterating a tuple of STRING literals boxes `_sh_attr`
                # to int64_t on the self-hosted path, so `hasattr(gen,
                # <boxed>)` was False for every entry and NO nested temp_gen
                # ever inherited `_selfhost_gimplegen_stmts`/`_sigs` — the
                # frozen GimpleGen signature table (362 entries on the
                # reference) was EMPTY in every nested temp_gen, so the
                # `GimpleGen__*` method externs (gimple_module_gen.py's
                # `_imported_typedef_structs` loop) were never emitted and
                # `./mojoc fire.py --dump-full` diverged from the python3
                # reference at the first `#ifndef _MOJO_STUB_GimpleGen_...`
                # block. Verified by file-tracing: reference
                # `stmts_none=0 nsigs=362` in all 36 gens, self-hosted
                # `stmts_none=1 nsigs=0` in 34 of 35.
                if hasattr(gen, '_selfhost_gimplegen_stmts'):
                    temp_gen._selfhost_gimplegen_stmts = gen._selfhost_gimplegen_stmts
                if hasattr(gen, '_selfhost_gimplegen_extra_fields'):
                    temp_gen._selfhost_gimplegen_extra_fields = gen._selfhost_gimplegen_extra_fields
                if hasattr(gen, '_selfhost_gimplegen_registered'):
                    temp_gen._selfhost_gimplegen_registered = gen._selfhost_gimplegen_registered
                if hasattr(gen, '_selfhost_gimplegen_sigs'):
                    temp_gen._selfhost_gimplegen_sigs = gen._selfhost_gimplegen_sigs
                if hasattr(gen, '_selfhost_gimplegen_dict_vts'):
                    temp_gen._selfhost_gimplegen_dict_vts = gen._selfhost_gimplegen_dict_vts
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
                # share: "is this bare name a recognized imported MODULE"
                # (gimple_codegen.py __init__) -- an ALREADY real instance
                # attribute (not a bare local) that was never added to this
                # sharing block, same bug class as `_auto_stubbed` above. A
                # nested temp_gen with its own fresh, empty copy forgets
                # that e.g. `ownership_destruct` was imported as a module
                # in the enclosing context, so `ownership_destruct.analyze_
                # function(...)` (a real, correctly-resolved module-
                # qualified call everywhere else) gets misread as a method
                # call on an unknown local (inferred int64_t) and silently
                # auto-stubbed instead -- confirmed directly: self-hosted
                # `--dump t_list.mojo` then finds 0 ownership-free
                # candidates where python3 finds 1, a real stage1-vs-
                # stage2 `make bootstrap` divergence (missing `mojo_
                # cleanup_push_list`/`mojo_list_free`/`mojo_cleanup_
                # cancel_n` in t_list.ci).
                temp_gen._module_alias_names = gen._module_alias_names
                # share: the "unresolved import" stub-declaration dedup set
                # (see its own declaration in gimple_codegen.py __init__)
                # -- must be shared like _module_globals/_module_global_
                # inits just above, or each of a heavily-referenced
                # symbol's many importing fragments re-emits its own copy.
                temp_gen._emitted_unresolved_stub_syms = gen._emitted_unresolved_stub_syms
                # share: the "auto-stub a not-yet-resolved struct method"
                # dedup set (gimple_gen_methods.py's `_lower_struct_
                # method_call`) -- ALREADY a real instance attribute (not
                # a bare local), but never added to this sharing block,
                # so every nested temp_gen got its own fresh, empty copy
                # instead of sharing the root's. Confirmed as the actual
                # cause of a heavily-referenced class (e.g. GimpleGen
                # itself, ~363 methods) getting its auto-stub declarations
                # re-emitted once per importing fragment (~56x, 20328
                # total occurrences for 363 unique names in a real
                # `fire.py --dump-full`) -- each fragment's own empty set
                # independently concluded "I haven't stubbed this yet".
                temp_gen._auto_stubbed = gen._auto_stubbed
                # NOTE: `_elaborated_externs` (gimple_codegen.py __init__)
                # is deliberately NOT shared here, despite looking like an
                # obvious candidate (it's where GimpleGen's own ~363
                # method stub declarations get recorded as "already
                # emitted", and unshared it's the actual cause of those
                # stubs being re-emitted once per importing fragment --
                # confirmed directly). Sharing it makes things WORSE, not
                # better: gen_module_impl's own emission of this list
                # (`for _decl in self._elaborated_externs: parts.append(
                # _decl)`) runs ONCE PER FRAGMENT and dumps the list's
                # ENTIRE CURRENT CONTENTS every time, not just entries
                # added since that fragment's own last check -- sharing
                # the list so it keeps growing across fragments means
                # EACH LATER fragment's own emission re-dumps everything
                # every EARLIER fragment already emitted too, compounding
                # the duplication instead of fixing it (confirmed: total
                # occurrences went UP, 20328 -> 26136, when this sharing
                # line was tried). The actual fix is a POST-PROCESSING
                # dedup of the final assembled text (see gimple_codegen.
                # _dedup_guarded_blocks), the same technique already used
                # for the toplev-struct duplication -- not a sharing fix.
                if hasattr(gen, '_global_to_module'):
                    temp_gen._global_to_module = gen._global_to_module  # share global -> module mapping
                # share: async/generator API tables across modules so
                # cross-module async composition (await on an async fn
                # defined in another module) can resolve the callee's
                # API without failing (Phase 5).
                temp_gen._async_api = gen._async_api
                temp_gen._generator_api = gen._generator_api
                temp_gen._generator_method_api = gen._generator_method_api
                # share: the (home-qualifier, fn-name)-keyed cross-module
                # generator registry — every module inlined into this
                # whole-program compile must see every OTHER module's
                # compiled generators, or an aliased import of one (`from
                # a import walk as walk_a`) can't bind to its api at all.
                # _imported_generator_bindings deliberately stays
                # per-instance: each module's import bindings are its own.
                temp_gen._generator_home_api = gen._generator_home_api
                # share: link mode's own link-line accumulators
                # (dylibs/objects the final `fire.py build` link step
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
                # Cross-module generator scalar contracts: share the
                # importing side's collected hints with THIS temp_gen —
                # gen_module applies the entries matching its own
                # module_name right after its _inferred_param_types init
                # (see the merge there), so the generator eligibility pass
                # resolves each unannotated param via _param_ctype from the
                # caller's real char */double instead of int64_t defaults.
                if getattr(gen, '_xmod_gen_param_hints', None):
                    temp_gen._xmod_gen_param_hints = gen._xmod_gen_param_hints
                # Companion list-ELEMENT hints (see _xmod_gen_elem_hints's
                # docstring) — shared identically; the temp_gen merges the
                # entries matching its own module_name into
                # _param_list_elem_types, which _gen_cpp_generator_unit seeds
                # into the coroutine-body emitter's local-elem registry.
                if getattr(gen, '_xmod_gen_elem_hints', None):
                    temp_gen._xmod_gen_elem_hints = gen._xmod_gen_elem_hints

                # Share the struct-__init__ registries by reference and
                # pre-register every StructDef.__init__ reachable in the
                # whole transitive closure BEFORE this module's bodies are
                # lowered. Without this, a cross-module `Class(kw=...)`
                # constructor whose class lives in a not-yet-lowered sibling
                # (e.g. gimple_gen_resolve.py's own
                # `gimple_codegen.GimpleGen(do_imports=True, ...)`) missed
                # `_struct_has_init`, fell to _lower_struct_constructor's
                # field-assignment fallback, and emitted `_alloc_GimpleGen()`
                # + raw field stores with NO `GimpleGen___init__(...)` call —
                # so every dict field (`_actual_types`, `_module_stmts`, ...)
                # stayed NULL and the shimless `--dump-full` SIGSEGV'd in
                # `_dict_set_raw_seq_kind`. (Invisible until now because
                # `stage2/mojo --dump-full` is shimmed to python3 in
                # `make bootstrap`.)
                temp_gen._struct_has_init = gen._struct_has_init
                temp_gen._struct_init_params = gen._struct_init_params
                temp_gen._struct_init_defaults = gen._struct_init_defaults
                temp_gen._struct_method_names = gen._struct_method_names
                _register_closure_struct_inits(gen, stmts)

                # A3 stack-switch coroutine lowering for this SIBLING module
                # too (mirrors _run_pipeline's own call). Without it, a
                # generator defined in an imported module still goes through
                # the gimple_cpp_* path while the root module's went through
                # gimple_gen_coro -- a split that leaves the client .c
                # referencing symbols nobody defines.
                stmts, _ss_meta = gimple_codegen.gimple_gen_coro.lower(stmts)
                if _ss_meta:
                    gimple_codegen.gimple_gen_coro.register(temp_gen, _ss_meta)

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
                # `print`, NOT `sys.stderr.write`: the self-hosted backend
                # has no lowering for `sys.stderr.write` (it faults —
                # `mojo_subprocess_stderr` deref of a NULL handle), so on a
                # shimless `--dump-full` a module whose compile legitimately
                # raises (and is meant to fall back to source inclusion via
                # the rollback below) instead crashed the whole run inside
                # this handler. `print(..., flush=True)` is the diagnostic
                # channel that works in the compiled binary.
                print(f"# ERROR: compiling imported module {module_name!r} from {path}: {e}", flush=True)
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
                for _n in list(gen._funcptr_builtins_needed - funcptr_needed_before):
                    gen._funcptr_builtins_needed.discard(_n)
                for _e in list(gen._emitted_funcptr_builtins - funcptr_emitted_before):
                    gen._emitted_funcptr_builtins.discard(_e)
                # doc/OWNERSHIP_MODEL.md Phase 3's per-function state
                # (gimple_gen_infra.py's begin_function/_owned_free_
                # candidates) is NOT tied to modules_before/etc like the
                # sets above, but a failed nested-module compile attempt
                # can still have called begin_function for some function
                # inside the module that just failed, leaving `gen.
                # _owned_free_candidates`/`_owned_free_pushed`/`_owned_
                # stack_allocated` pointing at sets built during (and
                # scoped to) that now-abandoned compile attempt. Whatever
                # code runs next (this module's own outer function, or
                # the next sibling) must not see that stale state — reset
                # exactly like `reset_no_candidates` does for a
                # struct-method/toplevel body this analysis doesn't
                # cover. Found via a real, reproducible `make bootstrap`
                # crash: `mojo_set_update` dereferencing a `MojoSet *`
                # whose bytes were garbage, immediately downstream of a
                # "cannot compile module: ... is ambiguous" rollback.
                gen._owned_free_candidates = set()
                gen._owned_free_pushed = set()
                gen._owned_stack_allocated = set()
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
        # Guard BEFORE calling load_module, not just try/except around it:
        # this codegen's compiled try/except does not reliably catch a
        # raised exception, so a sibling `.py` compiler module (not under
        # STDLIB_PATH/TEST_PATH) reached module_loader's `raise ValueError
        # ("Only stdlib and test imports supported")` UNCAUGHT. See
        # ModuleLoader.can_resolve_module_path's docstring.
        import module_loader as _mlmod_exp
        if not _mlmod_exp.can_resolve_module_path(module):
            return {}, False, _sib_path
        try:
            return gimple_ctypes.load_module(module), False, _sib_path
        except Exception as e:
            gimple_ctypes._debug_note(f'load_module({module!r}) failed; treating module as empty', e)
            return {}, False, _sib_path

    def scan(stmt_list):
        for stmt in stmt_list:
            if isinstance(stmt, gimple_ctypes.FromImportStmt):
                exports, from_reflection, source = _exports(stmt.module)
                for _fip11 in (getattr(stmt, 'name_alias_strs', None) or []):
                    name = gimple_ctypes._fi_name(_fip11)
                    alias = gimple_ctypes._fi_alias(_fip11)
                    info = exports.get(name)
                    sym = alias if alias else name
                    # Overload registration must NOT be gated on `not info`:
                    # `exports`/`info` (the dylib-reflection or source-scan
                    # ABI lookup) records exactly ONE signature per bare
                    # name, so a genuinely overloaded free function (two-plus
                    # `def <name>(...)` in `source` with different param
                    # types — e.g. pwd/_macos.mojo's `_getpw_macos(uid:
                    # UInt32)` / `_getpw_macos(var name: String)`) still gets
                    # an `info` hit (for whichever overload the ABI/scan
                    # happened to pick, almost always the first declared),
                    # which used to short-circuit the `if not info:` block
                    # below — the ONLY place that ever populated
                    # `_imported_overloads` — so `_elaborate_overload_call`'s
                    # per-call-site signature match (gimple_gen_calls.py)
                    # never even ran. Every call site then fell through to
                    # the generic single-signature path, which always
                    # emitted a call to THAT ONE cached signature's mangled
                    # symbol regardless of the actual argument types —
                    # `pwd.getpwnam(name: String)`'s `_getpw_macos(name)`
                    # silently called the `(UInt32)`-parameter overload,
                    # truncating the `char *` argument to `uint32_t` (a real
                    # `-Wpointer-to-int-cast` warning and a wrong value, not
                    # just a diagnostic). Scanning for and registering
                    # overloads FIRST, unconditionally, lets the real
                    # per-call-site resolution run whenever the source
                    # genuinely defines more than one `<name>(...)`, with
                    # `info` still available below for every other
                    # (non-overloaded) import.
                    if source:
                        try:
                            _ov_src = open(source).read()
                        except Exception:
                            _ov_src = ''
                        if len(gimple_ctypes.re.findall(
                                rf'\b(?:fn|def)\s+{gimple_ctypes.re.escape(name)}\s*\(', _ov_src)) > 1:
                            gen._imported_overloads.setdefault(sym, source)
                    # Record the module source for any imported name, so a
                    # comptime call to it can be evaluated at compile time.
                    if source:
                        gen._imported_fn_sources.setdefault(name, source)
                    if not info:
                        # Not a concrete export — if this is a bare `from
                        # PKG import SUBMODULE` (module marker, not a
                        # symbol defined inside PKG's own source), the
                        # submodule's own top-level functions/globals must
                        # still be lowerable if later read as a plain VALUE
                        # off the marker (`isfuture = base_futures.
                        # isfuture` — a real function bound to a module-
                        # level name, not called). Phase 0 registration
                        # (gimple_module_gen.py's FromImportStmt scan)
                        # already binds the marker itself into
                        # `imported_symbols`, which is all a CALL through
                        # it needs (`base_futures.isfuture(...)`, routed by
                        # `_lower_method_call`'s import-aware path) — but a
                        # bare-value read goes through `_lower_MemberExpr`'s
                        # `node.member in gen.func_return_types` branch,
                        # which stays empty for the submodule's functions
                        # unless something actually compiles/registers
                        # them. Route through the existing `_link_inline_
                        # modules` fallback (same mechanism the generic-
                        # struct/fn-not-resolved branches below already use
                        # for a module this scan couldn't otherwise link
                        # against) — it inline-compiles the submodule into
                        # this same translation unit, which naturally
                        # populates func_return_types for all its top-
                        # level defs via the normal imported_stmts
                        # machinery, so no separate reflection/extern-decl
                        # bookkeeping is needed here.
                        if gen._from_import_name_is_submodule(stmt.module, name):
                            gen._link_inline_modules.add(
                                gimple_ctypes._join_import_member(stmt.module, name))
                            continue
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
                    # BUG-2026-029: a module-level global imported from
                    # ANOTHER module (kind 2 / SYM_GLOBAL — reflect.py's
                    # collect_exports). Before this, `g_world` fell all the
                    # way through this scan (no `info` at all — reflect.py
                    # never exported globals) to the generic identifier
                    # resolver's "ct param or undeclared" placeholder,
                    # silently reading as 0 — even with an explicit `from
                    # OtherModule import g_world`. A cross-module global has
                    # no locally-visible struct field to read directly (this
                    # module only sees the OWNING module's globals struct as
                    # an `__attribute__((incomplete))` forward decl) — route
                    # every read through the owning module's real accessor
                    # function instead, reusing the SAME
                    # `_imported_global_accessors` mechanism
                    # `_emit_imported_global_accessors` already populates
                    # for the (narrower, .py-selfhost-only) module_loader
                    # path — `_lower_IdentExpr` already checks it before
                    # falling back to a direct field read, so no read-path
                    # change is needed here, only registration. Deliberately
                    # QUALIFIED by the accessor's own module-prefixed C
                    # symbol (never a bare name) — see this function's
                    # module docstring on the bare-name collision hazard a
                    # sibling fix in this exact area hit and had to revert.
                    if from_reflection and info.get('kind') == 2:
                        seen.add(sym)
                        # The accessor symbol is the last token before '('
                        # in the advertised signature — same extraction
                        # reflect.py's own `export_csym` uses for every
                        # non-SYM_FUNCTION kind (methods, and now globals).
                        gsym = info['signature'].split('(', 1)[0].strip().split()[-1].lstrip('*')
                        # Register (and extern-declare) the accessor as
                        # returning `void *`, NOT the struct type reflect.py
                        # advertised (e.g. `World *`) — this importing
                        # translation unit has no `struct World { ... }`
                        # declaration at all (a SYM_GLOBAL export carries no
                        # field-layout information, unlike a SYM_TYPE import,
                        # which DOES bring one via `_register_reflected_
                        # struct`), so an extern decl naming the real struct
                        # type is a hard "unknown type name 'World'" compile
                        # error. `void *` is sufficient for every currently
                        # supported use of a cross-module global (BUG-2026-
                        # 029's own repro: `Int64(addr(g_world))`/
                        # `Int64(g_world)`, both of which only need the
                        # pointer's BITS — see `_lower_scalar_ctor`'s and the
                        # `addr` builtin's `at.endswith(' *')` checks, which
                        # accept any pointer type). Genuine cross-module
                        # FIELD access on an imported global (`g_world.x`)
                        # remains unsupported either way — that needs the
                        # struct's real layout imported too, a larger,
                        # separate feature.
                        gen._imported_global_accessors[sym] = ('void *', gsym)
                        guard = gimple_ctypes._stub_guard_name(gsym)
                        decls.append(
                            f'#ifndef {guard}\n#define {guard}\n'
                            f'extern void * {gsym} (void);\n#endif')
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
    for ename in exports:   # not `.items()` — 2-tuple unpack boxes the key
        einfo = exports[ename]
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
    # `_as_str(ctype)` — a CHOKEPOINT guard, deliberately here rather than at
    # the hundreds of call sites. A C type is a plain `str`, and this backend
    # erases an uninferable `str` to int64_t; a caller that hands one over
    # would have its ADDRESS written as the declaration's type:
    #     47303466400 * _t34;          /* should be `Parser * _t34;` */
    # which is invalid C and different on every run (ASLR).
    ctype = _as_str(ctype)
    gen.temp_counter += 1
    name = f"_t{gen.temp_counter}"
    gen.decls.append(f"  {gimple_ctypes._c_var_decl(ctype, name)};")
    gen.var_types[name] = ctype
    return name


def _new_val(gen, ctype: str, rhs: str) -> str:
    """Alloc a GIMPLE temp, emit `t = rhs`, return t."""
    # Determinism-trace chokepoint: every emitted value flows through here,
    # so a per-call iota+xorshift64 step sees the first divergent value with
    # no other instrumentation. Entropy is CONTENT only (the ctype's and the
    # rhs text's stable hashes) — never an address — so two runs that agree
    # produce identical streams and diff lands on the first real divergence.
    # Dead branch when MOJO_TRACE is unset (the default).
    if _dtrace.enabled():
        _dtrace.note(_dtrace.str_hash(_as_str(ctype)) ^ _dtrace.str_hash(rhs))
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
    # substitution` (~22 occurrences in a `fire.py build
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
    # Same chokepoint guard as _new_temp: these two are C TYPE text, and an
    # erased one is emitted as its own address in the cast written below.
    src = _as_str(src)
    dst = _as_str(dst)

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
    # A bare identifier LHS naming a local `_seed_addressed_locals` has
    # flagged (its address gets taken somewhere in this function via
    # `UnsafePointer(to=x)` — see that pass's docstring): needs the
    # IDENTICAL "coerce into a register temp first, then a plain (no
    # embedded cast) store" treatment as a struct-field/deref LHS, for
    # the same underlying `-fgimple` reason — a cast expression's result
    # can't be stored directly into an ADDRESSABLE variable either, not
    # just through a COMPONENT_REF/INDIRECT_REF (confirmed via std/gpu/
    # host/device_context.mojo's `var result: Int32 = 0` — an initial
    # cast-assignment INTO an addressed local, happening before its own
    # `UnsafePointer(to=result)` a few lines later — see bugs/CODEGEN_
    # unsafepointer_to_kwarg_dropped.md).
    is_addressed = lhs in getattr(gen, '_addressed_locals', ())
    val_is_literal = val.startswith('"') or val.startswith("'") or (
        val.lstrip('-').replace('.','',1).isdigit())  # All numeric strings including single digits
    needs_temp = is_field or is_deref or is_addressed

    if needs_temp:
        t = gen._new_temp(dst)
        _sce_simple_emit(gen, t, val, src, dst)
        gen._emit(f'  {lhs} = {t};')
    else:
        _sce_simple_emit(gen, lhs, val, src, dst)


def _sce_simple_emit(gen, dest: str, v: str, s: str, d: str) -> None:
    """Hoisted out of `_safe_coerce_emit` (was a nested closure showing the
    lifted-closure-env call-site arity flip) — `gen` threaded."""
    if (s != d and s in gimple_ctypes._CONTAINER_KIND_TYPES
            and d in gimple_ctypes._CONTAINER_KIND_TYPES):
        # DESIGN.html R2: these are distinct, non-layout-compatible runtime
        # structs (MojoDict/MojoList/MojoSet/MojoBytes each have their own
        # slot layout) — a cast between them is not a conversion, it is
        # reinterpreting one struct's memory as another's. This is the
        # chokepoint every coercion already passes through; refusing here
        # turns a wrong container-kind inference (previously a 26ms SIGBUS
        # 34GB past a slot array, see ast_rewriter.py's `bindings`) into an
        # immediate build-time error naming both types and the value.
        filename = getattr(gen, '_current_filename', '') or '<unknown>'
        line = getattr(gen, '_current_line', None)
        loc = f'{filename}:{line}' if line else filename
        raise TypeError(
            f'cannot coerce {s} to {d} (incompatible container kinds) '
            f'at {loc}: value={v!r} dest={dest!r}')
    if True:
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
            # Found via fire_compiler.py's own
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


def _param_safe_name(gen, bare: str) -> str:
    """The C identifier a function/method/closure PARAMETER named `bare`
    should actually be declared under, avoiding two distinct C-level name
    collisions real Mojo source can trigger:

    1. An ordinary C keyword/reserved word (`_kw_` prefix, pre-existing).
    2. A STRUCT TYPEDEF NAME (`_parm_` prefix, this case): every compiled
       struct emits `typedef struct X X;`, and C keeps typedef names and
       ordinary identifiers in ONE namespace — a parameter named `A` when
       a struct `A` exists SHADOWS that typedef for the rest of the
       function. Every later `A * <local>;`-shaped declaration inside the
       function body (e.g. a local of type `A *`) is then misparsed as an
       expression (`A * <local>` = multiply undeclared `<local>` by the
       parameter `A`) instead of a declaration, cascading into
       "undeclared" errors at every subsequent use of that local. Real:
       CPython's own Tools/scripts/var_access_benchmark.py defines `def
       read_classvar_from_instance(trials=trials, A=A):` — deliberately
       shadowing global class `A` with a same-named parameter (to
       benchmark local vs. global attribute access uniformly across
       sibling functions). Renaming just the C-level parameter identifier
       (not the struct/typedef, and not any bare-name struct/class LOOKUP
       elsewhere in this codegen) is sufficient here: `_cname`/`_c_names`
       already retarget every read/write of the Mojo-level name `bare`
       inside this function's body to the renamed C identifier, so the
       struct typedef `A` stays visible and usable throughout — nothing
       about actual struct/class name RESOLUTION changes, only which raw
       C token a value read from the parameter itself is stored under."""
    if bare in gimple_ctypes._C_KEYWORDS or bare in gimple_ctypes._C_PARAM_EXTRA_KEYWORDS:
        return f'_kw_{bare}'
    if bare in gen.struct_field_types:
        return f'_parm_{bare}'
    return bare


def _cname(gen, name: str) -> str:
    """Translate a Python variable name to its C name (handles C keyword renaming)."""
    return gen._c_names.get(name, name)


def _record_closure_alias(gen, result: dict, tgt: str, val):
    """Record `tgt`'s C type when `val` is a bare reference to a nested
    (closure) function. Kept as a top-level helper so `val` usage-infers to
    a pointer instead of the `int` a `None`-initialized local would get."""
    if tgt in result or not isinstance(val, gimple_ctypes.IdentExpr):
        return
    _ci = gen._closure_info_for_ident(val.name)
    if _ci is not None:
        result[tgt] = 'MojoBoundMethod *' if _ci.env_struct else 'void *'


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
            # NB: keep the target-name / value pair off local vars that get
            # a `None` initializer — the self-hosted backend types those
            # `int`, which truncates the char*/AST-node pointer and makes
            # the `isinstance(val, IdentExpr)` tag read segfault. Route
            # straight through a helper whose params usage-infer to pointers.
            if isinstance(st, gimple_ctypes.AssignStmt) and isinstance(st.target, gimple_ctypes.IdentExpr):
                _record_closure_alias(gen, result, st.target.name, st.value)
            elif (isinstance(st, gimple_ctypes.VarDecl) and isinstance(st.name, str)
                    and ',' not in st.name and st.value is not None):
                _record_closure_alias(gen, result, st.name, st.value)
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
    if isinstance(node, gimple_ctypes.StringLiteral):
        return 'MojoBytes *' if getattr(node, 'is_bytes', False) else 'char *'
    if isinstance(node, gimple_ctypes.IdentExpr):
        if node.name in gen.var_types:
            return gen.var_types[node.name]
        if node.name == '__file__':
            # Mirrors _lower_IdentExpr's own '__file__' case, which always
            # yields a char* interned literal ("<bootstrap>") — without
            # this, the estimator guessed int64_t and mis-typed consumers
            # that consult it BEFORE lowering (e.g.
            # _lower_opaque_ctor's single-char*-arg identity passthrough).
            return 'char *'
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
        # (address 0x1). Found chasing self-hosted fire.py evaluating
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
        _BUILTIN_CTORS = {'set': 'MojoSet *', 'dict': 'MojoDict *', 'list': 'MojoList *',
                          # sorted()/reversed() both materialise a MojoList*
                          # (see _lower_builtin_sorted / _lower_builtin_reversed).
                          'sorted': 'MojoList *'}
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
        # Same construction-shape rule for a generator reached through an
        # ALIASED/qualified cross-module import (`from a import walk as
        # walk_a`): the binding table records exactly the names THIS module
        # imported as compiled generators, so `var g = walk_a("x")` quick-
        # types to the same opaque MojoGenerator* a local definition would.
        if fname in getattr(gen, '_imported_generator_bindings', ()):
            return 'MojoGenerator *'
        # Scalar type constructors (Float64(x), Int8(x), etc.) — checked
        # BEFORE the opaque single-char*-arg passthrough just below, which
        # would otherwise wrongly claim a call like `Float64("not a
        # float")` (same shape: one char*-typed arg, uppercase name) as an
        # opaque-class passthrough and infer `char *` instead of the real
        # `double` — mis-declaring the assignment target and producing an
        # invalid `(char *)<double value>` cast downstream. Mirrors
        # gimple_gen_calls.py's `_lower_scalar_ctor` dispatch exactly (same
        # shared table + same not-shadowed gate), since that's what the
        # actual lowering does for this shape.
        if (fname in gimple_ctypes._SCALAR_CTORS and fname not in gen.func_return_types
                and fname not in gen.imported_symbols):
            return gimple_ctypes._SCALAR_CTORS[fname]
        # Single-char*-argument OPAQUE-constructor passthrough (`Path(x)`
        # where `Path` is an imported class this compile never inlined):
        # _lower_opaque_ctor returns its single string argument UNCHANGED
        # for this exact shape (the strings-as-path-values convention `/`
        # on a char* receiver already relies on), so the estimator must
        # mirror that or every consumer of this pre-pass (global/local
        # variable typing, return-type inference) mis-declares the result
        # int64_t against a body that produces a real char*.
        if (fname[:1].isupper() and fname not in gen.func_return_types
                and fname not in gen.imported_symbols
                and not gen._locally_binds_name(fname)
                and len(node.args) == 1 and not getattr(node, 'kwargs', None)
                and gen._quick_type(node.args[0]) == 'char *'):
            return 'char *'
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
        # `Path(x).resolve()` (no-arg) on a path-shaped char* receiver —
        # real char* result (POSIX realpath via int64_t_realpath, see
        # _lower_str_method's 'resolve' case); quick-type mirrors it so
        # chained shapes like `Path(f).resolve().parent` type the whole
        # chain correctly.
        if (node.func.member == 'resolve' and not node.args
                and gen._quick_type(node.func.obj) == 'char *'):
            return 'char *'
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
            # `with open(input_file) as f: src = f.read()` in fire.py's
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
            if mod == 'os' and meth == 'listdir': return 'MojoList *'
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
        # `os.path.splitext(os.path.basename(input_file))[0]` in fire.py's
        # build_executable: the parameter fix above still left this local
        # variable declared int64_t (a real char* pointer value shown as
        # a raw address by print()).
        elif (isinstance(node.func.obj, gimple_ctypes.MemberExpr)
                and isinstance(node.func.obj.obj, gimple_ctypes.IdentExpr)
                and node.func.obj.obj.name == 'os' and node.func.obj.member == 'path'):
            if node.func.member in ('basename', 'expanduser'):
                return 'char *'
            if node.func.member in ('splitext', 'split', 'splitdrive', 'splitroot'):
                # All string-tuple results in this codegen's model —
                # splitext -> [root, ext] (int64_t_splitext + a built list),
                # split -> [head, tail] (int64_t_path_split),
                # splitdrive -> [drive, tail], splitroot -> [drive, root, tail].
                return 'MojoList *'
        # Chained string methods, e.g. `s.replace(a, b).replace(c, d)` —
        # the receiver here is itself a CallExpr (the inner .replace()),
        # not a plain IdentExpr, so the `isinstance(node.func.obj,
        # IdentExpr)` branch above never matches this shape at all. Same
        # class of gap as the os.path.* chained case just above: without
        # this, format_token()'s `tok.value.replace(...).replace(...)`
        # (fire_compiler.py's own tokenizer dump helper) declared its
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
                   or _sms_key(sn, node.member) in gen._struct_method_signatures):
            candidates = gen._struct_method_signatures.get(_sms_key(sn, node.member))
            overload_id = ''
            if candidates and len(candidates) == 1:
                overload_id = candidates[0].get('overload_id', '') or ''
            mangled = gen._struct_method_csym(sn, node.member, overload_id)
            return gen.func_return_types.get(
                mangled, gen.func_return_types.get(f"{sn}_{node.member}", 'int64_t'))
        # pathlib.Path attribute reads on a path-shaped char* value —
        # `.name` is basename and `.parent` is dirname, both real char*
        # results (see _lower_MemberExpr's matching char*-receiver case).
        if ot == 'char *' and node.member in ('name', 'parent'):
            return 'char *'
        return 'int64_t'
    if isinstance(node, gimple_ctypes.ListExpr):  return 'MojoList *'
    if isinstance(node, gimple_ctypes.DictExpr):  return 'MojoDict *'
    if isinstance(node, gimple_ctypes.SetExpr):   return 'MojoSet *'
    if isinstance(node, gimple_ctypes.TupleExpr): return 'MojoList *'
    if isinstance(node, gimple_ctypes.Comprehension):
        # `[x for x in y]`/`{k: v for ...}`/`{x for x in y}`/a
        # generator-expression — a distinct AST node from the literal
        # ListExpr/DictExpr/SetExpr cases just above (fire_compiler.py),
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
        # Real bug found via `input_file = sys.argv[1]` in fire.py's own
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
                and obj.func.member in ('splitext', 'split', 'splitdrive', 'splitroot')):
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
    # Annotated as a real dict: `inferred` is captured by the nested
    # `collect_assigned_types` closure (passed through its lifted env
    # struct), and an unannotated `{}` left that env field / the closure's
    # writes typed int64_t on the self-hosted path, corrupting the dict so
    # the later `for vname in inferred:` SIGSEGV'd in
    # `mojo_dict_iter_key` (`it->dict->slots[it->order[...]]`) while
    # compiling `./mojoc fire.py --dump-full`.
    inferred: dict[str, list] = {}

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
                # A FRESH local (`_as_node`), not a reassignment of `node`
                # itself: `node` is the shared `for node in nodes:` loop
                # variable, whole-function-unified to whatever ambient type
                # its OTHER uses across every branch settle on (opaque
                # int64_t, since `nodes` is a heterogeneous statement list)
                # — rebinding the SAME name here does not give it a fresh,
                # independent static type. A brand-new name bound only to
                # `_as_assignstmt_node(node)`'s annotated return type gets
                # its own real `AssignStmt *` typing.
                _as_node = _as_assignstmt_node(node)
                # Use _quick_type instead of lower_expr to avoid incomplete var_types
                if isinstance(_as_node.target, gimple_ctypes.TupleExpr):
                    targets = _as_node.target.elements
                    # Type each unpack target by its own value, never by the
                    # whole RHS: _quick_type(a_tuple) is 'MojoList *', which would
                    # wrongly poison scalar unpack targets (e.g. start, stop, step
                    # = ivals[0], ivals[1], ivals[2]).
                    if (isinstance(_as_node.value, gimple_ctypes.TupleExpr)
                            and len(_as_node.value.elements) == len(targets)):
                        elem_types = [gen._quick_type(e) for e in _as_node.value.elements]
                    else:
                        # Unpacking a single iterable: per-element type is
                        # unknown here; use the int64_t storage default.
                        # EXCEPT `text, is_fstring = ..._decode_str_literal_
                        # text(...)`, which returns `(char*, char*)` — the
                        # `is_fstring` slot is genuinely a "" / "1" STRING
                        # (see that helper's own docstring). Pre-typing it
                        # int64_t here re-boxed the per-slot get_str result
                        # into an int64_t local, so `if not is_fstring:`
                        # tested pointer-non-null and an empty-string ""
                        # pointer (non-null) read as truthy → every plain
                        # literal took the f-string path and lost its text.
                        _cv = _as_node.value
                        _is_decode = (
                            isinstance(_cv, gimple_ctypes.CallExpr)
                            and isinstance(_cv.func, gimple_ctypes.MemberExpr)
                            and _cv.func.member == '_decode_str_literal_text')
                        elem_types = [('char *' if _is_decode else 'int64_t')] * len(targets)
                else:
                    targets = [_as_node.target]
                    elem_types = [gen._quick_type(_as_node.value)]
                # Index both lists in parallel — `for target, vtype in
                # zip(targets, elem_types)` unpacks a zip 2-tuple, the
                # established boxing bug.
                for _zi in range(min(len(targets), len(elem_types))):
                    target = targets[_zi]
                    vtype = _as_str(elem_types[_zi])
                    if isinstance(target, gimple_ctypes.IdentExpr):
                        vname = _as_str(target.name)
                        if vname not in inferred:
                            inferred[vname] = []
                        inferred[vname].append(vtype)
            elif (isinstance(node, gimple_ctypes.VarDecl) and isinstance(node.name, str)
                    and ',' not in node.name):
                # Fresh local, not a `node` reassignment — see the
                # AssignStmt branch's identical comment above.
                _vd_node = _as_vardecl_node(node)
                # `var out = self._buf[a:]` — a VarDecl, not an AssignStmt.
                # Historically this pass "never scans VarDecl" (see
                # _closure_value_locals' docstring), so a `var`-declared
                # local's type fell to the int64_t default, breaking
                # `return out` return-type inference and the local's own
                # declared C type when the initializer is a pointer value
                # (bytes accumulator, sliced field, ...).
                vname = _as_str(_vd_node.name)
                # Empty-string sentinel, NOT `None`: an explicit `_vt: str |
                # None = None` annotation here was NOT enough — this local
                # lives inside a doubly-nested closure (collect_assigned_
                # types nested inside _infer_local_var_types), and that
                # scope's own C-type inference does not honor a local
                # variable's annotation the way parameter annotations are
                # honored elsewhere in this file; it still settled on plain
                # `int` (from the `= None` assignments), and every real
                # `_mojo_type(...)`/`_quick_type(...)` char* result then got
                # TRUNCATED to 32 bits storing into that narrower slot —
                # corrupting the pointer. The later `_vt == 'int64_t'`
                # string compare then read the truncated address and
                # SIGSEGV'd in strcmp, on virtually any VarDecl with a type
                # annotation (i.e. almost any compiled program). Using ''
                # instead of `None` for "unset" keeps every assignment to
                # `_vt` a genuine `char *` literal/result, so there is no
                # int-vs-pointer ambiguity left for the inferencer to get
                # wrong.
                _vt = ''
                if getattr(_vd_node, 'type_ann', None):
                    try:
                        _vt = gimple_ctypes._mojo_type(_vd_node.type_ann)
                    except Exception:
                        _vt = ''
                if (not _vt or _vt == 'int64_t') and _vd_node.value is not None:
                    _vt = gen._quick_type(_vd_node.value)
                if _vt:
                    inferred.setdefault(vname, []).append(_vt)
            elif isinstance(node, gimple_ctypes.MultiAssignStmt):
                # Fresh local, not a `node` reassignment — see the
                # AssignStmt branch's identical comment above.
                _ma_node = _as_multiassignstmt_node(node)
                # `a = b = ... = expr` (chained assignment): every target
                # receives the SAME value/type (real Python chained-
                # assignment semantics), unlike AssignStmt's TupleExpr
                # unpack case above. Was entirely unhandled here — every
                # target of a chained assignment fell through to this
                # scan's int64_t default regardless of the RHS's real
                # type. See bugs/hard/CODEGEN_multi_assign_local_var_
                # type_not_inferred.md.
                vtype = gen._quick_type(_ma_node.value)
                for target in _ma_node.targets:
                    if isinstance(target, gimple_ctypes.IdentExpr):
                        vname = _as_str(target.name)
                        if vname not in inferred:
                            inferred[vname] = []
                        inferred[vname].append(vtype)
            elif isinstance(node, gimple_ctypes.IfStmt):
                collect_assigned_types(node.then_body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
                for _elif in node.elifs:  # index, not unpack — tuple-boxing bug
                    collect_assigned_types(_elif[1])
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
                vname = _as_str(node.value.name)
                if vname not in inferred:
                    inferred[vname] = []
                inferred[vname].append(gen._quick_type(node.value.value))

    try:
        collect_assigned_types(func.body)
    finally:
        gen.var_types = _saved_var_types

    # Join all types for each variable using TypeLattice
    result: dict[str, str] = {}
    for vname in inferred:
        types = inferred[vname]
        if types:
            result[_as_str(vname)] = gimple_ctypes.TypeLattice.join_all(types)

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
    """Walk ONE statement, appending every reachable CallExpr to out.

    A FAITHFUL translation of the old `for attr in ('value','condition',
    'iterable'): ... / for attr in ('body','then_body','else_body',
    'finally_body'): if isinstance(sub, list): ...` loop into explicit
    per-node-type branches — same node coverage, same recursion, NOTHING
    added (in particular NOT `WithStmt.items`). The old form used
    `getattr(n, <runtime-attr-name>)` + `isinstance(sub, list)`, and on
    the self-hosted path a dynamic getattr yields int64_t while
    `isinstance(<int64_t>, list)` is the always-false runtime stub — so it
    never recursed into ANY control flow and the cross-call scalar
    contract missed every call site nested inside an `if`/`try`."""
    # ── the `value`/`condition`/`iterable` expression sweep ──
    if isinstance(n, (ExprStmt, ReturnStmt, AssignStmt,
                      AugAssignStmt, MultiAssignStmt, RaiseStmt, AssertStmt,
                      VarDecl, ComptimeVarStmt)):
        _v = getattr(n, 'value', None)
        if _v is not None:
            gen._collect_calls(_v, out)
    if isinstance(n, (IfStmt, WhileStmt)):
        gen._collect_calls(n.condition, out)
    elif isinstance(n, ForStmt):
        gen._collect_calls(n.iterable, out)
    # ── the body-list recursion sweep ──
    if isinstance(n, IfStmt):
        gen._calls_in_stmts(n.then_body, out)
        if isinstance(n.else_body, list):
            gen._calls_in_stmts(n.else_body, out)
        for _cond, _eb in (n.elifs or []):
            gen._calls_in_stmts(_eb, out)
    elif isinstance(n, TryStmt):
        gen._calls_in_stmts(n.body, out)
        for _h in (n.handlers or []):
            _hb = getattr(_h, 'body', None)
            if isinstance(_hb, list):
                gen._calls_in_stmts(_hb, out)
        if isinstance(n.else_body, list):
            gen._calls_in_stmts(n.else_body, out)
        if isinstance(n.finally_body, list):
            gen._calls_in_stmts(n.finally_body, out)
    elif isinstance(n, (WhileStmt, ForStmt, WithStmt, FunctionDef)):
        _b = getattr(n, 'body', None)
        if isinstance(_b, list):
            gen._calls_in_stmts(_b, out)
        _eb2 = getattr(n, 'else_body', None)
        if isinstance(_eb2, list):
            gen._calls_in_stmts(_eb2, out)

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


def _parse_fstring_parts(gen, inner: str) -> list[tuple[str, str, str, str]]:
    """Parse f-string body into `(kind, text, spec, conv)` 4-tuples, kind
    being 'lit' or 'expr'.

    The `-> list[tuple[str, str, str, str]]` return annotation is
    load-bearing for the self-hosted compiler: without it every slot but
    the first was typed int64_t, so the consumer (`_lower_StringLiteral`'s
    f-string branch) read each part's TEXT as a boxed pointer, ran
    `_c_escape` on the integer bits, and interned an empty string — every
    compiled-codegen f-string collapsed to `""`."""
    parts: list = []
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
    if rat == 'MojoBytes *':
        return gen._call_expr('char *', 'mojo_bytes_repr', [('MojoBytes *', rav)])
    if rat == 'MojoMemoryView *':
        return gen._call_expr('char *', 'mojo_memoryview_repr', [('MojoMemoryView *', rav)])
    if rat.endswith(' *') or rat == 'void *':
        # Dispatch through the per-struct field-by-field reprs generated
        # in gen_module (see reflect_structs) when the runtime type tag
        # is one this program actually allocates — falls back to the
        # address placeholder (mojo_repr_obj) for anything else, same
        # as before. Real bug found via fire.py's own `--dump`'s
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


def _decode_str_literal_text(gen, val: str) -> tuple[str, str]:
    """Strip a raw StringLiteral.value's f/r/b/u/t prefix and outer quotes,
    returning (text, is_fstring). Shared by plain-string lowering, f-string
    interpolation, and `%`-style string-formatting (which needs the format
    string's literal text at codegen time, before any quoting/escaping)."""
    # Detect and strip f/r/b/u/t prefix — only if followed by a quote character
    # Regular strings have their quotes already stripped by the parser; f-strings
    # and t-strings (template strings — same `{expr}` interpolation syntax,
    # treated identically here) keep prefix+quotes.
    is_fstring = False
    # Index-based prefix walk (was `while val: ... val = val[1:]`). Once
    # self-hosted, a `while` loop that reslices `val = val[1:]` every
    # iteration to shrink it never terminated for an f/r/b-prefixed string
    # (`f"..."`) — the compiled reslice-in-condition-loop didn't make
    # progress, `val[0]` stayed `'f'`, and `_parse_fstring_parts` then spun
    # on a mangled `inner` allocating forever. A single positive slice at
    # the end has no such issue.
    _pfx_end = 0
    while _pfx_end < len(val) and val[_pfx_end] in 'fFrRbBuUtT':
        _pfx_end += 1
    prefix = val[:_pfx_end]
    val = val[_pfx_end:]
    # fire_compiler.py's Parser already strips the outer quotes from a plain
    # (non-f/t-string) StringLiteral's value at tokenize time. So if what's
    # left after the prefix walk does NOT start with a quote, it is a plain
    # string whose content is final — return it verbatim (plus any
    # prefix-like leading chars that turned out to be content, not a
    # prefix). Do NOT re-run the quote strip below: a plain string whose
    # CONTENT happens to start and end with a quote — this file's own
    # `'"'` / `"'"` / `'"""'` / `"'''"` literals, and every user string
    # like `"a "` — would otherwise be mangled ( `'"""'` → `''`, so once
    # self-hosted `"anything".startswith(<that literal>)` matched and every
    # user StringLiteral's text was stripped to "" in the emitted pool ).
    if not val or val[0] not in ('"', "'"):
        return prefix + val, ''
    # A value that is ENTIRELY quote characters (this file's own `'"'` /
    # `"'"` / `'"""'` / `"'''"` literals — content, not delimiters) has no
    # inner text to strip. Return it verbatim. Critical once self-hosted:
    # otherwise `'"""'` -> `'"'` (a single `"`), and since this function's
    # own `val.startswith('"""')` argument then IS just `"`,
    # `"anything".startswith('"')` matched and every user `"..."` /
    # `f"..."` literal got its "triple quotes" stripped
    # (`'"vv={x}"'[3:len-3]` == `'={'`), mangling every f-string body ->
    # `_parse_fstring_parts` spun forever.
    _all_quote = True
    for _c in val:
        if _c != '"' and _c != "'":
            _all_quote = False
            break
    if _all_quote:
        return prefix + val, ('1' if any(c in 'fFtT' for c in prefix) else '')
    # val still carries quotes: an f/t-string (prefix has f/F/t/T) or a
    # triple-quoted value handed back from the placeholder cache.
    is_fstring = any(c in 'fFtT' for c in prefix)
    # `len(val) >= 6` / `>= 2`: a value that IS just quote characters (`"""`,
    # `"`, this file's own such literals) starts and ends with the quote but
    # carries no delimited content — a real `"""x"""` is >= 7 chars (>= 6
    # empty), a real `"x"` is >= 3 (>= 2 empty).
    # `val[1:len(val)-1]` not `val[1:-1]`: a negative slice stop, once
    # self-hosted, resolved wrong on the compiled path (`'"AB={x}"'[1:-1]`
    # came back as a single middle char), which mangled every f-string
    # body.
    _vl = len(val)
    if _vl >= 6 and val.startswith('"""') and val.endswith('"""'):
        val = val[3:_vl - 3]
    elif _vl >= 6 and val.startswith("'''") and val.endswith("'''"):
        val = val[3:_vl - 3]
    elif _vl >= 2 and ((val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'"))):
        val = val[1:_vl - 1]
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
    # numeric-casting. Found via fire_compiler.py's own
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
    return gen._lower_struct_constructor(name, node.args, node.kwargs)


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
    constructs `NoneLiteral`, despite fire_compiler.py defining the
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
    # Bracket-AWARE split, matching every other loop path (_gen_for_list,
    # _gen_for_enumerate, _gen_for_zip): a naive `inner_str.split(',')` tore
    # the nested slot of `for i, (pn, _pt) in enumerate(params)` into the
    # fragments `(pn` / `_pt)`, and `(pn` was then handed straight to
    # `_declare_var` — emitting the hard C syntax error `int64_t (pn;`.
    # (Real: this compiler's own `_struct_method_overload_ids` param scan,
    # only reachable once `zip()` got a lowering and the enclosing pass
    # stopped running zero times.)
    parts = [p.strip() for p in gen._split_top_level_comma(inner_str)]
    idx_var = parts[0] if len(parts) >= 1 and parts[0] else '_enum_i'
    val_var = parts[1] if len(parts) >= 2 and parts[1] else '_enum_val'

    elem = gen._elem_of(it_val)
    gen._declare_var(idx_var, 'int64_t')
    # A nested tuple value slot (`for i, (a, b) in enumerate(pairs)`) is not
    # itself a variable: bind the element into a fresh temp and unpack its
    # own slots from that below, mirroring _gen_for_enumerate's val_is_tuple
    # path. `_nested_elem_types` supplies the inner slot accessor.
    val_names = None
    if val_var.startswith('(') and val_var.endswith(')'):
        val_names = [v.strip() for v
                     in gen._split_top_level_comma(val_var[1:-1].strip())]
        val_var = gen._new_temp('int64_t')
        gen.var_types[val_var] = 'int64_t'
    else:
        gen._declare_var(val_var, elem if elem else 'int64_t')
    # Emitted references go through _cname: _declare_var renames targets
    # colliding with C reserved identifiers (`index` is a POSIX function →
    # `_var_index`), and emitting the raw Python name wrote an UNDECLARED
    # identifier while body reads resolved through _c_names to the declared
    # but never-assigned mangled name (GCC: "lvalue required as left
    # operand of assignment"; real repro: Tools/scripts/summarize_stats.py's
    # `{kind_to_text(index, opcode): value for (index, value) in
    # enumerate(failure_kinds) if value}`).
    idx_c = gen._cname(idx_var)
    val_c = gen._cname(val_var)

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
        gen._emit(f"  {idx_c} = {disp_idx};")
    else:
        gen._emit(f"  {idx_c} = {idx64};")
    suf = gimple_ctypes.TypeLattice.list_suffix(elem) if elem else 'int'
    if suf == 'double':
        gen._emit(f"  {val_c} = mojo_list_get_double ({it_val}, {idx64});")
    elif suf == 'str':
        temp_str = gen._new_val('char *', f"mojo_list_get_str ({it_val}, {idx64})")
        target_type = gen._type_of(val_var)
        if target_type == 'char *':
            gen._emit(f"  {val_c} = {temp_str};")
        else:
            int_ptr = gen._new_val('int64_t', f"(int64_t){temp_str}")
            gen._emit(f"  {val_c} = {int_ptr};")
    else:
        raw64 = gen._new_val('int64_t', f"mojo_list_get_int ({it_val}, {idx64})")
        target_type = gen._type_of(val_var)
        if target_type and target_type != 'int64_t':
            gen._safe_coerce_emit('int64_t', target_type, raw64, val_c)
        else:
            gen._emit(f"  {val_c} = (int64_t) {raw64};")
    if val_names is not None:
        # Unpack the nested tuple slot bound above into its own names, with
        # the accessor matching the inner tuple's recorded slot type.
        _pair_ptr = gen._new_val('MojoList *', f"(MojoList *){val_c}")
        _pair_elem = gen._nested_elem_types.get(it_val, 'int64_t')
        _pair_suf = gimple_ctypes.TypeLattice.list_suffix(_pair_elem)
        for _vi in range(len(val_names)):
            _vn = val_names[_vi]
            if _vn == '_':
                continue
            gen._declare_var(_vn, _pair_elem)
            _vc = gen._cname(_vn)
            _vt = gen.var_types.get(_vn, _pair_elem)
            if _pair_suf == 'str':
                _sv = gen._new_val('char *', f"mojo_list_get_str ({_pair_ptr}, {_vi})")
                if _vt == 'char *':
                    gen._emit(f"  {_vc} = {_sv};")
                else:
                    _bv = gen._new_val('int64_t', f"(int64_t){_sv}")
                    gen._emit(f"  {_vc} = {_bv};")
                    gen._actual_types[_vn] = 'char *'
            else:
                _iv = gen._new_val('int64_t', f"mojo_list_get_int ({_pair_ptr}, {_vi})")
                if _vt == 'int64_t':
                    gen._emit(f"  {_vc} = {_iv};")
                else:
                    gen._safe_coerce_emit('int64_t', _vt, _iv, _vc)
    gen._gen_compr_append(node, gen0, res, res_type, bb_post)
    gen._emit(f"  goto {bb_post};")
    gen._emit_label(bb_post)
    one64 = gen._new_val('int64_t', "(int64_t)1")
    st = gen._new_val('int64_t', f"{idx64} + {one64}")
    gen._emit(f"  {idx64} = {st};")
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_after)


def _compr_str_loop(gen, node, gen0, res, res_type, it_val):
    _iv = _as_str(it_val)   # see _compr_list_loop: keep the ptr a char* in the f-string
    gen._declare_var(gen0.target, 'char')
    len64 = gen._new_val('int64_t', f'mojo_str_len ({_iv})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._emit(f"  {gen._cname(gen0.target)} = mojo_str_char_at ({_iv}, {idx64});")
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
    for the real-world impact this had (fire_compiler.py's own
    `any(c in (...) for c in prefix)` silently evaluating empty/False
    for every self-hosted-compiled program). Mirrors _compr_str_loop's
    identical index-loop shape, just over mojo_strlen/_mojo_at_char
    instead of mojo_str_len/mojo_str_char_at."""
    _iv = _as_str(it_val)   # see _compr_list_loop
    gen._declare_var(gen0.target, 'char')
    len64 = gen._new_val('int64_t', f'mojo_strlen ({_iv})')
    idx64 = gen._new_val('int64_t', '(int64_t)0')
    bb_cond = gen._new_bb(); bb_body = gen._new_bb()
    bb_post = gen._new_bb(); bb_after = gen._new_bb()
    gen._emit(f"  goto {bb_cond};")
    gen._emit_label(bb_cond)
    cond_t = gen._new_val('_Bool', f"{idx64} < {len64}")
    gen._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
    gen._emit_label(bb_body)
    gen._ptr_helpers_needed.add('char')
    addr = gen._new_val('char *', f"_mojo_at_char ({_iv}, {idx64})")
    gen._emit(f"  {gen._cname(gen0.target)} = *{addr};")
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
            _ct, cv = gen.lower_expr(cond_expr)
            # A bare `if x` filter where `x` is a string must test
            # non-EMPTY (Python truthiness), not merely non-NULL — an
            # empty `char *` "" pointer is non-null and would wrongly pass.
            cv = gen._ensure_bool_cond(_ct, cv)
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
        # (fire_compiler.py's `_process_nested_tstrings` uses exactly
        # this any(genexpr) shape).
        # Index the 2-tuple return rather than `et, ev = ...`: the unpack
        # boxes `et` on the self-hosted path, and `_elem_types[res] = et`
        # then stored a garbage ctype string that a later `_elem_of(res)`
        # (nested comprehension / `for` over the result) fed into
        # `_declare_var`'s `mojo_str_cat` -> `strlen()` segfault on the
        # single-TU `--dump myinterpreter.py`.
        _lr = gen.lower_expr(node.element)
        et = _as_str(_lr[0]); ev = _lr[1]
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
        # Index the 2-tuple, NOT `et, ev = gen.lower_expr(...)`: the
        # unpack boxes `et` on the self-hosted path, so `et == 'char *'`
        # failed for a genuinely-string element and EVERY `{s for s in
        # strs}` / `frozenset({...})` re-added its strings via
        # `mojo_set_add_int` — the set then had int-tagged slots holding
        # char* pointers and `name in <that set>` (mojo_set_contains_str)
        # always missed (e.g. `_SELFHOST_HARDCODED_FUNCS`, so
        # `Interpreter_execute` got a conflicting arity-variadic weak
        # stub on the shimless `--dump`).
        _sr = gen.lower_expr(node.element)
        et = _as_str(_sr[0]); ev = _sr[1]
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
