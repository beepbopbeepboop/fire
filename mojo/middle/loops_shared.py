"""Shared middle-end extracted from gimple_gen_loops.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _as_str, _pair_key
import regex_compile
import mlir
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

def _tuple_elem_value(gen, vtype: str, v: str, idx: int) -> tuple[str, str]:
    """Read element `idx` of a tuple value (vtype, v), returning
    (elem_ctype, value). A tuple literal lowers with vtype 'MojoList *';
    a tuple RETURNED BY A CALL lowers with vtype 'int64_t' (the handle is
    boxed — this codegen's own `-> tuple[str, str]` annotation resolves to
    int64_t via _mojo_type), its real type only recoverable through
    _actual_types. The old consumers only handled the MojoList* case, so
    call-returned tuples were indexed with mojo_list_get_int — reading the
    (ctype, cval) string-pair tuples this codegen returns everywhere as
    decimal pointers. Resolve the actual type first, then pick the
    accessor from the element type, mirroring the MojoList* branch."""
    real = gen._get_actual_type(vtype, v)
    idx64 = gen._new_val('int64_t', f"(int64_t){idx}")
    if real == 'MojoList *':
        elem = gen._elem_of(v)
        suf = gimple_ctypes.TypeLattice.list_suffix(elem)
        if vtype == real:
            lp = v
        else:
            # The C storage is int64_t (boxed handle); cast to a real
            # MojoList* temp before the accessor call, or GIMPLE rejects
            # "passing int64_t where MojoList * expected".
            lp = gen._coerce_to_type('int64_t', 'MojoList *', v)
        if suf == 'str':
            return 'char *', gen._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
        if suf == 'double':
            return 'double', gen._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
        if elem in ('int64_t', 'int', '_Bool'):
            return 'int64_t', gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        # Pointer elem that isn't char* (e.g. a nested MojoList*): read the
        # opaque int64_t then cast, matching the old 'int'-suffix handling.
        # An UNKNOWN/empty element type (the tuple handle's elem type was
        # never tracked) reads back as int64_t with NO cast — the previous
        # `({elem}){raw}` produced an empty `()` cast
        # (`a = ()_t5;` — not even valid C; repro:
        # std/test/builtin/test_int.mojo's `a, b = divmod(...)`).
        if not elem or elem == 'unknown':
            return 'int64_t', gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        raw = gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        return elem, gen._new_val(elem, f"({elem}){raw}")
    # Non-container / untracked: despite this function's name, its real
    # callers include plain multi-assign unpacking (`a, b = x`) over ANY
    # iterable, not just a syntactic tuple/call-return — `a, b = some_dict`
    # is real, valid Python (unpacks the dict's keys) and reaches here with
    # `vtype == 'MojoDict *'` directly (found via a real crash: DESIGN.html
    # R1/R5, shares _materialize_as_list with all()/any()/enumerate()/
    # *.join()/the list-pattern-target branch above in gimple_gen_stmts.py).
    lp = gen._materialize_as_list(vtype, v)
    elem = gen._elem_of(lp)
    suf = gimple_ctypes.TypeLattice.list_suffix(elem) if elem else 'int'
    if suf == 'str':
        return 'char *', gen._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
    if suf == 'double':
        return 'double', gen._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
    return 'int64_t', gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")

def _try_const_fold_int(gen, expr) -> int | None:
    if isinstance(expr, gimple_ctypes.IntLiteral):
        return expr.value
    return None

def _tuple_unpack_slot_elems(gen, it_val: str, nslots: int) -> list:
    """Per-slot C element types for a tuple-UNPACKING loop target
    (`for k, v in <pairs>:`), from whatever container metadata is
    tracked for the iterable value: dict-items pairs have a char* key
    slot and the dict's own value-type value slot; a heterogeneous
    tuple-literal list carries its per-slot types (_tuple_slot_types);
    anything else falls back to the pair element type / int64_t."""
    is_dict_items = it_val in gen._dict_items_val_elems
    value_elem = gen._dict_items_val_elems.get(it_val) if is_dict_items else None
    slot_types = gen._tuple_slot_types.get(it_val)
    pair_elem = gen._nested_elem_types.get(it_val, 'int64_t')
    elems = []
    # `_as_str` on every appended slot type: the source metadata dicts
    # (_tuple_slot_types / _nested_elem_types / _dict_items_val_elems)
    # can hand back a boxed/garbage value on the self-hosted path, and
    # `_declare_var`'s `mojo_str_cat` then ran `strlen()` on it — a hard
    # segfault on the single-TU `--dump myinterpreter.py`.
    for i in range(nslots):
        if is_dict_items:
            elems.append('char *' if i == 0 else _as_str(value_elem or 'int64_t'))
        elif slot_types is not None and i < len(slot_types):
            elems.append(_as_str(slot_types[i]))
        else:
            elems.append(_as_str(pair_elem))
    return elems

def _gfl_declare_target_name(gen, shadow_name, vn: str, se: str) -> None:
    """Hoisted out of `_gen_for_list` (recursive nested closure) — the
    lifted-closure-env determinism fix; `gen`/`shadow_name` threaded."""
    if vn.startswith('(') and vn.endswith(')'):
        for _nv in gen._split_top_level_comma(vn[1:-1].strip()):
            _gfl_declare_target_name(gen, shadow_name, _nv, 'int64_t')
    else:
        gen._declare_var(vn, se, force=(vn == shadow_name))

