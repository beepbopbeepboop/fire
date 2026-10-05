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
# NO top-level `import gimple_codegen`: `gimple_codegen` imports the whole
# `mojo/backend_gimple/*` tier at its own top level (gimple_codegen.py:738),
# and that tier reads this module back at ITS top level, so a top-level
# import here means this module cannot be a process's first `mojo.*`
# import. Nothing in this file read one (the import's comment claimed
# "constants used by some extracted helpers" and there were none), so
# deleting it breaks no reference. A middle module that does need
# something from `gimple_codegen` imports it at its USE SITE, the shape
# `mojo/backend_gimple/module_gen.py:6727` uses for this same module.
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
        # A `struct.unpack(...)` result has ONE container ctype but a
        # per-slot real kind, statically known from the format string. The
        # subscript path already prefers that per-slot kind (emit_calls.py's
        # MojoList branch); this is the SAME preference for the other
        # statically-indexed read of a tuple, the `a, b = t` destructuring
        # target, which read every slot with `mojo_list_get_int` and so handed
        # `a, b = struct.unpack('<if', buf)` the float's raw IEEE-754 bits.
        # `idx` is always a literal here (the target list is walked in order),
        # so the slot kind is a compile-time fact — unlike a computed
        # subscript, which genuinely has none.
        _sk = gen._struct_slot_kinds.get(v)
        if _sk is not None and 0 <= idx < len(_sk):
            if _sk[idx] == 'double':
                return 'double', gen._new_val(
                    'double', f"mojo_list_get_double ({lp}, {idx64})")
            if _sk[idx] == 'bytes':
                # A bytes slot is a `MojoBytes *` stored in the raw int64_t
                # slot (see fire_runtime.h's MojoList comment), so the read
                # goes back through the coercion chokepoint rather than an
                # ad-hoc pointer cast — DESIGN.html R2/R3.
                _bp = gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
                return 'MojoBytes *', gen._coerce_to_type(
                    'int64_t', 'MojoBytes *', _bp)
            if _sk[idx] == 'str':
                # A `char *` slot: the raw word IS the pointer, so this is
                # the string accessor and not a coercion. Only a
                # heterogeneous list LITERAL carries this kind — a
                # `struct.unpack` format cannot — including one that reached
                # this value through a `return`
                # (`gen._return_value_slot_kinds`).
                return 'char *', gen._new_val(
                    'char *', f"mojo_list_get_str ({lp}, {idx64})")
            return 'int64_t', gen._new_val(
                'int64_t', f"mojo_list_get_int ({lp}, {idx64})")
        # Per-slot types recorded for this exact value, when it has them:
        # a heterogeneous tuple literal, or a multi-value return's tuple
        # re-keyed onto the call result (see gen._return_slot_types). Each
        # slot is then read with ITS OWN type instead of the container's
        # single joined element type — which for `(cfg, model)` is the
        # useless int64_t, and produced a `Config *` local assigned an
        # int64_t read (GIMPLE: "internal compiler error: in build2").
        _pst = gen._tuple_slot_types.get(v)
        if _pst is not None and 0 <= idx < len(_pst):
            _pc = _pst[idx]
            if _pc == 'double':
                return 'double', gen._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
            if _pc == 'char *':
                return 'char *', gen._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
            if _pc in ('int64_t', 'int', '_Bool', 'double', 'char', '', 'unknown'):
                return 'int64_t', gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
            # Any other slot type is a boxed pointer: read the raw slot and
            # put it back through the coercion chokepoint rather than an
            # ad-hoc cast (same rule as the bytes slot above).
            _pr = gen._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
            return _pc, gen._coerce_to_type('int64_t', _pc, _pr)
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
            elems.append(('int64_t' if it_val in gen._dict_items_int_keys else 'char *') if i == 0
                         else _as_str(value_elem or 'int64_t'))
        elif slot_types is not None and i < len(slot_types):
            elems.append(_as_str(slot_types[i]))
        else:
            elems.append(_as_str(pair_elem))
    return elems

def starred_slot_index(slots: list) -> int:
    """Which slot of an unpacking target is `*`-starred, or -1 for none.

    Python's extended unpacking (`for first, *rest in ...`) puts the star in
    the SLOT TEXT, and `fire_compiler.for_target_names` keeps it there on
    purpose — "a starred leaf keeps its star ... the binding rules for it are
    the consumer's". Two consumers already read it: `boundnames`' binder
    strips it for the bound-name set, and the interpreter's
    `_bind_comprehension_target` finds it and does the before/star/after
    arithmetic. A third one did not, and used a slot as a variable name
    verbatim — so `*rest` reached the C declarator as `int64_t *rest;` and
    the assignment that followed was `*rest = _t22;`, a store through an
    UNINITIALISED pointer. It did not always crash: the slot landed in
    whatever the frame held, so `for first, *rest in [(1,2,3)]` printed
    `1 0` where CPython prints `1 [2, 3]`.

    By POSITION, which is what makes the rest of the rule expressible: every
    slot before the star is measured from the front of the item, every slot
    after it from the END, and the star takes what is left between them
    (`a, *mid, z` over a 4-item row gives `mid == [2, 3]`). Scanning names
    for a `*` character cannot express that; the interpreter's `star_idx` is
    the model.

    The first star wins. A second one is a CPython `SyntaxError` ("multiple
    starred expressions in assignment"), so it cannot come from real source —
    only from a hand-built AST, where treating the extra `*name` as an
    ordinary slot name is at least not a silent misreading of valid code.
    """
    for _i in range(len(slots)):
        _s = _as_str(slots[_i]).strip()
        if _s.startswith('*'):
            return _i
    return -1


def starred_slot_name(slot: str) -> str:
    """The name a starred target slot binds: `'*rest'` -> `'rest'`. A slot
    with no star is returned unchanged, so a caller that has already found
    the star by position can hand every slot through this."""
    _s = _as_str(slot).strip()
    if _s.startswith('*'):
        return _s[1:].strip()
    return _s


def _emit_starred_slot_list(gen, list_ptr: str, name: str, start: str,
                            stop: str, slot_elem: str) -> None:
    """`name = <list_ptr>[start:stop]`, emitted as a real counted loop.

    GIMPLE has no slice expression and no variable-length array, so the
    remainder is built the only way it can be: a fresh list, an index from
    `start`, and one append per element up to `stop`. `start`/`stop` are
    already-emitted int64_t operand NAMES, not literals, because a starred
    slot's own bounds depend on the item's runtime length (the slots after
    the star are counted from its end) — see `starred_slot_index`.

    The element accessor is the per-slot rule every non-starred slot uses
    (`mojo_list_get_str` for a `char *` slot, the int accessor otherwise),
    so the list the body goes on to read has the same element type as the
    row it came from.

    Declares `name` as a `MojoList *` and records its element type: the body
    must be able to print/iterate/len it as the list Python bound, which is
    the whole point of the star. The declaration is NOT forced — each site's
    own pre-pass declares the stripped name first (that is where the C
    declarations are emitted, before the loop opens), and `_declare_var` is
    first-decl-wins, so this call only fills the entry in when a site has not
    declared it yet.
    """
    _lp = _as_str(list_ptr)
    _nm = _as_str(name)
    gen._declare_var(_nm, 'MojoList *')
    if slot_elem and slot_elem != 'int64_t':
        gen._elem_types[_nm] = slot_elem
    _dst = gen._cname(_nm)
    _lst = gen._new_temp('MojoList *')
    gen._emit(f"  {_lst} = mojo_list_new ();")
    gen._emit(f"  {_dst} = {_lst};")
    _i = gen._new_val('int64_t', _as_str(start))
    _cond = gen._new_bb(); _body = gen._new_bb(); _after = gen._new_bb()
    gen._emit(f"  goto {_cond};")
    gen._emit_label(_cond)
    _c = gen._new_val('_Bool', f"{_i} < {_as_str(stop)}")
    gen._emit(f"  if ({_c}) goto {_body}; else goto {_after};")
    gen._emit_label(_body)
    if gimple_ctypes.TypeLattice.list_suffix(slot_elem) == 'str':
        _rd = gen._new_val('char *', f"mojo_list_get_str ({_lp}, {_i})")
        gen._void_call('mojo_list_append_str', [('MojoList *', _dst), ('char *', _rd)])
    elif gimple_ctypes.TypeLattice.list_suffix(slot_elem) == 'double':
        _rd = gen._new_val('double', f"mojo_list_get_double ({_lp}, {_i})")
        gen._void_call('mojo_list_append_double', [('MojoList *', _dst), ('double', _rd)])
    else:
        _rd = gen._new_val('int64_t', f"mojo_list_get_int ({_lp}, {_i})")
        gen._void_call('mojo_list_append_int', [('MojoList *', _dst), ('int64_t', _rd)])
    _one = gen._new_val('int64_t', "1LL")
    _nxt = gen._new_val('int64_t', f"{_i} + {_one}")
    gen._emit(f"  {_i} = {_nxt};")
    gen._emit(f"  goto {_cond};")
    gen._emit_label(_after)


def _emit_starred_slot_from_value(gen, name: str, value_ctype: str,
                                  value: str, slot_elem: str) -> None:
    """`name = [value]` — a starred slot whose remainder is exactly ONE value.

    The shape is `enumerate`/`zip`, which yield a 2-tuple per iteration, so
    `for i, *rest in enumerate(xs)` binds `rest` to a one-element LIST
    (`rest == [7]`, not `7`). These two lowerings have no shared row to slice
    — the pair is synthesized slot by slot — so this is the
    `_emit_starred_slot_list` counterpart for "the remainder is a value, not
    a range".

    `value_ctype` is the already-lowered value's C type and `value` its
    operand name; the element type recorded on the new list is `slot_elem`,
    which is the SEQUENCE's element type (what the value holds), not the
    value's C storage.
    """
    _nm = _as_str(name)
    gen._declare_var(_nm, 'MojoList *')
    if slot_elem and slot_elem != 'int64_t':
        gen._elem_types[_nm] = slot_elem
    _dst = gen._cname(_nm)
    _lst = gen._new_temp('MojoList *')
    gen._emit(f"  {_lst} = mojo_list_new ();")
    gen._emit(f"  {_dst} = {_lst};")
    if gimple_ctypes.TypeLattice.list_suffix(slot_elem) == 'str':
        gen._void_call('mojo_list_append_str',
                       [('MojoList *', _dst), ('char *', _as_str(value))])
    elif gimple_ctypes.TypeLattice.list_suffix(slot_elem) == 'double':
        gen._void_call('mojo_list_append_double',
                       [('MojoList *', _dst), ('double', _as_str(value))])
    else:
        _iv = gen._new_val('int64_t', f"(int64_t){_as_str(value)}")
        gen._void_call('mojo_list_append_int',
                       [('MojoList *', _dst), ('int64_t', _iv)])


def _emit_starred_slot_from_cstr(gen, name: str, cstr: str, start, stop) -> None:
    """`name = [cstr[i] for i in range(start, stop)]` — the starred slot of a
    for target whose item is a C STRING, one 1-character string per element.

    The shape is `for k, *rest in <dict>` and `for k, *rest in d.items()`'s
    sibling over a string item: CPython unpacks the item, a key is a `str`, and
    indexing a `str` yields a 1-character `str`, so the remainder is a list of
    1-character STRINGS — `for k, *rest in {"abc": 1}` gives `rest == ['b',
    'c']`, not `rest == "bc"` and not a list of ints. `mojo_cstr_slice(s, i,
    i + 1)` is therefore both the element producer and the reason this is a
    counted loop rather than one call: GIMPLE has no comprehension and no slice
    expression.

    This is the third member of one family and the shape of the first two, so it
    is written as the same three steps they are: declare `name` as a
    `MojoList *` and record its element type (the body must be able to print and
    len it as the list Python bound — that is the whole point of the star), make
    a fresh list, then append one element per index from `start` up to `stop`.
    `start`/`stop` are already-emitted int64_t operand NAMES rather than
    literals, for the reason `starred_slot_index` gives: a starred slot's bounds
    depend on the item's RUNTIME length, and the slots after the star are counted
    from its end.

    `cstr` is the item as a C string. It is `const char *` on the dict-key path
    (`mojo_dict_iter_key`), and `mojo_cstr_slice` takes `char *`, so the
    const is cast away here rather than at the call site.
    """
    _nm = _as_str(name)
    gen._declare_var(_nm, 'MojoList *')
    gen._elem_types[_nm] = 'char *'
    _dst = gen._cname(_nm)
    _lst = gen._new_temp('MojoList *')
    gen._emit(f"  {_lst} = mojo_list_new ();")
    gen._emit(f"  {_dst} = {_lst};")
    _src = gen._new_val('char *', f"(char *){_as_str(cstr)}")
    _i = gen._new_val('int64_t', _as_str(start))
    _cond = gen._new_bb(); _body = gen._new_bb(); _after = gen._new_bb()
    gen._emit(f"  goto {_cond};")
    gen._emit_label(_cond)
    _c = gen._new_val('_Bool', f"{_i} < {_as_str(stop)}")
    gen._emit(f"  if ({_c}) goto {_body}; else goto {_after};")
    gen._emit_label(_body)
    _one = gen._new_val('int64_t', "1LL")
    _next = gen._new_val('int64_t', f"{_i} + {_one}")
    _stop = gen._new_val('int64_t', f"{_next}")
    _chr = gen._new_val('char *', f"mojo_cstr_slice ({_as_str(_src)}, {_i}, "
                                  f"{_as_str(_stop)})")
    gen._void_call('mojo_list_append_str',
                   [('MojoList *', _dst), ('char *', _as_str(_chr))])
    gen._emit(f"  {_i} = {_next};")
    gen._emit(f"  goto {_cond};")
    gen._emit_label(_after)


def _gfl_declare_target_name(gen, shadow_name, vn: str, se: str) -> None:
    """Hoisted out of `_gen_for_list` (recursive nested closure) — the
    lifted-closure-env determinism fix; `gen`/`shadow_name` threaded."""
    if vn.startswith('(') and vn.endswith(')'):
        for _nv in gen._split_top_level_comma(vn[1:-1].strip()):
            _gfl_declare_target_name(gen, shadow_name, _nv, 'int64_t')
    else:
        gen._declare_var(vn, se, force=(vn == shadow_name))

