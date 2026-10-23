# Dependent-return iterator factory evaluation.
#
# `peekable(l)` / `enumerate(l)` / `take(l, 3)` / `drop(l, 2)` / `cycle(l)`
# return types that depend on the STATIC TYPE of their container argument:
#
#     def peekable(ref iterable: Some[Iterable]) -> _PeekableIterator[
#         type_of(iterable).IteratorType[origin_of(iterable)]]
#     def take[origin: ImmOrigin, IterableType: Iterable, //,](
#         ref[origin] iterable: IterableType, count: Int) -> _TakeIterator[
#         IterableType.IteratorType[origin]]
#     def cycle[IterableType: Iterable](
#         ref iterable: IterableType) -> _CycleIterator[type_of(iter(iterable))]
#
# (all measured against `std/iter/__init__.mojo` and
# `std/itertools/itertools.mojo` — the ref AND the var/moved overload of each;
# the var overloads return `...[type_of(iterable).IteratorOwnedType]`.)
#
# The `.o` route cannot serve these: its elaboration of the FACTORY succeeds,
# but the dependent return erases to a boxed `int64_t` (the elaborator has no
# access to the importer's container types), so the local receives no struct
# type and `next(<local>)` refuses. This module evaluates the dependency
# statically — the container is a local whose declaration this compile can
# read (`var nums = [1, 2, 3]`, `var e = List[Int]()`, `var r = range(10)`,
# or a NESTED factory call whose wrapper is itself an iterator) — and hands
# the two callers a single record:
#
#   * the elab side (`elab_intu._seed_factories`) registers the wrapper struct
#     the record names and enqueues it for in-TU materialization, so the
#     materialized definition and this module's evaluation are ONE reading of
#     the same annotations;
#   * the emit side (`emit_calls._lower_factory_call`) reconstructs what the
#     factory BODY would have produced at the call site — `iter(container)`
#     and then the wrapper constructor — from the record.
#
# WHAT IT IS NOT. It lowers nothing and it does not generalize past the
# measured shapes: a container it cannot statically resolve (a parameter, a
# global, an unannotated `[]` of a non-List element type, a non-List
# container) means NO record, and the call site then behaves exactly as it
# did before this module existed (honest refusal, per the elab pass's own
# refusal rule). `test_zip` / `test_product` (multi-container and variadic
# factories) and closure factories (`test_map` / `test_take_while` /
# `test_drop_while`) are deliberately outside it — see
# `bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md`.
# `monomorphize` is deliberately NOT imported here: it imports `GimpleGen`
# from `gimple_codegen` at module level, and this module loads in the MIDDLE
# of `gimple_codegen`'s own import (via `module_gen` -> `elab_intu`). The
# mangled names this module's analysis feeds are computed by the elab/emit
# callers, which lazy-import `monomorphize` inside a function (the same way
# `elab_intu._materialize` does) so the cycle never closes at import time.
from __future__ import annotations

import re

# ── the dependent-return annotation shapes (measured, closed set) ──────────
#
# One wrapper mention with ONE type argument, in exactly one of three forms:
#   W[X.IteratorType[<origin-expr>]]      borrowed inner (X = a type param or
#                                         the `type_of(<name>)` of the arg)
#   W[X.IteratorOwnedType]                owned inner (the var/moved overload)
#   W[type_of(iter(<name>))]              `cycle`'s ref form — iter() of a
#                                         borrowed List IS X.IteratorType, so
#                                         it evaluates to the same answer
# `<origin-expr>` is `origin_of(<name>)` or the factory's own `origin` type
# parameter; either erases to the same placeholder for our purposes (see
# `expand_inner`: the origin parameter of a List iterator is erased-only).

_RE_QUAL = re.compile(
    r'^(\w+)\[\s*(?:type_of\((\w+)\)\s*\.|(\w+)\s*\.)'
    r'(IteratorType|IteratorOwnedType)\s*(?:\[[^\]]*\])?\s*\]$')
_RE_TYPEOF_ITER = re.compile(r'^(\w+)\[\s*type_of\(\s*iter\((\w+)\)\s*\)\s*\]$')
# The BARE `iter` builtin names the container's OWN iterator type directly —
# no wrapper mention. Two overloads, two shapes (std/iter/__init__.mojo):
#   owned    `type_of(iterable).IteratorOwnedType`
#   borrowed `IterableType.IteratorType[origin_of(iterable)]`
# `wrapper: None` in the answer is the discriminator the seed/emit sides use
# (the inner IS the return value, so it is materialized as its own root).
_RE_BARE_ITER_OWNED = re.compile(r'^type_of\(\s*(\w+)\s*\)\s*\.\s*IteratorOwnedType$')
_RE_BARE_ITER_BORROWED = re.compile(r'^(\w+)\s*\.\s*IteratorType\s*\[[^\]]*\]$')
# The DIRECT-STRUCT factory (measured 2026-10-21: `def count(start: Int = 0,
# step: Int = 1) -> _CountIterator:` in std/itertools/itertools.mojo): the
# return names a CONCRETE struct — a single identifier, no brackets, no dot,
# no type argument. `kind: 'direct'` is seeded ONLY for a call with no
# POSITIONAL args (elab_intu._seed_direct_factory — the `if not args:`
# branch), which includes the measured kwarg form `count(start=10, step=2)`;
# on the positional-arg path a 'direct' candidate is inert —
# _factory_return_for's owned/borrowed pick can never select it, so a
# `def f(x) -> ConcreteStruct` is handled exactly as before this arm
# existed. The emit side (emit_calls._lower_factory_call, kind 'direct')
# maps positionals, kwargs, then the factory's own parameter defaults.
_RE_BARE_STRUCT = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)$')
# The KEYWORD-ARG form (measured 2026-10-21 (further): `def take_while[...]
# -> _TakeWhileIterator[InnerIteratorType=IterableType.IteratorType[origin],
# predicate=predicate]` in std/itertools/itertools.mojo): the type-arg block
# carries `name=expr` pairs instead of the single `X.IteratorType[...]`
# mention. `kind` comes from which iterator member the INNER kwarg names
# (`IteratorOwnedType` -> owned, `IteratorType` -> borrowed — check owned
# first, its string contains the other). The remaining kwargs are the
# FUNCTION parameters (take_while/drop_while's `predicate`), bound from the
# call's explicit type arg by elab_intu._seed_one_factory.
_RE_KW_STRUCT = re.compile(r'^(\w+)\s*\[(.*)\]$')


def _top_level_split(s: str) -> list:
    """The comma parts of a type-arg block, splitting only at bracket/paren/
    brace depth 0 — a kwarg VALUE may itself carry nested brackets
    (`...IteratorType[origin]`) and a function annotation parens
    (`def(...) thin -> Bool`)."""
    parts, depth, cur = [], 0, []
    for c in s:
        if c in '[({':
            depth += 1
        elif c in '])}':
            depth -= 1
        if c == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
    tail = ''.join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_return(ann) -> dict | None:
    """The wrapper a dependent-return annotation names, or None when the
    annotation is not one of the measured shapes. `ann` may be multi-line
    source text; it is normalized to single-spaced before matching."""
    if not isinstance(ann, str) or not ann:
        return None
    s = ' '.join(ann.split())
    m = _RE_QUAL.match(s)
    if m:
        kind = 'borrowed' if m.group(4) == 'IteratorType' else 'owned'
        return {'wrapper': m.group(1), 'kind': kind,
                'x': m.group(2) or m.group(3)}
    # The MULTI-CONTAINER dependent return (measured 2026-10-21, part 4:
    # `product` — the borrowed overloads spell `-> _Product2[
    # IterableTypeA.IteratorType[origin_of(iterable_a)],
    # IterableTypeB.IteratorType[origin_of(iterable_b)]]` and the owned
    # ones `-> _Product2[type_of(iterable_a).IteratorOwnedType,
    # type_of(iterable_b).IteratorOwnedType]`): one iterator-type MENTION
    # per container parameter, and mention i corresponds POSITIONALLY to
    # argument i — the wrapper's type arguments are the per-argument
    # INNER types. Both mention spellings are accepted (the borrowed
    # `<TypeVar>.IteratorType[origin_of(<p>)]` and the owned
    # `type_of(<p>).IteratorOwnedType`); the kind is the single marker
    # present in the block, and a mixed block is refused. `x` is None —
    # the per-argument resolution (not a single container) feeds the
    # inner, the way the seed's multi subpath reads `rec['multi_args']`.
    _mm = _RE_KW_STRUCT.match(s)
    if _mm:
        _mparts = _top_level_split(_mm.group(2))
        if len(_mparts) >= 2:
            _multi = []
            for _p in _mparts:
                _qm = re.match(
                    r'^(?:type_of\(\s*(\w+)\s*\)\s*\.\s*|(\w+)\s*\.\s*)'
                    r'(IteratorType|IteratorOwnedType)'
                    r'(?:\s*\[\s*origin_of\(\s*(\w+)\s*\)\s*\])?\s*$',
                    _p.strip())
                if _qm:
                    _multi.append((_qm.group(3),
                                   _qm.group(1) or _qm.group(4)))
            if len(_multi) == len(_mparts):
                _mkinds = {k for k, _ in _multi}
                if len(_mkinds) == 1:
                    return {'wrapper': _mm.group(1),
                            'kind': ('borrowed'
                                     if _mkinds == {'IteratorType'}
                                     else 'owned'),
                            'x': None,
                            'multi': _multi}
    m = _RE_TYPEOF_ITER.match(s)
    if m:
        return {'wrapper': m.group(1), 'kind': 'borrowed', 'x': m.group(2)}
    m = _RE_BARE_ITER_OWNED.match(s)
    if m:
        return {'wrapper': None, 'kind': 'owned', 'x': m.group(1)}
    m = _RE_BARE_ITER_BORROWED.match(s)
    if m:
        return {'wrapper': None, 'kind': 'borrowed', 'x': m.group(1)}
    m = _RE_KW_STRUCT.match(s)
    if m:
        if '=' in m.group(2):
            kind, inner_kwarg = None, None
            for part in _top_level_split(m.group(2)):
                km = re.match(r'(\w+)\s*=\s*(.*)$', part, re.S)
                if not km:
                    continue
                v = km.group(2)
                if 'IteratorOwnedType' in v:
                    kind, inner_kwarg = 'owned', km.group(1)
                    break
                if 'IteratorType' in v:
                    kind, inner_kwarg = 'borrowed', km.group(1)
                    break
            if kind is None:
                return None
            return {'wrapper': m.group(1), 'kind': kind, 'x': None,
                    'inner_kwarg': inner_kwarg}
        # The positional arm (measured 2026-10-21 (further): map's
        # `_MapIterator[function]` — the single positional is the FUNCTION
        # VALUE the call passes as its explicit type arg, `map[add_one](l)`;
        # a positional cannot carry a kind, so `kind` is None and the seed
        # derives the pass mode from the call argument's own `moved`).
        # The other single-bare-identifier returns in the measured stdlib
        # (`_RepeatIterator[ElementType]`, `_Empty[T]`, `_Once[T]`) match this
        # arm too, but the seed refuses them: their calls pass no bare-
        # identifier explicit type arg that resolves to a def in scope, so
        # the call site is left exactly as this arm found it — the same C as
        # the pre-arm refusal.
        parts = _top_level_split(m.group(2))
        if parts and all(re.match(r'^\w+$', p) for p in parts):
            return {'wrapper': m.group(1), 'kind': None, 'x': None}
    m = _RE_BARE_STRUCT.match(s)
    if m:
        return {'wrapper': m.group(1), 'kind': 'direct', 'x': None}
    return None


def parse_out_res(params, return_type) -> dict | None:
    """The OUT-PARAMETER dependent-return factory (measured 2026-10-21,
    part 4: `chain` / `zip` — `def chain[*Ts: Iterable](*iterables: *Ts,
    out res: _ChainedIterator[*_iterable_to_iterator[...]])`, return_type
    None, the dependent wrapper named in the trailing `out` parameter's
    annotation; the parser drops the `out` marker, so the parameter arrives
    as a plain `('res', ann)` pair).

    The KIND comes from the annotation's inner-kind marker, the same
    overload-pair distinction `parse_return` reads off `IteratorType` /
    `IteratorOwnedType`: the borrowed overload threads
    `_iterable_to_iterator`, the owned one `_iterable_owned_to_iterator`
    (zip's owned overload additionally names `MutUntrackedOrigin` in the
    origin slot). Returns {'wrapper', 'kind', 'x': None, 'out_param'} or
    None for any spelling this subpath has not measured."""
    if return_type:
        return None   # a dependent RETURN annotation is the other subpath
    if not params:
        return None
    pname, pann = params[-1]
    if not isinstance(pann, str):
        return None
    m = re.match(r'^\s*(_\w+)\s*\[', pann)
    if not m:
        return None
    s = ' '.join(pann.split())
    kind = 'owned' if '_iterable_owned_to_iterator' in s else 'borrowed'
    return {'wrapper': m.group(1), 'kind': kind, 'x': None,
            'out_param': pname}


# ── the container's iterator-type members, read from its source ────────────

def _matching_bracket(s: str, open_at: int):
    """Index of the `]` matching the `[` at `open_at`, or None (bracket depth
    only — no string skipping: iterator-type RHS text contains no brackets
    inside string literals in the measured stdlib, and a mismatch is a
    refusal, not a guess)."""
    depth = 0
    for i in range(open_at, len(s)):
        if s[i] == '[':
            depth += 1
        elif s[i] == ']':
            depth -= 1
            if depth == 0:
                return i
    return None


def _struct_block(src: str, tname: str) -> str | None:
    """The top-level `struct TNAME[...]` (head AND body), or None.

    The head is parsed structurally, not by a column-0 guess, because a
    struct's OWN header routinely spans lines with column-0 closers:
    `struct List[T: AnyType, /](\\n    Boolable,\\n ...\\n)` puts the
    conformance list's `)` at column 0, so "the next column-0 line ends the
    block" truncates the block to the head. The head is exactly: the
    type-parameter `]`, then an optional `(` ... `)` conformance list, then
    the terminating `:`. The BODY runs from after that colon to the next
    column-0 line — which, once the head is consumed, is genuinely a new
    top-level statement (the measured stdlib indents docstring content, so
    no column-0 line hides inside the body's docstring)."""
    m = re.search(rf'^struct\s+{re.escape(tname)}\s*\[', src, re.M)
    if not m:
        return None
    i = _matching_bracket(src, m.end() - 1)
    if i is None:
        return None
    j = i + 1
    while j < len(src) and src[j] in ' \t\r\n':
        j += 1
    if j < len(src) and src[j] == '(':
        # A conformance list can itself contain `)` inside nested brackets
        # (`conforms_to(X, (A, B))`); scan depth instead of taking the first.
        depth, p = 0, j
        while p < len(src):
            c = src[p]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            p += 1
        if depth != 0:
            return None
        j = p + 1
        while j < len(src) and src[j] in ' \t\r\n':
            j += 1
    if j >= len(src) or src[j] != ':':
        return None
    body_start = j + 1
    eol = src.find('\n', body_start)
    if eol == -1:
        return src[m.start():]
    nxt = re.search(r'^\S', src[eol:], re.M)
    end = eol + nxt.start() if nxt else len(src)
    return src[m.start():end]


def iter_type_rhs(container_src: str, tname: str, kind: str) -> str | None:
    """The RHS of the container's `comptime IteratorType[...]` (kind
    'borrowed') or `comptime IteratorOwnedType` (kind 'owned') member, e.g.
    List's `_ListIter[downcast[Self.T, Copyable], iterable_origin, True]`.

    Both spellings are measured in `std/collections/list.mojo`; the member may
    carry a `where` clause and span lines, so the scan is: find the member
    name, (for the borrowed form: consume its bracketed parameter list), then
    take the text from the `=` to the end of its line."""
    block = _struct_block(container_src, tname)
    if not block:
        return None
    if kind == 'borrowed':
        m = re.search(r'comptime\s+IteratorType\s*\[', block)
        if not m:
            return None
        i = _matching_bracket(block, m.end() - 1)
        if i is None:
            return None
        rest = block[i + 1:]
    else:
        m = re.search(r'comptime\s+IteratorOwnedType\b', block)
        if not m:
            return None
        rest = block[m.end():]
    eq = re.search(r'(?<![:\w])=\s*', rest)
    if not eq:
        return None
    line = rest[eq.end():].split('\n', 1)[0].strip()
    return line or None


def _downcast_sub(text: str) -> str:
    """`downcast[A, B]` -> A, iterated (a downcast may nest another)."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'downcast\[\s*([^,\]]+)\s*,[^,\]]*\]',
                      lambda m: m.group(1).strip(), text)
    return text


_ORIGINISH = re.compile(
    r'\b(origin_of\([^)]*\)|iterable_origin|iterable_mut|origin|'
    r'Self\.\w*origin\w*|Self\.iterable_\w+)\b')


def expand_inner(container_src: str, inner_base: str, rhs: str,
                 elem: str, mut: bool) -> dict | None:
    """The FULL explicit type-argument list for the inner iterator struct.

    `rhs` is the container's iterator-type RHS (`_ListIter[downcast[Self.T,
    Copyable], iterable_origin, True]` for a borrowed List); the inner
    struct's own head may carry DERIVED parameters before a `//` marker that
    the RHS never spells (`_ListIter[mut: Bool, //, T, origin, forward]` —
    the stdlib calls it with the three explicit parameters and the compiler
    derives `mut` from the origin). Positionally bind the RHS arguments onto
    the explicit parameters, fill derived ones (`mut`-annotated -> the
    pass-mode Bool, everything else origin-ish -> the `ImmOrigin`
    placeholder), and substitute `Self.T`/`downcast` with the concrete
    element. Returns {'names': [...], 'args': [...]} (parallel lists, for
    the mangle's `{param: value}` dict) or None when anything the measured
    stdlib does not write survives — a parameter left unbound with no
    default, or a `Self.` member no rule covers — and the caller then
    refuses rather than guessing."""
    m = re.search(rf'^struct\s+{re.escape(inner_base)}\s*\[',
                  container_src, re.M)
    if not m:
        return None
    close = _matching_bracket(container_src, m.end() - 1)
    if close is None:
        return None
    head = container_src[m.end():close]
    # Parameter NAMES in order. The `//` marker (a line of its own or inline)
    # separates the derived prefix from the explicit parameters —
    # `_ListIter[mut: Bool, //, T, origin, forward]` is called with the three
    # explicit parameters and the compiler derives `mut` from the origin.
    # With NO `//` at all (`_ListIterOwned[T: Movable & Deinitable]`) every
    # parameter is explicit: the marker, not position, is what makes a
    # parameter derived.
    parts = [p.strip() for p in _split_top_commas(head)]
    names, derived_n = [], []
    seen_sep = False
    for p in parts:
        if not p or p in ('//', '/', '*', '**'):
            if p == '//':
                seen_sep = True
            continue
        nm = p.split(':', 1)[0].strip()
        if seen_sep:
            names.append(nm)
        else:
            derived_n.append(nm)
    if not seen_sep:
        names, derived_n = derived_n + names, []
    bracket = rhs[rhs.index('[') + 1:rhs.rindex(']')]
    rhs_args = [a.strip() for a in _split_top_commas(bracket)] if bracket else []
    defaults = {}
    for p in parts:
        if p and '=' in p and p not in ('//', '/'):
            h, _, d = p.partition('=')
            nm = h.split(':', 1)[0].strip()
            if nm:
                defaults[nm] = d.strip()

    def sub(a: str) -> str:
        a = _downcast_sub(a)
        a = a.replace('Self.T', elem)
        a = _ORIGINISH.sub(lambda m: 'ImmOrigin'
                           if 'mut' not in m.group(1) else str(mut), a)
        return a

    out = []
    for nm in derived_n:
        ann = ''
        for p in parts:
            if p.split(':', 1)[0].strip() == nm:
                ann = p.split(':', 1)[1] if ':' in p else ''
                break
        out.append(str(mut) if 'Bool' in ann else 'ImmOrigin')
    for i, nm in enumerate(names):
        if i < len(rhs_args):
            out.append(sub(rhs_args[i]))
        elif nm in defaults:
            out.append(sub(defaults[nm]))
        else:
            return None
    # A `Self.` member no rule covered is an unmeasured shape, not an error
    # to paper over: refusing keeps the call site on its old (honest) path.
    if re.search(r'\bSelf\.\w+', ' '.join(out)):
        return None
    return {'names': derived_n + names, 'args': out}


def _header_params(src: str, sname: str) -> list | None:
    """The header parameters of `struct <sname>[...]` as an ORDERED list of
    `(name, default)` pairs (default is the empty string when absent), or
    None when the header is not found or its brackets do not close. The `//`
    derived-parameter separator is skipped like a parameter with no name."""
    m = re.search(rf'^struct\s+{re.escape(sname)}\s*\[', src, re.M)
    if not m:
        return None
    close = _matching_bracket(src, m.end() - 1)
    if close is None:
        return None
    head = src[m.end():close]
    out = []
    for p in _split_top_commas(head):
        p = p.strip()
        if not p or p == '//':
            continue
        h, _, d = p.partition('=')
        nm = h.split(':', 1)[0].strip()
        if nm:
            out.append((nm, d.strip()))
    return out


def struct_iter_inner(container_src: str, sname: str, rhs: str,
                      sargs: list) -> dict | None:
    """The FULL explicit type-argument list for the inner iterator of a
    USER-STRUCT container (measured 2026-10-22, part 5: test_cycle's
    `cycle(_owned3(1, 2, 3))` — the container is a LOCAL function's owned
    return, a user `IterableOwned` struct `_CopyableOwned[3]`, whose own
    `comptime IteratorOwnedType: Iterator = _CopyableOwnedIter[Self.size]`
    member names the inner with the container's CONCRETE type arguments in
    place of the container's type parameters).

    Unlike `expand_inner` (the LIST container's element parameter is the
    fixed token `Self.T`), the member text here carries the container's own
    parameter NAME (`Self.size`): bind every `Self.<param>` to the concrete
    argument the call spells, positionally against the container's header
    parameters — a parameter the call omits takes its header default, and a
    `Self.` member no header parameter names (or a parameter with neither
    argument nor default) is a refusal, not a guess. The inner's own header
    must be present in the same source (the measured shapes keep both
    structs in the test module) so its parameter NAMES can key the mangle's
    `{param: value}` dict. Returns {'names', 'args'} (parallel lists) or
    None, exactly as `expand_inner` does."""
    hparams = _header_params(container_src, sname)
    if hparams is None:
        return None
    names = [nm for nm, _ in hparams]
    defaults = {nm: d for nm, d in hparams}
    out = rhs
    for i, nm in enumerate(names):
        val = sargs[i] if i < len(sargs) else defaults.get(nm, '')
        if not val:
            return None
        out = re.sub(rf'\bSelf\.{re.escape(nm)}\b', val, out)
    if re.search(r'\bSelf\.\w+', out):
        return None
    if '[' not in out:
        return None
    inner_base = out.split('[', 1)[0].strip()
    bracket = out[out.index('[') + 1:out.rindex(']')]
    iargs = [a.strip() for a in _split_top_commas(bracket)] if bracket else []
    inames = _header_params(container_src, inner_base)
    if inames is None:
        return None      # the member names a struct this source does not declare
    inames = [nm for nm, _ in inames]
    if len(inames) != len(iargs):
        return None      # the member's arity does not bind the inner's header
    return {'names': inames, 'args': iargs}


def struct_args_map(container_src: str, sname: str,
                    sargs: list) -> dict | None:
    """The `{param: value}` mangle dict for a USER struct's CONCRETE type
    arguments: the call's arguments positionally against the struct's header
    parameters, a trailing parameter the call omits taking its header
    default, a parameter with neither argument nor default a refusal (None).
    Sibling of `struct_iter_inner`'s own binding rule — the seed uses it for
    the container's OWN mangled name (the emit side calls the container's
    in-TU `__iter__` through it)."""
    hparams = _header_params(container_src, sname)
    if hparams is None:
        return None
    defaults = {nm: d for nm, d in hparams}
    out = {}
    for i, (nm, _) in enumerate(hparams):
        val = sargs[i] if i < len(sargs) else defaults.get(nm, '')
        if not val:
            return None
        out[nm] = val
    return out


def _split_top_commas(s: str) -> list[str]:
    """Top-level comma split (bracket-depth aware, string-skip — the same
    rule `mojo.middle.exprtypes._split_top_level_commas` applies; re-imposed
    here so this module stays free of a dependency on that module)."""
    out, buf, depth = [], [], 0
    i, n, q = 0, len(s), ''
    while i < n:
        c = s[i]
        if q:
            buf.append(c)
            if c == q and s[i - 1] != '\\':
                q = ''
            i += 1
            continue
        if c in ('"', "'"):
            q = c
            buf.append(c)
        elif c in '[(':
            depth += 1
            buf.append(c)
        elif c in '])':
            depth -= 1
            buf.append(c)
        elif c == ',' and depth == 0:
            out.append(''.join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    out.append(''.join(buf))
    return out


# ── the call site: argument signature + container resolution ───────────────

def arg_signature(node) -> tuple:
    """A pure, structural signature of one argument expression — the KEY this
    module's record is filed under, so the elab side and the emit side
    (which see the SAME node objects) agree without sharing state or
    depending on traversal order. Deliberately coarse: two calls with the
    same signature get the same record, which is exactly what a record being
    a pure function of its call site means."""
    if node is None:
        return ('none',)
    t = type(node).__name__
    name = getattr(node, 'name', None)
    if t == 'IntLiteral':
        return ('L', node.value)
    if t == 'FloatLiteral':
        return ('F', node.value)
    if t == 'StringLiteral':
        return ('S', node.value)
    if t == 'IdentExpr':
        return ('i', name)
    if t == 'BoolLiteral':
        return ('b', node.value)
    if t == 'UnaryOp':
        return (node.op, arg_signature(getattr(node, 'operand', None)))
    if t == 'CallExpr':
        f = getattr(node, 'func', None)
        fn = getattr(f, 'name', None) or (
            getattr(getattr(f, 'obj', None), 'name', None) if f else None)
        args = getattr(node, 'args', None) or ()
        kws = getattr(node, 'kwargs', None) or ()
        return ('c', fn, tuple(arg_signature(a) for a in args),
                tuple(k[0] for k in kws))
    if t == 'ListExpr':
        # Element-aware (part 4): the flat `('lit',)` collapsed
        # `List([0, 1, 2])` and `List(["0", "1", "2"])` into ONE record
        # key, so the chain/zip out-res subpath's per-call records
        # collided and the last-seeded spelling (String) retyped every
        # Int call site in the file — `var cl = chain(List([0, 1, 2]),
        # ...)` declared a String wrapper and gcc refused the
        # incompatible-pointer assignment. Two calls with the same
        # element VALUES still share a record (same mangled
        # instantiation — the record is a pure function of the call
        # site); different values get their own.
        return ('lit', tuple(arg_signature(e) for e in
                             (getattr(node, 'elements', None) or ())))
    if t == 'SetExpr':
        return ('set', tuple(arg_signature(e) for e in
                             (getattr(node, 'elements', None) or ())))
    if t == 'SubscriptExpr':
        return ('sub', name, arg_signature(getattr(node, 'index', None)))
    if t == 'TupleExpr':
        return ('tup', tuple(arg_signature(e) for e in
                             (getattr(node, 'elements', None) or ())))
    return ('x', t, name)


def factory_call_key(name: str, node) -> tuple:
    """The record key for one factory CALL: name + the explicit type args +
    every argument's signature + the kwarg names (values already inside the
    argument signatures). The type-arg part matters exactly when the factory
    takes a FUNCTION as a type argument (measured 2026-10-21 (further):
    `take_while[less_than_5](nums)` — two calls with the same container
    local but different predicates are DIFFERENT instantiations; a key
    without the type arg let the second seed's record silently replace the
    first, and both call sites would have emitted the same wrapper).

    The LINE is the positional discriminator (2026-10-22 part 5): the
    structural key is per-call-SHAPE, not per-call-SITE, so same-name
    same-shape calls in DIFFERENT test functions shared one record and the
    later seed's record silently replaced the earlier — measured in the
    A/B on two already-green files: test_nth's 14 `iter(l)` sites (the
    String instantiation leaked into 11 Int-test sites: lists built with
    mojo_list_append_int were alloced as _ListIterOwned[String]) and
    test_bool's `map[gt0](l)` in test_all baking the test_any_gt0 symbol.
    (test_product's own line-30/line-82 `product(l1, l2)` pair is the same
    hazard with identical element types — harmless there, latent in
    general.) Two call sites cannot share a LINE with the same signature
    and different static element types (same scope => same locals;
    different scopes => different lines), so the line never merges
    distinct instantiation semantics."""
    fn = getattr(node, 'func', None)
    type_args = ()
    if type(fn).__name__ == 'SubscriptExpr':
        idx = getattr(fn, 'index', None)
        if idx is not None:
            type_args = (arg_signature(idx),)
    args = getattr(node, 'args', None) or ()
    kws = getattr(node, 'kwargs', None) or ()
    return (name, getattr(node, 'line', 0), type_args,
            tuple(arg_signature(a) for a in args),
            tuple(k[0] for k in kws))


# Element-type table shared by the mangled NAME side (`Int`, `String`, ...)
# and the C side (`int64_t`, `char *`, ...). The C side mirrors
# `emit_exprs._lower_list_literal`'s own answers: all-bool literals are
# `_Bool`, strings `char *`, numeric lists promote int -> double.
_MOJO_ELEM_C = {'Int': 'int64_t', 'String': 'char *', 'Bool': '_Bool',
                'Float64': 'double'}


def _struct_ctor_mention(e) -> str | None:
    """The generic-struct MENTION a list-literal CONSTRUCTOR element spells,
    or None. `CopyCounter[NoneType](None)` -> `CopyCounter[NoneType]`.

    Measured 2026-10-22 (part 5, test_map): the element is a CallExpr whose
    func is a SubscriptExpr — a generic struct CONSTRUCTOR, not a value
    subscript — and its type arguments are TYPE NAMES (IdentExprs; a
    multi-argument spelling is a TupleExpr of them). The value-subscript
    spelling (`f[0](x)`) indexes with a literal or expression, never a bare
    type name, so the IdentExpr-index gate is the discriminator. The mention
    is the mangled-NAME-side spelling the seed feeds `expand_inner` and
    `mm.mangle` (the in-TU materializer takes the same text through
    `bind_type_args`); the C-side slot is a raw pointer word (see
    `_MOJO_ELEM_C`'s default). A mention that does not turn out to be a
    registered generic struct is refused downstream in the seed — exactly as
    every other unresolved container is — so the gate here stays textual."""
    f = getattr(e, 'func', None)
    if type(f).__name__ != 'SubscriptExpr':
        return None
    obj = getattr(f, 'obj', None)
    if type(obj).__name__ != 'IdentExpr':
        return None
    idx = getattr(f, 'index', None)
    t = type(idx).__name__
    if t == 'IdentExpr':
        args = [idx.name]
    elif t == 'TupleExpr':
        args = [a.name for a in (getattr(idx, 'elements', None) or ())
                if type(a).__name__ == 'IdentExpr']
        if len(args) != len(getattr(idx, 'elements', None) or ()):
            return None
    else:
        return None
    if not args or any(not a for a in args):
        return None
    return f"{obj.name}[{', '.join(args)}]"


def list_literal_elem(elements) -> str | None:
    """The Mojo element type of a list LITERAL, mirroring the emitter's
    promotion rules (all-bool -> Bool, any float -> Float64, otherwise
    Int). None when the literal is empty or mixes element kinds the emitter
    would box (heterogeneous) — a refusal, not a guess."""
    if not elements:
        return None
    kinds = set()
    for e in elements:
        t = type(e).__name__
        nm = getattr(e, 'name', None)
        if t == 'IntLiteral':
            kinds.add('Int')
        elif t == 'FloatLiteral':
            kinds.add('Float64')
        elif t == 'StringLiteral':
            kinds.add('String')
        elif t == 'BoolLiteral':
            kinds.add('Bool')
        elif t == 'IdentExpr' and nm in ('True', 'False'):
            kinds.add('Bool')
        elif t == 'UnaryOp' and getattr(e, 'op', None) in ('-', '+'):
            # A signed numeric LITERAL (`[5, 3, 1, 0, -1, 2]` parses `-1`
            # as a UnaryOp, not an IntLiteral): the emitter's `_quick_type`
            # answers the default int64_t for it, so the list lowers as a
            # numeric one — mirror that. Any other operand (an identifier,
            # a call) stays a refusal: the element type is not static here.
            _op = getattr(e, 'operand', None)
            _ot = type(_op).__name__
            if _ot == 'IntLiteral':
                kinds.add('Int')
            elif _ot == 'FloatLiteral':
                kinds.add('Float64')
            else:
                return None
        elif t == 'CallExpr' and type(getattr(e, 'func', None)).__name__ \
                == 'IdentExpr' and getattr(getattr(e, 'func', None),
                                           'name', None) == 'String':
            # A `String(...)` constructor element (measured 2026-10-21
            # part 4: test_zip's `var long = [String("aaa"),
            # String("bbb"), ...]`): the constructor answers `String`
            # regardless of its argument, and the emitter appends such an
            # element through `mojo_list_append_str` — the list IS a
            # String list.
            kinds.add('String')
        elif t == 'CallExpr':
            # A GENERIC STRUCT constructor element (measured 2026-10-22
            # part 5: test_map's `var list = [CopyCounter[NoneType](None)]`)
            # — the element type is the struct MENTION itself, carried as a
            # distinct kind so the homogeneity answer below is exact: two
            # elements of the same struct kind are one element type, any
            # mix (struct beside a scalar, or two different structs) is a
            # heterogeneous refusal, exactly as a String beside an Int is.
            _mention = _struct_ctor_mention(e)
            if _mention is not None:
                kinds.add(('struct', _mention))
            else:
                return None
        else:
            return None
    if len(kinds) == 1:
        _k = next(iter(kinds))
        if isinstance(_k, tuple):
            return _k[1]
    if 'String' in kinds:
        return 'String' if kinds == {'String'} else None
    if kinds == {'Bool'}:
        return 'Bool'
    if kinds <= {'Int', 'Float64'}:
        return 'Float64' if 'Float64' in kinds else 'Int'
    if kinds == {'Int'}:
        return 'Int'
    return None


def resolve_container(node, factory_names, locals_map, struct_names=None,
                      fn_returns=None) -> dict | None:
    """What a factory's FIRST argument statically IS, or None (refuse).

    Returns one of:
      {'kind': 'list',   'tname': 'List', 'elem': <mojo>, 'moved': bool}
          a local `var x = [1, 2, 3]` / `var e = List[Int]()` /
          `var x: List[Int] = ...` / `var r = range(10)`, read (or moved by
           a single `^`) in THIS function; or a direct `List[T]()` rvalue.
           A plain `var` local and an rvalue are passed BY VALUE, so both
           answer moved=True — the factory's `var`/owned overload is the one
           real Mojo can pick (a `ref` parameter cannot bind an owned value),
           and the owned inner takes the container pointer regardless of which
           representation (MojoList or in-TU `List_N_T...`) the local carries.
           A bare `range(...)` call keeps moved=False: its result is a fresh
           temporary this codegen backs with a real MojoList, and the borrowed
           inner is the measured shape for it.
      {'kind': 'factory', 'name': <factory>, 'node': <call>, 'moved': bool}
          a NESTED factory call — its wrapper is itself the container
          (every std/iter wrapper's `comptime IteratorType[...] = Self`), so
          the caller evaluates the nested call itself.
      {'kind': 'struct', 'sname': <struct>, 'moved': bool}
          a USER-DEFINED iterator struct constructor rvalue (measured
          2026-10-21 part 4: test_zip_bounds's `zip(TestIter(2, {2}),
          TestIter(2, {2}))`) — the struct ITSELF is the inner iterator
          (its `comptime IteratorType[...] = Self`), so the constructor's
          `<Struct> *` result is the wrapper's `_values[i]`. `struct_names`
          must be supplied for this kind (the caller's module-local struct
          names); with it absent the shape answers None, exactly as before
          part 4 added it.
      {'kind': 'struct-fn', 'fn': <fn>, 'sname': <struct>, 'sargs': [...],
           'moved': True}
           a LOCAL function call whose RETURN annotation names a module-local
           generic struct (measured 2026-10-22 part 5: test_cycle's
           `cycle(_owned3(1, 2, 3))` - `def _owned3(...) -> _CopyableOwned[3]`,
           an `IterableOwned` whose `comptime IteratorOwnedType` member names
           the inner `_CopyableOwnedIter[Self.size]`). The rvalue selects the
           owned overload like every direct rvalue; `fn_returns` (the caller's
           own module-level defs' return annotations, built by the seed from
           the module's statements) and `struct_names` must both be supplied
           for this kind - without either, the shape answers None, as before
           part 5."""
    moved = False
    if type(node).__name__ == 'UnaryOp' and getattr(node, 'op', '') == '^':
        moved = True
        node = getattr(node, 'operand', None)
        if type(node).__name__ != 'IdentExpr':
            return None          # `f(x^)^` / other moved shapes: unmeasured
    t = type(node).__name__
    if t == 'IdentExpr':
        d = (locals_map or {}).get(node.name)
        if d is None:
            return None          # parameter / global / other: unmeasured
        ann = getattr(d, 'type_ann', None)
        if isinstance(ann, str) and ann.strip():
            m = re.match(r'^(\w+)\[\s*(\w+)\s*\]$', ann.strip())
            if m:
                # A plain `var` local is passed BY VALUE — the factory's
                # `var`/owned overload is the one real Mojo can pick here
                # (a `ref` parameter cannot bind an owned value), so the
                # inner is the owned one regardless of the argument spelling.
                # A `Set[T]` local is a SET container (measured 2026-10-21
                # (further): `var my_set = {4, 5, 6}` — the literal infers
                # `Set[Int]`): the seed side derives its inner from the
                # LIST source (the emit side feeds it
                # `mojo_set_to_list(<set>)` — the runtime's insertion-order
                # materialization, the same order the runtime set for-loop
                # iterator walks).
                return {'kind': 'set' if m.group(1) == 'Set' else 'list',
                        'tname': m.group(1),
                        'elem': m.group(2), 'moved': True}
            return None          # annotated, but not a single-param container
        v = getattr(d, 'value', None)
        vt = type(v).__name__ if v is not None else ''
        if vt == 'ListExpr':
            elem = list_literal_elem(getattr(v, 'elements', None) or ())
            if elem is None:
                return None
            return {'kind': 'list', 'tname': 'List', 'elem': elem,
                    'moved': True}
        if vt == 'SetExpr':
            # A set LITERAL local (`var my_set = {4, 5, 6}` — no annotation,
            # the literal IS the type evidence): element from the literal,
            # same promotion rules as a list literal.
            elem = list_literal_elem(getattr(v, 'elements', None) or ())
            if elem is None:
                return None
            return {'kind': 'set', 'tname': 'Set', 'elem': elem,
                    'moved': True}
        if vt == 'CallExpr':
            f = getattr(v, 'func', None)
            fn = getattr(f, 'name', None) or (
                getattr(getattr(f, 'obj', None), 'name', None) if f else None)
            if fn == 'range':
                return {'kind': 'list', 'tname': 'List', 'elem': 'Int',
                        'moved': True}
            if fn == 'List':
                # `List[T]()`: the constructor's type parameter is the element.
                _idx = getattr(f, 'index', None)
                idx = getattr(_idx, 'name', None) \
                    if type(_idx).__name__ == 'IdentExpr' else None
                if idx in ('Int', 'String', 'Bool'):
                    return {'kind': 'list', 'tname': 'List', 'elem': idx,
                            'moved': True}
                return None      # `List[K, V]` / multi-param: unmeasured
            if fn == 'Set':
                # `Set[T]()`: the constructor's type parameter is the
                # element (measured 2026-10-21 (further): `var s = Set[Int]()`
                # in test/collections/test_set).
                _idx = getattr(f, 'index', None)
                idx = getattr(_idx, 'name', None) \
                    if type(_idx).__name__ == 'IdentExpr' else None
                if idx in ('Int', 'String', 'Bool'):
                    return {'kind': 'set', 'tname': 'Set', 'elem': idx,
                            'moved': True}
                return None      # `Set[K, V]` / multi-param: unmeasured
            if fn in (factory_names or ()):
                return {'kind': 'factory', 'name': fn, 'node': v,
                        'moved': moved}
            return None
        return None
    if t == 'CallExpr':
        f = getattr(node, 'func', None)
        if type(f).__name__ == 'SubscriptExpr':
            # `List[T]()` / `Set[T]()`: the constructor's own type parameter
            # is the element. A direct argument is an rvalue — the owned
            # overload.
            obj = getattr(f, 'obj', None)
            if type(obj).__name__ == 'IdentExpr' and obj.name in ('List', 'Set'):
                idx = getattr(getattr(f, 'index', None), 'name', None)
                if idx in ('Int', 'String', 'Bool'):
                    return {'kind': 'set' if obj.name == 'Set' else 'list',
                            'tname': obj.name, 'elem': idx,
                            'moved': True}
                return None
            return None
        fn = getattr(f, 'name', None)
        if fn == 'range':
            return {'kind': 'list', 'tname': 'List', 'elem': 'Int',
                    'moved': moved}
        if fn in ('List', 'Set'):
            # `List([1, 2, 3])` — the NO-typ-arg constructor spelling
            # (measured 2026-10-21 part 4: test_chain_owned's
            # `chain(List([1, 2, 3]), List([1, 2, 3]))`): the element is
            # the literal argument's, same promotion rules as the local
            # ListExpr case above. A direct argument is an rvalue — the
            # owned overload (`moved=True` regardless of the call's
            # spelling).
            _cargs = getattr(node, 'args', None) or ()
            if len(_cargs) != 1:
                return None
            _lit = _cargs[0]
            if type(_lit).__name__ not in ('ListExpr', 'SetExpr'):
                return None
            elem = list_literal_elem(getattr(_lit, 'elements', None) or ())
            if elem is None:
                return None
            return {'kind': 'set' if fn == 'Set' else 'list',
                    'tname': fn, 'elem': elem, 'moved': True}
        if fn in (factory_names or ()):
            return {'kind': 'factory', 'name': fn, 'node': node,
                    'moved': moved}
        if fn in (struct_names or ()):
            # A USER-DEFINED iterator struct constructor rvalue (measured
            # 2026-10-21 part 4: test_zip_bounds's `zip(TestIter(2, {2}),
            # TestIter(2, {2}))`): the struct itself is the inner iterator
            # (its `comptime IteratorType[...] = Self`), so the constructor's
            # `<Struct> *` result is exactly the wrapper's `_values[i]`.
            # `struct_names` gates this (the caller's own module-local
            # struct names) so a runtime-name collision cannot claim the
            # shape; without it the answer is None, as before part 4.
            return {'kind': 'struct', 'sname': fn, 'moved': True}
        if fn in (fn_returns or ()):
            # A LOCAL function call whose RETURN annotation names a
            # module-local generic struct (measured 2026-10-22 part 5:
            # test_cycle's `cycle(_owned3(1, 2, 3))` - `def _owned3(...) ->
            # _CopyableOwned[3]`, an `IterableOwned` whose `comptime
            # IteratorOwnedType` member names the inner
            # `_CopyableOwnedIter[Self.size]`). The rvalue selects the owned
            # overload like every direct rvalue. `fn_returns` (built by the
            # seed from the caller's own module-level defs) and
            # `struct_names` both gate this: a return annotation that is not
            # a local generic-struct mention - or a base not defined in the
            # module - answers None, the honest pre-part-5 refusal.
            _ann = (fn_returns or {}).get(fn)
            if isinstance(_ann, str):
                _am = re.match(
                    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\]]+)\]\s*$',
                    ' '.join(_ann.split()))
                if _am and _am.group(1) in (struct_names or ()):
                    return {'kind': 'struct-fn', 'fn': fn,
                            'sname': _am.group(1),
                            'sargs': [a.strip() for a in _am.group(2)
                                      .split(',')],
                            'moved': True}
            return None
        if (type(f).__name__ == 'MemberExpr'
                and getattr(f, 'member', None) == '__iter__'
                and not (getattr(node, 'args', None) or ())):
            # A PythonObject local's own `__iter__()` call (measured 2026-10-
            # 21 part 4, further: test_python_object's `enumerate(list_obj.
            # __iter__())` on `var list_obj: PythonObject = ["apple", ...]`):
            # the box IS the runtime list pointer (the method dispatch
            # unboxes it with `(MojoList *)(int64_t)<box>` — measured in the
            # probe C), so the call is the borrowed-list cursor over that
            # list, and the element comes from the local's list-literal
            # initializer. Any shape without that annotation + literal pair
            # has no statically knowable element: None, the honest refusal
            # stands.
            _obj = getattr(f, 'obj', None)
            if type(_obj).__name__ != 'IdentExpr':
                return None
            d = (locals_map or {}).get(_obj.name)
            if d is None:
                return None
            _ann = getattr(d, 'type_ann', None)
            if not (isinstance(_ann, str) and _ann.strip() == 'PythonObject'):
                return None
            _v = getattr(d, 'value', None)
            if type(_v).__name__ != 'ListExpr':
                return None
            elem = list_literal_elem(getattr(_v, 'elements', None) or ())
            if elem is None:
                return None
            return {'kind': 'pyobj-list', 'tname': 'List', 'elem': elem,
                    'moved': False}
        return None
    if t == 'ListExpr':
        elem = list_literal_elem(getattr(node, 'elements', None) or ())
        if elem is None:
            return None
        return {'kind': 'list', 'tname': 'List', 'elem': elem,
                'moved': moved}
    if t == 'SetExpr':
        # A set literal as a DIRECT factory argument: same promotion rules
        # as a list literal, owned overload (an rvalue is passed by value).
        elem = list_literal_elem(getattr(node, 'elements', None) or ())
        if elem is None:
            return None
        return {'kind': 'set', 'tname': 'Set', 'elem': elem,
                'moved': True}
    return None
