"""Shared middle-end extracted from gimple_gen_methods.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _sms_key, _as_str
import regex_compile
import mlir
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

def _gmm_callexpr_node(x) -> CallExpr:
    """Same-module `CallExpr`-view identity helper (the `_gmm_as_str`
    pattern; an imported `_as_callexpr_node` from fire_compiler is emitted
    as an `int64_t` weak stub and would return 0). Lets
    `_lower_struct_method_call` read `.args`/`.kwargs` as DIRECT struct
    fields instead of through `_mojo_dispatch_getattr`, whose per-type
    table does not reliably carry a CallExpr case in every compiled module
    (miss sentinel 1 -> `mojo_list_len(1)` SIGSEGV)."""
    return x

def _is_selfhost_sibling_alias(gen, module_name: str) -> bool:
    """True when compiling this compiler's OWN backend source and
    `module_name` is a local alias for one of its sibling implementation
    modules (`import mojo.backend_gimple.emit_calls as ggc`,
    `import mojo.middle.types as gimple_ctypes`, `import gimple_codegen`, …).

    Gated hard to `.py` sources under this repo that are either root
    `gimple*.py` or inside the `mojo/` package (the self-hosting bootstrap
    is always this compiler's own Python — no `.mojo` file is ever part of
    it), so it can never intercept a real stdlib module reference like
    `re.compile(...)`."""
    cf = getattr(gen, '_current_filename', None)
    if not cf or not cf.endswith('.py'):
        return False
    cur_abs = gimple_ctypes.os.path.abspath(cf)
    sd = gimple_codegen._SELFHOST_DIR
    # Path-INDEPENDENT sibling signal (`fire_compiler.py` at the tree root),
    # mirroring gimple_module_gen._is_selfhost_source_dir. The bare
    # `_SELFHOST_DIR` equality/prefix check alone is FALSE when the compiler
    # is compiled from a DIFFERENT checkout than the one acting as driver —
    # a downstream GCC frontend vendoring a byte-identical copy at its own
    # path (confirmed: /Users/mrs/net/gcc/gcc/fire). Without this, every
    # sibling-qualified reference (`gimple_codegen.GimpleGen._cpp_kwfwd_counter`,
    # `mojo.middle.solvers.LayoutSolver.HEAP`) missed this gate in that build and
    # fell through to the "class-as-value not modeled" stub / a
    # `_mojo_dispatch_setattr` on a bogus pointer. Re-derived locally rather
    # than imported cross-module (see _is_selfhost_source_dir's own docstring
    # for the self-hosted resolution gap that forces the duplication).
    _rcur = gimple_ctypes.os.path.realpath(cur_abs)
    _rsd = gimple_ctypes.os.path.realpath(sd)
    _in_shtree = (cur_abs == sd or cur_abs.startswith(sd + gimple_ctypes.os.sep)
                  or _rcur == _rsd or _rcur.startswith(_rsd + gimple_ctypes.os.sep))
    if not _in_shtree:
        # Walk up to the tree root: a genuine compiler-source tree is the
        # one holding a `fire_compiler.py` next to the file or at any
        # ancestor. This recognizes a SUBDIRECTORY (`mojo/middle`,
        # `mojo/backend_gimple`) reached through a SYMLINKED source root,
        # where `_SELFHOST_DIR` (realpath) and `cur_abs` (symlink path)
        # never prefix-match. Same defect and same fix as gimple_module_gen.
        # _is_selfhost_source_dir.
        _rparts = _rcur.split(gimple_ctypes.os.sep)
        for _p in range(len(_rparts), 0, -1):
            _cand = gimple_ctypes.os.sep.join(_rparts[:_p])
            if gimple_ctypes.os.path.isfile(gimple_ctypes.os.path.join(
                    _cand, 'fire_compiler.py')):
                _in_shtree = True
                break
    if not _in_shtree:
        return False
    if module_name in getattr(gen, '_module_alias_names', ()):
        _info = (getattr(gen, 'imported_symbols', {}) or {}).get(module_name) or {}
        _mod = _info.get('module') or module_name
        return _mod.startswith(_SELFHOST_SIBLING_MODULE_PREFIXES)
    # A bare sibling-module base name (`regex_compile`, `ast_rewriter`,
    # `mlir`) reached without a local `import` of its own. Safe here: we
    # are already inside this compiler's own backend source.
    return module_name.startswith(_SELFHOST_SIBLING_MODULE_PREFIXES)


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_methods.py)
# ---------------------------------------------------------------------------

# --- dependency _SELFHOST_SIBLING_MODULE_PREFIXES (from gimple_gen_methods.py) ---
_SELFHOST_SIBLING_MODULE_PREFIXES = (
    'gimple_', 'mojo.', 'ast_rewriter', 'mlir', 'regex_compile',
    'module_loader', 'ownership_destruct', 'fire_compiler',
    'determinism_trace', 'imports', 'elaborate', 'monomorphize', 'comptime',
    'cas', 'build_stdlib_dylib', 'driver')

