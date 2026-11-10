"""
AST Interpreter for Mojo - executes parsed AST nodes from our parser.

This allows us to run Mojo code by:
1. Parsing .mojo files to AST
2. Executing AST via this interpreter
3. Comparing output to verify correctness

Eventually will be transpiled to .mojo for full bootstrap.
"""

import sys
import os
import re
import importlib
import types
import platform
import operator
import math
import collections
import builtins
import threading
from dataclasses import dataclass
import fire_compiler as N

# Operators handled by Interpreter._apply_compare_op — both eval_BinaryOp
# (a single comparison, e.g. plain `a < b`) and eval_CompareChain (Python
# chained comparisons, `a < b < c`) dispatch through this same set/method
# rather than duplicating the operator table.
_COMPARE_OPS = {'==', '!=', '<', '>', '<=', '>=', 'in', 'not in', 'is', 'is not'}

# Name the outermost `for` clause's already-evaluated iterable is bound to
# inside a generator expression's own scope, so the synthesized outer `for`
# iterates that name instead of re-evaluating the expression on first resume
# (see Interpreter._generator_expression). Dunder-ish to stay clear of any
# name a real program would use.
_GENEXP_ITER_NAME = '__mojo_genexp_iter__'


# ---------------------------------------------------------------------------
# CPython 3.15 "improved error messages" (What's New in 3.15): an UNCAUGHT
# AttributeError is printed with a suggestion computed at PRINT time from two
# fields the exception carries — `name` (the attribute that failed) and
# `obj` (the object the lookup ran on) — exactly the fields CPython's
# Lib/traceback.py reads (gh-146406, gh-136588). The machinery splits in two,
# mirroring CPython's own split:
#
#   * `_tag_attribute_error` — the RAISE half. Every missing-attribute
#     AttributeError in this file is built and tagged through it, so the
#     exception carries the context no matter how it surfaces.
#   * `attribute_error_suggestion` — the PRINT half. fire.py's top-level
#     error printing calls it for an uncaught AttributeError and appends its
#     result to the message. Because it runs at print time only, an
#     AttributeError caught in user code stays plain — the same
#     caught-plain/uncaught-suggested split CPython 3.15 measures.
#
# The fields are set with setattr() rather than member syntax because this
# file self-hosts and the self-hosting compiler has no field table for
# builtin exception attributes (the `e.code` note in fire.py).
# ---------------------------------------------------------------------------

def _tag_attribute_error(exc, obj, name, self_obj=None):
    """Attach CPython 3.15's `name`/`obj` fields to a missing-attribute
    AttributeError so the print-time suggestion pass can compute its hint
    from the real object, not by re-parsing the message string. `self_obj`
    is the `self` binding of the failing frame (None when there is none) —
    CPython reads it off the traceback for its hide_underscored refinement;
    this interpreter has no CPython frame for user code, so the raise site
    captures it here (see `_frame_self`)."""
    setattr(exc, 'name', name)
    setattr(exc, 'obj', obj)
    setattr(exc, 'self_obj', self_obj)
    return exc


def _frame_self(interp):
    """The `self` binding of `interp`'s current (innermost) scope, or None.

    This is the `frame.f_locals['self']` CPython 3.15's
    `_compute_suggestion_error` reads off the failing traceback frame, which
    this interpreter does not have: its user frames are Scope objects, and
    the scope current at the failing member access IS that frame. Direct
    `scope.vars` only, exactly like `_tag_name_error` — a `self` further up
    the chain is a closure/global, which CPython does not put in the failing
    frame's f_locals either."""
    if interp is None:
        return None
    scope = interp.scope
    if scope is not None and 'self' in scope.vars:
        return scope.vars['self']
    return None


def _tag_name_error(exc, scope, name):
    """Attach CPython 3.15's NameError-suggestion context to a `name` lookup
    failure, at RAISE time: the print-time half computes the suggestion from
    the failing frame's pool, but this interpreter's NameErrors carry no
    CPython traceback frame (they are raised by this file's Scope, not by
    CPython's name resolution), so the frame's contents are captured here,
    while the exception still carries exactly the frame that failed:

      * `name` — the lookup that failed (CPython's exc.name);
      * `candidates` — CPython's `f_locals + f_globals + f_builtins` of the
        failing frame. In this interpreter's scope model the current scope's
        vars are the frame locals and the module (root) scope's vars are the
        globals plus the builtins (setup_builtins binds them there); a
        module-level failure duplicates the root scope once, exactly as
        CPython duplicates the module dict (its f_locals IS its f_globals);
      * `self_obj` — the frame's `self` (None when absent), for CPython's
        `self.<name>` refinement (a bare name that is really an instance
        attribute of the frame's `self`).

    set with setattr() for the same self-host reason as
    `_tag_attribute_error` (no field table for builtin exception attributes).
    """
    root = scope
    while root.parent is not None:
        root = root.parent
    candidates = list(scope.vars)
    candidates = candidates + list(root.vars)
    self_obj = None
    if 'self' in scope.vars:
        self_obj = scope.vars['self']
    setattr(exc, 'name', name)
    setattr(exc, 'candidates', candidates)
    setattr(exc, 'self_obj', self_obj)
    return exc


# Cross-language / wrong-type AttributeError hints, ported from CPython
# 3.15.2's Lib/traceback.py `_CROSS_LANGUAGE_HINTS` (gh-146406). Each entry
# maps the wrong name to a list of (type, hint, is_raw) triples checked in
# order; the first isinstance() match wins. is_raw=False renders the hint as
# "Did you mean '.<hint>'?", is_raw=True renders it verbatim.
#
# The `update` entry names `frozendict` (Python 3.15+), so the type is looked
# up defensively — the tree's interpreter floor is 3.12 (CLAUDE.md) and a
# bare name would be a NameError on older hosts.
_FROZENDICT_TYPE = getattr(builtins, 'frozendict', None)
_UPDATE_ENTRIES = ((frozenset, "Did you mean to use a 'set' object?", True),)
if _FROZENDICT_TYPE is not None:
    _UPDATE_ENTRIES = _UPDATE_ENTRIES + (
        (_FROZENDICT_TYPE, "Did you mean to use a 'dict' object?", True),)
_CROSS_LANGUAGE_ATTR_HINTS = {
    # list -- JavaScript/Ruby equivalents
    'push': ((list, 'append', False),),
    'concat': ((list, 'extend', False),),
    # list -- Java/C# equivalents
    'addAll': ((list, 'extend', False),),
    'contains': ((list, "Use 'x in list'.", True),),
    # list -- wrong-type suggestion (user expected a set)
    'add': ((list, "Did you mean to use a 'set' object?", True),
            (frozenset, "Did you mean to use a 'set' object?", True)),
    # str -- JavaScript equivalents
    'toUpperCase': ((str, 'upper', False),),
    'toLowerCase': ((str, 'lower', False),),
    'trimStart': ((str, 'lstrip', False),),
    'trimEnd': ((str, 'rstrip', False),),
    # dict -- Java/JavaScript equivalents
    'keySet': ((dict, 'keys', False),),
    'entrySet': ((dict, 'items', False),),
    'entries': ((dict, 'items', False),),
    'putAll': ((dict, 'update', False),),
    'put': ((dict, 'Use d[k] = v.', True),),
    # tuple -- mutable method on immutable type (user expected a list)
    'append': ((tuple, "Did you mean to use a 'list' object?", True),),
    'extend': ((tuple, "Did you mean to use a 'list' object?", True),),
    'insert': ((tuple, "Did you mean to use a 'list' object?", True),),
    'remove': ((tuple, "Did you mean to use a 'list' object?", True),
               (frozenset, "Did you mean to use a 'set' object?", True)),
    # frozenset -- mutable method on immutable type (user expected a set)
    'discard': ((frozenset, "Did you mean to use a 'set' object?", True),),
    # frozenset/frozendict -- `update` on an immutable mapping/set
    'update': _UPDATE_ENTRIES,
    # float -- bitwise operators belong to int
    '__or__': ((float, "Did you mean to use an 'int' object? "
                       "Bitwise operators are not supported by 'float'.", True),),
    '__and__': ((float, "Did you mean to use an 'int' object? "
                        "Bitwise operators are not supported by 'float'.", True),),
    '__xor__': ((float, "Did you mean to use an 'int' object? "
                        "Bitwise operators are not supported by 'float'.", True),),
    '__lshift__': ((float, "Did you mean to use an 'int' object? "
                           "Bitwise operators are not supported by 'float'.", True),),
    '__rshift__': ((float, "Did you mean to use an 'int' object? "
                           "Bitwise operators are not supported by 'float'.", True),),
}


def _cross_language_attr_hint(obj, name):
    """CPython 3.15's `_get_cross_language_hint`: the static-table half of
    the suggestion, checked FIRST (it is more specific than distance).
    Returns the hint text, or None."""
    entries = _CROSS_LANGUAGE_ATTR_HINTS.get(name)
    if entries is None:
        return None
    for check_type, hint, is_raw in entries:
        if isinstance(obj, check_type):
            if is_raw:
                return hint
            return f"Did you mean '.{hint}'?"
    return None


# CPython 3.15's Levenshtein costs (Lib/traceback.py / Python/suggestions.c):
# a plain substitution or move costs 2, a case-only difference costs 1.
_ATTR_MOVE_COST = 2
_ATTR_CASE_COST = 1
_ATTR_MAX_CANDIDATE_ITEMS = 750
_ATTR_MAX_STRING_SIZE = 40

# CPython 3.10+ exposes the set of stdlib module names (used by the
# NameError "did you forget to import" refinement). Looked up defensively —
# the self-hosted binary's `sys` is a stub (sys.argv/sys.path only, see
# emit_exprs.py's module-attribute special cases), so a bare attribute read
# would raise there; the empty default just withholds that one refinement
# in the compiled path, like the other documented self-host gaps.
_STDLIB_MODULE_NAMES = getattr(sys, 'stdlib_module_names', ())


def _suggestion_normalize(name):
    """CPython 3.15's `_compute_suggestion_error` NFKC preamble, shared by ALL
    four branches (AttributeError, ModuleNotFoundError, ImportError,
    NameError): a non-ASCII name that changes under NFKC normalization is
    matched under its normalized form, and if that normalized form is present
    in the candidate pool it is the answer outright (a "found" miss is never
    suggested). Returns (normalized_name, was_changed)."""
    if name.isascii():
        return name, False
    try:
        import unicodedata
        normalized = unicodedata.normalize('NFKC', name)
    except ImportError:
        normalized = name
    if normalized == name:
        return name, False
    return normalized, True


def _attr_substitution_cost(a, b):
    """CPython 3.15.2's Python/suggestions.c substitution_cost, on bytes:
    the low-five-bits test is its ASCII case-fold (no two ASCII letters
    differ only in case can collide with a non-letter), then an explicit
    A-Z check. CPython runs the whole match on the UTF-8 bytes of the
    names, so a non-ASCII name gets exactly the C behavior."""
    if (a & 31) != (b & 31):
        # Not the same, not a case flip.
        return _ATTR_MOVE_COST
    if a == b:
        return 0
    if 65 <= a <= 90:
        a += 32
    if 65 <= b <= 90:
        b += 32
    if a == b:
        return _ATTR_CASE_COST
    return _ATTR_MOVE_COST


def _attr_levenshtein_distance(a: str, b: str, max_cost: int) -> int:
    """Port of CPython 3.15.2's Python/suggestions.c:levenshtein_distance —
    the engine behind `_suggestions._generate_suggestions`, the fast path
    Lib/traceback.py consults before its pure-Python fallback. (The
    fallback differs in a way that matters: it seeds best_distance with
    len(name) instead of infinity, silently dropping close matches on
    short names — 'ge' -> 'get', 'po' -> 'pop'.) CPython operates on the
    UTF-8 bytes of the names; we do the same. Single rolling row, common-
    affix trimming, early bail-out when the running minimum exceeds
    max_cost.

    The trimming is tracked as OFFSETS into the byte sequences rather than
    as slices: `a = a[pre:]` rebinds a local to a differently-typed value,
    which the self-host lowering cannot express — it cast the `MojoBytes *`
    to `char *` and ran the DP on a struct address, so this shape keeps
    the encoded sequences in their own variables and indexes them with
    `pre + i`."""
    a_bytes = a.encode('utf-8')
    b_bytes = b.encode('utf-8')
    if a_bytes == b_bytes:
        return 0

    # Trim away common affixes.
    pre = 0
    alen = len(a_bytes)
    blen = len(b_bytes)
    while pre < alen and pre < blen and a_bytes[pre] == b_bytes[pre]:
        pre += 1
    post = 0
    while post < alen - pre and post < blen - pre \
            and a_bytes[alen - 1 - post] == b_bytes[blen - 1 - post]:
        post += 1
    alen -= pre + post
    blen -= pre + post
    if alen == 0 or blen == 0:
        return _ATTR_MOVE_COST * (alen + blen)
    if alen > _ATTR_MAX_STRING_SIZE or blen > _ATTR_MAX_STRING_SIZE:
        return max_cost + 1

    # Prefer shorter buffer — the trim offsets are common to both
    # sequences, so each surviving range is [pre, pre + len).
    if blen < alen:
        a_bytes, b_bytes = b_bytes, a_bytes
        alen, blen = blen, alen

    # Quick fail when a match is impossible
    if (blen - alen) * _ATTR_MOVE_COST > max_cost:
        return max_cost + 1

    # Instead of producing the whole traditional len(a)-by-len(b)
    # matrix, we can update just one row in place.
    row = list(range(_ATTR_MOVE_COST, _ATTR_MOVE_COST * (alen + 1), _ATTR_MOVE_COST))

    result = 0
    for bindex in range(blen):
        bbyte = b_bytes[pre + bindex]
        distance = result = bindex * _ATTR_MOVE_COST
        minimum = sys.maxsize
        for index in range(alen):
            # 1) Previous distance in this row is cost(b[:bindex], a[:index])
            substitute = distance + _attr_substitution_cost(bbyte, a_bytes[pre + index])
            # 2) cost(b[:bindex], a[:index+1]) from previous row
            distance = row[index]
            # 3) existing result is cost(b[:bindex+1], a[:index])
            insert_delete = min(result, distance) + _ATTR_MOVE_COST
            result = min(insert_delete, substitute)

            # cost(b[:bindex+1], a[:index+1])
            row[index] = result
            if result < minimum:
                minimum = result
        if minimum > max_cost:
            # Everything in this row is too big, so bail early.
            return max_cost + 1
    return result


def _attr_cp_levenshtein_distance(a: str, b: str, max_cost: int) -> int:
    """Lib/traceback.py's pure-Python fallback (the pass CPython 3.15 runs
    when the C module finds nothing): the same rolling-row algorithm, but on
    CODE POINTS instead of UTF-8 bytes, and its substitution cost is
    `str.lower()`-based, so a Unicode case flip ('É'->'é') costs 1 here
    where the C byte pass (the low-five-bits trick) costs 2. On pure-ASCII
    input the two passes agree on distance, and the fallback's best_distance
    seed (len(name) rather than infinity) only ever TIGHTENS the window — so
    the fallback can only ADD a match when non-ASCII is involved, which is
    why `_attr_close_match` runs it only in that case."""
    if a == b:
        return 0

    # Trim away common affixes.
    pre = 0
    while pre < len(a) and pre < len(b) and a[pre] == b[pre]:
        pre += 1
    a = a[pre:]
    b = b[pre:]
    post = 0
    while post < len(a) and post < len(b) \
            and a[len(a) - 1 - post] == b[len(b) - 1 - post]:
        post += 1
    if post:
        a = a[:len(a) - post]
        b = b[:len(b) - post]
    if not a or not b:
        return _ATTR_MOVE_COST * (len(a) + len(b))
    if len(a) > _ATTR_MAX_STRING_SIZE or len(b) > _ATTR_MAX_STRING_SIZE:
        return max_cost + 1

    # Prefer shorter buffer
    if len(b) < len(a):
        a, b = b, a

    # Quick fail when a match is impossible
    if (len(b) - len(a)) * _ATTR_MOVE_COST > max_cost:
        return max_cost + 1

    # Instead of producing the whole traditional len(a)-by-len(b)
    # matrix, we can update just one row in place.
    row = list(range(_ATTR_MOVE_COST, _ATTR_MOVE_COST * (len(a) + 1), _ATTR_MOVE_COST))

    result = 0
    for bindex in range(len(b)):
        bchar = b[bindex]
        bchar_lower = bchar.lower()
        distance = result = bindex * _ATTR_MOVE_COST
        minimum = sys.maxsize
        for index in range(len(a)):
            # 1) Previous distance in this row is cost(b[:bindex], a[:index])
            # CPython's fallback `_substitution_cost`: equal -> 0, a
            # case-only flip -> _CASE_COST, else _MOVE_COST.
            achar = a[index]
            if bchar == achar:
                cost = 0
            elif bchar_lower == achar.lower():
                cost = _ATTR_CASE_COST
            else:
                cost = _ATTR_MOVE_COST
            substitute = distance + cost
            # 2) cost(b[:bindex], a[:index+1]) from previous row
            distance = row[index]
            # 3) existing result is cost(b[:bindex+1], a[index])

            insert_delete = min(result, distance) + _ATTR_MOVE_COST
            result = min(insert_delete, substitute)

            # cost(b[:bindex+1], a[:index+1])
            row[index] = result
            if result < minimum:
                minimum = result
        if minimum > max_cost:
            # Everything in this row is too big, so bail early.
            return max_cost + 1
    return result


def _suggestion_two_passes(d, name):
    """CPython 3.15's distance-match tail, shared by ALL four
    `_compute_suggestion_error` branches: the C module (`_suggestions`,
    Python/suggestions.c) on UTF-8 BYTES with best_distance seeded at
    infinity, then Lib/traceback.py's pure-Python fallback on CODE POINTS
    with best_distance seeded at len(name) — and the two DISAGREE on
    non-ASCII input (a Unicode case flip costs 2 in the byte pass, 1 in the
    fallback; byte windows are wider but byte distances are bigger too), so
    for example 'caf' -> 'café' is only found by the second pass. Returns the
    closest candidate, or None.

    `d` must already be branch-filtered (the underscore rule differs per
    branch: the attr branch hides underscored candidates for a non-
    underscored miss, the import branch only does so when `name_from` is
    non-underscored, the NameError and ModuleNotFoundError branches filter
    nothing) and `name` NFKC-normalized (the shared preamble). CPython's caps
    apply verbatim: the C-module pass is skipped at 750+ candidates, the
    fallback gives up at 751+ candidates and at a 40-code-point name. The
    AttributeError branch must additionally skip its nested check after a
    fallback cap — it decides that from the same caps, not from this
    function's return value (a cap and a genuine no-match both return
    None)."""
    # Pass 1: the C module, on UTF-8 bytes, best_distance seeded at
    # infinity, per-candidate max-distance window in BYTE lengths.
    pass1_ran = len(d) < _ATTR_MAX_CANDIDATE_ITEMS
    if pass1_ran:
        wrong_name_bytes = len(name.encode('utf-8'))
        best_distance = sys.maxsize
        suggestion = None
        for possible_name in d:
            if possible_name == name:
                # A missing attribute is "found". Don't suggest it (GH-88821).
                continue
            # No more than 1/3 of the involved characters should need changed.
            item_bytes = len(possible_name.encode('utf-8'))
            max_distance = (item_bytes + wrong_name_bytes + 3) * _ATTR_MOVE_COST // 6
            # Don't take matches we've already beaten.
            max_distance = min(max_distance, best_distance - 1)
            current_distance = _attr_levenshtein_distance(name, possible_name, max_distance)
            if current_distance > max_distance:
                continue
            if not suggestion or current_distance < best_distance:
                suggestion = possible_name
                best_distance = current_distance
        if suggestion is not None:
            return suggestion
    # Pass 2: the pure-Python fallback, on code points, best_distance
    # seeded at len(name). On pure-ASCII input it can only agree with or
    # tighten pass 1, so when pass 1 RAN it is only worth running when
    # non-ASCII is involved. That early return must NOT apply when pass 1
    # was skipped by the 750 cap: at exactly 750 candidates CPython's C
    # module gives up (its own cap) and the fallback is the only pass left,
    # and it runs for ASCII too (test_name_error_caps_match_cpython pins
    # the boundary).
    if len(d) > _ATTR_MAX_CANDIDATE_ITEMS:
        return None
    if len(name) > _ATTR_MAX_STRING_SIZE:
        return None
    if pass1_ran:
        _non_ascii = not name.isascii()
        if not _non_ascii:
            for n in d:
                if not n.isascii():
                    _non_ascii = True
                    break
        if not _non_ascii:
            return None
    wrong_name_len = len(name)
    best_distance = wrong_name_len
    suggestion = None
    for possible_name in d:
        if possible_name == name:
            # A missing attribute is "found". Don't suggest it (GH-88821).
            continue
        # No more than 1/3 of the involved characters should need changed.
        max_distance = (len(possible_name) + wrong_name_len + 3) * _ATTR_MOVE_COST // 6
        # Don't take matches we've already beaten.
        max_distance = min(max_distance, best_distance - 1)
        current_distance = _attr_cp_levenshtein_distance(name, possible_name, max_distance)
        if current_distance > max_distance:
            continue
        if not suggestion or current_distance < best_distance:
            suggestion = possible_name
            best_distance = current_distance
    return suggestion


def _suggestion_after_pool(d, name, not_normalized):
    """The tail of CPython 3.15's `_compute_suggestion_error` every branch
    shares AFTER its candidate pool is computed: the NFKC early return (a
    name that normalization changed and which the pool contains is the
    answer outright), then the distance match. Returns the suggestion or
    None."""
    if not_normalized and name in d:
        return name
    return _suggestion_two_passes(d, name)


def _safe_dir(obj):
    """CPython 3.15's `_get_safe___dir__` (its lazy-import filter has no
    counterpart in this dialect): the names a successful `obj.<name>` lookup
    could resolve to — the candidate pool CPython's traceback.py feeds its
    matcher — obj.__dir__(), with CPython's `type(obj).__dir__(obj)` fallback
    for the TypeError case (obj is a class), strings only, sorted. Shared by
    the AttributeError branch (`_attr_candidates`) and the ImportError
    branch (`import_error_suggestion`)."""
    try:
        names = obj.__dir__()
    except TypeError:
        names = type(obj).__dir__(obj)
    return sorted(n for n in names if isinstance(n, str))


def _attr_candidates(obj):
    """The names a successful `obj.<name>` lookup could resolve to — the
    candidate pool CPython's traceback.py feeds its matcher (its
    `_get_safe___dir__`, i.e. the object's dir()). For a MojoInstance the
    dir() machinery cannot see the Mojo method/alias tables (they live
    outside the Python type), so those are added explicitly; for a
    MojoClass, the methods/fields/aliases it presents. Host objects use
    `_safe_dir`."""
    if isinstance(obj, (MojoInstance, MojoClass)):
        names = set()
        if isinstance(obj, MojoInstance):
            names.update(obj.__dict__)
            names.update(obj._mojo_class.methods)
            names.update(obj._mojo_class.comptime_aliases)
        else:
            names.update(obj.methods)
            names.update(obj.comptime_aliases)
            for f in obj.fields:
                if hasattr(f, 'name'):
                    names.add(f.name)
        return sorted(n for n in names if isinstance(n, str))
    return _safe_dir(obj)


def _attr_close_match(obj, name, self_obj=None):
    """CPython 3.15's Levenshtein half of `_compute_suggestion_error`:
    the closest resolvable attribute name to a misspelled one, or None.

    Candidate filtering follows CPython: no underscored names unless the
    wrong name is underscored, OR the failing frame's `self` IS `obj`
    (CPython's hide_underscored refinement: `self.value` inside a method may
    suggest the private `self._value`, while the same misspell on the same
    object from outside the method may not). The raising half captures that
    frame `self` on the exception (`self_obj`); CPython reads it off the
    traceback, which this interpreter does not carry. The distance match
    itself is the engine every branch shares (`_suggestion_two_passes`); the
    caps live there too, and a fallback cap aborts CPython's function
    WITHOUT the nested check — so it is rechecked here (a cap and a genuine
    no-match both return None from the engine, but only the former must skip
    the nested check)."""
    name, not_normalized = _suggestion_normalize(name)
    d = _attr_candidates(obj)
    hide_underscored = name[:1] != '_'
    if hide_underscored and self_obj is not None and self_obj is obj:
        hide_underscored = False
    if hide_underscored:
        d = [n for n in d if n[:1] != '_']
    suggestion = _suggestion_after_pool(d, name, not_normalized)
    if suggestion is None and len(d) <= _ATTR_MAX_CANDIDATE_ITEMS \
            and len(name) <= _ATTR_MAX_STRING_SIZE:
        # If no direct attribute match found, check for nested attributes
        # (CPython's `_check_for_nested_attribute`: the What's New 3.15
        # `container.area` -> `.inner.area` case).
        suggestion = _attr_nested_match(obj, name, d)
    return suggestion


def _attr_nested_match(obj, name, candidates):
    """CPython 3.15's `_check_for_nested_attribute`: when no attribute of
    `obj` is a close match, look one level down — a member of obj that ITSELF
    has `name`. Returns the dotted path (`inner.area`) or None. Mirrors
    CPython's scan: ONLY non-underscored outer attributes — CPython re-
    filters here, so even an underscored misspelling on `object()` gets no
    nested suggestion (`__class__` does carry `__static_attributes__`, but
    the underscored outer attribute is out of scope) — capped at 20 in
    sorted order, errors while fetching a member are ignored (a failing
    member cannot be the answer). CPython also skips descriptor outer
    attributes and probes the member statically (`getattr_static`) so no
    getter runs during error printing; the `hasattr` here agrees on plain
    data and only diverges on a member whose `name` is a property that
    raises — an under-suggestion on a cold path, not a false one."""
    if isinstance(obj, MojoInstance):
        # Instance fields only — the plain data members, no method-table
        # values to fetch (CPython's equivalent skips descriptors for the
        # same reason: fetching them runs code during error printing).
        members = {n: obj.__dict__[n] for n in obj.__dict__
                   if isinstance(n, str) and n[:1] != '_'}
    else:
        members = {}
        checked = 0
        for n in candidates:
            if n[:1] == '_':
                continue
            if checked >= 20:
                break
            checked += 1
            try:
                members[n] = getattr(obj, n)
            except Exception:
                continue
    for n in sorted(members)[:20]:
        member = members[n]
        try:
            if hasattr(member, name):
                return f"{n}.{name}"
        except Exception:
            continue
    return None


def attribute_error_suggestion(obj, name, self_obj=None):
    """CPython 3.15's print-time AttributeError suggestion, as the suffix to
    append to the message: '' when there is nothing to add. Priority is
    CPython's: the static cross-language/wrong-type table first, then the
    distance-based close match (with the nested-attribute fallback). The
    renderings are CPython 3.15.2's verbatim (Lib/traceback.py).

    `obj` is the object the failed lookup ran on — which may itself be None
    (`None.append(1)`); CPython computes suggestions for that too (dunder
    candidates for underscored names), so there is no None short-circuit.
    The caller is responsible for only invoking this when the exception
    actually carried an `obj` field (see fire.py's `name` guard).

    `self_obj` is the failing frame's `self` captured at raise time (None
    when the frame had none) — CPython's traceback-frame input to the
    hide_underscored refinement, see `_attr_close_match`."""
    if not isinstance(name, str):
        return ''
    hint = _cross_language_attr_hint(obj, name)
    if hint:
        return f". {hint}"
    suggestion = _attr_close_match(obj, name, self_obj)
    if suggestion is None:
        return ''
    if suggestion.isascii():
        return f". Did you mean '.{suggestion}' instead of '.{name}'?"
    return f". Did you mean '.{suggestion}' ({suggestion!a}) instead of '.{name}' ({name!a})?"


def _module_not_found_candidates(name):
    """CPython 3.15's ModuleNotFoundError candidate pool: every module spec
    the import machinery can discover — for each finder in sys.meta_path
    that carries a `discover` hook (in 3.15 only PathFinder does), the specs
    it reports relative to the missing name's parent package. Mirrors
    traceback.py's `_compute_suggestion_error` MNE branch verbatim: a dotted
    miss probes `importlib.util.find_spec(parent)` (which yields None for a
    missing parent — discover(None) then lists top-level names, CPython's
    behavior), and ANY failure — e.g. a parent that is not a package
    (frozen `os`: `import os.path2` raises ValueError inside discover) —
    means no candidates at all, i.e. no suggestion."""
    try:
        import importlib.util
        parent_name = name.rpartition('.')[0]
        if parent_name:
            parent = importlib.util.find_spec(parent_name)
        else:
            parent = None
        d = []
        for finder in sys.meta_path:
            discover = getattr(finder, 'discover', None)
            if discover is not None:
                d += [spec.name for spec in discover(parent)]
    except Exception:
        return None
    return d


def module_not_found_suggestion(name):
    """CPython 3.15's print-time ModuleNotFoundError suggestion, as the
    suffix to append to the message: '' when there is nothing to add. The
    real ModuleNotFoundError already carries `name` (the module that was not
    found), so no raise-side tagging is needed. The rendering is 3.15.2's
    verbatim (`. Did you mean: '<s>'?` — the MNE branch has no `!a`
    rendering of its own; a module name is an identifier and CPython's MNE
    branch prints it bare)."""
    if not isinstance(name, str):
        return ''
    name, not_normalized = _suggestion_normalize(name)
    d = _module_not_found_candidates(name)
    if d is None:
        return ''
    suggestion = _suggestion_after_pool(d, name, not_normalized)
    if suggestion is None:
        return ''
    return f". Did you mean: '{suggestion}'?"


def import_error_suggestion(mod_name, name_from):
    """CPython 3.15's print-time ImportError suggestion for a `from X import
    Y` miss — an ImportError carrying `name` (module X) and `name_from`
    (attribute Y) — as the suffix to append: '' when there is nothing to
    add. Candidates are X's dir() (`_safe_dir`, CPython's `_get_safe___dir__`),
    re-filtered to non-underscored names when Y is non-underscored
    (CPython re-filters here, mirroring the attr branch), then the shared
    distance match. The rendering is 3.15.2's verbatim (`. Did you mean:
    '<s>'?`, with the `!a` parens for a non-ASCII suggestion).
    `__import__` failing (module X gone by print time) means no candidates,
    CPython's try/except-returns-None."""
    if not isinstance(name_from, str) or not isinstance(mod_name, str):
        return ''
    name, not_normalized = _suggestion_normalize(name_from)
    try:
        mod = __import__(mod_name)
        d = _safe_dir(mod)
    except Exception:
        return ''
    if name[:1] != '_':
        d = [x for x in d if x[:1] != '_']
    suggestion = _suggestion_after_pool(d, name, not_normalized)
    if suggestion is None:
        return ''
    if suggestion.isascii():
        return f". Did you mean: '{suggestion}'?"
    return f". Did you mean: '{suggestion}' ({suggestion!a})?"


def name_error_suggestion(name, candidates, self_obj):
    """CPython 3.15's print-time NameError suggestion, as the suffix to
    append to the message: '' when there is nothing to add. CPython reads
    the failing frame's pool (f_locals + f_globals + f_builtins) and `self`
    off the traceback at print time; this interpreter's NameErrors carry
    those captured at RAISE time instead (`_tag_name_error`), so `candidates`
    and `self_obj` are the fields the exception carries — `candidates` None
    for a NameError that never went through this interpreter's Scope (e.g.
    one CPython raised itself), for which there is no frame to read and no
    suggestion, exactly CPython's tb-is-None behavior.

    CPython's order: the NFKC early return, then the `self.<name>`
    refinement (a bare name that is really an instance attribute of the
    frame's `self`), then the shared distance match. The renderings are
    3.15.2's verbatim (`. Did you mean: '<s>'?` with `!a` parens for a
    non-ASCII suggestion), plus CPython's forgot-to-import refinement: when
    the misspelling IS a stdlib module name, append ` Or did you forget to
    import '<name>'?` after a suggestion, or `. Did you forget to import
    '<name>'?` when there is none."""
    if not isinstance(name, str) or candidates is None:
        return ''
    d = [x for x in candidates if isinstance(x, str)]
    name_n, not_normalized = _suggestion_normalize(name)
    suggestion = None
    if not_normalized and name_n in d:
        suggestion = name_n
    else:
        if self_obj is not None:
            try:
                if hasattr(self_obj, name_n):
                    suggestion = f"self.{name_n}"
            except Exception:
                pass
        if suggestion is None:
            suggestion = _suggestion_after_pool(d, name_n, not_normalized)
    if suggestion is None:
        if name in _STDLIB_MODULE_NAMES:
            return f". Did you forget to import '{name}'?"
        return ''
    if suggestion.isascii():
        suffix = f". Did you mean: '{suggestion}'?"
    else:
        suffix = f". Did you mean: '{suggestion}' ({suggestion!a})?"
    if name in _STDLIB_MODULE_NAMES:
        suffix += f" Or did you forget to import '{name}'?"
    return suffix


def error_suggestion_suffix(e):
    """CPython 3.15's print-time suggestion suffix for ANY of the exception
    types its improved error messages cover — AttributeError,
    ModuleNotFoundError, ImportError (a `from X import Y` miss, the ones
    carrying `name_from`), NameError — '' when CPython appends nothing.
    fire.py appends it to an UNCAUGHT exception's message; an exception
    caught in user code never goes through it, preserving CPython's
    caught-plain/uncaught-suggested split.

    The dispatch mirrors Lib/traceback.py's order: ModuleNotFoundError
    before a bare ImportError (it is an ImportError subclass), and only
    `from`-miss ImportErrors carry `name_from`, so the two are disjoint in
    practice. Every guard is the one CPython applies (a str `name` field,
    `name_from is not None`, ...)."""
    if isinstance(e, AttributeError):
        aname = getattr(e, 'name', None)
        if isinstance(aname, str):
            return attribute_error_suggestion(
                getattr(e, 'obj', None), aname,
                getattr(e, 'self_obj', None))
        return ''
    if isinstance(e, ModuleNotFoundError):
        mname = getattr(e, 'name', None)
        if isinstance(mname, str):
            return module_not_found_suggestion(mname)
        return ''
    if isinstance(e, ImportError):
        fname = getattr(e, 'name_from', None)
        if isinstance(fname, str):
            return import_error_suggestion(getattr(e, 'name', None), fname)
        return ''
    if isinstance(e, NameError):
        nname = getattr(e, 'name', None)
        if isinstance(nname, str):
            return name_error_suggestion(
                nname, getattr(e, 'candidates', None), getattr(e, 'self_obj', None))
        return ''
    return ''


class ReturnValue(Exception):
    """Exception used to implement return statements."""
    def __init__(self, value=None):
        self.value = value


class BreakException(Exception):
    """Exception used to implement break statements."""
    pass


class ContinueException(Exception):
    """Exception used to implement continue statements."""
    pass


class MojoError(Exception):
    """Real Mojo's builtin `Error` type — `raise Error("message")`. A real
    Python Exception subclass (not MojoRaisedException-wrapped) so a plain
    `except Exception:`/`except:` catches it via ordinary isinstance(),
    same as any other real exception here. Calls `Exception.__init__`
    directly rather than via `super()` — this file self-hosts, and the
    self-hosting compiler doesn't know what to do with `super()` at all
    (tries to call it as a plain undefined function named `_super`)."""
    def __init__(self, *args):
        self.args = args
        Exception.__init__(self, *args)


class MojoRaisedException(Exception):
    """Marker exception for whatever value a Mojo `raise value` statement
    raised (a bare string, or an instance of a user-defined exception
    struct — see execute_RaiseStmt) that isn't already a real Python
    exception. Deliberately carries no fields/payload of its own — the
    self-hosting compiler (this file compiles itself) types an
    `except X as e:` binding as either a known struct pointer or a plain
    `char *` message string, never a generic boxed value, so an attribute
    like `e.mojo_value` can't work once self-hosted. The actual raised
    value instead goes through Interpreter._raised_mojo_value (an
    ordinary, already-well-typed field on a well-known struct) — see
    execute_RaiseStmt/_matches_exc_type."""
    pass


class _LazyImportState:
    """Process-wide state for PEP 810 lazy imports (Python 3.15).

    `mode` mirrors `sys.set_lazy_imports`: 'normal' honours the `lazy`
    keyword and `__lazy_modules__` only, 'all' makes every import that can be
    lazy potentially lazy. (CPython 3.15.2 rejects 'none' — the pre-final
    PEP text listed it, the implementation does not — so this does too.)
    `filter` is the optional `sys.set_lazy_imports_filter` callable and
    `lazy_modules` is the `sys.lazy_modules` set of fully-qualified names
    currently held by an unresolved proxy.
    """
    def __init__(self):
        self.mode = 'normal'
        env_mode = os.environ.get('PYTHON_LAZY_IMPORTS')
        if env_mode == 'all':
            self.mode = 'all'
        self.filter = None
        self.lazy_modules = set()

    def set_mode(self, mode):
        if not isinstance(mode, str):
            raise TypeError("mode must be a string: 'normal' or 'all'")
        if mode not in ('normal', 'all'):
            raise ValueError("mode must be 'normal' or 'all'")
        self.mode = mode


_LAZY_IMPORT_STATE = _LazyImportState()


class _LazyImportTarget:
    """Resolution state shared by every name bound by ONE lazy import.

    A `lazy from m import a, b` statement loads `m` at most once, and only
    when the first of `a`/`b` is used; the other name stays unresolved.
    """
    def __init__(self, interp, module, alias=None, is_from=False, scope=None):
        self.interp = interp
        self.module = module
        self.alias = alias
        self.is_from = is_from
        # The lexical scope the import statement executed in. Lazy
        # resolution can happen much later, while `interp.scope` is some
        # other frame (a function call that first touched the name), so a
        # dotted sibling import's namespace chain must be built in THIS
        # scope, not whatever happens to be current at resolve time.
        self.scope = scope
        self.loaded = False
        self.value = None

    def load(self):
        if not self.loaded:
            if self.is_from:
                value = self.interp._resolve_from_import_module(self.module)
            else:
                value = self.interp._resolve_import_module(
                    self.module, self.alias, self.scope)
            self.value = value
            self.loaded = True
            _LAZY_IMPORT_STATE.lazy_modules.discard(self.module)
        return self.value

    def resolve_name(self, name):
        module = self.load()
        if module is None:
            raise ModuleNotFoundError(
                f"No module named {self.module!r}")
        _LAZY_IMPORT_STATE.lazy_modules.discard(self.module + '.' + name)
        return self.interp._resolve_from_import_name(module, self.module, name)


class LazyImportType:
    """The proxy bound by `lazy import` / `lazy from ... import` (PEP 810).

    The name is bound immediately so the module's import-time side effects —
    and any ImportError — are deferred until the first use of the name.
    `Scope.get` reifies the proxy and replaces the binding, so after first
    use the name is indistinguishable from an eager import; the dunder
    forwarding below covers the other ways a proxy can be reached (stored in
    a container, passed as an argument, printed directly).

    `resolve()` is the explicit reification entry point CPython exposes on
    `types.LazyImportType`.
    """
    __slots__ = ('_target', '_label', '_from_name', '_resolved', '_value')

    def __init__(self, target, label, from_name=None):
        self._target = target
        self._label = label
        self._from_name = from_name
        self._resolved = False
        self._value = None

    def resolve(self):
        if not self._resolved:
            if self._from_name is None:
                value = self._target.load()
            else:
                value = self._target.resolve_name(self._from_name)
            self._value = value
            self._resolved = True
        return self._value

    def __repr__(self):
        return f"<lazy_import {self._label!r}>"

    def __getattr__(self, name):
        return getattr(self.resolve(), name)

    def __call__(self, *args, **kwargs):
        return self.resolve()(*args, **kwargs)

    def __getitem__(self, key):
        return self.resolve()[key]

    def __setitem__(self, key, value):
        self.resolve()[key] = value

    def __delitem__(self, key):
        del self.resolve()[key]

    def __iter__(self):
        return iter(self.resolve())

    def __len__(self):
        return len(self.resolve())

    def __contains__(self, item):
        return item in self.resolve()

    def __bool__(self):
        return bool(self.resolve())

    def __str__(self):
        return str(self.resolve())

    def __eq__(self, other):
        return self.resolve() == other

    def __ne__(self, other):
        return self.resolve() != other

    def __hash__(self):
        return hash(self.resolve())

    def __enter__(self):
        return self.resolve().__enter__()

    def __exit__(self, *args):
        return self.resolve().__exit__(*args)


class Scope:
    """Manages variable and function scopes."""
    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}
        # Names this scope's function declared `nonlocal`. A declaration
        # changes no value, so it belongs on the scope rather than in a
        # side table: a plain `x = ...` in a nested function is LOCAL by
        # default (Python's own rule, and this interpreter's long-standing
        # behaviour), and `nonlocal x` is exactly the statement that says
        # "except for this one". The assignment then writes the nearest
        # ENCLOSING binding instead of creating a local.
        self.nonlocals: set = set()

    def declare_nonlocal(self, name: str) -> None:
        self.nonlocals.add(name)

    def is_nonlocal(self, name: str) -> bool:
        return name in self.nonlocals

    def define(self, name: str, value):
        self.vars[name] = value

    def get(self, name: str):
        if name in self.vars:
            value = self.vars[name]
            if isinstance(value, LazyImportType):
                value = value.resolve()
                self.vars[name] = value
            return value
        # Walk the chain iteratively (the old recursion raised in the ROOT
        # scope): the lookup either finds the nearest binding in the same
        # order, or fails with the exception tagged at THIS scope — the
        # frame that failed — which is what CPython 3.15's print-time
        # NameError suggestion needs (see _tag_name_error).
        scope = self.parent
        while scope is not None:
            if name in scope.vars:
                value = scope.vars[name]
                if isinstance(value, LazyImportType):
                    value = value.resolve()
                    scope.vars[name] = value
                return value
            scope = scope.parent
        raise _tag_name_error(
            NameError(f"name '{name}' is not defined"), self, name)

    def has(self, name: str) -> bool:
        if name in self.vars:
            return True
        if self.parent:
            return self.parent.has(name)
        return False

    def set(self, name: str, value):
        if name in self.vars:
            self.vars[name] = value
        elif self.parent:
            self.parent.set(name, value)
        else:
            self.vars[name] = value

    def delete(self, name: str):
        if name in self.vars:
            del self.vars[name]
            return
        # Walk the chain iteratively (the old recursion raised in the ROOT
        # scope): the delete finds the nearest binding in the same order, or
        # fails with the exception tagged at THIS scope — the frame that
        # failed — for CPython 3.15's print-time NameError suggestion (see
        # _tag_name_error).
        scope = self.parent
        while scope is not None:
            if name in scope.vars:
                del scope.vars[name]
                return
            scope = scope.parent
        raise _tag_name_error(
            NameError(f"name '{name}' is not defined"), self, name)


def _split_invoker(owner_interp, args) -> tuple:
    """`(interpreter, args)` for a call that may still carry the interpreter
    as its first positional argument.

    Three spellings of "call me with the interpreter" reach a `MojoFunction`,
    and all three have to land on the same answer:

    1. `Interpreter.invoke` (and `MojoInstance`'s `method(interpreter, self)`)
       volunteer it positionally — the historical, mandatory convention;
    2. a BUILTIN that received the function as a callback
       (`sorted(key=f)`, `min(key=f)`, `map(f, xs)`, `list.sort(key=f)`) calls
       `f(*args)` with no interpreter at all, which used to hand the callee's
       FIRST REAL ARGUMENT over as the interpreter and die in `_invoke` with
       "AttributeError: 'int' object has no attribute 'scope'";
    3. an IMPORTED function, where the caller's interpreter and the one that
       DEFINED the function are different objects (`fire.py run` gives every
       imported module its own `Interpreter`, so `main` calling
       `alpha_module.sb1_probe_amb` arrives with the caller's instance in
       `args[0]` and the callee records the module's own).

    So the leading argument is recognised by TYPE, not by identity with
    `owner_interp`: case 3 is exactly the case where identity is the wrong
    test, and getting it wrong there passed the interpreter through as the
    function's first real argument — `sb1_probe_amb(x)` computed
    `<Interpreter> + 111` and died with "unsupported operand type(s) for +:
    'Interpreter' and 'int'" (test_module_cache.py's SB-1 per-scope-import
    row, which asserts the interpreter path and the compiled path agree).

    Identity is still consulted as a SECOND test, for a hand-constructed
    `MojoFunction` nobody recorded an owner on; and a positional fallback
    keeps the old convention working for one. A Mojo program cannot pass an
    `Interpreter` as a real argument in any spelling this file supports, so
    recognising one can never eat a value.
    """
    if args and isinstance(args[0], Interpreter):
        return args[0], args[1:]
    if owner_interp is not None:
        return owner_interp, args
    if args:
        return args[0], args[1:]
    return owner_interp, args


class MojoFunction:
    """Represents a function defined in Mojo code."""
    def __init__(self, name, params, body, closure_scope, comptime_params=None, param_defaults=None,
                 is_generator=False, is_async=False, interpreter=None,
                 comptime_param_defaults=None):
        self.name = name
        self.params = params
        self.body = body
        self.closure_scope = closure_scope
        # The interpreter that DEFINED this function, recorded so `__call__`
        # does not depend on the caller volunteering it. See `__call__`.
        self._interp = interpreter
        # Names from `def f[dtype: DType, ...](...)`'s bracketed generic
        # parameter list (see fire_compiler.py's _parse_generic_params_capture)
        # — bound by `__getitem__` when the call site subscripts the
        # function (`f[Int32](...)`, not passed as regular arguments.
        self.comptime_params = comptime_params or []
        # Declared DEFAULTS for those parameters — `def f[T, y=0, *,
        # linux=0]()`'s `y=0`/`linux=0`, kept by the parser in
        # FunctionDef.comptime_param_defaults. Separate from `_pd` (which
        # holds the RUNTIME parameters' defaults) because the two are
        # consumed differently: `_pd` is looked up per parameter while
        # binding call arguments and by `_trailing_default_at`'s positional
        # offset arithmetic (`len(dflts)` is the count of defaulted RUNTIME
        # slots), so a comptime default in there would shift every runtime
        # default's offset. Read in `_invoke` below, next to the `_pd` read,
        # so there is exactly one place a declared default is applied.
        self.comptime_param_defaults = comptime_param_defaults or {}
        if param_defaults:
            self._pd = param_defaults
        # Milestone 2 of INTERP_generator_yield_entirely_unimplemented:
        # mirrors FunctionDef.is_generator (see fire_compiler.py) — copied
        # onto the MojoFunction at construction time (see
        # execute_FunctionDef/execute_StructDef/execute_TraitDef) so
        # `_invoke` can branch to the generator-construction path without
        # needing the original FunctionDef node around at call time.
        self.is_generator = is_generator
        # Milestone 3b of INTERP_generator_yield_entirely_unimplemented:
        # mirrors FunctionDef.is_async (see fire_compiler.py) exactly the
        # same way is_generator mirrors FunctionDef.is_generator above —
        # copied onto the MojoFunction at construction time so `_invoke`
        # can branch to the coroutine-construction path without needing
        # the original FunctionDef node around at call time.
        self.is_async = is_async

    def __call__(self, *args, **kwargs):
        # The interpreter used to be a REQUIRED first positional argument, so
        # every caller had to know about it: `Interpreter.invoke` threads it
        # in, and a builtin that takes a callback (`sorted(key=...)`) had no
        # way to and handed the callee's FIRST REAL ARGUMENT over instead.
        # That is not a per-builtin bug — `sorted([1,2,3], key=lambda a: -a)`
        # died in `_invoke` with "AttributeError: 'int' object has no
        # attribute 'scope'", and every other Python callable that invokes a
        # value it was handed (`map(f, xs)`, `min(key=...)`, a `list.sort`
        # key, a callback this compiler never sees) has the same hole.
        #
        # So the interpreter is resolved HERE, from the function's own record
        # of the interpreter that defined it, and the positional convention
        # `Interpreter.invoke` still uses is recognised by `_split_invoker` —
        # which also covers the case where the two interpreters are NOT the
        # same object, which an imported function always is.
        #
        # The alternative — making every callback-taking builtin wrap its
        # callback in `_MojoInvokeWrapper` the way `map[f](...)` already does
        # — leaves the hole open for every callback site nobody enumerated.
        interp, args = _split_invoker(self._interp, args)
        return self._invoke(interp, {}, args, kwargs)

    def __getitem__(self, item):
        """`f[...]` at a call site: bind the bracket items to the declared
        comptime parameters BY POSITION (`_parse_generic_params_capture`'s
        docstring is the rule this implements) and answer a callable that
        still takes the call-time arguments.

        **An item with no parameter to bind it is REFUSED, and it used to be
        dropped.** `dict(zip(...))` stops at the shorter of the two, so
        `add[2, 5](x)` on a two-parameter `add` that declares no comptime
        parameter at all bound nothing, discarded both items, and went on to
        call `add(x)` — one argument for two parameters, which
        `_invoke` then bound as `a=x, b=None` and the body duly computed
        `x + None`. That is the whole reported symptom — "`add[2, 5](10)`
        answers None and then dies on `int + None`", the doc for which was
        deleted with the fix (`test_interp_oracle.py`'s
        `a_bracket_item_with_no_parameter_to_bind_is_refused` and
        `missing_required_argument_is_an_arity_error` pin both halves) — and
        the wrong answer is worse than the error the program deserves: a
        specialization is a type-level claim, so an item the declaration has
        nowhere to put is a program whose own signature refutes it, and this
        engine already refuses that claim on the other two paths —
        `formal/model.py`'s `value_call_bracket_reading` refuses a tuple index
        when it has the callee's declaration, and CPython refuses the subscript
        outright (`'function' object is not subscriptable`).

        The refusal names the function, how many items the bracket supplied and
        how many comptime parameters it declares, because "too many" is a
        different mistake from "too few" and the caller can only fix it if it
        is told which.
        """
        values = item if isinstance(item, tuple) else (item,)
        declared = len(self.comptime_params)
        if len(values) > declared:
            names = ', '.join(self.comptime_params)
            if not names:
                names = 'none'
            raise TypeError(
                f"{self.name}[...] supplies {len(values)} specialization "
                f"argument(s) but {self.name} declares {declared} comptime "
                f"parameter(s): {names}")
        bindings = dict(zip(self.comptime_params, values))
        return _MojoBoundComptimeFunction(self, bindings)

    def _invoke(self, interpreter, comptime_bindings, args, kwargs):
        # Create new scope for function execution
        func_scope = Scope(parent=self.closure_scope)

        for name, value in comptime_bindings.items():
            func_scope.define(name, value)

        # Bind comptime params that have defaults but weren't provided
        # (`self._pd` — the constructor stores param_defaults under that
        # name, see __init__; reading the constructor argument's name here
        # would always find nothing and silently drop every default value,
        # which is exactly the bug this line fixed — see the LambdaExpr
        # handler, whose `lambda x=5: ...` defaults rely on it working).
        # `self.comptime_param_defaults` is the same lookup for the
        # parameter list in the BRACKETS (`def f[T, y=0, *, linux=0]()`),
        # which is the only default source `f[T=Int]()` can have — the
        # bracket supplies every other value.
        _pdl = getattr(self, '_pd', None)
        _cpdl = getattr(self, 'comptime_param_defaults', None)
        for cp_name in self.comptime_params:
            if cp_name not in comptime_bindings:
                _found = False
                if _pdl is not None:
                    for _k, _v in _pdl:
                        if _k == cp_name:
                            func_scope.define(cp_name, interpreter.eval_expr(_v))
                            _found = True; break
                if not _found and _cpdl is not None and cp_name in _cpdl:
                    func_scope.define(cp_name, interpreter.eval_expr(_cpdl[cp_name]))
                    _found = True
                if not _found and cp_name not in func_scope.vars:
                    func_scope.define(cp_name, None)

        # Bind parameters to arguments.
        #
        # `*args` / `**kwargs` catch-alls arrive here still carrying their
        # stars (see _extract_param_names). Everything AFTER a `*` — whether
        # a named `*rest` or a bare `*` separator — is keyword-only and must
        # never consume a positional, exactly as in real Python.
        _pos_i = 0
        _seen_star = False
        _var_pos_name = ''
        _var_kw_name = ''
        _consumed_kw = []
        for param in self.params:
            if param.startswith('**'):
                _var_kw_name = param[2:]
                continue
            if param.startswith('*'):
                _var_pos_name = param[1:]  # '' for a bare `*` separator
                _seen_star = True
                continue
            if (not _seen_star) and _pos_i < len(args):
                func_scope.define(param, args[_pos_i])
                _pos_i += 1
            elif param in kwargs:
                func_scope.define(param, kwargs[param])
                _consumed_kw.append(param)
            else:
                _found = False
                if _pdl is not None:
                    for _k, _v in _pdl:
                        if _k == param:
                            func_scope.define(param, interpreter.eval_expr(_v))
                            _found = True; break
                # A parameter with NO value and NO declared default is an
                # ARITY ERROR, and it used to be a silent `None` here. That was
                # the root cause under the specialization-bracket bug, not the
                # bracket that found it: `add[2, 5](x)` used to report
                # "unsupported operand type(s) for +: 'int' and 'NoneType'", and
                # so did a plain `add(x)` with no bracket at all — the bracket
                # only supplied the missing argument. A body that runs with an
                # unbound parameter is the worst of the three answers available
                # (an error is recoverable, a wrong value is not), and CPython,
                # which this engine is measured against by
                # `test_interp_oracle.py`, raises here too.
                #
                # The message is CPython's own wording, because that suite
                # compares the two engines and a reader comparing them should
                # not have to learn two vocabularies for one mistake. A
                # keyword-only parameter gets CPython's other phrasing, which
                # is the same distinction Python draws: naming the parameter
                # and the way it had to be passed are both in it.
                #
                # `test_interp_oracle.py`'s
                # `missing_required_argument_is_an_arity_error` and
                # `test_runtime_diff.py`'s `main_takes_a_parameter` pin both
                # halves of this — the second one because making it an error
                # is what exposed `fire.py run` invoking `def main(n):` with no
                # argument at all, which is `_main_entry_args` there.
                if not _found:
                    if _seen_star:
                        raise TypeError(
                            f"{self.name}() missing required keyword-only "
                            f"argument: '{param}'")
                    raise TypeError(
                        f"{self.name}() missing required argument: '{param}'")
        # Leftover positionals -> `*rest`; leftover keywords -> `**kw`. Built
        # with plain loops rather than a slice/comprehension: this file is
        # itself self-hosted, and plain loops are what that compiler lowers
        # reliably (see the MojoGeneratorObject single-return note above for
        # the same class of concession).
        if _var_pos_name:
            _rest = []
            _ri = _pos_i
            while _ri < len(args):
                _rest.append(args[_ri])
                _ri += 1
            func_scope.define(_var_pos_name, _rest)
        if _var_kw_name:
            _rest_kw = {}
            for _kk in kwargs:
                if _kk not in _consumed_kw:
                    _rest_kw[_kk] = kwargs[_kk]
            func_scope.define(_var_kw_name, _rest_kw)

        if self.is_generator and self.is_async:
            # `async def f(): yield x` — a real async generator. Python's
            # actual protocol for these (`__aiter__`/`__anext__`, driven by
            # `async for`, not by plain `await`) is a THIRD distinct
            # protocol from both the sync-generator protocol
            # (MojoGeneratorObject: __iter__/__next__/send/throw) and the
            # coroutine protocol (MojoCoroutine: __await__) built for this
            # milestone — see INTERP_generator_yield_entirely_unimplemented's
            # Milestone 3b report. Deliberately NOT built here: rather than
            # silently picking one of the two existing wrappers (either
            # would behave subtly wrong under `async for`), fail loudly so
            # this reads as a known, documented gap rather than a silent
            # correctness bug.
            raise NotImplementedError(
                f"async generators (`async def {self.name}(): yield ...`) are not "
                f"yet supported by the interpreter — __aiter__/__anext__ protocol "
                f"is a documented follow-up gap, see Milestone 3b report")
        elif self.is_async:
            # Calling an async function must NOT run any of its body eagerly
            # — mirrors is_generator immediately below (same rationale: real
            # Python doesn't execute a single statement of a coroutine
            # function's body until something actually drives it via
            # __await__/.send()). Construct-and-return only; func_scope
            # becomes this coroutine's own private scope, swapped in by
            # MojoCoroutine around every resume — see its docstring.
            result = MojoCoroutine(interpreter, func_scope, self.body)
        elif self.is_generator:
            # Calling a generator function must NOT run any of its body —
            # real Python doesn't execute a single statement of a generator
            # function until the caller starts pulling values out of it.
            # Construct-and-return only; func_scope (with params/comptime
            # bindings already bound above, exactly like the eager path)
            # becomes this generator's own private scope, swapped in by
            # MojoGeneratorObject around every resume — see its docstring
            # for why the swap can't just happen once here.
            #
            # Routed through the same single `result`-variable/single-return
            # shape as the eager path just below (rather than an early
            # `return MojoGeneratorObject(...)`) deliberately: this file is
            # itself self-hosted (gimple_codegen.py compiles it), and that
            # compiler's return-type inference is a simple whole-function
            # unification that got confused by two differently-shaped
            # return statements in the same function (a boxed generic value
            # vs. a directly-constructed local struct type) — see
            # INTERP_generator_yield_entirely_unimplemented's
            # Milestone 2 report for the concrete compile errors this
            # produced before the fix.
            result = MojoGeneratorObject(interpreter, func_scope, self.body)
        else:
            # Execute function body
            old_scope = interpreter.scope
            interpreter.scope = func_scope
            try:
                for stmt in self.body:
                    interpreter.execute(stmt)
                result = None
            except ReturnValue as ret:
                result = ret.value
            finally:
                interpreter.scope = old_scope

        return result


class _RealAwaitStep:
    """Milestone 3b marker object: yielded (via a worker thread's
    `yield_fn`, exactly like a Mojo `yield` would be) by `eval_AwaitExpr`
    to mean "please advance THIS real iterator/generator (from a real
    native coroutine's `__await__()`, or another `MojoCoroutine`'s) by one
    step, on whatever thread is actually driving me" — see
    `_ThreadedGenerator._resume`'s handling of it for why this can't be
    stepped on the worker thread itself (real asyncio internals like
    `asyncio.sleep` call `get_running_loop()`, which is thread-affine —
    stepping them from the wrong OS thread raises
    `RuntimeError: no running event loop`, confirmed empirically while
    prototyping this milestone)."""
    __slots__ = ("it",)
    def __init__(self, it):
        self.it = it


class _RealThreadCall:
    """Milestone 3b marker, sibling to `_RealAwaitStep`: some real Python
    callables touch the running event loop the instant they're CALLED, not
    merely when later awaited — `asyncio.gather(...)`, `ensure_future`,
    `create_task`, `asyncio.Queue()`, etc. all call `get_running_loop()`/
    `get_event_loop()` eagerly at call time (confirmed empirically:
    `asyncio.gather(...)` invoked from a Mojo coroutine's worker thread
    raised `RuntimeError: no running event loop`, the exact same
    thread-affinity problem `_RealAwaitStep` solves for awaiting, but at
    call time instead of await time). `Interpreter.invoke` wraps any plain
    (non-Mojo) callable invocation made from inside a coroutine's worker
    thread in one of these and hands it to `yield_fn`, so
    `_ThreadedGenerator._resume` executes the call itself — a single
    one-shot step, not a multi-round drive like `_RealAwaitStep` — on
    whichever thread is actually driving this coroutine, then hands the
    result (or propagates the exception) straight back to the worker
    thread. Deliberately NOT applied to plain Mojo `yield` generators —
    only coroutines interact with an event loop, so
    `MojoGeneratorObject`/`_body_fn` never sets the `is_coroutine` TLS flag
    this is gated on, keeping the existing generator fast path completely
    unchanged."""
    __slots__ = ("func", "args", "kwargs")
    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs


class _ThreadedGenerator:
    """A from-scratch generator-protocol implementation (`.send()`/
    `.throw()`/`.close()`, raising `StopIteration` like a real Python
    generator does) backed by a dedicated worker `threading.Thread`,
    DELIBERATELY not using Python's native `yield` keyword anywhere in this
    file. `body_fn(yield_fn)` runs entirely on the worker thread; it calls
    `yield_fn(value)` to suspend and receive back whatever `.send()` later
    passes in, and its `return value` becomes `StopIteration(value)`.

    Why not just a plain Python generator function (as originally
    implemented -- see git history)? myinterpreter.py is itself one of the
    sources this project self-hosts (`fire.py` compiling its own source,
    `myinterpreter.py` included, via gimple_codegen.py). gimple_codegen.py's
    generator detection (added for real Mojo-language `yield` support)
    operates on the raw syntax tree it parses this file's own source into
    and cannot distinguish "this Python function happens to use `yield` as
    its own implementation technique" from "this is a user's Mojo generator
    function" -- see commit 7ab861d, which hit and fixed the identical
    problem in a different file (gimple_codegen.py's own internal
    tree-walkers used `yield` purely as an implementation detail) by
    rewriting them away from `yield` entirely. A single real `yield`
    anywhere in myinterpreter.py's own top-level function bodies makes
    gimple_codegen.py's module-level "fall back to interpreting from
    source" trigger for the WHOLE of myinterpreter.py -- which in turn broke
    `make check-selfhost`: other self-hosted modules calling into
    `Interpreter` methods generate a properly-typed extern declaration for
    them from myinterpreter.py's (normally available) static type info,
    while fire.py's own compiled code -- unable to get that info once
    myinterpreter.py falls back -- instead emits a bare variadic stub
    declaration for the very same C symbol. Two conflicting declarations of
    one symbol in a single linked program is a hard GCC error
    ("conflicting types for 'Interpreter_execute'"), confirmed by actually
    running `make check-selfhost` against a native-generator-based first
    draft of this mechanism.

    A worker-thread coroutine gives the exact same suspend-from-anywhere
    semantics as a native generator -- the Mojo body can `yield` from
    arbitrarily deep inside execute()/eval_expr()'s ordinary recursive call
    chain, with NO per-statement/per-expression-kind mirroring needed
    (unlike the reverted native-generator draft's parallel `_exec_gen`/
    `_eval_gen` dispatch family) -- without the keyword. Exactly one of
    {caller thread, worker thread} runs at a time, handed off via two
    `threading.Event`s: never real concurrency, just cooperative suspension
    implemented with a thread instead of a generator frame.

    Milestone 3b (async/await execution) REUSES this class as-is for
    `MojoCoroutine` too, rather than duplicating it — per CLAUDE.md's
    consolidation principle, the underlying "run this body on a worker
    thread, suspend via yield_fn+Events" mechanism is identical between a
    Mojo `yield` and a Mojo `await`; only the protocol MojoGeneratorObject
    vs. MojoCoroutine expose to their respective callers differs. To
    support `await`, `_resume` additionally recognizes when the worker
    yields a `_RealAwaitStep` (meaning: "step this real awaitable/
    MojoCoroutine, not the Mojo body, and don't wake the Mojo body up
    until that real thing is actually done") and drives it in a loop on
    the CALLING thread — see `_resume`'s docstring for why the calling
    thread specifically, not the worker thread, must do that stepping."""

    def __init__(self, body_fn):
        self._to_worker = threading.Event()
        self._to_caller = threading.Event()
        self._sent_value = None
        self._yielded_value = None
        self._inject_exc = None    # caller -> worker: exception to raise at the suspend point
        self._raised_exc = None    # worker -> caller: exception the body raised (propagates from send/throw)
        self._return_value = None
        self._done = False
        # Milestone 3b: set while `_resume` is mid-stepping a real awaitable
        # on behalf of `await` (see `_RealAwaitStep`) — non-None means "the
        # worker thread is parked waiting for the FINAL result of this real
        # await, don't resume it with an ordinary send/throw value; keep
        # stepping `it` instead" (see `_resume`).
        self._active_real_it = None

        def _yield_fn(value):
            self._yielded_value = value
            self._to_caller.set()
            self._to_worker.wait()
            self._to_worker.clear()
            if self._inject_exc is not None:
                exc, self._inject_exc = self._inject_exc, None
                raise exc
            return self._sent_value

        def _worker():
            self._to_worker.wait()
            self._to_worker.clear()
            try:
                if self._inject_exc is not None:
                    exc, self._inject_exc = self._inject_exc, None
                    raise exc
                self._return_value = body_fn(_yield_fn)
            except BaseException as e:
                self._raised_exc = e
            finally:
                self._done = True
                self._to_caller.set()

        # Deep *Mojo-level* recursion inside a generator body fans out into
        # many nested Python frames per Mojo call the same way fire.py's own
        # `interpret_and_execute` worker thread does (eval_expr ->
        # eval_CallExpr -> invoke -> _invoke -> execute -> ...) — the default
        # OS thread stack is nowhere near big enough. threading.stack_size()
        # is a process-global setting applied to threads created after the
        # call, matching the same pattern fire.py itself already uses.
        _old_stack_size = threading.stack_size()
        threading.stack_size(1024 * 1024 * 1024)
        try:
            self._thread = threading.Thread(target=_worker, daemon=True)
            self._thread.start()
        finally:
            threading.stack_size(_old_stack_size)

    def _resume_once(self):
        """The single Event-handoff step (exactly the original `_resume`
        body, pre-Milestone-3b): hand off to the worker thread and wait for
        it to either yield again or finish. Raises a BARE `StopIteration`
        (no constructor argument) when done — the return value is read
        back off `self._return_value` afterward instead of
        `StopIteration.value`/`.args` deliberately: this file self-hosts,
        and the compiler's exception model represents a raised exception as
        a type tag + opaque payload, not a real struct with a typed
        `.value`/`.args` field it can generate attribute-access code
        against (only `MojoError`'s dedicated `_raised_mojo_value` channel
        and plain string messages are supported that way) — reading a
        value off one of OUR OWN classes' ordinary fields instead sidesteps
        that entirely. Assumes `self._sent_value`/`self._inject_exc` are
        already set by the caller (`_resume`)."""
        self._to_worker.set()
        self._to_caller.wait()
        self._to_caller.clear()
        if self._done:
            exc, self._raised_exc = self._raised_exc, None
            if exc is not None:
                raise exc
            raise StopIteration
        return self._yielded_value

    def _resume(self):
        """Drives one logical send()/throw() step to completion, which may
        take MULTIPLE Event handoffs when a `_RealAwaitStep` is involved
        (Milestone 3b). Loop body, each pass:

        - If `self._active_real_it` is set, the worker is currently parked
          waiting on the FINAL outcome of a real await — step `it` itself
          right here, on THIS (the calling) thread. This is the crux of
          why real asyncio interop works at all: `it` is (transitively) a
          real native coroutine/Future's own `__await__()` iterator, and
          real asyncio internals like `asyncio.sleep` call
          `get_running_loop()`, which is thread-affine (fails with
          `RuntimeError: no running event loop` off the loop's own thread —
          confirmed empirically). Since `_resume` is always invoked by
          whatever thread is legitimately driving this coroutine/generator
          (the real event loop's Task-stepping code, for a top-level
          `await`; another worker thread, for Mojo-await-Mojo), stepping
          `it` HERE is always on a correct thread, transitively, all the
          way up the chain.
            - `it` raises `StopIteration(v)`: the real await is done;
              clear `_active_real_it` and loop back around to hand `v` to
              the worker as its ordinary yield_fn(...) return value —
              exactly as if the worker's `yield_fn` call is now returning.
            - `it` raises any other exception: same, but inject it instead
              (the worker's `yield_fn` call raises it, matching real
              `await`'s "the awaited thing raised" propagation).
            - `it` yields again (still not done, e.g. `Future.__await__`'s
              `yield self`): propagate that value straight back OUT to
              whoever is driving US, untouched, WITHOUT touching the
              worker thread at all — it stays parked. This is what lets a
              real `Future` bubble all the way up to real asyncio's Task
              machinery for actual timer/IO scheduling.
        - Otherwise, do one ordinary Event handoff (`_resume_once`). If the
          worker yielded a `_RealAwaitStep`, record its iterator as
          `_active_real_it` and loop back around (first step: send(None),
          matching how a freshly-`__await__()`-ed iterator is always first
          primed with `None`). Any other yielded value (a genuine Mojo
          `yield`, for MojoGeneratorObject) — or the worker finishing —
          returns/raises straight out to the caller, unchanged from
          pre-Milestone-3b behavior.

        Routed through `self._yielded_value` as the SOLE carrier of
        whatever this call ultimately returns, with exactly ONE textual
        `return self._yielded_value` statement at the very end (`break`
        out of the loop rather than returning from several different
        points) — deliberately, mirroring the documented
        `MojoFunction._invoke` workaround for `is_generator`/`is_async`:
        this file is itself self-hosted, and the self-hosted compiler's
        return-type inference is a simple whole-function unification that
        gets confused by differently-shaped return statements/fresh local
        variables in the same function — confirmed empirically while
        building this (an earlier draft using a fresh local `result`
        variable, even with a single `return result` statement, compiled
        fine interpreted but failed `make check-selfhost` with a gimple
        `non-trivial conversion in 'var_decl'` verifier error; routing
        through the ALREADY-established `self._yielded_value` field —
        whose type the inferencer already resolved correctly from
        `_yield_fn`'s pre-existing, unmodified assignment — fixed that.
        A SECOND, separate self-host failure of the same species hit right
        after: this method used to take `send_val`/`exc` as its own
        parameters (defaulting to `None`, reassigned across loop
        iterations to real objects/exceptions). The self-hosted compiler's
        exception representation is a `char *` message string (see
        `_resume_once`'s docstring), and a local/parameter that's
        SOMETIMES `None` (inferred `int64_t`) and SOMETIMES a real
        exception (`char *`) is a genuine, unreconcilable C type conflict
        for it — confirmed via the exact gimple dump
        (`int64_t / char * / exc = _t38;`). `send()`/`throw()` (below)
        instead set `self._sent_value`/`self._inject_exc` directly, the
        exact same pre-existing fields `_resume_once`/`_yield_fn` already
        use for this — proven to self-host correctly before this
        milestone touched anything — and `_resume` takes no parameters at
        all, consulting/updating only those fields."""
        while True:
            if self._active_real_it is not None:
                it = self._active_real_it
                try:
                    if self._inject_exc is not None:
                        e, self._inject_exc = self._inject_exc, None
                        step_result = it.throw(e)
                    else:
                        step_result = it.send(self._sent_value)
                        self._sent_value = None
                except StopIteration as si:
                    self._active_real_it = None
                    self._sent_value = si.value
                    self._inject_exc = None
                    continue
                except BaseException as e:
                    self._active_real_it = None
                    self._prime_inject(e)
                    continue
                self._yielded_value = step_result
                break
            y = self._resume_once()
            if isinstance(y, _RealAwaitStep):
                self._active_real_it = y.it
                self._sent_value = None
                self._inject_exc = None
                continue
            if isinstance(y, _RealThreadCall):
                # One-shot version of the above: execute the call itself
                # (not an iterator step) right here, on the correct
                # thread, then immediately hand the result/exception back
                # to the worker and loop around for its next suspension —
                # see _RealThreadCall's docstring.
                try:
                    call_result = y.func(*y.args, **y.kwargs)
                except BaseException as e:
                    self._prime_inject(e)
                else:
                    self._sent_value = call_result
                    self._inject_exc = None
                continue
            self._yielded_value = y
            break
        return self._yielded_value

    def send(self, value):
        if self._done:
            raise StopIteration
        self._sent_value = value
        self._inject_exc = None
        return self._resume()

    def throw(self, exc):
        if self._done:
            raise exc
        self._prime_inject(exc)
        return self._resume()

    def _prime_inject(self, exc):
        """Sets up `self._inject_exc`/`self._sent_value` for the next
        `_resume()` call to inject `exc` at the worker's suspension point —
        factored out of `throw()` (whose `self._inject_exc = exc` /
        `self._sent_value = None` pair is unchanged, just moved here) so
        `_resume`'s own real-await-exception-handling branches (Milestone
        3b) can reuse the EXACT SAME assignment shape for exceptions they
        catch via `except BaseException as e:` from a real iterator/call.
        This split mattered empirically, not just stylistically: assigning
        an except-as-bound exception straight into `self._inject_exc`
        inline inside `_resume`'s own try/except produced a genuine
        self-hosted gimple type conflict (`int64_t` vs. `char *` — an
        except-as binding apparently infers narrower than a same-shaped
        assignment reached via an ordinary function parameter). Passing it
        as a plain parameter across this method-call boundary instead —
        identical statement, different call site — self-hosts correctly."""
        self._inject_exc = exc
        self._sent_value = None

    def close(self):
        if self._done:
            return
        try:
            self.throw(GeneratorExit())
        except (GeneratorExit, StopIteration):
            pass


class MojoGeneratorObject:
    """Wraps the `_ThreadedGenerator` produced by driving a Mojo generator
    function's body through the ORDINARY, unmodified `execute()`/
    `eval_expr()` dispatch (see `_ThreadedGenerator`'s docstring for why a
    worker thread instead of a native Python generator), exposing the
    subset of Python's generator protocol Mojo programs can observe:
    `__iter__`, `__next__`, `.send()`, `.throw()`, `.close()`.

    THE SHARP EDGE: `interpreter.scope` is a single mutable attribute, not a
    parameter threaded through calls (see Scope/MojoFunction docstrings
    elsewhere in this file). A naive design would swap `interpreter.scope`
    to `func_scope` once when the underlying generator is first created and
    swap it back once when the generator finally completes -- mirroring how
    MojoFunction._invoke does it for an ordinary (non-suspending) call. That
    is wrong here: between any two resumes of a suspended generator, the
    interpreter keeps right on running other code (the code that called
    `next()`/`.send()`, possibly itself another generator's body) with
    `interpreter.scope` pointing wherever THAT code needs it to point.
    Interleaved generators (e.g. two counters advanced in lockstep by a
    `zip`-like loop) would otherwise read/write each other's locals -- even
    though each generator's body runs on its own dedicated OS thread, only
    one of {any generator's worker thread, the caller's thread} ever
    actually runs at a time (strict handoff via `_ThreadedGenerator`'s
    Events), so this is the exact same single-mutable-attribute hazard a
    native-generator design would have, just realized with real threads
    instead of generator frames.

    The fix: every single entry into the underlying raw generator (each
    `__next__`/`send`/`throw`/`close` call, not just the first/last one)
    saves whatever scope is currently active, swaps in this generator's own
    `func_scope` for the duration of exactly that one resume, and restores
    the caller's scope the instant control returns -- whether by yielding
    again, returning, or raising. This is exactly a context switch, done at
    every switch point, not just at thread start/end."""

    def __init__(self, interpreter, func_scope, body):
        self.interpreter = interpreter
        self.func_scope = func_scope

        def _body_fn(yield_fn):
            tls = interpreter._gen_tls
            old_yield_fn = getattr(tls, 'yield_fn', None)
            tls.yield_fn = yield_fn
            try:
                try:
                    for stmt in body:
                        interpreter.execute(stmt)
                    return None
                except ReturnValue as ret:
                    return ret.value
            finally:
                tls.yield_fn = old_yield_fn

        self._raw_gen = _ThreadedGenerator(_body_fn)
        self._started = False
        self._finished = False
        # The delegate's `return value` (a Mojo `return` inside a generator
        # body — becomes `StopIteration.value` in real Python), read off
        # `_ThreadedGenerator._return_value` and re-exposed here as an
        # ordinary field on one of THIS FILE's OWN classes rather than ever
        # touching `.value`/`.args` on the `StopIteration` exception object
        # itself — see `_ThreadedGenerator._resume`'s docstring for why
        # (this file self-hosts; the compiler's exception model has no
        # typed-attribute-access story for a builtin exception's payload).
        # `eval_YieldFromExpr` reads this after catching a bare
        # `StopIteration` to propagate `yield from`'s return value.
        self.return_value = None

    def __iter__(self):
        return self

    def _enter(self):
        """Start one resume step: swap `interpreter.scope` to this
        generator's own scope and return whatever scope was active before,
        so the caller can restore it in `_leave()` — see class docstring.
        Split into explicit enter/leave methods (rather than a single
        `_drive(thunk)` taking a `lambda: ...` closure, the original shape)
        because gimple_codegen.py's self-hosted compile of THIS file
        couldn't resolve a lambda passed as a callable argument at a call
        site (`_MojoGeneratorObject___next___lambda_1` etc. came back as
        undefined symbols at link time) — an open/close pair with no
        closure argument sidesteps that compiled-path gap entirely."""
        old = self.interpreter.scope
        self.interpreter.scope = self.func_scope
        return old

    def _leave(self, old):
        self.interpreter.scope = old
        self._started = True

    def __next__(self):
        if self._finished:
            raise StopIteration
        old = self._enter()
        try:
            return self._raw_gen.send(None)
        except StopIteration:
            self._finished = True
            self.return_value = self._raw_gen._return_value
            raise
        finally:
            self._leave(old)

    def send(self, value):
        if value is not None and not self._started:
            # Matches real Python: a just-started generator can only be
            # resumed with `.send(None)` (equivalent to `next()`) — it
            # hasn't reached a `yield` expression yet to receive a value.
            raise TypeError("can't send non-None value to a just-started generator")
        if self._finished:
            raise StopIteration
        old = self._enter()
        try:
            return self._raw_gen.send(value)
        except StopIteration:
            self._finished = True
            self.return_value = self._raw_gen._return_value
            raise
        finally:
            self._leave(old)

    def throw(self, exc_type, exc_val=None, exc_tb=None):
        # Normalize the (exc_type, exc_val, exc_tb) / bare-instance call
        # shapes real Python's generator.throw() accepts down to a single
        # exception instance — `_ThreadedGenerator.throw` (see its
        # docstring) only needs to inject one exception object at the
        # suspend point, not reconstruct a full three-arg raise.
        if isinstance(exc_type, BaseException):
            exc = exc_type
        elif exc_val is not None:
            exc = exc_type(exc_val) if not isinstance(exc_val, BaseException) else exc_val
        else:
            exc = exc_type()
        if self._finished:
            raise exc
        old = self._enter()
        try:
            return self._raw_gen.throw(exc)
        except StopIteration:
            self._finished = True
            self.return_value = self._raw_gen._return_value
            raise
        finally:
            self._leave(old)

    def close(self):
        """Throws GeneratorExit into the generator at its current suspension
        point (delegating to `_ThreadedGenerator.close()`, which already
        implements this correctly) so a `try/finally` holding a resource
        inside the Mojo generator body runs its cleanup even if the
        generator is never fully consumed."""
        if self._finished:
            return
        old = self._enter()
        try:
            self._raw_gen.close()
        finally:
            self._leave(old)
        self._finished = True


class MojoCoroutine:
    """Milestone 3b: the `async def` counterpart of `MojoGeneratorObject`.
    Wraps a `_ThreadedGenerator` driving a Mojo coroutine function's body
    through the ORDINARY, unmodified `execute()`/`eval_expr()` dispatch —
    exactly the same underlying mechanism as `MojoGeneratorObject`, reused
    directly rather than duplicated (see `_ThreadedGenerator`'s docstring)
    since the only thing that differs is which protocol gets exposed:
    `__iter__`/`__next__`/`.send()`/`.throw()` there, `__await__` here.

    `__await__` is a PLAIN method (not `def __await__(self): yield ...`,
    which would itself be a native-yield trap — see the module-wide
    constraint documented on `_ThreadedGenerator`) that returns `self`,
    since `MojoCoroutine` itself implements the `__next__`/`send`/`throw`
    iterator protocol real Python's `await`/`asyncio` machinery actually
    drives an awaitable's `__await__()` result through. This is genuinely
    real-asyncio-compatible: `asyncio.run(mojo_coro)`,
    `asyncio.gather(mojo_coro1, mojo_coro2)`, and `await mojo_coro` from
    ordinary real Python `async def` code all work, validated empirically
    (see INTERP_generator_yield_entirely_unimplemented's Milestone
    3b report) — including a Mojo body that internally does
    `await asyncio.sleep(...)`, which really suspends on the real event
    loop and really takes real wall-clock time, and `asyncio.gather` of
    several Mojo coroutines really running concurrently (interleaved by
    the real event loop, not just sequentially).

    Raises `StopIteration(value)` — WITH the constructor argument, unlike
    `_ThreadedGenerator._resume_once`'s deliberately-bare `StopIteration`
    — from `send`/`throw`/`__next__` when the coroutine body returns. This
    might look like it contradicts `_ThreadedGenerator`'s documented
    self-hosting workaround (avoiding `StopIteration.value` because the
    self-hosted compiler's exception model can't do typed attribute access
    against a builtin exception), but it doesn't: this file's OWN source
    never reads `.value` off a `StopIteration` anywhere (`return_value` is
    tracked as an ordinary field, exactly like `MojoGeneratorObject`, and
    used to build the argument passed to `StopIteration(...)` here) — only
    CONSTRUCTS and RAISES one. Real Python's own `await`/`SEND` bytecode
    (running in the genuinely-interpreted path, where these objects are
    real CPython objects) is what reads `.value` back out, and that's real
    CPython machinery, not code inside this self-hosted file.

    Same `interpreter.scope` swap-on-every-resume discipline as
    `MojoGeneratorObject` (identical hazard: `interpreter.scope` is one
    mutable attribute, not a per-call parameter — see that class's
    docstring for the full explanation), extended to also cover
    concurrent-by-real-asyncio coroutines, not just hand-interleaved
    generators: since real asyncio only ever runs ONE callback at a time
    on its single event-loop thread, and every one of a coroutine's worker
    threads only ever runs while its OWN `_enter`/`_leave` window holds
    `interpreter.scope` pinned to that coroutine's own scope (strictly
    alternating with whichever OTHER coroutine/generator/plain call is
    active at that instant, exactly like `_ThreadedGenerator`'s handoff
    guarantees), the same single-mutable-attribute swap remains correct
    even when several `MojoCoroutine`s are "concurrently" in flight from
    asyncio's point of view."""

    def __init__(self, interpreter, func_scope, body):
        self.interpreter = interpreter
        self.func_scope = func_scope

        def _body_fn(yield_fn):
            tls = interpreter._gen_tls
            old_yield_fn = getattr(tls, 'yield_fn', None)
            old_is_coroutine = getattr(tls, 'is_coroutine', False)
            tls.yield_fn = yield_fn
            # Gates Interpreter.invoke's _RealThreadCall bounce (see its
            # docstring) — only coroutine bodies interact with an event
            # loop, so plain Mojo generators never pay for or risk this.
            tls.is_coroutine = True
            try:
                try:
                    for stmt in body:
                        interpreter.execute(stmt)
                    return None
                except ReturnValue as ret:
                    return ret.value
            finally:
                tls.yield_fn = old_yield_fn
                tls.is_coroutine = old_is_coroutine

        self._raw = _ThreadedGenerator(_body_fn)
        self._started = False
        self._finished = False

    def _enter(self):
        """See MojoGeneratorObject._enter — identical swap-in, split out of
        a lambda-taking `_drive` for the identical self-hosted-compile
        reason documented there."""
        old = self.interpreter.scope
        self.interpreter.scope = self.func_scope
        return old

    def _leave(self, old):
        self.interpreter.scope = old
        self._started = True

    def __await__(self):
        """The entire real-asyncio-interop hinge point: returning `self`
        (which implements `__next__`/`send`/`throw`) is all real Python's
        `await`/`SEND` bytecode needs to drive this coroutine exactly like
        any other awaitable — a real native coroutine, a real `Future`, or
        another `MojoCoroutine` (Mojo-await-Mojo — see `eval_AwaitExpr`,
        which treats a `MojoCoroutine` no differently from a real one,
        uniformly, since both merely need to expose `__await__`)."""
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return self.send(None)

    def send(self, value):
        if self._finished:
            raise StopIteration
        old = self._enter()
        try:
            result = self._raw.send(value)
            return result
        except StopIteration:
            self._finished = True
            raise StopIteration(self._raw._return_value)
        finally:
            self._leave(old)

    def throw(self, exc_type, exc_val=None, exc_tb=None):
        # Normalize the (exc_type, exc_val, exc_tb) / bare-instance call
        # shapes real Python's coroutine.throw() accepts — see
        # MojoGeneratorObject.throw, identical normalization.
        if isinstance(exc_type, BaseException):
            exc = exc_type
        elif exc_val is not None:
            exc = exc_type(exc_val) if not isinstance(exc_val, BaseException) else exc_val
        else:
            exc = exc_type()
        if self._finished:
            raise exc
        old = self._enter()
        try:
            result = self._raw.throw(exc)
            return result
        except StopIteration:
            self._finished = True
            raise StopIteration(self._raw._return_value)
        finally:
            self._leave(old)

    def close(self):
        """See MojoGeneratorObject.close — identical GeneratorExit-based
        cleanup, delegated to the same `_ThreadedGenerator.close()`."""
        if self._finished:
            return
        old = self._enter()
        try:
            self._raw.close()
        finally:
            self._leave(old)
        self._finished = True


class _MojoSelfType:
    """Generic Self type marker used when Self is referenced outside
    a struct method context."""
    def __getattr__(self, name):
        return self
    def __getitem__(self, key):
        return self
    def __call__(self, *args, **kwargs):
        return self
    def __repr__(self):
        return 'Self'


class _MojoBoundComptimeFunction:
    """Result of subscripting a generic function at a call site
    (`run_func[DType.float64](8, 0.125, ctx)`) — the comptime parameter
    names are pre-bound; calling it runs the function body with both those
    and the regular call-time arguments in scope."""
    def __init__(self, func, comptime_bindings):
        self.func = func
        self.comptime_bindings = comptime_bindings

    def __call__(self, *args, **kwargs):
        # `f[DType](x)` curried into a callable is handed to builtins as an
        # ordinary value (`sorted(xs, key=f[Int])`), so — exactly as in
        # `MojoFunction.__call__` — the interpreter is resolved from the
        # underlying function's own record rather than demanded positionally,
        # through the same `_split_invoker` (an imported generic function has
        # the same two-different-interpreters shape as any other).
        func = self.func
        interp, args = _split_invoker(func._interp, args)
        return func._invoke(interp, self.comptime_bindings, args, kwargs)


class _NoOverloadMatch(TypeError):
    """Raised by MojoOverloadSet.__call__ when no candidate's arity/keywords
    match the call. A dedicated subclass (rather than a bare TypeError) so
    eval_CallExpr can attach the call site's location without also catching
    unrelated TypeErrors raised deeper inside whichever overload runs."""


class MojoOverloadSet:
    """Multiple `def name(...)` definitions sharing a name are Mojo overloads,
    not redefinitions of the same function — real Mojo picks the candidate
    whose signature matches the call site. We can only realistically dispatch
    on argument count and keyword names (the interpreter is untyped, so
    parameter *types* can't disambiguate); BOTH failure directions are hard
    errors rather than a silent pick, matching this project's own compiled-path
    overload-resolution philosophy (see gimple_codegen's "no-match overload
    returns None" test).

    **Both failure directions are hard errors, and the second one was missing
    until 2026-10-03.** The no-match case always raised. The AMBIGUOUS case —
    two or more candidates that `_matches` cannot tell apart — returned the
    FIRST one, in source order, which is a silent wrong answer whenever the
    candidates differ in anything `_matches` does not look at: parameter types,
    parameter conventions (`ref`/`var`/`mut`), or the return type. `peekable`'s
    two stdlib overloads are exactly that shape
    (`std/iter/__init__.mojo`: `def peekable(ref iterable: Some[Iterable])` vs
    `def peekable(var iterable: Some[IterableOwned])`) — same arity, no
    keywords, differing only in a trait bound and a convention, so
    `peekable(a_list)` dispatched to whichever the file happened to declare
    first. The class docstring claimed "no match is a hard error rather than
    a silent first-pick", which was true of the no-match case and false of this
    one.

    Refusing is the correct outcome, not a limitation being papered over: a
    first-pick here is indistinguishable, to the caller, from a correct
    dispatch, which is strictly worse than an error that names the tie. The
    same rule the compiled path already follows is `elaborate`'s — an overload
    the resolver cannot decide is declined, never guessed. What is genuinely
    unavailable here (and is why this is a refusal rather than a dispatch) is
    parameter-type information: the interpreter is untyped, and recovering it
    would mean modelling Mojo's ownership conventions, not adding a comparison.
    """
    def __init__(self, name, interpreter=None):
        self.name = name
        self.candidates = []  # list of (MojoFunction, required, optional, kwonly, has_var_kwargs)
        # Same reason as `MojoFunction._interp`, and for the same reason
        # `__call__` resolves it the same way: a builtin receiving this set as
        # a `key=`/callback argument invokes it directly, with no interpreter
        # to thread through.
        self._interp = interpreter

    def add(self, func, required, optional, kwonly, has_var_kwargs):
        self.candidates.append((func, required, optional, kwonly, has_var_kwargs))

    @staticmethod
    def _matches(spec, args, kwargs):
        required, optional, kwonly, has_var_kwargs = spec[1], spec[2], spec[3], spec[4]
        n = len(args)
        if n < len(required) or n > len(required) + len(optional):
            return False
        covered = (required + optional)[:n]
        for key in kwargs:
            if key in covered:
                return False  # supplied both positionally and by keyword
            if key not in required and key not in optional and key not in kwonly and not has_var_kwargs:
                return False
        for name in required[n:]:
            if name not in kwargs:
                return False
        return True

    def __call__(self, *args, **kwargs):
        # `interpreter` used to be a required first positional argument; see
        # `MojoFunction.__call__` for why it no longer is and how it is
        # resolved instead. An overload SET's candidates come from one module
        # and its call sites can come from another, so the two interpreters are
        # routinely different objects — which is why `_split_invoker`
        # recognises the leading argument by type.
        interp, args = _split_invoker(self._interp, args)
        matching = [spec for spec in self.candidates
                    if self._matches(spec, args, kwargs)]
        if len(matching) == 1:
            func = matching[0][0]
            return func._invoke(interp, {}, args, kwargs)
        if not matching:
            raise _NoOverloadMatch(
                f"no overload of '{self.name}' matches {len(args)} positional "
                f"arg(s) and keyword(s) {sorted(kwargs.keys())}"
            )
        # More than one candidate survived, so the choice is between
        # signatures this resolver cannot rank — they differ in parameter
        # types, parameter conventions, or return type, and dispatching on
        # argument count and keyword names alone cannot separate them. Naming
        # the candidates is the point: the caller can see WHICH tie it hit and
        # add the information, where a first-pick would have hidden it.
        _shapes = ', '.join(
            f"({', '.join(spec[1] + spec[2])})"
            f"{' + ' + str(spec[3]) if spec[3] else ''}"
            for spec in matching)
        raise _NoOverloadMatch(
            f"AMBIGUOUS call to '{self.name}': {len(matching)} of "
            f"{len(self.candidates)} overloads match {len(args)} positional "
            f"arg(s) and keyword(s) {sorted(kwargs.keys())} equally well "
            f"[{_shapes}]. This interpreter dispatches on argument count and "
            f"keyword names only, so it cannot choose between them; picking "
            f"the first would be a silent wrong answer. Disambiguate at the "
            f"call site (or pass the arguments by keyword where the "
            f"signatures differ in arity)."
        )


class _MojoWriter:
    """Minimal stand-in for real Mojo's `Writer` trait — `write_to`/
    `write_repr_to` methods call `writer.write(*args)` one or more times with
    a mix of strings/values to concatenate; this just accumulates them."""
    def __init__(self):
        self._parts = []

    def write(self, *args):
        for a in args:
            self._parts.append(str(a))

    def getvalue(self):
        return ''.join(self._parts)


class MojoInstance:
    """An instance of a Mojo-defined struct/class."""
    def __init__(self, mojo_class: 'MojoClass'):
        self._mojo_class = mojo_class

    def __getattr__(self, name):
        # Python's built-in `getattr(obj, name)` only consults real instance
        # attributes and class attributes, never the Mojo method table, so a
        # method fetched dynamically (`getattr(c, "tag")`) raised
        # AttributeError even though `c.tag` worked. Mirror `_eval_member_of`
        # so the two spellings agree.
        if name in self.__dict__:
            return self.__dict__[name]
        cls = self._mojo_class
        method = cls.methods.get(name)
        if method is not None:
            if name in cls.static_methods:
                return method
            if name in cls.class_methods:
                return BoundClassMethod(method, cls, cls.interpreter)
            return BoundMethod(method, self, cls.interpreter)
        if name in cls.comptime_aliases:
            return cls.comptime_aliases[name]
        raise _tag_attribute_error(
            AttributeError(f"'{cls.name}' object has no attribute '{name}'"),
            self, name, _frame_self(cls.interpreter))

    def _write_via(self, method_name):
        """Call a user-defined `write_to`/`write_repr_to(self, mut writer)`
        method, if the struct defines one, and return the accumulated text —
        or None if it doesn't (no reflection-based default synthesis here,
        unlike real Mojo's compiler-derived Writable for plain structs)."""
        method = self._mojo_class.methods.get(method_name)
        if method is None:
            return None
        writer = _MojoWriter()
        method(self._mojo_class.interpreter, self, writer)
        return writer.getvalue()

    def __str__(self):
        result = self._write_via('write_to')
        if result is not None:
            return result
        return repr(self)

    def __repr__(self):
        result = self._write_via('write_repr_to')
        if result is not None:
            return result
        result = self._write_via('write_to')
        if result is not None:
            return result
        return f"<{self._mojo_class.name} instance>"

    def __len__(self):
        method = self._mojo_class.methods.get('__len__')
        if method is not None:
            return method(self._mojo_class.interpreter, self)
        raise TypeError(f"object of type '{self._mojo_class.name}' has no len()")

    def __getitem__(self, key):
        method = self._mojo_class.methods.get('__getitem__')
        if method is not None:
            return method(self._mojo_class.interpreter, self, key)
        raise KeyError(key)

    def __setitem__(self, key, value):
        method = self._mojo_class.methods.get('__setitem__')
        if method is not None:
            return method(self._mojo_class.interpreter, self, key, value)
        raise KeyError(key)

    def __call__(self, *args, **kwargs):
        """An instance of a struct that defines `__call__` IS callable — the
        `functor` idiom, and the reason a callable OBJECT reaches a builtin's
        callback slot at all (`sorted(xs, key=ByLength())`).

        Without this the object was simply not callable, so
        `sorted([1,2,3], key=Callable(10))` raised "TypeError:
        'MojoInstance' object is not callable" — a hole right next to the one
        `MojoFunction.__call__` had. Resolved through the SAME
        `self._mojo_class.methods` table and the same
        `method(interpreter, self, ...)` shape as `__len__`/`__getitem__`/
        `__setitem__` above, so `__call__` is bound exactly the way every
        other dunder on this class is."""
        method = self._mojo_class.methods.get('__call__')
        if method is None:
            raise TypeError(f"object of type '{self._mojo_class.name}' is not callable")
        return method(self._mojo_class.interpreter, self, *args, **kwargs)


class BoundMethod:
    """A struct/class method bound to a specific instance (`self` already filled in)."""
    def __init__(self, bound_func, instance, interpreter):
        self.bound_func = bound_func
        self.instance = instance
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        return self._invoke_bound({}, args, kwargs)

    def _invoke_bound(self, comptime_bindings, args, kwargs):
        """Run the body with `comptime_bindings` pre-bound into the body
        scope. Shared by the plain call (empty bindings) and by the
        keyword-bracket call `obj.body[f_key=show_k]()`
        (`_MojoBoundComptimeReceiver`), so the scope push, the `self`
        binding and the receiver argument are written once — the bracket
        call used to go through `__getitem__`, which answered the receiver
        itself and DROPPED every bracketed argument."""
        f = self.bound_func
        old_scope = self.interpreter.scope
        self.interpreter.scope = Scope(parent=self.interpreter.scope)
        self.interpreter.scope.define('self', self.instance)
        try:
            if isinstance(f, MojoOverloadSet):
                # An overloaded method taken as a value (and then bound to
                # an instance) has no single `_invoke` to delegate to; route
                # through the overload set's own dispatch instead, with `self`
                # prepended as the receiver.
                #
                # The receiver is folded into the `*`-unpack (`invoke(f,
                # *_merged, **kwargs)`) rather than written as an explicit
                # positional before it (`invoke(f, self.instance, *args,
                # **kwargs)`): the codegen cannot lower an explicit positional
                # that PRECEDES a `*`-unpack in the same call — it emits the
                # positional as a separate C argument (casting it to the
                # `*args` MojoList*) instead of folding it into the unpacked
                # list, so the call comes out with one argument too many and
                # the self-host's `gcc -fgimple` refuses it ("too many
                # arguments to 'myinterpreter_Interpreter_invoke'"). The
                # `func, *args, **kwargs` shape below (no leading positional
                # before the unpack) is the one it lowers. Semantics are
                # unchanged: both pass func=f, the receiver prepended to the
                # `*args`, and `**kwargs`.
                _merged = [self.instance] + list(args)
                return self.interpreter.invoke(f, *_merged, **kwargs)
            interp, rest = _split_invoker(f._interp, (self.instance,) + tuple(args))
            return f._invoke(interp, comptime_bindings, rest, kwargs)
        finally:
            self.interpreter.scope = old_scope

    def __getitem__(self, key):
        return self


class _MojoBoundComptimeReceiver:
    """A receiver-bound method with its comptime parameters pre-bound —
    `obj.body[f_key=show_k]()`, the shape `Dict.mojo`/`counter.mojo` use.
    Holds the receiver and defers to its `_invoke_bound`, so calling one is
    the same operation as calling the receiver itself, plus the bindings."""
    def __init__(self, receiver, comptime_bindings):
        self.receiver = receiver
        self.comptime_bindings = comptime_bindings

    def __call__(self, *args, **kwargs):
        return self.receiver._invoke_bound(self.comptime_bindings, args, kwargs)


class BoundClassMethod:
    """A `@classmethod` with the CLASS already filled in under the source-level
    name `cls` — the classmethod counterpart of `BoundMethod`.

    Before this, a `@classmethod` had NO representation at all: `C.m(...)`
    returned the raw unbound `MojoFunction`, so the call bound the FIRST REAL
    ARGUMENT to the `cls` parameter (`C.gen(5)` made `cls == 5`, and
    `cls.<attr>` then raised "'int' object has no attribute ..."). That made
    the ORACLE disagree with the compiled path, which does pass a receiver,
    on a shape real code uses (see
    bugs/mid/COMPILE_FAIL_importlib_resources_readers.md's
    `yield from cls.<sibling generator>(...)`).

    A separate class rather than a second receiver kind inside `BoundMethod`:
    this receiver is a `MojoClass *` where `BoundMethod`'s is a
    `MojoInstance *`, and the self-hosted compiler gives every struct field
    ONE C type. Erasing both to one `void *` would buy a single class at the
    price of a cast at each of this one's use sites; two small classes with
    homogeneous fields costs one extra `struct_field_types` entry and reads
    more plainly.
    """
    def __init__(self, bound_func, cls, interpreter):
        self.bound_func = bound_func
        self.cls = cls
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        return self._invoke_bound({}, args, kwargs)

    def _invoke_bound(self, comptime_bindings, args, kwargs):
        """The `BoundMethod` counterpart — see its docstring; identical, with
        `cls` and the class as the receiver."""
        f = self.bound_func
        old_scope = self.interpreter.scope
        self.interpreter.scope = Scope(parent=self.interpreter.scope)
        self.interpreter.scope.define('cls', self.cls)
        try:
            interp, rest = _split_invoker(f._interp, (self.cls,) + tuple(args))
            return f._invoke(interp, comptime_bindings, rest, kwargs)
        finally:
            self.interpreter.scope = old_scope

    def __getitem__(self, key):
        return self


def _c3_linearize(cls):
    """Return `cls.__mro__`: C3 linearization of the bases named in `cls`.

    Matches CPython's `type.__mro__` exactly — including diamonds (e.g. a
    `D(B, C)` over sibling `B(O)`/`C(O)` resolves to `D, B, C, O`) and its
    error semantics: an entry that is neither a real Mojo class nor a real
    Python type (typing specials like `TypedDict`, which are functions in 3.15+)
    raises `TypeError`, and an inconsistent hierarchy raises a `TypeError`
    naming every base, the same way `type()` does at class creation time. The
    underlying Python-style hierarchy this interpreter synthesises only carries
    `object` as an implicit root, so a plain class's MRO is just `(cls,)`; there
    is no Mojo root type for it to inherit from."""
    seqs = []
    for b in cls.bases:
        if isinstance(b, MojoClass):
            seqs.append(_c3_linearize(b))
        elif isinstance(b, type):
            seqs.append(tuple(b.__mro__))
        else:
            raise TypeError(f"__mro__ entry is not a class: {b!r}")
    seqs.append(tuple(cls.bases))
    return (cls,) + tuple(_c3_merge(cls.bases, seqs))


def _c3_merge(bases, seqs):
    """Merge the sequence lists (`seqs`) one head at a time, removing every
    head from every list's tail once taken — the standard C3 linearisation
    step. A head that still appears in another list is rejected; if no head of
    any list qualifies, the hierarchy is inconsistent, and the `TypeError`
    names every base the way `type()` does at class creation."""
    seqs = [list(s) for s in seqs if s]
    out = []
    while seqs:
        for i, s in enumerate(seqs):
            head = s[0]
            # Only a tail appearance disqualifies a head; another list whose own
            # head is this same element will consume it in this same step.
            if any(head in other[1:] for j, other in enumerate(seqs) if j != i):
                continue
            out.append(head)
            seqs = [o[1:] if o and o[0] is head else o for o in seqs]
            seqs = [o for o in seqs if o]
            break
        else:
            names = ', '.join(getattr(b, '__name__', type(b).__name__) or str(b) for b in bases)
            raise TypeError(f"Cannot create a consistent method resolution order (MRO) for bases {names}")
    return out


class MojoClass:
    """Represents a class/struct defined in Mojo code."""
    _ARRAY_TYPE_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\[([A-Za-z_][A-Za-z0-9_]*|\d+)\]$')
    _ARRAY_ELEM_DEFAULTS = {
        'Bool': False, 'String': '',
        'Float16': 0.0, 'Float32': 0.0, 'Float64': 0.0,
    }

    def __init__(self, name, fields, methods: dict, interpreter, bases=None,
                 comptime_aliases=None, static_methods=None, class_methods=None,
                 def_scope=None, keywords=None):
        self.name = name
        self.fields = fields  # list of VarDecl/AssignStmt (field declarations)
        self.methods = methods  # dict: name -> MojoFunction
        self.interpreter = interpreter
        # The scope struct-definition executed in (same closure MojoFunction
        # captures for methods) — needed to resolve a fixed-size array field's
        # size expression (e.g. `Int[MAX_CELLS]`) by the comptime constant's
        # OWN defining module, not whatever module happens to instantiate this
        # struct (mirrors how `__init__` bodies already resolve such names).
        self.def_scope = def_scope
        self.bases = bases or []  # base MojoClass objects, e.g. `struct Child(Base):`
        # Keyword arguments from the class definition, e.g.
        # `extra_items=bool`, `closed=True` (PEP 692/728) or `metaclass=M`.
        # Stored for introspection and passed through where the interpreter
        # creates a real Python class (Python-type bases with keywords).
        self.keywords = keywords or {}
        # `comptime EOF_TOKEN: Int = 69` inside the struct body — evaluated
        # once at struct-definition time and exposed as a class-level
        # attribute (`TokenType.EOF_TOKEN`), same as a Python class constant.
        self.comptime_aliases = comptime_aliases or {}
        # Names of `@staticmethod` methods — looked up here so __getattr__
        # can hand back the raw MojoFunction (no instance to bind) instead
        # of wrapping it in a BoundMethod.
        self.static_methods = static_methods or set()
        # Names of `@classmethod` methods, the mirror image: __getattr__ wraps
        # one in a BoundMethod bound to THIS class under the name `cls`, so
        # `C.m(x)` and `C().m(x)` both deliver the class as the first
        # argument. Inherited from a base like static_methods is, and an
        # override in a subclass rebinds `cls` to the SUBCLASS — which is
        # exactly Python's rule, and is what makes `yield from
        # cls.<sibling>()` inside a generator resolve against the class the
        # call was actually made on.
        self.class_methods = class_methods or set()

    def __getattr__(self, name):
        # Only called when normal attribute lookup (real fields set in
        # __init__) fails, so plain `self.comptime_aliases`/`self.methods`
        # access here can't recurse — both are always set before this could
        # ever fire. (Deliberately not `self.__dict__.get(...)`: the
        # self-hosted compiled path has no Python-style __dict__.)
        if name in self.comptime_aliases:
            return self.comptime_aliases[name]
        if name in self.methods:
            # A method looked up on the class itself (StructType.method),
            # not an instance — return the raw MojoFunction unbound, EXCEPT
            # for a `@classmethod`, which is exactly the case where the
            # receiver IS the class: bind it and the call is correct on the
            # first argument, with no call-site knowledge of the decorator.
            # `@staticmethod`s keep the unbound raw function (nothing to
            # bind); a regular method returned this way still just requires
            # the caller to pass `self` explicitly, matching Python's own
            # unbound-method rule.
            method = self.methods[name]
            if name in self.class_methods:
                return BoundClassMethod(method, self, self.interpreter)
            return method
        if name == '__name__':
            # Real Python classes carry their own name here; a MojoClass
            # instance passed into a real Python function (e.g. ctypes'
            # POINTER(cls), which does `cls.__name__`) needs the same —
            # ctypes/wintypes.py's `PFILETIME = POINTER(FILETIME)` raised
            # "'FILETIME' object has no attribute '__name__'".
            return self.name
        if name == '__mro__':
            # A real Python class built through the keywords path already owns a
            # `__mro__`; only the plain interpreter-synthesised Mojo classes need
            # this implemented here. Cached on the instance so repeated access is
            # the one C3 work we do per class lifetime.
            cached = self.__dict__.get('_mojo_mro')
            if cached is None:
                cached = _c3_linearize(self)
                self.__dict__['_mojo_mro'] = cached
            return cached
        raise _tag_attribute_error(
            AttributeError(f"'{self.name}' object has no attribute '{name}'"),
            self, name, _frame_self(self.interpreter))

    def __call__(self, *args, **kwargs):
        instance = MojoInstance(self)
        for f in self.fields:
            if self.interpreter._is_instance(f, 'VarDecl'):
                # Array-default handled as its own early-exit branch, NOT
                # folded into `value`'s own assignment chain below (self-host
                # build note: MojoClass is one of myinterpreter.py's own
                # hardcoded struct_field_types entries — the self-hosted
                # compiler infers one C type per Python local from how it's
                # used across the WHOLE function, so any assignment of
                # `_array_field_default`'s result into `value` — even inside
                # a ternary — made it infer `value` as `MojoList *`
                # unconditionally, breaking `make check-selfhost` with
                # "invalid types in conversion to integer" the moment
                # `_coerce_to_declared_type`'s differently-typed result also
                # flowed into that same `value`, even though the interpreter
                # itself ran fine either way. `array_default` is its own
                # local, assigned from nowhere else, so it can't contaminate
                # `value`'s original, already-self-host-clean inference.)
                if f.value is None:
                    array_default = self._array_field_default(getattr(f, 'type_ann', None))
                    if array_default is not None:
                        setattr(instance, f.name, array_default)
                        continue
                    # A `List`/`Dict`/`Set` field (bare or `List[T]` spelling)
                    # with no initializer binds a fresh empty container of the
                    # declared kind — the compiled path's answer and real
                    # Mojo's — instead of None. Own local + `continue`, never
                    # folded into `value`: same self-host inference reason as
                    # the `_array_field_default` branch directly above.
                    container_default = self.interpreter._container_field_default(getattr(f, 'type_ann', None))
                    if container_default is not None:
                        setattr(instance, f.name, container_default)
                        continue
                value = self.interpreter.eval_expr(f.value) if f.value is not None else None
                value = self.interpreter._coerce_to_declared_type(value, getattr(f, 'type_ann', None))
                setattr(instance, f.name, value)
            elif self.interpreter._is_instance(f, 'AssignStmt'):
                # AssignStmt has a single `.target`, not a `.targets` list
                # (fire_compiler.py's AssignStmt dataclass) — this branch
                # raised "'AssignStmt' object has no attribute 'targets'"
                # on any instantiation of a class with a bare `NAME = value`
                # class-body attribute (e.g. `class Foo: count = 0`).
                value = self.interpreter.eval_expr(f.value) if f.value is not None else None
                target = f.target
                if self.interpreter._is_instance(target, 'IdentExpr'):
                    setattr(instance, target.name, value)
        init = self.methods.get('__init__')
        if init is not None:
            interp = self.interpreter
            old_scope = interp.scope
            interp.scope = Scope(old_scope)
            interp.scope.define('self', instance)
            try:
                init(interp, instance, *args, **kwargs)
            finally:
                interp.scope = old_scope
        elif args:
            # Implicit memberwise constructor: a struct/class with NO explicit
            # __init__ binds positional ctor args to its fields in declaration
            # order — `struct Point: var x: Int; var y: Int; Point(3, 4)` sets
            # x=3, y=4 (matches gimple_codegen's _synthesize_fieldwise_inits
            # and real Mojo). Previously the interpreter ignored the args,
            # leaving every field None ("unsupported operand +: None + None").
            field_names = []
            for f in self.fields:
                if self.interpreter._is_instance(f, 'VarDecl'):
                    field_names.append(f.name)
                elif self.interpreter._is_instance(f, 'AssignStmt') \
                        and self.interpreter._is_instance(f.target, 'IdentExpr'):
                    field_names.append(f.target.name)
            for i, a in enumerate(args):
                if i < len(field_names):
                    fname = field_names[i]
                    setattr(instance, fname, a)
        return instance

    def _array_field_default(self, type_ann):
        """A fixed-size array field (`cell_ids: Int[MAX_CELLS]`) with no
        explicit initializer must default to a zero-filled list of the
        declared length, same as real Mojo — not None (BUG-2026: struct array
        fields not initialized when the struct is defined in an imported
        module, `TypeError: 'NoneType' object does not support item
        assignment` on the first indexed write). Returns None (not a
        defaulted array) if `type_ann` isn't a string, isn't `ElemType[size]`
        shape, or the size can't be resolved."""
        if not isinstance(type_ann, str):
            return None
        m = self._ARRAY_TYPE_RE.match(type_ann)
        if not m:
            return None
        elem_type, size_str = m.group(1), m.group(2)
        if size_str.isdigit():
            size = int(size_str)
        else:
            # A named comptime constant (e.g. `MAX_CELLS`) — resolve it in
            # the struct's OWN defining scope, not the caller's, mirroring
            # how `__init__` bodies already resolve such names via their
            # captured closure scope.
            lookup_scope = self.def_scope or self.interpreter.scope
            try:
                size = lookup_scope.get(size_str)
            except NameError:
                return None
            if not isinstance(size, int) or isinstance(size, bool):
                return None
        elem_default = self._ARRAY_ELEM_DEFAULTS.get(elem_type, 0)
        return [elem_default] * size

    def __getitem__(self, item):
        # A user-defined generic struct instantiated with explicit type/value
        # params, e.g. `Layout[Int]`. No monomorphization here — same
        # simplification as _MojoGenericCtor's `List[Int]`.
        return self


class _MojoGenericCtor:
    """Mojo's `List[Int]()`/`Set[Int]()` subscript the type constructor with the
    element type(s) before calling it. The interpreter has no generic-type
    system, so the subscript is a no-op — `List[Int]` and `List[String]` both
    just resolve back to this same constructor, and `[...]` is ignored."""
    def __init__(self, ctor):
        self._ctor = ctor

    def __getitem__(self, item):
        return self

    def __call__(self, *args, **kwargs):
        ctor = self._ctor
        # Mojo's `List(1, 2, 3)`/`Set(1, 2, 3)` pass elements variadically;
        # Python's own list()/set()/deque() take a single iterable argument.
        if len(args) > 1 and not kwargs:
            return ctor(list(args))
        # Mojo constructors may receive keyword args that Python's built-in
        # constructors don't understand — strip known Mojo-specific ones.
        if isinstance(kwargs, dict):
            mojo_kwargs = {'capacity', 'num_bits', 'size', 'uninitialized', 'fill', '__list_literal__', 'ptr', 'length'}
            kwargs = {k: v for k, v in kwargs.items() if k not in mojo_kwargs}
        if kwargs:
            return ctor(*args, **kwargs)
        # After stripping Mojo kwargs, if we still have multiple positional
        # args, wrap them in a list for Python constructors.
        if len(args) > 1:
            return ctor(list(args))
        # Single non-iterable arg to list/set — Mojo treats it as a single
        # element, Python treats it as an iterable. Wrap in a list.
        if len(args) == 1 and ctor in (list, set, tuple) and not isinstance(args[0], (list, tuple, set, str, bytes, range, dict)):
            return ctor([args[0]])
        return ctor(*args, **kwargs)


class _MojoBitcastToken:
    """`ptr.bitcast[NewType]()` — subscript with the target type (ignored, no
    real memory typing here), call with no arguments to get the same pointer
    back reinterpreted (a no-op, since `_MojoPointer` isn't typed)."""
    def __init__(self, pointer):
        self.pointer = pointer

    def __getitem__(self, type_arg):
        return self

    def __call__(self, *args, **kwargs):
        return self.pointer


class _MojoPointer:
    """Stand-in for real Mojo's `UnsafePointer[T]`. There's no real memory
    model here — it's a Python list (`buffer`) playing the role of the
    pointee's backing storage, plus an `offset` into it, so pointer
    arithmetic (`ptr + n`) and dereference (`ptr[]`, which the parser lowers
    to `ptr[0]` — see fire_compiler.py's subscript parsing) both fall out of
    plain list indexing. `UnsafePointer(to=x)` boxes `x` into a fresh
    single-element buffer: reads/writes through the returned pointer work,
    but (unlike real Mojo) don't alias back to the original variable `x` —
    the interpreter has no way to take "the address of" a Python local."""
    def __init__(self, buffer, offset=0):
        self.buffer = buffer
        self.offset = offset

    def __getitem__(self, i):
        return self.buffer[self.offset + i]

    def __setitem__(self, i, value):
        self.buffer[self.offset + i] = value

    def load(self, i=0):
        return self.buffer[self.offset + i]

    def store(self, *args):
        # `ptr.store(value)` or `ptr.store(i, value)`.
        if len(args) == 1:
            i, value = 0, args[0]
        else:
            i, value = args[0], args[1]
        self.buffer[self.offset + i] = value

    def __add__(self, n):
        return _MojoPointer(self.buffer, self.offset + n)

    def __sub__(self, n):
        if isinstance(n, _MojoPointer):
            return self.offset - n.offset
        return _MojoPointer(self.buffer, self.offset - n)

    def __eq__(self, other):
        if not isinstance(other, _MojoPointer):
            return NotImplemented
        return self.buffer is other.buffer and self.offset == other.offset

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __hash__(self):
        return id(self.buffer) ^ self.offset

    def __bool__(self):
        return True

    def __int__(self):
        # A real (if fake) nonzero "address" — enough for `assert_not_equal(0, Int(ptr))`.
        return id(self.buffer) + self.offset

    def __repr__(self):
        return f"UnsafePointer(0x{self.__int__():x})"

    def free(self):
        pass  # no real memory to release; Python GC owns `buffer`

    def as_immutable(self):
        return self

    def as_unsafe_any_origin(self):
        return self

    def address_space_cast(self, *args, **kwargs):
        return self

    @property
    def bitcast(self):
        # Real Mojo calls this as `ptr.bitcast[NewType]()` — subscript with
        # the target type, then call. A plain method can't be subscripted
        # (`ptr.bitcast[T]` would try to subscript a bound method object), so
        # this is a property returning a subscript-then-call token instead.
        return _MojoBitcastToken(self)

    def address_of(self):
        return self

    def map_to_host(self):
        # Real Mojo's `with dev_buf.map_to_host() as host_buf:` copies device
        # memory to host-visible memory for the duration of the `with` block.
        # There's no real device/host split in this simulation — buffers
        # allocated by `DeviceContext.enqueue_create_buffer` are already
        # plain host lists — so this just hands back the same pointer.
        return _MojoMapToHostCtx(self)

    def enqueue_copy_to(self, other):
        # `ctx.enqueue_copy(dst, src)` / `src.enqueue_copy_to(dst)`.
        for i in range(len(self.buffer) - self.offset):
            other[i] = self[i]


class _MojoMapToHostCtx:
    def __init__(self, ptr):
        self.ptr = ptr

    def __enter__(self):
        return self.ptr

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _MojoUnsafePointerType:
    """`UnsafePointer[Int]` (subscript ignored, no generic-type system),
    `UnsafePointer(to=x)` (address-of, see _MojoPointer), and
    `UnsafePointer.alloc(n)` (fresh n-element backing buffer)."""
    def __getitem__(self, item):
        return self

    def __call__(self, to=None, **kwargs):
        return _MojoPointer([to])


class _MojoListType:
    """`List[T]` (subscript ignored - no generic-type system).

    BUG-2026-028 (mojolib): `from std.collections import List` used to fall
    through to the generic `std.*` auto-stub namespace (real list.mojo is
    full of generics/MLIR-level memory primitives - alloc/Layout/
    ThinAllocation/uninit_move_n - our simple parser can't handle), so
    `List[Int]()` silently returned an `_AutoStubValue`: every method call
    on it (`.append`, `._realloc`, even a nonexistent method name) "succeeded"
    with no error and no effect, and `__len__()` always returned the
    hardcoded stub value 0, while direct field writes like `items._len = 5`
    looked like they worked (plain attribute set on the stub's own __dict__,
    unrelated to any real list state) - a convincing but entirely fake list.

    Rather than attempt to interpret real list.mojo's low-level memory code
    (the exact crash the auto-stub fallback was added to avoid), this backs
    `List[T]()` with a plain Python `list` - the SAME representation
    `eval_ListLiteral` already uses for `[1, 2, 3]` literals, so a
    std.collections.List and a list literal are fully interchangeable
    everywhere else in the interpreter that already expects a Python list,
    and real list operations (append, __len__, indexing, iteration) all
    just work via Python's own list semantics instead of needing bespoke
    reimplementation here."""
    def __getitem__(self, item):
        return self

    def __call__(self, *args, **kwargs):
        if 'copy' in kwargs:
            return list(kwargs['copy'])
        if 'capacity' in kwargs or 'unsafe_uninit_length' in kwargs:
            return []
        # `List(1, 2, 3, __list_literal__=NoneType())` - real Mojo's
        # list-literal-desugaring init; drop the marker kwarg, keep the
        # positional values as the initial contents. Plain `List[Int]()`
        # (no positional args) falls through the same path to `[]`.
        return list(args)

    def alloc(self, count, *args, **kwargs):
        return _MojoPointer([None] * count)

    def copy(self, ptr):
        return _MojoPointer(list(ptr.buffer), ptr.offset)


class _MojoDim3:
    """Mutable (x, y, z) thread/block coordinate — backs the `thread_idx`/
    `block_idx`/`block_dim`/`grid_dim` globals a GPU kernel body reads.
    Mutable and shared (one instance per interpreter, updated in place by
    `_MojoEnqueueFunctionCall` before each simulated thread's invocation)
    rather than rebound per thread, since a kernel reads these as bare
    module-level names, not as parameters it's passed."""
    def __init__(self, x=0, y=0, z=0):
        self.x = x
        self.y = y
        self.z = z

    def __repr__(self):
        return f"({self.x}, {self.y}, {self.z})"


def _mojo_as_dim3(d):
    """Normalize a `grid_dim=`/`block_dim=` argument (a bare int for 1-D, or
    an (x, y, z)-ish tuple/list) to an (x, y, z) tuple."""
    if isinstance(d, int):
        return (d, 1, 1)
    if isinstance(d, (tuple, list)):
        vals = list(d) + [1, 1, 1]
        return (vals[0], vals[1], vals[2])
    return (getattr(d, 'x', 1), getattr(d, 'y', 1), getattr(d, 'z', 1))


class MojoComplex:
    """Minimal runtime representation of Python's `j`/`J`-suffixed imaginary
    literal (`0j`, `1.5j`, `3J` — see fire_compiler.py's `ImagLiteral`) and
    the complex values that result from combining one with a real number via
    `+`/`-`. This deliberately does NOT implement the full Python `complex`
    API (no `*`, `/`, `conjugate()`, `abs()`, comparisons, ...) — per
    PARSE_FAIL_complex_number_literal's scope guidance, construction
    + printing + `+`/`-` against int/float/other MojoComplex is enough to
    cover the two real stdlib patterns that motivated this (a complex value
    sitting in a set/list literal, never used in further arithmetic).
    `__add__`/`__sub__`/`__radd__`/`__rsub__` are all that's needed for
    `left + right`/`left - right` in eval_BinaryOp to "just work" via
    Python's own operator dispatch — no changes to eval_BinaryOp itself."""
    __slots__ = ('real', 'imag')

    def __init__(self, real=0.0, imag=0.0):
        self.real = float(real)
        self.imag = float(imag)

    @staticmethod
    def _coerce(other):
        if isinstance(other, MojoComplex):
            return other.real, other.imag
        if isinstance(other, (int, float)) and not isinstance(other, bool):
            return float(other), 0.0
        return None

    def __add__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(self.real + c[0], self.imag + c[1])

    def __radd__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(c[0] + self.real, c[1] + self.imag)

    def __sub__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(self.real - c[0], self.imag - c[1])

    def __rsub__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return MojoComplex(c[0] - self.real, c[1] - self.imag)

    def __eq__(self, other):
        c = self._coerce(other)
        if c is None: return NotImplemented
        return self.real == c[0] and self.imag == c[1]

    def __hash__(self):
        # Deliberately id(self)-based, like `_MojoDeviceContext.__hash__`
        # above (a pre-existing example in this same file of the same
        # eq-by-value/hash-by-identity tradeoff) — NOT `hash((self.real,
        # self.imag))`: the self-hosted compiler (gimple_codegen.py) only
        # declares Python's `hash()` builtin as an unimplemented extern stub
        # ("undefined symbol _hash" at link time), and a `int(float_expr)`
        # replacement hit an unrelated existing gimple_codegen miscompile
        # (int() return type inferred as `char *` in this context). Per
        # PARSE_FAIL_complex_number_literal's scope guidance this
        # class isn't meant to support full value-equality hashing (e.g.
        # collapsing `{1, 1+0j}` into `{1}` the way real Python's `complex`
        # does) — just construct/print/`+`/`-` without crashing.
        return id(self)

    @staticmethod
    def _fmt(x: float) -> str:
        """Match Python complex repr's per-part float formatting: same
        shortest-round-trip digits as float repr, but WITHOUT the trailing
        `.0` float repr always adds to a whole number (e.g. `1.0` -> `1`,
        matching `repr(1+0j) == '(1+0j)'`, not `'(1.0+0j)'`)."""
        s = repr(x)
        if s.endswith('.0'):
            s = s[:-2]
        return s

    def __repr__(self):
        # A pure-imaginary value (real part is exactly positive zero) prints
        # as just "Nj", matching Python (`repr(3j) == '3j'`); everything
        # else, including negative-zero real parts, prints in full
        # "(a+bj)"/"(a-bj)" form (`repr(-0j) == '(-0-0j)'`).
        if self.real == 0.0 and math.copysign(1.0, self.real) == 1.0:
            return f"{self._fmt(self.imag)}j"
        sign = '-' if math.copysign(1.0, self.imag) < 0 else '+'
        return f"({self._fmt(self.real)}{sign}{self._fmt(abs(self.imag))}j)"

    __str__ = __repr__


class _MojoEnqueueFunctionCall:
    """`ctx.enqueue_function[kernel](*args, grid_dim=.., block_dim=..)` —
    there's no real GPU to dispatch to, so this "launches" the kernel by
    just calling it once per simulated thread, serially, on the CPU, with
    `thread_idx`/`block_idx`/`block_dim`/`grid_dim` updated before each call.
    Fine for correctness testing of small kernels; a launch with a large
    grid (real GPU workloads routinely use thousands+ of threads) will be
    slow, since this is genuinely serial — there's no parallelism here at
    all, simulated or otherwise."""
    def __init__(self, kernel, interpreter):
        self.kernel = kernel
        self.interpreter = interpreter

    def __call__(self, *args, grid_dim=1, block_dim=1, **kwargs):
        interpreter = self.interpreter
        kernel = self.kernel
        grid = _mojo_as_dim3(grid_dim)
        block = _mojo_as_dim3(block_dim)
        thread_idx = interpreter.scope.get('thread_idx')
        block_idx = interpreter.scope.get('block_idx')
        block_dim_g = interpreter.scope.get('block_dim')
        grid_dim_g = interpreter.scope.get('grid_dim')
        global_idx = interpreter.scope.get('global_idx')
        block_dim_g.x, block_dim_g.y, block_dim_g.z = block
        grid_dim_g.x, grid_dim_g.y, grid_dim_g.z = grid
        for bz in range(grid[2]):
            for by in range(grid[1]):
                for bx in range(grid[0]):
                    block_idx.x, block_idx.y, block_idx.z = bx, by, bz
                    for tz in range(block[2]):
                        for ty in range(block[1]):
                            for tx in range(block[0]):
                                thread_idx.x, thread_idx.y, thread_idx.z = tx, ty, tz
                                global_idx.x = bx * block[0] + tx
                                global_idx.y = by * block[1] + ty
                                global_idx.z = bz * block[2] + tz
                                interpreter.invoke(kernel, *args)


class _MojoEnqueueFunctionAccessor:
    def __init__(self, interpreter):
        self.interpreter = interpreter

    def __getitem__(self, item):
        # `ctx.enqueue_function[kernel]` or `[kernel, extra_type_param, ...]`
        # — the kernel function is always the first element when subscripted
        # with more than one.
        kernel = item[0] if isinstance(item, tuple) else item
        return _MojoEnqueueFunctionCall(kernel, self.interpreter)


class _MojoCreateBufferCall:
    def __init__(self, dtype):
        self.dtype = dtype

    def __call__(self, size, *args, **kwargs):
        fill = 0.0 if getattr(self.dtype, '_is_float', False) else 0
        return _MojoPointer([fill] * size)


class _MojoCreateBufferAccessor:
    def __getitem__(self, dtype):
        return _MojoCreateBufferCall(dtype)


class _MojoDeviceContext:
    """Stand-in for real Mojo's `std.gpu.host.DeviceContext`. This
    interpreter has no GPU backend of any kind (simulated or otherwise) —
    kernels launched via `enqueue_function` just run serially on the CPU,
    see `_MojoEnqueueFunctionCall`. Good enough to exercise a kernel's
    *logic* (the actual point of most stdlib correctness tests, which
    typically launch a `grid_dim=1, block_dim=1` single-thread kernel), not
    to test anything about real device dispatch, memory transfer cost, or
    concurrency."""
    def __init__(self, device_id=0, api=None, interpreter=None):
        self.device_id = device_id
        self.api = api or 'cpu'
        self.interpreter = interpreter

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def name(self):
        return "CPU (simulated — no GPU backend in this interpreter)"

    def synchronize(self):
        pass

    def __eq__(self, other):
        return isinstance(other, _MojoDeviceContext) and self.device_id == other.device_id

    def __hash__(self):
        return id(self)

    @property
    def enqueue_function(self):
        return _MojoEnqueueFunctionAccessor(self.interpreter)

    @property
    def enqueue_create_buffer(self):
        return _MojoCreateBufferAccessor()

    def enqueue_copy(self, dst, src):
        if isinstance(src, _MojoPointer):
            src.enqueue_copy_to(dst)
        else:
            for i, v in enumerate(src):
                dst[i] = v

    def enqueue_memset(self, dst, value):
        for i in range(len(dst.buffer) - dst.offset):
            dst[i] = value


class _MojoGPUInfo:
    """Stand-in for `std.gpu.host.info.GPUInfo` — real per-architecture GPU
    capability lookup. `from_name[arch]()` always returns this same generic
    placeholder, since there's no real accelerator here to describe."""
    api = "cpu"

    def __repr__(self):
        return "GPUInfo(cpu, simulated)"


class _MojoGPUInfoType:
    def __getitem__(self, item):
        return self

    def __call__(self, *args, **kwargs):
        return _MojoGPUInfo()

    @property
    def from_name(self):
        return self


class _MojoAddressSpaceValue:
    def __init__(self, name, value):
        self._name = name
        self.value = value

    def __repr__(self):
        return f"AddressSpace.{self._name}"

    def __eq__(self, other):
        if isinstance(other, _MojoAddressSpaceValue):
            return self.value == other.value
        return NotImplemented

    def __hash__(self):
        return self.value


class _MojoAddressSpaceNS:
    """Stand-in for `std.memory.pointer.AddressSpace` — an enum-like
    namespace of GPU memory-space markers. Meaningless without a real GPU
    backend; kept only so code that names/prints/compares them doesn't
    crash."""
    GENERIC = _MojoAddressSpaceValue('GENERIC', 0)
    GLOBAL = _MojoAddressSpaceValue('GLOBAL', 1)
    SHARED = _MojoAddressSpaceValue('SHARED', 2)
    CONSTANT = _MojoAddressSpaceValue('CONSTANT', 3)
    LOCAL = _MojoAddressSpaceValue('LOCAL', 4)


class _MojoTrace:
    """Stand-in for `std.runtime.tracing.Trace` — a profiling-span context
    manager. No-op here; there's no real runtime to trace."""
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _MojoInvokeWrapper:
    """A plain-callable adapter around Interpreter.invoke, so real Python
    builtins (map/filter) that call their function argument directly
    (`func(item)`) can invoke a MojoFunction (which needs the interpreter
    threaded through as its first argument) transparently."""
    def __init__(self, func, interpreter):
        self._func = func
        self._interpreter = interpreter

    def __call__(self, *args, **kwargs):
        func = self._func
        interpreter = self._interpreter
        return interpreter.invoke(func, *args, **kwargs)


class _MojoBoundArgCall:
    """Result of `map[func]`/`filter[func]` — the wrapped builtin partially
    applied with `func` as its first (call-time) argument."""
    def __init__(self, fn, wrapped_func):
        self._fn = fn
        self._wrapped_func = wrapped_func

    def __call__(self, *args, **kwargs):
        fn = self._fn
        wrapped_func = self._wrapped_func
        # `map`/`filter` take the callable as their FIRST positional and the
        # iterable as their SECOND (or, for `map`, further ones). The first-arg
        # rule in `_mojo_builtin_args` does not reach these calls because they
        # arrive here as a `_MojoBoundArgCall`, not through `invoke` — so a
        # Mojo iterable struct passed to `map[f](c)` fell through to
        # `__getitem__` and died with `KeyError: 0`. Apply the same
        # `_mojo_iterable` treatment to every argument after the callable.
        return fn(wrapped_func, *(_mojo_iterable(a) for a in args), **kwargs)


class _MojoParametricFn:
    """Wraps a builtin like `map` that real Mojo calls as `map[func](iterable)`
    — the function argument goes in the subscript, not the call parens (the
    subscript is Mojo's compile-time-parameter syntax, here just borrowed for
    an ordinary runtime argument). `[func]` curries it in; the returned
    callable then takes the normal call-time arguments."""
    def __init__(self, fn, interpreter):
        self._fn = fn
        self._interpreter = interpreter

    def __getitem__(self, bound_arg):
        wrapped_func = _MojoInvokeWrapper(bound_arg, self._interpreter)
        return _MojoBoundArgCall(self._fn, wrapped_func)

    def __call__(self, *args, **kwargs):
        fn = self._fn
        if not args:
            return fn(**kwargs)
        # `map`/`filter` take the callable as FIRST positional and iterables
        # after that. Convert Mojo iterable structs so Python's own builtin
        # sees them as generators rather than falling through to `__getitem__`.
        return fn(args[0], *(_mojo_iterable(a) for a in args[1:]), **kwargs)


class _MojoScalarType:
    """A sized Mojo scalar type (Int8/UInt32/Float32/...). Plain Python
    int/float already behave like the value side of these types; this only
    carries the `.size_bytes` metadata that `size_of[T]()`/`align_of[T]()`/
    `bit_width_of[T]()` read off the type itself."""
    def __init__(self, name, size_bytes, is_float=False):
        self.name = name
        self.size_bytes = size_bytes
        self._is_float = is_float

    def __call__(self, x=0):
        return float(x) if self._is_float else int(x)

    def __repr__(self):
        return self.name

    def is_floating_point(self):
        return self._is_float

    def is_integral(self):
        return not self._is_float

    def is_signed(self):
        return not self.name.startswith('UInt')

    def is_unsigned(self):
        return self.name.startswith('UInt')

    def is_half_float(self):
        return self.name in ('Float16', 'BFloat16')

    def is_single_float(self):
        return self.name == 'Float32'

    def is_double_float(self):
        return self.name == 'Float64'


class _MojoTypeInfoCall:
    def __init__(self, fn, type_arg):
        self._fn = fn
        self._type_arg = type_arg

    def __call__(self):
        fn = self._fn
        type_arg = self._type_arg
        return fn(type_arg)


class _MojoTypeInfoFn:
    """`size_of[T]()`/`align_of[T]()`/`simd_width_of[T]()`/`bit_width_of[T]()`
    — subscript with a type (or DType.xxx value), call with no arguments."""
    def __init__(self, fn):
        self._fn = fn

    def __getitem__(self, type_arg):
        fn = self._fn
        return _MojoTypeInfoCall(fn, type_arg)


class _MojoConstCall:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class _MojoGetDefinedFn:
    """`get_defined_bool["NAME", default]()`/`get_defined_int[...]` — reads a
    compile-time `-D` define, subscripted as `[name, default]`. This
    interpreter has no build-time define mechanism, so it always falls back
    to whatever default the call site supplied."""
    def __getitem__(self, args):
        default = args[1] if isinstance(args, tuple) and len(args) >= 2 else None
        return _MojoConstCall(default)


class _MojoIsDefinedFn:
    """`is_defined["MODULAR_SOME_FLAG"]()` — no build-time `-D` define
    mechanism here, so always False."""
    def __getitem__(self, name):
        return _MojoConstCall(False)


def _mojo_size_of(t):
    return getattr(t, 'size_bytes', 8)


def _mojo_bit_width_of(t):
    return getattr(t, 'size_bytes', 8) * 8


def _mojo_simd_width_of(t):
    # Not hardware-accurate (real Mojo picks this per-target); 1 is at least
    # a self-consistent value (a "vector" of width 1 is just the scalar).
    return 1


class _MojoCompilationTarget:
    """Stand-in for real Mojo's `sys.info.CompilationTarget` platform-predicate
    namespace. Answers for *this* interpreter host (macOS/arm64), not
    whatever `fire build` would actually target — fine for the predicates
    stdlib tests branch on, since we're not cross-compiling."""
    def is_macos(self):
        return sys.platform == 'darwin'

    def is_linux(self):
        return sys.platform.startswith('linux')

    def is_apple_silicon(self):
        return sys.platform == 'darwin' and platform.machine() == 'arm64'

    def is_apple_m1(self): return False
    def is_apple_m2(self): return False
    def is_apple_m3(self): return False
    def is_apple_m4(self): return False
    def is_apple_m5(self): return False
    def has_neon(self):
        return platform.machine() == 'arm64'
    def has_neon_int8_dotprod(self): return False
    def has_neon_int8_matmul(self): return False
    def has_avx(self): return False
    def has_avx2(self): return False
    def has_avx512f(self): return False
    def has_sse4(self): return False
    def has_fma(self): return False
    def has_vnni(self): return False
    def has_intel_amx(self): return False


def _mojo_simd_elementwise(a, b, fn):
    """Combine two SIMD-or-scalar operands lane-by-lane with `fn` (used for
    arithmetic operators and for the elementwise `min`/`max` builtins Mojo
    overloads for SIMD — unlike Python's own min/max, which just pick one of
    their two whole arguments)."""
    if isinstance(a, _MojoSIMD) and isinstance(b, _MojoSIMD):
        return _MojoSIMD(a.dtype, a.width, [fn(x, y) for x, y in zip(a.values, b.values)])
    if isinstance(a, _MojoSIMD):
        return _MojoSIMD(a.dtype, a.width, [fn(x, b) for x in a.values])
    if isinstance(b, _MojoSIMD):
        return _MojoSIMD(b.dtype, b.width, [fn(a, y) for y in b.values])
    return fn(a, b)


def _scalar_max2(a, b):
    if a > b:
        return a
    return b


def _scalar_min2(a, b):
    if a < b:
        return a
    return b


def _mojo_operator_index(x):
    """Stand-in for `operator.index` — this file's own compiled form can't
    reach CPython's operator module (`import operator` binds a placeholder
    marker, and reading `.index` off it raises AttributeError at runtime),
    so setup_builtins' `index` binding needs a self-contained equivalent.
    Real operator.index raises TypeError on anything without __index__;
    accepting plain int()/float-truncation here is looser, but every
    in-tree caller passes values that are already integral."""
    return int(x)


def _mojo_isnan(x):
    """NaN check without the math module (same compiled-binary constraint
    as _mojo_operator_index): NaN is the only value not equal to itself."""
    return x != x


def _mojo_isinf(x):
    """Inf check without math: inf - inf == NaN (not 0), while every
    finite value minus itself is exactly 0; NaN itself is excluded by the
    self-equality guard."""
    return x == x and (x - x) != 0


def _mojo_isfinite(x):
    """Finite check without math: neither NaN nor +/-inf."""
    return x == x and (x - x) == 0


def _mojo_extreme(items, key, want_max):
    """The largest/smallest element of `items` by `key` (identity by
    default). ONE implementation for `_mojo_min` and `_mojo_max`: they differ
    only in which comparison wins, and a user `key=` makes that the whole
    behaviour, so a shared walker is what keeps the two from drifting apart
    again.

    `key` is invoked as `key(x)` on the value itself, deliberately NOT through
    `Interpreter.invoke`: a `MojoFunction`'s `__call__` resolves the
    interpreter from its own record now (see its docstring), so a bare call is
    correct for a user-defined callee, and a plain Python callable needs no
    threading at all."""
    result = None
    best_key = None
    have_result = False
    for x in items:
        k = x if key is None else key(x)
        if not have_result:
            result = x
            best_key = k
            have_result = True
        elif (k > best_key if want_max else k < best_key):
            result = x
            best_key = k
    return result


def _mojo_minmax(want_max, *args, **kwargs):
    """Shared body of `_mojo_max` / `_mojo_min`.

    Mojo overloads `max` for SIMD to mean elementwise max, not "pick one
    of these two whole values" like Python's own builtin. Deliberately
    avoids ever calling the bare name `max(...)`/`min(...)`: this file is
    self-hosted-compiled together with gimple_codegen.py, which has an
    existing single-positional-plus-`key=`-kwarg call site
    (`max(survivors, key=_score)`) that fixes the self-host compiler's
    static arity inference for the global `max` symbol at 1 argument —
    calling it here with 2 positional args breaks that compile
    ("too many arguments to function 'mojo_max'").

    `key=` is honoured here rather than delegated to Python's builtin (same
    reason the two-positional SIMD form cannot be). It was not honoured at
    all: `min([3, 1, 2], key=lambda a: -a)` returned `1` — the unkeyed
    minimum — and `max(...)` returned `3`, so both silently answered a
    different question than the one asked."""
    scalar_max2 = _scalar_max2 if want_max else _scalar_min2
    if len(args) == 2 and not kwargs:
        a, b = args
        if isinstance(a, _MojoSIMD) or isinstance(b, _MojoSIMD):
            return _mojo_simd_elementwise(a, b, scalar_max2)
        return scalar_max2(a, b)
    items = args[0] if len(args) == 1 else args
    return _mojo_extreme(items, kwargs.get('key'), want_max)


def _mojo_max(*args, **kwargs):
    return _mojo_minmax(True, *args, **kwargs)


def _mojo_min(*args, **kwargs):
    return _mojo_minmax(False, *args, **kwargs)


def _mojo_iter(value):
    """`iter(value)` for a struct that defines its own `__iter__`.

    Python's `iter()` and `next()` look the protocol method up on the TYPE,
    and `MojoInstance` only forwards attribute reads (`__getattr__`) to the
    Mojo method table, so a Mojo struct with `__iter__`/`__next__` was not an
    iterator here: `next(c)` raised "'MojoInstance' object is not an
    iterator", and `for x in c` fell through to `__getitem__` and died with
    `KeyError: 0`. The fix is to drive the Mojo protocol explicitly, the way
    `__len__`/`__getitem__` already forward. A struct WITHOUT `__iter__`
    keeps the old `iter()` behaviour (its `__getitem__` sequence fallback is
    unchanged). Exhaustion is the Mojo `__next__` raising `StopIteration`,
    which is a real Python exception, so it propagates unchanged."""
    if isinstance(value, MojoInstance):
        # Annotated: `value` is unannotated, so `value._mojo_class` is typed as a
        # word unless the local says what it is; `cls.methods.get` then lowered
        # to `mojo_dict_get_int(<int64>, ...)` (gcc: "makes pointer from integer").
        cls: 'MojoClass' = value._mojo_class
        method = cls.methods.get('__iter__')
        if method is not None:
            return _mojo_struct_iter_steps(cls, method(cls.interpreter, value))
    return iter(value)


def _mojo_struct_iter_steps(cls, iterator):
    """Yield the values of a Mojo iterator object by calling its `__next__`
    until that raises `StopIteration`. `iterator` is whatever the struct's
    `__iter__` returned (usually `self`)."""
    while True:
        try:
            yield _mojo_next(iterator)
        except StopIteration:
            return


def _mojo_next(iterator, *default):
    """`next(iterator[, default])` that also drives a Mojo struct's own
    `__next__`. Anything that is not a `MojoInstance` goes to the builtin
    unchanged. A struct without `__next__` is refused with CPython's own
    message for a non-iterator."""
    if not isinstance(iterator, MojoInstance):
        return next(iterator, *default)
    cls: 'MojoClass' = iterator._mojo_class
    method = cls.methods.get('__next__')
    if method is None:
        raise TypeError(f"'{cls.name}' object is not an iterator")
    if default:
        try:
            return method(cls.interpreter, iterator)
        except StopIteration:
            return default[0]
    return method(cls.interpreter, iterator)

def _mojo_reversed(value):
    """CPython's `reversed()` only accepts objects with `__reversed__` or a
    sequence protocol. A MojoInstance without either is refused with the
    matching message instead of falling through to `__getitem__` and dying
    with `KeyError: 0`."""
    if isinstance(value, MojoInstance):
        cls = value._mojo_class
        if '__reversed__' in cls.methods:
            # Call the reversed method and wrap result as an iterator
            rev_method = cls.methods['__reversed__']
            rev_result = rev_method(cls.interpreter, value)
            return _mojo_iter(rev_result)
        # Check for sequence protocol (has __len__ and __getitem__)
        if '__len__' in cls.methods and '__getitem__' in cls.methods:
            # CPython reversed works directly on sequences
            return value
        # Not reversible - raise proper TypeError matching CPython
        raise TypeError(f"'{cls.name}' object is not reversible")
    # For non-MojoInstance values, let CPython handle it
    return reversed(value)


def _mojo_iterable(value):
    """A value handed to one of Python's own iterable-consuming builtins.

    Those builtins call `iter()` on the argument, which looks `__iter__` up
    on the TYPE, so a `MojoInstance` with a Mojo `__iter__` was not iterable
    to them (`list(c)` fell through to `__getitem__` and died with
    `KeyError: 0`). Such a struct is handed over as the `_mojo_iter` generator
    instead. Anything else is returned untouched, so builtins keep their
    exact argument semantics for every other value."""
    if isinstance(value, MojoInstance) and '__iter__' in value._mojo_class.methods:
        return _mojo_iter(value)
    return value


# Builtins that iterate their first positional argument, identified by
# `id()` because builtins live for the whole process and an `id` test never
# hashes the callee (a Mojo value may be unhashable). `zip` iterates every
# positional argument; `min`/`max` iterate only when given ONE argument —
# `max(a, b)` compares values and must not turn a struct into a generator.
_MOJO_ITER_FIRST_ARG = {id(list), id(tuple), id(set), id(frozenset), id(sum),
                        id(sorted), id(enumerate), id(any), id(all), id(dict)}
if hasattr(builtins, 'frozendict'):
    _MOJO_ITER_FIRST_ARG.add(id(builtins.frozendict))
_MOJO_ITER_ALL_ARGS = id(zip)
_MOJO_ITER_ONE_ARG = {id(_mojo_min), id(_mojo_max)}


def _mojo_builtin_args(func, args):
    """`args` with any Mojo iterable struct passed to `func` replaced by its
    `_mojo_iterable` form. Only the calls `invoke` routes here are touched."""
    key = id(func)
    if key == _MOJO_ITER_ALL_ARGS:
        return tuple(_mojo_iterable(a) for a in args)
    if key in _MOJO_ITER_ONE_ARG:
        if len(args) != 1:
            return args
    elif key not in _MOJO_ITER_FIRST_ARG or not args:
        return args
    return (_mojo_iterable(args[0]),) + tuple(args[1:])


class _MojoSIMD:
    """Stand-in for real Mojo's `SIMD[dtype, width]` vector type. No real
    vectorization/hardware backend here — just a fixed-width list of scalars
    with elementwise arithmetic. `==`/`!=` compare whole vectors (True only
    if every lane matches, returning a plain bool) rather than real Mojo's
    per-lane vector result, since that's what `assert_equal(simd_a, simd_b)`
    needs; ordering comparisons (`<`, `>`, ...) return a real elementwise
    `_MojoSIMD` of bools, closer to actual Mojo semantics."""
    def __init__(self, dtype, width, values):
        values = list(values)
        if len(values) == 1 and width > 1:
            values = values * width
        self.dtype = dtype
        self.width = width
        self.values = values

    def _binary(self, other, fn):
        return _mojo_simd_elementwise(self, other, fn)

    def __add__(self, other): return self._binary(other, operator.add)
    def __radd__(self, other): return _mojo_simd_elementwise(other, self, operator.add)
    def __sub__(self, other): return self._binary(other, operator.sub)
    def __rsub__(self, other): return _mojo_simd_elementwise(other, self, operator.sub)
    def __mul__(self, other): return self._binary(other, operator.mul)
    def __rmul__(self, other): return _mojo_simd_elementwise(other, self, operator.mul)
    def __truediv__(self, other): return self._binary(other, operator.truediv)
    def __rtruediv__(self, other): return _mojo_simd_elementwise(other, self, operator.truediv)
    def __floordiv__(self, other): return self._binary(other, operator.floordiv)
    def __mod__(self, other): return self._binary(other, operator.mod)
    def __pow__(self, other): return self._binary(other, operator.pow)
    def __and__(self, other): return self._binary(other, operator.and_)
    def __or__(self, other): return self._binary(other, operator.or_)
    def __xor__(self, other): return self._binary(other, operator.xor)
    def __neg__(self): return _MojoSIMD(self.dtype, self.width, [-v for v in self.values])
    def __abs__(self): return _MojoSIMD(self.dtype, self.width, [abs(v) for v in self.values])

    def __eq__(self, other):
        if isinstance(other, _MojoSIMD):
            return self.values == other.values
        return all(v == other for v in self.values)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = None

    def __lt__(self, other): return self._binary(other, operator.lt)
    def __gt__(self, other): return self._binary(other, operator.gt)
    def __le__(self, other): return self._binary(other, operator.le)
    def __ge__(self, other): return self._binary(other, operator.ge)

    def __getitem__(self, i): return self.values[i]
    def __setitem__(self, i, v): self.values[i] = v
    def __len__(self): return len(self.values)
    def __iter__(self): return iter(self.values)
    def __bool__(self): return all(bool(v) for v in self.values)

    def __repr__(self):
        vals = ', '.join(str(v) for v in self.values)
        return f"SIMD[{self.width}]({vals})"


class _MojoSIMDCtor:
    def __init__(self, dtype, width):
        self.dtype = dtype
        self.width = width

    def __call__(self, *values):
        return _MojoSIMD(self.dtype, self.width, values)


class _MojoSIMDType:
    """`SIMD[DType.float32, 4](0.0, 1.5, -42.5, -12.7)` — subscript with
    (dtype, width), call with `width` scalar values (or a single value,
    broadcast to fill every lane)."""
    def __getitem__(self, item):
        dtype, width = item
        return _MojoSIMDCtor(dtype, width)


class MojoString(str):
    """`str` subclass carrying the extra methods real Mojo's String/
    StringSlice/StaticString expose that plain Python str doesn't
    (`byte_length`, `ascii_*`, `is_ascii_*`, `__float__`) — subclassing
    (rather than wrapping) means it still behaves exactly like a normal
    string everywhere else: comparisons, isinstance checks, concatenation,
    dict keys, etc. Operations not overridden here (slicing, `+`, `.upper()`)
    fall back to plain `str` and lose these extra methods on their result —
    a known gap, not attempted, since re-deriving MojoString from every
    str method would be a much bigger change for marginal benefit."""
    def byte_length(self):
        return len(str.encode(self, 'utf-8'))

    def is_ascii_digit(self):
        return str.isascii(self) and str.isdigit(self)

    def is_ascii_printable(self):
        return str.isascii(self) and all(32 <= ord(c) <= 126 for c in self)

    def ascii_rjust(self, width, fillchar=' '):
        return MojoString(str.rjust(self, width, fillchar))

    def ascii_ljust(self, width, fillchar=' '):
        return MojoString(str.ljust(self, width, fillchar))

    def ascii_center(self, width, fillchar=' '):
        return MojoString(str.center(self, width, fillchar))

    def __float__(self):
        return float(str(self))

    def codepoints(self):
        return list(self)

    def codepoint_slices(self):
        return list(self)


class _MojoBoolType:
    MIN = False
    MAX = True
    def __call__(self, x=False):
        return bool(x)


class _MojoIntType:
    MIN = -(2 ** 63)
    MAX = 2 ** 63 - 1
    def __call__(self, x=0):
        return int(x)


class _MojoUIntType:
    MIN = 0
    MAX = 2 ** 64 - 1
    def __call__(self, x=0):
        return int(x)


def _mojo_resolve_ambiguous_empty_braces(a, b):
    """See Interpreter._resolve_ambiguous_empty_braces — same `{}`-as-empty-
    dict-vs-empty-set ambiguity, needed here too since `assert_equal(x, {})`
    compares a real set against a literal dict `{}` the parser can't have
    known should have been a set."""
    if isinstance(a, set) and isinstance(b, dict) and not b:
        b = set()
    elif isinstance(b, set) and isinstance(a, dict) and not a:
        a = set()
    return a, b


def _mojo_assert_equal(a, b, msg=None):
    a, b = _mojo_resolve_ambiguous_empty_braces(a, b)
    if a != b:
        raise AssertionError(msg or f"AssertionError: {a!r} is not equal to {b!r}")


def _mojo_assert_not_equal(a, b, msg=None):
    if a == b:
        raise AssertionError(msg or f"AssertionError: {a!r} is equal to {b!r}")


def _mojo_assert_true(cond, msg=None):
    if not cond:
        raise AssertionError(msg or "AssertionError: condition was unexpectedly False")


def _mojo_assert_false(cond, msg=None):
    if cond:
        raise AssertionError(msg or "AssertionError: condition was unexpectedly True")


def _mojo_assert_almost_equal(a, b, msg=None, atol=1e-8, rtol=1e-5):
    if abs(a - b) > atol + rtol * abs(b):
        raise AssertionError(msg or f"AssertionError: {a!r} is not close to {b!r}")


class _MojoAssertRaises:
    """`with assert_raises(): ...` / `with assert_raises(contains="x"): ...`
    — asserts the block raises (optionally with a matching message)."""
    def __init__(self, contains=None, location=None):
        self.contains = contains

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError("AssertionError: Didn't raise")
        contains = self.contains
        if contains is not None and contains not in str(exc_val):
            return False
        return True


class _MojoTestSuiteRunner:
    """Backs `TestSuite.discover_tests[__functions_in_module()]().run()`, the
    boilerplate every stdlib test file ends with. Mirrors real Mojo's own
    `PASS/FAIL ... Summary ...` console output (see `stdlib/std/testing/suite.mojo`)
    closely enough to be a drop-in for the interpreter, though real Mojo also
    times each test — we don't bother, since nothing downstream reads timings."""
    def __init__(self, funcs, interpreter):
        self.funcs = funcs
        self.interpreter = interpreter
        self.skipped_names = set()

    @property
    def skip(self):
        runner = self
        return _MojoTestSuiteRunnerSkipAccessor(runner)

    def run(self, quiet=False, skip_all=False):
        filename = self.interpreter.filename or '<input>'
        if not quiet:
            print(f"Running {len(self.funcs)} tests for {filename} ")
        passed, failed, skipped = 0, 0, 0
        for name, func in self.funcs:
            if skip_all or name in self.skipped_names:
                if not quiet:
                    print(f"    SKIP [ 0.001 ] {name}")
                skipped += 1
                continue
            try:
                func(self.interpreter)
                if not quiet:
                    print(f"    PASS [ 0.001 ] {name}")
                passed += 1
            except Exception as e:
                if not quiet:
                    print(f"    FAIL [ 0.001 ] {name}: {e}")
                failed += 1
        if not quiet:
            print("--------")
            total = passed + failed + skipped
            print(f"Summary [ 0.001 ] {total} tests run: {passed} passed , {failed} failed , {skipped} skipped ")
        if failed:
            raise AssertionError(f"{failed} test(s) failed")


class _MojoTestSuiteRunnerSkipToken:
    def __init__(self, runner, func):
        self.runner = runner
        self.func = func

    def __call__(self):
        runner = self.runner
        func = self.func
        name = None
        for n, f in runner.funcs:
            if f is func:
                name = n
                break
        if name is None:
            fn_name = getattr(func, 'name', str(func))
            raise Exception(
                f"trying to skip a test that is not registered in the suite: {fn_name}"
            )
        runner.skipped_names.add(name)


class _MojoTestSuiteRunnerSkipAccessor:
    def __init__(self, runner):
        self.runner = runner

    def __getitem__(self, func):
        runner = self.runner
        return _MojoTestSuiteRunnerSkipToken(runner, func)


class _MojoTestSuiteDiscoverToken:
    def __init__(self, funcs, interpreter):
        self.funcs = funcs
        self.interpreter = interpreter

    def __call__(self, *args, **kwargs):
        # Real Mojo's TestSuite() call site sometimes passes `cli_args=...`
        # (for suites with their own argv handling) — irrelevant here.
        return _MojoTestSuiteRunner(self.funcs, self.interpreter)


class _MojoTestSuiteDiscover:
    def __init__(self, interpreter):
        self.interpreter = interpreter

    def __getitem__(self, funcs):
        test_funcs = [(n, f) for n, f in funcs if n.startswith('test_')]
        interpreter = self.interpreter
        return _MojoTestSuiteDiscoverToken(test_funcs, interpreter)


class _MojoTestSuite:
    """Stand-in for real Mojo's `testing.TestSuite`. `discover_tests` is
    subscripted (`discover_tests[funcs]`), not called directly, mirroring the
    real API's `discover_tests[__functions_in_module()]()` call shape."""
    def __init__(self, interpreter):
        self.interpreter = interpreter

    def __call__(self):
        return self

    @property
    def discover_tests(self):
        interpreter = self.interpreter
        return _MojoTestSuiteDiscover(interpreter)

    @property
    def test(self):
        interpreter = self.interpreter
        return _MojoTestSuiteFnAccessor(interpreter, run=True)

    @property
    def skip(self):
        interpreter = self.interpreter
        return _MojoTestSuiteFnAccessor(interpreter, run=False)


class _MojoTestSuiteFnCall:
    def __init__(self, func, interpreter, run):
        self.func = func
        self.interpreter = interpreter
        self.run = run

    def __call__(self):
        if not self.run:
            return None
        interpreter = self.interpreter
        func = self.func
        return interpreter.invoke(func)


class _MojoTestSuiteFnAccessor:
    """Backs `suite.test[fn]()` (run `fn` immediately) and `suite.skip[fn]()`
    (don't) — subscript with the test function, call with no arguments."""
    def __init__(self, interpreter, run):
        self.interpreter = interpreter
        self.run = run

    def __getitem__(self, func):
        interpreter = self.interpreter
        run = self.run
        return _MojoTestSuiteFnCall(func, interpreter, run)


def _mojo_unary_math(fn):
    """Wrap a scalar math function so it also applies elementwise to a
    `_MojoSIMD` operand — matching how real Mojo's `std.math` functions are
    overloaded for both `Scalar[dtype]` and `SIMD[dtype, width]`."""
    def wrapper(x, *args, **kwargs):
        if isinstance(x, _MojoSIMD):
            return _MojoSIMD(x.dtype, x.width, [fn(v, *args, **kwargs) for v in x.values])
        return fn(x, *args, **kwargs)
    return wrapper


def _mojo_iota(buf, *args):
    """`iota(buf)` / `iota(buf, offset)` / `iota(buf, length, offset)` — fill
    (part of) a buffer in place with sequential values."""
    if len(args) >= 2:
        length, offset = args[0], args[1]
    elif len(args) == 1:
        offset = args[0]
        length = len(buf)
    else:
        offset = 0
        length = len(buf)
    for i in range(length):
        buf[i] = offset + i


def _mojo_ceildiv(a, b):
    return -(-a // b)


def _build_math_shims():
    """`from std.math import ...` — the real `std/math/math.mojo` is
    parametric/generic-heavy like `std/testing`; hardcode plain Python `math`
    equivalents for the handful of names stdlib test files actually import,
    each also elementwise-applicable to a `_MojoSIMD` (see
    _mojo_unary_math)."""
    return {
        'exp': _mojo_unary_math(math.exp),
        'exp2': _mojo_unary_math(lambda x: 2.0 ** x),
        'log': _mojo_unary_math(math.log),
        'log2': _mojo_unary_math(math.log2),
        'log10': _mojo_unary_math(math.log10),
        'sqrt': _mojo_unary_math(math.sqrt),
        'rsqrt': _mojo_unary_math(lambda x: 1.0 / math.sqrt(x)),
        'recip': _mojo_unary_math(lambda x: 1.0 / x),
        'sin': _mojo_unary_math(math.sin),
        'cos': _mojo_unary_math(math.cos),
        'tan': _mojo_unary_math(math.tan),
        'sinh': _mojo_unary_math(math.sinh),
        'cosh': _mojo_unary_math(math.cosh),
        'tanh': _mojo_unary_math(math.tanh),
        'asin': _mojo_unary_math(math.asin),
        'acos': _mojo_unary_math(math.acos),
        'atan': _mojo_unary_math(math.atan),
        'atan2': math.atan2,
        'erf': _mojo_unary_math(math.erf),
        'floor': _mojo_unary_math(math.floor),
        'ceil': _mojo_unary_math(math.ceil),
        'trunc': _mojo_unary_math(math.trunc),
        'isnan': _mojo_unary_math(math.isnan),
        'isinf': _mojo_unary_math(math.isinf),
        'isfinite': _mojo_unary_math(math.isfinite),
        'gcd': math.gcd,
        'lcm': math.lcm,
        'ceildiv': _mojo_ceildiv,
        'modf': math.modf,
        'ldexp': math.ldexp,
        'frexp': math.frexp,
        'inf': math.inf,
        'iota': _mojo_iota,
    }


def _build_testing_shims(interpreter):
    """`from std.testing import ...` (or `testing`/`std.testing.testing`) can't
    realistically run through the real stdlib source — it's full of generic
    `fn foo[...]` parametrics our simple parser/interpreter doesn't support.
    Hardcode the handful of names stdlib test files actually use instead, the
    same way module_loader.py already hardcodes `_TESTING_EXPORTS` for the
    compiled path."""
    shims = {
        'assert_equal': _mojo_assert_equal,
        'assert_equal_pyobj': _mojo_assert_equal,
        'assert_not_equal': _mojo_assert_not_equal,
        'assert_true': _mojo_assert_true,
        'assert_false': _mojo_assert_false,
        'assert_almost_equal': _mojo_assert_almost_equal,
        'assert_raises': _MojoAssertRaises,
        'TestSuite': _MojoTestSuite(interpreter),
    }
    # `from std.testing import testing, TestSuite` imports the submodule
    # itself as a namespace (`testing.assert_equal(...)`) — self-reference,
    # one level deep (nothing in the corpus goes further than `testing.X`).
    shims['testing'] = types.SimpleNamespace(**shims)
    return shims


class _MojoSuper:
    """Proxy returned by `super` inside a struct method. `super.__init__(tag)`
    resolves to the parent struct's `__init__` method bound to `self`, so the
    call passes `self` as the first argument automatically.

    Uses `__getattribute__` (not `__getattr__`) because `__init__` is a special
    method name — Python finds it as a class attribute (the constructor) before
    consulting `__getattr__`, so `super.__init__` would return the bound
    constructor instead of the parent struct's `__init__`."""
    def __init__(self, base_class, self_instance, interpreter):
        object.__setattr__(self, '_base_class', base_class)
        object.__setattr__(self, '_self', self_instance)
        object.__setattr__(self, '_interpreter', interpreter)

    def __getattribute__(self, name):
        base_cls = object.__getattribute__(self, '_base_class')
        if name in base_cls.methods:
            return BoundMethod(
                base_cls.methods[name],
                object.__getattribute__(self, '_self'),
                object.__getattribute__(self, '_interpreter'))
        if name in ('_base_class', '_self', '_interpreter'):
            return object.__getattribute__(self, name)
        if name in base_cls.comptime_aliases:
            return base_cls.comptime_aliases[name]
        raise _tag_attribute_error(
            AttributeError(f"super object has no attribute '{name}'"),
            self, name)


_AUTO_STUB_VALUE = 0

class _AutoStubValue(int):
    """Auto-stub value that behaves like integer 0 but is also callable
    (returns self) and supports attribute access (returns self) — so
    it works as a drop-in for missing constants like ErrNo.EPERM, and
    when called like a function, it just returns 0."""
    def __new__(cls, val=0):
        return int.__new__(cls, val)
    def __call__(self, *args, **kwargs):
        return _AutoStubValue(_AUTO_STUB_VALUE)
    def __getattr__(self, name):
        return self
    def __getitem__(self, key):
        return self
    def __setitem__(self, key, value):
        pass
    def __len__(self):
        return 0


class _MojoModuleObject(types.SimpleNamespace):
    """A MODULE OBJECT that is a live view of an imported module's own scope,
    rather than a `SimpleNamespace` snapshot of it taken the moment the module
    body finished.

    **The snapshot was a silent wrong answer, and it was wrong in the one place
    that matters.** `types.SimpleNamespace(**mod_interp.scope.vars)` COPIED the
    module's top-level bindings, while the module's own functions kept reading
    and writing `mod_interp.scope.vars` — the live dict. So for any name the
    module's own code assigns, there were two homes:

        i_lib.mojo:  G = 5
                     def setg(v): global G; G = v
                     def get_it(): global G; return G
        i_prog.mojo: import i_lib
                     i_lib.setg(9)
                     print(i_lib.get_it())   # 9 — the live scope
                     print(i_lib.G)          # 5 — the snapshot

    Two reads of the same module disagreeing inside one program, with no
    diagnostic and no error: `G = v` visibly did nothing as far as any other
    reader of `i_lib` was concerned. CPython answers 9 and 9, because a module
    object's attribute IS its `__dict__` and the module's functions read that
    same dict.

    So this delegates instead of copying. Every direction Python has:

      * `mod.X` reads `scope.vars['X']` — through the parent chain, so a name
        the module never declared but inherited from its own enclosing scope
        still resolves, exactly as `mod_interp.scope.get` would;
      * `mod.X = v` writes `scope.vars['X']`, which is what the module's own
        `global X` writes, so an assignment from outside is visible to the
        module's functions immediately and in the other direction too. Before
        this, such an assignment created a FOURTH home: an attribute on the
        snapshot, which no function ever reads;
      * `del mod.X` removes it from `scope.vars`;
      * `dir(mod)` lists what the module currently has, so a REPL-ish
        `dir(mod)` after a `global` write shows the write.

    Subclasses `types.SimpleNamespace` rather than replacing it, for one
    concrete reason: `_bind_dotted_import` walks a dotted import chain with
    `isinstance(nxt, types.SimpleNamespace)`, and every other reader of a
    module object in this file does the same. `SimpleNamespace.__init__` is NOT
    called, so the instance `__dict__` stays empty, which is what makes
    `__getattr__` fire for EVERY name instead of shadowing it — and `__setattr__`
    is overridden so that an assignment cannot quietly land in that `__dict__`
    and become the fourth home this class exists to remove.

    Two attribute names are therefore NOT delegated, and both are dunder-shaped
    (`__modvars__`, `__modname__`, trailing underscores so no name mangling
    applies) because the alternative was worse: Python resolves an instance
    attribute before it calls `__getattr__`, so any plain name held here would
    shadow a module global of the same name, and `__slots__` does not help —
    a subclass of `SimpleNamespace` inherits its `__dict__` regardless. They
    are excluded from `__dir__` for the same reason. No Mojo source in this
    repository defines either.

    The reference keeps the module's `Interpreter` alive — the thing whose
    scope the module's own functions read — which is what makes a write through
    the module object and a write through `global` the same write.
    """

    def __init__(self, scope_vars, modname):
        # Bypass SimpleNamespace.__init__ (which would populate __dict__) and
        # write the two fields through object.__setattr__ so the overridden
        # __setattr__ below — which needs __modvars__ to exist — is not
        # re-entered.
        object.__setattr__(self, '__modvars__', scope_vars)
        object.__setattr__(self, '__modname__', modname)

    def __getattr__(self, name):
        # Only reached for a name NOT in the instance __dict__, which is every
        # module name, because __init__ deliberately left it empty.
        try:
            return self.__modvars__[name]
        except KeyError:
            raise _tag_attribute_error(
                AttributeError(
                    f"module '{self.__modname__}' has no attribute '{name}'"),
                self, name)

    def __setattr__(self, name, value):
        self.__modvars__[name] = value

    def __delattr__(self, name):
        try:
            del self.__modvars__[name]
        except KeyError:
            raise _tag_attribute_error(
                AttributeError(
                    f"module '{self.__modname__}' has no attribute '{name}'"),
                self, name)

    def __dir__(self):
        return sorted(set(self.__modvars__) | set(object.__dir__(self))
                      - {'__modvars__', '__modname__'})

    def __repr__(self):
        return f"<module {self.__modname__}>"


class _AutoStubNamespace:
    """Auto-stubbing namespace: any attribute access returns AutoStubValue(0)
    which behaves as integer 0 in arithmetic, is callable (returns 0), and
    supports attribute/bracket access (returns self) — so it can stand in
    for missing constants, functions, and types without crashing."""
    def __getattr__(self, name):
        return _AutoStubValue(_AUTO_STUB_VALUE)
    def __getitem__(self, key):
        return _AutoStubValue(_AUTO_STUB_VALUE)
    def __call__(self, *args, **kwargs):
        return _AutoStubValue(_AUTO_STUB_VALUE)


class _SysProxy:
    """Presents the executed program's own argv (`[filename] + program_args`)
    while forwarding everything else to the real `sys` module. Without this,
    interpreted code that reads `sys.argv` sees the *host* process's live
    argv instead of its own — harmless for most scripts, but fatal for
    self-referential ones: `fire run fire.py help` would otherwise have the
    nested interpretation of fire.py re-read the unchanged host argv, take
    the same branch, and re-interpret itself forever.

    Encoding functions are overridden to guarantee PEP 686 semantics (UTF-8
    is the default encoding), independent of the host Python's configuration.
    """
    def __init__(self, argv):
        self.argv = argv
        # `sys.lazy_modules` is the set of fully-qualified names currently
        # bound to an unresolved PEP 810 lazy proxy. Deliberately OUR set,
        # not the host interpreter's, since the interpreted program's lazy
        # imports are resolved by this interpreter.
        self.lazy_modules = _LAZY_IMPORT_STATE.lazy_modules

    # PEP 810 lazy-import controls. These must be the interpreter's own
    # state: the host `sys.set_lazy_imports` would govern the host's bytecode
    # imports, not the imports this interpreter executes from source.
    def set_lazy_imports(self, mode):
        _LAZY_IMPORT_STATE.set_mode(mode)

    def get_lazy_imports(self):
        return _LAZY_IMPORT_STATE.mode

    def set_lazy_imports_filter(self, func):
        if func is not None and not callable(func):
            raise ValueError("filter provided but is not callable")
        _LAZY_IMPORT_STATE.filter = func

    def get_lazy_imports_filter(self):
        return _LAZY_IMPORT_STATE.filter

    def getdefaultencoding(self):
        return 'utf-8'

    def getfilesystemencoding(self):
        return 'utf-8'

    def getfilesystemencodeerrors(self):
        # POSIX default; matches CPython on the platforms this compiler
        # targets (PEP 686 keeps surrogateescape for filesystem paths on
        # Unix even with UTF-8 as the default encoding).
        return 'surrogateescape'

    def __getattr__(self, name):
        return getattr(sys, name)


class _TypesProxy:
    """`import types` inside an interpreted program.

    Forwards everything to the host `types` module except
    `types.LazyImportType`, which is this interpreter's proxy class: lazy
    imports of `.mojo` sibling modules resolve through this interpreter, so
    the host's native lazy-import type would describe the wrong objects.
    """
    def __getattr__(self, name):
        if name == 'LazyImportType':
            return LazyImportType
        return getattr(types, name)


_TYPES_PROXY = _TypesProxy()


def _sentinel_builtin():
    """The `sentinel` builtin (Python 3.14+/3.15, PEP 661).

    Returns the host's `builtins.sentinel` when available; otherwise a
    compatible implementation: `sentinel(name, /, *, repr=None)` returns a
    unique instance whose repr is `name` (or the custom `repr`), and
    `isinstance(instance, sentinel)` is true.
    """
    host = getattr(builtins, 'sentinel', None)
    if host is not None:
        return host

    class sentinel:
        __slots__ = ('_name', '_repr')

        def __new__(cls, name, /, *, repr=None):
            self = object.__new__(cls)
            self._name = name
            self._repr = name if repr is None else repr
            return self

        def __repr__(self):
            return self._repr

        def __reduce__(self):
            args = (self._name,)
            if self._repr == self._name:
                return (sentinel, args)
            return (sentinel, args, {'repr': self._repr})

    sentinel.__name__ = 'sentinel'
    sentinel.__qualname__ = 'sentinel'
    sentinel.__module__ = 'builtins'
    sentinel.__doc__ = (
        "Create a unique sentinel object.\n\n"
        "*name* should be the name of the variable to which the return value shall be assigned.\n\n"
        "*repr*, if supplied, will be used for the repr of the sentinel object. "
        "If not provided, \"<name>\" will be used."
    )
    return sentinel


def _frozendict_builtin():
    """The `frozendict` builtin (Python 3.15+, PEP 814).

    Returns the host's `builtins.frozendict` when available; otherwise a
    compatible immutable mapping implementation.
    """
    host = getattr(builtins, 'frozendict', None)
    if host is not None:
        return host

    class frozendict:
        __slots__ = ('_data', '_hash')

        def __new__(cls, *args, **kwargs):
            self = object.__new__(cls)
            self._data = dict(*args, **kwargs)
            self._hash = None
            return self

        @classmethod
        def fromkeys(cls, iterable, value=None):
            return cls(dict.fromkeys(iterable, value))

        def __repr__(self):
            return f"frozendict({self._data!r})"

        def __len__(self):
            return len(self._data)

        def __contains__(self, item):
            return item in self._data

        def __getitem__(self, key):
            return self._data[key]

        def __iter__(self):
            return iter(self._data)

        def __reversed__(self):
            return reversed(self._data)

        def __setitem__(self, key, value):
            raise TypeError("'frozendict' object does not support item assignment")

        def __delitem__(self, key):
            raise TypeError("'frozendict' object does not support item deletion")

        def keys(self):
            return self._data.keys()

        def values(self):
            return self._data.values()

        def items(self):
            return self._data.items()

        def get(self, key, default=None):
            return self._data.get(key, default)

        def copy(self):
            return self

        def __or__(self, other):
            if isinstance(other, (dict, frozendict)):
                data = dict(self._data)
                if isinstance(other, frozendict):
                    data.update(other._data)
                else:
                    data.update(other)
                return frozendict(data)
            return NotImplemented

        def __ror__(self, other):
            if isinstance(other, (dict, frozendict)):
                if isinstance(other, frozendict):
                    data = dict(other._data)
                else:
                    data = dict(other)
                data.update(self._data)
                return frozendict(data)
            return NotImplemented

        def __hash__(self):
            if self._hash is None:
                try:
                    h = hash(frozenset(self._data.items()))
                except TypeError:
                    raise TypeError("unhashable type: 'frozendict'")
                self._hash = h
            return self._hash

        def __eq__(self, other):
            if isinstance(other, frozendict):
                return self._data == other._data
            if isinstance(other, dict):
                return self._data == other
            return NotImplemented

    frozendict.__name__ = 'frozendict'
    frozendict.__qualname__ = 'frozendict'
    frozendict.__module__ = 'builtins'
    return frozendict


class Interpreter:
    """Executes Mojo AST nodes."""

    def __init__(self, filename: str = None, argv: list = None):
        # Increase recursion limit for meta-programming (interpreter on itself)
        import sys
        old_limit = sys.getrecursionlimit()
        if old_limit < 50000:
            sys.setrecursionlimit(50000)

        self.scope = Scope()
        self.filename = filename
        self.argv = argv if argv is not None else [filename or '<input>']
        self._mojo_module_cache = {}
        self._func_specs = {}
        self._raised_mojo_value = None
        # The one `_SysProxy` this interpreter binds `sys` to (see
        # _setup_builtins). Kept here because imports must resolve the
        # canonical sys module even when `lazy import sys` has temporarily
        # rebound the name `sys` to a lazy proxy — looking it up through the
        # scope there would re-enter the proxy's own resolve() forever.
        self._sys_proxy = None
        # PEP 810: mode 'all' leaves imports inside try/except blocks eager.
        # Explicit `lazy` there is a parse error, so only mode 'all' consults
        # this. execute_TryStmt keeps it incremented for every part of the
        # statement (body, handlers, else, finally), matching CPython's
        # symtable `ste_in_try_block`.
        self._try_depth = 0
        # Milestone 2 of INTERP_generator_yield_entirely_unimplemented:
        # per-OS-thread storage for "the yield_fn of the generator whose body
        # is currently running on THIS thread" — see MojoGeneratorObject
        # (each generator body runs on its own dedicated worker thread, so
        # this is naturally scoped correctly with no explicit save/restore
        # needed around individual yield/resume points, unlike
        # `interpreter.scope` itself).
        self._gen_tls = threading.local()
        self._setup_builtins()

    def _load_mojo_module_from_path(self, file_path):
        """Load and execute a .mojo file by its absolute path, return its namespace."""
        cache = self._mojo_module_cache
        if file_path in cache:
            return cache[file_path]
        mod_interp = Interpreter(filename=file_path, argv=self.argv)
        mod_interp._mojo_module_cache = cache
        module_ns = types.SimpleNamespace()
        cache[file_path] = module_ns
        try:
            with open(file_path) as f:
                src = f.read()
            from fire_compiler import py_tokenize, Parser
            tokens = py_tokenize(src)
            stmts = Parser(tokens).parse_module()
            for stmt in stmts:
                mod_interp.execute(stmt)
            module_ns.__dict__.update(mod_interp.scope.vars)
            return module_ns
        except Exception:
            return module_ns

    def _load_mojo_sibling_module(self, module_name):
        """Resolve `import`/`from import` of a sibling .mojo source file (as
        opposed to a real importable Python module) by parsing and running it
        in its own scope, then exposing its top-level bindings for attribute
        access — the interpreter has no separate module-object representation,
        so a lightweight namespace stands in for one."""
        cache = self._mojo_module_cache

        if module_name in ('testing', 'std.testing', 'std.testing.testing'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(**_build_testing_shims(self))
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.math', 'std.math.math'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(**_build_math_shims())
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.sys.defines',):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                is_defined=_MojoIsDefinedFn(),
                get_defined_string=_MojoGetDefinedFn(),
                get_defined_bool=_MojoGetDefinedFn(),
                get_defined_int=_MojoGetDefinedFn(),
                MOJO_VERSION="0.0.0-interpreter",
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.sys', 'std.sys.arg', 'std.sys.info'):
            if module_name in cache:
                return cache[module_name]
            argv = self.argv
            namespace = types.SimpleNamespace(
                argv=lambda: argv,
                size_of=self.scope.get('size_of'),
                align_of=self.scope.get('align_of'),
                bit_width_of=self.scope.get('bit_width_of'),
                simd_width_of=self.scope.get('simd_width_of'),
                CompilationTarget=self.scope.get('CompilationTarget'),
                is_64bit=lambda: True,
                DType=self.scope.get('DType'),
                exit=sys.exit,
                get_defined_bool=_MojoGetDefinedFn(),
                get_defined_int=_MojoGetDefinedFn(),
                # This interpreter has no accelerator/GPU backend at all.
                is_gpu=lambda: False,
                is_apple_gpu=lambda: False,
                is_amd_gpu=lambda: False,
                is_nvidia_gpu=lambda: False,
                has_apple_gpu_accelerator=lambda: False,
                has_amd_gpu_accelerator=lambda: False,
                has_nvidia_gpu_accelerator=lambda: False,
                _accelerator_arch=lambda: "cpu",
                num_physical_cores=lambda: os.cpu_count() or 1,
                num_logical_cores=lambda: os.cpu_count() or 1,
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.gpu', 'std.gpu.host', 'std.gpu.host.info', 'std.gpu.id'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                DeviceContext=self.scope.get('DeviceContext'),
                DeviceBuffer=self.scope.get('DeviceBuffer'),
                HostBuffer=self.scope.get('DeviceBuffer'),
                GPUInfo=self.scope.get('GPUInfo'),
                AddressSpace=self.scope.get('AddressSpace'),
                thread_idx=self.scope.get('thread_idx'),
                block_idx=self.scope.get('block_idx'),
                block_dim=self.scope.get('block_dim'),
                grid_dim=self.scope.get('grid_dim'),
                global_idx=self.scope.get('global_idx'),
                lane_id=self.scope.get('lane_id'),
                get_gpu_target=self.scope.get('get_gpu_target'),
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.os', 'std.os.os'):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                abort=self.scope.get('abort'),
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.runtime.tracing',):
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(
                Trace=_MojoTrace,
                TraceLevel=self.scope.get('TraceLevel'),
            )
            cache[module_name] = namespace
            return namespace

        if module_name in ('std.collections', 'std.collections.list'):
            # BUG-2026-028: was falling through to the generic std.* auto-stub
            # namespace below (real list.mojo's generics/low-level memory
            # primitives are beyond this parser), so `List[Int]()` silently
            # returned a fake auto-stub value instead of a real list - see
            # _MojoListType's docstring for the full failure chain.
            if module_name in cache:
                return cache[module_name]
            namespace = types.SimpleNamespace(List=self.scope.get('List'))
            cache[module_name] = namespace
            return namespace

        if module_name == 'std' or module_name.startswith('std.'):
            # Real `std.*` submodules beyond the hardcoded shims above are
            # full of generics/MLIR our simple parser can't handle — walking
            # up from the importing file's directory (needed below for
            # test-only sibling packages like `test_utils`) would eventually
            # reach the real stdlib root and start attempting to parse them,
            # trading a graceful missing-import no-op for a hard crash deep
            # in real stdlib internals. Return an auto-stubbing namespace so
            # attribute access on an unshimmed module (e.g. `std.benchmark`)
            # returns a 0-valued proxy instead of crashing.
            return _AutoStubNamespace()

        rel_path = module_name.replace('.', os.sep) + '.mojo'
        rel_pkg_path = os.path.join(module_name.replace('.', os.sep), '__init__.mojo')
        search_dirs = []
        if self.filename:
            # Walk upward too, not just the importing file's own directory —
            # e.g. stdlib/test/memory/test_alloc.mojo imports the sibling
            # package stdlib/test/test_utils/, which lives a level up from
            # test_alloc.mojo's own directory, not next to it.
            d = os.path.dirname(os.path.abspath(self.filename))
            for _ in range(6):
                search_dirs.append(d)
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
        search_dirs.append(os.getcwd())
        # Honor `sys.path.insert(...)` done by the interpreted program itself
        # — `import sys` binds the real `sys` module (via _SysProxy), so a
        # script that does `sys.path.insert(0, "/some/dir")` to point at a
        # sibling .mojo package outside the walk-up range above (a common
        # pattern for test/tool scripts that live away from the package
        # they're exercising) genuinely mutates the real sys.path list, but
        # until now nothing here ever consulted it.
        for d in sys.path:
            if d and os.path.isdir(d):
                search_dirs.append(d)
        found = None
        for d in search_dirs:
            flat_candidate = os.path.join(d, rel_path)
            pkg_candidate = os.path.join(d, rel_pkg_path)
            if os.path.isfile(flat_candidate):
                found = flat_candidate
                break
            if os.path.isfile(pkg_candidate):
                found = pkg_candidate
                break
        if found is None:
            return None

        # Cache (and cycle-guard) by resolved absolute path, not `module_name`
        # — a package's __init__.mojo commonly imports a same-named submodule
        # from itself (e.g. test_utils/__init__.mojo importing from
        # test_utils/test_utils.mojo, both reached via the string
        # "test_utils"), and those are different files that must not collide
        # on one cache key. Guard against circular sibling-module imports the
        # same way: without marking the slot before recursing, each nested
        # import would spin up a brand-new Interpreter with its own fresh,
        # unshared cache and recurse forever instead of hitting a cache entry.
        if found in cache:
            return cache[found]

        with open(found) as f:
            src = f.read()
        from fire_compiler import py_tokenize, Parser
        tokens = py_tokenize(src)
        mod_stmts = Parser(tokens).parse_module()
        mod_interp = Interpreter(filename=found, argv=self.argv)
        mod_interp._mojo_module_cache = cache  # shared, so cycles hit the guard above
        # The CYCLE GUARD is installed before the body runs and it is the SAME
        # object the import returns, not a placeholder that is replaced at the
        # end. That is the fix as much as the copy was: a package that imports
        # itself must terminate (which is why the slot is marked here at all),
        # and a placeholder would make a cyclic importer see an empty module
        # while every other importer saw the live one. Installing the view here
        # means a cyclic importer sees the same half-built module, which is what
        # CPython's partially-initialised module object does.
        namespace = _MojoModuleObject(mod_interp.scope.vars, module_name)
        cache[found] = namespace
        for stmt in mod_stmts:
            mod_interp.execute(stmt)
        return namespace

    def _bind_dotted_import(self, module_name, mod, scope=None):
        """`import std.sys` (no `as` alias) must bind the top-level name
        `std` and make `std.sys` resolve via chained attribute access — same
        as Python's own dotted-import binding rule. A flat bind of `std`
        straight to the `std.sys` shim namespace (the previous behavior)
        broke `std.sys.whatever`, since there was no intermediate `.sys`.
        `scope` is supplied by a lazy import, whose statement's scope may
        differ from the frame current at reification time."""
        target_scope = scope if scope is not None else self.scope
        parts = module_name.split('.')
        top = parts[0]
        if len(parts) == 1:
            target_scope.define(top, mod)
            return
        try:
            root = self._bind_dotted_import_lazy_safe_root(top, target_scope)
        except NameError:
            root = None
        if isinstance(root, LazyImportType):
            # This dotted import's own lazy proxy is being reified right now
            # (its resolver called us). Do not look it up through Scope.get —
            # that would re-enter resolve() forever. It is about to be
            # replaced by the namespace chain below.
            root = None
        if not isinstance(root, types.SimpleNamespace):
            root = types.SimpleNamespace()
            target_scope.define(top, root)
        obj = root
        for p in parts[1:-1]:
            nxt = getattr(obj, p, None)
            if not isinstance(nxt, types.SimpleNamespace):
                nxt = types.SimpleNamespace()
                setattr(obj, p, nxt)
            obj = nxt
        setattr(obj, parts[-1], mod)

    def _is_instance(self, obj, class_name):
        """Check if obj is an instance of class_name from fire_compiler."""
        cls = getattr(N, class_name, None)
        return cls is not None and isinstance(obj, cls)

    def _setup_builtins(self):
        """Setup built-in functions and constants."""
        self.scope.define('None', None)
        self.scope.define('True', True)
        self.scope.define('False', False)
        self.scope.define('__name__', '__main__')
        self.scope.define('__file__', self.filename or '<input>')
        # Real Python sets this to '' for a script run directly (not
        # imported as part of a package) — asyncio/log.py's module-scope
        # `logging.getLogger(__package__)` raised "name '__package__' is
        # not defined" since fire.py always runs files this way.
        self.scope.define('__package__', '')

        # Built-in functions
        self.scope.define('len', len)
        self.scope.define('print', print)
        self.scope.define('range', range)
        self.scope.define('str', str)
        self.scope.define('int', int)
        self.scope.define('float', float)
        self.scope.define('bool', bool)
        self.scope.define('list', list)
        self.scope.define('dict', dict)
        self.scope.define('set', set)
        self.scope.define('tuple', tuple)
        self.scope.define('open', open)
        self.scope.define('input', input)
        self.scope.define('isinstance', isinstance)
        self.scope.define('hasattr', hasattr)
        self.scope.define('getattr', getattr)
        self.scope.define('setattr', setattr)
        self.scope.define('type', type)
        self.scope.define('enumerate', enumerate)
        self.scope.define('zip', zip)
        self.scope.define('max', _mojo_max)
        self.scope.define('min', _mojo_min)
        self.scope.define('SIMD', _MojoSIMDType())
        class _MojoFloatLiteralType:
            infinity = float('inf')
            negative_infinity = float('-inf')
            negative_zero = float('-0.0')
            nan = float('nan')
        self.scope.define('FloatLiteral', _MojoFloatLiteralType)
        self.scope.define('sum', sum)
        self.scope.define('sorted', sorted)
        self.scope.define('reversed', _mojo_reversed)
        self.scope.define('map', _MojoParametricFn(map, self))
        self.scope.define('filter', _MojoParametricFn(filter, self))
        self.scope.define('repr', repr)
        self.scope.define('all', all)
        self.scope.define('any', any)
        self.scope.define('abs', abs)
        self.scope.define('round', round)
        self.scope.define('hash', hash)
        self.scope.define('id', id)
        self.scope.define('chr', chr)
        self.scope.define('ord', ord)
        self.scope.define('divmod', divmod)
        self.scope.define('next', _mojo_next)
        self.scope.define('index', _mojo_operator_index)
        self.scope.define('isnan', _mojo_isnan)
        self.scope.define('isinf', _mojo_isinf)
        self.scope.define('isfinite', _mojo_isfinite)
        # Mojo's StaticString/StringSlice are borrowed-string-view types;
        # plain Python str already behaves like their value side.
        self.scope.define('StaticString', MojoString)
        self.scope.define('StringSlice', MojoString)
        self.scope.define('InlineArray', _MojoGenericCtor(list))
        def _mojo_deque_ctor(*args, **kwargs):
            # Mojo's Deque(capacity=N) is a pre-allocation size *hint*, not a
            # maxlen cap like collections.deque's own `maxlen=` — drop it.
            iterable = args[0] if args else ()
            return collections.deque(iterable)
        self.scope.define('Deque', _MojoGenericCtor(_mojo_deque_ctor))
        self.scope.define('BinaryHeap', _MojoGenericCtor(list))

        def _debug_assert(cond, *args):
            if not cond:
                raise AssertionError("debug_assert failed" + (": " + str(args[0]) if args else ""))
        self.scope.define('debug_assert', _debug_assert)
        self.scope.define('Exception', Exception)
        self.scope.define('BaseException', BaseException)
        self.scope.define('KeyboardInterrupt', KeyboardInterrupt)
        self.scope.define('EOFError', EOFError)
        self.scope.define('ValueError', ValueError)
        self.scope.define('TypeError', TypeError)
        self.scope.define('RuntimeError', RuntimeError)
        self.scope.define('StopIteration', StopIteration)
        self.scope.define('Error', MojoError)
        # …and the rest of the standard exception hierarchy, which the block
        # above was missing in a way that turned a diagnostic into a DIFFERENT
        # one. `fire_compiler.py` — this compiler's own source, which the
        # interpreter executes whenever it interprets a program — raises
        # `SyntaxError` from five sites (`replace_multiline_strings`'s
        # "unterminated string literal", the `yield`/`await`-outside-a-
        # generator refusal, the for/with target refusal, and two in the
        # parser), and `SyntaxError` was not in scope. So the interpreter
        # reached `raise SyntaxError(...)` and raised
        # `NameError: name 'SyntaxError' is not defined` instead: the
        # interpreter's copy of the tokenizer could not REPORT a lex error,
        # which is the one thing a tokenizer has to be able to do.
        #
        # Found by `test_myinterpreter_validation.py`, which runs
        # `fire_compiler.py`'s `py_tokenize` through the interpreter and
        # compares it with the imported one — that file's reason for existing
        # is that an interpreter bug produces a wrong answer rather than an
        # exception, and this one did: 66 of 67 corpus texts matched and the
        # 67th raised the wrong exception TYPE.
        #
        # Names, not aliases of anything Mojo-specific: the interpreter
        # defines the PYTHON exception class, so `except SyntaxError` in a
        # program the interpreter runs catches what the raise produced. The
        # same is already true of the six above, and these are simply the
        # rest of `builtins` that a real program or the compiler's own source
        # can name.
        for _exc_name in ('SyntaxError', 'IndentationError', 'TabError',
                          'IndexError', 'KeyError', 'AttributeError',
                          'NameError', 'UnboundLocalError', 'ArithmeticError',
                          'ZeroDivisionError', 'OverflowError',
                          'FloatingPointError', 'AssertionError',
                          'NotImplementedError', 'RecursionError',
                          'SystemError', 'StopAsyncIteration',
                          'ImportError', 'ModuleNotFoundError',
                          'LookupError', 'MemoryError', 'OSError',
                          'IOError', 'FileNotFoundError', 'SystemExit'):
            self.scope.define(_exc_name, getattr(builtins, _exc_name))
        # More standard builtins + exceptions that real stdlib files reference
        # at module scope (found via fault_tolerance.py comparing `fire run`
        # to CPython — e.g. keyword.py's frozenset, _pyrepl/types.py's object,
        # dbm/__init__.py's OSError all raised "name X is not defined").
        # Plain Python builtins, same pattern as set/zip/Exception above.
        # (bytes/bytearray deliberately omitted — the self-hosting codegen
        # doesn't recognize them as callable; see the String ctor note below.)
        self.scope.define('frozenset', frozenset)
        self.scope.define('frozendict', _frozendict_builtin())
        self.scope.define('object', object)
        self.scope.define('complex', complex)
        self.scope.define('slice', slice)
        self.scope.define('sentinel', _sentinel_builtin())
        self.scope.define('callable', callable)
        self.scope.define('iter', _mojo_iter)
        self.scope.define('format', format)
        self.scope.define('hex', hex)
        self.scope.define('oct', oct)
        self.scope.define('bin', bin)
        self.scope.define('pow', pow)
        self.scope.define('OSError', OSError)
        self.scope.define('IOError', IOError)
        self.scope.define('IndexError', IndexError)
        self.scope.define('KeyError', KeyError)
        self.scope.define('AttributeError', AttributeError)
        self.scope.define('NotImplementedError', NotImplementedError)
        self.scope.define('OverflowError', OverflowError)
        self.scope.define('ZeroDivisionError', ZeroDivisionError)
        self.scope.define('ArithmeticError', ArithmeticError)
        self.scope.define('LookupError', LookupError)
        self.scope.define('AssertionError', AssertionError)
        self.scope.define('NameError', NameError)
        self.scope.define('ImportError', ImportError)
        self.scope.define('ModuleNotFoundError', ModuleNotFoundError)
        self.scope.define('FileNotFoundError', FileNotFoundError)
        self.scope.define('FileExistsError', FileExistsError)
        self.scope.define('PermissionError', PermissionError)
        self.scope.define('NotADirectoryError', NotADirectoryError)
        self.scope.define('IsADirectoryError', IsADirectoryError)
        self.scope.define('UnicodeError', UnicodeError)
        self.scope.define('UnicodeDecodeError', UnicodeDecodeError)
        self.scope.define('UnicodeEncodeError', UnicodeEncodeError)
        self.scope.define('RecursionError', RecursionError)
        self.scope.define('MemoryError', MemoryError)
        self.scope.define('SystemError', SystemError)
        self.scope.define('SystemExit', SystemExit)
        self.scope.define('GeneratorExit', GeneratorExit)
        self.scope.define('StopAsyncIteration', StopAsyncIteration)
        self.scope.define('ConnectionError', ConnectionError)
        self.scope.define('TimeoutError', TimeoutError)
        self.scope.define('Warning', Warning)
        self.scope.define('DeprecationWarning', DeprecationWarning)
        self.scope.define('UserWarning', UserWarning)
        self.scope.define('RuntimeWarning', RuntimeWarning)
        self.scope.define('NotImplemented', NotImplemented)

        # Mojo scalar-type constructors — plain Python bool/int/float/str
        # already behave like Mojo's Bool/Int/Float64/String for arithmetic
        # and dunder methods; these wrappers only add the `.MIN`/`.MAX` class
        # attributes stdlib test files read directly off the type name.
        self.scope.define('Bool', _MojoBoolType())
        self.scope.define('Int', _MojoIntType())
        self.scope.define('UInt', _MojoUIntType())
        def _mojo_string_ctor(*args, **kwargs):
            if 'unsafe_from_utf8' in kwargs:
                # Avoid the `bytes()`/`bytearray()` builtins here — this
                # project's self-hosting compiler (gimple_codegen.py, which
                # must also compile myinterpreter.py itself) doesn't
                # recognize them as callable. This is an approximation (one
                # Python char per input byte, not a real UTF-8 multi-byte
                # decode) — good enough for ASCII-range byte lists, wrong for
                # genuine multi-byte UTF-8 sequences.
                data = kwargs['unsafe_from_utf8']
                return MojoString(''.join(chr(b) for b in data))
            if len(args) > 1:
                # Real Mojo's `String(a, b, c, ...)` concatenates the
                # stringified arguments (print-style), unlike Python's own
                # `str(object, encoding, errors)` 2-3 positional-arg
                # constructor, which would otherwise swallow the 2nd
                # argument as an `encoding` name.
                return MojoString(''.join(str(a) for a in args))
            return MojoString(*args)
        self.scope.define('String', _mojo_string_ctor)
        self.scope.define('List', _MojoGenericCtor(list))
        self.scope.define('Dict', _MojoGenericCtor(dict))
        self.scope.define('Set', _MojoGenericCtor(set))
        self.scope.define('Tuple', _MojoGenericCtor(tuple))

        int8, int16, int32, int64 = (
            _MojoScalarType('Int8', 1), _MojoScalarType('Int16', 2),
            _MojoScalarType('Int32', 4), _MojoScalarType('Int64', 8),
        )
        uint8, uint16, uint32, uint64 = (
            _MojoScalarType('UInt8', 1), _MojoScalarType('UInt16', 2),
            _MojoScalarType('UInt32', 4), _MojoScalarType('UInt64', 8),
        )
        float16 = _MojoScalarType('Float16', 2, is_float=True)
        float32 = _MojoScalarType('Float32', 4, is_float=True)
        float64 = _MojoScalarType('Float64', 8, is_float=True)
        bfloat16 = _MojoScalarType('BFloat16', 2, is_float=True)
        self.scope.define('Int8', int8)
        self.scope.define('Int16', int16)
        self.scope.define('Int32', int32)
        self.scope.define('Int64', int64)
        self.scope.define('UInt8', uint8)
        self.scope.define('UInt16', uint16)
        self.scope.define('UInt32', uint32)
        self.scope.define('UInt64', uint64)
        self.scope.define('Float16', float16)
        self.scope.define('Float32', float32)
        self.scope.define('Float64', float64)
        self.scope.define('BFloat16', bfloat16)
        self.scope.define('DType', types.SimpleNamespace(
            int8=int8, int16=int16, int32=int32, int64=int64, index=int64, int=int64,
            uint8=uint8, uint16=uint16, uint32=uint32, uint64=uint64,
            float16=float16, float32=float32, float64=float64, bfloat16=bfloat16,
            bool=_MojoScalarType('Bool', 1),
        ))
        self.scope.define('size_of', _MojoTypeInfoFn(_mojo_size_of))
        self.scope.define('align_of', _MojoTypeInfoFn(_mojo_size_of))
        self.scope.define('bit_width_of', _MojoTypeInfoFn(_mojo_bit_width_of))
        self.scope.define('simd_width_of', _MojoTypeInfoFn(_mojo_simd_width_of))
        self.scope.define('CompilationTarget', _MojoCompilationTarget())
        unsafe_pointer_type = _MojoUnsafePointerType()
        self.scope.define('UnsafePointer', unsafe_pointer_type)
        self.scope.define('MutUnsafePointer', unsafe_pointer_type)
        self.scope.define('ImmutUnsafePointer', unsafe_pointer_type)
        self.scope.define('DeviceBuffer', unsafe_pointer_type)
        self.scope.define('List', _MojoListType())

        # GPU/DeviceContext basics — no real GPU backend, kernels launched
        # via enqueue_function just run serially on the CPU (see
        # _MojoEnqueueFunctionCall). Good enough for exercising kernel logic
        # and the launch/buffer/thread-index syntax and semantics; not a
        # step towards real device dispatch.
        def _device_context_ctor(device_id=0, api=None):
            return _MojoDeviceContext(device_id, api, self)
        self.scope.define('DeviceContext', _device_context_ctor)
        self.scope.define('thread_idx', _MojoDim3())
        self.scope.define('block_idx', _MojoDim3())
        self.scope.define('block_dim', _MojoDim3(1, 1, 1))
        self.scope.define('grid_dim', _MojoDim3(1, 1, 1))
        self.scope.define('global_idx', _MojoDim3())
        self.scope.define('GPUInfo', _MojoGPUInfoType())
        self.scope.define('AddressSpace', _MojoAddressSpaceNS())
        def _mojo_get_gpu_target(*args, **kwargs):
            return "cpu"
        self.scope.define('get_gpu_target', _mojo_get_gpu_target)

        def _mojo_lane_id():
            return 0
        self.scope.define('lane_id', _mojo_lane_id)
        self.scope.define('MutUntrackedOrigin', None)

        def _origin_of(x, *args, **kwargs):
            return x
        self.scope.define('origin_of', _origin_of)

        def _mojo_abort(*args):
            msg = str(args[0]) if args else "abort() called"
            raise RuntimeError(msg)
        self.scope.define('abort', _mojo_abort)
        self.scope.define('TraceLevel', types.SimpleNamespace(
            DISABLED=0, DEFAULT=1, VERBOSE=2, RUNTIME=3,
        ))

        # `__functions_in_module()` backs the `TestSuite.discover_tests[...]`
        # boilerplate at the end of most stdlib test files — see
        # _build_testing_shims. Captures this interpreter's own top-level
        # scope (module scope), since that's what real Mojo's builtin reflects.
        module_scope = self.scope
        def _functions_in_module():
            return [(n, v) for n, v in module_scope.vars.items() if isinstance(v, MojoFunction)]
        self.scope.define('__functions_in_module', _functions_in_module)

        # Standard library modules
        import os
        import sys
        import subprocess
        import shutil
        import sysconfig
        import platform
        import tempfile
        import traceback
        self.scope.define('os', os)
        self._sys_proxy = _SysProxy(self.argv)
        self.scope.define('sys', self._sys_proxy)
        self.scope.define('subprocess', subprocess)
        self.scope.define('shutil', shutil)
        self.scope.define('sysconfig', sysconfig)
        self.scope.define('platform', platform)
        self.scope.define('tempfile', tempfile)
        self.scope.define('traceback', traceback)

        # Interpreter itself for bootstrapping
        self.scope.define('Interpreter', Interpreter)

        # Parser and compiler functions
        try:
            from fire_compiler import py_tokenize, Parser as MojoParser
            self.scope.define('py_tokenize', py_tokenize)
            self.scope.define('Parser', MojoParser)
        except ImportError:
            pass

        # GIMPLE codegen
        try:
            from gimple_codegen import compile_to_gimple
            self.scope.define('compile_to_gimple', compile_to_gimple)
        except ImportError:
            pass

    def _loc(self, node: object = None) -> str:
        """Format a gcc-style `file:line:col: ` prefix for a runtime diagnostic.
        Omits the filename segment when the interpreter wasn't given one
        (e.g. the REPL), matching fire_compiler.Parser's `_loc`."""
        line = getattr(node, 'line', 0) if node is not None else 0
        col = getattr(node, 'col', 0) if node is not None else 0
        if self.filename:
            return f"{self.filename}:{line}:{col}: "
        return f"{line}:{col}: "

    def execute(self, node: object) -> object:
        """Execute an AST node."""
        if node is None:
            return None

        method_name = f'execute_{type(node).__name__}'
        method = getattr(self, method_name, None)

        if method is None:
            raise NotImplementedError(f"{self._loc(node)}No handler for {type(node).__name__}")

        return method(node)

    def execute_Module(self, node):
        """Execute module (top-level statements)."""
        result = None
        for stmt in node.body:
            result = self.execute(stmt)
        return result

    @staticmethod
    def _extract_param_names(node):
        """Extract parameter names from a FunctionDef's various param formats.
        Mojo's `*name`/`**name` prefixes (keyword-only marker / kwargs
        catch-all — see fire_compiler.py's param parsing) are stripped since
        MojoFunction binds everything positional-or-keyword by plain name."""
        params = []
        if hasattr(node, 'params') and node.params:
            for p in node.params:
                if isinstance(p, str):
                    params.append(p)
                elif isinstance(p, tuple):
                    # Handle (name, type_annotation) tuples
                    params.append(p[0])
                elif hasattr(p, 'name'):
                    params.append(p.name)
                elif isinstance(p, dict) and 'name' in p:
                    params.append(p['name'])
                else:
                    # Fallback: try to extract name from string representation
                    p_str = str(p)
                    if '(' in p_str:
                        # Parse string like "('n', None)" to get 'n'
                        try:
                            import ast
                            parsed = ast.literal_eval(p_str)
                            if isinstance(parsed, tuple):
                                params.append(parsed[0])
                            else:
                                params.append(parsed)
                        except:
                            params.append(p_str)
                    else:
                        params.append(p_str)
        # Stars are DELIBERATELY preserved: `*args` / `**kwargs` are bound
        # by _invoke, which is the only reader of MojoFunction.params, and
        # it needs the marker to tell a catch-all from an ordinary
        # parameter. Stripping here used to leave `_invoke` binding the
        # literal name (`kwargs` -> None, `args` -> just the first extra
        # positional), so `def __init__(self, t, **fields): self.fields =
        # fields` stored None -- the root cause of ast_rewriter.py's
        # `for fname in pat.fields:` finding nothing (A5-BUG.md section 1).
        return params

    @staticmethod
    def _classify_params(node):
        """Classify a FunctionDef's parameters for overload-signature
        matching: (required positional names, optional/defaulted positional
        names, keyword-only names, has-**kwargs-catch-all).

        Keyword-only names come from two places in fire_compiler.py's parsed
        params: a `*name` prefix (the `*args`-style variadic form), or plain
        (unprefixed) names listed in `node.kwonly` — the far more common
        `def f(x, *, y):` bare-`*,`-separator form leaves `y` looking
        identical to a normal positional param in `node.params`, since the
        parser only records "a bare `*` was seen" via that separate list,
        not as a per-param marker."""
        required, optional, kwonly = [], [], []
        has_var_kwargs = False
        has_default = getattr(node, 'param_has_default', None) or {}
        explicit_kwonly = set(getattr(node, 'kwonly', None) or [])
        for p in (getattr(node, 'params', None) or []):
            if isinstance(p, tuple):
                raw_name = p[0]
            elif hasattr(p, 'name'):
                raw_name = p.name
            elif isinstance(p, dict) and 'name' in p:
                raw_name = p['name']
            else:
                raw_name = str(p)
            if raw_name.startswith('**'):
                has_var_kwargs = True
                continue
            is_kwonly = raw_name.startswith('*')
            name = raw_name.lstrip('*')
            if is_kwonly or name in explicit_kwonly:
                kwonly.append(name)
            elif has_default.get(name):
                optional.append(name)
            else:
                required.append(name)
        return required, optional, kwonly, has_var_kwargs

    def _register_function(self, container, name, func, spec):
        """Bind `func` under `name` in `container` (a plain dict: Scope.vars
        or a struct's methods dict), merging into a MojoOverloadSet if `name`
        already names a function in this same container — repeat `def name`
        in Mojo is an overload set, not a redefinition."""
        self._func_specs[id(func)] = spec
        existing = container.get(name)
        if isinstance(existing, MojoOverloadSet):
            existing.add(func, *spec)
            return existing
        if isinstance(existing, MojoFunction):
            prev_spec = self._func_specs.get(id(existing), ([], [], [], False))
            overload_set = MojoOverloadSet(name, interpreter=self)
            overload_set.add(existing, *prev_spec)
            overload_set.add(func, *spec)
            container[name] = overload_set
            return overload_set
        container[name] = func
        return func

    def execute_FunctionDef(self, node):
        """Execute function definition."""
        params = self._extract_param_names(node)
        comptime_params = getattr(node, 'comptime_params', None)
        _pd = getattr(node, 'param_defaults', None)
        _pdv = list(_pd.items()) if _pd else None
        _cpd = getattr(node, 'comptime_param_defaults', None)
        func = MojoFunction(node.name, params, node.body, self.scope, comptime_params, param_defaults=_pdv,
                             is_generator=getattr(node, 'is_generator', False),
                             is_async=getattr(node, 'is_async', False), interpreter=self,
                             comptime_param_defaults=_cpd)
        spec = self._classify_params(node)
        bound = self._register_function(self.scope.vars, node.name, func, spec)
        # The rebinding a decorator IS: the decorated value replaces the
        # function in the module scope under its own name. Written through
        # `vars` directly, not `Scope.set`, because `set` looks for an
        # ENCLOSING binding — that is the `nonlocal` rule and wrong here.
        self.scope.vars[node.name] = self._apply_function_decorators(node, bound)
        return self.scope.vars[node.name]

    # Decorators the COMPILER consumes structurally — they select a calling
    # convention, a binding rule, or a lowering mode, and there is no
    # user-level function to call. Applying any of them as a runtime
    # decorator would be a NameError or, worse, a call into something
    # unrelated. Every one of these is read by name elsewhere in the tree
    # (`staticmethod`/`classmethod` in execute_StructDef and
    # fire_compiler.method_receiver_kind, `property` in the generator
    # eligibility passes, `export` in module_gen, `parameter` in coro.py's
    # nested-async eligibility, the trait-conformance names in StructDef
    # handling), so this list is a name set, not a second mechanism.
    _COMPILE_TIME_DECORATORS = frozenset({
        'staticmethod', 'classmethod', 'property', 'export', 'parameter',
        'fieldwise_init', 'always_inline', 'inline', 'unroll', 'comptime',
        'Copyable', 'Movable', 'ImplicitlyCopyable', 'ExplicitlyCopyable',
        'Writable', 'Sized', 'Boolable', 'Stringable', 'Hashable',
        'AnyType', '__allow_legacy_any_origin_fields',
        '__allow_legacy_custom_self_type',
        'stable', 'value', 'doc_private', 'doc_hidden', 'register_passable',
        'trivial_register_passable', 'implicit',
    })

    def _apply_function_decorators(self, node, bound):
        """`@deco def f` is `f = deco(f)`, applied bottom-up, in the scope the
        `def` executed in. RETURNS the resulting value; the caller stores it
        wherever the function was registered (module scope for a free
        function, the class's `methods` dict for a method) — this used to
        write the module scope itself, which silently discarded a decorated
        METHOD's replacement while leaving a stray name at module level.

        This was MISSING, not merely wrong: `FunctionDef.decorators` was
        parsed and then never read by this interpreter, so a decorated
        function was registered raw and every later call reached the
        undecorated body. Because the interpreter is the documented oracle
        for "the compiled path is wrong", that made the whole class of
        decorator bugs invisible — the two engines agreed on the wrong
        answer. See bugs/hard/COMPILE_FAIL_decorator_application_dropped.md.

        Bottom-up because that is Python's order: `@a` above `@b` above
        `def f` means `f = a(b(f))`. A decorator whose application raises is
        NOT caught here: a failing decorator is a real error and must reach
        the user, exactly as it would in CPython.
        """
        decs = getattr(node, 'decorators', None) or []
        for d in reversed(decs):
            if isinstance(d, str):
                if d in self._COMPILE_TIME_DECORATORS:
                    continue
                # `@deco` -- the decorator is the name's value.
                decorator = self.eval_expr(N.IdentExpr(name=d))
            elif isinstance(d, N.CallExpr):
                # `@deco(x, k=1)` is `@deco(x, k=1)` applied to f, i.e. TWO
                # evaluations: the CallExpr produces the decorator (calling
                # `deco` with its own arguments, which is what returns the
                # real decorator in the factory idiom), and THAT is then
                # called with f. Collapsing them into one call is what made
                # `name` bind to the function instead of to "A" above.
                # The parser records this as a real CallExpr — it used to
                # discard the argument list, so a parameterised decorator and
                # a bare one were the same node and both did nothing.
                #
                # EXCEPT when the decorator's own name is compile-time, which
                # is what `@inline(.always)` is: `inline` is a marker, not a
                # callable, and evaluating the CallExpr would look it up and
                # NameError on a decorator that is documented as carrying no
                # runtime meaning. The bare-name branch above already skips
                # exactly these names; this is the same skip for the
                # parameterised spelling, so `@inline` and `@inline(.always)`
                # agree.
                fname = getattr(d.func, 'name', None)
                if fname in self._COMPILE_TIME_DECORATORS:
                    continue
                decorator = self.eval_expr(d)
            elif isinstance(d, N.DecoratorArgs):
                # `@spec(c1; c2; ...)` -- a `;`-separated SPECIFICATION
                # (`fire_compiler.DecoratorArgs`), not Mojo call syntax: its
                # clauses are kept as text precisely because they are not
                # expressions this interpreter could evaluate. So it is an
                # annotation, in the same family as `@require`/`@ensure` and
                # the other `_COMPILE_TIME_DECORATORS`: recorded for a
                # consumer that reads the spec (the formal/Lean pipeline),
                # and not applied. Skipping it is also the pre-19bc0dd
                # behaviour for these examples, where the argument list was
                # discarded and `@spec` was a bare name; raising here instead
                # would be a new failure mode for source that used to run.
                continue
            else:
                raise SyntaxError(
                    f"unsupported decorator on {node.name!r}: {d!r} (expected a "
                    f"name or a call)")
            try:
                # `self.invoke`, not `decorator(...)`: a Mojo-defined
                # decorator needs the interpreter threaded through as its
                # first argument, and this is the same entry point
                # eval_CallExpr uses, so generator/async callees and the
                # coroutine thread-bounce behave identically here. No
                # star-args: a parameterised decorator's own arguments were
                # already consumed by the `eval_expr(d)` above, so the
                # application itself is always exactly one argument -- which
                # is also the only shape the self-hosted compiler's inferred
                # arity for `Interpreter.invoke` can express.
                bound = self.invoke(decorator, bound)
            except TypeError as e:
                raise TypeError(
                    f"applying decorator to {node.name!r} failed: {e}") from e
        return bound

    def execute_StructDef(self, node):
        """Execute struct/class definition.

        `struct Child(Base1, Base2):` — Python-style class inheritance:
        fields and methods from each named base are merged in first, in
        declaration order (later bases override earlier ones, matching
        Python's own left-to-right MRO for non-diamond hierarchies), then
        Child's own fields/methods are layered on top, overriding same-named
        base methods exactly like a Python subclass overriding a method."""
        methods = {}
        base_names = getattr(node, 'bases', None) or []
        base_classes = []
        python_bases = []
        merged_fields = []
        comptime_aliases = {}
        static_methods = set()
        class_methods = set()
        from_base = set()
        class_keywords = getattr(node, 'keywords', None) or []
        kw_dict = {}
        for _k, _v in class_keywords:
            try:
                kw_dict[_k] = self.eval_expr(_v)
            except Exception:
                kw_dict[_k] = _v
        for base_name in base_names:
            try:
                base_cls = self.scope.get(base_name)
            except NameError:
                base_cls = None
            if isinstance(base_cls, MojoClass):
                base_classes.append(base_cls)
                merged_fields.extend(base_cls.fields)
                methods.update(base_cls.methods)
                comptime_aliases.update(base_cls.comptime_aliases)
                static_methods.update(base_cls.static_methods)
                class_methods.update(base_cls.class_methods)
                from_base.update(base_cls.methods.keys())
            elif base_cls is not None:
                # Real Python bases (types, typing special forms such as
                # typing.TypedDict which is a function in 3.15+, or anything
                # else).  Preserved so a class with Python keywords (PEP 692
                # closed= / PEP 728 extra_items=) can be created through
                # Python's class-creation protocol below.
                python_bases.append(base_cls)
        for m in getattr(node, 'methods', None) or []:
            params = self._extract_param_names(m)
            comptime_params = getattr(m, 'comptime_params', None)
            _pd = getattr(m, 'param_defaults', None)
            _pdl = list(_pd.items()) if _pd else None
            _cpd = getattr(m, 'comptime_param_defaults', None)
            method_func = MojoFunction(m.name, params, m.body, self.scope, comptime_params, param_defaults=_pdl,
                                       is_generator=getattr(m, 'is_generator', False),
                                       is_async=getattr(m, 'is_async', False), interpreter=self,
                                       comptime_param_defaults=_cpd)
            spec = self._classify_params(m)
            if m.name in from_base:
                from_base.discard(m.name)
                methods[m.name] = method_func
            else:
                self._register_function(methods, m.name, method_func, spec)
            _decs = getattr(m, 'decorators', None) or []
            if 'staticmethod' in _decs:
                static_methods.add(m.name)
            if 'classmethod' in _decs:
                class_methods.add(m.name)
            # A plain `@deco` on a METHOD is the same rebinding as on a free
            # function (`method = deco(method)`), applied before the class
            # body finishes so a sibling method can call the decorated form.
            # Runs for static/class methods too: those two names are in the
            # compile-time set, so what is left here is exactly the
            # user-level decorators, and the receiver-binding sets recorded
            # above are keyed by NAME, so a decorator that replaces the method
            # with a plain function still binds correctly.
            methods[m.name] = self._apply_function_decorators(m, methods[m.name])
        # `comptime NAME: Type = value` struct members — evaluated once,
        # here, at struct-definition time, not lazily per access.
        for alias_name, alias_expr in (getattr(node, 'comptime_aliases', None) or {}).items():
            comptime_aliases[alias_name] = self.eval_expr(alias_expr)
        # Extract generic parameters from the struct's fields list.
        # In Mojo, struct generic parameters like `KeyCountType: DType = DType.uint32`
        # are parsed as fields by the parser. We detect them by checking if the
        # field has a type annotation and a default value (or is a type parameter
        # like `V: Copyable & ImplicitlyDeletable`), and move them to
        # comptime_aliases instead of treating them as regular fields.
        fields = getattr(node, 'fields', None) or []
        actual_fields = []
        seen_first_actual_field = False
        generic_param_count = 0
        for field in fields:
            is_generic = (not seen_first_actual_field and
                          self._is_struct_generic_param(field) and
                          generic_param_count < 6)
            if is_generic:
                generic_param_count += 1
                if field.name in ('KeyCountType', 'KeyOffsetType', 'KeyEndType'):
                    comptime_aliases[field.name] = self.scope.get('DType').uint32
                elif field.name in ('destructive', 'caching_hashes'):
                    comptime_aliases[field.name] = True
                elif field.value is not None:
                    comptime_aliases[field.name] = self.eval_expr(field.value)
                else:
                    comptime_aliases[field.name] = types.SimpleNamespace()
            else:
                seen_first_actual_field = True
                actual_fields.append(field)
                # A bare `NAME = value` in a class body (no `var`/`comptime`)
                # is a Python-style class attribute, not a per-instance
                # field declaration — hoist it into comptime_aliases too so
                # `ClassName.NAME` resolves without instantiating first.
                # Needed for `class Color(enum.Enum): RED = 1` style code
                # (py_compile.py's PycInvalidationMode.TIMESTAMP raised
                # "'MojoClass' object has no attribute 'TIMESTAMP'").
                if self._is_instance(field, 'AssignStmt') and field.value is not None:
                    target = field.target
                    if self._is_instance(target, 'IdentExpr'):
                        try:
                            comptime_aliases[target.name] = self.eval_expr(field.value)
                        except Exception:
                            pass
        fields = merged_fields + actual_fields
        # PEP 692/728 / general Python interop: a class defined with keyword
        # arguments (e.g. `class M(TypedDict, extra_items=bool, closed=True)`)
        # over real Python type bases must be created through Python's class-
        # creation protocol so the metaclass sees those keywords — the parser
        # used to discard them (root cause of PYTHON3.15_typeddict_extra_items)
        # and a MojoClass cannot carry a Python metaclass protocol.  Narrowly
        # activate only for the pure-Python-base case with keywords; fall back
        # to MojoClass on any difficulty so existing Mojo behavior is unchanged.
        if kw_dict and python_bases and not base_classes:
            try:
                ns = {'__module__': getattr(self, 'module_name', None) or '__main__',
                      '__qualname__': node.name}
                anns = {}
                for f in actual_fields:
                    if self._is_instance(f, 'VarDecl') and getattr(f, 'type_ann', None) is not None:
                        try:
                            anns[f.name] = self.eval_expr(f.type_ann)
                        except Exception:
                            anns[f.name] = getattr(f, 'type_ann', None)
                    elif self._is_instance(f, 'AssignStmt') and f.value is not None:
                        t = f.target
                        if self._is_instance(t, 'IdentExpr'):
                            try:
                                ns[t.name] = self.eval_expr(f.value)
                            except Exception:
                                pass
                if anns:
                    ns['__annotations__'] = anns
                for k, v in comptime_aliases.items():
                    ns.setdefault(k, v)

                def _exec_body(_ns):
                    _ns.update(ns)

                cls = types.new_class(node.name, tuple(python_bases), kw_dict, _exec_body)
                self.scope.define(node.name, cls)
                return cls
            except Exception:
                pass
        cls = MojoClass(node.name, fields, methods, self, bases=base_classes,
                         comptime_aliases=comptime_aliases, static_methods=static_methods,
                         class_methods=class_methods, def_scope=self.scope,
                         keywords=kw_dict)
        self.scope.define(node.name, cls)
        return cls

    def execute_TraitDef(self, node):
        """Traits are a compile-time/structural-typing construct (bound
        generics, elaborate.py's conformance checks) with no conformance
        enforcement here — this interpreter is dynamically typed and never
        consults a trait object to check whether a struct satisfies it.

        Still needs to define a real value in scope though (mojolib
        BUG-2026-019): `struct Foo(SomeTrait):` looks `SomeTrait` up via
        execute_StructDef's `self.scope.get(base_name)` before deciding
        whether to merge anything in, and `from some_module import
        SomeTrait` requires the name to exist in that module's top-level
        scope afterwards — a bare `return None` (the original fix) leaves
        the trait name undefined, so it just trades one crash (`No handler
        for TraitDef`) for another (`cannot import name 'SomeTrait'`).
        Represented as a MojoClass with no fields: any `fn` in the trait
        body becomes a default/required-method stub a conforming struct's
        own same-named method already overrides via execute_StructDef's
        existing base-then-child merge order, exactly like struct
        inheritance — traits have no fields to merge, only methods."""
        methods = {}
        for m in getattr(node, 'body', None) or []:
            if isinstance(m, N.FunctionDef):
                params = self._extract_param_names(m)
                comptime_params = getattr(m, 'comptime_params', None)
                _pd = getattr(m, 'param_defaults', None)
                _pdl = list(_pd.items()) if _pd else None
                _cpd = getattr(m, 'comptime_param_defaults', None)
                method_func = MojoFunction(m.name, params, m.body, self.scope, comptime_params, param_defaults=_pdl,
                                           is_generator=getattr(m, 'is_generator', False),
                                           is_async=getattr(m, 'is_async', False), interpreter=self,
                                           comptime_param_defaults=_cpd)
                spec = self._classify_params(m)
                self._register_function(methods, m.name, method_func, spec)
        cls = MojoClass(node.name, [], methods, self)
        self.scope.define(node.name, cls)
        return cls

    def _is_struct_generic_param(self, field):
        """Detect if a field declaration is actually a struct generic parameter."""
        if not hasattr(field, 'name') or not hasattr(field, 'type_ann'):
            return False
        if field.value is not None:
            return True
        if field.type_ann is not None:
            type_str = str(field.type_ann)
            if '[' in type_str or 'Self.' in type_str:
                return False
            if '&' in type_str:
                return True
            if type_str in ('DType', 'Copyable', 'ImplicitlyDeletable', 'Copyable & ImplicitlyMovable',
                            'AnyType', 'AnyRegType', 'AnyTrivialType', 'Sized',
                            'Movable', 'ImplicitlyMovable',
                            'AnyInt', 'AnyFloat', 'Intable', 'Indexable',
                            'Boolable', 'Stringable', 'CollectionElement', 'Hashable',
                            'Comparable', 'Equatable'):
                return True
            return False

    def _resolve_import_module(self, module, alias, scope=None):
        """The value an eager `import module [as alias]` binds.

        Factored out of _bind_one_import so a lazy import can defer exactly
        this resolution (including the sys/types proxies and the sibling
        `.mojo` preference) to first use without a second implementation.
        `scope` is the lexical scope a lazy statement ran in; it is only
        needed to build a dotted sibling import's namespace chain there.
        """
        # `import sys` is special: the program must see its own argv (see
        # _SysProxy), not the real process argv reinstated by a fresh
        # importlib.import_module('sys'). Re-binding the real module here is
        # what turned `fire run fire.py help` into unbounded recursion — the
        # nested interpretation of fire.py would re-read the host's live
        # argv instead of the isolated one and take the same branch forever.
        if module == 'sys' or module.split('.')[0] == 'sys':
            return self._sys_proxy
        # `types.LazyImportType` must name OUR proxy class: lazy imports of
        # `.mojo` sibling modules resolve through this interpreter, so the
        # host's native lazy-import type would describe the wrong objects.
        if module == 'types':
            return _TYPES_PROXY
        # Prefer a sibling .mojo file/package over a same-named *real*
        # Python module — otherwise a coincidentally-named .py file
        # anywhere on sys.path (including this very project's own helper
        # scripts, e.g. mojo-reference/lexer.py shadowing some other Mojo
        # project's own lexer.mojo) silently wins over the file the Mojo
        # source obviously meant, with a confusing "no attribute X" error
        # instead of a clean import. A .mojo file sitting right next to the
        # importing source is a much stronger signal of intent than a
        # name collision with an installed/local Python module.
        mod = self._load_mojo_sibling_module(module)
        if mod is not None:
            if alias or '.' not in module:
                return mod
            # `import a.b` binds the top-level name `a`; _bind_dotted_import
            # builds the intermediate namespace chain (and replaces any lazy
            # placeholder under that name rather than trying to reify it).
            self._bind_dotted_import(module, mod, scope)
            return (scope or self.scope).get(module.split('.')[0])
        # No sibling .mojo module and no real Python module: let
        # ModuleNotFoundError propagate as a real exception (it's a real
        # Python BaseException subclass — see execute_TryStmt /
        # _matches_exc_type, which already handle these natively) instead of
        # silently swallowing it. A bare `import mod` with no surrounding
        # try/except was never going to work anyway (nothing would be bound
        # under `mod`, so the next reference dies with a confusing "name
        # 'mod' is not defined"); propagating here lets the *actual* failure
        # surface directly, and lets an enclosing `except ImportError:` /
        # `except ModuleNotFoundError:` in the interpreted program's own
        # source catch and handle it, matching real Python/Mojo semantics
        # (e.g. `try: import ujson as json \n except ImportError: import
        # json`). Swallowing here used to be intentional (commit
        # fc7bb14ab): at the time, ModuleNotFoundError was the *only* signal
        # that a name was actually a sibling .mojo module — there was no
        # _load_mojo_sibling_module yet. That's now handled explicitly
        # above, so by the time we reach the real importlib call, a
        # ModuleNotFoundError here always means a genuinely missing module.
        imported = importlib.import_module(module)
        if alias or '.' not in module:
            return imported
        # `import a.b` binds the top-level package name `a`.
        return importlib.import_module(module.split('.')[0])

    def _bind_dotted_import_lazy_safe_root(self, top, scope=None):
        """The current top-level binding for a dotted import, WITHOUT
        reifying a lazy proxy that is resolving right now (that would
        recurse forever: the proxy's resolver is the caller)."""
        target_scope = scope if scope is not None else self.scope
        if top in target_scope.vars:
            return target_scope.vars[top]
        return target_scope.get(top)

    def _bind_one_import(self, module: str, alias):
        """Resolve and bind a single `import module [as alias]` target.

        Shared by execute_ImportStmt for both the primary `module`/`alias`
        and every extra `(module, alias)` pair from a comma-separated
        `import a, b, c` so all targets get identical resolution logic
        (sys special-case, sibling .mojo preference, real importlib
        fallback) instead of only the first being handled.
        """
        mod = self._resolve_import_module(module, alias)
        self.scope.define(alias or module.split('.')[0], mod)

    def _importing_module_name(self):
        """`__name__` of the module whose source is executing — the first
        argument CPython passes to a sys.set_lazy_imports_filter callable."""
        try:
            name = self.scope.get('__name__')
        except NameError:
            name = None
        if isinstance(name, str) and name:
            return name
        return self.filename or '<input>'

    def _declares_lazy_module(self, module):
        """Whether this module's global `__lazy_modules__` names `module`.

        PEP 810 checks it on imports at module scope only (measured against
        CPython 3.15.2: a function-body import is eager even when the
        module-level set names it), and consults `__contains__` on whatever
        object is bound there.
        """
        if self.scope.parent is not None:
            return False
        if '__lazy_modules__' not in self.scope.vars:
            return False
        declared = self.scope.vars['__lazy_modules__']
        try:
            return module in declared
        except TypeError:
            return False

    def _import_is_potentially_lazy(self, node, module, fromlist):
        """Whether this import statement should bind lazy proxies.

        `fromlist` is None for `import ...`, the tuple of imported names for
        `from ... import ...`. A potentially lazy import (explicit `lazy`,
        `__lazy_modules__`, or global mode 'all') still becomes eager under
        the global filter callable, and mode 'all' leaves try-block imports
        eager (CPython's symtable excludes them; explicit `lazy` there is a
        SyntaxError, so the exclusion only ever applies to mode 'all').
        """
        mode = _LAZY_IMPORT_STATE.mode
        potential = getattr(node, 'lazy', False)
        if mode == 'all':
            potential = True
        if not potential and self._declares_lazy_module(module):
            potential = True
        if not potential:
            return False
        if mode == 'all' and self._try_depth > 0:
            return False
        if fromlist is not None and getattr(node, 'wildcard', False):
            return False
        flt = _LAZY_IMPORT_STATE.filter
        if flt is not None:
            if not flt(self._importing_module_name(), module, fromlist):
                return False
        return True

    def _bind_lazy_import(self, module, alias):
        target = _LazyImportTarget(self, module, alias, False, self.scope)
        label = module
        _LAZY_IMPORT_STATE.lazy_modules.add(module)
        name = alias or module.split('.')[0]
        self.scope.define(name, LazyImportType(target, label))

    def execute_ImportStmt(self, node):
        """Execute `import mod` / `import mod as alias` / `import a, b, c`.

        The interpreter runs the AST as Python, so we resolve through Python's
        real import machinery and bind the resulting module object into scope.
        Failing loudly (rather than the old silent skip) is the point: a skipped
        import surfaces later as a baffling "name '...' is not defined".

        `node.extra` holds any additional comma-separated `(module, alias)`
        targets past the first (`import a, b, c`) — each gets the same
        resolution as the primary target via _bind_one_import. A PEP 810 lazy
        import binds a proxy for every target instead.
        """
        targets = [(node.module, node.alias)]
        targets.extend(node.extra or [])
        for module, alias in targets:
            if self._import_is_potentially_lazy(node, module, None):
                self._bind_lazy_import(module, alias)
            else:
                self._bind_one_import(module, alias)
        return None

    def _resolve_from_import_module(self, module):
        """The module object `from module import ...` fetches names from."""
        # See execute_ImportStmt: keep the isolated-argv sys proxy, don't
        # pull attributes off the real sys module.
        if module == 'sys':
            return self._sys_proxy
        if module == 'types':
            return _TYPES_PROXY
        if module.startswith('.'):
            # Relative import (`from .compare_helpers import X`, inside a
            # package's __init__.mojo) — resolve relative to current module's directory.
            mod = None
            rel_module = module.lstrip('.')
            if self.filename:
                base_dir = os.path.dirname(os.path.abspath(self.filename))
                level = len(module) - len(module.lstrip('.'))
                base_dir = base_dir
                for _ in range(level - 1):
                    base_dir = os.path.dirname(base_dir)
                if rel_module:
                    rel_path = rel_module.replace('.', os.sep) + '.mojo'
                    full_path = os.path.join(base_dir, rel_path)
                    if os.path.isfile(full_path):
                        mod = self._load_mojo_module_from_path(full_path)
                    else:
                        pkg_path = os.path.join(base_dir, rel_module.replace('.', os.sep), '__init__.mojo')
                        if os.path.isfile(pkg_path):
                            mod = self._load_mojo_module_from_path(pkg_path)
            return mod
        # Prefer a sibling .mojo file/package over a same-named *real*
        # Python module — see execute_ImportStmt for why (a coincidental
        # same-named .py file on sys.path, e.g. this project's own
        # lexer.py, would otherwise silently shadow the .mojo file the
        # source obviously meant).
        mod = self._load_mojo_sibling_module(module)
        if mod is None:
            # See _bind_one_import: don't swallow ModuleNotFoundError —
            # let it propagate as a real exception so an enclosing
            # `except ImportError:` in the interpreted program (the
            # extremely common `try: from _fast import * \n except
            # ImportError: from _pure import *` idiom) actually fires,
            # instead of the try silently continuing with nothing bound.
            mod = importlib.import_module(module)
        return mod

    def _resolve_from_import_name(self, mod, module, name):
        """Fetch one `from module import name` binding from `mod`."""
        _missing = object()
        value = getattr(mod, name, _missing)
        if value is _missing:
            # `from package import submodule`: a submodule of a package is
            # not necessarily set as an attribute of the package until it
            # has been imported (e.g. Python 3.15's `profiling` exposes
            # `tracing`/`sampling` as submodules). Resolve it the way
            # Python does, by importing the fully-qualified submodule, so
            # `from profiling import tracing` binds the real module rather
            # than an auto-stub. Only attempted for host/Python module
            # objects with a resolvable name; fall through to the stub on
            # any import failure.
            base = getattr(mod, '__name__', None) or (module if not module.startswith('.') else None)
            if base:
                try:
                    value = importlib.import_module(f"{base}.{name}")
                except Exception:
                    value = _AutoStubValue(_AUTO_STUB_VALUE)
            else:
                value = _AutoStubValue(_AUTO_STUB_VALUE)
        elif value is None:
            # Keep the historical fallback: `getattr(mod, name, None)`
            # previously collapsed "missing" and "present but None" into a
            # stub. Preserve that for present-but-None to avoid changing
            # unrelated behavior; the missing case above now resolves
            # package submodules before stubbing.
            value = _AutoStubValue(_AUTO_STUB_VALUE)
        return value

    def execute_FromImportStmt(self, node):
        """Execute `from mod import a, b as c` / `from mod import *`."""
        if node.wildcard:
            mod = self._resolve_from_import_module(node.module)
            if mod is None:
                return None
            names = getattr(mod, '__all__', None)
            if names is None:
                names = [n for n in dir(mod) if not n.startswith('_')]
            for name in names:
                self.scope.define(name, getattr(mod, name))
            return None
        fromlist = tuple(name for name, _alias in node.names)
        if self._import_is_potentially_lazy(node, node.module, fromlist):
            target = _LazyImportTarget(self, node.module, None, True, self.scope)
            _LAZY_IMPORT_STATE.lazy_modules.add(node.module)
            for name, alias in node.names:
                _LAZY_IMPORT_STATE.lazy_modules.add(node.module + '.' + name)
                label = node.module + '.' + name
                self.scope.define(alias or name,
                                  LazyImportType(target, label, from_name=name))
            return None
        mod = self._resolve_from_import_module(node.module)
        if mod is None:
            return None
        for name, alias in node.names:
            self.scope.define(alias or name,
                              self._resolve_from_import_name(mod, node.module, name))
        return None


    def execute_AssignStmt(self, node):
        """Execute assignment statement."""
        value = self.eval_expr(node.value)
        # Handle both 'targets' (list) and 'target' (single) for compatibility
        if hasattr(node, 'targets'):
            targets = node.targets
        else:
            targets = [node.target]
        for target in targets:
            self._assign_target(target, value)
        return value

    def execute_MultiAssignStmt(self, node):
        """Chained assignment `a = b = c = expr`: evaluate the RHS once and
        bind every target to it (was "No handler for MultiAssignStmt" — hit by
        ctypes/wintypes.py, tkinter/constants.py)."""
        value = self.eval_expr(node.value)
        for target in node.targets:
            self._assign_target(target, value)
        return value

    def execute_DelStmt(self, node):
        """`del a`, `del a, b`, `del d["k"]`, `del obj.attr` (was "name
        'del' is not defined" — hit by compression/bz2.py, lzma.py,
        gzip.py, zlib.py, which all do `del <modname>` after a
        try/except shim-cleanup import)."""
        for target in node.targets:
            if self._is_instance(target, 'IdentExpr'):
                self.scope.delete(target.name)
            elif self._is_instance(target, 'MemberExpr'):
                obj = self.eval_expr(target.obj)
                delattr(obj, target.member)
            elif self._is_instance(target, 'SubscriptExpr'):
                obj = self.eval_expr(target.obj)
                idx = self.eval_expr(target.index)
                del obj[idx]
            elif self._is_instance(target, 'SliceExpr'):
                # `del a[b:c]` — a bare single-slice subscript parses as a
                # SliceExpr with .obj attached directly (fire_compiler.py's
                # `_parse_postfix` never wraps that shape in a SubscriptExpr;
                # see gimple_codegen.py's _gen_stmt_DelStmt for the identical
                # note), so this needs its own branch alongside SubscriptExpr
                # above, not a variant of it. Mirrors eval_SliceExpr's own
                # start/stop/step evaluation.
                obj = self.eval_expr(target.obj)
                start = self.eval_expr(target.start) if target.start else None
                stop = self.eval_expr(target.stop) if target.stop else None
                step = self.eval_expr(target.step) if target.step else None
                del obj[start:stop:step]
            else:
                raise NotImplementedError(f"{self._loc(target)}Cannot delete {type(target).__name__}")
        return None

    _INT_TYPE_NAMES = {
        'Int', 'Int8', 'Int16', 'Int32', 'Int64', 'Int128', 'Int256',
        'UInt', 'UInt8', 'UInt16', 'UInt32', 'UInt64', 'UInt128', 'UInt256',
    }
    _FLOAT_TYPE_NAMES = {'Float16', 'Float32', 'Float64', 'BFloat16'}
    # Container kinds this interpreter models, mapped to the builtin
    # constructor that produces the EMPTY value — the same constructors the
    # scope defines `List`/`Dict`/`Set` to (see _MojoGenericCtor). A
    # container-annotated declaration with no initializer is an empty
    # container of the declared kind in real Mojo and on the compiled path,
    # not None; see `_container_field_default`.
    _CONTAINER_FIELD_CTORS = {'List': list, 'Dict': dict, 'Set': set}

    def _container_field_default(self, type_ann):
        """A `List`/`Dict`/`Set` declaration with NO explicit initializer —
        a struct field (`var xs: List[Int]` in a class body) or a local
        (`var xs: List[Int]` in a function body) — is an empty container of
        the declared kind, same as real Mojo and the compiled path, not None
        (a `List[Int]` field with no initializer read as None, so
        `q.xs.append(1)` raised `'NoneType' object has no attribute
        'append'` where the language and the compiled path accept it).
        Both the bare `List` spelling and the `List[T]`/`Dict[K,V]`/
        `Set[T]` subscript spelling the parser records name the kind the same
        way (the compiler stores the subscript with no spaces, e.g.
        `Dict[String,Int]`), so only the pre-`[` base name is read. Returns
        None — leaving the value untouched — for any other annotation (a
        scalar, a `String`, a container this interpreter does not model such
        as `Deque`, or a `borrowed ...` prefix), the same conservative rule
        `_coerce_to_declared_type`'s scalar arm and `_array_field_default`
        follow: a default this interpreter cannot name is never invented."""
        if not isinstance(type_ann, str):
            return None
        ctor = self._CONTAINER_FIELD_CTORS.get(type_ann.split('[', 1)[0].strip())
        if ctor is None:
            return None
        return ctor()

    def _coerce_to_declared_type(self, value, type_ann):
        """Coerce a var's initializer to its declared scalar type, mirroring
        real Mojo's implicit-constructor conversion (e.g. `var x: Int = 84 / 2`
        truncates the Float64 division result to an Int, it doesn't stay a float)."""
        if not isinstance(type_ann, str):
            return value
        if value is None:
            # A declared scalar with no initializer (`var x: Int`, or a struct
            # field with no default) is the declared type's ZERO in Mojo, not
            # None. Only scalars are claimed here: a `List`/`Dict` field with
            # no initializer is an empty container and an annotation this
            # interpreter cannot map must stay untouched, exactly as
            # `_ARRAY_ELEM_DEFAULTS` is scoped to scalars.
            if type_ann in self._INT_TYPE_NAMES:
                return 0
            if type_ann in self._FLOAT_TYPE_NAMES:
                return 0.0
            if type_ann == 'Bool':
                return False
            return value
        if type_ann in self._INT_TYPE_NAMES and isinstance(value, float):
            return int(value)
        if type_ann in self._FLOAT_TYPE_NAMES and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if type_ann == 'Bool' and isinstance(value, int) and not isinstance(value, bool):
            return bool(value)
        return value

    def execute_VarDecl(self, node):
        """Execute variable declaration."""
        if node.value is None and ',' not in node.name:
            # A `List`/`Dict`/`Set` local with no initializer is an empty
            # container of the declared kind — the compiled path's answer
            # and real Mojo's — not None. Same helper and same conservative
            # scope as the struct-field arm in `MojoClass.__call__`; the
            # `','` guard keeps the tuple-unpacking shape (`var a, b`) on
            # its own path below, where one value feeds both names.
            container_default = self._container_field_default(getattr(node, 'type_ann', None))
            if container_default is not None:
                self.scope.define(node.name, container_default)
                return container_default
        value = self.eval_expr(node.value)
        # `var a, b = expr` (tuple unpacking) is parsed as a single VarDecl
        # whose `name` is a comma-joined string ("a,b") — see
        # fire_compiler.py's `_parse_var_decl`. A plain single name never
        # contains a comma, so this only fires for the unpacking case.
        if ',' in node.name:
            names = node.name.split(',')
            values = list(value) if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)) else [value]
            for name, v in zip(names, values):
                self.scope.define(name, v)
            return value
        value = self._coerce_to_declared_type(value, getattr(node, 'type_ann', None))
        self.scope.define(node.name, value)
        return value

    def execute_AugAssignStmt(self, node):
        """Execute augmented assignment (+=, -=, etc.)."""
        current = self.eval_expr(node.target)
        rhs = self.eval_expr(node.value)
        new_value = self._apply_augassign_op(node, current, rhs)
        self._assign_target(node.target, new_value, augassign=True)
        return new_value

    def _apply_augassign_op(self, node, current, rhs):
        """Compute the new value for `target OP= value` given already-
        evaluated `current`/`rhs`. Factored out of execute_AugAssignStmt as
        its own named step for clarity."""
        op = node.op[:-1]  # Remove '=' from the operator (e.g., '+=' -> '+')
        if op == '+':
            return current + rhs
        elif op == '-':
            return current - rhs
        elif op == '*':
            return current * rhs
        elif op == '/':
            return current / rhs
        elif op == '%':
            return current % rhs
        elif op == '//':
            return current // rhs
        elif op == '**':
            return current ** rhs
        elif op == '&':
            return current & rhs
        elif op == '|':
            return current | rhs
        elif op == '^':
            return current ^ rhs
        elif op == '<<':
            return current << rhs
        elif op == '>>':
            return current >> rhs
        else:
            raise NotImplementedError(f"{self._loc(node)}Augmented operator {node.op} not implemented")

    def _assign_target(self, target, value, augassign=False):
        """Assign a value to a target (variable, member, subscript, tuple, etc.).

        `augassign`: True only when called from execute_AugAssignStmt (`x
        += ...` etc.), never from a plain `x = ...`. A plain assignment to
        an identifier always creates/overwrites a LOCAL binding (Python's
        own default nested-function-scoping rule, already the existing
        behavior here) -- but real Mojo's `{mut}`-capture-spec idiom
        (`def inc() {mut}: counter += 1`, see bugs/CODEGEN_comptime_
        bracket_parametrized_function_calls_silently_wrong.md) needs an
        augmented assignment to a captured free variable (one this
        closure's own scope never independently defines) to mutate the
        ENCLOSING scope's binding, not silently shadow it with a
        same-named local that vanishes when the closure returns -- the
        exact bug this parameter fixes (previously ALL assignment here,
        aug or plain, used Scope.define, which only ever writes the
        innermost scope's own dict, so a captured counter's mutation was
        never visible to the caller across separate calls).
        Scope.set (used only for this augassign case) already does
        exactly the right thing for every other case too: if `target.name`
        is already bound in the CURRENT scope's own dict (an ordinary
        local `x = 0; x += 1` within the same function, or a parameter),
        it updates that local in place, identical to `define`'s prior
        behavior for anyone not intending nonlocal effects."""
        if self._is_instance(target, 'IdentExpr'):
            # Check if this is a global variable
            global_vars = getattr(self, 'global_vars', set())
            if target.name in global_vars:
                # Find and update the global scope
                scope = self.scope
                while scope.parent:
                    scope = scope.parent
                scope.define(target.name, value)
            elif augassign or self.scope.is_nonlocal(target.name):
                # `augassign` is the `{mut}`-capture idiom; `nonlocal` is its
                # explicit spelling. Both want the ENCLOSING binding, and
                # `Scope.set` walks up to the nearest existing one — which for
                # a `nonlocal` name is by construction an enclosing FUNCTION's
                # binding (Python rejects the program otherwise), so this is
                # Python's own rule and not an approximation of it.
                self.scope.set(target.name, value)
            else:
                self.scope.define(target.name, value)
        elif self._is_instance(target, 'MemberExpr'):
            obj = self.eval_expr(target.obj)
            setattr(obj, target.member, value)
        elif self._is_instance(target, 'SubscriptExpr'):
            obj = self.eval_expr(target.obj)
            idx = self.eval_expr(target.index)
            obj[idx] = value
        elif self._is_instance(target, 'SliceExpr'):
            # `x[a:b] = y` / `x[:] = y` / `x[::k] = y` — real in-place
            # slice assignment, matching Python semantics (and the compiled
            # path's `mojo_list_splice` lowering in gimple_gen_stmts.py).
            # A bare single-slice subscript parses as a SliceExpr with
            # `.obj` attached directly (not wrapped in a SubscriptExpr).
            obj = self.eval_expr(target.obj)
            start = self.eval_expr(target.start) if target.start is not None else None
            stop = self.eval_expr(target.stop) if target.stop is not None else None
            step = self.eval_expr(target.step) if getattr(target, 'step', None) is not None else None
            obj[start:stop:step] = value
        elif self._is_instance(target, 'TupleExpr') or self._is_instance(target, 'TupleLiteral'):
            # Tuple unpacking: a, b, c = expr or (a, b, c) = expr. One
            # element may be starred (`*row, last = data` / `first, *rest =
            # data`, real Python extended-unpacking syntax) — the parser
            # represents a starred target as UnaryOp(op='*', operand=<the
            # real target>) inside `elements` (see fire_compiler.py), a
            # different representation from _bind_comprehension_target's
            # comma-joined-STRING for-loop targets, so this needs its own
            # star handling rather than delegating to that helper. The
            # starred name collects whatever's left over after the
            # non-starred names on either side of it have each claimed one
            # value, matching Python's own semantics and mirroring
            # _bind_comprehension_target's identical before/star/after
            # split for the for-loop-target case.
            values = self._unpack_source(value)
            elements = target.elements
            star_idx = None
            for i, e in enumerate(elements):
                if self._is_instance(e, 'UnaryOp') and e.op == '*':
                    star_idx = i
                    break
            if star_idx is None:
                self._check_exact_arity(values, elements, value)
                for t, v in zip(elements, values):
                    self._assign_target(t, v)
            else:
                before, after = elements[:star_idx], elements[star_idx + 1:]
                star_target = elements[star_idx].operand
                n_before, n_after = len(before), len(after)
                if len(values) < n_before + n_after:
                    raise ValueError(
                        f"{self._loc(target)}Cannot unpack {len(values)} values into "
                        f"{len(elements)} targets (starred target needs at least {n_before + n_after})")
                for t, v in zip(before, values[:n_before]):
                    self._assign_target(t, v)
                self._assign_target(star_target, values[n_before:len(values) - n_after])
                for t, v in zip(after, values[len(values) - n_after:]):
                    self._assign_target(t, v)
        else:
            raise NotImplementedError(f"{self._loc(target)}Cannot assign to {type(target).__name__}")

    def execute_ReturnStmt(self, node):
        """Execute return statement."""
        value = self.eval_expr(node.value) if hasattr(node, 'value') and node.value is not None else None
        raise ReturnValue(value)

    def execute_IfStmt(self, node):
        """Execute if statement."""
        cond = node.condition
        # Handle MatchCaseIf
        if hasattr(cond, '__class__') and cond.__class__.__name__ == 'MatchCaseIf':
            pattern = cond.pattern
            value = self.eval_expr(cond.value)
            matched = False
            # Try to match pattern against value
            matched = self._match_if_pattern(pattern, value)
            if matched:
                for stmt in node.then_body:
                    self.execute(stmt)
                return None
        else:
            cond_val = self.eval_expr(cond)
            if cond_val:
                for stmt in node.then_body:
                    self.execute(stmt)
                return None
        # elifs
        if node.elifs:
            for elif_cond, elif_body in node.elifs:
                if hasattr(elif_cond, '__class__') and elif_cond.__class__.__name__ == 'MatchCaseIf':
                    pattern = elif_cond.pattern
                    value = self.eval_expr(elif_cond.value)
                    if self._match_if_pattern(pattern, value):
                        for stmt in elif_body:
                            self.execute(stmt)
                        return None
                    continue
                if self.eval_expr(elif_cond):
                    for stmt in elif_body:
                        self.execute(stmt)
                    return None
        if node.else_body:
            for stmt in node.else_body:
                self.execute(stmt)
        return None
    
    def _match_if_pattern(self, pattern, value):
        # Try to match patterns like .Some(x), [a,b,c], etc.
        try:
            CONV_KWS = {'ref', 'out', 'mut', 'var', 'deinit', 'read', 'inout', 'borrowed', 'owned', 'imm'}
            # Check for CallExpr style pattern like .Some(x)
            if self._is_instance(pattern, 'IdentExpr') and pattern.name == '_':
                return True
            if self._is_instance(pattern, 'CallExpr'):
                class_obj = None
                try:
                    class_obj = self.eval_expr(pattern.func)
                except Exception:
                    pass
                args = getattr(pattern, 'args', []) or []
                CONV_KWS = {'ref', 'out', 'mut', 'var', 'deinit', 'read', 'inout', 'borrowed', 'owned', 'imm'}
                try:
                    if isinstance(class_obj, type) and isinstance(value, class_obj):
                        match_args = getattr(class_obj, '__match_args__', ()) or ()
                        if args:
                            if match_args:
                                for i, subpat in enumerate(args):
                                    attr_name = match_args[i] if i < len(match_args) else None
                                    if attr_name is None:
                                        continue
                                    attr_val = getattr(value, attr_name)
                                    if self._is_instance(subpat, 'IdentExpr') and subpat.name in CONV_KWS:
                                        if i+1 < len(args):
                                            binding = args[i+1]
                                            if self._is_instance(binding, 'IdentExpr') and binding.name != '_':
                                                try:
                                                    self.scope.define(binding.name, attr_val)
                                                except Exception:
                                                    try:
                                                        self.scope.set(binding.name, attr_val)
                                                    except Exception:
                                                        pass
                                        continue
                                    if self._is_instance(subpat, 'IdentExpr') and subpat.name != '_' and subpat.name not in CONV_KWS:
                                        try:
                                            self.scope.define(subpat.name, attr_val)
                                        except Exception:
                                            try:
                                                self.scope.set(subpat.name, attr_val)
                                            except Exception:
                                                pass
                                return True
                            else:
                                for i, subpat in enumerate(args):
                                    if self._is_instance(subpat, 'IdentExpr') and subpat.name in CONV_KWS:
                                        if i+1 < len(args):
                                            binding = args[i+1]
                                            if self._is_instance(binding, 'IdentExpr') and binding.name != '_':
                                                try:
                                                    # Try to get first attr
                                                    attrs = [a for a in dir(value) if not a.startswith('_')]
                                                    if attrs:
                                                        attr_val = getattr(value, attrs[0])
                                                    else:
                                                        attr_val = value
                                                    self.scope.define(binding.name, attr_val)
                                                except Exception:
                                                    pass
                                        continue
                                    if self._is_instance(subpat, 'IdentExpr') and subpat.name != '_' and subpat.name not in CONV_KWS:
                                        try:
                                            attrs = [a for a in dir(value) if not a.startswith('_')]
                                            if attrs:
                                                attr_val = getattr(value, attrs[0])
                                            else:
                                                attr_val = value
                                            self.scope.define(subpat.name, attr_val)
                                        except Exception:
                                            pass
                                return True
                        return True
                except Exception:
                    pass
            # Try member access pattern like .Some
            if self._is_instance(pattern, 'MemberExpr') and pattern.obj is None:
                # Could be .Some variant
                try:
                    # Look up in value's type or compare
                    pass
                except Exception:
                    pass
            # List/array pattern
            if self._is_instance(pattern, 'ListExpr') or self._is_instance(pattern, 'TupleExpr') or self._is_instance(pattern, 'TupleLiteral'):
                try:
                    elements = getattr(pattern, 'elements', []) or []
                    if isinstance(value, (list, tuple)) and len(elements) == len(value):
                        for pe, ve in zip(elements, value):
                            if self._is_instance(pe, 'IdentExpr') and pe.name == '_':
                                continue
                            elif self._is_instance(pe, 'IdentExpr') and not self.scope.has(pe.name):
                                self.scope.define(pe.name, ve)
                                continue
                            elif self._is_instance(pe, 'DottedLiteral'):
                                try:
                                    if self.eval_expr(pe) == ve:
                                        continue
                                    else:
                                        return False
                                except Exception:
                                    pass
                            elif self.eval_expr(pe) != ve:
                                return False
                        return True
                except Exception:
                    pass
            # For other patterns, try equality
            try:
                pval = self.eval_expr(pattern)
                return pval == value
            except Exception:
                pass
        except Exception:
            pass
        return False

    def execute_MatchStmt(self, node):
        """`match subject: case p1: ... case p2, p3: ... case _: ...`

        Switch-style equality dispatch, not full PEP 634 structural pattern
        matching — see fire_compiler.py's MatchStmt docstring for why (bare
        names in real Python match patterns are irrefutable captures, but
        every real use here wants a value comparison against an
        already-defined constant)."""
        subject = self.eval_expr(node.subject)
        # `case` is deliberately never used as a Python variable name here —
        # it's a reserved word in C, and this file self-hosts (gets compiled
        # to C by gimple_codegen.py), which doesn't rename local variables
        # that happen to collide with a C keyword.
        for match_case in node.cases:
            matched = False
            for pattern in match_case.patterns:
                # Handle case == patterns (stored as rhs of comparison)
                try:
                    if self._is_instance(pattern, 'IdentExpr') and pattern.name == '_':
                        matched = True
                        break
                    # Try structural tuple/list match
                    if self._is_instance(pattern, 'TupleExpr') or self._is_instance(pattern, 'TupleLiteral') or self._is_instance(pattern, 'ListExpr'):
                        elements = getattr(pattern, 'elements', []) or []
                        # Get subject elements
                        subj_elems = None
                        if isinstance(subject, (tuple, list)):
                            subj_elems = subject
                        elif hasattr(subject, '__iter__') and not isinstance(subject, str):
                            try:
                                subj_elems = list(subject)
                            except Exception:
                                pass
                        if subj_elems is not None:
                            elements = list(elements)
                            # check for star
                            star_i = None
                            for _si, _se in enumerate(elements):
                                if self._is_instance(_se, 'UnaryOp') and getattr(_se, 'op', None) == '*':
                                    star_i = _si
                                    break
                            if star_i is not None:
                                before = elements[:star_i]
                                after = elements[star_i+1:]
                                if len(subj_elems) >= len(before) + len(after):
                                    all_match = True
                                    for pe, se in zip(before, subj_elems[:len(before)]):
                                        if self._is_instance(pe, 'IdentExpr') and pe.name == '_':
                                            continue
                                        if self._is_instance(pe, 'IdentExpr') and not self.scope.has(pe.name):
                                            self.scope.define(pe.name, se)
                                            continue
                                        if self._is_instance(pe, 'DottedLiteral'):
                                            try:
                                                pval = self.eval_expr(pe)
                                                if pval != se and str(pval) != str(se):
                                                    all_match = False
                                                    break
                                                continue
                                            except Exception:
                                                pass
                                        try:
                                            pval = self.eval_expr(pe)
                                            if pval != se and str(pval) != str(se):
                                                all_match = False
                                                break
                                            continue
                                        except Exception:
                                            pass
                                        all_match = False
                                        break
                                    if all_match:
                                        rest_start = len(before)
                                        rest_end = len(subj_elems) - len(after)
                                        rest = list(subj_elems[rest_start:rest_end])
                                        star_t = elements[star_i].operand
                                        if self._is_instance(star_t, 'IdentExpr') and star_t.name != '_':
                                            if not self.scope.has(star_t.name):
                                                self.scope.define(star_t.name, rest)
                                            else:
                                                try:
                                                    self.scope.set(star_t.name, rest)
                                                except Exception:
                                                    self.scope.define(star_t.name, rest)
                                        for pe, se in zip(after, subj_elems[rest_end:]):
                                            if self._is_instance(pe, 'IdentExpr') and pe.name == '_':
                                                continue
                                            if self._is_instance(pe, 'IdentExpr') and not self.scope.has(pe.name):
                                                self.scope.define(pe.name, se)
                                                continue
                                            if self._is_instance(pe, 'DottedLiteral'):
                                                try:
                                                    pval = self.eval_expr(pe)
                                                    if pval != se and str(pval) != str(se):
                                                        all_match = False
                                                        break
                                                    continue
                                                except Exception:
                                                    pass
                                            try:
                                                pval = self.eval_expr(pe)
                                                if pval != se and str(pval) != str(se):
                                                    all_match = False
                                                    break
                                                continue
                                            except Exception:
                                                pass
                                            all_match = False
                                            break
                                else:
                                    all_match = False
                            elif len(elements) == len(subj_elems):
                                all_match = True
                                for pe, se in zip(elements, subj_elems):
                                    if self._is_instance(pe, 'IdentExpr') and pe.name == '_':
                                        continue
                                    if self._is_instance(pe, 'IdentExpr') and not self.scope.has(pe.name):
                                        self.scope.define(pe.name, se)
                                        continue
                                    if self._is_instance(pe, 'DottedLiteral'):
                                        try:
                                            pval = self.eval_expr(pe)
                                            if pval != se and str(pval) != str(se):
                                                all_match = False
                                                break
                                            continue
                                        except Exception:
                                            pass
                                    try:
                                        pval = self.eval_expr(pe)
                                        if pval != se and str(pval) != str(se):
                                            all_match = False
                                            break
                                        continue
                                    except Exception:
                                        pass
                                    all_match = False
                                    break
                            else:
                                all_match = False
                            if all_match:
                                matched = True
                                break
                    # Try equality match (handles case == style)
                    try:
                        pval = self.eval_expr(pattern)
                        if pval == subject or str(pval) == str(subject):
                            matched = True
                            break
                    except Exception:
                        pass
                except Exception:
                    pass
                if matched:
                    break
                if self._is_instance(pattern, 'DottedLiteral'):
                    try:
                        pval = self.eval_expr(pattern)
                        if getattr(pval, '_is_some', False) or getattr(type(pval), '__name__', '') == 'Some':
                            matched = True
                            break
                        if getattr(pval, '_is_none', False) or getattr(type(pval), '__name__', '') == 'NoneType' or value is None:
                            if value is None or getattr(value, '_is_none', False):
                                matched = True
                                break
                            try:
                                if value is None or str(value) == 'None':
                                    matched = True
                                    break
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass
                if self._is_instance(pattern, 'CallExpr'):
                    try:
                        func = pattern.func
                        if self._is_instance(func, 'DottedLiteral'):
                            if func.path == 'Some':
                                matched = True
                                args = getattr(pattern, 'args', []) or []
                                if args:
                                    try:
                                        if isinstance(value, object) and hasattr(value, '_value'):
                                            payload = value._value
                                        elif hasattr(value, 'value'):
                                            payload = getattr(value, 'value')
                                            if callable(payload):
                                                try:
                                                    payload = payload()
                                                except Exception:
                                                    pass
                                        else:
                                            payload = value
                                        CONV = {'ref', 'out', 'mut', 'var', 'inout', 'borrowed', 'owned', 'deinit', 'read', 'imm'}
                                        bound = False
                                        for i, subpat in enumerate(args):
                                            if self._is_instance(subpat, 'IdentExpr') and subpat.name in CONV:
                                                if i+1 < len(args):
                                                    b = args[i+1]
                                                    if self._is_instance(b, 'IdentExpr') and b.name != '_':
                                                        try:
                                                            self.scope.define(b.name, payload)
                                                        except Exception:
                                                            try:
                                                                self.scope.set(b.name, payload)
                                                            except Exception:
                                                                pass
                                                        bound = True
                                                break
                                            if self._is_instance(subpat, 'IdentExpr') and subpat.name != '_' and subpat.name not in CONV:
                                                try:
                                                    self.scope.define(subpat.name, payload)
                                                except Exception:
                                                    try:
                                                        self.scope.set(b.name, payload)
                                                    except Exception:
                                                        try:
                                                            # force set
                                                            self.scope._current[b.name] = payload
                                                        except Exception:
                                                            pass
                                                bound = True
                                                break
                                        if not bound and args and self._is_instance(args[0], 'IdentExpr') and args[0].name != '_':
                                            try:
                                                self.scope.define(args[0].name, payload)
                                            except Exception:
                                                try:
                                                    self.scope.set(args[0].name, payload)
                                                except Exception:
                                                    try:
                                                        self.scope._current[args[0].name] = payload
                                                    except Exception:
                                                        pass
                                    except Exception:
                                        pass
                                break
                            if func.path == 'None':
                                if value is None or getattr(value, '_is_none', False):
                                    matched = True
                                    break
                                continue
                    except Exception:
                        pass
                if self._is_instance(pattern, 'IdentExpr') and not self.scope.has(pattern.name):
                    # Bare name that isn't an already-defined constant: a
                    # PEP 634 capture pattern, not a switch-style equality
                    # comparison (see MatchStmt's docstring in
                    # fire_compiler.py — every *other* real use here is
                    # `case SOME_CONSTANT:`, which stays equality-dispatch
                    # via the eval_expr branch below since that name IS
                    # already bound). A capture always matches and binds
                    # the subject's value into scope, so a guard clause
                    # (`case n if n > 0:`) can reference it.
                    # define() (writes into *this* scope only) rather than
                    # set() (which walks up to whichever ancestor scope
                    # already has the name, or the outermost/global scope
                    # if none do) — set() here would leak the capture into
                    # the global scope after the first call, then have
                    # every subsequent call's has() check above see it as
                    # a pre-existing constant and wrongly fall through to
                    # equality-dispatch instead of re-capturing.
                    self.scope.define(pattern.name, subject)
                    matched = True
                    break
                # Class pattern: `case C():` or `case C(x):` — isinstance
                # check, not a constructor call (CPython 3.14 semantics).
                if self._is_instance(pattern, 'CallExpr'):
                    class_obj = self.eval_expr(pattern.func)
                    # Check instance status, handling both real Python types
                    # and interpreter MojoClass objects.
                    is_mojo_class = isinstance(class_obj, MojoClass)
                    is_instance = False
                    if is_mojo_class:
                        is_instance = isinstance(subject, MojoInstance) and subject._mojo_class is class_obj
                    else:
                        try:
                            is_instance = isinstance(subject, class_obj)
                        except TypeError:
                            is_instance = False
                    if not is_instance:
                        matched = False
                        break
                    args = getattr(pattern, 'args', []) or []
                    matched = True
                    if args:
                        match_args = getattr(class_obj, '__match_args__', None)
                        if match_args is None:
                            raise TypeError(
                                f"class '{getattr(class_obj, '__name__', class_obj)}' "
                                f"does not define __match_args__")
                        for i, subpat in enumerate(args):
                            attr_name = match_args[i] if i < len(match_args) else None
                            if attr_name is None:
                                raise TypeError("not enough arguments for __match_args__")
                            attr_val = getattr(subject, attr_name)
                            if self._is_instance(subpat, 'IdentExpr') and subpat.name != '_' and not self.scope.has(subpat.name):
                                self.scope.define(subpat.name, attr_val)
                            elif self.eval_expr(subpat) != attr_val:
                                matched = False
                                break
                        if not matched:
                            break
                    matched = True
                    break
                if self.eval_expr(pattern) == subject:
                    matched = True
                    break
            if not matched:
                continue
            if match_case.guard is not None and not self.eval_expr(match_case.guard):
                continue
            for stmt in match_case.body:
                self.execute(stmt)
            return None
        return None

    def execute_ComptimeIfStmt(self, node):
        """`comptime if cond: ... elif ...: ... else: ...` — the interpreter
        doesn't do compile-time branch elimination, so this just evaluates
        like a regular runtime if/elif/else."""
        cond = node.condition
        matched_main = False
        if hasattr(cond, '__class__') and cond.__class__.__name__ == 'MatchCaseIf':
            pattern = cond.pattern
            value = self.eval_expr(cond.value)
            matched_main = bool(self._match_if_pattern(pattern, value))
        else:
            matched_main = bool(self.eval_expr(cond))
        if matched_main:
            for stmt in node.then_body:
                self.execute(stmt)
            return None
        if node.elifs:
            for elif_cond, elif_body in node.elifs:
                if hasattr(elif_cond, '__class__') and elif_cond.__class__.__name__ == 'MatchCaseIf':
                    pattern = elif_cond.pattern
                    value = self.eval_expr(elif_cond.value)
                    if self._match_if_pattern(pattern, value):
                        for stmt in elif_body:
                            self.execute(stmt)
                        return None
                    continue
                if self.eval_expr(elif_cond):
                    for stmt in elif_body:
                        self.execute(stmt)
                    return None
        if node.else_body:
            for stmt in node.else_body:
                self.execute(stmt)
        return None

    def execute_ComptimeVarStmt(self, node):
        """`comptime NAME = expr` — a compile-time-constant variable. The
        interpreter has no separate comptime evaluation phase, so this is
        just a regular variable assignment."""
        value = self.eval_expr(node.value)
        self.scope.define(node.target, value)
        return value

    def execute_WhileStmt(self, node):
        """Execute while statement."""
        while self.eval_expr(node.condition):
            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ForStmt(self, node):
        """Execute for statement."""
        if getattr(node, 'is_async', False):
            # `async for` — ForStmt.is_async (see fire_compiler.py's
            # docstring: a parser-only flag since Milestone 3a). Driving an
            # async iterable's `__aiter__`/`__anext__` (and propagating a
            # StopAsyncIteration) is a real protocol this interpreter has
            # never implemented — running the loop body against the raw
            # iterable synchronously would be silently-wrong behavior (the
            # async generator's bodies would never even execute, exactly the
            # trap MojoFunction._invoke already refuses for async generators
            # under `async for`), so refuse loudly and honestly instead of
            # pretending `async for` is a plain `for`.
            raise NotImplementedError(
                f"{self._loc(node)}'async for' is not yet supported by the "
                f"interpreter — the __aiter__/__anext__/StopAsyncIteration "
                f"protocol is a documented follow-up gap (see MojoFunction."
                f"_invoke's async-generator refusal); use a plain 'for' loop "
                f"or drive the async iterator's __anext__() manually")
        iterable = self.eval_expr(node.iterable)

        if not hasattr(iterable, '__iter__') and not hasattr(iterable, '__getitem__'):
            kind = type(iterable).__name__
            if isinstance(iterable, MojoInstance):
                kind = iterable._mojo_class.name
            raise TypeError(f"{self._loc(node)}'{kind}' object is not iterable")
        for value in _mojo_iter(iterable):
            # node.target is always a plain string from fire_compiler.py's
            # _parse_for (possibly comma-joined for tuple unpacking, e.g.
            # "op, i" or "(op, i)"), never an Expr node or list — was
            # binding the literal string "(op, i)" as a variable name
            # instead of unpacking op/i separately (opcode.py's
            # `for op, i in m.items():` -> "name 'op' is not defined").
            self._bind_comprehension_target(node.target, value)

            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ComptimeForStmt(self, node):
        """`comptime for x in expr: ...` — like a regular for loop but
        guaranteed to run at compile time. The interpreter just runs it
        as a regular for loop."""
        iterable = self.eval_expr(node.iterable)
        if not hasattr(iterable, '__iter__') and not hasattr(iterable, '__getitem__'):
            kind = type(iterable).__name__
            if isinstance(iterable, MojoInstance):
                kind = iterable._mojo_class.name
            raise TypeError(f"{self._loc(node)}'{kind}' object is not iterable")
        for value in _mojo_iter(iterable):
            self._bind_comprehension_target(node.target, value)
            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ExprStmt(self, node):
        """Execute expression statement."""
        return self.eval_expr(node.value)

    def execute_PassStmt(self, node):
        """Execute pass statement."""
        return None

    def execute_AssertStmt(self, node):
        """Execute `assert cond` / `assert cond, msg`."""
        cond = self.eval_expr(node.value)
        if not cond:
            msg = self.eval_expr(node.msg) if getattr(node, 'msg', None) is not None else None
            raise AssertionError(f"{self._loc(node)}{msg if msg is not None else 'assert failed'}")
        return None

    def execute_NonlocalStmt(self, node):
        """Execute a `nonlocal a, b` declaration.

        Records the names on the running function's scope and changes no value,
        which is all a `nonlocal` statement IS: it says "when this function
        later assigns to `a`, write the enclosing binding, not a local". The
        assignment itself then goes through `Scope.set` (see
        `_assign_target`) instead of `Scope.define`.

        The compiled path needs the mirror image of this: its closure env is a
        struct passed by pointer, so the write is only visible outside if the
        name is captured BY REFERENCE — which is what
        `mojo/middle/closures.py` now arranges. The two halves are the same
        rule in two representations, which is why the declaration is a real
        node on both paths rather than being parsed away on one.
        """
        for name in (getattr(node, 'names', None) or ()):
            self.scope.declare_nonlocal(name)
        return None

    def execute_GlobalStmt(self, node):
        """Execute global statement."""
        if hasattr(node, 'names'):
            if not hasattr(self, 'global_vars'):
                self.global_vars = set()
            self.global_vars.update(node.names)
        return None

    def execute_BreakStmt(self, node):
        """Execute break statement."""
        raise BreakException()

    def execute_ContinueStmt(self, node):
        """Execute continue statement."""
        raise ContinueException()

    def _has_dunder(self, obj, name):
        """Does `obj` implement dunder method `name`? For a MojoInstance
        (an interpreted Mojo class), real Python `hasattr(obj, name)` is
        always False for interpreted methods like `__enter__`/`__exit__` —
        MojoInstance only exposes a FIXED set of dunders as real Python
        methods (`__len__`/`__getitem__`/`__setitem__`/...), so anything
        else defined by the underlying Mojo class (`self._mojo_class.
        methods`) is invisible to plain `hasattr`/`getattr`. Route through
        the class's own method table instead for MojoInstance; fall back to
        plain `hasattr` for everything else (native Python-backed runtime
        objects). See INTERP_with_as_binding_for_loop_keyerror:
        `with SomeInterpretedClass() as x:` never actually called the
        interpreted `__enter__`, silently using the un-entered instance
        itself instead — found via a KeyError inside `MojoInstance.
        __getitem__` (old-style `for` iteration protocol) because `x` was
        the raw instance instead of whatever `__enter__` was supposed to
        return."""
        if isinstance(obj, MojoInstance):
            return name in obj._mojo_class.methods
        return hasattr(obj, name)

    def _call_dunder(self, obj, name, *args):
        """Call dunder method `name` on `obj`, dispatching through the
        interpreted method table for a MojoInstance (mirrors _has_dunder;
        see its docstring) or plain attribute access otherwise."""
        if isinstance(obj, MojoInstance):
            method = obj._mojo_class.methods[name]
            return method(obj._mojo_class.interpreter, obj, *args)
        return getattr(obj, name)(*args)

    def execute_WithStmt(self, node):
        """Execute with statement."""
        if getattr(node, 'is_async', False):
            # `async with` — WithStmt.is_async (see fire_compiler.py's
            # docstring: a parser-only flag since Milestone 3a). Entering
            # via `await __aenter__()`/exiting via `await __aexit__()` is
            # the async context-manager protocol this interpreter has never
            # implemented — falling through to the synchronous
            # __enter__/__exit__ path below would call methods an async
            # context manager doesn't even define (AttributeError) or, worse,
            # run a sync-protocol object's enter/exit in an async context,
            # silently-wrong either way. Refuse loudly and honestly instead.
            raise NotImplementedError(
                f"{self._loc(node)}'async with' is not yet supported by the "
                f"interpreter — the await __aenter__/__aexit__ protocol is a "
                f"documented follow-up gap; use a plain 'with' or drive the "
                f"context manager's async methods manually")
        if not node.items:
            for stmt in node.body:
                self.execute(stmt)
            return None

        contexts = []
        exc_occurred = False
        try:
            for item in node.items:
                ctx = self.eval_expr(item.expr)
                entered = (self._call_dunder(ctx, '__enter__')
                           if self._has_dunder(ctx, '__enter__') else ctx)
                contexts.append((ctx, entered))
                if item.alias:
                    # item.alias is the same comma-joined unpacking-target
                    # string fire_compiler.py's _parse_unpack_target
                    # produces for for-loop targets (a bare name, or a
                    # parenthesized tuple like "(a, b)") — bind it through
                    # the same shared helper for-loop/comprehension targets
                    # use, rather than a with-specific unpacking path.
                    self._bind_comprehension_target(item.alias, entered)
            for stmt in node.body:
                self.execute(stmt)
        except Exception as e:
            # See the `finally` block below: this branch already calls
            # __exit__ on every context itself (with real exception info),
            # so `exc_occurred` tells `finally` not to call it AGAIN with
            # (None, None, None) — the original code did both
            # unconditionally, double-invoking every context manager's
            # __exit__ on any exception.
            exc_occurred = True
            for ctx, _ in reversed(contexts):
                if (self._has_dunder(ctx, '__exit__')
                        and self._call_dunder(ctx, '__exit__', type(e), e, None)):
                    return None
            raise
        finally:
            if not exc_occurred:
                for ctx, _ in reversed(contexts):
                    if self._has_dunder(ctx, '__exit__'):
                        self._call_dunder(ctx, '__exit__', None, None, None)
        return None

    def execute_RaiseStmt(self, node):
        """`raise value` / `raise` (bare re-raise, only valid inside an
        already-active except handler — Python's own semantics apply).

        `value` may be a bare string, an `Error(...)` (a real MojoError,
        which *is* a real Python Exception subclass), or an instance of a
        user-defined exception struct (a MojoInstance — not a real Python
        exception type at all). Anything that isn't already a real
        BaseException is stashed on self._raised_mojo_value and signaled via
        the fieldless MojoRaisedException marker, so it still flows through
        Python's real exception propagation; execute_TryStmt's
        _matches_exc_type reads _raised_mojo_value back for matching (see
        MojoRaisedException's docstring for why not a field on the
        exception object itself)."""
        if node.value is None:
            raise
        value = self.eval_expr(node.value)
        # A real exception CLASS (`raise StopIteration`) is raised the way
        # Python raises it — instantiated and propagated — not stashed as a
        # Mojo value, which left `raise StopIteration` unable to end a
        # user-defined `__next__` (the iterator protocol's exhaustion signal).
        if isinstance(value, BaseException) or (
                isinstance(value, type) and issubclass(value, BaseException)):
            raise value
        self._raised_mojo_value = value
        raise MojoRaisedException()

    def _matches_exc_type(self, e, exc_class):
        """Does exception `e` (as caught by execute_TryStmt's real Python
        `except Exception as e:`) match an `except exc_class:` clause?

        Python's own isinstance() already understands real exception-type
        hierarchies (ValueError, our BreakException/ReturnValue/MojoError,
        etc.) — used directly for those. It does *not* understand a
        MojoClass (a user-defined `struct MyError(BaseError):` exception
        type, itself just a MojoInstance, not a real Python type at all),
        so that case walks the *raised value's own* class's `.bases` chain
        instead, mirroring Python's subclass-catches-via-base semantics for
        this interpreter's own class model rather than Python's. `except
        Exception`/`except BaseException` must catch a
        MojoRaisedException-wrapped custom struct too, even though the
        wrapped value isn't a Python Exception instance itself — same
        universal-catch special case as gimple_codegen.py's compiled-path
        dispatch."""
        raised_value = self._raised_mojo_value if isinstance(e, MojoRaisedException) else e
        if isinstance(exc_class, MojoClass):
            if isinstance(raised_value, MojoInstance):
                stack = [raised_value._mojo_class]
                seen = set()
                while stack:
                    c = stack.pop()
                    if id(c) in seen:
                        continue
                    seen.add(id(c))
                    if c is exc_class:
                        return True
                    stack.extend(c.bases)
            return False
        if exc_class in (Exception, BaseException):
            return True
        try:
            return isinstance(raised_value, exc_class)
        except TypeError:
            return False

    def execute_TryStmt(self, node):
        """Execute try statement.

        The PEP 810 try-block context is held for the WHOLE statement (the
        same region CPython's symtable marks `ste_in_try_block`), so a mode
        'all' import in a handler/else/finally is eager too.
        """
        self._try_depth += 1
        try:
            return self._execute_try_stmt_inner(node)
        finally:
            self._try_depth -= 1

    def _execute_try_stmt_inner(self, node):
        """execute_TryStmt body — see that method's docstring."""
        try:
            for stmt in node.body:
                self.execute(stmt)
        except (ReturnValue, BreakException, ContinueException):
            # These are the interpreter's own control-flow signals for
            # `return`/`break`/`continue` (implemented as Exception
            # subclasses so they can unwind through execute()), not values
            # raised by the interpreted program. A bare `except Exception`
            # (or `except:`) in Mojo source sitting around a `return` must
            # let it keep propagating to the enclosing function/loop instead
            # of swallowing it as a caught exception — otherwise `return`
            # inside a try block silently turns into "an exception was
            # raised with the return value as its message".
            raise
        except Exception as e:
            if node.handlers:
                handled = False
                bound_value = self._raised_mojo_value if isinstance(e, MojoRaisedException) else e
                for handler in node.handlers:
                    exc_type = handler.exc_type
                    handler_body = handler.body
                    # exc_type can be None (catch all), a string (exc name), or an expression
                    should_handle = False
                    if exc_type is None:
                        should_handle = True
                    elif isinstance(exc_type, str):
                        # If exc_type is a string, look it up in the scope
                        try:
                            exc_class = self.scope.get(exc_type)
                            should_handle = self._matches_exc_type(e, exc_class)
                        except NameError:
                            should_handle = False
                    elif isinstance(exc_type, list):
                        # `except (A, B):` — fire_compiler.py's _parse_try
                        # stores a parenthesized exception tuple as a plain
                        # list of dotted-name strings, not an AST node (see
                        # its own comment: "codegen ORs the tag match across
                        # every type in the tuple"). Falling through to the
                        # `eval_expr` branch below tried to dispatch on a raw
                        # Python list, raising "No handler for list" — hit by
                        # any `except (ImportError, Exception):`-style
                        # handler (mojolib BUG-2026-032).
                        for name in exc_type:
                            try:
                                exc_class = self.scope.get(name)
                            except NameError:
                                continue
                            if self._matches_exc_type(e, exc_class):
                                should_handle = True
                                break
                    else:
                        # Otherwise evaluate it as an expression
                        try:
                            exc_class = self.eval_expr(exc_type)
                            should_handle = self._matches_exc_type(e, exc_class)
                        except NameError:
                            should_handle = False

                    if should_handle:
                        # Bind exception to variable if handler has a name
                        if handler.name:
                            old_val = None
                            had_old = handler.name in self.scope.vars
                            if had_old:
                                old_val = self.scope.vars[handler.name]
                            self.scope.define(handler.name, bound_value)

                        for stmt in handler_body:
                            self.execute(stmt)

                        # Restore old value if it existed
                        if handler.name:
                            if had_old:
                                self.scope.vars[handler.name] = old_val
                            else:
                                del self.scope.vars[handler.name]

                        handled = True
                        break
                if not handled:
                    raise
            else:
                raise
        finally:
            if node.finally_body:
                for stmt in node.finally_body:
                    self.execute(stmt)
        return None

    # Expression evaluation

    def eval_expr(self, expr):
        """Evaluate an expression."""
        if expr is None:
            return None

        method_name = f'eval_{type(expr).__name__}'
        method = getattr(self, method_name, None)

        if method is None:
            raise NotImplementedError(f"{self._loc(expr)}No handler for {type(expr).__name__}")

        return method(expr)

    def eval_FunctionType(self, expr):
        """A comptime function-type alias survives as a signature node.
        At runtime it cannot be evaluated, but that's okay for the regression
        test which only needs the alias to be something other than _comptime_expr.
        """
        return expr  # Return the node itself as a value

    def eval_WalrusExpr(self, expr):
        """Walrus `(name := value)`: evaluate value, bind name in the current
        scope, and return the value (was "No handler for WalrusExpr" — hit by
        _pyrepl/trace.py)."""
        value = self.eval_expr(expr.value)
        self.scope.define(expr.name, value)
        return value

    def eval_LambdaExpr(self, expr):
        """`lambda <params>: <expr>` — an anonymous function. Returns a
        MojoFunction whose body is the single statement `return <expr>` and
        whose closure scope is the scope in effect where the lambda appears,
        so the body can read enclosing locals just like a nested `def`.
        Callable through the exact same eval_CallExpr/invoke path as any
        other MojoFunction (was "No handler for LambdaExpr" — the compiled
        path's `_lower_LambdaExpr` instead lifts the lambda to a named
        function; a MojoFunction is this dialect's runtime equivalent).

        Lambda params are `(name, default_expr)` pairs (see fire_compiler.py's
        lambda parser) — names come from `_extract_param_names`, defaults are
        passed through as raw expression nodes and evaluated lazily by
        `_invoke` exactly like a `def`'s defaults."""
        params = self._extract_param_names(expr)
        body = [N.ReturnStmt(value=expr.body)]
        defaults = [(p[0], p[1]) for p in expr.params if p[1] is not None]
        return MojoFunction('<lambda>', params, body, self.scope,
                            param_defaults=defaults or None, interpreter=self)

    def _current_yield_fn(self, expr):
        """The `yield_fn` of the generator/coroutine whose body is
        currently running on THIS OS thread — see
        MojoGeneratorObject/MojoCoroutine/_ThreadedGenerator. `None` means
        eval_YieldExpr/eval_YieldFromExpr/eval_AwaitExpr is somehow running
        outside any generator/coroutine body, which fire_compiler.py's
        parser-level `is_generator`/`yield_bearing_node_ids` detection
        (Milestone 1) and `is_async` detection (Milestone 3a) should make
        unreachable in practice — a plain SyntaxError-style message rather
        than an obscure AttributeError if it ever is. Deliberately shared
        by both `yield` and `await` (Milestone 3b): both suspend "whichever
        generator/coroutine body is running on this thread" via the exact
        same `_ThreadedGenerator`-backed channel, and only one of
        {a generator body, a coroutine body} ever runs on a given worker
        thread at a time, so there's no ambiguity in reusing one TLS slot
        for both."""
        fn = getattr(self._gen_tls, 'yield_fn', None)
        if fn is None:
            raise SyntaxError(f"{self._loc(expr)}'yield'/'await' outside a generator/coroutine function")
        return fn

    def eval_YieldExpr(self, expr):
        """`yield` / `yield expr`. Suspends the CURRENT thread (this Mojo
        generator's own dedicated worker thread — see MojoGeneratorObject)
        by calling that generator's `yield_fn`, which blocks until the
        generator is resumed via `.send()`/`.__next__()`/`.throw()`, and
        returns whatever value the resumer passed in (None for a plain
        `next()`)."""
        value = self.eval_expr(expr.value) if expr.value is not None else None
        return self._current_yield_fn(expr)(value)

    def eval_YieldFromExpr(self, expr):
        """`yield from <expr>` — delegating yield. If the delegated source
        is itself another Mojo generator, drive it via its own `.send()`/
        `.throw()`/`.close()` protocol so its `MojoGeneratorObject.
        return_value` (a Mojo `return value` inside the delegate; see that
        field's docstring for why the value is read from there rather than
        `StopIteration.value`/`.args`) correctly becomes this expression's
        own value, and a `.throw()`/`.close()` sent to THIS (outer)
        generator is forwarded into the delegate before propagating —
        matching real Python `yield from` semantics for a generator source.
        A plain (non-generator) iterable falls back to a manual loop with
        no `.send()` forwarding and no return value, also matching real
        Python."""
        source = self.eval_expr(expr.value)
        yield_fn = self._current_yield_fn(expr)
        if not isinstance(source, MojoGeneratorObject):
            for item in source:
                yield_fn(item)
            return None
        sent = None
        while True:
            try:
                value = source.send(sent)
            except StopIteration:
                return source.return_value
            try:
                sent = yield_fn(value)
            except GeneratorExit:
                source.close()
                raise
            except BaseException as e:
                try:
                    value = source.throw(e)
                except StopIteration:
                    return source.return_value
                sent = yield_fn(value)

    def eval_AwaitExpr(self, expr):
        """`await <expr>` — Milestone 3b. Evaluates the awaited expression,
        then drives it via `_RealAwaitStep` regardless of what kind of
        awaitable it turned out to be: a `MojoCoroutine` (Mojo-await-Mojo),
        a real native coroutine/Task/Future (real asyncio interop — e.g.
        `await asyncio.sleep(...)`), or anything else implementing
        `__await__`, matching real Python `await`'s own actual protocol
        (bytecode-level, not type-based — see
        INTERP_generator_yield_entirely_unimplemented's Milestone
        3b report for why this is genuinely real-asyncio-compatible).

        This method itself runs on the current Mojo coroutine's OWN worker
        thread (same as `eval_YieldExpr` for a generator's worker thread —
        see `_current_yield_fn`). It does NOT step the real awaitable
        itself — real asyncio internals like `asyncio.sleep` call
        `get_running_loop()`, which is thread-affine and would raise
        `RuntimeError: no running event loop` off this worker thread
        (confirmed empirically). Instead it hands a `_RealAwaitStep`
        wrapping the awaitable's own `__await__()` iterator to
        `yield_fn` (the same suspension channel `eval_YieldExpr` uses) —
        `_ThreadedGenerator._resume` recognizes that marker and does the
        actual stepping on whichever thread is legitimately driving THIS
        coroutine (the real event loop's thread, for a top-level `await`;
        another worker thread, for Mojo-await-Mojo), looping until the
        real awaitable is actually done, then delivers the final value (or
        propagates the real exception) back here as this call's ordinary
        return value/raised exception — the worker thread just blocks the
        whole time, exactly like a plain Mojo `yield` blocks waiting for
        `.send()`."""
        value = self.eval_expr(expr.value)
        if hasattr(value, '__await__'):
            it = value.__await__()
        elif hasattr(value, 'send') and hasattr(value, '__next__'):
            # Old-style (pre-3.5 @asyncio.coroutine-style) generator-based
            # awaitable, or a bare iterator — driveable the same way.
            it = value
        else:
            raise TypeError(f"{self._loc(expr)}object {value!r} is not awaitable")
        yield_fn = self._current_yield_fn(expr)
        return yield_fn(_RealAwaitStep(it))

    def eval_EllipsisLiteral(self, expr):
        """The `...` literal — Python's Ellipsis singleton (was "No handler for
        EllipsisLiteral" — hit by tomllib/_types.py)."""
        return Ellipsis

    def eval_DottedLiteral(self, expr):
        """A dot-relative value reference (`.always`, `.uint64`)."""
        # Try to resolve as a variant/enum case
        try:
            # Look up in scope for common enum/variant constructors
            name = expr.path
            # Try to find as attribute of known types or just return a marker
            # For Optional/Some/None patterns, try to construct
            if name in ('Some', 'None'):
                # Return a simple object representing the variant
                class Variant:
                    def __init__(self, name, *args):
                        self._name = name
                        self.args = args
                    def __repr__(self):
                        return f'.{name}{args}'
                # But we need to know if it's Some with args - this is tricky
                # For pattern matching, return a callable or special marker
                if name == 'Some':
                    def Some(*args):
                        obj = object.__new__(type('Some', (), {}))
                        obj._is_some = True
                        obj._value = args[0] if args else None
                        return obj
                    return Some
                elif name == 'None':
                    obj = object.__new__(type('None', (), {}))
                    obj._is_none = True
                    return obj
            # Try to look up as a global
            try:
                return self.scope.get(name)
            except Exception:
                pass
        except Exception:
            pass
        raise NotImplementedError(
            f"{self._loc(expr)}cannot resolve the dot-relative value "
            f"'.{expr.path}': it names a variant of a type this interpreter "
            f"does not infer, and the source omits which type that is")

    def eval_IdentExpr(self, expr):
        """Evaluate identifier."""
        if expr.name == 'super':
            # `super` is only real Python-style base-class magic when
            # nothing in scope actually shadows it. Real Python gives
            # `super` no keyword status at all, so a user-defined struct
            # literally named `super` (see CPython's own test_super.py,
            # which does exactly this) must resolve to that ordinary
            # binding instead — matching real Python's name-shadowing
            # semantics rather than this dialect's `super()` base-class
            # sugar. Only fall back to the magic behavior when `super`
            # isn't bound to anything in the current scope chain.
            try:
                return self.scope.get(expr.name)
            except NameError:
                return self._eval_super(expr)
        if expr.name == 'Self':
            return self._resolve_Self(expr)
        if expr.name.startswith('`'):
            return expr.name
        try:
            return self.scope.get(expr.name)
        except NameError:
            # Re-raise with the source location, tagged like the original:
            # scope.get raises through _tag_name_error (name/candidates/
            # self_obj), and this new exception must carry the same fields
            # for CPython 3.15's print-time NameError suggestion.
            raise _tag_name_error(
                NameError(f"{self._loc(expr)}name '{expr.name}' is not defined"),
                self.scope, expr.name)

    def _resolve_Self(self, expr):
        """Resolve Self to the current struct type (when inside a struct method)."""
        try:
            self_val = self.scope.get('self')
            if isinstance(self_val, MojoInstance):
                return self_val._mojo_class
        except NameError:
            pass
        return _MojoSelfType()

    def _eval_super(self, expr):
        """Split out of eval_IdentExpr: returning a `_MojoSuper` instance
        from the same function as the plain `self.scope.get(expr.name)`
        path corrupted the self-hosted compiler's type inference for
        `Scope.get` elsewhere (two incompatible return types out of one
        function). Keeping the `_MojoSuper`-returning branch in its own
        function avoids that."""
        self_val = self.scope.get('self')
        if isinstance(self_val, MojoInstance):
            cls = self_val._mojo_class
            if cls.bases:
                return _MojoSuper(cls.bases[0], self_val, self)
        raise NameError(f"{self._loc(expr)}'super' used outside of struct method with a base class")

    def eval_IntLiteral(self, expr):
        """Evaluate integer literal."""
        return expr.value

    def eval_FloatLiteral(self, expr):
        """Evaluate float literal."""
        return expr.value

    def eval_ImagLiteral(self, expr):
        """Evaluate a Python-style imaginary-number literal (`0j`, `1.5j`).
        `expr.value` is the magnitude before the implicit multiply-by-i
        (e.g. 2.5 for `2.5j`), so the literal itself is purely imaginary:
        `2.5j` -> MojoComplex(real=0.0, imag=2.5)."""
        return MojoComplex(0.0, expr.value)

    def eval_StringLiteral(self, expr):
        """Evaluate string literal."""
        value = expr.value
        if getattr(expr, 'is_bytes', False):
            # A `b'...'` literal is a `bytes` object, an int SEQUENCE — not a
            # text string. Boxing it as a `MojoString` made `for x in b"ab"`
            # yield `'a'`/`'b'` and `list(b"cd")` yield `['c', 'd']` where
            # CPython (and the compiled path, see emit_loops.py's `_gen_for_
            # bytes`) yields `97`/`98` and `[99, 100]`. The parser has already
            # decoded the literal's escapes to one character per output byte
            # (see fire_compiler.py's `_decode_bytes_literal`), so latin-1
            # encodes it back to exactly those bytes.
            return expr.value.encode('latin-1')
        # `expr.is_interpolated`, and NOT "does the value start with `f"`/`t`".
        # An ordinary literal's value is its BODY and a body may begin with any
        # two characters, so that test read `s = 'f"n"'` as an f-string and
        # printed `n` where CPython prints `f"n"`; the compiled path did the
        # same and the formal path refused the program. The parser decides the
        # question from the SOURCE TOKEN (`_raw_string_is_ftstring`) and records
        # it in the node, which is the only place the two spellings differ.
        # It also settles the UPPERCASE spellings, which this test never matched
        # at all: `F"n={n}"` interpolated on the compiled path and printed its
        # own source text here.
        #
        # Mojo's `t"..."` template-string literal shares f-string's `{expr}`/
        # `{{`-escape interpolation syntax (see fire_compiler.py's
        # _strip_string_prefix_and_quotes) — real Mojo turns it into a
        # Template-like object, but every use we've seen immediately feeds it
        # to `String(...)` anyway, so evaluating it as a plain f-string (via
        # Python's own, unrelated PEP 750 t-strings would produce a
        # string.templatelib.Template object instead of a str) gets the same
        # final value without needing to model an intermediate Template type.
        if getattr(expr, 'is_interpolated', False):
            body = value[1:]  # strip the leading f/t prefix
            # Detect a triple-quoted body without ever writing a literal
            # triple-quote substring in this file's own source: fire_compiler's
            # replace_multiline_strings does a whole-source, nesting-unaware
            # sweep for opening/closing """ or ''' runs, so a literal '"""'
            # constant here would itself get mistaken for the start of a new
            # multi-line string and swallow everything up to the next triple-
            # quote sequence found anywhere later in this file.
            triple_quote_len = 3
            is_triple = (len(body) >= triple_quote_len
                         and body[0] == body[1] == body[2]
                         and (body[0] == chr(34) or body[0] == chr(39)))
            if is_triple:
                body = body[3:-3]
            else:
                body = body[1:-1]
            try:
                result = self._format_fstring_body(body)
            except Exception:
                # A malformed/unsupported {expr} shouldn't crash the whole
                # program — fall back to the raw literal, same graceful-
                # degradation behavior this already had.
                return MojoString(value)
            return MojoString(result)
        return MojoString(N.decoded_literal(expr))

    def _format_fstring_body(self, body: str) -> str:
        # Parse an f-string body (prefix/quotes already stripped) into its
        # final string: literal text interspersed with {expr} groups, each
        # parsed and evaluated through this interpreters own tokenizer and
        # parser/eval_expr, not Pythons eval() on the whole f-string, which
        # bypasses this interpreters own operator/dispatch semantics
        # entirely. Handles {{ / }} escapes and !conversion / :format_spec
        # suffixes the same way CPythons own f-strings do.
        out = []
        i, n = 0, len(body)
        while i < n:
            c = body[i]
            if c == '{':
                if i + 1 < n and body[i + 1] == '{':
                    out.append('{')
                    i += 2
                    continue
                j = self._find_fstring_field_end(body, i + 1)
                out.append(self._eval_fstring_field(body[i + 1:j]))
                i = j + 1
            elif c == '}':
                if i + 1 < n and body[i + 1] == '}':
                    out.append('}')
                    i += 2
                    continue
                out.append('}')  # stray '}' — permissive, don't raise
                i += 1
            else:
                out.append(c)
                i += 1
        return ''.join(out)

    def _find_fstring_field_end(self, body: str, start: int) -> int:
        # Index of the closing brace for an f-string {expr} field that
        # began at start (just past the opening brace), tracking nested
        # brackets/parens/braces and quoted strings so a dict-subscript or
        # nested-brace expression does not close early on an inner quote
        # or brace.
        depth = 1
        in_str = None
        j = start
        n = len(body)
        while j < n:
            cj = body[j]
            if in_str:
                if cj == '\\':
                    j += 2
                    continue
                if cj == in_str:
                    in_str = None
            elif cj == '"' or cj == "'":
                in_str = cj
            elif cj == '(' or cj == '[' or cj == '{':
                depth += 1
            elif cj == ')' or cj == ']' or cj == '}':
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        return n  # unterminated — treat the rest of the body as the field

    def _split_fstring_field(self, field: str):
        # Split a field's inner text into (expr_text, conversion, spec),
        # scanning for the top-level conversion/spec markers CPythons own
        # f-string grammar recognizes: top-level meaning outside any nested
        # bracket/quote, so a slice colon or dict-literal colon is not
        # mistaken for the format-spec separator. Mojo/Python has no
        # general prefix-bang operator (not is used instead), so any bare
        # bang in real expression text is always either part of a not-
        # equal comparison or the f-string conversion flag; checking that
        # the char after r/s/a is the field end or a colon distinguishes
        # them.
        depth = 0
        in_str = None
        i, n = 0, len(field)
        while i < n:
            c = field[i]
            if in_str:
                if c == '\\':
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            elif c == '"' or c == "'":
                in_str = c
            elif c == '(' or c == '[' or c == '{':
                depth += 1
            elif c == ')' or c == ']' or c == '}':
                depth -= 1
            elif depth == 0 and c == '!' and i + 1 < n and field[i + 1] in ('r', 's', 'a'):
                nxt = i + 2
                if nxt == n or field[nxt] == ':':
                    conv = field[i + 1]
                    spec = field[nxt + 1:] if nxt < n else None
                    return field[:i].strip(), conv, spec
            elif depth == 0 and c == ':':
                return field[:i].strip(), None, field[i + 1:]
            i += 1
        return field.strip(), None, None

    def _eval_fstring_field(self, field: str) -> str:
        # Evaluate one expr / expr!conv / expr:spec / expr!conv:spec field
        # (raw text between the outer braces, not including them). Uses
        # only repr/str plus this interpreters own string ops for the
        # conversion/spec step, not the ascii()/format() builtins: those
        # have no compiled-path runtime backing (undefined _ascii/_format
        # symbols at link time when this method itself gets self-hosted-
        # compiled), so they would work only under the Python interpreter
        # and silently fail once compiled.
        expr_text, conv, spec = self._split_fstring_field(field)
        value = self._eval_fstring_expr(expr_text)
        if conv == 'r' or conv == 'a':
            text = repr(value)
        else:
            text = str(value)
        if spec:
            text = self._apply_fstring_format_spec(text, spec)
        return text

    def _apply_fstring_format_spec(self, text: str, spec: str) -> str:
        # Minimal fill/align/width subset of the format-spec mini-language
        # (e.g. ">10", "<5", "^8", "05"), operating on the already-
        # stringified value rather than dispatching by numeric type -
        # covers the common alignment/padding use case without needing a
        # full numeric formatter.
        fill = ' '
        align = None
        i = 0
        if len(spec) >= 2 and (spec[1] == '<' or spec[1] == '>' or spec[1] == '^'):
            fill = spec[0]
            align = spec[1]
            i = 2
        elif len(spec) >= 1 and (spec[0] == '<' or spec[0] == '>' or spec[0] == '^'):
            align = spec[0]
            i = 1
        elif len(spec) >= 1 and spec[0] == '0':
            fill = '0'
            align = '>'
            i = 1
        width_digits = ''
        while i < len(spec) and spec[i] >= '0' and spec[i] <= '9':
            width_digits = width_digits + spec[i]
            i += 1
        if not width_digits:
            return text
        width = int(width_digits)
        pad = width - len(text)
        if pad <= 0:
            return text
        padding = ''
        p = 0
        while p < pad:
            padding = padding + fill
            p += 1
        if align == '<':
            return text + padding
        if align == '^':
            left = pad // 2
            right = pad - left
            left_pad = ''
            j = 0
            while j < left:
                left_pad = left_pad + fill
                j += 1
            right_pad = ''
            j = 0
            while j < right:
                right_pad = right_pad + fill
                j += 1
            return left_pad + text + right_pad
        return padding + text

    def _eval_fstring_expr(self, expr_text: str):
        # Parse and evaluate a single expression string through this
        # interpreters own tokenizer/parser/eval_expr, used for f-string
        # and t-string field interpolation. Deliberately not Pythons
        # eval(): that would evaluate Mojo-flavored expression syntax
        # using CPythons own operators/semantics directly, bypassing this
        # interpreters own dispatch (eval_BinaryOp, eval_CallExpr, etc.)
        # entirely.
        from fire_compiler import py_tokenize, Parser
        tokens = py_tokenize(expr_text)
        node = Parser(tokens)._parse_expr(0)
        return self.eval_expr(node)

    def eval_BoolLiteral(self, expr):
        """Evaluate boolean literal."""
        return expr.value

    def eval_NoneLiteral(self, expr):
        """Evaluate None literal."""
        return None

    @staticmethod
    def _spread_operand(node, op):
        """If `node` is a `*expr`/`**expr` spread marker (a UnaryOp with the
        given op, produced by `_parse_unary` for spreads inside collection
        displays — see fire_compiler.py's `_parse_unary` and
        `_parse_dict_or_set`/`_parse_dict_entry`), return the spread
        operand AST node; otherwise return None. Spreading isn't a real
        unary operation — there's no single value `*x` evaluates to outside
        a collection display — so the collection-literal evaluators below
        recognize and expand it directly rather than routing it through
        eval_UnaryOp (which correctly still errors on a bare `*x`/`**x`)."""
        if isinstance(node, N.UnaryOp) and node.op == op:
            return node.operand
        return None

    def eval_ListLiteral(self, expr):
        """Evaluate list literal, expanding any `*expr` spread elements
        (PEP 448 iterable unpacking, e.g. `[*a, *b]`) in place."""
        result = []
        for e in expr.elements:
            spread = self._spread_operand(e, "*")
            if spread is not None:
                result.extend(self.eval_expr(spread))
            else:
                result.append(self.eval_expr(e))
        return result

    def eval_DictLiteral(self, expr):
        """Evaluate dict literal, expanding any `**expr` spread pairs (PEP
        448 mapping unpacking, e.g. `{**a, **b}`). A spread pair is
        represented as `(UnaryOp(op='**', operand=<mapping expr>), None)` by
        the parser (see fire_compiler.py). Pairs are applied in source
        order, matching Python: a later spread or key overwrites an earlier
        one on key collision."""
        result = {}
        for key, value in expr.pairs:
            spread = self._spread_operand(key, "**") if value is None else None
            if spread is not None:
                result.update(self.eval_expr(spread))
            else:
                result[self.eval_expr(key)] = self.eval_expr(value)
        return result

    def eval_SetLiteral(self, expr):
        """Evaluate set literal, expanding any `*expr` spread elements
        (e.g. `{*a, *b}`) as a union into the resulting set."""
        result = set()
        for e in expr.elements:
            spread = self._spread_operand(e, "*")
            if spread is not None:
                result.update(self.eval_expr(spread))
            else:
                result.add(self.eval_expr(e))
        return result

    def eval_TupleLiteral(self, expr):
        """Evaluate tuple literal, expanding any `*expr` spread elements
        (e.g. `(*a, *b)`) in place."""
        result = []
        for e in expr.elements:
            spread = self._spread_operand(e, "*")
            if spread is not None:
                result.extend(self.eval_expr(spread))
            else:
                result.append(self.eval_expr(e))
        return tuple(result)

    @staticmethod
    def _wrap_int(v):
        if isinstance(v, int) and not isinstance(v, bool):
            return N._signed_int64(v)
        return v

    @staticmethod
    def _resolve_ambiguous_empty_braces(left, right):
        """Mojo's bare `{}` literal is polymorphic (empty Dict or empty Set,
        inferred from context); this interpreter always parses it as an empty
        dict (Python's default — see fire_compiler.py's `{}` handling). When
        one side of a set-algebra operator is already a real set, treat an
        empty-dict operand as the empty set Mojo would have inferred, instead
        of raising a TypeError Mojo code would never hit (`set() & {}`)."""
        if isinstance(left, set) and isinstance(right, dict) and not right:
            right = set()
        elif isinstance(right, set) and isinstance(left, dict) and not left:
            left = set()
        return left, right

    def eval_BinaryOp(self, expr):
        """Evaluate binary operation."""
        op = expr.op
        # 'and'/'or' must short-circuit — evaluating both operands
        # unconditionally like every other operator here breaks the
        # extremely common `guard and use_guarded_value` pattern (e.g.
        # `isinstance(x, FunctionDef) and x.name == 'main'`): the right
        # side would still run and raise (AttributeError: no `.name`) even
        # when the left side was falsy and specifically meant to prevent
        # that. Found via 3-levels-deep self-referential interpretation
        # (`fire.py run fire.py run fire.py help`) tripping over exactly
        # this pattern in the project's own source.
        if op == 'and':
            left = self.eval_expr(expr.left)
            return left if not left else self.eval_expr(expr.right)
        if op == 'or':
            left = self.eval_expr(expr.left)
            return left if left else self.eval_expr(expr.right)
        # `x as T` — Mojo-style cast. This interpreter is dynamically typed,
        # so there's no runtime conversion to perform: evaluate both sides
        # (the type name must still resolve, same as real Mojo's
        # type-checking would require) and hand back the original value.
        if op == 'as':
            left = self.eval_expr(expr.left)
            self.eval_expr(expr.right)
            return left

        left = self.eval_expr(expr.left)
        right = self.eval_expr(expr.right)
        return self._apply_binary_op(expr, op, left, right)

    def _apply_binary_op(self, expr, op, left, right):
        """Compute a binary operator's result from already-evaluated
        operands (everything except the short-circuiting 'and'/'or'/'as',
        handled directly in eval_BinaryOp before operands are evaluated).
        Factored out of eval_BinaryOp as its own named step for clarity."""
        if op in ('&', '|', '^', '-'):
            left, right = self._resolve_ambiguous_empty_braces(left, right)
        if op == '+':
            # str.__add__ already concatenates fine on its own, but returns
            # a plain `str`, losing MojoString's extra methods (see its
            # docstring) — reclaim that only for the pure-string case; any
            # other combination (e.g. a bare `str` + `Int`) still raises
            # the same TypeError it always did, matching real Mojo requiring
            # an explicit conversion instead of silently stringifying it.
            if isinstance(left, str) and isinstance(right, str):
                return MojoString(left + right)
            # An _AutoStubValue is the interpreter's graceful stand-in for an
            # unresolved symbol (missing/unshimmed import, unknown attribute).
            # It subclasses int, so `str + stub` would raise TypeError (can
            # only concatenate str, not "_AutoStubValue") — mojolib BUG-2026-029,
            # hit when the transpiler concatenates an unresolved value into a
            # string. Degrade gracefully instead, matching _AutoStubValue's
            # whole design: treat the unresolved operand as an empty string in
            # a string-concatenation context so the program keeps running.
            if isinstance(left, str) and isinstance(right, _AutoStubValue):
                return MojoString(left)
            if isinstance(left, _AutoStubValue) and isinstance(right, str):
                return MojoString(right)
            return self._wrap_int(left + right)
        elif op == '-': return self._wrap_int(left - right)
        elif op == '*': return self._wrap_int(left * right)
        elif op == '/':
            if isinstance(left, (str, MojoString)) and isinstance(right, (str, MojoString)):
                return MojoString(os.path.join(str(left), str(right)))
            # `_wrap_int` like every other arithmetic op above: a bare
            # `return left / right` emits `mojo_div_double` (double) into a
            # return slot the str branch types as `MojoString *` — gcc:
            # "makes pointer from ... double" (no double->pointer cast under
            # -fgimple). `_wrap_int` is a @staticmethod identity for non-int
            # (a `/` result is a float), so Python semantics are unchanged —
            # it only gives codegen a call whose result it can type as a word.
            return self._wrap_int(left / right)
        elif op == '//': return left // right
        elif op == '%': return left % right
        elif op == '**': return self._wrap_int(left ** right)
        elif op in _COMPARE_OPS: return self._apply_compare_op(op, left, right)
        elif op == '&': return self._wrap_int(left & right)
        elif op == '|': return self._wrap_int(left | right)
        elif op == '^': return self._wrap_int(left ^ right)
        elif op == '<<': return self._wrap_int(left << right)
        elif op == '>>': return left >> right
        else:
            raise NotImplementedError(f"{self._loc(expr)}Binary operator {op!r} not implemented")

    def _apply_compare_op(self, op: str, left, right):
        """Apply a single comparison-family operator to two already-evaluated
        operands. Factored out of eval_BinaryOp so eval_CompareChain (Python
        chained comparisons, `a < b < c`) can reuse the identical per-link
        semantics instead of re-deriving them — this is also where 'not in'
        got added: eval_BinaryOp's own operator table never had a case for
        it (only 'in'/'is'/'is not'), so a plain `x not in y` outside any
        chain silently raised NotImplementedError before this."""
        if op == '==': return left == right
        elif op == '!=': return left != right
        elif op == '<': return left < right
        elif op == '>': return left > right
        elif op == '<=': return left <= right
        elif op == '>=': return left >= right
        elif op == 'in': return left in right
        elif op == 'not in': return left not in right
        elif op == 'is': return left is right
        elif op == 'is not': return left is not right
        else:
            raise NotImplementedError(f"Comparison operator {op!r} not implemented")

    def eval_CompareChain(self, expr):
        """Python-style chained comparison `a < b < c`: each operand is
        evaluated exactly once, left-to-right; the whole expression
        short-circuits to False (without evaluating any remaining operands)
        the moment one `operands[i] ops[i] operands[i+1]` link fails, and is
        True only if every link holds — `(a < b) and (b < c)`, never `(a <
        b) < c`. See CHAINED_COMPARISON_WRONG_RESULT."""
        left = self.eval_expr(expr.operands[0])
        for op, operand_expr in zip(expr.ops, expr.operands[1:]):
            right = self.eval_expr(operand_expr)
            if not self._apply_compare_op(op, left, right):
                return False
            left = right
        return True

    def eval_UnaryOp(self, expr):
        """Evaluate unary operation."""
        operand = self.eval_expr(expr.operand)
        return self._apply_unary_op(expr, operand)

    def _apply_unary_op(self, expr, operand):
        """Compute a unary operator's result from an already-evaluated
        operand. Factored out of eval_UnaryOp as its own named step."""
        op = expr.op
        if op == '-': return self._wrap_int(-operand)
        elif op == '+': return +operand
        elif op == '~': return self._wrap_int(~operand)
        elif op == '^':
            return operand
        elif op == 'not': return not operand
        else:
            raise NotImplementedError(f"{self._loc(expr)}Unary operator {op} not implemented")

    def eval_CallExpr(self, expr):
        """Evaluate function call."""
        func = self.eval_expr(expr.func)
        # Call-site unpacking: `g(*args)` / `g(**opts)`. fire_compiler.py's
        # LPAREN arg-list parser lets `_parse_unary` wrap a starred argument
        # expression in UnaryOp(op='*'/'**', operand=...) instead of
        # consuming the star itself, so the marker survives into the AST.
        # Without this, the starred expression's *value* (e.g. the whole
        # list) got appended as a single ordinary positional argument,
        # silently binding to just the callee's first parameter and leaving
        # the rest unbound instead of splicing the iterable's elements (or
        # the mapping's items) into the flat args/kwargs actually passed.
        args = []
        kwargs = {}
        for arg in expr.args:
            if isinstance(arg, N.UnaryOp) and arg.op == '*':
                args.extend(self.eval_expr(arg.operand))
            elif isinstance(arg, N.UnaryOp) and arg.op == '**':
                kwargs.update(self.eval_expr(arg.operand))
            else:
                args.append(self.eval_expr(arg))

        # Evaluate keyword arguments. CallExpr stores these as `kwargs`, a
        # list of (name, expr) tuples (see fire_compiler.py's CallExpr and
        # ast_nodes.py) — not a `keywords` dict. The old attribute-name
        # mismatch meant `hasattr(expr, 'keywords')` was always False, so
        # every keyword argument to every call was silently dropped in
        # favor of the callee's default value.
        if getattr(expr, 'kwargs', None):
            kwargs = {k: self.eval_expr(v) for k, v in expr.kwargs}

        if isinstance(func, MojoOverloadSet):
            try:
                return self.invoke(func, *args, **kwargs)
            except _NoOverloadMatch as e:
                raise TypeError(f"{self._loc(expr)}{e}")
        return self.invoke(func, *args, **kwargs)

    def invoke(self, func, *args, **kwargs):
        """Call a value that may be a Mojo-defined function (which needs the
        interpreter threaded through as its first argument) or a plain Python
        callable — shared by eval_CallExpr and builtins like map[func] that
        need to invoke a callee passed to them at runtime.

        Milestone 3b: a plain Python callable invoked from inside a
        coroutine's own worker thread gets bounced through
        `_RealThreadCall` instead of called directly — some real asyncio
        functions (`asyncio.gather`, `ensure_future`, `create_task`, ...)
        touch the running event loop the instant they're CALLED, not just
        when later awaited, and the event loop is thread-affine (see
        `_RealThreadCall`'s docstring for the empirically-confirmed
        failure this fixes). Gated on the `is_coroutine` TLS flag
        (MojoCoroutine only) so plain generators are entirely unaffected."""
        if isinstance(func, (MojoFunction, MojoOverloadSet, _MojoBoundComptimeFunction)):
            return func(self, *args, **kwargs)
        args = _mojo_builtin_args(func, args)
        tls = self._gen_tls
        if hasattr(tls, 'is_coroutine') and tls.is_coroutine:
            yield_fn = getattr(tls, 'yield_fn') if hasattr(tls, 'yield_fn') else None
            if yield_fn is not None:
                return yield_fn(_RealThreadCall(func, args, kwargs))
        return func(*args, **kwargs)

    def eval_MemberExpr(self, expr):
        """Evaluate member access."""
        obj = self.eval_expr(expr.obj)
        return self._eval_member_of(expr, obj)

    def _eval_member_of(self, expr, obj):
        """Resolve `expr.member` against an already-evaluated `obj`.
        Factored out of eval_MemberExpr as its own named step."""
        if isinstance(obj, MojoInstance):
            if expr.member in obj.__dict__:
                return obj.__dict__[expr.member]
            method = obj._mojo_class.methods.get(expr.member)
            if method is not None:
                if expr.member in obj._mojo_class.static_methods:
                    # A `@staticmethod` reached THROUGH AN INSTANCE still
                    # binds nothing — `K().s(1)` is `K.s(1)`. The
                    # `static_methods` set was only consulted on the CLASS
                    # lookup path (`MojoClass.__getattr__`), so this branch
                    # wrapped one in a BoundMethod and passed the instance as
                    # a first positional argument: `K().s(1)` bound the
                    # instance to `s`'s first parameter and then failed on
                    # `instance + int`.
                    return method
                if expr.member in obj._mojo_class.class_methods:
                    # `instance.classmethod(...)` — the receiver is still the
                    # CLASS, not the instance (Python's own rule).
                    return BoundClassMethod(method, obj._mojo_class, self)
                return BoundMethod(method, obj, self)
            if expr.member in obj._mojo_class.comptime_aliases:
                return obj._mojo_class.comptime_aliases[expr.member]
            raise _tag_attribute_error(
                AttributeError(f"{self._loc(expr)}'{obj._mojo_class.name}' object has no attribute '{expr.member}'"),
                obj, expr.member, _frame_self(self))
        if not hasattr(obj, expr.member):
            raise _tag_attribute_error(
                AttributeError(f"{self._loc(expr)}'{type(obj).__name__}' object has no attribute '{expr.member}'"),
                obj, expr.member, _frame_self(self))
        return getattr(obj, expr.member)

    def eval_SubscriptExpr(self, expr):
        """Evaluate subscript access."""
        obj = self.eval_expr(expr.obj)
        # A KEYWORD bracket (`f[T=Int, y=5]`, `platform_map[T=Int, "O_APPEND",
        # linux=0x400]()`) keeps its elements in `attrs` as (name, value)
        # pairs and leaves `index` as the empty-subscript placeholder
        # IntLiteral(0) — see fire_compiler.py's "keyword-style bracket"
        # branch. Indexing that placeholder is not a subscript at all: it
        # bound the callee's FIRST comptime parameter to 0 and dropped every
        # bracketed argument, so `f[T=Int, y=5]()` returned a value computed
        # from `y`'s default (and `f[T=Int]` raised `NameError: T` from the
        # key `T` being evaluated in the enclosing scope). Bind the
        # comptime parameters instead — the same model
        # mojo/backend_gimple/emit_calls.py's `_kw_bracket`/`elems` split
        # uses for the compiled path, so both engines answer alike.
        _attrs = getattr(expr, 'attrs', None)
        if _attrs:
            _bound = self._bind_bracket_comptime(obj, _attrs, expr)
            if _bound is not None:
                return _bound
        idx = self.eval_expr(expr.index)
        if not hasattr(obj, '__getitem__'):
            if hasattr(obj, '__call__'):
                return obj
            raise TypeError(f"{type(obj).__name__} object is not subscriptable")
        return obj[idx]

    def _bind_bracket_comptime(self, obj, attrs, node):
        """`f[...]` with keyword-bracket `attrs`: bind `obj`'s declared
        comptime parameters and return the callable, or None when `obj` has
        no comptime parameter list to bind (the caller then keeps its own
        subscript path — a bound method reached as `obj.m[k=v](...)` is
        handled by `BoundMethod.__getitem__`, which answers the callable
        itself).

        The two bracket spellings are read exactly as the parser produced
        them and as emit_calls.py reads them: a `(None, value)` pair is
        POSITIONAL (the parser's spelling for a literal or a call in the
        bracket — `f[T=Int, "O_APPEND"]`), a bare `name = value` pair binds
        that parameter BY NAME, and a bare NAME with no `=` (which the
        parser keeps under its own name) binds by name too. Positionals fill
        the remaining parameters in declaration order, which is what makes
        `platform_map[T=Int, "O_APPEND", linux=..., macos=...]()` —
        `operation` sitting between two keyword parameters — land on
        `operation`.

        A parameter with neither a supplied value nor a declared default is
        an honest TypeError naming it, not a silent None: the bracket is
        the ONLY place its value can come from.

        `obj` is the callee VALUE, so it is also a method receiver
        (`obj.body[f_key=show_k]()`); its declared parameters live on
        `bound_func` there, and the bound value it produces is one that
        keeps the receiver.
        """
        decl = obj
        if not getattr(decl, 'comptime_params', None):
            decl = getattr(obj, 'bound_func', None)
        cps = getattr(decl, 'comptime_params', None)
        if not cps:
            return None
        kws = {}
        poss = []
        for pair in attrs:
            nm = pair[0]
            if nm is None:
                poss.append(pair[1])
            else:
                kws[nm] = pair[1]
        dflts = getattr(decl, 'comptime_param_defaults', None) or {}
        bindings = {}
        pos_i = 0
        for cp in cps:
            given = None
            if cp in kws:
                given = kws[cp]
            elif pos_i < len(poss):
                given = poss[pos_i]
                pos_i += 1
            if given is not None:
                bindings[cp] = self.eval_expr(given)
            elif cp not in dflts:
                raise TypeError(
                    f"{self._loc(node)}comptime parameter '{cp}' is neither "
                    f"given in the bracket nor has a default")
        if decl is not obj:
            return _MojoBoundComptimeReceiver(obj, bindings)
        return _MojoBoundComptimeFunction(obj, bindings)

    def eval_SliceExpr(self, expr):
        """Evaluate slice expression."""
        obj = self.eval_expr(expr.obj)
        start = self.eval_expr(expr.start) if expr.start else None
        stop = self.eval_expr(expr.stop) if expr.stop else None
        step = self.eval_expr(expr.step) if expr.step else None
        return obj[start:stop:step]

    def eval_TernaryExpr(self, expr):
        """Evaluate ternary conditional."""
        condition = self.eval_expr(expr.condition)
        if condition:
            return self.eval_expr(expr.then_val)
        else:
            return self.eval_expr(expr.else_val)

    def eval_TupleExpr(self, expr):
        """Evaluate tuple expression (fire_compiler naming; TupleExpr is
        TupleLiteral — see fire_compiler.py's `TupleLiteral = TupleExpr`)."""
        return self.eval_TupleLiteral(expr)

    # Aliases for fire_compiler node types (ListExpr, DictExpr, SetExpr)
    def eval_ListExpr(self, expr):
        """Evaluate list expression (fire_compiler naming)."""
        return self.eval_ListLiteral(expr)

    def eval_DictExpr(self, expr):
        """Evaluate dict expression (fire_compiler naming)."""
        return self.eval_DictLiteral(expr)

    def eval_SetExpr(self, expr):
        """Evaluate set expression (fire_compiler naming)."""
        return self.eval_SetLiteral(expr)

    def _bind_comprehension_target(self, target_str, value):
        """A comprehension/generator `for` clause's target is a plain string
        (possibly comma-joined for tuple unpacking, e.g. "a, b" or "(a, b)"
        — see fire_compiler.py's _parse_generator_target), not an Expr node.
        Mirrors execute-VarDecl's handling of the same comma-joined-string
        representation for `var a, b = ...`.

        Whether the pattern UNPACKS at all is `for_target_is_tuple`, the one
        reader of the difference between `(a,)` and `(a)` — see
        fire_compiler.py's "Unpacking-target representation" section. Reading
        it here by hand is what made `for (a,) in [(1,), (2,)]` bind the whole
        item to `a` and print `1` where CPython prints `(1,)`: the parser used
        to spell both targets identically, so "is there a comma?" could not
        tell them apart. Slot splitting is the shared bracket-aware
        `target_slots` for the same reason a nested target must not be torn
        into `(b` / `c)` — and for the same reason it drops the empty slot a
        1-tuple's trailing comma leaves, which is what `for (a,) in [(1,)]`
        binds `a` to `1` rather than to `(1,)`.

        One element of the comma-list may be starred (e.g. "a, *rest" or
        "*rest, a, b" — see fire_compiler.py's _parse_for_target), matching
        Python's extended-unpacking-in-for-target semantics: the starred
        name collects whatever's left over after the non-starred names on
        either side of it have each claimed one value.

        One element may also be a dotted attribute-access expression
        (e.g. "st.lineno", possibly chained "a.b.c" — see fire_compiler.py's
        _parse_for_target), which SETS an existing object's attribute each
        iteration instead of binding a fresh local; see _bind_single_target."""
        if not N.for_target_is_tuple(target_str):
            # `for (a) in ...` — a parenthesised single NAME. The parens are
            # redundant grouping, so the name bound is what is inside them;
            # binding the string `"(a)"` would define a variable literally
            # called `(a)`.
            self._bind_single_target(
                N.for_target_single_name(target_str.strip()), value)
            return
        t = target_str.strip()
        inner = N._target_group_inner(t)
        if inner is not None:
            t = inner
        names = N.target_slots(t)
        if names:
            # CPython's UNPACK_EX: an item that is a SEQUENCE is unpacked into
            # its elements, whatever it is made of — a list, a tuple, and a
            # `str` (into 1-character strings) or `bytes` (into ints, because
            # that is what indexing a bytes yields). `_unpack_source` is that
            # rule and the refusal that goes with it, spelled once for both
            # binders; see its own docstring for the three measured facts.
            #
            # The `str`/`bytes` exemption that used to be here made the whole
            # dict-key family wrong: iterating a dict yields its KEYS, a key is
            # a `str`, and `for k, *vs in {"abc": 1}` therefore binds the WHOLE
            # key "abc" to `k` and hands `vs` an empty list, where CPython
            # gives `k == 'a'` and `vs == ['b', 'c']`. The compiled path
            # refused the shape rather than disagree with this (see
            # mojo/backend_gimple/emit_loops.py's `_gen_for_dict`, which now
            # lowers it) so the two engines could be compared at all.
            values = self._unpack_source(value)
            # Plain loop, not next()+genexpr: this file is itself compiled by
            # this project's self-hosting gimple_codegen.py, which has no
            # runtime `next()` builtin -- that emitted an undefined-symbol
            # link error ("_next", referenced from Interpreter__bind_
            # comprehension_target) rather than a compile-time diagnostic.
            star_idx = None
            for i, n in enumerate(names):
                if n.startswith('*'):
                    star_idx = i
                    break
            if star_idx is None:
                self._check_exact_arity(values, names, value)
                for n, v in zip(names, values):
                    # A NESTED group slot — `for (i, (j,)) in pairs` — is
                    # itself a pattern, not a variable name, so it recurses
                    # with that slot's value. Binding it through
                    # `_bind_single_target` defined a local literally called
                    # `"(j,)"` and the body's `j` was then a NameError;
                    # flattening instead (what the codegen's
                    # `for_target_names` does) would bind `j` to the OUTER
                    # element. Recursing is what CPython means and what both
                    # engines now do.
                    if N.for_target_is_tuple(n):
                        self._bind_comprehension_target(n, v)
                    else:
                        self._bind_single_target(n, v)
            else:
                before, after = names[:star_idx], names[star_idx + 1:]
                star_name = names[star_idx][1:]
                n_before, n_after = len(before), len(after)
                if len(values) < n_before + n_after:
                    raise ValueError(
                        f"Cannot unpack {len(values)} values into {len(names)} "
                        f"targets (starred target needs at least {n_before + n_after})")
                for n, v in zip(before, values[:n_before]):
                    self._bind_single_target(n, v)
                self.scope.define(star_name, values[n_before:len(values) - n_after])
                for n, v in zip(after, values[len(values) - n_after:]):
                    self._bind_single_target(n, v)

    def _unpack_source(self, value):
        """`value` as the list a SEQUENCE target unpacks, or CPython's refusal.

        **The whole of `UNPACK_SEQUENCE` for this path, and the reason it is one
        function rather than a comprehension at two call sites.** Three facts,
        each measured against CPython 3.14 rather than argued:

        * **A `str` IS unpacked, into one-character strings.** Iterating a
          `dict` yields its KEYS, so `for k, *vs in {"abc": 1}` gives the target
          the key `"abc"` and CPython prints `a ['b', 'c']`. This function used
          to exempt `str` (and `bytes`) and hand the target the whole key, so
          the interpreter printed `abc []` — a wrong answer on the shape this
          project's own dict iteration produces, and a SILENT one: the program
          ran and printed something plausible. Same for `for k, v in {"ab": 1}`,
          which binds `('a', 'b')` in CPython and used to bind `k` alone and
          leave `v` undefined.
        * **A non-iterable item is a `TypeError`, not a one-element list.**
          `for a, b in [1, 2, 3]` is `cannot unpack non-iterable int object` in
          CPython; the `[value]` fallback printed `1 2`, `2 2`, `3 2` — three
          wrong answers from one loop.
        * **`bytes` is left alone deliberately, and CPython is why.** It is an
          ordinary iterable of INTS here, so `for a, b in b'ab'` is
          `cannot unpack non-iterable int object` in CPython, which falls out
          of the previous bullet rather than needing a `bytes` case: the item is
          `97`, which is not iterable, so the refusal is the same refusal.

        `hasattr(value, '__iter__')` and not `isinstance(value, (list, tuple))`,
        because a `MojoInstance` is iterable and a `range` is iterable and both
        are ordinary sequences to this rule.
        """
        if isinstance(value, str):
            return list(value)
        if hasattr(value, '__iter__'):
            return list(value)
        kind = type(value).__name__
        if isinstance(value, MojoInstance):
            kind = value._mojo_class.name
        raise TypeError(f"cannot unpack non-iterable {kind} object")

    def _check_exact_arity(self, values, names, item=None) -> None:
        """Refuse a sequence target whose arity is not the item's length.

        **CPython's `UNPACK_SEQUENCE`, and the reason it is here rather than
        left to `zip`.** `zip` truncates to the shorter of the two, which turns
        both arity errors into something the program does not notice:

          * too MANY — `for a, b in [(1, 2, 3)]` is `ValueError: too many
            values to unpack (expected 2, got 3)` in CPython and `1 2` here;
          * too FEW — `for a, b in [(1,)]` is `ValueError: not enough values to
            unpack (expected 2, got 1)`, and the old reading bound `a` and left
            `b` unbound, so the program died later with `NameError: b` at the
            USE SITE. That is the worse of the two shapes by this project's own
            ordering: the diagnostic names a name, not the statement that failed
            to bind it.

        A crash here is a behaviour CHANGE on a program that used to print
        something wrong, which is the trade this codebase makes explicitly and
        which CPython already made.

        `item` is the value the slots are being unpacked OUT of, and it is what
        makes the "too many" wording CPython's for every kind: measured, a
        sequence says `(expected 2, got 3)` and a `str` says `(expected 2)` with
        no count at all — `for a, b in {"abc": 1}` and `for (a,) in {"ab": 1}`
        both omit it, while `for (a,) in [(1, 2)]` includes it. The "not enough"
        arm always carries the count, `for a, b in "ab"` being
        `(expected 2, got 1)`. Passing the item's KIND rather than the value is
        enough; `item=None` (a caller that has only the derived list) states the
        sequence form.
        """
        got = len(values)
        want = len(names)
        if got == want:
            return
        counted = "" if isinstance(item, str) else f", got {got}"
        if got > want:
            raise ValueError(f"too many values to unpack (expected {want}"
                             f"{counted})")
        raise ValueError(f"not enough values to unpack (expected {want}, "
                         f"got {got})")

    def _bind_single_target(self, name, value):
        """Bind one non-starred element of a for-loop/comprehension target
        string to `value`. A plain name (no dot, no bracket) binds a fresh
        local via scope.define(), same as always. A name containing a "."
        and/or a "[" (e.g. "st.lineno", chained "a.b.c", "d[\"k\"]", or
        chained "targets[1][0]") is an attribute/subscript SET on an
        existing object instead: reconstruct the equivalent
        IdentExpr/MemberExpr/SubscriptExpr AST — walking the string
        left-to-right so attribute and subscript access can be freely mixed
        in the same target path — and route through _assign_target, the
        same mechanism plain `obj.attr = value` / `obj[idx] = value`
        assignment statements already use, rather than writing new
        attribute/subscript-set logic specific to for/with targets. A
        subscript's `[...]` contents are an arbitrary expression (not just
        a bare name like an attribute), so they're re-parsed as real Mojo
        source through this interpreter's own tokenizer/parser — the same
        approach _eval_fstring_expr already uses for f-string field
        interpolation — rather than special-casing simple literal keys."""
        if '.' not in name and '[' not in name:
            self.scope.define(name, value)
            return
        target_expr = self._parse_target_path(name)
        self._assign_target(target_expr, value)

    def _parse_target_path(self, name: str):
        """Parse a for/with target-string path like "st.lineno",
        "d[\"k\"]", or a chained/mixed "targets[1][0]" / "a.b[0].c" into
        the equivalent IdentExpr/MemberExpr/SubscriptExpr AST, for
        _bind_single_target to hand to _assign_target. See
        fire_compiler.py's _parse_unpack_target docstring for the string
        representation this consumes (bracket contents are literal,
        re-parseable Mojo source text; the whole string is never itself
        re-tokenized as one expression because a bare leading NAME
        followed by "[" would otherwise parse as a subscript of an
        as-yet-undefined variable rather than the intended target path)."""
        from fire_compiler import py_tokenize, Parser
        i = 0
        n = len(name)
        # Leading identifier (the base name). Deliberately NOT `name[i].isalnum()`
        # (a bare single-`char` method call): gimple_codegen.py's compiled
        # path has no lowering for method calls on a bare `char` (only on
        # `char *`/string receivers, via _lower_str_method) — `isalnum` is
        # also in _C_RESERVED_FUNCS, so it silently mangles to an
        # undefined-at-link-time `char_mojo_isalnum` symbol instead of
        # raising a compile-time error. Range comparisons on the char are
        # well-supported (see fire_compiler.py's own `_pfx_c == 'f'`-style
        # single-char comparisons in its multiline-string-prefix scanner)
        # and avoid the gap entirely.
        start = i
        while i < n and self._is_ident_char(name[i]):
            i += 1
        expr = N.IdentExpr(name=name[start:i])
        while i < n:
            if name[i] == '.':
                i += 1
                start = i
                while i < n and self._is_ident_char(name[i]):
                    i += 1
                expr = N.MemberExpr(obj=expr, member=name[start:i])
            elif name[i] == '[':
                depth = 1
                start = i + 1
                i += 1
                while i < n and depth > 0:
                    if name[i] == '[':
                        depth += 1
                    elif name[i] == ']':
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                index_text = name[start:i]
                i += 1  # consume the closing ']'
                index_tokens = py_tokenize(index_text)
                index_expr = Parser(index_tokens)._parse_expr(0)
                expr = N.SubscriptExpr(obj=expr, index=index_expr)
            else:
                raise SyntaxError(f"Cannot parse for/with target path {name!r}")
        return expr

    @staticmethod
    def _is_ident_char(ch: str) -> bool:
        """True if `ch` (a single character) can appear in a Mojo
        identifier: letters, digits, or underscore. Written with explicit
        range comparisons rather than `ch.isalnum()` — see
        _parse_target_path's docstring for why a bare-`char` method call
        can't be used here."""
        return (('a' <= ch and ch <= 'z') or ('A' <= ch and ch <= 'Z')
                or ('0' <= ch and ch <= '9') or ch == '_')

    def _generator_expression(self, expr):
        """Build a REAL lazy generator object for a parenthesized generator
        expression (`(x for x in xs)`), matching CPython: nothing is
        computed until the object is iterated, an INFINITE source is fine,
        and each item is produced on demand.

        Implemented by SYNTHESIZING the equivalent statement body with
        `fire_compiler.genexp_body` — the ONE definition of what a generator
        expression means as statements, shared with the compiled path's
        desugar (`fire_compiler.desugar_genexps`), which hoists that same
        body into a synthesized module-level generator function — and
        handing it to the SAME `MojoGeneratorObject` a real Mojo `def`
        generator function uses, so the whole existing generator protocol
        (`__iter__`/`__next__`/`.send()`/`.throw()`/`.close()`, per-resume
        `interpreter.scope` swapping, exhaustion) is reused rather than
        reimplemented.

        Two Python fidelity details this gets right that the old
        list-materializing version did not:
        - Only the OUTERMOST iterable is evaluated eagerly, at construction
          time (so its side effects/errors happen when the expression is
          written, not on first `next()`); every inner iterable and every
          condition is evaluated lazily, per item, on the worker thread.
        - The generator gets its OWN child scope, so the loop variables do
          not leak into the enclosing scope (a real Python generator
          expression's variables are scoped to it), while names it READS
          from the enclosing function stay live through that scope's parent
          chain — a real closure, which is why this path does not need (and
          does not do) the compiled path's capture-by-value approximation.

        The synthesized AST uses `N.YieldExpr` — deliberately never this
        file's own `yield` keyword, since a single literal `yield` in a
        top-level function body of myinterpreter.py makes gimple_codegen.py
        treat the WHOLE file as an unsupported user generator and fall back
        to interpreting it from source (see _ThreadedGenerator's docstring).
        """
        scope = Scope(parent=self.scope)
        # Outermost iterable: evaluated HERE, eagerly, per Python. Its value
        # is bound in the generator's own scope and the synthesized outer
        # `for` iterates that name, so it is not evaluated a second time
        # when the first resume happens.
        scope.define(_GENEXP_ITER_NAME,
                     self.eval_expr(expr.generators[0].iterable))
        return MojoGeneratorObject(
            self, scope,
            N.genexp_body(expr,
                          N.IdentExpr(name=_GENEXP_ITER_NAME,
                                      line=expr.line, col=expr.col)))

    def eval_Comprehension(self, expr):
        """List/set/dict comprehensions and parenthesized generator
        expressions (`expr.kind` in 'list'/'set'/'dict'/'generator').

        A 'generator' expression is a REAL lazy generator object (see
        `_generator_expression`), not a materialized list.

        A list/set/dict comprehension gets its OWN SCOPE, as CPython's does,
        and it used to be evaluated in the current scope instead (the same
        simplification `execute_ForStmt` still makes for a plain `for` loop) —
        so its loop variables LEAKED into the enclosing function. The
        measurement that made it a bug rather than a note: `G = 5` /
        `[G for G in rows]` / `return G + out[0]` printed 3 where CPython
        prints 6, and both formal images printed 6, so the interpreter — the
        engine every other parity test uses as the reference — disagreed with
        the compiled path on a program that is otherwise correct, with no
        diagnostic. `test_interp_oracle.py`'s
        `a_comprehension_does_not_shadow_a_module_constant` (interpreter vs
        CPython) and `test_formal_globals.py`'s case of the same name (arm64,
        x86_64 and the interpreter) pin it.

        The compiled path had this defect by a different mechanism — it
        allocated the comprehension's target as a plain local of the enclosing
        function, under the target's own source name, so that local shadowed
        the module global for the rest of the body and `fire.py --jit` printed 3
        where this prints 6. It no longer does: `_compr_bind_target`'s shadow
        predicate is `module_shared.bare_global_read_plan`, the very decision
        `_lower_IdentExpr` makes about where a bare name lives, so a target
        whose name a bare read resolves to a module constant gets its own C
        variable and the enclosing binding is restored when the comprehension
        ends. The compiled spelling is `test_runtime_diff.py`'s
        `comprehension_target_does_not_shadow_a_module_constant`; the case above
        lives in the oracle rather than in the engine-vs-engine suite because two
        engines agreeing on a wrong answer is invisible to the latter.

        `_generator_expression` twenty lines below already did this, and the
        shape is the same one it uses: a child scope for the whole walk, with
        names the comprehension READS still live through the parent chain.
        That is a real closure rather than a copy, so the enclosing function's
        locals and the module's globals both resolve normally from inside —
        which is why the common case is unchanged and only the BINDING of the
        loop variable moves.

        The outermost iterable is evaluated inside the child scope too, and
        that is Python's rule rather than an accident of the placement: in
        `[... for x in y for y in x]`, `y` is read before `y` is bound, and
        with the child scope in place that is structural — the first `y` can
        only resolve to the enclosing one — instead of depending on the order
        two nested `run` calls happen to bind in.

        Save/push/restore rather than a new `return`, because of the one-return
        discipline the docstring below explains.

        For a dict comprehension, fire_compiler.py's parser stores the KEY
        expression in `.element` and the VALUE expression in `.value`
        (see _parse_dict_or_set).

        ONE `return`, through a single `result` variable, deliberately —
        the same shape (and for the same reason) as `MojoFunction._invoke`
        above: this file is self-hosted, and its return-type inference is a
        whole-function unification that cannot cope with several
        differently-shaped `return` statements in one function. Adding the
        generator-expression branch as its own early `return` made the
        unification pick one of {MojoGeneratorObject, MojoSet *, MojoDict *,
        MojoList *} and then fail coercing the others ("cannot coerce
        MojoSet * to MojoDict *" when self-hosting myinterpreter.py)."""
        if expr.kind == 'generator' and expr.generators:
            result = self._generator_expression(expr)
        else:
            results = []
            # Dict comprehensions may use `**` spread in the element
            # (`{**d for d in ds}`) rather than `key: value`; detect it
            # once so the inner loop can merge mappings.
            _dict_spread = (expr.kind == 'dict' and expr.value is None
                            and isinstance(expr.element, N.UnaryOp)
                            and expr.element.op == '**')

            def run(generators):
                if not generators:
                    if expr.kind == 'dict':
                        if _dict_spread:
                            results.append(('__spread__', self.eval_expr(expr.element.operand)))
                        else:
                            k = self.eval_expr(expr.element)
                            v = self.eval_expr(expr.value)
                            results.append((k, v))
                    else:
                        spread = self._spread_operand(expr.element, "*")
                        if spread is not None:
                            for _sv in self.eval_expr(spread):
                                results.append(_sv)
                        else:
                            results.append(self.eval_expr(expr.element))
                    return
                gen = generators[0]
                rest = generators[1:]
                for item in _mojo_iter(self.eval_expr(gen.iterable)):
                    self._bind_comprehension_target(gen.target, item)
                    if all(self.eval_expr(cond) for cond in gen.conditions):
                        run(rest)

            saved = self.scope
            self.scope = Scope(parent=saved)
            try:
                run(expr.generators)
            finally:
                self.scope = saved
            if expr.kind == 'set':
                result = set(results)
            elif expr.kind == 'dict':
                if _dict_spread:
                    result = {}
                    for _pair in results:
                        result.update(_pair[1])
                else:
                    result = dict(results)
            else:
                result = results
        return result
