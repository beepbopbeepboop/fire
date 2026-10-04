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
from mojo.middle.types import _BUILTIN_RET_CTYPES  # underscore name: `import *` won't carry it
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
# `_resolved_export_entry` — `from X import *` skips underscore names, and
# `_register_sym` needs it to give a re-exported function's registered
# signature the DEFINING module's real one instead of the export text scan's
# parameter-less placeholder. It is NOT imported here or at its use site: like
# the re-export-hop WALK beside it, it needs `gen`, so it is reached as the
# `GimpleGen` method `gen._resolved_export_entry` — the same shape as
# `gen._find_symbol_home_module` and `gen._parsed_import`.
#
# Not importing it at all is also what makes the self-hosted closure compile.
# The one `from mojo.middle.funcs_shared import _resolved_export_entry` this
# used to carry, at `_register_sym`'s one call, registered the name in THAT
# module's `imported_symbols`, and `imported_symbols` is per-gen while
# `inline_defined` — the preamble's "this TU defines it, so do not declare it
# again" set — is built from TOP-LEVEL imports only. So the same symbol that
# `emit_funcs`' top-level `from mojo.middle.funcs_shared import ...` correctly
# suppresses here escaped the suppression, and the text scan's declaration of
# it reached the file beside the definition it contradicts:
#
#   mojo/middle/module_shared.py:561: error: too many arguments to function
#     'mojo_middle_funcs_shared__resolved_export_entry_ee1b12'; expected 2,
#     have 4
#   mojo/middle/funcs_shared.py:507: error: conflicting types for the same
#     symbol; have 'int64_t(GimpleGen *, char *, char *, int64_t)'
#
# Two is the scan's arity, not the definition's: the def annotates two of its
# four params and `module_loader._scan_source` DROPS an unannotated one, and
# nothing in the scan can type a leading `gen` as `GimpleGen *` at all — so
# the scan cannot be made to agree, and a `name (...)` fallback cannot either
# (gcc rejects a prototype against a later full one). Removing the import
# removes the declaration instead, which is the fix.
#
# `funcs_shared` reaches `gimple_codegen`, which reaches the gimple backend,
# which reaches `funcs_shared` again, so a top-level import in BOTH middle
# modules closes a cycle. Whichever of the two the process happened to
# reach first then died with `ImportError: cannot import name ... from
# partially initialized module`, and the measured victim was the formal
# build path, which enters through `reflect` -> `gimple_codegen` and has no
# other way in: `formal/model.py` `runtime_abi` -> ... ->
# `mojo/backend_gimple/emit_funcs.py` -> here. The direction that stays
# top-level is `funcs_shared` -> `gimple_codegen`; every edge back down
# into the middle tier is at its use site, so importing EITHER middle module
# first works. See `funcs_shared._struct_method_qualifier._sanitize_qualifier`
# for the same rule on the other side.
# Closure-scan leaf helpers live in mojo/middle.closures (formal + gimple
# share one copy; closures must not import this module — it pulls gimple_codegen).
from mojo.middle.closures import (
    _gmi_all_stmts_nonfunc, _selfhost_fn_reassigns_method,
)
import gimple_codegen  # constants used by some extracted helpers
from gimple_codegen import _selfhost_impl_py_files
from mojo.middle.funcs_shared import _selfhost_parsed_source
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

def _selfhost_parsed_modules(sd: str) -> list:
    """`[(path, stmts)]` for every compiler implementation source under `sd`,
    tokenized, parsed and rewritten EXACTLY ONCE per process and shared by
    all three `_selfhost_*` seed passes below.

    Those three passes (`_selfhost_module_scalar_globals`,
    `_selfhost_struct_dict_field_val_types`,
    `_selfhost_homogeneous_tuple_ret_funcs`) each independently did
    `py_tokenize` + `parse_module` + `ast_rewriter.rewrite` over
    substantially the same file list, and each cached its RESULT under its
    own key (`'k'` / `'sdfvt'` / `'httrf'`). Because the three caches hold
    three results rather than three views of one, the same source was
    tokenized and parsed three times AND all three AST copies stayed live
    for the life of the process. That is both the repeated work and a
    contributor to the never-frees accumulation measured in
    `bugs/CODEGEN_bootstrap_resource_blowup.md`: one shared parse is ~1/3
    the instructions and ~1/3 the retained AST nodes.

    The cache is keyed PER FILE on `(path, mtime)`, not on the whole file
    list. A whole-list key means editing one file re-parses all 43 and
    invalidates the other two passes wholesale; a per-file key means one
    file is re-read and the other 42 are reused by all three passes, which
    is the behaviour the callers actually want (the three lists differ —
    `_selfhost_module_scalar_globals` covers a superset — so a whole-list
    key could never be shared between them anyway).

    The per-file cache and its string key live in
    funcs_shared._selfhost_parsed_source (shared with the fn-index and
    extra-field scans). A file that fails to parse is cached as a FAILURE and
    contributes an empty statement list.
    """
    _files = sorted(_selfhost_impl_py_files(sd)
                    + [os.path.join(sd, n) for n in
                       ('fire_compiler.py', 'module_loader.py', 'monomorphize.py',
                        'ast_rewriter.py', 'imports.py', 'generated_dispatch.py',
                        'reflect.py', 'mlir.py', 'regex_compile.py', 'cas.py',
                        'elaborate.py', 'myinterpreter.py')])
    _out: list = []
    for _f in _files:
        if not os.path.isfile(_f):
            continue
        _out.append((_f, _selfhost_parsed_source(_f)))
    return _out

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
    # Home-side C-decl for a container module global is `int64_t` (boxed)
    # UNLESS it is one of gen_module_impl's hardcoded dispatch tables (which
    # get a bare `MojoDict *` / `MojoSet *` field). Skip those names so the
    # pre-seed can never disagree with the home's field/accessor type.
    # Derived from the module that DEFINES them rather than written out here.
    # This list used to name the globals of `gimple_codegen.py`, which is where
    # they lived before the split into `mojo/middle/` + `mojo/backend_gimple/`;
    # `_TYPE_MAP` moved to `types.py` and several others with it, so a
    # hand-kept list silently stopped covering them and every consumer of a
    # moved dispatch table then found no cdecl entry -- "struct
    # _mojo_middle_types_toplev has no member named '_TYPE_MAP'".
    #
    # `dispatch_table_global_ctype` in `mojo.middle.types` is the ONE table,
    # and both this skip and `gen_module_impl`'s declaration sites read it.
    # `... is not None`, not `set(<the table>)`: `set()` over a module-level
    # container is a shape the self-hosted compiled path gets wrong (a
    # module-level `set(<tuple literal>)` lowers to a value `len()` cannot
    # take, "passing argument 1 of 'mojo_list_len' makes pointer from integer
    # without a cast"), and membership is all this skip ever wanted from it.
    _dispatch_only = gimple_ctypes.dispatch_table_global_ctype
    _out: dict = {}
    for _f, _stmts in _selfhost_parsed_modules(sd):
        _mod = _selfhost_module_name_for_path(sd, _f)
        for _s in _stmts:
            if not (isinstance(_s, AssignStmt) and isinstance(_s.target, IdentExpr)):
                continue
            _n, _v = _s.target.name, _s.value
            if _n in _out or _dispatch_only(_n) is not None:
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
    _out: dict = {}
    for _f, _stmts in _selfhost_parsed_modules(sd):
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

    for _f, _stmts in _selfhost_parsed_modules(sd):
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
    return _out

# Constants a MODULE MARKER exports that this compiler knows BY VALUE rather
# than by compiled module body. `os` and `signal` are markers, never inlined
# into the translation unit (their bodies are not part of any program's
# closure the way a `from . import sibling` sibling's is), so there is no
# `_module_globals['os']` field to read and no emitted struct to name — the
# per-module field lookup that every other `mod.CONST` read answers through
# (see `GimpleGen._module_global_field_type`) legitimately has nothing to say
# about these two. These values are fixed by the OS ABI and by os.py's own
# literals, so emitting them directly is not a guess.
#
# One table, because two backends read the same `os.linesep`: the ordinary
# GIMPLE path's `_lower_MemberExpr` and the coroutine C++20 emitter's
# module-constant read. Kept as two near-identical literal dicts, the
# disagreement was invisible until the second reader existed and then produced
# a SILENT wrong answer rather than an error — the coroutine emitter stubbed
# `os.linesep` to `0` (an empty string) while the ordinary path in the same
# program read `'\n'`, and the only thing that kept the coroutine body off
# the compiled path was the mixed-yield refusal that difference caused
# (bugs/COMPILE_FAIL_Tools_c-analyzer_c_common_scriptutil.md).
#
# The POSIX-only half of `signal` is deliberate: only the numbers identical
# across every POSIX platform this runtime targets are listed, so a
# BSD/Linux-only member (`SIGUSR1`, `SIGCHLD`, ...) keeps the honest
# unresolved-attribute answer rather than risking a wrong number.
_BUILTIN_MODULE_CONSTANTS = {
    'os': {
        'sep': ('char *', '/'),
        'pathsep': ('char *', ':'),
        'curdir': ('char *', '.'),
        'pardir': ('char *', '..'),
        'linesep': ('char *', '\n'),
    },
    'signal': {
        'SIGHUP': ('int64_t', 1),
        'SIGINT': ('int64_t', 2),
        'SIGQUIT': ('int64_t', 3),
        'SIGILL': ('int64_t', 4),
        'SIGABRT': ('int64_t', 6),
        'SIGFPE': ('int64_t', 8),
        'SIGKILL': ('int64_t', 9),
        'SIGSEGV': ('int64_t', 11),
        'SIGPIPE': ('int64_t', 13),
        'SIGALRM': ('int64_t', 14),
        'SIGTERM': ('int64_t', 15),
    },
}


def builtin_module_constant(module: str, name: str) -> tuple[str, object] | None:
    """`(ctype, value)` for a constant `module` exports that this compiler
    knows by value — `os.linesep` is `('char *', '\\n')`, `signal.SIGTERM` is
    `('int64_t', 15)` — or None when it knows of no such constant.

    `module` is the CANONICAL (import-resolved) module name, so an
    `import os as _os` alias resolves the same as a bare `os`.

    Both readers are in this file's `bugs/` and neither can be a second
    implementation: see `_BUILTIN_MODULE_CONSTANTS`'s own comment for the
    silent-wrong-answer failure the duplication produced. The VALUE is
    returned unconverted so each backend can put it through its own literal
    spelling (`_intern_string`/`_c_escape` for the GIMPLE path's string pool,
    a C++ literal for the coroutine path's text) and neither has to reach
    through the other.
    """
    return _BUILTIN_MODULE_CONSTANTS.get(module, {}).get(name)


def builtin_module_constant_names(module: str) -> tuple:
    """The `name`s `builtin_module_constant` knows for `module` — for the
    callers that need the whole set rather than one lookup (the coroutine
    emitter builds its per-unit `"<marker>.<name>" -> ctype` map by walking
    markers, so it must be able to ask which names exist without holding a
    second copy of the keys)."""
    return tuple(_BUILTIN_MODULE_CONSTANTS.get(module, {}).keys())


def module_qualifier(q) -> str:
    """The ONE module-string -> C-qualifier sanitization every cross-module
    registry key and symbol prefix in this codegen must agree on.

    Every one of these keys is written by ONE half of the compiler and read
    by the OTHER (a defining module registering its own signature/struct/-
    generator under a `(home, name)` key; an importing module looking that
    same key up to mangle its call site to the same symbol). Two internally
    consistent but MUTUALLY DISAGREEING spellings of one module therefore
    do not fail loudly — they make a lookup MISS, and a miss silently
    falls through to a worse tier (the shared bare-name slot, all-int64_t
    param types) whose overload hash then differs from the definition's,
    producing `implicit declaration of function '<name>_<suffixA>'; did you
    mean '<name>_<suffixB>'?` at g++ time.

    That is exactly what happened for every module whose name carries a
    leading depth dot AND an underscore of its own — the overwhelmingly
    common `from . import _common` / `from ._regexes import ...` shape.
    The leading-dot strip is load-bearing, NOT cosmetic:
      `'._common'` -> lstrip-then-substitute -> `_common`   (correct)
                   -> substitute-only        -> `__common`  (a key nothing
                                                     will ever look up)
    `._regexes` happens to agree under both (`_regexes` either way), which
    is why the bug read as "sometimes it works" rather than "always
    broken".

    Callers that additionally need the per-compile `_inline_module_qualifiers`
    remap keep doing that lookup themselves (it needs a `gen`; this is a pure
    string function on purpose, so both the reference side and the defining
    side can call it without one).

    Consolidated out of four near-identical private copies
    (`_func_qualifier._sanitize_qualifier`,
    `_struct_method_qualifier._sanitize_qualifier`,
    `_cpp_sanitize_module_qualifier`, and the inline chain in `_local_def_pts`
    / `_imported_def_pts`), two of which omitted the lstrip. One
    implementation, so the halves cannot drift again.
    """
    if not q:
        return q
    return q.lstrip('.').replace('.', '_').replace('-', '_')


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
    # `from M import Class as Alias`: the export table carries no class
    # exports at all (module_loader only emits function and global_var
    # entries), so `sym_info` is empty and the alias would otherwise land
    # in `_unresolved_import_aliases` with nothing recorded. Recorded
    # BEFORE the falsy-`sym_info` bail below so the constructor dispatch
    # can still resolve the name; the alias map is deliberately NOT
    # `imported_symbols`, which every reader treats as "a function I can
    # emit an `extern` for" (see module_gen.py's re-export preamble).
    if not s.wildcard:
        self._note_struct_import_alias(s.module, _sk, orig_name)
    # `from REEXPORTER import name`, where `REEXPORTER` only RE-EXPORTS
    # `name` from somewhere else — the standard package layout
    # (`p/__init__.py` doing `from .sub import tri`). The export table
    # `load_module`/`_local_sibling_module_exports` builds is a TEXT scan of
    # the module the statement NAMES, and a re-exporting `__init__.py`
    # contains no `def` at all, so `sym_info` is empty and the import used
    # to die in the `_unresolved_import_aliases` bail immediately below —
    # nothing recorded, and the call site bound to the extern preamble's
    # `weak` "unavailable in compiled mode" stub instead of the real
    # definition (link mode) or failed to resolve outright. Follow the
    # re-export hops and take the DEFINING module's own export entry,
    # which is the entry the definer's C symbol was built from.
    #
    # Gated on `not sym_info` so the ordinary case (the named module does
    # define the function) does no extra work at all, and on the resolver
    # answering, so a name nothing reachable defines keeps today's exact
    # behaviour — including the `_unresolved_import_aliases` bail. Every
    # use of `s.module` BELOW is `_eff_mod` for the same reason: the
    # registered entry's `module`, the sibling param resolution and the
    # param-ctype snapshot all have to name the module that actually
    # defines the symbol, not the one it was re-exported through, or each
    # of them looks the answer up under a key nothing ever wrote.
    _eff_mod = s.module
    # Gated on the bail this is rescuing, NOT on `not sym_info` alone. An
    # import that DID resolve is already registered correctly by the pass
    # that owns it (`_emit_stdlib_import_externs` for a stdlib/test module),
    # and re-pointing its recorded module changes the emitted symbol's
    # spelling and whether it is overload-mangled at all — measured: with
    # the wider gate, `from std.memory import alloc` stopped being the bare
    # `extern int64_t alloc (...)` the stdlib dylib's own export table
    # advertises and became a mangled `std_memory_alloc_alloc_9f63a2
    # (int64_t layout)`, and four stdlib modules then failed with
    # `implicit declaration of function 'mojo_memset'` (32 sites) plus a
    # spurious `unsafe_memcpy: unavailable in compiled mode` weak stub.
    # The narrower gate below can only ever REPLACE an abandoned import
    # with a resolved one, so it cannot demote a name that already worked.
    if _sib_qualifier and not sym_info and not s.wildcard:
        _home_fn = self._find_symbol_home_module(s.module, orig_name, 'fn')
        if _home_fn and _home_fn != s.module:
            # The ABSOLUTIZED ref for opening the file: a relative spelling
            # (`.alloc`, from a re-exporting `__init__.py`) resolved
            # against THIS importing module is a different file as soon as
            # the chain is more than one level deep, and the export lookup
            # would then silently consult the wrong module's source.
            _home_abs = self._find_symbol_home_module(s.module, orig_name, 'fn',
                                                      want_abs=True) or _home_fn
            _hexp = None
            _hqual = None
            try:
                _hexp, _hqual = self._local_sibling_module_exports(_home_abs)
            except Exception:
                _hexp = None
            if _hexp is None:
                try:
                    import module_loader as _mlmod_reexp
                    if _mlmod_reexp.can_resolve_module_path(_home_abs):
                        _hexp = load_module(_home_abs)
                except Exception:
                    _hexp = None
            _hinfo = _hexp.get(orig_name) if _hexp else None
            if _hinfo:
                # Adopt the defining module ONLY now, when its own exports
                # really have this name. Adopting it on the strength of the
                # hop alone (with those exports still empty) also adopted
                # `_hqual`, and that flipped the `_sib_qualifier and not
                # sym_info` bail below ON for names that used to fall
                # through to `_emit_stdlib_import_externs`' stdlib
                # registration — so the symbol lost its `extern` entirely
                # and its call site emitted a call to nothing. Measured
                # across the stdlib dylib build: `implicit declaration of
                # function 'mojo_memset'`, 32 sites in 4 modules, plus a
                # spurious `unsafe_memcpy: unavailable in compiled mode`
                # weak stub that had not been emitted before.
                _eff_mod = _home_fn
                # Through the DEFINING module's own parsed signature, not
                # the text scan's: this entry is re-emitted as an `extern`
                # for a symbol this translation unit does not define (the
                # re-exporting module has no definition to skip it for), so
                # the scan's parameter-less `int64_t tri (void)` for an
                # unannotated `def tri(x)` would become the only prototype
                # in the file and reject its own call site. See
                # `_resolved_export_entry`.
                # Reached as a `GimpleGen` method, not imported at this use
                # site: the module-scope comment above gives both reasons.
                sym_info = self._resolved_export_entry(_eff_mod, orig_name,
                                                       _hinfo)
                if _hqual:
                    _sib_qualifier = _hqual
    if _sib_qualifier and not sym_info:
        if not s.wildcard:
            self._unresolved_import_aliases.add(_sk)
        return
    if isinstance(sym_info, str):
        # One writer for the three tables, shared with the bare-`import`
        # module-qualified call site (see
        # `funcs_shared.register_imported_symbol`), which has the same three
        # writes to do and used to have no writer to call. The
        # `original_name` rule lives there too: only a genuine
        # `import X as Y` alias records it, because storing it for an
        # unaliased import makes `_func_csym` read it back (MojoDict get ->
        # int64_t, then a POINTER `!=` against `bare_name` that is always
        # true on the self-hosted path) take its alias branch ->
        # `_safe_name(<erased ptr>)` -> a decimal-address guard name
        # (`#ifndef _Users_..._<addr>`), different every run. This str branch
        # used to record it unconditionally, which is that bug.
        self._register_imported_symbol(
            _sk,
            {'module': _eff_mod, 'original_name': orig_name,
             'return_type': sym_info, 'parameters': [],
             'signature': f"{sym_info} {_sk} (void)"},
            orig_name)
    elif isinstance(sym_info, dict):
        sym_info = _as_dict(dict(sym_info))
        sym_info['module'] = _eff_mod
        _ret_changed = False
        if orig_name.startswith('_'):
            pass
        elif _sib_is_local_project and sym_info.get('return_type'):
            _resolved_ret = self._resolve_sibling_param_ctype(
                _eff_mod, sym_info['return_type'])
            if _resolved_ret:
                sym_info['c_return_type'] = _resolved_ret
                _ret_changed = True
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
                    _eff_mod, _p_raw_type)
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
        # `_sib_qualifier` decides the param types and nothing else: when
        # THIS compile will emit the definition, the definition's own
        # signature is authoritative and a second entry here is what a stale
        # cross-module hint would read instead.
        self._register_imported_symbol(_sk, sym_info, orig_name,
                                       write_param_types=bool(_sib_qualifier))
    if _sib_qualifier and sym_info:
        # The condition is "will THIS compile emit that module's own
        # definition into this translation unit?", NOT `do_imports`. Two
        # modes inline modules and they must spell the qualifier the same
        # way, because the qualifier is half of a mangled symbol and the
        # two halves come from two different code paths:
        #   * the DEFINITION's half comes from the inline-compile loop's
        #     own module key (`modules_to_compile`), which is the IMPORT
        #     STRING — `p.sub` for `from p.sub import tri` (gen_module_impl
        #     now runs that one shared loop for link mode too, so
        #     link-mode definitions are keyed the same way);
        #   * the CALL SITE's half is what is computed here.
        # `do_imports`-only let link mode fall to the `else` and use
        # `_local_sibling_module_exports`' path-derived qualifier, which is
        # `module_name_for_path`'s BASENAME — `sub` for `p/sub.py`. The two
        # halves then disagreed on a DOTTED module name: the call site
        # emitted `sub_tri_<suffix>` against a definition emitted as
        # `p_sub_tri_<suffix>`, a hard "implicit declaration of function
        # 'sub_tri_...'; did you mean 'p_sub_tri_...'?" — the same class of
        # divergence the comment below records fixing for the RELATIVE
        # spelling, and the same requirement the inline loop keys its own
        # registration by. Measured: `from p.sub import tri` in a package
        # sibling.
        #
        # Restricted to the modules link mode actually INLINES
        # (`_link_inline_modules`, filled by Phase 0's
        # `_register_link_imports` for exactly the imports with no dylib to
        # link against) rather than to every `link_imports` compile, so a
        # module that IS satisfied by a recorded dylib keeps the
        # path-derived spelling the dylib's own export table used.
        if self.do_imports or s.module in self._link_inline_modules:
            # `lstrip('.')` is LOAD-BEARING and was missing here, making this
            # the single outlier among five call sites that mangle a module
            # string into a C symbol prefix (compare
            # funcs_shared.py:376, :602 and :830, and
            # emit_resolve.py's `_module_key`, which all strip). Without it a
            # RELATIVE import's leading depth dot was itself turned into an
            # underscore, so the call site's prefix gained an underscore the
            # definition side never had:
            #
            #   `from ._itertools import only`  (CPython's
            #   Lib/importlib/resources/readers.py:15)
            #     here        : '._itertools' -> '__itertools'  (dot + the
            #                   module's OWN leading underscore)
            #     definition : '_itertools'   (leading dot dropped, the
            #                   module's own underscore kept)
            #   => call site emitted `__itertools_only_37bd8e(...)` against a
            #      definition emitted as `_itertools_only_37bd8e(...)`:
            #      `implicit declaration of function '__itertools_only_...'`
            #      for every such import. Same root cause and same class as
            #      the struct-side divergence fixed at funcs_shared.py:830
            #      (bugs/CODEGEN_link_mode_from_submodule_import_symbol_value
            #      _call_segfault.md) — this function was simply missed by it.
            #
            # The key this writes is `_pair_key(_qual, _sk)` in
            # `_imported_home_param_types` and the arg to
            # `_note_own_func_home`, i.e. the "which module defines this
            # symbol" half of the mangled name — and the comment immediately
            # below states that requirement in as many words ("the qualifier
            # half and suffix half of one mangled symbol always mean the
            # same binding", "the DEFINITION side's exact resolver"). A
            # qualifier derived from the import STRING cannot honour that;
            # only the module_name the defining module was itself compiled
            # under can.
            #
            # "The module the defining module was compiled under" is NOT
            # always the module this statement names: a package
            # `__init__.py` that re-exports (`from .sub import tri`) is a
            # re-exporting module, not a defining one, so `from p import
            # tri` was qualifying by `p` against a definition emitted as
            # `sub_tri_<suffix>` — a hard gcc "implicit declaration of
            # function 'p_tri_...'; did you mean 'sub_tri_...'?" on the
            # single-TU path, and a silent wrong answer on the link-mode
            # one (the extern preamble's `weak` "unavailable in compiled
            # mode" stub binds instead). Worse than the wrong symbol: the
            # same wrong qualifier is the `_home_def_param_types` /
            # `_imported_home_param_types` lookup key beside it, so a
            # mismatch there is a mis-TYPED result rather than a
            # compile error — that is how a re-exported CLASS loses its
            # field types (`from mod_root import Dialog` typed
            # `Dialog.widgetName` `int64_t` and printed the `char *`'s
            # bits). `_find_symbol_home_module` answers the question this
            # half is actually asking ("which module DEFINES this name,
            # following re-export hops"), with the visited-set that makes
            # a re-export cycle terminate. A None answer (nothing
            # resolvable defines it) falls back to the import string
            # unchanged — no worse than before, and never a guess.
            # `_eff_mod` already IS the defining module when the name only
            # REACHES `s.module` through a re-export (resolved above);
            # otherwise this statement names the defining module directly and
            # the import string is the right spelling.
            _home_ref = _eff_mod if _eff_mod != s.module else None
            if _home_ref:
                _qual = (_home_ref.lstrip('.').replace('.', '_')
                         .replace('-', '_'))
            else:
                _qual = (s.module.lstrip('.').replace('.', '_')
                         .replace('-', '_'))
        else:
            # Same requirement, opposite spelling: a module satisfied by a
            # recorded dylib keeps the PATH-derived qualifier, because that
            # is what the dylib's own export table used. When the symbol
            # only REACHES this module through a re-export, the defining
            # module is a different file, so re-derive the basename from
            # the DEFINING module's path instead of the importing one's.
            _qual = _sib_qualifier
            _home_ref = _eff_mod if _eff_mod != s.module else None
            if _home_ref:
                try:
                    _hp = self._parsed_import(_home_ref)[0]
                    if _hp:
                        import module_loader as _mlmod_home
                        _qual = _mlmod_home.module_name_for_path(_hp)
                except Exception:
                    pass
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
            for _fs in (self._parsed_import(_eff_mod)[2] or []):
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
    annotated per the hoist GOTCHA.

    Records, per CONTAINER, the element C type of every value appended to
    it anywhere in this module. The consumer
    (`gen_module_impl`'s `_phase17_append_hits` loop) keys the answer on a
    module GLOBAL's name, which is what makes the conclusion function-
    independent: a registry populated by a constructor and read by a
    different function is exactly the case this exists for, and the two gaps
    named below are that case failing — with the whole of the observable
    damage being a downstream method call on an element that read back as
    `int64_t`.

    Two receivers reach a module-level container, and only one of them was
    recognised:

    * `REGISTRY.append(x)` — a bare global name. Handled by the
      `IdentExpr` test below, in every nesting kind this walks.
    * `T.registry.append(x)` — a CLASS ATTRIBUTE, which reads as
      `MemberExpr(obj=IdentExpr('T'), member='registry')` and is stored as
      the synthesized `_classattr_T__registry` global
      (`_class_attrs[T]['registry']`). The `IdentExpr` test rejected it, so
      a class-level registry never recorded its element type and
      `T.registry[0].method()` degraded to an `int64_t` receiver stub —
      a pointer-sized decimal, exit 0.

    And one NESTING kind reached nothing: the walk below descends into
    `FunctionDef`, `IfStmt`, `WhileStmt`/`ForStmt`, `TryStmt` and
    `WithStmt`, but not `StructDef`, so an append inside a constructor —
    the overwhelmingly common registry shape — was invisible to the whole
    pass. `self` is seeded as `<Struct> *` so `_quick_type` on the appended
    argument resolves the same way it does in every other method.
    """
    for _n in _node_list:
        if (isinstance(_n, ExprStmt)
                and isinstance(_n.value, CallExpr)
                and isinstance(_n.value.func, MemberExpr)
                and _n.value.func.member == 'append'
                and len(_n.value.args) == 1):
            _p17_recv = None
            if isinstance(_n.value.func.obj, IdentExpr):
                _p17_recv = _as_str(_n.value.func.obj.name)
            elif (isinstance(_n.value.func.obj, MemberExpr)
                    and isinstance(_n.value.func.obj.obj, IdentExpr)):
                # `Cls.NAME.append(x)` — resolve the class attribute to the
                # `_classattr_<Cls>__<name>` global the class-attribute
                # registration pass synthesizes, so the key this records is
                # the same one that pass's consumer looks up. Plain
                # `.name` access, NOT a dict lookup with a `None` default:
                # `_class_attrs` is a `dict[str, dict[str, str]]` and its
                # own `.get` result is untyped on the self-hosted compiled
                # path (see `_ctor_lit_param_types`'s FLAT-dict note), so a
                # nested lookup would compare a boxed int against a string
                # and never match.
                _p17_cls = _as_str(_n.value.func.obj.obj.name)
                _p17_map = getattr(self, '_class_attrs', None)
                if _p17_map:
                    _p17_inner = None
                    for _p17_k in _p17_map:
                        if _as_str(_p17_k) == _p17_cls:
                            _p17_inner = _p17_map[_p17_k]
                            break
                    if _p17_inner:
                        for _p17_k2 in _p17_inner:
                            if _as_str(_p17_k2) == _as_str(_n.value.func.obj.member):
                                _p17_recv = _as_str(_p17_inner[_p17_k2])
                                break
            if _p17_recv is not None:
                _append_hits.setdefault(_p17_recv, []).append(
                    self._quick_type(_n.value.args[0]))
        if isinstance(_n, StructDef):
            # A constructor or any other method is a call site like any
            # other; see this function's docstring. `self` is typed so
            # `_quick_type(self)` below answers the struct pointer, exactly
            # as the `FunctionDef` arm seeds a function's own parameters.
            for _p17_m in (_n.methods or []):
                _p17_saved = self.var_types
                _p17_mark = self._scan_scratch_top
                self.var_types = self._scratch_dict_copy(_p17_saved)
                self.var_types['self'] = _as_str(_n.name) + ' *'
                for _p17_pn, _p17_pt in (_p17_m.params or []):
                    if _p17_pt:
                        self.var_types[_as_str(_p17_pn)] = _mojo_type(_p17_pt)
                _gmi_phase17_collect_appends(
                    self, _p17_m.body or [], _append_hits)
                self.var_types = _p17_saved
                self._scan_scratch_top = _p17_mark
            continue
        if isinstance(_n, FunctionDef):
            _saved = self.var_types
            _scratch_mark_17: int = self._scan_scratch_top
            self.var_types = self._scratch_dict_copy(_saved)
            for _pname, _ptype in (_n.params or []):
                if _ptype:
                    self.var_types[_pname] = _mojo_type(_ptype)
            for _lname, _ltype in self._infer_local_var_types(_as_funcdef_node(_n)).items():
                if _lname not in self.var_types:
                    self.var_types[_lname] = _ltype
            _gmi_phase17_collect_appends(self, _n.body or [], _append_hits)
            self.var_types = _saved
            self._scan_scratch_top = _scratch_mark_17
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
    # `self.buf = [0.0] * n` / `self.xs = xs * 2` — a REPEAT of a container
    # literal is that container, at runtime and in the emitted C
    # (mojo_list_repeat / mojo_bytes_repeat). Without this the field fell
    # through to _UNKNOWN_FIELD_CTYPE, and because a field read with an
    # unknown ctype is iterated down the DICT dual-dispatch arm, a plain
    # `for g in self.buf:` over a repeated float list emitted
    # mojo_dict_iter_key + `char * g` and then `(char*)*(char*)` — an
    # internal compiler error in gcc (build2/tree.cc), i.e. a hard ICE
    # rather than the "refuse rather than guess" diagnostic this codegen
    # prefers. Answering MojoList * here is a proof, not a guess: the
    # operand's container kind is syntactic.
    if isinstance(v, BinaryOp) and v.op == '*':
        _rep_l = _gmi_container_ctype(v.left)
        _rep_r = _gmi_container_ctype(v.right)
        if _rep_l is not None:
            return _rep_l
        if _rep_r is not None:
            return _rep_r
    return None


def _gmi_collect_self_assigns(self, _sname: str, body, param_types: dict,
                              found: dict) -> None:
    """Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_
    comptime`'s docstring. Not recursive (walks via _walk_ast), but a
    lifted closure all the same; `param_types`/`found` (dicts) threaded
    and annotated per the hoist GOTCHA, and the captured struct name is
    passed as `_sname` instead of the whole StructDef.

    The bool evidence is read from `self._gmi_bool_params`, the per-method set
    of parameter names whose DECLARED annotation is `bool`, which
    `param_types` cannot express: `_TYPE_MAP` maps `'bool'` to `'int'` on
    purpose, so a `def __init__(self, flag: bool)` parameter and an `int` one
    are the same string in that dict. The annotation is the only place the
    difference exists, and it is what `gen.struct_bool_fields` records — the
    table `is_python_bool_expr` reads to decide whether `self.<f>` is a Python
    bool worth printing as True/False rather than 1/0, and that the struct's
    own generated `_mojo_repr_<Sn>` already reads. Without it the canonical
    Python shape (`self.flag = flag` from a `flag: bool` parameter) had no
    bool evidence anywhere and every spelling of `b.flag` printed `1`/`0`.

    On `self`, not a threaded argument, and that is deliberate on both counts.
    Threading it would mean one more parameter through all seventeen
    recursive calls below, every one of which is a place to forget it; and the
    set has a lifetime narrower than the recursion — `gen_module_impl` REBUILDS
    it per method, so one method's answer cannot leak into the next one's
    fields. The descent below walks into `if`/`else`/`try`/`match`/nested-
    `def` bodies, so this is read at every level of that descent rather than
    captured once."""
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
                    # `self.flag = flag` with `flag: bool`. The field's own
                    # ctype is a plain `int` -- `_TYPE_MAP` maps `'bool'` to
                    # `'int'` -- so `ft` above carries no bool-ness at all and
                    # every `_Bool` arm downstream (print, repr, str, the dict
                    # store) has nothing to fire on: `print(b.flag)` printed
                    # `1` where CPython prints `True`, in every spelling,
                    # while `print(b)` said `flag=True` because the struct's
                    # generated `__repr__` consults `struct_bool_fields`.
                    # This assignment is the one place that knows BOTH that
                    # the parameter is a bool and which field it feeds, which
                    # is why the annotation has to be spent here rather than
                    # recovered later.
                    if v.name in self._gmi_bool_params:
                        self.struct_bool_fields.setdefault(_sname, set()).add(fn)
                elif isinstance(v, IntLiteral):
                    ft = 'int64_t'
                elif isinstance(v, FloatLiteral):
                    # `self.v = 0.0` in __init__ — a float-initialised
                    # scalar field. Without this it fell through to
                    # _UNKNOWN_FIELD_CTYPE (int64_t), so the field stored
                    # an int64_t: `self.v += x * x` over double x's
                    # truncated on every store (6.75 read back as 6, and
                    # 0.0 + 0.0 stayed 0 so a pure-fraction accumulator
                    # never moved at all) — silently wrong, exit 0. The
                    # arith above still runs in double and only the STORE
                    # was lossy, which is exactly why it reads as a
                    # rounding bug rather than an obvious type error.
                    ft = 'double'
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
                    elif cn in _BUILTIN_RET_CTYPES:
                        # The shared builtin-return table
                        # (mojo/middle/types.py), so this stays in step with
                        # `_quick_type`'s view of the same names instead of
                        # being a second, shorter list. See that table's
                        # docstring for what the divergence cost:
                        # `self.itos = sorted(set(text))` typed the field
                        # int64_t and every later read of it lost its
                        # element type.
                        ft = _BUILTIN_RET_CTYPES[cn]
                    elif cn.startswith('_alloc_'):
                        sname = cn[len('_alloc_'):]
                        ft = sname + ' *'
                    elif cn in self.struct_field_types:
                        ft = cn + ' *'
                    elif (isinstance(cfn, MemberExpr)
                          and isinstance(cfn.obj, CallExpr)):
                        # `self.w = Tensor(...).fill(rng, scale)` -- a
                        # CONSTRUCTOR call immediately followed by one of
                        # its own methods. The value is still a Tensor; the
                        # pre-pass just cannot see through the chain, so the
                        # field fell to int64_t and EVERY later
                        # `self.w.<anything>` became a stubbed int64_t call
                        # ("int64_t.row() stubbed"), which then poisons
                        # everything downstream that reads the field.
                        _ctor = _gmi_as_str(getattr(cfn.obj.func, 'name', ''))
                        if _ctor in self.struct_field_types:
                            ft = _ctor + ' *'
                        else:
                            # The `else` this branch was missing. Without it
                            # `ft` kept whatever the previous iteration left
                            # in it, and on the FIRST field that reached here
                            # it was never assigned at all -- so
                            # `found[fn] = ft` three lines below raised
                            # `UnboundLocalError: cannot access local
                            # variable 'ft'`, which aborted the whole module.
                            #
                            # Measured: 5 stdlib files died on it
                            # (std/collections/{list,_swisstable}.mojo,
                            # std/memory/{arc_pointer,owned_pointer}.mojo,
                            # std/python/_cpython.mojo) plus every module that
                            # imports them.
                            #
                            # `_UNKNOWN_FIELD_CTYPE` is the right default and
                            # not merely a safe one: it is exactly what the
                            # sibling branches above and below use for "the
                            # pre-pass cannot see through this", and it never
                            # asserts a pointer type the code has not earned.
                            ft = _UNKNOWN_FIELD_CTYPE
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

def _gmi_scan_imported_global_homes(self, stmt_list) -> None:
    """Record every bare name THIS module's own top-level `from b import K`
    binds, together with the module whose `_<mod>_globals` struct declares
    the field, so a later BARE read of that name loads the OWNER's field
    instead of this module's.

    Hoisted out of `gen_module_impl` — see `_gmi_prefold_toplevel_comptime`'s
    docstring — and runs after Phase 1.7 (which is what populates
    `_global_to_module`/`_global_var_types`) but BEFORE any function body is
    emitted, because the reads it fixes happen inside those bodies.

    What was wrong without it: the bare-name global read in
    `_lower_IdentExpr` loads `_<current module>_globals.NAME`, and for a
    `from b import K` that struct has no such member — gcc's "'struct
    _root_toplev' has no member named 'K'", one error per read site. The
    self-host closure had 26 distinct such names in 15 modules. The qualified
    `b.K` spelling of the same value never had the problem, because
    `_lower_MemberExpr` resolves the field through the owning module's own
    `_module_global_field_type(bound_module, member)` triple; this is the
    bare-name half of that pair.

    Two gates, and both are load-bearing rather than defensive:

    * **The owner must be a DIFFERENT module.** `from <self> import K` (a
      module importing a name out of itself) is this module's own global
      and must keep loading its own field.
    * **This module must not declare a global of that name ITSELF.** `from b
      import N` followed by a module-level `N = 'a-side'` rebinds the name in
      THIS module's namespace (Python semantics), so the bare `N` afterwards
      is this module's field, not `b`'s. `_own_global_var_types` is the
      right test for "this module declares it", and it is only a sound test
      because `_phase17_set_gtype`'s own-scope split keeps imported
      modules' names out of it — the two changes are one fix, not two.
    * **`_module_global_field_type(owner, name)` must answer.** That is the
      exact member list the owner's struct typedef, its initializer and its
      `_<mod>_mojo_global_get_<name>` accessor are all generated from, so a
      hit is proof the field EXISTS rather than a claim that it should. A
      from-import of a name no inline-compiled module declares as a global
      (a function — this is the value half, see
      `_own_imported_global_home`'s own comment — a submodule, an unresolvable
      stdlib) fails this and is left entirely alone, which is what keeps
      every already-working from-import spelling byte-identical.

    An ambiguous binding (two `from` statements in this module binding one
    bare name to two different owners' fields) is DROPPED rather than
    resolved by scan order, mirroring `_note_own_func_home`'s
    `_AMBIGUOUS_FUNC_HOME` policy: there is no right answer to pick, and
    leaving the read un-routed reproduces today's behaviour rather than a
    coin flip.
    """
    homes = self._own_imported_global_home
    fields = self._own_imported_global_field
    this_mod = self.module_name if len(self.module_name) > 0 else "root"
    for _ig in stmt_list:
        if not isinstance(_ig, FromImportStmt):
            continue
        # `from b import *` binds names this scan never sees, so there is
        # nothing per-name to record; the qualified `b.K` path is what
        # handles it.
        if getattr(_ig, 'wildcard', False):
            continue
        for _nm2 in (getattr(_ig, 'name_alias_strs', None) or []):
            _iname = _as_str(gimple_ctypes._fi_name(_nm2))
            _ialias = _as_str(gimple_ctypes._fi_alias(_nm2))
            _local = _ialias if _ialias else _iname
            if not _local:
                continue
            _iowner = getattr(self, '_global_to_module', {}).get(_iname)
            if _iowner is None:
                continue
            _iowner_s = _as_str(_iowner)
            if (not _iowner_s) or _iowner_s == this_mod:
                continue
            if _iname in self._own_global_var_types:
                continue
            if _local in homes:
                # Two owners for one bare name: ambiguous, so record
                # nothing (see the docstring).
                if homes[_local] != _iowner_s:
                    del homes[_local]
                    if _local in fields:
                        del fields[_local]
                continue
            if self._module_global_field_type(_iowner_s, _iname) is None:
                continue
            homes[_local] = _iowner_s
            fields[_local] = _iname


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


# The three `_selfhost_*` seed passes used to cache their RESULTS in a shared
# `_SELFHOST_MODGLOBAL_CACHE` under three private keys ('k' / 'sdfvt' /
# 'httrf'). That dict is GONE: three result caches over one shared file list
# is three parses of the same source and three AST copies retained for the
# life of the process. `_selfhost_parsed_modules` above reads the one
# per-FILE cache (funcs_shared._SELFHOST_PARSE_CACHE, keyed `path@mtime`).
from mojo.middle.exprtypes import _walk_ast
from mojo.middle.types import _LIST_RETURNING_METHODS, _STR_RETURNING_METHODS, _extract_init_expr, _import_targets, _mojo_type
