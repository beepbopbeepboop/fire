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
# NO module-level `import gimple_codegen` here. The rule, and this file's two
# readers of `gimple_codegen._SELFHOST_DIR`, are in the header comment below.
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

# NO `import gimple_codegen` AT MODULE LEVEL, anywhere in `mojo/middle/*`, and
# this file's two readers of `gimple_codegen._SELFHOST_DIR` are the reason the
# rule exists. The edge middle-tier -> `gimple_codegen` -> the gimple backend
# -> middle-tier IS a cycle, and Python resolves it by letting whichever module
# the process reached first finish: enter through any of the eight middle-tier
# modules and `from mojo.middle.infra_infer import _FC_SEP` (or
# `user_dunder_repr_call`, `_selfhost_parsed_source`, `builtin_module_constant`,
# `_is_none_literal`, `_annotation_container_elem_type`,
# `_emit_starred_slot_list`, `_is_selfhost_source_file`) meets a half-built
# module. Only `test_suite.py`'s declared exemption list kept that from being a
# red, and every real entry point in `driver.py` reaches `gimple_codegen`
# first, so nothing else could see it.
#
# `import X` binds a module object and survives a half-initialised X (its
# attribute reads happen later, at call time, by which point X is finished);
# `from X import NAME` resolves EAGERLY and does not. So the two readers below
# do their `import gimple_codegen` inside the function — the same placement
# `module_loader.load_module` and `fire_compiler.compile_with_interpreter`
# already use for exactly this reason.
#
# `test_suite.py`'s "imports: every real entry point imports first" is the
# measurement, and it is checked in both directions: a new module that closes
# the cycle fails, and so does an entry left on the exemption list that now
# imports fine.

def _gmm_callexpr_node(x) -> CallExpr:
    """Same-module `CallExpr`-view identity helper (the `_gmm_as_str`
    pattern; an imported `_as_callexpr_node` from fire_compiler is emitted
    as an `int64_t` weak stub and would return 0). Lets
    `_lower_struct_method_call` read `.args`/`.kwargs` as DIRECT struct
    fields instead of through `_mojo_dispatch_getattr`, whose per-type
    table does not reliably carry a CallExpr case in every compiled module
    (miss sentinel 1 -> `mojo_list_len(1)` SIGSEGV)."""
    return x

# `os.path.realpath` is a chain of lstat calls and these two predicates ask it about the
# same few paths (`_SELFHOST_DIR`, each compiler source file) tens of thousands of times
# per `--dump-full` -- about 7% of the compile. A path's realpath does not change while the
# compile runs. Annotated like the other module-level memo tables the compiled path uses.
_REALPATH_MEMO: dict = {}


def _cached_realpath(p: str) -> str:
    # Typed on purpose: an unannotated helper's result unified with unrelated
    # call sites in the self-hosted build (`invalid operands to binary +`).
    _hit: str = _as_str(_REALPATH_MEMO.get(p, ''))
    if _hit != '':
        return _hit
    _r: str = _as_str(os.path.realpath(p))
    _REALPATH_MEMO[p] = _r
    return _r


def _is_selfhost_source_file(path: str) -> bool:
    """True when `path` is a source file OF this compiler — a root-level
    `*.py` beside `fire_compiler.py`, or one inside its own `mojo/` package
    or `jit/` helper package. The one answer to "is the file being compiled
    the compiler itself?", for every caller that needs exactly that and not
    the name of the thing being referenced (`_is_selfhost_sibling_alias`
    below answers the other, stricter question).

    Deliberately NOT "any `.py` at or under `_SELFHOST_DIR`". A program's
    location is not something a compiler has any reason to treat specially,
    so a bare prefix test silently classified as "the compiler's own source"
    every file that merely happens to sit inside the install directory: a
    test fixture, a scratch script, a downstream project's subdirectory, a
    `build/` artifact. Anything gated on it then behaved differently purely
    because of where the file was written, and in
    `_lower_method_call`'s generic module-qualified-call branch
    (`mojo/backend_gimple/emit_methods.py`) that meant a
    `<marker>.<plain_top_level_fn>(...)` call was refused module-qualifier
    resolution, fell through to the generic scalar-receiver stub, and
    answered a literal `0` — a silent wrong value whose only trigger was
    `$TMPDIR`, which is what made the registered `linkmode` gate step pass or
    fail depending on the checkout it ran in. `test_link_mode.py`'s
    `test_bare_submodule_import_call_inside_source_tree` pins it.

    Realpath- and symlink-tolerant like the predicate it replaces: both
    `abspath` and `realpath` of `_SELFHOST_DIR` are accepted as a base, so
    a source root reached through a symlink is still recognised. Note the
    COMPILED binary's own `_SELFHOST_DIR` is its CWD, not the real source
    dir (see `gimple_codegen._selfhost_load_gimplegen_class`) — that
    imprecision is unchanged from the prefix test this replaces, and is
    conservative in the same direction: an unrecognised self-host file
    simply takes the ordinary resolution path, which is what every
    self-host compile already did under the compiled binary.

    `.py` only, for the same reason `_is_selfhost_sibling_alias` below
    requires it: the self-hosting bootstrap is this compiler's own Python,
    so no `.mojo` file is ever part of it. That matters for a synthetic
    name — `os.path.abspath('client.mojo')` resolves against the process
    CWD, which IS this checkout whenever a test runs from the repo root, so
    without the extension check a bare relative name would read as a
    compiler source file.
    """
    if not path or not path.endswith('.py'):
        return False
    # FUNCTION-LOCAL, and that placement is the whole point: see the header
    # comment's rule. Nothing in `mojo/middle/*` may reach `gimple_codegen` at
    # module level, because that edge IS the middle-tier import cycle.
    import gimple_codegen
    _rp = _cached_realpath(os.path.abspath(path))
    _sd = gimple_codegen._SELFHOST_DIR
    _rsd = _cached_realpath(_sd)
    _dir = os.path.dirname(_rp)
    # `'/'`, not `os.sep`: `gimple_ctypes.os` is an opaque module marker on
    # the compiled backend and `.sep` raised `AttributeError: sep`
    # (mojo/backend_gimple/emit_resolve.py's own note on the same trap).
    # The `if not _base` guard is for the OTHER half of that hazard —
    # `_SELFHOST_DIR` is a module-level global that reads back as a boxed
    # int64_t on the self-hosted path unless `_seed_selfhost_module_globals`
    # has already corrected its type for this call site, and a boxed `0`
    # would otherwise be concatenated as if it were a path.
    for _base in (_sd, _rsd):
        if not _base:
            continue
        if _dir == _base:
            return True
        for _sub in ('mojo', 'jit'):
            _pkg = _base + '/' + _sub
            if _rp == _pkg or _rp.startswith(_pkg + '/'):
                return True
    # The same question asked of the FILE'S OWN TREE, which is the answer
    # that does not depend on where the running compiler lives. The compiled
    # binary has no source location of its own (`__file__` is `<bootstrap>`,
    # so its `_SELFHOST_DIR` is the process CWD): the stage2 binary's
    # `--dump ../fire_main.py`, run from `stage2/`, answered False here where the
    # python reference answered True, and every compiler-source dump it made
    # lacked the self-host struct layouts (`Scope`, `Token`, `Parser`,
    # `CallExpr`, ...) -- the stage1-vs-stage2 `.ci` divergence. A compiler
    # source tree is recognised by the module that defines it: the root holds
    # `fire_compiler.py` and `gimple_codegen.py`. Same marker
    # `_is_selfhost_sibling_alias` below already uses, applied at the file
    # level only (the file's own directory, or the root above its `mojo/` /
    # `jit/` package), never by walking up, so a file merely somewhere under
    # the checkout (`tools/`, `build/`) is still not compiler source.
    if _is_compiler_root(_dir):
        return True
    _parts = _rp.split('/')
    for _i in range(1, len(_parts) - 1):
        _pi = _parts[_i]
        if _pi == 'mojo' or _pi == 'jit':
            if _is_compiler_root('/'.join(_parts[:_i])):
                return True
    return False


def _is_compiler_root(d: str) -> bool:
    """`d` is the root of a copy of this compiler's source (see
    `_is_selfhost_source_file`)."""
    return (os.path.isfile(d + '/fire_compiler.py')
            and os.path.isfile(d + '/gimple_codegen.py'))

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
    import gimple_codegen          # function-local; see the header comment
    sd = gimple_codegen._SELFHOST_DIR
    # Path-INDEPENDENT sibling signal (`fire_compiler.py` at the tree root),
    # mirroring `_is_selfhost_source_file` above. The bare
    # `_SELFHOST_DIR` equality/prefix check alone is FALSE when the compiler
    # is compiled from a DIFFERENT checkout than the one acting as driver —
    # a downstream GCC frontend vendoring a byte-identical copy at its own
    # path (confirmed: /Users/mrs/net/gcc/gcc/fire). Without this, every
    # sibling-qualified reference (`gimple_codegen.GimpleGen._cpp_kwfwd_counter`,
    # `mojo.middle.solvers.LayoutSolver.HEAP`) missed this gate in that build and
    # fell through to the "class-as-value not modeled" stub / a
    # `_mojo_dispatch_setattr` on a bogus pointer. Re-derived locally rather
    # than imported cross-module (see _is_selfhost_source_file's own docstring
    # for the self-hosted resolution gap that forces the duplication).
    _rcur = _cached_realpath(cur_abs)
    _rsd = _cached_realpath(sd)
    _in_shtree = (cur_abs == sd or cur_abs.startswith(sd + gimple_ctypes.os.sep)
                  or _rcur == _rsd or _rcur.startswith(_rsd + gimple_ctypes.os.sep))
    if not _in_shtree:
        # Walk up to the tree root: a genuine compiler-source tree is the
        # one holding a `fire_compiler.py` next to the file or at any
        # ancestor. This recognizes a SUBDIRECTORY (`mojo/middle`,
        # `mojo/backend_gimple`) reached through a SYMLINKED source root,
        # where `_SELFHOST_DIR` (realpath) and `cur_abs` (symlink path)
        # never prefix-match. Same defect and same fix as
        # `_is_selfhost_source_file` above — and unlike that one, which asks
        # the file-level question and so needs no walk at all, this question
        # is genuinely about the tree, hence the walk.
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



def poly_dispatch_plan(self):
    """The generated polymorphic-receiver dispatches for this module.

    A constructor slot that received two or more different `<Struct> *`
    (`self._poly_slot_cands`) stays `int64_t`, so a method called on it is a
    call on a word of unknown type. Each method name at least two candidates
    define gets one generated `static int64_t _mojo_poly_<m>_<S1>_<S2>(int64_t)`
    that switches on the receiver's leading `__mojo_type_id` and calls the
    candidate's own `<S>_<m>`. A tag that matches no candidate raises the same
    AttributeError a missing dynamic attribute raises.

    Scope of this first slice, chosen so nothing that compiles today is refused:
    only methods that take NO arguments beyond `self` and return `int64_t` are
    dispatched. Any other polymorphic method keeps the scalar no-op stub, which
    is the behaviour before this function existed.

    Candidates that disagree on the method's return type or on its arity have
    no single dispatch call shape, so they are not dispatched at all: they are
    recorded under `'refused'` with the compile error the call site raises. A
    method that is merely not dispatchable yet (arguments, a non-`int64_t`
    unanimous return) is left out of both, and keeps the stub it always had.

    Returns {'slots': {slot key: {method: dispatch name}},
             'dispatch': {dispatch name: (method, [struct, ...])},
             'refused': {slot key: {method: error message}}}.
    Cached on `self._poly_plan`, keyed by the candidate-slot count so a plan
    asked for before the constructor pass has run is never served stale.
    """
    _cache_key = len(getattr(self, '_poly_slot_cands', None) or {})
    _cached = getattr(self, '_poly_plan', None)
    if _cached is not None and _cached[0] == _cache_key:
        return _cached[1]
    plan = {'slots': {}, 'dispatch': {}, 'refused': {}}
    defs = getattr(self, '_poly_struct_defs', None) or {}
    for skey, cands in (getattr(self, '_poly_slot_cands', None) or {}).items():
        defining_by_method = {}
        for S in cands:
            sd = defs.get(S)
            if sd is None:
                continue
            for md in (sd.methods or []):
                m = _as_str(md.name)
                if m.startswith('__'):
                    continue
                defining_by_method.setdefault(m, []).append(S)
        for m, defining in defining_by_method.items():
            if len(defining) < 2:
                continue
            shapes = {}
            for S in defining:
                md = None
                for _x in (defs[S].methods or []):
                    if _as_str(_x.name) == m:
                        md = _x
                        break
                extra = [p for p in (md.params or []) if _as_str(p[0]) != 'self']
                shapes[S] = (len(extra), self.func_return_types.get(f"{S}_{m}"))
            arities = {a for a, _r in shapes.values()}
            # A return type is only a disagreement once every candidate's is
            # known: an unregistered one is "not yet inferred", not a conflict.
            rets = {r for _a, r in shapes.values()}
            ret_conflict = None not in rets and len(rets) > 1
            if len(arities) > 1 or ret_conflict:
                what = ("arity" if len(arities) > 1 else "return type")
                detail = ", ".join(f"{S}.{m} {shapes[S][0]} extra arg(s) -> "
                                   f"{shapes[S][1]}" for S in sorted(defining))
                plan['refused'].setdefault(skey, {})[m] = (
                    f"polymorphic receiver {skey}.{m}(): the structs "
                    f"{sorted(defining)} that a constructor slot received disagree "
                    f"on the {what} of `{m}` ({detail}); no single dispatch call "
                    f"can serve them")
                continue
            eligible = True
            for S in defining:
                extra_n, ret = shapes[S]
                if extra_n or ret != 'int64_t':
                    eligible = False
                    break
            if not eligible:
                continue
            names = sorted(defining)
            dname = f"_mojo_poly_{m}_" + "_".join(names)
            plan['slots'].setdefault(skey, {})[m] = dname
            plan['dispatch'][dname] = (m, names)
    self._poly_plan = (_cache_key, plan)
    return plan
