"""Shared middle-end extracted from gimple_gen_stmts.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _as_str, _pair_key
import regex_compile
import mlir
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

# With-alias naming lives in the light mojo.middle.boundnames module
# (formal imports that directly; this file re-exports so emit_stmts'
# `from mojo.middle.stmts_shared import _with_item_alias_name` keeps working).
from mojo.middle.boundnames import _with_item_alias_name

def _annotation_dict_val_type(gen, ann) -> str | None:
    """`dict[K, V]` / `Dict[K, V]` annotation → the dict's VALUE C type,
    else None. Seeds _dict_val_types so dict.items()/d[k] reads pick the
    right accessor for a string-valued dict (without it, `self._str_pool:
    dict[str, str]` in __init__ left the value type unknown, and the
    self-hosted string-pool loop read the boxed value slot via get_int,
    emitting `static char * <address> = "<address>"` instead of
    `_slit_N = "text"`)."""
    if isinstance(ann, str):
        s = ann.strip()
        if s.startswith('dict[') or s.startswith('Dict['):
            inner = s.split('[', 1)[1].rstrip(']').strip()
            parts = gimple_ctypes._split_top_level_commas(inner)
            if len(parts) >= 2:
                return gen._resolve_type(parts[1].strip())
    return None

def _annotation_dict_nested_val_type(gen, ann) -> str | None:
    """For `dict[K, dict[K2, V2]]` → the inner dict's value C type (`V2`);
    for `dict[K, list[E]]` / `dict[K, set[E]]` → the inner container's
    ELEMENT C type (`E`). So a `field[k]` / `field.get(k, ...)` /
    `field.items()` read one level down carries a real type instead of
    boxing. None otherwise."""
    if isinstance(ann, str):
        s = ann.strip()
        if s.startswith('dict[') or s.startswith('Dict['):
            inner = s.split('[', 1)[1].rstrip(']').strip()
            parts = gimple_ctypes._split_top_level_commas(inner)
            if len(parts) >= 2:
                v = parts[1].strip()
                vbase = v.split('[', 1)[0].strip()
                if vbase in ('dict', 'Dict') and '[' in v:
                    vparts = gimple_ctypes._split_top_level_commas(
                        v.split('[', 1)[1].rstrip(']').strip())
                    if len(vparts) >= 2:
                        return gen._resolve_type(vparts[1].strip())
                if vbase in ('list', 'List', 'set', 'Set', 'frozenset') and '[' in v:
                    eparts = gimple_ctypes._split_top_level_commas(
                        v.split('[', 1)[1].rstrip(']').strip())
                    if len(eparts) == 1 and eparts[0].strip():
                        _e = gen._resolve_type(eparts[0].strip())
                        return _e if _e and _e != 'int64_t' else None
    return None

def _iter_ast(n):
    """Return `n` and every AST descendant (attribute + list-attribute
    children), as a list, in the same pre-order sequence a recursive
    `yield`/`yield from` walk would produce. Mirrors gimple_gen_coro._walk.

    Deliberately NOT a generator (it used to be): a `yield`/`yield from`
    function compiles to a REAL stack-switching coroutine in this
    codegen, and this runtime's own docs (runtime/fire_runtime.h) already
    flag that "a coroutine body can't use setjmp/longjmp directly" — the
    C stack frame that ran `setjmp()` for some OTHER try/except elsewhere
    in this compiler's own pipeline no longer exists once a coroutine has
    suspended onto its own separate fiber stack, so a `mojo_raise()`
    firing while this walk is mid-iteration can longjmp across that fiber
    boundary — undefined behavior. Found via bugs/
    CODEGEN_noshim_dumpfull_preexisting_divergence.md: a zip()-nested-
    tuple ValueError (gimple_gen_loops.py's `_gen_for_zip`, meant to be
    caught locally by `_gen_stmt_ForStmt`'s try/except and fall back
    gracefully) instead escaped to the module-level handler ONLY when
    self-hosted — confirmed via lldb that the raise fires from inside
    `__mojo_coro_yield` while this exact function (as a compiled
    coroutine, `__mgco__iter_ast_body`) is suspended mid-walk.

    None of this function's 8 call sites need laziness (each one -
    `for`/list-comp/`sum(1 for ...)`/set-comp - fully consumes the
    result), so building a real list up front with an explicit stack
    avoids the coroutine machinery entirely for this internal walk."""
    result = []
    stack = [n]
    while stack:
        cur = stack.pop()
        result.append(cur)
        d = getattr(cur, '__dict__', None)
        if not d:
            continue
        children = []
        for v in d.values():
            if isinstance(v, list):
                for x in v:
                    if hasattr(x, '__dict__'):
                        children.append(x)
            elif hasattr(v, '__dict__'):
                children.append(v)
        # Push in reverse so children still pop (and thus visit their
        # own full subtrees) in original left-to-right order.
        stack.extend(reversed(children))
    return result

def _seed_genexp_list_narrowing(gen, func_node):
    """Pre-pass: find `name = (<generator expression>)` local assignments
    whose `name` is then consumed EXACTLY ONCE, in an iterating position
    (`for _ in name`, or `... for x in name ...` inside another
    comprehension), and mark `name` for materialisation as a real list.

    A generator expression consumed a single time by a forward iteration is
    semantically identical to the equivalent list comprehension, and the
    scalar codegen model has no lazy-generator-object-in-a-local
    representation. Deliberately conservative: a name read more than once,
    never iterated, or used where laziness matters is left untouched (its
    existing behaviour / honest refusal stands). See
    bugs/COMPILE_FAIL_zipfile___init__.md blocker 3.
    """
    body = getattr(func_node, 'body', None) or []
    # Names the function pins via `global`/`nonlocal` are out of scope.
    pinned = set()
    for n in _iter_ast(func_node):
        if isinstance(n, GlobalStmt):
            for nm in (getattr(n, 'names', None) or []):
                pinned.add(_as_str(nm))

    def _assign_target_ids(root):
        out = set()
        for n in _iter_ast(root):
            tgts = []
            if isinstance(n, (AssignStmt, AugAssignStmt, ForStmt)):
                tgts = [n.target]
            elif isinstance(n, MultiAssignStmt):
                tgts = list(getattr(n, 'targets', []) or [])
            for t in tgts:
                if isinstance(t, IdentExpr):
                    out.add(id(t))
        return out

    def _reads_of(root, name, skip_ids):
        return [n for n in _iter_ast(root)
                if isinstance(n, IdentExpr) and n.name == name
                and id(n) not in skip_ids]

    # Flow-ordered scan over the function's TOP-LEVEL statement list: for a
    # `name = (<genexp>)` assignment, the FIRST later sibling that reads
    # `name` must read it exactly once, as a `for`/comprehension iterable.
    for i, stmt in enumerate(body):
        if not (isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr)
                and _is_genexp(stmt.value)):
            continue
        name = stmt.target.name
        if name in pinned:
            continue
        # `name` must not be a genexp target more than once anywhere.
        if sum(1 for n in _iter_ast(func_node)
               if isinstance(n, AssignStmt) and isinstance(n.target, IdentExpr)
               and n.target.name == name and _is_genexp(n.value)) != 1:
            continue
        narrow_ids = {id(x) for x in _iter_ast(stmt.value)}
        consumer = None
        for later in body[i + 1:]:
            if _reads_of(later, name, narrow_ids):
                consumer = later
                break
        if consumer is None:
            continue
        skip = _assign_target_ids(consumer) | narrow_ids
        reads = _reads_of(consumer, name, skip)
        if len(reads) != 1:
            continue
        the_read = reads[0]
        ok_iter = any(
            isinstance(n, (Generator, ForStmt))
            and getattr(n, 'iterable', None) is the_read
            for n in _iter_ast(consumer))
        if ok_iter:
            gen._genexp_narrow_names.add(name)

def _assign_target(gen, tgt, et, ev):
    """Assign a lowered value (et, ev) to one unpack target, which may be a
    plain name or a nested tuple (e.g. (a, b), (c, d) = ...). Recurses for
    nested tuples by indexing the inner iterable."""
    if isinstance(tgt, gimple_ctypes.IdentExpr):
        if tgt.name not in gen.var_types:
            hint = gen._inferred_var_types.get(gen.current_func_name, {}).get(tgt.name) \
                if hasattr(gen, '_inferred_var_types') else None
            # `or 'int64_t'` fallback: an unpack element whose real type could
            # not be resolved arrives as '' here, and declaring a local with
            # the EMPTY type produced `a = ()_t5;` (an empty cast — not even
            # valid C) at the later assignment. Repro:
            # std/test/builtin/test_int.mojo's `var a, b = divmod(7, 3)`.
            gen._declare_var(tgt.name, hint or et or 'int64_t')
        gen._track_pointer_actual_type(tgt.name, gen.var_types[tgt.name], ev, et)
        gen._safe_coerce_emit(et, gen.var_types[tgt.name], ev, gen._write_dest(tgt.name))
        # A `MojoBoundMethod *` value stored into a local whose declared C
        # type is NOT `MojoBoundMethod *` (a var-type-inference join with
        # another branch's plain fn-pointer / lambda value collapsed it to
        # `void *`/`int64_t`, e.g. `if c: f = lambda: 42 else: f =
        # self.tell`). A later `f()` must dispatch dynamically: a bound
        # method needs `self` re-supplied, a plain fnptr must not. Record
        # the name so _lower_call routes it through mojo_maybe_bound_call_N.
        if et == 'MojoBoundMethod *' and gen.var_types.get(tgt.name) != 'MojoBoundMethod *':
            gen._bm_tainted_locals.add(tgt.name)
            _brt = gen._bound_method_ret_types.get(ev)
            if _brt:
                gen._bound_method_ret_types[tgt.name] = _brt
    elif isinstance(tgt, (gimple_ctypes.TupleExpr, gimple_ctypes.ListExpr)):
        # A list-pattern target (`[a] = ...` / `[a, b] = ...`) is
        # semantically identical to the tuple-pattern spelling (`a, = ...`
        # / `a, b = ...`) — same `.elements` shape, same unpack — so it
        # shares this branch exactly rather than a parallel implementation.
        # ev is itself an iterable; view it as a MojoList* and unpack by
        # index. DESIGN.html R1/R5: shares _materialize_as_list with all()/
        # any()/enumerate()/*.join() - `a, b = some_dict` is real Python
        # (unpacks the dict's keys), not just an ambiguous boxed handle.
        lp = gen._materialize_as_list(et, ev)
        for i, sub in enumerate(tgt.elements):
            idx64 = gen._new_val('int64_t', f"(int64_t){i}")
            elem_type = gen._elem_of(lp)
            suf = gimple_ctypes.TypeLattice.list_suffix(elem_type)
            set_et = elem_type if elem_type != 'unknown' else 'int64_t'
            sev = gen._new_val(set_et, f"mojo_list_get_{suf} ({lp}, {idx64})")
            gen._assign_target(sub, set_et, sev)

def _is_except_as_member_target(gen, obj_node) -> bool:
    """True when `obj_node` (a MemberExpr's `.obj`) is a bare identifier
    currently bound by an enclosing `except <ExcType> as <name>:` clause
    — see `self._except_as_names`'s own docstring. Deliberately keyed off
    this SYNTACTIC fact (which name was introduced by an except-as
    binding), not the receiver's C type (`char *`), so this can never
    accidentally match an ordinary string variable that merely happens
    to share a name — an ordinary string is never added to
    `_except_as_names` in the first place. See bugs/hard/
    CODEGEN_dynamic_attribute_on_generic_object.md's "Residual gap"
    section for why the type-keyed alternative was rejected."""
    return (isinstance(obj_node, gimple_ctypes.IdentExpr)
            and obj_node.name in gen._except_as_names)

def _narrow_key_for_expr(gen, e) -> str:
    """The `_narrowed_exprs` key for an expression the compiler can track
    across an `isinstance` guard — an IdentExpr, or a MemberExpr whose base
    is an IdentExpr (`node.target`, `self.x`). "" for anything else."""
    if isinstance(e, gimple_ctypes.IdentExpr):
        return f'i:{e.name}'
    if (isinstance(e, gimple_ctypes.MemberExpr)
            and isinstance(e.obj, gimple_ctypes.IdentExpr)):
        return f'm:{e.obj.name}.{e.member}'
    return ''

def _isinstance_narrow_struct(gen, type_arg) -> str:
    """If `type_arg` names a single struct known to this codegen (a bare
    `IdentExpr('IdentExpr')` or the `gimple_ctypes.IdentExpr` MemberExpr
    spelling this codebase uses), return that bare struct name, else "".
    A tuple of types yields "" (no single type to narrow to)."""
    tn = ''
    if isinstance(type_arg, gimple_ctypes.IdentExpr):
        tn = type_arg.name
    elif (isinstance(type_arg, gimple_ctypes.MemberExpr)
          and isinstance(type_arg.obj, gimple_ctypes.IdentExpr)):
        tn = type_arg.member
    if tn and tn in gen.struct_field_types:
        return tn
    return ''

def _collect_isinstance_narrowings(gen, cond, out: list) -> None:
    """Walk `cond` for `isinstance(E, Struct)` tests (bare, or joined by
    `and`) and append (narrow_key, 'Struct *', E) for each trackable E."""
    if isinstance(cond, gimple_ctypes.BinaryOp) and cond.op == 'and':
        gen._collect_isinstance_narrowings(cond.left, out)
        gen._collect_isinstance_narrowings(cond.right, out)
        return
    if (isinstance(cond, gimple_ctypes.CallExpr)
            and isinstance(cond.func, gimple_ctypes.IdentExpr)
            and cond.func.name == 'isinstance'
            and len(cond.args) == 2
            and not gen._locally_binds_name('isinstance')):
        key = gen._narrow_key_for_expr(cond.args[0])
        sn = gen._isinstance_narrow_struct(cond.args[1])
        if key and sn:
            out.append((key, sn + ' *', cond.args[0]))

def _handler_exc_name(gen, h):
    if h.exc_type is None:
        return None
    # `except (A, B):` stores a list of type-name strings; use the first
    # as the representative name (typed/bare classification, binding
    # type). The full OR-match across all types is done via
    # _handler_exc_all_names in the dispatch loop.
    if isinstance(h.exc_type, list):
        if len(h.exc_type) > 0:
            return h.exc_type[0]
        return None
    if hasattr(h.exc_type, 'name'):
        return h.exc_type.name
    if isinstance(h.exc_type, str):
        # Step I (create_task/Task/TaskGroup/RaisingTask project):
        # real Mojo's `except e:` idiom — a BARE identifier with no
        # `as` — means "catch anything, bind it to e" (there is no
        # Python-style class named "e" being referenced; Mojo's
        # grammar reuses the same "type or name?" position Python's
        # `except <expr>:` uses, but a bare lowercase identifier that
        # ISN'T a real, known exception type is conventionally the
        # bind-all shorthand instead — confirmed via a hand repro
        # against this project's own interpreter: `except e: print(e)`
        # after `raise Error(...)` silently never caught anything
        # before this fix, exactly mirroring the bug this method's own
        # bare-string branch had). fire_compiler.py's parser has no
        # symbol table at parse time, so it can't distinguish these
        # up front — it always stores a bare identifier in `exc_type`
        # (see _parse_try's "the common case is a single ... exception
        # type" comment) — so the distinction has to be made HERE,
        # where struct_field_types/_KNOWN_EXCEPTION_NAMES are actually
        # available: only a name _is_exc_class_name confidently
        # recognizes as a real exception type (a builtin like
        # ValueError, or a user-defined struct) is treated as a real
        # type at all; anything else (test_raising_asyncrt.mojo's own
        # `except e:`/`except caught_err:`-style handlers) is
        # reported as untyped (None) here, which _gen_stmt_TryStmt's
        # typed/bare classification then correctly treats as a
        # catch-all — see _emit_except_handler's own mirrored fix for
        # the BINDING half of this (the name still needs to reach the
        # handler body as a real local, which `handler.name` alone
        # doesn't carry for this shape).
        if not gen._is_exc_class_name(h.exc_type):
            return None
        return h.exc_type
    return None

def _handler_bind_name(gen, h):
    """The real local variable name this handler's body should bind the
    caught exception to, or None if it doesn't bind one at all. Usually
    just `h.name` (an explicit `except ... as e:`) — but Mojo's `except
    e:` idiom (a bare identifier, no `as`) parses the name into
    `h.exc_type` instead (fire_compiler.py has no symbol table at parse
    time to tell "real type" and "bind-all name" apart — see
    _handler_exc_name's own docstring for the full rationale), so when
    `h.name` is empty but `h.exc_type` is a string _handler_exc_name
    does NOT recognize as a real exception type, THAT string is the
    intended bind name instead."""
    if h.name:
        return h.name
    if isinstance(h.exc_type, str) and gen._handler_exc_name(h) is None:
        return h.exc_type
    return None


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_stmts.py)
# ---------------------------------------------------------------------------

# --- dependency _is_genexp (from gimple_gen_stmts.py) ---
def _is_genexp(node) -> bool:
    return isinstance(node, Comprehension) and node.kind == 'generator'


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_stmts.py)
# ---------------------------------------------------------------------------

