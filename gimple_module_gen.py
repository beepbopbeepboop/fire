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
    py_tokenize, Parser,
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


def gen_module_impl(self, stmts):
    self._actual_types['stmts'] = 'MojoList *'
    # Direct local-sibling modules this file imports at top level (e.g.
    # `from base.resource import ...`) — populated by the "Process
    # imports" loop below, consumed by _gen_toplevel to call each
    # sibling's own <module>_init() before this module's own top-level
    # code runs. Fresh per gen_module call (never leaks across the
    # separate GimpleGen instances driver.compile_dylib/build_stdlib_
    # dylib.py spin up per module). See _gen_toplevel's own comment for
    # why this is needed: cross-module __attribute__((constructor))
    # firing order in a `mojo dylib` build follows link/discovery order
    # (driver._expand_dylib_modules' BFS), NOT the real dependency
    # graph, so a module whose top-level code calls into a transitively
    # -imported sibling's globals can run before that sibling's own
    # ctor has initialized them.
    self._toplevel_dep_init_modules: list[str] = []
    # Fold every TOP-LEVEL `comptime NAME = value` into self._comptime_vals
    # BEFORE anything else in this module gets compiled. Without this, a
    # module-level comptime constant was invisible everywhere: the only
    # two existing fold sites are `_gen_stmt_ComptimeVarStmt` (fires
    # during ordinary Phase 2a statement generation — but a top-level
    # ComptimeVarStmt is never even added to `toplevel_stmts` below,
    # since its isinstance tuple doesn't include ComptimeVarStmt, so
    # that never runs for one) and the FUNCTION-nested pre-fold a few
    # thousand lines down (scoped to `stmt.body` of the function
    # currently being compiled, not file/module scope). Every OTHER
    # reference anywhere in the file — struct field array-size
    # annotations, ordinary runtime reads via `_lower_IdentExpr`, bounds
    # checks — silently read the "ct param or undeclared" placeholder
    # value 0 instead. See test_gimple.py's
    # "toplevel_comptime_const_visible_everywhere". Recurses into
    # IfStmt/TryStmt/While/For bodies (mirroring this file's other
    # top-level pre-scans) since a comptime constant can legitimately be
    # declared inside a platform-resolved `if` block; processes in
    # source order so a later comptime referencing an earlier one folds
    # correctly.
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
    # Bare `from X import <comptime_const>` (BUG-2026-009): a `comptime`
    # constant is normally inlined as a literal VALUE at every use site
    # within its own home module (`_prefold_toplevel_comptime` just
    # above) — a genuinely different strategy from an ordinary runtime
    # `extern` symbol reference (which is what `_emit_imported_global_
    # accessors`, right above, does for a plain `var` global). Crossing
    # a module boundary, the constant's VALUE still needs to become
    # visible here somehow: `mojo dylib`'s per-module-independent
    # compile (driver.compile_dylib -> one GimpleGen per file, no
    # shared state) means this module's own `_comptime_vals` prefold
    # above only ever sees ITS OWN top-level statements, never module
    # X's — so `MAX_N` used directly (`Int64(MAX_N)`) previously fell
    # through `_lower_IdentExpr` all the way to the "unknown identifier"
    # placeholder and silently read 0.
    #
    # Reuses `_parsed_import` — the same source-resolution/parse-cache
    # this file already uses to resolve a sibling/stdlib module's
    # source text for OTHER purposes (comptime function calls via
    # `_imported_fn_sources`, the fixed-size-array `[Elem; N]`
    # annotation's `_module_const_int`) — and the identical recursive
    # `_prefold_toplevel_comptime` walk, just pointed at the imported
    # module's own top-level statements instead of this module's own.
    # Only DIRECT (this module's own top-level `from X import ...`)
    # imports are resolved — matches `_module_const_int`'s own scope,
    # not a full transitive closure.
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
    # Per-lexical-scope import tracking: push THIS module's own top-level
    # scope (frame 0) before any import scan or body generation runs.
    # _emit_stdlib_import_externs / _register_link_imports populate it from
    # this module's own top-level `from X import ...` statements; each
    # function/method body pushes its own frame on top (see gen_func /
    # _gen_struct_method / _gen_lifted_closure). Not popped on the
    # exception path: a raise abandons the whole compile and this
    # instance, so there is nothing to leak.
    self._import_scope_stack.append({})
    # Generator functions (`yield`/`yield from` anywhere in a function's
    # own body — mojo_compiler.py's parser sets FunctionDef.is_generator
    # during parsing) and async functions (`async def` — sets
    # FunctionDef.is_async) cannot be lowered to a single straight-line C
    # function the way this codegen represents every other function:
    # generators need an explicit suspend/resume state-machine transform
    # and async functions need an event loop / suspend-resume codegen,
    # neither of which exists yet (see
    # bugs/INTERP_generator_yield_entirely_unimplemented.md — generator
    # codegen and async codegen are both later milestones than the
    # parser-only ones that introduced these flags). A function CAN be
    # both (`async def f(): yield x`, a real "async generator") — that's
    # reported as its own combined category below rather than tripping
    # both the generator and async raises separately (only the first
    # raise encountered would ever be seen by a caller). Detect every
    # such FunctionDef anywhere in this module (top-level, nested inside
    # if/elif/else branches, struct/class methods, or nested defs) via
    # `_walk_ast`'s generic traversal — reused rather than a hand-rolled
    # walk, matching this file's own established "don't duplicate a
    # tree-walk" convention (see `_walk_ast`'s own docstring). The actual
    # eligibility/compile attempt (and the raise covering whichever
    # categories remain unsupported) is deferred to further below, AFTER
    # the module-wide parameter-type inference passes (in particular
    # Pass 1.3d's cross-call scalar contract) have run — see the comment
    # at that later site for why: an UNANNOTATED generator parameter
    # needs that same inference an ordinary function's unannotated
    # parameter already gets, and doing this here (before those passes
    # exist) silently defaulted such a parameter to int64_t instead of
    # honestly refusing it. Every caller of gen_module
    # (_compile_imported_module, build_stdlib_dylib.py's per-module
    # compile job, compile_stdlib.py, mojo.py's build_executable) already
    # treats an exception raised from codegen (at any point during it) as
    # "this module/file can't be compiled natively" and falls back to
    # interpreting it from source instead of emitting silently wrong or
    # broken C, so raising later than the earliest possible point is a
    # pure (harmless) perf trade-off, not a correctness one — each
    # gen_module call runs against its own freshly-constructed GimpleGen
    # instance (see this method's callers), so there is nothing to leak
    # into a later compile even if this one is ultimately refused after
    # partially populating this instance's tables.
    # Keyed by id(FunctionDef), NOT by name: a bare-name set (the shape
    # this used prior to Milestone C step 3, generator METHODS) is only
    # safe when every generator/async function in the module has a
    # name unique across the WHOLE tree — true for top-level functions
    # (already deduped by the `_overloaded` filter above... in practice,
    # by the time struct methods entered scope for real support, no
    # longer reliably true: two different structs may each define a
    # same-named generator method (`def __iter__(self): yield ...`),
    # one shape-supported and one not, or a struct method may simply
    # share a name with an unrelated top-level generator function. A
    # bare-name discard (`_generator_names.discard(s.name)`) in that
    # situation would incorrectly mark the OTHER, still-unsupported,
    # same-named function/method as resolved, silently skipping the
    # honest whole-module refusal it still needs. Identity-based keys
    # make this collision structurally impossible; display names are
    # derived from the FunctionDef objects only at the very end, for
    # the error message.
    _generator_fns: dict[int, FunctionDef] = {}
    _async_fns: dict[int, FunctionDef] = {}
    for n in _walk_ast(stmts):
        if isinstance(n, FunctionDef):
            if n.is_generator: _generator_fns[id(n)] = n
            if n.is_async: _async_fns[id(n)] = n
    # Every generator function NAME anywhere in this module, computed
    # ONCE here before the compile-attempt passes below start `.pop()`-
    # ing entries out of `_generator_fns` as they succeed — kept for
    # this GimpleGen instance's whole lifetime (unlike `_generator_fns`,
    # a purely-local dict) so `_cpp_for_generator_delegate`'s caller
    # (`_cpp_for_stmt`) can tell "this callee IS a generator in this
    # module, just not compiled yet (wrong source order for THIS pass)"
    # apart from "this callee was never a generator at all" even AFTER
    # the callee's own entry has already been popped/registered or is
    # still pending in a later pass. Without this, a `for x in g():`
    # loop whose callee `g` happens to be defined LATER in the module
    # (dis.py's `_get_instructions_bytes` calling `_unpack_opargs`,
    # defined ~180 lines below it) would see `g` missing from
    # `self._generator_api` on pass 1, silently fall through to the
    # generic (non-generator-aware) iterable lowering below, and emit
    # invalid C++ instead of raising `_UnsupportedGeneratorShape` — the
    # one signal that gets THIS caller retried once `g` has actually
    # been compiled, in pass 2/3/4, exactly like `_cpp_yield_from`'s own
    # identical source-order dependency already relies on.
    self._all_generator_names: set = {n.name for n in _generator_fns.values()}
    # Step I (create_task/Task/TaskGroup/RaisingTask project): every
    # async function NAME anywhere in this module (top-level or
    # nested), regardless of whether it ends up eligible/compiled —
    # lets create_task/create_raising_task's call-site lowering in
    # _lower_call tell "this genuinely names some async def in this
    # module, just one our narrow codegen couldn't compile" (a real,
    # documented, narrow degrade — see that call site's own docstring)
    # apart from "this name doesn't exist / isn't async at all" (still
    # an honest hard refusal, unchanged) when the inner call doesn't
    # resolve in self._async_api.
    self._all_async_fn_names: set[str] = {n.name for n in _async_fns.values()}

    # Structs DECLARED IN THIS FILE's own top-level stmts (as opposed to
    # imported, or referenced but never actually resolved as local or
    # imported) — the only names _struct_method_qualifier may safely
    # apply self.module_name to. See that method's docstring: a struct
    # name this compile can't place in EITHER _imported_struct_home NOR
    # here must fall back to the bare/unqualified form, not guess that
    # it belongs to the module currently being compiled — confirmed
    # regression otherwise (a cross-module call to an imported struct
    # that _register_imported_structs' narrow parameter-type-annotation
    # gate never registered, e.g. StridedSlice/TString/ContiguousSlice
    # used only via untyped locals, got glued with THIS file's own
    # module qualifier instead of either its real home module's or no
    # qualifier at all).
    # Rename any struct/class named after a C keyword (`auto`, ...) to a
    # C-safe name BEFORE anything reads sd.name — so registration, typedef
    # emission, method symbols, alloc, etc. all use the safe name uniformly
    # (the logical name IS the safe name from here on, avoiding the
    # emit-vs-bookkeeping split that made a pure emission-site patch
    # unworkable). Mutates sd.name in place and records the mapping in the
    # shared _c_kw_struct_renames; reference sites (constructor calls, type
    # annotations) map through it at lookup time. Idempotent: a safe name
    # like `_kw_auto` isn't a keyword, so re-running is a no-op.
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

    # `try: from X import Y / except ImportError: from Z import Y`
    # (or a bare `def NAME(): ...` fallback shape) — the standard
    # CPython compatibility idiom for "try the modern/preferred name,
    # fall back to an older/alternate one on ImportError", both
    # branches binding the SAME local name. Unlike the IfStmt
    # platform-conditional case just below (which already flattens
    # to one branch), NOTHING resolves a top-level TryStmt's
    # try/except branches down to one — both get scanned/compiled,
    # producing two conflicting C definitions for the same symbol
    # ("redefinition of X"), or — when one branch's def/import never
    # gets its own real definition emitted — a silently-wrong
    # "unavailable in compiled mode" stub instead. This compiler
    # doesn't implement real exception-based control flow at the
    # type-checking/codegen level (whether the try branch's import
    # actually succeeds depends on the target platform's real
    # availability, unlike an `if sys.platform == ...:` check this
    # compiler CAN resolve), so — mirroring how the `if` case below
    # picks one branch with a fixed heuristic when the condition
    # isn't staticaly resolvable — the correct behavior for THIS
    # specific idiom is "prefer the try branch, drop the except
    # branch(es)" for the purpose of choosing which definition of a
    # shared name to emit. Deliberately conservative in TWO ways:
    # (a) the trigger only looks at FromImportStmt/ImportStmt/
    # FunctionDef bindings — the shapes that actually emit a real
    # C-level symbol DEFINITION that can collide — NOT plain
    # AssignStmt/MultiAssignStmt/VarDecl. An ordinary
    # `try: result = f() \n except: result = fallback` shares the
    # variable name `result` across both branches, but that's
    # everyday defensive error-handling, not the redefinition bug
    # this fix targets; treating a shared assignment target as
    # grounds to silently drop the except branch's actual fallback
    # logic would be a real behavior regression for that (far more
    # common) idiom. (b) even when triggered, an ordinary try/except
    # doing genuinely different, non-overlapping things in each
    # branch is left completely untouched. See
    # bugs/hard/CODEGEN_try_except_import_fallback_both_branches_
    # compiled.md.
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
                # Same-name-rebinding fallback idiom confirmed: keep
                # only the try branch's own statements (dropping the
                # except handler(s), else_body, and finally_body
                # entirely for codegen purposes — matches the
                # IfStmt case's "drop the branch container" comment
                # just below), so every later pass (Phase 1.7, the
                # closure/def scan, actual statement emission) sees
                # ordinary top-level statements instead of a TryStmt
                # it has no special handling for.
                _try_replaced.extend(_s.body or [])
            else:
                _try_replaced.append(_s)
        else:
            _try_replaced.append(_s)
    stmts = _try_replaced

    # Two (or more) top-level `def NAME(...):` statements with the SAME
    # name, nested in mutually-exclusive `if`/`elif`/`else` branches at
    # module scope (a common platform-conditional idiom — e.g.
    # `if sys.platform == 'win32': def wait(...): ...` /
    # `else: def wait(...): ...`, as seen for real in
    # multiprocessing/connection.py) cannot be compiled as distinct C
    # functions: both bodies would want the same unmangled top-level
    # symbol. Worse, unlike the plain-top-level `_overloaded` case just
    # above, nested-in-conditional defs are not even recognized as
    # ordinary top-level functions anywhere else in this pass (the
    # module-level closure scan a few hundred lines down only walks
    # *direct* top-level FunctionDef entries in `stmts`, never into
    # IfStmt branches) — so they silently fall through as unregistered
    # "closures", emit no body at all, and leave call sites to guess an
    # extern declaration for the bare name. That previously surfaced as a
    # confusing conflict with an unrelated same-named libc symbol (e.g.
    # `wait` vs. <sys/wait.h>'s `pid_t wait(int *)`) instead of an honest
    # diagnostic pointing at the real problem.
    #
    # Detect the shape here and fail this module's compile clearly and
    # immediately. Every caller of gen_module (_compile_imported_module,
    # build_stdlib_dylib.py's per-module compile job, compile_stdlib.py,
    # and mojo.py's own build_executable) already treats an exception
    # raised from codegen as "this module/file can't be compiled natively"
    # and reacts accordingly — an import falls back to being resolved via
    # dylib/extern/interpreted-source instead of inlined C, and a directly
    # built file gets a clear compiler error — both are honest outcomes,
    # unlike silently emitting broken code or guessing which branch's
    # definition should win.
    # Iterative worklist, not a self-recursive nested helper: a nested
    # function calling itself does not survive self-host closure-lifting
    # (see _register_imported_structs's _collect, a few hundred lines
    # up, for the same gotcha spelled out in full) — this exact shape
    # broke `make check-selfhost` (undefined symbol
    # `__collect_conditional_toplevel_defs`) the first time this was
    # written as `def _collect_conditional_toplevel_defs(...): ...
    # _collect_conditional_toplevel_defs(...)`.
    #
    # Pre-fold simple top-level constant assignments (e.g. `_MS_WINDOWS
    # = (sys.platform == 'win32')`) into self._comptime_vals, the same
    # dict real `comptime NAME = value` declarations populate — an
    # ordinary module-level assignment whose RHS is itself compile-time
    # foldable (now that _eval_const understands `sys.platform`) is
    # semantically the same kind of constant for the platform-
    # conditional-toplevel-def idiom below, which needs to resolve
    # `if _MS_WINDOWS:`-style bare-name conditions, not just direct
    # `if sys.platform == 'win32':` ones. `setdefault` only, matching
    # the existing pre-fold pattern elsewhere in this file — never
    # overwrites a genuine comptime declaration.
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
    # handles BOTH the same-name collision case AND the single,
    # non-duplicated `def` nested in a module-scope if/elif/else
    # (bugs/CODEGEN_conditional_toplevel_def_never_compiled.md), by
    # hoisting the first-branch def into a real top-level FunctionDef so
    # it flows through the same pre-pass structures (closure scan, gen_
    # func loop) a direct top-level def goes through. What it does NOT
    # yet do — the durable fix's remaining half — is represent the
    # branch-selectivity faithfully for COLLIDING names:
    #   1. Give same-named defs from sibling branches distinct mangled C
    #      symbols (e.g. suffix by branch index), rather than the single
    #      unmangled name every direct top-level def gets.
    #   2. Make each call site to that name dispatch at runtime between
    #      the mangled per-branch symbols, re-evaluating the same
    #      condition the def was originally guarded by (or, if the
    #      guarding condition is one this compiler can already resolve
    #      statically — e.g. a literal `sys.platform` check, if that's
    #      special-cased anywhere else already — pick the matching
    #      branch's mangled symbol directly at compile time instead of
    #      emitting a runtime check).
    # Until that exists, first-branch-wins (matching CPython semantics
    # for the branch that RUNS) is the honest approximation, not the
    # complete one.
    _cond_collisions = {n for n, c in _cond_fn_counts.items() if c > 1}
    # A SINGLE, non-duplicated `def` nested in a module-scope
    # if/elif/else is JUST as invisible to the pre-passes below (which
    # only walk direct top-level FunctionDef entries in `stmts`, never
    # IfStmt branches) as a collision-pair is — it would silently fall
    # through to _gen_stmt_FunctionDef's closure path with no pre-pass
    # ClosureInfo, emit no body, and leave every call site with a
    # dangling extern that fails at LINK time (the `if sys.platform ==
    # 'darwin': def greet(): ...` + `print(greet())` repro in
    # bugs/CODEGEN_conditional_toplevel_def_never_compiled.md). Promote
    # it to a real top-level statement exactly like the collision case
    # above, first-branch-wins. Guard: never promote a name that ALSO
    # has a direct top-level `def` in this module — hoisting it would
    # create exactly the same-name C-symbol clash the collision case
    # exists to catch (such a def stays exactly as broken as it was
    # before, no regression).
    _direct_toplevel_names = {s.name for s in stmts if isinstance(s, FunctionDef)}
    _cond_unique = {n for n, c in _cond_fn_counts.items()
                    if c == 1 and n not in _direct_toplevel_names}
    _promote_names = _cond_collisions | _cond_unique
    if _promote_names:
        # Platform-conditional def idiom (same fn name in if/elif/else
        # branches, or a single conditionally-defined helper). This
        # compiler targets CPython semantics, so the FIRST branch's
        # definition is the correct one — promote it to a real top-level
        # function and discard the branch container (the other branches'
        # same-named defs would otherwise collide). A top-level IfStmt
        # whose branches contain no def to promote is left untouched —
        # it's ordinary conditional top-level code, not a definition.
        # Iterative explicit-stack traversal (first-occurrence defs
        # across then/elif/else branches in execution order, recursing
        # into NESTED IfStmts the same way the counting worklist above
        # does — the two share one root cause: defs inside module-scope
        # conditionals), NOT a self-recursive nested helper: a nested
        # function calling itself does not survive self-host closure-
        # lifting (same constraint the counting worklist above documents
        # in full).
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
                    # If this IfStmt's own condition (and each elif's,
                    # in order) is compile-time-resolvable (e.g. `if
                    # sys.platform == 'win32':` — see _eval_const's
                    # `sys.platform` case), use ONLY the single branch
                    # CPython would actually execute on this host,
                    # instead of blindly concatenating every branch and
                    # letting first-occurrence-in-source-order win
                    # regardless of truth value. Without this, `if
                    # _MS_WINDOWS: def f(): ...(Windows body)... else:
                    # def f(): ...(POSIX body)...` always promoted the
                    # Windows body even when _MS_WINDOWS folds to False
                    # on this (non-Windows) host — a silent WRONG-
                    # runtime-behavior bug, not just a missed-compile
                    # one. Falls back to the old "concatenate every
                    # branch" behavior unchanged whenever the condition
                    # isn't foldable, so non-constant conditionals are
                    # unaffected. See bugs/COMPILE_FAIL_importlib__
                    # bootstrap_external.md.
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
                # Drop the branch container entirely (its non-promoted
                # defs and other statements are not the platform-correct
                # ones — mirroring the collision path above)
            else:
                _replaced.append(_s)
        stmts = _replaced

    # Local generic free functions: the parser drops the `[T]` type params, so
    # detect them from the source text. Register each (with this module's own
    # source) so call sites elaborate a concrete CAS-cached instantiation
    # (id[Int64] → id_Int64), and drop the erased template so it is neither
    # emitted as a type-erased body nor collides across modules.
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
            # A nested async/generator def inside a stripped local
            # generic (test_tracing.mojo's own real shape:
            # `test_tracing_add`/`test_tracing_add_two_of_them` nested
            # inside `def test_tracing[level: TraceLevel, enabled:
            # Bool]()`) was already counted into _async_fns/
            # _generator_fns by the deep `_walk_ast(stmts)` scan a few
            # lines above — which ran BEFORE this strip, over the
            # ORIGINAL (unstripped) `stmts`. Once the outer generic is
            # stripped here, nothing else in THIS module compile will
            # ever attempt (or pop) that nested id — it's only ever
            # compiled inside the SEPARATE, per-call-site elaborated
            # instance `_elaborate_generic_call`/monomorphize.py spins
            # up (its own independent GimpleGen, own independent
            # gen_module run, own independent _async_fns/_generator_fns
            # tally). Left uncleaned, it would ALWAYS show up in this
            # module's own final "still unsupported" error — a real,
            # pre-existing false-positive refusal for ANY module with a
            # local generic function that happens to nest an async/
            # generator def, confirmed via a hand-written repro
            # matching test_tracing.mojo's exact structure.
            for _sgf in _stripped_generic_fns:
                for _n in _walk_ast(_sgf.body):
                    if isinstance(_n, FunctionDef):
                        _async_fns.pop(id(_n), None)
                        _generator_fns.pop(id(_n), None)

    # Struct methods with a FUNCTION-TYPED comptime bracket parameter that
    # is actually referenced (directly or via a nested closure) — see
    # _method_threaded_comptime_params' docstring / bugs/CODEGEN_
    # device_context_captured_function_parameter_closures_broken.md's
    # Repro 1. Unlike the local-generic-FREE-FUNCTION case above (which
    # elaborates a distinct specialized function per call site via
    # textual substitution), a function-typed comptime parameter carries
    # no compile-time-varying information this codegen's monomorphization
    # needs — it's always just an opaque callable pointer — so it's
    # threaded through as one ordinary trailing C parameter instead
    # (_gen_struct_method appends it; the "obj.method[...]"  call site in
    # _lower_call forwards the bracket argument as an extra positional
    # arg), with NO per-call-site specialization and no change to methods
    # whose comptime bracket parameter is never independently threaded
    # (an Int/Bool/other comptime method parameter, or one that's a pure
    # type-bound never referenced as a plain identifier — e.g. `FuncType:
    # def() -> None` typing an ordinary `func: FuncType` parameter — is
    # completely unaffected, left exactly as before).
    if _gsrc:
        for _s in stmts:
            if not isinstance(_s, StructDef):
                continue
            # Scope the textual bracket-annotation search to just THIS
            # struct's own source slice (not the whole module) — an
            # occurrence index is only meaningful relative to a single,
            # well-defined search space; scoping to the struct keeps
            # "occurrence N of this method name" unambiguous even if
            # some other struct/free-function elsewhere in the same file
            # happens to reuse the same method name with its own bracket
            # parameters.
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

    # Structs with a __call__ method: a variable of such a type invoked like a
    # function (obj(args)) routes to Struct___call__(obj, args).
    self._callable_structs = {
        s.name for s in stmts
        if isinstance(s, StructDef) and any(m.name == '__call__' for m in s.methods)
    }

    # Register concrete imported structs used (with field access) as param types.
    self._register_imported_structs(stmts)
    # Register imported generic free functions (via re-export chains) so their
    # calls elaborate a concrete CAS-cached instantiation.
    self._register_imported_generics(stmts)
    # Register imported generic structs (via re-export chains) so
    # Struct[Args](...) calls / nested generic-struct type args elaborate too.
    self._register_imported_generic_structs(stmts)

    # Pre-scan MODULE-LEVEL `comptime NAME = [...]` list constants so
    # `for a, b in materialize[NAME]():` (see _gen_for_iter's special
    # case) has them available no matter which function is compiled
    # first — a top-level ComptimeVarStmt is normally only recorded by
    # _gen_stmt_ComptimeVarStmt when gen_stmt walks over IT, which for a
    # module-level statement happens only as part of the toplevel-code
    # pass; a function whose body is emitted BEFORE that pass runs would
    # otherwise see an empty _comptime_list_asts even though the comptime
    # list is textually declared earlier in the file (real, in stdlib's
    # test_atof.mojo).
    for _s in stmts:
        if isinstance(_s, ComptimeVarStmt) and isinstance(_s.value, ListExpr):
            self._comptime_list_asts.setdefault(_s.target, _s.value)

    # This module's own top-level function names — used by _func_qualifier
    # (SB-1 fix) to tell a genuinely LOCAL definition (qualify with THIS
    # module's own name) apart from a same-bare-name entry that merely got
    # added to self._mangled_funcs because it's an IMPORTED function (must
    # use its actual defining module's qualifier instead — see
    # _imported_func_home). `stmts` is this call's own top-level list, so
    # identity membership here is exactly "declared in this file".
    self._local_top_level_func_names = {
        s.name for s in stmts if isinstance(s, FunctionDef)}

    # Pre-register current module's own function names into _global_inline_defs
    # BEFORE Phase 0 so that recursive sub-module compilations see them.
    for _s in stmts:
        if isinstance(_s, FunctionDef):
            self._global_inline_defs.add(_s.name)
        elif isinstance(_s, StructDef):
            for _m in _s.methods:
                self._global_inline_defs.add(_m.name)
                self._global_inline_defs.add(f"{_s.name}_{_m.name}")
            # Struct-level comptime aliases (e.g. BitSet._words_size) expand
            # to their expression at member-access sites, not physical fields.
            _al = getattr(_s, 'comptime_aliases', None)
            if _al:
                self._struct_comptime_aliases[_s.name] = _al

    # Link mode: register imported symbol signatures (return/param types) from
    # module_loader so call sites lower correctly; decls emitted in preamble.
    # No body inlining — bodies come from the linked artifact (ABI.md).
    self._link_import_decl_list = []
    if self.link_imports:
        self._link_import_decl_list = self._register_link_imports(stmts)

    # Lightweight stdlib import extern pass: scan from-imports and emit extern
    # declarations for concrete functions found via load_module (simple text
    # parser, no dylib builds). This resolves "implicit declaration" errors for
    # functions like `is_occupied` imported from other stdlib modules.
    self._link_import_decl_list = list(self._link_import_decl_list)
    self._emit_stdlib_import_externs(stmts)
    self._emit_imported_global_accessors(stmts)

    # ── Phase 0: Compile imported modules and extract their type info ────
    # Do this FIRST so imported function types are available for everything
    imported_code = []
    imported_stmts = []
    if self.do_imports:
        modules_to_compile = set()
        # Recursively scan for all imports (including in function bodies)
        def find_imports(node_list):
            for stmt in node_list:
                if isinstance(stmt, FromImportStmt):
                    modules_to_compile.add(stmt.module)
                    # `from PACKAGE import SUBMODULE` (e.g. `from
                    # tkinter import commondialog`) — real Python
                    # resolves the imported NAME as a submodule FILE
                    # (tkinter/commondialog.py), not a name looked up
                    # inside tkinter/__init__.py, so compiling just
                    # `stmt.module` alone never pulls in commondialog's
                    # own struct/function defs (e.g. `Dialog`, whose
                    # methods a same-transitive-closure subclass like
                    # tkinter/filedialog.py's `_Dialog(commondialog.
                    # Dialog)` needs merged in — see bugs/
                    # COMPILE_FAIL_tkinter_filedialog.md). Try each
                    # imported name as a dotted submodule path too, in
                    # addition to the bare module — _compile_imported_
                    # module already resolves dotted names via its own
                    # existing search-path logic, and silently finds
                    # nothing (a no-op) for the overwhelmingly common
                    # case where the imported name is genuinely just a
                    # symbol inside the module rather than a submodule
                    # file.
                    for _fn, _fa in (stmt.names or []):
                        modules_to_compile.add(f"{stmt.module}.{_fn}")
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

        # Compile imported modules to extract type information
        for module_name in sorted(modules_to_compile):
            if module_name not in self._compiled_modules:
                self._compiled_modules.add(module_name)
                code, module_stmts = self._compile_imported_module(module_name)
                if code:
                    imported_code.append(f"/* ─── Imported module: {module_name} ───────────────────── */")
                    imported_code.append(code)
                    imported_code.append('')
                    imported_stmts.extend(module_stmts)
                    # Record all function names defined inline to suppress extern stubs
                    for _ms in module_stmts:
                        if isinstance(_ms, FunctionDef):
                            self._global_inline_defs.add(_ms.name)
                            # SB-1 fix (_func_qualifier): the nested temp_gen
                            # that compiled this function inline used
                            # module_name=module_name as ITS OWN module_name
                            # (see _compile_imported_module below), so any
                            # mangled symbol it emitted for this function was
                            # qualified with that same prefix. Record it here
                            # (mirroring _imported_struct_home just below) so
                            # a call site in this module recomputes the
                            # identical qualified symbol instead of an
                            # unqualified one nothing defines.
                            self._imported_func_home.setdefault(_ms.name, module_name)
                            # _own_imported_func_home (per-instance, NOT
                            # shared across nested temp_gens — see its own
                            # comment): `self` HERE is specifically the
                            # temp_gen that is DOING the importing (its own
                            # find_imports scan is what put module_name into
                            # modules_to_compile), so this registration is
                            # always correct for THIS module's own call
                            # sites and must win over any OTHER importer's
                            # conflicting claim on the same bare name in the
                            # shared _imported_func_home fallback above.
                            # record_scope=False: these are TRANSITIVE
                            # registrations of an inlined dependency
                            # module's OWN top-level functions, NOT this
                            # module's own lexical imports — they must not
                            # pollute this module's scope (a call site's
                            # authoritative binding comes from ITS OWN
                            # `from X import ...` statements, recorded
                            # into the right scope by _gen_stmt_FromImport
                            # Stmt / the body pre-scan).
                            self._note_own_func_home(_ms.name, module_name, record_scope=False)
                        elif isinstance(_ms, StructDef):
                            for _m in _ms.methods:
                                self._global_inline_defs.add(_m.name)
                                self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                            # _compile_imported_module's nested temp_gen
                            # compiled with module_name=module_name, so
                            # every one of its own locally-defined
                            # structs' method symbols got qualified with
                            # that prefix. A call site in THIS module (or
                            # a shallower ancestor, imported_struct_home
                            # is shared down the whole nested-temp_gen
                            # chain) on that struct needs to derive the
                            # identical qualified symbol — see
                            # _struct_method_qualifier. Previously
                            # unregistered here: harmless for a direct
                            # (root -> leaf) import, since the struct's
                            # OWN compile pass registers types into the
                            # shared struct_field_types dict either way,
                            # but a 3-level-deep chain (root -> A -> B,
                            # B defines the struct, A merely re-uses it)
                            # left the root's own call sites on that
                            # struct recomputing an unqualified symbol
                            # the defining module never exports under
                            # (BUG-2026-032's arena.mojo/ast_nodes.mojo).
                            self._imported_struct_home.setdefault(_ms.name, module_name)
                self._compiled_modules.add(module_name)

        # Also collect stmts from transitively compiled modules (compiled by sub-temp-gens).
        # These may not be in imported_stmts if a sub-gen compiled them first (e.g. mojo_compiler
        # compiled via gimple_codegen before the outer gen could compile it directly).
        #
        # PERF (see bugs/hard/PERF_nested_module_compile_walk_ast_
        # quadratic_rescan.md, Phase 1): iterate the incrementally-
        # maintained flat `_all_transitive_stmts_ordered` list instead
        # of re-flattening `self._module_stmts.items()` from scratch —
        # identical final `imported_stmts` content (same dedup-by-id
        # logic, same append order, since `_all_transitive_stmts_
        # ordered` is itself built by walking each module's stmts in
        # the same per-module order `_module_stmts.items()` would visit
        # them, just accumulated once instead of re-derived at every
        # nesting level), but O(this level's own delta) instead of
        # O(current total tree size) — the repeated full re-flattening
        # at every one of N nesting levels is what produced the O(N^2)
        # `_walk_ast` blowup this doc profiles (4.47M calls for a
        # 36-module graph in Lib/contextlib.py).
        already_in_stmts = set(id(s) for s in imported_stmts)
        for s in self._all_transitive_stmts_ordered:
            if id(s) not in already_in_stmts:
                imported_stmts.append(s)
                already_in_stmts.add(id(s))

        # Imported types are now in self._imported_func_types and struct_field_types

    # Link mode's fallback for plain structs with no dylib to reflect off
    # of (_register_link_imports, above) records the MODULE name here —
    # compile it for real (body generation, not just field-type
    # registration) the same way do_imports=True's Phase 0 above compiles
    # each transitively-imported module, since there's no dylib to link
    # its methods from. Kept separate from the `if self.do_imports:`
    # block above: that block additionally tries to fully compile+inline
    # EVERY transitively-imported module (Phase 0's find_imports), which
    # would be a large, unwanted behavior change for link mode (defeats
    # per-import dylib caching for every OTHER, dylib-resolvable import
    # in the program) — this only compiles modules that already proved
    # unresolvable any other way.
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
                            # SB-1 fix (_func_qualifier): the nested temp_gen
                            # that compiled this function inline used
                            # module_name=module_name as ITS OWN module_name
                            # (see _compile_imported_module below), so any
                            # mangled symbol it emitted for this function was
                            # qualified with that same prefix. Record it here
                            # (mirroring _imported_struct_home just below) so
                            # a call site in this module recomputes the
                            # identical qualified symbol instead of an
                            # unqualified one nothing defines.
                            self._imported_func_home.setdefault(_ms.name, module_name)
                            # _own_imported_func_home (per-instance, NOT
                            # shared across nested temp_gens — see its own
                            # comment): `self` HERE is specifically the
                            # temp_gen that is DOING the importing (its own
                            # find_imports scan is what put module_name into
                            # modules_to_compile), so this registration is
                            # always correct for THIS module's own call
                            # sites and must win over any OTHER importer's
                            # conflicting claim on the same bare name in the
                            # shared _imported_func_home fallback above.
                            # record_scope=False: these are TRANSITIVE
                            # registrations of an inlined dependency
                            # module's OWN top-level functions, NOT this
                            # module's own lexical imports — they must not
                            # pollute this module's scope (a call site's
                            # authoritative binding comes from ITS OWN
                            # `from X import ...` statements, recorded
                            # into the right scope by _gen_stmt_FromImport
                            # Stmt / the body pre-scan).
                            self._note_own_func_home(_ms.name, module_name, record_scope=False)
                        elif isinstance(_ms, StructDef):
                            for _m in _ms.methods:
                                self._global_inline_defs.add(_m.name)
                                self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                            # _compile_imported_module's nested temp_gen
                            # compiles with module_name=module_name, so
                            # _struct_method_qualifier qualified every one
                            # of its own locally-defined structs' method
                            # symbols with that same prefix (e.g.
                            # ast_nodes_IfStmt___init__). THIS module's own
                            # call sites on that struct (imported by bare
                            # name, e.g. `from ast_nodes import IfStmt`)
                            # need to derive the identical qualified
                            # symbol — _struct_method_qualifier checks
                            # _imported_struct_home for exactly that.
                            self._imported_struct_home.setdefault(_ms.name, module_name)

    # ── Phase 1: build complete type tables (pre-pass) ────────────────

    # Register struct field types first so _resolve_type works for funcs
    # Include both current module and imported module structs
    # NOTE: do NOT clear struct_field_types here — it was already populated
    # by temp_gens during Phase 0 import compilation.  Clearing it would
    # lose structs from transitive imports (ModuleLoader, Layout, etc.)
    # that were added to the shared dict by nested temp_gens.

    # These hardcoded field/param tables exist for exactly one reason:
    # self-hosting this very compiler. When gimple_codegen.py compiles
    # mojo.py's own transitive closure (mojo_compiler.py, myinterpreter.py,
    # ...), those files' classes are plain Python `class Foo: def
    # __init__(self): self.x = ...` — field-type inference from scanning
    # `__init__` bodies (_collect_self_assigns) sometimes can't recover a
    # field's real type, so these entries are a hand-maintained cheat
    # sheet for THIS repo's own Scope/Token/Parser/Interpreter/MojoClass/
    # CallExpr/BinaryOp/... classes specifically.
    #
    # They must NOT apply to an external project's unrelated same-named
    # struct. A compiler-adjacent Mojo project (a hand-written parser,
    # interpreter, or AST library — exactly the kind of thing someone
    # writes in Mojo) is very likely to define its OWN Parser/Token/
    # Scope/CallExpr/BinaryOp/... with completely different fields, and
    # unconditionally seeding this dict before scanning the real
    # StructDefs let those hardcoded phantom fields leak into that
    # unrelated struct's C typedef, and (worse) the "don't overwrite an
    # already-known field name" guard in the real-struct scan below meant
    # the struct's ACTUAL matching field names were silently ignored too
    # (see BUG-2026-014's fuller repro, test_cp_tree_final.mojo: a
    # same-named `Parser` struct's real `errors: Int` field was invisible
    # at codegen because 'errors' happened not to collide with any
    # hardcoded name, but plenty of OTHER user structs — VarDecl, Parser
    # itself for its other fields — silently got the wrong ones instead).
    #
    # Gate on whether we're compiling one of THIS repo's own files: only
    # then can `s.name` genuinely be gimple_codegen.py's own bootstrap
    # class rather than a coincidentally-same-named third-party struct.
    # Span / StringSlice — fat pointer {data, len}. Seeded so .unsafe_ptr()
    # and .__len__()/len() lower to field reads even without walking
    # span.mojo. Unlike the self-host-only block below, this is a REAL
    # stdlib type used broadly — NOT gated on _is_selfhost_file (an
    # earlier version of this fix wrongly gated it too, which broke
    # every ordinary stdlib compile referencing Span with "unknown type
    # name 'Span'": compile_stdlib.py isn't compiling one of THIS repo's
    # own files, so the gate was always False for it).
    self.struct_field_types['Span'] = {
        '_data': 'char *',
        '_len': 'int64_t',
    }

    _cur_file = getattr(self, '_current_filename', None)
    _cur_abs = os.path.abspath(_cur_file) if _cur_file else ''
    # Self-host detection: the compiled `mojoc` binary is ALWAYS the
    # self-hosted compiler, regardless of which input file it compiles
    # (its `__file__` is the literal "<bootstrap>", so _SELFHOST_DIR
    # resolves to the process CWD — which differs from the input file's
    # dir — and a path-only check would wrongly be False for a user
    # file, skipping the interpreter/AST struct registrations and
    # segfaulting on node.condition etc. Class D of the A/B list).
    # Self-host detection is PATH-BASED only (repo files under
    # _SELFHOST_DIR). The old `_compiled_selfhost` override
    # (__file__ == "<bootstrap>") forced _is_selfhost_file True for EVERY
    # file the compiled binary compiled, so a user file emitted the 26
    # self-host-only struct registrations (Parser/Interpreter/Scope/Token/
    # CallExpr/BinaryOp/... plus the _AutoStub*/_Mojo* helpers) as typedefs
    # in its .ci — an A/B divergence (Python emits only the 53 ungated
    # AST structs for a user file). Path-based detection keeps the gated
    # self-host structs for repo files (byte-identical with Python's own
    # self-host compile) while user files match Python's 53-struct set.
    _is_selfhost_file = bool(_cur_file) and (
        _cur_abs == _SELFHOST_DIR or _cur_abs.startswith(_SELFHOST_DIR + '/'))
    if _is_selfhost_file:
        # Pre-populate known interpreter structs with their field types
        # This handles cases where field type inference from method bodies fails
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
            # Milestone 2 of
            # bugs/INTERP_generator_yield_entirely_unimplemented.md:
            # MojoFunction.is_generator (myinterpreter.py) — mirrors
            # FunctionDef.is_generator, gates MojoFunction._invoke's
            # generator-construction-only vs. eager-execution branch.
            'is_generator': '_Bool',
            # Milestone 3b of
            # bugs/INTERP_generator_yield_entirely_unimplemented.md:
            # MojoFunction.is_async (myinterpreter.py) — mirrors
            # FunctionDef.is_async, gates MojoFunction._invoke's
            # coroutine-construction-only vs. eager-execution branch,
            # same treatment as is_generator immediately above.
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
            # `_INT_TYPE_NAMES`/`_FLOAT_TYPE_NAMES` are class-level `set`
            # literals on Interpreter (myinterpreter.py, used by
            # `_coerce_to_declared_type`) — plain Python class attributes
            # with no `var` declaration, so like Parser._known_traits
            # below they need an explicit entry here or codegen silently
            # infers 'int' and self-host miscompiles.
            '_INT_TYPE_NAMES': 'MojoSet *',
            '_FLOAT_TYPE_NAMES': 'MojoSet *',
            # Milestone 2 of
            # bugs/INTERP_generator_yield_entirely_unimplemented.md:
            # Interpreter._gen_tls (myinterpreter.py, a
            # `threading.local()`) — per-OS-thread storage for the
            # currently-running Mojo generator's `yield_fn`. Opaque to
            # the compiled path (only ever getattr/setattr'd, never
            # itself Mojo-observable), same treatment as 'object'/'Any'
            # elsewhere in this file.
            '_gen_tls': 'void *',
        }
        self.struct_field_types['Parser'] = {
            '_tok': 'MojoList *',
            '_pos': 'int64_t',
            '_filename': 'char *',
            '_pending_decs': 'MojoList *',
            # `set(_BUILTIN_TRAITS)` in Parser.__init__ (mojo_compiler.py)
            # — a plain Python class field, no `var` declaration for the
            # self-host type inferencer to consult, so an unlisted field
            # here silently fell back to "assume it's a pointer to the
            # containing struct" (Parser *), corrupting `x not in
            # self._known_traits` under self-hosting. See the "self-host
            # hardcoded struct tables" memory note: any new field added to
            # a self-hosted Python class needs a matching entry here.
            '_known_traits': 'MojoSet *',
            # `_CONV_KWS` is a class-level `set` literal (mojo_compiler.py,
            # used by the `ref`/`out`/`mut`/... soft-keyword handling in
            # _parse_for/_parse_funcdef/_parse_primary) — same class-field
            # gap as `_known_traits` above.
            '_CONV_KWS': 'MojoSet *',
        }
        self.struct_field_types['Scope'] = {
            'parent': 'Scope *',
            'vars': 'MojoDict *',
        }

        # Hardcode Scope method param types so 'name' is char* not int
        self.func_param_types['Scope_define'] = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope_get']    = ['Scope *', 'char *']
        self.func_param_types['Scope_set']    = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope___init__'] = ['Scope *', 'Scope *']
        # Lock these four against Pass 1.3c's later unconditional
        # overwrite -- see `_selfhost_locked_param_types`'s own comment
        # (__init__) for why this is necessary, not just defensive.
        self._selfhost_locked_param_types.update((
            'Scope_define', 'Scope_get', 'Scope_set', 'Scope___init__',
        ))
        # `MojoFunction.__call__(self, interpreter, *args, **kwargs)`:
        # register its kwargs slot so `_repack_method_call_spread_args`
        # (see that method's own docstring) can fix up
        # `BoundMethod.__call__`'s `f(self.interpreter, self.instance,
        # *args, **kwargs)` -- a mixed fixed-arg + spread call into this
        # exact signature shape, previously mis-packed (arity mismatch
        # against the real 4-param C signature). Index 3: self=0,
        # interpreter=1, args(vararg, one MojoList* slot)=2, kwargs=3.
        self._func_kwargs_slot['MojoFunction___call__'] = 3
        self._func_kwargs_has_vararg['MojoFunction___call__'] = True

        # Pre-populate AST node struct fields
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
        # These hardcoded fields are boxed (Optional/Any-typed AST-node refs
        # stored as int64_t) same as the annotation-scan-derived ones below —
        # pre-populated here so they bypass that scan (see the `if f_name not
        # in self.struct_field_types[s.name]` guard), so their boxed-ness must
        # be recorded explicitly too or repr() prints raw pointers for them.
        self.struct_boxed_fields['CallExpr'] = {'func'}
        self.struct_boxed_fields['BinaryOp'] = {'left', 'right'}
        self.struct_boxed_fields['UnaryOp'] = {'operand'}
        self.struct_boxed_fields['TernaryExpr'] = {'condition', 'then_val', 'else_val'}
        self.struct_boxed_fields['MemberExpr'] = {'obj'}
    self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}
    # Literal/collection node boxed fields: the `value` of a child
    # expression node is an int64_t handle to a nested AST node, not a
    # raw integer (e.g. WalrusExpr.value, YieldExpr.value, AwaitExpr.value).
    self.struct_boxed_fields['WalrusExpr'] = {'value'}
    self.struct_boxed_fields['YieldExpr'] = {'value'}
    self.struct_boxed_fields['YieldFromExpr'] = {'value'}
    self.struct_boxed_fields['AwaitExpr'] = {'value'}

    # ── AST statement/expression node fields (ALWAYS-ON, not gated) ──────
    # The compiled `mojoc` binary reads AST-node fields off the parser's
    # runtime objects (node.then_body, node.condition, node.body, ...) via
    # struct_field_types-driven member lowering. Those reads happen for ANY
    # input file, not just this repo's own self-host files — but
    # `_is_selfhost_file` is False for a plain user file, so the block above
    # (which registers only the 7 expression nodes CallExpr/BinaryOp/...)
    # would be skipped and every statement-node field access would fall back
    # to mojo_obj_getattr returning 0/NULL → garbage → segfault (the
    # if_else.mojo `mojo_str_join(parts=NULL)` crash). Register them here,
    # unconditionally, with the same C types the dataclass annotation-scan
    # below derives (object→int64_t boxed, str→char *, list→MojoList *,
    # dict→MojoDict *, bool→_Bool) so the baked struct layout matches.
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
    # Literal and collection expression nodes — the compiled binary's own
    # parser produces these for ANY input file, and unregistered fields
    # fall back to mojo_obj_getattr → 0/NULL → garbage operands (e.g. the
    # `0` in `x > 0` lowering to a node handle instead of int 0, crashing
    # _lower_binary_tail's mojo_str_join). Register the full field sets.
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
    # Boxed-object fields (int64_t handles to child AST nodes / values),
    # mirroring the same-named entries in the gated block above. Must be
    # recorded explicitly so repr()/getattr treat them as boxed handles
    # rather than raw integers (see the _is_selfhost_file block's comment).
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
    # SubscriptExpr.attrs is a MojoList of (name, value) tuple-pairs, so it
    # stays out of struct_boxed_fields; obj/index are already registered in
    # the gated block above — keep them here too since this block is the one
    # that runs for non-self-host user files.
    self.struct_boxed_fields['SubscriptExpr'] = {'obj', 'index'}

    # Fields declared `object = None` (or bare `object`, no
    # default_factory) in the real dataclass but hardcoded above to a
    # concrete 'MojoList *' ctype — see struct_nullable_container_fields'
    # own doc comment for why these need a NULL check in repr().
    self.struct_nullable_container_fields['SubscriptExpr'] = {'attrs'}
    self.struct_nullable_container_fields['IfStmt'] = {'else_body'}
    self.struct_nullable_container_fields['WhileStmt'] = {'else_body'}
    self.struct_nullable_container_fields['ForStmt'] = {'else_body'}
    self.struct_nullable_container_fields['TryStmt'] = {'else_body', 'finally_body'}
    self.struct_nullable_container_fields['ComptimeIfStmt'] = {'else_body'}
    self.struct_nullable_container_fields['ImportStmt'] = {'extra'}

    # Snapshot of every struct name whose field list is already known at
    # this point — either a real stdlib type seeded just above (Span) or,
    # when `_is_selfhost_file`, one of this repo's own hand-maintained
    # cheat-sheet entries (Scope/Token/Parser/Interpreter/_AutoStubValue/...).
    # The completeness passes further down (which auto-discover extra
    # fields by scanning method bodies for `self.x`/annotated-local reads
    # not caught by the normal `__init__`-assignment scan — the general
    # fix for stdlib files failing with "has no member named ...") must
    # never ADD to one of these: `_AutoStubValue = {}` above is a real,
    # deliberately empty field list (it's compiled as a bare scalar int
    # with dynamic getattr, not a real struct) — found via check-selfhost
    # regressing when a read-scan pass walked unrelated code elsewhere in
    # this same file that calls `_AutoStubValue(...)` and accesses an
    # attribute on the result (resolved dynamically via `__getattr__` in
    # real Python), and added that attribute as a phantom field here,
    # corrupting the intentionally-scalar C representation.
    self._selfhost_hardcoded_struct_names = frozenset(self.struct_field_types.keys())

    all_struct_defs = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    # Captured before _merge_struct_inheritance runs (it only mutates
    # .fields/.methods, never .bases, so ordering doesn't matter here) —
    # used by _lower_method_call's `super().method(...)` handling to find
    # the struct's base class name(s) at call-lowering time.
    self._struct_bases = {s.name: list(getattr(s, 'bases', None) or [])
                           for s in all_struct_defs if isinstance(s, StructDef)}
    # Structs with at least one base name that isn't any StructDef this
    # compilation unit knows about — e.g. `class IDGatherer
    # (html.parser.HTMLParser)`, where the parser only captures the
    # leading name token of a dotted base expression (see
    # mojo_compiler.py's ClassDef/StructDef base-list parsing), so even
    # `html` never resolves to a real struct. Used by
    # _lower_struct_method_call's auto-stub path: a method call that
    # can't be found on the struct's own/resolved-base methods, on one
    # of these, is inherited from a base with no native definition
    # anywhere — not a same-struct forward reference — so the auto-stub
    # must be a real (weak) definition, not a bare declaration.
    #
    # This must be a TRANSITIVE closure, not just a direct-base check:
    # e.g. Lib/logging/handlers.py's `class BaseRotatingHandler
    # (logging.FileHandler)` has an unresolved base (bare `import
    # logging` never pulls logging/__init__.py's StructDefs into this
    # compile's known-struct set, unlike `from logging import X`), so
    # BaseRotatingHandler correctly lands in this set — but its OWN
    # subclass `TimedRotatingFileHandler(BaseRotatingHandler)` has a
    # base name that IS a known StructDef (BaseRotatingHandler, defined
    # right there in the same file), so a direct-base-only check never
    # flagged the SUBCLASS, even though it inherits (and calls, e.g.
    # `self.handleError(...)`, `self._open()`) the exact same
    # never-defined-anywhere methods through that chain. Those calls
    # fell into the bare-forward-declaration branch below instead of
    # the weak-definition one, leaving a real undefined symbol at link
    # time (confirmed via `mojo.py build .../logging/handlers.py`).
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
    # Pre-register all struct names so cross-references in _collect_self_assigns work
    # regardless of definition order (e.g. DispatchSolver before FunctionCompilability).
    for _s in all_struct_defs:
        if isinstance(_s, StructDef) and _s.name not in self.struct_field_types:
            self.struct_field_types[_s.name] = {}
    # Two unrelated classes sharing a bare name (found via mojo_compiler.py's
    # FunctionDef/ExprStmt/StringLiteral/... vs ast_nodes.py's own, entirely
    # separate, same-named AST-node classes — both reachable in the same
    # self-hosted closure since myinterpreter.py imports ast_nodes purely
    # for method-signature type annotations, never actually instantiating
    # them) must NOT have their fields merged into the same
    # struct_field_types[name] entry: struct reflection (_struct_type_id,
    # getattr/setattr/dataclasses.fields/repr) dispatches purely on that
    # bare name, so every REAL instance of either class — regardless of
    # which module it's really from — would get read through one
    # Frankenstein field list combining both. Found via `repr(ast)` on
    # even hello.mojo's trivial 2-statement AST once self-hosted:
    # FunctionDef gained a phantom `is_static` field (only ast_nodes.py's
    # FunctionDef has one) and unrelated later fields read as raw
    # addresses. First StructDef seen under a given name wins entirely;
    # track by identity (in the cross-module-shared _struct_name_owner,
    # not a call-local dict — a name claimed while compiling one imported
    # module must stay claimed when a *different* temp_gen sub-compile
    # later reaches an unrelated same-named class in another module) so a
    # legitimate re-scan of the *same* node (e.g. the transitive closure
    # reaching one file via two import paths) is still a harmless no-op,
    # not itself treated as a collision.
    # Constructor call-site scalar inference (bugs/hard/CODEGEN_
    # unannotated_init_param_field_type_defaults_int64.md): the
    # struct-field-collection loop just below (`_collect_self_assigns`)
    # types `self.field = unannotated_param` purely from __init__'s own
    # declared params, with zero cross-reference to how the class is
    # actually constructed — `Widget("hello")` right there in the same
    # file never informs `Widget.__init__`'s own `label` parameter,
    # which silently defaults to int64_t (the raw pointer's bit pattern
    # printed as a decimal integer instead of the real string). This
    # codebase already has a general mechanism for exactly this class of
    # problem for FREE functions (Pass 1.3d's cross-call scalar
    # contract, a few thousand lines down in this same method) — but
    # that pass runs too LATE to help here: it depends on
    # self._inferred_var_types, itself only populated even later, and
    # by the time it runs, `_collect_self_assigns` below has already
    # locked in every field's type. Rather than reordering Pass 1.3d
    # (broad, high-risk — this exact call-argument/parameter type-
    # inference machinery has already produced two real regressions
    # elsewhere this session), this is a standalone, narrower, EARLY
    # pass: only DIRECT LITERAL constructor arguments (StringLiteral/
    # FloatLiteral) are observed, not the fuller "IdentExpr referencing
    # an already-inferred variable" evidence Pass 1.3d's free-function
    # version uses (that needs machinery not built yet at this point in
    # gen_module). Still resolves the common, directly-reproducible
    # shape (a literal argument passed straight to a constructor)
    # additively — every unresolvable case (no literal evidence, or
    # disagreeing call sites) is left at today's int64_t default,
    # unchanged. Kept in its OWN attribute (not self._inferred_param_
    # types) since that dict is unconditionally reset to {} later, at
    # Pass 1.3c (~line 29351) — harmless for THIS pass's own consumer
    # (which reads it before that reset), but a distinct name avoids
    # any ambiguity about which pass owns which entries.
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
                # Avoid `next(gen, default)` here — a self-hosted build
                # of this very file failed to link with an undefined
                # `_next` symbol the last time this pattern was used
                # over a freshly-built generator (see the identical,
                # already-documented gotcha a few thousand lines down
                # at Pass 1.3d's own scalar-type resolution).
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

    for s in all_struct_defs:
        if isinstance(s, StructDef) and s.name not in self._struct_name_owner:
            self._struct_name_owner[s.name] = id(s)
    # Pre-create every owned struct's field dict BEFORE any field is
    # resolved below (same register-before-resolve convention
    # _materialize_imported_struct established for cycle safety in
    # 3fc4073). Without this, a field annotation naming a struct defined
    # LATER in the same file (`struct C: d: D` with D textually after C)
    # saw no entry yet and fell to the opaque int64_t default -- while
    # the same shape across module boundaries already worked via
    # _materialize_imported_struct's own recursion.
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
            # For now, assume all struct fields on unknown types are pointers to the same struct
            # (e.g. Scope.parent is Scope*, Interpreter.scope is Scope*, etc.)
            # This is a heuristic to handle incomplete type information from imports
            for field in (s.fields if hasattr(s, 'fields') else []):
                if isinstance(field, VarDecl) and field.name and field.name != 'self':
                    # For untyped fields, assume they're pointers to the containing struct
                    if not field.type_ann and field.name not in self.struct_field_types[s.name]:
                        # An untyped (`type_ann is None`) VarDecl here isn't
                        # always a genuinely-unresolvable field: it's ALSO
                        # the exact placeholder shape `_merge_struct_
                        # inheritance` copies in from a BASE class's
                        # `.fields` once that base's own fields were
                        # already fully resolved by an earlier compile
                        # pass (module caching — the base struct's real
                        # per-field types live in `self.struct_field_
                        # types[base_name]`, never in the placeholder
                        # VarDecl's own `type_ann`, by design: see the
                        # `_collect_self_assigns`/`_collect_self_reads`
                        # completion loop just below, which appends
                        # `VarDecl(name=fn, type_ann=None, value=None)`
                        # for exactly this reason). Blindly guessing
                        # "pointer to self" for such an inherited field
                        # clobbers its real, already-known type — e.g. a
                        # subclass with no `__init__` of its own
                        # (`class Parser(PLexer): ...`, only ever using
                        # the base's inherited constructor) got EVERY
                        # inherited field (`pos`, `src`, `filename`,
                        # `tokens`, all correctly `int64_t`/`char *`/
                        # `MojoList *` on the base struct `PLexer`)
                        # redeclared `struct Parser *` on `Parser`
                        # itself — a self-referential pointer type that
                        # is never actually assigned a `Parser *` value
                        # anywhere, so every real (scalar/string/list)
                        # value written through it hit GCC's `-fgimple`
                        # frontend as a hard type mismatch, or — for a
                        # `-` used on such a field's boxed-as-a-property
                        # value further downstream — a frontend internal
                        # compiler error. Look the field up on each base
                        # (in MRO order, matching `_merge_struct_
                        # inheritance`'s own `s.bases` walk) BEFORE
                        # falling back to the same-struct-pointer guess,
                        # so a genuinely inherited, already-resolved
                        # field keeps its real type and only a truly
                        # unknown field (not found on any base either —
                        # the original `Scope.parent`-style case this
                        # heuristic was written for) still gets the
                        # same-struct-pointer fallback. Found via Tools/
                        # cases_generator/parsing.py's `Parser(PLexer)`.
                        _inherited_ft = None
                        for _base_name in (getattr(s, 'bases', None) or []):
                            _base_ft = self.struct_field_types.get(_base_name, {})
                            if field.name in _base_ft:
                                _inherited_ft = _base_ft[field.name]
                                break
                        self.struct_field_types[s.name][field.name] = (
                            _inherited_ft if _inherited_ft is not None else s.name + ' *')
            # Record which of this struct's OWN methods are generators
            # (`FunctionDef.is_generator`) — used by `_cls_refs_supported`/
            # `_cpp_expr`'s `cls.<method>(...)` call handling to refuse a
            # call to another compiled GENERATOR method via `cls` (that
            # needs its own coroutine-construction call convention this
            # fix does not add — see those two call sites' own comments)
            # even when the method's mangled name also happens to be a
            # real `@classmethod` (`self._classmethod_names` is populated
            # purely from the decorator, independent of whether the
            # method is ALSO a generator — Lib/enum.py's `Flag.
            # _iter_member_by_value_` is exactly both at once). Populated
            # here (not derived on demand from `self._classmethod_names`/
            # `self.func_return_types`, neither of which distinguishes
            # "compiled as an ordinary function" from "compiled as a
            # coroutine") since this same loop already has `s.methods`
            # in scope for every struct. See bugs/CODEGEN_generator_
            # function_Lib_enum.md's 2026-08-21 update.
            self._struct_generator_method_names.setdefault(s.name, set()).update(
                m.name for m in s.methods if getattr(m, 'is_generator', False))
            # Collect class-level attributes (non-self, non-method assignments at class body)
            self._class_attrs[s.name] = {}
            for field in s.fields:
                if isinstance(field, AssignStmt):
                    if isinstance(field.target, IdentExpr):
                        aname = field.target.name
                        # Store a C-safe mangled name for this class attribute
                        mangled = f"_classattr_{s.name}__{aname}"
                        self._class_attrs[s.name][aname] = mangled
                        # Pre-populate _global_var_types so Phase 2a sees the correct type
                        v = field.value
                        ctype = _class_attr_ctype(v)
                        if ctype is not None:
                            self._global_var_types[mangled] = ctype
                            # A container-valued class-body attribute (e.g.
                            # `_PRELUDE_GENERICS = {...}`) is ALSO an
                            # instance struct field when read via `self.X`:
                            # _lower_MemberExpr checks struct_field_types
                            # (direct `self->X` read) BEFORE the _class_attrs
                            # global redirect, so without an entry here the
                            # self-reads scan defaulted the field to a
                            # 32-bit `int` and _alloc_{s.name}'s seeding
                            # guard (`field type == class-global type`)
                            # skipped the seed — leaving the instance slot
                            # as raw malloc garbage. The first
                            # `self._X.items()` / `x in self._X` then
                            # dereferenced that garbage (deterministic
                            # SIGSEGV/SIGABRT; the _PRELUDE_GENERICS one
                            # reproduced 100% with MallocGuardEdges=1).
                            # Register the matching container type here so
                            # the struct field is correct AND the alloc
                            # seed fires (Python semantics: a fresh
                            # instance's attr starts as the class value).
                            cur = self.struct_field_types[s.name].get(aname)
                            if cur is None or cur in ('int', 'int64_t'):
                                self.struct_field_types[s.name][aname] = ctype
                            # Record the container's ELEMENT type too
                            # (`_field_elem_types`, the same map an
                            # instance `self.x = [...]` assignment in
                            # `__init__` already populates — see the
                            # CallExpr-branch companion in
                            # `_collect_self_assigns`) so a later `for x
                            # in self.<field>:` inside a generator body
                            # (`_cpp_for_stmt`) knows whether to unpack
                            # elements as `char *`/`int64_t` instead of
                            # guessing. Without this, a class-body tuple-
                            # of-strings attribute (save_env.py's
                            # `resources = ('sys.argv', 'cwd', ...)`)
                            # left `_field_elem_types` empty, and the
                            # generator-body for-loop defaulted every
                            # element to `int64_t` — wrong C type for a
                            # string, cascading into `name.replace(...)`
                            # "request for member ... non-class type
                            # int64_t" downstream.
                            if ctype == 'MojoList *' and isinstance(v, (ListExpr, TupleExpr)):
                                self._field_elem_types.setdefault(s.name, {})[aname] = (
                                    self._infer_list_elem_type(v.elements))
                        elif isinstance(v, StringLiteral):
                            self._global_var_types[mangled] = 'char *'
                        elif isinstance(v, (IntLiteral, BoolLiteral)):
                            self._global_var_types[mangled] = 'int64_t'
                        else:
                            self._global_var_types[mangled] = 'int64_t'
                        # Seed `self._global_dict_val_types` from this
                        # class-body attribute's OWN declared annotation
                        # (`_X: dict[K, V] = {...}`), mirroring the
                        # struct-field pre-pass's identical eager seed
                        # of `_field_dict_val_types` a little further
                        # down in this same method (see that seed's own
                        # docstring for the full "generator methods are
                        # translated before the lazy per-statement pass"
                        # rationale — the class-level-global sibling has
                        # the exact same timing problem). Needed so a
                        # `cls.<dict-class-attr>.get(key)` read inside a
                        # compiled @classmethod generator (see this
                        # file's `_cpp_expr` MemberExpr/CallExpr `cls.
                        # <attr>` handling) can resolve the dict's real
                        # VALUE type instead of defaulting to int64_t.
                        # A dict literal WITH pairs already gets this
                        # from Phase 1.7's `_phase17_infer_global_type`
                        # (`_global_dict_val_types[_gname] = _vt`, from
                        # the pairs' own values) — but that only fires
                        # for a NON-EMPTY literal; an empty `{}` (the
                        # common class-attr-declared-then-populated-
                        # elsewhere idiom, e.g. `_value2member_map_:
                        # dict[Any, Flag] = {}`) needs the annotation
                        # instead, exactly like the struct-field case.
                        # Deliberately a SEPARATE, independent statement
                        # (not nested inside the ctype if/elif/else
                        # chain just above) so it can never change that
                        # chain's own control flow for a class attr with
                        # no annotation, or perturb `struct_field_types`
                        # for a non-container-valued attribute.
                        if field.type_ann is not None:
                            _dv_cls_early = self._annotation_dict_val_type(field.type_ann)
                            if _dv_cls_early is not None:
                                self._global_dict_val_types[mangled] = _dv_cls_early
            # Explicit field declarations. A dataclass field with a
            # default (`x: Type = default`, the normal shape for every
            # trailing/optional field — e.g. `decorators: list =
            # field(default_factory=list)`) parses as an AssignStmt with
            # its type_ann set (not a VarDecl, which is a bare `x: Type`
            # declaration with no value) — see mojo_compiler.py's
            # annotated-assignment parsing. Without this, such fields
            # were invisible to struct_field_types entirely: found via
            # StructDef's own _fieldwise_ctor_synthesized field aborting
            # through the generic getattr fallback (struct_field_types
            # only had StructDef's 3 no-default fields, missing all 6
            # that have one).
            for field in s.fields:
                _is_typed_assign = (isinstance(field, AssignStmt)
                                     and isinstance(field.target, IdentExpr)
                                     and field.type_ann is not None)
                if isinstance(field, VarDecl) or _is_typed_assign:
                    f_name = field.name if isinstance(field, VarDecl) else field.target.name
                    # Don't overwrite hardcoded entries (e.g. BinaryOp.op)
                    if f_name not in self.struct_field_types[s.name]:
                        ft = _mojo_type(field.type_ann)
                        # BUG-2026-014 (box.3d/game): a bare capitalized
                        # annotation naming a struct this compile already
                        # knows (`hopper: Hopper` in the struct's own home
                        # module, Hopper imported and materialized by
                        # _register_imported_structs -- or a same-file
                        # struct, forward reference included via the
                        # pre-registration pass above) must resolve to a
                        # real `Hopper *` field, not _mojo_type's opaque
                        # int64_t default. The stateless default made the
                        # DEFINING module's own typedef collapse nested
                        # machine-component fields to scalars, so every
                        # later `b.hopper.input_count` -- here AND in every
                        # importing module -- fell through to the dynamic
                        # `_mojo_dispatch_getattr` path (the reported
                        # `AttributeError: input_count`). This mirrors
                        # exactly what the cross-module twin of this code
                        # (_materialize_imported_struct's per-field
                        # resolution via _imported_field_ctype ->
                        # _resolve_type) already does; kept inline rather
                        # than switching this site to _resolve_type
                        # wholesale so every OTHER unresolved-annotation
                        # default stays byte-identical.
                        _fann_s = str(field.type_ann).strip() if field.type_ann else ''
                        if (_fann_s and _fann_s[0].isupper() and '[' not in _fann_s
                                and '.' not in _fann_s and '*' not in _fann_s
                                and _fann_s not in self._IMPORTED_STRUCT_SKIP_BASENAMES
                                and _TYPE_MAP.get(_fann_s) is None):
                            if _fann_s in self.struct_field_types:
                                ft = f"{_fann_s} *"
                            else:
                                # Not registered yet -- materialize it from
                                # THIS FILE's own imports on demand (same
                                # lookup _register_imported_structs uses,
                                # which doesn't fire here because its gates
                                # key on param-types/ctor-calls, not
                                # field-type usage). Mirrors the per-field
                                # bare-name recursion
                                # _materialize_imported_struct itself does
                                # for ITS fields, applied one level up to a
                                # locally-defined struct's fields.
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
                        # Fixed-size-array field: `var x: [ElemType; N]`.
                        # See _FIXED_ARRAY_ANN_RE's own comment and
                        # bugs/BUG-2026-008.md (box.3d/game) — `ft` here
                        # becomes the marker string "ElemCtype[N]" (never
                        # produced by any other branch: it doesn't end in
                        # ' *', isn't a bare _TYPE_MAP/struct name), which
                        # the struct-typedef emission (gen_module) turns
                        # into a REAL embedded C array field, and
                        # _lower_subscript's dedicated branch (via
                        # self._array_field_sizes) turns `obj.field[i]`
                        # into real C array indexing instead of falling
                        # through to the MojoList*/generic-pointer paths.
                        _arr_m = (_FIXED_ARRAY_ANN_RE.match(str(field.type_ann).strip())
                                  if field.type_ann else None)
                        if _arr_m:
                            _elem_nm, _size_txt = _arr_m.group(1), _arr_m.group(2)
                            _n = (int(_size_txt) if _size_txt.isdigit()
                                  else self._module_const_int(_size_txt, stmts, imported_stmts))
                            if _n is not None and _n > 0:
                                # A locally-defined struct element type is
                                # embedded BY VALUE (the bare struct-typedef
                                # name, not "Name *" — this is genuinely
                                # different from every other struct-typed
                                # field in this codegen, which are always
                                # pointers; see the array-field comment
                                # block above _FIXED_ARRAY_ANN_RE).
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
                        # If the type resolved to a generic container pointer (MojoList *,
                        # MojoDict *, MojoSet *, or double-pointer like MojoDict * *)
                        # but there is a locally-defined struct, prefer the local struct.
                        # Also handle Pointer[LocalStruct[...]] → LocalStruct *.
                        if field.type_ann and not _arr_m:
                            _ann_str = str(field.type_ann)
                            # Extract the outermost base name (e.g. 'Pointer', 'Dict', 'List')
                            _outer_base = _ann_str.split('[')[0].strip()
                            _ptr_wrappers = ('UnsafePointer', 'OwnedPointer',
                                             'ArcPointer', 'Pointer', 'Reference')
                            if _outer_base in _ptr_wrappers and '[' in _ann_str:
                                # Pointer[InnerType[...], origin] — grab InnerType base
                                _inner = _ann_str.split('[', 1)[1]
                                _inner_base = _inner.split('[')[0].strip()
                                if _inner_base in self.struct_field_types:
                                    # Pointer[LocalStruct[...]] → LocalStruct *
                                    ft = f'{_inner_base} *'
                            elif ft.endswith(' *') and _outer_base in self.struct_field_types:
                                # Direct: List[T] → List * (override MojoList *)
                                ft = f'{_outer_base} *'
                        self.struct_field_types[s.name][f_name] = ft
                        # Seed `self._field_dict_val_types` from this
                        # field's OWN declared annotation (`var x: dict[K,
                        # V]`) at this same early pre-pass, using the
                        # SAME `_annotation_dict_val_type` helper the
                        # ordinary per-statement AssignStmt lowering later
                        # uses for its own (lazier) seeding -- reused, not
                        # duplicated. Needed so a compiled GENERATOR
                        # METHOD's `self.<dict-field>.get(key)` (struct-
                        # pointer-yield support, see
                        # _infer_simple_expr_ctype's docstring) can see
                        # the field's real dict value type: generator
                        # methods are translated in gen_module's
                        # "Milestone C step 3" pass, which runs BEFORE
                        # the ordinary per-statement body-compile loop
                        # that populates `_field_dict_val_types` lazily
                        # (from an ANNOTATED `self.x: dict[K, V] = ...`
                        # assignment inside `__init__`'s own body) — a
                        # class-body-declared field's annotation is
                        # already sitting right here, so there is no
                        # reason to wait for that later pass to see it
                        # for THIS shape.
                        _dv_early = self._annotation_dict_val_type(field.type_ann)
                        if _dv_early is not None:
                            self._field_dict_val_types.setdefault(s.name, {})[f_name] = _dv_early
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
                        if (ft == 'MojoList *' and field.type_ann
                                and '[' in str(field.type_ann)):
                            _li = gimple_ctypes._split_top_level_commas(
                                str(field.type_ann).split('[', 1)[1].rstrip(']').strip())
                            if _li:
                                _et = self._resolve_type(_li[0].strip())
                                if _et and _et not in ('int64_t', 'MojoList *'):
                                    self._field_elem_types.setdefault(s.name, {})[f_name] = _et
                                elif _et == 'MojoList *':
                                    self._field_elem_types.setdefault(s.name, {})[f_name] = _et

            # Always scan ALL methods for self.x = ... to build complete field list.
            # Uses the generic _walk_ast walker (module-level, above) rather than
            # a hand-rolled list of body-bearing attribute names, so assignments
            # nested inside elif/try-except/finally/with/match bodies are seen too
            # (a real, previously-missed gap: fields only ever assigned inside such
            # a branch were absent from struct_field_types and the generated C
            # struct never declared them at all — not merely mistyped).
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
                        # Was: `fn not in found` (first assignment to a
                        # given field wins, later ones in the SAME method
                        # silently ignored). Real bug: turtle.py's
                        # RawTurtle.__init__ assigns `self.screen` from
                        # FOUR different branches of one if/elif chain —
                        # the FIRST in document order is
                        # `self.screen = canvas` where `canvas` is an
                        # unannotated, defaulted (`=None`) parameter, so
                        # `ft` below is the generic 'int64_t' fallback;
                        # a later, much more specific branch in the very
                        # same __init__ (`self.screen =
                        # TurtleScreen(canvas)`, `cn in
                        # self.struct_field_types` below) would have
                        # correctly resolved to 'TurtleScreen *', but
                        # "first wins" never let it compete. The wrongly-
                        # int64_t-typed `screen` field then made every
                        # `self.screen.<method>(...)` call site (real:
                        # RawTurtle._color/_colorstr calling
                        # `self.screen._color(args)`) unresolvable to a
                        # real struct method, silently lowered as an
                        # "int64_t.<method>() stubbed" no-op instead —
                        # which in turn made `_color`'s OWN inferred
                        # return type wrong (int64_t instead of the real
                        # pointer/string type its body actually produces
                        # via the stub's fallthrough), cascading into
                        # `-fgimple`'s honest "invalid conversion in
                        # return statement" for every caller (`pencolor`/
                        # `fillcolor`) whose forward-declared return type
                        # was inferred from that wrong `_color` return
                        # type. Mirrors the EXACT same weak-vs-strong
                        # upgrade reasoning the cross-method `can_override`
                        # check below already uses (there: 'int' ->
                        # pointer, across separate methods) — generalized
                        # here to also apply WITHIN one method's own
                        # multiple assignment sites, and to the 'int64_t'
                        # weak default too (the case that actually fires
                        # for an unannotated/defaulted parameter, not just
                        # bare 'int'). Only ever upgrades a generic
                        # int/int64_t guess to a more specific type —
                        # never fights two already-specific candidates
                        # against each other, so a field genuinely
                        # reassigned different concrete types across
                        # branches keeps whichever specific type is
                        # found first, same as before.
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
                                # A comprehension is a DIFFERENT AST node
                                # than a literal ListExpr/DictExpr/SetExpr
                                # (see bugs/hard/CODEGEN_unannotated_
                                # init_param_field_type_defaults_int64.md's
                                # "Sibling gap" section) and matched none
                                # of the cases above, falling to the
                                # generic 'int' default -- found via
                                # Tools/cases_generator/cwriter.py's
                                # `self.indents = [i * 4 for i in
                                # range(indent + 1)]` (declared `int
                                # indents;`, the real value a truncated
                                # MojoList* pointer).
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
                                    # _alloc_StructName() returns StructName *
                                    sname = cn[len('_alloc_'):]
                                    ft = sname + ' *'
                                elif cn in self.struct_field_types:
                                    ft = cn + ' *'
                                elif (isinstance(cfn, MemberExpr)
                                      and cfn.member in _STR_RETURNING_METHODS):
                                    # A chained method call (`loader.prefix.
                                    # replace(...)`) has a MemberExpr func, not
                                    # a bare IdentExpr, so `cn` above is always
                                    # '' for it -- every one of these fell to
                                    # the generic 'int' default below regardless
                                    # of the method actually being one of
                                    # Python's well-known ALWAYS-str-returning
                                    # str methods. A field seeded 'int' here
                                    # then gets a real `char *` value written
                                    # into it (self.prefix = ...replace(...)),
                                    # a struct-field type mismatch ("non-trivial
                                    # conversion" family of GIMPLE errors) rather
                                    # than a targeted fix -- found via importlib/
                                    # resources/readers.py's ZipReader.__init__.
                                    ft = 'char *'
                                elif (isinstance(cfn, MemberExpr)
                                      and cfn.member in _LIST_RETURNING_METHODS):
                                    ft = 'MojoList *'
                                else:
                                    ft = 'int'
                            else:
                                ft = 'int'
                            found[fn] = ft
                    elif isinstance(node, MultiAssignStmt):
                        for tgt in node.targets:
                            fn = _self_member(tgt)
                            if fn is not None and fn not in found:
                                found[fn] = 'int'
                    elif isinstance(node, AugAssignStmt):
                        fn = _self_member(node.target)
                        if fn is not None and fn not in found:
                            found[fn] = 'int64_t'

            # Second pass: fields that are only ever *read* via `self.x` and never
            # assigned anywhere in this class's own methods (e.g. a field a real
            # subclass, possibly in another module, is responsible for setting —
            # `_markupbase.ParserBase.rawdata`/`updatepos` is the canonical example:
            # every method reads `self.rawdata` but only a subclass like
            # `html.parser.HTMLParser` ever assigns it). Compiling this class
            # standalone can't see that subclass, but the C struct still must
            # declare the field or every read is a hard 'has no member named'
            # compiler error — so register it with the same generic boxed-object
            # representation ('int') already used for any field whose type can't
            # be pinned down statically; runtime attribute access on it still goes
            # through the normal dynamic dispatch machinery.
            # `self.foo` walked generically by `_walk_ast` also matches the
            # `.func` of a method CALL (`self.foo(...)`) — that is a read of
            # the *method* `foo`, never a struct field, and must not be
            # confused with one. Otherwise every ordinary method call inside
            # the class's own methods (e.g. BufferedSubFile.close() calling
            # `self.pushlines(...)`) synthesizes a spurious int-typed field
            # named after the method, which then fights the method's real
            # signature — the `non-trivial conversion`/`declared void`/
            # `conflicting types` family of C errors on the generated
            # struct's getattr/setattr/repr dispatch functions.
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
                        # Unannotated params hold object handles (pointer-width);
                        # default to int64_t so a field assigned from one isn't
                        # truncated to 32-bit int (size-mismatch cast on read).
                        if ptype:
                            pm[pname] = self._resolve_type(ptype)
                        elif pname in _defaults:
                            # Infer type from the default value when no
                            # annotation is provided (e.g. `file=""`).
                            _dv = _defaults[pname]
                            if isinstance(_dv, StringLiteral):
                                pm[pname] = 'char *'
                            elif isinstance(_dv, BoolLiteral):
                                pm[pname] = '_Bool'
                            else:
                                pm[pname] = 'int64_t'
                        elif (method.name == '__init__'
                              and pname in self._ctor_lit_param_types.get(s.name, {})):
                            # Real constructor call-site evidence (a
                            # literal argument observed above) beats the
                            # generic int64_t default — see bugs/hard/
                            # CODEGEN_unannotated_init_param_field_type_
                            # defaults_int64.md. Scoped to __init__ only:
                            # a same-named param on a DIFFERENT method has
                            # no relation to how the class was constructed.
                            pm[pname] = self._ctor_lit_param_types[s.name][pname]
                        else:
                            pm[pname] = 'int64_t'
                new_fields = {}
                _collect_self_assigns(method.body, pm, new_fields)
                for fn, ft in new_fields.items():
                    # Don't overwrite annotation-based / hardcoded field types,
                    # annotations are the source of truth for struct field types.
                    # However, allow overriding 'int' (from = None / = 0) with a more
                    # specific pointer type discovered in a later method assignment.
                    existing_ft = self.struct_field_types[s.name].get(fn)
                    can_override = (existing_ft == 'int' and ft.endswith(' *'))
                    if fn not in self.struct_field_types[s.name] or can_override:
                        self.struct_field_types[s.name][fn] = ft
                        if fn not in already:
                            s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                            already.add(fn)
            if s.name in self._selfhost_hardcoded_struct_names:
                # Authoritative hand-maintained field list (see the
                # snapshot comment above) — never auto-extend it.
                continue
            for method in s.methods:
                read_fields = {}
                _collect_self_reads(method.body, read_fields)
                for fn, ft in read_fields.items():
                    if fn not in self.struct_field_types[s.name]:
                        # Before falling back to the generic 'int'
                        # read-only default, check whether a base class
                        # already resolved this field to something more
                        # specific. A field ASSIGNED only inside a base
                        # class's `__init__` (`TurtleScreenBase.__init__`:
                        # `self.cv = cv`) is invisible to this class's own
                        # `_collect_self_assigns` scan whenever the
                        # subclass overrides `__init__` itself (even if
                        # that override's only job is calling
                        # `Base.__init__(self, cv)` — `_merge_struct_
                        # inheritance` excludes an overridden method from
                        # `s.methods` entirely, by design, so the base
                        # method's own self-assignment is never walked
                        # for THIS class). The field is still read all
                        # over the subclass's own methods
                        # (`self.cv.coords(...)`/`self.cv.config(...)`),
                        # so `_collect_self_reads` finds it and, absent
                        # this check, always guesses the generic 'int'
                        # boxed-object fallback — even when the base
                        # class already pinned it to a real, specific
                        # type (here 'int64_t', from the unannotated
                        # `cv` constructor param). A mixed 'int' (this
                        # class's struct field) vs 'int64_t' (the actual
                        # value stored through it, e.g. via another
                        # subclass that DOES scan the base assignment)
                        # cross-struct-instance type split is exactly the
                        # shape GCC's `-fgimple` rejects as "non-trivial
                        # conversion"/"type mismatch in binary
                        # expression" once two differently-typed
                        # monomorphized copies of a shared method
                        # (`_pointlist`, common to `TurtleScreenBase`/
                        # `TurtleScreen`/`_Screen`) exist side by side.
                        # Mirrors the identical base-lookup pattern the
                        # VarDecl-completion pass above already uses
                        # (same MRO-order walk over `s.bases`) — only
                        # ever upgrades a generic guess to a more
                        # specific inherited type, never overrides an
                        # already-specific local finding.
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

    # Fourth completeness pass: fields accessed only through a *locally
    # annotated* variable of a known struct type, not through `self`
    # directly. E.g. _pyrepl/completing_reader.py's `complete.do()`:
    #   r: CompletingReader
    #   r = self.reader
    #   r.msg = "..."
    # `r`'s own class (`complete`, a Command) is unrelated to
    # CompletingReader — the field belongs on CompletingReader, a
    # *different* struct than the one whose method we're scanning, so
    # this can't be folded into the per-`s` passes above (each of those
    # only ever registers fields on `s.name` itself). Runs after every
    # struct's own fields are known so `local_types` below can recognize
    # any struct name regardless of definition order.
    # This also covers a plain free function's local variable, not just a
    # method's (e.g. asyncio/__main__.py's `repl_thread = REPLThread(...)`
    # / later `repl_thread.daemon = True`, both inside a module-level
    # function, no class involved at all).
    _struct_by_name = {st.name: st for st in all_struct_defs
                        if isinstance(st, StructDef)
                        and self._struct_name_owner.get(st.name) == id(st)}

    # Per-top-level-statement caches for the two `_walk_ast` sub-scans
    # below (see bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
    # rescan.md, Phase 2). `_scan_body_for_local_field_access` used to
    # call `_walk_ast(body)` twice on every invocation, and `body`
    # (`imported_stmts` in particular) grows to O(total transitive tree
    # size) at EVERY nesting level (see the doc's root-cause section) —
    # summed over N levels that's O(N^2) total node visits. Since
    # `_walk_ast(list_of_stmts)` is exactly the concatenation of
    # `_walk_ast([s])` for each `s` in the list (no cross-statement
    # state in `_walk_ast` itself), the expensive per-node walk of each
    # INDIVIDUAL top-level statement's own subtree can be memoized by
    # `id(stmt)` and reused verbatim across every later call that also
    # includes that same statement object — shared by reference into
    # every temp_gen exactly like `_all_transitive_stmts_ordered`
    # (see its own sharing block in `_compile_imported_module`), so the
    # memoization applies tree-wide, not just within one level.
    #
    # Care point: the CANDIDATES cached here are the raw syntactic
    # matches only (VarDecl-with-annotation / `x = Ctor(...)` shape,
    # MemberExpr-with-IdentExpr-obj minus dunder members) — NOT
    # filtered by `ann in self.struct_field_types` / `not in
    # self._selfhost_hardcoded_struct_names` / `!= own_struct_name`.
    # Those three filters are all time-/call-dependent (struct_field_
    # types grows monotonically as unrelated structs are discovered
    # elsewhere during compilation; _selfhost_hardcoded_struct_names is
    # a per-gen_module-call snapshot; own_struct_name is a per-call
    # parameter) — baking them into the cache at first-visit time would
    # silently and permanently miss any candidate whose governing
    # struct becomes known only on a LATER call. Re-applying them fresh
    # against the cached candidate list on every call (cheap — a plain
    # list iteration, no `_walk_ast`) preserves the original's exact
    # per-call semantics while still eliminating the repeated tree
    # walk itself, which is what the profile shows dominating cost.
    def _scan_stmt_var_candidates(stmt):
        sid = id(stmt)
        cached = self._field_scan_var_cache.get(sid)
        if cached is not None:
            return cached
        cands = []
        for node in _walk_ast(stmt):
            if isinstance(node, VarDecl) and node.type_ann:
                cands.append((node.name, str(node.type_ann).strip()))
            # `x = SomeStruct(...)` — no explicit annotation, but the
            # constructor call itself pins the type just as well.
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
        local_types = {}
        for stmt in body:
            for name, ann in _scan_stmt_var_candidates(stmt):
                if (ann in self.struct_field_types and ann != own_struct_name
                        and ann not in self._selfhost_hardcoded_struct_names):
                    local_types[name] = ann
        if not local_types:
            return
        for stmt in body:
            for obj_name, fn in _scan_stmt_member_candidates(stmt):
                target_struct = local_types.get(obj_name)
                if target_struct is None:
                    continue
                if fn in self.struct_field_types[target_struct]:
                    continue
                self.struct_field_types[target_struct][fn] = 'int'
                target_def = _struct_by_name.get(target_struct)
                if target_def is not None and not any(
                        isinstance(f, VarDecl) and f.name == fn for f in target_def.fields):
                    target_def.fields.append(VarDecl(name=fn, type_ann=None, value=None))

    # `_walk_ast` already recurses into every nested FunctionDef/StructDef
    # method/if/try/loop body reachable from a statement list, so a single
    # call over the whole module's top-level statements also reaches every
    # function body AND every class method body in one pass — no need to
    # separately iterate `s.methods` vs. free `FunctionDef`s vs. bare
    # module-level code (e.g. asyncio/__main__.py's `repl_thread = REPLThread(...)`
    # sits directly under an `if __name__ == "__main__":` at module scope,
    # not inside any function or class at all).
    _scan_body_for_local_field_access(stmts, None)
    if self.do_imports or self.link_imports:
        _scan_body_for_local_field_access(imported_stmts, None)

    # Register struct constructors as functions returning T *
    # Include both current module and imported module structs
    # Preserve types registered by _emit_stdlib_import_externs (Phase 0 pre-pass) so
    # they survive the Phase 1 reset. _RUNTIME_FUNCS forms the base; Phase 0 types win.
    _phase0_func_types = dict(self.func_return_types)   # save Phase 0 registrations
    _phase0_imported   = dict(getattr(self, 'imported_symbols', {}))  # save Phase 0 imported_symbols
    self.func_return_types = dict(_RUNTIME_FUNCS)
    self.func_return_types.update(_phase0_func_types)   # Phase 0 types win over defaults
    all_struct_defs_for_types = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    for s in all_struct_defs_for_types:
        if isinstance(s, StructDef):
            self.func_return_types[s.name] = f"{s.name} *"

    # Process imports: load modules and register imported symbols
    self.imported_symbols = dict(_phase0_imported)   # restore Phase 0 imported_symbols
    for s in stmts:
        if isinstance(s, FromImportStmt):
            # A local project sibling module (e.g. `mojo dylib`'s
            # per-module standalone compile importing a neighboring
            # .mojo file — see bugs/DYLIB_sibling_import_calls_bind_
            # to_weak_stubs.md) isn't in module_loader's stdlib/test
            # tracked set, so load_module() raises. Before falling back
            # to the "genuinely external/unresolved" path below (weak
            # stub, no module qualifier), try resolving it the same way
            # _find_imported_struct/_find_generic_source already do for
            # cross-module struct/generic lookups: if it resolves, this
            # sibling's real definition is compiled into the very same
            # output (driver._expand_dylib_modules walks this same
            # import closure into the dylib's build list) — so its call
            # sites must learn the sibling's module qualifier via
            # _note_own_func_home, not bind to an unqualified weak stub.
            _sib_qualifier = None
            try:
                exports = load_module(s.module)
            except Exception:
                exports, _sib_qualifier = self._local_sibling_module_exports(s.module)
            # Whether `s.module` resolved to a file genuinely OUTSIDE the
            # tracked stdlib/test trees — i.e. a real local PROJECT
            # sibling (base/chest.mojo, this whole mechanism's actual
            # target — see bugs/DYLIB_sibling_import_calls_bind_to_weak_
            # stubs.md), not a stdlib-internal relative import that
            # merely failed the bare `load_module(s.module)` call above
            # because that call doesn't resolve leading-dot relative
            # module strings itself (unlike `_emit_stdlib_import_
            # externs`'s own explicit dot-resolution) even though the
            # module IS a real, already-tracked stdlib file. Confirmed
            # via std/pwd/__init__.mojo's `from .pwd import getpwnam,
            # getpwuid`: `.pwd` hits this same `_local_sibling_module_
            # exports` fallback (`_sib_qualifier` gets set) purely
            # because of that dot-resolution gap, and `_emit_stdlib_
            # import_externs` (Phase 0, run earlier) ALSO independently
            # registers an extern for the SAME qualified symbol —
            # harmless while both computed the same generic `int64_t`
            # default, but a hard "conflicting types" compile error once
            # the struct/return-type corrections below started
            # resolving ONE of the two declarations to the real
            # `Passwd *` while the other stayed stale. Scoping these
            # corrections to genuine non-stdlib project files avoids
            # this pre-existing dual-registration hazard entirely rather
            # than trying to reconcile two independently-maintained
            # extern-emission passes.
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
                    # `from PKG import NAME` where NAME is a real
                    # SUBMODULE FILE (`PKG/NAME.py`/`PKG/NAME/
                    # __init__.py`), not a symbol defined inside PKG's
                    # own source — this is the TOP-LEVEL (module-scope)
                    # twin of `_gen_stmt_FromImportStmt`'s identical
                    # submodule check (see `_from_import_name_is_
                    # submodule`'s docstring and bugs/CODEGEN_
                    # generator_function_Lib_test_test_support.md's
                    # 2026-08-09 root-cause: `TESTFN = os_helper.
                    # TESTFN` via a MODULE-LEVEL `from test.support
                    # import os_helper` never reaches the function-
                    # body statement-lowering path at all — gen_module
                    # skips top-level FromImportStmts there entirely
                    # and processes them here instead). Register a
                    # genuine module marker (mirrors `_gen_stmt_
                    # ImportStmt`'s function-body registration shape)
                    # BEFORE the `sym_info`-empty fallback below, which
                    # would otherwise mark it `_unresolved_import_
                    # aliases` — losing the submodule's real dotted
                    # identity, and with it any chance of
                    # `_lower_MemberExpr`'s cross-module-global-read
                    # branch resolving `os_helper.TESTFN` to the real
                    # value instead of a NULL-pointer runtime dispatch.
                    if not s.wildcard and self._from_import_name_is_submodule(s.module, orig_name):
                        self.imported_symbols[sym_name] = {
                            'module': f"{s.module}.{orig_name}",
                            'return_type': 'unknown',
                        }
                        return
                    if _sib_qualifier and not sym_info:
                        # The sibling FILE resolved, but this particular
                        # imported name wasn't found among its fn/def
                        # signatures (module_loader's scanner — same one
                        # load_module() itself uses for stdlib — only
                        # extracts FUNCTIONS; a struct, comptime alias,
                        # or re-exported-from-a-further-sibling name
                        # comes back with no info). Unlike the stdlib
                        # case just below (where this has always been a
                        # silent no-op — untouched, pre-existing
                        # behavior), a local sibling name reaching here
                        # was, before this whole sibling-import fix
                        # existed, marked `_unresolved_import_aliases`
                        # (the module-load exception below used to fire
                        # for EVERY name in a local-sibling import,
                        # struct or not) — and callers like
                        # `_lower_opaque_ctor`'s uppercase-constructor
                        # guard rely on that marking to fall back to a
                        # self-contained weak stub instead of emitting a
                        # bare `extern` with no definition anywhere
                        # (confirmed via box.3d/game's real `ItemSlot`
                        # struct, imported cross-module exactly this
                        # way: silently link-broken — "symbol not found"
                        # at dlopen — without this fallback, since this
                        # fix's own function scan never taught struct
                        # constructors a home module). Restore that
                        # fallback for exactly this "resolved file, but
                        # this specific name isn't a function" case, so
                        # non-function local-sibling imports keep
                        # working exactly as before this fix.
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
                        # Defensive shallow copy BEFORE any mutation: this
                        # dict is NOT private to this call — it's the
                        # actual object cached inside module_loader's
                        # process-WIDE singleton (`_module_loader.
                        # _path_cache[path][sym_name]`, returned by
                        # `_local_sibling_module_exports` ->
                        # `load_module_from_path`, keyed purely by file
                        # path — the SAME dict object is handed back,
                        # unconditionally, to every GimpleGen instance in
                        # this process that ever imports this symbol from
                        # this path, for the lifetime of the process, not
                        # just this one compile). Mutating it in place
                        # (as every line below this comment, and the
                        # return-type/parameter-type corrections further
                        # down, do) silently poisons that shared cache for
                        # every OTHER, unrelated module's compile that
                        # happens to import the same symbol later in the
                        # same process — e.g. `mojo dylib`'s multi-module
                        # build compiles dozens of files sequentially in
                        # one process. Confirmed real: compiling game_
                        # engine.mojo (which resolves `engine_world`'s
                        # `engine_view_hopper_input` return type to a
                        # real `ItemSlot *` ONLY because game_engine.mojo
                        # ALSO separately imports `ItemSlot` directly from
                        # base.items, pre-registering it in THAT
                        # instance's own struct_field_types) mutated the
                        # shared cache entry for `engine_view_hopper_
                        # input` to `c_return_type='ItemSlot *'`; a LATER,
                        # completely independent compile of game_ffi.mojo
                        # then inherited that leaked `'ItemSlot *'` return
                        # type from the poisoned cache (its OWN, correct,
                        # from-scratch resolution attempt returns None —
                        # traced and confirmed) WITHOUT also getting a
                        # real local typedef for ItemSlot (materialization
                        # is genuinely per-instance, so it did NOT leak) —
                        # "unknown type name 'ItemSlot'". Copying here
                        # makes every mutation below strictly local to
                        # THIS sym_name/THIS import statement/THIS
                        # GimpleGen instance, closing the leak at its
                        # single point of entry rather than auditing every
                        # mutation site individually.
                        sym_info = dict(sym_info)
                        sym_info['module'] = s.module
                        sym_info['original_name'] = orig_name
                        self.imported_symbols[sym_name] = sym_info
                        _ret_changed = False
                        # A leading-underscore ORIGINAL name (e.g.
                        # std/pwd/_macos.mojo's `_getpw_macos`) is NOT
                        # exported by reflect.py's dylib-reflection table
                        # (module_loader.py's own `_mojo_type_to_c`
                        # docstring documents this — BUG-2026-036), so a
                        # call site importing one is resolved through a
                        # SEPARATE mechanism that computes its own extern
                        # declaration independently of `sym_info`/
                        # `imported_symbols` (confirmed: std/pwd/pwd.mojo
                        # emits TWO differently-guarded externs for
                        # `_getpw_macos` — one from this loop, one from
                        # that other path — that happened to coincide on
                        # the generic `int64_t`/`(...)` default before
                        # this fix and diverge, a hard "conflicting
                        # types" compile error, once this loop alone
                        # started resolving its real `Passwd *` return
                        # type). Correcting the type on only ONE of two
                        # independently-emitted declarations for the same
                        # symbol is unsafe by construction (exactly the
                        # "two sides compute different signatures for one
                        # symbol" class of bug this whole fix exists to
                        # avoid) — leave leading-underscore names exactly
                        # as module_loader's scan computed them, matching
                        # `_register_imported_structs`'s own established
                        # `nm.startswith('_')` skip for the same class of
                        # name.
                        if orig_name.startswith('_'):
                            pass
                        elif _sib_is_local_project and sym_info.get('return_type'):
                            # Mirror the parameter-type correction below,
                            # but for the sibling function's own RETURN
                            # type — e.g. base/chest.mojo's `Chest_new()
                            # -> Chest`. Left uncorrected, module_loader's
                            # text-only scan defaults an unrecognized
                            # `Chest` return type to plain int64_t, so a
                            # caller's `c := Chest_new()` types `c` as a
                            # bare scalar — NOT a `Chest *` — and a
                            # subsequent local `c.s0_id = 5` then lowers
                            # to a DYNAMIC `_mojo_dispatch_setattr` call
                            # (the generic "unknown struct type" fallback)
                            # instead of a real struct field write.
                            # Meanwhile a later call whose PARAMETER type
                            # WAS corrected (chest_total_count(c, ...))
                            # casts that same `c` to a real `Chest *` and
                            # reads its fields directly — a different
                            # storage path than the dynamic setattr wrote
                            # to, so the read silently comes back as the
                            # zero-initialized default instead of the
                            # value just assigned. No crash, no link
                            # error — just a silently wrong value
                            # (confirmed via `Chest_new()` + direct
                            # `c.s0_id = 5`/`c.s0_count = 10` field writes
                            # + `chest_total_count(c, 5)`: real Mojo/the
                            # interpreter both return the correct `10`;
                            # this gap alone made the compiled dylib path
                            # return `0`). Correcting `c_return_type` here
                            # (before it's read into func_return_types
                            # just below, and before this loop's own
                            # parameter/signature correction further down
                            # rebuilds `signature` from it) makes both the
                            # WRITE side (real struct field assignment,
                            # once `c`'s real type is known) and the READ
                            # side (already correct) agree on the same
                            # real struct memory.
                            _resolved_ret = self._resolve_sibling_param_ctype(
                                s.module, sym_info['return_type'])
                            if _resolved_ret:
                                sym_info['c_return_type'] = _resolved_ret
                                _ret_changed = True
                        if 'c_return_type' in sym_info:
                            self.func_return_types[sym_name] = sym_info['c_return_type']
                        if sym_info.get('variadic'):
                            # An OVERLOADED sibling name (module_loader's
                            # scan can't represent multiple real
                            # signatures under one name, so it collapses
                            # them to a variadic `name(...)` accepting
                            # any arity — e.g. std/pwd/_macos.mojo's
                            # `_getpw_macos` is defined twice, once per
                            # parameter type) has an intentionally EMPTY
                            # `parameters`/`c_parameters` and a `(...)`
                            # signature — that emptiness is not "zero
                            # arguments", so the parameter-correction
                            # block below (keyed on `parameters`/
                            # `c_parameters` having equal, iterable
                            # length) must never treat it as a genuine
                            # zero-arg function and rebuild `signature`
                            # as `Name ()` (found via std/pwd/pwd.mojo
                            # regressing to "too many arguments to
                            # function ... expected 0, have 1" once the
                            # RETURN type correction below started firing
                            # for these two purely by virtue of returning
                            # a struct, `Passwd`, independent of the
                            # variadic-arity gap). Only rebuild the
                            # signature's RETURN type here, preserving
                            # the `(...)` marker verbatim.
                            if _ret_changed:
                                sym_info['signature'] = (
                                    f"{sym_info.get('c_return_type', 'int64_t')} "
                                    f"{orig_name} (...)")
                        elif (_sib_is_local_project and not orig_name.startswith('_')
                                and sym_info.get('c_parameters') is not None
                                and len(sym_info.get('parameters') or []) == len(sym_info['c_parameters'])
                                and (sym_info.get('parameters') or _ret_changed)):
                            # (leading-underscore names excluded — see the
                            # matching skip on the return-type correction
                            # above, same dual-extern-declaration reason.)
                            # A sibling function's OWN parameter may be
                            # typed with a struct defined in ITS module
                            # (e.g. base/chest.mojo's `chest_total_count(c:
                            # Chest, item_id: UInt64)`) that THIS file
                            # never itself imports. module_loader's
                            # text-only scan (which computed
                            # sym_info['c_parameters']/['signature']
                            # above, via load_module_from_path) has no
                            # struct-layout knowledge at all and defaults
                            # such a parameter to plain int64_t — while
                            # `Chest`'s own home module (compiled
                            # standalone) resolves it to `Chest *` via its
                            # real struct_field_types. Left uncorrected,
                            # that mismatch propagates into
                            # func_param_types below (this call site's
                            # emitted qualified symbol hashes int64_t,
                            # the real definition hashes `Chest *` — an
                            # undefined-symbol link/dlopen failure), and
                            # even if only the HASH were patched (a prior,
                            # reverted attempt: see bugs/DYLIB_sibling_
                            # import_calls_bind_to_weak_stubs.md's
                            # "follow-on attempt #2"), this file would
                            # still pass a bare int64_t on the call —
                            # `Chest`'s real caller-side construction
                            # would be a null placeholder, corrupting
                            # memory on first field write.
                            #
                            # Fix in place, at the source: resolve each
                            # parameter's REAL Mojo type name (still
                            # available in sym_info['parameters'], unlike
                            # the already-C-typed 'c_parameters') against
                            # the callee's OWN module via
                            # _resolve_sibling_param_ctype below. When it
                            # names a genuine struct there,
                            # _materialize_imported_struct gives THIS
                            # file a real local typedef (fields resolved
                            # the same way _register_imported_structs
                            # resolves any other imported struct's
                            # fields) and this loop corrects
                            # sym_info['c_parameters']/['signature'] to
                            # match — the SAME dict object the extern-
                            # declaration emission (gen_module's
                            # "_emit_stdlib_import_externs"-adjacent pass,
                            # which reads sym_info['signature'] verbatim)
                            # and the func_param_types hash computation
                            # just below both read, so both sides of the
                            # symbol-name agreement AND the actual
                            # calling convention are fixed together, by
                            # construction, not independently patched
                            # (the mistake the reverted attempt made).
                            # Only genuine structs get corrected — a
                            # param that's really a scalar/collection
                            # type, or a struct this compile genuinely
                            # can't find anywhere, is left exactly as
                            # module_loader's scan computed it (an
                            # honest, unresolvable case keeps today's
                            # honest link-failure behavior, never a
                            # guess).
                            # (Also reached, with an empty `parameters`
                            # list, when only the RETURN type changed —
                            # see `_ret_changed` above and its own
                            # docstring-length comment just above this
                            # block for why a zero-argument function like
                            # `Chest_new() -> Chest` still needs its
                            # `signature` text rebuilt here, not only
                            # `c_return_type`.)
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
                            # A local-sibling import bypasses
                            # _emit_stdlib_import_externs (which raised
                            # on this same non-stdlib module name and
                            # gave up before reaching its own
                            # func_param_types population) — the ONLY
                            # other place that sets it. Without this,
                            # _overload_suffix(sym_name) sees no param
                            # types here and hashes '' while the
                            # sibling's OWN standalone compile hashes
                            # its real params, so this call site's
                            # qualified symbol (module_suffix1) and the
                            # sibling's actual definition (module_
                            # suffix2) disagree — an undefined symbol at
                            # link/dlopen time, not just a wrong-value
                            # miscompile.
                            self.func_param_types[sym_name] = [
                                ' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                                for cp in (sym_info.get('c_parameters') or [])
                            ]
                    if _sib_qualifier and sym_info:
                        # Mode-dependent qualifier: must match how the
                        # DEFINING module's symbols are actually named in
                        # THIS pipeline. In do_imports=True (--jit/build)
                        # the sibling is inlined by
                        # _compile_imported_module with GimpleGen.
                        # module_name == the dotted import string
                        # verbatim, tier-1-sanitized ('pkg.util' ->
                        # 'pkg_util'); module_name_for_path's basename
                        # fallback ('util') only matches the per-file
                        # dylib pipeline (build_stdlib_dylib derives each
                        # module name from its file path), so keep it for
                        # do_imports=False. Registering the wrong one
                        # made every `from pkg.util import f` program
                        # fail to link under --jit/build with an
                        # implicit-declaration error (call sites emitted
                        # util_f_0c85c9 vs definition pkg_util_f_0c85c9).
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
                        # Wildcard import: register all exported symbols
                        for _wc_key, _wc_info in exports.items():
                            _register_sym(_wc_key, _wc_key, _wc_info)
                    else:
                        for name, alias in s.names:
                            sym_name = alias if alias else name
                            sym_info = exports.get(name, {})
                            _register_sym(sym_name, name, sym_info)
                except Exception:
                    _debug_note('error registering sibling module imports', s.module)
            else:
                # Gracefully ignore module load errors — but still
                # record each imported NAME (under its alias, if any)
                # as *having been imported at all*, even with no real
                # type info. Without this, `from os import getcwd as
                # main` (a real, common shape: importing a C-stdlib-
                # backed module this compiler's own load_module()
                # doesn't resolve at all — it's scoped to THIS
                # compiler's own tracked Mojo stdlib/test set, raising
                # "Only stdlib and test imports supported: os") left
                # no record whatsoever of 'main' having been imported,
                # so the "is this call site's `main()` really calling
                # an aliased IMPORT, or genuinely this module's own
                # entry point?" check elsewhere (`fname_raw not in
                # self.imported_symbols`) wrongly concluded "not an
                # import" and redirected the call to `_gimple_main` —
                # producing a bogus, wrongly-typed second definition of
                # the real entry point ("conflicting types for
                # '_gimple_main'"). Found via tkinter/__main__.py's own
                # `from . import _test as main; main()` (a relative
                # import hitting the identical module-load-failure
                # path here).
                #
                # Deliberately NOT added to `self.imported_symbols`
                # itself: half a dozen OTHER call-lowering checks
                # (`_lower_opaque_ctor`'s uppercase-constructor guard,
                # the scalar-ctor guard, both auto-stub-unknown-name
                # guards) treat "not in imported_symbols" as "safe to
                # treat this bare name as a locally-stubbable opaque
                # constructor / auto-stub extern". An entry here has no
                # real signature behind it, so it doesn't actually
                # satisfy any of those paths -- it only suppressed
                # them, leaving calls like `from concurrent.futures
                # import ProcessPoolExecutor` + `ProcessPoolExecutor(
                # max_workers=jobs)` (build_stdlib_dylib.py) with NO
                # declaration at all ("implicit declaration of function
                # 'ProcessPoolExecutor'" — a real check-selfhost
                # regression this exact fix introduced the first time
                # it used `self.imported_symbols` directly). A separate,
                # narrow set — consulted ONLY by the aliased-main
                # checks below — fixes the original bug without
                # touching any of those unrelated call-lowering paths.
                _debug_note('module load failed while registering imports')
                if not s.wildcard:
                    for _fb_name, _fb_alias in s.names:
                        _fb_sym = _fb_alias if _fb_alias else _fb_name
                        # `s.module` itself didn't resolve as a package
                        # this compiler tracks, but `_fb_name` may still
                        # independently resolve as a real submodule FILE
                        # on the search path (`_submodule_source_path`
                        # does its own probing, not dependent on `s.
                        # module` having parsed) — same submodule-marker
                        # registration as the `exports is not None`
                        # branch above, so a module-attribute read off
                        # it (`submod.GLOBAL`) still resolves instead of
                        # being marked permanently unresolved.
                        if self._from_import_name_is_submodule(s.module, _fb_name):
                            self.imported_symbols[_fb_sym] = {
                                'module': f"{s.module}.{_fb_name}",
                                'return_type': 'unknown',
                            }
                            continue
                        self._unresolved_import_aliases.add(_fb_sym)

    # Register user function return types (from current + imported modules)
    #   Pass 1: annotated return types (authoritative)
    all_functions = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    # 'main' is kept a fixed, unqualified name on purpose
    # (_NO_OVERLOAD_MANGLE) — it's THE program's entry point, renamed to
    # _gimple_main/_{module}_main at emission (see gen_func) and looked
    # up back under the bare key 'main' at every call site that
    # redirects to it (_lower_call, _gen_stmt_ExprStmt). Those bare
    # 'main' lookups into func_param_types/func_return_types (populated
    # by the several passes below that iterate `all_functions` keyed by
    # bare name — Pass 1, Pass 1.3c, the cross-call scalar-contract
    # rebuild, Pass 2, ...) are only ever meant to mean THIS module's own
    # main. But an inlined dependency (do_imports=True whole-program
    # compile) can ALSO define its own top-level `def main():` (e.g. a
    # self-test entry point) — its own FunctionDef node rides along in
    # imported_stmts, appended AFTER stmts, so it's visited LAST and
    # silently overwrites the importing module's own, correctly-
    # registered 'main' entry in these bare-keyed dicts — even though
    # the two modules' `main`s can have completely different
    # arity/return type. A later call site padding missing args from a
    # default (`def main(args=None): ...` called bare as `main()`) then
    # looked up the WRONG (inlined dependency's) arity, found nothing to
    # pad, and emitted a call with too few arguments against the real
    # (correctly-aritied) _gimple_main definition — a hard GCC compile
    # error (BUG-2026-051). An inlined dependency's own main is never
    # called by anyone under the bare name 'main' (the call-site
    # redirect logic is entirely module-local; that dependency's OWN
    # internal self-reference to its own main is compiled by its own
    # private, unshared temp_gen instance — see
    # _compile_imported_module — which has its own, unaffected
    # func_param_types/func_return_types dicts).
    #
    # `_is_foreign_main` guards ONLY the specific dict-population sites
    # below (Pass 1, Pass 1.3c, the scalar-contract rebuild) — it does
    # NOT filter `all_functions` itself. `all_functions` is also the
    # source list for the cross-call scalar-contract pass's call-site
    # scan (`_caller_bodies`, a few hundred lines down), which walks
    # every function body — including main's — looking for calls whose
    # argument types can pin down an unannotated callee parameter (e.g.
    # `jit_compile_and_execute`'s own `src` param). Self-hosting this
    # very file (do_imports=True compiling mojo.py, which imports
    # gimple_codegen.py, myinterpreter.py, driver.py, jit/arm64.py — a
    # genuinely circular dependency graph) means mojo.py's OWN real
    # `main` (the one whose body contains the ONE call site to
    # `jit_compile_and_execute`) legitimately rides along in more than
    # one of those modules' own `imported_stmts` too, structurally
    # unequal to whatever THIS particular temp_gen's own `stmts` holds
    # (each module's own compile parses/rewrites independently). Actually
    # dropping such an entry out of `all_functions` (an earlier version
    # of this fix did exactly that) starved the scalar-contract scan of
    # that one real call site in some module compiles, silently
    # regressing `jit_compile_and_execute`'s inferred `src` type back to
    # the naive `int64_t` default — caught by `make check-selfhost`
    # (`build/system.o`'s two conflicting `jit_compile_and_execute`
    # declarations). Guarding only the dict writes (which must stay
    # module-local to fix BUG-2026-051) leaves the call-site scan
    # untouched (harmless to see the same real call once per module that
    # happens to carry a copy of it — same evidence, same conclusion).
    def _is_foreign_main(s):
        return isinstance(s, FunctionDef) and s.name == 'main' and s not in stmts
    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef) and s.return_type is not None:
            self.func_return_types[s.name] = self._resolve_type(s.return_type)
        # Register parameter types (for call-site coercion via _emit_call)
        if isinstance(s, FunctionDef) and s.params:
            if any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params]
        # Record free-function param DEFAULTS keyed by the mangled name, so
        # a call site that omits an argument can pad with the real default
        # (`def greet(name: String = "world")` called as `greet()`) instead
        # of NULL/0. `param_defaults` maps param name -> default expr AST.
        if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
            _dflts = getattr(s, 'param_defaults', None) or {}
            if _dflts:
                # `s` ranges over ALL_FUNCTIONS (this module's own stmts
                # PLUS every transitively-inlined foreign FunctionDef —
                # see all_functions' own construction above), not just
                # bare-name-callable functions of THIS module. A foreign
                # function whose bare name is _AMBIGUOUS_FUNC_HOME (two
                # different sibling modules transitively inlined here
                # each define a same-named top-level function — e.g.
                # os.py inlining both posixpath.py's and ntpath.py's own
                # `relpath(path, start=None)` via its `if 'posix' in
                # _names: import posixpath as path / elif 'nt' in
                # _names: import ntpath as path` branch, neither of
                # which this prepass can statically pick between) would
                # make `_func_csym` raise here — even though this is
                # only building an auxiliary lookup TABLE keyed by the
                # mangled name, not a genuine bare-name call-site
                # reference. If `s`'s bare name is never actually called
                # unqualified anywhere in this compile unit, this table
                # entry is simply never looked up, so skipping it is
                # harmless; if it IS genuinely bare-called somewhere,
                # THAT call site's own `_func_csym`/`_func_qualifier`
                # resolution still raises the same honest refusal (this
                # guard does not touch that path, only this prepass's
                # own indexing). Mirrors the identical, already-
                # established guard on the sibling `_func_kwargs_slot`
                # registration a few lines below.
                try:
                    _mangled = self._func_csym(s.name)
                except Exception:
                    _mangled = None
                if _mangled:
                    self._func_param_defaults[_mangled] = [
                        (pn, _dv) for pn, _dv in _dflts.items()]
        # Record the `**kwargs` slot so a call site with literal keyword
        # arguments can pack them into a real dict — see _func_kwargs_slot.
        # The C-signature index is the DECLARATION index: `*args` collapses
        # to exactly one MojoList* slot when a `**kwargs` follows it (see
        # _param_ctypes_for's has_kw pass-through), so positions line up.
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
                try:
                    _mangled_kw_name = self._func_csym(s.name)
                    self._func_kwargs_slot[_mangled_kw_name] = _kw_i
                    self._func_kwargs_has_vararg[_mangled_kw_name] = _seen_star
                except Exception:
                    pass
        # A genuine user free function (FunctionDef node, not a libc extern):
        # eligible for overload-mangling its C symbol by parameter types.
        if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
            self._mangled_funcs.add(s.name)
        # @export: callable from C under its plain Mojo name — never
        # overload-mangled (mirrors the _static_methods decorator-read
        # pattern below, for the free-function case).
        if isinstance(s, FunctionDef) and 'export' in (getattr(s, 'decorators', None) or []):
            self._extra_no_mangle.add(s.name)

    # Collect "memoize on the function object" attribute assignments —
    # Python's `def f(): ...; cached = getattr(f, "_cached", None); ...;
    # f._cached = cached; return cached` idiom (jit/arm64.py's own
    # `_toolchain_id`/`_compiler_id`, first reached via BUG-2026-049's
    # fix: `import jit.arm64` is a dotted import, previously never
    # resolved/compiled at all — see that bug's fix notes). `f.attr = ..`
    # used to fall through to `_lower_MemberExpr`'s "C function name used
    # as a value" special case (a function name can't be a bare rvalue
    # under -fgimple, so it's boxed as a `void *` via a pre-declared
    # `_funcptr_...` static) — `f.attr = ..` then tried to treat that
    # `void *` as a STRUCT POINTER and write through a `.attr` member,
    # which GCC correctly rejects ("request for member in something not
    # a structure or union"): a function has no real fields to write.
    # Mirrors `_class_attrs` (StructDef class-body attributes, just
    # above) exactly, but for a FREE FUNCTION's own attribute instead of
    # a struct's: redirect to a synthesized global variable
    # (`_funcattr_{func}__{attr}`) rather than inventing a new storage
    # mechanism. Unlike `_class_attrs`, there's no class-body literal to
    # read an initial value/type from — the attribute doesn't exist
    # until the function's OWN body assigns it at runtime — so every
    # such global is simply declared `int64_t` (boxed, zero-initialized
    # by C's own static default), matching this file's existing
    # "unknown/dynamic global boxed as int64_t" convention used
    # pervasively elsewhere (see _lower_IdentExpr's global-read
    # docstring). Must recurse into EVERY body shape a function can
    # contain (If/Try/While/For), not just its top-level statements —
    # `_toolchain_id._cached = cached` sits at top level here, but the
    # general pattern (e.g. inside a `try:`) must still be found.
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

    #   Pass 1b: struct method annotated return types + param types (from current + imported modules)
    all_structs_for_methods = (stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
                                + self._imported_typedef_structs)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                mangled = f"{s.name}_{m.name}"
                if m.return_type is not None:
                    self.func_return_types[mangled] = self._resolve_type(m.return_type)
                # Track @staticmethod methods so call sites don't pass cls arg
                if hasattr(m, 'decorators') and 'staticmethod' in (m.decorators or []):
                    self._static_methods.add(mangled)
                # Track REAL classmethods (explicit @classmethod, or the
                # two dunders Python makes implicit classmethods without
                # the decorator) — see _classmethod_names' own docstring
                # at its declaration for why _lower_method_call needs
                # this instead of trusting any parameter literally named
                # `cls`.
                if ((hasattr(m, 'decorators') and 'classmethod' in (m.decorators or []))
                        or m.name in ('__init_subclass__', '__class_getitem__')):
                    self._classmethod_names.add(mangled)
                # Also store method param types using the mangled name (for call-site arg padding)
                if m.params:
                    ctypes = []
                    for i, (pn, pt) in enumerate(m.params):
                        if i == 0 and pn == 'self':
                            ctypes.append(f"{s.name} *")
                        else:
                            ctypes.append(self._param_ctype(pn, pt, m))
                    # Don't overwrite hardcoded entries (e.g. Scope_define uses char* for name)
                    if mangled not in self.func_param_types:
                        self.func_param_types[mangled] = ctypes

    #   Pass 2: infer return types for unannotated functions using
    #           already-seeded func_return_types for callee types
    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef) and s.return_type is None:
            # Seed param types so _quick_type works for param names.
            # `*args`/`**kwargs` are seeded under their BARE name (the
            # body refers to `kw`, never `**kw`) and with the concrete
            # container type gen_func gives them — otherwise `return kw`
            # inferred the int64_t default and the caller read a
            # MojoDict * back as a MojoList *.
            for pname, ptype in s.params:
                if pname.startswith('**'):
                    self.var_types[pname[2:]] = 'MojoDict *'
                elif pname.startswith('*'):
                    self.var_types[pname[1:]] = 'MojoList *'
                else:
                    self.var_types[pname] = self._resolve_type(ptype)
            inferred = self._infer_return_type(s.body)
            # Special case: main() should return int, not void
            if s.name == 'main' and inferred == 'void':
                inferred = 'int64_t'
            self.func_return_types[s.name] = inferred
            self.var_types.clear()

    #   Pass 2b: infer return types for unannotated struct methods
    # Run to fixpoint: callee return types discovered in one round improve
    # inference for callers in the next round (handles forward calls like
    # Parser._parse_stmt calling Parser._parse_comptime).
    for _pass2b_iter in range(4):
        _changed = False
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    # Real method names, straight from the struct's own
                    # AST -- the ONE authoritative "is `x` a method (not
                    # a field)" signal for this struct. Needed because
                    # `struct_field_types[name]` alone can't be trusted
                    # for that question: `_scan_body_for_local_field_
                    # access` (this same pre-pass, below) synthesizes a
                    # phantom `'int'`-typed FIELD entry for ANY
                    # `<known-struct local>.<unrecognized member>` read
                    # found anywhere in the module (dynamic-attribute
                    # support) -- including a bound-method-as-VALUE read
                    # like `getpos = self.tell`/`data.tell` (see
                    # bugs/hard/CODEGEN_generator_lambda_expr_
                    # unsupported.md), which would otherwise get
                    # mistaken for a genuine field the moment that scan
                    # runs (it always does, unconditionally, for every
                    # module). Consulted by `_cpp_expr`'s/`_cpp_stmt`'s
                    # coroutine-body bound-method-as-value handling.
                    self._struct_method_names.setdefault(s.name, set()).add(m.name)
                    if m.name == '__init__':
                        self._struct_has_init.add(s.name)
                        # Record __init__ param names (excl self) so a
                        # keyword-arg constructor call (Counter(start=...))
                        # binds kwargs to the right __init__ parameters.
                        self._struct_init_params[s.name] = [
                            pn for pn, _pt in m.params if pn != 'self']
                        _init_defaults = getattr(m, 'param_defaults', {}) or {}
                        self._struct_init_defaults[s.name] = {
                            pn: dv for pn, dv in _init_defaults.items() if pn != 'self'}
                    if m.return_type is None:
                        for i, (pname, ptype) in enumerate(m.params):
                            if pname == 'self':
                                self.var_types[pname] = f"{s.name} *"
                            else:
                                self.var_types[pname] = self._resolve_type(ptype)
                        inferred = self._infer_return_type(m.body)
                        key = f"{s.name}_{m.name}"
                        if self.func_return_types.get(key) != inferred:
                            self.func_return_types[key] = inferred
                            _changed = True
                        self.var_types.clear()
        if not _changed:
            break


    #   Pass 2c: infer container RETURN ELEMENT types to a fixpoint, so a
    #   call site emitted before the callee's own body (the common
    #   self-host order — lower_expr dispatches to the _lower_* helpers
    #   defined after it) still sees the callee's tuple/list return
    #   element type. Populated statically here before any body is
    #   emitted; _gen_stmt_ReturnStmt's dynamic recording stays as a
    #   fallback for shapes this syntactic scan can't resolve.
    for _pass2c_iter in range(8):
        _c_changed = False
        for s in all_functions:
            if _is_foreign_main(s) or not isinstance(s, FunctionDef):
                continue
            _ret_elem = self._infer_return_elem_type(s.body, func_def=s)
            if _ret_elem is not None and self._return_elem_types.get(s.name) != _ret_elem:
                self._return_elem_types[s.name] = _ret_elem
                _c_changed = True
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                self._prepass_struct = s.name
                for m in s.methods:
                    if m.name == '__init__':
                        continue
                    _ret_elem = self._infer_return_elem_type(m.body)
                    _key = f"{s.name}_{m.name}"
                    if _ret_elem is not None and self._return_elem_types.get(_key) != _ret_elem:
                        self._return_elem_types[_key] = _ret_elem
                        _c_changed = True
        self._prepass_struct = None
        if not _c_changed:
            break

    # ── Pass 2b-bis: register per-struct-method overload candidates ────
    # Static/syntactic (arity range + C param types), so no fixpoint needed —
    # a single pass over every struct's own methods (including any
    # @fieldwise_init-synthesized __init__, since that's already a real
    # FunctionDef in s.methods by the time the parser hands stmts to us).
    # Used by _lower_struct_constructor/_lower_struct_method_call to pick
    # the right overload instead of guessing an unsuffixed symbol name.
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            _moids = self._struct_method_overload_ids(s)
            for m, _oid in zip(s.methods, _moids):
                _has_self_first = bool(m.params) and m.params[0][0] == 'self'
                _params_no_self = m.params[1:] if _has_self_first else m.params
                # A `*args: *Ts` pack param (single '*', not '**') consumes
                # every call-site positional arg from its position onward —
                # everything named after it in Mojo syntax is necessarily
                # keyword-only. Treating it (as the old real_params filter
                # below did) as contributing NOTHING to arity meant a call
                # with more positional args than the struct's OTHER,
                # non-variadic overloads could ever match would find no
                # survivor in _resolve_overload and fall through to a bare,
                # never-defined symbol (confirmed via String's *args:
                # *Ts-typed Writable constructor and DeviceGraphBuilder.
                # add_function's *Ts-typed overloads in the real stdlib).
                _star_idx = next((i for i, (pn, _pt) in enumerate(_params_no_self)
                                   if pn.startswith('*') and not pn.startswith('**')), None)
                # A `**kwargs`-style param (double star) MUST stay in
                # real_params/param_names: _build_call_args_for_candidate
                # locates its slot by scanning param_names for a '**'-
                # prefixed entry (to pack literal keyword args into a
                # real MojoDict there) and param_ctypes already carries
                # a real 'MojoDict *' slot for it (_signature_ctypes
                # only strips the *args pack's OWN sentinel, never a
                # **kwargs one). Dropping it here (the old filter
                # stripped ANY '*'-prefixed name, single or double star)
                # desynced param_names/max_arity from param_ctypes by
                # exactly one slot — the resolved overload's call sites
                # then never emitted an argument for that trailing
                # MojoDict* param at all, a hard "too few arguments"
                # compile error (e.g. tkinter/font.py's `Font.__init__
                # (self, root=None, font=None, name=None, exists=False,
                # **options)` called as `Font(name=.., exists=True,
                # root=..)`).
                real_params = [(pn, pt) for pn, pt in _params_no_self
                               if not (pn.startswith('*') and not pn.startswith('**'))]
                _defaults = m.param_has_default or {}
                if _star_idx is not None:
                    _pre_star = _params_no_self[:_star_idx]
                    min_arity = sum(1 for pn, _pt in _pre_star if pn not in _defaults)
                    max_arity = float('inf')
                else:
                    # A `**kwargs` slot is never itself required (real
                    # Python: `f()` is always valid even when `f` takes
                    # `**kwargs`) — exclude it from min_arity, but it
                    # still occupies one real slot in max_arity (a
                    # concrete MojoDict* parameter in the C signature).
                    min_arity = sum(1 for pn, _pt in real_params
                                     if pn not in _defaults and not pn.startswith('**'))
                    max_arity = len(real_params)
                _all_ctypes = self._signature_ctypes(m.params, m, s.name)
                param_ctypes = _all_ctypes[1:] if _has_self_first else _all_ctypes
                if _star_idx is not None:
                    # Drop the pack's own sentinel entry ('...', from the
                    # default _signature_ctypes sentinel) so param_ctypes
                    # stays aligned with param_names/real_params, which
                    # already exclude the pack's own name.
                    param_ctypes = [c for c in param_ctypes if c != '...']
                # Compute this overload's own return type here, rather than
                # reading func_return_types[f"{struct}_{method}{overload_id}"]
                # at the call site later: that key is only populated when
                # THIS overload's own body gets emitted (Phase 2a, in
                # declaration order), so a call from an earlier-processed
                # sibling overload's body into this one would see nothing
                # yet and silently default to int64_t. Mirrors the logic
                # in _gen_struct_method (return-type resolution + the
                # pointer-family self-referencing-generic special case).
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
                key = (s.name, m.name)
                self._struct_method_signatures.setdefault(key, []).append({
                    'overload_id': _oid,
                    'param_names': [pn for pn, _pt in real_params],
                    'param_ctypes': param_ctypes,
                    'min_arity': min_arity,
                    'max_arity': max_arity,
                    'ret_type': _ret_type,
                    'has_varargs': _star_idx is not None,
                    'pre_star_count': _star_idx if _star_idx is not None else None,
                })
                # Also register this overload's full param signature (incl.
                # self) in _mangled_signature_ctypes — NOT func_param_types
                # (see that dict's own comment for why: writing this same
                # info into func_param_types early was tried and reverted,
                # confirmed to change codegen elsewhere in ways not limited
                # to argument coercion). _emit_call reads this dict as a
                # fallback so a call to a not-yet-emitted sibling overload
                # (Phase 2a processes s.methods in declaration order) still
                # gets its arguments coerced correctly — confirmed fixing
                # std/ffi/__init__.mojo's DLHandle.get_symbol
                # kwarg-forwarding call, which regressed without this.
                self._mangled_signature_ctypes[f"{s.name}_{m.name}{_oid}"] = _all_ctypes

    # Imported structs (_register_imported_structs): no body is emitted for
    # these here — the real definition lives in the struct's home module,
    # compiled separately (e.g. into build/libmojostdlib.dylib). Emit an
    # `extern` for each of their methods now that the loop above has
    # resolved its real mangled name/return type/param types, so calls
    # route to the actual linked symbol instead of the generic scalar-
    # method stub in _lower_struct_method_call.
    for s in self._imported_typedef_structs:
        if not s.methods:
            continue
        for _oid, m in zip(self._struct_method_overload_ids(s), s.methods):
            bare_mangled = f"{s.name}_{m.name}{_oid}"
            mangled = self._struct_method_csym(s.name, m.name, _oid)
            # _mangled_signature_ctypes is keyed by the BARE form (Pass
            # 2b-bis populates it before any qualifier is known) — look
            # up under that key regardless of what mangled resolved to.
            param_ctypes = self._mangled_signature_ctypes.get(bare_mangled)
            if param_ctypes is None:
                continue
            # The suffixed func_return_types[mangled] key is only ever
            # populated when a struct's OWN method body is emitted
            # (Phase 2a) — which never happens here, since no body is
            # available for an imported struct. Pull the return type from
            # _struct_method_signatures instead (populated for every
            # struct in all_structs_for_methods regardless of emission).
            ret_type = None
            for _cand in self._struct_method_signatures.get((s.name, m.name), []):
                if _cand.get('overload_id') == _oid:
                    ret_type = _cand.get('ret_type')
                    break
            if ret_type is None:
                ret_type = self.func_return_types.get(f"{s.name}_{m.name}", 'void' if m.name == '__init__' else 'int64_t')
            # A "..." entry mid-list (e.g. a *args/**kwargs-style param)
            # is a bookkeeping placeholder in _mangled_signature_ctypes,
            # not literal C — splicing it in as-is produces invalid syntax
            # like `(T *, ..., int64_t)`. Fall back to a fully variadic
            # signature whenever that marker appears anywhere.
            if any('...' in p for p in param_ctypes):
                params_str = '...'
            else:
                params_str = ', '.join(param_ctypes) or 'void'
            sig = f"{ret_type} {mangled} ({params_str})"
            guard = _stub_guard_name(mangled)
            decl = f"#ifndef {guard}\n#define {guard}\nextern {sig};\n#endif"
            if decl not in self._elaborated_externs:
                self._elaborated_externs.append(decl)
            # Call-site overload resolution (_resolve_overload) can fail
            # to confidently pick a candidate (e.g. a bracketed type
            # argument like get_symbol[NoneType] it can't match) and
            # falls back to the bare, unsuffixed mangled name even when
            # the method IS overloaded — declare that variadic fallback
            # too, mirroring the auto-stub pattern _lower_struct_method_call
            # already uses elsewhere for genuinely-unknown methods.
            if _oid:
                # "bare" here means no OVERLOAD-HASH suffix (the call
                # site's own unresolved-overload fallback, per
                # _lower_struct_method_call's `self._struct_method_csym(
                # struct_name, method, '')`) — still module-qualified,
                # for the same reason every other decl in this loop is.
                no_oid = self._struct_method_csym(s.name, m.name, '')
                bare_guard = _stub_guard_name(no_oid)
                bare_decl = f"#ifndef {bare_guard}\n#define {bare_guard}\nextern {ret_type} {no_oid} (...);\n#endif"
                if bare_decl not in self._elaborated_externs:
                    self._elaborated_externs.append(bare_decl)

    # ── Pass 1.3: Infer parameter types from usage ─────────────────────
    # For parameters without type annotations, infer from member accesses
    self._inferred_param_types: dict[str, dict[str, str]] = {}  # func_name -> {param_name -> type}
    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_param_types[s.name] = self._infer_param_types(s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{s.name}_{m.name}"
                self._inferred_param_types[key] = self._infer_param_types(m)

    # ── Pass 1.3b: Infer local variable types from assignments ──────────
    # Scan all assignments to determine variable types; use int64_t for
    # variables that receive 64-bit values (list elements, arithmetic results)
    self._inferred_var_types: dict[str, dict[str, str]] = {}  # func_name -> {var_name -> type}
    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_var_types[s.name] = self._infer_local_var_types(s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{s.name}_{m.name}"
                self._inferred_var_types[key] = self._infer_local_var_types(m)

    # ── Pass 1.3c: Populate func_param_types for all user functions ────────
    # CRITICAL: Must happen before Phase 2a (code generation) so that call-site
    # argument coercion has the correct expected parameter types. Otherwise,
    # _emit_call defaults to converting pointers to int64_t, losing type info.
    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef):
            if s.params and any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                method_full_name = f"{s.name}_{m.name}"
                # Don't clobber a deliberately-hardcoded entry (see
                # `_selfhost_locked_param_types`'s own comment) with
                # this pass's own weaker signature inference.
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
                            param_ctypes.append(self._param_ctype(pname, ptype, m))
                    self.func_param_types[method_full_name] = param_ctypes

    # ── Pass 1.3c2: Patch GimpleGen func_param_types from inference ─────
    # _param_ctype uses bare method name as key for _inferred_param_types,
    # but struct methods are keyed by "{struct}_{method}".  Fixup: scan
    # GimpleGen methods and upgrade stale int64_t entries where inference
    # knows a pointer type.  Scoped to GimpleGen only — other struct
    # inferences may be wrong.
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

    # ── Pass 1.3d: cross-call element-type contract ────────────────────
    # A container's element type lives in side-tables keyed by SSA name and
    # does not survive a call boundary, so a callee that indexes a passed-in
    # container falls back to int getters and silently corrupts non-int
    # payloads. Propagate it: where a caller passes a container whose element
    # types we can derive, record them onto the callee's parameter. Free
    # functions only for now (methods carry a `self` and are handled via
    # struct fields). Conflicting call sites collapse to unknown.
    self._param_elem_types: dict[str, dict[str, tuple]] = {}
    _free_params = {s.name: [pn for pn, _ in (s.params or []) if not pn.startswith('*')]
                    for s in all_functions if isinstance(s, FunctionDef)}

    def _record_param_elem(callee, pname, e, ne):
        d = self._param_elem_types.setdefault(callee, {})
        if pname in d and d[pname] != (e, ne):
            d[pname] = (None, None)   # conflicting call sites → unknown
        else:
            d[pname] = (e, ne)

    # Cross-call scalar contract: an unannotated scalar param defaults to the
    # int64_t machine word, so passing a double silently truncates (bnbody's
    # dt=0.01 -> 0 froze the sim). Observe each call argument's scalar type and
    # propagate a unanimous concrete one (double) onto the callee's param. A
    # function name -> def map lets us skip annotated params.
    #
    # Same mechanism also carries pointer-shaped evidence (char *) — an
    # unannotated param that is merely held/returned (no body-usage evidence
    # at all, e.g. `def g(a): return a`) got no entry from _infer_param_types
    # above and defaulted to int64_t, so calling it with a string argument
    # (`g("ab")`) compiled the identity function as returning int64_t: the
    # correct char* pointer value silently reinterpreted as an integer and
    # printed as garbage. See bugs/CODEGEN_untyped_param_string_passthrough_wrong.md.
    # Reuses this exact observe-per-call-site/apply-if-unanimous contract
    # (rather than adding a third narrow body-usage special case alongside
    # the map() one above) since the evidence here is inherently about the
    # CALL SITE, not the function body.
    _fn_by_name = {s.name: s for s in all_functions if isinstance(s, FunctionDef)}
    _scalar_obs: dict[str, dict[str, set]] = {}   # callee -> {pname -> {types}}

    def _arg_scalar_type(caller_name, a):
        if isinstance(a, FloatLiteral):
            return 'double'
        if isinstance(a, StringLiteral):
            return 'char *'
        if isinstance(a, IdentExpr):
            t = (self._inferred_var_types.get(caller_name, {}).get(a.name)
                 or self._inferred_param_types.get(caller_name, {}).get(a.name))
            return t
        return None

    # Observe call sites both inside every function body AND at module top
    # level (`_TOPLEVEL_CALLER`) — a call like `print(g("ab"))` sitting
    # directly in module-level code (not inside any `def`) is otherwise
    # invisible to this analysis entirely, since it only walked
    # `all_functions`' bodies. `_TOPLEVEL_CALLER` is a name no real Mojo
    # function can have (leading `<`), so _inferred_var_types/_inferred_
    # param_types lookups for it simply miss (harmless) rather than
    # colliding with a real function's per-name entries.
    _TOPLEVEL_CALLER = '<toplevel>'
    _caller_bodies = [(s.name, s.body) for s in all_functions if isinstance(s, FunctionDef)]
    _caller_bodies.append((_TOPLEVEL_CALLER, stmts))
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

    # Apply: a unanimous concrete double (or char *) observed across all call
    # sites of an unannotated, weakly-defaulted param becomes that param's type.
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
                # types is exactly {'double'} or {'char *'} here (checked
                # above) — pick without next(iter(...)): a self-hosted
                # build of this very file (`make check-selfhost`) failed to
                # link with an undefined `_next` symbol when this used
                # `next(iter(types))`, since gimple_codegen.py's own
                # compiled-path lowering of the `next()` builtin over a
                # freshly-constructed set iterator doesn't cover this
                # shape.
                resolved_type = 'double' if types == {'double'} else 'char *'
                self._inferred_param_types.setdefault(callee, {})[pname] = resolved_type

    # Rebuild free-function param-type signatures so call-site coercion sees
    # the propagated scalar types (this must follow the propagation above).
    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef):
            if s.params and any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []

    # ── Pass 1.3d-ctor: constructor call-site scalar contract, IdentExpr
    # args (bugs/hard/CODEGEN_unannotated_init_param_field_type_defaults_
    # int64.md). The EARLY pass above (self._ctor_lit_param_types, run
    # before the struct-field-collection loop that locks in every field's
    # C type) only sees DIRECT LITERAL constructor arguments
    # (`Widget("hello")`), because it necessarily runs before
    # self._inferred_var_types exists — a variable-argument call site
    # (`s = "hello"; w = Widget(s)`) was invisible to it, leaving the
    # field wrongly typed int64_t (a raw pointer printed as a decimal
    # integer). Now that Pass 1.3b (above) has populated
    # self._inferred_var_types, redo the same observe/apply contract,
    # reusing `_arg_scalar_type`/`_caller_bodies` (the exact helpers
    # Pass 1.3d's free-function version just above used) so IdentExpr
    # arguments contribute real evidence too. This is a RECONCILIATION,
    # not a reorder of the earlier, already-working pass: it runs before
    # any C struct typedef / code text has been emitted (typedef
    # emission is Phase 2, well below in this method), so patching
    # self.struct_field_types here still lands before that dict is ever
    # read for codegen — there is no already-emitted C text to fix up.
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
            # Patch the struct field(s) this param feeds via a direct
            # `self.field = param` assignment in __init__'s own body —
            # avoid `next(gen, default)` here for the exact same reason
            # the neighboring passes' comments already document (a
            # self-hosted build failed to link with an undefined `_next`
            # symbol the last time that pattern was used over a freshly-
            # built generator); use an explicit loop instead.
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

    # ── Pass 1.3d-gen: compiled-generator eligibility/compile attempt ──
    # Deliberately placed HERE — after the cross-call scalar contract
    # above has fully populated self._inferred_param_types — rather than
    # at the top of gen_module where an earlier revision of this pass
    # used to run. _gen_cpp_generator_unit's parameter-type refusal check
    # (`ctype not in ('int64_t', 'double', '_Bool')`) calls
    # self._param_ctype for each unannotated parameter, which itself
    # consults self._inferred_param_types when present (see
    # _param_ctype's "Check inferred parameter types first" branch) —
    # but running the generator compile attempt before that dict even
    # existed meant every unannotated generator parameter fell straight
    # through to _resolve_type(None)'s naive int64_t default with NO
    # cross-call-site evidence at all, unlike every ordinary (non-
    # generator) unannotated parameter, which already benefits from this
    # exact inference. A generator like `def g(s): yield s` called as
    # `g("hi")` was silently compiled with `s` (and the coroutine
    # promise's `current_value`) typed `int64_t` instead of being
    # honestly refused — a char*/MojoStr* pointer value stored into and
    # read back out of an int64_t slot, surviving only by platform-ABI
    # luck since it was never arithmetically touched. See
    # bugs/CODEGEN_compiled_generator_unannotated_string_param_mistyped.md.
    # Moving the compile attempt to after Pass 1.3d means an unanimous
    # non-scalar (`char *`) cross-call observation for an unannotated
    # generator parameter now lands in self._inferred_param_types before
    # _gen_cpp_generator_unit ever looks, so _param_ctype resolves it to
    # `char *`, which the existing refusal check already rejects —
    # reusing that check exactly as before, with no new logic. A
    # scalar-only (int64_t/double/_Bool) unannotated parameter, or one
    # with no call-site scalar evidence either way (still defaults to
    # int64_t, matching every other unannotated scalar parameter in this
    # codegen), continues to compile exactly as it did before this move.
    # Deferring this far also means _gen_cpp_generator_unit's body
    # emission (_cpp_stmt) now runs with func_param_types/func_return_
    # types/struct registries/imported-symbol tables/_inferred_var_types
    # etc. already fully populated by the passes above, instead of the
    # much sparser state that existed at the top of gen_module — a
    # strict improvement, not a new dependency risk, since ordinary
    # (non-generator) function bodies were always emitted this late
    # already (Phase 2a, further below).
    #
    # A generator BODY can reference module-level globals (`sys`, `os`,
    # `_flags`, ...) and module-level functions (`detect_encoding`,
    # ...). The full global pre-scan (Phase 1.7) runs later in gen_module,
    # AFTER this loop, so a lightweight name-only pre-scan of module-level
    # assignments and imports is run here first — enough for _cpp_expr to
    # resolve a bare name as a module global (vs. a genuinely-undeclared
    # local) and to register the symbol for the .cpp preamble's extern
    # declarations.
    for _gm_stmt in stmts:
        if isinstance(_gm_stmt, AssignStmt) and isinstance(_gm_stmt.target, IdentExpr):
            self._cpp_early_global_names.add(_gm_stmt.target.name)
        elif isinstance(_gm_stmt, ImportStmt):
            for _tm, _ta in _import_targets(_gm_stmt):
                # `import os.path` (no alias) binds the TOP-LEVEL
                # package name `os` in real Python, not the literal
                # dotted string "os.path" -- registering the latter
                # left bare `os` references in the generator body
                # unrecognized as a known global, falling through to
                # an undeclared C++ identifier ("'os' was not declared
                # in this scope") for any `os.replace(...)`-style call
                # not already special-cased as `os.path.*`. Found via
                # Tools/build/update_file.py's own `import os.path`.
                self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
        elif isinstance(_gm_stmt, FromImportStmt):
            for _nm in getattr(_gm_stmt, 'names', []) or []:
                self._cpp_early_global_names.add(_nm)
        elif isinstance(_gm_stmt, FunctionDef):
            self._cpp_early_global_names.add(_gm_stmt.name)
            self._cpp_module_fn_names.add(_gm_stmt.name)

    # Imports nested inside module-scope try/if bodies (`try: import
    # winreg as _winreg` — mimetypes.py's own shape; a `try:` around a
    # platform-specific import) are module globals too, but the flat scan
    # above misses them. Also collect module-level ASSIGNMENTS nested in
    # try/if bodies (locale.py's `except ImportError: CHAR_MAX = 127`
    # fallback constants). Walk one level of try/if bodies.
    def _scan_cpp_nested_imports(stmt_list):
        for _gi in stmt_list:
            if isinstance(_gi, (ImportStmt, FromImportStmt)):
                if isinstance(_gi, ImportStmt):
                    for _tm, _ta in _import_targets(_gi):
                        # Same `import a.b` (no alias) top-level-name
                        # fix as the flat scan above.
                        self._cpp_early_global_names.add(_ta if _ta else _tm.split('.', 1)[0])
                else:
                    for _nm in getattr(_gi, 'names', []) or []:
                        self._cpp_early_global_names.add(_nm)
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
    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) in _generator_fns
                and id(s) not in _async_fns):
            continue
        # Skip generator METHODS (they have 'self', or 'cls' for a
        # @classmethod generator, as first param) — the dedicated
        # method loop at Phase 2 handles those with the correct
        # struct_name. Widening this to also recognize 'cls' matters
        # even though this particular loop only ever sees TOP-LEVEL
        # `stmts` (a real struct method can't appear here) — kept in
        # sync with the identical check in the "second + third passes"
        # loop below purely so the two don't silently diverge; see that
        # loop's own comment for why the 'cls' case is load-bearing
        # THERE (that loop iterates ALL of `_generator_fns`, including
        # nested struct methods, by identity — see
        # CODEGEN_generator_classmethod_first_param_must_be_self.md).
        if s.params and s.params[0][0] in ('self', 'cls'):
            continue
        if not _generator_quick_eligible(s):
            continue
        try:
            cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_generator_unit(s)
        except _UnsupportedGeneratorShape as e:
            _debug_note(f'generator {s.name!r} not eligible for C++ '
                        'coroutine path, falling back to honest refusal', e)
            continue
        self._supported_generators[s.name] = s
        self._generator_api[s.name] = {
            'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
            # None for every generator except a tuple-valued one
            # (`yield a, b, ...`) — see _cpp_yield_tuple's producer-
            # side boxing and _gen_for_generator_iter's/next()'s
            # consumer-side unpacking, both keyed off this.
            'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
        }
        # <base>_start's real C parameter types, registered the exact
        # same way an ordinary function's signature is registered — this
        # is what lets _emit_call's existing argument-coercion machinery
        # (int-literal-to-int64_t, etc.) apply to a generator call's
        # arguments for free, with no separate coercion logic written
        # for this path.
        self.func_param_types[f"{base}_start"] = param_ctypes
        _gen_dflts = getattr(s, 'param_defaults', None) or {}
        if _gen_dflts:
            self._func_param_defaults[f"{base}_start"] = [
                (pn, dv) for pn, dv in _gen_dflts.items()]
        self._generator_cpp_units.append(cpp_text)
        _generator_fns.pop(id(s), None)

    # Second + third passes: try remaining generators (some may have had
    # yield-from dependencies that weren't compiled yet in the first pass).
    for _pass in range(3):
        if not _generator_fns:
            break
        for _gm_id, s in list(_generator_fns.items()):
            if _gm_id in _async_fns:
                continue
            # Skip generator METHODS (handled by the dedicated method
            # loop) — this loop iterates `_generator_fns` directly
            # (built from a DEEP `_walk_ast(stmts)` scan, keyed by
            # object identity), so unlike the first-pass loop above
            # (which only ever sees top-level `stmts`), this one DOES
            # see nested struct methods, including @classmethod
            # generators whose first param is conventionally `cls`, not
            # `self`. Before this widened to also recognize 'cls', a
            # @classmethod generator method slipped past this "skip"
            # check, got compiled HERE as if it were an ordinary
            # free function (struct_name=None, `cls` treated as a
            # plain scalar parameter, popped out of `_generator_fns`
            # before the dedicated per-struct method loop ever got a
            # turn) — silently wrong for two reasons: (1) it registers
            # under the bare function name in `_generator_api`, which
            # a `ClassName.method(...)` call site never looks up (call
            # sites for a generator METHOD only ever consult
            # `_generator_method_api`, keyed by (struct_name, method)),
            # so the compiled unit was simply dead code; worse, (2) if
            # the body ever read `cls.<attr>` (a real shape — see
            # Lib/test/test_finalization.py's `test`), `_cpp_expr`'s
            # MemberExpr case falls to its "non-self member access"
            # branch (obj_expr.member) since the receiver isn't
            # literally named `self`, emitting `cls.attr` on a plain
            # `int64_t cls` parameter — invalid C++, a hard g++
            # compile failure instead of a graceful source fallback.
            # See CODEGEN_generator_classmethod_first_param_must_be_
            # self.md for the full root-cause writeup.
            if s.params and s.params[0][0] in ('self', 'cls'):
                continue
            if not _generator_quick_eligible(s):
                continue
            try:
                cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_generator_unit(s)
            except _UnsupportedGeneratorShape as e:
                _debug_note(f'generator {s.name!r} not eligible for C++ '
                            f'coroutine path (pass {_pass+2}), falling back', e)
                continue
            self._supported_generators[s.name] = s
            self._generator_api[s.name] = {
                'base': base, 'value_ctype': value_ctype, 'params': param_ctypes,
                'tuple_slot_ctypes': self._cpp_last_tuple_slot_ctypes,
            }
            self.func_param_types[f"{base}_start"] = param_ctypes
            _gen_dflts = getattr(s, 'param_defaults', None) or {}
            if _gen_dflts:
                self._func_param_defaults[f"{base}_start"] = [
                    (pn, dv) for pn, dv in _gen_dflts.items()]
            self._generator_cpp_units.append(cpp_text)
            _generator_fns.pop(_gm_id, None)

    # ── Final step: combined async-generator eligibility/compile attempt ──
    # `async def f(): ... yield ... ...` (is_async AND is_generator both
    # true — the ONE category the plain-generator loop just above and
    # the plain-async loop just below deliberately exclude via their own
    # `id(s) not in _async_fns` / `id(s) not in _generator_fns` guards).
    # Runs BEFORE the plain-async loop below, not after — deliberately:
    # this step's target shape has a plain `async def` (e.g.
    # `main_driver`) consume an async GENERATOR (e.g. `f`) via `async
    # for`, which needs `f`'s own `_mojoasyncgen_f_handle`/`_impl`/
    # `_AnextAwaiter` C++ types already TEXTUALLY DEFINED, earlier in
    # the one concatenated .cpp translation unit (`_generator_cpp_units`
    # — see gen_module's docstring), before `main_driver`'s own cpp text
    # uses them (same-translation-unit composition, exactly like an
    # ordinary async-awaits-async call — see `_is_async_call_to_known_fn`
    # 's docstring for the identical "callee compiled first" source-
    # order constraint) — so `f` must be compiled (and registered in
    # `self._async_gen_api`) before `main_driver` is even attempted, not
    # after. Same late-running shape as the other two loops (after the
    # cross-call scalar-contract inference), keyed off membership in
    # BOTH `_generator_fns` and `_async_fns`, via
    # `_async_gen_quick_eligible`/`_gen_cpp_async_generator_unit`
    # instead of either single-purpose pair. On success, popped from
    # BOTH dicts so it's correctly excluded from every one of the three
    # mutually-exclusive category computations further below (this
    # function is no longer "still unsupported" in any of them).
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

    # Second pass for async generators not in top-level stmts (nested in
    # module-scope if/else/try bodies — types.py's `async def _ag():
    # yield` inside an `except ImportError:` handler).
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

    # ── Step B: compiled-async-function eligibility/compile attempt ────
    # Same shape as the generator loop just above (run this late, after
    # the cross-call scalar-contract inference, for the identical reason
    # — an unannotated local's/return's real type benefits from the same
    # inference an ordinary function already gets), but keyed off
    # `_async_fns` and _async_quick_eligible/_gen_cpp_async_unit instead.
    # `id(s) not in _generator_fns` excludes an `async def f(): yield x`
    # async generator — that's its own combined-refusal category,
    # reported by the honest-fallback raise further below, never
    # silently compiled via either single-purpose path.
    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) in _async_fns
                and id(s) not in _generator_fns):
            continue
        # See _inline_single_use_task_composition's/_normalize_await_
        # kwargs's own docstrings — must run BEFORE the eligibility
        # check below (mirrors the identical calls in
        # _compile_nested_async_functions).
        s.body = self._inline_single_use_task_composition(s.body)
        self._normalize_await_kwargs(s.body)
        if not _async_quick_eligible(s, frozenset(self._async_api.keys())):
            continue
        try:
            cpp_text, value_ctype, base, param_ctypes = self._gen_cpp_async_unit(s)
        except _UnsupportedGeneratorShape as e:
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
    # Second pass for async functions NOT in top-level stmts (nested in
    # if/else/try bodies at module scope — e.g. types.py's `async def
    # _c(): pass` inside an `except ImportError:` handler). Iterate
    # _async_fns directly, mirroring the generator multi-pass. MUST
    # exclude any async def nested INSIDE an ordinary top-level
    # function's own body — those belong exclusively to the dedicated
    # Step I (_compile_nested_async_functions) and async-closure
    # discovery passes further below, which thread the enclosing
    # function's scope, comptime bracket parameters, and captured free
    # variables into _gen_cpp_async_unit. Compiling one here as a bare
    # top-level-style unit silently drops all of that context (a real,
    # hand-verified regression: this pass claimed test_asyncrt.mojo's
    # comptime-parametrized `test_asyncrt_add[lhs: Int]` before the
    # closure pass could, registering a wrong, param-less unit under
    # the bare name and popping it out of `_async_fns`, so the closure
    # pass never populated `_async_closure_api` and `await
    # create_task(test_asyncrt_add[1](a))` fell through to the honest
    # whole-module refusal).
    #
    # MUST equally exclude any async def nested INSIDE A STRUCT
    # METHOD's own body — device_context.mojo's `async def wrapper(...)
    # capturing -> None:` shape, owned exclusively by the dedicated
    # "Async closures NESTED INSIDE A METHOD" pass further below (keyed
    # by (struct_name, method_name), threading `self`/method params/
    # threaded comptime function-typed params as captures). Originally
    # this set was only ever built by walking top-level FunctionDefs
    # (`_st in stmts`), never StructDefs — so a nested-in-a-METHOD async
    # def's id was never added here, and this pass (running BEFORE the
    # dedicated method-nested pass) claimed it first: compiled as a bare
    # top-level-style unit with `extra_captures=None`, silently dropping
    # every captured free variable (e.g. `func`), and popped it out of
    # `_async_fns` so the dedicated pass never got a turn. The generated
    # C++ body then referenced the captured name directly (`func()`)
    # with no parameter/local ever declaring it — a real, hand-verified
    # `'func' was not declared in this scope` g++ compile failure (see
    # test_async_void_return.py's test_device_context_shaped_repro_
    # end_to_end / test_enqueue_cpu_range_shaped_repro_multiple_
    # handles). Fixed by ALSO walking every struct method's body here,
    # exactly mirroring the top-level-FunctionDef loop just above.
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

    # Step I (create_task/Task/TaskGroup/RaisingTask project): async
    # functions NESTED inside an ordinary top-level function's own body
    # (real Mojo's own idiom: `@parameter async def wrapper(): ...`
    # scoped inside the test function that uses it, never a bare
    # top-level `async def`) — the loop just above only ever iterates
    # top-level `stmts`, so a nested one is otherwise always left
    # uncompiled in `_async_fns`, tripping the final "unhandled async
    # function(s)" whole-module refusal below. Must run BEFORE that
    # final check (not deferred to the later per-statement body-compile
    # loop, which runs much further down) — see
    # _compile_nested_async_functions's own docstring for the full
    # design (qualified-key registration into self._nested_async_api,
    # scoped push/pop into self._async_api done later, per enclosing
    # function, by the per-statement loop). Only ordinary (not
    # themselves async/generator) top-level FunctionDefs are scanned —
    # an async/generator top-level function's own body was already
    # fully handled by its own dedicated `_gen_cpp_*_unit` pass above,
    # which has no nested-def support of its own (out of scope: no
    # target file needs a doubly-nested async def).
    for s in stmts:
        if not (isinstance(s, FunctionDef) and id(s) not in _async_fns
                and id(s) not in _generator_fns):
            continue
        self._compile_nested_async_functions(s, _async_fns)

    # Milestone C step 3: generator METHODS on structs — same eligibility/
    # compile-attempt shape as the free-function loop just above, keyed
    # by (struct_name, method_name) rather than by bare name (see
    # _supported_generator_methods' docstring). Runs in the same
    # struct-declaration order as everything else in this file, after
    # the identical Pass-1.3d cross-call inference the free-function
    # loop above depends on, for the same reason (an unannotated scalar
    # parameter of a generator method benefits from the exact same
    # cross-call-site scalar inference an ordinary method's unannotated
    # parameter already gets).
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

    # Second pass for generator methods (yield-from dependencies)
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

    # Async closures/functions NESTED INSIDE A TOP-LEVEL FUNCTION (not a
    # method) — test_asyncrt.mojo's/test_tracing.mojo's own shape:
    # `@parameter async def test_asyncrt_add[lhs: Int](rhs: Int) -> Int:
    # ...` defined inside an ordinary `def test_runtime_task() raises:`.
    # Comptime bracket parameters on a NESTED async function are
    # threaded through as ordinary trailing parameters exactly like
    # _method_threaded_comptime_params does for a function-TYPED
    # comptime method parameter (see that mechanism's own docstring) —
    # but here unconditionally, for EVERY comptime param regardless of
    # its annotated type (Int, Bool, ...), because this reasoning
    # applies more broadly than just function-typed values: _gen_cpp_
    # async_unit never does any compile-time folding/specialization on
    # a comptime parameter's VALUE at all (it just compiles one
    # coroutine body per Mojo function definition and threads whatever
    # scalar arguments a call site supplies) — so `test_asyncrt_add[1]
    # (10)` and `test_asyncrt_add[2](20)` calling the SAME compiled
    # coroutine unit with `lhs` passed as an ordinary 1/2 argument is
    # exactly equivalent to real per-call-site monomorphization for
    # this codegen's own (non-branching-on-comptime-ness) purposes —
    # unlike the general (non-async) free-function/struct-method paths
    # elsewhere in this file, which DO need real per-call-site
    # elaboration (see bugs/CODEGEN_comptime_bracket_parametrized_
    # function_calls_silently_wrong.md) because those bodies CAN
    # observe comptime-ness (e.g. `@parameter if`, static array sizes)
    # — no compiled async function anywhere in this codebase does that.
    if _gsrc:
        for _od in stmts:
            if not isinstance(_od, FunctionDef):
                continue
            _outer_scope2 = {}
            for _pname, _ptype in (_od.params or []):
                _outer_scope2[_pname] = self._resolve_type(_ptype)
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

    # Async closures NESTED INSIDE A METHOD (not themselves a method,
    # and not a top-level function either) — device_context.mojo's
    # `async def wrapper(...) capturing -> None:` shape, defined inside
    # `enqueue_cpu_function`/`enqueue_cpu_range`. Neither the free-
    # function loop above (only scans top-level `stmts`) nor the
    # generator/async-METHOD loops (only scan `_sd.methods` themselves,
    # one level deep) ever attempt a doubly-nested async def like this
    # one — confirmed via a hand-written repro that reached this file's
    # final "still unsupported" refusal even after `_async_quick_
    # eligible` itself was widened to accept parameterized async defs
    # (Step H's merge) — `wrapper` is never even OFFERED to that
    # eligibility check by any existing pass. This is a NEW pass, not a
    # widening of an existing one, run in the same struct-declaration
    # order as everything else in this file, one level deeper (struct
    # -> method -> nested async def).
    for _sd in stmts:
        if not isinstance(_sd, StructDef):
            continue
        _moids_ac = self._struct_method_overload_ids(_sd)
        for _m, _oid in zip(_sd.methods, _moids_ac):
            # The same outer scope Pass 3 (_scan_for_closures, below)
            # would build for this method: self, its own params, and
            # any function-typed comptime bracket parameter threaded
            # through as an ordinary trailing parameter (see
            # _method_threaded_comptime_params) — the only kinds of
            # free variable a nested async closure could actually
            # capture here.
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

    # Plain for-loops (not comprehensions) building plain lists, then
    # sorted — deliberately avoiding a `for i, fn in ...items()` set/
    # dict comprehension here: this project's OWN self-hosting compiler
    # flattens gen_module into one giant C function sharing a single
    # flat per-name variable-type namespace (see the rename note on
    # `_generator_fns`/`_async_fns` above), and the extremely common
    # 2-letter name `fn` is ALREADY reused elsewhere in this same
    # method for a plain field-name STRING (not a FunctionDef) — a
    # comprehension-based version of this exact loop produced a real
    # "assignment to 'char' from 'char *'" self-host compile error
    # (confirmed via `make check-selfhost`), so this uses an
    # unambiguous, never-reused local name and an ordinary loop instead.
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
            # Register stub extern declarations for skipped functions so
            # importing modules can at least reference them (they'll print
            # a warning if actually called at runtime).
            for _fn_name in _gen_only + _async_only + _async_gen:
                _csym = self._func_csym(_fn_name)
                _g = _stub_guard_name(_csym)
                _stub = f'#ifndef {_g}\n#define {_g}\nint64_t {_csym} (...);\n#endif'
                if _stub not in self._elaborated_externs:
                    self._elaborated_externs.append(_stub)
                # See _unsupported_generator_names's docstring: Phase 2a
                # must not ALSO compile this name as an ordinary function.
                self._unsupported_generator_names.add(_fn_name)
        else:
            raise RuntimeError(
                "cannot compile module: function(s) "
                + "; ".join(_categories) +
                " — this codegen compiles every function into a single "
                "straight-line C function and has no suspend/resume "
                "state-machine transform for generators, nor an event loop "
                "/ suspend-resume codegen for async functions, yet, so "
                "these cannot be represented as compiled C without "
                "emitting silently wrong or broken code; falling back to "
                "interpreting this module from source instead")

    # ── Pass 1.3e: refresh return types now that param inference is final ──
    # "Pass 2" (above, executed earlier despite the lower number — it seeds
    # func_return_types before _infer_param_types/Pass 1.3d even run) infers
    # each unannotated function's return type by seeding its unannotated
    # params with the naive int64_t default, since neither the body-usage
    # pass (1.3) nor the cross-call contract (1.3d, just above) had run yet.
    # A function whose real parameter shape only became known from body
    # usage or from a call site's argument type — e.g. `def g(a): return a`
    # called as `g("ab")`, whose `a`/return only resolve to char* via
    # 1.3d's cross-call observation — was frozen here with the wrong
    # int64_t return type. That stayed wrong for every caller compiled
    # before g's own gen_func happened to re-sync func_return_types in
    # Phase 2a (gen_func's "Sync so forward declarations match Phase 2a
    # inference") — in particular a module-level statement like
    # `y = g("a", "b")` (scanned further below, before Phase 2a) and any
    # other function's local-variable type inference (Pass 1.3b above,
    # which itself ran before this correction). Re-run the same
    # inference here with the now-final param types as the seed, rather
    # than adding a parallel special case. See
    # bugs/CODEGEN_untyped_param_string_passthrough_wrong.md.
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

    # ── Pass 1.3f: re-run local-variable type inference ────────────────
    # Pass 1.3b (above) computed _inferred_var_types using the func_return_types
    # in effect at the time — stale for any unannotated callee just corrected
    # by Pass 1.3e. A local assigned straight from such a call (`y = g("a",
    # "b")`) needs the refreshed callee return type to be typed as the real
    # pointer instead of int64_t. Cheap to redo in full (same pass, same cost
    # as Pass 1.3b already paid) rather than special-casing which functions
    # need it recomputed.
    for s in all_functions:
        if isinstance(s, FunctionDef):
            self._inferred_var_types[s.name] = self._infer_local_var_types(s)
    for s in all_structs_for_methods:
        if isinstance(s, StructDef):
            for m in s.methods:
                key = f"{s.name}_{m.name}"
                self._inferred_var_types[key] = self._infer_local_var_types(m)

    # ── Pass 1.3f-gen: cross-call generator-value contract ─────────────
    # A compiled generator's `MojoGenerator *` result is only typed
    # correctly for a LOCAL variable once Pass 1.3d-gen has populated
    # self._generator_api AND Pass 1.3f has re-run local-variable type
    # inference (see `_quick_type`'s generator-call branch) — Pass 1.3d's
    # cross-call scalar contract ran BEFORE both, so a call site that
    # passes a stored generator as an argument (`consume(g)` where
    # `g = counter(3)`) observed `g`'s stale int64_t inference there and
    # left the callee's unannotated param defaulted to int64_t (a `for x
    # in g:` inside the callee then hit the unsupported-iterable
    # fallback). Re-observe those call sites here with the corrected
    # _inferred_var_types, and:
    #   (a) propagate the unanimous `MojoGenerator *` type onto the
    #       callee's unannotated param, mirroring exactly how Pass 1.3d
    #       already propagates a unanimous `char *`/`double` (same
    #       observe-per-call-site/apply-if-unanimous contract, run again
    #       rather than added as a parallel narrow special case), AND
    #   (b) record WHICH generator function made the value (provenance,
    #       walked from the caller's own assignment statements, or
    #       chained through a caller param a previous round already
    #       resolved) so the callee's body can recover the concrete
    #       `base`/`value_ctype` extern "C" API for `for x in g:` /
    #       `next(g)`. The api is keyed per generator FUNCTION in
    #       `self._generator_api`; a param crossing a call boundary has
    #       no `_generator_var_api` entry of its own (that dict is only
    #       populated at construction/assignment sites — see its
    #       docstring), so the provenance is what lets gen_func seed one
    #       for the param. Also records which functions RETURN a
    #       generator (`def mk(): return counter(3)`) so a call to such a
    #       function gets a `_generator_var_api` entry on its result too
    #       (stored-generator/for-loop over `mk()` and `g = mk()` both
    #       then work exactly like `counter(3)` itself). See
    #       bugs/CODEGEN_compiled_generator_not_first_class_value.md.
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
            nonlocal found
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
                        if found is None:
                            found = prov
                        elif found != prov:
                            found = '<conflict>'
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
        return found

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
            # Not assigned in the caller's own body → a pass-through of
            # one of the caller's own params (a prior round's provenance).
            return self._param_generator_api.get(caller_name, {}).get(arg.name)
        if isinstance(arg, CallExpr) and isinstance(arg.func, IdentExpr):
            if arg.func.name in self._generator_api:
                return arg.func.name
            return self._fn_returns_generator.get(arg.func.name)
        return None

    # Functions whose EVERY value-return is a known generator call
    # (`def mk(): return counter(3)`) — used as provenance at call sites
    # AND by _lower_named_call to seed a _generator_var_api entry on the
    # call's result. Skipping nested FunctionDef bodies: only the
    # function's OWN returns count.
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
                # Any generator-valued observation makes the param
                # genuinely `MojoGenerator *` (provenance is only ever
                # non-None for generator-typed call-site arguments), so
                # type it regardless of unanimity — a `for x in g:`
                # inside the callee will then dispatch on the right type
                # and (when no single provenance exists) refuse honestly
                # with "no known API" instead of the misleading int64_t
                # unsupported-iterable. Provenance is recorded ONLY for
                # a unanimous single generator function.
                _annot = None
                for _p, _pt in (_fn.params or []):
                    if _p == _pname:
                        _annot = _pt
                        break
                if _annot is not None:
                    continue  # respect an explicit annotation
                _cur = self._inferred_param_types.get(_callee, {}).get(_pname)
                # `MojoList *` is included here alongside the int64_t
                # default: `_infer_param_types`'s generic body-usage scan
                # (run BEFORE this pass) has no visibility into call-site
                # argument types, so a param consumed only via `for x in
                # g:` (with no subscript) is guessed `MojoList *` purely
                # from `is_iterated` — the same syntactic shape a param
                # consuming a generator has. That guess is exactly wrong
                # when every real call-site argument we observed here is
                # generator-provenanced (`prov is not None`, checked
                # above the observation loop this dict is built from),
                # which is strictly stronger evidence than the body
                # scan's blind guess: it traced the actual value
                # flowing in. Found via `consume(g)`/`consume(mk())`
                # (bugs/CODEGEN_compiled_generator_not_first_class_
                # value.md's composed boundary shapes): `consume`'s
                # param `g` was pre-typed `MojoList *` by the body scan,
                # this pass's guard then skipped it as "already picked a
                # real type", so the caller's real `MojoGenerator *` got
                # force-cast to `MojoList *` at the call site and every
                # `for x in g:` inside `consume` read the coroutine
                # frame's raw bytes through `mojo_list_len`/
                # `mojo_list_get_int` as if it were a MojoList struct —
                # a silent miscompile (no error, no crash at compile
                # time) producing garbage int64 values instead of a hard
                # failure.
                if _cur not in (None, 'int', 'int64_t', 'MojoList *'):
                    continue  # body evidence already picked a real type
                self._inferred_param_types.setdefault(_callee, {})[_pname] = 'MojoGenerator *'
                if len(_keys) == 1 and _keys[0] != '<conflict>':
                    self._param_generator_api.setdefault(_callee, {})[_pname] = _keys[0]
                _changed = True
        if not _changed:
            break

    # Rebuild free-function param-type signatures so call-site coercion
    # (and the emitted declarations) see the propagated MojoGenerator *
    # param types — must follow the propagation above, exactly like Pass
    # 1.3d's own identical rebuild (gen_func's `_param_ctype` consults
    # _inferred_param_types, so the emitted signature is right, but
    # func_param_types is what _emit_call's argument coercion reads).
    for s in all_functions:
        if _is_foreign_main(s):
            continue
        if isinstance(s, FunctionDef):
            if s.params and any(pn.startswith('*') for pn, _ in s.params):
                self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                self._note_vararg_trailing_param_types(s)
            else:
                self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []

    # ── Phase 1.5: dispatch solving (static dispatch table planning) ───
    # Run DispatchSolver to identify dynamic dispatch patterns and plan
    # virtual method tables before generating code. This enables static
    # dispatch instead of dynamic getattr/dict lookups.
    if self.emit_struct_defs:  # Only main module does dispatch solving
        self._dispatch_solver = DispatchSolver(
            self.struct_field_types, self.func_return_types,
            allow_assume_all_methods=_is_selfhost_file,
            generator_method_api=self._generator_method_api)
        all_stmts_for_dispatch = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
        self._dispatch_solver.analyze(all_stmts_for_dispatch)
        self._dispatch_tables = self._dispatch_solver.get_dispatch_tables()

    # ── Pass 3: collect closures (nested FunctionDef nodes) ──────────
    self._all_closures: dict = {}  # outer_name → {inner_name → ClosureInfo}

    def _scan_for_closures(outer_name: str, outer_scope: dict, body: list):
        """Scan a function/method body for nested FunctionDefs and register them as closures."""
        def _all_stmts_nonfunc(stmts):
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

        # Enrich outer_scope with local variable assignments/declarations for capture detection.
        enriched_scope = dict(outer_scope)
        _saved_vt2 = dict(self.var_types)
        self.var_types.update(outer_scope)
        for bstmt in _all_stmts_nonfunc(body):
            if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                name = bstmt.target.name
                if name not in enriched_scope:
                    t = self._quick_type(bstmt.value)
                    enriched_scope[name] = t
                    self.var_types[name] = t
            elif isinstance(bstmt, VarDecl):
                if bstmt.name not in enriched_scope:
                    t = self._quick_type(bstmt.value) if bstmt.value else 'int64_t'
                    enriched_scope[bstmt.name] = t
                    self.var_types[bstmt.name] = t
        self.var_types = _saved_vt2
        for stmt in _all_stmts_nonfunc(body):
            if not isinstance(stmt, FunctionDef):
                continue
            # Step I (create_task/Task/TaskGroup/RaisingTask project):
            # a nested `async def` (not an async GENERATOR — those stay
            # on this ordinary closure-lifting path unchanged, out of
            # this step's scope) was already compiled, if eligible, via
            # the dedicated C++20-coroutine path by gen_module's own
            # _compile_nested_async_functions pre-pass (which runs
            # BEFORE this closure scan — see gen_module for the pass
            # ordering) — it must NOT also be lifted into an ordinary
            # plain-C closure function here, which would either
            # silently shadow/duplicate it or (since no ordinary,
            # non-coroutine lowering anywhere in this file has ever
            # handled `await` — confirmed via grep) simply re-hit the
            # same "unsupported expression" refusal an ordinary
            # lowering attempt of an `await`-containing body always
            # already did before this project's async codegen existed
            # at all. Skipping it here is therefore never a regression
            # (a nested async def with `await` in its body could not
            # have compiled via this ordinary path either way) and is
            # required for a genuinely ELIGIBLE one (skipping it here
            # is what lets the C++ coroutine unit be the only
            # definition anyone calls into).
            if stmt.is_async and not stmt.is_generator:
                continue
            inner     = stmt
            lifted    = f"{outer_name}_{inner.name}"
            # Compute free variables: used in inner body minus inner scope
            used      = set()
            for body_node in inner.body:
                used |= _used_idents_node(body_node)
            # Include AssignStmt targets in declared vars (they're local to inner).
            # Recurse into for/if/while bodies since Python scoping is function-wide.
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
            # Exclude known globals/imported functions from capture — but NOT if
            # the outer function has a PARAMETER with the same name (parameter
            # shadows the global and must be captured, not treated as a global ref).
            # We use outer_scope (parameters only) not enriched_scope (which includes
            # local assignments like module imports that should NOT be captured).
            outer_params = set(outer_scope.keys())
            free_globals = set(self.func_return_types.keys()) - outer_params
            free         = used - inner_declared - free_globals
            captures     = [(v, enriched_scope[v]) for v in sorted(free)
                            if v in enriched_scope]
            # Transitively union in the captures of any REGISTERED
            # nested async unit THIS closure's body calls BY NAME
            # (test_locks.mojo's `test_atomic()` calling `inc()`
            # without itself ever textually referencing `inc()`'s own
            # captured `lock`/`rawCounter` -- gap (1) of bugs/CODEGEN_
            # comptime_bracket_parametrized_function_calls_silently_
            # wrong.md's test_locks.mojo analysis). `self.
            # _nested_async_api` (keyed `f"{enclosing}::{name}"`) is
            # already fully populated for `outer_name` by gen_module's
            # own `_compile_nested_async_functions` pass, which always
            # runs BEFORE this scan (see that method's own docstring
            # for the pass ordering) -- a flat "does this closure call
            # that async unit's name" lookup, not general call-graph
            # analysis, since the async registration already gives an
            # exact, flat name -> captures lookup.
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
            env_struct   = f"{lifted}_env" if captures else ""
            ci           = ClosureInfo(lifted, env_struct, captures, inner)
            # Register this closure's own param defaults keyed by its
            # lifted name, mirroring the top-level free-function
            # registration a few hundred lines up (`all_functions` only
            # covers MODULE-LEVEL FunctionDefs, so a nested closure like
            # `def _inject(iterator=iterator, suffix=suffix): ...`
            # never got an entry there at all) -- without this,
            # _lower_closure_call had no default values to pad with
            # when a call site omits args relying on them (e.g. bare
            # `_inject()`), producing a hard "too few arguments" C
            # compile error instead of a working call.
            # Loop variable deliberately NOT named `_dv`: `gen_module`
            # (this method's enclosing scope) already uses `_dv` as a
            # comprehension loop variable for the identical pattern a
            # few hundred lines up (top-level free-function default
            # registration) -- see this file's own documented self-
            # host gotcha a few lines above (`v` reuse across two
            # comprehensions in the same enclosing function breaks
            # self-hosted compilation, confirmed here by an identical
            # '_dv' undeclared error during make check-selfhost).
            _inner_dflts = getattr(inner, 'param_defaults', None) or {}
            if _inner_dflts:
                self._func_param_defaults[lifted] = [
                    (_pn2, _dv2) for _pn2, _dv2 in _inner_dflts.items()]
            # `{mut}`-capture-spec closures (`def inc() {mut}: counter
            # += 1`) reassign a captured free variable -- detected the
            # same way the async mutable-capture mechanism detects it
            # (_mutated_free_names, a static "does the body ever
            # reassign this name" scan; the parser discards the actual
            # `{mut}` capture-spec text today, so this is the only
            # signal available) -- see ClosureInfo.mut_names. Unioned
            # with `_transitive_mut` (above) so a captured name that's
            # only mutated INSIDE the called async unit's own body
            # (never textually reassigned by THIS closure itself) still
            # gets threaded through by reference, not by value.
            # Loop variable deliberately NOT named `v`: this file is
            # itself self-hosted, and re-using a name already bound by
            # an EARLIER comprehension in this same enclosing function
            # (the `captures = [(v, ...) for v in ...]` a few lines up)
            # in a SECOND, later comprehension hit a real self-host
            # compile error ('v' undeclared) -- gimple_codegen.py's own
            # comprehension-loop lowering doesn't give each
            # comprehension a properly independent C-level loop
            # variable when the same source name is reused. Not
            # investigated further here (see the async path's
            # identical `_cn`-named sibling below for why `_cn`, not
            # `v`, is this project's established safe convention).
            ci.mut_names = self._mutated_free_names(inner, _cap_names_so_far) | _transitive_mut
            if outer_name not in self._all_closures:
                self._all_closures[outer_name] = {}
            self._all_closures[outer_name][inner.name] = ci
            # Register lifted name so callers can resolve its return type
            if inner.return_type is not None:
                self.func_return_types[lifted] = self._resolve_type(inner.return_type)
            else:
                # Quick inference for unannotated inner
                for pname, ptype in inner.params:
                    self.var_types[pname] = self._resolve_type(ptype)
                self.func_return_types[lifted] = self._infer_return_type(inner.body)
                self.var_types.clear()
            # Also recursively scan inner body for doubly-nested closures.
            # Build inner_scope from enriched_scope + inner params + inner local assignments.
            inner_scope = dict(enriched_scope)
            for pn, pt in inner.params:
                inner_scope[pn] = self._resolve_type(pt)
            for bstmt in inner.body:
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    name = bstmt.target.name
                    if name not in inner_scope:
                        inner_scope[name] = self._quick_type(bstmt.value)
            _scan_for_closures(lifted, inner_scope, inner.body)

        # After registering all closures for this outer function, detect re.sub callbacks.
        # Pattern: re.sub(pattern, callback_name, src) where callback_name is a registered inner.
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
                    # re.sub(pat, callback, src)
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
            # Build outer scope: params + VarDecl locals + untyped assignment targets
            outer_scope: dict = {}
            for pname, ptype in s.params:
                outer_scope[pname] = self._resolve_type(ptype)
            # Seed var_types so _quick_type can resolve calls on typed parameters
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
            # Also scan struct methods for nested functions
            _moids = self._struct_method_overload_ids(s)
            for method, _oid in zip(s.methods, _moids):
                outer_name = f"{s.name}_{method.name}{_oid}"
                outer_scope = {s.name.lower(): f"{s.name} *"}  # struct instance
                for pname, ptype in method.params:
                    if pname == 'self':
                        outer_scope['self'] = f"{s.name} *"
                    else:
                        outer_scope[pname] = self._resolve_type(ptype)
                # Function-typed, actually-used comptime bracket parameters
                # are threaded through as ordinary trailing parameters (see
                # _method_threaded_comptime_params) — include them in
                # outer_scope too, so a nested closure that references one
                # (e.g. device_context.mojo's `wrapper` calling the
                # enclosing method's own `func` bracket parameter) is
                # correctly detected as a free variable and captured,
                # instead of falling through as an unresolved bare
                # identifier.
                for _cp_name in self._method_threaded_comptime_params.get((s.name, method.name), {}).get(_oid, []):
                    outer_scope[_cp_name] = 'int64_t'
                # Seed var_types so _quick_type can resolve method calls on self/params
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

    # ── Phase 1.6: propagate transitive captures ─────────────────────
    # If sub-closure S captures variable X from scope that intermediate
    # closure C doesn't directly use, C must also capture X so it can
    # pass it to S's env struct. Repeat until fixpoint.
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

    # ── Pass 3b: re-infer return types now that closures are registered ──
    # `_scan_for_closures` (Pass 3) populated `_all_closures`, which is
    # what lets `_quick_type` type a nested-function VALUE reference
    # (`return add`) as MojoBoundMethod*/void* instead of the int64_t
    # default every earlier return-type-inference pass (Pass 2 / Pass
    # 1.3e) saw. Re-run the same inference here (mirroring Pass 1.3e's
    # identical "refresh now that inputs are final" pattern, with
    # current_func_name seeded per function so the closure lookup
    # resolves) so an unannotated function whose body returns a closure
    # — `def make_adder(n): ...; return add` — gets the real value type
    # in func_return_types BEFORE Phase 2a, regardless of which
    # function's body happens to be compiled first (a call site in any
    # other function types its local from this entry).
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

    # ── Phase 1.7: pre-scan global variable declarations ──────────────
    # Must run before Phase 2a so _lower_IdentExpr can find globals.
    #
    # `if <platform-check>: X = [...] else: X = [...]` (the plain-
    # assignment sibling of gen_module's own conditional-toplevel-def
    # promotion a few hundred lines up -- e.g. Lib/importlib/
    # _bootstrap_external.py's `if _MS_WINDOWS: path_separators =
    # [...] else: path_separators = [...]`) was INVISIBLE to this
    # pre-scan: the loop below only recognizes a plain top-level
    # AssignStmt, never descending into an IfStmt's branches, so such
    # a global never got a `_global_var_types`/`_elem_types` entry at
    # all here. Flatten any top-level conditional whose condition
    # resolves to a known platform-constant bool (mirroring the
    # def-promotion pass's identical resolution logic) down to just
    # its platform-correct branch's statements before scanning, the
    # same way real CPython only ever executes ONE of the branches.
    # Iterative explicit-stack traversal, NOT a self-recursive nested
    # helper -- see the def-promotion pass's own identical comment on
    # why (a nested function calling itself doesn't survive this
    # file's own self-host closure-lifting).
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
    _phase17_mod = self.module_name or "root"  # module name for _global_to_module mapping
    _phase17_own_stmts = _flatten_resolved_conditionals(stmts)
    _phase17_stmts = (_phase17_own_stmts
                       + (_flatten_resolved_conditionals(imported_stmts)
                          if (self.do_imports or self.link_imports) else []))
    # OWNERSHIP (which module's globals struct a name lives in,
    # `_global_to_module`) must only ever be claimed from a module's
    # OWN top-level statements, never from `imported_stmts` (the
    # whole-transitive-tree-visibility superset — see `imported_stmts`'
    # own declaration/PERF doc). `_global_to_module` is a SHARED,
    # first-writer-wins dict: if ownership could be claimed from
    # `imported_stmts` too, then whichever module's OWN Phase 1.7 scan
    # happens to run FIRST (compile order, not true ownership) would
    # permanently claim any name it discovers anywhere in the closure
    # — a real, confirmed bug (found via `mojo.py`'s own self-host
    # build): `mojo_compiler.py`'s top-level `filename = ...` (inside
    # its `if __name__ == "__main__":` block) got attributed to
    # `gimple_codegen` (an unrelated module, merely compiled earlier
    # in this particular closure) purely because gimple_codegen.py's
    # OWN Phase 1.7 scan reached mojo_compiler.py's `filename` via
    # `imported_stmts` before mojo_compiler.py's own temp_gen got a
    # chance to register it correctly. `_global_var_types` (the type-
    # only registry, still populated from the full `_phase17_stmts`
    # below) is unaffected — this only narrows OWNERSHIP attribution,
    # not type-visibility, so cross-module type inference for e.g. an
    # inherited method spliced from a different origin module (see
    # `_merge_struct_inheritance`) keeps working exactly as before.
    # See bugs/CODEGEN_generator_function_Lib_weakref.md.
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
            # `g_mod = dict()` / `g_list = list()` / `g_set = set()` — a
            # constructor CALL, not a `{...}`/`[...]`/`{elem, ...}`
            # literal AST node, so none of the DictExpr/ListExpr/SetExpr
            # branches above ever match it. Without this, it fell
            # through to the generic IdentExpr-call branch just below,
            # which only knows about USER functions (self.struct_field_types
            # / self.func_return_types) — 'dict'/'list'/'set' are neither,
            # so it silently defaulted to 'int64_t'. That wrong type,
            # recorded here in Phase 1.7 (which runs BEFORE Phase 2a
            # generates any function body), is what every function
            # reading the global sees via _global_var_types at the time
            # its OWN body is compiled — even though a separate, later
            # "Module-level globals" pass (_gscan_declare_global's own
            # sibling VarDecl branch) already special-cases this exact
            # shape correctly, that pass runs AFTER Phase 2a and so never
            # gets a chance to correct what function bodies already
            # baked in. Symptom: a global dict/list/set populated via
            # one function and read via `in`/subscript-get from another
            # silently treated the read as a bare int64_t (the `_lower_
            # in_dispatch`/subscript-get dispatch has no 'int64_t'
            # branch, so `x in g_mod` always evaluated False and
            # `g_mod[x]` always misread) even though a `for k in g_mod:`
            # in the SAME function (a separate lowering path that
            # defaults ambiguous globals to dict/falls back through
            # _get_actual_type differently) still worked — see
            # box.3d/game/bugs/DICT_global_rebound_lookup_miss_and_
            # dylib_for_segv.md. Mirrors _quick_type's own _BUILTIN_CTORS
            # map (kept as the single other place this exact mapping is
            # spelled out; not merged into one shared table because
            # _quick_type takes no `self` scan-context and is called in
            # a different pass/signature — same reasoning as the
            # existing three-way Phase-1.7/_gscan_declare_global/Module-
            # level-globals split documented on those functions).
            if (isinstance(_value.func, IdentExpr)
                    and _value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set')):
                return {'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                        'list': 'MojoList *', 'List': 'MojoList *',
                        'set': 'MojoSet *', 'Set': 'MojoSet *'}[_value.func.name]
            if isinstance(_value.func, IdentExpr) and _value.func.name in self.struct_field_types:
                return f"{_value.func.name} *"
            elif isinstance(_value.func, IdentExpr):
                ret = self.func_return_types.get(_value.func.name, '')
                if ret.endswith(' *'):
                    return ret
                elif ret == 'char *':
                    return 'char *'
                else:
                    return 'int64_t'
            elif (isinstance(_value.func, MemberExpr)
                    and _value.func.member in ('read', 'readline')
                    and not _value.args):
                return 'char *'
            elif (isinstance(_value.func, MemberExpr)
                    and _value.func.member == 'readlines'):
                return 'MojoList *'
            else:
                return 'int64_t'
        elif (isinstance(_value, MemberExpr) and isinstance(_value.obj, IdentExpr)
                and _value.obj.name in self.imported_symbols):
            # `X = submod.GLOBAL` — a module-level global initialized
            # from a cross-module attribute read off a real submodule
            # marker (see `_gen_stmt_FromImportStmt`'s and the top-
            # level "Process imports" pre-pass's submodule-marker
            # registration, and `_lower_MemberExpr`'s matching
            # cross-module-global-read branch). The generic `_quick_
            # type` fallback below has no notion of this shape at all
            # and always defaults it to `int64_t` — harmless for a
            # genuinely-int64_t submodule global, but WRONG for e.g. a
            # `char *` one (real case: `Lib/test/test_support.py`'s
            # `TESTFN = os_helper.TESTFN`): the outer global then gets
            # declared `int64_t` while `_lower_MemberExpr` correctly
            # reads back the real `char *` value and boxes it into that
            # `int64_t` slot — a later bare read of the outer global
            # (e.g. `print(TESTFN)`) has no way to know it's actually a
            # boxed pointer and prints the raw address as a number
            # instead of dereferencing it as a string. Resolve the
            # submodule's OWN already-known global type directly (Phase
            # 0 has already fully compiled that submodule via
            # `_compile_imported_module` and populated `_global_var_
            # types`/`_global_to_module` for it, by the time THIS
            # module's own Phase 1.7 scan runs) instead of guessing.
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
            return 'int64_t'
        else:
            qt = self._quick_type(_value) or 'int64_t'
            if qt.endswith(' *'):
                return qt
            elif qt == '_Bool':
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
            # Dict-VALUE-type sibling of the list/tuple element-type
            # inference just above -- was never implemented at all
            # before (a global dict literal's value type had no
            # Phase 1.7 tracking whatsoever, list/tuple-only). Only
            # _global_dict_val_types (persistent) is written here, not
            # the per-function _dict_val_types directly, since that
            # one is now seeded FROM _global_dict_val_types in
            # _reset_func -- see that seed's own comment.
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
            # Track `X = re.compile("literal pattern")` so a later
            # `X.finditer(...)` call (in some function compiled after this
            # module-level scan — see _gen_for_iter) can look the pattern
            # up and get a REAL regex lowering instead of falling to the
            # "unsupported iterable" fallback. See regex_compile.py and
            # BACKLOG-CODEGEN.md §4f for why this exists: re.Pattern.finditer()
            # previously had no codegen lowering at all.
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
            # `a = b = ... = expr` at module scope (e.g. `Modules/
            # getpath.py`'s `executable_dir = real_executable_dir =
            # value.strip()` and `prefix = exec_prefix = ''`) was
            # entirely invisible to this pre-scan — only plain
            # single-target AssignStmt was ever matched above — so
            # every target of a module-level chained assignment fell
            # through to the int64_t default regardless of the RHS's
            # real type. Mirrors the AssignStmt branch: every target
            # gets the SAME inferred type, since real Python chained
            # assignment binds every target to the identical value.
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
                self._global_var_types[_scan_stmt.name] = _resolved
                # MojoDict*/MojoList*/MojoSet* globals are boxed as
                # int64_t at the C storage level (see _lower_IdentExpr's
                # `if gtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                # ctype = 'int64_t'` — the actual, load-bearing read-side
                # convention) — without this, an annotated global (`X:
                # dict = {...}`, now a VarDecl since the parser fix that
                # also fixed StructDef's dataclass-field visibility — see
                # mojo_compiler.py's annotated-assignment parsing) got
                # its struct field declared as the real pointer type
                # directly, mismatching every read site's int64_t
                # assumption: "assignment to 'int64_t' from 'MojoDict *'
                # without a cast".
                #
                # Deliberately NARROWER than "any pointer type" (an
                # earlier version of this comment/condition claimed
                # _lower_IdentExpr boxes EVERY pointer-typed global
                # unconditionally — that's not what the code there
                # actually does: char*/struct-pointer globals are read
                # AND declared directly, unboxed, everywhere else in
                # this file — see _gscan_declare_global's identical
                # MojoDict*/MojoList*/MojoSet*-only boxing a few hundred
                # lines down in gen_module). Boxing char* here too made
                # a bare `X: str` annotation's struct field 'int64_t'
                # while every WRITE to X during Phase 2a (which reads
                # THIS dict, populated here, before the struct-
                # declaration pass further down even runs) correctly
                # boxed a char* value into it — consistent with itself,
                # but not with the eventual UNBOXED 'char *' struct
                # field the struct-declaration pass declares to match
                # _lower_IdentExpr's read side. See bugs/hard/CODEGEN_
                # global_prescan_blind_to_trystmt_and_bare_annotation.md,
                # "Part 2".
                if _resolved in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
            else:
                # Infer type from value if present
                if hasattr(_scan_stmt, 'value') and _scan_stmt.value:
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
                    elif (isinstance(_scan_stmt.value, CallExpr)
                            and isinstance(_scan_stmt.value.func, IdentExpr)
                            and _scan_stmt.value.func.name in ('dict', 'Dict', 'list', 'List', 'set', 'Set')):
                        # `var g_mod = dict()` / `= list()` / `= set()` —
                        # a constructor CALL, not a `{...}`/`[...]`
                        # literal AST node, so none of the DictExpr/
                        # ListExpr/SetExpr branches just above ever
                        # matched it; it fell through to the generic
                        # CallExpr branch below, which only recognizes
                        # USER functions via self.func_return_types —
                        # 'dict'/'list'/'set' aren't registered there, so
                        # it silently defaulted to 'int64_t'. THIS branch
                        # (Phase 1.7, which runs before Phase 2a generates
                        # any function body) is what every function
                        # reading the global actually sees — a separate,
                        # correctly-special-cased "Module-level globals"
                        # pass exists further down (_gscan_declare_global's
                        # sibling VarDecl branch) but runs AFTER Phase 2a,
                        # too late to fix what function bodies already
                        # compiled against. See _phase17_value_type's
                        # identical fix (this mirrors it exactly — kept
                        # as a separate inline branch rather than calling
                        # that helper here since this VarDecl scan also
                        # needs to set _global_c_decl_types, which the
                        # AssignStmt-oriented helper doesn't) and
                        # box.3d/game/bugs/DICT_global_rebound_lookup_
                        # miss_and_dylib_for_segv.md.
                        self._global_var_types[_scan_stmt.name] = {
                            'dict': 'MojoDict *', 'Dict': 'MojoDict *',
                            'list': 'MojoList *', 'List': 'MojoList *',
                            'set': 'MojoSet *', 'Set': 'MojoSet *',
                        }[_scan_stmt.value.func.name]
                        self._global_c_decl_types[_scan_stmt.name] = 'int64_t'
                    elif isinstance(_scan_stmt.value, CallExpr):
                        if isinstance(_scan_stmt.value.func, IdentExpr):
                            ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                            if ret and ret.endswith(' *'):
                                self._global_var_types[_scan_stmt.name] = ret
                            elif ret == 'char *':
                                self._global_var_types[_scan_stmt.name] = 'char *'
                            else:
                                self._global_var_types[_scan_stmt.name] = 'int64_t'
                        elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                and _scan_stmt.value.func.member in ('read', 'readline')
                                and not _scan_stmt.value.args):
                            self._global_var_types[_scan_stmt.name] = 'char *'
                        elif (isinstance(_scan_stmt.value.func, MemberExpr)
                                and _scan_stmt.value.func.member == 'readlines'):
                            self._global_var_types[_scan_stmt.name] = 'MojoList *'
                        else:
                            self._global_var_types[_scan_stmt.name] = 'int64_t'
                    else:
                        qt = self._quick_type(_scan_stmt.value) or 'int64_t'
                        self._global_var_types[_scan_stmt.name] = qt if (qt.endswith(' *') or qt == '_Bool') else 'int64_t'
                else:
                    self._global_var_types[_scan_stmt.name] = 'int64_t'
        elif isinstance(_scan_stmt, TryStmt):
            # A top-level `X: T` / feature-detection global that is
            # ONLY ever assigned inside a try/except/else (e.g. Lib/
            # _pyrepl/main.py's CAN_USE_PYREPL/FAIL_REASON pattern) was
            # completely invisible to this pre-scan before: the loop
            # only ever matched AssignStmt/MultiAssignStmt/VarDecl at
            # this SAME nesting level, so every AssignStmt living
            # inside a TryStmt's branches fell straight through,
            # leaving the global's type unresolved and (per
            # _lower_IdentExpr's unconditional "globals are int64_t at
            # the C storage level" fallback used whenever this pass
            # never recorded anything) eventually causing a type-
            # incoherent placeholder initializer downstream. See
            # bugs/hard/CODEGEN_global_prescan_blind_to_trystmt_and_
            # bare_annotation.md.
            for _gname, _gtype in _phase17_scan_try_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    # A preceding bare `X: T` VarDecl (handled above,
                    # in source order before this TryStmt in the real-
                    # world idiom) or an earlier plain assignment
                    # already resolved this name -- an explicit
                    # annotation/assignment always takes priority over
                    # a type merely inferred from try/except branches.
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                self._global_var_types[_gname] = _gtype
        elif isinstance(_scan_stmt, IfStmt):
            # See _phase17_scan_if_branches' own docstring: an IfStmt
            # whose condition couldn't be comptime-folded away by
            # _flatten_resolved_conditionals (so it still appears here
            # as a single nested node, not inlined into its winning
            # branch) was previously invisible to this pre-scan.
            for _gname, _gtype in _phase17_scan_if_branches(_scan_stmt).items():
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                    self._global_to_module[_gname] = _phase17_mod
                self._global_var_types[_gname] = _gtype
        elif (isinstance(_scan_stmt, ComptimeVarStmt)
                and isinstance(_scan_stmt.value, (ListExpr, TupleExpr))
                and _scan_stmt.target not in _pre_declared_globals):
            # A top-level `comptime NAME = [literal, literal, ...]` (e.g.
            # box.3d/game's `comptime DIR_OFFSETS: [Int; 18] = [0, 0,
            # -1, ...]`) is real Mojo — compile-time-KNOWN VALUE, not a
            # compile-time-ONLY construct: ordinary Mojo code is free to
            # read it at runtime with a DYNAMIC (non-constant) index,
            # e.g. `DIR_OFFSETS[direction * 3]`. Before this branch, a
            # top-level ComptimeVarStmt was invisible to this whole
            # Phase 1.7 pre-scan (it only matches AssignStmt/
            # MultiAssignStmt/VarDecl/TryStmt/IfStmt) — the parser also
            # discards the `[Int; 18]` type annotation entirely for
            # `comptime` statements (see mojo_compiler.py's
            # `_parse_comptime`, "parse and discard type annotation"),
            # so nothing downstream ever learned this name denotes a
            # real array. `_lower_IdentExpr` then fell through to its
            # final "unknown identifier" placeholder (int64_t 0) for
            # every ordinary (non-materialize[]) read of the name, and
            # subscripting that placeholder degraded to indexing a NULL
            # MojoList* (returns 0, doesn't crash) — every element of
            # the array silently read as 0 forever. Registering the
            # SAME type-inference here as an equivalent AssignStmt
            # would (`_phase17_infer_global_type`) makes this a real
            # 'MojoList *' global exactly like `var NAME = [...]` at
            # module scope; the matching toplevel-codegen branch (see
            # this file's other `ComptimeVarStmt` case in the top-level
            # statement dispatch loop) builds the actual backing list
            # at startup so subscripting it now indexes real memory.
            # This does not disturb the EXISTING compile-time-only
            # consumers of a comptime list (`materialize[NAME]()`
            # unrolling, `_comptime_list_asts`) — those are checked at
            # their own call sites before any of this runtime machinery
            # is ever reached. Found via box.3d/game's BUG-2026-011:
            # `_get_adjacent_block`'s `DIR_OFFSETS[direction * 3]`
            # always read (0, 0, 0), so every "neighbor" lookup silently
            # resolved to the block asking the question, and a redstone
            # counter's clock input never saw its lever's real signal.
            _pre_declared_globals.add(_scan_stmt.target)
            if _scan_stmt.target not in self._global_to_module and id(_scan_stmt) in _phase17_own_ids:
                self._global_to_module[_scan_stmt.target] = _phase17_mod
            _phase17_infer_global_type(_scan_stmt.target, _scan_stmt.value)

    # A module-level `var g: list()` / `var g = list()` (no literal
    # elements ever — the empty-at-declaration idiom, e.g. box.3d/
    # game/lib/recipes.mojo's `g_item_names`/`g_item_ids`) has NO
    # element type any of the branches above can see: they only ever
    # look at the declaration's own literal elements (`_elt =
    # self._quick_type(_value.elements[0])` above), and an empty/
    # constructor-call declaration has none. Such a global is
    # populated exclusively via `.append(...)` calls in some OTHER
    # function (e.g. `register_item_name`), read via subscript/`in`/
    # iteration in yet another (e.g. `_name_to_id`) — cross-function,
    # usage-only element-type inference that nothing above attempts.
    # Left unresolved, `_elem_types`/`_global_elem_types` stays empty
    # for these globals and every later list-element codegen path
    # (_lower_subscript's list-get, `.append` itself, `for x in g:`)
    # falls back to its int64_t default: every STRING actually
    # `.append()`-ed gets correctly stored via `mojo_list_append_str`
    # (append lowering resolves the element type from the ARGUMENT's
    # own type, not the global's), but every READ instead did
    # `(char)mojo_list_get_int(...)` — truncating the stored string
    # POINTER to its low byte and reinterpreting that single byte as
    # a 1-char string. `len()` and the append itself are unaffected
    # (the list is genuinely shared/populated correctly — only
    # element READS silently misread), which is exactly why this
    # shape is easy to miss: nothing crashes, nothing is empty, only
    # every stored value reads back wrong. See box.3d/game/bugs/
    # DYLIB_dict_int_key_strdup_null.md's final section.
    #
    # Fix: for every global already known to be a MojoList* (boxed
    # int64_t at the C storage level) that STILL has no element type
    # after the scan above, walk the ENTIRE module (own + imported,
    # matching _phase17_stmts' own scope — an appending function need
    # not be textually before its global's declaration) looking for
    # `<name>.append(<expr>)` call sites anywhere, including nested
    # inside other functions/if/while/for/try/with bodies, and
    # TypeLattice.join the argument's _quick_type across every site
    # found. Mirrors _infer_local_var_types' own param-seeding
    # pattern: since this runs before Phase 2a populates var_types
    # per-function, a function's own annotated parameters (e.g.
    # `name: String`) must be seeded temporarily so `_quick_type` of
    # a bare identifier argument (`g_item_names.append(name)`)
    # resolves to 'char *' instead of falling through to the int64_t
    # "unknown identifier" default.
    def _phase17_collect_appends(_node_list, _append_hits):
        for _n in _node_list:
            if (isinstance(_n, ExprStmt)
                    and isinstance(_n.value, CallExpr)
                    and isinstance(_n.value.func, MemberExpr)
                    and _n.value.func.member == 'append'
                    and isinstance(_n.value.func.obj, IdentExpr)
                    and len(_n.value.args) == 1):
                # Resolve the argument's type NOW, while self.var_types
                # still carries whatever function-parameter seeding is
                # active for this call site (see the FunctionDef branch
                # below) -- deferring to a later pass (after that seeding
                # has been restored) would silently lose it and infer
                # every string-typed parameter argument as int64_t again.
                _append_hits.setdefault(_n.value.func.obj.name, []).append(
                    self._quick_type(_n.value.args[0]))
            if isinstance(_n, FunctionDef):
                _saved = self.var_types
                self.var_types = dict(_saved)
                for _pname, _ptype in (_n.params or []):
                    if _ptype:
                        self.var_types[_pname] = _mojo_type(_ptype)
                # Also seed LOCAL (walrus/assign) variable types, not just
                # annotated params -- e.g. `r := ShapedRecipe(); g_list.
                # append(r)`. Without this, `_quick_type(IdentExpr('r'))`
                # below finds no var_types entry and falls through to its
                # int64_t default, so a global struct list populated only
                # via a local-var append (never a literal or a bare-param
                # append) gets no element type at all. Every subsequent
                # `g_list[i]` read then emits `mojo_list_get_int`, which
                # reads only the boxed pointer's first 8 bytes worth of
                # dispatch instead of the real struct pointer -- see
                # box.3d/game/bugs/DYLIB_struct_list_index_reads_first_
                # field_only_wrong_craft_results.md (game/lib/recipes.mojo's
                # `register_shaped_recipe` etc.).
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

    # Also scan ImportStmts inside TryStmt/IfStmt blocks (e.g., try: import mojo_compiler)
    # These are missed by the flat scan above.
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

    # Pre-populate _global_c_decl_types from _global_var_types so Phase 2a
    # generates correct loads for globals whose C type is a pointer (not boxed int64_t).
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

    # ── Phase 2a: generate all function bodies ────────────────────────
    # This pass populates _ptr_helpers_needed and _struct_allocs_needed
    # so the preamble helpers can be emitted before the __GIMPLE bodies.

    func_parts: list[str] = []

    _emitted_closures: set[str] = set()

    def _emit_closure_recursive(ci, outer_name: str = None) -> None:
        """Emit sub-closures first (depth-first), then this closure's allocator + body."""
        # Deduplicate: overloaded methods share the same closure outer_name, so
        # the same lifted closure may be emitted multiple times (once per overload).
        if ci.lifted_name in _emitted_closures:
            return
        _emitted_closures.add(ci.lifted_name)
        for sub_ci in self._all_closures.get(ci.lifted_name, {}).values():
            _emit_closure_recursive(sub_ci, ci.lifted_name)
        if ci.env_struct:
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

    # Collect top-level statements for _toplevel() function
    toplevel_stmts = []

    # Pre-scan so the main() wrapper (emitted by _gen_function below, before
    # has_toplevel_code is known) can decide whether to call _toplevel().
    # If there is no top-level code we trim the call entirely; otherwise the
    # _toplevel() function is emitted and the call links.
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
        # A top-level `comptime NAME = [literal, ...]` is synthesized
        # into a real runtime-init AssignStmt further down (see this
        # file's other ComptimeVarStmt/ListExpr branches) and DOES need
        # `_toplevel()` called — this pre-scan runs first (the `main()`
        # wrapper it feeds is emitted before the real toplevel_stmts
        # collection below), so it needs the identical condition or the
        # call to `_toplevel()` gets trimmed as dead even though the
        # function now has real initialization code in it.
        if isinstance(_ts, ComptimeVarStmt) and isinstance(_ts.value, (ListExpr, TupleExpr)):
            self._has_toplevel_code = True
            break
    # Step I (create_task/Task/TaskGroup/RaisingTask project): a REAL,
    # pre-existing bug found while getting a real behavioral (compile+
    # link+RUN) verification of test_raising_asyncrt.mojo working —
    # NOT something new this project introduced, but exposed by it
    # (compile_stdlib.py's own gate never actually RUNS anything, only
    # `gcc -fsyntax-only`, so this was invisible to every existing
    # quality gate). `gen_func`'s wrapper for a module's own `def
    # main():` (see its own comment there) assumed ANY top-level code
    # at all means "the top-level code itself already calls main() —
    # e.g. `if __name__ == '__main__': main()`" and therefore skips
    # calling the compiled main function directly, relying entirely on
    # `_toplevel()` to do it. That assumption is FALSE for a real Mojo
    # program's top-level MODULE DOCSTRING (`"""...""""` as the file's
    # first statement — an ordinary, harmless top-level `ExprStmt`,
    # extremely common in real Mojo/stdlib source, ubiquitous in every
    # test file) with NO `__name__` guard at all (real Mojo has no
    # `__name__`/`__main__` convention — `main()` is just the direct,
    # unconditional program entry point) — the compiled binary would
    # silently do NOTHING and exit 0, "looking" like a clean, silent
    # success while actually never running a single line of the
    # program. Confirmed via a minimal repro
    # (`"""doc"""\ndef main(): print(42)`) — `int main` called only
    # `_toplevel()`, whose own body was just the inert docstring
    # assignment, and `42` was never printed.
    #
    # Distinguishes the two cases correctly instead of guessing: does
    # ANY top-level statement actually contain a call to `main(...)`
    # anywhere in its own subtree (the real `if __name__ ==
    # '__main__': main()` shape, and anything structurally
    # equivalent)? If so, unchanged behavior (`_toplevel()` alone,
    # avoiding the ORIGINAL double-invocation bug this code was built
    # to prevent). If not, `gen_func`'s wrapper now calls BOTH
    # `_toplevel()` (for whatever real top-level side effects exist)
    # AND the compiled main function directly — the correct behavior
    # for the common, unconditional-`main()` case this always should
    # have handled.
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
                # Milestone B / Step B: this function's body was already
                # fully translated to C++20 coroutine text by the pre-
                # pass above (self._generator_cpp_units, which holds both
                # generator AND async fragments — see gen_module's two
                # pre-pass loops) — it gets NO ordinary -fgimple C body
                # here at all; only its extern "C" API forward
                # declarations appear in this .c/.ci output (see the
                # preamble emission and the free-function forward-decl
                # loop below, both gated the same way).
                continue
            if stmt.name in self._unsupported_generator_names:
                # See _unsupported_generator_names's docstring: this
                # generator/async function failed C++ translation and was
                # stub-declared instead (relaxed_imports). It must NOT
                # also get an ordinary body here — gen_func has no idea
                # how to lower `yield`, and a second, differently-shaped
                # definition of the same C symbol is a hard conflicting-
                # types compile error, not just wasted work.
                continue
            # Step I: scoped push — temporarily expose this function's
            # own nested async helpers (compiled earlier by
            # gen_module's own _compile_nested_async_functions pass,
            # under a QUALIFIED key — see self._nested_async_api's
            # docstring) into self._async_api under their bare names,
            # for the duration of THIS ONE function's body compile
            # only, so create_task(wrapper())/await composition inside
            # it resolve exactly like a top-level async function would.
            # Popped again right after (whether or not gen_func raises
            # — see `finally`), so a later, unrelated top-level
            # function never sees a stale entry belonging to a
            # DIFFERENT enclosing function's same-named nested helper.
            #
            # Pushed BEFORE the closure-lifting loop just below too
            # (not only around `gen_func`, its original, narrower
            # scope) — test_locks.mojo's own real shape: `inc()` is
            # nested directly in `test_basic_lock`, but CALLED (via
            # `tg.create_task(inc())`) from `test_atomic()`, a
            # DIFFERENT ordinary nested function ALSO declared inside
            # `test_basic_lock` and compiled via the GENERAL (non-
            # async) closure-LIFTING mechanism (`_emit_closure_
            # recursive`/`_gen_lifted_closure`), a separate code path
            # from `gen_func` that this push never used to cover — a
            # real, hand-verified gap: `tg.create_task(inc())` inside a
            # sibling lifted closure found no entry for `inc` in self.
            # _async_api at all (the push hadn't happened yet), and hit
            # `TaskGroup.create_task(...)`'s own "not a call to a
            # known compiled async unit" refusal.
            _nested_pushed = []
            _prefix = f"{stmt.name}::"
            for _qn, _info in self._nested_async_api.items():
                if _qn.startswith(_prefix):
                    _nm = _info['nested_name']
                    self._async_api[_nm] = _info
                    _nested_pushed.append(_nm)
            # A `comptime NAME = <value>` declared directly in `stmt`'s
            # own top-level body is normally only folded into `self.
            # _comptime_vals` when `_gen_stmt_ComptimeVarStmt` actually
            # RUNS, during `gen_func(stmt)` below -- too late for any
            # NESTED closure of `stmt` that references it (`range(0,
            # maxI)`-shaped, test_locks.mojo's own `test_atomic()`
            # idiom), since `_emit_closure_recursive` just below
            # compiles every nested closure BEFORE `gen_func(stmt)`
            # ever runs. Pre-fold them here first -- pure compile-time
            # constant folding, no runtime state involved, so doing it
            # early is always safe. A hand-verified real bug: without
            # this, `range(0, maxI)` inside a nested closure silently
            # read `maxI` as `0` (the same "ct param or undeclared"
            # placeholder `_lower_IdentExpr`'s comptime fallback uses
            # for a genuinely unresolvable name), not a compile error —
            # exactly the kind of silent miscompile CLAUDE.md forbids.
            for _cvs in stmt.body:
                if isinstance(_cvs, ComptimeVarStmt):
                    _cv = self._eval_const(_cvs.value)
                    if _cv is not None:
                        self._comptime_vals.setdefault(_cvs.target, _cv)
            # Per-lexical-scope import tracking: the enclosing function's
            # own body is a scope, and it must stay active while this
            # function's nested CLOSURES are emitted too — closures are
            # emitted BEFORE gen_func(stmt) below, so without this frame a
            # nested def's body could not resolve a name the enclosing
            # function imported locally (a legitimate Mojo pattern). The
            # frame is kept through closure emission AND gen_func (which
            # pushes/pops its own narrower frame on top), then popped.
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
            # Flush any lambdas lifted during gen_func, emitting them
            # immediately before the enclosing function body so forward
            # declarations in the preamble resolve correctly.
            if self._lambda_parts:
                func_parts.extend(self._lambda_parts)
                self._lambda_parts = []
            func_parts.append('')
        elif isinstance(stmt, StructDef):
            # Overload IDs aligned with stmt.methods; the closure-emit, the
            # method symbol, and the pre-pass closure registration all key by
            # the same overload-suffixed name (so overloaded methods with
            # nested closures don't share capture state).
            _moids = self._struct_method_overload_ids(stmt)
            for m, overload_id in zip(stmt.methods, _moids):
                if (stmt.name, m.name) in self._supported_generator_methods:
                    # Milestone C step 3: this method's body was already
                    # fully translated to C++20 coroutine text by the
                    # pre-pass above (self._generator_cpp_units) — same
                    # as a supported free-function generator (see the
                    # analogous FunctionDef skip just above), it gets NO
                    # ordinary -fgimple C body here at all.
                    continue
                method_outer_name = f"{stmt.name}_{m.name}{overload_id}"
                # Emit lifted closures for this method (if any), recursively
                # — with the method's own body as an enclosing lexical
                # scope so a nested closure can resolve a name the method
                # imported locally (see the same wrapping for free
                # functions in the FunctionDef branch above).
                _method_outer_scope = self._push_import_scope()
                self._collect_body_import_bindings(m.body, _method_outer_scope)
                for ci in self._all_closures.get(method_outer_name, {}).values():
                    _emit_closure_recursive(ci, method_outer_name)
                self._lambda_parts = []
                func_parts.append(self._gen_struct_method(stmt.name, m, overload_id))
                func_parts.append('')
                self._pop_import_scope()
                # Flush any lambdas lifted during this method's body (see
                # the identical flush for top-level FunctionDefs above,
                # whose comment explains why body ORDER doesn't matter —
                # the forward decl already lives in the preamble). Without
                # this, a lambda inside a struct method (e.g. a
                # `@classmethod`'s `return lambda *a, **k: ...`) got its
                # forward declaration AND static function-pointer
                # initializer emitted (both registered unconditionally by
                # `_lower_LambdaExpr`), but the actual lifted C function
                # DEFINITION accumulated in `self._lambda_parts` was never
                # flushed anywhere for the struct-method code path — a
                # silent "declared but never defined" link failure.
                # Confirmed via importlib/util.py's `LazyLoader.factory`
                # classmethod: `return lambda *args, **kwargs: cls(loader(
                # *args, **kwargs))` linked as an undefined symbol
                # (`_LazyLoader_factory_lambda_1`) despite compiling clean.
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
            # A top-level `comptime NAME = [literal, ...]` needs REAL
            # runtime backing storage, not just compile-time folding —
            # see this file's matching Phase 1.7 branch (same
            # ComptimeVarStmt/ListExpr condition, a few thousand lines
            # up) for the full why. Synthesize the equivalent
            # `NAME = [literal, ...]` AssignStmt and feed it through the
            # SAME toplevel-init codegen every ordinary module-level
            # list global already uses (builds the real MojoList* via
            # runtime append calls at startup) — this reuses that
            # machinery exactly rather than duplicating a second list-
            # construction path. A plain `comptime NAME = 4096` (or any
            # non-list value) is unaffected: it isn't a ListExpr, so
            # this branch never matches, and it keeps its existing
            # pure-compile-time-fold-only handling.
            toplevel_stmts.append(AssignStmt(
                target=IdentExpr(stmt.target, line=stmt.line, col=stmt.col),
                value=stmt.value, line=stmt.line, col=stmt.col))
        elif isinstance(stmt, (AssignStmt, AugAssignStmt, MultiAssignStmt,
                               ExprStmt, IfStmt, WhileStmt, ForStmt,
                               TryStmt, WithStmt, PassStmt,
                               BreakStmt, ContinueStmt, ReturnStmt,
                               RaiseStmt, AssertStmt, VarDecl)):
            # Collect all executable statements for _toplevel()
            toplevel_stmts.append(stmt)
        else:
            _debug_note('top-level statement dropped', type(stmt).__name__)
            func_parts.append(f"/* TODO: top-level {type(stmt).__name__} */")

    # Populate func_param_types BEFORE _gen_toplevel so call-site coercion works
    # This must happen before _gen_toplevel since it needs param types for _emit_call
    func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
    for fn in func_defs:
        if fn.name == 'main':
            continue
        if fn.params and any(pn.startswith('*') for pn, _ in fn.params):
            self.func_param_types[fn.name] = self._signature_ctypes(fn.params, fn)
            self._note_vararg_trailing_param_types(fn)
        else:
            inferred_params = self._inferred_param_types.get(fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
            param_ctypes = []
            for pn, pt in (fn.params or []):
                if pn in inferred_params:
                    param_ctypes.append(inferred_params[pn])
                else:
                    param_ctypes.append(self._param_ctype(pn, pt, fn))
            self.func_param_types[fn.name] = param_ctypes

    # Only generate _toplevel() if there are actual top-level statements
    has_toplevel_code = len(toplevel_stmts) > 0
    if has_toplevel_code:
        toplevel_func = self._gen_toplevel(toplevel_stmts)
        func_parts.append(toplevel_func)
        func_parts.append('')
        # In library mode, register the sub-module toplevel for the root to call
        if not self.emit_entry_points:
            sub_fn = _module_toplevel_name(self.module_name)
            if sub_fn not in self._sub_toplevels:
                self._sub_toplevels.append(sub_fn)
            # bugs/DYLIB_module_scope_never_executes.md (box.3d/game repo):
            # a standalone `mojo dylib` compile of THIS module (do_imports
            # is False here — an imported sibling pulled into an
            # EXECUTABLE's own translation unit sets do_imports=True and
            # is deliberately excluded below; its toplevel already runs
            # correctly via the executable's own `main()` wrapper calling
            # `_sub_toplevels` explicitly, and giving it an automatic
            # ctor too would fire before that `main()`'s Py_Initialize(),
            # which is unsafe for USE_PYTHON code even though it's
            # otherwise harmless thanks to the one-shot guard in
            # `_gen_toplevel`) has no `main()`/`_gimple_main` at all in
            # its own ABI — nothing EVER calls `sub_fn`. Fix: emit an
            # automatic `__attribute__((constructor))` (fires at dlopen
            # time with no C host cooperation needed) AND export a
            # documented `<module>_init()` alias a C host may call
            # explicitly instead/as well — both simply call `sub_fn`,
            # which is itself one-shot-guarded, so any combination of
            # "ctor already ran it" / "host also called `<module>_init`"
            # is safe, never a double-init.
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

    # Only generate entry points (main/_gimple_main) for the root module
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
            # Call sub-module toplevels first
            for sub_fn in self._sub_toplevels:
                func_parts.append(f"  {sub_fn} ();")
            # Then call root's own _toplevel if it has top-level code
            if has_toplevel_code:
                func_parts.append("  _toplevel ();")
            func_parts.append("#if USE_PYTHON")
            func_parts.append("  Py_Finalize ();")
            func_parts.append("#endif")
            func_parts.append("  return 0;")
            func_parts.append("}")

    # ── Phase 2b: assemble final C output ────────────────────────────

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
    # Forward declarations for sub-module toplevels and root toplevel
    if self.emit_entry_points:
        # Root module: forward-declare all sub-module toplevels
        for sub_fn in self._sub_toplevels:
            parts.append(f'void {sub_fn}(void);')
        # Forward-declare root's own _toplevel if it has top-level code
        if has_toplevel_code:
            parts.append('void _toplevel(void);')
    else:
        # Library module: forward-declare this module's own toplevel if it has one
        if has_toplevel_code:
            fn_name = _module_toplevel_name(self.module_name)
            parts.append(f'void {fn_name}(void);')
    # Built-in type constructor stubs: only emit for names not defined as
    # structs in this module AND not imported (both would conflict with the
    # function declaration).
    _local_structs = set(self.struct_field_types.keys())
    _imported_names = set(self.imported_symbols.keys())
    _skip_ctors = _local_structs | _imported_names
    _builtin_ctors = [
        # Use (...) so any argument type is accepted — these are stubs for
        # Mojo type constructors whose call signatures vary widely at use sites.
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
        # Also suppress this ctor-function stub if the same name was emitted
        # as a struct typedef: `typedef … Error;` (a type) and `int64_t
        # Error(...)` (a function) collide as "Error redeclared as a
        # different kind of symbol". The struct-typedef paths #define
        # _MOJO_STUB_<NAME> right after the typedef and are emitted earlier
        # in the file, so this #ifndef sees it. Hit by `Error` (Mojo's
        # builtin error type) when a module in the closure registers it as
        # an opaque struct — e.g. any enum-importing file (types.py).
        stub_guard = _stub_guard_name(name)
        return (f'#ifndef {stub_guard}\n#ifndef {guard}\n#define {guard}\n'
                + (decl + '\n#endif\n#endif'))
    _ctor_lines = [_guarded_ctor(name, decl) for name, decl in _builtin_ctors if name not in _skip_ctors]
    if _ctor_lines:
        parts.append('/* Mojo built-in type constructors */')
        parts.extend(_ctor_lines)
        parts.append('')
    # Also skip utility stubs for locally-defined functions (they'd conflict).
    # Exclude _C_RESERVED_FUNCS names: those Mojo functions get renamed to mojo_X,
    # so the C function (e.g. getuid) still needs its stub declaration.
    _local_funcs = {s.name for s in stmts
                    if isinstance(s, FunctionDef) and s.name not in _C_RESERVED_FUNCS}
    # Also include struct method names (e.g. Span_unsafe_ptr from fn Span.unsafe_ptr)
    for _s in stmts:
        if isinstance(_s, StructDef):
            for _m in (_s.methods or []):
                if isinstance(_m, FunctionDef):
                    _local_funcs.add(f'{_s.name}_{_m.name}')
    # Renamed forms of local/imported functions — Phase 2b emits proper forward
    # declarations with real signatures; the variadic preamble stub would conflict.
    _local_funcs_renamed = {_safe_name(s.name) for s in stmts if isinstance(s, FunctionDef)}
    _imported_names_renamed = {_safe_name(n) for n in _imported_names}
    # Also skip stubs for functions defined in any sub-module (do_imports=True monolithic build).
    # Exclude _C_RESERVED_FUNCS: their Mojo wrappers get renamed (e.g. getuid → mojo_getuid)
    # so the underlying C function still needs its util stub.
    _all_defined_funcs = (set(self.func_return_types.keys()) | self._global_inline_defs) - _C_RESERVED_FUNCS
    _skip_util = (_local_structs | _imported_names | _local_funcs | _all_defined_funcs
                  | _local_funcs_renamed | _imported_names_renamed)
    _util_pairs = [
        ('iter',    'int64_t iter(...);'),         # FIXME: should be MojoList *iter(MojoList *obj) [current code boxes pointers as int64_t]; variadic so both int and pointer call sites typecheck
        ('next',    'int64_t next(...);'),           # FIXME: should be MojoList *next(MojoList *it) [current code boxes pointers as int64_t]; variadic so both int and pointer call sites typecheck
        ('swap',    'void swap(...);'),    # FIXME: should be void swap(int64_t *a, int64_t *b) [takes pointer arguments boxed as int64_t]; variadic so both int and pointer call sites typecheck
        ('op',      'int64_t op(...);'),
        ('U128',    'int64_t U128(...);'),
        # Pointer: guarded so it's suppressed if the struct typedef was already emitted
        ('Pointer', '#ifndef _MOJO_POINTER_STRUCT_DEF\nint64_t Pointer(...);\n#endif'),
        # Commonly used Mojo stdlib types/constructors — forward-declared as variadic
        # so they compile without full type resolution (do_imports=False mode).
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
        # Mojo's abort() is overloaded (0-arg trap, or message + optional
        # SourceLocation) — incompatible with libc's `void abort(void)`;
        # variadic so every call shape typechecks (see _FORCE_RENAME_RESERVED).
        ('mojo_abort',             'void mojo_abort(...);'),
        ('Span_as_bytes',          'int64_t Span_as_bytes(...);'),
        ('Span_get_immutable',     'int64_t Span_get_immutable(...);'),
        ('_Bool___mlir_i1__',      'int64_t _Bool___mlir_i1__(...);'),
        ('sync_parallelize',       'void sync_parallelize(...);'),
        ('main_func',              'void main_func(void);'),
        # Mojo SIMD/Scalar type constructors and utilities
        ('scalar',                 'int64_t scalar(...);'),
        ('Scalar',                 'int64_t Scalar(...);'),
        ('type_of',                'int64_t type_of(...);'),
        ('align_up',               'int64_t align_up(...);'),
        ('align_down',             'int64_t align_down(...);'),
        ('clamp',                  'int64_t clamp(...);'),
        # NOTE: `isdir` intentionally has NO entry here (removed — see
        # bugs/COMPILE_FAIL_Modules_getpath.md and the paired removal of
        # `'isdir'` from `_KNOWN_SIGS` below, in `_lower_named_call`'s
        # docstring-adjacent comment, for the full root-cause writeup).
        # Short version: unlike every other name in this table (real C
        # stdlib/POSIX functions, or genuine Mojo runtime helpers that
        # always have a backing definition somewhere in the link), a bare
        # `isdir` reference with no local def/import (e.g. CPython's own
        # Modules/getpath.py, where the C embedder injects `isdir` into
        # the exec() namespace at runtime — a mechanism this compiler
        # doesn't have) has NO possible backing definition at all, ever.
        # This table is emitted UNCONDITIONALLY into every compiled
        # file's preamble regardless of whether the name is even
        # referenced (see `_skip_util`/`_util_stubs` above) — fine for a
        # one-line prototype, but wrong for anything needing a real weak
        # body (bloats every single compiled unit, confirmed via
        # test_module_cache.py's "reflect: client object is tiny" size
        # assertion regressing from a first attempt that put a weak
        # `{ mojo_print(...); return 0; }` body directly in this table).
        # The right mechanism for "only synthesize a stub in files that
        # actually call this unresolved name" already exists and is
        # exercised by every sibling CPython-injected name (`abspath`/
        # `isfile`/`joinpath`/`hassuffix`/`warn`/...): `_lower_named_
        # call`'s `_is_unknown`/`self._elaborated_externs` fallback,
        # which lazily emits a `__attribute__((weak))` stub with that
        # same safe body, ONE PER FILE THAT ACTUALLY CALLS IT. `isdir`
        # just needs to be routed through that path instead of this one.
        ('serialize',              'void serialize(...);'),
        ('slice',                  'int64_t slice(...);'),
        ('_getpw_linux',           'int64_t _getpw_linux(...);'),
        ('_lstat_macos',           'int64_t _lstat_macos(...);'),
        # POSIX functions not declared by our minimal header set (<unistd.h> stubs)
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
        # Suppress mojo_open decl when this module defines or imports 'open'
        # (renamed to mojo_open via _C_RESERVED_FUNCS, causing a conflict)
        *([] if ('open' in self.func_return_types or 'open' in self.imported_symbols) else ['void *mojo_open(char *filename, char *mode);']),
        'int64_t int_write (int64_t, char *);',
        'int64_t int_parse_module (int);',
        # Genuinely-unimplemented dispatch helpers (ctypes Structure.in_dll
        # interop; a mis-dispatched .items()). Define as abort() stubs so the
        # program links, but any real call detonates loudly rather than
        # silently returning garbage. Include-guarded: the preamble is emitted
        # once per module, but these must be defined exactly once.
        # `static` so separately-compiled units (module cache: c1.o + l1.o)
        # don't collide at link; the include guard prevents same-file dup
        # (the preamble repeats per module).
        '#ifndef _MOJO_UNIMPL_STUBS',
        '#define _MOJO_UNIMPL_STUBS',
        'static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }',
        'static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }',
        'static int64_t id (int64_t x) { return x; }',
        '#endif',
    ])

    # NOTE: extern prototypes for external_call[...] targets (e.g. write/read/
    # isatty) are emitted AFTER the struct typedef section below — an
    # external_call's argument can be a real user struct pointer (e.g.
    # `external_call["...", Ret](a_device_stream_var, ...)` lowers its arg to
    # `DeviceStream *`, not a boxed int64_t), so the prototype must not precede
    # that struct's typedef.

    # Link mode: extern decls for imported symbols (bodies live in the linked
    # artifact / stdlib dylib, per ABI.md). Collected by the Phase-0 pre-pass.
    for _decl in self._link_import_decl_list:
        parts.append(_decl)
    # NOTE: extern decls for elaborated instantiations (incl. struct methods,
    # which reference monomorphized struct types) are emitted AFTER the struct
    # typedef section below, so the types they reference are already defined.

    # For all modules, declare extern references to known module globals structs
    # Each module can reference globals from other modules via these externs
    # Determine which module is being compiled from either module_name or filename
    our_mod = self.module_name or "root"
    if not self.module_name and self._current_filename:
        # Infer module name from filename (e.g., "myinterpreter.py" → "myinterpreter")
        # (`os` is already imported at module level — a redundant local
        # `import os` here used to shadow it for gen_module's ENTIRE body,
        # since Python scopes a name as local to the whole function the
        # moment it's assigned anywhere in that function, not just from
        # the assignment point onward — any earlier `os.*` use in this
        # same function raised UnboundLocalError.)
        our_mod = os.path.splitext(os.path.basename(self._current_filename))[0]

    all_modules_to_declare = set()

    # If this is not the root module, always declare root's globals (it's special)
    if our_mod != "root":
        all_modules_to_declare.add("root")

    # Add all modules we know about (including successfully compiled ones)
    all_modules_to_declare.update(self._module_globals.keys())

    # Also add all directly imported modules from stmts — even modules that
    # fail to compile need an extern incomplete-struct forward declaration
    # so references like `_build_stdlib_dylib_globals.x` don't get "undeclared".
    # Use the module name (not alias) since generated C accesses _module_globals not _alias_globals.
    all_scan_for_mods = stmts + (imported_stmts if (self.do_imports or self.link_imports) else [])
    for _ms in all_scan_for_mods:
        if isinstance(_ms, ImportStmt):
            # module name, not alias (globals struct uses module name) — every
            # comma-separated target (`import a, b, c`), not just the first.
            for _mn, _ in _import_targets(_ms):
                if _mn and not _mn.startswith('_'):
                    all_modules_to_declare.add(_mn)
        elif isinstance(_ms, FromImportStmt):
            _mn = _ms.module
            if _mn and not _mn.startswith('_') and '.' not in _mn:
                all_modules_to_declare.add(_mn)

    # Emit initial #line directive at the start if we have a filename
    # This sets the context for all subsequent code
    if self._current_filename:
        parts.append(f'#line 1 "{self._current_filename}"')

    # Emit struct typedefs early, before any functions that use them
    # This includes structs from struct_field_types (like Interpreter, Scope, etc.)
    # Emit in dependency order: structs with no struct dependencies first
    # Self-referential dependencies (e.g. Scope->Scope*) are allowed in C
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
                # Check if all dependencies are emitted (excluding self-references)
                dependencies_met = True
                for field_type in fields.values():
                    # Extract struct name from type (e.g., "Scope *" → "Scope")
                    # `'' + field_type` recovers the char* (dict value boxed
                    # as int64_t) so `.rstrip(' *')`/comparison see real
                    # text — without it the self-hosted dependency check saw
                    # garbage and emitted structs out of dependency order.
                    # Also strip a fixed-size-array marker suffix ("Block[4096]"
                    # -> "Block", see _FIXED_ARRAY_ANN_RE) so a struct embedding
                    # a fixed-size array of another local struct still gets
                    # correctly ordered AFTER that element struct's own typedef.
                    base_type = re.sub(r'\[\d+\]$', '', ('' + field_type).rstrip(' *'))
                    # Allow self-references: Scope can have a field of type Scope*
                    if base_type == struct_name:
                        continue  # Self-reference is OK
                    if base_type in self.struct_field_types and base_type not in emitted:
                        dependencies_met = False
                        break
                if not dependencies_met:
                    continue
                # All dependencies met (or are self-references), emit this struct
                _td_start = len(parts)
                if struct_name == 'Pointer':
                    parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    _td_start = len(parts)
                parts.append(f"typedef struct {struct_name} {{")
                # Runtime type tag, always first — see the other struct-typedef
                # emission below (Section 2 for AST-sourced StructDefs) and
                # mojo_read_type_tag in runtime/mojo_runtime.c. This is a
                # SEPARATE typedef-emission path (topologically sorted from
                # struct_field_types rather than walking StructDef nodes
                # directly) that needs the same leading field, or a struct
                # emitted via THIS path never gets tagged and isinstance()
                # against it always reads a stale/garbage first field.
                parts.append(f"  int64_t __mojo_type_id;")
                if fields:
                    # Iterate in DICT INSERTION order, not sorted() —
                    # every population site for struct_field_types[name]
                    # (the main s.fields walk after _merge_struct_
                    # inheritance around gen_module's Phase 1, the
                    # reflected-dylib layout-descriptor parse in
                    # _register_reflected_struct, elaborate_generic_
                    # struct's field list, and _materialize_imported_
                    # struct's own sdef.fields walk) inserts fields in
                    # real declaration/merge order — base fields first,
                    # own fields after — specifically so a subclass
                    # pointer cast to its base type (`(Base *)self`, the
                    # unbound-instance-method call shape) sees identical
                    # field offsets to a real Base struct, C-struct-
                    # inheritance style (no vtable in this codegen).
                    # sorted() here silently alphabetized every such
                    # struct's fields instead, corrupting that layout
                    # compatibility for any subclass that adds its own
                    # field(s) on top of an inherited base (confirmed via
                    # bugs/hard/CODEGEN_struct_typedef_alphabetical_field
                    # _order_breaks_inheritance_layout.md's repro — a
                    # base method invoked through the cast wrote into the
                    # wrong field entirely, a silent data corruption, not
                    # a crash). Section 2 below (the AST-`StructDef.
                    # fields`-driven typedef path) already walks fields
                    # in this same real order; this makes Section 1
                    # agree instead of maintaining a second, independently
                    # -wrong ordering rule.
                    for field_name, field_type in fields.items():
                        # field_type arrives boxed as int64_t (tuple-unpacked
                        # from dict.items()); an f-string interpolation of it
                        # would lower to mojo_str_from_int (its pointer value
                        # as decimal text) in the self-hosted binary. `'' +
                        # field_type` (a fresh local, so its type is the
                        # concat's char* — reassigning the int64_t-typed loop
                        # var itself would keep the old declared type and
                        # still str_from_int it) recovers the char*, and
                        # `ft` is what every f-string below interpolates.
                        ft = '' + field_type
                        # For self-references in typedef, use 'struct Name *' syntax
                        if ft == f"{struct_name} *":
                            # Change Scope * to struct Scope * for self-references
                            ft = f"struct {struct_name} *"
                        safe_fn = f'_kw_{field_name}' if (field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS) else field_name
                        # Fixed-size-array field marker ("ElemCtype[N]",
                        # see _FIXED_ARRAY_ANN_RE): C array-declarator
                        # syntax puts the size after the FIELD NAME, not
                        # after the type ("ElemCtype name[N];"), unlike
                        # every other field shape here.
                        _arr_dm = re.match(r'^(.+)\[(\d+)\]$', ft)
                        if _arr_dm:
                            parts.append(f"  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];")
                        else:
                            parts.append(f"  {ft} {safe_fn};")
                else:
                    # Empty struct - add a dummy field for valid C
                    parts.append(f"  int _dummy;")
                parts.append(f"}} {struct_name};")
                # Milestone C step 3: verbatim copy of this exact typedef
                # text (nothing else, so an identical view compiles under
                # BOTH gcc -fgimple and g++) — reused, not re-derived, by
                # the .cpp preamble for any struct a compiled generator
                # METHOD needs to see (self.<field> access / the `self`
                # parameter's own pointer type). See the generated_cpp
                # assembly further below in gen_module.
                self._struct_typedef_texts[struct_name] = '\n'.join(parts[_td_start:])
                parts.append(f"#define {_stub_guard_name(struct_name)}")  # suppress any later variadic stub
                emitted.add(struct_name)
                self._emitted_structs.add(struct_name)  # track for dedup in Section 2
        parts.append('')

    # `type(node).__name__` runtime resolver: maps a struct's leading
    # __mojo_type_id tag (the _struct_type_id hash) back to its name. Used
    # by every compiled AST walker's `type(x).__name__` dispatch — the
    # self-hosted gimple_codegen's gen_stmt/_EXPR_DISPATCH and the
    # interpreter's execute_{TypeName}. See the __name__ member-expr
    # handling in _lower_MemberExpr (the "<type>" stub made every compiled
    # statement emit `/* TODO: <type> */`).
    if self._needs_type_name_table and not gimple_codegen._emitted_type_name_emitted:
        gimple_codegen._emitted_type_name_emitted = True
        parts.append("static char * _mojo_type_name (int64_t tag)")
        parts.append("{")
        # struct_field_types alone is NOT enough: the compiled binary's
        # gen_stmt/_EXPR_DISPATCH dispatch on `type(node).__name__` for
        # EVERY AST node, and most node types (ExprStmt, AssignStmt,
        # FunctionDef, IntLiteral, ...) are NOT in struct_field_types for
        # an ordinary compile — without them _mojo_type_name fell back to
        # "<type>" and every compiled statement/expression silently emitted
        # `/* TODO: <type> */`. Include the dispatch-table keys so every
        # node type resolves to its real name.
        _type_name_set = set(self.struct_field_types)
        for _dspk in _STMT_DISPATCH.keys():
            _type_name_set.add('' + _dspk)
        for _dspk in _EXPR_DISPATCH.keys():
            _type_name_set.add('' + _dspk)
        for _tn in sorted(_type_name_set):
            # `'' + _tn` recovers the char* (dict key boxed as int64_t); a
            # bare interpolation of `_tn`/`_struct_type_id(_tn)` would
            # str_from_int the pointer instead of the name text.
            _tn_s = '' + _tn
            parts.append(f"  if (tag == {_struct_type_id(_tn_s)}) return \"{_tn_s}\";")
        parts.append("  return \"<type>\";")
        parts.append("}")
        parts.append('')

    for mod_name in sorted(all_modules_to_declare):
        # Skip declaring our own module as extern (sorted: deterministic .ci
        # output, required for the bootstrap stage1==stage2==stage3 check)
        # `mod_s = '' + mod_name` recovers the char*: the loop var arrives
        # boxed as int64_t (a MojoSet element), and an f-string/str() on it
        # would stringify its pointer VALUE instead of the name text
        # (`str()` on an int64_t lowers to mojo_str_from_int — a numeric
        # string that _c_field_name then strips to empty, producing the
        # bogus `struct __toplev`).
        mod_s = '' + mod_name
        if mod_s == our_mod:
            continue
        # Ensure module names are valid C identifiers (replace dots → underscores)
        mod_str = mod_s if mod_s else "root"
        safe_mod = _c_field_name(mod_str) if mod_str else "root"
        struct_name = f"_{safe_mod}_toplev"
        global_var = f"_{safe_mod}_globals"
        # If this OTHER module's real globals field list is already known
        # (see bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
        # defined.md) reconstruct a REAL, field-matching struct typedef
        # here instead of an incomplete stub, mirroring the identical
        # reconstruction the C++ generator side already does from the
        # same shared dict (see the `_cpp_module_global_refs` typedef-
        # copy block further down in this method). A plain incomplete
        # forward declaration only supports pointer-only uses of the
        # extern instance; any real member access (`genericpath.
        # something`) requires the type to be COMPLETE at the point of
        # access, which C disallows for an incomplete type ("invalid
        # use of undefined type"). Field order is deterministic (the
        # populating scan always inserts in sorted name order — see the
        # `for gname in sorted(_declared_globals)` loop below) so this
        # reconstruction exactly matches the layout that module's own
        # compile would emit for itself.
        #
        # This whole `for mod_name in ...` loop is deliberately
        # positioned AFTER the struct_field_types typedef block above
        # (moved there 2026-08-07, "mechanism 2" fix — originally sat
        # right after `all_modules_to_declare` is computed, well BEFORE
        # struct_field_types): a known field's C type can itself be a
        # pointer to a Mojo struct/class type (`_Unknown *`, `_TupleType
        # *`, ...) that struct_field_types defines — reconstructing a
        # full struct HERE, this early, before that typedef exists,
        # produced a real, confirmed regression (`gcc -fsyntax-only`
        # error count on Lib/subprocess.py went 788 -> 1123, "unknown
        # type name '_Unknown'" etc., even though the TARGETED "invalid
        # use of undefined type" error count did drop 26 -> 0) the first
        # time this loop was widened to run unconditionally. Moving the
        # whole loop to after struct_field_types (same place `external_
        # call[...]` prototypes and elaborated-instantiation externs
        # already live, for the identical reason — see their own NOTE
        # comments near the top of this preamble) fixed it — see the doc
        # (bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
        # defined.md) for the exact before/after error-count breakdown.
        #
        # 2026-08-07 update (see the doc's "mechanism 2" section): the
        # `mod_str not in self._module_stmts` restriction above (i.e.
        # "only reconstruct when the module will NOT also get a real
        # definition inlined later") turned out to be based on a false
        # assumption — a module can be fully, successfully compiled
        # (`self._module_stmts` populated) and STILL never have its own
        # text actually embedded anywhere in THIS file's final output,
        # because the TEXT propagation path is per-PARENT: a nested
        # module's compiled C text only reaches the root's output by
        # being threaded, unmodified, through every ancestor's own
        # `imported_code` list — and if any ONE ancestor in that chain
        # itself ultimately fails (e.g. `os.py` failing on an unrelated
        # bug well after successfully, recursively compiling `posixpath`
        # -> `genericpath` as part of its own Phase 0), that ancestor's
        # ENTIRE returned code (including the successfully-compiled
        # descendants nested within it) is discarded by the `if code:`
        # guard around `imported_code.append(code)` — while the
        # descendants' own entries in the SHARED `self._module_globals`/
        # `self._module_stmts` dicts remain, since those commit
        # independently of whatever their parent does afterward.
        # Confirmed via direct .ci inspection on `Lib/subprocess.py`:
        # `_genericpath_toplev`'s real definition (`struct
        # _genericpath_toplev {`) appears NOWHERE in the ~14MB output
        # (0 matches) despite `self._module_globals['genericpath']`
        # being fully populated — because `os` (the only path by which
        # subprocess reaches genericpath) fails outright on an unrelated
        # "'relpath' is ambiguous" bug, so `Imported module: os` never
        # appears in the output at all.
        #
        # There is no way to know, AT THIS POINT, whether the eventual
        # real definition will actually make it into the final text —
        # so this now ALWAYS reconstructs a full, field-matching struct
        # whenever the field list is known, regardless of
        # `self._module_stmts`, guarded by an `#ifndef`/`#define`
        # preprocessor pair (using a name derived purely from the
        # module's own C-safe name, so every emission site for the same
        # module agrees on it) rather than by Python-side "has this
        # already been emitted" bookkeeping — cheap, and correct by
        # construction regardless of how many places (this loop, at
        # however many ancestor levels reference this module; the
        # module's own official per-module emission below) attempt to
        # define the SAME struct, and regardless of which one ends up
        # textually first. The module's own official emission (below,
        # `if self._module_globals.get(current_mod_name):`) wraps its
        # typedef in the identical guard for the same reason. Whichever
        # occurrence is textually first in the final file wins; every
        # later one is a preprocessor no-op — never a GCC "redefinition
        # of struct or union" error, unlike the old Python-side
        # `mod_str not in self._module_stmts` gate this replaces.
        #
        # Falls back to the old incomplete stub only when the field
        # list isn't known at all (e.g. do_imports=False's isolated
        # per-file compiles, where no other module is ever recursively
        # compiled, or a module this level references that was never
        # reached by ANY globals scan anywhere in the tree) — same
        # behavior as before this fix, not a regression for that mode.
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
            # Forward-declare the struct type with gcc attribute to allow incomplete use
            # AND the extern global instance
            parts.append(f'struct {struct_name} __attribute__((incomplete));  /* extern module globals struct */')
            parts.append(f'extern struct {struct_name} {global_var};')

    # extern decls for elaborated instantiations (generic functions + struct
    # methods). Emitted here, after the struct typedefs above, so struct-method
    # declarations like `Box_Int64_unbox (Box_Int64 *)` see the type.
    for _decl in self._elaborated_externs:
        parts.append(_decl)

    # extern prototypes for external_call[...] targets (e.g. write/read/isatty).
    # Skip libc names already declared by our standard includes to avoid clashes.
    for _ecname in sorted(self._external_protos):
        if _ecname in self._LIBC_DECLARED and _ecname not in self._NEEDS_SELF_EXTERN:
            continue
        _eret, _eargs = self._external_protos[_ecname]
        _argstr = ', '.join(_eargs) if _eargs else 'void'
        parts.append(f'extern {_eret} {_ecname} ({_argstr});')


    # Include compiled imported modules.
    # Record where imported code begins: imported modules may reference THIS
    # module's globals struct (e.g. myinterpreter reading _root_globals.mojo_compiler),
    # so the complete struct typedef must be inserted *before* this point rather than
    # after, otherwise those functions see an incomplete type. See the globals struct
    # emission below, which inserts at this index.
    _module_globals_insert_idx = len(parts)
    if imported_code:
        parts.append('')
        parts.extend(imported_code)

    # Pointer-at helper functions (plain C — pointer arithmetic forbidden in __GIMPLE)
    new_helpers = self._ptr_helpers_needed - self._emitted_ptr_helpers
    for et in sorted(new_helpers):
        cn = _c_id(et)
        parts.append(
            f"static {et} * _mojo_at_{cn} ({et} * p, int64_t n) {{ return p + n; }}"
        )
        self._emitted_ptr_helpers.add(et)
    if new_helpers:
        parts.append('')

    # Module-level globals (imported modules, dicts, lists, sets, values at module scope)
    global_decls = []  # kept for compatibility, but won't be emitted
    # Initialize module globals tracking for this module
    current_mod_name = self.module_name or "root"
    if current_mod_name not in self._module_globals:
        self._module_globals[current_mod_name] = []
        self._module_global_inits[current_mod_name] = {}
    # Dispatch table globals already forward-declared near top of file
    # Also declare imported dispatch tables as MojoDict/MojoSet globals
    _dispatch_dict_names = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                            '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
    _dispatch_set_names = {'_CMP_OPS'}
    _dispatch_names = _dispatch_dict_names | _dispatch_set_names
    _declared_globals = set()
    # Scan ONLY this module's own top-level `stmts` here — NOT
    # `imported_stmts`. `imported_stmts` is the whole-transitive-tree
    # visibility list (see bugs/hard/PERF_nested_module_compile_walk_
    # ast_quadratic_rescan.md's "Why the reconciliation loop exists"),
    # deliberately a superset of every module compiled anywhere in the
    # program so far — appropriate for struct/function *visibility*
    # scans (all_struct_defs, all_functions, ...) but WRONG here: this
    # scan's job is registering the CURRENT module's (`current_mod_name`)
    # own globals-struct fields (`self._module_globals[current_mod_name]`
    # below). Every module already independently registers its OWN
    # globals under its OWN name via its own recursive `gen_module` call
    # (each transitively-imported module gets its own `temp_gen` with
    # `module_name=<that module>`, which runs this exact code with
    # `current_mod_name` set correctly) — so re-scanning `imported_stmts`
    # here was pure double-registration under the WRONG module name.
    # Confirmed real bug (found via Lib/weakref.py's transitive-closure
    # build, which pulls in a much larger module graph than earlier
    # per-file tests): `_functools_toplev` ended up with fields like
    # `BINBYTES`/`BOM32_BE` (pickle.py/codecs.py module-level globals)
    # and `AsyncGenerator`/`Attribute` (ast.py/typing.py names) merged
    # into functools.py's OWN globals struct, because `all_scan`/
    # `all_global_scan` included every foreign top-level statement
    # reachable via `imported_stmts` and attributed ANY matching
    # AssignStmt/ImportStmt/VarDecl to `current_mod_name` regardless of
    # which module it actually came from — a massive, real field-name
    # cross-contamination across unrelated modules that (at weakref.py's
    # transitive-closure scale) produced genuine GCC "redefinition"/
    # type-mismatch errors cascading through the rest of the compile.
    # See bugs/CODEGEN_generator_function_Lib_weakref.md.
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
    # Scan current module + imported stmts for module-level variable declarations.
    # Also recurse into TryStmt/IfStmt/ForStmt bodies at module level since Python
    # allows module-level assignments inside try/except (e.g. mojo_compiler = None).
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

    # Same reasoning as `all_scan` just above: only this module's own
    # top-level `stmts`, not the whole-tree `imported_stmts` superset.
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
            if isinstance(value.func, IdentExpr) and value.func.name in self.struct_field_types:
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
                elif ret == 'char *':
                    global_decls.append(f"char * {gname};")
                    self._global_var_types[gname] = 'char *'
                    self._global_c_decl_types[gname] = 'char *'
                else:
                    global_decls.append(f"int64_t {gname};")
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'
            elif (isinstance(value.func, MemberExpr)
                    and value.func.member in ('read', 'readline')
                    and not value.args):
                global_decls.append(f"char * {gname};")
                self._global_var_types[gname] = 'char *'
                self._global_c_decl_types[gname] = 'char *'
            elif (isinstance(value.func, MemberExpr)
                    and value.func.member == 'readlines'):
                global_decls.append(f"int64_t {gname};  /* MojoList * */")
                self._global_var_types[gname] = 'MojoList *'
                self._global_c_decl_types[gname] = 'int64_t'
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
            # `X = submod.GLOBAL` — mirrors the identical MemberExpr
            # case added to `_phase17_value_type` above (see that
            # branch's docstring for the full why: without this, THIS
            # later pass — which actually determines the struct field
            # text and unconditionally overwrites whatever Phase 1.7
            # already inferred, since it runs AFTER Phase 1.7 — would
            # silently downgrade a correctly-inferred `char *` back to
            # `int64_t`, reintroducing the exact same "print(TESTFN)
            # shows a raw pointer address" bug Phase 1.7's fix alone
            # doesn't prevent).
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
            # Module-level `var NAME: T = value` — a real global, not just
            # an AssignStmt. Without this, a top-level `var counter: Int = 0`
            # was never registered in _global_var_types, so a function doing
            # `global counter; counter += 1` emitted "counter undeclared"
            # (gcc error) at compile time. Reuse the AssignStmt path by
            # treating the VarDecl's name+value as the global definition.
            gname = stmt.name
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            if stmt.type_ann and stmt.value is None:
                # A BARE (unassigned) annotation — `FAIL_REASON: str`,
                # no `= ...` — e.g. a feature-detection global only
                # ever assigned inside try/except/else (real instance:
                # Lib/_pyrepl/main.py's CAN_USE_PYREPL/FAIL_REASON).
                # `stmt.value` is None for this shape, so every
                # isinstance(_gv, ...) check below used to fail and
                # fall through to the final catch-all ("int gname;"),
                # silently OVERWRITING whatever real pointer type the
                # separate, EARLIER-running Phase 1.7 pre-scan (which
                # has always consulted type_ann for exactly this case
                # — see gen_module's "Phase 1.7" VarDecl branch) had
                # already correctly recorded in these same
                # self._global_var_types/_global_c_decl_types dicts —
                # this loop runs LATER and unconditionally clobbers
                # them.
                #
                # Resolve the annotation and declare the struct field
                # using the SAME boxing convention this pass's own
                # sibling branches already use (NOT Phase 1.7's: that
                # pass's comment claims "every pointer-typed global is
                # boxed as int64_t", but the actual, load-bearing
                # convention -- both in _gscan_declare_global just
                # above, for AssignStmt-declared globals, AND in the
                # READ side, _lower_IdentExpr's `if gtype in
                # ('MojoDict *', 'MojoList *', 'MojoSet *'): ctype =
                # 'int64_t' else: ctype = gtype` -- only boxes
                # MojoDict*/MojoList*/MojoSet*; a char*/struct-pointer
                # global is declared and read as its real pointer type
                # directly, unboxed. Boxing char* here too (an earlier
                # version of this fix did, copying Phase 1.7's
                # convention literally) declared the struct field
                # int64_t while _lower_IdentExpr's read path still
                # assigned it straight into a char* temp with no cast
                # -- "assignment to 'char *' from 'int64_t'" at every
                # read site. See bugs/hard/CODEGEN_global_prescan_
                # blind_to_trystmt_and_bare_annotation.md, "Part 3".
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
            if (isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr)
                    and _gv.func.name in ('list', 'List', 'dict', 'Dict', 'set', 'Set')):
                # `var g_cooking_recipes = list()` / `= dict()` — a
                # constructor CALL, not a `[...]`/`{...}` literal AST
                # node, so none of the ListExpr/DictExpr/SetExpr branches
                # below ever matched it; it fell all the way through to
                # the final "else: int gname;" catch-all, which is wrong
                # in the SAME way the literal-value branches were before
                # this fix (and just as unboxed on top of being the wrong
                # base type) — "assignment to 'int' from 'MojoList *'" at
                # every read/write of such a global. Found alongside the
                # `_fuel_burn_times` dict-literal bug in the same file
                # (box.3d/game/lib/recipes.mojo's `g_cooking_recipes`/
                # `g_stonecut_recipes`/`g_shapeless_recipes`/
                # `g_shaped_recipes`/`g_name_to_id`).
                _ctype = 'MojoDict *' if _gv.func.name in ('dict', 'Dict') else (
                    'MojoSet *' if _gv.func.name in ('set', 'Set') else 'MojoList *')
                global_decls.append(f"int64_t {gname};  /* {_ctype} */")
                self._global_var_types[gname] = _ctype
                self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(_gv, CallExpr) and isinstance(_gv.func, IdentExpr):
                # `var g_world = engine_create_world()` — a general
                # user-function call (not a list()/dict()/set() literal
                # constructor, handled above), whose return type may be
                # a real struct pointer. This VarDecl-with-value inline
                # scan (distinct from, and previously missing the
                # CallExpr branch that, its sibling `_gscan_declare_
                # global` function above already has — that function is
                # only reached from the separate AssignStmt-based global
                # scan, never from this VarDecl one) fell all the way
                # through to the final "else: int gname;" catch-all for
                # ANY function-call initializer, unconditionally
                # declaring the struct field `int` regardless of the
                # function's real return type. Harmless while every
                # cross-module struct-typed consumer ALSO defaulted to a
                # generic int64_t/int placeholder (a self-consistent,
                # if imprecise, world) — but once a sibling function's
                # OWN parameter type is correctly resolved to a real
                # struct pointer (see _resolve_sibling_param_ctype /
                # the "Process imports" loop's return-type correction
                # above), a global initialized this way and then passed
                # to such a function mismatches: "assignment to 'World
                # *' from 'int' makes pointer from integer without a
                # cast" (confirmed via box.3d/game/lib/game_ffi.mojo's
                # real `var g_world = engine_create_world()` +
                # `engine_place_block(g_world, ...)`). Mirrors
                # `_gscan_declare_global`'s own CallExpr branch exactly
                # (same struct_field_types / func_return_types / char*
                # / generic-int64_t rules) rather than inventing a new
                # rule, so both scans agree on any name they might both
                # eventually see.
                if _gv.func.name in self.struct_field_types:
                    _struct_name = _gv.func.name
                    global_decls.append(f"{_struct_name} * {gname};")
                    self._global_var_types[gname] = f"{_struct_name} *"
                    self._global_c_decl_types[gname] = f"{_struct_name} *"
                else:
                    _ret = self.func_return_types.get(_gv.func.name, '')
                    if _ret.endswith(' *'):
                        global_decls.append(f"{_ret} {gname};")
                        self._global_var_types[gname] = _ret
                        self._global_c_decl_types[gname] = _ret
                    elif _ret == 'char *':
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
                # Boxed as int64_t at the struct-field level — the SAME
                # convention this loop's own bare-annotation branch just
                # above (and _gscan_declare_global's identical AssignStmt-
                # without-annotation case) already use for a
                # MojoDict*/MojoList*/MojoSet* global. This branch handles
                # `var name: T = [...]/{...}/{elem, ...}` — a VarDecl with
                # BOTH a type_ann and a value — and previously declared
                # the struct field as the real pointer type directly,
                # unboxed, while every *read* site of a module-level
                # dict/list/set global (_lower_IdentExpr et al) assumes
                # the boxed convention: "assignment to 'int64_t' from
                # 'MojoList *'/'MojoDict *'/'MojoSet *' makes integer from
                # pointer without a cast" at every read. Found via
                # box.3d/game/lib/recipes.mojo's
                # `var _fuel_burn_times: Dict[Int, Int] = {}`, which
                # failed to compile standalone (a WRITE —
                # `_fuel_burn_times[k] = v` — happened to declare its own
                # temp straight from the correct semantic type and so
                # never tripped over this).
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
            # Struct-field-declaration sibling of this file's other two
            # ComptimeVarStmt/ListExpr branches (Phase 1.7's type-only
            # pre-scan, and the toplevel-statement dispatch loop that
            # synthesizes the matching runtime-init AssignStmt) — see
            # either of those for the full why. Without this branch, the
            # C struct backing this module's globals never gained a
            # field for the comptime array at all, so a synthesized
            # init AssignStmt (this file's earlier fix) that reads
            # `<module>_globals.<name>` at startup referenced an
            # undeclared struct member ("invalid use of undefined type"
            # / "undeclared" GCC errors). Reuses `_gscan_declare_global`
            # exactly like a plain `NAME = [...]` global would.
            gname = stmt.target
            if gname in _declared_globals:
                continue
            _declared_globals.add(gname)
            _gscan_declare_global(gname, stmt.value)
        elif isinstance(stmt, MultiAssignStmt):
            # `a = b = ... = expr` at module scope (e.g. `Lib/codecs.py`'s
            # `BOM_LE = BOM_UTF16_LE = b'\xff\xfe'`) was invisible to
            # this scan — only plain single-target AssignStmt was ever
            # matched above — so a global ONLY ever assigned via a
            # chained assignment never got a struct field declared for
            # it at all. See `_gscan_declare_global`'s own docstring
            # for why this must stay in sync with the separate Phase
            # 1.7 pre-scan's identical fix. Every target gets the same
            # inferred type (real Python chained-assignment semantics).
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
            # `import X as Y` (esp. platform-conditional: `import posixpath
            # as path` / `import ntpath as path` inside os.py's if/else)
            # must register the bound name `Y` as a module-globals struct
            # field. The non-recursive top-level scan above only sees imports
            # at the very top level; _collect_global_stmts recurses into
            # IfStmt/TryStmt/ForStmt bodies, so an import nested there was
            # silently dropped — leaving `globals.path` referencing a field
            # that was never emitted (bug: "struct _X_toplev has no member
            # named 'path'"). Mirror the top-level ImportStmt handler here.
            for _tm, _ta in _import_targets(stmt):
                local_name = _ta if _ta else _tm
                if local_name not in _declared_globals:
                    _declared_globals.add(local_name)
                    global_decls.append(f"int64_t {local_name};")
                    self._global_var_types[local_name] = 'int64_t'
                    self._global_c_decl_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name
    # Skip emitting standalone global declarations — they'll be in module globals structs instead
    # if global_decls:
    #     parts.extend(global_decls)
    #     parts.append('')

    # Populate _module_globals tracking from collected globals
    # Build a map of global name -> module name for later lookup.
    #
    # Do NOT reassign `self._global_to_module` to a fresh `{}` here —
    # it's a SHARED, by-reference dict across every GimpleGen instance
    # in the whole transitive-closure build (see its own declaration
    # in __init__: "global_name -> module_name (shared)", and
    # `_compile_imported_module`'s `temp_gen._global_to_module = self.
    # _global_to_module` sharing). Reassigning the attribute here
    # silently detaches THIS instance from that shared object going
    # forward — every entry any OTHER module's Phase 1.7/this-same
    # section wrote into the ORIGINAL dict stays correct there, but
    # THIS instance's own later reads (in particular `_lower_
    # IdentExpr`'s bare-identifier "does this name belong to some
    # OTHER module" check, which runs during this SAME gen_module
    # call's later statement-lowering phase) only ever see a narrow,
    # freshly-rebuilt view containing just `current_mod_name`'s own
    # globals — losing all ownership information about every other
    # module's globals discovered via Phase 1.7 just above. Confirmed
    # real bug (found via `mojo.py`'s own self-host build): removing
    # this reassignment (this fix) plus scoping Phase 1.7's ownership
    # writes to a module's own statements (that section's own fix,
    # same commit) together resolve a same-symptom regression where a
    # closure inside `gimple_codegen.py` capturing its own enclosing
    # function's `filename` PARAMETER got misresolved as
    # `_gimple_codegen_globals.filename` (a field gimple_codegen.py
    # never declares — the real one lives in `mojo_compiler.py`). See
    # bugs/CODEGEN_generator_function_Lib_weakref.md.
    for gname in sorted(_declared_globals):   # sorted: deterministic field order for bootstrap
        if gname in self._global_var_types:
            g_mtype = self._global_var_types[gname]
            # Use g_mtype as C type; if it ends with *, it's a pointer type
            # Otherwise default to int64_t for numeric types
            if gname in self._global_c_decl_types:
                c_type = self._global_c_decl_types[gname]
            elif g_mtype and g_mtype.endswith(' *') \
                    and self._cpp_known_ptr_struct(g_mtype):
                c_type = g_mtype
            else:
                c_type = 'void *' if (g_mtype and g_mtype.endswith(' *')) else (
                    g_mtype if g_mtype and g_mtype in ('MojoDict *', 'MojoList *', 'MojoSet *', 'char *') else 'int64_t')
            # Find the initialization expression from stmts
            init_code = '0'
            for stmt in _collect_global_stmts(all_global_scan):
                if isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr) and stmt.target.name == gname:
                    init_code = _extract_init_expr(stmt.value)
                    break
                elif (isinstance(stmt, MultiAssignStmt)
                        and any(isinstance(_t, IdentExpr) and _t.name == gname for _t in stmt.targets)):
                    # Same chained-assignment blind spot as the two
                    # scans above (`_gscan_declare_global`/Phase 1.7) —
                    # without this, a global ONLY ever assigned via
                    # `a = b = expr` always got a '0' initializer
                    # (harmless for most types since _gen_toplevel's
                    # own runtime assignment sets the real value right
                    # after, but inconsistent with the plain-AssignStmt
                    # case just above, which extracts the real literal).
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

    # Generate per-module struct typedefs and instances for globals.
    # Build into a local list and insert *before* the imported module code so that
    # imported functions referencing this module's globals (e.g. _root_globals.x) see
    # the complete struct type rather than the incomplete forward declaration.
    if self._module_globals.get(current_mod_name):
        globals_list = self._module_globals[current_mod_name]
        # Ensure module names are valid C identifiers (replace dots → underscores)
        current_mod_str = str(current_mod_name) if current_mod_name else "root"
        safe_name = _c_field_name(current_mod_str) if current_mod_str else "root"
        typedef_name = f"_{safe_name}_toplev"

        globals_struct_lines = []
        # Emit struct typedef, guarded the identical way (same macro
        # name, derived purely from `safe_name`) as the "other
        # referenced modules" reconstruction above — see that block's
        # comment (bugs/hard/COMPILE_FAIL_module_toplev_struct_never_
        # fully_defined.md, "mechanism 2"). An ancestor level may have
        # already emitted (or may later emit) a field-matching
        # reconstruction of this exact struct before this module's own
        # "official" text ends up positioned in the final file — the
        # guard makes whichever occurrence is textually first the one
        # real definition, with every other one a harmless no-op,
        # regardless of emission order or how many places attempt it.
        _toplev_guard = f'_MOJO_TOPLEV_GUARD_{safe_name}'
        globals_struct_lines.append(f'#ifndef {_toplev_guard}')
        globals_struct_lines.append(f'#define {_toplev_guard}')
        globals_struct_lines.append(f"typedef struct {typedef_name} {{")
        for gname, c_type, _ in globals_list:
            globals_struct_lines.append(f"  {c_type} {_c_field_name(gname)};")
        globals_struct_lines.append(f"}} {typedef_name};")
        globals_struct_lines.append('#endif')
        globals_struct_lines.append("")

        # Emit struct instance with initializers
        instance_name = f"_{safe_name}_globals"
        globals_struct_lines.append(f"struct {typedef_name} {instance_name} = {{")
        inits = self._module_global_inits.get(current_mod_name, {})

        for gname, c_type, _ in globals_list:
            init_val = inits.get(gname)
            # C struct initializers must be compile-time constants
            # Only use simple values; function calls must be deferred to runtime
            if not init_val or init_val == '0' or 'mojo_' in str(init_val) or 'new' in str(init_val):
                # Use compile-time constant: NULL for pointers, 0 for integers
                if c_type.endswith(' *'):
                    init_val = f'({c_type})0'
                else:
                    init_val = '0'
            elif init_val.startswith('"') or init_val.startswith("'"):
                # String literals are OK
                pass
            elif init_val.lstrip('-').isdigit():
                # Numeric literals are OK
                pass
            else:
                # Non-constant expression - use default null
                if c_type.endswith(' *'):
                    init_val = f'({c_type})0'
                else:
                    init_val = '0'
            globals_struct_lines.append(f"  .{_c_field_name(gname)} = {init_val},")
        globals_struct_lines.append("};")
        globals_struct_lines.append("")

        # Synthesized cross-module accessor for every one of THIS
        # module's own plain `var` globals (BUG-2026-009) — a real,
        # externally-linked, module-qualified C function that a
        # DIFFERENT translation unit (a bare `from thismodule import
        # <this_global>` in another `mojo dylib`-compiled module — see
        # `_emit_imported_global_accessors`, the consuming half) can
        # `extern`-declare and call to read this global's REAL, live
        # value/pointer, instead of trying to replicate this module's
        # own internal globals-struct FIELD LAYOUT in a foreign TU
        # (fragile: two independently-compiled translation units
        # agreeing byte-for-byte on a whole struct's field order/
        # offsets is not something this per-module-independent compile
        # path can guarantee — a partial/foreign reconstruction of
        # this struct with only ONE field, e.g., would read the WRONG
        # offset whenever this real struct has other fields ahead of
        # it). Emitted unconditionally for every global — mirroring
        # how every free function is already unconditionally exported
        # (module A's own compile has no visibility into which OTHER
        # modules, if any, actually import a given name) — so this is
        # pure additional exported surface, never a behavior change
        # for this module's own code (nothing here is called from
        # THIS module's own body). Symbol naming
        # (`<safe_name>__mojo_global_get_<field>`) must exactly match
        # what `_emit_imported_global_accessors` independently derives
        # on the importing side — both computed via the same
        # `_c_field_name`/`module_name_for_path` convention, so a
        # sibling module's compile agrees on the symbol without either
        # side needing to see the other's actual compile.
        for gname, c_type, _ in globals_list:
            _acc_sym = f'{safe_name}__mojo_global_get_{_c_field_name(gname)}'
            globals_struct_lines.append(
                f'{c_type} {_acc_sym} (void) {{ return {instance_name}.{_c_field_name(gname)}; }}')
        globals_struct_lines.append("")

        insert_idx = _module_globals_insert_idx
        if insert_idx is not None and insert_idx <= len(parts):
            parts[insert_idx:insert_idx] = globals_struct_lines
        else:
            parts.extend(globals_struct_lines)

    # Class-level attribute globals (class body AssignStmt not in __init__)
    class_attr_decls = []
    class_attr_inits = []
    for s in all_struct_defs:
        if isinstance(s, StructDef):
            class_attrs = self._class_attrs
            for aname, mangled in class_attrs.get(s.name, {}).items():
                # Find the assignment in the class body to determine value type
                for field in s.fields:
                    if isinstance(field, AssignStmt) and isinstance(field.target, IdentExpr) and field.target.name == aname:
                        v = field.value
                        ctype = _class_attr_ctype(v)
                        if ctype == 'MojoSet *':
                            # Build init code: create set and add elements
                            inits = [f"  {mangled} = mojo_set_new();"]
                            _set_elts = v.elements if isinstance(v, SetExpr) else []
                            for elt in _set_elts:
                                if isinstance(elt, StringLiteral):
                                    inits.append(f'  mojo_set_add_str ({mangled}, "{_c_escape(elt.value)}");')
                                elif isinstance(elt, IntLiteral):
                                    inits.append(f'  mojo_set_add_int ({mangled}, {elt.value});')
                            class_attr_inits.extend(inits)
                        elif ctype == 'MojoDict *':
                            class_attr_inits.append(f"  {mangled} = mojo_dict_new();")
                        elif ctype == 'MojoList *':
                            class_attr_inits.append(f"  {mangled} = mojo_list_new();")
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
    # Save for use in module init
    self._class_attr_inits = class_attr_inits

    # Free-function "memoize on the function object" attribute globals
    # (`_func_attrs` — see its pre-scan docstring, gen_module Phase 1,
    # and `_lower_MemberExpr`/`_gen_stmt_AssignStmt`'s matching read/
    # write branches). Emitted once per (function, attr) pair across the
    # WHOLE transitive closure — `_emitted_funcattr_decls` (shared the
    # same way `_emitted_ptr_helpers`/`_emitted_funcptr_builtins` are;
    # see those fields' own sharing comments in `_compile_imported_
    # module`) guards against a duplicate `int64_t` definition if two
    # nested temp_gens both see the same already-inlined function.
    # `static`, matching `class_attr_decls` immediately above: this is a
    # single-C-file/whole-program compile (do_imports=True), so there's
    # no cross-translation-unit sharing need, and `static` avoids ANY
    # theoretical clash with an unrelated same-named global elsewhere.
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

    # Struct typedefs (dedup across modules, keep most complete definition)
    if self.emit_struct_defs:
        track_best = {}
        for s in (stmts + self._imported_typedef_structs
                  + (imported_stmts if (self.do_imports or self.link_imports) else [])):
            if isinstance(s, StructDef):
                field_count = len([f for f in s.fields if isinstance(f, VarDecl)])
                if s.name not in track_best or field_count > track_best[s.name][1]:
                    track_best[s.name] = (s, field_count)

        for sd, _ in track_best.values():
            if sd.name not in self._emitted_structs:
                _td_start = len(parts)
                if sd.name == 'Pointer':
                    parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    _td_start = len(parts)
                parts.append(f"typedef struct {sd.name} {{")
                # Runtime type tag, always first — see mojo_read_type_tag
                # in runtime/mojo_runtime.c and _struct_type_id above. Must
                # be the leading field: reading it back needs no per-struct
                # layout knowledge, just a plain int64_t* dereference of the
                # struct's own address (no padding precedes a first member).
                parts.append(f"  int64_t __mojo_type_id;")
                emitted_fields = set()
                for field in sd.fields:
                    if isinstance(field, VarDecl):
                        # Use inferred type from struct_field_types, or resolve from annotation
                        if sd.name in self.struct_field_types and field.name in self.struct_field_types[sd.name]:
                            ft = self.struct_field_types[sd.name][field.name]
                        else:
                            ft = self._resolve_type(field.type_ann) if field.type_ann else 'int'
                        safe_fn = f'_kw_{field.name}' if (field.name in _C_KEYWORDS or field.name in _C_PARAM_EXTRA_KEYWORDS) else field.name
                        # Fixed-size-array field marker ("ElemCtype[N]",
                        # see _FIXED_ARRAY_ANN_RE / Section 1's identical
                        # handling above): the size goes after the field
                        # name in C array-declarator syntax.
                        _arr_dm = re.match(r'^(.+)\[(\d+)\]$', ft)
                        if _arr_dm:
                            parts.append(f"  {_arr_dm.group(1)} {safe_fn}[{_arr_dm.group(2)}];")
                        else:
                            parts.append(f"  {ft} {safe_fn};")
                        emitted_fields.add(field.name)
                # Also emit any fields that are in struct_field_types but not in AST fields
                if sd.name in self.struct_field_types:
                    for field_name, field_type in self.struct_field_types[sd.name].items():
                        if field_name not in emitted_fields:
                            safe_fn = f'_kw_{field_name}' if (field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS) else field_name
                            _arr_dm2 = re.match(r'^(.+)\[(\d+)\]$', field_type)
                            if _arr_dm2:
                                parts.append(f"  {_arr_dm2.group(1)} {safe_fn}[{_arr_dm2.group(2)}];")
                            else:
                                parts.append(f"  {field_type} {safe_fn};")
                parts.append(f"}} {sd.name};")
                # Milestone C step 3: see the identical capture in the
                # struct_field_types-based typedef path above (Section 1)
                # — this is Section 2's own analogous copy, for a struct
                # only ever emitted via THIS path (not already in
                # struct_field_types when Section 1 ran).
                self._struct_typedef_texts[sd.name] = '\n'.join(parts[_td_start:])
                # Suppress any builtin-ctor function stub of the same name in
                # this or another module (a `typedef … Name;` type collides
                # with an `int64_t Name(...)` function) — see _guarded_ctor.
                parts.append(f"#define {_stub_guard_name(sd.name)}")
                parts.append('')
                self._emitted_structs.add(sd.name)

        # Closure env struct typedefs (main module: inside emit_struct_defs block)
        for inner_map in self._all_closures.values():
            for ci in inner_map.values():
                if ci.env_struct and ci.env_struct not in self._emitted_structs:
                    parts.append(f"typedef struct {ci.env_struct} {{")
                    for vname, vtype in ci.captures:
                        # A mutably-captured (`{mut}`-spec) name gets a
                        # pointer field instead of a value copy -- see
                        # ClosureInfo.mut_names.
                        field_ctype = f"{vtype} *" if vname in ci.mut_names else vtype
                        parts.append(f"  {field_ctype} {_c_field_name(vname)};")
                    parts.append(f"}} {ci.env_struct};")
                    parts.append('')
                    self._emitted_structs.add(ci.env_struct)

        # ── Phase C: Dispatch table typedefs (from solver) ──────────────
        # Emit vtable struct typedefs for all planned dispatch tables
        if self._dispatch_solver and self._dispatch_tables:
            for callee_set, dispatch_table in self._dispatch_tables.items():
                if dispatch_table.name not in self._emitted_dispatch_typedefs:
                    typedef = dispatch_table.emit_typedef()
                    if typedef:
                        parts.append(typedef)
                        parts.append('')
                        self._emitted_dispatch_typedefs.add(dispatch_table.name)

    # Struct alloc helpers — __GIMPLE OK because StructName * is the return type
    # Emitted before user-function forward decls so no forward decl needed.
    for sn in sorted(self._struct_allocs_needed):
        if sn in self._emitted_allocs:
            continue  # already emitted by an imported module
        self._emitted_allocs.add(sn)
        alloc_name = f'_alloc_{sn}'
        if alloc_name not in self.func_return_types:
            self.func_return_types[alloc_name] = f'{sn} *'
        # Class-level attributes that are ALSO modeled as instance struct
        # fields (see struct_field_types['Parser']['_CONV_KWS'] etc. and
        # the "self-host hardcoded struct tables" memory note) need their
        # instance slot seeded from the class-level global right here.
        # Member-READ lowering (_lower_MemberExpr) checks struct_field_types
        # BEFORE _class_attrs, so once a name is in both tables (needed so
        # the field gets the right C type / doesn't corrupt self-host
        # GIMPLE type inference), `self.X` reads the INSTANCE field, not
        # the class global - and _alloc_{sn} used to leave every field but
        # __mojo_type_id as raw malloc garbage. A class attribute like
        # `_CONV_KWS = {...}` is never assigned inside __init__ (Python's
        # own attribute-lookup fallback to the class dict is exactly why
        # the source never needs to), so nothing else ever initializes
        # that instance slot - `self._peek().value in self._CONV_KWS`
        # dereferenced garbage as a MojoSet*, segfaulting the first time
        # a self-hosted Parser actually exercised the ref/out/mut
        # soft-keyword path (found debugging make bootstrap's stage2
        # SIGSEGV on mojo_compiler.py). Seeding from the class global here
        # mirrors real Python semantics (a fresh instance's attribute
        # starts as the class value until something assigns over it) and
        # composes correctly with any later `self.X = ...` in __init__/
        # methods, which still just overwrites this same instance field.
        class_attrs = self._class_attrs.get(sn, {})
        field_map = self.struct_field_types.get(sn, {})
        # Only seed when the instance field's declared type actually
        # matches the global's: some class attributes (e.g.
        # LayoutSolver.STACK/HEAP, plain string constants with no `var`
        # annotation) have an unrelated, pre-existing type-inference gap
        # in struct_field_types (defaulting to the wrong C type) that was
        # previously harmless because nothing ever wrote into that
        # instance slot - introducing a write here would turn that latent
        # gap into a new compile error. Skip those; they're no worse off
        # than before this fix (still uninitialized instance-field
        # garbage if ever read that way, same as pre-existing behavior).
        attr_inits = ''.join(
            f"  _p->{_safe_field(aname)} = {gname};\n"
            for aname, gname in sorted(class_attrs.items())
            if aname in field_map
            and field_map[aname] == self._global_var_types.get(gname, field_map[aname])
        )
        parts.append(
            # static: each module that needs it emits its own copy; the
            # monolithic stdlib dylib compiles modules independently, so an
            # externally-linked _alloc_<sn> would collide at link time.
            # Stamps __mojo_type_id (the struct's first field, see the
            # typedef emission above) so isinstance(x, sn) can recognize
            # this instance later — the sole struct-construction choke
            # point, so this is the only place that needs to set it.
            f"static {sn} * __GIMPLE _alloc_{sn} (void)\n"
            f"{{\n"
            f"  {sn} * _p;\n"
            f"  void * _vp;\n"
            f"  int64_t _tag;\n"
            f"\nbb_2:\n"
            # calloc, not malloc: a field with no initializer must read
            # back as 0/NULL (this runtime's None), not as whatever the
            # heap happened to hold. `struct Point: x: Int; y: Int` with
            # no __init__ (test_struct.mojo) left BOTH fields garbage, and
            # any pointer-typed field then fed a wild address to the
            # generic repr/getattr dispatch — a NONDETERMINISTIC segfault
            # (~25% of runs) that made `make bootstrap`'s stage 3 flaky.
            # Zeroing is also what every reader here already assumes: the
            # reflection helpers, _mojo_repr_*, and the `?:` None-guards
            # all test a field against 0/NULL.
            f"  _vp = calloc (1, sizeof({sn}));\n"
            f"  _p = ({sn} *) _vp;\n"
            f"  _tag = (int64_t){_struct_type_id(sn)};\n"
            f"  _p->__mojo_type_id = _tag;\n"
            f"{attr_inits}"
            f"  return _p;\n"
            f"}}"
        )
        parts.append('')

    # Generic reflection dispatch: getattr(x, name)/setattr(x, name, v)/
    # dataclasses.fields(x)/dataclasses.is_dataclass(x) on a value whose
    # static type is unknown (boxed as int64_t/void*) previously always
    # routed to the runtime's mojo_obj_getattr/mojo_setattr stubs, which
    # either abort() (a hard crash: e.g. ast_rewriter.py's generic
    # AST-node walk doing `getattr(node, f.name)`) or silently no-op.
    # Every codegen-emitted struct already carries a runtime type tag
    # (__mojo_type_id, see mojo_read_type_tag in runtime/mojo_runtime.c)
    # and this file already knows every struct's field names/types
    # (struct_field_types) — so a real dispatch table can be built here,
    # once per linked program, instead of leaving this permanently a stub.
    # Plain (non-__GIMPLE) C: GIMPLE's SSA-only restrictions don't apply
    # to functions without that marker (see _HELPERS above), so ordinary
    # if/strcmp control flow is fine here.
    if self.emit_struct_defs:
        # Scoped to structs actually ALLOCATED in this specific program
        # (not the full struct_field_types, which also carries every
        # hardcoded self-hosting compiler class — Parser, Interpreter,
        # Token, etc. — unconditionally, regardless of whether this
        # program touches them). Emitting a getattr/setattr/fieldnames
        # accessor per entry there bloated even a trivial unrelated
        # client program's compiled size (module-cache's whole point is
        # a client stays tiny because bodies live in the shared dylib —
        # see test_module_cache.py's "client object is tiny" checks).
        # _struct_allocs_needed itself used to only track the ROOT
        # module's own allocations, missing structs (e.g. StructDef)
        # only ever constructed inside an IMPORTED module's functions —
        # now shared across temp_gen sub-compiles like _emitted_structs
        # already was (see the do_imports module-compile setup above).
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
                # Fixed-size-array field ("ElemCtype[N]", see
                # _FIXED_ARRAY_ANN_RE): `obj->field` names the whole
                # embedded array, not a scalar/pointer value — casting
                # a VALUE to an array type ("(Block[4096])val") is not
                # legal C, so this generic reflection dispatch (only
                # ever reached for dynamically-typed/unknown-receiver
                # getattr/setattr, never ordinary compiled field access)
                # just skips it, same as any other field shape this
                # dispatch doesn't understand — no regression, since this
                # shape had no reflection support before this fix either.
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
            # `obj.__dict__`/`vars(obj)` on a struct with statically-known
            # fields (Step 0 of bugs/hard/
            # CODEGEN_dynamic_attribute_on_generic_object.md) — a real
            # MojoDict* view of the struct's OWN fields, matching
            # Python's `obj.__dict__` semantics, reusing this same
            # per-struct field enumeration rather than a second,
            # separately-maintained field list. Every value goes through
            # mojo_dict_set_int (the same generic int64_t boxed-value
            # convention every other MojoDict* this codegen builds
            # already uses), matching how _mojo_getattr_{sn}/repr's own
            # per-field access already treat pointer vs. scalar fields
            # identically at the storage-representation level. Gated on
            # `_asdict_dispatch_needed` (see its own declaration) —
            # UNLIKE its getattr/setattr/fieldnames siblings just above
            # (always emitted, however trivial), this one is genuinely
            # optional per-compile and a real client-object-size
            # regression (test_module_cache.py's "client object is
            # tiny" check) confirmed it must not be unconditional.
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
        # Field-by-field repr() — mirrors Python's dataclass repr
        # ("ClassName(field1=..., field2=...)"). Before this, repr() on
        # any compiled struct pointer (e.g. `repr(ast)` on a parsed AST
        # list, mojo.py's own `--dump`) fell to mojo_repr_obj, which has
        # no field-metadata table and just prints an address — real bug
        # found via verify's .ast comparison, where every stage's dump
        # was a meaningless, non-comparable `<object at 0x...>` instead
        # of the node's actual content. Ambiguous case: a field statically
        # typed int64_t that's really an Optional[int]/Any box can't be
        # told apart from a genuine int here (both are the same C
        # representation and Python's None is also encoded as int64_t 0 —
        # see _lower_IdentExpr's `if name == 'None': return 'int', '0'`),
        # so it always prints as a plain number rather than guessing
        # "None" for 0 — the same reasoning as the col=0-not-None fix
        # above, just applied per-field instead of per-print-call.
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
                    # IntLiteral.value wraps to a 64-bit machine word for
                    # real arithmetic, so a literal exceeding int64_t
                    # range (e.g. 0xFFFFFFFFFFFFFFFF) can't dump as the
                    # same decimal text Python's own arbitrary-precision
                    # int repr would show. `raw` (the original source
                    # token text) lets the dump reconstruct the exact
                    # decimal value instead — see
                    # mojo_int_literal_decimal's doc comment.
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
                    # Double-aware repr when this field's element type is
                    # tracked (see _field_elem_types): the generic
                    # _mojo_repr_list mis-reprs (or crashes on) a list of
                    # doubles. Unknown element type keeps the generic repr.
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
        # Forward-declare _mojo_dispatch_repr/_mojo_repr_list/
        # _mojo_repr_dict/_mojo_generic_elem_repr UNCONDITIONALLY (not
        # just when repr_fwd_decls is non-empty): _mojo_generic_elem_repr's
        # own body (emitted below, unconditionally, as part of "Generic
        # reflection dispatch") calls _mojo_repr_list directly (to
        # recurse into a nested list/tuple element) regardless of whether
        # any struct actually needs reflection — with zero reflect_structs
        # (e.g. a trivial program with no structs at all), the old
        # `if repr_fwd_decls:` guard skipped this block entirely, leaving
        # _mojo_repr_list undeclared at its call site inside
        # _mojo_generic_elem_repr and triggering GCC's old-style
        # "implicit declaration" (defaults to int, "conflicting types"
        # once the real definition appears later). Same class of ordering
        # bug the repr_fwd_decls path itself was originally added to fix
        # (see below) — just not covering the empty case.
        parts.append("static char * _mojo_dispatch_repr (void *);")
        parts.append("static char * _mojo_repr_list (MojoList *);")
        parts.append("static char * _mojo_repr_dict (MojoDict *);")
        parts.append("static char * _mojo_generic_elem_repr (int64_t);")
        if repr_fwd_decls:
            # Must precede every _mojo_repr_<sn> body: AST-shaped structs
            # reference each other directly by field type (e.g. FunctionDef
            # has a StringLiteral-typed default, ExprStmt has a value: CallExpr
            # field), so alphabetically-later structs called by an earlier
            # one's body need to already be declared. Found via
            # compile_stdlib.py: _ListIter's generated repr called
            # _mojo_dispatch_repr with no declaration in scope yet,
            # "implicit declaration of function".
            parts.append("/* Forward decls for generic repr() (mutual struct references) */")
            parts.append("\n".join(repr_fwd_decls))
            parts.append('')
        if True:
            # Unconditional (even with refl_parts empty / reflect_structs
            # empty): a forward declaration for these 4 names is always
            # emitted (see "Always add forward decls for cross-module
            # struct methods" below) so an importer calling getattr()/
            # setattr()/dataclasses.fields()/is_dataclass() compiles —
            # the definition must always exist too, or that forward
            # declaration is a link-time dangling reference.
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
            # `_mojo_dispatch_asdict` (Step 0 of bugs/hard/
            # CODEGEN_dynamic_attribute_on_generic_object.md) is, unlike
            # its 4 siblings just below, gated on `_asdict_dispatch_
            # needed` — see that flag's own declaration for why an
            # unconditional-like-its-siblings emission regressed
            # test_module_cache.py's tiny-client-object byte budget.
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

    # Forward declaration for class-attr initializer (main module only)
    if self.emit_struct_defs:
        parts.append("static void _mojo_classattr_init (void);")
        parts.append('')

    # Extern declarations: imported symbols with full parameter information
    # Skip symbols that are already hardcoded in the preamble
    hardcoded = {
        'mojo_print', 'gimple_codegen_compile_to_gimple', 'compile_to_gimple',
        'int_write', 'int_parse_module', 'py_tokenize', 'Parser', 'Interpreter'
    }
    # When do_imports=True, imported module code is inlined — functions will
    # have actual definitions, so extern stubs would conflict. Same for
    # link mode's own inlined-fallback modules (self._link_inline_modules,
    # compiled into imported_stmts above) — those have no dylib either.
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

    # Modules that are pure-Python compiler/JIT infrastructure and are deliberately
    # NOT self-compiled (e.g. the ARM64 JIT engine). Symbols imported from them have
    # no native definition, so emit an abort stub instead of an unresolved extern,
    # letting the self-compiled binary link. These paths are never exercised in
    # compiled mode (the JIT engine only runs under the Python interpreter).
    # TODO: this is a hack. Hardcoding a stub-module allowlist and silently
    # replacing every imported symbol with a no-op stub is wrong — it papers over
    # the real gap (no native JIT engine) and will mask genuinely-missing symbols
    # from these modules. Fine for now to get self-compile to link; revisit with a
    # proper mechanism (e.g. explicit @python_only markers or compiling jit.arm64).
    _stub_only_modules = {'jit.arm64', 'jit'}
    for sym_name in sorted(self.imported_symbols.keys()):
        if sym_name in hardcoded:
            continue
        sym_info = self.imported_symbols[sym_name]
        # Skip module-level imports (import os / import re) — those become
        # int64_t global variables, not extern function declarations.
        if sym_info.get('return_type') == 'unknown':
            continue
        # Skip symbols that are defined inline (when do_imports=True)
        if sym_name in inline_defined or sym_name in self._global_inline_defs:
            continue
        # Skip struct names — they're declared as typedefs, not extern functions
        if sym_name in self.struct_field_types:
            continue
        # Skip C stdlib names declared by system headers — but only if the name is used
        # as-is (i.e., not renamed by _C_RESERVED_FUNCS). If the name IS reserved, the
        # call site uses 'mojo_<name>' (a different symbol) so we still need the extern.
        if sym_name in self._LIBC_DECLARED and sym_name not in _C_RESERVED_FUNCS:
            continue

        module = sym_info.get('module', '')
        if module in _stub_only_modules:
            # Provide a defined-but-unusable stub (plain C, like the _mojo_at_ helpers)
            # so the symbol resolves at link time.
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
            # Guarded with the SAME canonical `_MOJO_STUB_{NAME}` macro
            # convention every other auto-stub generator in this file
            # uses (see the "no signature" branch below, and
            # `_lower_named_call`'s/`_gen_stmt_ExprStmt`'s `_is_unknown`
            # auto-stub paths) — this specific branch used to be emitted
            # completely UNGUARDED (no #ifndef at all), a latent
            # duplicate-definition risk for the same reason the "no
            # signature" branch below was fixed to use a matching guard
            # (see that fix's own comment / bugs/CODEGEN_generator_
            # function_Lib_weakref.md).
            _stub_only_guard = _stub_guard_name(cname)
            parts.append(f"#ifndef {_stub_only_guard}\n#define {_stub_only_guard}\n"
                          f"{ret_type} {cname} () {body}  /* stub from {module} */\n#endif")
            continue

        # _func_csym applies the overload suffix for imported Mojo functions so
        # this extern matches the defining module's mangled symbol and the call
        # sites in this module.
        safe = self._func_csym(sym_name)
        if 'signature' in sym_info:
            # For _C_RESERVED_FUNCS symbols (renamed to mojo_X), the Mojo wrapper may
            # have optional/default parameters that aren't passed at all call sites.
            # Use variadic (...) so any arity is accepted without "too few arguments".
            if sym_name in _C_RESERVED_FUNCS:
                # Prefer c_return_type (already a C type) over return_type (Mojo type)
                ret_type = sym_info.get('c_return_type') or sym_info.get('return_type', 'int64_t')
                if ret_type and ret_type != 'unknown' and not any(
                        c in ret_type for c in ('*', ' ', 'int', 'char', 'void', 'float', 'double')):
                    ret_type = self._resolve_type(ret_type)
                elif not ret_type or ret_type == 'unknown':
                    ret_type = 'int64_t'
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")
            else:
                # New format: use full signature with parameters, applying safe name
                signature = sym_info['signature']
                orig_name = sym_info.get('original_name', sym_name)
                # `signature` text was built (module_loader/_local_sibling_
                # module_exports) from the ORIGINAL definition's own
                # source — it always literally contains `orig_name`, never
                # the local alias `sym_name` (when the two differ). Always
                # substitute `orig_name`, not `sym_name` — matches
                # `_func_csym`'s own aliased-import handling just above
                # (mangling base uses `original_name`, not the alias), so
                # this extern's symbol and the call sites' emitted symbol
                # always agree. Substituting `sym_name` here instead (the
                # previous logic, keyed off `safe != sym_name` — true for
                # nearly every mangled function) was a silent no-op for any
                # ALIASED import: the regex searched for the alias, which
                # never appears in a signature drawn from the real
                # definition, so the extern kept the unmangled,
                # unqualified original name — "implicit declaration of
                # function 'qualifier_origname_hash'" at every call site.
                if safe != orig_name:
                    signature = re.sub(r'\b' + re.escape(orig_name) + r'\b', safe, signature, count=1)
                # Strip Mojo parameter modifiers (out, inout, mut, var, etc.) from signature
                signature = re.sub(
                    r'\b(inout|borrowed|owned|borrow|out|mut|ref|read|copy|var)\s+(?=\w)',
                    '', signature)
                # Rename C control/storage keywords used as Mojo parameter names.
                # Only rename non-type keywords: type keywords (void, int, char, etc.)
                # legitimately appear as C types in extern signatures and must NOT be renamed.
                for _ckw in ('default', 'register', 'auto', 'static', 'extern',
                             'volatile', 'inline'):
                    signature = re.sub(r'\b' + _ckw + r'\b(?=\s*[,)])', f'_kw_{_ckw}', signature)
                # Guard with #ifndef so C preprocessor macros (SEEK_END etc.) aren't
                # accidentally redeclared (the macro would expand before gcc sees the decl).
                parts.append(f"#ifndef {safe}\nextern {signature};  /* from {module} */\n#endif")
        else:
            # No 'signature' was ever attached (see module_loader.py — that
            # key is only set once a real definition is actually found,
            # whether an inlined Mojo function, a compiled dylib symbol,
            # or a reflected C signature). Reaching here means this name
            # (typically `from some_module import name`, e.g. `from
            # itertools import filterfalse`) was never resolved to any
            # real implementation.
            ret_type = sym_info.get('return_type', 'int64_t')
            ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
            if self.do_imports or self.link_imports:
                # do_imports=True is `mojo.py build`'s standalone-binary
                # mode: every resolvable Mojo definition is inlined into
                # this same translation unit and would already have hit
                # the `inline_defined`/`struct_field_types` skips above.
                # So an unresolved name here is genuinely never defined
                # anywhere this build will link against (e.g. a real
                # Python stdlib module this project doesn't implement) —
                # a bare `extern` forward declaration would leave an
                # undefined symbol at link time (bugs/consolidated/
                # COMPILE_FAIL_cc_error_ld_returned_n_exit_status.md).
                # Emit an actual (weak) definition instead, matching the
                # existing "unavailable in compiled mode" convention
                # _stub_only_modules above uses for the same situation.
                #
                # link_imports=True (driver.py's dylib-based link mode)
                # is included here too, NOT just do_imports=True: reaching
                # this branch under link_imports means _register_link_
                # imports's own Phase 0 pre-pass (gen_module, which DOES
                # resolve real dylib/reflection signatures when one
                # exists) already looked at this exact name and could
                # NOT find a 'signature' for it either — e.g. a function-
                # scoped `from pkgutil import read_code` reaching a
                # plain untyped Python function pulled in via module_
                # loader's source-level fallback (no dylib, no type
                # annotations to build a C signature from). Unlike the
                # OLD `else` branch's "another sibling .o will define it
                # later" assumption below (genuinely true for compile_
                # stdlib.py's separately-compiled-.mojo-files workflow),
                # link mode has no such other translation unit for a
                # name Phase 0 already failed to resolve — the bare
                # `extern` this used to fall through to left a real,
                # unconditional undefined symbol at LINK time (confirmed
                # via `Lib/runpy.py`'s `from pkgutil import read_code`/
                # `get_importer` inside `_get_code_from_file`/`_run_path`
                # — see bugs/hard/CODEGEN_function_scoped_import_call_
                # unresolved_at_link.md). Routing link_imports through
                # this same weak-stub path makes its behavior consistent
                # with what a TOP-LEVEL import of the exact same
                # unresolvable name already got for free (the separate,
                # per-call-site `_is_unknown`/`_is_unknown_stmt` auto-
                # stub mechanism in `_lower_named_call`/`_gen_stmt_
                # ExprStmt` — never reached for the function-scoped case
                # because `_gen_stmt_FromImportStmt` had already
                # registered this name into `self.imported_symbols`,
                # marking it "known" before the call site's own lowering
                # ever ran its "is this genuinely unknown" check).
                # Guard against re-emitting the SAME definition when
                # another module elsewhere in this flattened program also
                # imports the same never-resolved name (weak-symbol
                # linkage doesn't help here - this is one definition
                # showing up twice in one translation unit).
                if safe in _emitted_unresolved_stub_syms:
                    continue
                _emitted_unresolved_stub_syms.add(safe)
                if ret_type == 'void':
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); }}'
                else:
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); return ({ret_type})0; }}'
                # Guard name MUST be the canonical `_MOJO_STUB_{NAME}`
                # macro (not the bare `safe` symbol name) — this is the
                # SAME real symbol a completely separate auto-stub
                # mechanism (`_lower_named_call`'s/`_gen_stmt_ExprStmt`'s
                # `_is_unknown`/`_is_unknown_stmt` call-site auto-stub,
                # each per-`temp_gen`-instance, not deduped through the
                # module-global `_emitted_unresolved_stub_syms` set this
                # loop uses) can ALSO stub for the exact same unresolved
                # name (e.g. `get_cache_token`, imported via `from abc
                # import get_cache_token` in functools.py AND called at
                # a use site) — that mechanism already guards its own
                # emitted weak-definition text with `_MOJO_STUB_{NAME.
                # upper()}` (see its own `_stub_guard`/`_stub_key`
                # locals). Using a DIFFERENT guard string here (the bare
                # symbol name) meant cpp's `#ifndef` never recognized
                # the two occurrences as the same guard, so BOTH weak
                # function definitions survived into the same
                # translation unit — a real GCC "redefinition of X"
                # error (found via Lib/weakref.py's transitive-closure
                # build; confirmed via `get_cache_token`, doubly-stubbed
                # once here and once at the call site inside functools.py
                # — see bugs/CODEGEN_generator_function_Lib_weakref.md).
                # Matching the guard convention makes whichever
                # occurrence is textually first in the final .ci win,
                # exactly like every other `_MOJO_STUB_*`-guarded stub
                # in this file already relies on.
                _unresolved_guard = _stub_guard_name(safe)
                parts.append(f"#ifndef {_unresolved_guard}\n#define {_unresolved_guard}\n"
                              f"__attribute__((weak)) {ret_type} {safe} (...) {body}  /* stub from {module} */\n#endif")
            else:
                # do_imports=False AND link_imports=False (e.g.
                # build_module.py / compile_stdlib.py's separately-
                # compiled-.mojo-module workflow, NOT driver.py's dylib-
                # based link mode — that's handled above now): sibling
                # modules are compiled to their own .o and linked
                # together afterward, so an unresolved-here name may
                # legitimately be defined in one of those other
                # translation units. Keep the historical bare-extern
                # behavior — turning this into a stub would silently
                # swallow real cross-module calls instead of linking to
                # their real definition.
                # Legacy format fallback: use pure variadic so callers can pass any args.
                # GIMPLE mode treats () as "no params" (causing "too many args" errors),
                # so we use (...) instead which accepts any number of arguments.
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")

    if self.imported_symbols:
        parts.append('')

    # Note: user-defined functions (_hash, jit_compile_and_execute, etc.) must NOT
    # be pre-registered here with guessed signatures — they get forward declarations
    # generated from their actual definitions below, and pre-registering creates
    # conflicting type errors.

    # Forward declarations: free functions (skip main — handled specially)
    func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
    if self._supported_generators or self._generator_method_api:
        # Milestone B (free functions) / Milestone C step 3 (struct
        # methods): the extern "C" API (opaque handle + start/resume/
        # value/destroy) for every supported generator in this module —
        # the ONLY forward declarations these functions get (they have
        # no ordinary -fgimple C body/prototype at all; see the Phase 2a
        # skip above, both the FunctionDef one and the StructDef-methods
        # one). One shared opaque MojoGenerator typedef covers every
        # generator regardless of its yielded-value type — see
        # _gen_cpp_generator_unit's docstring for why a bare
        # reinterpret_cast of the coroutine_handle's own address is
        # enough, no separate wrapper allocation needed. A generator
        # METHOD's `<base>_start` takes the enclosing struct's `{Name}
        # *` as its first parameter — the struct's own C typedef is
        # already emitted earlier in this same preamble (see the
        # struct-typedef emission above, well before this point), so the
        # type is already known here.
        parts.append('typedef struct MojoGenerator MojoGenerator;')
        for _api in list(self._generator_api.values()) + list(self._generator_method_api.values()):
            _base, _vct = _api['base'], _api['value_ctype']
            _gptypes = ', '.join(_api.get('params') or []) or 'void'
            parts.append(f"extern MojoGenerator *{_base}_start ({_gptypes});")
            parts.append(f"extern _Bool {_base}_resume (MojoGenerator *);")
            parts.append(f"extern {_vct} {_base}_value (MojoGenerator *);")
            parts.append(f"extern void {_base}_destroy (MojoGenerator *);")
        parts.append('')
    # `_coro_resume_fn`/`_coro_destroy_fn` (std.builtin.coroutine) used
    # as bare VALUES anywhere in this compile — even a module with NO
    # supported async function/closure of its OWN can still reference
    # them this way (e.g. std/runtime/asyncrt.mojo's `_async_execute`
    # generic, elaborated via monomorphize.py's own INDEPENDENT
    # GimpleGen instance per instantiation — a real, hand-verified
    # regression: that instance's `_funcptr_mojo_coro_resume_generic =
    # (void *)mojo_coro_resume_generic;` static initializer referenced
    # an undeclared symbol, since the header's inclusion was gated only
    # on this SAME instance's own _supported_async/_supported_async_
    # closures, which an elaborated fragment with no async function of
    # its own never populates) — so this must ALSO pull in the header,
    # independent of the `_supported_async`/`_supported_async_closures`/
    # `_nested_async_api` gate just below. NOTE: this gate's operands
    # are deliberately plain `len(...)` ints rather than bare container
    # truthiness — `bool(dictA or dictB or dictC or set_intersection)`
    # compiles the `or` chain to a boxed int64_t (the dict/set types
    # join to int64_t), and `bool(int64_t_holding_a_pointer)` compares
    # pointer-non-nullness, so three EMPTY dicts plus an empty
    # intersection still read as True — a native-vs-Python divergence
    # (Python `bool({})` is False; the self-hosted binary's was True).
    # Explicit lengths sidestep the boxing entirely.
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
        # Step B: the extern "C" API (opaque handle + start/is_done/
        # value/destroy — no `_resume`, see _gen_cpp_async_unit's
        # docstring) for every supported async function in this module.
        # `_supported_async_closures` (device_context.mojo's nested
        # `async def wrapper(...) capturing -> None:` closures — see
        # gen_module's dedicated discovery pass) shares this exact same
        # extern "C" API shape, just keyed by (outer_ctx, inner_name)
        # instead of bare name, so it ALSO needs this preamble (the
        # `MojoAsync` opaque type + mojo_async_runtime.h) even when the
        # module has no genuinely TOP-LEVEL supported async function at
        # all — a name-only gate on _supported_async would silently
        # leave this file with implicit-declaration errors for
        # `_mojoasync_wrapper_start`/etc. instead.
        # A separate opaque `MojoAsync` type from `MojoGenerator` (not
        # reused) — matches _gen_cpp_async_unit's own promise_type being
        # a deliberately fresh, separate C++ type from the generator's;
        # keeping the C-side opaque pointer types distinct too means a
        # accidental cross-call (passing a MojoGenerator* where an
        # async handle is expected, or vice versa) is a real compile-
        # time type error here, not just a silent void*-shaped bug.
        # mojo_async_schedule_ready()/mojo_async_run_until_complete()
        # (Step A's own scheduler API, declared in mojo_async_runtime.h,
        # included just below) are called directly from the call-site
        # lowering in _lower_call — `MojoAsync *` converts to
        # mojo_async_schedule_ready's `void *` parameter implicitly in
        # C, no cast needed at the call site.
        parts.append('typedef struct MojoAsync MojoAsync;')
        parts.append('#include <mojo_async_runtime.h>')
        # Step I: nested async functions (self._nested_async_api,
        # qualified-key-only — see that dict's own docstring) get their
        # extern "C" declarations emitted here too, unconditionally,
        # alongside the top-level ones (self._async_api) — each has its
        # own already-unique, scope_prefix-qualified `base` (see
        # _gen_cpp_async_unit), so there is no name-collision risk in
        # emitting every nested unit's forward declarations regardless
        # of which one (if any) the module's own per-statement body
        # loop ends up actually calling into.
        for _api in list(self._async_api.values()) + list(self._nested_async_api.values()):
            _base, _vct = _api['base'], _api['value_ctype']
            _aptypes = ', '.join(_api.get('params') or []) or 'void'
            parts.append(f"extern MojoAsync *{_base}_start ({_aptypes});")
            parts.append(f"extern _Bool {_base}_is_done (MojoAsync *);")
            parts.append(f"extern {_vct} {_base}_value (MojoAsync *);")
            parts.append(f"extern void {_base}_destroy (MojoAsync *);")
            # Step E: the outermost-edge exception translation, called
            # ONLY from the `asyncio.run(...)` bridge below -- see
            # _gen_cpp_async_unit's own {base}_translate_pending_exc
            # docstring.
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
    for fn in func_defs:
        if fn.name == 'main':
            continue
        if (fn.name in self._supported_generators or fn.name in self._supported_async
                or fn.name in self._supported_async_gen):
            continue
        if fn.name in self._unsupported_generator_names:
            # See _unsupported_generator_names's docstring — already has
            # its own `int64_t NAME (...);` stub declaration; do not ALSO
            # forward-declare it here with a second, differently-shaped
            # ordinary signature (a "conflicting types" compile error).
            continue
        ret    = self.func_return_types.get(fn.name, 'int64_t')
        # If any param is *args, the call convention uses a packed MojoList*
        has_varargs = any(pn.startswith('*') for pn, _ in (fn.params or []))
        if has_varargs:
            param_ctypes = self._signature_ctypes(fn.params, fn, sentinel='MojoList *')
            self.func_param_types[fn.name] = self._signature_ctypes(fn.params, fn)
            self._note_vararg_trailing_param_types(fn)
        else:
            param_ctypes = []
            inferred_params = self._inferred_param_types.get(fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
            for pn, pt in (fn.params or []):
                if pn in inferred_params:
                    param_ctypes.append(inferred_params[pn])
                else:
                    param_ctypes.append(self._param_ctype(pn, pt, fn))
            self.func_param_types[fn.name] = param_ctypes
        ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
        # For _C_RESERVED_FUNCS (e.g. getuid → mojo_getuid), use the renamed
        # C name as the guard so the original C name's util stub is not blocked.
        # _func_csym adds the overload suffix so this forward decl matches the
        # definition and call sites.
        _c_fn_name = self._func_csym(fn.name)
        _guard_name = _c_fn_name if fn.name in _C_RESERVED_FUNCS else fn.name
        stub_guard = _stub_guard_name(_guard_name)
        parts.append(f'#ifndef {stub_guard}')
        parts.append(f"{ret} {_c_fn_name} ({ptypes});")
        parts.append('#endif')

    # Forward declarations: struct methods
    # When do_imports=True, imported code is inlined and already contains its own
    # forward declarations — don't re-emit them with potentially stale types.
    struct_defs = [s for s in stmts if isinstance(s, StructDef)]
    if not self.do_imports:
        struct_defs += [s for s in (imported_stmts or []) if isinstance(s, StructDef)]
    for sd in struct_defs:
        # Overload-id per method, aligned with sd.methods — this used to
        # be a second, hand-rolled copy of _struct_method_overload_ids'
        # exact logic (a maintenance risk: the two copies could drift).
        # Calling the shared @staticmethod instead guarantees this loop's
        # forward-declared name always matches _gen_struct_method's own
        # emitted symbol.
        _moids = self._struct_method_overload_ids(sd)
        method_ids = {id(m): oid for m, oid in zip(sd.methods, _moids)}

        for m in sd.methods:
            if (sd.name, m.name) in self._supported_generator_methods:
                # Milestone C step 3: no ordinary StructName_method(...)
                # C function exists for this method at all — it has its
                # own extern "C" <base>_start/_resume/_value/_destroy
                # API instead (forward-declared separately, alongside
                # the free-function generator API — see the
                # `_generator_api`/`_generator_method_api` forward-decl
                # block above). Emitting an ordinary forward declaration
                # here would just be a harmless-looking but WRONG
                # prototype for a symbol nothing defines or calls.
                continue
            overload_suffix = method_ids.get(id(m), '')
            mangled_name = self._struct_method_csym(sd.name, m.name, overload_suffix)
            # Use per-overload key first; fall back to base name, then AST annotation
            ret = (self.func_return_types.get(f"{sd.name}_{m.name}{overload_suffix}")
                   or self.func_return_types.get(f"{sd.name}_{m.name}")
                   or self._resolve_type(m.return_type))
            method_full_name = f"{sd.name}_{m.name}"
            # Prefer param types stored during definition generation (exact match)
            per_overload_params = self.func_param_types.get(mangled_name)
            if per_overload_params is not None:
                param_ctypes = per_overload_params
            elif any(pn.startswith('*') for pn, _ in (m.params or [])):
                # *args method: fixed params (+ self) + MojoList*; **kwargs -> MojoDict*
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

        # For overloaded methods, also emit a catch-all base-name decl so that
        # call sites that use the unmangled name (e.g. Slice___init__) don't fail
        # with "implicit declaration of function". Qualified the same way the
        # real per-overload decls above are, so it's declaring the same
        # (home-module-prefixed) symbol namespace, not a stray unqualified one.
        _emitted_base: set[str] = set()
        for m in sd.methods:
            if method_ids.get(id(m), ''):  # has an overload suffix
                base_cname = self._struct_method_csym(sd.name, m.name, '')
                if base_cname not in _emitted_base:
                    base_ret = (self.func_return_types.get(f"{sd.name}_{m.name}")
                                or self._resolve_type(m.return_type))
                    parts.append(f"{base_ret} {base_cname} (...);")
                    _emitted_base.add(base_cname)

    if func_defs or struct_defs:
        parts.append('')

    # Forward decls for cross-module struct methods that may be called —
    # but ONLY for self-hosting compiles (see `_is_selfhost_file` above
    # and BUG-2026-014): these reference gimple_codegen's OWN bootstrap
    # `Parser`/`Interpreter` classes (e.g. Parser_parse_module from
    # mojo_compiler, Interpreter from myinterpreter), whose typedef is
    # only emitted when struct_field_types['Parser'/'Interpreter'] was
    # seeded by that same self-host-only gate. Emitting these
    # unconditionally for an external project with its own same-named
    # (and differently-shaped) Parser/Interpreter struct is exactly the
    # kind of leak that gate exists to prevent — the prototypes below
    # would either reference a type gcc never saw a typedef for
    # ("unknown type name 'Interpreter'") or, worse, silently collide
    # with the external struct's OWN typedef.
    if _is_selfhost_file:
        parts.append("MojoList * Parser_parse_module (Parser *);")
        parts.append("void Parser___init__ (Parser *, MojoList *);")
        parts.append("void Interpreter___init__ (Interpreter *, char *, MojoList *);")
        parts.append("int64_t Interpreter_execute (Interpreter *, int64_t);")
        parts.append("_Bool jit_compile_and_execute (char *, char *, int64_t, int64_t, int64_t);  /* from mojo.py */")
    # Forward decls for the generic reflection dispatch (see the
    # "Generic reflection dispatch" block emitted earlier in this same
    # gen_module call, near the struct alloc helpers) — that block's
    # full definitions land textually AFTER function bodies compiled in
    # an earlier phase (e.g. ast_rewriter.py's _ast_eq/_rewrite_node
    # calling dataclasses.fields()/getattr()/setattr()), so without a
    # declaration visible before those call sites, GCC treats the call
    # as an implicit (and wrong-typed) int-returning declaration.
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
    if gimple_codegen._emitted_type_name_emitted:
        parts.append("static char * _mojo_type_name (int64_t);")
    parts.append('')

    # Forward declarations for lifted closures + env allocator helpers
    # For imported modules (emit_struct_defs=False), emit closure env struct typedefs here
    # (main module emits them inside the emit_struct_defs block above)
    if not self.emit_struct_defs:
        for inner_map in self._all_closures.values():
            for ci in inner_map.values():
                if ci.env_struct and ci.env_struct not in self._emitted_structs:
                    parts.append(f"typedef struct {ci.env_struct} {{")
                    for vname, vtype in ci.captures:
                        # A mutably-captured (`{mut}`-spec) name gets a
                        # pointer field instead of a value copy -- see
                        # ClosureInfo.mut_names.
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
            # Use cached types from Phase 2a if available (more accurate)
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
            # Emit static void* pointer for re.sub callback (avoids &func in GIMPLE)
            if ci.is_re_sub_callback:
                static_name = f"_mojo_cb_{ci.lifted_name}"
                # Regular C (not GIMPLE): valid function→void* assignment
                parts.append(f"static void * {static_name} = (void *){ci.lifted_name};")
    if self._all_closures:
        parts.append('')

    # ── Static function pointer vars for builtins (avoids &func in GIMPLE) ──
    # `_funcptr_builtins_needed`/`_emitted_funcptr_builtins` are shared across
    # every _compile_imported_module temp_gen for the same reason
    # _emitted_ptr_helpers/_emitted_structs are: all modules' generated code
    # is textually concatenated into one translation unit for the self-hosted
    # build, so declaring the SAME `static void * _funcptr_X` twice (once per
    # module that happens to reference builtin X as a bare value) is a real
    # gcc redefinition error, not just wasted output — skip any name this run
    # (or an earlier sub-gen sharing the same sets) already emitted.
    if self._funcptr_builtins_needed:
        _new_names = sorted(self._funcptr_builtins_needed - self._emitted_funcptr_builtins)
        if _new_names:
            for c_name in _new_names:
                # Sanitize name to be valid C identifier (skip casts like ((int)0))
                if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
                    parts.append(f"static void * _funcptr_{c_name} = (void *){c_name};")
                self._emitted_funcptr_builtins.add(c_name)
            parts.append('')

    # ── Dispatch table initializations (from Phase C) ──────────────────
    # Emit static const initializations for all planned dispatch tables
    # Only for main module (same as dispatch solving)
    if self.emit_struct_defs and self._dispatch_solver and self._dispatch_tables:
        parts.append("/* Dispatch table initializations (virtual method tables) */")
        for callee_set, dispatch_table in self._dispatch_tables.items():
            if dispatch_table.name not in self._emitted_dispatch_tables:
                table_init = dispatch_table.emit_table_init()
                if table_init:
                    parts.append(table_init)
                    self._emitted_dispatch_tables.add(dispatch_table.name)
        parts.append('')

    # Function bodies (generated in Phase 2a)
    # Collect string literals from all GimpleGen instances used in Phase 2a
    # and emit them as true global char arrays (required by GIMPLE strict mode)
    str_pool: dict = {}
    for attr in dir(self):
        pass  # self is the GimpleGenModule-level object, not per-function gen
    # Gather _str_pool from all lowering contexts (stored on the module gen)
    if hasattr(self, '_str_pool') and self._str_pool:
        parts.append("/* String literal globals — array form so address is a compile-time r-value (required by GIMPLE strict mode) */")
        if self.emit_str_pool:
            # String pool symbols are TU-local; static avoids duplicate-symbol
            # errors when multiple modules are compiled into the same dylib.
            # Use char* (pointer) not char[] (array): assigning a char[] to a
            # char* temp inside __GIMPLE functions triggers a GCC ICE in convert_move.
            for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                parts.append(f'static char * {sname} = "{escaped}";')
        else:
            # Imported module: emit tentative (uninitialised) declarations.
            # C allows multiple `static T foo;` tentative definitions in one TU;
            # the main module's full `static T foo = "..."` definition wins.
            for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                parts.append(f'static char * {sname};')
        parts.append('')
    # Compile-time-known regex program data (see regex_compile.py,
    # _gen_for_regex_iter, BACKLOG-CODEGEN.md §4f) — one prog/ranges/
    # classinfo/names array set per distinct pattern actually used via
    # `.finditer()`, populated during Phase 2a body generation above.
    # self._regex_progs is a dict SHARED across every recursively-compiled
    # submodule's own GimpleGen instance (see _compile_imported_module),
    # same as _str_pool. Unlike a scalar, these are `static const ARRAY[]
    # = {...}` with a full initializer — C doesn't allow repeating that as
    # a tentative definition the way _str_pool's imported-module branch
    # does for `static char *`. A module can be reached (and therefore
    # have its own gen_module() run this same final-assembly code) via
    # more than one do_imports path (e.g. mojo_compiler.py compiled
    # directly AND via gimple_codegen.py's own `import mojo_compiler`),
    # and the submodule that actually POPULATES an entry (compiling its
    # own .finditer() call in ITS Phase 2a) is also the only one whose
    # own func_parts (right after this point, in ITS OWN returned code
    # string) ever reference it — so gate on "not yet emitted anywhere"
    # (self._regex_progs_defined, shared the same way) rather than on
    # emit_str_pool/root-ness, so it lands in the right submodule's own
    # output, before that submodule's own use of it.
    _regex_new = {p: i for p, i in self._regex_progs.items() if p not in self._regex_progs_defined}
    if _regex_new:
        parts.append("/* Compile-time-compiled regex programs (finditer support) */")
        for pattern, info in _regex_new.items():
            parts.append(info['decls'])
            self._regex_progs_defined.add(pattern)
        parts.append('')
    # Also collect from func_parts generators (they share self._str_pool via gen_func)
    parts.extend(func_parts)

    # Emit class-level attribute initializer (plain C, not GIMPLE; main module only)
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
            # Step C (compiled-path async/await codegen project): this
            # module has at least one compiled `async def` that
            # actually uses `await asyncio.sleep(...)` (or could —
            # emitted unconditionally whenever ANY async function
            # compiled, harmless/unused otherwise, same convention as
            # `_mojogen_sub_guard` just above). `_mojoasync_
            # SleepAwaiter` is a real C++20 awaiter that arms Step A's
            # timer queue (mojo_async_schedule_timer, declared in
            # mojo_async_runtime.h) and genuinely suspends the awaiting
            # coroutine until the timer fires -- field-for-field the
            # same shape as the hand-written `SleepAwaiter` Step A's
            # own test_async_runtime_scaffold.py already proved works
            # end-to-end (see that file's HAND_WRITTEN_MAIN_CPP),
            # reused here as the one real, codegen-emitted awaiter
            # instead of inventing a second, parallel shape (see
            # CLAUDE.md: consolidate, don't duplicate). Emitted by
            # GimpleGen._cpp_stmt's own AwaitExpr case (see there for
            # the ns-conversion + co_await emission).
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
            # Step F (compiled-path async/await codegen project): the
            # ONE real-socket-I/O awaiter this step adds, for `await
            # asyncio.sock_recv(<fd>)` (see _is_asyncio_sock_recv_call's
            # docstring for the API-shape rationale). Reuses Step A's
            # kqueue reactor EXACTLY as it already is
            # (mojo_async_register_read, declared in
            # mojo_async_runtime.h) -- this awaiter is a thin codegen-
            # emitted wrapper around it, not a reimplementation, mirroring
            # `_mojoasync_SleepAwaiter`'s own relationship to Step A's
            # timer queue exactly. `await_ready()` is unconditionally
            # false (same as SleepAwaiter) -- even when `fd` already has
            # data available BEFORE this await runs, kqueue's EV_ADD
            # registration reports an already-ready fd as ready on the
            # very next kevent() call (standard kqueue semantics, no
            # special-cased "check first" logic needed here), so the
            # "already readable" case still correctly resumes on the
            # very next scheduler turn instead of blocking -- see this
            # step's own test for an explicit timing assertion proving
            # that path resumes near-instantly rather than waiting on
            # some later, unrelated event.
            #
            # `await_suspend` only REGISTERS interest and returns to the
            # scheduler -- per the standard reactor pattern (and this
            # project's own Step A design doc), the reactor only tells
            # you WHEN a fd becomes readable, never IF a subsequent
            # read will fully succeed, so the actual `read(2)` syscall
            # happens here, in `await_resume`, once the coroutine has
            # genuinely been resumed by the reactor reporting readiness.
            # Fixed at exactly 1 byte (see _is_asyncio_sock_recv_call's
            # docstring: the smallest useful real transfer for this
            # step's narrow scope) -- a real multi-byte, short-read-safe
            # `nbytes`-parameterized read (looping until `nbytes` bytes
            # are collected, or building a proper buffer/String result
            # type to carry more than one scalar byte across this
            # codegen's still-scalar-only value boundary) is explicitly
            # NOT built here; a short/partial transfer for MORE than one
            # byte is a real possibility future work would need to
            # handle, noted here rather than silently glossed over.
            # Returns int64_t: the byte value read (0-255) on success,
            # -1 on a clean EOF (peer closed / recv() returned 0), or -2
            # on an actual read() error (recv() returned -1) -- three
            # results a single scalar int64_t can distinguish without
            # needing errno plumbed across this boundary too.
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
            # Milestone C step 3: every struct a compiled generator
            # METHOD in this module binds `self` to needs its C layout
            # visible here too (for `self->field` access and for the
            # `self` parameter's own pointer type) — the EXACT same
            # typedef text the .c/.ci output got (see
            # self._struct_typedef_texts' docstring), not a
            # independently-derived copy, so gcc and g++ agree on the
            # struct's layout byte-for-byte. `_cpp_param_struct_names`
            # (bugs/hard/CODEGEN_generator_struct_typed_param_refused.md)
            # is the identical need for a struct accepted as a
            # generator/async function's own PARAMETER type, not just
            # via `self`; `_cpp_ctor_struct_names` is the same need for
            # a struct CONSTRUCTED inside the body (test_doctest.py's
            # `hook = TestHook(pathdir)`) — merged into the same
            # typedef-emission loop below rather than a separate one.
            cpp_parts.append('/* Struct layout(s) needed by this module\'s')
            cpp_parts.append('   compiled generator method(s) -- verbatim copy of')
            cpp_parts.append('   the same typedef(s) emitted into the .c/.ci output. */')
            # Comprehension variable names deliberately avoid the very
            # common `sn`/`_` — gen_module is one gigantic method that
            # this project's OWN self-hosting compiler flattens into a
            # single flat C function (every local across the whole
            # method shares one C declaration namespace by name), and
            # both those names are already used elsewhere in gen_module
            # with a different inferred C type (`sn` as int64_t, `_` as
            # int64_t) — reusing them here as char*/tuple-unpack targets
            # produced real "conflicting types for 'sn'"/"for '_'" GCC
            # errors under `make check-selfhost`, confirmed and fixed by
            # this rename (see CLAUDE.md's self-host quality gate).
            # Plain for-loop building a plain list (not a set/dict-key-
            # tuple-unpacking comprehension) — see the analogous rename/
            # rewrite a little further up (`_gen_only_names`/etc.) for
            # why: this project's self-hosting compiler mis-typed a
            # near-identical comprehension shape here too (confirmed via
            # `make check-selfhost`), so the same defensive plain-loop
            # style is used for consistency, not just to fix one spot.
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
            # Transitive closure over struct-pointer-typed FIELDS: a
            # struct pulled in above (test_doctest.py's `TestHook`) can
            # itself have a field typed as ANOTHER struct pointer
            # (`self.importer = TestImporter()` — a plain, no-`var`-
            # annotation instance attribute, so struct_field_types
            # infers its real constructed type, `TestImporter *`, same
            # as any other field) — that struct's own typedef needs to
            # be visible in this .cpp TU too, or the outer struct's
            # field declaration itself fails to compile ("'TestImporter'
            # does not name a type"). BFS rather than one flat pass:
            # the pulled-in struct can itself reference a THIRD struct
            # the same way, arbitrarily deep.
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
            # Forward-declare every struct tag in this closure BEFORE
            # any of their full typedefs below — `sorted()` order
            # (alphabetical, e.g. "TestHook" before "TestImporter")
            # doesn't necessarily match the dependency order a pointer
            # FIELD needs (TestHook's own typedef, emitted first
            # alphabetically, has a `TestImporter *importer;` field —
            # C++ requires `TestImporter` to at least name a type by
            # that point). A plain forward `struct Name;` ahead of time
            # (legal C++, later redefined by the real `typedef struct
            # Name {...} Name;`) sidesteps needing real dependency-
            # order sorting entirely.
            for _gm_fwd_sn in sorted(_gm_struct_names_seen):
                if _gm_fwd_sn in self._struct_typedef_texts:
                    cpp_parts.append(f'struct {_gm_fwd_sn};')
            if any(_fwd in self._struct_typedef_texts for _fwd in _gm_struct_names_seen):
                cpp_parts.append('')
            for _gm_method_struct_name in sorted(_gm_struct_names_seen):
                _td = self._struct_typedef_texts.get(_gm_method_struct_name)
                if _td:
                    # `_Bool` is a valid C99 type but NOT a valid C++
                    # type name (`bool` is) — the .ci side keeps `_Bool`
                    # (it genuinely is C); this .cpp copy must spell it
                    # `bool` (ABI-identical, 1 byte, same representation).
                    # The struct's own field types can legitimately be
                    # `_Bool` because the same typedef is emitted into the
                    # .ci/.c output (see the `_struct_typedef_texts`
                    # docstring's "verbatim copy" comment above — that
                    # verbatim-ness is about the SHAPE of the struct, not
                    # this one type-name spelling, which must differ per
                    # language exactly like _c_to_cpp_scalar_type already
                    # does for every other `_Bool` in the .cpp text).
                    cpp_parts.append(_td.replace('_Bool', 'bool'))
                    cpp_parts.append('')
        # Module-level symbols referenced by compiled generator bodies
        # (see _cpp_expr's IdentExpr/CallExpr resolution): module globals
        # need the module globals-struct typedef + extern instance (read
        # as `_{module}_globals.<name>`), module functions need their
        # mangled-C-symbol extern declaration — both in THIS .cpp TU,
        # since it's compiled standalone and linked against the .ci's
        # object (the generator body can't see the .c side's own
        # declarations). Emission is opportunistic: a referenced name
        # that isn't actually a known module global/function is skipped
        # silently (the generator-body emitter only ever records a name
        # it already confirmed exists in the corresponding dict).
        if self._cpp_module_global_refs or self._cpp_module_func_refs:
            cpp_parts.append('/* Extern declarations for module-level symbols')
            cpp_parts.append('   referenced by this module\'s compiled generator')
            cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
            # Plain loops, NOT a set-comprehension with tuple-unpacking
            # (`{m for m, _ in ...}`): this project's OWN self-hosting
            # compiler has no clean translation of that shape — it
            # lowered it to a GIMPLE `int64_t m, _;` multi-declaration
            # that collided with gen_module's own `_` declarations
            # ("redeclaration of '_' with no linkage", caught by
            # `make check-selfhost`). See the identical note a few
            # hundred lines up in gen_module for the same class of bug.
            _mref_modules: list = []
            for _mref_pair in self._cpp_module_global_refs:
                _mref_mod = _mref_pair[0]
                if _mref_mod not in _mref_modules:
                    _mref_modules.append(_mref_mod)
            for _mref_safe_mod in sorted(_mref_modules):
                _mt = f"_{_mref_safe_mod}_toplev"
                _mg = f"_{_mref_safe_mod}_globals"
                # The full struct typedef (field-by-field, matching the
                # .ci side's own globals struct — see Phase 1.7/2b's
                # `_module_globals` emission) so field reads like
                # `_root_globals.sys` compile; a forward-declared struct
                # alone would leave the instance incomplete. Field names
                # that are valid in C but are C++ keywords (`operator`,
                # `new`, ...) are escaped `_kw_<name>` — the .ci side can
                # keep the raw name (it genuinely is C), this .cpp copy
                # cannot (see the `_Bool`→`bool` spelling fix above: the
                # struct SHAPE is identical, only C++-invalid spellings
                # differ).
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
            # Unmangled module-level functions (os.py's fspath): the .ci
            # declares them `int64_t <name> (...);` — mirror that exact
            # variadic extern in the .cpp so a generator body calling
            # `fspath(top)` compiles (calls go through the same variadic
            # symbol, ABI-identical to the .ci side's own extern).
            for _vfn in sorted(self._cpp_module_variadic_func_refs):
                cpp_parts.append(f'extern "C" int64_t {_vfn} (...);')
            cpp_parts.append('')
        if self._cpp_class_attr_refs:
            # Class-level-attribute globals read via `cls.<attr>` in a
            # compiled @classmethod generator body (`_cpp_expr`'s
            # MemberExpr `cls.<attr>` case / `self._cpp_class_attr_
            # refs`) — declared extern here for the SAME "standalone
            # .cpp TU" reason as the module-global refs just above:
            # the real C variable is DEFINED once in the .c/.ci side
            # (`_gen_toplevel`'s "Global variable declarations" pass,
            # which seeds every `self._class_attrs[...]` mangled name
            # into `self._global_var_types` at Phase-1-ish time — see
            # that class-attr-collection pre-pass's own comment), never
            # in this .cpp TU. Uses the SAME real (non-int64_t-boxed)
            # pointer-ish C type that pass gives a container-valued
            # class attribute (`MojoDict *`/`MojoList *`/`MojoSet *`/
            # `char *`) — `self._global_var_types` (not `_global_c_
            # decl_types`, which is only ever populated for OTHER
            # kinds of globals, never for this mangled `_classattr_`
            # name) is already that class attr's authoritative
            # declared type; a class attr this codegen doesn't
            # recognize as a container/scalar type defaults to
            # `int64_t`, matching the .c side's own identical default
            # for an unrecognized global.
            cpp_parts.append('/* Extern declarations for class-level')
            cpp_parts.append('   attribute globals (`cls.<attr>`) read by this')
            cpp_parts.append('   module\'s compiled generator bodies. */')
            for _cattr_gname in sorted(self._cpp_class_attr_refs):
                _cattr_ctype = self._global_var_types.get(_cattr_gname, 'int64_t')
                _cattr_ctype = _cattr_ctype.replace('_Bool', 'bool')
                cpp_parts.append(f'extern {_cattr_ctype} {_cattr_gname};')
            cpp_parts.append('')
        if self._cpp_struct_method_refs:
            # Struct methods called from a compiled generator/async body
            # on `self` or a non-self struct-pointer-typed local (see
            # _cpp_struct_method_refs' own declaration comment and
            # bugs/hard/CODEGEN_generator_struct_typed_param_refused.md)
            # — declared extern "C" here exactly like a free function's
            # own declaration just above, using the SAME mangled-symbol/
            # signature lookup _struct_method_csym already populates for
            # the ordinary (non-generator) GIMPLE-compiled method.
            cpp_parts.append('/* Extern declarations for struct methods')
            cpp_parts.append('   called from this module\'s compiled generator')
            cpp_parts.append('   bodies (compiled standalone, linked with the .ci). */')
            for _sm_struct, _sm_method in sorted(self._cpp_struct_method_refs):
                try:
                    _smsym = self._struct_method_csym(_sm_struct, _sm_method, '')
                    _smkey = f"{_sm_struct}_{_safe_name(_sm_method)}"
                    _smret = self.func_return_types.get(
                        _smsym, self.func_return_types.get(_smkey, 'int64_t'))
                    _smparams = self.func_param_types.get(
                        _smsym, self.func_param_types.get(_smkey, [f"{_sm_struct} *"]))
                    _smret_cpp = _smret.replace('_Bool', 'bool')
                    _smparam_str = ', '.join(
                        p if p != '_Bool' else 'bool' for p in _smparams)
                    cpp_parts.append(
                        f'extern "C" {_smret_cpp} {_smsym} ({_smparam_str});')
                except Exception:
                    continue
            cpp_parts.append('')
        for unit in self._generator_cpp_units:
            cpp_parts.append(unit)
            cpp_parts.append('')
        self.generated_cpp = '\n'.join(cpp_parts)

    return self._dedup_variadic_externs(parts)


def __getattr__(name):
    import gimple_codegen as _gc
    return getattr(_gc, name)
