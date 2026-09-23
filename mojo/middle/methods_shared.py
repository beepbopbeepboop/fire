"""Shared middle-end extracted from gimple_gen_methods.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _sms_key, _as_str
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
    """True when compiling this compiler's OWN `gimple*.py` backend source and
    `module_name` is a local alias for one of its sibling implementation
    modules (`import gimple_gen_calls as ggc`, `import gimple_ctypes`, …).

    Gated hard to `.py` sources under this repo whose basename starts with
    `gimple` (the self-hosting bootstrap is always this compiler's own Python
    — no `.mojo` file is ever part of it), so it can never intercept a real
    stdlib module reference like `re.compile(...)`."""
    cf = getattr(gen, '_current_filename', None)
    if not cf or not cf.endswith('.py'):
        return False
    if not gimple_ctypes.os.path.basename(cf).startswith('gimple'):
        return False
    cur_abs = gimple_ctypes.os.path.abspath(cf)
    sd = gimple_codegen._SELFHOST_DIR
    # Path-INDEPENDENT sibling signal (`fire_compiler.py` next to the file),
    # mirroring gimple_module_gen._is_selfhost_source_dir. The bare
    # `_SELFHOST_DIR` equality/prefix check alone is FALSE when the compiler
    # is compiled from a DIFFERENT checkout than the one acting as driver —
    # a downstream GCC frontend vendoring a byte-identical copy at its own
    # path (confirmed: /Users/mrs/net/gcc/gcc/fire). Without this, every
    # sibling-qualified reference (`gimple_codegen.GimpleGen._cpp_kwfwd_counter`,
    # `gimple_solvers.LayoutSolver.HEAP`) missed this gate in that build and
    # fell through to the "class-as-value not modeled" stub / a
    # `_mojo_dispatch_setattr` on a bogus pointer. Re-derived locally rather
    # than imported cross-module (see _is_selfhost_source_dir's own docstring
    # for the self-hosted resolution gap that forces the duplication).
    if not (cur_abs == sd or cur_abs.startswith(sd + '/')
            or os.path.isfile(os.path.join(os.path.dirname(cur_abs), 'fire_compiler.py'))):
        return False
    if module_name in getattr(gen, '_module_alias_names', ()):
        _info = (getattr(gen, 'imported_symbols', {}) or {}).get(module_name) or {}
        _mod = _info.get('module') or module_name
        return _mod.startswith(_SELFHOST_SIBLING_MODULE_PREFIXES)
    # A bare sibling-module base name (`regex_compile`, `ast_rewriter`,
    # `mlir`) reached without a local `import` of its own — e.g. after the
    # `gimple_ctypes` re-export hub is stripped off `gimple_ctypes.
    # regex_compile.compile_pattern(...)`. Safe here: we are already inside
    # this compiler's own `gimple*.py` source.
    return module_name.startswith(_SELFHOST_SIBLING_MODULE_PREFIXES)


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_methods.py)
# ---------------------------------------------------------------------------

# --- dependency _SELFHOST_SIBLING_MODULE_PREFIXES (from gimple_gen_methods.py) ---
_SELFHOST_SIBLING_MODULE_PREFIXES = ('gimple_', 'ast_rewriter', 'mlir',
                                     'regex_compile', 'module_loader',
                                     'ownership_destruct', 'fire_compiler',
                                     # gated determinism-trace facility
                                     # (see determinism_trace.py): without
                                     # this, `import determinism_trace as
                                     # _dtrace` in gimple_gen_resolve.py
                                     # resolved to a bare module-GLOBAL
                                     # int64_t named `_dtrace` instead of the
                                     # module, so `_dtrace.enabled()` was a
                                     # scalar stub returning 0 and the trace
                                     # never fired.
                                     'determinism_trace')


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_methods.py)
# ---------------------------------------------------------------------------

# --- dependency _SELFHOST_SIBLING_MODULE_PREFIXES (from gimple_gen_methods.py) ---
_SELFHOST_SIBLING_MODULE_PREFIXES = ('gimple_', 'ast_rewriter', 'mlir',
                                     'regex_compile', 'module_loader',
                                     'ownership_destruct', 'fire_compiler',
                                     # gated determinism-trace facility
                                     # (see determinism_trace.py): without
                                     # this, `import determinism_trace as
                                     # _dtrace` in gimple_gen_resolve.py
                                     # resolved to a bare module-GLOBAL
                                     # int64_t named `_dtrace` instead of the
                                     # module, so `_dtrace.enabled()` was a
                                     # scalar stub returning 0 and the trace
                                     # never fired.
                                     'determinism_trace')

