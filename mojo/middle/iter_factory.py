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
    m = _RE_TYPEOF_ITER.match(s)
    if m:
        return {'wrapper': m.group(1), 'kind': 'borrowed', 'x': m.group(2)}
    m = _RE_BARE_ITER_OWNED.match(s)
    if m:
        return {'wrapper': None, 'kind': 'owned', 'x': m.group(1)}
    m = _RE_BARE_ITER_BORROWED.match(s)
    if m:
        return {'wrapper': None, 'kind': 'borrowed', 'x': m.group(1)}
    m = _RE_BARE_STRUCT.match(s)
    if m:
        return {'wrapper': m.group(1), 'kind': 'direct', 'x': None}
    return None


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
        return ('lit',)
    if t == 'SubscriptExpr':
        return ('sub', name, arg_signature(getattr(node, 'index', None)))
    if t == 'TupleExpr':
        return ('tup', tuple(arg_signature(e) for e in
                             (getattr(node, 'elements', None) or ())))
    return ('x', t, name)


def factory_call_key(name: str, node) -> tuple:
    """The record key for one factory CALL: name + every argument's signature
    + the kwarg names (values already inside the argument signatures)."""
    args = getattr(node, 'args', None) or ()
    kws = getattr(node, 'kwargs', None) or ()
    return (name, tuple(arg_signature(a) for a in args),
            tuple(k[0] for k in kws))


# Element-type table shared by the mangled NAME side (`Int`, `String`, ...)
# and the C side (`int64_t`, `char *`, ...). The C side mirrors
# `emit_exprs._lower_list_literal`'s own answers: all-bool literals are
# `_Bool`, strings `char *`, numeric lists promote int -> double.
_MOJO_ELEM_C = {'Int': 'int64_t', 'String': 'char *', 'Bool': '_Bool',
                'Float64': 'double'}


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
        else:
            return None
    if 'String' in kinds:
        return 'String' if kinds == {'String'} else None
    if kinds == {'Bool'}:
        return 'Bool'
    if kinds <= {'Int', 'Float64'}:
        return 'Float64' if 'Float64' in kinds else 'Int'
    if kinds == {'Int'}:
        return 'Int'
    return None


def resolve_container(node, factory_names, locals_map) -> dict | None:
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
          the caller evaluates the nested call itself."""
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
                return {'kind': 'list', 'tname': m.group(1),
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
            if fn in (factory_names or ()):
                return {'kind': 'factory', 'name': fn, 'node': v,
                        'moved': moved}
            return None
        return None
    if t == 'CallExpr':
        f = getattr(node, 'func', None)
        if type(f).__name__ == 'SubscriptExpr':
            # `List[T]()`: the constructor's own type parameter is the
            # element. A direct argument is an rvalue — the owned overload.
            obj = getattr(f, 'obj', None)
            if type(obj).__name__ == 'IdentExpr' and obj.name == 'List':
                idx = getattr(getattr(f, 'index', None), 'name', None)
                if idx in ('Int', 'String', 'Bool'):
                    return {'kind': 'list', 'tname': 'List', 'elem': idx,
                            'moved': True}
                return None
            return None
        fn = getattr(f, 'name', None)
        if fn == 'range':
            return {'kind': 'list', 'tname': 'List', 'elem': 'Int',
                    'moved': moved}
        if fn in (factory_names or ()):
            return {'kind': 'factory', 'name': fn, 'node': node,
                    'moved': moved}
        return None
    if t == 'ListExpr':
        elem = list_literal_elem(getattr(node, 'elements', None) or ())
        if elem is None:
            return None
        return {'kind': 'list', 'tname': 'List', 'elem': elem,
                'moved': moved}
    return None
